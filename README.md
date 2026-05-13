# KADAS Sillages

> **Live device tracking plugin for [KADAS Albireo](https://kadas.github.io/) / QGIS**
> powered by [Traccar](https://www.traccar.org/).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![KADAS](https://img.shields.io/badge/KADAS-Albireo%202-green)](https://kadas.github.io/)

---

## Features

| Feature | Details |
|---|---|
| **Live tracking** | WebSocket push from Traccar; automatic fallback to HTTP polling when a corporate proxy blocks the WebSocket upgrade |
| **Device list** | Status LED (online / offline), visibility toggle, per-device style editor |
| **Customisable appearance** | Track colour, width, maximum points; custom SVG/PNG marker icon; optional map label |
| **Historic export** | Download a date-range route as a KADAS layer (LineString or MultiPoint) or save to GeoJSON, GPX, or CSV |
| **Clock drift detection** | Warns when the Traccar server clock differs from the local clock (configurable thresholds) |
| **Auto-connect** | Reconnects automatically on plugin load when credentials are configured |

---

## Requirements

- KADAS Albireo 2 (based on QGIS ≥ 3.0) **or** QGIS ≥ 3.0
- Python ≥ 3.9 (bundled with KADAS/QGIS)
- A running [Traccar](https://www.traccar.org/) server (v6 recommended)
- Network access from the KADAS/QGIS machine to the Traccar server

---

## Installation

### From ZIP (recommended)

1. Download the latest `kadas_sillages_<version>.zip` from the
   [Releases](https://github.com/intelligeo/kadas-sillages-plugin/releases) page.
2. In KADAS/QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Browse to the downloaded ZIP and click **Install Plugin**.

### From source

```bash
git clone https://github.com/intelligeo/kadas-sillages-plugin.git
python package.py               # creates kadas_sillages_<version>.zip
# then install the ZIP as above
```

---

## Quick start

1. Open the **Sillages** dock panel from the GPS ribbon tab (KADAS) or the Plugins menu (QGIS).
2. Click **⚙** to open Settings and enter your Traccar server URL, username and password.
3. Click **Connetti** — the device list appears automatically.
4. Click **▶ Live** to start live tracking on the map canvas.
5. Use **⬇ Storico** to download and display a historic route.

---

## Building a release ZIP

```bash
# default version from metadata.txt
python package.py

# override version (also updates metadata.txt)
python package.py --version 1.2.3

# custom output directory
python package.py --output-dir dist/
```

The resulting ZIP can be installed directly via the KADAS/QGIS plugin manager.

---

## Project structure

```
kadas-sillages-plugin/
├── kadas_sillages/          # Plugin package (installed by KADAS/QGIS)
│   ├── __init__.py          # classFactory entry point
│   ├── plugin.py            # KadasSillagesPlugin – lifecycle & ribbon action
│   ├── metadata.txt         # QGIS plugin metadata
│   ├── core/
│   │   ├── connection_manager.py  # Auth, session, device refresh
│   │   ├── tracker_manager.py     # WebSocket / polling live tracking
│   │   ├── map_layer_manager.py   # In-memory QGIS layers (positions & tracks)
│   │   ├── layer_styler.py        # Categorised renderers & labels
│   │   ├── traccar_client.py      # Synchronous Traccar REST client
│   │   ├── exporter.py            # Historic route export
│   │   ├── models.py              # Device & Position dataclasses
│   │   └── settings.py            # QgsSettings wrapper
│   ├── gui/
│   │   ├── main_dock.py           # Main DockWidget
│   │   ├── device_list_widget.py  # Scrollable device list
│   │   ├── device_style_dialog.py # Per-device style editor
│   │   ├── export_dialog.py       # Historic export dialog
│   │   └── settings_dialog.py     # Connection settings dialog
│   └── resources/
│       └── markers/               # Built-in SVG/PNG marker icons
├── package.py               # Release packaging script
├── CHANGELOG.md
├── LICENSE
└── README.md
```

---

## Contributing

Pull requests and issue reports are welcome.

1. Fork the repository and create a feature branch.
2. Keep commits focused; follow the existing code style (PEP 8, type hints, docstrings).
3. Open a pull request describing what was changed and why.

---

## License

This project is released under the [MIT License](LICENSE).  
© 2026 [INTELLIGEO.ch](https://intelligeo.ch)
