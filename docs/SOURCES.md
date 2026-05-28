# SOURCES.md — Research Behind Each Data Source

For each of the three sources: what real-world format was researched, what was
learned about its quirks, why the sample data looks the way it does, and what
would break in a real deployment.

---

## Source 1 — SAP MB51 flat file (fuel and procurement)

### What format was researched

SAP transaction MB51 (Material Document List) is the standard way to extract
goods movement history from SAP ERP/ECC/S4HANA without IT involvement. A
sustainability lead opens MB51, sets a date range, filters for plant(s) and
movement type 101 (goods receipt from purchase order), and exports via the
"Spreadsheet" button in the ALV grid toolbar.

The output is a tab-separated .txt file (or .xlsx if the user presses the
local file button). The column headers are in the SAP system language — German
for DE-configured systems, which covers most European enterprise clients.

**Key transaction codes researched:**
- MB51 — Material Document List (goods movements)
- ME2M — Purchase Orders by Material (alternative for procurement view)
- SE16 — Table browser for EKKO/EKPO/MSEG (requires developer access)
- MB52 — Warehouse Stock (not useful for emissions — snapshot, not history)

**Key SAP tables behind MB51:**
- MSEG — Material Document Segment (one row per goods movement line)
- MKPF — Material Document Header (document date, posting date, company code)
- EKKO — Purchasing Document Header (PO number, vendor, company)
- EKPO — Purchasing Document Item (material, quantity, unit)
- T001W — Plant / Branch (WERKS → plant name, country, address)

**IDoc and OData were also researched and rejected** — see DECISIONS.md D1
for the full rationale.

### What was learned about real-world quirks

1. **German column headers are the default.** SAP's system language is German
   unless explicitly changed by IT. Column headers like `Werk` (plant), `Menge`
   (quantity), `Mengeneinheit` (unit of measure), `Buchungsdatum` (posting date)
   appear verbatim in the export. Sustainability leads at German or
   German-configured companies send these files without thinking twice about it.

2. **Dates are DD.MM.YYYY.** SAP's German date format. Python's `datetime`
   module and pandas both expect YYYY-MM-DD by default. Every date field must
   be parsed explicitly.

3. **Units are mixed within the same file.** Diesel delivered by tanker truck
   is recorded in litres (L). Diesel delivered in 200L drums (IBC containers)
   is often recorded in KG because the supplier invoices by weight. LPG is in
   KG or M3 depending on whether the delivery is by bottle or pipeline.
   A single MB51 export for one plant can have L, KG, and M3 in the same
   Mengeneinheit column.

4. **Plant codes (WERKS) are meaningless without a lookup table.** SAP plants
   are typically 4-character alphanumeric codes: `1000`, `DE01`, `IN01`,
   `HAMB`, etc. These codes mean nothing to anyone outside the SAP
   configuration. The plant name, country, and city live in table T001W, which
   is not included in the MB51 export. A separate PlantLookup table is
   required. Clients must supply this mapping at onboarding.

5. **Cost centres (KOSTL) are frequently blank.** When a goods receipt is
   posted without a WBS element or cost centre assignment (common for
   decentralised purchasing), the KOSTL field exports as empty. This is
   not an error — it is normal SAP behaviour for unassigned procurement.

6. **Re-exports can include duplicates.** If a sustainability lead exports Q1
   and then re-exports "just January to check something" and appends the file,
   every January document appears twice. The same Materialdokument number
   appearing twice in one upload is a reliable duplicate indicator.

   **Note:** The parser's docstring describes within-run dedup by
   Materialdokument number, but this check is **not currently implemented**
   in the codebase. The `doc_number` column is mapped via `COLUMN_ALIASES`
   but never checked for duplicates during parsing. Duplicate rows are
   processed as separate activities. Cross-upload dedup is handled at the
   file level via SHA-256 hash (HTTP 409 on identical files).

7. **Movement type 101 is not the only type in MB51 exports.** If the user
   forgets to filter by movement type, the export includes 261 (goods issue
   to cost centre), 122 (return delivery), 501 (receipt without PO), and
   others. Only 101 represents new fuel procurement.

### Why the sample data looks the way it does

`test_sap_mb51.csv` contains 16 data rows (excluding header), each designed
to exercise a specific parser path:

