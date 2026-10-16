import assert from 'node:assert/strict';
import fs from 'node:fs';
import { once } from 'node:events';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import test from 'node:test';
import express from 'express';
import { createUsageStore, type UsageStore } from './db.js';
import { indexSessionFile } from './sessionScan.js';
import { codexSessionSource } from './sessionLogs.js';
import { createSyncClient, type SyncSource } from './sync/client.js';
import { createDeviceRegistry, type DeviceRegistry } from './sync/registry.js';
import { createSyncRouter } from './sync/server.js';
import { baseTime, localEvent, partSummary, removeDir, tempDir } from './testSupport.js';
import type { ProviderId } from './types.js';

const SECRET = 'test-secret-with-enough-length';
const CENTRAL = 'http://central.test';
const iso = (seconds: number) => new Date(seconds * 1000).toISOString();

interface CentralServer {
  url: string;
  stores: Record<ProviderId, UsageStore>;
  registry: DeviceRegistry;
  close(): Promise<void>;
}

async function startCentral(dataDir: string): Promise<CentralServer> {
  const stores = {
    codex: createUsageStore({ file: 'codex-usage.sqlite', provider: 'codex', dataDir, deviceId: 'server' })
  };
  const registry = createDeviceRegistry(dataDir);
  const app = express();
  app.use('/api/sync', createSyncRouter({ secret: SECRET, registry, stores, selfDeviceId: 'server' }));
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    stores,
    registry,
    async close() {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      stores.codex.close();
      registry.close();
    }
  };
}

/** Routes the client's fixed URL to whichever server is running, or fails like a dead host. */
function routedFetch(target: { url: string | null }): typeof fetch {
  return (async (input: string | URL | Request, init?: RequestInit) => {
    if (!target.url) {
      throw Object.assign(new TypeError('fetch failed'), { cause: { code: 'ECONNREFUSED' } });
    }
    return fetch(String(input).replace(CENTRAL, target.url), init);
  }) as typeof fetch;
}

function collectorStore(dataDir: string, provider: ProviderId): UsageStore {
  return createUsageStore({ file: `${provider}-usage.sqlite`, provider, dataDir, deviceId: 'laptop', outbox: true });
}

function client(sources: SyncSource[], target: { url: string | null }, overrides: Partial<Parameters<typeof createSyncClient>[0]> = {}) {
  return createSyncClient({
    centralUrl: CENTRAL,
    secret: SECRET,
    deviceId: 'laptop',
    deviceLabel: 'Laptop',
    installId: 'install-1',
    version: 'test',
    sources,
    batchSize: 3,
    debounceMs: 10,
    heartbeatMs: 60_000,
    maxBackoffMs: 200,
    initialBackoffMs: 50,
    fetch: routedFetch(target),
    log: () => {},
    ...overrides
  });
}

function writeCodexRollout(codexHome: string, name: string, threadId: string, start: number, responses: number, model = 'gpt-5.6-sol'): string {
  const directory = path.join(codexHome, 'sessions', '2026', '09', '20');
  fs.mkdirSync(directory, { recursive: true });
  const lines: unknown[] = [
    { timestamp: iso(start), type: 'session_meta', payload: { id: threadId, cwd: '/home/daniel/project', thread_source: 'main', source: 'cli' } },
    { timestamp: iso(start + 1), type: 'turn_context', payload: { model, turn_id: 'turn-1' } },
    { timestamp: iso(start + 2), type: 'event_msg', payload: { type: 'task_started', turn_id: 'turn-1', started_at: start + 2 } },
    {
      timestamp: iso(start + 3),
      type: 'response_item',
      payload: { type: 'message', role: 'user', content: [{ type: 'input_text', text: `Work on ${threadId}` }] }
    }
  ];
  for (let index = 0; index < responses; index += 1) {
    lines.push({
      timestamp: iso(start + 10 + index * 30),
      type: 'event_msg',
      payload: {
        type: 'token_count',
        info: { last_token_usage: { input_tokens: 1_000, cached_input_tokens: 400, output_tokens: 100, total_tokens: 1_100 } }
      }
    });
  }
  lines.push({ timestamp: iso(start + 20 + responses * 30), type: 'event_msg', payload: { type: 'task_complete' } });
  const file = path.join(directory, name);
  fs.writeFileSync(file, `${lines.map((line) => JSON.stringify(line)).join('\n')}\n`);
  return file;
}

