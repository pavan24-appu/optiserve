"""Scenario library (9 cases) + time-series data augmentation. Synthetic, modelled on real-world patterns."""
import numpy as np, pandas as pd
 
DAYS = 28
 
 
def _ix():
    end = pd.Timestamp.utcnow().tz_localize(None).floor("h")
    return pd.date_range(end - pd.Timedelta(days=DAYS) + pd.Timedelta(hours=1), end, freq="h")
 
 
def P(*pts):  # 24-hour profile from (hour, value) anchors
    h, v = zip(*pts); return np.interp(np.arange(24), h, v)
 
 
def fleet(ix, rng, svc, it, n, pct, ram0=30, ramk=.35, err=.2, jit=.04, names=None):
    out = []
    for i in range(n):
        cpu = np.clip(pct * rng.normal(1, jit) + rng.normal(0, 2.5, len(ix)), 0, 100)
        out.append(pd.DataFrame(dict(
            service=svc, sid=(names[i] if names else f"{svc}-{i + 1:02d}"), itype=it, ts=ix, cpu=cpu,
            ram=np.clip(ram0 + ramk * cpu + rng.normal(0, 1.5, len(ix)), 0, 100),
            err=np.clip(err + .02 * cpu + rng.normal(0, .05, len(ix)), 0, None))))
    return out
 
 
def _boost(pct, ix, events):  # apply past events to the history
    p = pct.copy()
    for _, s, d, m in events:
        a = len(ix) + s
        if a >= 0: p[a:a + d] = p[a:a + d] * m
    return p
 
 
def s_real(ix, rng):
    fr = []
    for svc, it, n, lvl in (("batch-a", "m5.xlarge", 5, 35), ("svc-b", "m5.large", 4, 28), ("svc-c", "m5.2xlarge", 3, 22)):
        e = np.zeros(len(ix))
        for i in range(1, len(ix)): e[i] = .9 * e[i - 1] + rng.normal(0, 4)
        burst = (rng.random(len(ix)) < .01) * rng.uniform(20, 40, len(ix))
        fr += fleet(ix, rng, svc, it, n, np.clip(lvl + 14 * np.sin(2 * np.pi * (ix.hour - 14) / 24) + e + burst, 2, 98), jit=.1)
    return fr, []
 
 
def s_office(ix, rng):
    o = P((0, 3), (6, 3), (8, 45), (9, 85), (12, 90), (13, 70), (14, 88), (17, 80), (18, 25), (20, 5), (23, 3))
    return fleet(ix, rng, "office-erp", "m5.xlarge", 10, o[ix.hour] * .55 * np.where(ix.dayofweek >= 5, .06, 1)), []
 
 
def s_flash(ix, rng):
    b = P((0, 20), (5, 12), (9, 40), (13, 48), (20, 55), (23, 30))
    return fleet(ix, rng, "shop-web", "m5.xlarge", 10, b[ix.hour]), [("Festive flash sale", 100, 8, 6)]
 
 
def s_rush(ix, rng):
    p = np.where(ix.hour == 10, 92, np.where(ix.hour == 11, 45, 15)).astype(float)
    return fleet(ix, rng, "ticketing", "m5.large", 8, p), []
 
 
def s_stream(ix, rng):
    ev = [("Match", -456, 4, 5), ("Match", -288, 4, 5), ("Match", -120, 4, 5), ("Match", 52, 4, 5), ("Match", 196, 4, 5)]
    base = P((0, 10), (8, 18), (18, 25), (23, 14))[ix.hour]
    return fleet(ix, rng, "streaming", "m5.xlarge", 8, _boost(base, ix, ev)), ev
 
 
def s_growth(ix, rng):
    d = np.arange(len(ix)) / 24
    p = (15 + 55 * d / DAYS) * P((0, .4), (8, .6), (13, 1), (20, .9), (23, .5))[ix.hour] * np.where(ix.dayofweek >= 5, .7, 1)
    return fleet(ix, rng, "startup-api", "m5.large", 5, p), []
 
 
