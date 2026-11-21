"""偏离校验凭证登记表。

每次基线比较生成一张凭证，凭证里冻结当次使用的基线快照：
- 并发复算同一读数时按签名只确认一次异常；
- 重取画像或复核事件时，按凭证还原当时用的基线版本，而不是看当前基线；
- 校验凭证同时是字段画像入口和事件复核面板读取比较明细的键。
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Any


class BaselineCheckRegistry:
    def __init__(self) -> None:
        self._checks: dict[str, dict[str, Any]] = {}
        self._signatures: dict[str, str] = {}
        # 复算“查重 + 写事件 + 落凭证”必须在同一把锁里完成。
        self._lock = threading.RLock()
        self._sequence = 0

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def next_credential(self) -> str:
        with self._lock:
            self._sequence += 1
            return f"BC-{self._sequence:04d}"

    def signature_owner(self, signature: str) -> str | None:
        with self._lock:
            return self._signatures.get(signature)

    def save(self, signature: str, check: dict[str, Any]) -> None:
        with self._lock:
            credential = check["校验凭证"]
            self._checks[credential] = copy.deepcopy(check)
            self._signatures[signature] = credential

    def get(self, credential: str) -> dict[str, Any] | None:
        with self._lock:
            check = self._checks.get(str(credential or "").strip())
            return copy.deepcopy(check) if check else None

    def by_credential_or_incident(self, value: str) -> dict[str, Any] | None:
        """允许用校验凭证或质量事件编号回查。"""
        direct = self.get(value)
        if direct:
            return direct
        with self._lock:
            for check in self._checks.values():
                if check.get("质量事件编号") == value:
                    return copy.deepcopy(check)
        return None

    def list_checks(
        self,
        *,
        table_name: str | None = None,
        metric: str | None = None,
        credential: str | None = None,
        incident_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._lock:
            checks = [copy.deepcopy(item) for item in self._checks.values()]
        result = []
        for check in checks:
            if table_name and check.get("目标表名") != table_name:
                continue
            if metric and check.get("基线指标") != metric:
                continue
            if credential and check.get("校验凭证") != credential:
                continue
            if incident_id and check.get("质量事件编号") != incident_id:
                continue
            result.append(check)
        result.sort(key=lambda item: item.get("校验时间", ""), reverse=True)
        return result[:limit]

    def reset(self) -> None:
        """测试辅助：清空凭证，不影响业务数据。"""
        with self._lock:
            self._checks.clear()
            self._signatures.clear()
            self._sequence = 0


baseline_checks = BaselineCheckRegistry()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
