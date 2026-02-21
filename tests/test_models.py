"""Tests for Route Tracking plugin models.

This module contains unit tests for the plugin's data models.
Tests verify model creation, validation, the NetDB UPDATE/INSERT logic,
ECMP handling, and route exclusion.
"""

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from nautobot_route_tracking.models import RouteEntry, is_excluded_route


class TestIsExcludedRoute:
    """Tests for the is_excluded_route utility function."""

    def test_ipv4_multicast_excluded(self):
        """Test that IPv4 multicast prefixes are excluded."""
        assert is_excluded_route("224.0.0.0/4") is True
        assert is_excluded_route("239.1.2.0/24") is True

    def test_ipv4_link_local_excluded(self):
        """Test that IPv4 link-local prefixes are excluded."""
        assert is_excluded_route("169.254.0.0/16") is True
        assert is_excluded_route("169.254.1.0/24") is True

    def test_ipv4_loopback_excluded(self):
        """Test that IPv4 loopback prefixes are excluded."""
        assert is_excluded_route("127.0.0.0/8") is True
        assert is_excluded_route("127.0.0.1/32") is True

    def test_ipv6_multicast_excluded(self):
        """Test that IPv6 multicast prefixes are excluded."""
        assert is_excluded_route("ff00::/8") is True
        assert is_excluded_route("ff02::1/128") is True

    def test_ipv6_link_local_excluded(self):
        """Test that IPv6 link-local prefixes are excluded."""
        assert is_excluded_route("fe80::/10") is True
        assert is_excluded_route("fe80::1/128") is True

    def test_normal_prefix_not_excluded(self):
        """Test that normal prefixes are not excluded."""
        assert is_excluded_route("10.0.0.0/8") is False
        assert is_excluded_route("192.168.1.0/24") is False
        assert is_excluded_route("172.16.0.0/12") is False
        assert is_excluded_route("0.0.0.0/0") is False
        assert is_excluded_route("2001:db8::/32") is False

    def test_invalid_prefix_not_excluded(self):
        """Test that invalid CIDR strings return False (not crash)."""
        assert is_excluded_route("not-a-prefix") is False
        assert is_excluded_route("999.999.999.999/32") is False


@pytest.mark.django_db
class TestRouteEntry:
    """Tests for RouteEntry model creation and validation."""

    def test_create_basic(self, device):
        """Test creating a basic RouteEntry."""
        entry = RouteEntry(
            device=device,
            network="10.0.0.0/24",
            prefix_length=24,
            protocol=RouteEntry.Protocol.OSPF,
            next_hop="192.168.1.1",
            last_seen=timezone.now(),
        )
        entry.validated_save()

        assert entry.pk is not None
        assert entry.network == "10.0.0.0/24"
        assert entry.prefix_length == 24
        assert entry.protocol == "ospf"
        assert entry.first_seen is not None

    def test_protocol_normalization(self, device):
        """Test that protocol is normalized to lowercase."""
        entry = RouteEntry(
            device=device,
            network="10.0.1.0/24",
            prefix_length=24,
            protocol="OSPF",  # Uppercase — as EOS returns it
            next_hop="192.168.1.1",
            last_seen=timezone.now(),
        )
        entry.validated_save()

        assert entry.protocol == "ospf"

    def test_network_normalization(self, device):
        """Test that network prefix is normalized to canonical CIDR form."""
        entry = RouteEntry(
            device=device,
            network="10.0.0.1/24",  # Host bits set — not canonical
            prefix_length=24,
            protocol=RouteEntry.Protocol.OSPF,
            next_hop="192.168.1.1",
            last_seen=timezone.now(),
        )
        entry.validated_save()

        assert entry.network == "10.0.0.0/24"
        assert entry.prefix_length == 24

    def test_prefix_length_set_from_network(self, device):
        """Test that prefix_length is derived from network on clean()."""
        entry = RouteEntry(
            device=device,
            network="192.168.0.0/16",
            prefix_length=0,  # Wrong — should be fixed by clean()
            protocol=RouteEntry.Protocol.STATIC,
            next_hop="10.0.0.1",
            last_seen=timezone.now(),
        )
        entry.validated_save()

        assert entry.prefix_length == 16

    def test_connected_route_empty_next_hop(self, device):
        """Test that CONNECTED routes can have empty next_hop."""
        entry = RouteEntry(
            device=device,
            network="10.10.0.0/24",
            prefix_length=24,
            protocol=RouteEntry.Protocol.CONNECTED,
            next_hop="",  # Valid for CONNECTED routes
            last_seen=timezone.now(),
        )
        entry.validated_save()

        assert entry.next_hop == ""
        assert entry.pk is not None

    def test_outgoing_interface_wrong_device_raises(self, device, device2, interface):
        """Test that outgoing_interface must belong to device."""
        # interface belongs to device, not device2
        entry = RouteEntry(
            device=device2,
            network="10.0.2.0/24",
            prefix_length=24,
            protocol=RouteEntry.Protocol.CONNECTED,
            next_hop="",
            outgoing_interface=interface,  # interface is on device, not device2
            last_seen=timezone.now(),
        )
        with pytest.raises(ValidationError) as exc_info:
            entry.validated_save()
        assert "outgoing_interface" in str(exc_info.value)

    def test_str_representation(self, route_entry):
        """Test __str__ method."""
        result = str(route_entry)
        assert "10.0.0.0/24" in result
        assert "ospf" in result
        assert route_entry.device.name in result

    def test_vrf_null_means_global_table(self, device):
        """Test that vrf=None represents the global routing table."""
        entry = RouteEntry(
            device=device,
            vrf=None,
            network="10.0.3.0/24",
            prefix_length=24,
            protocol=RouteEntry.Protocol.STATIC,
            next_hop="10.0.0.1",
            last_seen=timezone.now(),
        )
        entry.validated_save()

        assert entry.vrf is None
        assert entry.pk is not None


