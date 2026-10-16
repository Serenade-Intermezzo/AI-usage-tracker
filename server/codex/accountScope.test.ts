import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createAccountScope,eligibleAt,isMainSurface,readLogin} from './accountScope.js';
import {codexSessionSource} from '../sessionLogs.js';
import {scanAllSessions} from '../sessionScan.js';
import {openStore,tempDir,removeDir} from '../testSupport.js';
const hash=(v:string)=>crypto.createHash('sha256').update(v).digest('hex');
test('account attribution excludes unknown history, other accounts, unobserved gaps, and API logins',()=>{
 const binding={version:1 as const,fingerprint:hash('account-a'),startedAt:100,windows:[{home:'/cli',start:110,end:120}]};
 assert.equal(eligibleAt(binding,'/cli',50,'account-a'),true);
 assert.equal(eligibleAt(binding,'/cli',50,undefined),false);
 assert.equal(eligibleAt(binding,'/cli',115,undefined),true);
 assert.equal(eligibleAt(binding,'/cli',115,'account-b'),false);
 assert.equal(eligibleAt(binding,'/cli',121,'account-a'),false);
 assert.equal(eligibleAt(binding,'/desktop',115,'account-a'),false);
 assert.equal(isMainSurface({source:'cli'},'/cli'),true);
 assert.equal(isMainSurface({source:'vscode'},'/test/.codex-desktop'),true);
 assert.equal(isMainSurface({source:'vscode'},'/test/.codex'),false);
 assert.equal(isMainSurface({source:'exec'},'/test/.codex'),false);
 assert.equal(isMainSurface({source:'vscode',originator:'Codex Desktop'},'C:\\Users\\User\\.codex'),true);
 assert.equal(isMainSurface({source:'vscode',originator:'codex_vscode'},'C:\\Users\\User\\.codex'),false);
});
test('scoped reindex keeps only official GUI/CLI account-tagged history and stable event IDs',async()=>{
 const dir=tempDir('account-scope');const home=path.join(dir,'.codex-desktop');fs.mkdirSync(path.join(home,'sessions'),{recursive:true});
 fs.writeFileSync(path.join(home,'auth.json'),JSON.stringify({auth_mode:'chatgpt',tokens:{account_id:'account-a'}}));
 const scope=createAccountScope(path.join(dir,'scope'),[home]);const store=openStore(path.join(dir,'store'),'local');
 try {
  for (const [name,provider,account,source] of [
   ['current','openai','account-a','vscode'],['api','rightcode','account-a','vscode'],
   ['other','openai','account-b','vscode'],['unknown','openai',undefined,'cli'],['exec','openai','account-a','exec']
  ]) {
   const records=[{type:'session_meta',timestamp:'2026-01-01T00:00:00Z',payload:{id:name,model_provider:provider,creator_account_id:account,source}},
    {type:'turn_context',timestamp:'2026-01-01T00:00:01Z',payload:{model:'gpt-6.1-sol'}},
    {type:'event_msg',timestamp:'2026-01-01T00:00:02Z',payload:{type:'token_count',info:{last_token_usage:{input_tokens:90,cached_input_tokens:20,output_tokens:10,total_tokens:100}}}}];
   fs.writeFileSync(path.join(home,'sessions',`rollout-${name}.jsonl`),records.map(r=>JSON.stringify(r)).join('\n')+'\n');
  }
  const source=scope.wrap(codexSessionSource(home));await scanAllSessions(store,source);
  assert.equal(store.getTokenTotals().totalTokens,100);assert.equal(store.getThreadSummaries()[0].threadId,'current');
  assert.equal(scope.summary().otherProviderFiles,1);assert.equal(scope.summary().unverifiedFiles,1);
  await scanAllSessions(store,source);assert.equal(store.getTokenTotals().totalTokens,100);
  const appendUsage = (timestamp: string) => fs.appendFileSync(path.join(home,'sessions','rollout-unknown.jsonl'), JSON.stringify({type:'event_msg',timestamp,payload:{type:'token_count',info:{last_token_usage:{input_tokens:40,cached_input_tokens:0,output_tokens:10,total_tokens:50}}}})+'\n');
  appendUsage(new Date().toISOString());
  await scanAllSessions(store,source);
  assert.equal(store.getTokenTotals().totalTokens,150,'new CLI usage under observed ChatGPT login is counted');
  fs.writeFileSync(path.join(home,'auth.json'),JSON.stringify({auth_mode:'apikey',tokens:{account_id:'account-a'}}));
  await new Promise(resolve=>setTimeout(resolve,10));
  appendUsage(new Date().toISOString());
  await scanAllSessions(store,source);
  assert.equal(store.getTokenTotals().totalTokens,150,'API-key usage is excluded even when a cached account id remains');
  assert.equal(readLogin(home).mode,'apikey');assert.equal(scope.summary().homes[0].matches,false);
 } finally {scope.stop();store.close();removeDir(dir);}
});
