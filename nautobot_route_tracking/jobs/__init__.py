"""Route Tracking jobs package.

Registers all jobs with Nautobot's Celery task registry at import time.
Without register_jobs() at module level, jobs won't appear in the Nautobot UI.

References:
- Nautobot Jobs: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/jobs/

"""

from nautobot.core.celery import register_jobs

from .collect_routes import CollectRoutesJob
from .purge_old_routes import PurgeOldRoutesJob

jobs = [CollectRoutesJob, PurgeOldRoutesJob]
register_jobs(*jobs)
