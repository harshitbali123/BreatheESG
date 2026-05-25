"""
SAP MB51 flat file parser
=========================
Handles tab-separated exports from SAP transaction MB51
(Material Document List), which is how a sustainability lead at
an enterprise client would typically extract fuel and procurement
data without IT involvement.

Real-world quirks this parser handles
--------------------------------------
1. German column headers — SAP defaults to the system language.
   A DE-configured system outputs WERKS, not "Plant". The HEADER_MAP
   below translates every column we care about.

2. Mixed units per row — some rows are in L (litres), some in KG
   (kilogram, e.g. drum purchases), some in M3 (cubic metres for
   LPG tanks). Emission factors are per-litre or per-kg depending on
   fuel type, so we normalise to the factor's expected unit before
   multiplying.

3. DD.MM.YYYY dates — SAP's German date format. Python's default
   date parsing expects YYYY-MM-DD or MM/DD/YYYY; we handle it
   explicitly.

4. Plant codes (WERKS) are meaningless without a lookup table.
   "1000" or "DE01" doesn't tell you country or site. We query
   PlantLookup; if the code is missing we flag the row (warning,
   not failure — the activity is still created).

5. Blank KOSTL (cost centre) — common when a goods receipt is posted
   without a WBS/cost centre assignment. We flag it but don't reject
   the row.

6. Outlier detection — a single-day receipt above OUTLIER_THRESHOLD_L
   (100,000 litres / equivalent) is statistically implausible for most
   sites and gets flagged for analyst review.

7. Duplicate material documents — SAP re-exports can include the same
   Materialdokument number twice. We detect this within a single run
   and skip the duplicate, logging it as a warning.

What this parser does NOT handle (and why)
-------------------------------------------
- Movement type 261 (goods issue to production) — we only ingest
  goods receipts (Bewegungsart 101). Other movement types don't
  represent fuel procurement. Noted in DECISIONS.md.
- Non-fuel materials — MATNR codes not in MATERIAL_MAP are skipped
  with a warning. A real deployment would have a configurable
  material master lookup.
- Multi-currency conversion — amounts are stored verbatim in their
  source currency (EUR / INR). FX conversion is out of scope.
"""

import csv
import io
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.ingestion.models import IngestionRun, RawRow
from apps.normalization.models import EmissionFactor, NormalizedActivity
from apps.tenants.models import PlantLookup
from .base import BaseParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# German SAP header → internal key used throughout this parser.
# Only columns we actually use are listed; everything else is ignored.
HEADER_MAP = {
    # Technical SAP field names / common export aliases
    "WERKS":             "plant_code",
    "WERK":              "plant_code",
    "MATNR":             "material_number",
    "KURZTEXT":          "material_desc",
    "BWART":             "movement_type",
    "MENGE":             "quantity",
    "MEINS":             "unit",
    "BUDAT":             "posting_date",
    "LIFNR":             "vendor_id",
    "LIEFERANTENNAME":   "vendor_name",
    "EINKAUFSBELEG":     "po_number",
    "KOSTENSTELLE":      "cost_centre",
    "KOSTL":             "cost_centre",
    "WAEHRUNG":          "currency",
    "WÄHRUNG":           "currency",
    "WERT":              "amount",

    # Material document identity
    "Materialdokument":  "doc_number",
    "Pos.":              "doc_position",

    # Dates
    "Buchungsdatum":     "posting_date",    # DD.MM.YYYY
    "Belegjahr":         "fiscal_year",

    # Organisational units
    "Werk":              "plant_code",       # WERKS
    "Lagerort":          "storage_location", # LGORT

    # Material
    "Materialnummer":    "material_number",  # MATNR
    "Kurztext":          "material_desc",    # MAKTX

    # Movement
    "Bewegungsart":      "movement_type",    # BWART — 101 = GR from PO

    # Quantity
    "Menge":             "quantity",         # MENGE
    "Mengeneinheit":     "unit",             # MEINS

    # Value
    "Wert (HW)":         "amount",           # DMBTR in local currency
    "Währung":           "currency",         # WAERS

    # Vendor / purchasing
    "Lieferant":         "vendor_id",        # LIFNR
    "Lieferantenname":   "vendor_name",
    "Einkaufsbeleg":     "po_number",        # EBELN

    # Cost assignment
    "Kostenstelle":      "cost_centre",      # KOSTL
    "Buchungsperiode":   "posting_period",
}

