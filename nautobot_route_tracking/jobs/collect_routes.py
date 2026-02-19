"""Job for collecting routing table entries from network devices via NAPALM.

This module implements CollectRoutesJob which uses Nornir for parallel
collection of full routing tables via NAPALM get_route_to().

The job implements the NetDB UPDATE vs INSERT logic:
- UPDATE last_seen if (device, vrf, network, next_hop, protocol) unchanged
- INSERT new record if the combination is new (route changed, new next-hop, etc.)
- ECMP routes produce separate RouteEntry rows (one per next-hop)

References:
- Nautobot Jobs: https://docs.nautobot.com/projects/core/en/stable/development/jobs/
- Nautobot Plugin Nornir: https://docs.nautobot.com/projects/plugin-nornir/en/latest/
- NAPALM get_route_to(): https://napalm.readthedocs.io/en/latest/base.html

"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from django.db import transaction
from nautobot.dcim.models import Device, Interface
from nautobot.extras.models import DynamicGroup, Location, Role, Tag
from nornir.core.exceptions import NornirSubTaskError
from nornir.core.task import Result, Task
from nornir_napalm.plugins.tasks import napalm_get

from nautobot_route_tracking.jobs._base import BaseCollectionJob, _extract_nornir_error
from nautobot_route_tracking.models import RouteEntry, is_excluded_route

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Module-level Nornir task (must be at module level for Nornir serialization)
# ---------------------------------------------------------------------------


def _collect_routes_task(task: Task) -> Result:
    """Collect the full routing table from one host via NAPALM get_route_to().

    Uses empty destination and protocol strings to retrieve all routes across
    all protocols in a single NAPALM call. NAPALM handles multi-protocol
    collection internally per driver.

    Args:
        task: Nornir Task instance for the current host.

    Returns:
        Result whose .result is a dict mapping prefix strings to lists of
        next-hop dicts as returned by NAPALM get_route_to().
        On failure, Result.failed is True and Result.result contains the
        error string.

    See: https://napalm.readthedocs.io/en/latest/base.html#napalm.base.base.NetworkDriver.get_route_to

    """
    try:
        sub_result = task.run(
            task=napalm_get,
            getters=["get_route_to"],
            getters_options={"get_route_to": {"destination": "", "protocol": ""}},
            severity_level=logging.DEBUG,
        )
        routes: dict[str, list[dict[str, Any]]] = sub_result[0].result.get("get_route_to", {})
        return Result(host=task.host, result=routes)

    except NornirSubTaskError as exc:
        root_cause = _extract_nornir_error(exc)
        return Result(host=task.host, failed=True, result=root_cause)

    except Exception as exc:
        return Result(host=task.host, failed=True, result=str(exc))


# ---------------------------------------------------------------------------
# Job class
# ---------------------------------------------------------------------------


class CollectRoutesJob(BaseCollectionJob):
    """Collect routing table entries from network devices using Nornir + NAPALM.

    Connects to all target devices in parallel via NAPALM get_route_to() and
    stores the results as RouteEntry records in Nautobot using the NetDB
    UPDATE vs INSERT logic.

    Features:
    - Parallel collection via Nornir (single nr.run(), no serial loops)
    - NAPALM-only (no Netmiko fallback — get_route_to() is well-supported)
    - ECMP awareness: each next-hop produces a separate RouteEntry row
    - Excluded prefix filtering (multicast, link-local, loopback)
    - Dry-run mode (commit=False) for safe inspection
    - Configurable worker count and per-device timeout
    - Device filtering: specific device, DynamicGroup, role, location, tag

    Supported platforms: cisco_ios, arista_eos
    (PAN-OS excluded: get_route_to raises NotImplementedError)

    See: https://docs.nautobot.com/projects/core/en/stable/development/jobs/

    """

    class Meta:
        """Job metadata."""

        name = "Collect Route Tables"
        grouping = "Route Tracking"
        description = "Collect routing table entries from network devices via NAPALM get_route_to()"
        has_sensitive_variables = False
        field_order = [
            "dynamic_group",
            "device",
            "device_role",
            "location",
            "tag",
            "workers",
            "timeout",
            "commit",
            "debug_mode",
        ]
        approval_required = False
        soft_time_limit = 3600  # 1 hour soft limit
        time_limit = 7200  # 2 hour hard limit

    def run(
        self,
        *,
        device: Device | None,
        dynamic_group: DynamicGroup | None,
        device_role: list[Role] | None,
        location: list[Location] | None,
        tag: list[Tag] | None,
        workers: int,
        timeout: int,
        commit: bool,
        debug_mode: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the route collection job.

        Args:
            device: Optional specific device (highest priority filter).
            dynamic_group: Optional DynamicGroup filter.
            device_role: Optional list of Role filters.
            location: Optional list of Location filters (descendants included).
            tag: Optional list of Tag filters.
            workers: Number of parallel Nornir workers.
            timeout: Per-device SSH timeout in seconds.
            commit: Write results to DB. False = dry-run (logs only).
            debug_mode: Enable verbose per-route debug logging.
            **kwargs: Absorbs any additional parameters from Nautobot.

        Returns:
            Dict with job statistics for JobResult.

        Raises:
            RuntimeError: Only when zero devices succeeded and at least one failed,
                indicating a total collection failure.

        """
        self._debug_mode = debug_mode

        stats: dict[str, int] = {
            "devices_total": 0,
            "devices_success": 0,
            "devices_failed": 0,
            "devices_skipped": 0,
            "routes_updated": 0,
            "routes_created": 0,
            "routes_skipped": 0,
        }

        job_start = time.monotonic()

        self.logger.info(
            "Starting route collection (commit=%s, workers=%d, timeout=%ds, debug=%s)",
            commit,
            workers,
            timeout,
            debug_mode,
            extra={"grouping": "parameters"},
        )

        # ------------------------------------------------------------------
        # 1. Resolve target devices
        # ------------------------------------------------------------------

        devices = self.get_target_devices(
            device=device,
            dynamic_group=dynamic_group,
            device_role=device_role,
            location=location,
            tag=tag,
        )

        device_count = devices.count()
        stats["devices_total"] = device_count

        if device_count == 0:
            self.logger.warning(
                "No devices matched the specified filters",
                extra={"grouping": "summary"},
            )
            return {"success": False, "message": "No devices matched filters", **stats}

        self.logger.info(
            "Found %d device(s) to process",
            device_count,
            extra={"grouping": "summary"},
        )

        # ------------------------------------------------------------------
        # 2. Initialize Nornir
        # ------------------------------------------------------------------

        try:
            nr = self.initialize_nornir(devices=devices, workers=workers, timeout=timeout)
        except RuntimeError as exc:
            self.logger.error(
                "Failed to initialize Nornir: %s",
                exc,
                extra={"grouping": "summary"},
            )
            return {"success": False, "error": str(exc), **stats}

        # ------------------------------------------------------------------
        # 3. Build device_map: name → Device (only hosts present in inventory)
        # ------------------------------------------------------------------

        device_map: dict[str, Device] = {}
        for device_obj in devices:
            if device_obj.name not in nr.inventory.hosts:
                self.logger.warning(
                    "Device not found in Nornir inventory (missing credentials or platform?)",
                    extra={"grouping": device_obj.name, "object": device_obj},
                )
                stats["devices_skipped"] += 1
                continue
            device_map[device_obj.name] = device_obj

        if not device_map:
            self.logger.error(
                "No devices found in Nornir inventory after filtering",
                extra={"grouping": "summary"},
            )
            return {"success": False, "message": "No devices in Nornir inventory", **stats}

        # ------------------------------------------------------------------
        # 4. Parallel collection — single nr.run() across ALL hosts
        # ------------------------------------------------------------------

        self.logger.info(
            "Starting parallel NAPALM collection on %d device(s)",
            len(device_map),
            extra={"grouping": "summary"},
        )

        collection_start = time.monotonic()
        results = nr.run(task=_collect_routes_task, severity_level=logging.DEBUG)
        collection_elapsed = time.monotonic() - collection_start

        self.logger.info(
            "Parallel collection completed in %.1fs",
            collection_elapsed,
            extra={"grouping": "summary"},
        )

        # ------------------------------------------------------------------
        # 5. Sequential DB processing per device
        # ------------------------------------------------------------------

        for device_name, device_obj in device_map.items():
            try:
                # Retrieve aggregated host result from Nornir
                if device_name not in results:
                    self.logger.error(
                        "No result returned from Nornir",
                        extra={"grouping": device_name, "object": device_obj},
                    )
                    stats["devices_failed"] += 1
                    continue

                host_result = results[device_name]

                if host_result.failed:
                    # host_result[0] is the outer task result; its .result holds the error string
                    error_msg = host_result[0].result if host_result else str(host_result)
                    self.logger.error(
                        "Collection failed: %s",
                        error_msg,
                        extra={"grouping": device_name, "object": device_obj},
                    )
                    stats["devices_failed"] += 1
                    continue

                # host_result[0].result is the routes dict from _collect_routes_task
                routes: dict[str, list[dict[str, Any]]] = host_result[0].result

                if not routes:
                    self.logger.warning(
                        "No routes returned (empty routing table or NAPALM returned {})",
                        extra={"grouping": device_name, "object": device_obj},
                    )
                    # Not a failure — device might have an empty table
                    stats["devices_success"] += 1
                    continue

                self.logger.info(
                    "Received %d prefix(es) from NAPALM",
                    len(routes),
                    extra={"grouping": device_name, "object": device_obj},
                )

                # Process routes within a single atomic block per device
                device_updated = 0
                device_created = 0
                device_skipped = 0

                with transaction.atomic():
                    for prefix, nexthops in routes.items():
                        # Exclude unwanted prefixes (multicast, link-local, loopback)
                        if is_excluded_route(prefix):
                            device_skipped += 1
                            if debug_mode:
                                self.logger.debug(
                                    "Skipping excluded prefix: %s",
                                    prefix,
                                    extra={"grouping": device_name},
                                )
                            continue

                        if not isinstance(nexthops, list):
                            # Defensive: NAPALM should always return a list
                            nexthops = [nexthops]

                        for nexthop in nexthops:
                            if not isinstance(nexthop, dict):
                                device_skipped += 1
                                continue

                            # Normalize protocol to lowercase
                            # EOS returns "OSPF", IOS returns "ospf"
                            protocol = nexthop.get("protocol", "unknown").lower() or "unknown"

                            # next_hop: empty string for CONNECTED/LOCAL routes
                            next_hop_raw = nexthop.get("next_hop", "")
                            next_hop: str = next_hop_raw if next_hop_raw else ""

                            # Resolve outgoing_interface FK only when interface name is present
                            iface_name = nexthop.get("outgoing_interface", "") or ""
                            outgoing_interface: Interface | None = None
                            if iface_name:
                                outgoing_interface = Interface.objects.filter(
                                    device=device_obj,
                                    name=iface_name,
                                ).first()
                                if outgoing_interface is None and debug_mode:
                                    self.logger.debug(
                                        "Interface %r not found in Nautobot for device %s",
                                        iface_name,
                                        device_name,
                                        extra={"grouping": device_name},
                                    )

                            # NAPALM "preference" = administrative distance
                            admin_distance: int = int(nexthop.get("preference", 0) or 0)
                            metric: int = int(nexthop.get("metric", 0) or 0)
                            is_active: bool = bool(nexthop.get("current_active", True))

                            # "routing_table" is the raw VRF/table name from NAPALM
                            routing_table: str = nexthop.get("routing_table", "default") or "default"

                            if not commit:
                                # Dry-run: log what would be written, skip DB write
                                device_skipped += 1
                                if debug_mode:
                                    self.logger.debug(
                                        "DRY-RUN: prefix=%s proto=%s nh=%s metric=%d",
                                        prefix,
                                        protocol,
                                        next_hop,
                                        metric,
                                        extra={"grouping": device_name},
                                    )
                                continue

                            _, created = RouteEntry.update_or_create_entry(
                                device=device_obj,
                                network=prefix,
                                protocol=protocol,
                                vrf=None,  # VRF FK not resolved in this version
                                next_hop=next_hop,
                                outgoing_interface=outgoing_interface,
                                metric=metric,
                                admin_distance=admin_distance,
                                is_active=is_active,
                                routing_table=routing_table,
                            )

                            if created:
                                device_created += 1
                            else:
                                device_updated += 1

                if commit:
                    self.logger.info(
                        "Routes: %d created, %d updated, %d skipped",
                        device_created,
                        device_updated,
                        device_skipped,
                        extra={"grouping": device_name, "object": device_obj},
                    )
                else:
                    self.logger.info(
                        "DRY-RUN: Would process %d prefix(es) (%d nexthop entries skipped)",
                        len(routes),
                        device_skipped,
                        extra={"grouping": device_name, "object": device_obj},
                    )

                stats["routes_created"] += device_created
                stats["routes_updated"] += device_updated
                stats["routes_skipped"] += device_skipped
                stats["devices_success"] += 1

            except Exception as exc:
                stats["devices_failed"] += 1
                self.logger.error(
                    "Unexpected error while processing device: %s",
                    exc,
                    extra={"grouping": device_name, "object": device_obj},
                    exc_info=debug_mode,
                )

        # ------------------------------------------------------------------
        # 6. Summary
        # ------------------------------------------------------------------

        job_elapsed = time.monotonic() - job_start
        summary_msg = (
            f"Job completed in {job_elapsed:.1f}s. "
            f"Devices: {stats['devices_success']} success, "
            f"{stats['devices_failed']} failed, "
            f"{stats['devices_skipped']} skipped | "
            f"Routes: {stats['routes_created']} created, "
            f"{stats['routes_updated']} updated, "
            f"{stats['routes_skipped']} skipped"
        )

        self.logger.info(
            "Job completed in %.1fs — devices: %d success / %d failed / %d skipped "
            "| routes: %d created / %d updated / %d skipped",
            job_elapsed,
            stats["devices_success"],
            stats["devices_failed"],
            stats["devices_skipped"],
            stats["routes_created"],
            stats["routes_updated"],
            stats["routes_skipped"],
            extra={"grouping": "summary"},
        )

        # Raise RuntimeError ONLY when every device failed (total failure)
        # Partial failures (some devices down) are not fatal — that is normal
        # in production environments.
        if stats["devices_success"] == 0 and stats["devices_failed"] > 0:
            raise RuntimeError(summary_msg)

        return {
            "success": stats["devices_failed"] == 0,
            "summary": summary_msg,
            **stats,
        }
