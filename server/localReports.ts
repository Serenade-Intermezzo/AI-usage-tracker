import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const OFFSET = 8 * 3600;
const DAY = 86400;
export interface ReportEvent {
  at: number; thread: string; input: number; cached: number; output: number; total: number;
}
export interface PeriodReport {
  start: string; endExclusive: string; startAt: number; endAt: number;
  status: 'open' | 'closed'; total: number; input: number; cached: number; output: number;
  chats: number; events: number; activeDays: number; firstRecordedPeriod: boolean;
}
export interface LocalReports {
  scope: 'local'; timezone: 'Asia/Shanghai'; monthStartDay: number;
  generatedAt: number; firstEventAt: number | null;
  weekly: PeriodReport[]; monthly: PeriodReport[];
}
function localDate(at: number): Date { return new Date((at + OFFSET) * 1000); }
function dateString(at: number): string { return localDate(at).toISOString().slice(0, 10); }
function midnight(year: number, month: number, day: number): number {
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return Date.UTC(year, month, Math.min(day, lastDay)) / 1000 - OFFSET;
}
export function monthBoundary(at: number, day: number): number {
  const d = localDate(at);
  const current = midnight(d.getUTCFullYear(), d.getUTCMonth(), day);
  return at >= current ? current : midnight(d.getUTCFullYear(), d.getUTCMonth() - 1, day);
}
function nextMonth(start: number, day: number): number {
  const d = localDate(start);
  return midnight(d.getUTCFullYear(), d.getUTCMonth() + 1, day);
}
function weekBoundary(at: number): number {
  const d = localDate(at);
  return Math.floor((at + OFFSET) / DAY) * DAY - OFFSET - ((d.getUTCDay() + 6) % 7) * DAY;
}
export function validateMonthDay(day: unknown): number {
  if (typeof day !== 'number' || !Number.isInteger(day) || day < 1 || day > 31) {
    throw new Error('月度起始日必须是 1–31 的整数。');
  }
  return day;
}
export function aggregateReports(events: ReportEvent[], day: number, now: number): LocalReports {
  validateMonthDay(day);
  const eligible = events.filter((event) => event.at <= now);
  const first = eligible.length ? eligible.reduce((minimum, e) => Math.min(minimum, e.at), Infinity) : null;
  const build = (kind: 'week' | 'month'): PeriodReport[] => {
    const boundary = (at: number) => kind === 'week' ? weekBoundary(at) : monthBoundary(at, day);
    const next = (at: number) => kind === 'week' ? at + 7 * DAY : nextMonth(at, day);
    const bins = new Map<number, { row: PeriodReport; chats: Set<string>; days: Set<string> }>();
    for (let start = boundary(first ?? now); start <= now; start = next(start)) {
      const endAt = next(start);
      bins.set(start, { row: { start: dateString(start), endExclusive: dateString(endAt), startAt: start, endAt,
        status: endAt <= now ? 'closed' : 'open', total: 0, input: 0, cached: 0, output: 0,
        chats: 0, events: 0, activeDays: 0, firstRecordedPeriod: first !== null && start === boundary(first) }, chats: new Set(), days: new Set() });
    }
    for (const e of eligible) {
      const bin = bins.get(boundary(e.at));
      if (!bin) continue;
      bin.row.total += e.total; bin.row.input += e.input; bin.row.cached += e.cached; bin.row.output += e.output;
      bin.row.events++; bin.chats.add(e.thread); bin.days.add(dateString(e.at));
    }
    return [...bins.values()].map(({row, chats, days}) => ({...row, chats: chats.size, activeDays: days.size})).reverse();
  };
  return {scope: 'local', timezone: 'Asia/Shanghai', monthStartDay: day, generatedAt: now, firstEventAt: first,
    weekly: build('week'), monthly: build('month')};
}
function atomicJson(file: string, value: unknown): void {
  const temporary = file + '.tmp';
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n', {mode: 0o600});
  fs.renameSync(temporary, file);
}
export function createLocalReports(dataDir: string, deviceId: string) {
  const settingsFile = path.join(dataDir, 'report-settings.json');
  const reportFile = path.join(dataDir, 'local-reports.json');
  let day = 1;
  if (fs.existsSync(settingsFile)) day = validateMonthDay(JSON.parse(fs.readFileSync(settingsFile, 'utf8')).monthStartDay);
  function refresh(): LocalReports {
    if (fs.existsSync(settingsFile)) day = validateMonthDay(JSON.parse(fs.readFileSync(settingsFile, 'utf8')).monthStartDay);
    const database = new DatabaseSync(path.join(dataDir, 'codex-usage.sqlite'), {readOnly: true});
    let events: ReportEvent[];
    try {
      events = database.prepare(`SELECT observed_at AS at, thread_id AS thread,
        input_tokens AS input, cached_input_tokens AS cached, output_tokens AS output, total_tokens AS total
        FROM session_part_token_events WHERE device_id = ? ORDER BY observed_at`).all(deviceId) as unknown as ReportEvent[];
    } finally { database.close(); }
    const reports = aggregateReports(events, day, Math.floor(Date.now() / 1000));
    atomicJson(reportFile, reports);
    return reports;
  }
  return {refresh, setMonthDay(value: unknown) {
    const next = validateMonthDay(value);
    atomicJson(settingsFile, {monthStartDay: next, timezone: 'Asia/Shanghai'});
    day = next;
    return refresh();
  }};
}
