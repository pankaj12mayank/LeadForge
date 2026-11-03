# Admin panel

Access: `/admin` (role=admin only). Seed admin via `ADMIN_EMAIL`/`ADMIN_PASSWORD`.

Sections:
- **Overview** — users, orgs, MRR (active subscriptions), jobs/day, failure rate, API cost/day.
- **Users / Orgs** — search, view, suspend/activate, impersonate (audited), manually grant credits, change plan.
- **Jobs monitor** — list/filter by status, view error, retry, cancel.
- **Plans editor** — edit prices/credits/features (applies to new periods).
- **Provider health** — ping Apollo/LLM/Places/Razorpay; last status stored.
- **Audit log** — actor, action, target, meta, timestamp.

Plan changes affect new subscription periods; existing subscriptions keep their plan until changed. Monthly credits reset on each successful Razorpay charge.
