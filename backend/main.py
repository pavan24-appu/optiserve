"""OptiServe API - AIOps rightsizing: ingest -> clean/aggregate -> forecast -> optimize -> approve."""
import io, os
from datetime import datetime, timedelta
import httpx, numpy as np, pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sklearn.ensemble import RandomForestRegressor
from sqlalchemy import Column, DateTime, Float, Index, Integer, String, create_engine, delete, select
from sqlalchemy.orm import declarative_base, sessionmaker
 
DB = os.getenv("DATABASE_URL", "sqlite:///optiserve.db").replace("postgres://", "postgresql://", 1)
engine = create_engine(DB, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if DB.startswith("sqlite") else {})
Session = sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()
 
# instance type -> (vCPU, RAM GB, $/month)
CATALOG = {"t3.small": (2, 2, 15), "t3.medium": (2, 4, 30), "m5.large": (2, 8, 70),
           "m5.xlarge": (4, 16, 140), "m5.2xlarge": (8, 32, 280), "m5.4xlarge": (16, 64, 560)}
TARGET_CPU, TARGET_RAM, RISK = 70, 80, 85   # healthy peak utilisation targets (%)
 
 
class Server(Base):
    __tablename__ = "servers"
    id = Column(String, primary_key=True)
    itype = Column(String, default="m5.large")
 
 
class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True)
    sid = Column(String)
    ts = Column(DateTime)
    cpu = Column(Float); ram = Column(Float); net = Column(Float); disk = Column(Float)
    __table_args__ = (Index("ix_metric_sid_ts", "sid", "ts"),)
 
 
class Action(Base):
    __tablename__ = "actions"
    id = Column(Integer, primary_key=True)
    sid = Column(String); kind = Column(String); frm = Column(String); to = Column(String)
    saving = Column(Float); reason = Column(String)
    status = Column(String, default="pending")
    at = Column(DateTime, default=datetime.utcnow)
 
 
Base.metadata.create_all(engine)
app = FastAPI(title="OptiServe", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
_cache: dict = {}
ALIASES = {"server": "sid", "instance": "sid", "host": "sid", "timestamp": "ts", "time": "ts",
           "cpu_utilization": "cpu", "memory": "ram", "instance_type": "itype"}
 
 
# ---------- ingestion + cleaning ----------
def store(df: pd.DataFrame) -> int:
    df = df.rename(columns=ALIASES).copy()
    if not {"sid", "ts", "cpu"} <= set(df.columns):
        raise HTTPException(422, "Need columns: server, ts, cpu (optional: ram, net, disk, itype)")
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True).dt.tz_localize(None)
    for c in ("cpu", "ram", "net", "disk"):
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    if "itype" not in df: df["itype"] = None
    df = df.dropna(subset=["sid", "ts", "cpu"]).drop_duplicates(["sid", "ts"])
    df["cpu"] = df.cpu.clip(0, 100); df["ram"] = df.ram.clip(0, 100)
    if df.empty: raise HTTPException(422, "No valid rows after cleaning")
    cols = df[["sid", "ts", "cpu", "ram", "net", "disk"]].astype(object)
    rows = cols.where(cols.notna(), None).to_dict("records")
    with Session.begin() as s:
        known = {x for x in s.scalars(select(Server.id))}
        for sid, it in df.groupby("sid")["itype"].first().items():
            if sid not in known:
                s.add(Server(id=str(sid), itype=it if it in CATALOG else "m5.large"))
        s.execute(Metric.__table__.insert(), rows)
    return len(rows)
 
 
class Point(BaseModel):
    server: str; ts: str; cpu: float
    ram: float | None = None; net: float | None = None; disk: float | None = None
    itype: str | None = None
 
 
@app.post("/ingest")
def ingest(points: list[Point]):
    return {"rows": store(pd.DataFrame([p.model_dump() for p in points]))}
 
 
@app.post("/ingest/file")
async def ingest_file(file: UploadFile = File(...)):
    raw = io.BytesIO(await file.read())
    try:
        df = pd.read_json(raw) if file.filename.lower().endswith(".json") else pd.read_csv(raw)
    except Exception as e:
        raise HTTPException(400, f"Unreadable file: {e}")
    return {"rows": store(df)}
 
 
class Prom(BaseModel):
    url: str; days: int = 7
    query: str = '100-avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m]))*100'
    ram_query: str | None = "100*(1-node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)"
 
 
