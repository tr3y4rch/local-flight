from __future__ import annotations

from localflight.radar.classify import classify_blip
from localflight.radar.map_layers import build_radar_map
from localflight.radar.normalize import adsbx_aircraft_to_blips, enrich_blip_display_fields
from localflight.radar import runways as runway_domain
from localflight.radar.runways import merge_runways
from localflight.sources.web.airport_map_context import fetch_overpass_map_context, normalize_overpass_map_context
from localflight.sources.web.terrain_context import (
    build_terrain_payload,
    decode_terrarium_rgb,
    latlon_to_tile,
    terrain_features_from_tile,
)
from PIL import Image


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


def test_radar_display_normalizer_adds_safe_common_fields_and_scrubs_vatsim_identity() -> None:
    blip = enrich_blip_display_fields(
        {
            "callsign": "BAW123",
            "source": "vatsim",
            "altitude_m": 3000,
            "speed_ms": 110,
            "vertical_rate": -3,
            "heading": 271,
            "departure_icao": "EGLL",
            "arrival_icao": "LSZH",
            "pilot_name": "Do Not Show",
            "cid": 123456,
            "server": "PRIVATE",
        }
    )

    assert blip["detail_mode"] == "virtual"
    assert blip["display_title"] == "BAW123"
    assert blip["route_display"] == "EGLL -> LSZH"
    assert blip["altitude_ft"] == 9843
    assert blip["speed_kt"] == 214
    assert blip["vertical_rate_fpm"] == -591
    assert blip["heading_deg"] == 271
    assert "pilot_name" not in blip
    assert "cid" not in blip
    assert "server" not in blip


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
    assert runways[0]["data_source"] == "openstreetmap+ourairports"
    assert runways[0]["geometry_precision"] == "osm-polyline"
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


def test_classifier_uses_airport_elevation_for_taxi_state() -> None:
    blip = classify_blip(
        {
            "callsign": "TAXI1",
            "altitude_ft": 5480,
            "speed_kt": 18,
            "distance_nm": 1.0,
        },
        airport_icao="KDEN",
        runways=[
            {
                "label": "16R",
                "endpoints": [
                    {"ident": "16R", "lat": 39.87, "lon": -104.67, "heading_deg": 160, "elevation_ft": 5434},
                    {"ident": "34L", "lat": 39.82, "lon": -104.65, "heading_deg": 340, "elevation_ft": 5430},
                ],
            }
        ],
    )

    assert blip["radar_phase"] == "taxi"
    assert blip["altitude_agl_ft"] < 100


def test_classifier_marks_confirmed_takeoff_roll_as_departing() -> None:
    blip = classify_blip(
        {
            "callsign": "SWR200",
            "on_ground": True,
            "speed_kt": 112,
            "distance_nm": 1.5,
            "departure_icao": "LSZH",
            "arrival_icao": "EGLL",
        },
        airport_icao="LSZH",
        runways=[],
    )

    assert blip["radar_phase"] == "departing"
    assert "takeoff-roll" in blip["phase_reason"]


def test_departed_board_status_never_overrides_live_final_phase() -> None:
    blip = classify_blip(
        {
            "callsign": "SWR100",
            "lat": 47.50,
            "lon": 8.50,
            "track_deg": 140,
            "altitude_ft": 2200,
            "speed_kt": 150,
            "vertical_rate_fpm": -650,
            "distance_nm": 5.0,
            "departure_icao": "EGLL",
            "arrival_icao": "LSZH",
            "board_status": "departed",
        },
        airport_icao="LSZH",
        runways=[
            {
                "label": "14",
                "endpoints": [{"ident": "14", "lat": 47.45, "lon": 8.55, "heading_deg": 140}],
                "points": [[47.45, 8.55], [47.55, 8.45]],
            }
        ],
    )

    assert blip["board_status"] == "departed"
    assert blip["radar_phase"] == "final"


