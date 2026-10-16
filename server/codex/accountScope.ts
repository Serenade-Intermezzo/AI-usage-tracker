import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import type { ResumableParser, SessionSource } from '../sessionScan.js';

interface Header {originator?: string; id?: string; model_provider?: string; source?: unknown; creator_account_id?: string; parent_thread_id?: string;}
interface Window {home: string; start: number; end: number;}
interface Binding {version: 1; fingerprint: string; startedAt: number; windows: Window[];}
const hash = (value: string) => crypto.createHash('sha256').update(value).digest('hex');
export function readLogin(home: string): {mode: string; fingerprint: string | null} {
  try {
    const a = JSON.parse(fs.readFileSync(path.join(home, 'auth.json'), 'utf8'));
    // Only the non-secret account identifier is used. Never persist tokens or passwords.
    return {mode: a.auth_mode ?? 'unknown', fingerprint: typeof a.tokens?.account_id === 'string' ? hash(a.tokens.account_id) : null};
  } catch { return {mode: 'unknown', fingerprint: null}; }
}
function atomic(file: string, value: unknown): void {
  fs.writeFileSync(file + '.tmp', JSON.stringify(value, null, 2) + '\n', {mode: 0o600});
  fs.renameSync(file + '.tmp', file);
}
function header(file: string): Header {
  let fd: number | undefined;
  try {
    fd = fs.openSync(file, 'r');
    const b = Buffer.alloc(1024 * 1024);
    const count = fs.readSync(fd, b, 0, b.length, 0);
    const line = b.toString('utf8', 0, count).split('\n', 1)[0];
    const record = JSON.parse(line);
    return record.type === 'session_meta' ? record.payload : {};
  } catch {return {};} finally {if (fd !== undefined) fs.closeSync(fd);}
}
export function isMainSurface(h: Header, home: string): boolean {
  if (h.source === 'cli' || h.source === 'tui') return true;
  if (h.source === 'desktop') return true;
  // Codex Desktop writes source=vscode; a separate IDE home is outside this scope.
  return h.source === 'vscode' && (/codex.*desktop|codex_work_desktop/i.test(h.originator ?? '') || (path.basename(home) === '.codex-desktop' && h.originator !== 'codex_vscode'));
}
export function eligibleAt(binding: Binding, home: string, at: number, creator: string | undefined): boolean {
  if (creator && hash(creator) !== binding.fingerprint) return false;
  if (at < binding.startedAt) return !!creator && hash(creator) === binding.fingerprint;
  return binding.windows.some((w) => w.home === home && at >= w.start && at <= w.end);
}
export function createAccountScope(dataDir: string, homes: string[]) {
  const file = path.join(dataDir, 'account-scope.json');
  fs.mkdirSync(dataDir, {recursive:true});
  let binding: Binding;
  if (fs.existsSync(file)) binding = JSON.parse(fs.readFileSync(file, 'utf8'));
  else {
    const primary = readLogin(homes[0]);
    if (primary.mode !== 'chatgpt' || !primary.fingerprint) throw new Error('当前主 Codex 目录未通过 OpenAI 账号登录，不能建立账号统计。');
    binding = {version:1, fingerprint:primary.fingerprint, startedAt:Math.floor(Date.now()/1000), windows:[]};
    atomic(file,binding);
  }
  let audit = {officialFiles:0, otherProviderFiles:0, otherAccountFiles:0, unverifiedFiles:0, otherSurfaceFiles:0};
  const byId = new Map<string, Header>();
  function observe() {
    const now = Date.now()/1000;
    for (const home of homes) {
      const login = readLogin(home);
      if (login.mode !== 'chatgpt' || login.fingerprint !== binding.fingerprint) continue;
      const previous = [...binding.windows].reverse().find((w) => w.home === home);
      if (previous && now - previous.end <= 4) previous.end = now;
      else binding.windows.push({home,start:now,end:now});
    }
    atomic(file,binding);
  }
  function parent(h: Header): Header | undefined {
    const source = h.source as {subagent?:{thread_spawn?:{parent_thread_id?:string}}} | undefined;
    const id = h.parent_thread_id ?? source?.subagent?.thread_spawn?.parent_thread_id;
    return id ? byId.get(id) : undefined;
  }
  function surface(h: Header, home: string, depth = 0): boolean {
    if (isMainSurface(h,home)) return true;
    const p = depth < 10 ? parent(h) : undefined;
    return !!p && p.model_provider === 'openai' && surface(p,home,depth+1);
  }
  function creator(h: Header, depth = 0): string | undefined {
    if (h.creator_account_id) return h.creator_account_id;
    const p = depth < 10 ? parent(h) : undefined;
    return p ? creator(p,depth+1) : undefined;
  }
  observe();
  const timer = setInterval(observe, 1000); timer.unref();
  function wrap(source: SessionSource): SessionSource {
    return {...source, parserVersion: source.parserVersion + ':account-scope-1',
      async listFiles() {
        const files = await source.listFiles();
        byId.clear();
        const headers = files.map((f) => ({file:f, h:header(f), home:homes.find((home) => f.startsWith(home + path.sep))!}));
        for (const {h} of headers) if (h.id) byId.set(h.id,h);
        audit = {officialFiles:0,otherProviderFiles:0,otherAccountFiles:0,unverifiedFiles:0,otherSurfaceFiles:0};
        for (const {h,home} of headers) {
          if (h.model_provider !== 'openai') audit.otherProviderFiles++;
          else if (!surface(h,home)) audit.otherSurfaceFiles++;
          else if (creator(h) && hash(creator(h)!) !== binding.fingerprint) audit.otherAccountFiles++;
          else if (!creator(h)) audit.unverifiedFiles++;
          else audit.officialFiles++;
        }
        observe();
        return files;
      },
      createParser(filePath: string, raw?: unknown): ResumableParser {
        observe();
        const saved = raw as {inner:unknown; header:Header} | undefined;
        const parser = source.createParser(filePath,saved?.inner);
        let meta: Header = saved?.header ?? {};
        const home = homes.find((home) => filePath.startsWith(home + path.sep)) ?? '';
        return {
          feed(line) {
            let r: {type?:string; timestamp?:string; payload?:Header};
            try {r=JSON.parse(line);} catch {parser.feed(line);return;}
            if (r.type === 'session_meta') {meta=r.payload ?? {};if(meta.id) byId.set(meta.id,meta);parser.feed(line);return;}
            if (r.type === 'turn_context') {parser.feed(line);return;}
            const at = typeof r.timestamp === 'string' ? Date.parse(r.timestamp)/1000 : NaN;
            const allowed = meta.model_provider === 'openai' && surface(meta,home) && Number.isFinite(at) && eligibleAt(binding,home,at,creator(meta));
            // Blank lines preserve original line numbers and stable event identifiers.
            parser.feed(allowed ? line : '');
          },
          snapshot: () => ({inner:parser.snapshot(), header:meta}),
          identity: () => parser.identity(),
          finish: () => parser.finish()
        };
      }
    };
  }
  return {wrap, stop:() => clearInterval(timer), summary:() => ({
    enabled:true, boundAccount:binding.fingerprint.slice(0,12), monitoringSince:binding.startedAt,
    ...audit, homes:homes.map((home) => {const s=readLogin(home);return {label:path.basename(home), matches:s.mode==='chatgpt' && s.fingerprint===binding.fingerprint};}),
    note:'历史仅纳入带当前账号标识的官方日志；无账号标记的记录仅在监测到当前账号登录的时段计入。离线期间的无标记历史不推定账号。'
  })};
}
