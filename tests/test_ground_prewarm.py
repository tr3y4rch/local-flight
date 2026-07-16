from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import relay.main as relay_main
from relay.ground_cache import (
    GROUND_PINNED_AIRPORTS,
    layer_cache_key,
    radius_bucket,
    select_hybrid_airports,
)
from localflight.sources.web.airport_map_context import (
    build_map_context_payload,
    build_overpass_map_context_query,
    clip_map_features,
    fetch_overpass_map_context,
)
from localflight.sources.web.airport_surface import (
    MAX_OVERPASS_RESPONSE_BYTES,
    OverpassPayloadTooLarge,
    build_surface_payload,
    build_overpass_query,
    decode_overpass_json_response,
    fetch_overpass_surface,
)
from localflight.sources.web.terrain_context import build_terrain_payload


def _use_temp_db(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "relay.db"))
    relay_main._ensure_schema()


def _activate(client: TestClient, install_id: str) -> str:
    response = client.post(
        "/v1/activate",
        json={
            "install_id": install_id,
            "install_fingerprint": relay_main._install_fingerprint(install_id),
            "airport_iata": "ZRH",
            "airport_icao": "LSZH",
            "timezone": "Europe/Zurich",
            "device_type": "phone",
            "requested_mode": "mobile_standalone",
            "app_version": "0.5.1",
        },
    )
    assert response.status_code == 200
    return str(response.json()["activation_token"])


def _seed_ground_layers() -> None:
    surface = build_surface_payload(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=5,
        features=[{"kind": "runway", "id": "r1", "label": "16/34", "points": [[47.44, 8.54], [47.46, 8.56]]}],
        cache_state="fresh",
    )
    map_context = build_map_context_payload(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=10,
        features=[{"kind": "road", "road_class": "primary", "id": "m1", "points": [[47.43, 8.52], [47.47, 8.58]]}],
        cache_state="fresh",
    )
    terrain = build_terrain_payload(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=10,
        features=[{"kind": "contour", "id": "t1", "elevation_ft": 1500, "points": [[47.42, 8.51], [47.48, 8.59]]}],
        cache_state="fresh",
    )
    relay_main._store_ground_snapshot("surface", 5, surface)
    relay_main._store_ground_snapshot("map", 10, map_context)
    relay_main._store_ground_snapshot("terrain", 10, terrain)


def test_ground_radius_buckets_and_hybrid_selection() -> None:
    assert [radius_bucket(value) for value in (1, 5, 5.1, 10, 10.1, 20)] == [5, 5, 10, 10, 20, 20]
    assert radius_bucket(20, max_radius_nm=10) == 10
    selection = select_hybrid_airports([("ZRH", 20), ("NRT", 15), ("ZRH", 2)])
    codes = [row["airport"] for row in selection]
    assert len(codes) == 20
    assert len(set(codes)) == 20
    assert all(code in codes for code in GROUND_PINNED_AIRPORTS)
    assert "ZRH" in codes