| Data row | Test scenario |
|---|---|
| 1 | Standard diesel in L — happy path |
| 2 | LPG in KG — different fuel type and unit |
| 3 | Diesel in KG + blank KOSTL — KG→L conversion + missing cost centre flag |
| 4 | Indian plant (IN01) + INR currency — non-EUR data |
| 5 | 425,000 L diesel — large quantity (outlier check was removed but row remains) |
| 6 | WERKS=UNKNOWN — unknown plant code flag |
| 7 | Movement type 261 — skip non-goods-receipt row |
| 8 | Heating oil (HEL-001) — different fuel prefix |
| 9 | UNKNOWN-MAT material — failed-parse path for unrecognised material |
| 10 | Zero quantity diesel — edge case |
| 11 | NOT-A-DATE posting date — date parse failure |
| 12 | NOT-A-NUMBER quantity — quantity parse failure |
| 13 | Diesel in M3 — cubic metre → litre conversion |
| 14 | Duplicate of row 1 — same Materialdokument (processed as separate activity; see note on dedup above) |
| 15 | LPG in M3 — M3→KG conversion for LPG |

### What would break in a real deployment

1. **Non-standard column headers.** Some SAP configurations output English
   headers, some output customer-specific column labels, some include extra
   columns for custom fields (Z-fields). The COLUMN_ALIASES system handles
   many variants but must be extensible per client.

2. **Large file sizes.** A multinational enterprise with 50 plants uploading
   a full year of goods movements could produce 100,000+ rows. Synchronous
   parsing times out. Celery task queue is required (see TRADEOFFS.md).

3. **Encoding edge cases.** Some SAP systems output Windows-1252 (a superset
   of Latin-1) with characters not in the Latin-1 range. The parser handles
   UTF-8, UTF-8-BOM, and Latin-1 but not Windows-1252 explicitly.

4. **Material master gaps.** The prefix-matching approach (DIES-, LPG-, HEL-)
   breaks for clients with non-standard material numbering. A real deployment
   needs a per-client MATNR mapping table.

5. **Multi-company code exports.** Large clients may export MB51 across
   multiple SAP company codes (BUKRS). The same plant code can mean different
   things in different company codes. Company code filtering must be
   configurable.

6. **Within-file duplicate detection.** The same Materialdokument number
   appearing twice in one upload currently produces duplicate activities.
   A production parser needs a `seen_doc_numbers` set to detect and skip
   or flag within-run duplicates.

---

## Source 2 — Utility portal CSV (electricity)

### What format was researched

Most large utilities offer a customer web portal where facilities managers
download billing history as CSV. Research covered:

**India:** MSEDCL (Maharashtra), BESCOM (Karnataka), TPDDL (Delhi),
Tata Power Mumbai — all offer portal CSV downloads with broadly similar
column structures (account number, meter ID, billing period dates,
consumption in kWh, demand in kW, billed amount).

**UK/Europe:** National Grid, E.ON UK, EDF Energy, Vattenfall — portal
exports typically include meter MPAN, billing period, consumption kWh,
standing charge, unit rate, total amount.

**US:** Con Edison (NY), PG&E (CA), ComEd (IL) — Green Button CSV standard
(ESPI format) is available from some utilities, but most corporate accounts
use plain CSV portal exports.

The Green Button / ESPI XML standard was also reviewed. It would be the ideal
ingestion format (standardised schema, machine-readable) but is not universally
supported — particularly outside the US — and requires XML parsing rather
than CSV, which adds complexity for a prototype.

### What was learned about real-world quirks

1. **Billing periods do not align with calendar months.** This is the defining
   quirk of utility data. Billing cycles are typically 28–35 days but start
   on whatever day the meter was first read. A meter installed on 15 January
   bills on the 15th of each month forever: 15 Jan–17 Feb, 17 Feb–18 Mar.
   No utility billing period aligns with 1st–31st of a month unless the
   account was set up that way.

2. **Multiple meters per account, multiple accounts per site.** A single
   factory may have a high-voltage meter for production equipment (HV tariff),
   a low-voltage meter for office areas (LV tariff), and a separate substation
   meter for a data room. All three appear in the same portal CSV with the
   same account number but different meter IDs.

3. **Tariff codes vary by supplier and change over time.** HV-ToU (High
   Voltage Time-of-Use), LV-Flat, HT-1 (High Tension India), LT-1 (Low
   Tension India) are common codes but each utility uses its own naming.
   A tariff code not in the known set does not mean the data is wrong —
   it means the code needs to be added to the lookup.

4. **Demand charges (kW) are billing mechanisms, not emission sources.**
   The demand_kw column represents peak demand billed in a period and
   is used for capacity pricing. It does not directly produce CO₂ emissions.
   It is stored verbatim in raw_data for reference but excluded from
   the emission calculation.

5. **Zero consumption rows are real.** A vacant premises, a meter that was
   replaced mid-period, or a closed site during a holiday period can produce
   a legitimate zero-kWh bill. Zero is flagged for analyst review, not
   automatically rejected.

