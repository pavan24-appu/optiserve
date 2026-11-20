import { useEffect, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
 
export const API = import.meta.env.VITE_API || 'http://localhost:8000'
export const call = (p, o) => fetch(API + p, o).then(async r => {
  if (!r.ok) { let m = await r.text(); try { m = JSON.parse(m).detail || m } catch {} throw new Error(String(m).slice(0, 160)) }
  return r.json() })
export const usd = n => '$' + Math.round(n).toLocaleString()
export const fmt = t => new Date(t).toLocaleString([], { weekday: 'short', hour: '2-digit' })
export const C = { cy: '#5ce1ff', am: '#ffb547', rd: '#ff5d73', gn: '#3ddc97', vi: '#a78bfa' }
export const ST = { zombie: ['Zombie', C.vi], wasteful: ['Wasteful', C.am], risky: ['Risky', C.rd], hot: ['Running hot', C.rd],
  resurrected: ['Resurrected', C.cy], rightsized: ['Rightsized', C.gn] }
export const loadColor = l => l > 85 ? C.rd : l < 25 ? C.am : C.gn
 
export function Num({ v, f = x => Math.round(x) }) {
  const [x, setX] = useState(0), from = useRef(0)
  useEffect(() => {
    const a = from.current, t0 = performance.now(); let id
    const step = t => { const k = Math.min(1, (t - t0) / 700); setX(a + (v - a) * (1 - (1 - k) ** 3)); k < 1 ? id = requestAnimationFrame(step) : from.current = v }
    id = requestAnimationFrame(step); return () => cancelAnimationFrame(id)
  }, [v])
  return f(x)
}
 
export function Cv({ cfg, h = 280 }) {
  const r = useRef(), c = useRef()
  useEffect(() => { c.current?.destroy(); c.current = new Chart(r.current, cfg); return () => c.current?.destroy() }, [cfg])
  return <div className="chart" style={{ height: h }}><canvas ref={r} /></div>
}
 
const opt = (y = {}) => ({ responsive: true, maintainAspectRatio: false, animation: { duration: 500 }, interaction: { intersect: false, mode: 'index' },
  elements: { point: { radius: 0 }, line: { tension: .3, borderWidth: 2 } },
  scales: { y: { grid: { color: 'rgba(255,255,255,.06)' }, ticks: { color: '#8b96b8' }, ...y }, x: { grid: { display: false }, ticks: { color: '#8b96b8', maxTicksLimit: 8 } } },
  plugins: { legend: { labels: { color: '#c9d2ef', boxWidth: 12, filter: l => !['High', 'Low'].includes(l.text) } } } })
const pad = k => Array(Math.max(0, k)).fill(null)
 
export const forecastCfg = p => { const n = p.hist.length, v = p.vcpu, lab = [...p.hts, ...p.fts].map(fmt)
  return { type: 'line', options: opt({ title: { display: true, text: 'vCPU demand', color: '#8b96b8' }, min: 0 }), data: { labels: lab, datasets: [
    { label: 'Actual demand', data: [...p.hist, ...pad(p.exp.length)], borderColor: C.cy, backgroundColor: 'rgba(92,225,255,.1)', fill: true },
    { label: 'Forecast', data: [...pad(n - 1), p.hist.at(-1), ...p.exp], borderColor: C.am, borderDash: [6, 4] },
    { label: 'High', data: [...pad(n), ...p.hi], borderColor: 'transparent', backgroundColor: 'rgba(255,181,71,.14)', fill: '+1' },
    { label: 'Low', data: [...pad(n), ...p.lo], borderColor: 'transparent' },
    { label: 'Current capacity', data: lab.map(() => p.n * v), borderColor: C.rd, borderDash: [2, 4], borderWidth: 1.5 },
    { label: 'Planned capacity', data: [...pad(n), ...p.plan.map(x => x * v)], borderColor: C.gn, stepped: true }] } } }
 
export const timeCfg = b => ({ type: 'line', options: opt({ title: { display: true, text: 'servers', color: '#8b96b8' }, min: 0 }), data: { labels: b.ts.map(fmt), datasets: [
  { label: 'Real demand (server-equiv.)', data: b.demand, borderColor: C.cy, backgroundColor: 'rgba(92,225,255,.1)', fill: true },
  { label: 'Actual setup', data: b.now, borderColor: C.rd, borderDash: [4, 4] },
  { label: 'OptiServe plan', data: b.plan, borderColor: C.gn, stepped: true }] } })
 
export const accCfg = a => ({ type: 'bar', options: opt({ title: { display: true, text: 'forecast error % (lower is better)', color: '#8b96b8' } }), data: { labels: a.map(x => x.day.slice(5)), datasets: [
  { label: 'Baseline (same hour last week)', data: a.map(x => x.baseline * 100), backgroundColor: 'rgba(139,150,184,.5)' },
  { label: 'OptiServe model', data: a.map(x => x.model * 100), backgroundColor: C.cy }] } })
 
