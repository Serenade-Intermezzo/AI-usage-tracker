import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';
import { spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import net, {type AddressInfo} from 'node:net';
import test from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import { createTeam } from './team.js';
import { atomicJson, readInstallation, validateInstallation } from './installation.js';
import { createDeviceRegistry } from './sync/registry.js';
import { openStore, tempDir, removeDir, parsed, remoteEvent } from './testSupport.js';

const ACCOUNT = 'synthetic-team-account';
const FP = crypto.createHash('sha256').update(ACCOUNT).digest('hex');
const SECRET = 'synthetic-team-test-secret-only';
const at = (s: string) => Date.parse(s + '+08:00') / 1000;
const sum = (r: any) => r.weekly.reduce((s: number, v: any) => s + v.total, 0);

test('team reports combine many devices per member, preserve ownership, and share monthly boundaries', () => {
  const root = tempDir('team-report');
  const store = openStore(root, 'hub', {file: 'codex-usage.sqlite'});
  const registry = createDeviceRegistry(root);
  let team = createTeam({dataDir: root, accountFingerprint: FP, self: null, memberName: '', registry,
    heartbeatMs: 1000, now: () => at('2026-10-20T12:00:00')});
  try {
    team.saveMember('Alice', 'alice'); team.saveMember('Bob', 'bob');
    for (const [device, member, date, total] of [
      ['a-linux', 'alice', '2026-10-15T23:59:59', 100],
      ['a-win', 'alice', '2026-10-16T00:00:00', 200],
      ['b-linux', 'bob', '2026-10-19T00:00:00', 300]
    ] as const) {
      team.validateIdentity({deviceId: device, memberId: member, installId: device, accountFingerprint: FP});
      const records = parsed([{kind: 'event', key: device, data: remoteEvent(device, device, at(date), null, total)}]);
      store.ingestRemoteRecords(device, records); store.ingestRemoteRecords(device, records);
    }
    // A copied event on a second machine keeps its first owner and is counted once.
    store.ingestRemoteRecords('b-linux', parsed([{kind: 'event', key: 'a-linux', data: remoteEvent('a-linux', 'a-linux', at('2026-10-15T23:59:59'), null, 100)}]));
    team.setMonthDay(16);
    assert.equal(sum(team.report()), 600);
    assert.equal(sum(team.report('alice')), 300);
    assert.equal(sum(team.report('bob')), 300);
    assert.deepEqual(team.report('alice').members.find(m => m.id === 'alice')?.devices, 2);
    assert.equal(team.report('alice').monthly.find(r => r.start === '2026-10-16')?.total, 200);
    assert.equal(team.report('alice').monthly.find(r => r.start === '2026-09-16')?.total, 100);
    assert.equal(team.report().incomplete, true, 'uncontacted devices cannot imply full coverage');
    assert.equal(team.report().overview.modelUsage[0].totalTokens, 600);
    assert.throws(() => team.report('missing'), /成员不存在/);
    assert.throws(() => team.validateIdentity({deviceId:'a-linux',memberId:'bob',installId:'a-linux',accountFingerprint:FP}), /另一成员/);
    assert.throws(() => team.validateIdentity({deviceId:'a-linux',memberId:'alice',installId:'cloned',accountFingerprint:FP}), /安装实例/);
    assert.throws(() => team.validateIdentity({deviceId:'x',memberId:'alice',installId:'x',accountFingerprint:'0'.repeat(64)}), /账号范围/);
    assert.throws(() => team.setMonthDay(32), /1–31/);
    team.saveMember('Alice renamed', 'alice');
    team.archive();
    const archive = JSON.parse(fs.readFileSync(path.join(root, 'team-reports.json'), 'utf8'));
    assert.equal(sum(archive.byMember.alice), 300);
    team.close();
    team = createTeam({dataDir: root, accountFingerprint: FP, self: null, memberName: '', registry, heartbeatMs:1000});
    assert.equal(team.monthDay(), 16);
    assert.equal(team.members().find(m => m.id === 'alice')?.name, 'Alice renamed');
    team.setMonthDay(31);
    assert.equal(team.report('bob').monthStartDay, 31);
  } finally { team.close(); registry.close(); store.close(); removeDir(root); }
});

test('installation persists connection preferences, generates a hub key, and validates joining data', () => {
  const root = tempDir('team-installation');
  try {
    const profile = validateInstallation({role:'server',memberName:'Me',deviceLabel:'Ubuntu',accountFingerprint:FP});
    assert.ok(profile.secret && profile.secret.length >= 32);
    atomicJson(path.join(root, 'installation.json'), profile);
    assert.deepEqual(readInstallation(root), profile);
    assert.equal(validateInstallation({...profile,secret:''},profile).secret,profile.secret);
    assert.throws(() => validateInstallation({...profile,role:'collector',centralUrl:'file:///etc/passwd'}), /地址/);
    assert.throws(() => validateInstallation({...profile,role:'collector',centralUrl:'http://user:pass@host'}), /地址/);
    assert.throws(() => validateInstallation({...profile,role:'collector',centralUrl:'http://host',accountFingerprint:null}), /账号范围/);
    if (process.platform !== 'win32') assert.equal(fs.statSync(path.join(root,'installation.json')).mode & 0o777, 0o600);
  } finally { removeDir(root); }
});

async function freePort(): Promise<number> {
  const s = net.createServer(); s.listen(0,'127.0.0.1'); await once(s,'listening');
  const port = (s.address() as AddressInfo).port; await new Promise<void>(r => s.close(() => r())); return port;
}
async function until(check: () => Promise<any>, timeout=20000): Promise<any> {
  const start = Date.now(); let last: unknown;
  while (Date.now()-start < timeout) {
    try { const value = await check(); if (value) return value; } catch (e) { last=e; }
    await new Promise(r => setTimeout(r,100));
  }
  throw new Error('Timed out waiting for team fixture: ' + String(last ?? 'condition was false'));
}
async function json(url: string, endpoint: string, body?: unknown, method?: string, headers: Record<string,string>={}) {
  const r = await fetch(url+endpoint, {method: method ?? (body === undefined ? 'GET' : 'PUT'),
    headers: {'content-type':'application/json','x-tracker-local':'1',...headers},
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(3000)});
  const value = await r.json() as any;
  return {status: r.status, value};
}
function fixtureHome(root: string, id: string, total=1000): string {
  const home=path.join(root, 'codex-home'); const directory=path.join(home,'sessions'); fs.mkdirSync(directory,{recursive:true});
  atomicJson(path.join(home,'auth.json'), {auth_mode:'chatgpt',tokens:{account_id:ACCOUNT}});
  const timestamp = Math.floor(Date.now()/1000)-3600;
  const stamp = (offset: number) => new Date((timestamp+offset)*1000).toISOString();
  const records = [
    {timestamp:stamp(0),type:'session_meta',payload:{id,source:'cli',model_provider:'openai',creator_account_id:ACCOUNT,cwd:'/private/project'}},
    {timestamp:stamp(1),type:'turn_context',payload:{model:'test-model',turn_id:'turn'}},
    {timestamp:stamp(2),type:'response_item',payload:{type:'message',role:'user',content:[{type:'input_text',text:'PRIVATE PROMPT DO NOT UPLOAD'}]}},
    {timestamp:stamp(3),type:'event_msg',payload:{type:'token_count',info:{last_token_usage:{input_tokens:total-100,cached_input_tokens:20,output_tokens:100,total_tokens:total}}}}
  ];
  fs.writeFileSync(path.join(directory,`rollout-${id}.jsonl`), records.map(r => JSON.stringify(r)).join('\n')+'\n'); return home;
}
interface Running {process: ChildProcess; url: string; stop(): Promise<void>;}
async function start(root: string, env: NodeJS.ProcessEnv): Promise<Running> {
  fs.mkdirSync(root,{recursive:true});
  const port = env.PORT || String(await freePort());
  let output = '';
  const child = spawn(process.execPath,['--import','tsx','server/index.ts'],{cwd:process.cwd(),env:{...process.env,
    INVOCATION_ID:'',DATA_DIR:root,HOST:'127.0.0.1',PORT:port,CODEX:'true',CLAUDE_CODE:'false',CODEX_SCAN:'false',
    CODEX_HOME:path.join(root,'empty-home'),CODEX_EXTRA_HOMES:'',CODEX_ACCOUNT_SCOPE:'true',LOCAL_ONLY:'true',NATIVE_GUI_ONLY:'true',
    QUOTA_POLLING:'false',CLOUD_TASKS:'false',DEMO_MODE:'false',WATCH_SESSIONS:'false',TEAM_ACCOUNT_FINGERPRINT:FP,
    SYNC_SECRET:SECRET,SYNC_HEARTBEAT_MS:'250',SYNC_DEBOUNCE_MS:'30',SYNC_MAX_BACKOFF_MS:'200',
    ...env},stdio:['ignore','pipe','pipe']});
  child.stdout!.on('data',d => output+=String(d)); child.stderr!.on('data',d => output+=String(d));
  const running = {process:child,url:`http://127.0.0.1:${port}`,async stop() {
    if (child.exitCode !== null || child.signalCode !== null) return;
    child.kill('SIGTERM'); await once(child,'exit');
  }};
  try {
    await until(async () => {
      if (child.exitCode !== null) throw new Error(output);
      return (await json(running.url,'/api/health')).value.ok;
    }); return running;
  } catch (e) { await running.stop(); throw new Error(String(e)+'\n'+output); }
}

test('real entry points sync two members and three scanner devices, block other accounts/Claude, and recover offline queues', {timeout:90000}, async () => {
  const root=tempDir('team-real-entry'); const children: Running[]=[];
  let hub: Running | undefined;
  try {
    const hubDir=path.join(root,'hub'); hub=await start(hubDir,{TRACKER_ROLE:'server',DEVICE_ID:'hub'}); children.push(hub);
    assert.equal((await json(hub.url,'/api/health')).value.role,'server');
    const alice=(await json(hub.url,'/api/team/members',{name:'Alice'},'POST')).value;
    const bob=(await json(hub.url,'/api/team/members',{name:'Bob'},'POST')).value;
    assert.ok(alice.id && bob.id);
    assert.equal((await json(hub.url,'/api/team/settings',{monthStartDay:16})).status,200);
    const invitation=(await json(hub.url,`/api/team/invitation?memberId=${alice.id}&url=${encodeURIComponent(hub.url)}`)).value.invitation;
    const invitationData=JSON.parse(Buffer.from(invitation,'base64url').toString());
    assert.equal(invitationData.memberId,alice.id); assert.equal(invitationData.accountFingerprint,FP);
    const devices: Running[]=[];
    for (const [id,member,total] of [['alice-linux',alice.id,1000],['alice-windows',alice.id,2000],['bob-linux',bob.id,3000]] as const) {
      const directory=path.join(root,id); const home=fixtureHome(directory,id,total);
      const collector=await start(directory,{TRACKER_ROLE:'collector',DEVICE_ID:id,MEMBER_ID:member,CODEX_SCAN:'true',CODEX_HOME:home,CENTRAL_URL:hub.url});
      children.push(collector); devices.push(collector);
    }
    const report=await until(async () => {const r=(await json(hub!.url,'/api/team/reports')).value;return sum(r)===6000 && !r.incomplete ? r : null;});
    assert.equal(report.members.find((m:any) => m.id===alice.id).devices,2);
    assert.equal(sum((await json(hub.url,`/api/team/reports?memberId=${alice.id}`)).value),3000);
    assert.equal(sum((await json(devices[0].url,`/api/team/reports?memberId=${bob.id}`)).value),3000);
    assert.equal((await json(devices[0].url,'/api/overview?provider=codex')).status,200);
    assert.equal((await json(devices[0].url,'/api/local-reports')).value.canEditMonthDay,false);
    assert.equal((await json(devices[0].url,'/api/local-reports/settings',{monthStartDay:1})).status,403);
    assert.equal((await json(devices[0].url,'/api/team/settings',{monthStartDay:1})).status,403);
    const unauth=await fetch(hub.url+'/api/team/settings',{method:'PUT',headers:{'content-type':'application/json'},body:'{"monthStartDay":1}'});
    assert.equal(unauth.status,403,'local control requires a native request header');
    await json(hub.url,'/api/team/settings',{monthStartDay:31});
    await until(async () => (await json(devices[1].url,'/api/local-reports')).value.monthStartDay===31);
    assert.equal((await json(devices[2].url,'/api/team/reports')).value.monthStartDay,31);
    // Only event rows reached the hub; no conversations or project paths were uploaded.
    const db=new DatabaseSync(path.join(hubDir,'codex-usage.sqlite'),{readOnly:true});
    try { for (const table of ['prompt_metrics','thread_metadata','session_parts']) assert.equal((db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get() as {n:number}).n,0); }
    finally {db.close();}
    const identity={protocol:1,deviceId:'impostor',deviceLabel:'impostor',installId:'impostor',memberId:alice.id,accountFingerprint:'0'.repeat(64)};
    const upload={...identity,provider:'codex',records:[]};
    assert.equal((await json(hub.url,'/api/sync/upload',upload,'POST',{authorization:`Bearer ${SECRET}`})).status,409);
    assert.equal((await json(hub.url,'/api/sync/upload',{...upload,accountFingerprint:FP,provider:'claude'},'POST',{authorization:`Bearer ${SECRET}`})).status,409);
    assert.equal((await json(hub.url,'/api/sync/upload',{...upload,accountFingerprint:FP},'POST',{authorization:'Bearer wrong'})).status,401);
    // Bring the hub down, collect on another device, then restart the collector and hub.
    const hubPort=new URL(hub.url).port; await hub.stop();
    const offlineDir=path.join(root,'alice-offline'); const home=fixtureHome(offlineDir,'alice-offline',4000);
    let offline=await start(offlineDir,{TRACKER_ROLE:'collector',DEVICE_ID:'alice-offline',MEMBER_ID:alice.id,CODEX_SCAN:'true',CODEX_HOME:home,CENTRAL_URL:hub.url});children.push(offline);
    await until(async () => {const h=(await json(offline.url,'/api/health')).value;return h.sync?.pending?.codex>0 && h.sync.state==='offline';});
    await offline.stop();
    offline=await start(offlineDir,{TRACKER_ROLE:'collector',DEVICE_ID:'alice-offline',MEMBER_ID:alice.id,CODEX_SCAN:'true',CODEX_HOME:home,CENTRAL_URL:hub.url});children.push(offline);
    hub=await start(hubDir,{TRACKER_ROLE:'server',DEVICE_ID:'hub',PORT:hubPort});children.push(hub);
    await until(async () => sum((await json(hub!.url,'/api/team/reports')).value)===10000,30000);
    assert.equal((await json(hub.url,'/api/team/reports')).value.monthStartDay,31);
    assert.equal(sum((await json(hub.url,`/api/team/reports?memberId=${alice.id}`)).value),7000);
    // Force a re-export: idempotent resends never increase total usage.
    await offline.stop();
    const ledger=openStore(offlineDir,'alice-offline',{file:'codex-usage.sqlite',outbox:true});
    ledger.exportAllToOutbox('force-test-resend'); ledger.close();
    offline=await start(offlineDir,{TRACKER_ROLE:'collector',DEVICE_ID:'alice-offline',MEMBER_ID:alice.id,CODEX_SCAN:'true',CODEX_HOME:home,CENTRAL_URL:hub.url});children.push(offline);
    await until(async () => (await json(offline.url,'/api/health')).value.sync?.state==='synced');
    assert.equal(sum((await json(hub.url,'/api/team/reports')).value),10000);
  } finally { for (const c of children.reverse()) await c.stop(); removeDir(root); }
});

test('network-facing hub requires a key and cannot expose local administration or chats', {timeout:30000}, async () => {
  const address=Object.values(os.networkInterfaces()).flat().find(v => v && !v.internal && v.family==='IPv4')?.address;
  if (!address) return;
  const root=tempDir('team-network'); let server:Running|undefined;
  try {
    server=await start(root,{TRACKER_ROLE:'server',DEVICE_ID:'network-hub',HOST:'0.0.0.0'});
    const url=`http://${address}:${new URL(server.url).port}`;
    assert.equal((await json(url,'/api/team')).status,401);
    const auth={authorization:`Bearer ${SECRET}`};
    const team=await json(url,'/api/team',undefined,undefined,auth);
    assert.equal(team.status,200);assert.equal(team.value.canManage,false);
    assert.equal((await json(url,'/api/overview',undefined,undefined,auth)).status,403);
    assert.equal((await json(url,'/api/team/members',{name:'intruder'},'POST',auth)).status,403);
    assert.equal((await json(url,'/api/team/settings',{monthStartDay:1},'PUT',auth)).status,403);
    assert.equal((await json(url,'/api/installation',{},'PUT',auth)).status,403);
  } finally {await server?.stop(); removeDir(root);}
});

test('first scoped startup backs up unscoped caches and rebuilds only eligible local history', {timeout:30000}, async () => {
  const root=tempDir('team-migration'); let server: Running|undefined;
  try {
    const home=fixtureHome(root,'eligible',1500);
    const legacy=openStore(root,'legacy',{file:'codex-usage.sqlite'});
    legacy.ingestRemoteRecords('legacy',parsed([{kind:'event',key:'unverified-cache',data:remoteEvent('unverified-cache','unknown-account',Math.floor(Date.now()/1000)-3000,null,999999)}]));
    legacy.close();
    const source=path.join(home,'sessions','rollout-eligible.jsonl');
    const others=fs.readFileSync(source,'utf8').trim().split('\n').map(s => JSON.parse(s));
    others[0].payload.id='other-account';others[0].payload.creator_account_id='another-account';
    fs.writeFileSync(path.join(home,'sessions','rollout-other.jsonl'),others.map(r => JSON.stringify(r)).join('\n')+'\n');
    const third=structuredClone(others);third[0].payload.id='third-party';third[0].payload.model_provider='external';third[0].payload.creator_account_id=ACCOUNT;
    fs.writeFileSync(path.join(home,'sessions','rollout-third.jsonl'),third.map(r => JSON.stringify(r)).join('\n')+'\n');
    server=await start(root,{TRACKER_ROLE:'server',DEVICE_ID:'local-owner',CODEX_SCAN:'true',CODEX_HOME:home});
    await until(async () => sum((await json(server!.url,'/api/team/reports')).value)===1500);
    const backup=fs.readdirSync(root).find(f => f.startsWith('unscoped-backup-'));
    assert.ok(backup);assert.ok(fs.existsSync(path.join(root,backup,'codex-usage.sqlite')));
    assert.equal(sum((await json(server.url,'/api/local-reports')).value),1500);
    assert.equal((await json(server.url,'/api/overview?provider=codex')).value.modelUsage[0].totalTokens,1500);
  } finally {await server?.stop();removeDir(root);}
});

test('native configuration saves mode and restarts the real backend with the persisted profile', {timeout:30000}, async () => {
  const root=tempDir('team-restart');let server:Running|undefined;let replacementPid:number|undefined;
  try {
    server=await start(root,{TRACKER_ROLE:'standalone',DEVICE_ID:'setup-device'});
    const profile=(await json(server.url,'/api/installation')).value;
    assert.equal(profile.secret,undefined);
    const save=await json(server.url,'/api/installation',{...profile,role:'server',memberName:'Admin',deviceLabel:'Hub',scanLocal:false,accountFingerprint:FP});
    assert.equal(save.status,200); assert.equal(save.value.restartRequired,true);
    assert.equal((await json(server.url,'/api/installation/restart',{},'POST')).status,200);
    const health=await until(async () => {const h=(await json(server!.url,'/api/health')).value;return h.pid!==profile.pid && h.role==='server' ? h : null;});
    replacementPid=health.pid;
    assert.equal(health.scanLocal,false);
    const member=(await json(server.url,'/api/team/members',{name:'Teammate'},'POST')).value;
    assert.ok(member.id);
    assert.equal((await json(server.url,'/api/installation')).value.secret,undefined);
  } finally {
    if (replacementPid) {
      try {process.kill(replacementPid,'SIGTERM');} catch {}
      await new Promise(r => setTimeout(r,250));
    }
    await server?.stop(); removeDir(root);
  }
});
