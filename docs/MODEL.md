# MODEL.md — BreatheESG Data Model

## Overview

The data model has one job: take messy, multi-format emissions data from three
different source systems, normalize it to a single unit (kg CO₂e), and produce
a record that an analyst can approve and an auditor can verify — without ever
losing the original source value.

Eight tables. Every design decision below serves one of three concerns:
tenant isolation, source traceability, or audit integrity.

---

## Table summary

| Table | Purpose |
|---|---|
| `tenant` | One enterprise client |
| `auth_user_extended` | Analyst / admin, scoped to a tenant |
| `ingestion_run` | One file upload event |
| `raw_row` | Verbatim copy of one source row, never modified |
| `normalized_activity` | Clean reviewable emission record derived from one raw row |
| `audit_log` | Append-only log of every system action |
| `plant_lookup` | SAP WERKS codes → human site names |
| `emission_factor` | Versioned kg CO₂e conversion factors (DEFRA 2023) |

---

## Multi-tenancy

Every table carries a `tenant_id` foreign key. This is row-level tenancy in a
single shared PostgreSQL schema.

**Why row-level over schema-per-tenant:**
Schema-per-tenant gives stronger physical isolation but multiplies migration
complexity by N tenants. Every `manage.py migrate` must loop across schemas.
Adding a column means touching every schema individually. Cross-tenant admin
queries (total uploads across all clients this month) require dynamic SQL.
At the scale of an early-stage product, a single schema with a mandatory
`tenant` filter on every query is operationally simpler and fast enough.

**How isolation is enforced:**
Every DRF ViewSet overrides `get_queryset()` to filter by
`request.user.tenant`. This is applied at the viewset layer — not the
serializer — so it cannot be bypassed by any API call regardless of what URL
is constructed. Superuser accounts (Breathe internal staff) carry `tenant=null`
on the `User` model; the `get_queryset()` filter naturally excludes
tenant-scoped data for null-tenant users. A dedicated middleware layer for
superuser access control is not yet implemented — it is a production
requirement noted below in "What I would build next".

**The honest tradeoff:**
A missing filter in a new viewset could theoretically expose one tenant's data
to another. Schema-per-tenant prevents this at the database level. Row-level
tenancy requires discipline. This is documented in TRADEOFFS.md.

---

## Scope 1 / 2 / 3 categorization

`normalized_activity` carries `scope` (values: "1", "2", "3") and
`scope3_category` (integer 1–15, GHG Protocol numbering, populated only when
scope = 3).

**Categorization is set by the parser, not the analyst:**

| Source | Scope | Category | Logic |
|---|---|---|---|
| SAP MB51 fuel | 1 | — | Direct combustion at owned facilities |
| Utility electricity | 2 | — | Purchased electricity, location-based |
| Corporate travel | 3 | 6 | Business travel (GHG Protocol Cat. 6) |

Material number prefixes drive Scope 1 sub-type: `DIES-` → diesel,
`LPG-` → LPG/propane, `HEL-` → heating oil, `CNG-` → natural gas.

**Why analysts cannot change scope assignments:**
Scope is a property of the activity type, not a judgment call. If a scope
assignment is wrong, the source data is wrong — the fix belongs in a corrected
re-upload. Allowing silent reclassification would produce approved datasets
whose scope assignments cannot be traced to source data. Analysts flag
the row with a note; a corrected file is re-ingested. The review edit endpoint
deliberately excludes `scope` and `scope3_category` from the list of editable
fields.

---

## Source-of-truth and lineage

Every `normalized_activity` links back through an unbreakable chain:

```
normalized_activity
  └── raw_row          (OneToOne — one raw row → one activity)
        └── ingestion_run  (ForeignKey)
              └── filename, file_hash_sha256, uploaded_by, created_at
```

**Why raw rows are stored:**
`raw_row.raw_data` is a JSON field containing the column-name-to-value mapping
exactly as it appeared in the source file — German headers, original date
strings, original units, verbatim. Written once on ingest, never updated.
If a parser bug corrupts normalized values, every affected activity can be
re-derived from stored raw rows without asking the client to re-upload.

