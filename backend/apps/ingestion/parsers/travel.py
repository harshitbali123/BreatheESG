"""
Corporate travel CSV parser
===========================
Handles Concur / Navan style corporate travel exports.

The parser supports flights, hotels, and ground transport rows and
turns each source row into a NormalizedActivity.

Flexible column mapping (resilient ingestion):
Files from different travel management systems use different column
headers. We use an alias system so that e.g. "transaction_date",
"travel_date", "trip_date" all map to the internal key. Only columns
essential for CO2 calculation cause failure when truly absent.
"""

import csv
import io
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from apps.ingestion.models import IngestionRun, RawRow
from apps.normalization.models import EmissionFactor, NormalizedActivity

from .base import BaseParser, parse_flexible_date
from .iata_distances import distance_km, unknown_airports

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flexible column alias map
# ---------------------------------------------------------------------------
# Each internal key maps to a list of aliases (case-insensitive).
# CRITICAL for CO2 = expense_type (determines which EF to use)
# The travel_date is important but we can default to today if missing.

COLUMN_ALIASES = {
    # --- CRITICAL for CO2 calculation ---
    "expense_type": [
        "expense_type", "travel_type", "trip_type", "type",
        "category", "expense_category", "service_type",
    ],

    # --- Important for CO2 calculation ---
    "travel_date": [
        "travel_date", "transaction_date", "trip_date", "date",
        "departure_date", "start_date",
    ],
    "origin": [
        "origin", "departure_code", "from", "from_code",
        "departure", "origin_code", "dep_code", "from_airport",
    ],
    "destination": [
        "destination", "arrival_code", "to", "to_code",
        "arrival", "dest_code", "arr_code", "to_airport",
    ],
    "distance_km": [
        "distance_km", "distance", "km", "miles", "dist",
    ],
    "nights": [
        "nights", "quantity_nights", "num_nights", "hotel_nights",
        "number_of_nights", "no_of_nights",
    ],
    "cabin_class": [
        "cabin_class", "class", "travel_class", "flight_class",
        "service_class", "booking_class",
    ],

    # --- OPTIONAL (context / reporting) ---
    "trip_id": [
        "trip_id", "report_id", "booking_id", "reservation_id",
        "reference", "ref",
    ],
    "employee_id": [
        "employee_id", "emp_id", "traveler_id", "traveller_id",
        "staff_id", "person_id",
    ],
    "cost_center": [
        "cost_center", "cost_centre", "department", "dept",
        "business_unit", "cc",
    ],
    "amount": [
        "amount", "total_amount", "cost", "total_cost",
        "expense_amount", "charge",
    ],
    "currency": [
        "currency", "currency_code", "ccy",
    ],
    "vendor": [
        "vendor", "supplier", "airline", "hotel_name",
        "provider", "carrier",
    ],
}


def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """
    Given the raw CSV column headers, build a mapping:
        raw_column_name -> internal_key
    """
    mapping = {}
    normalised_fields = {f.strip().lower(): f.strip() for f in fieldnames if f}

    for internal_key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in normalised_fields:
                original_header = normalised_fields[alias.lower()]
                mapping[original_header] = internal_key
                break

    return mapping


# ---------------------------------------------------------------------------
# Expense type mapping — flexible to handle various naming conventions
# ---------------------------------------------------------------------------
EXPENSE_TYPE_MAP = {
    "AIR": NormalizedActivity.ActivityType.FLIGHT,
    "FLIGHT": NormalizedActivity.ActivityType.FLIGHT,
    "HOTEL": NormalizedActivity.ActivityType.HOTEL,
    "CAR": NormalizedActivity.ActivityType.GROUND_TRANSPORT,
    "CAR RENTAL": NormalizedActivity.ActivityType.GROUND_TRANSPORT,
    "GROUND TRANSPORT": NormalizedActivity.ActivityType.GROUND_TRANSPORT,
    "GROUND_TRANSPORT": NormalizedActivity.ActivityType.GROUND_TRANSPORT,
    "TRAIN": NormalizedActivity.ActivityType.GROUND_TRANSPORT,
    "TAXI": NormalizedActivity.ActivityType.GROUND_TRANSPORT,
    "UBER": NormalizedActivity.ActivityType.GROUND_TRANSPORT,
    "BUS": NormalizedActivity.ActivityType.GROUND_TRANSPORT,
}

