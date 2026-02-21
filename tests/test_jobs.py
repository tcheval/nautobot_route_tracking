"""Tests for Route Tracking plugin jobs.

Tests verify the collection logic, Nornir integration (mocked), parsers, and purge job.
"""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from nautobot_route_tracking.jobs._base import _extract_nornir_error
from nautobot_route_tracking.jobs.collect_routes import (
    _collect_routes_task,
    _parse_eos_routes,
    _parse_ios_routes,
)
from nautobot_route_tracking.models import RouteEntry

# =============================================================================
# Parser Tests
# =============================================================================


class TestParseEosRoutes:
    """Tests for _parse_eos_routes (Arista EOS JSON parser)."""

    def test_basic_routes(self):
        """Test parsing basic EOS routes with VRF default."""
        eos_json = json.dumps(
            {
                "vrfs": {
                    "default": {
                        "routes": {
                            "10.0.0.0/24": {
                                "routeType": "eBGP",
                                "preference": 20,
                                "metric": 0,
                                "vias": [{"nexthopAddr": "192.168.1.1", "interface": "Ethernet1"}],
                            },
                            "192.168.0.0/16": {
                                "routeType": "connected",
                                "preference": 0,
                                "metric": 0,
                                "vias": [{"interface": "Loopback0"}],
                            },
                        }
                    }
                }
            }
        )
        routes = _parse_eos_routes(eos_json)

        assert "10.0.0.0/24" in routes
        assert len(routes["10.0.0.0/24"]) == 1
        nh = routes["10.0.0.0/24"][0]
        assert nh["protocol"] == "bgp"
        assert nh["next_hop"] == "192.168.1.1"
        assert nh["outgoing_interface"] == "Ethernet1"
        assert nh["preference"] == 20
        assert nh["routing_table"] == "default"

        # Connected route — no nexthopAddr
        assert "192.168.0.0/16" in routes
        conn = routes["192.168.0.0/16"][0]
        assert conn["protocol"] == "connected"
        assert conn["next_hop"] == ""
        assert conn["outgoing_interface"] == "Loopback0"

    def test_ecmp_vias(self):
        """Test that multiple vias produce multiple nexthop entries (ECMP)."""
        eos_json = json.dumps(
            {
                "vrfs": {
                    "default": {
                        "routes": {
                            "10.1.0.0/24": {
                                "routeType": "eBGP",
                                "preference": 20,
                                "metric": 0,
                                "vias": [
                                    {"nexthopAddr": "10.0.0.1", "interface": "Ethernet1"},
                                    {"nexthopAddr": "10.0.0.2", "interface": "Ethernet2"},
                                ],
                            }
                        }
                    }
                }
            }
        )
        routes = _parse_eos_routes(eos_json)
        assert len(routes["10.1.0.0/24"]) == 2
        next_hops = {nh["next_hop"] for nh in routes["10.1.0.0/24"]}
        assert next_hops == {"10.0.0.1", "10.0.0.2"}

    def test_blackhole_route_no_vias(self):
        """Test that routes with empty vias still produce an entry."""
        eos_json = json.dumps(
            {
                "vrfs": {
                    "default": {
                        "routes": {
                            "10.99.0.0/24": {
                                "routeType": "static",
                                "preference": 1,
                                "metric": 0,
                                "vias": [],
                            }
                        }
                    }
                }
            }
        )
        routes = _parse_eos_routes(eos_json)
        assert "10.99.0.0/24" in routes
        assert len(routes["10.99.0.0/24"]) == 1
        assert routes["10.99.0.0/24"][0]["next_hop"] == ""

    def test_protocol_mapping(self):
        """Test EOS protocol type normalization."""
        test_cases = [
            ("eBGP", "bgp"),
            ("iBGP", "bgp"),
            ("ospfInter", "ospf"),
            ("ospfExt1", "ospf"),
            ("connected", "connected"),
            ("local", "local"),
            ("static", "static"),
            ("aggregate", "static"),
            ("unknownProto", "unknown"),
        ]
        for eos_type, expected_proto in test_cases:
            eos_json = json.dumps(
                {
                    "vrfs": {
                        "default": {
                            "routes": {
                                "10.0.0.0/24": {
                                    "routeType": eos_type,
                                    "preference": 0,
                                    "metric": 0,
                                    "vias": [{"nexthopAddr": "1.2.3.4"}],
                                }
                            }
                        }
                    }
                }
            )
            routes = _parse_eos_routes(eos_json)
            assert routes["10.0.0.0/24"][0]["protocol"] == expected_proto, (
                f"EOS type {eos_type!r} should map to {expected_proto!r}"
            )

    def test_multiple_vrfs(self):
        """Test parsing routes from multiple VRFs."""
        eos_json = json.dumps(
            {
                "vrfs": {
                    "default": {
                        "routes": {
                            "10.0.0.0/24": {
                                "routeType": "static",
                                "preference": 1,
                                "metric": 0,
                                "vias": [{"nexthopAddr": "192.168.1.1"}],
                            }
                        }
                    },
                    "MGMT": {
                        "routes": {
                            "172.16.0.0/16": {
                                "routeType": "connected",
                                "preference": 0,
                                "metric": 0,
                                "vias": [{"interface": "Management1"}],
                            }
                        }
                    },
                }
            }
        )
        routes = _parse_eos_routes(eos_json)
        assert routes["10.0.0.0/24"][0]["routing_table"] == "default"
        assert routes["172.16.0.0/16"][0]["routing_table"] == "MGMT"


