"""校时记录登记与营业日归属重算。

设计要点：

- 校时记录按 (设备, 设备时间) 幂等去重，重复补录不产生新行、不重复计账。
- 每次补录后对指定数据批次全量重算归属，只返回受影响营业日（跨日改归属时
  原营业日与新营业日一起返回）。
- 挂起台账在单个数据库事务内「整体替换」，配合行级锁与幂等键，保证并发重试
  不会留下重复挂起记录；已归属流水不落挂起表。
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.domain.clock import (
    PENDING, REASON_CROSS_DAY_LABEL,
    affected_business_days, attribute_all, validate_calibration,
)
from src.domain.spec import CANTEEN
from src.models.clock import AttributionSnapshot, ClockCalibration, PendingAttribution
from src.models.source import Dataset
from src.services.audit import record

CROSS = "跨日待定"
MISSING = "缺校时依据"


def _reason_kind(basis):
    return CROSS if basis.startswith(REASON_CROSS_DAY_LABEL) else MISSING


def add_calibration(db, payload, actor):
    """登记一条校时记录，返回 (对象, 是否新建)。重复记录幂等返回已有行。"""
    item = validate_calibration(payload)
    lookup = select(ClockCalibration).where(
        ClockCalibration.device_id == item["device_id"],
        ClockCalibration.device_time == item["device_time"].isoformat(timespec="seconds"),
    )
    existing = db.scalar(lookup)
    if existing:
        if existing.standard_time != item["standard_time"].isoformat(timespec="seconds"):
            raise ValueError("同一设备时间已登记不同的标准时间，请核对校时数据")
        return existing, False
    row = ClockCalibration(
        device_id=item["device_id"],
        device_time=item["device_time"].isoformat(timespec="seconds"),
        standard_time=item["standard_time"].isoformat(timespec="seconds"),
        offset_seconds=item["offset_seconds"],
        author=actor,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        existing = db.scalar(lookup.with_for_update())
        if existing:
            if existing.standard_time != row.standard_time:
                raise ValueError("同一设备时间已登记不同的标准时间，请核对校时数据")
            return existing, False
        raise
    return row, True


def list_calibrations(db):
    return list(db.scalars(
        select(ClockCalibration).order_by(ClockCalibration.device_id, ClockCalibration.device_time))).copy()


def calibration_payloads(db):
    return [{"device_id": row.device_id, "device_time": row.device_time,
             "standard_time": row.standard_time} for row in list_calibrations(db)]


def _pending_rows(dataset_id, attributions, actor):
    rows = []
    for attr in attributions:
        if attr["status"] != PENDING:
            continue
        rows.append(PendingAttribution(
            dataset_id=dataset_id,
            transaction_key=attr["transaction_key"],
            device_id=attr.get("device_id"),
            device_time=attr.get("device_time"),
            recorded_day=attr.get("recorded_day"),
            reason_kind=_reason_kind(attr["basis"] or ""),
            pending_reason=attr["pending_reason"],
            basis=attr["basis"],
            range_start=attr.get("range_start"),
            range_end=attr.get("range_end"),
            evidence={
                "status": attr["status"],
                "business_day": attr.get("business_day"),
                "recorded_day": attr.get("recorded_day"),
                "range_start": attr.get("range_start"),
                "range_end": attr.get("range_end"),
                "basis": attr.get("basis"),
            },
            author=actor,
        ))
    return rows


def recompute_dataset(db, dataset_id, actor):
    """对单个数据批次重算营业日归属并整体替换挂起台账与归属快照。

    返回字典：受影响营业日、挂起/已归属计数，以及完整归属明细（供页面回查）。
    """
    dataset = db.get(Dataset, dataset_id, with_for_update=True)
    if not dataset:
        raise ValueError("找不到指定的数据批次")

    calibrations = calibration_payloads(db)
    current, _ = attribute_all(dataset.rows, calibrations)
    current_canteen = [attr for attr in current if attr.get("ledger") == CANTEEN]

    # 上一轮全量归属快照：首次重算时不存在，所有当日归属都视为受影响。
    snapshot = db.scalar(
        select(AttributionSnapshot).where(AttributionSnapshot.dataset_id == dataset_id))
    previous = snapshot.attributions if snapshot else []
    if previous:
        days = affected_business_days(previous, current_canteen)
    else:
        days = sorted({attr["business_day"] for attr in current_canteen
                       if attr.get("business_day")})

    # 整体替换挂起台账：先删后插，全部在同一事务内，失败整体回滚。
    # 并发重算在上面的数据集行锁上串行化，因此这里无需 skip_locked，避免漏删。
    old_pending = list(db.scalars(
        select(PendingAttribution).where(PendingAttribution.dataset_id == dataset_id)
        .order_by(PendingAttribution.id)))
    for stale in old_pending:
        db.delete(stale)
    db.add_all(_pending_rows(dataset_id, current_canteen, actor))

    if snapshot is None:
        snapshot = AttributionSnapshot(dataset_id=dataset_id, author=actor)
        db.add(snapshot)
    snapshot.attributions = current_canteen
    snapshot.author = actor

    pending = [attr for attr in current_canteen if attr["status"] == PENDING]
    record(db, actor, "clock.recomputed", dataset_id,
           affected_days=days, pending=len(pending), calibrations=len(calibrations))
    return {
        "dataset_id": dataset_id,
        "affected_days": days,
        "pending_count": len(pending),
        "attributed_count": len(current_canteen) - len(pending),
        "attributions": current,
    }


def list_pending(db, dataset_id=None, day=None):
    query = select(PendingAttribution)
    if dataset_id is not None:
        query = query.where(PendingAttribution.dataset_id == dataset_id)
    if day is not None:
        query = query.where(PendingAttribution.recorded_day == day)
    return list(db.scalars(query.order_by(PendingAttribution.dataset_id, PendingAttribution.id)))
