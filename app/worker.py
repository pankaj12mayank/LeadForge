"""Postgres-backed job worker + saved-search scheduler.

Run separately:  python -m app.worker
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from app.models import Job, JobStatus, Lead, Organization, Plan, Search, Subscription
from app.services import enrich, merge, planner, quota, score, sources

log = logging.getLogger("leadforge.worker")
POLL_INTERVAL = 3
STALE_RUNNING_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _claim_job(db) -> Job | None:
    row = db.execute(
        text(
            """
            SELECT id FROM jobs
            WHERE status = 'queued' AND run_after <= :now
            ORDER BY run_after ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ),
        {"now": _now()},
    ).fetchone()
    if not row:
        return None
    job_id = row[0]
    db.execute(
        text(
            "UPDATE jobs SET status = 'running', locked_at = :now, attempts = attempts + 1 WHERE id = :id"
        ),
        {"now": _now(), "id": job_id},
    )
    db.commit()
    return db.get(Job, job_id)


def _recover_stale(db) -> int:
    cutoff = _now() - timedelta(minutes=STALE_RUNNING_MINUTES)
    result = db.execute(
        text(
            """
            UPDATE jobs
            SET status = 'queued', locked_at = NULL
            WHERE status = 'running' AND locked_at IS NOT NULL AND locked_at < :cutoff
            """
        ),
        {"cutoff": cutoff},
    )
    db.commit()
    return result.rowcount or 0


def _fail_job(db, job: Job, error: str) -> None:
    job.status = JobStatus.failed
    job.error = error[:2000]
    db.commit()


def _done_job(db, job: Job, summary: dict) -> None:
    job.status = JobStatus.done
    job.result_summary = summary
    db.commit()


async def _run_sources(org_id, features, plan, limit):
    srcs = sources.get_sources(features)
    coros = [s.search(plan.filters, limit) for s in srcs]
    results = await asyncio.gather(*coros, return_exceptions=True)
    leads = []
    for s, res in zip(srcs, results):
        if isinstance(res, Exception):
            log.warning("source %s failed: %s", s.name, res)
            continue
        for lead in res or []:
            lead["org_id"] = org_id
            leads.append(lead)
    return leads


async def _execute_job(org_id, search, plan_features, target):
    plan_obj = await planner.plan_query(search.query if search else "leads", features=plan_features)
    raw_leads = await _run_sources(org_id, plan_features, plan_obj, target)
    merged = merge.merge_incoming(raw_leads)
    delivered = merged[:target]

    keys = {
        "apollo": settings.APOLLO_API_KEY,
        "hunter": settings.HUNTER_API_KEY,
        "skrapp": settings.SKRAPP_API_KEY,
    }
    delivered = await enrich.enrich_batch(delivered, keys)
    is_pro = (plan_features or {}).get("code") == "pro"
    delivered = await score.score_leads(delivered, is_pro=is_pro)
    return delivered, {
        "target_count": target,
        "collected": len(raw_leads),
        "deduplicated": len(merged),
    }


def process_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        search = db.get(Search, job.search_id) if job.search_id else None
        org = db.get(Organization, job.org_id)
        if not org:
            _fail_job(db, job, "org not found")
            return

        plan_features = {}
        plan = None
        sub = (
            db.query(Subscription)
            .filter(Subscription.org_id == org.id)
            .order_by(Subscription.created_at.desc())
            .first()
        )
        if sub:
            plan = db.query(Plan).get(sub.plan_id)
        if plan:
            plan_features = dict(plan.features or {})
            plan_features["code"] = plan.code
        is_pro = plan.code == "pro" if plan else False

        target = job.result_summary.get("target_count", 10) if job.result_summary else 10

        try:
            quota.reserve_credits(org.id, target, f"job {job.id}", db, job_id=job.id)
        except ValueError as exc:
            _fail_job(db, job, str(exc))
            return

        try:
            delivered, summary = asyncio.run(
                _execute_job(org.id, search, plan_features, target)
            )
        except Exception as exc:
            log.exception("job %s execution failed", job.id)
            job.attempts = (job.attempts or 0) + 1
            if job.attempts >= 3:
                _fail_job(db, job, str(exc)[:2000])
                quota.refund_credits(org.id, target, f"job {job.id} failed", db, job_id=job.id)
            else:
                job.status = JobStatus.queued
                job.locked_at = None
                job.run_after = _now() + timedelta(minutes=2 ** job.attempts)
                db.commit()
            return

        saved = 0
        for lead in delivered:
            exists = (
                db.query(Lead)
                .filter(Lead.org_id == org.id)
                .filter(
                    (Lead.linkedin_url == lead.get("linkedin_url"))
                    | (Lead.email == lead.get("email"))
                )
                .first()
            )
            if exists:
                continue
            db.add(
                Lead(
                    org_id=org.id,
                    search_id=search.id if search else None,
                    name=lead.get("name"),
                    title=lead.get("title"),
                    company=lead.get("company"),
                    domain=lead.get("domain"),
                    email=lead.get("email"),
                    email_status=lead.get("email_status"),
                    phone=lead.get("phone"),
                    linkedin_url=lead.get("linkedin_url"),
                    location=lead.get("location"),
                    source=lead.get("source"),
                    score=lead.get("score"),
                    tier=lead.get("tier"),
                    pain_point=lead.get("pain_point"),
                    reason=lead.get("reason"),
                    opener=lead.get("opener") if is_pro else None,
                    status="new",
                    raw=lead.get("raw"),
                )
            )
            saved += 1
        db.commit()

        used = target
        unused = max(0, used - saved)
        if unused:
            quota.refund_credits(org.id, unused, f"job {job.id} unused", db, job_id=job.id)

        summary["delivered"] = saved
        summary["credits_used"] = used - unused
        _done_job(db, job, summary)
        log.info("job %s done: %s", job.id, summary)
    finally:
        db.close()


def enqueue_saved_searches(db) -> int:
    now = _now()
    searches = db.query(Search).filter(Search.is_saved == True).all()  # noqa: E712
    count = 0
    for search in searches:
        cron = search.schedule_cron
        if not cron:
            continue
        parts = cron.split()
        if len(parts) != 5:
            continue
        minute = parts[0]
        if minute not in ("*", str(now.minute)):
            continue
        already = (
            db.query(Job)
            .filter(Job.search_id == search.id)
            .filter(Job.created_at >= now - timedelta(minutes=15))
            .first()
        )
        if already:
            continue
        db.add(
            Job(
                org_id=search.org_id,
                search_id=search.id,
                type="saved_search",
                status=JobStatus.queued,
                run_after=now,
                result_summary={"target_count": 10},
            )
        )
        count += 1
    if count:
        db.commit()
    return count


def main() -> None:
    logging.basicConfig(level=settings.LOG_LEVEL.upper())
    log.info("LeadForge worker starting")
    while True:
        db = SessionLocal()
        try:
            recovered = _recover_stale(db)
            if recovered:
                log.info("recovered %s stale jobs", recovered)
            job = _claim_job(db)
            enqueue_saved_searches(db)
            if job:
                process_job(job.id)
        except Exception as exc:  # noqa: BLE001
            log.exception("worker loop error: %s", exc)
        finally:
            db.close()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
