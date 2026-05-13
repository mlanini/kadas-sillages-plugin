# Changelog

All notable changes to **KADAS Sillages** are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.1.0] – 2026-05-13

### Added

#### Core
- **Live tracking** via Traccar WebSocket with automatic HTTP long-polling fallback when WebSocket is unavailable.
- **`TraccarClient`** — synchronous Traccar REST API wrapper (login, logout, session verification, device list, position history, route, server info). Proxy-aware via `QgsNetworkAccessManager`.
- **`ConnectionManager`** — manages the HTTP session lifecycle, device list cache, and per-device visual-style persistence across refreshes.
- **`TrackerManager`** — dual-mode tracking loop (WebSocket + polling); emits `device_status_changed` and `transport_mode_changed` signals.
- **`MapLayerManager`** — creates and maintains two QGIS memory layers (*Sillages – Positions* and *Sillages – Tracks*); updates features in real time.
- **`LayerStyler`** — applies per-device SVG/PNG icons, track colour/width and name labels to the position layer.
- **`Exporter`** — downloads historic position data from Traccar and exports as QGIS layer (LineString or MultiPoint), GeoJSON, GPX or CSV.
- **`PluginSettings`** — `QgsSettings` wrapper; stores server URL, credentials, auto-connect flag and default track style.
- **Server clock-drift detection** — warns the user when the Traccar server clock is more than 30 s ahead or behind local time.

#### GUI
- **`MainDock`** — side panel with connection toolbar (Connect/Disconnect, Refresh ↻, ▶ Live, ⬇ History, ⚙ Settings, ℹ About), device list, status bar and log area.
- **`DeviceListWidget`** — scrollable, sortable device list (online first, then alphabetical); per-row status LED, visibility checkbox, colour swatch, Style ⚙, Clear track ✕ and Centre map 📍 buttons.
- **`DeviceStyleDialog`** — per-device style editor: preset SVG marker grid, custom file picker, track colour (with preview swatch and colour picker), track width (spin + slider), max track length, show/hide label checkbox.
- **`ExportDialog`** — historic export wizard: device selector, UTC date-range picker with quick shortcuts (Last hour / 6h / 24h / Last week), output format selector (QGIS layer, GeoJSON, GPX, CSV), file path picker.
- **`SettingsDialog`** — connection settings dialog: server URL, username, password, auto-connect toggle, default track colour/width/max-length, proxy note.
- **`AboutDialog`** — metadata-driven about dialog (reads `metadata.txt`); shows version, author, description, repository link and MIT licence notice.

#### Infrastructure
- **`package.py`** — CLI packaging script; builds `kadas_sillages_<version>.zip` ready for *Install from ZIP*. Supports `--output-dir` and `--version` flags.
- **`README.md`** — full project documentation (overview, requirements, installation, quick start, configuration, project structure).
- **`LICENSE`** — MIT Licence (© 2026 Michael Lanini).
- **`CHANGELOG.md`** — this file.

### Fixed
- `_parse_reply` in `TraccarClient`: `reply.url()` was called after `reply.deleteLater()`, causing a use-after-free access. URL is now saved to a local variable before deletion.
- `DeviceListWidget._on_visibility_changed`: double call to `update_device_visuals` removed; `MainDock` handles the signal once.
- `ConnectionManager.refresh_devices`: per-device style customisations (colour, width, icon, label) were lost on every refresh. Visual properties are now saved before and restored after the refresh.

### Notes
- Minimum QGIS / KADAS version: **3.0**.
- Tested with Python 3.12 (QGIS 3.40.7 bundle).
- Traccar minimum version: any release supporting the `/api/session`, `/api/devices` and `/api/positions` REST endpoints.
- The plugin ribbon button is placed in the **GPS** tab of the KADAS ribbon; a fallback entry is added to the standard *Plugins* menu for plain QGIS.

[0.1.0]: https://github.com/mlanini/kadas-sillages-plugin/releases/tag/v0.1.0