class TestParseIosRoutes:
    """Tests for _parse_ios_routes (Cisco IOS TextFSM parser)."""

    # Realistic IOS "show ip route" output snippet
    IOS_ROUTE_OUTPUT = """\
Codes: L - local, C - connected, S - static, R - RIP, M - mobile, B - BGP
       D - EIGRP, EX - EIGRP external, O - OSPF, IA - OSPF inter area
       N1 - OSPF NSSA external type 1, N2 - OSPF NSSA external type 2
       E1 - OSPF external type 1, E2 - OSPF external type 2
       i - IS-IS, su - IS-IS summary, L1 - IS-IS level-1, L2 - IS-IS level-2
       ia - IS-IS inter area, * - candidate default, U - per-user static route
       o - ODR, P - periodic downloaded static route, H - NHRP, l - LISP
       a - application route
       + - replicated route, % - next hop override, p - overrides from PfR

Gateway of last resort is 10.0.0.1 to network 0.0.0.0

      10.0.0.0/8 is variably subnetted, 4 subnets, 2 masks
C        10.0.0.0/24 is directly connected, GigabitEthernet0/0
L        10.0.0.10/32 is directly connected, GigabitEthernet0/0
S        10.1.0.0/24 [1/0] via 10.0.0.1
O        10.2.0.0/24 [110/20] via 10.0.0.2, 00:01:23, GigabitEthernet0/1
B        172.16.0.0/16 [20/0] via 10.0.0.3, 00:05:00
S*    0.0.0.0/0 [1/0] via 10.0.0.1
"""

    def test_basic_parsing(self):
        """Test parsing basic IOS output."""
        routes = _parse_ios_routes(self.IOS_ROUTE_OUTPUT)

        # Should parse several prefixes
        assert len(routes) >= 4

    def test_protocol_codes(self):
        """Test that IOS protocol codes are correctly mapped."""
        routes = _parse_ios_routes(self.IOS_ROUTE_OUTPUT)

        # Check specific protocol mappings
        if "10.0.0.0/24" in routes:
            connected_nh = routes["10.0.0.0/24"][0]
            assert connected_nh["protocol"] == "connected"

        if "10.1.0.0/24" in routes:
            static_nh = routes["10.1.0.0/24"][0]
            assert static_nh["protocol"] == "static"

        if "10.2.0.0/24" in routes:
            ospf_nh = routes["10.2.0.0/24"][0]
            assert ospf_nh["protocol"] == "ospf"

    def test_metric_and_distance(self):
        """Test that metric and distance are parsed."""
        routes = _parse_ios_routes(self.IOS_ROUTE_OUTPUT)

        if "10.2.0.0/24" in routes:
            ospf_nh = routes["10.2.0.0/24"][0]
            assert ospf_nh["preference"] == 110
            assert ospf_nh["metric"] == 20

    def test_empty_output(self):
        """Test that empty output returns empty dict."""
        routes = _parse_ios_routes("")
        assert routes == {}


