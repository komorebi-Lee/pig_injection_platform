"""系统级接口：健康检查、版本、统计概览。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import (
    Alarm,
    Device,
    InjectionTask,
    MediaAsset,
    ObstacleEvent,
    Operator,
    Pen,
    Pig,
    ThermalCapture,
)
from ..schemas import SystemHealth
from ..services import registry, telemetry, ws

router = APIRouter(tags=["系统"])
TZ = ZoneInfo("Asia/Shanghai")


@router.get("/health", response_model=SystemHealth, summary="健康检查")
def health(db: Session = Depends(get_db)) -> SystemHealth:
    adapter = registry.get_adapter()
    db_state = "ok"
    try:
        db.execute(select(1))
    except Exception as exc:
        db_state = f"error: {exc}"

    arm_online = False
    try:
        arm_online = bool(adapter.get_status().get("device_online", True))
    except Exception:
        arm_online = False

    return SystemHealth(
        ok=db_state == "ok",
        app_version=settings.app_version,
        database=db_state,
        arm_driver=adapter.name,
        arm_online=arm_online,
        websocket_clients=ws.hub.client_count,
        telemetry_cycles=telemetry.poller.cycles,
        telemetry_last_error=telemetry.poller.last_error,
        server_time=datetime.now(TZ),
    )


@router.get("/overview", summary="首页概览统计")
def overview(db: Session = Depends(get_db)) -> dict:
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)

    def count(stmt) -> int:
        return int(db.scalar(stmt) or 0)

    return {
        "ok": True,
        "data": {
            "pens": count(select(func.count()).select_from(Pen)),
            "pigs": count(select(func.count()).select_from(Pig)),
            "devices": count(select(func.count()).select_from(Device)),
            "operators": count(select(func.count()).select_from(Operator)),
            "injections_today": count(
                select(func.count()).select_from(InjectionTask).where(InjectionTask.created_at >= today)
            ),
            "injections_success_today": count(
                select(func.count())
                .select_from(InjectionTask)
                .where(InjectionTask.created_at >= today)
                .where(InjectionTask.status == "completed")
            ),
            "injections_failed_today": count(
                select(func.count())
                .select_from(InjectionTask)
                .where(InjectionTask.created_at >= today)
                .where(InjectionTask.status == "failed")
            ),
            "injections_week": count(
                select(func.count()).select_from(InjectionTask).where(InjectionTask.created_at >= week_ago)
            ),
            "active_alarms": count(
                select(func.count()).select_from(Alarm).where(Alarm.status == "active")
            ),
            "critical_alarms": count(
                select(func.count())
                .select_from(Alarm)
                .where(Alarm.status == "active")
                .where(Alarm.level == "critical")
            ),
            "obstacle_events_week": count(
                select(func.count()).select_from(ObstacleEvent).where(ObstacleEvent.detected_at >= week_ago)
            ),
            "thermal_captures_today": count(
                select(func.count()).select_from(ThermalCapture).where(ThermalCapture.captured_at >= today)
            ),
            "media_assets": count(select(func.count()).select_from(MediaAsset)),
        },
    }
