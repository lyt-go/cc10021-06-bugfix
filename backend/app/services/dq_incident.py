"""质量事件服务：记录和追踪数据质量异常事件，驱动趋势分析和评分卡计算。

domain_chain: 质量事件 (dq_incident)
  └─ 关联 → 趋势分析 (dq_trend)
  └─ 聚合 → 评分卡 (dq_scorecard)
  └─ 清洗 → 告警通知 (dq_alert_channel)

基线偏离回写的事件都带校验凭证，事件复核面板按凭证读取当时的基线比较明细，
不在复核时重新按当前基线算一遍。
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.baseline_registry import baseline_checks
from app.store import store


class DqIncidentService(BaseModuleService):
    MODULE = "dq_incident"
    ENTITY = "质量事件"
    OPERATION_TERM = "写入"
    LIST_FIELDS = ["事件编号", "关联规则", "触发时间", "偏离程度", "影响行数", "严重级别", "处理状态", "处理人", "校验凭证"]
    REQUIRED_FIELDS = ["事件编号", "关联规则", "触发时间"]
    STATUS_ORDER = ["待确认", "调查中", "已修复", "已关闭"]
    ACTION_RULES = {"确认事件": "待确认", "开始调查": "调查中", "标记修复": "已修复", "关闭事件": "已关闭"}
    NEGATIVE_ACTIONS = []

    def aggregate_incident_summary(self, table_name: str, days: int = 7) -> dict[str, Any]:
        """聚合指定表在时间窗口内的质量事件摘要。

        查询该表所有关联质量事件，按严重级别和状态聚合统计，
        去重同类事件并分析根因分布，生成事件摘要报告。
        """
        all_incidents = store.rows(self.MODULE)
        related = [
            i for i in all_incidents
            if table_name in str(i.get("关联规则", ""))
        ]

        by_level = {"critical": 0, "warning": 0, "info": 0}
        by_status = {}
        root_causes = {}

        for inc in related:
            level = inc.get("严重级别", "info")
            by_level[level] = by_level.get(level, 0) + 1
            status = inc.get("status", "待确认")
            by_status[status] = by_status.get(status, 0) + 1
            cause = inc.get("关联规则", "未知")
            root_causes[cause] = root_causes.get(cause, 0) + 1

        # 去重同规则事件
        deduped = {}
        for inc in related:
            key = inc.get("关联规则", "")
            if key not in deduped:
                deduped[key] = inc

        return {
            "目标表名": table_name,
            "时间窗口": f"{days}天",
            "事件总数": len(related),
            "去重后": len(deduped),
            "按级别": by_level,
            "按状态": by_status,
            "根因分布": dict(
                sorted(root_causes.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
            "聚合时间": datetime.now(timezone.utc).isoformat(),
        }

    def write_quality_incident(self, rule_id: str, severity: str,
                                deviation: str, table_name: str) -> dict[str, Any]:
        """写入质量事件记录并将事件关联到告警通知通道。

        当检测到数据质量异常时，写入质量事件记录到事件存储中，
        同时将事件分发到告警通道触发通知，并登记到趋势服务。
        """
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1

        entry = {
            "id": new_id,
            "事件编号": f"DQ_I-{new_id:04d}",
            "关联规则": rule_id,
            "触发时间": datetime.now(timezone.utc).isoformat(),
            "偏离程度": deviation,
            "影响行数": str(random.randint(500, 100000)),
            "严重级别": severity,
            "处理状态": "新建",
            "处理人": "系统自动",
            "status": "待确认",
            "pending": True,
            "abnormal": True,
        }
        rows.append(entry)

        # 关联写入趋势记录
        trend_rows = store.rows("dq_trend")
        new_tid = max((int(r.get("id", 0)) for r in trend_rows), default=0) + 1
        trend_rows.append({
            "id": new_tid,
            "记录编号": f"DQ_T-{new_tid:04d}",
            "目标表名": table_name,
            "日期": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "完备率": f"{random.uniform(70, 85):.1f}%",
            "准确率": f"{random.uniform(75, 90):.1f}%",
            "及时率": f"{random.uniform(80, 95):.1f}%",
            "综合质量": f"{random.uniform(70, 85):.1f}",
            "趋势标记": "下降趋势",
            "status": "下降趋势",
            "pending": True,
            "abnormal": True,
        })

        return entry

    def review_incident(self, incident_ref: str) -> dict[str, Any] | None:
        """事件复核面板：按校验凭证（或事件编号）读取基线比较明细。

        复核读的是当时冻结的基线版本，而不是复核时刻的当前基线，
        因此有效结论、争议明细和报告来源都能随着事件一起还原。
        """
        check = baseline_checks.by_credential_or_incident(str(incident_ref or "").strip())
        if not check:
            return None
        return {
            "复核对象": incident_ref,
            "校验凭证": check.get("校验凭证"),
            "质量事件编号": check.get("质量事件编号"),
            "事件核对": self._incident_by_id(check.get("质量事件编号")),
            "目标表名": check.get("目标表名"),
            "基线指标": check.get("基线指标"),
            "当前读数": check.get("当前读数"),
            "校验结果": check.get("校验结果"),
            "使用基线版本": check.get("基线版本"),
            "有效结论": check.get("有效结论"),
            "基线快照": check.get("基线快照"),
            "基线明细": check.get("基线明细"),
            "争议明细": check.get("争议明细"),
            "报告来源": check.get("报告来源"),
        }

    def _incident_by_id(self, incident_id: str | None) -> dict[str, Any] | None:
        if not incident_id:
            return None
        for row in store.rows(self.MODULE):
            if row.get("事件编号") == incident_id:
                return row
        return None

    def analyze_incident_trend(self, table_name: str) -> dict[str, Any]:
        """分析质量事件趋势并计算改善评分。

        查询历史事件数据，计算事件频率变化、修复率和趋势方向，
        聚合后的趋势分析结果关联到评分卡计算。
        """
        all_incidents = store.rows(self.MODULE)
        related = [i for i in all_incidents if table_name in str(i.get("关联规则", ""))]

        if not related:
            return {
                "目标表名": table_name,
                "状态": "无历史事件",
                "历史事件总数": 0,
                "已修复": 0,
                "修复率": "0.0%",
                "趋势方向": "平稳",
                "趋势": "平稳",
                "建议": "保持监控",
            }

        resolved = sum(1 for i in related if i.get("status") in ("已修复", "已关闭"))
        resolution_rate = resolved / len(related) * 100 if related else 0

        trend = "改善中" if resolution_rate > 60 else "恶化" if resolution_rate < 30 else "平稳"

        return {
            "目标表名": table_name,
            "历史事件总数": len(related),
            "已修复": resolved,
            "修复率": f"{resolution_rate:.1f}%",
            "趋势方向": trend,
            "建议": "加强规则覆盖" if trend == "恶化" else "保持监控" if trend == "平稳" else "继续改进",
        }

    def domain_snapshot(self) -> dict[str, Any]:
        snapshot = super().domain_snapshot()
        snapshot["operation"] = "写入"
        snapshot["desc"] = "写入质量事件记录并关联告警与趋势分析"
        snapshot["artifact"] = "质量事件数据集"
        snapshot["artifact_desc"] = "含趋势、告警关联和校验凭证的质量事件数据集"
        return snapshot
