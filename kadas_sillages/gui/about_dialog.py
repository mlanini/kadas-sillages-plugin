# -*- coding: utf-8 -*-
"""
AboutDialog: modal dialog showing plugin metadata (version, author, links).

Reads information from the bundled metadata.txt so it is always in sync
with the installed plugin version.
"""
from __future__ import annotations

import configparser
import os

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


def _read_metadata() -> dict:
    """Parse metadata.txt and return the [general] section as a dict."""
    meta_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "metadata.txt",
    )
    cfg = configparser.ConfigParser()
    cfg.read(meta_path, encoding="utf-8")
    return dict(cfg["general"]) if "general" in cfg else {}


class AboutDialog(QDialog):
    """Modal About dialog driven by the plugin's metadata.txt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        meta = _read_metadata()

        self.setWindowTitle(f"About {meta.get('name', 'Sillages')}")
        self.setMinimumWidth(420)
        self.setMaximumWidth(480)
        self._build_ui(meta)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self, m: dict):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # --- Icon + name row ---
        top_row = QHBoxLayout()
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "resources", "icon.svg",
        )
        icon_lbl = QLabel()
        pix = QPixmap(icon_path)
        if not pix.isNull():
            icon_lbl.setPixmap(pix.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon_lbl.setFixedSize(54, 54)
        icon_lbl.setAlignment(Qt.AlignCenter)

        name_block = QVBoxLayout()
        name_lbl = QLabel(f"<b style='font-size:16px'>{m.get('name', 'Sillages')}</b>")
        version_lbl = QLabel(f"Version {m.get('version', '—')}")
        version_lbl.setStyleSheet("color: #555; font-size: 11px;")
        name_block.addWidget(name_lbl)
        name_block.addWidget(version_lbl)
        name_block.addStretch()

        top_row.addWidget(icon_lbl)
        top_row.addLayout(name_block, 1)
        layout.addLayout(top_row)

        # --- Description ---
        desc = m.get("description", "")
        if desc:
            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("font-size: 11px;")
            layout.addWidget(desc_lbl)

        # --- About text ---
        about = m.get("about", "")
        if about:
            about_lbl = QLabel(about)
            about_lbl.setWordWrap(True)
            about_lbl.setStyleSheet("color: #333; font-size: 11px;")
            layout.addWidget(about_lbl)

        # --- Metadata grid ---
        meta_html = "<table style='font-size:11px; border-spacing:0;'>"

        author = m.get("author", "")
        email  = m.get("email", "")
        if author:
            contact = f"{author}"
            if email:
                contact += f" &lt;<a href='mailto:{email}'>{email}</a>&gt;"
            meta_html += f"<tr><td style='color:#777; padding-right:8px;'>Author</td><td>{contact}</td></tr>"

        repo = m.get("repository", "") or m.get("homepage", "")
        if repo:
            meta_html += (
                f"<tr><td style='color:#777; padding-right:8px;'>Repository</td>"
                f"<td><a href='{repo}'>{repo}</a></td></tr>"
            )

        tracker = m.get("tracker", "")
        if tracker and tracker != repo:
            meta_html += (
                f"<tr><td style='color:#777; padding-right:8px;'>Bug tracker</td>"
                f"<td><a href='{tracker}'>{tracker}</a></td></tr>"
            )

        tags = m.get("tags", "")
        if tags:
            meta_html += f"<tr><td style='color:#777; padding-right:8px;'>Tags</td><td>{tags}</td></tr>"

        meta_html += (
            f"<tr><td style='color:#777; padding-right:8px;'>License</td>"
            f"<td>MIT</td></tr>"
        )
        meta_html += "</table>"

        meta_lbl = QLabel(meta_html)
        meta_lbl.setOpenExternalLinks(True)
        meta_lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(meta_lbl)

        # --- Buttons ---
        btn_row = QHBoxLayout()

        if repo:
            btn_repo = QPushButton("Open repository…")
            btn_repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(repo)))
            btn_row.addWidget(btn_repo)

        btn_row.addStretch()

        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.rejected.connect(self.reject)
        btn_row.addWidget(close_box)

        layout.addLayout(btn_row)
