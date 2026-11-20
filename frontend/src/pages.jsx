import { useMemo, useState } from 'react'
import { API, C, ST, Cv, Num, accCfg, forecastCfg, timeCfg, usd } from './lib.jsx'
 
export const SvcPick = ({ ov, svc, setSvc }) => <select value={svc || ''} onChange={e => setSvc(e.target.value)}>
  {(ov?.services || []).filter(s => s.n > 1).map(s => <option key={s.svc} value={s.svc}>{s.svc} · {s.n} × {s.itype}</option>)}</select>
 
export function Graveyard({ fl, pick }) {
  const [view, setView] = useState('creative'), [f, setF] = useState('all'), [k, setK] = useState('waste')
  const list = useMemo(() => (fl?.servers || []).filter(s => f === 'all' || s.status === f)
    .sort((a, b) => typeof a[k] === 'string' ? String(a[k]).localeCompare(b[k]) : (b[k] ?? 0) - (a[k] ?? 0)), [fl, f, k])
  const cols = [['id', 'Server'], ['itype', 'Type'], ['status', 'Status'], ['avg', 'Avg %'], ['peak', 'Peak %'], ['idle_days', 'Idle d'], ['cost', '$/mo'], ['waste', 'Waste'], ['action', 'Action'], ['conf', 'Conf']]
  return <section className="card">
    <h3>Server graveyard <span className="row">
      {['all', ...Object.keys(ST)].map(s => <button key={s} className={'chip ' + (f === s ? 'on' : '')} onClick={() => setF(s)}>{s === 'all' ? 'All' : ST[s][0]}</button>)}
      <button className="pri" onClick={() => setView(view === 'creative' ? 'formal' : 'creative')}>{view === 'creative' ? 'Formal view' : 'Creative view'}</button></span></h3>
    {view === 'creative' ? <div className="tombs">{list.map(s => <button key={s.id} className="tomb" title={s.reason} style={{ '--c': ST[s.status][1] }} onClick={() => pick(s)}>
      <small>R.I.P.</small><b>{s.id}</b><span>{s.itype}</span><em>{usd(s.cost)}/mo</em>
      <small>{s.idle_days ? `idle ${s.idle_days}d · since ${s.died_on}` : `avg ${s.avg}% · peak ${s.peak}%`}</small><i className="badge">{ST[s.status][0]}</i></button>)}</div>
      : <div className="scroll"><table><thead><tr>{cols.map(([c, n]) => <th key={c} onClick={() => setK(c)}>{n}{k === c ? ' ↓' : ''}</th>)}</tr></thead>
        <tbody>{list.map(s => <tr key={s.id} onClick={() => pick(s)}>{cols.map(([c]) => <td key={c} style={c === 'status' ? { color: ST[s.status][1] } : null}>
          {c === 'cost' || c === 'waste' ? usd(s[c]) : c === 'status' ? ST[s.status][0] : s[c]}</td>)}</tr>)}</tbody></table></div>}
    {!!fl?.buried.length && <p className="hint">⚰ Buried: {fl.buried.map(b => b.id).join(', ')} · saving {usd(fl.buried.reduce((a, b) => a + b.saving, 0))}/mo</p>}
  </section>
}
 
export function Forecast({ p, an }) {
  const cfg = useMemo(() => p && forecastCfg(p), [p]), ac = useMemo(() => an && accCfg(an.accuracy), [an])
  if (!p) return <div className="empty">Computing forecast…</div>
  const s = an?.stats
  return <div className="two"><section className="card"><h3>Demand vs capacity <span className="tag">{p.model.replace('_', '-')} · confidence {Math.round(p.conf * 100)}%</span></h3>
    <Cv cfg={cfg} h={330} /><h3 style={{ marginTop: 18 }}>Forecast accuracy tracker</h3>{ac ? <Cv cfg={ac} h={190} /> : <div className="chart sk" style={{ height: 190 }} />}</section>
    <aside className="card"><h3>Recommendation</h3><p className="rec">{p.rec}</p>
      {p.notes.map(n => <p key={n} className="warnbox">{n}</p>)}
      <h3>Time-series statistics</h3>{s ? <div className="stats">{[['Mean', s.mean], ['Std dev', s.std], ['CV', s.cv], ['P95', s.p95], ['ACF 24h', s.acf24], ['ACF 7d', s.acf168],
        ['Trend/day', s.trend_per_day], ['Trend p', s.trend_p], ['Seasonality', s.seasonal_strength], ['ADF p', s.adf_p ?? 'n/a']].map(([k, v]) => <div key={k}><small>{k}</small><b>{v}</b></div>)}</div> : <p className="hint">Loading…</p>}
      {an && <p className="hint">Model beat the weekly baseline by {Math.round(an.gain * 100)}%. Holdout MAE: {Object.entries(an.scores).map(([k, v]) => `${k} ${v}`).join(' · ')}</p>}
    </aside></div>
}
 
