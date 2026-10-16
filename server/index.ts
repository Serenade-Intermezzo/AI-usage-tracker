import 'dotenv/config';
import { createLocalReports } from './localReports.js';
import fs from 'node:fs';
import os from 'node:os';
import { readLogin } from './codex/accountScope.js';
import { spawn } from 'node:child_process';
import { atomicJson, readInstallation, validateInstallation } from './installation.js';
import { createTeam, accountFingerprint, meterOverview, readMeterEvents } from './team.js';
import { authorized } from './sync/server.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { createCodexProvider } from './codex/provider.js';
import { ConfigError, flagEnv, loadTrackerConfig, type TrackerConfig } from './config.js';
import { isProviderId, providerInfo, type Provider, type ProviderRuntime } from './providers.js';
import { createSyncClient } from './sync/client.js';
import { createDeviceRegistry } from './sync/registry.js';
import { createSyncRouter } from './sync/server.js';
import type { ProviderId } from './types.js';

function numberEnv(name: string, fallback: number): number {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

const currentDir = path.dirname(fileURLToPath(import.meta.url));

function readVersion(): string {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(currentDir, '../package.json'), 'utf8')) as { version?: string };
    return pkg.version ?? 'unknown';
  } catch {
    return 'unknown';
  }
}

let config: TrackerConfig;
try {
  config = loadTrackerConfig();
} catch (error) {
  if (error instanceof ConfigError) {
    console.error(`AI Usage Tracker configuration error: ${error.message}`);
    process.exit(1);
  }
  throw error;
}

const version = readVersion();
const port = Number(process.env.PORT || 8893);
const host = config.listenHost;
const isCollector = config.role === 'collector';
const registry = config.role === 'server' ? createDeviceRegistry(config.dataDir) : null;

let providers: Record<ProviderId, Provider>;

process.env.LOCAL_ONLY = 'true';
if (config.scanLocal) process.env.CODEX_ACCOUNT_SCOPE = 'true';
if (!process.env.CODEX_HOME) {
  const homes = ['.codex-desktop', '.codex'].map(name => path.join(os.homedir(), name));
  process.env.CODEX_HOME = homes.find(home => readLogin(home).mode === 'chatgpt') ?? homes[1];
  if (process.env.CODEX_EXTRA_HOMES === undefined) process.env.CODEX_EXTRA_HOMES = homes.filter(home => home !== process.env.CODEX_HOME).join(path.delimiter);
}
const runtime: ProviderRuntime = {
  role: config.role,
  deviceId: config.deviceId,
  dataDir: config.dataDir,
  watchSessions: config.watchSessions,
  outbox: isCollector,
  scanLocal: config.scanLocal,
};

// A previous upstream database may contain account-wide/unscoped records.
// Preserve it before creating the first account binding, then reindex eligible logs.
if (process.env.CODEX_ACCOUNT_SCOPE === 'true' && config.scanLocal &&
    !fs.existsSync(path.join(config.dataDir, 'account-scope.json')) &&
    fs.existsSync(path.join(config.dataDir, 'codex-usage.sqlite'))) {
  const backup = path.join(config.dataDir, 'unscoped-backup-' + Date.now());
  fs.mkdirSync(backup, {mode: 0o700});
  for (const suffix of ['', '-wal', '-shm']) {
    const source = path.join(config.dataDir, 'codex-usage.sqlite' + suffix);
    if (fs.existsSync(source)) fs.renameSync(source, path.join(backup, path.basename(source)));
  }
  console.log('Preserved unscoped history in a local backup; rebuilding account-scoped metering.');
}

providers = {
  codex: createCodexProvider({
    enabled: flagEnv(process.env, 'CODEX', true),
    sessionScanMs: numberEnv('SESSION_SCAN_MS', 120_000),
    runtime
  })
};

