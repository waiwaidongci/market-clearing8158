"""青禾大学双账明细，含隔日冲正、退扣、需追查的流水及离线收银设备时钟。

食堂核销账的每一行都带 ``device_id`` 与 ``device_time``（设备时间）；校园卡账
沿用卡中心日期，不需要设备字段。三台演示设备对应三种营业日归属情形：

- POS-01：校时完整、偏差小，所有核销真实时间都落在同一天，正常归属。
- POS-02：时钟偏慢，凌晨核销 C009 的真实时间区间横跨两日，先挂起（跨日待定）。
- POS-03：校时依据不完整，C007 缺前置校时、C010 缺后置校时，先挂起（缺校时依据）。
"""

from .spec import CAMPUS, CANTEEN, DEMO_DAY, PARTIAL, PRIOR_DAY, REDEEM, REVERSE

# (流水号、入账日、校区、档口组、类型、原核销、校园分、食堂分、设备编号、设备时间)
_ENTRIES = (
    ("C001", PRIOR_DAY, "东校区", "自营档口", REDEEM, None, 1200, 1200, "POS-01", "2026-11-19T12:10:00+08:00"),
    ("C002", PRIOR_DAY, "西校区", "合作档口", REDEEM, None, 900, 900, "POS-02", "2026-11-19T12:25:00+08:00"),
    ("C003", PRIOR_DAY, "东校区", "合作档口", REDEEM, None, 800, 800, "POS-01", "2026-11-19T12:40:00+08:00"),
    ("C004", DEMO_DAY, "东校区", "自营档口", REDEEM, None, 1550, 1550, "POS-01", "2026-11-20T11:05:00+08:00"),
    ("C005", DEMO_DAY, "西校区", "合作档口", REDEEM, None, 1250, 1200, "POS-02", "2026-11-20T11:20:00+08:00"),
    ("C006", DEMO_DAY, "东校区", "合作档口", REDEEM, None, 640, None, None, None),
    # C007 设备时间 10:30，早于 POS-03 首次校时（11:00），缺前置校时挂起
    ("C007", DEMO_DAY, "西校区", "自营档口", REDEEM, None, None, 730, "POS-03", "2026-11-20T10:30:00+08:00"),
    ("C008", DEMO_DAY, "东校区", "合作档口", REDEEM, None, 680, 680, "POS-02", "2026-11-20T11:50:00+08:00"),
    # POS-02 时钟偏慢：设备 23:55，真实时间区间 23:59 ~ 次日 00:03，跨日挂起
    ("C009", DEMO_DAY, "东校区", "自营档口", REDEEM, None, 520, 520, "POS-02", "2026-11-20T23:55:00+08:00"),
    # C010 设备时间 19:30，晚于 POS-03 末次校时（18:00），缺后置校时挂起
    ("C010", DEMO_DAY, "西校区", "合作档口", REDEEM, None, None, 460, "POS-03", "2026-11-20T19:30:00+08:00"),
    ("R003", DEMO_DAY, "东校区", "合作档口", REVERSE, "C003", 800, 800, "POS-01", "2026-11-20T15:10:00+08:00"),
    ("P001", DEMO_DAY, "东校区", "自营档口", PARTIAL, "C001", 150, 150, "POS-01", "2026-11-20T15:25:00+08:00"),
    ("P002", DEMO_DAY, "西校区", "合作档口", PARTIAL, "C002", 100, 130, "POS-02", "2026-11-20T15:40:00+08:00"),
)


def demo_rows():
    rows = []
    for key, day, zone, group, kind, original, campus, canteen, device, device_time in _ENTRIES:
        for ledger, cents in ((CAMPUS, campus), (CANTEEN, canteen)):
            if cents is None:
                continue
            row = {
                "ledger": ledger, "transaction_key": key, "posting_date": day,
                "zone": "西校区" if key == "C008" and ledger == CANTEEN else zone,
                "merchant_group": group, "kind": kind, "original_key": original,
                "amount_cents": cents, "device_id": None, "device_time": None,
            }
            if ledger == CANTEEN:
                row["device_id"] = device
                row["device_time"] = device_time
            rows.append(row)
    return rows


def demo_calibrations():
    """校时记录（设备时间 → 标准时间）。POS-03 故意留空，演示缺依据挂起。"""
    return [
        # POS-01：略快，偏差 -300 / -360 秒，真实时间始终在同一自然日
        {"device_id": "POS-01", "device_time": "2026-11-19T08:00:00+08:00",
         "standard_time": "2026-11-19T07:55:00+08:00"},
        {"device_id": "POS-01", "device_time": "2026-11-19T20:00:00+08:00",
         "standard_time": "2026-11-19T19:54:00+08:00"},
        {"device_id": "POS-01", "device_time": "2026-11-20T08:00:00+08:00",
         "standard_time": "2026-11-20T07:55:00+08:00"},
        {"device_id": "POS-01", "device_time": "2026-11-20T20:00:00+08:00",
         "standard_time": "2026-11-20T19:54:00+08:00"},
        # POS-02：偏慢，偏差 +240 / +300 秒；C009（设备 23:55）夹出 23:59~次日 00:03
        {"device_id": "POS-02", "device_time": "2026-11-19T08:00:00+08:00",
         "standard_time": "2026-11-19T08:04:00+08:00"},
        {"device_id": "POS-02", "device_time": "2026-11-19T20:00:00+08:00",
         "standard_time": "2026-11-19T20:05:00+08:00"},
        {"device_id": "POS-02", "device_time": "2026-11-20T18:00:00+08:00",
         "standard_time": "2026-11-20T18:04:00+08:00"},
        {"device_id": "POS-02", "device_time": "2026-11-21T00:30:00+08:00",
         "standard_time": "2026-11-21T00:35:00+08:00"},
        # POS-03：仅有 11:00 与 18:00 两次校时。
        # C007（11:35 前无更早校时）缺前置；C010（19:30 后无更晚校时）缺后置。
        {"device_id": "POS-03", "device_time": "2026-11-20T11:00:00+08:00",
         "standard_time": "2026-11-20T11:02:00+08:00"},
        {"device_id": "POS-03", "device_time": "2026-11-20T18:00:00+08:00",
         "standard_time": "2026-11-20T18:03:00+08:00"},
    ]
