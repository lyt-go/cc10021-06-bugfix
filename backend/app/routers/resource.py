"""统一资源接口：查询、导出、登记和动作按模块 key 分派到领域服务。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services import service_for
from app.services.column_profile import ColumnProfileService
from app.services.dq_baseline import DqBaselineService
from app.services.dq_incident import DqIncidentService

router = APIRouter(prefix="/api", tags=["业务资源"])


class BaselineCheckPayload(BaseModel):
    table_name: str
    current_value: Any
    unit: str | None = None
    metric: str | None = "字段空值率"


class NullRateCheckPayload(BaseModel):
    table_name: str
    null_rate: Any
    unit: str | None = None


class ProfileAggregatePayload(BaseModel):
    table_name: str
    columns: list[dict[str, Any]] = Field(default_factory=list)


def require_service(module: str):
    service = service_for(module)
    if service is None:
        raise HTTPException(status_code=404, detail=f"未知业务模块：{module}")
    return service


# ----------------------------------------------------------------------
# 基线比较凭证接口：必须注册在 /{module}/{entry_id} 之前，避免凭证被当成 id。
# ----------------------------------------------------------------------
@router.get("/dq_baseline/checks")
def list_baseline_checks(
    table_name: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    items = DqBaselineService().list_check_records(
        table_name=table_name, metric=metric, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/dq_baseline/checks/{credential}")
def get_baseline_check(credential: str) -> dict[str, Any]:
    check = DqBaselineService().replay_baseline_check(credential)
    if check is None:
        raise HTTPException(status_code=404, detail=f"校验凭证 {credential} 不存在")
    return check


@router.post("/dq_baseline/checks")
def run_baseline_check(payload: BaselineCheckPayload) -> dict[str, Any]:
    return DqBaselineService().check_baseline_deviation(
        payload.table_name,
        payload.current_value,
        unit=payload.unit,
        metric=payload.metric,
    )


@router.post("/column_profile/null-rate-check")
def run_null_rate_check(payload: NullRateCheckPayload) -> dict[str, Any]:
    return ColumnProfileService().validate_null_rate(
        payload.table_name, payload.null_rate, unit=payload.unit)


@router.post("/column_profile/aggregate")
def run_profile_aggregate(payload: ProfileAggregatePayload) -> dict[str, Any]:
    service = ColumnProfileService()
    profiles = service.compute_column_statistics(payload.table_name, payload.columns)
    return service.aggregate_table_profile(payload.table_name, profiles)


@router.get("/column_profile/checks/{credential}")
def get_profile_check(credential: str) -> dict[str, Any]:
    check = ColumnProfileService().read_baseline_comparison(credential)
    if check is None:
        raise HTTPException(status_code=404, detail=f"校验凭证 {credential} 不存在")
    return check


@router.get("/dq_incident/{incident_ref}/baseline-review")
def review_incident_baseline(incident_ref: str) -> dict[str, Any]:
    review = DqIncidentService().review_incident(incident_ref)
    if review is None:
        raise HTTPException(status_code=404, detail=f"事件 {incident_ref} 没有可复核的基线校验凭证")
    return review


@router.get("/{module}", response_model=PageResult[dict])
def list_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, total = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{module}/export")
def export_entries(
    module: str,
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    service = require_service(module)
    filters = {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in service.LIST_FIELDS and value.strip()
    }
    items, _ = service.list_entries(
        filters=filters, keyword=keyword, status=status, page=1, size=1_000_000)
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *service.LIST_FIELDS, "status"])
    for item in items:
        values = [item.get("id"), *(item.get(field, "") for field in service.LIST_FIELDS),
                  item.get("status", "")]
        writer.writerow([
            "'" + str(value) if str(value or "").startswith(("=", "+", "-", "@")) else value
            for value in values
        ])
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{module}.csv"'},
    )


@router.get("/{module}/{entry_id}", response_model=dict)
def get_entry(module: str, entry_id: str) -> dict[str, Any]:
    service = require_service(module)
    try:
        numeric_id = int(entry_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{service.ENTITY} {entry_id} 不存在或已归档")
    entry = service.get_entry(numeric_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{service.ENTITY} {entry_id} 不存在或已归档")
    return entry


@router.post("/{module}", response_model=ActionResult)
def create_entry(module: str, payload: EntryPayload) -> ActionResult:
    service = require_service(module)
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message=f"{service.ENTITY}已登记", entry=entry)


@router.post("/{module}/{entry_id}/actions", response_model=ActionResult)
def run_action(module: str, entry_id: int, payload: ActionPayload) -> ActionResult:
    service = require_service(module)
    entry, message = service.run_action(entry_id, payload.action.strip())
    return ActionResult(ok=entry is not None, message=message, entry=entry)