test('Codex events from a collector arrive once, with their device and log timestamps', async () => {
  const root = tempDir('sync-codex');
  const central = await startCentral(path.join(root, 'server'));
  const collector = collectorStore(path.join(root, 'laptop'), 'codex');
  const target = { url: central.url as string | null };
  const sync = client([{ provider: 'codex', store: collector, enabled: true, scannedThrough: () => baseTime(0) }], target);
  try {
    const start = baseTime(1);
    const codexHome = path.join(root, 'codex-home');
    const file = writeCodexRollout(codexHome, 'rollout-2026-09-20T10-00-00-aaaa.jsonl', 'thread-laptop', start, 7);
    assert.equal(await indexSessionFile(collector, codexSessionSource(codexHome), file), 'full');
    assert.ok(collector.outboxStats().pending > 7);

    assert.equal(await sync.flush(), true);
    assert.equal(collector.outboxStats().pending, 0);
    const [thread] = central.stores.codex.getThreadSummaries();
    assert.equal(thread.threadId, 'thread-laptop');
    assert.deepEqual(thread.deviceIds, ['laptop']);
    assert.equal(thread.totalTokens, 7 * 1_100);
    assert.equal(thread.prompts.length, 1);
    assert.equal(thread.title, 'Work on thread-laptop');
    const events = central.stores.codex.getTokenEventsBetween(start, start + 1_000);
    assert.deepEqual(events.map((event) => event.observedAt), Array.from({ length: 7 }, (_, index) => start + 10 + index * 30));
    assert.ok(events.every((event) => event.deviceId === 'laptop'));
    const serverCost = central.stores.codex.getTokenTotals().estimatedApiCostUsd;
    assert.ok(Math.abs(serverCost - collector.getTokenTotals().estimatedApiCostUsd) < 1e-9);

    // A full re-send (as after a server reset) changes nothing.
    collector.exportAllToOutbox('another-server');
    assert.equal(await sync.flush(), true);
    assert.equal(central.stores.codex.getTokenTotals().totalTokens, 7 * 1_100);
    assert.equal(central.stores.codex.getThreadSummaries().length, 1);

    const [device] = central.registry.list();
    assert.equal(device.deviceId, 'laptop');
    assert.equal(device.label, 'Laptop');
    assert.equal(device.status?.providers.codex?.pending, 0);
  } finally {
    sync.stop();
    collector.close();
    await central.close();
    removeDir(root);
  }
});

test('re-indexing unchanged GPT-6.1 Sol logs refreshes collector and server history without duplicates', async () => {
  const root = tempDir('sync-sol-61');
  const central = await startCentral(path.join(root, 'server'));
  const collector = collectorStore(path.join(root, 'laptop'), 'codex');
  const sync = client([{ provider: 'codex', store: collector, enabled: true, scannedThrough: () => baseTime(0) }], { url: central.url });
  try {
    const start = baseTime(1);
    const home = path.join(root, 'codex-home');
    const source = codexSessionSource(home);
    const file = writeCodexRollout(home, 'rollout-sol-61.jsonl', 'thread-sol-61', start, 2, 'gpt-6.1-sol');
    // Simulate the previous build, which saved these logs without a known price.
    const previousSource = {
      ...source,
      parserVersion: '7',
      createParser(filePath: string) {
        const parser = source.createParser(filePath);
        return {
          feed: (line: string) => parser.feed(line),
          snapshot: () => parser.snapshot(),
          identity: () => parser.identity(),
          async finish() {
            const output = await parser.finish();
            for (const part of output.parts ?? []) {
              part.summary.estimatedApiCostUsd = null;
              part.summary.pricingStatus = 'unknown';
              for (const event of part.events) event.estimatedApiCostUsd = null;
              for (const prompt of part.prompts) {
                prompt.estimatedApiCostUsd = null;
                prompt.pricingStatus = 'unknown';
              }
            }
            return output;
          }
        };
      }
    };
    await indexSessionFile(collector, previousSource, file);
    assert.equal(collector.getThreadSummaries()[0].pricingStatus, 'unknown');
    await sync.flush();

    assert.equal(await indexSessionFile(collector, source, file), 'full');
    assert.equal(await sync.flush(), true);
    for (const target of [collector, central.stores.codex]) {
      const [thread] = target.getThreadSummaries();
      assert.equal(thread.pricingStatus, 'exact-model-match');
      assert.ok(Math.abs(thread.estimatedApiCostUsd! - 0.00448) < 1e-12);
      assert.equal(thread.prompts[0].pricingStatus, 'exact-model-match');
      assert.ok(Math.abs(thread.prompts[0].estimatedApiCostUsd! - 0.00448) < 1e-12);
      assert.equal(thread.totalTokens, 2_200);
      assert.equal(target.getTokenEventsBetween(start, start + 1_000).length, 2);
    }
    assert.equal(await indexSessionFile(collector, source, file), 'skipped');
    assert.equal(collector.outboxStats().pending, 0);
  } finally {
    sync.stop();
    collector.close();
    await central.close();
    removeDir(root);
  }
});

