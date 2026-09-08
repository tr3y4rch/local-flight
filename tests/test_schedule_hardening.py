from __future__ import annotations

import multiprocessing
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from localflight.sources.web.aerodatabox_plan import InvalidFidsPayload, plan_fids, validate_fids
from localflight.sources.web.schedule_fusion import enrich_schedule_records
from relay.schedule_service import ScheduleService, epoch, suspicious


def record():
    return {"callsign": "FAKE101", "flight_number": "ZZ101", "direction": "DEP",
            "origin_iata": "ZRH", "destination_iata": "LHR", "status": "scheduled",
            "scheduled": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}


class Backend:
    def __init__(self, path, delay=0):
        self.path, self.delay = str(path), delay

    def policy_key(self): return "fake-policy"
    def allowed(self, provider): return True
    def retention_seconds(self, provider): return 7 * 86400
    def enrichment_enabled(self): return False

    def fetch(self, airport, timezone_name, grace, horizon):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("INSERT INTO attempts VALUES (1)")
        conn.commit()
        conn.close()
        time.sleep(self.delay)
        now = datetime.now(timezone.utc)
        return {"provider": "aerodatabox", "generated_at": now.isoformat(), "records": [record()],
                "meta": {"source_fetched_at": now.isoformat(),
                         "coverage_from": (now - timedelta(minutes=grace + 1)).isoformat(),
                         "coverage_to": (now + timedelta(hours=horizon, minutes=15)).isoformat(),
                         "coverage_complete": True}}


def service(tmp_path, **kwargs):
    path = tmp_path / 'schedule.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE attempts(n INTEGER)')
    conn.close()
    return ScheduleService(path, Backend(path, 0.1), **kwargs)


def _parallel_reader(path, ready, go, result):
    svc = ScheduleService(path, Backend(path, 0.2))
    ready.put(True)
    go.wait(10)
    try:
        with ThreadPoolExecutor(max_workers=50) as pool:
            rows = list(pool.map(lambda _: svc.read(airport='ZRH', timezone_name='Europe/Zurich', grace=30, horizon=12), range(50)))
        result.put(len({row['snapshot_id'] for row in rows}))
    except Exception as exc:
        result.put(str(exc))
    finally:
        svc.close()


def test_hundred_clients_two_processes_one_refresh(tmp_path):
    svc = service(tmp_path)
    svc.close()
    ctx = multiprocessing.get_context('spawn')
    ready, result, go = ctx.Queue(), ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=_parallel_reader, args=(svc.path, ready, go, result)) for _ in range(2)]
    for p in processes: p.start()
    for _ in processes: assert ready.get(timeout=15)
    go.set()
    for _ in processes: assert result.get(timeout=45) == 1
    for p in processes:
        p.join(10)
        assert p.exitcode == 0
    with svc.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 1


def test_wider_window_cannot_bypass_timer_and_narrower_reuses(tmp_path):
    svc = service(tmp_path)
    try:
        first = svc.read(airport='ZRH', timezone_name='Europe/Zurich', grace=30, horizon=12)
        narrow = svc.read(airport='ZRH', timezone_name='UTC', grace=15, horizon=6)
        wider = svc.read(airport='ZRH', timezone_name='UTC', grace=60, horizon=24)
        assert first['snapshot_id'] == narrow['snapshot_id'] == wider['snapshot_id']
        assert narrow['coverage_complete']
        assert not wider['coverage_complete']
        assert first['source_fetched_at'] == wider['source_fetched_at']
        with svc.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 1
    finally: svc.close()


def test_expired_generation_cannot_publish(tmp_path):
    svc = service(tmp_path)
    try:
        svc.read(airport='ZRH', timezone_name='UTC', grace=30, horizon=12)
        svc.close()
        lane = svc.lane('ZRH')
        with svc.connect() as conn:
            conn.execute('UPDATE schedule_refresh_state SET generation=generation+1, lease_until=?', (time.time()+60,))
            before = svc._load(conn, lane)
        assert not svc._publish(lane, 1, svc.backend.fetch('ZRH', 'UTC', 30, 12), published=True)
        with svc.connect() as conn:
            assert svc._load(conn, lane)['meta']['snapshot_id'] == before['meta']['snapshot_id']
    finally: svc.close()


