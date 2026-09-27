import os
import time
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from domain import DEFAULT_CLAIM_NAME, judge

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")

# 「领取中」保持可见的秒数,便于署名台看到领取名后再结案
CLAIM_VISIBLE_SECONDS = float(os.environ.get("CLAIM_VISIBLE_SECONDS", "1.5"))


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


def finalize_due(conn, now):
    """结案:领取中且超过可见窗口的单,写出合格或超差;署名(领取名)保留。"""
    due = conn.execute(
        """
        SELECT id, nominal_nm, measured_nm FROM jobs
        WHERE status='claiming' AND claimed_at <= %s
        ORDER BY id
        """,
        (now - timedelta(seconds=CLAIM_VISIBLE_SECONDS),),
    ).fetchall()
    for row in due:
        verdict, reason = judge(row["nominal_nm"], row["measured_nm"])
        conn.execute(
            "UPDATE jobs SET status='done', verdict=%s, reason=%s WHERE id=%s AND status='claiming'",
            (verdict, reason, row["id"]),
        )
    return len(due)


def claim_one(conn, now):
    """领取:把最早的在途新单切入领取中并落领取名;已被改派预指派的单沿用该名。"""
    row = conn.execute(
        """
        SELECT id, claim_name FROM jobs
        WHERE status='pending'
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    name = row["claim_name"] or DEFAULT_CLAIM_NAME
    conn.execute(
        "UPDATE jobs SET status='claiming', claim_name=%s, claimed_at=%s WHERE id=%s",
        (name, now, row["id"]),
    )
    conn.execute(
        """
        INSERT INTO claim_history(job_id, kind, from_name, to_name, changed_by, created_at)
        VALUES (%s,'claim',%s,%s,'worker',%s)
        """,
        (row["id"], row["claim_name"], name, now),
    )
    return row["id"]


def main():
    while True:
        try:
            now = datetime.now(timezone.utc)
            with connect() as conn:
                finalize_due(conn, now)
                claim_one(conn, now)
                conn.commit()
        except Exception as exc:
            print("worker err", exc, flush=True)
        time.sleep(0.4)


if __name__ == "__main__":
    main()
