import os
import time
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from domain import judge

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
# 每个 worker 以一个具名领取人身份运行（compose 起两个：领取员甲 / 领取员乙）
CLAIMER_NAME = os.environ.get("CLAIMER_NAME", "领取员甲")
# 进入领取中后停留多久才结案，留出在途改派窗口
HOLD_SECONDS = float(os.environ.get("HOLD_SECONDS", "6"))
ROSTER = ["领取员甲", "领取员乙"]


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


def claim_one(conn) -> int | None:
    """领取一个待处理单：落领取名、状态切到领取中，并写首次领取履历。"""
    now = datetime.now(timezone.utc)
    row = conn.execute(
        """
        UPDATE jobs SET status='processing', assignee=%s, claimed_at=%s
        WHERE id = (
            SELECT id FROM jobs WHERE status='pending'
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
        )
        RETURNING id
        """,
        (CLAIMER_NAME, now),
    ).fetchone()
    if not row:
        return None
    conn.execute(
        """
        INSERT INTO claim_events(job_id, kind, actor, from_assignee, to_assignee, note, created_at)
        VALUES (%s,'claim',%s,'',%s,'首次领取',%s)
        """,
        (row["id"], CLAIMER_NAME, CLAIMER_NAME, now),
    )
    conn.commit()
    print(f"[{CLAIMER_NAME}] claimed job {row['id']}", flush=True)
    return row["id"]


def finish_held(conn) -> int | None:
    """把停留够久、且署名仍是自己的在途单结案；署名已被改派则不动（留给新领取人的 worker）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=HOLD_SECONDS)
    row = conn.execute(
        """
        SELECT id, nominal_nm, measured_nm, assignee, claimed_at
        FROM jobs
        WHERE status='processing' AND assignee=%s AND claimed_at <= %s
        ORDER BY claimed_at
        FOR UPDATE SKIP LOCKED LIMIT 1
        """,
        (CLAIMER_NAME, cutoff),
    ).fetchone()
    if not row:
        return None
    # 防御性复检：行锁拿到后署名必须仍是自己，改派后的单子不结案
    if row["assignee"] != CLAIMER_NAME:
        conn.rollback()
        return None
    verdict, reason = judge(row["nominal_nm"], row["measured_nm"])
    now = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE jobs SET status='done', verdict=%s, reason=%s WHERE id=%s",
        (verdict, reason, row["id"]),
    )
    conn.execute(
        """
        INSERT INTO claim_events(job_id, kind, actor, from_assignee, to_assignee, note, created_at)
        VALUES (%s,'complete',%s,%s,%s,'结案保留署名',%s)
        """,
        (row["id"], CLAIMER_NAME, CLAIMER_NAME, CLAIMER_NAME, now),
    )
    conn.commit()
    print(f"[{CLAIMER_NAME}] finished job {row['id']} -> {verdict}", flush=True)
    return row["id"]


def main():
    if CLAIMER_NAME not in ROSTER:
        print(f"[{CLAIMER_NAME}] 不在领取名册 {ROSTER}，仍以该名运行", flush=True)
    while True:
        try:
            with connect() as conn:
                claim_one(conn)
            with connect() as conn:
                finish_held(conn)
        except Exception as exc:
            print("worker err", exc, flush=True)
        time.sleep(0.4)


if __name__ == "__main__":
    main()