6. **Currency varies by site country.** German sites bill in EUR, Indian
   sites in INR, UK sites in GBP. Monetary amounts are stored verbatim with
   their source currency. No FX conversion is performed — cost reporting in
   a single currency is out of scope.

### Why the sample data looks the way it does

`test_utility.csv` contains 15 data rows (excluding header):

| Data row | Test scenario |
|---|---|
| 1 | MET-001, cross-month billing (15 Jan–17 Feb), HV-ToU — happy path |
| 2 | MET-002, calendar-aligned month (01 Jan–31 Jan), LV-Flat — contrast case |
| 3 | MET-IN01, INR currency, HT-1 tariff — Indian grid, different emission factor |
| 4 | MET-003, UNKNOWN-X tariff — unknown tariff code flag |
| 5 | MET-004, zero consumption — zero_consumption flag |
| 6 | MET-005, 3-day billing period (15–18 Feb) — short_period flag |
| 7 | MET-006, 90-day billing period (01 Jan–31 Mar) — long_period flag |
| 8 | MET-IN02, INR currency, HT-2 tariff — second Indian meter |
| 9 | MET-007, inverted dates (31 Mar–01 Mar) — inverted_period flag |
| 10 | Blank meter_id — missing_optional_field flag |
| 11 | MET-009, NOT-A-DATE end date — date parse handling |
| 12 | MET-010, NOTANUMBER consumption — quantity parse failure |
| 13 | Duplicate of row 1 (MET-001, same dates) — duplicate row |
| 14 | MET-011, LT-1 tariff — another known tariff |
| 15 | MET-012, blank consumption — empty value handling |

### What would break in a real deployment

1. **PDF bills.** Many utilities still mail PDF invoices. Some portals only
   offer PDF download for older periods. OCR-based PDF parsing would be
   required for full coverage.

2. **Non-standard column names.** Every utility names columns differently.
   The parser's COLUMN_ALIASES system handles many common variants.
   A real deployment needs a configurable per-utility column mapping.

3. **Green Button / ESPI XML format.** US utilities that support Green Button
   export data in ESPI XML, not CSV. A separate XML parser would be needed.

4. **Estimated vs actual readings.** Some utilities include an `E/A`
   (Estimated/Actual) flag on each bill. Estimated readings should be
   flagged differently from actual meter reads — the emission figure is
   less reliable.

5. **Time-of-use granularity.** HV-ToU tariffs charge different rates for
   peak and off-peak consumption. The portal CSV often splits consumption
   into peak_kwh and off_peak_kwh. Our parser treats total consumption as
   a single figure. Time-of-use granularity matters for demand response
   analysis but not for total Scope 2 emissions.

---

## Source 3 — Corporate travel CSV (Concur/Navan)

### What format was researched

**Concur SAP** (market leader, ~65% enterprise share): The standard expense
report export is accessible via Reports → Expense Report → Export. Columns
include ExpenseType (AIR/HOTEL/CAR/TRAIN), TransactionDate, City1/City2
(sometimes IATA codes, sometimes city names depending on config), Amount,
Currency, CostCenter, EmployeeID. The Concur API (v4) also exposes expense
data as JSON but requires OAuth and admin-level API credentials.

**Navan (TripActions)**: Similar CSV export structure. More consistent IATA
code capture than Concur. REST API is more developer-friendly but requires
per-client OAuth setup.

**TravelPerk**: EU-focused. Exports include a sustainability report with
pre-computed kg CO₂e — useful for cross-checking but not a substitute for
our own calculation (their methodology may differ).

**Cytric (Amadeus)**: Common in European enterprises. CSV export has similar
fields to Concur.

The Concur format was chosen as the primary target because of its install base
and because the column names are the most widely documented. See DECISIONS.md
D9.

### What was learned about real-world quirks

1. **Flights are identified by IATA codes only — no distance column.**
   Concur's expense form has fields for departure city and arrival city.
   When a corporate travel agent books the ticket, these are populated with
   airport codes. When an employee self-books and manually enters the expense,
   they sometimes enter city names instead of codes (e.g. "London" instead
   of "LHR"). The parser handles IATA codes; city names without codes
   produce an unknown_iata_code flag.

2. **Cabin class is frequently missing.** Concur's standard expense category
   for AIR does not have a mandatory cabin class field in many client
   configurations. Employees booking economy don't think to record it.
   The cabin class gap is systematic: it's absent on most economy bookings
   and present on business/first bookings (which are often pre-approved
   and more carefully documented).

