TOLERANCE_NM = 0.08

# 领取进程可落的名（领取名）。校准员改派时只能在这些名之间切换。
CLAIM_NAMES = ["worker-a", "worker-b", "worker-c"]
DEFAULT_CLAIM_NAME = CLAIM_NAMES[0]

# 任务状态:pending 待处理 -> claiming 领取中 -> done 已结案
STATUS_PENDING = "pending"
STATUS_CLAIMING = "claiming"
STATUS_DONE = "done"


def judge(nominal: float, measured: float) -> tuple[str, str]:
    delta = abs(measured - nominal)
    if delta <= TOLERANCE_NM:
        return "合格", f"偏差 {delta:.4f} nm 在允差内"
    return "超差", f"偏差 {delta:.4f} nm 超过允差 {TOLERANCE_NM}"