# Reverse map to get the emission factor key for each expense type
EXPENSE_TYPE_TO_EF_CATEGORY = {
    "AIR": "AIR",
    "FLIGHT": "AIR",
    "HOTEL": "HOTEL",
    "CAR": "CAR",
    "CAR RENTAL": "CAR",
    "GROUND TRANSPORT": "CAR",
    "GROUND_TRANSPORT": "CAR",
    "TRAIN": "TRAIN",
    "TAXI": "CAR",
    "UBER": "CAR",
    "BUS": "CAR",
}

CABIN_CLASS_MAP = {
    "economy": "flight_eco",
    "eco": "flight_eco",
    "coach": "flight_eco",
    "premium": "flight_eco",
    "premium economy": "flight_eco",
    "business": "flight_bus",
    "business class": "flight_bus",
    "first": "flight_first",
    "first class": "flight_first",
}

GROUND_EF_MAP = {
    "CAR": "car",
    "CAR RENTAL": "car",
    "GROUND TRANSPORT": "car",
    "GROUND_TRANSPORT": "car",
    "TAXI": "car",
    "UBER": "car",
    "BUS": "car",
    "TRAIN": "train",
}

UNSUPPORTED_TYPES = {"FERRY", "CRUISE", "BOAT", "SHIP"}
DEFAULT_CABIN_CLASS = "economy"
NIGHTS_PATTERN = re.compile(r"(\d+)\s*night", re.IGNORECASE)


def parse(run: IngestionRun, file_obj) -> dict:
    """Module-level entry point used by the ingestion dispatch layer."""
    return TravelParser().parse(run, file_obj)