def test_planning_includes_lookback_margin_and_bounded_overlap():
    now = datetime(2026, 10, 25, 0, 45, tzinfo=timezone.utc)
    windows = plan_fids(grace_minutes=30, horizon_hours=12, now=now)
    assert len(windows) == 2
    assert windows[0].start <= now - timedelta(minutes=30)
    assert windows[-1].end >= now + timedelta(hours=12, minutes=15)
    assert all(w.params(now=now)['durationMinutes'] <= 720 for w in windows)
    assert windows[1].start < windows[0].end
    assert len(plan_fids(grace_minutes=30, horizon_hours=12, max_minutes=1440)) == 1


@pytest.mark.parametrize('payload', [{}, {'departures': []}, {'departures': [], 'arrivals': None},
                                     {'departures': [{}], 'arrivals': []}])
def test_invalid_response_never_becomes_empty_board(payload):
    with pytest.raises(InvalidFidsPayload): validate_fids(payload)


def test_valid_quiet_period_and_enrichment_expiry():
    assert validate_fids({'departures': [], 'arrivals': []}) == {'departures': [], 'arrivals': []}
    now = datetime.now(timezone.utc)
    primary = record()
    secondary = dict(primary, gate='FAKE-G1', aircraft_type='A320', status='cancelled')
    unrelated = dict(secondary, callsign='FAKE999', flight_number='ZZ999')
    rows, meta = enrich_schedule_records([primary], [secondary, unrelated], fetched_at=now.isoformat(), now=now)
    assert len(rows) == 1 and rows[0]['status'] == 'scheduled' and rows[0]['gate'] == 'FAKE-G1'
    rows, _ = enrich_schedule_records([primary], [secondary], fetched_at=now.isoformat(), now=now+timedelta(minutes=16))
    assert not rows[0].get('gate') and rows[0]['aircraft_type'] == 'A320'
    rows, _ = enrich_schedule_records([primary], [secondary], fetched_at=now.isoformat(), now=now+timedelta(hours=1))
    assert not rows[0].get('aircraft_type')


