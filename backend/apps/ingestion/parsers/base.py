"""
BaseParser
==========
Abstract base class that every source-specific parser inherits from.

Concrete parsers must implement:
    _iter_rows(file_obj) -> Iterator[dict]
        Yield one dict per row from the raw file.

    _normalize_row(raw_row, run) -> NormalizedActivity | None
        Convert a raw dict to a NormalizedActivity instance.
        Return None to skip a row (counts as failed).

The base class handles:
    - Wrapping each row in a try/except so one bad row can't abort the run
    - Creating RawRow records
    - Calling _normalize_row and saving NormalizedActivity
    - Accumulating counts
    - Logging parse errors onto the RawRow
"""

import logging
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from django.db import transaction

from apps.ingestion.models import IngestionRun, RawRow
from apps.normalization.models import NormalizedActivity
from apps.audit.models import AuditLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Flexible date parser — shared by all parsers
# ---------------------------------------------------------------------------

# strptime format strings ordered from most specific to least.
# We try each one until one succeeds.
_DATE_FORMATS = [
    # ISO 8601
    "%Y-%m-%dT%H:%M:%S",       # 2024-01-03T14:30:00
    "%Y-%m-%dT%H:%M",          # 2024-01-03T14:30
    "%Y-%m-%d",                 # 2024-01-03
    "%Y/%m/%d",                 # 2024/01/03

    # German / European  (day first)
    "%d.%m.%Y",                 # 03.01.2024
    "%d-%m-%Y",                 # 03-01-2024
    "%d/%m/%Y",                 # 03/01/2024

    # US  (month first)
    "%m/%d/%Y",                 # 01/03/2024
    "%m-%d-%Y",                 # 01-03-2024

    # With 2-digit year
    "%d.%m.%y",                 # 03.01.24
    "%d-%m-%y",                 # 03-01-24
    "%d/%m/%y",                 # 03/01/24
    "%m/%d/%y",                 # 01/03/24
    "%Y%m%d",                   # 20240103  (compact ISO)

    # Long month names
    "%d %B %Y",                 # 03 January 2024
    "%d %b %Y",                 # 03 Jan 2024
    "%B %d, %Y",                # January 03, 2024
    "%b %d, %Y",                # Jan 03, 2024
    "%d-%b-%Y",                 # 03-Jan-2024
    "%d-%B-%Y",                 # 03-January-2024
]

# Pre-compiled regex to strip ordinal suffixes (1st, 2nd, 3rd, 4th …)
_ORDINAL_RE = re.compile(r'(\d+)(st|nd|rd|th)\b', re.IGNORECASE)


def parse_flexible_date(date_str: str):
    """
    Attempt to parse a date string using many common formats.

    Returns a ``datetime.date`` on success, or ``None`` if no format
    matched.  Never raises — callers should treat ``None`` as a
    parse failure and handle it accordingly.

    Supported families:
        ISO:     2024-01-03, 2024/01/03, 20240103
        German:  03.01.2024, 03-01-2024
        EU:      03/01/2024  (day/month/year)
        US:      01/03/2024  (month/day/year — tried after EU)
        Long:    03 January 2024, Jan 03, 2024, 03-Jan-2024
        Short:   03.01.24, 01/03/24
        ISO+T:   2024-01-03T14:30:00

    Ambiguity note (DD/MM vs MM/DD):
        When a date like ``03/01/2024`` is encountered, we try
        DD/MM/YYYY *first* (European convention), then MM/DD/YYYY.
        Both will succeed only when day ≤ 12. The European reading
        wins in that edge case — which matches the SAP / German
        origin of most BreatheESG uploads.
    """
    if not date_str or not date_str.strip():
        return None

    s = date_str.strip()

    # Remove ordinal suffixes so "3rd January 2024" becomes "3 January 2024"
    s = _ORDINAL_RE.sub(r'\1', s)

    # Strip ISO 8601 timezone suffixes: Z, +00:00, -05:30, etc.
    # "2026-05-10T09:30:00Z" → "2026-05-10T09:30:00"
    # "2026-05-10T09:30:00+05:30" → "2026-05-10T09:30:00"
    s = re.sub(r'[Zz]$', '', s)
    s = re.sub(r'[+\-]\d{2}:\d{2}$', '', s)

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            # Sanity: reject dates outside a reasonable range
            if 1900 <= dt.year <= 2100:
                return dt.date()
        except ValueError:
            continue

    return None


class BaseParser(ABC):

    def parse(self, run: IngestionRun, file_obj) -> dict:
        """
        Entry point called by the dispatch layer.
        Returns {"success": int, "failed": int, "flagged": int}.
        """
        success = failed = flagged = 0

        for row_number, raw_data in enumerate(self._iter_rows(file_obj), start=1):
            try:
                with transaction.atomic():
                    raw_row, activity = self._process_row(run, row_number, raw_data)

                if activity is None:
                    failed += 1
                else:
                    success += 1
                    if activity.is_flagged_suspicious:
                        flagged += 1

            except Exception as exc:
                failed += 1
                logger.warning(
                    "Row %d failed in run %s: %s", row_number, run.id, exc
                )
                # Still save the raw row so analysts can see what failed
                try:
                    RawRow.objects.get_or_create(
                        ingestion_run=run,
                        row_number=row_number,
                        defaults={
                            "tenant":       run.tenant,
                            "raw_data":     raw_data if isinstance(raw_data, dict) else {},
                            "parse_status": RawRow.ParseStatus.FAILED,
                            "parse_errors": [f"{type(exc).__name__}: {exc}"],
                        },
                    )
                except Exception:
                    pass  # Don't let error-recording break the loop

        return {"success": success, "failed": failed, "flagged": flagged}

    def _process_row(self, run, row_number, raw_data):
        """
        Wraps one row: save RawRow → normalize → save NormalizedActivity.
        Called inside an atomic savepoint so a failed row rolls back cleanly.
        """
        errors    = []
        is_warning = False

        # Let the subclass validate/flag before saving
        parse_errors = self._validate_raw(raw_data)
        if parse_errors:
            errors.extend(parse_errors)
            is_warning = True

        raw_row = RawRow.objects.create(
            tenant        = run.tenant,
            ingestion_run = run,
            row_number    = row_number,
            raw_data      = raw_data,
            parse_status  = (RawRow.ParseStatus.WARNING
                             if is_warning else RawRow.ParseStatus.OK),
            parse_errors  = errors,
        )

        activity = self._normalize_row(raw_row, run)

        if activity is not None:
            activity.save()
            AuditLog.objects.create(
                tenant       = run.tenant,
                actor        = None,   # system action
                action       = AuditLog.Action.ACTIVITY_CREATED,
                target_type  = "normalized_activity",
                target_id    = activity.id,
                detail       = f"Created from run {run.id}, row {row_number}.",
            )

        return raw_row, activity

    # ------------------------------------------------------------------ #
    # Interface for subclasses
    # ------------------------------------------------------------------ #

    @abstractmethod
    def _iter_rows(self, file_obj):
        """Yield one dict per row from the raw file."""

    @abstractmethod
    def _normalize_row(self, raw_row: RawRow, run: IngestionRun):
        """Return a NormalizedActivity (unsaved) or None to skip."""

    def _validate_raw(self, raw_data: dict) -> list:
        """
        Return a list of warning strings for this row.
        Override in subclasses to add source-specific checks.
        Empty list = no warnings.
        """
        return []