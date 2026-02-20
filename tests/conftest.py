"""Pytest configuration and fixtures for Route Tracking plugin tests.

This module provides common fixtures and configuration for all tests.

References:
- Pytest: https://docs.pytest.org/
- Factory Boy: https://factoryboy.readthedocs.io/
- Django Testing: https://docs.djangoproject.com/en/4.2/topics/testing/
- Nautobot Testing: https://docs.nautobot.com/projects/core/en/stable/development/core/testing/
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status

User = get_user_model()


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "integration: mark test as an integration test (requires network)")
    config.addinivalue_line("markers", "slow: mark test as slow running")


# =============================================================================
# Base Nautobot Model Fixtures
# =============================================================================


@pytest.fixture
def location_type(db):
    """Create a LocationType for testing."""
    device_ct = ContentType.objects.get_for_model(Device)
    lt, _ = LocationType.objects.get_or_create(
        name="Site",
        defaults={"nestable": True},
    )
    lt.content_types.add(device_ct)
    return lt


@pytest.fixture
def location(db, location_type):
    """Create a Location for testing."""
    status = Status.objects.get_for_model(Location).first()
    return Location.objects.get_or_create(
        name="Test Site",
        location_type=location_type,
        defaults={"status": status},
    )[0]


@pytest.fixture
def manufacturer(db):
    """Create a Manufacturer for testing."""
    return Manufacturer.objects.get_or_create(name="Test Manufacturer")[0]


@pytest.fixture
def device_type(db, manufacturer):
    """Create a DeviceType for testing."""
    return DeviceType.objects.get_or_create(
        model="Test Device Type",
        manufacturer=manufacturer,
    )[0]


@pytest.fixture
def device_role(db):
    """Create a device Role for testing."""
    device_ct = ContentType.objects.get_for_model(Device)
    role, _ = Role.objects.get_or_create(name="Test Role")
    role.content_types.add(device_ct)
    return role


@pytest.fixture
def device(db, location, device_type, device_role):
    """Create a Device for testing."""
    status = Status.objects.get_for_model(Device).first()
    return Device.objects.create(
        name="test-device-01",
        location=location,
        device_type=device_type,
        role=device_role,
        status=status,
    )


@pytest.fixture
def device2(db, location, device_type, device_role):
    """Create a second Device for testing."""
    status = Status.objects.get_for_model(Device).first()
    return Device.objects.create(
        name="test-device-02",
        location=location,
        device_type=device_type,
        role=device_role,
        status=status,
    )


@pytest.fixture
def interface(db, device):
    """Create an Interface for testing."""
    status = Status.objects.get_for_model(Interface).first()
    return Interface.objects.create(
        name="GigabitEthernet0/1",
        device=device,
        type="1000base-t",
        status=status,
    )


# =============================================================================
# Route Tracking Fixtures
# =============================================================================


@pytest.fixture
def route_entry(db, device):
    """Create a RouteEntry for testing."""
    from django.utils import timezone

    from nautobot_route_tracking.models import RouteEntry

    entry = RouteEntry(
        device=device,
        network="10.0.0.0/24",
        prefix_length=24,
        protocol=RouteEntry.Protocol.OSPF,
        next_hop="192.168.1.1",
        metric=10,
        admin_distance=110,
        is_active=True,
        routing_table="default",
        last_seen=timezone.now(),
    )
    entry.validated_save()
    return entry


@pytest.fixture
def route_entry_static(db, device):
    """Create a static RouteEntry for testing."""
    from django.utils import timezone

    from nautobot_route_tracking.models import RouteEntry

    entry = RouteEntry(
        device=device,
        network="0.0.0.0/0",
        prefix_length=0,
        protocol=RouteEntry.Protocol.STATIC,
        next_hop="10.0.0.1",
        metric=0,
        admin_distance=1,
        is_active=True,
        routing_table="default",
        last_seen=timezone.now(),
    )
    entry.validated_save()
    return entry


# =============================================================================
# User and Authentication Fixtures
# =============================================================================


@pytest.fixture
def admin_user(db):
    """Create an admin user for testing."""
    return User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="admin",
    )


@pytest.fixture
def api_client(db, admin_user):
    """Create an authenticated API client."""
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def authenticated_client(db, admin_user):
    """Create an authenticated Django test client."""
    from django.test import Client

    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def request_factory():
    """Create a RequestFactory for table and view tests."""
    return RequestFactory()


# =============================================================================
# Platform Fixtures
# =============================================================================


@pytest.fixture
def platform_cisco_ios(db):
    """Create a Cisco IOS platform for testing jobs."""
    from nautobot.dcim.models import Platform

    return Platform.objects.get_or_create(
        name="Cisco IOS",
        defaults={"network_driver": "cisco_ios"},
    )[0]


@pytest.fixture
def platform_arista_eos(db):
    """Create an Arista EOS platform for testing jobs."""
    from nautobot.dcim.models import Platform

    return Platform.objects.get_or_create(
        name="Arista EOS",
        defaults={"network_driver": "arista_eos"},
    )[0]


@pytest.fixture
def device_with_platform(db, device, platform_cisco_ios):
    """Assign a Cisco IOS platform to device for testing."""
    device.platform = platform_cisco_ios
    device.validated_save()
    return device