def test_stale_returns_without_waiting_for_background_refresh(tmp_path):
    import json
    svc = service(tmp_path)
    try:
        first = svc.read(airport='ZRH', timezone_name='UTC', grace=30, horizon=12)
        svc.backend.delay = 0.5
        lane = svc.lane('ZRH')
        with svc.connect() as conn:
            payload = svc._load(conn, lane)
            payload['meta']['source_fetched_at'] = (datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat()
            conn.execute("UPDATE schedule_provider_cache SET payload=? WHERE lane=? AND provider='published'", (json.dumps(payload), lane))
            conn.execute('UPDATE schedule_refresh_state SET next_at=0 WHERE lane=?', (lane,))
        start = time.monotonic()
        stale = svc.read(airport='ZRH', timezone_name='UTC', grace=30, horizon=12)
        assert time.monotonic() - start < 0.4
        assert stale['cache_state'] == 'stale'
        assert stale['source_fetched_at'] != first['source_fetched_at']
    finally: svc.close()


def test_cold_failure_has_retry_after_and_no_empty_success(tmp_path):
    svc = service(tmp_path, cold_wait=1)
    svc.backend.fetch = lambda *args: (_ for _ in ()).throw(RuntimeError('fake-private-provider-message'))
    try:
        with pytest.raises(HTTPException) as failure:
            svc.read(airport='ZRH', timezone_name='UTC', grace=30, horizon=12)
        assert failure.value.status_code == 503
        assert int(failure.value.headers['Retry-After']) > 0
        assert 'fake-private' not in failure.value.detail
    finally: svc.close()


def test_primary_publication_does_not_wait_for_enrichment(tmp_path):
    import threading
    svc = service(tmp_path)
    entered, release = threading.Event(), threading.Event()
    svc.backend.enrichment_enabled = lambda: True
    def enrich(*args):
        entered.set()
        release.wait(5)
        raise RuntimeError('fake enrichment unavailable')
    svc.backend.enrich = enrich
    try:
        result = svc.read(airport='ZRH', timezone_name='UTC', grace=30, horizon=12)
        assert result['records']
        assert entered.wait(1)
        assert not release.is_set()
    finally:
        release.set()
        svc.close()


def test_retention_blocks_reads_even_before_physical_prune(tmp_path):
    svc = service(tmp_path, cold_wait=0)
    try:
        svc.cold_wait = 1
        svc.read(airport='ZRH', timezone_name='UTC', grace=30, horizon=12)
        with svc.connect() as conn:
            conn.execute('UPDATE schedule_provider_cache SET expires_at=0')
            assert svc._load(conn, svc.lane('ZRH')) is None
    finally: svc.close()


def test_busy_overlap_requires_independent_empty_confirmation(tmp_path):
    svc = service(tmp_path)
    try:
        svc.read(airport='ZRH', timezone_name='UTC', grace=30, horizon=12)
        svc.close()
        lane = svc.lane('ZRH')
        busy = svc.backend.fetch('ZRH', 'UTC', 30, 12)
        busy['records'] = [dict(record(), callsign=f'FAKE{i}') for i in range(20)]
        with svc.connect() as conn:
            conn.execute('UPDATE schedule_refresh_state SET lease_until=?', (time.time()+60,))
        assert svc._publish(lane, 1, busy, published=True)
        empty = svc.backend.fetch('ZRH', 'UTC', 30, 12)
        empty['records'] = []
        empty['meta']['validated_empty'] = True
        with pytest.raises(ValueError): svc._publish(lane, 1, empty, published=True)
        with svc.connect() as conn:
            assert len(svc._load(conn, lane)['records']) == 20
            conn.execute('UPDATE schedule_refresh_state SET generation=2')
        assert svc._publish(lane, 2, empty, published=True)
        with svc.connect() as conn: assert svc._load(conn, lane)['records'] == []
    finally: svc.close()


def test_waiting_provider_request_obeys_new_global_cooldown(tmp_path, monkeypatch):
    import relay.schedule_transport as transport_module
    path = tmp_path / 'transport.db'
    def connect(): return sqlite3.connect(path)
    with connect() as conn: transport_module.ensure_schema(conn)
    transport = transport_module.ProviderTransport(connect, provider='aerodatabox', credential='fake')
    transport._slot()
    monkeypatch.setattr(transport_module.time, 'sleep', lambda _: transport._defer(120))
    with pytest.raises(HTTPException):
        transport.get(lambda: pytest.fail('request escaped the global cooldown'), reserve_retry=lambda: None)


def test_managed_snapshot_read_enforces_stale_ceiling_and_safe_metadata(tmp_path, monkeypatch):
    from localflight.storage import flights_store
    monkeypatch.setattr(flights_store, 'config_path', lambda: tmp_path / 'config.json')
    monkeypatch.setattr(flights_store, '_legacy_store_root', lambda: tmp_path / 'empty')
    now = datetime.now(timezone.utc)
    metadata = {'managed': True, 'source_fetched_at': (now-timedelta(hours=25)).isoformat(),
                'expires_at': (now+timedelta(days=6)).isoformat(), 'provider_errors': {'fake': 'private-debug-data'}}
    flights_store.save_snapshot('ZRH', [], metadata=metadata)
    assert flights_store.load_latest_snapshot_path('ZRH') is None
    assert 'provider_errors' not in flights_store.safe_schedule_metadata(metadata)
    flights_store.save_snapshot('ZRH', [], metadata={'managed': True})
    assert flights_store.latest_schedule_metadata('ZRH')['cache_state'] == 'unknown'


def test_relay_route_shares_desktop_and_mobile_provider_work(tmp_path, monkeypatch):
    import types
    from fastapi.testclient import TestClient
    import relay.main as main
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'relay.db'))
    monkeypatch.setenv('AERODATABOX_API_KEY', 'fake-adb-key')
    monkeypatch.setenv('RELAY_SCHEDULE_PROVIDER', 'aerodatabox')
    monkeypatch.setenv('RELAY_SCHEDULE_V2_ENABLED', '1')
    monkeypatch.setenv('RELAY_SCHEDULE_V2_AIRPORTS', 'ZRH')
    monkeypatch.setenv('RELAY_AERODATABOX_REQUESTS_PER_SECOND', '1000')
    main._ensure_schema()
    monkeypatch.setattr(main, '_resolve_access', lambda **kw: {'subject_key': 'fake-consumer', 'plan': 'managed', 'limit': 1000})
    monkeypatch.setattr(main, '_licensed_schedule_snapshot_allowed', lambda provider: True)
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params'])
        return types.SimpleNamespace(status_code=200, json=lambda: {'departures': [{
            'number': 'ZZ101', 'callSign': 'FAKE101', 'status': 'Expected',
            'departure': {'airport': {'iata': 'ZRH'}, 'scheduledTime': {'utc': record()['scheduled']}},
            'arrival': {'airport': {'iata': 'LHR'}}}], 'arrivals': []})
    monkeypatch.setattr(main._req, 'get', get)
    client = TestClient(main.app)
    args = {'airport_iata': 'ZRH', 'timezone': 'Europe/Zurich', 'install_id': '00000000-0000-4000-8000-000000000001'}
    try:
        desktop = client.get('/v1/schedule', params=args)
        phone = client.get('/v1/schedule', params={**args, 'client_kind': 'mobile_standalone', 'display_horizon_hours': 6})
        assert desktop.status_code == phone.status_code == 200
        assert desktop.json()['snapshot_id'] == phone.json()['snapshot_id']
        monkeypatch.setattr(main, '_require_mobile_standalone_access', lambda **kw: {})
        board = client.get('/v1/mobile/board', params={**args, 'client_kind': 'mobile_standalone', 'app_version': '0.6.0'})
        assert board.status_code == 200
        assert board.json()['snapshot_id'] == desktop.json()['snapshot_id']
        assert len(board.json()['departures']) == 1
        assert len(calls) == 2  # One complete planned sequence, not one per consumer.
        with main._schedule_service().connect() as conn:
            accesses = conn.execute('SELECT SUM(accesses) FROM schedule_refresh_state').fetchone()[0]
        monkeypatch.setattr(main, '_resolve_access', lambda **kw: (_ for _ in ()).throw(HTTPException(401, 'Access required')))
        assert client.get('/v1/schedule', params=args).status_code == 401
        with main._schedule_service().connect() as conn:
            assert conn.execute('SELECT SUM(accesses) FROM schedule_refresh_state').fetchone()[0] == accesses
    finally:
        main._schedule_service().close()
        main._schedule_services.clear()


