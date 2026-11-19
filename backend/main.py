"""OptiServe API v2 - routes + persistence. Logic lives in engine.py / service.py."""
import asyncio, io, os
from datetime import datetime, timedelta
import httpx, numpy as np, pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Float, Index, Integer, String, create_engine, delete, text
from sqlalchemy.orm import declarative_base, sessionmaker
import engine as E, scenarios as SC, service as V
 
DB = os.getenv("DATABASE_URL", "sqlite:///optiserve.db").replace("postgres://", "postgresql://", 1)
eng = create_engine(DB, pool_pre_ping=True, connect_args={"check_same_thread": False} if DB.startswith("sqlite") else {})
Session = sessionmaker(eng, expire_on_commit=False)
Base = declarative_base()
 
 
class Server(Base):
    __tablename__ = "servers"
    id = Column(String, primary_key=True); itype = Column(String); service = Column(String); state = Column(String, default="active")
 
 
class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True); sid = Column(String); ts = Column(DateTime)
    cpu = Column(Float); ram = Column(Float); err = Column(Float)
    __table_args__ = (Index("ix_metric_sid_ts", "sid", "ts"),)
 
 
class Action(Base):
    __tablename__ = "actions"
    id = Column(Integer, primary_key=True); sid = Column(String); verb = Column(String); detail = Column(String)
    saving = Column(Float); at = Column(DateTime, default=datetime.utcnow)
 
 
Base.metadata.create_all(eng)
app = FastAPI(title="OptiServe", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])
ALIAS = {"server": "sid", "instance": "sid", "host": "sid", "timestamp": "ts", "time": "ts", "cpu_utilization": "cpu",
         "memory": "ram", "instance_type": "itype", "errors": "err"}
META = dict(case=None, title="No data")
 
 
def refresh():
    df = pd.read_sql(text("SELECT m.sid,m.ts,m.cpu,m.ram,m.err,s.itype,s.service FROM metrics m JOIN servers s ON s.id=m.sid "
                          "WHERE s.state='active'"), eng, parse_dates=["ts"])
    V.load_df(df)
 
 
def store(df, reset=False):
    df = df.rename(columns=ALIAS).copy()
    if not {"sid", "ts", "cpu"} <= set(df.columns): raise HTTPException(422, "Need columns: server, ts, cpu (optional ram, err, itype, service)")
    df["ts"] = pd.to_datetime(df.ts, errors="coerce", utc=True).dt.tz_localize(None)
    for c, dv in (("ram", np.nan), ("err", 0.0), ("itype", "m5.large"), ("service", None)):
        if c not in df: df[c] = dv
    df["service"] = df.service.fillna(df.sid)
    df["itype"] = df.itype.where(df.itype.isin(E.CATALOG), "m5.large")
    df[["cpu", "ram"]] = df[["cpu", "ram"]].apply(pd.to_numeric, errors="coerce").clip(0, 100)
    df = df.dropna(subset=["sid", "ts", "cpu"]).drop_duplicates(["sid", "ts"])
    df["ram"] = df.ram.fillna(df.cpu)
    if df.empty: raise HTTPException(422, "No valid rows after cleaning")
    with Session.begin() as s:
        if reset:
            for t in (Metric, Server, Action): s.execute(delete(t))
        known = {r[0] for r in s.execute(text("SELECT id FROM servers"))}
        for sid, g in df.groupby("sid").first().iterrows():
            if sid not in known: s.add(Server(id=sid, itype=g.itype, service=g.service))
    df[["sid", "ts", "cpu", "ram", "err"]].to_sql("metrics", eng, if_exists="append", index=False, chunksize=2000, method="multi")
    return len(df)
 
 
# ---------- data in ----------
@app.get("/scenarios")
def scenarios():
    return [dict(id=k, title=v[0], story=v[1], expect=v[2]) for k, v in SC.SCENARIOS.items()]
 
 
@app.post("/scenarios/{case}/load")
def load_case(case: int, augment: bool = False):
    if case not in SC.SCENARIOS: raise HTTPException(404, "Unknown scenario")
    df, ev = SC.build(case)
    if augment: df = SC.augment(df, seed=case)
    store(df, reset=True); META.update(case=case, title=SC.SCENARIOS[case][0] + (" (augmented)" if augment else ""))
    refresh(); V.S["raw_evs"] = ev; V.load_df(V.S["df"], ev)
    return overview()
 
 
@app.post("/ingest/file")
async def ingest_file(file: UploadFile = File(...)):
    raw = io.BytesIO(await file.read())
    try: df = pd.read_json(raw) if file.filename.lower().endswith(".json") else pd.read_csv(raw)
    except Exception as e: raise HTTPException(400, f"Unreadable file: {e}")
    n = store(df, reset=True); META.update(case="upload", title=file.filename); refresh(); V.load_df(V.S["df"], [])
    return dict(rows=n, **overview())
 
 
class Prom(BaseModel):
    url: str; days: int = 7
    query: str = '100-avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m]))*100'
    ram_query: str | None = "100*(1-node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)"
 
 
