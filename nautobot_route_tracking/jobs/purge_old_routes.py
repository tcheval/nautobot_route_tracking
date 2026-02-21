"""Job for purging old RouteEntry records from the database.

This module implements PurgeOldRoutesJob which removes RouteEntry rows whose
last_seen timestamp is older than the configured retention period.

References:
- Nautobot Jobs: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/jobs/

"""

from __future__ import annotations

import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from nautobot.apps.jobs import BooleanVar, IntegerVar, Job

from nautobot_route_tracking.models import RouteEntry


class PurgeOldRoutesJob(Job):
    """Delete RouteEntry records older than the configured retention period.

    Implements data retention for the route tracking history table.
    Supports dry-run mode (commit=False) so operators can preview how many
    records would be removed before committing the deletion.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/jobs/

    """

    class Meta:
        """Job metadata."""

        name = "Purge Old Route Entries"
        grouping = "Route Tracking"
        description = "Delete route entries older than the configured retention period"
        has_sensitive_variables = False
        approval_required = False
        soft_time_limit = 600  # 10 minutes
        time_limit = 1200  # 20 minutes

    # ------------------------------------------------------------------
    # Job variables
    # ------------------------------------------------------------------

    retention_days = IntegerVar(
        default=90,
        min_value=1,
        max_value=3650,
        description="Delete entries whose last_seen is older than N days",
    )

    commit = BooleanVar(
        default=True,
        description="Commit changes to database (False = dry-run, only count affected rows)",
    )

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        retention_days: int,
        commit: bool,
        **kwargs,
    ) -> dict[str, int]:
        """Execute the purge job.

        Args:
            retention_days: Remove RouteEntry rows whose last_seen is older
                than this many days.
            commit: When False, only count and log — do not delete.
            **kwargs: Absorbs any additional parameters from Nautobot.

        Returns:
            Dict with key "route_entries" containing the count of records
            deleted (or that would be deleted in dry-run mode).

        """
        job_start = time.monotonic()
        cutoff = timezone.now() - timedelta(days=retention_days)

        self.logger.info(
            "Purging route entries older than %d day(s) (cutoff: %s)",
            retention_days,
            cutoff.isoformat(),
            extra={"grouping": "parameters"},
        )

        if commit:
            with transaction.atomic():
                deleted, _ = RouteEntry.objects.stale(days=retention_days).delete()
            self.logger.info(
                "Deleted %d route entry(ies)",
                deleted,
                extra={"grouping": "summary"},
            )
            result_count = deleted
        else:
            result_count = RouteEntry.objects.stale(days=retention_days).count()
            self.logger.info(
                "DRY-RUN: would delete %d route entry(ies) — no changes written",
                result_count,
                extra={"grouping": "summary"},
            )

        job_elapsed = time.monotonic() - job_start
        mode = "Purged" if commit else "Would purge (DRY-RUN)"
        self.logger.info(
            "%s %d record(s) in %.1fs",
            mode,
            result_count,
            job_elapsed,
            extra={"grouping": "summary"},
        )

        return {"route_entries": result_count}
