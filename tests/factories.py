"""Factory Boy factories for Route Tracking plugin tests.

This module provides factories for creating test data for all plugin models.

References:
- Factory Boy: https://factoryboy.readthedocs.io/
"""

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status

from nautobot_route_tracking.models import RouteEntry


class LocationTypeFactory(DjangoModelFactory):
    """Factory for LocationType model."""

    class Meta:
        model = LocationType
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Location Type {n}")
    nestable = True


class LocationFactory(DjangoModelFactory):
    """Factory for Location model."""

    class Meta:
        model = Location
        django_get_or_create = ("name", "location_type")

    name = factory.Sequence(lambda n: f"Location {n}")
    location_type = factory.SubFactory(LocationTypeFactory)

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Location).first()


class ManufacturerFactory(DjangoModelFactory):
    """Factory for Manufacturer model."""

    class Meta:
        model = Manufacturer
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Manufacturer {n}")


class DeviceTypeFactory(DjangoModelFactory):
    """Factory for DeviceType model."""

    class Meta:
        model = DeviceType
        django_get_or_create = ("model", "manufacturer")

    model = factory.Sequence(lambda n: f"Device Type {n}")
    manufacturer = factory.SubFactory(ManufacturerFactory)


class RoleFactory(DjangoModelFactory):
    """Factory for Role model."""

    class Meta:
        model = Role
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Role {n}")


class DeviceFactory(DjangoModelFactory):
    """Factory for Device model."""

    class Meta:
        model = Device

    name = factory.Sequence(lambda n: f"device-{n:03d}")
    location = factory.SubFactory(LocationFactory)
    device_type = factory.SubFactory(DeviceTypeFactory)
    role = factory.SubFactory(RoleFactory)

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Device).first()


class InterfaceFactory(DjangoModelFactory):
    """Factory for Interface model."""

    class Meta:
        model = Interface

    name = factory.Sequence(lambda n: f"GigabitEthernet0/{n}")
    device = factory.SubFactory(DeviceFactory)
    type = "1000base-t"

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Interface).first()


class RouteEntryFactory(DjangoModelFactory):
    """Factory for RouteEntry model."""

    class Meta:
        model = RouteEntry

    device = factory.SubFactory(DeviceFactory)
    vrf = None
    network = factory.Sequence(lambda n: f"10.{(n // 256) % 256}.{n % 256}.0/24")
    prefix_length = 24
    protocol = RouteEntry.Protocol.OSPF
    next_hop = factory.Sequence(lambda n: f"192.168.{(n // 256) % 256}.{n % 256}")
    outgoing_interface = None
    metric = 10
    admin_distance = 110
    is_active = True
    routing_table = "default"
    last_seen = factory.LazyFunction(timezone.now)