const fingerprint = accountFingerprint(config.dataDir) ?? config.accountFingerprint;
if (config.role !== 'standalone' && (!fingerprint || (config.accountFingerprint && config.accountFingerprint !== fingerprint))) {
  throw new Error('多人统计需要与本机绑定账号一致的账号范围；无本机采集的中心需设置 TEAM_ACCOUNT_FINGERPRINT。');
}
const team = registry ? createTeam({
  dataDir: config.dataDir, accountFingerprint: fingerprint!, memberName: config.memberName, registry,
  heartbeatMs: config.sync.heartbeatMs, selfScannedThrough: () => providers.codex.scannedThrough(), selfError: () => providers.codex.health().error, self: config.scanLocal ? {deviceId: config.deviceId,
    memberId: config.memberId, installId: config.installId, label: config.deviceLabel} : null
}) : null;

const syncClient = isCollector
  ? createSyncClient({
      centralUrl: config.sync.centralUrl!,
      secret: config.sync.secret!,
      deviceId: config.deviceId,
      deviceLabel: config.deviceLabel,
      installId: config.installId,
      role: config.role,
      version,
      memberId: config.memberId, accountFingerprint: fingerprint!, usageOnly: true,
      readyToSync: () => !config.scanLocal || providers.codex.scannedThrough() !== null,
      onCalendar: day => {
        localReports?.setMonthDay(day);
        atomicJson(path.join(config.dataDir, 'team-calendar.json'), {monthStartDay: day, fetchedAt: Date.now() / 1000});
      },
      sources: Object.values(providers).filter(provider => provider.enabled).map((provider) => ({
        provider: provider.id,
        store: provider.store,
        enabled: provider.enabled,
        scannedThrough: () => provider.scannedThrough()
      })),
      batchSize: config.sync.batchSize,
      debounceMs: config.sync.debounceMs,
      heartbeatMs: config.sync.heartbeatMs,
      maxBackoffMs: config.sync.maxBackoffMs,
      watching: () => Object.values(providers).some((provider) => provider.enabled && provider.watching())
    })
  : null;

const app = express();
function loopback(request: express.Request): boolean {
  return ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(request.socket.remoteAddress ?? '');
}
function localAdmin(request: express.Request, response: express.Response): boolean {
  if (loopback(request) && request.header('x-tracker-local') === '1') return true;
  response.status(403).json({error: '此操作仅允许在汇总中心本机的原生界面中完成。'}); return false;
}
app.use((request, response, next) => {
  if (loopback(request)) { next(); return; }
  if (config.role !== 'server' || !config.sync.secret || !authorized(request.header('authorization'), config.sync.secret)) {
    response.status(401).json({error: '需要有效的接入配置。'}); return;
  }
  if (!['/api/team', '/api/team/reports', '/api/sync/upload', '/api/sync/heartbeat'].includes(request.path)) {
    response.status(403).json({error: '远程仅提供计量同步和团队报表。'}); return;
  }
  next();
});

// The sync API parses its own (larger) request bodies, so it is mounted before
// the default JSON parser.
if (registry && config.sync.secret) {
  app.use('/api/sync', createSyncRouter({
    secret: config.sync.secret,
    registry,
    stores: { codex: providers.codex.store },
    validateIdentity: team!.validateIdentity, usageOnly: true, calendar: () => ({monthStartDay: team!.monthDay()}),
    selfDeviceId: config.deviceId
  }));
}
app.use(express.json());


