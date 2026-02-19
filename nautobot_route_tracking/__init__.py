"""Nautobot Route Tracking Plugin.

This plugin collects and historizes routing table entries from network devices
via NAPALM get_route_to(). It follows the same UPDATE/INSERT logic as
nautobot-netdb-tracking, tracking route changes over time with full history.

Key Features:
- Historical tracking with 90-day retention
- UPDATE last_seen vs INSERT for actual changes (NetDB logic)
- ECMP support (each next-hop is a separate RouteEntry row)
- Multi-vendor support via NAPALM (Cisco IOS/XE, Arista EOS)
- Full Nautobot integration (UI, API, permissions, Device tab)

References:
- Nautobot App Development: https://docs.nautobot.com/projects/core/en/stable/development/apps/
- Network-to-Code Cookiecutter: https://github.com/nautobot/cookiecutter-nautobot-app

"""

from importlib.metadata import metadata

from nautobot.apps import NautobotAppConfig

__version__ = metadata("nautobot-route-tracking")["Version"]


class NautobotRouteTrackingConfig(NautobotAppConfig):
    """Nautobot App Config for Route Tracking.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/nautobot-app-config/
    """

    name = "nautobot_route_tracking"
    verbose_name = "Route Tracking"
    version = __version__
    author = "Thomas"
    author_email = "thomas@networktocode.com"
    description = "Track routing table entries from network devices via NAPALM"
    base_url = "route-tracking"
    required_settings = []
    min_version = "3.0.6"
    max_version = "3.99"
    default_settings = {
        "retention_days": 90,
        "purge_enabled": True,
        "nornir_workers": 50,
        "device_timeout": 30,
    }

    def ready(self) -> None:
        """Hook called when Django app is ready.

        Used to import signals and fix job grouping.
        """
        super().ready()
        from nautobot_route_tracking.signals import register_signals

        register_signals(sender=self.__class__)
        self._fix_job_grouping()

    @staticmethod
    def _fix_job_grouping() -> None:
        """Ensure plugin jobs are grouped under 'Route Tracking'.

        Nautobot's register_jobs() resets grouping to the module path on startup.
        This method runs on every startup via ready() to fix the grouping.

        Uses QuerySet.update() to bypass validated_save() which would overwrite
        the grouping field.
        """
        from django.db import OperationalError, ProgrammingError

        try:
            from nautobot.extras.models import Job

            Job.objects.filter(module_name__startswith="nautobot_route_tracking.jobs").update(grouping="Route Tracking")
        except (OperationalError, ProgrammingError):
            # Tables may not exist yet during initial migration
            pass


config = NautobotRouteTrackingConfig  # pylint: disable=invalid-name
