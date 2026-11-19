"""OptiServe engine: clean > profile > forecast > plan > guardrails > backtest. Pure pandas/numpy (no DB), unit-testable."""
from functools import reduce
import numpy as np, pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestRegressor
try:
    from statsmodels.tsa.stattools import adfuller
except ImportError:
    adfuller = None
 
CATALOG = {"t3.small": (2, 2, 15), "t3.medium": (2, 4, 30), "m5.large": (2, 8, 70), "m5.xlarge": (4, 16, 140),
           "m5.2xlarge": (8, 32, 280), "m5.4xlarge": (16, 64, 560)}   # vCPU, GB, $/month
HM = 730
 
 
def cheapest(v, g, pk_cpu, pk_ram):
    ok = [k for k, (a, b, _) in CATALOG.items() if a >= v * pk_cpu / 70 and b >= g * pk_ram / 80]
    return min(ok or ["m5.4xlarge"], key=lambda k: CATALOG[k][2])
 
 
# ---------- ingest + clean ----------
def ev_mult(ix, evs):
    m = np.ones(len(ix))
    for _, a, b, k in evs: m[(ix >= a) & (ix < b)] *= k
    return m
 
 
def clean(df, evs=()):
    """Hourly resample, fill gaps (flag completeness), flag one-off spikes (not recurring peaks, not known events)."""
    out = {}
    for sid, g in df.groupby("sid"):
        h = g.set_index("ts")[["cpu", "ram", "err"]].sort_index().resample("h").mean()
        gap = float(h.cpu.isna().mean())
        h = h.interpolate(limit=6).ffill().bfill()
        how = h.index.dayofweek * 24 + h.index.hour
        prof = h.cpu.groupby(how).transform("median")
        r = h.cpu - prof
        mad = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-6
        ev = ev_mult(h.index, evs) > 1
        h["anom"] = (r > np.maximum(15, 6 * mad)) & ~ev
        h["cpu_c"] = h.cpu.where(~(h.anom | ev), prof)
        h["gap"] = gap
        out[sid] = h
    return out
 
 
def demand(fr, info):
    """Per service: demand in vCPU / GB units (cleaned 'cpu', raw 'raw', 'mem')."""
    rows = {}
    for sid, h in fr.items():
        svc, it = info[sid]; v, g, _ = CATALOG[it]
        rows.setdefault(svc, []).append(pd.DataFrame({"cpu": h.cpu_c * v / 100, "raw": h.cpu * v / 100, "mem": h.ram * g / 100}))
    return {s: reduce(lambda a, b: a.add(b, fill_value=0), l) for s, l in rows.items()}
 
 
# ---------- profiler ----------
def profile(h, it):
    v, g, c = CATALOG[it]
    d = h.cpu.resample("D").max(); idle = (d < 15).values
    run = 0
    for x in idle[::-1]:
        if not x: break
        run += 1
    died = str(d.index[-run].date()) if run else None
    pk_c, pk_r = float(h.cpu.quantile(.95)), float(h.ram.quantile(.95)); peak = max(pk_c, pk_r); avg = float(h.cpu.mean())
    dr = h.ram.resample("D").mean(); sl = stats.linregress(np.arange(len(dr)), dr.values) if len(dr) > 3 else None
    e = h.err.values; er3, er0 = e[-72:].mean(), e[:-72].mean() + 1e-6
    leak = bool(sl and sl.slope > .5 and sl.rvalue > .9)
    sick = leak or (er3 > 3 * er0 and er3 > 1) or h.ram.iloc[-24:].max() > 92
    back = idle[:-3].sum() >= 7 and d.values[-3:].min() >= 15
    st = ("risky" if sick else "resurrected" if back else "hot" if peak > 85 else
          "zombie" if run >= 14 and avg < 5 else "wasteful" if peak < 40 else "rightsized")
    to = cheapest(v, g, pk_c, pk_r) if st in ("wasteful", "zombie") else it
    why = {"risky": f"Memory climbing {sl.slope:.1f} pts/day, errors {er3:.1f}/h; scale-down blocked" if sl else "Health warning",
           "resurrected": "Was idle, demand is back; keep", "hot": f"Peak {peak:.0f}% of capacity; add headroom",
           "zombie": f"{avg:.1f}% avg, idle {run} days; decommission after owner confirms",
           "wasteful": f"Peak only {peak:.0f}% of capacity; shrink to {to}", "rightsized": "Healthy utilisation"}[st]
    waste = c if st == "zombie" else max(0, c - CATALOG[to][2]) if st == "wasteful" else 0
    return dict(status=st, cost=c, avg=round(avg, 1), peak=round(peak, 1), idle_days=run, died_on=died, to=to,
                waste=waste, action={"zombie": "bury", "wasteful": "shrink", "risky": "hold", "hot": "scale_up"}.get(st, "keep"),
                reason=why, conf=round(max(0, 1 - 5 * float(h.gap.iloc[0])) * min(1, len(h) / 336), 2),
                anomalies=int(h.anom.sum()))
 
 