function publicInstallation() {
  const saved = readInstallation(config.dataDir);
  return {...(saved ?? {version: 1, role: config.role, memberId: config.memberId,
    memberName: config.memberName, deviceLabel: config.deviceLabel, centralUrl: config.sync.centralUrl,
    listenHost: host, scanLocal: config.scanLocal, accountFingerprint: fingerprint}), secret: undefined,
    memberName: team?.members().find(m => m.id === config.memberId)?.name ?? config.memberName,
    pid: process.pid, hasSecret: !!config.sync.secret, deviceId: config.deviceId};
}
app.get('/api/installation', (request, response) => {
  if (!localAdmin(request, response)) return;
  response.json(publicInstallation());
});
app.put('/api/installation', (request, response) => {
  if (!localAdmin(request, response)) return;
  try {
    const previous = readInstallation(config.dataDir) ?? { ...publicInstallation(), secret: config.sync.secret };
    const next = validateInstallation(request.body, previous as ReturnType<typeof readInstallation>);
    const localAccount = accountFingerprint(config.dataDir);
    if (next.role !== 'standalone' && next.scanLocal && localAccount && next.accountFingerprint && next.accountFingerprint !== localAccount) {
      throw new Error('接入配置对应的 OpenAI 账号与本机统计账号不一致。');
    }
    if (next.role !== 'standalone' && !next.accountFingerprint && localAccount) next.accountFingerprint = localAccount;
    if (next.role !== 'standalone' && !next.accountFingerprint) throw new Error('请先登录 Codex，或为不采集本机的汇总中心填写账号指纹。');
    if (team && next.role === 'server' && next.scanLocal) {
      const owner = team.devices().find(d => d.deviceId === config.deviceId);
      if (owner && next.memberId !== owner.memberId) throw new Error('本机已有成员归属，请保留成员编号，通过成员管理修改名称。');
    }
    if (team && next.role === 'server' && next.scanLocal) team.saveMember(next.memberName, next.memberId);
    atomicJson(path.join(config.dataDir, 'installation.json'), next);
    response.json({ok: true, restartRequired: true});
  } catch (error) { response.status(400).json({error: (error as Error).message}); }
});
app.post('/api/installation/restart', (request, response) => {
  if (!localAdmin(request, response)) return;
  response.json({ok: true});
  setTimeout(() => {
    syncClient?.stop();
    for (const provider of Object.values(providers)) provider.stop();
    httpServer.close(() => {
      if (!process.env.INVOCATION_ID) {
        const child = spawn(process.execPath, [...process.execArgv, ...process.argv.slice(1)], {
          cwd: process.cwd(), env: process.env, detached: true, stdio: 'ignore', windowsHide: true
        });
        child.unref();
      }
      process.exit(0);
    });
    httpServer.closeIdleConnections();
  }, 150).unref();
});
async function centralGet(endpoint: string): Promise<any> {
  const upstream = await fetch(config.sync.centralUrl + endpoint, {headers: {authorization: `Bearer ${config.sync.secret}`}, signal: AbortSignal.timeout(8000)});
  const body = await upstream.json() as {error?: string};
  if (!upstream.ok) throw new Error(body.error || '汇总中心暂不可用。');
  if ((body as {accountFingerprint?: string}).accountFingerprint !== fingerprint) throw new Error('汇总中心账号范围不一致。');
  return body;
}
app.get('/api/team', async (request, response) => {
  try {
    if (isCollector) { response.json({...await centralGet('/api/team'), role: 'collector', canManage: false, sync: syncClient?.status()}); return; }
    response.json({enabled: !!team, role: config.role, members: team?.members() ?? [],
      accountFingerprint: team?.fingerprint ?? null, canManage: !!team && loopback(request), selfMemberId: config.memberId, sync: null});
  } catch (error) { response.status(503).json({error: '汇总中心连接失败：' + (error as Error).message, sync: syncClient?.status()}); }
});
app.get('/api/team/reports', async (request, response) => {
  const member = typeof request.query.memberId === 'string' ? request.query.memberId : undefined;
  try {
    if (isCollector) {
      const report = await centralGet('/api/team/reports' + (member ? '?memberId=' + encodeURIComponent(member) : ''));
      // All local period views use the hub's last successfully fetched calendar.
      localReports?.setMonthDay(report.monthStartDay);
      atomicJson(path.join(config.dataDir, 'team-calendar.json'), {monthStartDay: report.monthStartDay, fetchedAt: Date.now() / 1000});
      response.json({...report, canEditMonthDay: false}); return;
    }
    if (!team) { response.status(404).json({error: '请先设置多人统计模式。'}); return; }
    response.json({...team.report(member), canEditMonthDay: loopback(request)});
  } catch (error) { response.status(isCollector ? 503 : 400).json({error: (error as Error).message}); }
});
app.put('/api/team/settings', (request, response) => {
  if (!localAdmin(request, response)) return;
  if (!team) { response.status(403).json({error: '请在汇总中心修改月度起始日。'}); return; }
  try { team.setMonthDay(request.body?.monthStartDay); team.archive(); response.json({...team.report(), canEditMonthDay: true}); }
  catch (error) { response.status(400).json({error: (error as Error).message}); }
});
app.post('/api/team/members', (request, response) => {
  if (!localAdmin(request, response)) return;
  if (!team) { response.status(403).json({error: '请在汇总中心管理成员。'}); return; }
  try {
    if (request.body?.id && !team.members().some(m => m.id === request.body.id)) throw new Error('成员不存在。');
    response.json(team.saveMember(request.body?.name, request.body?.id));
  } catch (error) { response.status(400).json({error: (error as Error).message}); }
});
app.get('/api/team/invitation', (request, response) => {
  if (!localAdmin(request, response)) return;
  const member = team?.members().find(m => m.id === request.query.memberId);
  if (!team || !member) { response.status(400).json({error: '请选择已登记成员。'}); return; }
  try {
    const address = new URL(String(request.query.url));
    if (!['http:', 'https:'].includes(address.protocol) || address.username || address.password || address.pathname !== '/' || address.search || address.hash) throw new Error();
    const invitation = {version: 1, centralUrl: address.origin, secret: config.sync.secret,
      memberId: member.id, memberName: member.name, accountFingerprint: team.fingerprint};
    response.json({invitation: Buffer.from(JSON.stringify(invitation)).toString('base64url')});
  } catch { response.status(400).json({error: '请输入其他设备可以访问的汇总中心地址。'}); }
});

