"""Integration: scenario data -> service layer -> recommendations/alerts (what the API returns)."""
import sys; sys.path.insert(0, "backend")
import service as V
from scenarios import build, augment
 
def go(c, aug=False):
    df, ev = build(c); V.load_df(augment(df) if aug else df, ev); return V.overview(.5)
 
def test_case7_overview():
    o = go(7); assert o["status"].get("zombie", 0) >= 2 and o["status"].get("resurrected") == 1 and o["kpi"]["potential"] > 400
 
def test_case8_blocks_scaledown_and_alerts():
    o = go(8); p = V.compute("payments"); assert any("unhealthy" in a[1] for a in o["alerts"]) and min(p["plan"]) >= p["n"]
 
def test_case3_event_alerts():
    go(3); on, off = V.compute("shop-web", use_ev=True), V.compute("shop-web", use_ev=False)
    assert max(on["plan"]) > 25 and any("pre-scaled" in a[1] for a in on["alerts"]) and any("NOT in plan" in a[1] for a in off["alerts"])
 
def test_case2_risk_slider_monotonic():
    go(2); c = [V.compute("office-erp", r)["new"]["monthly"] for r in (0, .5, 1)]; assert c[0] <= c[1] <= c[2]
 
def test_case2_whatif_growth_and_removal():
    go(2); base = V.compute("office-erp"); g = V.compute("office-erp", growth=60); rm = V.compute("office-erp", remove=6)
    assert g["new"]["monthly"] > base["new"]["monthly"] and rm["now"]["shortfall_hours"] >= base["now"]["shortfall_hours"]
 
def test_case9_backtest_and_augmented_robustness():
    go(9, aug=True); b = V.backtest("reports"); assert b["optiserve"]["shortfall_hours"] <= b["actual_setup"]["shortfall_hours"] + 2
 
def test_case6_capacity_runs_out_warning():
    go(6); p = V.compute("startup-api"); assert any("runs out" in a[1] for a in p["alerts"])
 
if __name__ == "__main__":
    import time
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            t = time.time()
            try: f(); print(f"PASS {n} ({time.time() - t:.1f}s)")
            except Exception as e: print(f"FAIL {n}: {type(e).__name__} {e}")
 
