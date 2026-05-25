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
from abc import ABC, abstractmethod
from django.db import transaction

from apps.ingestion.models import IngestionRun, RawRow
from apps.normalization.models import NormalizedActivity
from apps.audit.models import AuditLog

logger = logging.getLogger(__name__)


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