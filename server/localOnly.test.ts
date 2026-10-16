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
    runtime: standaloneRuntime({ dataDir: directory, pollAccount: true }),
    rateLimitPollMs: 60000, accountUsagePollMs: 900000, sessionScanMs: 120000,
    threadMetadataPollMs: 900000, cloudTaskPollMs: 600000, cloudTasksEnabled: true
  });
  try {
    const now = baseTime(0);
    store.insertRateLimitSnapshots([sample(now, 75, now + 3600)]);
    store.upsertAccountDailyUsage([{date: new Date().toISOString().slice(0, 10), tokens: 999999999, source: 'account'}]);
    const overview = provider.overview();
    assert.equal(overview.trackingScope, 'local');
    assert.equal(overview.account.statsSource, 'local');
    assert.equal(overview.account.lifetimeTokens, overview.totals.totalTokens);
    assert.deepEqual(overview.accountDailyUsage, []);
    assert.deepEqual(overview.histories, {fiveHour: [], sevenDay: []});
    assert.deepEqual(overview.modelEfficiency, []);
    assert.equal(overview.limits.fiveHour, null);
    assert.equal(overview.cloudTasks.status, 'disabled');
    assert.deepEqual(provider.windows(300), []);
    assert.equal(provider.windowDetail(300, now + 3600), null);
    assert.equal(provider.health().connected, false);
  } finally {
    provider.stop();
    store.close();
    if (previous === undefined) delete process.env.LOCAL_ONLY;
    else process.env.LOCAL_ONLY = previous;
    removeDir(directory);
  }
});
