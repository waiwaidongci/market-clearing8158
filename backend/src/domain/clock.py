"""收银设备离线时钟漂移与营业日归属。

校园卡账按卡中心的真实日期入账；食堂核销账由离线收银机按「设备时间」记录，
设备时钟会漂移。设备每次联网校时会留下一条校时记录（设备时间 ↔ 标准时间）。

对一笔设备时间为 ``device_time`` 的核销流水，取其前后相邻的两次校时：

- 前一次校时的偏差 ``offset_before = standard - device``，
- 后一次校时的偏差 ``offset_after = standard - device``，
- 真实时间被夹在闭区间::

      device_time + min(offset_before, offset_after)
      device_time + max(offset_before, offset_after)

整个真实时间区间落在同一自然日（北京时间），才把该笔核销归入该营业日的双账清分；
区间跨日，或缺前/后校时依据的，一律先挂起。模块同时给出挂起原因与归属依据，
供清分页面回查。所有计算均为纯函数，不依赖数据库与第三方库，便于离线单测。
"""

from datetime import datetime, timedelta, timezone

from .spec import CANTEEN

# 归属状态
ATTRIBUTED = "已归属"
PENDING = "挂起"
# 挂起原因
REASON_MISSING_BEFORE = "缺少前置校时记录，无法确定核销前的时钟偏差"
REASON_MISSING_AFTER = "缺少后置校时记录，无法确定核销后的时钟偏差"
REASON_CROSS_DAY = "真实时间区间跨营业日，无法唯一归属"
# 清分页面的两类待定原因
REASON_NO_CALIBRATION = "缺校时依据"
REASON_CROSS_DAY_LABEL = "跨日待定"

BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")
# 允许校时记录乱序补录，但限制单台设备校时条数，避免异常数据放大计算量
MAX_CALIBRATIONS_PER_DEVICE = 2000


def _parse_dt(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}须为 YYYY-MM-DDTHH:MM:SS+08:00 格式的时间")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{label}时间格式不正确：{text}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{label}须带时区偏移（如 +08:00）：{text}")
    return parsed.astimezone(BEIJING)


def validate_calibration(raw):
    """归一化并校验单条校时记录，返回内部字典（时间统一为北京时间）。"""
    if not isinstance(raw, dict):
        raise ValueError("校时记录须为字段对象")
    device = raw.get("device_id")
    if not isinstance(device, str) or not device.strip() or len(device) > 80:
        raise ValueError("设备编号缺失或格式不正确")
    device_time = _parse_dt(raw.get("device_time"), "设备时间")
    standard_time = _parse_dt(raw.get("standard_time"), "标准时间")
    return {
        "device_id": device.strip(),
        "device_time": device_time,
        "standard_time": standard_time,
        "offset_seconds": int((standard_time - device_time).total_seconds()),
    }


def build_timelines(calibrations):
    """按设备分组并按设备时间升序排列，返回 {device_id: [calibration, ...]}。

    同一设备同一设备时间只允许一条校时（重复补录视为同一条，以标准时间一致为准）。
    """
    timelines = {}
    for index, raw in enumerate(calibrations, 1):
        try:
            item = validate_calibration(raw)
        except ValueError as error:
            raise ValueError(f"校时记录第 {index} 条 · {error}") from None
        device = item["device_id"]
        line = timelines.setdefault(device, [])
        if len(line) >= MAX_CALIBRATIONS_PER_DEVICE:
            raise ValueError(f"设备 {device} 的校时记录超过 {MAX_CALIBRATIONS_PER_DEVICE} 条上限")
        if any(cal["device_time"] == item["device_time"] for cal in line):
            conflict = next(cal for cal in line if cal["device_time"] == item["device_time"])
            if conflict["standard_time"] != item["standard_time"]:
                raise ValueError(
                    f"校时记录第 {index} 条 · 设备 {device} 在同一设备时间存在冲突的标准时间")
            continue  # 幂等：完全相同的补录直接忽略
        line.append(item)
    for line in timelines.values():
        line.sort(key=lambda cal: cal["device_time"])
    return timelines


def _bracket(line, device_time):
    """返回 (前一条校时, 后一条校时)，边界采用闭区间。"""
    before = after = None
    for cal in line:
        if cal["device_time"] <= device_time:
            before = cal
        if cal["device_time"] >= device_time and after is None:
            after = cal
    return before, after


def _format_dt(stamp):
    return stamp.isoformat(timespec="seconds")