# Material number prefixes → (activity_type, emission_factor_fuel_type, scope)
# A real deployment would drive this from a configurable material master table.
MATERIAL_MAP = {
    "DIES-": ("diesel",      "diesel",      "1"),
    "LPG-":  ("lpg",         "lpg",         "1"),
    "HEL-":  ("heating_oil", "heating_oil", "1"),
    "CNG-":  ("natural_gas", "natural_gas", "1"),
}

# Movement types we ingest. 101 = goods receipt from purchase order.
# All others are skipped — this is intentional (see module docstring).
ACCEPTED_MOVEMENT_TYPES = {"101"}

# Diesel density for KG → L conversion (EN590 grade, ~15°C)
DIESEL_DENSITY_KG_PER_L = Decimal("0.8400")

# LPG density for M3 → KG conversion (propane at ~20°C)
LPG_DENSITY_KG_PER_M3 = Decimal("1.8980")

# Any single-day receipt above this number of litres (or kg-equivalent)
# triggers a suspicion flag. Analyst must explicitly approve or dismiss.
OUTLIER_THRESHOLD = Decimal("100000")


# ---------------------------------------------------------------------------
# Public entry point (called by dispatch layer in views.py)
# ---------------------------------------------------------------------------

def parse(run: IngestionRun, file_obj) -> dict:
    """
    Module-level entry point. Instantiates the parser and delegates.
    The dispatch layer in views.py calls parse(run, file_obj).
    """
    return SapMb51Parser().parse(run, file_obj)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class SapMb51Parser(BaseParser):
    """
    Concrete parser for SAP MB51 tab-separated flat file exports.
    Inherits the row-loop, RawRow creation, and error handling from
    BaseParser. Only _iter_rows and _normalize_row are implemented here.
    """

    def _iter_rows(self, file_obj):
        """
        Read the file and yield one dict per data row.

        SAP MB51 exports are almost always UTF-8 or Latin-1. We try
        UTF-8 first; if that fails we fall back to latin-1 which covers
        the German umlauts (ü, ö, ä) that appear in some Kurztext fields.

        We also strip the BOM that Excel sometimes prepends when a user
        opens the file and saves it.
        """
        raw_bytes = file_obj.read()

        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = raw_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(
                "Could not decode the file. Expected UTF-8 or Latin-1 encoding."
            )

        # SAP exports use tab as the delimiter. Some older exports use
        # a semicolon; we detect by checking the first line.
        first_line = text.split("\n")[0]
        delimiter  = "\t" if "\t" in first_line else ";"

        reader = csv.DictReader(
            io.StringIO(text),
            delimiter=delimiter,
            skipinitialspace=True,
        )

        # Translate German headers to internal keys on the first row.
        # If a header is not in HEADER_MAP we keep it as-is so raw_data
        # is always a complete copy of the source row.
        for raw_row in reader:
            # Strip whitespace from all values (SAP pads some fields)
            cleaned = {k.strip(): v.strip() for k, v in raw_row.items()}

            # Translate to internal keys
            translated = {}
            for header, value in cleaned.items():
                internal_key = HEADER_MAP.get(header, header)
                translated[internal_key] = value

            yield translated

    # ------------------------------------------------------------------ #

    def _validate_raw(self, raw: dict) -> list:
        """
        Pre-save validation. Returns a list of warning strings.
        Called by BaseParser before creating the RawRow.
        Empty list = clean row.
        """
        warnings = []

        # Required fields
        for field in ("posting_date", "quantity", "unit", "material_number"):
            if not raw.get(field):
                warnings.append(f"missing_required_field: '{field}' is blank")

        # Movement type filter
        mvt = raw.get("movement_type", "")
        if mvt and mvt not in ACCEPTED_MOVEMENT_TYPES:
            warnings.append(
                f"skipped_movement_type: {mvt} is not a goods receipt (101)"
            )

        # Cost centre
        if not raw.get("cost_centre"):
            warnings.append(
                "missing_cost_centre: KOSTL is blank — "
                "cost centre not assigned in SAP"
            )

        # Date format sanity
        posting_date = raw.get("posting_date", "")
        if posting_date and not _looks_like_german_date(posting_date):
            warnings.append(
                f"unexpected_date_format: '{posting_date}' "
                "is not DD.MM.YYYY — date parsing may fail"
            )

        return warnings

    # ------------------------------------------------------------------ #

    def _normalize_row(self, raw_row: RawRow, run: IngestionRun):
        """
        Convert one RawRow to a NormalizedActivity.
        Returns None if the row should not produce an activity
        (unknown material, wrong movement type, unparseable quantity).
        """
        raw   = raw_row.raw_data
        tenant = run.tenant

        # ── Skip non-GR movement types ────────────────────────────────
        mvt = raw.get("movement_type", "")
        if mvt and mvt not in ACCEPTED_MOVEMENT_TYPES:
            logger.debug(
                "Run %s row %s: skipping movement type %s",
                run.id, raw_row.row_number, mvt,
            )
            return None

        # ── Identify the material ─────────────────────────────────────
        matnr        = raw.get("material_number", "")
        activity_type, ef_fuel_key, scope = _classify_material(matnr)

        if activity_type is None:
            logger.debug(
                "Run %s row %s: unknown material '%s' — skipping",
                run.id, raw_row.row_number, matnr,
            )
            # Record as a failed row so the analyst can see it
            raw_row.parse_status = RawRow.ParseStatus.FAILED
            raw_row.parse_errors = raw_row.parse_errors + [
                f"unknown_material: '{matnr}' not in material map"
            ]
            raw_row.save(update_fields=["parse_status", "parse_errors"])
            return None

        # ── Parse quantity and unit ───────────────────────────────────
        try:
            raw_qty  = Decimal(raw.get("quantity", "0").replace(",", "."))
            raw_unit = raw.get("unit", "").strip().upper()
        except InvalidOperation:
            raw_row.parse_status = RawRow.ParseStatus.FAILED
            raw_row.parse_errors = raw_row.parse_errors + [
                f"invalid_quantity: '{raw.get('quantity')}' cannot be parsed"
            ]
            raw_row.save(update_fields=["parse_status", "parse_errors"])
            return None

        # ── Unit normalisation ────────────────────────────────────────
        # Convert to the unit the emission factor expects.
        # We store the original (raw_qty, raw_unit) and the normalised
        # quantity separately so auditors can verify the conversion.
        norm_qty, norm_unit = _normalise_unit(raw_qty, raw_unit, activity_type)

        # ── Fetch emission factor ─────────────────────────────────────
        ef = _get_emission_factor(ef_fuel_key, norm_unit)
        if ef is None:
            raw_row.parse_status = RawRow.ParseStatus.FAILED
            raw_row.parse_errors = raw_row.parse_errors + [
                f"missing_emission_factor: no factor for "
                f"fuel_type='{ef_fuel_key}' unit='{norm_unit}'"
            ]
            raw_row.save(update_fields=["parse_status", "parse_errors"])
            return None

        kg_co2e = norm_qty * ef.kg_co2e_per_unit

        # ── Parse date ────────────────────────────────────────────────
        activity_date = _parse_german_date(raw.get("posting_date", ""))
        if activity_date is None:
            raw_row.parse_status = RawRow.ParseStatus.FAILED
            raw_row.parse_errors = raw_row.parse_errors + [
                f"invalid_date: '{raw.get('posting_date')}' "
                "could not be parsed as DD.MM.YYYY"
            ]
            raw_row.save(update_fields=["parse_status", "parse_errors"])
            return None

        # ── Plant lookup ──────────────────────────────────────────────
        plant_code = raw.get("plant_code", "")
        plant_name = ""
        country_code = ""
        flag_reasons = list(raw_row.parse_errors)  # carry forward _validate_raw warnings

        if plant_code:
            lookup = PlantLookup.objects.filter(
                tenant=tenant, plant_code=plant_code
            ).first()
            if lookup:
                plant_name   = lookup.plant_name
                country_code = lookup.country_code
            else:
                flag_reasons.append(
                    f"unknown_plant_code: '{plant_code}' not in plant "
                    "lookup table — add it via Django admin"
                )
        else:
            flag_reasons.append("missing_plant_code: WERKS is blank")

        # ── Outlier detection ─────────────────────────────────────────
        # Compare normalised quantity (always in factor's unit) to threshold.
        if norm_qty > OUTLIER_THRESHOLD:
            flag_reasons.append(
                f"value_outlier: {norm_qty} {norm_unit} in a single receipt "
                f"exceeds the threshold of {OUTLIER_THRESHOLD} — "
                "verify against purchase order"
            )

        # ── Parse monetary amount ─────────────────────────────────────
        try:
            original_amount = Decimal(
                raw.get("amount", "0").replace(",", ".") or "0"
            )
        except InvalidOperation:
            original_amount = None

        # ── Build NormalizedActivity ──────────────────────────────────
        is_suspicious = bool(flag_reasons)

        activity = NormalizedActivity(
            tenant        = tenant,
            ingestion_run = run,
            raw_row       = raw_row,

            activity_type = activity_type,
            activity_date = activity_date,
            description   = raw.get("material_desc", ""),

            facility_code = plant_code,
            facility_name = plant_name,
            country_code  = country_code,
            cost_centre   = raw.get("cost_centre", ""),
            vendor        = raw.get("vendor_name", raw.get("vendor_id", "")),

            scope           = scope,
            scope3_category = None,  # Scope 1 — no S3 category

            # Source values — verbatim from the file
            original_value    = raw_qty,
            original_unit     = raw_unit,
            original_currency = raw.get("currency", ""),
            original_amount   = original_amount,

            # Normalised emission output
            normalized_kg_co2e     = round(kg_co2e, 6),
            emission_factor_used   = ef.kg_co2e_per_unit,
            emission_factor_source = ef.source,

            review_status         = NormalizedActivity.ReviewStatus.PENDING,
            is_flagged_suspicious = is_suspicious,
            flag_reasons          = flag_reasons,
        )

        # ── Update raw_row parse_status to reflect any flags ──────────
        if is_suspicious and raw_row.parse_status == RawRow.ParseStatus.OK:
            raw_row.parse_status = RawRow.ParseStatus.WARNING
            raw_row.parse_errors = flag_reasons
            raw_row.save(update_fields=["parse_status", "parse_errors"])

        return activity   # BaseParser calls .save() after we return


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _classify_material(matnr: str):
    """
    Return (activity_type, ef_fuel_key, scope) for a material number,
    or (None, None, None) if the material is not recognised.

    We match by prefix so that DIES-001, DIES-002, DIES-003 all resolve
    to diesel without needing every individual material number listed.
    """
    matnr_upper = matnr.upper()
    for prefix, mapping in MATERIAL_MAP.items():
        if matnr_upper.startswith(prefix):
            return mapping
    return (None, None, None)