test('the outbox survives a collector restart and a server outage, then uploads the backlog', async () => {
  const root = tempDir('sync-offline');
  const serverDir = path.join(root, 'server');
  const laptopDir = path.join(root, 'laptop');
  const target: { url: string | null } = { url: null };
  const start = baseTime(4);

  // Server unreachable: several days of work queue up locally.
  let collector = collectorStore(laptopDir, 'codex');
  let sync = client([{ provider: 'codex', store: collector, enabled: true, scannedThrough: () => baseTime(0) }], target);
  const events = Array.from({ length: 40 }, (_, index) =>
    localEvent(`backlog-${index}`, 'offline-chat', start + index * 7_200, 0.05, 500));
  collector.replaceThreadData(partSummary('offline-chat', 'offline-chat.jsonl'), events, []);
  const queued = collector.outboxStats().pending;
  assert.ok(queued >= 41);
  assert.equal(collector.outboxStats().oldestPendingAt, start);
  assert.equal(await sync.flush(), false);
  const status = sync.status();
  assert.equal(status.state, 'offline');
  assert.equal(status.online, false);
  assert.ok(status.nextRetryAt !== null, 'a retry is scheduled');
  assert.equal(collector.outboxStats().pending, queued, 'nothing is dropped while offline');
  sync.stop();
  collector.close();

  // The laptop restarts; the queue is still there.
  collector = collectorStore(laptopDir, 'codex');
  assert.equal(collector.outboxStats().pending, queued);

  // The server comes back and receives the backlog in batches.
  let central = await startCentral(serverDir);
  target.url = central.url;
  sync = client([{ provider: 'codex', store: collector, enabled: true, scannedThrough: () => baseTime(0) }], target, { batchSize: 7 });
  try {
    assert.equal(await sync.flush(), true);
    assert.equal(collector.outboxStats().pending, 0);
    assert.equal(central.stores.codex.getTokenTotals().totalTokens, 40 * 500);
    assert.equal(sync.status().state, 'synced');

    // The server restarts too: its data and identity persist, nothing is re-sent twice.
    const instance = central.registry.instanceId;
    await central.close();
    target.url = null;
    collector.replaceThreadData(partSummary('offline-chat', 'offline-chat.jsonl'), [
      ...events,
      localEvent('after-restart', 'offline-chat', start + 90 * 3_600, 0.05, 500)
    ], []);
    assert.equal(await sync.flush(), false);
    central = await startCentral(serverDir);
    target.url = central.url;
    assert.equal(central.registry.instanceId, instance);
    assert.equal(await sync.flush(), true);
    assert.equal(central.stores.codex.getTokenTotals().totalTokens, 41 * 500);
    assert.equal(collector.outboxStats().pending, 0);
  } finally {
    sync.stop();
    collector.close();
    await central.close();
    removeDir(root);
  }
});

test('a wrong secret or the server\'s own device id is refused and nothing is dequeued', async () => {
  const root = tempDir('sync-auth');
  const central = await startCentral(path.join(root, 'server'));
  const collector = collectorStore(path.join(root, 'laptop'), 'codex');
  const target = { url: central.url as string | null };
  const sources: SyncSource[] = [{ provider: 'codex', store: collector, enabled: true, scannedThrough: () => null }];
  const wrongSecret = client(sources, target, { secret: 'not-the-secret' });
  const impostor = client(sources, target, { deviceId: 'server' });
  try {
    collector.replaceThreadData(partSummary('chat', 'chat.jsonl'), [localEvent('e1', 'chat', baseTime(), 0.1)], []);
    const pending = collector.outboxStats().pending;
    assert.equal(await wrongSecret.flush(), false);
    assert.equal(wrongSecret.status().state, 'unauthorized');
    assert.equal(await impostor.flush(), false);
    assert.equal(impostor.status().state, 'rejected');
    assert.match(impostor.status().lastError ?? '', /DEVICE_ID/);
    assert.equal(collector.outboxStats().pending, pending);
    assert.equal(central.stores.codex.getTokenTotals().totalTokens, 0);
  } finally {
    wrongSecret.stop();
    impostor.stop();
    collector.close();
    await central.close();
    removeDir(root);
  }
});
