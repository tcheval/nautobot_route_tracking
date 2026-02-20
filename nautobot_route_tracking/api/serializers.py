"""API Serializers for Route Tracking plugin.

This module defines the REST API serializers for RouteEntry model data.
All serializers inherit from NautobotModelSerializer provided by Nautobot.

References:
- Nautobot Serializers: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/serializers/

"""

from nautobot.apps.api import NautobotModelSerializer

from nautobot_route_tracking.models import RouteEntry


class RouteEntrySerializer(NautobotModelSerializer):
    """API Serializer for RouteEntry model.

    NautobotModelSerializer automatically provides nested representations
    for FK fields (device, vrf, outgoing_interface) with id, url, and
    display fields. No explicit nested serializers needed in Nautobot 3.x.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/serializers/
    """

    class Meta:
        """Serializer metadata."""

        model = RouteEntry
        fields = [
            "id",
            "url",
            "display",
            "device",
            "vrf",
            "network",
            "prefix_length",
            "protocol",
            "next_hop",
            "outgoing_interface",
            "metric",
            "admin_distance",
            "is_active",
            "routing_table",
            "first_seen",
            "last_seen",
            "tags",
            "created",
            "last_updated",
        ]
        read_only_fields = [
            "first_seen",
            "last_seen",
            "created",
            "last_updated",
        ]
