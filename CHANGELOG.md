# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/);
versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.1.0] – 2026-05-13

### Added
- Initial release.
- Live tracking via [Traccar](https://www.traccar.org/) server (WebSocket + HTTP polling fallback).
- Automatic WebSocket → HTTP polling fallback when a corporate proxy blocks the WebSocket upgrade.
- Customisable track colour, width and maximum number of points per device.
- Custom SVG/PNG marker icons per device.
- Optional map labels per device.
- Dock panel with device list, status LED, visibility toggle, style editor, track clear and map-centre buttons.
- Historic track export as KADAS layer (LineString or MultiPoint) or file (GeoJSON, GPX, CSV).
- Server/client clock-offset detection with configurable warning/error thresholds.
- Auto-connect on plugin load when configured.
- `package.py` helper script to build a distributable ZIP.