def ts_stats(y):
    v = y.values; n = len(v); ac = lambda l: round(float(np.corrcoef(v[:-l], v[l:])[0, 1]), 3) if n > l + 2 else None
    d = y.resample("D").mean().dropna(); lr = stats.linregress(np.arange(len(d)), d.values)
    prof = y.groupby(y.index.dayofweek * 24 + y.index.hour).transform("mean")
    return dict(mean=round(float(v.mean()), 2), std=round(float(v.std()), 2), cv=round(float(v.std() / (v.mean() + 1e-9)), 2),
                p95=round(float(np.quantile(v, .95)), 2), acf24=ac(24), acf168=ac(168),
                trend_per_day=round(float(lr.slope), 3), trend_p=round(float(lr.pvalue), 4),
                seasonal_strength=round(float(np.clip(1 - (y - prof).var() / y.var(), 0, 1)), 3),
                adf_p=round(float(adfuller(v)[1]), 4) if adfuller and n > 50 else None)
 
 
# ---------- forecasting ----------
def _season(n): return 168 if n >= 336 else 24
 
 
def m_naive(y, h):
    s = _season(len(y)); return y.values[-s:][np.arange(h) % s]
 
 
def _hw(v, s, a, b, g, phi):
    l, t, S = v[:s].mean(), (v[s:2 * s].mean() - v[:s].mean()) / s, list(v[:s] - v[:s].mean())
    sse = 0.0
    for k in range(s, len(v)):
        i = k % s; e = v[k] - (l + phi * t + S[i]); sse += e * e
        l = l + phi * t + a * e; t = phi * t + a * b * e; S[i] += g * (1 - a) * e
    return sse, l, t, S
 
 
def m_hw(y, h):
    """Additive damped-trend Holt-Winters with a small grid search (pure numpy)."""
    v = y.values.astype(float); n, s, phi = len(v), _season(len(v)), .97
    best = min((_hw(v, s, a, b, g, phi) + (a, b, g) for a in (.05, .2, .4) for b in (0, .05) for g in (.05, .2)), key=lambda r: r[0])
    _, l, t, S = best[:4]
    return np.array([l + sum(phi ** j for j in range(1, k + 1)) * t + S[(n + k - 1) % s] for k in range(1, h + 1)])
 
 
def _feat(ix):
    h, d = ix.hour.values, ix.dayofweek.values
    return np.c_[h, d, d >= 5, np.sin(h / 24 * 6.283), np.cos(h / 24 * 6.283)]
 
 
def m_rf(y, h):
    """Random Forest on calendar features + damped linear trend (extrapolates growth)."""
    d = y.resample("D").mean().dropna()
    sl = float(np.clip(np.polyfit(np.arange(len(d)), d.values, 1)[0], -.04 * d.mean(), .04 * d.mean())) if len(d) > 2 else 0.
    t = lambda ix: np.asarray((ix - y.index[0]).total_seconds()) / 86400
    rf = RandomForestRegressor(100, min_samples_leaf=3, n_jobs=-1, random_state=1).fit(_feat(y.index), y.values - sl * t(y.index))
    fi = pd.date_range(y.index[-1] + pd.Timedelta(hours=1), periods=h, freq="h")
    return rf.predict(_feat(fi)) + sl * t(fi)
 
 