const configuredDefault = process.env.DEFAULT_PROVIDER;
const defaultProvider: ProviderId =
  isProviderId(configuredDefault) && providers[configuredDefault].enabled
    ? configuredDefault
    : (Object.values(providers).find((provider) => provider.enabled)?.id ?? 'codex');

function resolveProvider(
  request: express.Request,
  response: express.Response
): Provider | null {
  const requested = typeof request.query.provider === 'string' ? request.query.provider : defaultProvider;
  if (!isProviderId(requested)) {
    response.status(400).json({ error: `Unknown provider "${requested}". Use "codex".` });
    return null;
  }
  const provider = providers[requested];
  if (!provider.enabled) {
    response.status(404).json({ error: `${provider.label} is turned off in .env.` });
    return null;
  }
  return provider;
}

// Reports use this machine's persisted token events; no account API is called.
const localReports = process.env.LOCAL_ONLY === 'true'
  ? createLocalReports(config.dataDir, config.deviceId) : null;
app.get('/api/local-reports', (_request, response) => {
  if (!localReports) { response.status(404).json({error: '仅本机模式支持周报与月报。'}); return; }
  try { response.json({...localReports.refresh(), canEditMonthDay: !isCollector}); }
  catch { response.status(500).json({error: '读取本机报表失败，请稍后重试。'}); }
});
app.put('/api/local-reports/settings', (request, response) => {
  if (!localAdmin(request, response)) return;
  if (isCollector) { response.status(403).json({error: '月度起始日由汇总中心统一管理。'}); return; }
  if (!localReports) { response.status(404).json({error: '仅本机模式支持周报与月报。'}); return; }
  try { response.json(localReports.setMonthDay(request.body?.monthStartDay)); }
  catch (error) { response.status(error instanceof Error && error.message.startsWith('月度起始日') ? 400 : 500)
    .json({error: error instanceof Error && error.message.startsWith('月度起始日') ? error.message : '保存设置失败，请稍后重试。'}); }
});
// Persist ended periods even when the browser is closed; catch up after startup.
const reportTimer = localReports ? setInterval(() => {
  try { localReports.refresh(); team?.archive(); } catch { console.warn('Could not update local period reports'); }
}, 60_000) : null;
reportTimer?.unref();

