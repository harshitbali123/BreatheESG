"""
Utility portal CSV parser
=========================
Handles electricity billing data exported from utility portals
(e.g. MSEDCL, Tata Power, National Grid, Con Edison). A facilities
manager downloads this as a CSV from the supplier's web portal and
uploads it to BreatheESG.

Real-world quirks this parser handles
--------------------------------------
1. Billing periods ≠ calendar months.
   A bill might run "15 Jan – 17 Feb". We store both dates verbatim
   on NormalizedActivity (activity_date = period_start,
   period_end = period_end). We do NOT prorate across months in this
   prototype — noted in TRADEOFFS.md. The full kWh for the billing
   period is assigned to the start date.

2. Multiple meters per file.
   A single upload can contain rows for MET-001, MET-002, MET-003 at
   the same site. Each meter row becomes its own NormalizedActivity so
   analysts can approve/reject per meter.

3. Tariff codes vary by supplier and region.
   We maintain a known-good set (KNOWN_TARIFFS). Any tariff_code not
   in that set is flagged as a warning — the activity is still created
   because the consumption is real, but an analyst must review it.

4. demand_kw is informational only.
   Demand charges don't directly produce CO2 emissions — they are a
   billing mechanism. We store demand_kw on raw_data for reference but
   do not use it in the emission calculation.

5. Grid emission factor is tenant-scoped.
   Each Tenant has a grid_emission_factor_kg_per_kwh field set at
   onboarding (defaulting to UK DEFRA 2023: 0.23314 kg/kWh). Indian
   sites use a different grid mix — the tenant field handles this.
   We also look up an EmissionFactor record (DEFRA 2023) and use
   whichever is more specific: per-tenant factor takes precedence.

6. Consumption of zero is suspicious.
   A meter reporting 0 kWh for a billing period usually means the
   export was wrong (empty cell interpreted as 0). We flag it.

7. Period length sanity check.
   A billing period longer than 95 days or shorter than 10 days is
   unusual — we flag it. Most billing cycles are 28–35 days.

8. Flexible column mapping (resilient ingestion).
   Files from different utility portals use different column headers.
   We use an alias system so that e.g. "Usage_Value", "consumption_kwh",
   "kwh", "usage_kwh" all map to the internal "consumption_kwh" key.
   Only columns essential for CO2 calculation cause failure when missing.

What this parser does NOT handle
----------------------------------
- Market-based Scope 2 (RECs, PPAs, green tariffs). All rows are
  treated as location-based Scope 2. Market-based is noted in
  TRADEOFFS.md as a deliberate cut.
- PDF bills. We only handle CSV portal exports. PDF parsing would
  require OCR and is a separate ingestion mode.
- Gas or water meters. Only electricity (kWh) is handled. Other
  utilities would require different emission factors and unit logic.
- Multi-currency electricity costs. Monetary amounts are stored
  verbatim with their source currency; no FX conversion.
"""

import csv
import io
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.ingestion.models import IngestionRun, RawRow
from apps.normalization.models import EmissionFactor, NormalizedActivity
from .base import BaseParser, parse_flexible_date

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Flexible column alias map
# ---------------------------------------------------------------------------
# Each internal key maps to a list of aliases (case-insensitive) that should
# be recognised in incoming files. The first matching alias wins.
# Priority: columns essential for CO2 calculation are marked as CRITICAL.
#
# CRITICAL for CO2 = consumption_kwh, period_start (at least one date)
# All other fields are OPTIONAL — ingestion proceeds even if they are absent.

COLUMN_ALIASES = {
    "consumption_kwh": [
        "consumption_kwh", "usage_value", "kwh", "usage_kwh",
        "consumption", "total_kwh", "energy_kwh", "units_consumed",
    ],
    "period_start": [
        "billing_period_start", "bill_start_date", "period_start",
        "start_date", "from_date", "bill_from",
    ],
    "period_end": [
        "billing_period_end", "bill_end_date", "period_end",
        "end_date", "to_date", "bill_to",
    ],
    "meter_id": [
        "meter_id", "account_number", "account_no", "meter_number",
        "meter_no", "meter_ref", "meter",
    ],
    "service_address": [
        "service_address", "address", "site_address", "location",
        "site", "facility",
    ],
    "demand_kw": [
        "demand_kw", "peak_demand_kw", "peak_demand", "max_demand",
        "demand",
    ],
    "amount": [
        "amount", "total_amount", "bill_amount", "cost", "charge",
        "total_cost", "total_charge",
    ],
    "currency": [
        "currency", "currency_code", "ccy",
    ],
    "tariff_code": [
        "tariff_code", "rate_schedule", "tariff", "rate_code",
        "plan_code", "tariff_type",
    ],
}


