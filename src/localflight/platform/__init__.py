"""
localflight/platform/__init__.py

Platform detection and abstraction layer for Local Flight.
Provides cross-platform browser, tray, and runtime utilities.
"""
from localflight.platform.detect import detect, Platform

__all__ = ["detect", "Platform"]