"""OptiServe service layer: state + guardrailed recommendations (no web/DB deps, fully testable)."""
import numpy as np, pandas as pd
import engine as E
 
S = dict(df=None, raw_evs=[], evs=[], fr={}, info={}, dem={}, fc={}, prof=None, bt={})
R = lambda a: np.round(np.asarray(a, float), 1).tolist()
ISO = lambda ix: [t.isoformat() + "Z" for t in ix]
 
 
def load_df(df, raw_evs=None):
    """Replace fleet data (df: service,sid,itype,ts,cpu,ram,err) and rebuild cleaned frames + demand."""
    if raw_evs is not None: S["raw_evs"] = raw_evs
    S.update(df=df, fc={}, prof=None, bt={})
    if df is None or df.empty: S.update(fr={}, info={}, dem={}, evs=[]); return
    end = df.ts.max()
    S["evs"] = [(n, end + pd.Timedelta(hours=s), end + pd.Timedelta(hours=s + d), m) for n, s, d, m in S["raw_evs"]]
    S["info"] = df.groupby("sid")[["service", "itype"]].first().apply(tuple, axis=1).to_dict()
    S["fr"] = E.clean(df, S["evs"]); S["dem"] = E.demand(S["fr"], S["info"])
 
 
def profiles():
    if S["prof"] is None:
        S["prof"] = {s: {**E.profile(h, S["info"][s][1]), "service": S["info"][s][0], "itype": S["info"][s][1], "id": s}
                     for s, h in S["fr"].items()}
    return S["prof"]
 
 
def SV():
    o = {}
    for s, (v, it) in S["info"].items(): o.setdefault(v, dict(itype=it, sids=[]))["sids"].append(s)
    for v in o.values(): v["n"] = len(v["sids"])
    return o
 
 
def fc(svc):
    if svc not in S["fc"]:
        d = S["dem"][svc]; r = E.forecast(d.cpu, 720); r["mem"] = E.mem_fc(d.mem, r["ix"]); S["fc"][svc] = r
    return S["fc"][svc]
 
 
def compute(svc, risk=.5, growth=0., use_ev=True, remove=0):
    """7-day plan for one service: forecast bands -> servers/hour -> guardrails -> cost/shortfall -> reasons."""
    sv = SV()[svc]; it = sv["itype"]; n = max(1, sv["n"] - remove); d = S["dem"][svc]; r = fc(svc); H = 168
    ix = r["ix"][:H]; m = E.ev_mult(ix, S["evs"]) if use_ev else np.ones(H); g = 1 + growth / 100
    e, hi, lo = (r[k][:H] * g * m for k in ("f", "hi", "lo")); mem = r["mem"][:H] * g
    sick = [s for s in sv["sids"] if profiles()[s]["status"] == "risky"]
    hold = r["conf"] < .5 or len(d) < 72
    p = E.plan(e, hi, mem, it, n, risk, hold, bool(sick)); pl = p["plan"]
    v, gb, c = E.CATALOG[it]; now, new = E.score(e, mem, n, it), E.score(e, mem, pl, it)
    u = np.maximum(e / (n * v), mem / (n * gb)); first = ix[int(np.argmax(u > 1))] if (u > 1).any() else None
    save = round(now["monthly"] - new["monthly"], 2); pk = int(np.argmax(p["need"]))
    notes, alerts = [], []
    if sick: notes.append(f"Guardrail: scale-down blocked, unhealthy server {', '.join(sick)}"); alerts.append(("high", f"{svc}: {sick[0]} is unhealthy; scale-down blocked"))
    if hold: notes.append(f"Guardrail: forecast confidence {r['conf']:.0%} too low; holding {n} servers")
    if p["mem_bound"] > .2: notes.append(f"Sized by memory in {p['mem_bound']:.0%} of hours (CPU is not the limit)")
    if first is not None: alerts.append(("high", f"{svc}: current {n} servers run short from {first:%a %H:00} ({now['shortfall_hours']} h in 7 days)"))
    fut = [x for x in S["evs"] if x[2] > S["df"].ts.max()]
    for nm, a, b, k in fut:
        alerts.append(("info" if use_ev else "high", f"{svc}: '{nm}' ({k:g}x) on {a:%a %H:00}; " + (f"pre-scaled to {int(pl.max())} servers" if use_ev else "NOT in plan, shortfall risk")))
    over = np.where(r["f"] * g > n * v * .9)[0]
    if over.size: alerts.append(("high" if over[0] < 168 else "warn", f"{svc}: forecast demand exceeds 90% of current capacity in ~{over[0] // 24 + 1} days; capacity runs out"))
    word = "Shrink" if save > 0 else "Grow" if save < 0 else "Keep"
    rec = (f"{word} {svc} from {n} to {int(pl.min())}-{int(pl.max())} servers (avg {pl.mean():.1f}). "
           f"{'Saves' if save >= 0 else 'Adds'} ${abs(save):,.0f}/mo. Busiest hour {ix[pk]:%a %H:00} needs {int(p['need'][pk])}; "
           f"quietest needs {int(p['need'].min())}. Risk {risk:.2f}, forecast confidence {r['conf']:.0%} ({r['model']}).")
    h = d.raw.iloc[-168:]
    heat = pd.DataFrame({"d": ix.dayofweek, "h": ix.hour, "v": pl}).groupby(["d", "h"]).v.mean().unstack().round(1).values.tolist()
    return dict(svc=svc, itype=it, n=n, vcpu=v, model=r["model"], conf=round(r["conf"], 2), gain=round(r["gain"], 2),
                hts=ISO(h.index), hist=R(h.values), fts=ISO(ix), exp=R(e), lo=R(lo), hi=R(hi), need=p["need"].astype(int).tolist(),
                plan=pl.astype(int).tolist(), heat=heat, now=now, new=new, saving=save, rec=rec, notes=notes, alerts=alerts)
 
 