def s_forgot(ix, rng):
    d = P((0, 25), (9, 45), (14, 50), (22, 30))[ix.hour]
    fr = fleet(ix, rng, "web", "m5.large", 4, d, ram0=35)
    for k in "abc": fr += fleet(ix, rng, f"staging-{k}", "m5.xlarge", 1, np.full(len(ix), 2.0), ram0=8, ramk=.1)
    late = np.where(np.arange(len(ix)) > len(ix) - 11 * 24, 28.0, 2.0)
    fr += fleet(ix, rng, "staging-d", "m5.xlarge", 1, late, ram0=8, ramk=.1)
    fr += fleet(ix, rng, "batch-old", "m5.2xlarge", 1, P((0, 8), (12, 16), (23, 8))[ix.hour])
    return fr, []
 
 
def s_sick(ix, rng):
    fr = fleet(ix, rng, "payments", "m5.large", 4, P((0, 8), (12, 22), (23, 9))[ix.hour])
    n = len(ix); fr[3].ram = np.linspace(30, 93, n) + rng.normal(0, 1, n); fr[3].err = np.linspace(.2, 6, n)
    return fr, []
 
 
def s_night(ix, rng):
    return fleet(ix, rng, "reports", "m5.xlarge", 4, np.where((ix.hour >= 1) & (ix.hour <= 4), 85, 10).astype(float)), []
 
 
SCENARIOS = {
    1: ("Real cluster (trace-style)", "Mixed, noisy daily cycles", "Forecast beats same-hour-last-week baseline", s_real),
    2: ("Office-hours app", "Busy 9-6 weekdays, idle nights/weekends", "Schedule cuts night+weekend capacity, zero shortfall", s_office),
    3: ("Flash sale", "Flat, then a planned 6x surge", "Scale-up before the surge; alert if event not planned", s_flash),
    4: ("Morning rush", "Sharp spike at 10:00 daily", "Pre-scales before the spike, scales back after", s_rush),
    5: ("Live-event streaming", "Match-day surges from a calendar", "Holds capacity through matches", s_stream),
    6: ("Growing startup", "Trend + weekly cycle", "Plan rises weekly; warns capacity runs out", s_growth),
    7: ("Forgotten servers", "Staging boxes left running", "Zombies buried, one resurrected kept", s_forgot),
    8: ("Sick server", "Memory leak + rising errors", "Scale-down blocked, health alert", s_sick),
    9: ("Night batch jobs", "Quiet days, heavy 1-4 AM", "Night capacity NOT cut, daytime shrinks", s_night),
}
 
 
def build(case: int, seed: int = 7):
    """Returns (df, events[(name,start_h,dur_h,mult)]) with columns service,sid,itype,ts,cpu,ram,err."""
    ix, rng = _ix(), np.random.default_rng(seed + case)
    fr, ev = SCENARIOS[case][3](ix, rng)
    return pd.concat(fr, ignore_index=True), ev
 
 
def augment(df, seed=1, jitter=.03, scale=(.9, 1.1), spikes=3, gap=.02):
    """Time-series augmentation: jitter, per-server magnitude scaling, one-off spike injection, missing-hour gaps."""
    rng = np.random.default_rng(seed); d = df.copy(); k = len(d)
    d["cpu"] = d.cpu * rng.normal(1, jitter, k)
    for sid, i in d.groupby("sid").groups.items():
        f = rng.uniform(*scale); d.loc[i, ["cpu", "ram"]] *= f
    d.loc[rng.choice(d.index, spikes, replace=False), "cpu"] = 96
    d[["cpu", "ram"]] = d[["cpu", "ram"]].clip(0, 100)
    return d.drop(rng.choice(d.index, int(gap * k), replace=False)).reset_index(drop=True)
 
