"""Lazy import helpers for native UI modules."""
from __future__ import annotations

from importlib import import_module
from typing import Any


def lazy_symbol(module_name: str, symbol_name: str) -> Any:
    module = import_module(module_name)
    return getattr(module, symbol_name)