def test_stale_arrival_target_cannot_advance_to_final() -> None:
    blip = classify_blip(
        {
            "callsign": "OLD100",
            "lat": 47.50,
            "lon": 8.50,
            "track_deg": 140,
            "altitude_ft": 2200,
            "speed_kt": 150,
            "vertical_rate_fpm": -650,
            "distance_nm": 5.0,
            "departure_icao": "EGLL",
            "arrival_icao": "LSZH",
            "position_age_s": 90,
        },
        airport_icao="LSZH",
        runways=[
            {
                "label": "14",
                "endpoints": [{"ident": "14", "lat": 47.45, "lon": 8.55, "heading_deg": 140}],
                "points": [[47.45, 8.55], [47.55, 8.45]],
            }
        ],
    )

    assert blip["position_stale"] is True
    assert blip["radar_phase"] == "approach"
    assert blip["phase_confidence"] == "low"


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


def test_classifier_reports_enroute_and_level_motion_without_extra_detail() -> None:
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

    assert blip["radar_phase"] == "enroute"
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


def test_osm_map_context_normalizer_keeps_quiet_background_features() -> None:
    features = normalize_overpass_map_context(
        {
            "elements": [
                {
                    "type": "way",
                    "id": 1,
                    "tags": {"highway": "service", "name": "Airport Way"},
                    "geometry": [{"lat": 47.0, "lon": 8.0}, {"lat": 47.01, "lon": 8.01}],
                },
                {
                    "type": "way",
                    "id": 2,
                    "tags": {"natural": "water", "name": "Lake"},
                    "geometry": [{"lat": 47.0, "lon": 8.0}, {"lat": 47.0, "lon": 8.02}, {"lat": 47.01, "lon": 8.02}, {"lat": 47.0, "lon": 8.0}],
                },
                {
                    "type": "way",
                    "id": 3,
                    "tags": {"amenity": "cafe", "name": "Noisy POI"},
                    "geometry": [{"lat": 47.0, "lon": 8.0}, {"lat": 47.01, "lon": 8.01}],
                },
            ]
        }
    )

    assert [feature["kind"] for feature in features] == ["water", "road"]
    assert features[0]["closed"] is True


def test_osm_map_context_prefers_larger_readable_features() -> None:
    features = normalize_overpass_map_context(
        {
            "elements": [
                {
                    "type": "way",
                    "id": 1,
                    "tags": {"highway": "primary", "name": "Short"},
                    "geometry": [{"lat": 47.0, "lon": 8.0}, {"lat": 47.0001, "lon": 8.0001}],
                },
                {
                    "type": "way",
                    "id": 2,
                    "tags": {"highway": "primary", "name": "Long"},
                    "geometry": [{"lat": 47.0, "lon": 8.0}, {"lat": 47.03, "lon": 8.05}],
                },
            ]
        }
    )

    assert [feature["label"] for feature in features] == ["Long", "Short"]


def test_radar_map_includes_label_free_map_context_below_operational_layers(monkeypatch) -> None:
    monkeypatch.setattr("localflight.radar.runways.ourairports_runways_for", lambda airport_icao, **kwargs: [])
    payload = build_radar_map(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=5,
        surface_payload=None,
        map_payload={
            "provider": "openstreetmap",
            "cache_state": "fresh",
            "features": [
                {"kind": "road", "label": "Airport road", "points": [[47.44, 8.54], [47.45, 8.55]]},
                {"kind": "water", "label": "Lake", "closed": True, "points": [[47.43, 8.53], [47.44, 8.53], [47.44, 8.54], [47.43, 8.53]]},
            ],
        },
    )

    assert [feature["kind"] for feature in payload["map_features"]] == ["road", "water"]
    assert {feature["label"] for feature in payload["map_features"]} == {""}
    assert payload["sources"]["map"] == "openstreetmap"
    assert payload["confidence"]["map_feature_count"] == 2


def test_radar_map_thins_context_at_wide_ranges(monkeypatch) -> None:
    monkeypatch.setattr("localflight.radar.runways.ourairports_runways_for", lambda airport_icao, **kwargs: [])
    payload = build_radar_map(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=40,
        surface_payload=None,
        map_payload={
            "provider": "openstreetmap",
            "cache_state": "fresh",
            "features": [
                {"kind": "road", "points": [[47.44, 8.54], [47.45, 8.55]]},
                {"kind": "rail", "points": [[47.44, 8.54], [47.45, 8.55]]},
                {"kind": "water", "points": [[47.43, 8.53], [47.44, 8.53]]},
            ],
        },
    )

    assert [feature["kind"] for feature in payload["map_features"]] == ["water"]


