import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import type { TrackerRole } from '../types.js';
import type { CollectorStatusReport } from './protocol.js';

export interface DeviceRow {
  deviceId: string;
  label: string;
  role: TrackerRole;
  installId: string | null;
  firstSeenAt: number;
  lastSeenAt: number;
  lastUploadAt: number | null;
  uploadedRecords: number;
  status: CollectorStatusReport | null;
  clockOffsetSeconds: number | null;
  installChangedAt: number | null;
}

export interface ContactInfo {
  deviceId: string;
  label: string;
  installId: string;
  role: TrackerRole;
}

/**
 * Devices known to the central server, and the server's own instance id.
 * Lives in `data/sync.sqlite`, next to the per-provider stores, because a
 * device reports for every provider at once.
 */
export function createDeviceRegistry(dataDir: string, file = 'sync.sqlite') {
  fs.mkdirSync(dataDir, { recursive: true });
  const db = new DatabaseSync(path.join(dataDir, file));
  db.exec('PRAGMA busy_timeout = 5000;');
  db.exec('PRAGMA journal_mode = WAL;');
  db.exec('PRAGMA synchronous = FULL;');
  db.exec(`
    CREATE TABLE IF NOT EXISTS devices (
      device_id TEXT PRIMARY KEY,
      label TEXT NOT NULL,
      role TEXT NOT NULL,
      install_id TEXT,
      first_seen_at INTEGER NOT NULL,
      last_seen_at INTEGER NOT NULL,
      last_upload_at INTEGER,
      uploaded_records INTEGER NOT NULL DEFAULT 0,
      status_json TEXT,
      clock_offset_s REAL,
      install_changed_at INTEGER
    );
    CREATE TABLE IF NOT EXISTS sync_meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
  `);

  function getMeta(key: string): string | null {
    const row = db.prepare('SELECT value FROM sync_meta WHERE key = ?').get(key) as { value: string } | undefined;
    return row?.value ?? null;
  }

  function setMeta(key: string, value: string): void {
    db.prepare(`
      INSERT INTO sync_meta (key, value) VALUES (?, ?)
      ON CONFLICT(key) DO UPDATE SET value = excluded.value
    `).run(key, value);
  }

  // Collectors re-send their whole history when this changes (a reset server).
  let instanceId = getMeta('instance_id');
  if (!instanceId) {
    instanceId = crypto.randomUUID();
    setMeta('instance_id', instanceId);
  }

  /** Register a request from a device; notes when a second installation claims its id. */
  function recordContact(info: ContactInfo, now: number): void {
    const existing = db.prepare('SELECT install_id AS installId FROM devices WHERE device_id = ?')
      .get(info.deviceId) as { installId: string | null } | undefined;
    const installChanged = existing?.installId && existing.installId !== info.installId ? now : null;
    db.prepare(`
      INSERT INTO devices (device_id, label, role, install_id, first_seen_at, last_seen_at, install_changed_at)
      VALUES (?, ?, ?, ?, ?, ?, NULL)
      ON CONFLICT(device_id) DO UPDATE SET
        label = excluded.label,
        role = excluded.role,
        install_id = excluded.install_id,
        last_seen_at = excluded.last_seen_at,
        install_changed_at = COALESCE(?, devices.install_changed_at)
    `).run(info.deviceId, info.label, info.role, info.installId, now, now, installChanged);
  }

  function recordUpload(deviceId: string, records: number, now: number): void {
    db.prepare(`
      UPDATE devices SET last_upload_at = ?, uploaded_records = uploaded_records + ? WHERE device_id = ?
    `).run(now, records, deviceId);
  }

  function recordStatus(deviceId: string, status: CollectorStatusReport, now: number): void {
    const offset = Number.isFinite(status.now) ? now - status.now : null;
    db.prepare('UPDATE devices SET status_json = ?, clock_offset_s = ? WHERE device_id = ?')
      .run(JSON.stringify(status), offset, deviceId);
  }

  function list(): DeviceRow[] {
    return (db.prepare(`
      SELECT device_id AS deviceId, label, role, install_id AS installId, first_seen_at AS firstSeenAt,
             last_seen_at AS lastSeenAt, last_upload_at AS lastUploadAt, uploaded_records AS uploadedRecords,
             status_json AS statusJson, clock_offset_s AS clockOffsetSeconds,
             install_changed_at AS installChangedAt
      FROM devices ORDER BY first_seen_at ASC
    `).all() as Array<Omit<DeviceRow, 'status'> & { statusJson: string | null }>).map(({ statusJson, ...row }) => {
      let status: CollectorStatusReport | null = null;
      try {
        status = statusJson ? JSON.parse(statusJson) as CollectorStatusReport : null;
      } catch {
        status = null;
      }
      return { ...row, status };
    });
  }

  function forget(deviceId: string): boolean {
    return Number(db.prepare('DELETE FROM devices WHERE device_id = ?').run(deviceId).changes) > 0;
  }

  return {
    instanceId,
    getMeta,
    setMeta,
    recordContact,
    recordUpload,
    recordStatus,
    list,
    forget,
    close: () => db.close()
  };
}

export type DeviceRegistry = ReturnType<typeof createDeviceRegistry>;
