import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { aggregateReports, validateMonthDay, type ReportEvent } from './localReports.js';
import { atomicJson, validFingerprint, validId } from './installation.js';
import type { DeviceRegistry } from './sync/registry.js';

export interface Member {id: string; name: string;}
interface TeamDevice {deviceId: string; memberId: string; installId: string; label: string;}
interface MeterEvent extends ReportEvent {device: string; model: string;}
export function accountFingerprint(dataDir: string): string | null {
  const file = path.join(dataDir, 'account-scope.json');
  if (!fs.existsSync(file)) return null;
  const value = JSON.parse(fs.readFileSync(file, 'utf8')).fingerprint;
  return validFingerprint(value) ? value : null;
}

/** Membership is independent of the shared OpenAI login. A device is pinned on first enrollment. */
export function createTeam(options: {
  dataDir: string; accountFingerprint: string; self: TeamDevice | null;
  memberName: string; registry: DeviceRegistry; heartbeatMs: number;
  now?: () => number;
  selfScannedThrough?: () => number | null;
  selfError?: () => string | null;
}) {
  if (!validFingerprint(options.accountFingerprint)) throw new Error('多人统计需要有效的目标账号指纹。');
  const now = options.now ?? (() => Math.floor(Date.now() / 1000));
  const file = path.join(options.dataDir, 'team.sqlite');
  const db = new DatabaseSync(file);
  db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS members (id TEXT PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS team_devices (device_id TEXT PRIMARY KEY, member_id TEXT NOT NULL REFERENCES members(id),
      install_id TEXT NOT NULL, label TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS team_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);`);
  const pinned = db.prepare("SELECT value FROM team_meta WHERE key='account'").get() as {value: string} | undefined;
  if (pinned && pinned.value !== options.accountFingerprint) { db.close(); throw new Error('汇总中心已绑定其他账号；请使用新的数据目录。'); }
  db.prepare("INSERT OR IGNORE INTO team_meta VALUES ('account', ?)").run(options.accountFingerprint);
  function members(): Member[] { return db.prepare('SELECT id, name FROM members ORDER BY name, id').all() as unknown as Member[]; }
  function saveMember(name: unknown, id = crypto.randomUUID() as string): Member {
    if (!validId(id) || typeof name !== 'string' || !name.trim() || name.trim().length > 80) throw new Error('成员名称需为 1–80 个字符。');
    if (members().some(m => m.id !== id && m.name.toLocaleLowerCase() === name.trim().toLocaleLowerCase())) {
      throw new Error('已有同名成员，请使用不同的姓名或昵称。');
    }
    db.prepare('INSERT INTO members VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name').run(id, name.trim());
    return {id, name: name.trim()};
  }
  function devices(): TeamDevice[] {
    return db.prepare('SELECT device_id AS deviceId, member_id AS memberId, install_id AS installId, label FROM team_devices ORDER BY device_id').all() as unknown as TeamDevice[];
  }
  function removeMember(id: string): void {
    if (!members().some(m => m.id === id)) throw new Error('成员不存在。');
    if (id === options.self?.memberId) throw new Error('不能删除汇总中心当前使用者。');
    if (devices().some(d => d.memberId === id)) throw new Error('该成员已关联设备，请保留其成员和历史归属；可以修改姓名。');
    db.prepare('DELETE FROM members WHERE id = ?').run(id);
    archive();
  }
  function enroll(device: TeamDevice): void {
    if (!validId(device.deviceId) || !validId(device.memberId) || !device.installId || device.installId.length > 100) throw new Error('成员或设备标识无效。');
    if (!members().some(m => m.id === device.memberId)) throw new Error('该成员尚未登记，请由汇总中心添加成员后重新获取接入配置。');
    const previous = devices().find(d => d.deviceId === device.deviceId);
    if (previous && (previous.memberId !== device.memberId || previous.installId !== device.installId)) {
      throw new Error('该设备编号已绑定另一成员或安装实例，请使用独立的数据目录和设备编号。');
    }
    db.prepare(`INSERT INTO team_devices VALUES (?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET label=excluded.label`)
      .run(device.deviceId, device.memberId, device.installId, device.label.slice(0, 80));
  }
  if (options.self) {
    if (!members().some(m => m.id === options.self!.memberId)) saveMember(options.memberName, options.self.memberId);
    enroll(options.self);
  }
  const settingsFile = path.join(options.dataDir, 'report-settings.json');
  function monthDay(): number {
    return fs.existsSync(settingsFile) ? validateMonthDay(JSON.parse(fs.readFileSync(settingsFile, 'utf8')).monthStartDay) : 1;
  }
  function setMonthDay(value: unknown): void { atomicJson(settingsFile, {monthStartDay: validateMonthDay(value), timezone: 'Asia/Shanghai'}); }
  function validateIdentity(body: Record<string, unknown>): void {
    if (body.accountFingerprint !== options.accountFingerprint) throw new Error('账号范围不一致；仅接收同一 OpenAI 账号的可确认用量。');
    if (body.provider !== undefined && body.provider !== 'codex') throw new Error('只支持 Codex GUI / CLI 用量。');
    enroll({deviceId: body.deviceId as string, memberId: body.memberId as string, installId: body.installId as string,
      label: typeof body.deviceLabel === 'string' ? body.deviceLabel : String(body.deviceId)});
  }
  function report(memberId?: string, deviceId?: string) {
    const people = members();
    if (memberId && !people.some(m => m.id === memberId)) throw new Error('成员不存在。');
    const owners = devices();
    const owned = new Map(owners.map(d => [d.deviceId, d.memberId]));
    const all = readMeterEvents(options.dataDir, now());
    const known = all.filter(e => owned.has(e.device));
    const selected = known.filter(e => (!memberId || owned.get(e.device) === memberId) && (!deviceId || e.device === deviceId));
    const timestamp = now();
    const day = monthDay();
    const periods = aggregateReports(selected, day, timestamp);
    const contacts = new Map(options.registry.list().map(d => [d.deviceId, d]));
    const status = owners.filter(d => !memberId || d.memberId === memberId).map(d => {
      const contact = contacts.get(d.deviceId);
      const self = d.deviceId === options.self?.deviceId;
      const provider = contact?.status?.providers.codex;
      return {deviceId: d.deviceId, memberId: d.memberId, label: d.label,
        lastSeenAt: self ? timestamp : contact?.lastSeenAt ?? null,
        lastUploadAt: contact?.lastUploadAt ?? null,
        online: self || !!contact && timestamp - contact.lastSeenAt < Math.max(options.heartbeatMs / 1000 * 3, 30),
        pending: self ? 0 : provider?.pending ?? null,
        syncedThrough: self ? options.selfScannedThrough?.() ?? null : provider?.syncedThrough ?? null,
        lastError: self ? options.selfError?.() ?? null : contact?.status?.lastError ?? null};
    });
    const summaries = people.map(m => {
      const r = aggregateReports(known.filter(e => owned.get(e.device) === m.id), day, timestamp);
      return {...m, devices: owners.filter(d => d.memberId === m.id).length,
        week: r.weekly[0]?.total ?? 0, month: r.monthly[0]?.total ?? 0,
        total: r.weekly.reduce((sum, row) => sum + row.total, 0)};
    });
    return {...periods, scope: 'team' as const, accountFingerprint: options.accountFingerprint, memberId: memberId ?? null,
      members: summaries, devices: status, unassignedEvents: all.length - known.length,
      incomplete: all.length > known.length || status.some(d => !d.online || d.pending === null || d.pending > 0 || d.syncedThrough === null || d.lastError !== null),
      overview: meterOverview(selected, timestamp)};
  }
  function archive(): void {
    atomicJson(path.join(options.dataDir, 'team-reports.json'), {all: report(), byMember: Object.fromEntries(members().map(m => [m.id, report(m.id)]))});
  }
  return {members, saveMember, removeMember, devices, validateIdentity, report, archive, monthDay, setMonthDay,
    fingerprint: options.accountFingerprint, close: () => db.close()};
}

export function meterOverview(selected: MeterEvent[], timestamp = Math.floor(Date.now() / 1000)) {
  const daily = new Map<string, number>();
  const models = new Map<string, {model: string; totalTokens: number; inputTokens: number; cachedInputTokens: number; outputTokens: number}>();
  const grid: number[][] = Array.from({length: 7}, () => Array(24).fill(0));
  for (const e of selected) {
    const d = new Date((e.at + 8 * 3600) * 1000);
    if (e.at >= timestamp - 30 * 86400) {
      const date = d.toISOString().slice(0, 10);
      daily.set(date, (daily.get(date) ?? 0) + e.total);
      grid[d.getUTCDay()][d.getUTCHours()] += e.total;
    }
    const model = models.get(e.model) ?? {model: e.model, totalTokens: 0, inputTokens: 0, cachedInputTokens: 0, outputTokens: 0};
    model.totalTokens += e.total; model.inputTokens += e.input; model.cachedInputTokens += e.cached; model.outputTokens += e.output;
    models.set(e.model, model);
  }
  return {localDailyUsage: [...daily].map(([date, tokens]) => ({date, tokens})), hourlyActivity: grid,
    modelUsage: [...models.values()].sort((a,b) => b.totalTokens-a.totalTokens), threads: []};
}

export function readMeterEvents(dataDir: string, now = Math.floor(Date.now() / 1000)): MeterEvent[] {
    const usage = new DatabaseSync(path.join(dataDir, 'codex-usage.sqlite'), {readOnly: true});
    try {
      return usage.prepare(`SELECT observed_at AS at, thread_id AS thread, device_id AS device, model,
        input_tokens AS input, cached_input_tokens AS cached, output_tokens AS output, total_tokens AS total
        FROM session_part_token_events WHERE observed_at <= ? ORDER BY observed_at`).all(now) as unknown as MeterEvent[];
    } finally { usage.close(); }
  }