export function Plan({ p, svc, risk }) {
  if (!p) return <div className="empty">Computing plan…</div>
  const mx = Math.max(...p.heat.flat()), D = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  return <div className="two"><section className="card"><h3>Next week's plan: servers per hour <a className="btn" href={`${API}/services/${svc}/schedule.csv?risk=${risk}`}>Export autoscaling schedule</a></h3>
    <div className="heat"><span />{[...Array(24).keys()].map(h => <small key={h}>{h}</small>)}
      {p.heat.map((r, d) => [<small key={'d' + d}>{D[d]}</small>, ...r.map((v, h) => <i key={d + '-' + h} title={`${D[d]} ${h}:00 → ${v} servers`}
        style={{ background: `hsl(${210 - 170 * v / mx} 75% ${22 + 30 * v / mx}%)` }}>{Math.round(v)}</i>)])}</div></section>
    <aside className="card"><h3>Current vs planned</h3>
      <div className="cmp"><div><small>Today ({p.n} fixed)</small><b>{usd(p.now.monthly)}</b><em>{p.now.shortfall_hours} shortfall h · {p.now.overprov_hours} idle h</em></div>
        <div className="good"><small>OptiServe plan</small><b>{usd(p.new.monthly)}</b><em>{p.new.shortfall_hours} shortfall h · {p.new.overprov_hours} idle h</em></div></div>
      <p className="rec">{p.rec}</p>{p.notes.map(n => <p key={n} className="warnbox">{n}</p>)}</aside></div>
}
 
export function TimeMachine({ b }) {
  const cfg = useMemo(() => b && timeCfg(b), [b])
  if (!b) return <div className="empty">Replaying last week…</div>
  const A = b.actual_setup, O = b.optiserve
  return <section className="card"><h3>Time machine: last 7 days replayed <span className="tag good">{b.cheaper_pct}% cheaper</span></h3><Cv cfg={cfg} h={300} />
    <div className="cmp">{[['Actual setup', A, ''], ['OptiServe plan', O, 'good']].map(([t, s, c]) => <div key={t} className={c}><small>{t}</small><b>{usd(s.monthly)}<span>/mo</span></b>
      <em>{s.shortfall_hours} shortfall hours · {s.overprov_hours} over-provisioned hours · {s.avg_util}% avg util</em></div>)}</div>
    <p className="hint">The forecast only saw data before this week; the plan was then replayed against what really happened.</p></section>
}
 
export function WhatIf({ p, w, setW, ov, svc, setSvc }) {
  const cfg = useMemo(() => p && forecastCfg(p), [p]), max = (ov?.services.find(s => s.svc === svc)?.n || 2) - 1
  return <div className="two"><section className="card"><h3>What-if simulator <SvcPick ov={ov} svc={svc} setSvc={setSvc} /></h3>
    <div className="sliders"><label>Traffic growth <b>+{w.growth}%</b><input type="range" min="0" max="150" step="5" value={w.growth} onChange={e => setW({ ...w, growth: +e.target.value })} /></label>
      <label>Remove servers <b>{w.remove}</b><input type="range" min="0" max={max} value={Math.min(w.remove, max)} onChange={e => setW({ ...w, remove: +e.target.value })} /></label>
      <label className="chk"><input type="checkbox" checked={w.events} onChange={e => setW({ ...w, events: e.target.checked })} /> Include calendar events (sale / match)</label></div>
    {p ? <Cv cfg={cfg} h={290} /> : <div className="chart sk" />}</section>
    <aside className="card"><h3>Outcome</h3>{p && <><div className="cmp"><div><small>Current setup</small><b>{usd(p.now.monthly)}</b><em>{p.now.shortfall_hours} shortfall hours</em></div>
      <div className="good"><small>Plan</small><b>{usd(p.new.monthly)}</b><em>{p.new.shortfall_hours} shortfall hours</em></div></div>
      <p className="rec">{p.rec}</p>{p.alerts.map(a => <p key={a[1]} className={a[0] === 'high' ? 'warnbox bad' : 'warnbox'}>{a[1]}</p>)}</>}</aside></div>
}
 
export function Report({ ov, fl, p, bt }) {
  return <section className="card report"><h3>Capacity report <span className="row"><a className="btn" href={`${API}/report.csv`}>CSV</a><button className="pri" onClick={() => window.print()}>Export PDF</button></span></h3>
    <p className="hint">{ov.meta.title} · generated {new Date().toLocaleString()}</p>
    <div className="cmp"><div><small>Monthly spend</small><b>{usd(ov.kpi.cost)}</b></div><div className="good"><small>After OptiServe</small><b>{usd(ov.kpi.cost_after)}</b></div>
      <div><small>Waste score</small><b>{ov.kpi.waste_score}%</b></div>{bt && <div><small>Backtest vs last week</small><b>{bt.cheaper_pct}% cheaper</b></div>}</div>
    <h4>Top recommendations</h4>{ov.recs.map(r => <p key={r.text} className="rec">{r.text}</p>)}
    <h4>Alerts</h4>{ov.alerts.map(a => <p key={a[1]} className="warnbox">{a[1]}</p>)}
    <h4>Fleet</h4><table><thead><tr><th>Server</th><th>Type</th><th>Status</th><th>Avg %</th><th>Peak %</th><th>$/mo</th><th>Action</th></tr></thead>
      <tbody>{fl.servers.map(s => <tr key={s.id}><td>{s.id}</td><td>{s.itype}</td><td>{ST[s.status][0]}</td><td>{s.avg}</td><td>{s.peak}</td><td>{usd(s.cost)}</td><td>{s.action}</td></tr>)}</tbody></table></section>
}
 