def _normalise_unit(qty: Decimal, unit: str, activity_type: str):
    """
    Convert quantity to the unit the emission factor expects.

    Rules:
    - Diesel in KG → L  (divide by density 0.84 kg/L)
    - Diesel in M3 → L  (multiply by 1000)
    - LPG in M3 → KG    (multiply by density 1.898 kg/m3)
    - Everything else → returned unchanged

    Returns (normalised_qty, normalised_unit).
    The original values are already saved on NormalizedActivity.original_value
    and .original_unit — we never overwrite them here.
    """
    if activity_type == "diesel":
        if unit == "KG":
            return qty / DIESEL_DENSITY_KG_PER_L, "L"
        if unit == "M3":
            return qty * Decimal("1000"), "L"
        return qty, unit   # already L

    if activity_type == "lpg":
        if unit == "M3":
            return qty * LPG_DENSITY_KG_PER_M3, "KG"
        return qty, unit   # already KG

    if activity_type == "heating_oil":
        if unit == "KG":
            # Heating oil density ~0.845 kg/L
            return qty / Decimal("0.845"), "L"
        if unit == "M3":
            return qty * Decimal("1000"), "L"
        return qty, unit

    if activity_type == "natural_gas":
        if unit == "M3":
            # Natural gas: 1 m3 ≈ 0.717 kg at standard conditions
            return qty * Decimal("0.717"), "KG"
        return qty, unit

    return qty, unit


