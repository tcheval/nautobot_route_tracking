"""Navigation configuration for Route Tracking plugin.

Contributes a "Route Tracking" group to the shared "Dashboards" tab (weight=400),
and keeps a separate "Route Tracking" tab (weight=500) for the Routes group.

References:
- Nautobot Navigation: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/navigation/

"""

from nautobot.apps.ui import (
    NavMenuGroup,
    NavMenuItem,
    NavMenuTab,
)

menu_items = (
    NavMenuTab(
        name="Dashboards",
        weight=150,
        icon="control-panel",
        groups=(
            NavMenuGroup(
                name="Route Tracking",
                weight=300,
                items=(
                    NavMenuItem(
                        link="plugins:nautobot_route_tracking:dashboard",
                        name="Dashboard",
                        permissions=["nautobot_route_tracking.view_routeentry"],
                        buttons=(),
                        weight=100,
                    ),
                ),
            ),
        ),
    ),
    NavMenuTab(
        name="Route Tracking",
        weight=500,
        groups=(
            NavMenuGroup(
                name="Routes",
                weight=100,
                items=(
                    NavMenuItem(
                        link="plugins:nautobot_route_tracking:routeentry_list",
                        name="Route Entries",
                        permissions=["nautobot_route_tracking.view_routeentry"],
                        buttons=(),
                        weight=100,
                    ),
                ),
            ),
        ),
    ),
)
