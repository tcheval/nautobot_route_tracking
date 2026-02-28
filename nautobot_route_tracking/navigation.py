"""Navigation configuration for Route Tracking plugin.

Contributes a "Route Tracking" group to the shared "Dashboards" tab (weight=50),
and adds Route Entries to the built-in "Apps" tab (weight=2200).

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
        weight=50,
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
        name="Apps",
        weight=2200,
        icon="elements",
        groups=(
            NavMenuGroup(
                name="Route Tracking",
                weight=300,
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
