"""Screen-size rules for native Qt windows.

The native shell has to run on everything from small Pi touch displays to large
desktop monitors. Keep the sizing math pure so it can be tested without a Qt
display server.
"""
from __future__ import annotations


DISPLAY_SPLIT_SIDE_BY_SIDE_MIN_WIDTH = 1320


def width_fraction(available_width: int) -> float:
    """Return a comfortable initial-window fraction for a display width."""
    if available_width <= 900:
        return 0.96
    if available_width <= 1280:
        return 0.90
    if available_width <= 1800:
        return 0.82
    if available_width <= 2600:
        return 0.74
    return 0.58


def fitted_window_size(
    available_width: int,
    available_height: int,
    *,
    max_width: int,
    max_height: int,
    min_width: int = 560,
    min_height: int = 420,
) -> tuple[int, int]:
    """Return an initial size that fits within the usable screen geometry."""
    available_width = max(1, int(available_width))
    available_height = max(1, int(available_height))
    target_width = int(available_width * width_fraction(available_width))
    target_height = int(available_height * 0.88)

    width = min(max_width, target_width)
    height = min(max_height, target_height)

    width = min(available_width, max(min_width, width))
    height = min(available_height, max(min_height, height))
    return width, height


def default_display_mode(available_width: int | None) -> str:
    """Use split view only when it has enough room to stay legible."""
    if available_width is not None and available_width < DISPLAY_SPLIT_SIDE_BY_SIDE_MIN_WIDTH:
        return "fids"
    return "split"


def display_split_orientation(available_width: int | None) -> str:
    """Return the Display Split orientation for the available page width."""
    if available_width is not None and int(available_width) < DISPLAY_SPLIT_SIDE_BY_SIDE_MIN_WIDTH:
        return "vertical"
    return "horizontal"


def native_visual_density(available_width: int | None) -> str:
    """Return a named density bucket for the native shell chrome."""
    if available_width is None:
        return "wide"
    width = max(1, int(available_width))
    if width < 900:
        return "compact"
    if width < 1320:
        return "medium"
    if width >= 2200:
        return "presentation"
    return "wide"
