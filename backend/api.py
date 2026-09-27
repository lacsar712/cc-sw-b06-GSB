import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "calibrator": {"role": "writer", "password_hash": pwd.hash("calib123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

# 领取名册：领取进程（worker）与改派目标都必须在此册内
CLAIMERS = ["领取员甲", "领取员乙"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id serial PRIMARY KEY,
    lamp text NOT NULL,
    nominal_nm double precision NOT NULL,
    measured_nm double precision NOT NULL,
    status text NOT NULL,
    verdict text NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    assignee text NOT NULL DEFAULT '',
    claimed_at timestamptz
);

CREATE TABLE IF NOT EXISTS claim_events (
    id serial PRIMARY KEY,
    job_id int NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind text NOT NULL,
    actor text NOT NULL DEFAULT '',
    from_assignee text NOT NULL DEFAULT '',
    to_assignee text NOT NULL DEFAULT '',
    note text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claim_events_job ON claim_events(job_id, id);
"""

# 老库幂等补列（基线 jobs 表没有 assignee / claimed_at）
MIGRATIONS = [
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS assignee text NOT NULL DEFAULT ''",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_at timestamptz",
]

JOB_COLUMNS = (
    "id, lamp, nominal_nm, measured_nm, status, verdict, reason, "
    "created_by, created_at, assignee, claimed_at"
)


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


def serialize_job(row: dict) -> dict:
    row = dict(row)
    row["claimed"] = bool(row.get("assignee"))
    # 署名与领取进程一致性：已署名必须处于领取中/已结案；未署名必须仍待处理
    status = row.get("status")
    if row.get("assignee"):
        row["signature_consistent"] = status in ("processing", "done")
    else:
        row["signature_consistent"] = status == "pending"
    return row


def fetch_events(conn, *job_ids) -> dict:
    if not job_ids:
        return {}
    rows = conn.execute(
        f"SELECT * FROM claim_events WHERE job_id = ANY(%s) ORDER BY job_id, id",
        (list(job_ids),),
    ).fetchall()
    grouped: dict = {}
    for r in rows:
        grouped.setdefault(r["job_id"], []).append(dict(r))
    return grouped


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float


class ReassignIn(BaseModel):
    assignee: str


def user_from_request(request: Request) -> dict:
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "spectrum-wavelength-desk"}


@post("/api/login")
async def login(data: LoginIn) -> dict:
    u = USERS.get(data.username)
    if not u or not pwd.verify(data.password, u["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token = jwt.encode(
        {
            "sub": data.username,
            "role": u["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"access_token": token, "role": u["role"], "username": data.username}


@get("/api/claimers")
async def list_claimers(request: Request) -> dict:
    user_from_request(request)
    return {"claimers": CLAIMERS}


@get("/api/jobs")
async def list_jobs(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(f"SELECT {JOB_COLUMNS} FROM jobs ORDER BY id DESC").fetchall()
        return [serialize_job(r) for r in rows]


@get("/api/station")
async def station(request: Request, assignee: str | None = None, lamp: str | None = None) -> dict:
    """署名台：已署名清单（可按领取人 / 灯种筛选）+ 全量改派履历。"""
    user_from_request(request)
    where = ["assignee <> ''"]
    params: list = []
    if assignee:
        where.append("assignee = %s")
        params.append(assignee)
    if lamp:
        where.append("lamp ILIKE %s")
        params.append(f"%{lamp.strip()}%")
    sql = (
        f"SELECT {JOB_COLUMNS} FROM jobs WHERE {' AND '.join(where)} "
        "ORDER BY claimed_at DESC NULLS LAST, id DESC"
    )
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        jobs = [serialize_job(r) for r in rows]
        events = fetch_events(conn, *(r["id"] for r in rows))
        for j in jobs:
            j["events"] = events.get(j["id"], [])
        history = conn.execute(
            "SELECT * FROM claim_events WHERE kind IN ('reassign','claim') ORDER BY id DESC LIMIT 200"
        ).fetchall()
    return {"jobs": jobs, "claimers": CLAIMERS, "history": [dict(e) for e in history]}


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            f"SELECT {JOB_COLUMNS} FROM jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="任务不存在")
        result = serialize_job(row)
        result["events"] = [
            dict(e)
            for e in conn.execute(
                "SELECT * FROM claim_events WHERE job_id=%s ORDER BY id",
                (job_id,),
            ).fetchall()
        ]
        return result


@post("/api/jobs")
async def create_job(request: Request, data: JobIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可提交")
    lamp = data.lamp.strip()
    if not lamp:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="灯种不能为空")
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason,
                             created_by, created_at, assignee, claimed_at)
            VALUES (%s,%s,%s,'pending','','',%s,%s,'',NULL) RETURNING id
            """,
            (lamp, data.nominal_nm, data.measured_nm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
        return {"id": row["id"], "status": "pending"}


@post("/api/jobs/{job_id:int}/reassign")
async def reassign_job(request: Request, job_id: int, data: ReassignIn) -> dict:
    """校准员把在途单（领取中）改派给名册内另一领取名；已结案不可改派。"""
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可改派")
    target = (data.assignee or "").strip()
    if target not in CLAIMERS:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="改派目标不在领取名册内")
    with connect() as conn:
        try:
            row = conn.execute(
                "SELECT id, status, assignee FROM jobs WHERE id=%s FOR UPDATE",
                (job_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="任务不存在")
            if row["status"] == "done":
                raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="已结案不可改派")
            if row["status"] != "processing":
                raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="仅在途（领取中）单可改派")
            old = row["assignee"]
            if old == target:
                raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="新领取人与当前相同")
            now = datetime.now(timezone.utc)
            # 改派：署名换成新人、重新计时，worker 按新署名新计时结案
            conn.execute(
                "UPDATE jobs SET assignee=%s, claimed_at=%s WHERE id=%s",
                (target, now, job_id),
            )
            conn.execute(
                """
                INSERT INTO claim_events(job_id, kind, actor, from_assignee, to_assignee, note, created_at)
                VALUES (%s,'reassign',%s,%s,%s,'',%s)
                """,
                (job_id, user["username"], old, target, now),
            )
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
    return {"id": job_id, "assignee": target}


def on_startup() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        for stmt in MIGRATIONS:
            conn.execute(stmt)
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            t0 = now - timedelta(seconds=30)
            conn.execute(
                """
                INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason,
                                 created_by, created_at, assignee, claimed_at)
                VALUES
                ('氦灯-587', 587.56, 587.50, 'done', '合格', '偏差 0.0600 nm 在允差内',
                 'seed', %s, '领取员甲', %s),
                ('汞灯-546', 546.07, 546.30, 'done', '超差', '偏差 0.2300 nm 超过允差 0.08',
                 'seed', %s, '领取员乙', %s)
                """,
                (now, t0, now, t0),
            )
            conn.execute(
                """
                INSERT INTO claim_events(job_id, kind, actor, from_assignee, to_assignee, note, created_at)
                VALUES
                (1,'claim','领取员甲','','领取员甲','首次领取',%s),
                (2,'claim','领取员甲','','领取员甲','首次领取',%s),
                (2,'reassign','calibrator','领取员甲','领取员乙','校准员改派',%s)
                """,
                (t0, t0, t0 + timedelta(seconds=5)),
            )
        conn.commit()


app = Litestar(
    route_handlers=[health, login, list_claimers, list_jobs, station, get_job, create_job, reassign_job],
    on_startup=[on_startup],
)
