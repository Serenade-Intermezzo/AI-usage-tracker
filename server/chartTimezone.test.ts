import assert from 'node:assert/strict';
import test from 'node:test';
import {addLocalChat,localEvent,openStore,tempDir,removeDir} from './testSupport.js';

test('native daily chart and weekday heatmap use Shanghai time independently of host time zone',()=>{
 const directory=tempDir('chart-timezone');const store=openStore(directory,'local');
 try {
  const timestamp=Math.floor(Date.now()/86400000)*86400-86400+20*3600;
  addLocalChat(store,'chart-chat',[localEvent('chart-event','chart-chat',timestamp,null,1234)]);
  const expected=new Date((timestamp+8*3600)*1000);
  const day=expected.toISOString().slice(0,10);
  assert.deepEqual(store.getLocalDailyUsage(30).map(row=>({...row})),[{date:day,tokens:1234,source:'local'}]);
  const heatmap=store.getHourlyActivity(30);
  assert.equal(heatmap[expected.getUTCDay()][4],1234);
  assert.equal(heatmap.flat().reduce((sum,value)=>sum+value,0),1234);
 } finally {store.close();removeDir(directory);}
});