**Note on raw_row mutability during edits:**
The review edit endpoint (`/api/review/activities/:id/edit/`) does update
`raw_row.raw_data` to reflect manual corrections, and can clear
`raw_row.parse_status` back to OK when `clear_flags=true`. This means raw rows
are not strictly immutable after creation — they can be modified through the
edit workflow. The original values are still preserved in the audit log's
`before_state` snapshot, maintaining full traceability.

**Why OneToOne between raw and normalized:**
One raw row produces exactly one normalized record. A ForeignKey (one-to-many)
would require explaining which normalized row is "the" one — ambiguous for
auditors. OneToOne makes the lineage unambiguous and enforced at the
database level.

**Duplicate upload detection:**
`ingestion_run.file_hash_sha256` stores the SHA-256 of the uploaded file.
Before processing, the upload view checks for an existing run with the same
hash for the same tenant. A duplicate returns HTTP 409 with the original run ID
and upload date, preventing double-counting when a sustainability lead
re-downloads and re-uploads the same export.

---

## Unit normalization

Four fields on `normalized_activity` make every conversion fully auditable:

| Field | Stores | Example |
|---|---|---|
| `original_value` | Quantity verbatim from source | `12500` |
| `original_unit` | Unit verbatim from source | `L` |
| `normalized_kg_co2e` | Result after applying emission factor | `33611.250000` |
| `emission_factor_used` | The exact factor applied | `2.68890000` |
| `emission_factor_source` | Publishing authority | `DEFRA 2023` |

An auditor reconstructs the calculation as:
`normalized_kg_co2e = original_value × emission_factor_used`
without touching any other table.

**SAP KG → L conversion for diesel:**
DEFRA's diesel factor is per-litre. SAP records drum purchases in KG.
The parser converts using diesel density 0.84 kg/L before multiplying.
`original_value` and `original_unit` still store `9800 KG` verbatim.
The conversion is visible in the factor chain and fully reproducible.

**Emission factors are versioned:**
`emission_factor` stores `valid_from_year` / `valid_to_year`. The factor
active at calculation time is copied onto `emission_factor_used` on the
activity row — historical records never need to re-query which factor was
current at that time.

**Storage precision:**
`normalized_kg_co2e` is stored to 6 decimal places. Rounding to 2 d.p.
at the row level before aggregation introduces systematic error across large
datasets. Display-layer rounding (2 d.p.) is the responsibility of the
frontend, not the database.

---

## Analyst approval workflow

`normalized_activity.review_status` drives the workflow:

```
pending ──► approved ──► locked   (immutable, sent to auditor)
         ↘
          flagged ──► (analyst resolves) ──► pending ──► approved ──► locked
```

**Immutability enforcement:**
`NormalizedActivity.save()` raises `ValueError` if any field is changed on a
record with `review_status = locked`. Enforced at the Django model layer — not
just the API — so no management command, Celery task, or future feature can
accidentally mutate a locked record.

---

## Audit trail

`audit_log` is append-only. `save()` raises `ValueError` on any update.
`delete()` is unconditionally blocked. Every meaningful action writes an entry:

| Field | Content |
|---|---|
| `actor` | User who performed the action (null for system actions) |
| `action` | Enumerated type (ingestion_started, activity_approved, etc.) |
| `target_type` | "ingestion_run" / "normalized_activity" / "raw_row" |
| `target_id` | UUID of the affected record |
| `before_state` | JSON snapshot before the change |
| `after_state` | JSON snapshot after the change |
| `timestamp` | UTC timestamp |
| `ip_address` | Client IP |

The full history of any record can be reconstructed from the log alone without
relying on a third-party audit library or database-level triggers.

---

## What I would build next

1. **`ReportingPeriod` table** — group approved activities into formal annual
   disclosures with locked scope totals per reporting year.
2. **Market-based Scope 2** — second `normalized_kg_co2e_market` column
   populated when the tenant supplies renewable energy certificates or PPAs.
3. **Schema-per-tenant migration** — for clients with contractual data
   isolation requirements.
4. **Configurable material master** — replace prefix-matching for SAP
   materials with a per-tenant MATNR → fuel type mapping table.
5. **Superuser access middleware** — dedicated middleware to handle
   `tenant=null` admin users with explicit cross-tenant access control, rather
   than relying on `get_queryset()` filter behaviour alone.
