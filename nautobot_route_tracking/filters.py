"""FilterSet definitions for Route Tracking plugin.

This module defines the filter classes used for filtering RouteEntry data
in the UI and API. All filters inherit from NautobotFilterSet.

References:
- Nautobot FilterSets: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/filters/
- Nautobot 3.x Role: https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/role/
- django-filter: https://django-filter.readthedocs.io/

"""

import django_filters
from nautobot.apps.filters import (
    NaturalKeyOrPKMultipleChoiceFilter,
    NautobotFilterSet,
    SearchFilter,
)
from nautobot.dcim.models import Device, Location
from nautobot.extras.models import Role
from nautobot.ipam.models import VRF

from nautobot_route_tracking.models import RouteEntry


class RouteEntryFilterSet(NautobotFilterSet):
    """FilterSet for RouteEntry model.

    Provides advanced filtering including:
    - Full-text search across network, device name, protocol, next_hop, routing_table
    - Device, Device Role, and Location FK filters (Nautobot 3.x compatible)
    - VRF filter
    - Protocol multi-choice filter
    - Partial-match filters for network and next_hop
    - Boolean filter for is_active
    - Date range filters for first_seen and last_seen

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/filters/

    Note:
        NaturalKeyOrPKMultipleChoiceFilter requires list input.
        Always pass e.g. ``{"device": [str(device.pk)]}`` — never a bare string.

    """

    q = SearchFilter(
        filter_predicates={
            "network": "icontains",
            "device__name": "icontains",
            "protocol": "icontains",
            "next_hop": "icontains",
            "routing_table": "icontains",
        },
    )

    device = NaturalKeyOrPKMultipleChoiceFilter(
        queryset=Device.objects.all(),
        label="Device",
        to_field_name="name",
    )

    device_role = NaturalKeyOrPKMultipleChoiceFilter(
        field_name="device__role",
        queryset=Role.objects.all(),
        label="Device Role",
        to_field_name="name",
    )

    location = NaturalKeyOrPKMultipleChoiceFilter(
        field_name="device__location",
        queryset=Location.objects.all(),
        label="Location",
        to_field_name="name",
    )

    vrf = NaturalKeyOrPKMultipleChoiceFilter(
        queryset=VRF.objects.all(),
        label="VRF",
        to_field_name="name",
    )

    protocol = django_filters.MultipleChoiceFilter(
        choices=RouteEntry.Protocol.choices,
        label="Protocol",
    )

    network = django_filters.CharFilter(
        lookup_expr="icontains",
        label="Network (partial match)",
    )

    next_hop = django_filters.CharFilter(
        lookup_expr="icontains",
        label="Next Hop (partial match)",
    )

    is_active = django_filters.BooleanFilter(
        label="Is Active",
    )

    routing_table = django_filters.CharFilter(
        lookup_expr="icontains",
        label="Routing Table (partial match)",
    )

    first_seen_after = django_filters.DateTimeFilter(
        field_name="first_seen", lookup_expr="gte", label="First Seen After"
    )
    first_seen_before = django_filters.DateTimeFilter(
        field_name="first_seen", lookup_expr="lte", label="First Seen Before"
    )
    last_seen_after = django_filters.DateTimeFilter(field_name="last_seen", lookup_expr="gte", label="Last Seen After")
    last_seen_before = django_filters.DateTimeFilter(
        field_name="last_seen", lookup_expr="lte", label="Last Seen Before"
    )

    class Meta:
        """Filter metadata."""

        model = RouteEntry
        fields = [
            "id",
            "device",
            "device_role",
            "location",
            "vrf",
            "protocol",
            "network",
            "next_hop",
            "is_active",
            "routing_table",
            "first_seen_after",
            "first_seen_before",
            "last_seen_after",
            "last_seen_before",
        ]
