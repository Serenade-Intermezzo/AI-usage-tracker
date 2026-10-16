import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export interface Installation {
  version: 1; role: 'standalone' | 'server' | 'collector';
  memberId: string; memberName: string; deviceLabel: string;
  centralUrl: string | null; secret: string | null;
  listenHost: string; scanLocal: boolean; accountFingerprint: string | null;
}
export const validId = (value: unknown): value is string => typeof value === 'string' && /^[a-z0-9][a-z0-9._-]{0,63}$/i.test(value);
export const validFingerprint = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export function atomicJson(file: string, value: unknown): void {
  fs.mkdirSync(path.dirname(file), {recursive: true});
  fs.writeFileSync(file + '.tmp', JSON.stringify(value, null, 2) + '\n', {mode: 0o600});
  fs.renameSync(file + '.tmp', file);
  fs.chmodSync(file, 0o600);
}
export function readInstallation(dataDir: string): Installation | null {
  const file = path.join(dataDir, 'installation.json');
  if (!fs.existsSync(file)) return null;
  return validateInstallation(JSON.parse(fs.readFileSync(file, 'utf8')));
}
export function validateInstallation(raw: unknown, previous?: Installation | null): Installation {
  const v = raw as Partial<Installation> | null;
  if (!v || !['standalone', 'server', 'collector'].includes(v.role ?? '')) throw new Error('请选择本机、汇总中心或采集设备。');
  const memberId = v.memberId || previous?.memberId || crypto.randomUUID();
  if (!validId(memberId)) throw new Error('成员编号无效。');
  const memberName = typeof v.memberName === 'string' ? v.memberName.trim() : '';
  const deviceLabel = typeof v.deviceLabel === 'string' ? v.deviceLabel.trim() : '';
  if (!memberName || memberName.length > 80 || !deviceLabel || deviceLabel.length > 80) throw new Error('成员和设备名称需为 1–80 个字符。');
  let centralUrl: string | null = null;
  if (v.role === 'collector') {
    try {
      const u = new URL(v.centralUrl ?? '');
      if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password || u.search || u.hash || u.pathname !== '/') throw new Error();
      centralUrl = u.origin;
    } catch { throw new Error('汇总中心地址应为 http://主机:端口 或 https://主机。'); }
  }
  let secret = v.secret === undefined || v.secret === '' ? previous?.secret ?? null : v.secret;
  if (v.role === 'server' && !secret) secret = crypto.randomBytes(32).toString('base64url');
  if (v.role === 'collector' && (!secret || secret.length < 16)) throw new Error('请粘贴汇总中心生成的接入配置。');
  if (secret && (typeof secret !== 'string' || secret.length > 512 || /[\r\n]/.test(secret))) throw new Error('接入密钥无效。');
  const listenHost = v.listenHost || '127.0.0.1';
  if (!['127.0.0.1', '0.0.0.0', '::1', '::'].includes(listenHost)) throw new Error('监听地址无效。');
  const accountFingerprint = v.accountFingerprint ?? previous?.accountFingerprint ?? null;
  if (accountFingerprint !== null && !validFingerprint(accountFingerprint)) throw new Error('账号范围指纹无效。');
  if (v.role === 'collector' && !accountFingerprint) throw new Error('接入配置缺少账号范围。');
  return {version: 1, role: v.role!, memberId, memberName, deviceLabel, centralUrl,
    secret: v.role === 'standalone' ? null : secret, listenHost,
    scanLocal: v.scanLocal !== false, accountFingerprint};
}
