"""Nautobot Route Tracking Plugin.

This plugin collects and historizes routing table entries from network devices
via NAPALM CLI commands (platform-specific: EOS JSON, IOS TextFSM). It follows
the same UPDATE/INSERT logic as nautobot-netdb-tracking, tracking route changes
over time with full history.

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

        Nautobot's ``register_jobs()`` resets grouping to the module path on
        every startup.  This must run in ``ready()`` (not just ``post_migrate``)
        because the grouping is overwritten on every process start, not only
        after migrations.

        The DB query is a single UPDATE (~<1 ms) and is wrapped in try/except
        so it is harmless when the database is unreachable (e.g.
        ``makemigrations`` or ``showmigrations``).

        Uses ``QuerySet.update()`` instead of ``validated_save()`` because the
        latter would overwrite the grouping field right back.
        """
        from django.db import OperationalError, ProgrammingError

        try:
            from nautobot.extras.models import Job

            Job.objects.filter(module_name__startswith="nautobot_route_tracking.jobs").update(grouping="Route Tracking")
        except (OperationalError, ProgrammingError):
            # Tables may not exist yet during initial migration
            pass


# Required by Nautobot 3.0.x plugin loader (looks up module.config)
config = NautobotRouteTrackingConfig