def test_managed_job_never_uses_direct_sources(monkeypatch):
    from localflight.scheduler import jobs
    from localflight.storage.config import AppConfig
    from localflight.sources.web import aviationstack_client
    monkeypatch.setenv('AERODATABOX_API_KEY', 'fake-local-adb')
    monkeypatch.setenv('AVIATIONSTACK_API_KEY', 'fake-local-as')
    monkeypatch.setattr(aviationstack_client, 'fetch_relay_schedule_records', lambda **kw: ([], {'source_fetched_at': '', 'managed': True}))
    def forbidden(*args, **kwargs): raise AssertionError('direct provider called')
    monkeypatch.setattr(jobs, '_fetch_aviationstack_records_windowed', forbidden)
    monkeypatch.setattr(jobs, '_enrich_with_adsbexchange', forbidden)
    monkeypatch.setattr(jobs, '_enrich_with_opensky', forbidden)
    assert jobs._fetch_real(AppConfig(data_route='relay', source='real')) == []
    monkeypatch.setattr(aviationstack_client, 'fetch_relay_schedule_records', lambda **kw: (_ for _ in ()).throw(RuntimeError('fake relay offline')))
    with pytest.raises(RuntimeError, match='fake relay offline'):
        jobs._fetch_real(AppConfig(data_route='relay', source='real'))


