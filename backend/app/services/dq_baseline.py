"""质量基线管理服务：管理数据质量统计基线，校验字段画像和监控指标。

domain_chain: 质量基线 (dq_baseline)
  └─ 校验 → 指标监控 (metric_monitor)
  └─ 关联 → 字段画像 (column_profile)

偏离校验统一走 :mod:`app.services.measures`：基线上界/下界/当前读数都先换算成
``(数值, 单位)`` 再比较，支持 ``12.00%`` 这种带单位写法和老基线里的存量数值。
同一张表同时有多套有效阈值时，有画像批次的画像基线作为有效结论来源，
其余单位可辨认的基线进入争议明细，指标不一致的直接排除，绝不混用。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.baseline_registry import baseline_checks, utc_now
from app.services.measures import (
    Measure,
    MeasureError,
    canonical_metric,
    format_measure,
    parse_measure,
    same_metric,
)
from app.store import store

# 偏离幅度超过该比例（百分数口径）判定为异常。
DEVIATION_THRESHOLD_PCT = 20.0


class DqBaselineService(BaseModuleService):
    MODULE = "dq_baseline"
    ENTITY = "基线定义"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["基线编号", "目标表名", "基线指标", "基线上界", "基线下界", "计算周期", "基准日期", "基线版本"]
    REQUIRED_FIELDS = ["基线编号", "目标表名", "基线指标"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已过期"]
    ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "标记过期": "已过期"}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------
    # 基线计算
    # ------------------------------------------------------------------
    def calculate_baseline_from_history(self, table_name: str, metric_name: str,
                                         historical_values: list[float] | None = None) -> dict[str, Any]:
        """从历史数据计算统计基线：处理历史值得到上下界。

        导入历史监控指标数据，清洗异常值后计算均值和标准差，
        生成统计基线边界并校验基线合理性，写入基线存储。
        基线单位跟随指标口径写清楚，避免下游把百分数和计数混在一起。
        """
        if historical_values is None:
            historical_values = [random.gauss(5000, 800) for _ in range(30)]

        # 清洗数据中的异常值
        mean_val = sum(historical_values) / len(historical_values)
        std_val = (sum((x - mean_val) ** 2 for x in historical_values) / len(historical_values)) ** 0.5
        cleaned = [v for v in historical_values if abs(v - mean_val) <= 2 * std_val]

        cleaned_mean = sum(cleaned) / len(cleaned)
        cleaned_std = (sum((x - cleaned_mean) ** 2 for x in cleaned) / len(cleaned)) ** 0.5

        upper = cleaned_mean + 2 * cleaned_std
        lower = max(0, cleaned_mean - 2 * cleaned_std)

        # 百分比类指标统一落成百分数口径，存量数值按原始值保存。
        metric = canonical_metric(metric_name) or metric_name
        try:
            upper_measure = parse_measure(upper, metric=metric, field="基线上界")
            lower_measure = parse_measure(lower, metric=metric, field="基线下界")
        except MeasureError:
            upper_measure = Measure(upper, "原始值", format_measure(upper, "原始值"))
            lower_measure = Measure(lower, "原始值", format_measure(lower, "原始值"))

        # 导入基线存储
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        baseline = {
            "id": new_id,
            "基线编号": f"DQ_B-{new_id:04d}",
            "目标表名": table_name,
            "基线指标": metric,
            "基线上界": upper_measure.display,
            "基线下界": lower_measure.display,
            "基线单位": upper_measure.unit,
            "基线来源": "人工基线",
            "画像批次": "",
            "计算周期": "每周",
            "基准日期": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "基线版本": "v1.0",
            "status": "已生效",
            "pending": False,
            "abnormal": False,
        }
        rows.append(baseline)

        return {
            "基线编号": baseline["基线编号"],
            "基线指标": metric,
            "基线单位": upper_measure.unit,
            "清洗前样本数": len(historical_values),
            "清洗后样本数": len(cleaned),
            "均值": round(cleaned_mean, 4),
            "标准差": round(cleaned_std, 4),
            "上界": round(upper, 4),
            "下界": round(lower, 4),
            "基线上界": upper_measure.display,
            "基线下界": lower_measure.display,
            "变异系数": f"{cleaned_std / cleaned_mean * 100:.2f}%" if cleaned_mean > 0 else "N/A",
        }

    # ------------------------------------------------------------------
    # 基线候选与单位换算
    # ------------------------------------------------------------------
    def _source_of(self, baseline: dict[str, Any]) -> str:
        source = str(baseline.get("基线来源") or "").strip()
        if source:
            return source
        if baseline.get("画像批次") or baseline.get("画像编号"):
            return "字段画像"
        return "人工基线"

    def _batch_of(self, baseline: dict[str, Any]) -> str:
        return str(
            baseline.get("画像批次")
            or baseline.get("批次编号")
            or baseline.get("画像编号")
            or ""
        ).strip()

    def _priority_key(self, baseline: dict[str, Any]) -> tuple:
        """有效结论优先级：有画像批次的画像基线 > 带批次基线 > 画像基线 > 人工基线。

        同档内取更新的基准日期，再以 id 兜底，保证结论稳定可复现。
        """
        source = self._source_of(baseline)
        has_batch = 1 if self._batch_of(baseline) else 0
        is_profile = 1 if source == "字段画像" else 0
        return (
            is_profile and has_batch,
            has_batch,
            is_profile,
            str(baseline.get("基准日期") or ""),
            int(baseline.get("id", 0)),
        )

    def _measure_baseline(
        self, baseline: dict[str, Any], field: str
    ) -> tuple[Measure, Measure]:
        unit = (
            baseline.get("基线单位")
            or baseline.get("上界单位")
            or baseline.get("读数单位")
            or ""
        )
        metric = baseline.get("基线指标")
        upper = parse_measure(
            baseline.get("基线上界"), unit=unit, metric=metric, field=f"{field}上界")
        lower_unit = baseline.get("下界单位") or unit
        lower = parse_measure(
            baseline.get("基线下界"), unit=lower_unit, metric=metric, field=f"{field}下界")
        if upper.unit != lower.unit:
            raise MeasureError(
                f"{field}上下界单位不一致：上界 {upper.unit}，下界 {lower.unit}"
            )
        return upper, lower

    def _compare(self, current: Measure, upper: Measure, lower: Measure) -> tuple[float, bool, str]:
        """在同一单位下比较读数与上下界，返回 (偏离百分比, 是否异常, 判定说明)。"""
        if current.unit != upper.unit:
            raise MeasureError(
                f"读数单位「{current.unit}」与基线单位「{upper.unit}」不一致，不能直接比较"
            )
        if current.value > upper.value:
            deviation = ((current.value - upper.value) / upper.value * 100) if upper.value > 0 else 0.0
            relation = f"高于上界 {format_measure(upper.value, upper.unit)}"
        elif current.value < lower.value:
            deviation = ((lower.value - current.value) / lower.value * 100) if lower.value > 0 else 0.0
            relation = f"低于下界 {format_measure(lower.value, lower.unit)}"
        else:
            deviation = 0.0
            relation = (
                f"落在 [{format_measure(lower.value, lower.unit)}, "
                f"{format_measure(upper.value, upper.unit)}] 内"
            )
        is_abnormal = abs(deviation) > DEVIATION_THRESHOLD_PCT
        verdict = (
            f"按{current.unit}口径比较：读数 {current.display} {relation}，"
            f"偏离 {deviation:.2f}%（阈值 {DEVIATION_THRESHOLD_PCT:.0f}%），"
            f"判定{'异常' if is_abnormal else '正常'}"
        )
        return deviation, is_abnormal, verdict

    def _collect_candidates(
        self, table_name: str, metric: str | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """筛出该表所有有效基线，解析不了的单独记口径问题，不中断校验。"""
        candidates: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        for baseline in store.rows(self.MODULE):
            if baseline.get("目标表名") != table_name:
                continue
            if baseline.get("status") != "已生效":
                continue
            item = {
                "baseline": baseline,
                "metric": canonical_metric(baseline.get("基线指标")) or baseline.get("基线指标"),
                "source": self._source_of(baseline),
                "batch": self._batch_of(baseline),
            }
            if metric and not same_metric(baseline.get("基线指标"), metric):
                invalid.append(self._invalid_entry(
                    item,
                    f"指标为「{baseline.get('基线指标')}」，与本次核对的「{metric}」不一致，未参与比较",
                ))
                continue
            try:
                upper, lower = self._measure_baseline(baseline, f"基线{baseline.get('基线编号')}")
            except MeasureError as exc:
                invalid.append(self._invalid_entry(item, str(exc)))
                continue
            item.update({"upper": upper, "lower": lower})
            candidates.append(item)
        return candidates, invalid

    def _invalid_entry(self, item: dict[str, Any], reason: str) -> dict[str, Any]:
        baseline = item["baseline"]
        return {
            "基线编号": baseline.get("基线编号"),
            "基线版本": baseline.get("基线版本"),
            "基线指标": baseline.get("基线指标"),
            "基线来源": item["source"],
            "画像批次": item["batch"],
            "口径问题": reason,
            "可用": False,
        }

    def _choose_metric(self, candidates: list[dict[str, Any]], metric: str | None) -> str | None:
        if metric:
            return canonical_metric(metric) or metric
        if not candidates:
            return None
        authoritative = max(candidates, key=lambda item: self._priority_key(item["baseline"]))
        return authoritative["metric"]

    def _signature(
        self, table_name: str, metric: str, current: Measure, candidates: list[dict[str, Any]]
    ) -> str:
        baseline_part = ";".join(sorted(
            f"{item['baseline'].get('id')}:{item['upper'].display}:"
            f"{item['lower'].display}:{item['baseline'].get('基线版本')}"
            for item in candidates
        ))
        return (
            f"{table_name}|{metric}|{current.value:.6f}|{current.unit}|"
            f"{DEVIATION_THRESHOLD_PCT}|{baseline_part}"
        )

    # ------------------------------------------------------------------
    # 偏离校验
    # ------------------------------------------------------------------
    def check_baseline_deviation(
        self,
        table_name: str,
        current_value: Any,
        unit: str | None = None,
        metric: str | None = None,
    ) -> dict[str, Any]:
        """校验当前值是否偏离统计基线。

        查询目标表的有效基线定义，把当前读数和基线上/下界换算到同一单位后比较，
        超过阈值标记异常并把比较结果回写质量事件。每次校验生成校验凭证，
        凭证里冻结当次使用的基线快照，供字段画像入口和事件复核面板回查。
        """
        candidates, invalid = self._collect_candidates(table_name, metric)
        effective_metric = self._choose_metric(candidates, metric)

        if not candidates:
            return {
                "目标表名": table_name,
                "基线指标": effective_metric,
                "当前值": current_value,
                "校验结果": "无有效基线",
                "口径问题": "没有单位可辨认且指标一致的有效基线",
                "无效基线": invalid,
                "基线明细": [],
                "争议明细": [],
                "有效结论": None,
            }

        # 指标不一致的候选不参与比较，也不允许把行数当作百分数。
        aligned: list[dict[str, Any]] = []
        for item in candidates:
            if effective_metric and not same_metric(item["metric"], effective_metric):
                invalid.append(self._invalid_entry(
                    item,
                    f"同表存在多套指标口径，本次按「{effective_metric}」核对，"
                    f"「{item['metric']}」未参与比较",
                ))
            else:
                aligned.append(item)
        candidates = aligned

        try:
            current = parse_measure(
                current_value, unit=unit, metric=effective_metric, field="当前读数")
        except MeasureError as exc:
            return {
                "目标表名": table_name,
                "基线指标": effective_metric,
                "当前值": current_value,
                "校验结果": "口径错误",
                "口径问题": str(exc),
                "无效基线": invalid,
                "基线明细": [],
                "争议明细": [],
                "有效结论": None,
            }

        details: list[dict[str, Any]] = []
        for item in candidates:
            baseline = item["baseline"]
            try:
                deviation, is_abnormal, verdict = self._compare(
                    current, item["upper"], item["lower"])
            except MeasureError as exc:
                invalid.append(self._invalid_entry(item, str(exc)))
                continue
            details.append({
                "基线编号": baseline.get("基线编号"),
                "基线版本": baseline.get("基线版本"),
                "基线指标": baseline.get("基线指标"),
                "基线来源": item["source"],
                "画像批次": item["batch"],
                "基线上界": item["upper"].display,
                "基线下界": item["lower"].display,
                "基线上界数值": item["upper"].value,
                "基线下界数值": item["lower"].value,
                "基线单位": item["upper"].unit,
                "当前读数": current.display,
                "读数单位": current.unit,
                "判定单位": item["upper"].unit,
                "判定标准": (
                    f"{item['upper'].unit}口径：[{item['lower'].display}, "
                    f"{item['upper'].display}]，偏离超过 {DEVIATION_THRESHOLD_PCT:.0f}% 判异常"
                ),
                "偏离幅度": f"{deviation:.2f}%",
                "是否异常": is_abnormal,
                "判定说明": verdict,
                "_priority": self._priority_key(baseline),
            })

        if not details:
            return {
                "目标表名": table_name,
                "基线指标": effective_metric,
                "当前值": current_value,
                "当前读数": current.display,
                "校验结果": "无有效基线",
                "口径问题": "候选基线与读数单位均不兼容",
                "无效基线": invalid,
                "基线明细": [],
                "争议明细": [],
                "有效结论": None,
            }

        details.sort(key=lambda item: item["_priority"], reverse=True)
        used = details[0]
        effective_abnormal = used["是否异常"]

        # 同表其它有效基线：结论或阈值口径不同即进入争议明细。
        disputes = []
        for other in details[1:]:
            same_verdict = other["是否异常"] == effective_abnormal
            same_threshold = (
                other["基线上界数值"] == used["基线上界数值"]
                and other["基线下界数值"] == used["基线下界数值"]
            )
            if same_verdict and same_threshold:
                continue
            disputes.append({
                "基线编号": other["基线编号"],
                "基线版本": other["基线版本"],
                "基线指标": other["基线指标"],
                "基线来源": other["基线来源"],
                "画像批次": other["画像批次"],
                "基线上界": other["基线上界"],
                "基线下界": other["基线下界"],
                "基线单位": other["基线单位"],
                "当前读数": other["当前读数"],
                "偏离幅度": other["偏离幅度"],
                "结论": "异常" if other["是否异常"] else "正常",
                "与有效结论一致": same_verdict,
                "争议原因": (
                    "同表同指标存在多套有效阈值，"
                    f"{other['基线来源']} {other['基线编号']}({other['基线版本']})"
                    f"判定为{'异常' if other['是否异常'] else '正常'}，"
                    f"与有效结论{'一致' if same_verdict else '不一致'}；"
                    f"有效结论以画像批次基线 {used['基线编号']}({used['基线版本']}) 为准"
                ),
            })

        for item in details:
            item.pop("_priority", None)

        source_text = (
            f"{used['基线来源']} {used['基线编号']}（{used['基线版本']}"
            + (f"，画像批次 {used['画像批次']}" if used["画像批次"] else "")
            + "）"
        )
        report_sources = {
            "有效结论": source_text,
            "争议明细": "；".join(
                f"{d['基线来源']} {d['基线编号']}（{d['基线版本']}）"
                for d in disputes
            ) or "无争议基线",
        }

        signature = self._signature(table_name, effective_metric, current, candidates)
        with baseline_checks.lock:
            existing_credential = baseline_checks.signature_owner(signature)
            if existing_credential:
                existing = baseline_checks.get(existing_credential) or {}
                existing["复算命中"] = True
                return existing

            credential = baseline_checks.next_credential()
            incident_id = None
            if effective_abnormal:
                incident_id = self._write_baseline_incident(
                    table_name=table_name,
                    metric=effective_metric,
                    current=current,
                    used=used,
                    disputes=disputes,
                    credential=credential,
                )

            check = {
                "校验凭证": credential,
                "校验时间": utc_now(),
                "目标表名": table_name,
                "基线指标": effective_metric,
                "当前读数": current.display,
                "当前值": current.value,
                "读数单位": current.unit,
                "校验结果": "异常" if effective_abnormal else "正常",
                "有效结论": {
                    "结论": "异常" if effective_abnormal else "正常",
                    "基线编号": used["基线编号"],
                    "基线版本": used["基线版本"],
                    "基线来源": used["基线来源"],
                    "画像批次": used["画像批次"],
                    "基线上界": used["基线上界"],
                    "基线下界": used["基线下界"],
                    "基线单位": used["基线单位"],
                    "偏离幅度": used["偏离幅度"],
                    "判定标准": used["判定标准"],
                    "结论来源": source_text,
                },
                "最大偏离": used["偏离幅度"],
                "基线版本": used["基线版本"],
                "使用基线": {
                    "基线编号": used["基线编号"],
                    "基线版本": used["基线版本"],
                    "基线来源": used["基线来源"],
                    "画像批次": used["画像批次"],
                    "基线上界": used["基线上界"],
                    "基线下界": used["基线下界"],
                },
                "基线快照": self._freeze_baseline(used),
                "基线明细": details,
                "争议明细": disputes,
                "无效基线": invalid,
                "报告来源": report_sources,
                "质量事件编号": incident_id,
                "重复校验": False,
            }
            baseline_checks.save(signature, check)
            return baseline_checks.get(credential) or check

    def _freeze_baseline(self, used: dict[str, Any]) -> dict[str, Any]:
        """冻结当次校验使用的基线，重取画像时按凭证还原这一版。"""
        return {
            "基线编号": used["基线编号"],
            "基线版本": used["基线版本"],
            "基线指标": used["基线指标"],
            "基线来源": used["基线来源"],
            "画像批次": used["画像批次"],
            "基线上界": used["基线上界"],
            "基线下界": used["基线下界"],
            "基线单位": used["基线单位"],
            "判定标准": used["判定标准"],
            "当前读数": used["当前读数"],
            "偏离幅度": used["偏离幅度"],
            "结论": "异常" if used["是否异常"] else "正常",
        }

    def _write_baseline_incident(
        self,
        *,
        table_name: str,
        metric: str,
        current: Measure,
        used: dict[str, Any],
        disputes: list[dict[str, Any]],
        credential: str,
    ) -> str:
        """把基线比较结果回写质量事件清单，事件上带校验凭证和基线版本。"""
        incident_rows = store.rows("dq_incident")
        new_iid = max((int(r.get("id", 0)) for r in incident_rows), default=0) + 1
        incident_id = f"DQ_I-{new_iid:04d}"
        incident_rows.append({
            "id": new_iid,
            "事件编号": incident_id,
            "关联规则": f"baseline:{table_name}:{metric}",
            "触发时间": utc_now(),
            "偏离程度": used["偏离幅度"],
            "当前读数": current.display,
            "基线编号": used["基线编号"],
            "基线版本": used["基线版本"],
            "基线来源": used["基线来源"],
            "画像批次": used["画像批次"],
            "基线指标": metric,
            "校验凭证": credential,
            "判定标准": used["判定标准"],
            "争议基线": len(disputes),
            "影响行数": "待评估",
            "严重级别": "warning",
            "处理状态": "基线异常",
            "处理人": "自动校验",
            "status": "待确认",
            "pending": True,
            "abnormal": True,
        })
        return incident_id

    # ------------------------------------------------------------------
    # 校验凭证回查
    # ------------------------------------------------------------------
    def replay_baseline_check(self, credential: str) -> dict[str, Any] | None:
        """按校验凭证还原当次校验：返回冻结的基线快照，不受之后基线变更影响。"""
        check = baseline_checks.by_credential_or_incident(str(credential or "").strip())
        if not check:
            return None
        return {
            "校验凭证": check.get("校验凭证"),
            "质量事件编号": check.get("质量事件编号"),
            "目标表名": check.get("目标表名"),
            "基线指标": check.get("基线指标"),
            "当前读数": check.get("当前读数"),
            "校验结果": check.get("校验结果"),
            "使用基线版本": check.get("基线版本"),
            "基线快照": check.get("基线快照"),
            "有效结论": check.get("有效结论"),
            "基线明细": check.get("基线明细"),
            "争议明细": check.get("争议明细"),
            "报告来源": check.get("报告来源"),
        }

    def list_check_records(
        self,
        table_name: str | None = None,
        metric: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return baseline_checks.list_checks(
            table_name=table_name, metric=metric, limit=limit)

    def domain_snapshot(self) -> dict[str, Any]:
        snapshot = super().domain_snapshot()
        snapshot["operation"] = "校验"
        snapshot["desc"] = "从历史数据计算统计基线并在统一单位下校验偏离"
        snapshot["artifact"] = "质量基线记录集"
        snapshot["artifact_desc"] = "经单位对齐的统计基线和偏离分析记录集"
        return snapshot