class TravelParser(BaseParser):
    def __init__(self):
        self._ef_cache: dict[str, Optional[EmissionFactor]] = {}

    def _iter_rows(self, file_obj):
        raw_bytes = file_obj.read()

        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = raw_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Could not decode the file. Expected UTF-8 or Latin-1.")

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("File appears to be empty - no header row found.")

        # Build flexible column mapping from aliases
        col_map = _build_column_map(reader.fieldnames)
        mapped_internal_keys = set(col_map.values())

        # --- Check ONLY critical columns for CO2 calculation ---
        # expense_type is critical — it determines which emission factor to use
        if "expense_type" not in mapped_internal_keys:
            raise ValueError(
                f"Missing critical column for CO2 calculation: 'expense_type'. "
                f"Expected one of: {', '.join(COLUMN_ALIASES['expense_type'])}. "
                f"Found columns: {', '.join(sorted(h.strip() for h in reader.fieldnames if h))}"
            )

        # Log optional missing columns
        optional_missing = [
            k for k in COLUMN_ALIASES
            if k not in mapped_internal_keys and k != "expense_type"
        ]
        if optional_missing:
            logger.info(
                "Travel parser: optional columns not found (will use defaults): %s",
                ", ".join(optional_missing),
            )

        for raw_row in reader:
            cleaned = {}
            for key, value in raw_row.items():
                if key is None:
                    continue
                cleaned[key.strip()] = _clean_value(value)

            yield {col_map.get(key, key): value for key, value in cleaned.items()}

    def _validate_raw(self, raw: dict) -> list:
        warnings = []
        expense_type = raw.get("expense_type", "").strip().upper()

        if not raw.get("travel_date"):
            warnings.append("missing_field: 'travel_date' is blank — will try to proceed")

        if not expense_type:
            warnings.append("missing_critical_field: 'expense_type' is blank")
            return warnings

        if expense_type in UNSUPPORTED_TYPES:
            warnings.append(
                f"unsupported_expense_type: '{expense_type}' is not handled by this parser"
            )

        if expense_type not in EXPENSE_TYPE_MAP and expense_type not in UNSUPPORTED_TYPES:
            warnings.append(
                f"unknown_expense_type: '{expense_type}' — expected AIR, FLIGHT, HOTEL, CAR, TRAIN, TAXI, UBER, BUS, GROUND TRANSPORT"
            )

        if not raw.get("cost_center"):
            warnings.append(
                "missing_cost_centre: 'cost_center' is blank — this row cannot be attributed to a business unit"
            )

        ef_category = EXPENSE_TYPE_TO_EF_CATEGORY.get(expense_type, "")

        if ef_category == "AIR":
            if not raw.get("origin"):
                warnings.append("missing_origin: IATA origin code is blank — distance will be 0")
            if not raw.get("destination"):
                warnings.append("missing_destination: IATA destination code is blank — distance will be 0")

            cabin_raw = raw.get("cabin_class", "").strip().lower()
            if not cabin_raw:
                warnings.append(
                    "missing_cabin_class: defaulting to Economy — verify against booking record"
                )
            elif cabin_raw not in CABIN_CLASS_MAP:
                warnings.append(
                    f"unknown_cabin_class: '{raw.get('cabin_class')}' not recognised — defaulting to Economy"
                )

        if ef_category == "HOTEL":
            nights_str = raw.get("nights", "").strip()
            if not nights_str and _extract_nights_from_vendor(raw.get("vendor", "")) is None:
                warnings.append(
                    "missing_nights: 'nights' field is blank and could not be inferred from vendor name — defaulting to 1 night"
                )

        if ef_category == "CAR" or ef_category == "TRAIN":
            if not raw.get("distance_km", "").strip():
                warnings.append(
                    "missing_distance: 'distance_km' is blank — emission will be recorded as 0 km"
                )

        return warnings

    def _normalize_row(self, raw_row: RawRow, run: IngestionRun):
        raw = raw_row.raw_data
        tenant = run.tenant
        expense_type = raw.get("expense_type", "").strip().upper()

        if not expense_type:
            _fail_raw_row(raw_row, "missing_critical_field: 'expense_type' is blank — cannot determine emission factor")
            return None

        if expense_type in UNSUPPORTED_TYPES:
            _fail_raw_row(raw_row, f"unsupported_expense_type: '{expense_type}'")
            return None

        if expense_type not in EXPENSE_TYPE_MAP:
            _fail_raw_row(raw_row, f"unknown_expense_type: '{expense_type}'")
            return None

        # Parse date — important but use fallback if missing
        activity_date = parse_flexible_date(raw.get("travel_date", ""))
        if activity_date is None:
            if raw.get("travel_date"):
                _fail_raw_row(
                    raw_row,
                    f"invalid_date: '{raw.get('travel_date')}' could not be parsed as DD.MM.YYYY or YYYY-MM-DD",
                )
                return None
            else:
                # No date column at all — use today as fallback, flag it
                from datetime import date as date_cls
                activity_date = date_cls.today()
                raw_row.parse_errors = raw_row.parse_errors + [
                    "defaulted_date: 'travel_date' was blank — defaulted to today"
                ]
                raw_row.parse_status = RawRow.ParseStatus.WARNING
                raw_row.save(update_fields=["parse_status", "parse_errors"])

        ef_category = EXPENSE_TYPE_TO_EF_CATEGORY.get(expense_type, "CAR")

        if ef_category == "AIR":
            result = self._handle_air(raw, raw_row)
        elif ef_category == "HOTEL":
            result = self._handle_hotel(raw, raw_row)
        else:
            result = self._handle_ground(raw, raw_row, expense_type)

        if result is None:
            return None

        quantity, unit, ef, extra_flags, description = result
        flag_reasons = _unique_list(list(raw_row.parse_errors) + extra_flags)
        is_suspicious = bool(flag_reasons)

        original_amount = _parse_decimal(raw.get("amount", ""))
        if original_amount is None:
            original_amount = Decimal("0")

        normalized_kg_co2e = quantity * ef.kg_co2e_per_unit

        if flag_reasons:
            raw_row.parse_status = RawRow.ParseStatus.WARNING
            raw_row.parse_errors = flag_reasons
            raw_row.save(update_fields=["parse_status", "parse_errors"])

        return NormalizedActivity(
            tenant=tenant,
            ingestion_run=run,
            raw_row=raw_row,
            activity_type=EXPENSE_TYPE_MAP[expense_type],
            activity_date=activity_date,
            description=description,
            facility_code=raw.get("origin", ""),
            facility_name="",
            country_code="",
            cost_center=raw.get("cost_center", ""),
            vendor=raw.get("vendor", ""),
            scope=NormalizedActivity.Scope.SCOPE_3,
            scope3_category=6,
            original_value=quantity,
            original_unit=unit,
            original_currency=raw.get("currency", ""),
            original_amount=original_amount,
            normalized_kg_co2e=round(normalized_kg_co2e, 6),
            emission_factor_used=ef.kg_co2e_per_unit,
            emission_factor_source=ef.source,
            review_status=NormalizedActivity.ReviewStatus.PENDING,
            is_flagged_suspicious=is_suspicious,
            flag_reasons=flag_reasons,
        )

    def _handle_air(self, raw: dict, raw_row: RawRow):
        origin = raw.get("origin", "").strip().upper()
        destination = raw.get("destination", "").strip().upper()
        extra_flags = []

        dist = distance_km(origin, destination)
        if dist is None:
            for code in unknown_airports(origin, destination):
                extra_flags.append(
                    f"unknown_iata_code: '{code}' not in airport registry"
                )
            dist = Decimal("0")
        else:
            dist = Decimal(str(dist))

        cabin_raw = raw.get("cabin_class", "").strip().lower()
        cabin_key = CABIN_CLASS_MAP.get(cabin_raw)
        if cabin_key is None:
            cabin_key = "flight_eco"
            if cabin_raw:
                extra_flags.append(
                    f"unrecognised_cabin_class: '{raw.get('cabin_class')}' defaulted to Economy"
                )
            else:
                extra_flags.append("missing_cabin_class: defaulted to Economy")

        ef = self._get_ef(cabin_key)
        if ef is None:
            _fail_raw_row(raw_row, f"missing_emission_factor: no factor for '{cabin_key}'")
            return None

        cabin_display = {
            "flight_eco": "Economy",
            "flight_bus": "Business",
            "flight_first": "First",
        }.get(cabin_key, cabin_key)

        description = f"Flight {origin}->{destination} ({cabin_display}) | {dist:.0f} km"
        return dist, "km", ef, extra_flags, description

    def _handle_hotel(self, raw: dict, raw_row: RawRow):
        extra_flags = []

        nights = _parse_integer(raw.get("nights", ""))
        if nights is None:
            nights = _extract_nights_from_vendor(raw.get("vendor", ""))
        if nights is None:
            nights = 1
            extra_flags.append(
                "defaulted_nights: 'nights' field blank and could not be inferred from vendor name — defaulted to 1 night"
            )
        if nights <= 0:
            extra_flags.append(f"invalid_nights: {nights} is not a valid night count")
            nights = 1

        ef = self._get_ef("hotel")
        if ef is None:
            _fail_raw_row(raw_row, "missing_emission_factor: no factor for 'hotel'")
            return None

        city = raw.get("origin") or raw.get("destination") or ""
        vendor = raw.get("vendor", "")
        description = f"Hotel: {vendor or city} | {nights} night{'s' if nights != 1 else ''}"

        return Decimal(str(nights)), "night", ef, extra_flags, description

    def _handle_ground(self, raw: dict, raw_row: RawRow, expense_type: str):
        extra_flags = []
        ef_key = GROUND_EF_MAP.get(expense_type, "car")

        dist = _parse_decimal(raw.get("distance_km", ""))
        if dist is None:
            extra_flags.append(
                f"missing_distance: 'distance_km' is blank for {expense_type} row — emission recorded as 0 km"
            )
            dist = Decimal("0")

        ef = self._get_ef(ef_key)
        if ef is None:
            _fail_raw_row(raw_row, f"missing_emission_factor: no factor for '{ef_key}'")
            return None

        origin = raw.get("origin", "")
        dest = raw.get("destination", "")
        route = f"{origin}->{dest}" if origin or dest else "route unknown"
        description = f"{expense_type.title()}: {route} | {dist:.0f} km"

        return dist, "km", ef, extra_flags, description

    def _get_ef(self, fuel_type: str) -> Optional[EmissionFactor]:
        if fuel_type not in self._ef_cache:
            ef = (
                EmissionFactor.objects.filter(fuel_type=fuel_type)
                .order_by("-valid_from_year")
                .first()
            )
            if ef is None and fuel_type == "flight_first":
                ef = (
                    EmissionFactor.objects.filter(fuel_type="flight_bus")
                    .order_by("-valid_from_year")
                    .first()
                )
            self._ef_cache[fuel_type] = ef
        return self._ef_cache[fuel_type]


def _clean_value(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def _fail_raw_row(raw_row: RawRow, message: str) -> None:
    parse_errors = list(raw_row.parse_errors)
    parse_errors.append(message)
    raw_row.parse_status = RawRow.ParseStatus.FAILED
    raw_row.parse_errors = _unique_list(parse_errors)
    raw_row.save(update_fields=["parse_status", "parse_errors"])




def _parse_decimal(value: str) -> Optional[Decimal]:
    if not value or not str(value).strip():
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _parse_integer(value: str) -> Optional[int]:
    if not value or not str(value).strip():
        return None
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return None


def _extract_nights_from_vendor(vendor: str) -> Optional[int]:
    if not vendor:
        return None
    match = NIGHTS_PATTERN.search(vendor)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (ValueError, IndexError):
        return None


def _unique_list(values: list[str]) -> list[str]:
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
