from __future__ import annotations

from localflight.radar.classify import classify_blip
from localflight.radar.map_layers import build_radar_map
from localflight.radar.normalize import adsbx_aircraft_to_blips
from localflight.radar import runways as runway_domain
from localflight.radar.runways import merge_runways


def test_adsbx_normalizer_preserves_navigation_and_quality_fields() -> None:
    blips = adsbx_aircraft_to_blips(
        [
            {
                "hex": "abc123",
                "flight": "SWR100 ",
                "lat": 47.5,
                "lon": 8.6,
                "alt_baro": 5000,
                "alt_geom": 5200,
                "gs": 210,
                "track": 140,
                "baro_rate": -700,
                "nav_altitude_mcp": 4000,
                "nav_heading": 142,
                "nav_modes": ["althold"],
                "seen_pos": 2.4,
                "nac_p": 9,
            }
        ],
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=20,
    )

    assert blips[0]["callsign"] == "SWR100"
    assert blips[0]["altitude_ft"] == 5000
    assert blips[0]["geo_altitude_ft"] == 5200
    assert blips[0]["speed_kt"] == 210
    assert blips[0]["vertical_rate_fpm"] == -700
    assert blips[0]["selected_altitude_ft"] == 4000
    assert blips[0]["source_quality"] == "adsb-quality"


def test_runway_merge_uses_osm_geometry_and_ourairports_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "localflight.radar.runways.ourairports_runways_for",
        lambda airport_icao, **kwargs: [
            {
                "id": "ourairports:LSZH:16-34",
                "label": "16/34",
                "length_ft": 12139,
                "width_ft": 197,
                "surface": "ASP",
                "lighted": True,
                "closed": False,
                "endpoints": [
                    {"ident": "16", "lat": 47.47, "lon": 8.53, "heading_deg": 160},
                    {"ident": "34", "lat": 47.43, "lon": 8.57, "heading_deg": 340},
                ],
            }
        ],
    )

    runways = merge_runways(
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        surface_features=[
            {
                "kind": "runway",
                "id": "way:1",
                "label": "16/34",
                "points": [[47.47, 8.53], [47.43, 8.57]],
            }
        ],
    )

    assert runways[0]["confidence"] == "ourairports+osm"
    assert runways[0]["length_ft"] == 12139
    assert runways[0]["lighted"] is True
    assert runways[0]["validation"]["validated_by"] == ["openstreetmap", "ourairports-runways"]


def test_runway_merge_can_match_by_heading_when_osm_label_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "localflight.radar.runways.ourairports_runways_for",
        lambda airport_icao, **kwargs: [
            {
                "id": "ourairports:LSZH:16-34",
                "label": "16/34",
                "length_ft": 12139,
                "endpoints": [
                    {"ident": "16", "lat": 47.40, "lon": 8.50, "heading_deg": 45},
                    {"ident": "34", "lat": 47.42, "lon": 8.52, "heading_deg": 225},
                ],
                "points": [[47.40, 8.50], [47.42, 8.52]],
            }
        ],
    )

    runways = merge_runways(
        airport_icao="LSZH",
        center_lat=47.41,
        center_lon=8.51,
        surface_features=[
            {
                "kind": "runway",
                "id": "way:unlabeled",
                "label": "",
                "points": [[47.4001, 8.5001], [47.4201, 8.5201]],
            }
        ],
    )

    assert runways[0]["confidence"] == "ourairports+osm"
    assert runways[0]["label"] == ""
    assert runways[0]["length_ft"] == 12139


def test_classifier_marks_final_only_with_runway_alignment() -> None:
    blip = classify_blip(
        {
            "callsign": "SWR100",
            "lat": 47.50,
            "lon": 8.50,
            "heading": 140,
            "track_deg": 140,
            "altitude_ft": 2200,
            "speed_kt": 150,
            "vertical_rate_fpm": -650,
            "distance_nm": 5.0,
            "departure_icao": "EGLL",
            "arrival_icao": "LSZH",
        },
        airport_icao="LSZH",
        runways=[
            {
                "label": "14",
                "confidence": "ourairports",
                "endpoints": [{"ident": "14", "lat": 47.45, "lon": 8.55, "heading_deg": 140}],
                "points": [[47.45, 8.55], [47.55, 8.45]],
            }
        ],
    )

    assert blip["radar_phase"] == "final"
    assert blip["matched_runway"] == "14"
    assert blip["phase_confidence"] in {"high", "medium"}


