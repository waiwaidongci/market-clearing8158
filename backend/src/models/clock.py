from datetime import datetime
from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.utils.time import now


class ClockCalibration(Base):
    """收银设备校时记录：一次联网校时对应一条设备时间 ↔ 标准时间。

    乱序补录天然支持：记录只登记校时事实，归属计算时按设备时间排序后再夹区间。
    同一设备同一设备时间只允许一条，重复补录在服务层按幂等处理。
    """
    __tablename__ = 'clock_calibrations'
    __table_args__ = (UniqueConstraint('device_id', 'device_time', name='uq_calibration_device_time'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), index=True)
    # 统一存带时区偏移的 ISO-8601 字符串，保持与导入数据同一口径
    device_time: Mapped[str] = mapped_column(String(40))
    standard_time: Mapped[str] = mapped_column(String(40))
    offset_seconds: Mapped[int]
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)


class PendingAttribution(Base):
    """食堂核销营业日挂起台账：跨日或缺校时依据的流水先挂起，不进入当日清分。

    每次校时补录后在同一事务内按数据批次重算并整体替换，保证并发重试不重复计账；
    ``reason_kind`` 区分「跨日待定」与「缺校时依据」，``basis`` 存归属依据原文。
    """
    __tablename__ = 'pending_attributions'
    __table_args__ = (
        UniqueConstraint('dataset_id', 'transaction_key', name='uq_pending_dataset_key'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(index=True)
    transaction_key: Mapped[str] = mapped_column(String(100))
    device_id: Mapped[str | None] = mapped_column(String(80))
    device_time: Mapped[str | None] = mapped_column(String(40))
    recorded_day: Mapped[str] = mapped_column(String(20), index=True)
    reason_kind: Mapped[str] = mapped_column(String(20))
    pending_reason: Mapped[str] = mapped_column(String(300))
    basis: Mapped[str] = mapped_column(String(600))
    range_start: Mapped[str | None] = mapped_column(String(40))
    range_end: Mapped[str | None] = mapped_column(String(40))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    author: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    created_at: Mapped[datetime] = mapped_column(default=now)


class AttributionSnapshot(Base):
    """每个数据批次最近一次全量营业日归属快照（食堂核销侧）。

    用单行 JSON 保存上一轮归属结果，使下一轮「受影响营业日」能逐笔比较状态与营业日
    变化（含已归属流水的跨日改归属），而不只是挂起集合的差集。随挂起台账在同一事务内
    整体替换，并发重算由数据集行锁串行化。
    """
    __tablename__ = 'attribution_snapshots'

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(unique=True, index=True)
    attributions: Mapped[list] = mapped_column(JSON, default=list)
    author: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    created_at: Mapped[datetime] = mapped_column(default=now)
