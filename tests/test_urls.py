"""URL configuration for pytest.

Includes Nautobot core URLs and injects the plugin URLs into the existing
``plugins:`` and ``plugins-api:`` namespaces that Nautobot defines.

pytest-django's ``django.setup()`` does not process the ``PLUGINS``
setting, so plugin URLs must be registered explicitly here.

The key trick: Nautobot's core URLs already define a ``plugins`` namespace
(top-level) and a ``plugins-api`` namespace (nested under ``api/``).
We inject our plugin URL patterns into those existing namespaces and
invalidate all cached resolver data so Django rediscovers sub-namespaces.
"""

from django.urls import URLResolver, clear_url_caches, include, path
from nautobot.core.urls import urlpatterns as nautobot_urls

# Plugin URL patterns to inject
_plugin_ui_pattern = path("route-tracking/", include("nautobot_route_tracking.urls"))

_plugin_api_pattern = path(
    "route-tracking/",
    include(("nautobot_route_tracking.api.urls", "nautobot_route_tracking-api")),
)

# Cached property names that Django uses internally on URLResolver
_RESOLVER_CACHE_ATTRS = ("namespace_dict", "app_dict", "reverse_dict", "url_patterns")


def _clear_resolver_caches(resolver):
    """Clear all cached properties on a URLResolver."""
    for attr in _RESOLVER_CACHE_ATTRS:
        resolver.__dict__.pop(attr, None)


def _inject_pattern(patterns, namespace, pattern_to_add):
    """Find a URLResolver by namespace and inject into it.

    Recursively searches un-namespaced resolvers (e.g. the ``api/`` resolver
    that wraps ``plugins-api``).
    """
    for sub in patterns:
        if isinstance(sub, URLResolver):
            if getattr(sub, "namespace", None) == namespace:
                sub.url_patterns.append(pattern_to_add)
                _clear_resolver_caches(sub)
                return True
            if getattr(sub, "namespace", None) is None:
                if _inject_pattern(sub.url_patterns, namespace, pattern_to_add):
                    _clear_resolver_caches(sub)
                    return True
    return False


# Inject plugin UI patterns into the top-level "plugins" namespace
_inject_pattern(nautobot_urls, "plugins", _plugin_ui_pattern)

# Inject plugin API patterns into "plugins-api" (nested under the api/ resolver)
_inject_pattern(nautobot_urls, "plugins-api", _plugin_api_pattern)

# Clear Django's global URL resolver caches so the injected patterns are visible
clear_url_caches()

urlpatterns = nautobot_urls
