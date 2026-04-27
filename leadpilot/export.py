"""Excel (primary) + optional JSON export for LeadPilot."""

from __future__ import annotations

import json
import os
from typing import Any

from leadpilot.utils import get_logger

log = get_logger("leadpilot.export")


def _flatten(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "Name": row.get("Name", ""),
        "Role": row.get("Role", ""),
        "Company": row.get("Company", ""),
        "LinkedIn URL": row.get("Profile Link", "") or row.get("linkedin_url", ""),
        "Work Email": row.get("work_email", ""),
        "Company Domain": row.get("company_domain", ""),
        "Industry": row.get("industry", ""),
        "Team Size (LinkedIn)": row.get("Team Size", ""),
        "Employee Count (validated)": row.get("employee_count", ""),
        "Revenue": row.get("revenue", ""),
        "Problems (AI refined)": row.get("problems_refined")
        or row.get("Problem Seen", ""),
        "Lead Score": row.get("lead_score", ""),
        "Priority": row.get("priority", ""),
        "Enrichment Status": row.get("enrichment_status", ""),
        "Enrichment Source": row.get("enrichment_source", ""),
        "Scoring Notes": row.get("scoring_reasoning", ""),
        "Solution (original)": row.get("Solution", ""),
        "Last Active": row.get("Last Active", "N/A"),
    }


def export_leadpilot(
    rows: list[dict[str, Any]],
    xlsx_path: str,
    json_path: str | None = None,
) -> None:
    if not rows:
        log.warning("No rows to export")
        return
    try:
        import pandas as pd
    except ImportError as e:
        raise RuntimeError("pip install pandas openpyxl") from e
    flat = [_flatten(r) for r in rows]
    df = pd.DataFrame(flat)
    df.to_excel(xlsx_path, index=False, engine="openpyxl")
    log.info("Wrote %s", xlsx_path)
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(flat, f, ensure_ascii=False, indent=2)
        log.info("Wrote %s", json_path)
