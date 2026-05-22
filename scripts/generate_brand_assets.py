#!/usr/bin/env python3
"""Compatibility entrypoint for generating brand assets.

The Local Flight brand is now sourced from the Beacon Tools / Local Flight V2
asset folders. Keep this filename for existing release muscle memory, but send
all work through the V2 sync script.
"""
from __future__ import annotations

from scripts.sync_brand_v2 import main


if __name__ == "__main__":
    main()