@app.post("/ingest/prometheus")
def ingest_prom(p: Prom):
    end = datetime.utcnow(); start = end - timedelta(days=p.days)
 
    def pull(q, name):
        r = httpx.get(p.url.rstrip("/") + "/api/v1/query_range", timeout=30,
                      params=dict(query=q, start=start.timestamp(), end=end.timestamp(), step=3600)); r.raise_for_status()
        return pd.DataFrame([(x["metric"].get("instance", "?"), datetime.utcfromtimestamp(float(t)), float(v))
                             for x in r.json()["data"]["result"] for t, v in x["values"]], columns=["sid", "ts", name])
    try:
        df = pull(p.query, "cpu")
        if p.ram_query: df = df.merge(pull(p.ram_query, "ram"), on=["sid", "ts"], how="left")
    except Exception as e: raise HTTPException(502, f"Prometheus error: {e}")
    n = store(df, reset=True); META.update(case="prometheus", title="Prometheus"); refresh(); V.load_df(V.S["df"], [])
    return dict(rows=n, **overview())
 
 
# ---------- analysis ----------
def need():
    if not V.S["dem"]: raise HTTPException(409, "No data loaded. Pick a scenario or upload a CSV.")
 
 
@app.get("/overview")
def overview(risk: float = .5):
    need(); return dict(meta=META, **V.overview(risk))
 
 
@app.get("/fleet")
def fleet():
    need(); P = list(V.profiles().values())
    with Session() as s:
        buried = [dict(id=r[0], service=r[1], itype=r[2], saving=E.CATALOG.get(r[2], (0, 0, 0))[2])
                  for r in s.execute(text("SELECT id,service,itype FROM servers WHERE state='buried'"))]
    return dict(servers=sorted(P, key=lambda p: -p["waste"]), buried=buried)
 
 
@app.post("/servers/{sid}/{verb}")
def act(sid: str, verb: str):
    need(); p = V.profiles().get(sid)
    if not p or verb not in ("bury", "shrink", "keep"): raise HTTPException(404, "Unknown server/action")
    if verb == "bury" and p["status"] != "zombie": raise HTTPException(409, f"Blocked by safety rules: {p['reason']}")
    if verb == "shrink" and (p["status"] not in ("wasteful", "zombie") or p["to"] == p["itype"]): raise HTTPException(409, f"Blocked by safety rules: {p['reason']}")
    with Session.begin() as s:
        row = s.get(Server, sid)
        if verb == "bury": row.state = "buried"
        if verb == "shrink": row.itype = p["to"]
        s.add(Action(sid=sid, verb=verb, detail=p["reason"], saving=p["waste"] if verb != "keep" else 0))
    refresh(); V.load_df(V.S["df"])
    return fleet()
 
 
@app.get("/services/{svc}/plan")
def plan(svc: str, risk: float = .5, growth: float = 0, events: bool = True, remove: int = 0):
    need()
    if svc not in V.SV() or V.SV()[svc]["n"] < 2: raise HTTPException(404, "Planning needs a service with 2+ servers")
    return V.compute(svc, risk, growth, events, remove)
 
 
@app.get("/services/{svc}/backtest")
def backtest(svc: str, risk: float = .5): need(); return V.backtest(svc, risk)
 
 
@app.get("/services/{svc}/analysis")
def analysis(svc: str):
    need(); d = V.S["dem"][svc]; r = V.fc(svc)
    return dict(stats=E.ts_stats(d.cpu), accuracy=E.accuracy(d, r["model"]), model=r["model"], conf=round(r["conf"], 2),
                scores={k: round(v, 3) for k, v in r["scores"].items()}, gain=round(r["gain"], 2))
 
 
@app.get("/services/{svc}/schedule.csv")
def schedule(svc: str, risk: float = .5):
    need(); p = V.compute(svc, risk)
    return Response(pd.DataFrame(dict(hour=p["fts"], servers=p["plan"])).to_csv(index=False), media_type="text/csv")
 
 
@app.get("/report.csv")
def report():
    need(); cols = ["id", "service", "itype", "status", "cost", "avg", "peak", "idle_days", "action", "to", "waste", "conf", "reason"]
    return Response(pd.DataFrame(V.profiles().values(), columns=cols).to_csv(index=False), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=optiserve_report.csv"})
 
 
@app.websocket("/ws/live")
async def live(ws: WebSocket):
    """Simulated live feed: replays last week's same-hour load per server + noise, one simulated hour per 1.5 s."""
    await ws.accept(); i, rng = 0, np.random.default_rng()
    try:
        while True:
            if V.S["fr"]:
                loads = {s: round(float(np.clip(h.cpu.values[-168 + i % 168] + rng.normal(0, 2), 0, 100)), 1) for s, h in V.S["fr"].items()}
                t = V.S["df"].ts.max() + pd.Timedelta(hours=i % 168 + 1)
                await ws.send_json(dict(t=t.isoformat() + "Z", loads=loads, svc={s: V.S["info"][s][0] for s in loads}))
                i += 1
            await asyncio.sleep(1.5)
    except (WebSocketDisconnect, RuntimeError): pass
 
 
@app.get("/health")
def health(): return {"ok": True}
 
 
refresh()
 