3. **Hotel rows have no distance, only city and nights.**
   Hotel emission factors are per room-night, not per distance. The
   city field is stored in `facility_name` for analyst reference.
   No distance calculation is attempted for hotels.

4. **Car hire rows sometimes include distance, sometimes do not.**
   When a car hire is booked through the corporate tool, distance is
   estimated from the rental agreement. When claimed as an out-of-pocket
   expense, distance is whatever the employee enters (often blank or
   estimated). Blank distance produces zero emission with a flag.

5. **Trip IDs group legs of the same journey but are not always populated.**
   A Frankfurt→London flight + 2 hotel nights in London + London→Frankfurt
   return should all share a trip_id. In practice, manually entered expenses
   often have blank trip_ids. We store trip_id on each activity row for
   filtering but do not enforce it as required.

6. **Multiple currencies in one file.** An employee based in Germany flying
   to India via Dubai may have expenses in EUR, INR, and USD in a single
   trip. Monetary amounts are stored verbatim. No FX conversion is performed.

7. **Unsupported and unknown expense types are failed, not stored.**
   The parser maintains an `UNSUPPORTED_TYPES` set (FERRY, CRUISE, BOAT,
   SHIP) and an `EXPENSE_TYPE_MAP` for recognised types (AIR, FLIGHT, HOTEL,
   CAR, TRAIN, TAXI, UBER, BUS). Expense types in `UNSUPPORTED_TYPES` are
   marked as **failed** with a descriptive error. Expense types not in either
   set are also **failed** as unknown. In both cases no `NormalizedActivity`
   is created — the failure is recorded on the `RawRow` for analyst
   visibility. The `NormalizedActivity.ActivityType.OTHER` enum value exists
   but is not currently used by any parser.

### Why the sample data looks the way it does

`test_travel.csv` contains 21 data rows (excluding header):

| Data row | Test scenario |
|---|---|
| 1 | FRA→LHR Business class — standard calculable flight |
| 2 | Hotel in London, 2 nights — hotel emission (per room-night) |
| 3 | LHR→FRA return, Business — verifies return legs as separate rows |
| 4 | BOM→DEL, blank cabin class — Economy default + missing_cabin_class flag |
| 5 | FRA→SIN Economy, long-haul — tests haversine accuracy over 10,000 km |
| 6 | CAR with 38 km distance — ground transport calculation |
| 7 | TRAIN with 545 km distance — rail emission factor |
| 8 | DXB→BOM First class — First class emission factor |
| 9 | Unknown IATA code XXX — unknown_iata_code flag |
| 10 | Blank employee, blank cost centre — multiple flag accumulation |
| 11 | Hotel with 0 nights — zero-night edge case |
| 12 | FRA→FRA same airport — zero-distance route |
| 13 | FERRY expense — unsupported expense type → failed |
| 14 | NOT-A-DATE travel date — date parse failure |
| 15 | NOTANUM distance — distance parse failure |
| 16–17 | Duplicate TRAIN T-014 rows — duplicate handling |
| 18 | JFK→LAX Economy — US domestic route |
| 19 | Hotel in New York, 4 nights — multi-night hotel |
| 20 | LHR→BOM EXECUTIVE cabin — unrecognised cabin alias → Economy default |

### What would break in a real deployment

1. **City names instead of IATA codes.** When employees self-book and enter
   "London" rather than "LHR", the distance calculation fails and the row
   is flagged. A city-to-IATA resolver (using Google Places or a city lookup
   table) would be needed for high-quality data.

2. **Return flight detection.** A FRA→LHR and LHR→FRA in the same trip
   are currently treated as two separate one-way flights. This is correct
   if both are in the source file. If the client's Concur configuration
   records round-trips as a single row, the distance would need to be
   doubled. The format must be confirmed with the client.

3. **Rail routes without distance.** The TRAIN handler requires a
   `distance_km` column. Many rail bookings in Concur do not include
   distance — only origin/destination city names. A city-pair rail distance
   lookup (similar to IATA haversine) would be needed for full coverage.

4. **Ride-sharing and taxi.** Uber, Bolt, and local taxi expenses appear in
   Concur exports as TAXI or RIDESHARE. TAXI and UBER are mapped to
   ground_transport and use the car emission factor per km. RIDESHARE is not
   in the current `EXPENSE_TYPE_MAP` and would be failed as an unknown type.
   A real deployment needs to expand the type map or add a configurable
   mapping.

5. **International roaming of IATA registry.** The static dict covers 83
   airports. Any client with significant travel to secondary airports
   (e.g. Tier-2 Indian cities: IXR, IXB, IXU) will produce
   unknown_iata_code flags for legitimate routes. The registry must be
   expanded or replaced with a full OurAirports database.
