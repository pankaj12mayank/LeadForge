from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import Workbook

FORMULA_PREFIXES = ("=", "+", "-", "@")


def _sanitize(v: Any) -> Any:
    if isinstance(v, str) and v.startswith(FORMULA_PREFIXES):
        return "'" + v
    return v


def export_csv(leads: list[dict[str, Any]]) -> bytes:
    cols = [
        "name", "title", "company", "domain", "email", "email_status", "phone",
        "linkedin_url", "location", "source", "score", "tier", "pain_point",
        "reason", "opener", "status", "created_at",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        row = {c: _sanitize(lead.get(c)) for c in cols}
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def export_xlsx(leads: list[dict[str, Any]]) -> bytes:
    cols = [
        "name", "title", "company", "domain", "email", "email_status", "phone",
        "linkedin_url", "location", "source", "score", "tier", "pain_point",
        "reason", "opener", "status", "created_at",
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(cols)
    for lead in leads:
        ws.append([_sanitize(lead.get(c)) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
