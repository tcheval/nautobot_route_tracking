"""API Views for Route Tracking plugin.

This module defines the REST API viewsets for CRUD operations on route tracking data.
All viewsets inherit from NautobotModelViewSet provided by Nautobot.

References:
- Nautobot API ViewSets: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/views/

"""

from nautobot.apps.api import NautobotModelViewSet

from nautobot_route_tracking.api.serializers import RouteEntrySerializer
from nautobot_route_tracking.filters import RouteEntryFilterSet
from nautobot_route_tracking.models import RouteEntry


class RouteEntryViewSet(NautobotModelViewSet):
    """API ViewSet for RouteEntry model (read-only).

    Route entries are collected exclusively by CollectRoutesJob via the
    update_or_create_entry() classmethod, which enforces NetDB logic
    (normalization, deduplication, validated_save). Direct API writes are
    disabled to prevent bypassing these invariants.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/views/
    """

    queryset = RouteEntry.objects.select_related(
        "device",
        "device__location",
        "vrf",
        "outgoing_interface",
    ).prefetch_related("tags")
    serializer_class = RouteEntrySerializer
    filterset_class = RouteEntryFilterSet
    http_method_names = ["get", "head", "options"]