@app.post("/ingest/prometheus")
def ingest_prom(p: Prom):
    end = datetime.utcnow(); start = end - timedelta(days=p.days)
 
    def pull(q, name):
        r = httpx.get(p.url.rstrip("/") + "/api/v1/query_range", timeout=30,
                      params=dict(query=q, start=start.timestamp(), end=end.timestamp(), step=300))
        r.raise_for_status()
        return pd.DataFrame([(x["metric"].get("instance", "?"), datetime.utcfromtimestamp(float(t)), float(v))
                             for x in r.json()["data"]["result"] for t, v in x["values"]],
                            columns=["sid", "ts", name])
    try:
        df = pull(p.query, "cpu")
        if p.ram_query: df = df.merge(pull(p.ram_query, "ram"), on=["sid", "ts"], how="left")
    except Exception as e:
        raise HTTPException(502, f"Prometheus error: {e}")
    return {"rows": store(df)}
 
 
# ---------- aggregation + ML ----------
def hourly(sid: str) -> pd.DataFrame:
    df = pd.read_sql(select(Metric.ts, Metric.cpu, Metric.ram).where(Metric.sid == sid), engine)
    if df.empty: return df
    h = df.assign(ts=pd.to_datetime(df.ts)).set_index("ts").resample("h").mean().interpolate(limit=6)
    h["ram"] = h.ram.fillna(h.cpu)          # no RAM metric -> assume it tracks CPU
    return h.dropna(subset=["cpu"])
 
 
def feat(ix):
    h, d = ix.hour.values, ix.dayofweek.values
    return np.c_[h, d, d >= 5, np.sin(h / 24 * 6.283), np.cos(h / 24 * 6.283)]
 
 
def forecast(cpu: pd.Series, days: int = 30):
    """Random Forest on hour/day seasonality + linear trend. Returns hourly forecast and 95% error margin."""
    d = cpu.resample("D").mean().dropna()
    slope = float(np.clip(np.polyfit(np.arange(len(d)), d.values, 1)[0], -.5, .5)) if len(d) > 2 else 0.0
    t = lambda ix: np.asarray((ix - cpu.index[0]).total_seconds()) / 86400
    y = cpu.values - slope * t(cpu.index)
    rf = RandomForestRegressor(150, min_samples_leaf=3, oob_score=True, n_jobs=-1, random_state=1)
    rf.fit(feat(cpu.index), y)
    margin = max(0.0, float(np.nanquantile(y - rf.oob_prediction_, .95)))
    fi = pd.date_range(cpu.index[-1] + pd.Timedelta(hours=1), periods=days * 24, freq="h")
    return pd.Series(np.clip(rf.predict(feat(fi)) + slope * t(fi), 0, 100), fi), margin
 
 
def get_fc(sid, h):
    key = (sid, len(h), h.index[-1])
    if key not in _cache: _cache[key] = forecast(h.cpu)
    return _cache[key]
 
 
# ---------- optimisation ----------
def analyze(sid: str, itype: str):
    h = hourly(sid)
    if len(h) < 48: return None
    fc, m = get_fc(sid, h)
    hp = h.cpu.quantile(.98)
    pk7 = min(100, max(fc[:168].max() + m, hp)); pk30 = min(100, max(fc.max() + m, hp))
    v, r, c = CATALOG[itype]
    need_v = v * max(pk7, pk30) / TARGET_CPU
    need_r = r * h.ram.quantile(.95) / TARGET_RAM
    best = min((k for k, (vv, rr, _) in CATALOG.items() if vv >= need_v and rr >= need_r),
               key=lambda k: CATALOG[k][2], default="m5.4xlarge")
    nc = CATALOG[best][2]
    kind = "scale_down" if nc < c else "scale_up" if nc > c else "none"
    status = "risk" if kind == "scale_up" or pk30 >= RISK else "idle" if kind == "scale_down" else "optimal"
    avg = h.cpu.mean()
    return dict(id=sid, itype=itype, cost=c, target=best, kind=kind, status=status, saving=round(c - nc, 2),
                avg_cpu=round(avg, 1), avg_ram=round(h.ram.mean(), 1), pk7=round(pk7, 1), pk30=round(pk30, 1),
                night=round(h.cpu[h.index.hour < 7].mean(), 1),
                normal=round(h.cpu[(h.index.hour >= 9) & (h.index.hour < 19)].mean(), 1),
                peak=round(h.cpu.quantile(.95), 1),
                reason=f"Forecast peak {pk7:.0f}% (7d) / {pk30:.0f}% (30d), avg {avg:.0f}% on {itype}")
 
 
def fleet():
    with Session() as s:
        servers = s.execute(select(Server).order_by(Server.id)).scalars().all()
    return [a for x in servers if (a := analyze(x.id, x.itype))]
 
 
def actions():
    with Session() as s:
        rows = s.execute(select(Action).order_by(Action.id.desc()).limit(50)).scalars().all()
    return [dict(id=a.id, sid=a.sid, kind=a.kind, frm=a.frm, to=a.to, saving=a.saving,
                 reason=a.reason, status=a.status, at=a.at.isoformat() + "Z") for a in rows]
 
 
