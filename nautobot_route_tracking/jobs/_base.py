"""Shared base classes and utilities for Route Tracking collection jobs.

This module provides common infrastructure used by CollectRoutesJob:
- NautobotORMInventory registration (once at import time)
- BaseCollectionJob: device filtering, Nornir initialization
- _extract_nornir_error(): safe extraction of root cause from NornirSubTaskError

References:
- Nautobot Jobs: https://docs.nautobot.com/projects/core/en/stable/development/jobs/
- Nautobot Plugin Nornir: https://docs.nautobot.com/projects/plugin-nornir/en/latest/
- Nornir: https://nornir.readthedocs.io/

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nautobot.apps.jobs import (
    BooleanVar,
    IntegerVar,
    Job,
    MultiObjectVar,
    ObjectVar,
)
from nautobot.dcim.models import Device, Location
from nautobot.extras.models import DynamicGroup, Role, Status, Tag
from nornir import InitNornir
from nornir.core.exceptions import NornirSubTaskError
from nornir.core.plugins.inventory import InventoryPluginRegister

from nautobot_route_tracking.models import SUPPORTED_PLATFORMS

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from nornir.core import Nornir


# ---------------------------------------------------------------------------
# Register the Nautobot ORM inventory plugin (once at import time)
# See: https://docs.nautobot.com/projects/plugin-nornir/en/latest/user/app_feature_inventory/
# ---------------------------------------------------------------------------

try:
    from nautobot_plugin_nornir.plugins.inventory.nautobot_orm import (
        NautobotORMInventory,
    )

    if "nautobot-inventory" not in InventoryPluginRegister.available:
        InventoryPluginRegister.register("nautobot-inventory", NautobotORMInventory)
except ImportError:
    NautobotORMInventory = None


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------


def _extract_nornir_error(exc: NornirSubTaskError) -> str:
    """Extract the root cause message from a NornirSubTaskError.

    NornirSubTaskError.result is a MultiResult (list of Result objects),
    not a single Result. Iterating is required to find the actual failed
    result's exception or error message.

    Args:
        exc: NornirSubTaskError raised by nr.run() or task.run()

    Returns:
        Human-readable error string from the first failed sub-result,
        or str(exc) as fallback.

    """
    if hasattr(exc, "result"):
        for r in exc.result:
            if r.failed:
                if r.exception:
                    return str(r.exception)
                if r.result:
                    return str(r.result)
    return str(exc)


# ---------------------------------------------------------------------------
# Base job class
# ---------------------------------------------------------------------------


class BaseCollectionJob(Job):
    """Abstract base class for Nornir-based route collection jobs.

    Provides shared functionality:
    - Device filtering by DynamicGroup, Role, Location, Tag, or specific device
    - Nornir initialization with Nautobot ORM inventory and NAPALM connection options
    - Common job variables for device targeting and performance tuning

    Subclasses must define their own Meta class and run() method.

    See: https://docs.nautobot.com/projects/core/en/stable/development/jobs/

    """

    class Meta:
        """Job metadata — must be overridden by subclasses."""

        abstract = True

    # ------------------------------------------------------------------
    # Device targeting variables
    # ------------------------------------------------------------------

    dynamic_group = ObjectVar(
        model=DynamicGroup,
        required=False,
        description="Collect from devices in this dynamic group",
        query_params={"content_type": "dcim.device"},
    )

    device = ObjectVar(
        model=Device,
        required=False,
        description="Collect from a single specific device (overrides other filters)",
    )

    device_role = MultiObjectVar(
        model=Role,
        required=False,
        description="Filter by device role",
        query_params={"content_types": "dcim.device"},
    )

    location = MultiObjectVar(
        model=Location,
        required=False,
        description="Filter by location (includes descendants)",
    )

    tag = MultiObjectVar(
        model=Tag,
        required=False,
        description="Filter by tag",
    )

    # ------------------------------------------------------------------
    # Performance variables
    # ------------------------------------------------------------------

    workers = IntegerVar(
        default=50,
        min_value=1,
        max_value=200,
        description="Number of parallel Nornir workers",
    )

    timeout = IntegerVar(
        default=30,
        min_value=5,
        max_value=300,
        description="Per-device SSH timeout in seconds",
    )

    # ------------------------------------------------------------------
    # Execution variables
    # ------------------------------------------------------------------

    commit = BooleanVar(
        default=True,
        description="Commit changes to database (False = dry-run)",
    )

    debug_mode = BooleanVar(
        default=False,
        description="Enable verbose debug logging",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize job with debug mode flag."""
        super().__init__(*args, **kwargs)
        self._debug_mode: bool = False

    # ------------------------------------------------------------------
    # Device filtering
    # ------------------------------------------------------------------

    def get_target_devices(
        self,
        device: Device | None,
        dynamic_group: DynamicGroup | None,
        device_role: list[Role] | None,
        location: list[Location] | None,
        tag: list[Tag] | None,
    ) -> QuerySet[Device]:
        """Return the filtered Device queryset to process.

        Priority: device > dynamic_group > role/location/tag.
        Always restricts to SUPPORTED_PLATFORMS (cisco_ios, arista_eos).

        Args:
            device: Specific device (highest priority — all other filters ignored).
            dynamic_group: DynamicGroup whose members are targeted.
            device_role: List of Role objects to filter by.
            location: List of Location objects; descendants are included automatically.
            tag: List of Tag objects to filter by.

        Returns:
            QuerySet of Device instances with .select_related("platform", "location").

        See: https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/dynamicgroup/

        """
        # Case 1: Single specific device — ignore all other filters
        if device:
            self.logger.info(
                "Targeting specific device: %s",
                device.name,
                extra={"grouping": "filters", "object": device},
            )
            return Device.objects.filter(pk=device.pk).select_related("platform", "location")

        # Base queryset: active devices with a platform and primary IP configured
        # (devices without a primary_ip4 cannot be reached via SSH)
        active_statuses = Status.objects.get_for_model(Device).filter(name__in=["Active", "Staged"])
        queryset = Device.objects.filter(
            status__in=active_statuses,
            platform__isnull=False,
            primary_ip4__isnull=False,
        ).select_related("platform", "location", "role")

        # Case 2: DynamicGroup — filter to its current members
        if dynamic_group:
            self.logger.info(
                "Using DynamicGroup: %s",
                dynamic_group.name,
                extra={"grouping": "filters", "object": dynamic_group},
            )
            member_ids = dynamic_group.members.values_list("pk", flat=True)
            queryset = queryset.filter(pk__in=member_ids)

        # Case 3: Manual filters (can be combined)
        if device_role:
            self.logger.info(
                "Filtering by role(s): %s",
                ", ".join(r.name for r in device_role),
                extra={"grouping": "filters"},
            )
            queryset = queryset.filter(role__in=device_role)

        if location:
            # Include descendant locations so a parent location captures all children
            # See: https://docs.nautobot.com/projects/core/en/stable/user-guide/core-data-models/dcim/location/
            location_ids: list = []
            for loc in location:
                self.logger.info(
                    "Filtering by location: %s (including descendants)",
                    loc.name,
                    extra={"grouping": "filters", "object": loc},
                )
                location_ids.extend(loc.descendants(include_self=True).values_list("pk", flat=True))
            queryset = queryset.filter(location__in=location_ids)

        if tag:
            self.logger.info(
                "Filtering by tag(s): %s",
                ", ".join(t.name for t in tag),
                extra={"grouping": "filters"},
            )
            for t in tag:
                queryset = queryset.filter(tags=t)

        # Restrict to platforms with a supported napalm_cli parser
        # (cisco_ios, arista_eos). PAN-OS has no structured routing table CLI.
        queryset = queryset.filter(platform__network_driver__in=SUPPORTED_PLATFORMS)

        return queryset.distinct()

    # ------------------------------------------------------------------
    # Nornir initialization
    # ------------------------------------------------------------------

    def initialize_nornir(
        self,
        devices: QuerySet[Device],
        workers: int,
        timeout: int,
    ) -> Nornir:
        """Initialize a Nornir instance with Nautobot ORM inventory.

        Uses nautobot-plugin-nornir for efficient ORM-based inventory when
        running inside a Nautobot Job. Also patches each host's NAPALM
        connection options so the correct NAPALM driver (e.g. "eos") is used
        instead of the raw network_driver string (e.g. "arista_eos").

        Args:
            devices: QuerySet of Device instances to include in inventory.
            workers: Number of parallel Nornir threaded workers.
            timeout: Per-device connection/command timeout in seconds.

        Returns:
            Configured Nornir instance ready for nr.run().

        Raises:
            RuntimeError: If nautobot-plugin-nornir is not installed, or if
                Nornir initialization fails for any other reason.

        See: https://docs.nautobot.com/projects/plugin-nornir/en/latest/user/app_feature_inventory/

        """
        if NautobotORMInventory is None:
            raise RuntimeError(
                "nautobot-plugin-nornir is required but not installed. "
                "Install it with: pip install nautobot-plugin-nornir"
            )

        if not devices.exists():
            raise RuntimeError("No devices to process")

        device_count = devices.count()
        self.logger.info(
            "Initializing Nornir for %d device(s) (workers=%d, timeout=%ds)",
            device_count,
            workers,
            timeout,
            extra={"grouping": "nornir"},
        )

        # Pre-build per-device NAPALM driver and napalm_args maps.
        # NautobotORMInventory populates host.platform from Platform.network_driver
        # (e.g. "arista_eos"), but NAPALM needs the napalm_driver value (e.g. "eos").
        # Platform.napalm_args provides optional_args such as {"transport": "ssh"}.
        napalm_driver_map: dict[str, str] = {}
        napalm_args_map: dict[str, dict] = {}
        for dev in devices.select_related("platform"):
            if dev.platform and dev.platform.napalm_driver:
                napalm_driver_map[dev.name] = dev.platform.napalm_driver
            if dev.platform and dev.platform.napalm_args:
                napalm_args_map[dev.name] = dev.platform.napalm_args

        inventory_config = {
            "plugin": "nautobot-inventory",
            "options": {
                "credentials_class": (
                    "nautobot_plugin_nornir.plugins.credentials.nautobot_secrets.CredentialsNautobotSecrets"
                ),
                "queryset": devices,
                "defaults": {
                    "connection_options": {
                        "napalm": {
                            "extras": {
                                "timeout": timeout,
                                "optional_args": {
                                    "transport": "ssh",
                                },
                            }
                        },
                        "netmiko": {
                            "extras": {
                                "timeout": timeout,
                                "session_timeout": timeout,
                                "auth_timeout": timeout,
                                "conn_timeout": timeout,
                            }
                        },
                    }
                },
            },
        }

        try:
            nr = InitNornir(
                runner={
                    "plugin": "threaded",
                    "options": {"num_workers": workers},
                },
                logging={
                    "enabled": True,
                    "level": "DEBUG" if self._debug_mode else "INFO",
                    "to_console": False,
                },
                inventory=inventory_config,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Nornir: {exc}") from exc

        self.logger.info(
            "Nornir initialized with %d host(s)",
            len(nr.inventory.hosts),
            extra={"grouping": "nornir"},
        )

        # Patch NAPALM connection options per host:
        # 1. Set platform to Platform.napalm_driver (e.g. "eos") so NAPALM
        #    selects the correct driver class.
        # 2. Merge Platform.napalm_args into optional_args (host-level extras
        #    from NautobotORMInventory can override the defaults dict, losing
        #    transport/timeout; we re-apply them here to be safe).
        for host_name, host in nr.inventory.hosts.items():
            napalm_driver = napalm_driver_map.get(host_name)
            napalm_opts = host.connection_options.get("napalm")

            if napalm_opts is None and napalm_driver:
                from nornir.core.inventory import ConnectionOptions

                napalm_opts = ConnectionOptions(platform=napalm_driver)
                host.connection_options["napalm"] = napalm_opts

            if napalm_opts is not None:
                if napalm_driver:
                    napalm_opts.platform = napalm_driver

                plat_args = napalm_args_map.get(host_name, {})
                if plat_args:
                    if napalm_opts.extras is None:
                        napalm_opts.extras = {}
                    opt_args = napalm_opts.extras.setdefault("optional_args", {})
                    for key, value in plat_args.items():
                        if key not in opt_args:
                            opt_args[key] = value

        return nr