def test_radar_map_keeps_balanced_context_at_twenty_nm(monkeypatch) -> None:
    monkeypatch.setattr("localflight.radar.runways.ourairports_runways_for", lambda airport_icao, **kwargs: [])
    features = [{"kind": "water", "points": [[47.43, 8.53], [47.44, 8.53]]} for _ in range(40)]
    features += [
        {"kind": "road", "points": [[47.44, 8.54], [47.45, 8.55]]},
        {"kind": "rail", "points": [[47.44, 8.55], [47.45, 8.56]]},
        {"kind": "landuse", "closed": True, "points": [[47.43, 8.53], [47.44, 8.53], [47.44, 8.54], [47.43, 8.53]]},
    ]

    payload = build_radar_map(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=20,
        surface_payload=None,
        map_payload={"provider": "openstreetmap", "cache_state": "fresh", "features": features},
    )

    kinds = {feature["kind"] for feature in payload["map_features"]}
    assert {"water", "road", "rail", "landuse"}.issubset(kinds)
    assert sum(1 for feature in payload["map_features"] if feature["kind"] == "water") == 14


def test_osm_map_context_fetch_tries_fallback_endpoint(monkeypatch) -> None:
    calls: list[str] = []

    class Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    def post(url: str, **kwargs: object) -> Response:
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("slow overpass")
        return Response({"elements": []})

    monkeypatch.setattr("localflight.sources.web.airport_map_context.requests.post", post)

    payload = fetch_overpass_map_context(lat=47.45, lon=8.55, radius_nm=5.0, timeout_s=0.1)

    assert payload == {"elements": []}
    assert calls[:2] == [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]