@app.get("/dashboard")
def dashboard():
    f = fleet()
    spend = sum(a["cost"] for a in f); waste = sum(max(a["saving"], 0) for a in f)
    count = lambda st: sum(a["status"] == st for a in f)
    return dict(
        summary=dict(servers=len(f), spend=spend, waste=waste,
                     savings_pct=round(100 * waste / spend, 1) if spend else 0,
                     efficiency=round(float(np.mean([min(100, a["avg_cpu"] * 2) for a in f]))) if f else 0,
                     idle=count("idle"), risk=count("risk"), optimal=count("optimal")),
        servers=f, actions=actions())
 
 
@app.get("/servers/{sid}/series")
def series(sid: str, days: int = 7):
    h = hourly(sid)
    if len(h) < 48: raise HTTPException(404, "Not enough data")
    fc, m = get_fc(sid, h)
    hh, ff = h.cpu[-days * 24:], fc[:days * 24]
    iso = lambda ix: [t.isoformat() + "Z" for t in ix]
    return dict(hts=iso(hh.index), hist=hh.round(1).tolist(), fts=iso(ff.index),
                fc=ff.round(1).tolist(), margin=round(m, 1))
 
 
@app.post("/optimize")
def optimize():
    f = fleet()
    with Session.begin() as s:
        s.execute(delete(Action).where(Action.status == "pending"))
        for a in f:
            if a["kind"] != "none":
                s.add(Action(sid=a["id"], kind=a["kind"], frm=a["itype"], to=a["target"],
                             saving=a["saving"], reason=a["reason"]))
    return dashboard()
 
 
def cloud_apply(s, a: Action):
    """Cloud simulator. Swap for boto3 ec2.modify_instance_attribute / Azure SDK resize in production."""
    s.get(Server, a.sid).itype = a.to
    return dict(provider="aws-sim", api="ModifyInstanceAttribute", instance=a.sid, type=a.to, ok=True)
 
 
@app.post("/actions/{aid}/{verb}")
def decide(aid: int, verb: str):
    if verb not in ("approve", "reject"): raise HTTPException(400, "verb must be approve|reject")
    cloud = None
    with Session.begin() as s:
        a = s.get(Action, aid)
        if not a or a.status != "pending": raise HTTPException(409, "Action not pending")
        if verb == "reject": a.status = "rejected"
        else: cloud = cloud_apply(s, a); a.status = "applied"
    return dict(cloud=cloud, **dashboard())
 
 
@app.get("/report.csv")
def report():
    cols = ["id", "itype", "target", "kind", "status", "cost", "saving", "avg_cpu", "avg_ram", "pk7", "pk30", "reason"]
    return Response(pd.DataFrame(fleet(), columns=cols).to_csv(index=False), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=optiserve_report.csv"})
 
 
# ---------- sample data ----------
BASE = [10] * 7 + [30, 40, 50, 55, 75, 90, 90, 75, 55, 50, 50, 45, 70, 85, 60, 30, 18]
SAMPLE = [("web-prod-01", "m5.xlarge", 1.5, .6), ("web-prod-02", "m5.2xlarge", .5, 0),
          ("api-gateway", "m5.large", 1.0, .9), ("batch-etl", "m5.4xlarge", .35, 0),
          ("db-replica", "m5.2xlarge", .8, .1), ("cache-01", "m5.xlarge", .6, 0),
          ("ml-train", "m5.4xlarge", .25, 0), ("staging-01", "m5.xlarge", .3, 0),
          ("auth-svc", "t3.medium", 1.0, .5), ("search-01", "m5.2xlarge", .7, .2),
          ("queue-01", "m5.large", .5, 0), ("report-gen", "m5.xlarge", .4, 0)]
 
 
@app.post("/seed")
def seed(days: int = 14):
    rng = np.random.default_rng(7)
    now = pd.Timestamp.utcnow().tz_localize(None).floor("h")
    ix = pd.date_range(now - pd.Timedelta(days=days) + pd.Timedelta(hours=1), now, freq="h")
    with Session.begin() as s:
        for t in (Metric, Action, Server): s.execute(delete(t))
    _cache.clear()
    frames = []
    for sid, it, scale, g in SAMPLE:
        grow = 1 + g * np.arange(len(ix)) / len(ix)
        wk = np.where(ix.dayofweek >= 5, .6, 1.0)
        cpu = np.clip(np.array(BASE)[ix.hour] * scale * wk * grow + rng.normal(0, 3, len(ix)), 3, 99)
        frames.append(pd.DataFrame(dict(sid=sid, ts=ix, cpu=cpu, itype=it,
                                        ram=np.clip(28 + .4 * cpu + rng.normal(0, 2, len(ix)), 5, 99))))
    store(pd.concat(frames))
    return dashboard()
 
 
@app.get("/health")
def health(): return {"ok": True}