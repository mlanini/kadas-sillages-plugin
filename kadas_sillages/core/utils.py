# -*- coding: utf-8 -*-
"""General plugin utilities."""
import os


def plugin_path(*parts: str) -> str:
    """Return the absolute path relative to the plugin package root."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def resource_path(filename: str) -> str:
    """Return the absolute path of a file inside the resources/ folder."""
    return plugin_path("resources", filename)