def overview(risk=.5):
    P = profiles(); sv = SV(); cost = sum(p["cost"] for p in P.values()); plans = {}
    for s, v in sv.items():
        if v["n"] >= 2: plans[s] = compute(s, risk)
    pot = sum(max(0, x["saving"]) for x in plans.values())
    pot += sum(p["waste"] for p in P.values() if sv[p["service"]]["n"] == 1)
    cnt = {}
    for p in P.values(): cnt[p["status"]] = cnt.get(p["status"], 0) + 1
    recs = sorted(({"svc": s, "text": x["rec"], "saving": x["saving"]} for s, x in plans.items()), key=lambda r: -r["saving"])
    recs += [{"svc": p["id"], "text": f"{p['action'].title()} {p['id']}: {p['reason']}", "saving": p["waste"]}
             for p in P.values() if p["status"] in ("zombie", "wasteful") and sv[p["service"]]["n"] == 1]
    al = [a for x in plans.values() for a in x["alerts"]]
    al += [("high", f"{p['id']}: {p['reason']}") for p in P.values() if p["status"] == "risky" and not any(p["id"] in a[1] for a in al)]
    al += [("warn", f"{p['id']}: {p['anomalies']} one-off spikes excluded from forecast") for p in P.values() if p["anomalies"] > 0][:3]
    util = float(np.mean([h.cpu.iloc[-168:].mean() for h in S["fr"].values()]))
    return dict(kpi=dict(servers=len(P), cost=cost, util=round(util, 1), potential=round(pot), waste_score=round(100 * pot / cost) if cost else 0,
                         cost_after=round(cost - pot)), status=cnt, recs=sorted(recs, key=lambda r: -r["saving"])[:5],
                alerts=sorted(al, key=lambda a: a[0] != "high")[:8], services=[dict(svc=s, n=v["n"], itype=v["itype"]) for s, v in sv.items()])
 
 
def backtest(svc, risk=.5):
    k = (svc, round(risk, 2))
    if k not in S["bt"]:
        sv = SV()[svc]; r = E.backtest(S["dem"][svc], sv["itype"], sv["n"], fc(svc)["model"], risk); v = E.CATALOG[sv["itype"]][0]
        a, b = r["actual_score"], r["plan_score"]
        S["bt"][k] = dict(ts=ISO(r["ix"]), demand=R(r["actual"] / v), now=[sv["n"]] * len(r["ix"]), plan=r["plan"].astype(int).tolist(),
                          actual_setup=a, optiserve=b, cheaper_pct=round(100 * (1 - b["monthly"] / a["monthly"]), 1))
    return S["bt"][k]
 
