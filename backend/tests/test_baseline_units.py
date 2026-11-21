"""基线单位口径与偏离校验测试。

覆盖：带单位画像基线读取、存量数值/百分数兼容、多套阈值争议明细、
并发复算只确认一次异常、校验凭证还原基线版本，以及单位不一致时拒绝比较。
"""
from __future__ import annotations

import copy
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.baseline_registry import baseline_checks
from app.services.column_profile import ColumnProfileService
from app.services.dq_baseline import DqBaselineService
from app.services.dq_incident import DqIncidentService
from app.services.measures import MeasureError, parse_measure
from app.store import store

TABLE = "dwd_unit_test_null_rate"


@pytest.fixture(autouse=True)
def clean_registry():
    baseline_checks.reset()
    snapshot = copy.deepcopy(store._tables)
    yield
    baseline_checks.reset()
    store._tables = snapshot


def add_baseline(**overrides):
    rows = store.rows("dq_baseline")
    new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
    row = {
        "id": new_id,
        "基线编号": f"DQ_B-T{new_id:03d}",
        "目标表名": TABLE,
        "基线指标": "字段空值率",
        "基线上界": "12.00%",
        "基线下界": "2.00%",
        "基线单位": "%",
        "基线来源": "字段画像",
        "画像批次": f"CP-T{new_id:03d}",
        "基线版本": "v2",
        "基准日期": "2026-11-20",
        "status": "已生效",
        "pending": False,
        "abnormal": False,
    }
    row.update(overrides)
    rows.append(row)
    return row


class TestMeasureUnits:
    def test_percent_text_and_stock_number(self):
        assert parse_measure("12.00%", metric="字段空值率").value == 12.0
        assert parse_measure("12.00", metric="字段空值率").value == 12.0
        assert parse_measure(12, metric="字段空值率").unit == "%"

    def test_fraction_reads_as_percent(self):
        measure = parse_measure(0.15, unit="比例", metric="字段空值率")
        assert measure.value == 15.0
        assert measure.unit == "%"

    def test_raw_metric_not_read_as_percent(self):
        measure = parse_measure(8500, metric="row_count")
        assert measure.value == 8500
        assert measure.unit == "原始值"

    def test_unparseable_value_raises(self):
        with pytest.raises(MeasureError):
            parse_measure("待评估", metric="字段空值率")


class TestProfileBaselineComparison:
    def test_profile_baseline_with_unit_is_comparable(self):
        add_baseline()
        result = DqBaselineService().check_baseline_deviation(TABLE, "15%")
        assert result["校验结果"] == "异常"
        row = result["基线明细"][0]
        assert row["基线上界"] == "12.00%"
        assert row["当前读数"] == "15.00%"
        assert row["判定单位"] == "%"
        assert "%口径" in row["判定标准"]
        assert row["偏离幅度"] == "25.00%"

    def test_stock_number_read_matches_percent_read(self):
        add_baseline()
        svc = DqBaselineService()
        assert svc.check_baseline_deviation(TABLE, 15)["校验结果"] == "异常"
        assert svc.check_baseline_deviation(TABLE, 0.15, unit="比例")["校验结果"] == "异常"

    def test_manual_version_and_effective_conclusion_sources(self):
        add_baseline()
        add_baseline(**{
            "基线来源": "人工基线",
            "画像批次": "",
            "基线版本": "v1.0",
            "基线上界": "18",
            "基线下界": "1",
            "基线单位": "",
            "基准日期": "2026-11-01",
        })
        result = DqBaselineService().check_baseline_deviation(TABLE, "15%")
        assert result["校验结果"] == "异常"
        assert result["有效结论"]["基线来源"] == "字段画像"
        assert result["有效结论"]["基线版本"] == "v2"
        assert len(result["争议明细"]) == 1
        assert result["争议明细"][0]["基线来源"] == "人工基线"
        assert result["报告来源"]["有效结论"].startswith("字段画像")
        assert "人工基线" in result["报告来源"]["争议明细"]

    def test_metric_mismatch_not_mixed(self):
        add_baseline(**{"基线指标": "row_count", "基线上界": "9000",
                        "基线下界": "1000", "基线单位": ""})
        result = DqBaselineService().check_baseline_deviation(TABLE, "15%", metric="字段空值率")
        assert result["校验结果"] == "无有效基线"
        assert any("指标" in item["口径问题"] for item in result["无效基线"])

    def test_conflicting_units_rejected(self):
        add_baseline(**{"基线单位": "原始值"})  # 12.00% 与原始值口径冲突
        result = DqBaselineService().check_baseline_deviation(TABLE, "15%")
        assert result["校验结果"] == "无有效基线"
        assert any("冲突" in item["口径问题"] for item in result["无效基线"])


class TestCredentialReplay:
    def test_credential_restores_baseline_version(self):
        add_baseline()
        svc = DqBaselineService()
        result = svc.check_baseline_deviation(TABLE, "15%")
        credential = result["校验凭证"]

        # 之后新增一版画像基线，不应改变既有凭证的结论。
        add_baseline(**{
            "基线版本": "v3", "基线上界": "20.00%", "基线下界": "3.00%",
            "基准日期": "2026-11-21", "画像批次": "CP-T-v3",
        })

        replay = svc.replay_baseline_check(credential)
        assert replay["使用基线版本"] == "v2"
        assert replay["校验结果"] == "异常"
        assert replay["基线快照"]["基线上界"] == "12.00%"

    def test_profile_entry_and_incident_review_share_credential(self):
        add_baseline()
        profile = ColumnProfileService()
        result = profile.validate_null_rate(TABLE, "15%")
        credential = result["校验凭证"]
        incident_id = result["质量事件编号"]
        assert incident_id

        by_profile = profile.read_baseline_comparison(credential)
        by_incident = DqIncidentService().review_incident(incident_id)
        assert by_profile["基线快照"] == by_incident["基线快照"]
        assert by_profile["争议明细"] == by_incident["争议明细"]
        assert by_incident["事件核对"]["校验凭证"] == credential
        assert by_incident["事件核对"]["基线版本"] == "v2"


class TestConcurrentRecompute:
    def test_concurrent_recompute_confirms_one_incident(self):
        add_baseline()
        before = len(store.rows("dq_incident"))
        results = []

        def worker():
            results.append(
                DqBaselineService().check_baseline_deviation(TABLE, "15%"))

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(store.rows("dq_incident")) - before == 1
        assert {item["校验凭证"] for item in results} == {results[0]["校验凭证"]}
        assert {item["校验结果"] for item in results} == {"异常"}
