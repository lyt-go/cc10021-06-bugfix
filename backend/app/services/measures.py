"""指标读数与阈值口径。

偏离校验最容易出错的地方不是算法，而是单位：字段画像写的是 ``12.00%``，
人工基线可能只写存量数值 ``12``，监控指标又可能是行数 ``8500``。
本模块把读数和阈值统一换算成同一种单位，换算不了就明确报口径错误，
绝不把百分数和计数混在一起比较。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# 指标别名只用来识别同一个指标的不同写法，不会把行数、金额之类的指标卷进空值率。
METRIC_ALIASES = {
    "字段空值率": "字段空值率",
    "空值率": "字段空值率",
    "空值比例": "字段空值率",
    "null_rate": "字段空值率",
    "null_ratio": "字段空值率",
    "填充率": "填充率",
    "完备率": "完备率",
    "完整率": "完整率",
    "准确率": "准确率",
    "及时率": "及时率",
    "波动幅度": "波动幅度",
    "异常率": "异常率",
    "修复率": "修复率",
    "通过率": "通过率",
    "失败率": "失败率",
    "覆盖率": "覆盖率",
}

# 指标名 -> 默认单位。带“率/比例”的指标默认按百分数解读；
# 其余指标保留原始值（行数、金额、次数等），避免把 0.12 误当成 0.12%。
PERCENT_METRICS = {
    "字段空值率",
    "填充率",
    "完备率",
    "完整率",
    "准确率",
    "及时率",
    "波动幅度",
    "异常率",
    "修复率",
    "通过率",
    "失败率",
    "覆盖率",
    "基数比例",
}

FRACTION_METRICS = {"比例", "小数", "ratio", "fraction"}

PERCENT_UNITS = {
    "%",
    "百分比",
    "百分数",
    "percent",
    "pct",
    "百分点",
    "pp",
    "比率",
}
FRACTION_UNITS = {"比例", "小数", "fraction", "ratio"}
RAW_UNITS = {"原始值", "raw", "count", "数值", "个", "行", "次", "条"}


class MeasureError(ValueError):
    """读数或阈值无法换算到可比较的单位。"""


@dataclass(frozen=True)
class Measure:
    """一次归一化后的读数：value 与 unit 始终成对出现。"""

    value: float
    unit: str
    display: str
    source_unit: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "数值": self.value,
            "单位": self.unit,
            "显示": self.display,
            "原始单位": self.source_unit,
        }


def normalize_unit(unit: Any) -> str:
    return str(unit or "").strip().replace("％", "%").lower()


def canonical_metric(metric_name: Any) -> str:
    name = str(metric_name or "").strip()
    if not name:
        return ""
    lowered = name.casefold()
    for alias, canonical in METRIC_ALIASES.items():
        if alias.casefold() == lowered:
            return canonical
    return name


def metric_unit(metric_name: Any) -> str:
    """给出指标默认口径；调用方仍可用显式 unit 覆盖。"""
    canonical = canonical_metric(metric_name)
    lowered = canonical.casefold()
    if canonical in PERCENT_METRICS or lowered in {
        item.casefold() for item in PERCENT_METRICS
    }:
        return "%"
    if lowered in {item.casefold() for item in FRACTION_METRICS}:
        return "比例"
    return "原始值"


def _unit_category(unit: str) -> str:
    if unit in PERCENT_UNITS:
        return "percent"
    if unit in FRACTION_UNITS:
        return "fraction"
    if unit in RAW_UNITS or unit == "":
        return "raw"
    return "unknown"


def format_measure(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.2f}%"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_measure(
    value: Any,
    *,
    unit: Any = None,
    metric: Any = None,
    field: str = "数值",
) -> Measure:
    """把带单位的读数/阈值换算为 ``(数值, 单位)``。

    支持的写法：
    - ``"12.00%"`` / ``"12.00％"`` / ``"12pct"``：百分数；
    - ``"12.00"`` + ``unit="%"``：存量百分数，按 12% 读取；
    - ``"12.00"`` + ``unit="比例"``：按 0.12 的比例读取，换算为 12%；
    - ``8500`` + 指标 ``row_count``：原始值，不会被当成百分数；
    - 单位无法识别、上下界口径冲突或文本无法解析时抛 :class:`MeasureError`，
      由调用方记入争议明细，而不是让整个偏离校验报错。
    """
    if value is None or isinstance(value, bool):
        raise MeasureError(f"{field}不是可比较的数值：{value!r}")

    suffix_unit = ""
    if isinstance(value, str):
        text = value.strip().replace("％", "%").replace(" ", "")
        if not text:
            raise MeasureError(f"{field}为空")
        lower = text.lower()
        if text.endswith("%"):
            suffix_unit = "%"
            text = text[:-1]
        elif lower.endswith("percent"):
            suffix_unit = "%"
            text = text[: -len("percent")]
        elif lower.endswith("pct"):
            suffix_unit = "%"
            text = text[:-3]
        try:
            number = float(text)
        except ValueError as exc:
            raise MeasureError(f"{field}「{value}」无法解析为数值") from exc
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        raise MeasureError(f"{field}不是可比较的数值：{value!r}")

    if not math.isfinite(number):
        raise MeasureError(f"{field}「{value}」不是有限数值")

    declared = normalize_unit(unit)
    suffix = normalize_unit(suffix_unit)
    declared_cat = _unit_category(declared)
    suffix_cat = _unit_category(suffix)

    if declared_cat == "unknown":
        raise MeasureError(f"{field}单位「{unit}」无法识别")
    if suffix_cat == "unknown":
        raise MeasureError(f"{field}单位「{suffix_unit}」无法识别")
    if suffix_cat in ("percent", "fraction") and declared:
        if declared_cat in ("percent", "fraction") and suffix_cat != declared_cat:
            raise MeasureError(
                f"{field}单位口径冲突：数值写成「{suffix_unit}」，单位字段却是「{unit}」"
            )
        if declared_cat == "raw":
            raise MeasureError(
                f"{field}单位口径冲突：数值写成「{suffix_unit}」，单位字段却是「{unit}」"
            )

    effective = suffix or declared or metric_unit(metric)
    category = _unit_category(effective)
    if category == "unknown":
        raise MeasureError(f"{field}单位「{effective}」无法识别")

    source_unit = suffix or declared or effective
    if category == "fraction":
        canonical = number * 100.0
        canonical_unit = "%"
    elif category == "percent":
        canonical = number
        canonical_unit = "%"
    else:
        canonical = number
        # 显式写了原始值就尊重显式口径；否则落到指标默认口径。
        canonical_unit = declared if declared in RAW_UNITS else metric_unit(metric)
        if canonical_unit in ("", "比例"):
            canonical_unit = "原始值"

    return Measure(
        value=canonical,
        unit=canonical_unit,
        display=format_measure(canonical, canonical_unit),
        source_unit=source_unit,
    )


def same_metric(left: Any, right: Any) -> bool:
    return canonical_metric(left).casefold() == canonical_metric(right).casefold()
