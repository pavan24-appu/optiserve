import { useCallback, useEffect, useRef, useState } from 'react'
import './styles.css'
import Tower from './tower.jsx'
import { Forecast, Graveyard, Plan, Report, SvcPick, TimeMachine, WhatIf } from './pages'
import { API, C, ST, Num, call, usd } from './lib.jsx'
 
const PAGES = [['tower', 'Control tower'], ['grave', 'Server graveyard'], ['fc', 'Forecast'], ['plan', 'Capacity plan'], ['time', 'Time machine'], ['wi', 'What-if'], ['rep', 'Report']]
 
export default function App() {
  const [sc, setSc] = useState([]), [ov, setOv] = useState(null), [fl, setFl] = useState(null), [svc, setSvc] = useState(null)
  const [risk, setRisk] = useState(.5), [rk, setRk] = useState(.5), [page, setPage] = useState('tower'), [aug, setAug] = useState(false)
  const [p, setP] = useState(null), [bt, setBt] = useState(null), [an, setAn] = useState(null), [wi, setWi] = useState(null)
  const [w, setW] = useState({ growth: 0, remove: 0, events: true }), [live, setLive] = useState(null), [dr, setDr] = useState(null)
  const [busy, setBusy] = useState(false), [toast, setToast] = useState(''), [bell, setBell] = useState(false), file = useRef()
  const say = m => { setToast(m); setTimeout(() => setToast(''), 4000) }
 
  const refresh = useCallback(async () => {
    try { const [o, f] = await Promise.all([call(`/overview?risk=${rk}`), call('/fleet')]); setOv(o); setFl(f)
      const s = o.services.filter(x => x.n > 1); setSvc(v => s.find(x => x.svc === v) ? v : s[0]?.svc) } catch { setOv(null) } }, [rk])
  useEffect(() => { call('/scenarios').then(setSc).catch(() => say('API offline: start the backend')) }, [])
  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { const t = setTimeout(() => setRk(risk), 350); return () => clearTimeout(t) }, [risk])
  const key = ov?.meta.title
  useEffect(() => { setP(null); svc && call(`/services/${svc}/plan?risk=${rk}`).then(setP).catch(e => say(e.message)) }, [svc, rk, key])
  useEffect(() => { setAn(null); svc && page === 'fc' && call(`/services/${svc}/analysis`).then(setAn).catch(() => {}) }, [svc, page, key])
  useEffect(() => { setBt(null); svc && ['time', 'rep'].includes(page) && call(`/services/${svc}/backtest?risk=${rk}`).then(setBt).catch(() => {}) }, [svc, rk, page, key])
  useEffect(() => { setWi(null); svc && page === 'wi' && call(`/services/${svc}/plan?risk=${rk}&growth=${w.growth}&remove=${w.remove}&events=${w.events}`).then(setWi).catch(() => {}) }, [svc, rk, page, w, key])
  useEffect(() => { let s, t; const open = () => { s = new WebSocket(API.replace('http', 'ws') + '/ws/live'); s.onmessage = e => setLive(JSON.parse(e.data)); s.onclose = () => { t = setTimeout(open, 3000) } }
    open(); return () => { clearTimeout(t); s.onclose = null; s.close() } }, [])
 
  const run = async (fn, ok) => { setBusy(true); try { const r = await fn(); ok && say(ok(r)) } catch (e) { say(e.message) } setBusy(false) }
  const load = id => run(async () => { await call(`/scenarios/${id}/load?augment=${aug}`, { method: 'POST' }); await refresh() }, () => 'Scenario loaded')
  const upload = f => { if (!f) return; const fd = new FormData(); fd.append('file', f); run(async () => { const r = await call('/ingest/file', { method: 'POST', body: fd }); await refresh(); return r }, r => `Ingested ${r.rows} rows`) }
  const act = (sid, v) => run(async () => { setFl(await call(`/servers/${sid}/${v}`, { method: 'POST' })); await refresh(); setDr(null) }, () => `${v} done`)
  const high = (ov?.alerts || []).filter(a => a[0] === 'high').length
 
  return <div className="shell">
    <aside className="side"><div className="logo"><i />OptiServe<small>capacity-planning copilot</small></div>
      {PAGES.map(([k, n]) => <button key={k} className={page === k ? 'on' : ''} onClick={() => setPage(k)} disabled={!ov}>{n}</button>)}
      <div className="hint">Prototype: real engine, sample data, simulated cloud actions.</div></aside>
    <div className="main">
      <header className="top"><select value="" onChange={e => e.target.value && load(+e.target.value)}><option value="">{ov ? ov.meta.title : 'Pick a scenario…'}</option>
        {sc.map(s => <option key={s.id} value={s.id}>{s.id}. {s.title}</option>)}</select>
        <label className="chk"><input type="checkbox" checked={aug} onChange={e => setAug(e.target.checked)} /> augment</label>
        <button onClick={() => file.current.click()}>Upload CSV</button><input ref={file} hidden type="file" accept=".csv,.json" onChange={e => upload(e.target.files[0])} />
        <span className={'live ' + (live ? 'on' : '')}>{live ? 'LIVE ' + new Date(live.t).toLocaleString([], { weekday: 'short', hour: '2-digit' }) : 'offline'}</span>
        <label className="risk">Cheapest<input type="range" min="0" max="1" step=".05" value={risk} onChange={e => setRisk(+e.target.value)} />Safest</label>
        {ov && <span className="cost">{usd(ov.kpi.cost)} → <b>{usd(ov.kpi.cost_after)}</b></span>}
        <button className="bell" onClick={() => setBell(!bell)}>🔔{high > 0 && <em>{high}</em>}</button>
        {bell && <div className="pop">{ov?.alerts.length ? ov.alerts.map(a => <p key={a[1]} className={a[0]}>{a[1]}</p>) : <p>No alerts</p>}</div>}</header>
 
      {!ov ? <div className="card welcome"><h2>Stop paying for servers nobody uses.</h2><p className="hint">Pick a scenario to load telemetry, or upload your own CSV (server, ts, cpu, ram).</p>
        <div className="scs">{sc.map(s => <button key={s.id} onClick={() => load(s.id)}><b>{s.id}. {s.title}</b><small>{s.story}</small></button>)}</div></div> : <>
      {page === 'tower' && <>
        <section className="kpis">{[['Monthly spend', ov.kpi.cost, usd], ['Avg utilisation', ov.kpi.util, x => x.toFixed(0) + '%'], ['Waste score', ov.kpi.waste_score, x => Math.round(x) + '%', 'warn'],
          ['Potential savings', ov.kpi.potential, usd, 'good'], ['Servers', ov.kpi.servers, x => Math.round(x)]].map(([k, v, f, c]) => <div key={k} className={'kpi ' + (c || '')}><span>{k}</span><b><Num v={v} f={f} /></b></div>)}</section>
        <div className="status">{Object.entries(ov.status).map(([k, v]) => <i key={k} style={{ flex: v, background: ST[k][1] }} title={ST[k][0]}>{ST[k][0]} {v}</i>)}</div>
        <section className="card"><h3>Air-traffic control: live workload routing <span className="hint">workloads are flights · cyan = AI rerouted from an overloaded server</span></h3>
          <Tower servers={fl.servers} loads={live?.loads} onPick={setDr} /></section>
        <div className="two"><section className="card"><h3>Top recommendations</h3>{ov.recs.map(r => <p key={r.text} className="rec"><b>{usd(r.saving)}/mo</b> {r.text}</p>)}</section>
          <section className="card"><h3>Live alerts</h3>{ov.alerts.map(a => <p key={a[1]} className={'warnbox ' + (a[0] === 'high' ? 'bad' : '')}>{a[1]}</p>)}</section></div></>}
      {['fc', 'plan', 'time', 'rep'].includes(page) && page !== 'rep' && <div className="bar2"><SvcPick ov={ov} svc={svc} setSvc={setSvc} /></div>}
      {page === 'grave' && <Graveyard fl={fl} pick={setDr} />}
      {page === 'fc' && <Forecast p={p} an={an} />}
      {page === 'plan' && <Plan p={p} svc={svc} risk={rk} />}
      {page === 'time' && <TimeMachine b={bt} />}
      {page === 'wi' && <WhatIf p={wi} w={w} setW={setW} ov={ov} svc={svc} setSvc={setSvc} />}
      {page === 'rep' && <Report ov={ov} fl={fl} p={p} bt={bt} />}</>}
    </div>
    {dr && <div className="drawer"><button className="x" onClick={() => setDr(null)}>×</button><h3>{dr.id}</h3><span className="tag" style={{ '--c': ST[dr.status][1] }}>{ST[dr.status][0]}</span>
      <p className="hint">{dr.service} · {dr.itype} · {usd(dr.cost)}/mo</p><div className="stats">{[['Avg CPU', dr.avg + '%'], ['Peak', dr.peak + '%'], ['Idle days', dr.idle_days], ['Confidence', Math.round(dr.conf * 100) + '%']].map(([k, v]) => <div key={k}><small>{k}</small><b>{v}</b></div>)}</div>
      <p className="rec">{dr.reason}</p><div className="btns"><button className="pri" disabled={busy} onClick={() => act(dr.id, 'bury')}>Bury</button>
        <button disabled={busy} onClick={() => act(dr.id, 'shrink')}>Shrink → {dr.to}</button><button disabled={busy} onClick={() => act(dr.id, 'keep')}>Keep</button></div>
      <p className="hint">Risky, hot or resurrected servers are blocked from burial by the guardrails.</p></div>}
    {busy && <div className="busy"><i />Working…</div>}{toast && <div className="toast">{toast}</div>}
  </div>
}
 