def test_retained_source_timestamp_deduplicates_history(tmp_path, monkeypatch):
    from localflight.storage import history, flights_store
    from localflight.core.models import AirportRef, Flight, FlightDirection, FlightTime
    from localflight.storage.config import AppConfig
    monkeypatch.setattr(history, '_db_path', lambda: tmp_path / 'history.db')
    monkeypatch.setattr(flights_store, 'config_path', lambda: tmp_path / 'config.json')
    monkeypatch.setattr(flights_store, '_legacy_store_root', lambda: tmp_path / 'empty')
    now = datetime.now(timezone.utc)
    flight = Flight(FlightDirection.DEPARTURE, AirportRef(iata='ZRH'), 'FAKE101', times=FlightTime(scheduled=now), source='aerodatabox')
    metadata = {'source_fetched_at': (now-timedelta(hours=1)).isoformat(), 'expires_at': (now+timedelta(days=6)).isoformat(), 'managed': True}
    path = flights_store.save_snapshot('ZRH', [flight], metadata=metadata)
    import json
    assert json.loads(path.read_text())['generated_at'] == metadata['source_fetched_at']
    cfg = AppConfig(data_route='relay', airport_iata='ZRH')
    history.write_snapshot_to_history([flight], cfg, snapshot_meta=metadata)
    history.write_snapshot_to_history([flight], cfg, snapshot_meta=metadata)
    with history._connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM flights').fetchone()[0] == 1
        assert conn.execute('SELECT observation_count FROM history_movements').fetchone()[0] == 1
        conn.execute("UPDATE flights SET expires_at='2000-01-01T00:00:00+00:00'")
        conn.execute("UPDATE history_movements SET expires_at='2000-01-01T00:00:00+00:00'")
    assert history.query_recent(airport_iata='ZRH') == []


def test_provider_pause_retry_after_and_rotation(tmp_path):
    import types
    from relay.schedule_transport import ProviderTransport, ensure_schema
    path = tmp_path / 'transport.db'
    def connect(): return sqlite3.connect(path)
    with connect() as conn: ensure_schema(conn)
    transport = ProviderTransport(connect, provider='aerodatabox', credential='fake-key')
    with pytest.raises(HTTPException):
        transport.get(lambda: types.SimpleNamespace(status_code=401), reserve_retry=lambda: None)
    with pytest.raises(HTTPException): transport.check_available()
    rotated = ProviderTransport(connect, provider='aerodatabox', credential='fake-rotated-key')
    rotated.check_available()
    with pytest.raises(HTTPException) as failure:
        rotated.get(lambda: types.SimpleNamespace(status_code=429, headers={'Retry-After': '120'}), reserve_retry=lambda: None)
    assert failure.value.headers['Retry-After'] == '120'
    with pytest.raises(HTTPException): rotated.check_available()


def test_enrichment_allowance_is_atomic_and_does_not_consume_fallback_budget_on_rejection(tmp_path, monkeypatch):
    import relay.main as main
    from relay.schedule_transport import enrichment
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'relay.db'))
    monkeypatch.setenv('RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT', '10')
    monkeypatch.setenv('RELAY_AVIATIONSTACK_UPSTREAM_DAILY_LIMIT', '10')
    main._ensure_schema()
    token = enrichment.set(True)
    try:
        main._reserve_aviationstack_request()
        main._reserve_aviationstack_request()
        with pytest.raises(main.UpstreamBudgetExceeded): main._reserve_aviationstack_request()
        assert main._get_usage('shared:upstream', 'aviationstack_upstream', main._month_key()) == 2
    finally: enrichment.reset(token)
    main._reserve_aviationstack_request()
    assert main._get_usage('shared:upstream', 'aviationstack_upstream', main._month_key()) == 3


