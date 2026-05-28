# TRADEOFFS.md — Three Things Deliberately Not Built

This document describes the three most significant features left out of this
prototype, why each was cut, what the cost of that cut is, and what a full
implementation would require.

---

## Tradeoff 1: No asynchronous parsing (no Celery task queue)

### What was built instead
File parsing happens synchronously within the HTTP request/response cycle.
The upload endpoint receives the file, parses every row, writes all RawRow
and NormalizedActivity records, and returns HTTP 201 with the completed
IngestionRun — all in one request.

### Why it was cut
Async parsing with Celery requires:
- A message broker (Redis or RabbitMQ) running as a separate service
- One or more Celery worker processes
- A polling mechanism or WebSocket on the frontend to show parse progress
- Error handling for tasks that time out or crash mid-run
- A mechanism to retry failed tasks without duplicating records

This is 2–3 days of infrastructure and frontend work. For files of 15–50 rows
(all sample data in this prototype), synchronous parsing completes in under
200ms — indistinguishable from async to the user, and far simpler to debug.

### What breaks without it
A realistic SAP MB51 export for a large enterprise covers a full quarter:
potentially 5,000–50,000 goods movement rows. At ~5ms per row (DB write +
emission factor lookup), a 10,000-row file takes 50 seconds synchronously.
The current Procfile sets Gunicorn's worker timeout to 120 seconds
(`--timeout 120`), so a 10,000-row file would likely complete within the
current configuration. However, a 50,000-row file (~250 seconds) would
exceed even this extended timeout. The request would fail mid-parse, leaving
a PROCESSING-status IngestionRun with partial data in the DB.

### What a full implementation requires
1. Redis add-on on Render (or any broker)
2. `celery.py` config in the Django project
3. `@shared_task` decorator on the parser dispatch function
4. `IngestionRun.status` updated from the task: PROCESSING → COMPLETED / FAILED
5. Frontend polls `GET /api/ingestion/runs/:id/` every 2 seconds until status
   is no longer PROCESSING
6. Celery Beat for scheduled re-ingestion (if the client wants automatic pulls)

**Effort to add:** 2–3 days. **Priority:** High — required before any
enterprise client uploads real quarterly data.

---

## Tradeoff 2: No market-based Scope 2 (no REC / PPA support)

### What was built instead
All electricity consumption is costed using the location-based method:
`consumption_kWh × tenant.grid_emission_factor_kg_per_kwh`.
The grid factor is set per tenant at onboarding and reflects the country-level
average grid carbon intensity (e.g. 0.233 kg/kWh for UK, 0.820 for India).

### Why it was cut
Market-based Scope 2 accounting requires the client to provide evidence of
renewable energy procurement: Renewable Energy Certificates (RECs), Power
Purchase Agreements (PPAs), green tariff contracts, or REGO certificates.
The platform would need to:
- Store certificate data (certificate type, volume in MWh, period covered,
  issuing registry, certificate ID)
- Match certificate MWh against metered consumption by site and time period
- Calculate a residual mix factor for consumption not covered by certificates
- Produce both location-based and market-based totals (GHG Protocol requires
  reporting both when market-based is used)

This is a significant data model addition (a `RenewableEnergyCertificate` table
plus matching logic) and a new ingestion pipeline. It also requires the client
to actually procure and record certificates, which many clients have not done.

### What breaks without it
For clients with renewable energy procurement (solar PPAs, wind RECs, 100%
green tariffs), the platform overstates their Scope 2 emissions. A company
with a fully renewable electricity supply that is location-based method only
would show non-zero Scope 2 when their actual market-based Scope 2 is zero.
This is a material accuracy issue for sustainability reporting.

### What a full implementation requires
1. New `RenewableEnergyCertificate` model: tenant, meter_id, certificate_type
   (REC/REGO/GO/PPA), volume_mwh, period_start, period_end, registry_id
2. New ingestion pipeline for certificate data (manual upload or API)
3. Matching logic: for each billing period, subtract certified MWh from
   consumption before applying residual mix factor
4. Second column on NormalizedActivity: `normalized_kg_co2e_market`
5. Summary endpoint updated to return both location-based and market-based
   Scope 2 totals
6. GHG Protocol mandates both figures in the disclosure output

**Effort to add:** 3–5 days. **Priority:** High for clients with
sustainability commitments; medium for clients just getting started.

---

## Tradeoff 3: No billing period prorating across calendar months

### What was built instead
Each utility billing row is stored with `activity_date = billing_period_start`
and `period_end = billing_period_end`. The full kWh for the billing period
is attributed to the start date. No attempt is made to split consumption
across the calendar months the period spans.

A bill running "15 Jan – 17 Feb" (33 days) stores:
- `activity_date`: 15 Jan 2024
- `period_end`: 17 Feb 2024
- `original_value`: 18,420 kWh (full billing period)
- `normalized_kg_co2e`: 18,420 × 0.233 = 4,291.86 kg CO₂e

Both January and February Scope 2 totals include this row's full emission
value if filtered by date range, which is incorrect.

### Why it was cut
Prorating introduces derived values that do not appear in the source document.
Correct prorating of a billing period requires:
1. Determining the fraction of days in each calendar month
2. Multiplying consumption by that fraction for each month
3. Creating two or more NormalizedActivity records from one source row

The complications: leap year handling (February 2024 has 29 days), billing
periods that span three months (a 90-day combined bill), periods with zero
consumption in one month. A bug in any of these cases produces wrong emissions
silently — there is no "invalid proration" error, just incorrect numbers.

The safe prototype decision is to store source values verbatim and preserve
both dates. Analysts reviewing the dashboard can see the full period and
understand what the record represents. Monthly granularity errors in the
prototype are visible (a Jan–Feb bill appears in both month filters) rather
than silently wrong.

### What a full implementation requires
1. A `prorate_billing_period(start, end, kwh)` utility function that returns
   a list of `(month, kwh_fraction)` tuples
2. Parser creates multiple NormalizedActivity records from one RawRow
   (requires relaxing the OneToOne constraint to OneToMany, or using a
   `ProrationGroup` linking table)
3. Each prorated record carries `is_prorated=True` and a reference to its
   parent record
4. Audit trail must show prorated records as derived, not original
5. Edge case handling: leap years, periods >92 days, periods crossing
   year boundaries (Dec–Jan)

**Effort to add:** 1–2 days for the proration logic, plus 1 day for the
data model change (OneToOne → group structure) and UI changes.
**Priority:** Medium — required for monthly Scope 2 reporting accuracy,
acceptable to skip for annual reporting.

---

## Honourable mentions (cut but worth noting)

These were also deliberately excluded and would be noted if asked:

**No role-based access control beyond Analyst/Admin:**
The `User.role` field exists (admin / analyst / viewer) but the API does not
enforce different permissions per role beyond IsAuthenticated. A Viewer can
currently call approve endpoints. A full RBAC implementation would add
permission classes per endpoint and a permission matrix.

**No configurable material master for SAP:**
Materials are classified by MATNR prefix. Unknown prefixes produce a failed
row. A real deployment needs a configuration UI where the client maps each
MATNR to a fuel type without modifying code.

**No re-run mechanism:**
If a parser bug corrupts a batch, the only fix is to delete the run manually
and re-upload. A proper re-run endpoint would replay parsing on stored RawRows
without requiring re-upload of the original file.

**No email notifications:**
Analysts have no notification when a new ingestion run completes or when rows
are flagged. A production system needs at minimum an email trigger when
`row_count_flagged > 0`.
