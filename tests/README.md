# Tests

Unit and integration tests for the **nautobot-route-tracking** plugin.

## Running Tests

Tests run inside the `nautobot` Docker container (no local venv):

```bash
docker cp ./tests nautobot:/tmp/tests
docker exec nautobot bash -c "cd /tmp && python -m pytest tests/ -v --tb=short"
```

## Structure

| File | Coverage |
| ---- | -------- |
| `conftest.py` | Shared fixtures (Device, Location, RouteEntry, authenticated client) |
| `factories.py` | Factory Boy factories for test data generation |
| `test_models.py` | Model validation, NetDB UPDATE/INSERT logic, protocol normalization |
| `test_parsers.py` | EOS JSON and IOS TextFSM route parsers |
| `test_filters.py` | FilterSet behavior (device, protocol, network, lookup) |
| `test_api.py` | REST API endpoints (list, detail, filtering) |
| `test_views.py` | UI views (list, detail, device tab) |
| `test_jobs.py` | Job execution with mocked NAPALM CLI calls |

## Conventions

- All fixtures use `validated_save()` for plugin models
- `get_or_create()` is acceptable for Nautobot core models (LocationType, etc.)
- FK filter tests use list format: `{"device": [str(device.pk)]}`
- Network calls are mocked via `napalm_cli` patching
