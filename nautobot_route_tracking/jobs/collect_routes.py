"""Job for collecting routing table entries from network devices via NAPALM CLI.

This module implements CollectRoutesJob which uses Nornir for parallel
collection of full routing tables using platform-specific NAPALM CLI commands:

- Arista EOS: ``show ip route vrf all | json``  (JSON, parsed directly)
- Cisco IOS:  ``show ip route`` + ``show ip route vrf *``  (text, parsed via TextFSM/ntc-templates)

The job implements the NetDB UPDATE vs INSERT logic:
- UPDATE last_seen if (device, vrf, network, next_hop, protocol) unchanged
- INSERT new record if the combination is new (route changed, new next-hop, etc.)
- ECMP routes produce separate RouteEntry rows (one per next-hop)

References:
- Nautobot Jobs: https://docs.nautobot.com/projects/core/en/stable/development/jobs/
- Nautobot Plugin Nornir: https://docs.nautobot.com/projects/plugin-nornir/en/latest/
- NAPALM CLI: https://napalm.readthedocs.io/en/latest/base.html#napalm.base.base.NetworkDriver.cli

"""

from __future__ import annotations

import io
import json
import logging
import pathlib
import time
from typing import Any

import ntc_templates as _ntc_pkg
import textfsm
from django.core.exceptions import ValidationError
from django.db import transaction
from nautobot.dcim.models import Device, Interface, Location
from nautobot.extras.models import DynamicGroup, Role, Tag
from nautobot.ipam.models import VRF
from nornir.core.exceptions import NornirSubTaskError
from nornir.core.task import Result, Task
from nornir_napalm.plugins.tasks import napalm_cli

from nautobot_route_tracking.jobs._base import BaseCollectionJob, _extract_nornir_error
from nautobot_route_tracking.models import RouteEntry, is_excluded_route

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to the ntc-templates TextFSM template for Cisco IOS routing table.
# Template content is read once at import time to avoid repeated disk I/O
# on every _parse_ios_routes() call.
_NTC_TEMPLATES_DIR = pathlib.Path(_ntc_pkg.__file__).parent / "templates"
_IOS_ROUTE_TEMPLATE = _NTC_TEMPLATES_DIR / "cisco_ios_show_ip_route.textfsm"
_IOS_ROUTE_TEMPLATE_TEXT: str = _IOS_ROUTE_TEMPLATE.read_text()

# Valid protocol values for RouteEntry.Protocol
_VALID_PROTOCOLS: set[str] = {c[0] for c in RouteEntry.Protocol.choices}

# Map EOS routeType values → normalized protocol names matching RouteEntry.Protocol choices.
# EOS returns values like "eBGP", "iBGP", "ospfInter", "ospfExt1", etc.
_EOS_PROTOCOL_MAP: dict[str, str] = {
    "ebgp": "bgp",
    "ibgp": "bgp",
    "bgp": "bgp",
    "ospf": "ospf",
    "ospfinter": "ospf",
    "ospfintra": "ospf",
    "ospfext1": "ospf",
    "ospfext2": "ospf",
    "ospfnssa1": "ospf",
    "ospfnssa2": "ospf",
    "static": "static",
    "connected": "connected",
    "local": "local",
    "isis": "isis",
    "rip": "rip",
    "eigrp": "eigrp",
    "aggregate": "static",
}

# Map IOS single-letter protocol codes → normalized lowercase protocol names
_IOS_PROTOCOL_MAP: dict[str, str] = {
    "C": "connected",
    "L": "local",
    "S": "static",
    "R": "rip",
    "M": "unknown",  # IOS "Mobile" — not a standard Protocol choice
    "B": "bgp",
    "D": "eigrp",
    "EX": "eigrp",
    "O": "ospf",
    "IA": "ospf",
    "N1": "ospf",
    "N2": "ospf",
    "E1": "ospf",
    "E2": "ospf",
    "i": "isis",
    "su": "isis",
    "L1": "isis",
    "L2": "isis",
    "ia": "isis",
}


# ---------------------------------------------------------------------------
# Module-level Nornir tasks (must be at module level for Nornir serialization)
# ---------------------------------------------------------------------------


