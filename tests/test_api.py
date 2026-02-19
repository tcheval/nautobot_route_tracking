"""Tests for Route Tracking plugin REST API.

Tests verify the API endpoints, filtering, and serialization.
"""

import pytest
from django.utils import timezone

from nautobot_route_tracking.models import RouteEntry


@pytest.mark.django_db
class TestRouteEntryAPI:
    """Tests for the RouteEntry API viewset."""

    LIST_URL = "/api/plugins/route-tracking/route-entries/"
    DETAIL_URL = "/api/plugins/route-tracking/route-entries/{pk}/"

    @pytest.fixture(autouse=True)
    def create_entries(self, device):
        """Create RouteEntry objects for API tests."""
        now = timezone.now()
        self.entry = RouteEntry.objects.create(
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

    def test_list_unauthenticated_returns_403(self, client):
        """Test that unauthenticated requests return 403."""
        response = client.get(self.LIST_URL)
        assert response.status_code in (401, 403)

    def test_list_authenticated_returns_200(self, api_client):
        """Test that authenticated requests return 200."""
        response = api_client.get(self.LIST_URL)
        assert response.status_code == 200

    def test_list_returns_entries(self, api_client):
        """Test that list endpoint returns RouteEntry objects."""
        response = api_client.get(self.LIST_URL)
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1
        assert any(r["network"] == "10.0.0.0/24" for r in data["results"])

    def test_detail_returns_entry(self, api_client):
        """Test that detail endpoint returns a single RouteEntry."""
        url = self.DETAIL_URL.format(pk=self.entry.pk)
        response = api_client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data["network"] == "10.0.0.0/24"
        assert data["protocol"] == "ospf"

    def test_filter_by_protocol(self, api_client):
        """Test filtering by protocol."""
        response = api_client.get(self.LIST_URL, {"protocol": "ospf"})
        assert response.status_code == 200
        data = response.json()
        for result in data["results"]:
            assert result["protocol"] == "ospf"

    def test_filter_by_network_partial(self, api_client):
        """Test filtering by network partial match."""
        response = api_client.get(self.LIST_URL, {"network": "10.0"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1

    def test_filter_by_is_active(self, api_client):
        """Test filtering by is_active."""
        response = api_client.get(self.LIST_URL, {"is_active": "true"})
        assert response.status_code == 200
        data = response.json()
        for result in data["results"]:
            assert result["is_active"] is True

    def test_serializer_fields(self, api_client):
        """Test that serializer exposes expected fields."""
        url = self.DETAIL_URL.format(pk=self.entry.pk)
        response = api_client.get(url)
        data = response.json()

        expected_fields = [
            "id", "network", "prefix_length", "protocol", "next_hop",
            "metric", "admin_distance", "is_active", "routing_table",
            "first_seen", "last_seen",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
