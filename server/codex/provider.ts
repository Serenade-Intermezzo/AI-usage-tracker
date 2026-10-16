import path from 'node:path';
import { createAccountScope } from './accountScope.js';
import { readLocalThreadMetadata } from './localThreadMetadata.js';
import { createUsageStore, type UsageStore } from '../db.js';
import { SCAN_MARGIN_SECONDS, standaloneRuntime, type Provider, type ProviderRuntime } from '../providers.js';
import { createSessionScanner } from '../sessionScan.js';
import { codexHomeDirectory, codexPartId, codexSessionSource } from '../sessionLogs.js';

export interface CodexProviderConfig {
  enabled: boolean;
  sessionScanMs: number;
  runtime?: ProviderRuntime;
  store?: UsageStore;
}

/** Local files only. No account API, subprocess login client, cloud tasks or quota polling. */
export function createCodexProvider(config: CodexProviderConfig): Provider {
  const runtime = config.runtime ?? standaloneRuntime();
  const store = config.store ?? createUsageStore({file: 'codex-usage.sqlite', provider: 'codex',
    dataDir: runtime.dataDir, deviceId: runtime.deviceId, outbox: runtime.outbox,
    legacyPartId: row => codexPartId(row.sourceFile)});
  const homes = [codexHomeDirectory(), ...(process.env.CODEX_EXTRA_HOMES || '').split(path.delimiter).filter(Boolean)];
  const scope = config.enabled && runtime.scanLocal !== false && process.env.CODEX_ACCOUNT_SCOPE === 'true'
    ? createAccountScope(runtime.dataDir, homes) : null;
  let lastMetadata = 0;
  let error: string | null = null;
  let timer: NodeJS.Timeout | null = null;
  const source = codexSessionSource(homes[0], homes.slice(1));
  const scanner = createSessionScanner({store, source: scope ? scope.wrap(source) : source,
    watch: runtime.watchSessions, onScanned(result, kind) {
      error = result.errors > 0 ? '部分日志未能读取，请检查本机日志文件权限。' : null;
      if (kind === 'full' || Date.now() - lastMetadata >= 30_000) {
        store.upsertThreadMetadata(homes.flatMap(home => readLocalThreadMetadata(home)));
        lastMetadata = Date.now();
      }
    }});
  async function refresh() {
    if (!config.enabled || runtime.scanLocal === false) return;
    try { await scanner.fullScan(); } catch { error = '本机日志扫描失败，请检查数据目录和文件权限。'; }
  }
  return {id: 'codex', label: 'Codex', enabled: config.enabled, store,
    start() {
      if (timer || !config.enabled || runtime.scanLocal === false) return;
      void refresh(); timer = setInterval(() => void refresh(), config.sessionScanMs); timer.unref();
    },
    stop() { if (timer) clearInterval(timer); timer = null; scanner.stop(); scope?.stop(); },
    refresh,
    overview() { return {provider: 'codex', trackingScope: 'local', generatedAt: Math.floor(Date.now() / 1000),
      accountScope: scope?.summary(), localDailyUsage: store.getLocalDailyUsage(14), hourlyActivity: store.getHourlyActivity(30),
      totals: store.getTokenTotals(), threads: store.getThreadSummaries(120), modelUsage: store.getModelUsageSummaries()}; },
    health: () => ({connected: !!scope?.summary().homes.some(home => home.matches), error}),
    scannedThrough: () => {const at = scanner.lastFullScanStartedAt(); return at === null ? null : at - SCAN_MARGIN_SECONDS;},
    watching: () => scanner.watching()
  };
}
