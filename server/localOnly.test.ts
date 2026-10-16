import assert from 'node:assert/strict';
import test from 'node:test';
import { createCodexProvider } from './codex/provider.js';
import { standaloneRuntime } from './providers.js';
import { openStore, tempDir, removeDir, sample, baseTime } from './testSupport.js';

test('local mode excludes shared-account caches and blocks quota endpoints and account refresh', async () => {
  const directory = tempDir('local-only');
  const store = openStore(directory, 'local');
  const previous = process.env.LOCAL_ONLY;
  process.env.LOCAL_ONLY = 'true';
  const provider = createCodexProvider({
    enabled: true, store,
    runtime: standaloneRuntime({ dataDir: directory, scanLocal: false }),
    sessionScanMs: 120000
  });
  try {
    const now = baseTime(0);
    store.insertRateLimitSnapshots([sample(now, 75, now + 3600)]);
    store.upsertAccountDailyUsage([{date: new Date().toISOString().slice(0, 10), tokens: 999999999, source: 'account'}]);
    const overview = provider.overview();
    assert.equal(overview.trackingScope, 'local');
    assert.equal('account' in overview, false);
    assert.equal('limits' in overview, false);
    assert.equal('cloudTasks' in overview, false);
    assert.equal(overview.totals.totalTokens, 0);
    assert.equal(provider.health().connected, false);
  } finally {
    provider.stop();
    store.close();
    if (previous === undefined) delete process.env.LOCAL_ONLY;
    else process.env.LOCAL_ONLY = previous;
    removeDir(directory);
  }
});
