# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [1.2.0] — 2026-03-09

### Added

- Lookup bar with IP-in-prefix matching
- Dashboard with route statistics
- GraphQL support for RouteEntry
- Device route tab with filtering

### Changed

- Redesigned lookup bar with prominent animations and monospace input
- Tokenized lookup bar CSS with design tokens

## [1.1.3] — 2026-03-08

### Added

- Smart route lookup with IP-in-prefix matching

## [1.0.0] — 2026-02-20

### Added

- Initial release
- RouteEntry model with UPDATE/INSERT (NetDB) logic
- CollectRoutesJob with Nornir parallel collection
- PurgeOldRoutesJob with configurable retention
- Arista EOS parser (`show ip route | json`)
- Cisco IOS parser (`show ip route` via TextFSM)
- REST API with full CRUD
- UI list view with filtering
- Device tab with route entries panel
- ECMP support (separate rows per next-hop)
- VRF support
- Excluded route networks (multicast, link-local, loopback)
