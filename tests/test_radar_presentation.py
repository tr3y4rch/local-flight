from __future__ import annotations

import json
from pathlib import Path

import pytest

from localflight.radar.presentation import (
    RADAR_DEGREES_PER_SECOND,
    RADAR_FLASH_DEGREES,
    RADAR_FRAME_INTERVAL_MS,
    RADAR_FOCUSED_MIN_OPACITY,
    RADAR_PRESENTATION_VERSION,
    RADAR_REVOLUTION_MS,
    RADAR_TRAIL_DEGREES,
    bearing_from_offset,
    blip_opacity,
    label_priority,
    normalize_radar_phase,
    radar_phase_label,
    sweep_angle_after,
    target_shape,
    target_tone_role,
)


CONTRACT = json.loads((Path(__file__).parents[1] / "contracts" / "radar-presentation-v1.json").read_text(encoding="utf-8"))


def test_radar_presentation_constants_match_contract() -> None:
    assert RADAR_PRESENTATION_VERSION == CONTRACT["version"]
    assert RADAR_REVOLUTION_MS == CONTRACT["revolution_ms"]
    assert RADAR_FRAME_INTERVAL_MS == CONTRACT["frame_interval_ms"]
    assert RADAR_TRAIL_DEGREES == CONTRACT["trail_degrees"]
    assert RADAR_FLASH_DEGREES == CONTRACT["flash_degrees"]
    assert RADAR_FOCUSED_MIN_OPACITY == CONTRACT["focused_min_opacity"]
    assert RADAR_DEGREES_PER_SECOND == 24.0


@pytest.mark.parametrize("vector", CONTRACT["bearing_vectors"], ids=lambda vector: vector["name"])
def test_radar_bearing_vectors(vector: dict[str, float]) -> None:
    assert bearing_from_offset(vector["x_nm"], vector["y_nm"]) == pytest.approx(vector["bearing"])


@pytest.mark.parametrize("vector", CONTRACT["opacity_vectors"], ids=lambda vector: vector["name"])
def test_radar_opacity_vectors(vector: dict[str, float]) -> None:
    assert blip_opacity(vector["target"], vector["sweep"]) == pytest.approx(vector["opacity"])


def test_radar_elapsed_clock_uses_fifteen_second_revolution() -> None:
    assert sweep_angle_after(0, 1000) == pytest.approx(24)
    assert sweep_angle_after(350, 1000) == pytest.approx(14)
    assert sweep_angle_after(72, RADAR_REVOLUTION_MS) == pytest.approx(72)


def test_radar_focus_keeps_target_visible_between_passes() -> None:
    assert blip_opacity(0, 180) == 0
    assert blip_opacity(0, 180, focused=True) == pytest.approx(RADAR_FOCUSED_MIN_OPACITY)


def test_radar_phase_semantics_ignore_passenger_board_status() -> None:
    blip = {"radar_phase": "approach", "board_status": "departed"}
    assert normalize_radar_phase(blip) == "approach"
    assert radar_phase_label(blip) == "APPROACH"
    assert target_tone_role(blip) == "approach"
    assert target_shape(blip) == "dot"


def test_radar_target_roles_and_label_priority_are_stable() -> None:
    assert target_tone_role({"radar_phase": "departing"}) == "departure"
    assert target_tone_role({"radar_phase": "taxi", "on_ground": True}) == "ground"
    assert target_tone_role({"radar_phase": "enroute", "source_quality": "stale"}) == "stale"
    assert target_shape({"radar_phase": "taxi"}) == "diamond"
    assert target_shape({"source_quality": "stale"}) == "hollow"
    assert label_priority({"radar_phase": "final"}) > label_priority({"radar_phase": "enroute"})
    assert label_priority({"radar_phase": "taxi"}, focused=True) > label_priority({"radar_phase": "final"})


def test_lan_radar_uses_shared_trailing_sweep_contract() -> None:
    root = Path(__file__).parents[1]
    template = (root / "src/localflight/ui/templates/radar.html").read_text(encoding="utf-8")
    presentation = (root / "src/localflight/ui/static/radar-presentation.js").read_text(encoding="utf-8")

    assert '/static/radar-presentation.js?v={{ static_version }}' in template
    assert "RadarPresentation.sweepAngleAfter" in template
    assert "RadarPresentation.blipOpacity" in template
    assert "-Math.PI/2-farAge" in template
    assert "staticLayerCanvas" in template
    assert "invalidateStaticLayer" in template
    assert "renderStaticRadarLayer" in template
    assert "age>350" not in template.replace(" ", "")
    assert "RADAR_BLIP_BASE_OPACITY" not in template
    assert "TRAIL_DEGREES = 72" in presentation
    assert "REVOLUTION_MS = 15000" in presentation
    assert 'return "stale"' in presentation