class TestCollectRoutesTask:
    """Tests for the _collect_routes_task Nornir task dispatcher."""

    def test_unsupported_platform_returns_failed(self):
        """Test that an unsupported platform returns a failed Result."""
        mock_task = MagicMock()
        mock_task.host.platform = "paloalto_panos"

        result = _collect_routes_task(mock_task)

        assert result.failed is True
        assert "Unsupported platform" in result.result
        assert "paloalto_panos" in result.result

    def test_empty_platform_returns_failed(self):
        """Test that an empty platform string returns a failed Result."""
        mock_task = MagicMock()
        mock_task.host.platform = ""

        result = _collect_routes_task(mock_task)

        assert result.failed is True
        assert "Unsupported platform" in result.result


class TestExtractNornirError:
    """Tests for the _extract_nornir_error utility function."""

    def test_extracts_exception_from_result(self):
        """Test that exception is extracted from the first failed result."""
        mock_exc = MagicMock()
        failed_result = MagicMock()
        failed_result.failed = True
        failed_result.exception = ValueError("SSH connection refused")
        failed_result.result = None
        mock_exc.result = [failed_result]

        error = _extract_nornir_error(mock_exc)
        assert "SSH connection refused" in error

    def test_extracts_result_string_when_no_exception(self):
        """Test that result string is used when exception is None."""
        mock_exc = MagicMock()
        failed_result = MagicMock()
        failed_result.failed = True
        failed_result.exception = None
        failed_result.result = "Authentication failed"
        mock_exc.result = [failed_result]

        error = _extract_nornir_error(mock_exc)
        assert "Authentication failed" in error

    def test_falls_back_to_str_exc(self):
        """Test fallback to str(exc) when no result attribute."""
        mock_exc = MagicMock()
        del mock_exc.result  # Remove the result attribute

        mock_exc.__str__ = lambda s: "NornirSubTaskError fallback"
        error = _extract_nornir_error(mock_exc)
        assert "NornirSubTaskError fallback" in error

    def test_skips_successful_results(self):
        """Test that successful results are skipped, failed ones are extracted."""
        mock_exc = MagicMock()
        success_result = MagicMock()
        success_result.failed = False
        success_result.exception = None

        failed_result = MagicMock()
        failed_result.failed = True
        failed_result.exception = RuntimeError("Device unreachable")
        failed_result.result = None

        mock_exc.result = [success_result, failed_result]

        error = _extract_nornir_error(mock_exc)
        assert "Device unreachable" in error


@pytest.mark.django_db
class TestPurgeOldRoutesJob:
    """Tests for PurgeOldRoutesJob."""

    def test_purge_deletes_old_entries(self, device):
        """Test that purge job deletes entries older than retention_days."""
        from nautobot_route_tracking.jobs.purge_old_routes import PurgeOldRoutesJob

        old_time = timezone.now() - timedelta(days=100)
        old_entry = RouteEntry(
            device=device,
            network="10.99.0.0/24",
            prefix_length=24,
            protocol=RouteEntry.Protocol.OSPF,
            next_hop="192.168.1.1",
            last_seen=old_time,
        )
        old_entry.validated_save()
        # Force last_seen to be in the past (auto_now_add workaround)
        RouteEntry.objects.filter(pk=old_entry.pk).update(last_seen=old_time)

        # Also create a fresh entry that should NOT be deleted
        fresh_entry = RouteEntry(
            device=device,
            network="10.88.0.0/24",
            prefix_length=24,
            protocol=RouteEntry.Protocol.OSPF,
            next_hop="192.168.1.2",
            last_seen=timezone.now(),
        )
        fresh_entry.validated_save()

        job = PurgeOldRoutesJob()
        job.logger = MagicMock()
        job.run(retention_days=90, commit=True)

        # Old entry should be deleted
        assert not RouteEntry.objects.filter(pk=old_entry.pk).exists()
        # Fresh entry should remain
        assert RouteEntry.objects.filter(pk=fresh_entry.pk).exists()

    def test_purge_dry_run_does_not_delete(self, device):
        """Test that dry-run does not delete entries."""
        from nautobot_route_tracking.jobs.purge_old_routes import PurgeOldRoutesJob

        old_time = timezone.now() - timedelta(days=100)
        old_entry = RouteEntry(
            device=device,
            network="10.77.0.0/24",
            prefix_length=24,
            protocol=RouteEntry.Protocol.OSPF,
            next_hop="192.168.1.3",
            last_seen=old_time,
        )
        old_entry.validated_save()
        RouteEntry.objects.filter(pk=old_entry.pk).update(last_seen=old_time)

        job = PurgeOldRoutesJob()
        job.logger = MagicMock()
        job.run(retention_days=90, commit=False)

        # Entry should still exist (dry-run)
        assert RouteEntry.objects.filter(pk=old_entry.pk).exists()