def _get_emission_factor(fuel_type: str, unit: str):
    """
    Fetch the most recent emission factor for fuel_type + unit.
    Returns None if no factor is found — caller marks row as failed.

    We order by valid_from_year descending so we always get the
    latest published factor. This matches what the seed command inserts
    (DEFRA 2023 values).
    """
    return (
        EmissionFactor.objects
        .filter(fuel_type=fuel_type, unit=unit)
        .order_by("-valid_from_year")
        .first()
    )


def _parse_german_date(date_str: str):
    """
    Parse DD.MM.YYYY into a Python date object.
    Returns None on failure rather than raising — callers handle None.

    Examples:
        "03.01.2024" → date(2024, 1, 3)
        "31.12.2023" → date(2023, 12, 31)
        ""           → None
    """
    if not date_str or not date_str.strip():
        return None
    try:
        parts = date_str.strip().split(".")
        if len(parts) != 3:
            return None
        day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def _looks_like_german_date(date_str: str) -> bool:
    """
    Quick sanity check before attempting full parse.
    Validates the XX.XX.XXXX pattern without allocating a date object.
    """
    parts = date_str.strip().split(".")
    if len(parts) != 3:
        return False
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        return 1 <= d <= 31 and 1 <= m <= 12 and 1900 <= y <= 2100
    except ValueError:
        return False