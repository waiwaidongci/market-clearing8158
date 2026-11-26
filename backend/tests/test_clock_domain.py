"""离线时钟漂移与营业日归属的纯标准库回归测试。

运行（无需第三方依赖，隔离模式避免本地注入模块）：

    python3 -I backend/tests/test_clock_domain.py

覆盖：同日归属、跨日挂起、缺前/后校时挂起、无校时设备、校园卡账沿用原日期、
乱序补录只重算受影响营业日、跨日改归属两天一起重算、重复/冲突校时处理。
"""

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# 以包方式导入真实源码，避免依赖任何已安装的第三方库
import importlib  # noqa: E402

_spec = importlib.import_module("src.domain.spec")
_clock = importlib.import_module("src.domain.clock")
_demo = importlib.import_module("src.domain.demo")
_analysis = importlib.import_module("src.domain.analysis")

CANTEEN = _spec.CANTEEN
CAMPUS = _spec.CAMPUS
ATTRIBUTED = _clock.ATTRIBUTED
PENDING = _clock.PENDING
BJ = timezone(timedelta(hours=8))


def cal(device, device_dt, standard_dt):
    return {"device_id": device,
            "device_time": device_dt.isoformat(timespec="seconds"),
            "standard_time": standard_dt.isoformat(timespec="seconds")}


def dt(hour, minute=0, day=20):
    return datetime(2026, 11, day, hour, minute, tzinfo=BJ)


class ClockEngineTests(unittest.TestCase):
    def setUp(self):
        # POS-01 略快（偏差为负）；POS-02 偏慢（偏差为正）
        self.calibrations = [
            cal("POS-01", dt(18, 19), dt(17, 55, 19)),
            cal("POS-01", dt(8), dt(7, 55)),
            cal("POS-01", dt(20), dt(19, 54)),
            cal("POS-02", dt(18), dt(18, 4)),
            cal("POS-02", dt(0, 30, 21), dt(0, 35, 21)),
        ]
        self.timelines = _clock.build_timelines(self.calibrations)

    def canteen_row(self, key, device, stamp):
        return {"ledger": CANTEEN, "transaction_key": key, "device_id": device,
                "posting_date": "2026-11-20", "device_time": stamp.isoformat(timespec="seconds")}

    def test_same_day_attribution(self):
        row = self.canteen_row("T1", "POS-01", dt(20))
        result = _clock.attribute_row(row, self.timelines)
        self.assertEqual(result["status"], ATTRIBUTED)
        self.assertEqual(result["business_day"], "2026-11-20")
        self.assertTrue(result["range_start"] <= result["range_end"])
        self.assertIn("偏差", result["basis"])

    def test_cross_day_is_pending(self):
        # 设备 23:55，POS-02 偏差 +240/+300 秒 → 真实 23:59 ~ 次日 00:00 跨日
        row = self.canteen_row("T2", "POS-02", dt(23, 55))
        result = _clock.attribute_row(row, self.timelines)
        self.assertEqual(result["status"], PENDING)
        self.assertEqual(result["basis"].split("；")[0], _clock.REASON_CROSS_DAY_LABEL)
        self.assertIn("跨营业日", result["pending_reason"])

    def test_missing_before_and_after(self):
        before = self.canteen_row("T3", "POS-02", dt(10))
        self.assertEqual(_clock.attribute_row(before, self.timelines)["status"], PENDING)
        after = self.canteen_row("T4", "POS-02", dt(2, 21))
        result = _clock.attribute_row(after, self.timelines)
        self.assertEqual(result["status"], PENDING)
        self.assertEqual(result["basis"], _clock.REASON_NO_CALIBRATION)

    def test_unknown_device_pending(self):
        row = self.canteen_row("T5", "POS-99", dt(12))
        result = _clock.attribute_row(row, self.timelines)
        self.assertEqual(result["status"], PENDING)
        self.assertEqual(result["basis"], _clock.REASON_NO_CALIBRATION)

    def test_campus_ledger_keeps_original_day(self):
        row = {"ledger": CAMPUS, "transaction_key": "T6", "posting_date": "2026-11-20"}
        result = _clock.attribute_row(row, self.timelines)
        self.assertEqual(result["status"], ATTRIBUTED)
        self.assertEqual(result["business_day"], "2026-11-20")

    def test_out_of_order_supplement_only_affects_changed_day(self):
        rows = [self.canteen_row("T7", "POS-03", dt(12))]
        previous, _ = _clock.attribute_all(rows, [cal("POS-03", dt(18), dt(18, 2))])
        self.assertEqual(previous[0]["status"], PENDING)
        supplemented = [cal("POS-03", dt(18), dt(18, 2)), cal("POS-03", dt(6), dt(6, 1))]
        current, _ = _clock.attribute_all(rows, supplemented)
        self.assertEqual(current[0]["status"], ATTRIBUTED)
        self.assertEqual(_clock.affected_business_days(previous, current), ["2026-11-20"])

    def test_cross_day_resolution_touches_both_candidate_days(self):
        # 设备时间在 11-20 00:10（设备记账日 20），但真实营业日可能落在 19 或 20。
        rows = [self.canteen_row("T8", "POS-04", dt(0, 10))]
        # 宽偏差：前校时 +50 分、后校时 -30 分 → 真实区间 19 日 23:40 ~ 20 日 01:00，跨日挂起
        wide = [cal("POS-04", dt(23, 19), dt(23, 50, 19)),
                cal("POS-04", dt(1, 20), dt(0, 30, 20))]
        previous, _ = _clock.attribute_all(rows, wide)
        self.assertEqual(previous[0]["status"], PENDING)
        # 补录更贴近的校时：偏差均为 -20 分 → 设备 00:10 夹出真实 19 日 23:50，整体落在 19 日
        tight = [cal("POS-04", dt(23, 30, 19), dt(23, 10, 19)),
                 cal("POS-04", dt(1, 20), dt(0, 40, 20))]
        current, _ = _clock.attribute_all(rows, tight)
        self.assertEqual(current[0]["status"], ATTRIBUTED)
        self.assertEqual(current[0]["business_day"], "2026-11-19")
        # 跨日改归属：设备记账日 20 与新营业日 19 必须一起进入重算范围
        self.assertEqual(
            _clock.affected_business_days(previous, current),
            ["2026-11-19", "2026-11-20"])

    def test_duplicate_calibration_idempotent_and_conflict_rejected(self):
        one = _clock.build_timelines([cal("P", dt(10), dt(10, 1)), cal("P", dt(10), dt(10, 1))])
        self.assertEqual(len(one["P"]), 1)
        with self.assertRaises(ValueError):
            _clock.build_timelines([cal("P", dt(10), dt(10, 1)), cal("P", dt(10), dt(10, 9))])

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            _clock.validate_calibration({"device_id": "P", "device_time": "2026-11-20T10:00:00",
                                         "standard_time": "2026-11-20T10:01:00+08:00"})


class DemoAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.rows = _demo.demo_rows()
        self.calibrations = _demo.demo_calibrations()

    def test_demo_pending_set(self):
        report = _analysis.analyze(self.rows, {"posting_date": "2026-11-20"}, self.calibrations)
        self.assertEqual({item["transaction_key"] for item in report["pending"]["items"]},
                         {"C007", "C009", "C010"})
        self.assertEqual(report["pending"]["total"], 3)

    def test_demo_day_blocks_and_prior_day_passes(self):
        blocked = _analysis.analyze(self.rows, {"posting_date": "2026-11-20"}, self.calibrations)
        gate = {row["check"]: row["status"] for row in blocked["tables"][0]["rows"]}
        self.assertEqual(gate["时钟归属"], "阻断")
        self.assertEqual(gate["结算放行"], "阻断")

        passed = _analysis.analyze(self.rows, {"posting_date": "2026-11-19"}, self.calibrations)
        prior_gate = {row["check"]: row["status"] for row in passed["tables"][0]["rows"]}
        self.assertEqual(prior_gate["结算放行"], "通过")
        metrics = {item["label"]: item["value"] for item in passed["metrics"]}
        self.assertEqual(metrics["校园券账净额（分）"], 2900)
        self.assertEqual(metrics["食堂核销账净额（分）"], 2900)

    def test_pending_excluded_from_canteen_ledger(self):
        report = _analysis.analyze(self.rows, {"posting_date": "2026-11-20"}, self.calibrations)
        drilldown = report["tables"][1]["rows"]
        keys = {row["transaction_key"] for row in drilldown}
        self.assertNotIn("C007", keys)   # 食堂单边且挂起 → 整体剔除
        self.assertNotIn("C010", keys)
        self.assertIn("C009", keys)      # 校园侧仍在，食堂侧挂起 → 显示食堂缺失
        attribution = next(table for table in report["tables"] if table["title"] == "食堂核销营业日归属")
        self.assertEqual(attribution["rows"][0]["status"], PENDING)

    def test_no_calibration_suspends_all_canteen_rows(self):
        report = _analysis.analyze(self.rows, {"posting_date": "2026-11-20"}, [])
        canteen_total = len([row for row in self.rows if row["ledger"] == CANTEEN])
        self.assertEqual(report["pending"]["total"], canteen_total)
        metrics = {item["label"]: item["value"] for item in report["metrics"]}
        self.assertEqual(metrics["食堂核销账净额（分）"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