def test_split_sequence_reserved_before_any_provider_request(tmp_path, monkeypatch):
    import relay.main as main
    monkeypatch.setenv('DB_PATH', str(tmp_path / 'relay.db'))
    monkeypatch.setenv('AERODATABOX_API_KEY', 'fake-adb-key')
    monkeypatch.setenv('RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT', '2')
    monkeypatch.setenv('RELAY_AERODATABOX_UPSTREAM_DAILY_UNITS_LIMIT', '2')
    main._ensure_schema()
    monkeypatch.setattr(main._req, 'get', lambda *args, **kwargs: pytest.fail('partial sequence went outbound'))
    with pytest.raises(main.UpstreamBudgetExceeded):
        main._aerodatabox_upstream_payload(airport_iata='ZRH', display_grace_minutes=30, display_horizon_hours=12)
    assert main._get_usage('shared:upstream', 'aerodatabox_upstream_units', main._month_key()) == 0


def test_provider_transient_retries_are_bounded_and_accounted(tmp_path, monkeypatch):
    import types
    import relay.schedule_transport as transport_module
    path = tmp_path / 'transport.db'
    def connect(): return sqlite3.connect(path)
    with connect() as conn: transport_module.ensure_schema(conn)
    transport = transport_module.ProviderTransport(connect, provider='aerodatabox', credential='fake', rps=10000)
    monkeypatch.setattr(transport_module.time, 'sleep', lambda _: None)
    requests, reservations = [], []
    def request():
        requests.append(1)
        return types.SimpleNamespace(status_code=500)
    response = transport.get(request, reserve_retry=lambda: reservations.append(1))
    assert response.status_code == 500
    assert len(requests) == 3 and len(reservations) == 2


def test_aerodatabox_times_and_uncertain_status_are_preserved():
    from localflight.decode.mappings.aerodatabox import aerodatabox_to_raw_records
    from localflight.decode.normalize import normalize_flights
    now = datetime.now(timezone.utc).isoformat()
    row = {'number': 'ZZ101', 'callSign': 'FAKE101', 'status': 'CanceledUncertain',
           'departure': {'scheduledTime': {'utc': now}, 'revisedTime': {'utc': now}, 'quality': ['Approximate']},
           'arrival': {'airport': {'iata': 'LHR'}}}
    rows = aerodatabox_to_raw_records({'departures': [row], 'arrivals': []}, airport_iata='ZRH')
    assert rows[0]['status'] == 'unknown' and rows[0]['status_uncertain']
    assert rows[0]['actual'] is None and rows[0]['estimated'] == now
    row['status'] = 'Departed'
    row['departure']['quality'] = ['Live']
    rows = aerodatabox_to_raw_records({'departures': [row], 'arrivals': []}, airport_iata='ZRH')
    flight = normalize_flights(rows, airport_iata='ZRH', airport_icao='LSZH', source_name='aerodatabox')[0]
    assert flight.times.actual and not flight.times.estimated
    assert flight.movement_quality == ('Live',)


def test_backup_excludes_provider_data_and_keeps_access_records(tmp_path):
    from relay.access.backup import AccessBackupManager
    path = tmp_path / 'relay.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE schedule_provider_cache(payload TEXT)')
        conn.execute("INSERT INTO schedule_provider_cache VALUES ('fake-provider-data')")
        conn.execute('CREATE TABLE fake_access_records(value TEXT)')
        conn.execute("INSERT INTO fake_access_records VALUES ('fake-access-record')")
    manager = AccessBackupManager(database_path=path, backup_directory=tmp_path / 'backups',
                                  active_key_id='fake-key-id', active_secret='fake-secret-not-real-1234567890')
    backup = manager.create_backup()
    target = tmp_path / 'restored.db'
    manager.restore(backup.path, target)
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT COUNT(*) FROM schedule_provider_cache').fetchone()[0] == 0
        assert conn.execute('SELECT value FROM fake_access_records').fetchone()[0] == 'fake-access-record'
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM schedule_provider_cache').fetchone()[0] == 1