def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """
    Given the raw CSV column headers, build a mapping:
        raw_column_name -> internal_key

    Uses case-insensitive matching against COLUMN_ALIASES.
    Columns not matching any alias are kept as-is (pass-through).
    """
    mapping = {}
    normalised_fields = {f.strip().lower(): f.strip() for f in fieldnames if f}

    for internal_key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in normalised_fields:
                original_header = normalised_fields[alias.lower()]
                mapping[original_header] = internal_key
                break  # first match wins

    return mapping


# Tariff codes we recognise. Anything outside this set gets flagged.
# These cover the codes present in our sample data and common real-world
# utility tariff structures:
#   HV-ToU  = High Voltage, Time-of-Use
#   LV-Flat = Low Voltage, Flat rate
#   HT-1    = High Tension type 1 (common in India)
#   LT-1    = Low Tension type 1
#   HT-2    = High Tension type 2
KNOWN_TARIFFS = {"HV-ToU", "LV-Flat", "HT-1", "LT-1", "HT-2"}

# Billing period sanity bounds (days)
MIN_PERIOD_DAYS = 10
MAX_PERIOD_DAYS = 95

# A meter reading of exactly zero is suspicious
ZERO_CONSUMPTION_FLAG = True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse(run: IngestionRun, file_obj) -> dict:
    """Module-level entry point called by the dispatch layer in views.py."""
    return UtilityParser().parse(run, file_obj)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class UtilityParser(BaseParser):
    """
    Concrete parser for utility portal CSV exports.
    Inherits the row loop, RawRow creation, and error handling from
    BaseParser. Implements _iter_rows and _normalize_row.
    """

    def _iter_rows(self, file_obj):
        """
        Read the CSV and yield one translated dict per data row.

        Encoding: utility portal exports are almost always UTF-8.
        We still try UTF-8-sig first to strip the Excel BOM.

        Header translation: we normalise the incoming header names
        to internal keys so the rest of the parser never touches raw
        column names.

        Resilient column mapping: uses COLUMN_ALIASES to recognise
        many common column name variants. Only fails if the columns
        critical for CO2 calculation are truly absent.
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
                "Could not decode the file. Expected UTF-8 or Latin-1."
            )

        reader = csv.DictReader(io.StringIO(text))

        if reader.fieldnames is None:
            raise ValueError("File appears to be empty — no header row found.")

        # Build flexible column mapping from aliases
        col_map = _build_column_map(reader.fieldnames)

        # --- Check ONLY critical columns for CO2 calculation ---
        # Critical: consumption_kwh (the quantity to multiply by EF)
        # At least one date is needed (period_start preferred, period_end as fallback)
        mapped_internal_keys = set(col_map.values())

        if "consumption_kwh" not in mapped_internal_keys:
            raise ValueError(
                f"Missing critical column for CO2 calculation: 'consumption_kwh'. "
                f"Expected one of: {', '.join(COLUMN_ALIASES['consumption_kwh'])}. "
                f"Found columns: {', '.join(sorted(h.strip() for h in reader.fieldnames if h))}"
            )

        has_start = "period_start" in mapped_internal_keys
        has_end = "period_end" in mapped_internal_keys
        if not has_start and not has_end:
            raise ValueError(
                f"Missing critical column for CO2 calculation: at least one billing date "
                f"(period start or end) is required. "
                f"Expected one of: {', '.join(COLUMN_ALIASES['period_start'] + COLUMN_ALIASES['period_end'])}. "
                f"Found columns: {', '.join(sorted(h.strip() for h in reader.fieldnames if h))}"
            )

        # Log which optional columns were not found
        optional_missing = []
        for key in COLUMN_ALIASES:
            if key not in mapped_internal_keys and key != "consumption_kwh":
                if key in ("period_start", "period_end"):
                    if has_start or has_end:
                        continue  # at least one date found
                optional_missing.append(key)

        if optional_missing:
            logger.info(
                "Utility parser: optional columns not found (will use defaults): %s",
                ", ".join(optional_missing),
            )

        for raw_row in reader:
            # Strip whitespace from keys and values
            cleaned = {k.strip(): v.strip() for k, v in raw_row.items()
                       if k is not None}
            # Translate to internal keys; unknown columns kept as-is
            yield {
                col_map.get(k, k): v for k, v in cleaned.items()
            }

    # ------------------------------------------------------------------ #

    def _validate_raw(self, raw: dict) -> list:
        """
        Pre-save validation. Returns warning strings.
        Called by BaseParser before creating the RawRow.
        """
        warnings = []

        # Critical field: consumption_kwh
        if not raw.get("consumption_kwh"):
            warnings.append(
                "missing_critical_field: 'consumption_kwh' is blank — "
                "cannot calculate CO2 emissions"
            )

        # At least one date
        if not raw.get("period_start") and not raw.get("period_end"):
            warnings.append(
                "missing_critical_field: both billing period dates are blank"
            )

        # Optional fields — warn but don't block
        if not raw.get("meter_id"):
            warnings.append(
                "missing_optional_field: 'meter_id' is blank — "
                "row will still be ingested"
            )

        # Tariff code check
        tariff = raw.get("tariff_code", "").strip()
        if tariff and tariff not in KNOWN_TARIFFS:
            warnings.append(
                f"unknown_tariff_code: '{tariff}' is not in the known "
                f"tariff list {sorted(KNOWN_TARIFFS)} — verify with "
                "the facilities team"
            )

        # Zero consumption
        kwh_str = raw.get("consumption_kwh", "").replace(",", ".")
        try:
            kwh = Decimal(kwh_str)
            if ZERO_CONSUMPTION_FLAG and kwh == 0:
                warnings.append(
                    "zero_consumption: meter reported 0 kWh — "
                    "check for export error or vacant premises"
                )
        except InvalidOperation:
            pass  # caught properly in _normalize_row

        # Billing period length
        start = parse_flexible_date(raw.get("period_start", ""))
        end   = parse_flexible_date(raw.get("period_end", ""))
        if start and end:
            delta = (end - start).days
            if delta < MIN_PERIOD_DAYS:
                warnings.append(
                    f"short_billing_period: {delta} days is unusually "
                    f"short (minimum expected: {MIN_PERIOD_DAYS})"
                )
            elif delta > MAX_PERIOD_DAYS:
                warnings.append(
                    f"long_billing_period: {delta} days is unusually "
                    f"long (maximum expected: {MAX_PERIOD_DAYS}) — "
                    "possible combined bill or export error"
                )
            if end < start:
                warnings.append(
                    "inverted_period: billing_period_end is before "
                    "billing_period_start"
                )

        return warnings

    # ------------------------------------------------------------------ #

    def _normalize_row(self, raw_row: RawRow, run: IngestionRun):
        """
        Convert one RawRow into a NormalizedActivity with scope=2.

        Emission calculation:
            normalized_kg_co2e = consumption_kwh × emission_factor

        The emission factor comes from one of two sources, in priority order:
            1. The Tenant's grid_emission_factor_kg_per_kwh (set at
               onboarding, accounts for regional grid mix)
            2. The EmissionFactor table (DEFRA 2023 UK average)

        We always store emission_factor_used and emission_factor_source
        on the activity so the calculation is auditable.
        """
        raw    = raw_row.raw_data
        tenant = run.tenant

        # ── Parse consumption (CRITICAL for CO2) ──────────────────────
        try:
            kwh = Decimal(
                raw.get("consumption_kwh", "0")
                   .replace(",", ".")
                   .strip() or "0"
            )
        except InvalidOperation:
            raw_row.parse_status = RawRow.ParseStatus.FAILED
            raw_row.parse_errors = raw_row.parse_errors + [
                f"invalid_consumption: "
                f"'{raw.get('consumption_kwh')}' cannot be parsed as a number"
            ]
            raw_row.save(update_fields=["parse_status", "parse_errors"])
            return None

        # ── Parse dates (at least one needed) ─────────────────────────
        period_start = parse_flexible_date(raw.get("period_start", ""))
        period_end   = parse_flexible_date(raw.get("period_end", ""))

        # If we have neither date, fail — we need at least one for activity_date
        if period_start is None and period_end is None:
            raw_row.parse_status = RawRow.ParseStatus.FAILED
            raw_row.parse_errors = raw_row.parse_errors + [
                "missing_critical_date: neither billing period start nor end "
                "could be parsed — at least one date is required for CO2 calculation"
            ]
            raw_row.save(update_fields=["parse_status", "parse_errors"])
            return None

        # Use whichever date we have as fallback
        if period_start is None:
            period_start = period_end
        if period_end is None:
            period_end = period_start

        # ── Resolve emission factor ───────────────────────────────────
        ef_value, ef_source = _resolve_emission_factor(tenant)

        kg_co2e = kwh * ef_value

        # ── Parse monetary amount (optional) ──────────────────────────
        try:
            original_amount = Decimal(
                raw.get("amount", "0").replace(",", ".").strip() or "0"
            )
        except InvalidOperation:
            original_amount = None

        # ── Carry forward any flags from _validate_raw ────────────────
        flag_reasons   = list(raw_row.parse_errors)
        is_suspicious  = bool(flag_reasons)

        # ── Build description ─────────────────────────────────────────
        meter_id = raw.get("meter_id", "")
        tariff   = raw.get("tariff_code", "")
        period_label = (
            f"{raw.get('period_start', '')} – {raw.get('period_end', '')}"
        )
        description = (
            f"Electricity — {meter_id}"
            + (f" ({tariff})" if tariff else "")
            + f" | {period_label}"
        )

        # ── Update raw_row parse_status if we have flags ──────────────
        if is_suspicious and raw_row.parse_status == RawRow.ParseStatus.OK:
            raw_row.parse_status = RawRow.ParseStatus.WARNING
            raw_row.parse_errors = flag_reasons
            raw_row.save(update_fields=["parse_status", "parse_errors"])

        # ── Build NormalizedActivity ──────────────────────────────────
        return NormalizedActivity(
            tenant        = tenant,
            ingestion_run = run,
            raw_row       = raw_row,

            activity_type = NormalizedActivity.ActivityType.ELECTRICITY,
            activity_date = period_start,   # billing period start
            period_end    = period_end,     # billing period end
            description   = description,

            # facility_code = meter ID so analysts can filter by meter
            facility_code   = meter_id,
            facility_name   = raw.get("service_address", ""),
            country_code    = "",           # not in source — tenant knows
            cost_center     = "",           # not in utility exports

            scope           = NormalizedActivity.Scope.SCOPE_2,
            scope3_category = None,

            # Source values — verbatim from file
            original_value    = kwh,
            original_unit     = "kWh",
            original_currency = raw.get("currency", ""),
            original_amount   = original_amount,

            # Emission output
            normalized_kg_co2e     = round(kg_co2e, 6),
            emission_factor_used   = ef_value,
            emission_factor_source = ef_source,

            review_status         = NormalizedActivity.ReviewStatus.PENDING,
            is_flagged_suspicious = is_suspicious,
            flag_reasons          = flag_reasons,
        )
        # BaseParser calls .save() after we return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------




def _resolve_emission_factor(tenant):
    """
    Return (factor_value: Decimal, source_label: str).

    Priority:
    1. Tenant's grid_emission_factor_kg_per_kwh — set at onboarding to
       reflect the regional grid mix (e.g. Indian grid ≈ 0.82 kg/kWh,
       much higher than UK's 0.233).
    2. EmissionFactor table record for electricity/kWh (DEFRA 2023
       UK average, seeded by seed_dev command).
    3. Hard-coded DEFRA 2023 fallback so the parser never crashes even
       if the DB was not seeded.

    We always prefer the tenant-specific factor because grid emission
    intensity varies significantly by country (0.02 kg/kWh in Norway
    vs 0.82 in India). Using a global average for an Indian site would
    understate emissions by 3.5×.
    """
    # 1. Tenant-specific factor (set at onboarding)
    if tenant.grid_emission_factor_kg_per_kwh:
        source = (
            f"Tenant grid factor — {tenant.name} "
            f"({tenant.country_code})"
        )
        return Decimal(str(tenant.grid_emission_factor_kg_per_kwh)), source

    # 2. EmissionFactor table
    ef = (
        EmissionFactor.objects
        .filter(fuel_type="electricity", unit="kWh")
        .order_by("-valid_from_year")
        .first()
    )
    if ef:
        return ef.kg_co2e_per_unit, ef.source

    # 3. Hard-coded fallback — DEFRA 2023 UK grid average
    logger.warning(
        "No electricity emission factor found in DB; "
        "using hard-coded DEFRA 2023 fallback (0.23314 kg/kWh)"
    )
    return Decimal("0.23314"), "DEFRA 2023 (fallback)"
