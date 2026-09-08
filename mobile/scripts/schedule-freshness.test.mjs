import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { projectStandaloneBoardLocally } from '../src/domain/boardLifecycle.ts';

const now = Date.parse('2026-09-09T12:00:00Z');
const row = {
  id: 'fake-movement', view: 'departures', display_time: '13:00', flight_display: 'ZZ101',
  callsign: 'FAKE101', sched_time: '2026-09-09T13:00:00Z',
  gate: 'FAKE-G1', gate_display: 'FAKE-G1', terminal_display: 'T1', terminal_gate_display: 'T1 / FAKE-G1',
  field_sources: { gate: { provider: 'aviationstack', fetched_at: '2026-09-09T11:00:00Z', expires_at: '2026-09-09T11:15:00Z' } }
};
const board = {
  schema_version: 'mobile-board-v2', source: 'real', generated_at: '2026-09-09T11:00:00Z',
  source_fetched_at: '2026-09-09T11:00:00Z', expires_at: '2026-09-16T11:00:00Z',
  snapshot_id: 'fake-snapshot', cache_state: 'fresh', refresh_after_s: 900,
  rows_per_direction: 50, departures: [row], arrivals: []
};
const projected = projectStandaloneBoardLocally(board, now);
assert.equal(projected.source_fetched_at, board.source_fetched_at);
assert.equal(projected.snapshot_id, board.snapshot_id);
assert.equal(projected.cache_state, 'stale');
assert.equal(projected.departures[0].gate, '');
assert.equal(projected.departures[0].terminal_display, 'T1');
assert.equal(board.departures[0].gate, 'FAKE-G1');
assert.deepEqual(projectStandaloneBoardLocally(board, now + 8 * 86400_000).departures, []);
assert.deepEqual(projectStandaloneBoardLocally(board, now + 86400_000).departures, []);
assert.deepEqual(projectStandaloneBoardLocally({ ...board, coverage_to: '2026-09-09T11:59:00Z' }, now).departures, []);
assert.equal(projectStandaloneBoardLocally({ ...board, source_fetched_at: '', generated_at: '' }, now).cache_state, 'unknown');

// Exercise the actual mobile upsert against SQLite: repeated and older cached
// snapshots must neither increment observations nor regress the saved state.
const source = readFileSync(new URL('../src/storage/standaloneHistory.ts', import.meta.url), 'utf8');
const schema = source.match(/CREATE TABLE IF NOT EXISTS standalone_fids_history \([\s\S]+?\n        \);/)[0];
const upsert = source.match(/INSERT INTO standalone_fids_history \([\s\S]+?\n        `/)[0].replace(/\s*`$/, '');
const columns = upsert.match(/INSERT INTO standalone_fids_history \(([\s\S]+?)\) VALUES/)[1]
  .split(',').map(c => c.trim()).filter(c => c !== 'observation_count');
const database = new DatabaseSync(':memory:');
database.exec(schema);
database.exec('CREATE UNIQUE INDEX movement_identity ON standalone_fids_history(movement_key)');
const write = (timestamp, status) => {
  const values = { movement_key: 'fake-movement', airport_key: 'ZRH', airport_iata: 'ZRH',
    snapshot_ts: timestamp, first_seen_ts: timestamp, last_seen_ts: timestamp,
    view: 'departures', callsign: 'FAKE101', row_json: '{}', status };
  database.prepare(upsert).run(...columns.map(c => values[c] ?? null));
};
write('2026-09-09T10:00:00Z', 'scheduled');
write('2026-09-09T10:00:00Z', 'scheduled');
assert.equal(database.prepare('SELECT observation_count FROM standalone_fids_history').get().observation_count, 1);
write('2026-09-09T11:00:00Z', 'departed');
write('2026-09-09T10:00:00Z', 'scheduled');
const saved = database.prepare('SELECT observation_count, status FROM standalone_fids_history').get();
assert.equal(saved.observation_count, 2);
assert.equal(saved.status, 'departed');
database.close();
console.log('Schedule freshness, enrichment expiry, and history replay checks passed.');