MODELS = {"naive": m_naive, "holt_winters": m_hw, "rf_trend": m_rf}
 
 
def forecast(y, h, model=None):
    """Pick the best model on a 48h holdout (must beat the seasonal-naive baseline) -> expected + 80% band."""
    ho = min(48, len(y) // 4); tr, te = y.iloc[:-ho], y.iloc[-ho:].values
    sc, pr = {}, {}
    for k, f in MODELS.items():
        try: pr[k] = f(tr, ho); sc[k] = float(np.mean(np.abs(pr[k] - te)))
        except Exception: pass
    model = model if model in pr else min(sc, key=sc.get)
    res = te - pr[model]; sig = float(res.std(ddof=1)) + 1e-6
    wape = float(np.abs(res).sum() / max(te.sum(), 1e-6))
    f = np.clip(MODELS[model](y, h), 0, None)
    k = 1.28 * sig * np.sqrt(1 + np.arange(h) / 168 * .5)
    return dict(ix=pd.date_range(y.index[-1] + pd.Timedelta(hours=1), periods=h, freq="h"), f=f, lo=np.clip(f - k, 0, None),
                hi=f + k, model=model, wape=wape, conf=float(np.clip(1 - wape, 0, 1)),
                gain=float(1 - sc[model] / sc["naive"]) if sc.get("naive") else 0., scores=sc)
 
 
def mem_fc(m, ix):
    d = m.resample("D").mean().dropna(); sl = stats.linregress(np.arange(len(d)), d.values).slope if len(d) > 2 else 0.
    base = m.groupby(m.index.dayofweek * 24 + m.index.hour).median().reindex(ix.dayofweek * 24 + ix.hour).values
    return np.clip(base + sl * (len(m) / 48 + np.arange(len(ix)) / 24), 0, None)
 
 
# ---------- capacity planner + guardrails ----------
def plan(cpu_e, cpu_h, mem, it, n_now, risk=.5, hold=False, block=False, min_n=2, lead=2):
    """Servers needed per hour. risk 0=cheapest(expected, 85% util) .. 1=safest(upper band, 50% util)."""
    v, g, _ = CATALOG[it]; tgt = .85 - .35 * risk
    nc = np.ceil((cpu_e + risk * (cpu_h - cpu_e)) / (v * tgt)); nm = np.ceil(mem / (g * min(.9, tgt + .1)))
    need = np.maximum(np.maximum(nc, nm), min_n)
    need = pd.Series(need[::-1]).rolling(lead + 1, min_periods=1).max().values[::-1]       # pre-scale `lead` hours early
    pl, prev = np.empty(len(need)), n_now
    for i, x in enumerate(need):                                                          # up instantly, down in 25% steps
        prev = x if x >= prev else max(x, prev - max(1, int(np.ceil(.25 * prev)))); pl[i] = prev
    if hold: pl[:] = n_now
    elif block: pl = np.maximum(pl, n_now)
    return dict(need=need, plan=pl, mem_bound=float((nm > nc).mean()))
 
 
def score(d_cpu, d_mem, cap, it):
    v, g, c = CATALOG[it]; cap = np.broadcast_to(cap, np.shape(d_cpu)).astype(float)
    u = np.maximum(d_cpu / (cap * v), d_mem / (cap * g))
    return dict(monthly=round(float(cap.mean() * c), 2), shortfall_hours=int((u > 1).sum()),
                overprov_hours=int((u < .4).sum()), avg_util=round(float(u.mean() * 100), 1))
 
 
def backtest(dem, it, n_now, model, risk=.5, days=7):
    """Time machine: forecast from data before the last `days`, plan, then replay against what really happened."""
    H = days * 24; fc = forecast(dem.cpu.iloc[:-H], H, model)
    pl = plan(fc["f"], fc["hi"], mem_fc(dem.mem.iloc[:-H], fc["ix"]), it, n_now, risk)["plan"]
    a, m = dem.raw.values[-H:], dem.mem.values[-H:]
    return dict(ix=dem.index[-H:], actual=a, plan=pl, now=n_now, actual_score=score(a, m, n_now, it), plan_score=score(a, m, pl, it))
 
 
def accuracy(dem, model, cuts=6, h=24):
    out = []
    for k in range(cuts, 0, -1):
        c = len(dem) - 24 * k; tr, te = dem.cpu.iloc[:c], dem.raw.values[c:c + h]; s = te.sum() + 1e-9
        try: pm = MODELS[model](tr, h)
        except Exception: pm = m_naive(tr, h)
        out.append(dict(day=str(dem.index[c].date()), model=round(float(np.abs(pm - te).sum() / s), 3),
                        baseline=round(float(np.abs(m_naive(tr, h) - te).sum() / s), 3)))
    return out
 
