"""收银设备时钟校正接口：校时登记、挂起台账查询与营业日重算。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.config.database import connection
from src.constants.enums import Role
from src.controllers.auth import allow, current
from src.models.identity import User
from src.schemas.requests import CalibrationRequest, RecomputeRequest
from src.services.audit import record
from src.services.clocking import (
    add_calibration, list_calibrations, list_pending, recompute_dataset,
)
from src.utils.time import iso

router = APIRouter(prefix='/clock')


def _calibration_view(item):
    return {
        'id': item.id, 'device_id': item.device_id, 'device_time': item.device_time,
        'standard_time': item.standard_time, 'offset_seconds': item.offset_seconds,
        'author': item.author, 'created_at': iso(item.created_at),
    }


def _pending_view(item):
    return {
        'id': item.id, 'dataset_id': item.dataset_id, 'transaction_key': item.transaction_key,
        'device_id': item.device_id, 'device_time': item.device_time,
        'recorded_day': item.recorded_day, 'reason_kind': item.reason_kind,
        'pending_reason': item.pending_reason, 'basis': item.basis,
        'range_start': item.range_start, 'range_end': item.range_end,
        'updated_at': iso(item.updated_at),
    }


@router.get('/calibrations')
def calibrations(db: Session = Depends(connection), actor: User = Depends(current)):
    return [_calibration_view(item) for item in list_calibrations(db)]


@router.post('/calibrations', status_code=201)
def register(body: CalibrationRequest, db: Session = Depends(connection),
             actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    item, created = add_calibration(db, body.model_dump(), actor.username)
    if created:
        record(db, actor.username, 'clock.calibration.registered', item.id,
               device_id=item.device_id, device_time=item.device_time)
    db.commit()
    return {**_calibration_view(item), 'created': created}


@router.get('/pending')
def pending(dataset_id: int | None = None, day: str | None = None,
            db: Session = Depends(connection), actor: User = Depends(current)):
    return [_pending_view(item) for item in list_pending(db, dataset_id, day)]


@router.post('/recompute')
def recompute(body: RecomputeRequest, db: Session = Depends(connection),
              actor: User = Depends(allow(Role.ADMIN, Role.ANALYST))):
    """乱序补录后重算指定批次的营业日归属，只返回受影响日期，事务保证不重复计账。"""
    result = recompute_dataset(db, body.dataset_id, actor.username)
    db.commit()
    return result
