"""Run: python tests/test_engine.py   (or pytest). Integration tests: scenarios -> engine -> expected results."""
import sys, time; sys.path.insert(0, "backend")
import numpy as np, pandas as pd
import engine as E
from scenarios import SCENARIOS, build, augment
 
def load(case, aug=False):
    df, ev = build(case)
    if aug: df = augment(df)
    end = df.ts.max()
    evs = [(n, end + pd.Timedelta(hours=s), end + pd.Timedelta(hours=s + d), m) for n, s, d, m in ev]
    info = df.groupby("sid")[["service", "itype"]].first().apply(tuple, axis=1).to_dict()
    fr = E.clean(df, evs); return df, fr, E.demand(fr, {k: v for k, v in info.items()}), info, evs
 
def prof(case): _, fr, _, info, _ = load(case); return {s: E.profile(h, info[s][1]) for s, h in fr.items()}
 
def test_data_integrity():
    for c in SCENARIOS:
        df, _ = build(c); assert df.cpu.between(0, 100).all() and df.ram.between(0, 100).all() and len(df) > 1000
        a = augment(df); assert len(a) < len(df) and a.cpu.max() <= 100          # gaps injected
        fr = E.clean(a); assert all(h.gap.iloc[0] > 0 for h in fr.values())       # gaps detected + filled
        assert all(h.cpu.notna().all() for h in fr.values())
 
def test_case7_zombies_and_resurrection():
    p = prof(7)
    assert [p[k]["status"] for k in ("staging-a-01", "staging-b-01", "staging-c-01")] == ["zombie"] * 3
    assert p["staging-d-01"]["status"] == "resurrected" and p["batch-old-01"]["status"] == "wasteful"
 
def test_case8_sick_server_blocked():
    p = prof(8); assert p["payments-04"]["status"] == "risky" and p["payments-01"]["status"] != "risky"
 
def test_case2_office_schedule_saves_without_shortfall():
    _, fr, dem, info, _ = load(2); d = dem["office-erp"]; it = "m5.xlarge"
    r = E.backtest(d, it, 10, None, risk=.6)
    assert r["plan_score"]["monthly"] < r["actual_score"]["monthly"] * .7 and r["plan_score"]["shortfall_hours"] <= 2
 
def test_case9_night_not_cut():
    _, fr, dem, *_ = load(9); d = dem["reports"]; f = E.forecast(d.cpu, 48)
    p = E.plan(f["f"], f["hi"], E.mem_fc(d.mem, f["ix"]), "m5.xlarge", 4, .5)["plan"]
    night = p[[i for i, t in enumerate(f["ix"]) if 1 <= t.hour <= 4]].mean(); day = p[[i for i, t in enumerate(f["ix"]) if 10 <= t.hour <= 15]].mean()
    assert night > day
 
def test_case3_prescale_before_event():
    _, fr, dem, info, evs = load(3); d = dem["shop-web"]; f = E.forecast(d.cpu, 168)
    m = E.ev_mult(f["ix"], evs); cpu = f["f"] * m
    p = E.plan(cpu, f["hi"] * m, E.mem_fc(d.mem, f["ix"]), "m5.xlarge", 10, .5)["plan"]
    s = int(np.argmax(m > 1)); assert p[s - 2:s + 8].max() > 25 and p[s - 1] >= p[s - 3]  # capacity already up before surge
 
def test_case6_growth_trend_and_warning():
    _, fr, dem, *_ = load(6); d = dem["startup-api"]; st = E.ts_stats(d.cpu)
    assert st["trend_per_day"] > 0 and st["trend_p"] < .01
    f = E.forecast(d.cpu, 24 * 14); assert f["f"][-24:].mean() > d.cpu.iloc[-24:].mean()
 
def test_forecast_beats_baseline_and_bands():
    for c in (2, 4, 9):
        _, fr, dem, *_ = load(c); y = list(dem.values())[0].cpu; f = E.forecast(y, 168)
        assert f["scores"][f["model"]] <= f["scores"]["naive"] and (f["lo"] <= f["f"]).all() and (f["f"] <= f["hi"]).all()
 
def test_edge_cases():
    df, _ = build(2); short = df[df.ts > df.ts.max() - pd.Timedelta(hours=40)]
    assert len(E.clean(short)["office-erp-01"]) <= 41            # tiny history does not crash cleaning
    spike = df.copy(); spike.loc[spike.index[500], "cpu"] = 99; assert E.clean(spike)[spike.sid[500]].anom.sum() >= 0
    p = E.plan(np.full(24, 1.), np.full(24, 2.), np.full(24, 1.), "m5.large", 10, .5); assert p["plan"][0] == 7 and p["plan"].min() >= 2  # gradual step down
 
def test_pipeline_speed():
    t = time.time(); _, fr, dem, *_ = load(1); [E.forecast(d.cpu, 720) for d in dem.values()]; assert time.time() - t < 90
 
if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            t = time.time()
            try: f(); print(f"PASS {n} ({time.time() - t:.1f}s)")
            except Exception as e: print(f"FAIL {n}: {type(e).__name__} {e}")
 
