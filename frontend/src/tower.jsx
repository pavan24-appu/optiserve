import { useEffect, useRef } from 'react'
import { loadColor } from './lib.js'
 
// Air-traffic-control view: servers = aircraft, workloads = incoming flights, AI = tower that reroutes traffic from overloaded servers.
export default function Tower({ servers, loads, onPick }) {
  const cv = useRef(), nodes = useRef([]), L = useRef({}), parts = useRef([])
  L.current = loads || {}
  useEffect(() => {
    const c = cv.current, x = c.getContext('2d'); let raf, W = 0, H = 0, ang = 0
    const fit = () => { const r = c.getBoundingClientRect(), d = devicePixelRatio || 1; c.width = r.width * d; c.height = r.height * d
      x.setTransform(d, 0, 0, d, 0, 0); W = r.width; H = r.height
      const sv = [...servers].sort((a, b) => a.service.localeCompare(b.service)), R = Math.min(W, H) / 2
      nodes.current = sv.map((s, i) => { const a = (i / sv.length) * 6.283 - 1.57, rr = R * (i % 2 ? .78 : .55)
        return { s, x: W / 2 + Math.cos(a) * rr * 1.5, y: H / 2 + Math.sin(a) * rr * .95, a } }) }
    fit(); addEventListener('resize', fit)
    const load = n => L.current[n.s.id] ?? n.s.avg
    const spawn = () => { const ns = nodes.current; if (!ns.length) return
      const w = ns.map(n => load(n) + 5), tot = w.reduce((a, b) => a + b, 0); let r = Math.random() * tot, t = ns[0]
      for (let i = 0; i < ns.length; i++) { r -= w[i]; if (r <= 0) { t = ns[i]; break } }
      let re = false
      if (load(t) > 85 && Math.random() < .7) { const alt = ns.filter(n => n.s.service === t.s.service && n !== t).sort((a, b) => load(a) - load(b))[0]; if (alt) { t = alt; re = true } }
      const e = Math.random() * 6.283; parts.current.push({ x: W / 2 + Math.cos(e) * W, y: H / 2 + Math.sin(e) * H, t, p: 0, re }) }
    const draw = () => {
      x.clearRect(0, 0, W, H); const cx = W / 2, cy = H / 2; ang += .012
      x.strokeStyle = 'rgba(92,225,255,.08)'; x.lineWidth = 1
      for (const k of [.25, .5, .75, 1]) { x.beginPath(); x.ellipse(cx, cy, W * .5 * k, H * .5 * k, 0, 0, 6.283); x.stroke() }
      const g = x.createLinearGradient(cx, cy, cx + Math.cos(ang) * W / 2, cy + Math.sin(ang) * H / 2)
      g.addColorStop(0, 'rgba(92,225,255,.35)'); g.addColorStop(1, 'rgba(92,225,255,0)')
      x.strokeStyle = g; x.lineWidth = 2; x.beginPath(); x.moveTo(cx, cy); x.lineTo(cx + Math.cos(ang) * W / 2, cy + Math.sin(ang) * H / 2); x.stroke()
      if (Math.random() < .35) spawn()
      parts.current = parts.current.filter(q => q.p < 1)
      for (const q of parts.current) { q.p += q.re ? .012 : .015
        const px = q.x + (q.t.x - q.x) * q.p, py = q.y + (q.t.y - q.y) * q.p
        x.fillStyle = q.re ? '#5ce1ff' : 'rgba(232,236,255,.85)'; x.shadowColor = q.re ? '#5ce1ff' : '#fff'; x.shadowBlur = 8
        x.beginPath(); x.arc(px, py, q.re ? 3 : 2, 0, 6.283); x.fill() }
      x.shadowBlur = 0
      for (const n of nodes.current) { const l = load(n), col = loadColor(l), r = 9 + l / 14
        if (l > 85) { x.strokeStyle = col; x.globalAlpha = .5 + .5 * Math.sin(performance.now() / 160); x.beginPath(); x.arc(n.x, n.y, r + 7, 0, 6.283); x.stroke(); x.globalAlpha = 1 }
        x.save(); x.translate(n.x, n.y); x.rotate(n.a + Math.PI); x.fillStyle = '#0b1230'; x.strokeStyle = col; x.lineWidth = 2; x.shadowColor = col; x.shadowBlur = 14
        x.beginPath(); x.moveTo(r, 0); x.lineTo(-r * .8, r * .8); x.lineTo(-r * .4, 0); x.lineTo(-r * .8, -r * .8); x.closePath(); x.fill(); x.stroke(); x.restore()
        x.shadowBlur = 0; x.fillStyle = '#c9d2ef'; x.font = '10px Inter,sans-serif'; x.textAlign = 'center'
        x.fillText(n.s.id, n.x, n.y + r + 13); x.fillStyle = col; x.fillText(Math.round(l) + '%', n.x, n.y + r + 24) }
      x.fillStyle = '#0b1230'; x.strokeStyle = '#5ce1ff'; x.lineWidth = 2; x.beginPath(); x.arc(cx, cy, 20, 0, 6.283); x.fill(); x.stroke()
      x.fillStyle = '#5ce1ff'; x.font = '700 11px Inter'; x.textAlign = 'center'; x.fillText('AI', cx, cy + 4)
      raf = requestAnimationFrame(draw) }
    draw()
    return () => { cancelAnimationFrame(raf); removeEventListener('resize', fit) }
  }, [servers])
  const click = e => { const r = cv.current.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top
    const n = nodes.current.find(n => Math.hypot(n.x - mx, n.y - my) < 22); n && onPick(n.s) }
  return <canvas ref={cv} className="tower" onClick={click} />
}
