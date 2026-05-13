# KADAS Sillages

> **Live device tracking via Traccar server for KADAS / QGIS**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Plugin version](https://img.shields.io/badge/version-0.1.0-green.svg)](kadas_sillages/metadata.txt)
[![QGIS minimum](https://img.shields.io/badge/QGIS-%E2%89%A53.0-brightgreen.svg)](https://qgis.org)

---

## Overview

**Sillages** is a KADAS / QGIS plugin that connects to a [Traccar](https://www.traccar.org/) GNSS tracking server, lists managed devices and displays their live positions and historical tracks directly on the map canvas.

Key features:

| Feature | Description |
|---|---|
| **Live tracking** | WebSocket feed with automatic HTTP polling fallback |
| **Device list** | Scrollable list with online/offline indicator and visibility toggle |
| **Per-device style** | Custom icon (SVG/PNG), track colour, width, max length, name label |
| **Historic export** | Download past tracks as QGIS layer (LineString / MultiPoint), GeoJSON, GPX or CSV |
| **Server clock check** | Warns if the Traccar server clock drifts more than 30 s |
| **Auto-connect** | Optional connection on plugin load |
| **Proxy-aware** | Uses KADAS/QGIS proxy settings transparently |

---

## Requirements

- KADAS ≥ 2.x **or** QGIS ≥ 3.0
- A running [Traccar](https://www.traccar.org/download/) instance (self-hosted or cloud)
- Network access from the client to the Traccar server (HTTP/HTTPS + WebSocket)

---

## Installation

### From ZIP (recommended)

1. Download the latest `kadas_sillages_<version>.zip` from the [Releases](../../releases) page.
2. Open KADAS/QGIS → **Plugins ▸ Manage and Install Plugins… ▸ Install from ZIP**.
3. Select the downloaded file and click **Install Plugin**.

### Build the ZIP yourself

```bash
python package.py                  # creates kadas_sillages_<version>.zip
python package.py --output-dir dist/
python package.py --version 1.2.3  # also updates metadata.txt
```

---

## Quick Start

1. Click the **Sillages** button in the **GPS** ribbon tab (or *Plugins* menu).
2. Click **⚙** to open *Settings* and enter your Traccar server URL, username and password.
3. Click **Connect**. The device list populates automatically.
4. Click **▶ Live** to start live tracking on the map.
5. Click **⬇ History** to export a historic track.

---

## Configuration

All settings are stored via `QgsSettings` (per-user, per-QGIS-profile).

| Setting | Default | Description |
|---|---|---|
| Server URL | *(empty)* | Full URL of the Traccar server, e.g. `https://traccar.example.com` |
| Username | *(empty)* | Traccar account e-mail |
| Password | *(empty)* | Traccar account password (stored in QgsSettings) |
| Auto-connect | `False` | Connect automatically when the plugin panel is first opened |
| Default track colour | `#0000FF` | Hex colour for new device tracks |
| Default track width | `2 px` | Line width for new device tracks |
| Default max track length | `500 pts` | Maximum number of points kept per device track |

Per-device style overrides are stored in memory for the duration of the session and survive a device-list refresh.

---

## Project Structure

```
kadas_sillages/
├── core/
│   ├── connection_manager.py   # HTTP session, device list, refresh
│   ├── exporter.py             # Historic track export
│   ├── layer_styler.py         # SVG/raster icon + label rendering
│   ├── map_layer_manager.py    # QGIS layer creation and feature updates
│   ├── models.py               # Device / Position dataclasses
│   ├── settings.py             # QgsSettings wrapper
│   ├── traccar_client.py       # Traccar REST API client
│   ├── tracker_manager.py      # WebSocket + polling live-tracking loop
│   └── utils.py                # Path helpers
├── gui/
│   ├── about_dialog.py         # About dialog (metadata-driven)
│   ├── device_list_widget.py   # Scrollable device list
│   ├── device_style_dialog.py  # Per-device style editor
│   ├── export_dialog.py        # Historic export dialog
│   ├── main_dock.py            # Main DockWidget
│   └── settings_dialog.py      # Connection settings dialog
├── resources/
│   ├── icon.svg
│   ├── kadas_star.png
│   └── markers/                # Preset SVG marker icons
├── metadata.txt
└── plugin.py                   # Plugin entry point
package.py                       # ZIP packaging script
```

---

## Contributing

Pull requests and bug reports are welcome on the [GitHub repository](https://github.com/mlanini/kadas-sillages-plugin).

Please open an issue before starting significant work so we can coordinate.

---

## License

This project is released under the **MIT License** — see [LICENSE](LICENSE) for details.

© 2026 Michael Lanini — [mlanini@proton.me](mailto:mlanini@proton.me)
