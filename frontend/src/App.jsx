import { useCallback, useEffect, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import './styles.css'
 
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const call = (p, o) => fetch(API + p, o).then(async r => {
  if (!r.ok) throw new Error((await r.text()).slice(0, 140)); return r.json() })
const usd = n => '$' + Math.round(n).toLocaleString()
const COL = { idle: '#ffb547', risk: '#ff5d73', optimal: '#3ddc97' }
const LABEL = { idle: 'Over-provisioned', risk: 'Peak risk', optimal: 'Optimal' }
 
function Num({ v, f = x => Math.round(x) }) {
  const [x, setX] = useState(0), from = useRef(0)
  useEffect(() => {
    const a = from.current, t0 = performance.now(); let id
    const step = t => { const k = Math.min(1, (t - t0) / 700)
      setX(a + (v - a) * (1 - (1 - k) ** 3)); k < 1 ? id = requestAnimationFrame(step) : from.current = v }
    id = requestAnimationFrame(step); return () => cancelAnimationFrame(id)
  }, [v])
  return f(x)
}
 
function Forecast({ s }) {
  const ref = useRef(), ch = useRef()
  useEffect(() => {
    ch.current?.destroy()
    const n = s.hist.length, m = s.margin
    const labels = [...s.hts, ...s.fts].map(t => new Date(t).toLocaleString([], { weekday: 'short', hour: '2-digit' }))
    const fc = [...Array(n - 1).fill(null), s.hist.at(-1), ...s.fc]
    ch.current = new Chart(ref.current, { type: 'line', data: { labels, datasets: [
      { label: 'Actual', data: [...s.hist, ...Array(s.fc.length).fill(null)], borderColor: '#5ce1ff', backgroundColor: 'rgba(92,225,255,.12)', fill: true },
      { label: 'Forecast', data: fc, borderColor: '#ffb547', borderDash: [6, 4] },
      { label: 'Upper', data: fc.map(v => v == null ? null : Math.min(100, v + m)), borderColor: 'transparent', backgroundColor: 'rgba(255,181,71,.12)', fill: '-1' },
      { label: 'Risk 85%', data: labels.map(() => 85), borderColor: '#ff5d73', borderDash: [2, 4], borderWidth: 1 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 600 }, interaction: { intersect: false, mode: 'index' },
        elements: { point: { radius: 0 }, line: { tension: .35, borderWidth: 2 } },
        scales: { y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,.06)' }, ticks: { color: '#8b96b8', callback: v => v + '%' } },
                  x: { grid: { display: false }, ticks: { color: '#8b96b8', maxTicksLimit: 7 } } },
        plugins: { legend: { labels: { color: '#c9d2ef', boxWidth: 12, filter: l => l.text !== 'Upper' } } } } })
    return () => ch.current?.destroy()
  }, [s])
  return <div className="chart"><canvas ref={ref} /></div>
}
 
export default function App() {
  const [d, setD] = useState(null), [sel, setSel] = useState(null), [ser, setSer] = useState(null)
  const [busy, setBusy] = useState(false), [toast, setToast] = useState(''), [over, setOver] = useState(false)
  const file = useRef()
  const say = m => { setToast(m); setTimeout(() => setToast(''), 3500) }
  const load = useCallback(() => call('/dashboard').then(setD).catch(() => say('API offline - start the backend')), [])
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [load])
  useEffect(() => { setSer(null); sel && call(`/servers/${sel}/series`).then(setSer).catch(() => {}) }, [sel, d?.summary.servers])
 
  const run = async (fn, ok) => { setBusy(true)
    try { const r = await fn(); if (r?.summary) setD(r); ok && say(ok(r)) } catch (e) { say(e.message) } setBusy(false) }
  const upload = f => { if (!f) return; const fd = new FormData(); fd.append('file', f)
    run(async () => { const r = await call('/ingest/file', { method: 'POST', body: fd }); await load(); return r }, r => `Ingested ${r.rows} rows`) }
  const decide = (id, v) => run(() => call(`/actions/${id}/${v}`, { method: 'POST' }),
    r => v === 'approve' ? `Applied via ${r.cloud.api} -> ${r.cloud.type}` : 'Rejected')
 
  const S = d?.summary, srv = d?.servers || [], cur = srv.find(x => x.id === sel)
  const pend = (d?.actions || []).filter(a => a.status === 'pending')
  const kpis = S && [['Monthly spend', S.spend, usd], ['Wasted spend', S.waste, usd, 'warn'],
    ['Potential saving', S.savings_pct, x => x.toFixed(1) + '%', 'good'], ['Efficiency', S.efficiency, x => Math.round(x) + '/100']]
 
  return <div className="app">
    <header><div className="logo"><i />OptiServe<small>pay only for the compute you use</small></div>
      <nav><button onClick={() => window.open(API + '/report.csv')}>Export report</button>
        <button className="pri" disabled={busy || !srv.length} onClick={() => run(() => call('/optimize', { method: 'POST' }), () => 'Optimizer produced a plan')}>Run optimizer</button></nav></header>
 
    {S && <section className="kpis">{kpis.map(([k, v, f, c]) => <div key={k} className={'kpi ' + (c || '')}><span>{k}</span><b><Num v={v} f={f} /></b></div>)}
      <div className="kpi mix"><span>Fleet health</span><div className="bar">
        {['optimal', 'idle', 'risk'].map(k => <i key={k} style={{ flex: S[k] || 0.001, background: COL[k] }} title={LABEL[k]} />)}</div>
        <em>{S.optimal} ok · {S.idle} idle · {S.risk} at risk</em></div></section>}
 
    <div className={'drop ' + (over ? 'over' : '')} onClick={() => file.current.click()}
      onDragOver={e => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
      onDrop={e => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]) }}>
      <input ref={file} type="file" accept=".json,.csv" hidden onChange={e => upload(e.target.files[0])} />
      <span>Drop <code>metrics.csv</code> / <code>.json</code> (server, ts, cpu, ram) or click</span>
      <button onClick={e => { e.stopPropagation(); run(() => call('/seed', { method: 'POST' }), () => 'Loaded 12 sample servers') }}>1-click sample data</button></div>
 
    {!srv.length ? <div className="empty">No telemetry yet. Load sample data to watch OptiServe find the waste.</div> :
    <main><section className="grid card"><h3>Server power grid
        <span className="legend">{Object.keys(COL).map(k => <em key={k} style={{ '--c': COL[k] }}>{LABEL[k]}</em>)}</span></h3>
      <div className="pods">{srv.map(a => <button key={a.id} onClick={() => setSel(a.id)}
        className={`pod ${a.status} ${sel === a.id ? 'on' : ''}`} style={{ '--c': COL[a.status], '--u': Math.min(100, a.avg_cpu) + '%' }}>
        <span className="fill" /><b>{a.id}</b><small>{a.itype}</small><i>{a.avg_cpu}%</i></button>)}</div></section>
 
      <aside className="card detail">{!cur ? <p className="hint">Select a server pod to see its 7-day forecast and rightsizing plan.</p> : <>
        <h3>{cur.id} <span className="tag" style={{ '--c': COL[cur.status] }}>{LABEL[cur.status]}</span></h3>
        {ser ? <Forecast s={ser} /> : <div className="chart sk" />}
        <div className="bands">{[['Night', cur.night], ['Normal', cur.normal], ['Peak', cur.peak]].map(([k, v]) =>
          <div key={k}><span>{k}</span><div><i style={{ width: v + '%', background: v > 85 ? COL.risk : v < 25 ? COL.idle : COL.optimal }} /></div><b>{v}%</b></div>)}</div>
        <div className="rec"><div><small>Recommended</small><b>{cur.itype} → {cur.target}</b></div>
          <div><small>{cur.saving >= 0 ? 'Saves / mo' : 'Adds / mo'}</small><b style={{ color: cur.saving >= 0 ? COL.optimal : COL.risk }}>{usd(Math.abs(cur.saving))}</b></div></div>
        <p className="hint">{cur.reason}</p></>}</aside>
 
      <section className="card queue"><h3>Approval queue <span className="count">{pend.length}</span></h3>
        {!pend.length && <p className="hint">Nothing pending. Run the optimizer to generate scaling actions.</p>}
        {(d.actions).slice(0, 12).map(a => <div key={a.id} className={'act ' + a.status}>
          <div><b>{a.sid}</b> <small>{a.frm} → {a.to}</small></div><span>{a.saving >= 0 ? '-' : '+'}{usd(Math.abs(a.saving))}/mo</span>
          {a.status === 'pending' ? <div className="btns"><button disabled={busy} onClick={() => decide(a.id, 'approve')}>Approve</button>
            <button className="ghost" disabled={busy} onClick={() => decide(a.id, 'reject')}>Reject</button></div> : <em>{a.status}</em>}</div>)}</section></main>}
    {toast && <div className="toast">{toast}</div>}</div>
}