def test_relay_image_includes_ground_helper_and_terrain_decoder() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "relay" / "Dockerfile").read_text(encoding="utf-8")
    requirements = (root / "relay" / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "COPY relay/ground_cache.py ./relay/ground_cache.py" in dockerfile
    assert "pillow" in requirements


def test_map_query_limits_road_classes_and_clips_to_ring() -> None:
    query = build_overpass_map_context_query(47.45, 8.55, 20 * 1852)
    assert "[maxsize:16777216]" in query
    assert '["highway"="motorway"]' in query
    assert '["highway"="primary"]' in query
    assert '["highway"="secondary"]' in query
    assert '["highway"="residential"]' not in query
    assert '["highway"="service"]' not in query
    features = clip_map_features(
        [{"kind": "road", "road_class": "primary", "points": [[47.45, 8.55], [48.45, 9.55]]}],
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=5,
    )
    assert len(features) == 1
    assert features[0]["road_class"] == "primary"
    assert len(features[0]["points"]) == 2
    assert len(features[0]["points"]) <= 180


def test_surface_query_uses_bounded_bbox_without_relation_expansion() -> None:
    query = build_overpass_query(33.64, -84.43, 5 * 1852)
    assert "[maxsize:16777216]" in query
    assert "around:" not in query
    assert "relation[" not in query
    assert 'way["aeroway"' in query


def test_map_context_respects_retry_after_and_retries_once(monkeypatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.headers = {"Retry-After": "2"}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self) -> dict[str, object]:
            return {"elements": []}

    def post(url: str, **_kwargs: object) -> Response:
        calls.append(url)
        return Response(429 if len(calls) == 1 else 200)

    monkeypatch.setattr("localflight.sources.web.airport_map_context.requests.post", post)
    monkeypatch.setattr("localflight.sources.web.airport_map_context.time.sleep", lambda value: sleeps.append(value))
    payload = fetch_overpass_map_context(
        lat=47.45,
        lon=8.55,
        radius_nm=20,
        overpass_url="https://overpass.invalid.test/api",
    )
    assert payload == {"elements": []}
    assert len(calls) == 2
    assert sleeps == [2.0]


def test_surface_context_retries_transient_timeout_once(monkeypatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    class Response:
        status_code = 200
        headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"elements": []}

    def post(url: str, **_kwargs: object) -> Response:
        calls.append(url)
        if len(calls) == 1:
            raise TimeoutError("temporary Overpass timeout")
        return Response()

    monkeypatch.setattr("localflight.sources.web.airport_surface.requests.post", post)
    monkeypatch.setattr("localflight.sources.web.airport_surface.time.sleep", lambda value: sleeps.append(value))
    payload = fetch_overpass_surface(
        lat=47.45,
        lon=8.55,
        radius_m=5000,
        overpass_url="https://overpass.invalid.test/api",
    )
    assert payload == {"elements": []}
    assert len(calls) == 2
    assert sleeps == [20.0]


def test_overpass_response_decoder_rejects_oversized_stream() -> None:
    class Response:
        headers: dict[str, str] = {}

        def iter_content(self, chunk_size: int) -> list[bytes]:
            assert chunk_size == 64 * 1024
            return [b"x" * (MAX_OVERPASS_RESPONSE_BYTES + 1)]

        def close(self) -> None:
            return None

    try:
        decode_overpass_json_response(Response())
    except OverpassPayloadTooLarge:
        pass
    else:
        raise AssertionError("oversized Overpass payload was accepted")


def test_schema_recovery_releases_interrupted_ground_warm(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    conn = relay_main._connect()
    try:
        now = datetime.now(timezone.utc)
        conn.execute(
            """
            INSERT INTO ground_warm_jobs (
                job_id, mode, status, requested_json, full_manifest, requested_count, created_at, started_at
            ) VALUES ('gw_interrupted', 'manual', 'running', '{}', 1, 20, ?, ?)
            """,
            (now.isoformat(), now.isoformat()),
        )
        conn.execute(
            """
            INSERT INTO ground_cache_leases (lease_name, holder, acquired_at, expires_at)
            VALUES ('prewarm', 'gw_interrupted', ?, ?)
            """,
            (now.isoformat(), (now + timedelta(hours=3)).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    relay_main._ensure_schema()

    conn = relay_main._connect()
    try:
        job = conn.execute("SELECT status, finished_at, error FROM ground_warm_jobs WHERE job_id='gw_interrupted'").fetchone()
        lease_count = conn.execute("SELECT COUNT(*) FROM ground_cache_leases").fetchone()[0]
    finally:
        conn.close()
    assert job["status"] == "failed"
    assert job["finished_at"]
    assert "interrupted" in str(job["error"]).lower()
    assert lease_count == 0


def test_authenticated_ground_endpoint_uses_server_airport_and_etag(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_AIRPORT_GROUND_ENABLED", "1")
    monkeypatch.setattr(relay_main, "_queue_ground_refresh", lambda *_args, **_kwargs: False)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000951"
    token = _activate(client, install_id)
    _seed_ground_layers()
    params = {
        "airport_iata": "ZRH",
        "radius_nm": 10,
        "install_id": install_id,
        "activation_token": token,
        "app_version": "0.5.1",
        "client_kind": "mobile_standalone",
        "device_type": "phone",
    }
    first = client.get("/v1/airport-ground", params=params)
    assert first.status_code == 200
    payload = first.json()
    assert payload["center"]["airport_icao"] == "LSZH"
    assert payload["coverage_radius_nm"] == 10
    assert payload["runways"][0]["label"] == "16/34"
    assert payload["map_features"][0]["road_class"] == "primary"
    assert payload["terrain"]["features"][0]["kind"] == "contour"
    assert first.headers["etag"]
    second = client.get("/v1/airport-ground", params=params, headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 304
    conn = relay_main._connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM usage WHERE service='airport_ground'").fetchone()[0] == 0
        access_row = conn.execute("SELECT install_fingerprint, network_tag FROM ground_access_events LIMIT 1").fetchone()
        assert access_row["install_fingerprint"] == relay_main._install_fingerprint(install_id)
        assert install_id not in dict(access_row).values()
    finally:
        conn.close()


def test_ground_endpoint_has_separate_bounded_rate_lane(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_AIRPORT_GROUND_ENABLED", "1")
    monkeypatch.setenv("RELAY_GROUND_INSTALL_RPM_LIMIT", "1")
    monkeypatch.setattr(relay_main, "_queue_ground_refresh", lambda *_args, **_kwargs: False)
    client = TestClient(relay_main.app)
    install_id = "00000000-0000-0000-0000-000000000952"
    token = _activate(client, install_id)
    params = {
        "airport_iata": "ZRH",
        "radius_nm": 5,
        "install_id": install_id,
        "activation_token": token,
        "app_version": "0.5.1",
        "client_kind": "mobile_standalone",
    }
    assert client.get("/v1/airport-ground", params=params).status_code == 200
    limited = client.get("/v1/airport-ground", params=params)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_ground_cache_never_relabels_small_radius_as_large(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(relay_main, "_queue_ground_refresh", lambda *_args, **_kwargs: False)
    airport = relay_main._ground_airport_record("ZRH")
    map_five = build_map_context_payload(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=5,
        features=[{"kind": "road", "road_class": "primary", "points": [[47.44, 8.54], [47.46, 8.56]]}],
        cache_state="fresh",
    )
    relay_main._store_ground_snapshot("map", 5, map_five)
    payload = relay_main._airport_ground_payload(airport, requested_radius_nm=20, queue_refresh=False)
    assert payload["map_features"] == []
    assert payload["sources"]["map_cache_state"] == "miss"
    assert layer_cache_key("map", "ZRH", "LSZH", 5) != layer_cache_key("map", "ZRH", "LSZH", 20)


def test_terrain_refresh_failure_keeps_stale_safe_copy(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    terrain = build_terrain_payload(
        airport_iata="ZRH",
        airport_icao="LSZH",
        center_lat=47.45,
        center_lon=8.55,
        radius_nm=20,
        features=[{"kind": "contour", "id": "t1", "points": [[47.4, 8.5], [47.5, 8.6]]}],
        cache_state="fresh",
    )
    relay_main._store_ground_snapshot("terrain", 20, terrain)
    old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    conn = relay_main._connect()
    try:
        conn.execute("UPDATE airport_ground_snapshots SET updated_at=? WHERE layer='terrain'", (old,))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(
        relay_main,
        "_fetch_ground_layer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("AWS unavailable")),
    )
    result = relay_main._refresh_ground_layer("terrain", relay_main._ground_airport_record("ZRH"), 20, force=True)
    assert result["status"] == "stale"
    row = relay_main._load_ground_snapshot("terrain", "ZRH", "LSZH", 20)
    assert row is not None
    assert "contour" in row["payload_json"]


def test_ground_warm_lease_and_monthly_due_are_persistent(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    assert relay_main._acquire_ground_lease("first") is True
    assert relay_main._acquire_ground_lease("second") is False
    relay_main._release_ground_lease("first")
    assert relay_main._acquire_ground_lease("second") is True
    relay_main._release_ground_lease("second")

    now = datetime.now(timezone.utc)
    conn = relay_main._connect()
    try:
        conn.execute(
            """
            INSERT INTO ground_warm_jobs (
                job_id, mode, status, requested_json, full_manifest, requested_count,
                created_at, finished_at, next_due_at
            ) VALUES ('gw_test', 'manual', 'completed', '{}', 1, 20, ?, ?, ?)
            """,
            (now.isoformat(), now.isoformat(), (now + timedelta(days=30)).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    assert relay_main._ground_full_warm_due() is False
    conn = relay_main._connect()
    try:
        conn.execute("UPDATE ground_warm_jobs SET next_due_at=? WHERE job_id='gw_test'", ((now - timedelta(seconds=1)).isoformat(),))
        conn.commit()
    finally:
        conn.close()
    assert relay_main._ground_full_warm_due() is True


def test_admin_can_queue_and_inspect_manual_ground_warm(tmp_path: Path, monkeypatch) -> None:
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RELAY_AIRPORT_GROUND_ENABLED", "1")
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "correct-horse")

    class CaptureExecutor:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def submit(self, *args: object) -> None:
            self.calls.append(args)

    executor = CaptureExecutor()
    monkeypatch.setattr(relay_main, "_ground_warm_executor", executor)
    client = TestClient(relay_main.app)
    headers = {"host": "network.beacontools.cc"}
    auth = ("operator", "correct-horse")
    queued = client.post(
        "/admin/api/cache-warm",
        headers=headers,
        auth=auth,
        json={"airports": ["ZRH"], "force": True},
    )
    assert queued.status_code == 202
    assert queued.json()["requested"] == 1
    assert len(executor.calls) == 1
    job_id = queued.json()["job_id"]
    status = client.get(f"/admin/api/cache-warm/{job_id}", headers=headers, auth=auth)
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["requested"]["airports"] == [{"airport": "ZRH", "max_radius_nm": 20}]

    override = client.post(
        "/admin/api/cache-warm/airport-override",
        headers=headers,
        auth=auth,
        json={"airport": "ZRH", "enabled": True, "pinned": True, "max_radius_nm": 10},
    )
    assert override.status_code == 200
    assert override.json()["max_radius_nm"] == 10