@pytest.mark.django_db
class TestCollectRoutesJob:
    """Tests for CollectRoutesJob (Nornir mocked)."""

    def test_no_devices_exits_early(self, device_with_platform):
        """Test that job exits early when no devices match filters."""
        from nautobot_route_tracking.jobs.collect_routes import CollectRoutesJob

        job = CollectRoutesJob()
        job.logger = MagicMock()

        # Call run() with no matching device (nonexistent PK)
        result = job.run(
            device=None,
            dynamic_group=None,
            device_role=None,
            location=None,
            tag=None,
            workers=5,
            timeout=10,
            commit=False,
            debug_mode=False,
        )

        # No supported-platform devices → returns early with "No devices matched"
        assert result["success"] is False
        assert result["devices_total"] == 0

    @patch("nautobot_route_tracking.jobs._base.InitNornir")
    def test_db_write_skipped_on_dry_run(self, mock_init_nornir, device_with_platform):
        """Test that DB writes are skipped when commit=False (dry-run)."""
        from nautobot_route_tracking.jobs.collect_routes import CollectRoutesJob

        # Setup mock Nornir with a mock result containing routes
        mock_nr = MagicMock()
        mock_init_nornir.return_value = mock_nr
        mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}

        # Build a fake Nornir result
        mock_host_result = MagicMock()
        mock_host_result.failed = False
        mock_task_result = MagicMock()
        mock_task_result.result = {
            "10.0.0.0/24": [
                {
                    "protocol": "ospf",
                    "next_hop": "192.168.1.1",
                    "outgoing_interface": "",
                    "preference": 110,
                    "metric": 10,
                    "current_active": True,
                    "routing_table": "default",
                }
            ]
        }
        mock_host_result.__getitem__ = lambda self, idx: mock_task_result
        mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

        initial_count = RouteEntry.objects.count()

        job = CollectRoutesJob()
        job.logger = MagicMock()
        result = job.run(
            device=device_with_platform,
            dynamic_group=None,
            device_role=None,
            location=None,
            tag=None,
            workers=5,
            timeout=10,
            commit=False,
            debug_mode=False,
        )

        # Dry-run: no new entries should be created
        assert RouteEntry.objects.count() == initial_count
        assert result["routes_dryrun"] >= 1

    def test_route_processing_normalizes_protocol(self, device):
        """Test that protocol is normalized to lowercase when processing results."""
        # Direct model-level test of the normalization behavior
        entry, created = RouteEntry.update_or_create_entry(
            device=device,
            network="10.50.0.0/24",
            protocol="OSPF",  # Uppercase — as EOS returns it
            next_hop="192.168.0.1",
        )
        assert created is True
        assert entry.protocol == "ospf"

    def test_excluded_routes_not_stored(self, device):
        """Test that excluded route prefixes are rejected by is_excluded_route."""
        from nautobot_route_tracking.models import is_excluded_route

        assert is_excluded_route("169.254.0.0/16") is True
        assert is_excluded_route("127.0.0.1/32") is True
        assert is_excluded_route("224.0.0.1/32") is True

    def test_ecmp_routes_produce_separate_entries(self, device):
        """Test that ECMP routes (same prefix, different next_hop) produce separate DB rows."""
        RouteEntry.update_or_create_entry(
            device=device,
            network="10.60.0.0/24",
            protocol="bgp",
            next_hop="10.0.0.1",
        )
        RouteEntry.update_or_create_entry(
            device=device,
            network="10.60.0.0/24",
            protocol="bgp",
            next_hop="10.0.0.2",
        )

        entries = RouteEntry.objects.filter(device=device, network="10.60.0.0/24")
        assert entries.count() == 2

    @patch("nautobot_route_tracking.jobs._base.InitNornir")
    def test_collect_routes_end_to_end(self, mock_init_nornir, device_with_platform):
        """End-to-end test: run() with mocked Nornir creates RouteEntry records."""
        from nautobot_route_tracking.jobs.collect_routes import CollectRoutesJob

        # Setup mock Nornir
        mock_nr = MagicMock()
        mock_init_nornir.return_value = mock_nr
        mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}

        # Build fake routes data (as returned by _collect_routes_task)
        routes_data = {
            "10.1.0.0/24": [
                {
                    "protocol": "ospf",
                    "next_hop": "192.168.1.1",
                    "outgoing_interface": "",
                    "preference": 110,
                    "metric": 20,
                    "current_active": True,
                    "routing_table": "default",
                }
            ],
            "10.2.0.0/24": [
                {
                    "protocol": "bgp",
                    "next_hop": "10.0.0.1",
                    "outgoing_interface": "",
                    "preference": 20,
                    "metric": 0,
                    "current_active": True,
                    "routing_table": "default",
                },
                {
                    "protocol": "bgp",
                    "next_hop": "10.0.0.2",
                    "outgoing_interface": "",
                    "preference": 20,
                    "metric": 0,
                    "current_active": True,
                    "routing_table": "default",
                },
            ],
            "0.0.0.0/0": [
                {
                    "protocol": "static",
                    "next_hop": "10.0.0.254",
                    "outgoing_interface": "",
                    "preference": 1,
                    "metric": 0,
                    "current_active": True,
                    "routing_table": "default",
                }
            ],
        }

        mock_host_result = MagicMock()
        mock_host_result.failed = False
        mock_task_result = MagicMock()
        mock_task_result.result = routes_data
        mock_host_result.__getitem__ = lambda self, idx: mock_task_result
        mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

        initial_count = RouteEntry.objects.count()

        job = CollectRoutesJob()
        job.logger = MagicMock()
        result = job.run(
            device=device_with_platform,
            dynamic_group=None,
            device_role=None,
            location=None,
            tag=None,
            workers=5,
            timeout=10,
            commit=True,
            debug_mode=False,
        )

        # Verify DB writes: 1 OSPF + 2 BGP ECMP + 1 static = 4 new entries
        assert RouteEntry.objects.count() == initial_count + 4
        assert result["devices_success"] == 1
        assert result["devices_failed"] == 0
        assert result["routes_created"] == 4

        # Verify ECMP: two BGP entries for 10.2.0.0/24
        bgp_entries = RouteEntry.objects.filter(device=device_with_platform, network="10.2.0.0/24", protocol="bgp")
        assert bgp_entries.count() == 2
        next_hops = set(bgp_entries.values_list("next_hop", flat=True))
        assert next_hops == {"10.0.0.1", "10.0.0.2"}

        # Verify OSPF entry
        ospf = RouteEntry.objects.get(device=device_with_platform, network="10.1.0.0/24", protocol="ospf")
        assert ospf.admin_distance == 110
        assert ospf.metric == 20
        assert ospf.is_active is True

    @patch("nautobot_route_tracking.jobs._base.InitNornir")
    def test_collect_routes_updates_existing(self, mock_init_nornir, device_with_platform):
        """Test that a second run UPDATEs (not INSERTs) existing routes."""
        from nautobot_route_tracking.jobs.collect_routes import CollectRoutesJob

        mock_nr = MagicMock()
        mock_init_nornir.return_value = mock_nr
        mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}

        routes_data = {
            "10.70.0.0/24": [
                {
                    "protocol": "ospf",
                    "next_hop": "192.168.1.1",
                    "outgoing_interface": "",
                    "preference": 110,
                    "metric": 10,
                    "current_active": True,
                    "routing_table": "default",
                }
            ],
        }

        mock_host_result = MagicMock()
        mock_host_result.failed = False
        mock_task_result = MagicMock()
        mock_task_result.result = routes_data
        mock_host_result.__getitem__ = lambda self, idx: mock_task_result
        mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

        job = CollectRoutesJob()
        job.logger = MagicMock()

        # First run — creates the route
        result1 = job.run(
            device=device_with_platform,
            dynamic_group=None,
            device_role=None,
            location=None,
            tag=None,
            workers=5,
            timeout=10,
            commit=True,
            debug_mode=False,
        )
        assert result1["routes_created"] == 1
        assert result1["routes_updated"] == 0
        entry_after_first = RouteEntry.objects.get(device=device_with_platform, network="10.70.0.0/24")
        first_run_last_seen = entry_after_first.last_seen

        # Second run — updates (same identity, metric changes)
        routes_data["10.70.0.0/24"][0]["metric"] = 30
        result2 = job.run(
            device=device_with_platform,
            dynamic_group=None,
            device_role=None,
            location=None,
            tag=None,
            workers=5,
            timeout=10,
            commit=True,
            debug_mode=False,
        )
        assert result2["routes_created"] == 0
        assert result2["routes_updated"] == 1

        # Same PK, updated metric and last_seen
        entry_after_second = RouteEntry.objects.get(device=device_with_platform, network="10.70.0.0/24")
        assert entry_after_second.pk == entry_after_first.pk
        assert entry_after_second.metric == 30
        assert entry_after_second.last_seen >= first_run_last_seen

    @patch("nautobot_route_tracking.jobs._base.InitNornir")
    def test_collect_routes_excludes_multicast(self, mock_init_nornir, device_with_platform):
        """Test that excluded prefixes (multicast, link-local) are skipped."""
        from nautobot_route_tracking.jobs.collect_routes import CollectRoutesJob

        mock_nr = MagicMock()
        mock_init_nornir.return_value = mock_nr
        mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}

        routes_data = {
            "10.80.0.0/24": [
                {
                    "protocol": "ospf",
                    "next_hop": "192.168.1.1",
                    "outgoing_interface": "",
                    "preference": 110,
                    "metric": 10,
                    "current_active": True,
                    "routing_table": "default",
                }
            ],
            "224.0.0.0/4": [
                {
                    "protocol": "connected",
                    "next_hop": "",
                    "outgoing_interface": "",
                    "preference": 0,
                    "metric": 0,
                    "current_active": True,
                    "routing_table": "default",
                }
            ],
            "169.254.0.0/16": [
                {
                    "protocol": "connected",
                    "next_hop": "",
                    "outgoing_interface": "",
                    "preference": 0,
                    "metric": 0,
                    "current_active": True,
                    "routing_table": "default",
                }
            ],
        }

        mock_host_result = MagicMock()
        mock_host_result.failed = False
        mock_task_result = MagicMock()
        mock_task_result.result = routes_data
        mock_host_result.__getitem__ = lambda self, idx: mock_task_result
        mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

        job = CollectRoutesJob()
        job.logger = MagicMock()
        result = job.run(
            device=device_with_platform,
            dynamic_group=None,
            device_role=None,
            location=None,
            tag=None,
            workers=5,
            timeout=10,
            commit=True,
            debug_mode=False,
        )

        # Only 10.80.0.0/24 should be created — multicast and link-local excluded
        assert result["routes_created"] == 1
        assert result["routes_excluded"] == 2
        assert RouteEntry.objects.filter(device=device_with_platform, network="10.80.0.0/24").exists()
        assert not RouteEntry.objects.filter(device=device_with_platform, network="224.0.0.0/4").exists()

    @patch("nautobot_route_tracking.jobs._base.InitNornir")
    def test_collect_routes_device_failure_graceful(self, mock_init_nornir, device_with_platform):
        """Test that a failed device does not crash the job."""
        from nautobot_route_tracking.jobs.collect_routes import CollectRoutesJob

        mock_nr = MagicMock()
        mock_init_nornir.return_value = mock_nr
        mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}

        # Simulate a failed host result
        mock_host_result = MagicMock()
        mock_host_result.failed = True
        mock_task_result = MagicMock()
        mock_task_result.result = "Connection refused"
        mock_host_result.__getitem__ = lambda self, idx: mock_task_result
        mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

        job = CollectRoutesJob()
        job.logger = MagicMock()

        # Should raise RuntimeError because all devices failed
        with pytest.raises(RuntimeError):
            job.run(
                device=device_with_platform,
                dynamic_group=None,
                device_role=None,
                location=None,
                tag=None,
                workers=5,
                timeout=10,
                commit=True,
                debug_mode=False,
            )
