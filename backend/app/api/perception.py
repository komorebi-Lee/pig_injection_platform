"""避障事件与热成像历史接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ObstacleEvent, ThermalCapture, ThermalRoi
from ..schemas import ObstacleEventOut, Page, ThermalOut, ThermalRoiOut

router = APIRouter(tags=["感知"])


@router.get("/obstacle/events", summary="避障事件列表")
def obstacle_events(
    event_type: str | None = Query(default=None),
    task_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(ObstacleEvent).order_by(ObstacleEvent.id.desc())
    count_stmt = select(func.count()).select_from(ObstacleEvent)
    if event_type:
        stmt = stmt.where(ObstacleEvent.event_type == event_type)
        count_stmt = count_stmt.where(ObstacleEvent.event_type == event_type)
    if task_id is not None:
        stmt = stmt.where(ObstacleEvent.task_id == task_id)
        count_stmt = count_stmt.where(ObstacleEvent.task_id == task_id)
    rows = list(db.scalars(stmt.offset(offset).limit(limit)))
    return {
        "ok": True,
        "page": Page(total=int(db.scalar(count_stmt) or 0), limit=limit, offset=offset),
        "items": [ObstacleEventOut.model_validate(r) for r in rows],
    }


@router.get("/obstacle/events/{event_id}", summary="避障事件详情")
def obstacle_event_detail(event_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(ObstacleEvent, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="事件不存在")
    return {"ok": True, "data": ObstacleEventOut.model_validate(row), "raw": row.raw}


@router.get("/thermal/captures", summary="热成像历史列表")
def thermal_captures(
    task_id: int | None = Query(default=None),
    fever_only: bool = Query(default=False, description="只看体温异常记录"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(ThermalCapture).order_by(ThermalCapture.id.desc())
    count_stmt = select(func.count()).select_from(ThermalCapture)
    if task_id is not None:
        stmt = stmt.where(ThermalCapture.task_id == task_id)
        count_stmt = count_stmt.where(ThermalCapture.task_id == task_id)
    if fever_only:
        stmt = stmt.where(ThermalCapture.is_fever.is_(True))
        count_stmt = count_stmt.where(ThermalCapture.is_fever.is_(True))
    rows = list(db.scalars(stmt.offset(offset).limit(limit)))
    return {
        "ok": True,
        "page": Page(total=int(db.scalar(count_stmt) or 0), limit=limit, offset=offset),
        "items": [ThermalOut.model_validate(r) for r in rows],
    }


@router.get("/thermal/captures/{capture_id}", summary="热成像详情（含 ROI）")
def thermal_capture_detail(capture_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(ThermalCapture, capture_id)
    if row is None:
        raise HTTPException(status_code=404, detail="采集记录不存在")
    rois = list(db.scalars(select(ThermalRoi).where(ThermalRoi.thermal_capture_id == capture_id)))
    return {
        "ok": True,
        "data": ThermalOut.model_validate(row),
        "rois": [ThermalRoiOut.model_validate(r) for r in rois],
    }
