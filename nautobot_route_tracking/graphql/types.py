from nautobot.core.graphql.types import OptimizedNautobotObjectType

from nautobot_route_tracking import filters, models


class RouteEntryType(OptimizedNautobotObjectType):
    """GraphQL type for RouteEntry model."""

    class Meta:
        model = models.RouteEntry
        filterset_class = filters.RouteEntryFilterSet


graphql_types = [RouteEntryType]
