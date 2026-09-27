import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_409_CONFLICT,
)
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

from domain import CLAIM_NAMES, DEFAULT_CLAIM_NAME, STATUS_DONE

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "calibrator": {"role": "writer", "password_hash": pwd.hash("calib123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

JOB_COLS = "id, lamp, nominal_nm, measured_nm, status, verdict, reason, claim_name, created_by"

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id serial PRIMARY KEY,
        lamp text NOT NULL,
        nominal_nm double precision NOT NULL,
        measured_nm double precision NOT NULL,
        status text NOT NULL,
        verdict text NOT NULL DEFAULT '',
        reason text NOT NULL DEFAULT '',
        created_by text NOT NULL,
        created_at timestamptz NOT NULL
    )
    """,
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claim_name text NOT NULL DEFAULT ''",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_at timestamptz",
    """
    CREATE TABLE IF NOT EXISTS claim_history (
        id serial PRIMARY KEY,
        job_id int NOT NULL REFERENCES jobs(id),
        kind text NOT NULL,
        from_name text NOT NULL DEFAULT '',
        to_name text NOT NULL,
        changed_by text NOT NULL,
        created_at timestamptz NOT NULL
    )
    """,
]


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float


class ReassignIn(BaseModel):
    claim_name: str


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


@get("/api/jobs")
async def list_jobs(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(f"SELECT {JOB_COLS} FROM jobs ORDER BY id DESC").fetchall()
        return list(rows)


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(f"SELECT {JOB_COLS} FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        return dict(row)


@post("/api/jobs")
async def create_job(request: Request, data: JobIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可提交")
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
            VALUES (%s,%s,%s,'pending','','',%s,%s) RETURNING id
            """,
            (data.lamp.strip(), data.nominal_nm, data.measured_nm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
        return {"id": row["id"], "status": "pending"}


def _job_filters(claim_name: str, lamp: str) -> tuple[list, list]:
    clauses, params = [], []
    if claim_name:
        clauses.append("claim_name = %s")
        params.append(claim_name)
    if lamp:
        clauses.append("lamp ILIKE %s")
        params.append(f"%{lamp}%")
    return clauses, params


@get("/api/signature-desk")
async def signature_desk(request: Request) -> dict:
    """署名台:在途单、已署名清单(可按领取人/灯种筛选)、改派履历,并核对署名与领取进程是否一致。"""
    user_from_request(request)
    query = request.query_params
    f_name = (query.get("claim_name") or "").strip()
    f_lamp = (query.get("lamp") or "").strip()
    clauses, params = _job_filters(f_name, f_lamp)
    extra = (" AND " + " AND ".join(clauses)) if clauses else ""
    with connect() as conn:
        inflight = conn.execute(
            f"SELECT {JOB_COLS} FROM jobs WHERE status <> 'done'{extra} ORDER BY id DESC",
            params,
        ).fetchall()
        signed = conn.execute(
            f"SELECT {JOB_COLS} FROM jobs WHERE claim_name <> ''{extra} ORDER BY id DESC",
            params,
        ).fetchall()

        h_clauses, h_params = [], []
        if f_name:
            h_clauses.append("(h.from_name = %s OR h.to_name = %s)")
            h_params += [f_name, f_name]
        if f_lamp:
            h_clauses.append("j.lamp ILIKE %s")
            h_params.append(f"%{f_lamp}%")
        h_where = ("WHERE " + " AND ".join(h_clauses)) if h_clauses else ""
        history = conn.execute(
            f"""
            SELECT h.id, h.job_id, j.lamp, h.kind, h.from_name, h.to_name, h.changed_by,
                   to_char(h.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS created_at
            FROM claim_history h JOIN jobs j ON j.id = h.job_id
            {h_where}
            ORDER BY h.id DESC
            """,
            h_params,
        ).fetchall()

        # 领取进程留下的最新落名,用于核对当前署名是否一致
        latest = {}
        for r in conn.execute("SELECT job_id, to_name FROM claim_history ORDER BY id").fetchall():
            latest[r["job_id"]] = r["to_name"]

    for j in signed:
        expected = latest.get(j["id"], j["claim_name"])
        j["expected_claim_name"] = expected
        j["consistent"] = expected == j["claim_name"]
    return {
        "claim_names": CLAIM_NAMES,
        "inflight": list(inflight),
        "signed": list(signed),
        "history": list(history),
    }


@post("/api/jobs/{job_id:int}/reassign")
async def reassign_job(request: Request, job_id: int, data: ReassignIn) -> dict:
    """把在途单改派给另一领取名并记履历;已结案不可改派。"""
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可改派")
    new_name = data.claim_name.strip()
    if new_name not in CLAIM_NAMES:
        raise HTTPException(status_code=400, detail="未知领取名")
    with connect() as conn:
        row = conn.execute(f"SELECT {JOB_COLS} FROM jobs WHERE id = %s FOR UPDATE", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        if row["status"] == STATUS_DONE:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail="已结案不可改派")
        old_name = row["claim_name"]
        if new_name == old_name:
            raise HTTPException(status_code=400, detail="新领取名与当前领取名相同")
        now = datetime.now(timezone.utc)
        conn.execute("UPDATE jobs SET claim_name = %s WHERE id = %s", (new_name, job_id))
        conn.execute(
            """
            INSERT INTO claim_history(job_id, kind, from_name, to_name, changed_by, created_at)
            VALUES (%s,'reassign',%s,%s,%s,%s)
            """,
            (job_id, old_name, new_name, user["username"], now),
        )
        conn.commit()
        row = conn.execute(f"SELECT {JOB_COLS} FROM jobs WHERE id = %s", (job_id,)).fetchone()
        return dict(row)


def on_startup() -> None:
    with connect() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            for lamp, nominal, measured, verdict, reason in [
                ("氦灯-587", 587.56, 587.50, "合格", "偏差 0.0600 nm 在允差内"),
                ("汞灯-546", 546.07, 546.30, "超差", "偏差 0.2300 nm 超过允差 0.08"),
            ]:
                row = conn.execute(
                    """
                    INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason,
                                     created_by, created_at, claim_name, claimed_at)
                    VALUES (%s,%s,%s,'done',%s,%s,'seed',%s,%s,%s) RETURNING id
                    """,
                    (lamp, nominal, measured, verdict, reason, now, DEFAULT_CLAIM_NAME, now),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO claim_history(job_id, kind, from_name, to_name, changed_by, created_at)
                    VALUES (%s,'claim','',%s,'seed',%s)
                    """,
                    (row["id"], DEFAULT_CLAIM_NAME, now),
                )
        conn.commit()


app = Litestar(
    route_handlers=[health, login, list_jobs, get_job, create_job, signature_desk, reassign_job],
    on_startup=[on_startup],
)
