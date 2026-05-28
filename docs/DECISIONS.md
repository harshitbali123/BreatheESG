# DECISIONS.md — Every Ambiguity Resolved

Every non-obvious fork in the road during this build: what I chose, why,
and what I would ask the PM before taking it to production.

---

## Source 1 — SAP MB51 (fuel and procurement)

### D1: IDoc vs OData vs flat file

**Chose:** MB51 tab-separated flat file (.txt / .csv)

**Rejected IDoc because:**
IDoc is SAP's EDI format for system-to-system integration. It has a rigid
three-part structure (control record, data segments, status records) and
requires EDI middleware to parse. It is what SAP uses to talk to logistics
providers and banks — not what a sustainability lead exports manually.
No enterprise sustainability team is emailing IDocs to their carbon platform.

**Rejected OData because:**
OData is SAP's REST API layer (SAP Gateway / BTP). It is the correct answer
for an S/4HANA Cloud customer with an active IT team willing to configure
gateway access and issue API credentials. Most on-premise SAP ECC
installations will not expose OData to the internet. Many sustainability leads
have no IT support at all. OData is the aspirational answer; flat file is
the realistic one.

**Why MB51 specifically:**
MB51 (Material Document List) is the standard SAP transaction for extracting
goods movement history. A sustainability lead runs it, selects a date range,
filters for movement type 101 (goods receipt), and clicks "Export to
Spreadsheet". No IT involvement. No API keys. This is how it actually works.

**PM question:** Is the client on S/4HANA Cloud with IT resources for API
integration, or on-premise ECC where flat file export is the only realistic
option?

---

### D2: Movement type 101 only

**Chose:** Accept only movement type 101 (goods receipt from purchase order).
Skip 261 (goods issue), 122 (return delivery), 501 (receipt without PO).

**Why:** 101 is the only movement type representing new fuel entering the
facility from an external supplier — a real procurement event. 261 is internal
consumption and would double-count fuel already captured at receipt. 122 is a
return that would produce a negative emission entry our review UI does not
handle. Skipping non-101 rows is logged on the RawRow so analysts can see
what was excluded.

**PM question:** Does the client track actual fuel consumption (261 movements)
separately from procurement (101)? If yes, we may need to ingest 261s and
net against 101s.

---

### D3: Material classification by number prefix

**Chose:** Match material numbers by prefix: `DIES-` → diesel, `LPG-` → LPG,
`HEL-` → heating oil, `CNG-` → natural gas.

**Why:** A full material master mapping would require the client to provide
a complete MATNR-to-fuel-type lookup table — a setup burden that cannot be
imposed in a 4-day prototype. Prefix matching works because clients with
structured SAP configurations tend to use meaningful prefixes.

**Fallback behaviour:** If the material number does not match any prefix in
`MATERIAL_MAP`, the parser attempts a secondary classification from the
material description text (`_classify_from_description`), looking for keywords
like "diesel", "LPG", "propane", "Heizöl", "Erdgas", etc. If neither the
prefix nor the description yields a match, the row is marked as **failed**
(`parse_status = FAILED`) and no `NormalizedActivity` is created. The failure
reason is recorded on the `RawRow.parse_errors` field so analysts can see
exactly which material number was unrecognised and request a mapping update.

**PM question:** Does the client use structured MATNR numbering or are their
material numbers arbitrary legacy codes? Arbitrary codes require a
configuration UI for material master mapping.

---

### D4: Outlier threshold (removed)

**Original design:** Flag any single-day receipt above 100,000 L as a
suspicious outlier.

**Current status:** The outlier threshold check was **removed** from the
parser during development. The validation logic in `_validate_raw` and
`_normalize_row` no longer enforces any quantity ceiling. This was a deliberate
change — hardcoded thresholds were causing legitimate data to be incorrectly
flagged during testing. The parser docstring still references
`OUTLIER_THRESHOLD_L` for historical context, but no threshold constant or
check exists in the current codebase.

**PM question:** Should outlier detection be reintroduced as a configurable
per-plant threshold rather than a system-wide constant? If so, the threshold
should be stored on `PlantLookup` and checked during normalisation.

---

### D5: Diesel density for KG → L conversion

**Chose:** 0.84 kg/L (EN590 standard diesel at ~15°C)

**Why:** DEFRA's emission factor is per-litre. SAP records some deliveries
in KG (drum/IBC purchases). Density varies slightly by temperature and grade
(0.820–0.845 kg/L) but 0.84 is the standard reference value for EN590 road
diesel across European markets. The original KG value is preserved in
`original_value` / `original_unit` for audit verification.

---

## Source 2 — Utility (electricity)

### D6: Portal CSV over PDF bill or direct API

**Chose:** CSV portal export.

**Rejected PDF because:**
PDF utility bills require OCR. OCR accuracy on utility bills is poor —
tariff codes, meter IDs, and decimal separators vary wildly by supplier.
A misread digit in a consumption figure would silently produce wrong
emissions with no parse error to alert the analyst. PDF parsing is a
separate engineering problem with a much higher failure rate than CSV.

