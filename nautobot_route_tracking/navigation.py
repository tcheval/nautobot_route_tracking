"""Navigation configuration for Route Tracking plugin.

This module defines the navigation menu structure for the plugin,
adding a "Route Tracking" top-level tab with a "Routes" group.

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