def test_classifier_keeps_real_unknown_intent_as_low_confidence_approach_not_final() -> None:
    blip = classify_blip(
        {
            "callsign": "ABC123",
            "lat": 47.50,
            "lon": 8.50,
            "track_deg": 140,
            "altitude_ft": 2400,
            "speed_kt": 145,
            "vertical_rate_fpm": -700,
            "distance_nm": 5.0,
            "source": "adsbexchange",
        },
        airport_icao="LSZH",
        runways=[
            {
                "label": "14",
                "confidence": "ourairports",
                "endpoints": [{"ident": "14", "lat": 47.45, "lon": 8.55, "heading_deg": 140}],
                "points": [[47.45, 8.55], [47.55, 8.45]],
            }
        ],
    )

    assert blip["radar_phase"] == "approach"
    assert blip["phase_confidence"] == "low"
    assert blip["nearest_runway"] == "14"
    assert blip["motion_trend"] == "descending"


def test_classifier_reports_cruise_and_level_motion_without_extra_detail() -> None:
    blip = classify_blip(
        {
            "callsign": "ENR123",
            "lat": 47.8,
            "lon": 8.8,
            "altitude_ft": 32000,
            "speed_kt": 430,
            "vertical_rate_fpm": 0,
            "distance_nm": 28.0,
        },
        airport_icao="LSZH",
        runways=[],
    )

    assert blip["radar_phase"] == "cruise"
    assert blip["motion_trend"] == "level"


def test_radar_map_omits_clutter_but_keeps_runways(monkeypatch) -> None:
    monkeypatch.setattr("localflight.radar.runways.ourairports_runways_for", lambda airport_icao, **kwargs: [])
    payload = build_radar_map(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=40,
        surface_payload={
            "provider": "openstreetmap",
            "cache_state": "fresh",
            "attribution": {"text": "OSM", "url": "https://www.openstreetmap.org/copyright"},
            "features": [
                {"kind": "runway", "label": "16/34", "points": [[47.47, 8.53], [47.43, 8.57]]},
                {"kind": "taxiway", "label": "A", "points": [[47.46, 8.54], [47.44, 8.56]]},
                {"kind": "boundary", "label": "airport", "points": [[47.4, 8.5], [47.5, 8.6]]},
            ],
        },
    )

    assert payload["runways"][0]["label"] == "16/34"
    assert [feature["kind"] for feature in payload["surface_features"]] == ["boundary"]


def test_ourairports_runway_cache_refresh_loads_public_csv(tmp_path, monkeypatch) -> None:
    class _Response:
        text = (
            "id,airport_ref,airport_ident,length_ft,width_ft,surface,lighted,closed,"
            "le_ident,le_latitude_deg,le_longitude_deg,le_elevation_ft,le_heading_degT,le_displaced_threshold_ft,"
            "he_ident,he_latitude_deg,he_longitude_deg,he_elevation_ft,he_heading_degT,he_displaced_threshold_ft\n"
            "1,1,LSZH,12139,197,ASP,1,0,16,47.47,8.53,1400,160,,34,47.43,8.57,1410,340,\n"
        )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(runway_domain, "_runway_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(runway_domain.requests, "get", lambda *args, **kwargs: _Response())
    runway_domain._load_ourairports_runways_cached.cache_clear()

    result = runway_domain.refresh_ourairports_runway_cache(force=True)
    loaded = runway_domain.ourairports_runways_for("LSZH")

    assert result["ok"] is True
    assert loaded[0]["label"] == "16/34"
    assert loaded[0]["length_ft"] == 12139
