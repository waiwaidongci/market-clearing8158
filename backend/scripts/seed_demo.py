import json
from sqlalchemy import func, select
from src.config.database import Session
from src.constants.enums import Role
from src.domain.demo import demo_calibrations, demo_rows
from src.domain.spec import SPEC
from src.models.clock import ClockCalibration
from src.models.identity import User
from src.models.source import Dataset
from src.services.clocking import add_calibration, recompute_dataset
from src.services.datasets import save
from src.utils.security import hash_password


def seed():
    with Session.begin() as db:
        for role in Role:
            if not db.get(User, role.value):
                db.add(User(username=role.value, role=role,
                            password_hash=hash_password(f'{role.value}-demo-2611')))
        item, created = save(db, SPEC['default_dataset'], SPEC['sample_name'], demo_rows(), 'seed')
        # 校时记录按 (设备, 设备时间) 幂等，重复执行 seed 不会产生重复行
        calibration_count = 0
        for payload in demo_calibrations():
            _, was_created = add_calibration(db, payload, 'seed')
            calibration_count += int(was_created)
        # 全量重算挂起台账（内部整体替换，可安全重复执行）
        clocking = recompute_dataset(db, item.id, 'seed')
        return {'users': db.scalar(select(func.count()).select_from(User)),
                'datasets': db.scalar(select(func.count()).select_from(Dataset)),
                'calibrations': db.scalar(select(func.count()).select_from(ClockCalibration)),
                'new_calibrations': calibration_count,
                'pending': clocking['pending_count'],
                'affected_days': clocking['affected_days'],
                'seed_dataset_id': item.id, 'row_count': item.row_count, 'checksum': item.checksum,
                'created_dataset': created}


if __name__ == '__main__':
    print(json.dumps(seed(), ensure_ascii=False))