**Rejected direct API because:**
Green Button (US) and SMETS2 (UK) require per-utility OAuth setup.
There are hundreds of utility suppliers across a multinational client's
operating geographies. A portal CSV requires zero API credentials and is
what facilities managers use today.

**PM question:** Does the client have a particularly high number of sites
where manual CSV export is a bottleneck? If yes, direct API integration with
major suppliers (Tata Power, National Grid, E.ON) is worth the engineering
investment.

---

### D7: No billing period prorating across calendar months

**Chose:** Store `activity_date = billing_period_start`,
`period_end = billing_period_end`. Do not split consumption across months.

**Why:** A bill running "15 Jan – 17 Feb" should ideally be split: 17 days in
January, 17 days in February. But prorating introduces derived values not
present in the source document. If the logic has an off-by-one error or handles
leap years wrong, we corrupt the data silently. The safe prototype choice is to
store what the source says and preserve both dates. Analysts can see the full
billing period. Monthly granularity can be added when the requirement is
formally specified.

**PM question:** Is monthly Scope 2 granularity required for the client's
reporting output, or is quarterly / annual aggregation sufficient?

---

### D8: Tenant-scoped grid emission factor

**Chose:** `Tenant.grid_emission_factor_kg_per_kwh` takes priority over the
DEFRA 2023 system default.

**Why:** Grid carbon intensity varies by country: UK ~0.233 kg/kWh, India
~0.820 kg/kWh, Norway ~0.029 kg/kWh. Applying a UK average to an Indian site
understates Scope 2 by 3.5×. The tenant field is set at onboarding to the
client's primary grid mix. The fallback chain is:
tenant factor → EmissionFactor table → DEFRA 2023 hardcoded constant.
The parser never crashes even if the DB is not fully seeded.

**PM question:** Does the client need site-level emission factors (e.g. one
grid mix for their German sites, another for Indian sites under the same
tenant)?

---

## Source 3 — Corporate travel

### D9: Concur CSV over Navan or TripActions API

**Chose:** Concur SAP standard expense report CSV export.

**Why:** Concur has ~65% enterprise market share. Its standard expense export
has consistent column names across client configurations. Navan and TripActions
have better REST APIs but smaller install bases. The Concur CSV parser covers
the most enterprise clients. A Navan CSV with the same column names works
without changes; a different column schema requires only a HEADER_MAP update.

**PM question:** Which specific travel platform does the client use?

---

### D10: Static IATA airport registry (83 airports) over full database

**Chose:** Static dict of 83 major business travel airports.

**Why:** A full OurAirports database (~7,500 airports) adds a file dependency,
a loading step, and a maintenance burden for a prototype. Enterprise corporate
travel is concentrated in the top 100 airports by passenger volume. All routes
in the sample data are covered. Unknown airport codes produce a named
`flag_reason` — the analyst can see exactly which code needs adding, without
re-uploading the file.

**PM question:** What percentage of the client's travel involves secondary or
regional airports not in the registry?

---

### D11: Missing cabin class defaults to Economy

**Chose:** Blank `cabin_class` → Economy + `missing_cabin_class` flag.

**Why:** Economy is the lower-emission assumption. Defaulting to Business
would overstate emissions for every uncaptured flight — a systematic upward
bias that is harder to defend to auditors than an understatement. "We used
the conservative default" is a defensible position. "We overstated every
flight" is not.

**PM question:** Does the client's Concur configuration reliably capture cabin
class, or is it typically blank? If blank is the norm, the Economy default
understates systematically and we need a better strategy (fare-amount proxy).

---

## System design decisions

### D12: Synchronous parsing (no Celery)

**Chose:** Parse files synchronously within the HTTP request/response cycle.

**Why:** Async parsing with Celery requires a Redis/RabbitMQ broker, a
separate worker process, and frontend polling or WebSockets for status
updates. For a 4-day prototype handling files of 15–50 rows, this adds
1–2 days of infrastructure work for no perceptible benefit. A 50-row CSV
parses in under 100ms.

**PM question:** What is the maximum expected file size from enterprise
clients? A 50,000-row SAP export takes 30+ seconds synchronously and must
move to an async queue before production.

### D13: DEFRA 2023 as the baseline emission factor standard

**Chose:** UK Government DEFRA 2023 Greenhouse Gas Reporting Conversion
Factors for all fuel types, electricity, and travel categories.

**Why:** DEFRA publishes annually updated, peer-reviewed factors covering
all major fuel types in kg CO₂e (including CH₄ and N₂O upstream). Freely
available, widely used in UK/EU corporate reporting, and covers Scope 1,
2, and 3 categories in one consistent publication. Factors are versioned in
the `emission_factor` table — when DEFRA 2024 is published, a new row is
added and historical records retain their original factor.

**PM question:** Does the client require EPA factors (US) or IPCC AR6 for
specific activities? The `emission_factor_source` field makes the standard
used auditable on every record.

### D14: Row-level tenancy, single PostgreSQL schema

**See MODEL.md — Multi-tenancy section for full rationale.**

Short version: simpler migrations, easier cross-tenant admin queries, accepted
tradeoff of requiring filter discipline on every viewset.
