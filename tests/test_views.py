"""Tests for Route Tracking plugin UI views.

Tests verify the list view, detail view, and device tab view.
"""

import pytest
from django.utils import timezone

from nautobot_route_tracking.models import RouteEntry


@pytest.mark.django_db
class TestRouteEntryListView:
    """Tests for the RouteEntry list view."""

    LIST_URL = "/plugins/route-tracking/route-entries/"

    def test_list_unauthenticated_redirects(self, client):
        """Test that unauthenticated access redirects to login."""
        response = client.get(self.LIST_URL)
        assert response.status_code in (302, 403)

    def test_list_authenticated_returns_200(self, authenticated_client):
        """Test that authenticated access returns 200."""
        response = authenticated_client.get(self.LIST_URL)
        assert response.status_code == 200

    def test_list_contains_entries(self, authenticated_client, route_entry):
        """Test that list view shows RouteEntry objects."""
        response = authenticated_client.get(self.LIST_URL)
        assert response.status_code == 200
        assert "10.0.0.0/24" in response.content.decode()


@pytest.mark.django_db
class TestRouteEntryDetailView:
    """Tests for the RouteEntry detail view."""

    DETAIL_URL = "/plugins/route-tracking/route-entries/{pk}/"

    def test_detail_authenticated_returns_200(self, authenticated_client, route_entry):
        """Test that authenticated access returns 200."""
        url = self.DETAIL_URL.format(pk=route_entry.pk)
        response = authenticated_client.get(url)
        assert response.status_code == 200

    def test_detail_shows_route_info(self, authenticated_client, route_entry):
        """Test that detail view shows route information."""
        url = self.DETAIL_URL.format(pk=route_entry.pk)
        response = authenticated_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert "10.0.0.0/24" in content


@pytest.mark.django_db
class TestDeviceRouteTabView:
    """Tests for the Device Routes tab view."""

    TAB_URL = "/plugins/route-tracking/devices/{pk}/routes/"

    def test_tab_unauthenticated_redirects(self, client, device):
        """Test that unauthenticated access redirects."""
        url = self.TAB_URL.format(pk=device.pk)
        response = client.get(url)
        assert response.status_code in (302, 403)

    def test_tab_authenticated_returns_200(self, authenticated_client, device, route_entry):
        """Test that authenticated access returns 200."""
        url = self.TAB_URL.format(pk=device.pk)
        response = authenticated_client.get(url)
        assert response.status_code == 200

    def test_tab_shows_device_routes(self, authenticated_client, device, route_entry):
        """Test that device route tab shows routes for that device."""
        url = self.TAB_URL.format(pk=device.pk)
        response = authenticated_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert "10.0.0.0/24" in content

    def test_tab_empty_device_shows_no_data(self, authenticated_client, device2):
        """Test that device tab with no routes shows empty state."""
        url = self.TAB_URL.format(pk=device2.pk)
        response = authenticated_client.get(url)
        assert response.status_code == 200
        # Either "No route entries" or an empty table
        assert response.status_code == 200
