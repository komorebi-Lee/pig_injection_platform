"""告警接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alarm
from ..schemas import AlarmOut, Page
from ..services import alarms

router = APIRouter(prefix="/alarms", tags=["告警"])


@router.get("", summary="告警列表")
def list_alarms(
    status: str | None = Query(default=None, description="active|acknowledged|cleared"),
    level: str | None = Query(default=None, description="info|warning|critical"),
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Alarm).order_by(Alarm.id.desc())
    count_stmt = select(func.count()).select_from(Alarm)
    for column, value in ((Alarm.status, status), (Alarm.level, level), (Alarm.category, category)):
        if value:
            stmt = stmt.where(column == value)
            count_stmt = count_stmt.where(column == value)
    rows = list(db.scalars(stmt.offset(offset).limit(limit)))
    return {
        "ok": True,
        "page": Page(total=int(db.scalar(count_stmt) or 0), limit=limit, offset=offset),
        "items": [AlarmOut.model_validate(r) for r in rows],
    }


@router.post("/{alarm_id}/acknowledge", summary="确认告警")
def acknowledge(alarm_id: int, payload: dict | None = None, db: Session = Depends(get_db)) -> dict:
    operator_id = (payload or {}).get("operator_id")
    alarm = alarms.acknowledge(db, alarm_id, operator_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="告警不存在或已处理")
    db.commit()
    return {"ok": True, "data": AlarmOut.model_validate(alarm)}


@router.post("/{alarm_id}/clear", summary="关闭告警")
def clear(alarm_id: int, db: Session = Depends(get_db)) -> dict:
    alarm = alarms.clear(db, alarm_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    db.commit()
    return {"ok": True, "data": AlarmOut.model_validate(alarm)}
