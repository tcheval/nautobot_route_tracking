"""Tests for Route Tracking plugin FilterSets.

Tests verify filter field behavior, especially the critical requirement that
NaturalKeyOrPKMultipleChoiceFilter requires list input.
"""

import pytest
from django.utils import timezone

from nautobot_route_tracking.filters import RouteEntryFilterSet
from nautobot_route_tracking.models import RouteEntry


@pytest.mark.django_db
class TestRouteEntryFilterSet:
    """Tests for RouteEntryFilterSet."""

    @pytest.fixture(autouse=True)
    def create_entries(self, device, device2):
        """Create several RouteEntry objects for filter testing."""
        now = timezone.now()

        self.entry_ospf = RouteEntry(
            device=device,
            network="10.0.0.0/24",
            prefix_length=24,
            protocol=RouteEntry.Protocol.OSPF,
            next_hop="192.168.1.1",
            metric=10,
            admin_distance=110,
            is_active=True,
            routing_table="default",
            last_seen=now,
        )
        self.entry_ospf.validated_save()
        self.entry_static = RouteEntry(
            device=device,
            network="0.0.0.0/0",
            prefix_length=0,
            protocol=RouteEntry.Protocol.STATIC,
            next_hop="10.0.0.1",
            metric=0,
            admin_distance=1,
            is_active=True,
            routing_table="default",
            last_seen=now,
        )
        self.entry_static.validated_save()
        self.entry_device2 = RouteEntry(
            device=device2,
            network="172.16.0.0/16",
            prefix_length=16,
            protocol=RouteEntry.Protocol.BGP,
            next_hop="10.0.0.2",
            metric=0,
            admin_distance=20,
            is_active=False,
            routing_table="default",
            last_seen=now,
        )
        self.entry_device2.validated_save()

    def test_no_filter_returns_all(self):
        """Test that no filter returns all RouteEntry objects."""
        filterset = RouteEntryFilterSet({})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 3

    def test_device_filter_pk_list(self, device):
        """Test device filter with PK — must be a list."""
        filterset = RouteEntryFilterSet({"device": [str(device.pk)]})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 2

    def test_device_filter_name_list(self, device):
        """Test device filter with name — must be a list."""
        filterset = RouteEntryFilterSet({"device": [device.name]})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 2

    def test_protocol_filter(self):
        """Test protocol multi-choice filter."""
        filterset = RouteEntryFilterSet({"protocol": ["ospf"]})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 1
        assert filterset.qs.first().protocol == "ospf"

    def test_protocol_filter_multiple(self):
        """Test protocol filter with multiple values."""
        filterset = RouteEntryFilterSet({"protocol": ["ospf", "static"]})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 2

    def test_network_partial_match(self):
        """Test network partial-match filter (CharFilter icontains)."""
        filterset = RouteEntryFilterSet({"network": "10.0"})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 1

    def test_next_hop_partial_match(self):
        """Test next_hop partial-match filter."""
        filterset = RouteEntryFilterSet({"next_hop": "192.168"})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 1

    def test_is_active_true(self):
        """Test is_active=True filter."""
        filterset = RouteEntryFilterSet({"is_active": True})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 2

    def test_is_active_false(self):
        """Test is_active=False filter."""
        filterset = RouteEntryFilterSet({"is_active": False})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 1

    def test_q_search_by_network(self):
        """Test SearchFilter on network field."""
        filterset = RouteEntryFilterSet({"q": "172.16"})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 1

    def test_q_search_by_device_name(self, device):
        """Test SearchFilter on device__name field."""
        filterset = RouteEntryFilterSet({"q": device.name})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 2

    def test_vrf_filter_null(self):
        """Test that vrf filter with isnull=True returns entries without VRF."""
        # All entries have vrf=None — filtering by vrf__isnull should return all
        filterset = RouteEntryFilterSet({"vrf": ["null"]})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 3

    def test_last_seen_after_filter(self):
        """Test last_seen_after DateTimeFilter."""
        from datetime import timedelta

        # Use a time clearly in the past — all entries last_seen=now should match
        one_hour_ago = (timezone.now() - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        filterset = RouteEntryFilterSet({"last_seen_after": one_hour_ago})
        assert filterset.is_valid(), filterset.errors
        assert filterset.qs.count() == 3