def attribute_row(row, timelines):
    """计算单笔食堂核销流水的真实时间区间与营业日归属。

    返回字典，字段供清分页面展示「待定原因」与「归属依据」。
    校园卡账流水不经过设备时钟，沿用原入账日，直接按已归属处理。
    """
    ledger = row.get("ledger")
    key = row.get("transaction_key")
    base = {
        "transaction_key": key,
        "ledger": ledger,
        "device_id": row.get("device_id"),
        "device_time": None,
        # recorded_day 保留设备/卡中心原始记账日，用于跨日改归属时定位旧营业日
        "recorded_day": row.get("posting_date"),
        "business_day": row.get("posting_date"),
        "status": ATTRIBUTED,
        "pending_reason": None,
        "range_start": None,
        "range_end": None,
        "basis": None,
    }
    if ledger != CANTEEN:
        base["basis"] = "校园卡账沿用卡中心入账日，不参与设备时钟校正"
        return base

    device_id = row.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        base["status"] = PENDING
        base["pending_reason"] = "食堂核销流水缺少设备编号，无法匹配校时记录"
        base["basis"] = REASON_NO_CALIBRATION
        return base
    line = timelines.get(device_id.strip())
    if not line:
        base["status"] = PENDING
        base["pending_reason"] = f"设备 {device_id.strip()} 没有任何校时记录"
        base["basis"] = REASON_NO_CALIBRATION
        return base

    device_time = _parse_dt(row.get("device_time"), f"流水 {key} 的设备时间")
    base["device_time"] = _format_dt(device_time)
    before, after = _bracket(line, device_time)

    if before is None:
        base["status"] = PENDING
        base["pending_reason"] = REASON_MISSING_BEFORE
        base["basis"] = REASON_NO_CALIBRATION
        return base
    if after is None:
        base["status"] = PENDING
        base["pending_reason"] = REASON_MISSING_AFTER
        base["basis"] = REASON_NO_CALIBRATION
        return base

    offsets = sorted((before["offset_seconds"], after["offset_seconds"]))
    range_start = device_time + timedelta(seconds=offsets[0])
    range_end = device_time + timedelta(seconds=offsets[1])
    base["range_start"] = _format_dt(range_start)
    base["range_end"] = _format_dt(range_end)
    start_day = range_start.date().isoformat()
    end_day = range_end.date().isoformat()

    base["basis"] = (
        f"前校时 {_format_dt(before['device_time'])} 偏差 {before['offset_seconds']} 秒，"
        f"后校时 {_format_dt(after['device_time'])} 偏差 {after['offset_seconds']} 秒；"
        f"真实时间夹于 {base['range_start']} 至 {base['range_end']}（北京时间）"
    )
    if start_day != end_day:
        base["status"] = PENDING
        base["pending_reason"] = f"{REASON_CROSS_DAY}（{start_day} / {end_day}）"
        base["basis"] = REASON_CROSS_DAY_LABEL + "；" + base["basis"]
        return base

    base["status"] = ATTRIBUTED
    base["business_day"] = start_day
    base["basis"] += f"，整个区间同属营业日 {start_day}"
    return base


def attribute_all(rows, calibrations):
    """对整批流水做营业日归属，返回 (attributions, timelines)。

    ``attributions`` 与输入流水一一对应、顺序一致，便于回挂原始行。
    """
    timelines = build_timelines(calibrations)
    attributions = [attribute_row(row, timelines) for row in rows]
    return attributions, timelines


def affected_business_days(previous, current):
    """乱序补到校时记录后，只挑出归属发生变化的营业日。

    入参为补录前后两次归属结果。按 (来源, 流水号) 配对比较，返回排序去重后的
    营业日集合，包含旧归属日（挂起时取设备原始记账日）与新归属日，保证跨日改
    归属时涉及的两天都会被重算。
    """
    def identity(attr):
        return attr.get("ledger"), attr.get("transaction_key")

    old_map = {identity(attr): attr for attr in previous}
    new_map = {identity(attr): attr for attr in current}
    if old_map.keys() != new_map.keys():
        raise ValueError("两次归属的流水集合不一致，无法比较受影响日期")

    days = set()

    def touched_day(item):
        # 挂起流水没有确定营业日，回退到设备原始记账日，确保跨日改归属不漏算旧日期
        return item.get("business_day") or item.get("recorded_day")

    for key, new in new_map.items():
        old = old_map[key]
        if (old.get("business_day"), old.get("status")) != (new.get("business_day"), new.get("status")):
            for item in (old, new):
                day = touched_day(item)
                if day:
                    days.add(day)
    return sorted(days)
