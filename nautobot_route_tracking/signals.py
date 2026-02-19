"""Django signals for Route Tracking plugin.

This module defines signal handlers for automatic maintenance tasks,
such as enabling and grouping plugin jobs after migrations.

References:
- Django Signals: https://docs.djangoproject.com/en/4.2/topics/signals/
- Nautobot Signals: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/signals/

"""

import logging

from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


def enable_route_tracking_jobs(sender, **kwargs):
    """Enable and group plugin jobs after migrations.

    Nautobot 3.x registers jobs as disabled by default and uses the module
    path as grouping. This handler ensures our jobs are enabled and grouped
    under "Route Tracking" after every migrate.

    Args:
        sender: The AppConfig instance (NautobotRouteTrackingConfig).
        **kwargs: Additional keyword arguments from the post_migrate signal.

    """
    from nautobot.extras.models import Job

    updated = Job.objects.filter(
        module_name__startswith="nautobot_route_tracking.jobs",
        enabled=False,
    ).update(enabled=True, grouping="Route Tracking")

    if updated:
        logger.info("Route Tracking: enabled %d jobs", updated)


def register_signals(sender):
    """Register signal handlers with the app config as sender.

    Called from NautobotRouteTrackingConfig.ready() to scope signals
    to this plugin's migrations only, avoiding duplicate executions.

    Args:
        sender: The AppConfig instance (NautobotRouteTrackingConfig).

    """
    post_migrate.connect(enable_route_tracking_jobs, sender=sender, weak=False)