app.get('/api/health', (_request, response) => {
  response.json({
    ok: true,
    version,
    pid: process.pid,
    role: config.role,
    deviceId: config.deviceId,
    deviceLabel: config.deviceLabel,
    memberId: config.memberId,
    memberName: config.memberName,
    scanLocal: config.scanLocal,
    defaultProvider,
    providers: Object.fromEntries(
      Object.values(providers).map((provider) => [
        provider.id,
        {
          enabled: provider.enabled,
          ...provider.health(),
          watching: provider.watching(),
          scannedThrough: provider.scannedThrough()
        }
      ])
    ),
    sync: syncClient?.status() ?? null,
    // Kept for older clients that read the Codex fields directly.
    error: providers.codex.health().error
  });
});

app.get('/api/providers', (_request, response) => {
  response.json({
    providers: Object.values(providers).filter((p) => p.enabled).map(providerInfo),
    defaultProvider
  });
});

app.get('/api/overview', (request, response) => {
  const provider = resolveProvider(request, response);
  if (!provider) return;
  const overview = provider.overview();
  const events = readMeterEvents(config.dataDir).filter(e => e.device === config.deviceId);
  const chats = new Map<string, {inputTokens: number; cachedInputTokens: number; outputTokens: number; totalTokens: number}>();
  for (const event of events) {
    const usage = chats.get(event.thread) ?? {inputTokens: 0, cachedInputTokens: 0, outputTokens: 0, totalTokens: 0};
    usage.inputTokens += event.input; usage.cachedInputTokens += event.cached;
    usage.outputTokens += event.output; usage.totalTokens += event.total; chats.set(event.thread, usage);
  }
  response.json({...overview, ...meterOverview(events),
    threads: overview.threads.filter(t => chats.has(t.threadId)).map(t => ({...t, ...chats.get(t.threadId)}))});
});

app.post('/api/refresh', async (request, response) => {
  if (!localAdmin(request, response)) return;
  const provider = resolveProvider(request, response);
  if (!provider) return;
  await provider.refresh();
  if (isCollector) {
    await syncClient?.flush();
  }
  response.json(provider.overview());
});

app.get('/', (_request, response) => response.json({service: 'Codex Usage Tracker', interface: 'native Qt Widgets'}));

const where = `http://${host ?? 'localhost'}:${port}`;
const onListening = (error?: Error) => {
  if (error) {
    // Express 5 hands listen errors to this callback instead of throwing. Without
    // exiting, a tracker whose HOST address is not up yet (Tailscale still
    // starting at boot) would keep running without serving anything, and the
    // service manager would never restart it.
    console.error(`AI Usage Tracker cannot listen on ${where}: ${error.message}`);
    process.exit(1);
  }
  const enabled = Object.values(providers).filter((provider) => provider.enabled).map((provider) => provider.label);
  console.log(
    `AI Usage Tracker ${version} (${config.role}, device "${config.deviceId}"): ${where} (${enabled.join(', ') || 'no providers enabled'})`
  );
  if (isCollector) console.log(`Sending usage to ${config.sync.centralUrl}; the outbox keeps it while the server is unreachable.`);
  if (config.role === 'server') console.log('Accepting usage from collectors at /api/sync.');
  if (localReports) { try { localReports.refresh(); team?.archive(); } catch { console.warn('Local reports will retry automatically'); } }
};
const httpServer = app.listen(port, host, onListening);

{
  for (const provider of Object.values(providers)) provider.start();
  syncClient?.start();
}

function shutdown(): void {
  if (reportTimer) clearInterval(reportTimer);
  syncClient?.stop();
  team?.close();
  registry?.close();
  for (const provider of Object.values(providers)) provider.stop();
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
