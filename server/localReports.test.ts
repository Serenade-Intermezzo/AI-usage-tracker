import test from 'node:test';
import assert from 'node:assert/strict';
import {aggregateReports, monthBoundary, validateMonthDay, type ReportEvent} from './localReports.js';
const at = (text: string) => Date.parse(text + '+08:00') / 1000;
const event = (text: string, total = 100): ReportEvent => ({at: at(text), thread: 'same-chat', input: total - 10, cached: 20, output: 10, total});
test('Shanghai Monday and billing-month boundaries assign every event once, including exact midnight', () => {
  const rows = [event('2026-10-11T23:59:59'), event('2026-10-12T00:00:00'), event('2026-10-15T23:59:59'), event('2026-10-16T00:00:00')];
  const r = aggregateReports(rows, 16, at('2026-10-20T00:00:00'));
  assert.equal(r.weekly.find((x) => x.start === '2026-10-05')?.total, 100);
  assert.equal(r.weekly.find((x) => x.start === '2026-10-12')?.total, 300);
  assert.equal(r.monthly.find((x) => x.start === '2026-09-16')?.total, 300);
  assert.equal(r.monthly.find((x) => x.start === '2026-10-16')?.total, 100);
  assert.equal(r.monthly[0].status, 'open');
  assert.equal(r.monthly[1].status, 'closed');
  assert.equal(r.weekly.reduce((sum, row) => sum + row.total, 0), 400);
  assert.equal(r.monthly.reduce((sum, row) => sum + row.total, 0), 400);
  assert.equal(r.weekly.find((x) => x.start === '2026-10-12')?.chats, 1);
});
test('31st uses last day in short months, handles leap years and December rollover', () => {
  for (const [stamp, expected] of [
    ['2026-03-01T00:00:00','2026-02-28T00:00:00'],
    ['2028-03-01T00:00:00','2028-02-29T00:00:00'],
    ['2027-01-01T00:00:00','2026-12-31T00:00:00']
  ]) assert.equal(monthBoundary(at(stamp), 31), at(expected));
  const r = aggregateReports([event('2026-01-31T00:00:00'), event('2026-02-28T00:00:00'), event('2026-03-31T00:00:00')], 31, at('2026-04-01T00:00:00'));
  assert.deepEqual(r.monthly.map((x) => x.total), [100, 100, 100]);
  assert.deepEqual(r.monthly.map((x) => x.start), ['2026-03-31','2026-02-28','2026-01-31']);
});
test('changing month day reaggregates history; empty periods have zeros and future events are excluded', () => {
  const events = [event('2026-10-10T00:00:00'), event('2026-10-20T00:00:00'), event('2026-12-01T00:00:00')];
  const now = at('2026-11-20T00:00:00');
  const r = aggregateReports(events, 16, now);
  assert.deepEqual(r.monthly.map((x) => x.total), [0, 100, 100]);
  assert.equal(aggregateReports(events, 1, now).monthly.find((x) => x.start === '2026-10-01')?.total, 200);
  assert.equal(r.monthly[2].firstRecordedPeriod, true);
  const empty = aggregateReports([], 1, now);
  assert.equal(empty.firstEventAt, null);
  assert.equal(empty.weekly.length, 1);
  assert.equal(empty.monthly[0].total, 0);
  for (const bad of [0,32,1.5,'16',null]) assert.throws(() => validateMonthDay(bad));
});
