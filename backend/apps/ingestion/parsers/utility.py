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

# Column headers we expect in the utility portal CSV.
# Keys are the exact strings in the file header row.
# Values are internal keys used throughout this parser.
HEADER_MAP = {
    "account_number":       "account_number",
    "meter_id":             "meter_id",
    "service_address":      "service_address",
    "billing_period_start": "period_start",
    "billing_period_end":   "period_end",
    "consumption_kwh":      "consumption_kwh",
    "demand_kw":            "demand_kw",
    "amount":               "amount",
    "currency":             "currency",
    "tariff_code":          "tariff_code",
}

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

        # Validate that the required columns are present before processing
        # any rows, so we fail fast with a clear message.
        incoming = {h.strip() for h in reader.fieldnames}
        required = {"meter_id", "billing_period_start",
                    "billing_period_end", "consumption_kwh"}
        missing = required - incoming
        if missing:
            raise ValueError(
                f"Missing required columns: {', '.join(sorted(missing))}. "
                f"Found: {', '.join(sorted(incoming))}"
            )

        for raw_row in reader:
            # Strip whitespace from keys and values
            cleaned = {k.strip(): v.strip() for k, v in raw_row.items()
                       if k is not None}
            # Translate to internal keys; unknown columns kept as-is
            yield {
                HEADER_MAP.get(k, k): v for k, v in cleaned.items()
            }

    # ------------------------------------------------------------------ #

    def _validate_raw(self, raw: dict) -> list:
        """
        Pre-save validation. Returns warning strings.
        Called by BaseParser before creating the RawRow.
        """
        warnings = []

        # Required fields
        for field in ("meter_id", "period_start", "period_end",
                      "consumption_kwh"):
            if not raw.get(field):
                warnings.append(
                    f"missing_required_field: '{field}' is blank"
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

        # ── Parse consumption ─────────────────────────────────────────
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

        # ── Parse dates ───────────────────────────────────────────────
        period_start = parse_flexible_date(raw.get("period_start", ""))
        period_end   = parse_flexible_date(raw.get("period_end", ""))

        if period_start is None:
            raw_row.parse_status = RawRow.ParseStatus.FAILED
            raw_row.parse_errors = raw_row.parse_errors + [
                f"invalid_date: billing_period_start "
                f"'{raw.get('period_start')}' could not be parsed"
            ]
            raw_row.save(update_fields=["parse_status", "parse_errors"])
            return None

        if period_end is None:
            raw_row.parse_status = RawRow.ParseStatus.FAILED
            raw_row.parse_errors = raw_row.parse_errors + [
                f"invalid_date: billing_period_end "
                f"'{raw.get('period_end')}' could not be parsed"
            ]
            raw_row.save(update_fields=["parse_status", "parse_errors"])
            return None

        # ── Resolve emission factor ───────────────────────────────────
        ef_value, ef_source = _resolve_emission_factor(tenant)

        kg_co2e = kwh * ef_value

        # ── Parse monetary amount ─────────────────────────────────────
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