def test_terrain_context_decodes_terrarium_and_builds_bands_and_contours() -> None:
    image = Image.new("RGB", (256, 256))
    for y in range(256):
        for x in range(256):
            elevation_m = 120 + y * 2 + x * 0.3
            encoded = elevation_m + 32768
            r = int(encoded // 256)
            g = int(encoded % 256)
            b = int((encoded - int(encoded)) * 256)
            image.putpixel((x, y), (r, g, b))

    tile_x, tile_y = latlon_to_tile(33.942501, -118.407997, 10)
    features = terrain_features_from_tile(
        image,
        tile_x=tile_x,
        tile_y=tile_y,
        zoom=10,
        center_lat=33.942501,
        center_lon=-118.407997,
        radius_nm=5,
    )

    assert round(decode_terrarium_rgb((128, 0, 0))) == 0
    assert features
    assert {feature["kind"] for feature in features} == {"terrain_band", "contour"}
    contour_segments = [feature for feature in features if feature["kind"] == "contour"]
    assert contour_segments
    assert any(
        abs(segment["points"][0][0] - segment["points"][1][0]) > 0.000001
        for segment in contour_segments
    )
    assert all(not feature["label"] for feature in features)


def test_radar_map_includes_terrain_only_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr("localflight.radar.runways.ourairports_runways_for", lambda airport_icao, **kwargs: [])
    terrain_payload = build_terrain_payload(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=5,
        cache_state="fresh",
        features=[{"kind": "contour", "label": "", "elevation_ft": 1800, "points": [[47.44, 8.54], [47.45, 8.55]]}],
    )

    off = build_radar_map(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=5,
        surface_payload=None,
        terrain_payload=terrain_payload,
        terrain_enabled=False,
    )
    on = build_radar_map(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=5,
        surface_payload=None,
        terrain_payload=terrain_payload,
        terrain_enabled=True,
    )

    assert off["terrain"]["features"] == []
    assert on["terrain"]["features"][0]["kind"] == "contour"
    assert on["sources"]["terrain"] == "aws-terrain-tiles"
    assert on["confidence"]["terrain_feature_count"] == 1


def test_radar_map_does_not_promote_estimated_runways_to_osm(monkeypatch) -> None:
    monkeypatch.setattr(
        "localflight.radar.runways.ourairports_runways_for",
        lambda airport_icao, **kwargs: [
            {
                "kind": "runway",
                "id": "ourairports:KLAX:7L-25R",
                "label": "7L/25R",
                "closed": False,
                "length_ft": 12894,
                "width_ft": 150,
                "endpoints": [
                    {"ident": "7L", "lat": 33.935556, "lon": -118.422089, "heading_deg": 83},
                    {"ident": "25R", "lat": 33.939881, "lon": -118.379794, "heading_deg": 263},
                ],
                "points": [[33.935556, -118.422089], [33.939881, -118.379794]],
                "confidence": "ourairports",
            }
        ],
    )
    payload = build_radar_map(
        airport_iata="LAX",
        airport_icao="KLAX",
        center_lat=33.942501,
        center_lon=-118.407997,
        radius_nm=2,
        surface_payload={
            "provider": "localflight-estimated",
            "cache_state": "estimated",
            "features": [
                {"kind": "boundary", "label": "Estimated airport", "points": [[33.93, -118.42], [33.95, -118.40]]},
                {"kind": "runway", "label": "EST RWY", "points": [[33.93, -118.40], [33.95, -118.42]]},
            ],
        },
    )

    assert [runway["label"] for runway in payload["runways"]] == ["7L/25R"]
    assert payload["runways"][0]["confidence"] == "ourairports"
    assert payload["sources"]["runways"] == ["ourairports"]
    assert payload["sources"]["runway_geometry_precision"] == ["endpoint"]
    assert payload["confidence"]["has_provider_runways"] is True
    assert payload["confidence"]["runway_endpoint_count"] == 1


def test_radar_map_uses_ourairports_runways_when_surface_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "localflight.radar.runways.ourairports_runways_for",
        lambda airport_icao, **kwargs: [
            {
                "kind": "runway",
                "id": "ourairports:KLAX:7L-25R",
                "label": "7L/25R",
                "closed": False,
                "width_ft": 150,
                "points": [[33.935556, -118.422089], [33.939881, -118.379794]],
                "confidence": "ourairports",
                "data_source": "ourairports",
                "geometry_precision": "endpoint",
            }
        ],
    )

    payload = build_radar_map(
        airport_iata="LAX",
        airport_icao="KLAX",
        center_lat=33.942501,
        center_lon=-118.407997,
        radius_nm=2,
        surface_payload=None,
    )

    assert [runway["label"] for runway in payload["runways"]] == ["7L/25R"]
    assert payload["sources"]["surface"] == "none"
    assert payload["sources"]["runways"] == ["ourairports"]
    assert payload["sources"]["runway_geometry_precision"] == ["endpoint"]
    assert payload["confidence"]["runway_exact_count"] == 1


def test_radar_map_retries_ourairports_before_estimated_fallback(monkeypatch) -> None:
    calls: list[bool] = []

    def _runways(_airport_icao: str, **kwargs):
        auto_refresh = bool(kwargs.get("auto_refresh"))
        calls.append(auto_refresh)
        if not auto_refresh:
            return []
        return [
            {
                "kind": "runway",
                "id": "ourairports:KLAX:6L-24R",
                "label": "6L/24R",
                "closed": False,
                "points": [[33.949119, -118.431187], [33.952112, -118.401954]],
                "confidence": "ourairports",
                "data_source": "ourairports",
                "geometry_precision": "endpoint",
            }
        ]

    monkeypatch.setattr("localflight.radar.runways.ourairports_runways_for", _runways)

    payload = build_radar_map(
        airport_iata="LAX",
        airport_icao="KLAX",
        center_lat=33.942501,
        center_lon=-118.407997,
        radius_nm=2,
        surface_payload=None,
    )

    assert calls == [False, True]
    assert [runway["label"] for runway in payload["runways"]] == ["6L/24R"]
    assert payload["confidence"]["has_provider_runways"] is True


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
    assert loaded[0]["data_source"] == "ourairports"
    assert loaded[0]["geometry_precision"] == "endpoint"