@pytest.mark.django_db
class TestRouteEntryNetDBLogic:
    """Tests for the NetDB UPDATE vs INSERT logic."""

    def test_update_or_create_creates_new(self, device):
        """Test that a new route combination creates a new record."""
        entry, created = RouteEntry.update_or_create_entry(
            device=device,
            network="10.1.0.0/24",
            protocol="ospf",
            next_hop="192.168.1.1",
            metric=20,
            admin_distance=110,
        )

        assert created is True
        assert entry.pk is not None
        assert entry.protocol == "ospf"
        assert entry.network == "10.1.0.0/24"

    def test_update_or_create_updates_existing(self, device):
        """Test that an existing route combination updates last_seen."""
        entry1, created1 = RouteEntry.update_or_create_entry(
            device=device,
            network="10.2.0.0/24",
            protocol="ospf",
            next_hop="192.168.1.1",
            metric=20,
        )
        assert created1 is True
        original_first_seen = entry1.first_seen

        entry2, created2 = RouteEntry.update_or_create_entry(
            device=device,
            network="10.2.0.0/24",
            protocol="ospf",
            next_hop="192.168.1.1",
            metric=20,
        )
        assert created2 is False
        assert entry1.pk == entry2.pk
        # first_seen must not change
        assert entry2.first_seen == original_first_seen

    def test_ecmp_creates_separate_rows(self, device):
        """Test that ECMP routes (same prefix, different next_hop) create separate rows."""
        entry1, created1 = RouteEntry.update_or_create_entry(
            device=device,
            network="10.3.0.0/24",
            protocol="bgp",
            next_hop="192.168.1.1",
        )
        entry2, created2 = RouteEntry.update_or_create_entry(
            device=device,
            network="10.3.0.0/24",
            protocol="bgp",
            next_hop="192.168.1.2",  # Different next_hop — ECMP
        )

        assert created1 is True
        assert created2 is True
        assert entry1.pk != entry2.pk
        assert RouteEntry.objects.filter(device=device, network="10.3.0.0/24").count() == 2

    def test_protocol_normalized_in_update_or_create(self, device):
        """Test that protocol is normalized to lowercase by update_or_create_entry."""
        entry, created = RouteEntry.update_or_create_entry(
            device=device,
            network="10.4.0.0/24",
            protocol="OSPF",  # Uppercase — as EOS returns
            next_hop="192.168.1.1",
        )
        assert created is True
        assert entry.protocol == "ospf"

    def test_update_refreshes_mutable_fields(self, device):
        """Test that update_or_create_entry refreshes metric and is_active."""
        _entry1, _ = RouteEntry.update_or_create_entry(
            device=device,
            network="10.5.0.0/24",
            protocol="ospf",
            next_hop="192.168.1.1",
            metric=10,
            is_active=True,
        )
        entry2, created = RouteEntry.update_or_create_entry(
            device=device,
            network="10.5.0.0/24",
            protocol="ospf",
            next_hop="192.168.1.1",
            metric=20,  # Changed
            is_active=False,  # Changed
        )
        assert created is False
        assert entry2.metric == 20
        assert entry2.is_active is False

    def test_update_or_create_with_vrf(self, device, vrf):
        """Test update_or_create_entry with a non-None VRF."""
        entry, created = RouteEntry.update_or_create_entry(
            device=device,
            network="10.7.0.0/24",
            protocol="ospf",
            vrf=vrf,
            next_hop="192.168.1.1",
        )
        assert created is True
        assert entry.vrf == vrf
        assert entry.vrf.name == "TestVRF"

        # Second call with same identity — should UPDATE, not INSERT
        entry2, created2 = RouteEntry.update_or_create_entry(
            device=device,
            network="10.7.0.0/24",
            protocol="ospf",
            vrf=vrf,
            next_hop="192.168.1.1",
            metric=50,
        )
        assert created2 is False
        assert entry2.pk == entry.pk
        assert entry2.metric == 50

    def test_update_or_create_invalid_cidr_raises(self, device):
        """Test that update_or_create_entry raises ValueError for invalid CIDR."""
        with pytest.raises(ValueError, match="Invalid CIDR prefix"):
            RouteEntry.update_or_create_entry(
                device=device,
                network="not-a-prefix",
                protocol="ospf",
                next_hop="192.168.1.1",
            )

    def test_uniqueconstraint_enforced(self, device):
        """Test that the UniqueConstraint prevents duplicate rows."""
        from django.db import IntegrityError

        entry = RouteEntry(
            device=device,
            network="10.6.0.0/24",
            prefix_length=24,
            protocol="ospf",
            next_hop="192.168.1.1",
            last_seen=timezone.now(),
        )
        entry.validated_save()
        with pytest.raises(IntegrityError):
            # Intentionally using objects.create() to test DB-level constraint
            RouteEntry.objects.create(
                device=device,
                network="10.6.0.0/24",
                prefix_length=24,
                protocol="ospf",
                next_hop="192.168.1.1",
                last_seen=timezone.now(),
            )