def _parse_eos_routes(json_text: str) -> dict[str, list[dict[str, Any]]]:
    """Parse Arista EOS ``show ip route | json`` output into normalized nexthop dicts.

    Args:
        json_text: Raw JSON string from EOS ``show ip route | json``.

    Returns:
        Dict mapping prefix strings (e.g. ``"10.0.0.0/8"``) to lists of
        nexthop dicts with keys: protocol, next_hop, outgoing_interface,
        preference, metric, current_active, routing_table.

    """
    data = json.loads(json_text)
    routes: dict[str, list[dict[str, Any]]] = {}

    for vrf_name, vrf_data in data.get("vrfs", {}).items():
        for prefix, route_data in vrf_data.get("routes", {}).items():
            protocol_raw = (route_data.get("routeType") or "unknown").lower()
            protocol = _EOS_PROTOCOL_MAP.get(protocol_raw, protocol_raw)
            if protocol not in _VALID_PROTOCOLS:
                protocol = "unknown"
            preference = int(route_data.get("preference") or 0)
            metric = int(route_data.get("metric") or 0)
            vias = route_data.get("vias") or []

            nexthop_list: list[dict[str, Any]] = []
            for via in vias:
                nexthop_list.append(
                    {
                        "protocol": protocol,
                        "next_hop": via.get("nexthopAddr") or "",
                        "outgoing_interface": via.get("interface") or "",
                        "preference": preference,
                        "metric": metric,
                        "current_active": True,
                        "routing_table": vrf_name,
                    }
                )

            if not nexthop_list:
                # Route with no via entries (e.g. blackhole) — still record it
                nexthop_list.append(
                    {
                        "protocol": protocol,
                        "next_hop": "",
                        "outgoing_interface": "",
                        "preference": preference,
                        "metric": metric,
                        "current_active": True,
                        "routing_table": vrf_name,
                    }
                )

            routes.setdefault(prefix, []).extend(nexthop_list)

    return routes


def _parse_ios_routes(text: str) -> dict[str, list[dict[str, Any]]]:
    """Parse Cisco IOS ``show ip route`` text output into normalized nexthop dicts.

    Uses the ntc-templates TextFSM template for ``cisco_ios_show_ip_route``.

    Args:
        text: Raw text output from ``show ip route``.

    Returns:
        Dict mapping prefix strings (e.g. ``"10.0.0.0/8"``) to lists of
        nexthop dicts with keys: protocol, next_hop, outgoing_interface,
        preference, metric, current_active, routing_table.

    """
    fsm = textfsm.TextFSM(io.StringIO(_IOS_ROUTE_TEMPLATE_TEXT))
    parsed = fsm.ParseTextToDicts(text)

    routes: dict[str, list[dict[str, Any]]] = {}
    for row in parsed:
        network = row.get("NETWORK", "")
        prefix_length = row.get("PREFIX_LENGTH", "")
        if not network or not prefix_length:
            continue

        prefix = f"{network}/{prefix_length}"
        protocol_code = row.get("PROTOCOL", "")
        protocol = _IOS_PROTOCOL_MAP.get(protocol_code, "unknown")
        if protocol not in _VALID_PROTOCOLS:
            protocol = "unknown"

        distance_raw = row.get("DISTANCE", "")
        metric_raw = row.get("METRIC", "")
        vrf = row.get("VRF", "") or "default"

        nexthop: dict[str, Any] = {
            "protocol": protocol,
            "next_hop": row.get("NEXTHOP_IP") or "",
            "outgoing_interface": row.get("NEXTHOP_IF") or "",
            "preference": int(distance_raw) if distance_raw else 0,
            "metric": int(metric_raw) if metric_raw else 0,
            "current_active": True,
            "routing_table": vrf,
        }

        if prefix not in routes:
            routes[prefix] = []
        routes[prefix].append(nexthop)

    return routes


def _collect_routes_task(task: Task) -> Result:
    """Collect the full routing table from one host via platform-specific NAPALM CLI.

    Dispatches to the appropriate platform handler:
    - ``arista_eos``: ``show ip route | json``
    - ``cisco_ios``:  ``show ip route`` (TextFSM parsed)

    Args:
        task: Nornir Task instance for the current host.

    Returns:
        Result whose .result is a dict mapping prefix strings to lists of
        normalized nexthop dicts (keys: protocol, next_hop, outgoing_interface,
        preference, metric, current_active, routing_table).
        On failure, Result.failed is True and Result.result contains the
        error string.

    """
    platform: str = task.host.platform or ""

    try:
        if platform == "arista_eos":
            return _collect_routes_eos(task)
        elif platform == "cisco_ios":
            return _collect_routes_ios(task)
        else:
            return Result(
                host=task.host,
                failed=True,
                result=f"Unsupported platform for route collection: {platform!r}",
            )

    except Exception as exc:
        return Result(host=task.host, failed=True, result=str(exc))


