import { useEffect, useState } from 'react';
import { compact } from '../format';
interface Period {
  start: string; endExclusive: string; status: 'open' | 'closed'; total: number;
  input: number; cached: number; output: number; chats: number; activeDays: number;
  firstRecordedPeriod: boolean;
}
interface Reports {
  monthStartDay: number; generatedAt: number; firstEventAt: number | null; weekly: Period[]; monthly: Period[];
}
async function fetchReports(day?: number): Promise<Reports> {
  const r = await fetch(day === undefined ? '/api/local-reports' : '/api/local-reports/settings', day === undefined ? undefined : {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({monthStartDay: day})
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || '读取报表失败');
  return data;
}
function endLabel(exclusive: string): string {
  return new Date(Date.parse(exclusive + 'T00:00:00Z') - 86400000).toISOString().slice(0, 10);
}
export function LocalReports() {
  const [data, setData] = useState<Reports | null>(null);
  const [day, setDay] = useState(1);
  const [view, setView] = useState<'weekly' | 'monthly'>('weekly');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    const load = () => fetchReports().then((r) => {if (alive) {setData(r); setError('');}}).catch((e) => {if (alive) setError(e.message);});
    fetchReports().then((r) => {if (alive) {setData(r); setDay(r.monthStartDay);}}).catch((e) => {if (alive) setError(e.message);});
    const timer = window.setInterval(load, 30000);
    return () => {alive = false; window.clearInterval(timer);};
  }, []);
  async function save() {
    setSaving(true); setMessage(''); setError('');
    try {const r = await fetchReports(day);setData(r);setMessage('已保存，历史月报已更新。');}
    catch(e) {setError((e as Error).message);} finally {setSaving(false);}
  }
  const rows = data ? data[view].filter(r => r.total > 0 || r.status === 'open') : [];
  const total = data?.weekly.reduce((sum, r) => sum + r.total, 0) ?? 0;
  return <section className="section period-reports" id="reports" aria-label="周报与月报">
    <div className="usage-summary">
      {[{label:'累计用量',value:total,note:'当前账号 · 已确认记录'},
        {label:'本周',value:data?.weekly[0]?.total ?? 0,note:'周一至周日'},
        {label:'本月',value:data?.monthly[0]?.total ?? 0,note:data ? `每月 ${data.monthStartDay} 日起算` : '读取中'}].map(item =>
        <div key={item.label} className="usage-summary-card"><span>{item.label}</span><strong title={item.value.toLocaleString('zh-CN')+' Token'}>{compact(item.value)}<small> Token</small></strong><p>{item.note}</p></div>)}
    </div>
    <div className="panel report-panel">
      <div className="report-toolbar"><div className="segmented" role="group" aria-label="报表周期">
        <button type="button" className={view==='weekly'?'active':''} onClick={()=>setView('weekly')}>周报</button>
        <button type="button" className={view==='monthly'?'active':''} onClick={()=>setView('monthly')}>月报</button>
      </div>
      <div className="report-month-setting"><label>月度起始日 <select aria-label="月度起始日" value={day} onChange={e=>{setDay(Number(e.target.value));setMessage('');}}>{Array.from({length:31},(_,i)=><option key={i+1} value={i+1}>{i+1}</option>)}</select> 日</label>
        {data && day!==data.monthStartDay ? <button className="button" disabled={saving} onClick={()=>void save()}>{saving?'保存中…':'保存'}</button>:null}</div></div>
      {message ? <p className="report-message" role="status">{message}</p>:null}
      {error ? <p className="report-message" role="alert">{error}</p>:null}
      <div className="period-scroll"><table className="period-table"><thead><tr><th>周期</th><th>总 Token</th><th>输入</th><th>输出</th><th>聊天数</th><th>状态</th></tr></thead>
        <tbody>{rows.map(r=><tr key={r.start}><td>{r.start} <span className="muted">—</span> {endLabel(r.endExclusive)}</td>
          {[r.total,r.input,r.output].map((value,i)=><td key={i} title={value.toLocaleString('zh-CN')+' Token'}>{compact(value)}</td>)}
          <td>{r.chats}</td><td><span className={r.status==='open'?'period-open':'muted'}>{r.status==='open'?'进行中':'已结束'}</span></td></tr>)}</tbody></table></div>
      {!data ? <p className="report-message">正在读取记录…</p>:null}
      <div className="report-bottom">北京时间 · 周期结束后自动汇总 · 输入已包含缓存{view==='monthly'?' · 短月份使用当月最后一天':''}</div>
    </div>
  </section>;
}