def _collect_routes_eos(task: Task) -> Result:
    """Collect routes from Arista EOS using ``show ip route vrf all | json``."""
    try:
        cmd = "show ip route vrf all | json"
        sub_result = task.run(
            task=napalm_cli,
            commands=[cmd],
            severity_level=logging.DEBUG,
        )
        raw: Any = sub_result[0].result
        if not isinstance(raw, dict):
            return Result(
                host=task.host,
                failed=True,
                result=f"napalm_cli returned unexpected type {type(raw).__name__}: {raw!r}",
            )

        json_text: str = raw.get(cmd, "")
        if not json_text:
            return Result(host=task.host, result={})

        routes = _parse_eos_routes(json_text)
        return Result(host=task.host, result=routes)

    except NornirSubTaskError as exc:
        root_cause = _extract_nornir_error(exc)
        return Result(host=task.host, failed=True, result=root_cause)

    except Exception as exc:
        return Result(host=task.host, failed=True, result=str(exc))


def _collect_routes_ios(task: Task) -> Result:
    """Collect routes from Cisco IOS using ``show ip route`` + ``show ip route vrf *`` + TextFSM."""
    try:
        cmd_global = "show ip route"
        cmd_vrf = "show ip route vrf *"
        sub_result = task.run(
            task=napalm_cli,
            commands=[cmd_global, cmd_vrf],
            severity_level=logging.DEBUG,
        )
        raw: Any = sub_result[0].result
        if not isinstance(raw, dict):
            return Result(
                host=task.host,
                failed=True,
                result=f"napalm_cli returned unexpected type {type(raw).__name__}: {raw!r}",
            )

        routes: dict[str, list[dict[str, Any]]] = {}

        # Parse global routing table
        global_text: str = raw.get(cmd_global, "")
        if global_text:
            routes = _parse_ios_routes(global_text)

        # Parse VRF routing tables (best-effort — empty if no VRFs configured)
        vrf_text: str = raw.get(cmd_vrf, "")
        if vrf_text:
            vrf_routes = _parse_ios_routes(vrf_text)
            for prefix, nexthops in vrf_routes.items():
                routes.setdefault(prefix, []).extend(nexthops)

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

    Connects to all target devices in parallel via platform-specific NAPALM CLI
    commands and stores the results as RouteEntry records in Nautobot using
    the NetDB UPDATE vs INSERT logic.

    Collection strategy per platform:
    - **Arista EOS**: ``show ip route vrf all | json`` — structured JSON, all VRFs
    - **Cisco IOS**: ``show ip route`` + ``show ip route vrf *`` — parsed via TextFSM (ntc-templates), all VRFs

    Features:
    - Parallel collection via Nornir (single nr.run(), no serial loops)
    - NAPALM CLI-only (no direct SSH/Netmiko fallback)
    - ECMP awareness: each next-hop produces a separate RouteEntry row
    - Excluded prefix filtering (multicast, link-local, loopback)
    - Dry-run mode (commit=False) for safe inspection
    - Configurable worker count and per-device timeout
    - Device filtering: specific device, DynamicGroup, role, location, tag

    Supported platforms: cisco_ios, arista_eos
    (PAN-OS excluded: no structured routing table output via SSH CLI)

    See: https://docs.nautobot.com/projects/core/en/stable/development/jobs/

    """

    class Meta:
        """Job metadata."""

        name = "Collect Route Tables"
        grouping = "Route Tracking"
        description = "Collect routing table entries from network devices via NAPALM CLI"
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
            "routes_excluded": 0,
            "routes_dryrun": 0,
            "routes_invalid": 0,
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

        # VRF cache: routing_table name → VRF object (or None for global table)
        vrf_cache: dict[str, VRF | None] = {}

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
                routes_raw: Any = host_result[0].result
                if not isinstance(routes_raw, dict):
                    self.logger.error(
                        "Unexpected routes result type %s: %r",
                        type(routes_raw).__name__,
                        routes_raw,
                        extra={"grouping": device_name, "object": device_obj},
                    )
                    stats["devices_failed"] += 1
                    continue
                routes: dict[str, list[dict[str, Any]]] = routes_raw

                if not routes:
                    self.logger.warning(
                        "No routes returned (empty routing table)",
                        extra={"grouping": device_name, "object": device_obj},
                    )
                    # Not a failure — device might have an empty table
                    stats["devices_success"] += 1
                    continue

                self.logger.info(
                    "Received %d prefix(es)",
                    len(routes),
                    extra={"grouping": device_name, "object": device_obj},
                )

                # Pre-fetch all interfaces for this device (avoid N+1 queries)
                interfaces_by_name: dict[str, Interface] = {
                    i.name: i for i in Interface.objects.filter(device=device_obj)
                }

                device_updated = 0
                device_created = 0
                device_excluded = 0
                device_dryrun = 0
                device_invalid = 0

                # Outer transaction per device: if a truly unexpected error occurs,
                # the entire device batch rolls back cleanly. Inner transaction in
                # update_or_create_entry() becomes a savepoint (lightweight on PG)
                # and is kept for standalone callers that don't wrap in a transaction.
                with transaction.atomic():
                    for prefix, nexthops in routes.items():
                        # Exclude unwanted prefixes (multicast, link-local, loopback)
                        if is_excluded_route(prefix):
                            device_excluded += 1
                            if debug_mode:
                                self.logger.debug(
                                    "Skipping excluded prefix: %s",
                                    prefix,
                                    extra={"grouping": device_name},
                                )
                            continue

                        if not isinstance(nexthops, list):
                            nexthops = [nexthops]

                        for nexthop in nexthops:
                            if not isinstance(nexthop, dict):
                                device_invalid += 1
                                continue

                            protocol = nexthop.get("protocol", "unknown").lower() or "unknown"
                            next_hop: str = nexthop.get("next_hop") or ""

                            # Resolve outgoing_interface FK via pre-fetched cache
                            iface_name = nexthop.get("outgoing_interface") or ""
                            outgoing_interface: Interface | None = None
                            if iface_name:
                                outgoing_interface = interfaces_by_name.get(iface_name)
                                if outgoing_interface is None and debug_mode:
                                    self.logger.debug(
                                        "Interface %r not found in Nautobot for device %s",
                                        iface_name,
                                        device_name,
                                        extra={"grouping": device_name},
                                    )

                            # "preference" = administrative distance
                            admin_distance: int = int(nexthop.get("preference") or 0)
                            metric: int = int(nexthop.get("metric") or 0)
                            is_active: bool = bool(nexthop.get("current_active", True))
                            routing_table: str = nexthop.get("routing_table") or "default"

                            # Resolve VRF FK from routing_table name
                            vrf_obj: VRF | None = None
                            if routing_table not in ("default", "inet.0", ""):
                                if routing_table not in vrf_cache:
                                    vrf_cache[routing_table] = VRF.objects.filter(
                                        name=routing_table,
                                    ).first()
                                vrf_obj = vrf_cache[routing_table]

                            if not commit:
                                device_dryrun += 1
                                if debug_mode:
                                    self.logger.debug(
                                        "DRY-RUN: prefix=%s proto=%s nh=%s metric=%d vrf=%s",
                                        prefix,
                                        protocol,
                                        next_hop,
                                        metric,
                                        routing_table,
                                        extra={"grouping": device_name},
                                    )
                                continue

                            try:
                                _, created = RouteEntry.update_or_create_entry(
                                    device=device_obj,
                                    network=prefix,
                                    protocol=protocol,
                                    vrf=vrf_obj,
                                    next_hop=next_hop,
                                    outgoing_interface=outgoing_interface,
                                    metric=metric,
                                    admin_distance=admin_distance,
                                    is_active=is_active,
                                    routing_table=routing_table,
                                )
                            except (ValueError, ValidationError) as exc:
                                device_invalid += 1
                                if debug_mode:
                                    self.logger.debug(
                                        "Skipping invalid route %s: %s",
                                        prefix,
                                        exc,
                                        extra={"grouping": device_name},
                                    )
                                continue

                            if created:
                                device_created += 1
                            else:
                                device_updated += 1

                if commit:
                    self.logger.info(
                        "Routes: %d created, %d updated, %d excluded, %d invalid",
                        device_created,
                        device_updated,
                        device_excluded,
                        device_invalid,
                        extra={"grouping": device_name, "object": device_obj},
                    )
                else:
                    self.logger.info(
                        "DRY-RUN: %d prefix(es), %d nexthops, %d excluded",
                        len(routes),
                        device_dryrun,
                        device_excluded,
                        extra={"grouping": device_name, "object": device_obj},
                    )

                stats["routes_created"] += device_created
                stats["routes_updated"] += device_updated
                stats["routes_excluded"] += device_excluded
                stats["routes_dryrun"] += device_dryrun
                stats["routes_invalid"] += device_invalid
                stats["devices_success"] += 1

            except Exception as exc:
                stats["devices_failed"] += 1
                self.logger.error(
                    "Unexpected error while processing device: %s",
                    exc,
                    extra={"grouping": device_name, "object": device_obj},
                    exc_info=True,
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
            f"{stats['routes_excluded']} excluded, "
            f"{stats['routes_invalid']} invalid"
            + (f", {stats['routes_dryrun']} dry-run" if stats["routes_dryrun"] else "")
        )

        self.logger.info(
            "Job completed in %.1fs — devices: %d success / %d failed / %d skipped "
            "| routes: %d created / %d updated / %d excluded / %d invalid",
            job_elapsed,
            stats["devices_success"],
            stats["devices_failed"],
            stats["devices_skipped"],
            stats["routes_created"],
            stats["routes_updated"],
            stats["routes_excluded"],
            stats["routes_invalid"],
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
