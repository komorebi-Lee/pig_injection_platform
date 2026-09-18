"""报表与统计接口：给前端出图表、出日报。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alarm, InjectionTask, ObstacleEvent, Pig, ThermalCapture, VisionDetection

router = APIRouter(prefix="/reports", tags=["报表"])
TZ = ZoneInfo("Asia/Shanghai")


@router.get("/injections/daily", summary="按天的注射统计（成功率、平均耗时）")
def injections_daily(
    days: int = Query(default=14, ge=1, le=180),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(TZ) - timedelta(days=days)
    day_expr = cast(InjectionTask.created_at, Date)
    rows = db.execute(
        select(
            day_expr.label("day"),
            func.count().label("total"),
            func.count().filter(InjectionTask.status == "completed").label("completed"),
            func.count().filter(InjectionTask.status == "failed").label("failed"),
            func.count().filter(InjectionTask.status == "aborted").label("aborted"),
            func.avg(InjectionTask.duration_ms).label("avg_duration_ms"),
            func.avg(InjectionTask.dose_ml).label("avg_dose_ml"),
            func.avg(InjectionTask.peak_force_n).label("avg_peak_force_n"),
        )
        .where(InjectionTask.created_at >= since)
        .group_by(day_expr)
        .order_by(day_expr)
    ).all()

    items = []
    for row in rows:
        total = int(row.total or 0)
        completed = int(row.completed or 0)
        items.append(
            {
                "day": row.day,
                "total": total,
                "completed": completed,
                "failed": int(row.failed or 0),
                "aborted": int(row.aborted or 0),
                "success_rate": round(completed / total, 4) if total else None,
                "avg_duration_ms": int(row.avg_duration_ms) if row.avg_duration_ms is not None else None,
                "avg_dose_ml": float(row.avg_dose_ml) if row.avg_dose_ml is not None else None,
                "avg_peak_force_n": float(row.avg_peak_force_n) if row.avg_peak_force_n is not None else None,
            }
        )
    return {"ok": True, "days": days, "items": items}


@router.get("/injections/failure-reasons", summary="失败原因分布")
def failure_reasons(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(TZ) - timedelta(days=days)
    rows = db.execute(
        select(InjectionTask.fail_reason, func.count().label("count"))
        .where(InjectionTask.created_at >= since)
        .where(InjectionTask.fail_reason.is_not(None))
        .group_by(InjectionTask.fail_reason)
        .order_by(func.count().desc())
    ).all()
    return {"ok": True, "items": [{"fail_reason": r.fail_reason, "count": int(r.count)} for r in rows]}


@router.get("/injections/phase-durations", summary="各阶段平均耗时（用于找瓶颈）")
def phase_durations(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(TZ) - timedelta(days=days)
    rows = list(
        db.scalars(
            select(InjectionTask.phase_durations_ms)
            .where(InjectionTask.created_at >= since)
            .where(InjectionTask.phase_durations_ms.is_not(None))
        )
    )
    sums: dict[str, list[int]] = {}
    for payload in rows:
        if not isinstance(payload, dict):
            continue
        for phase, value in payload.items():
            if isinstance(value, (int, float)):
                sums.setdefault(str(phase), []).append(int(value))
    return {
        "ok": True,
        "samples": len(rows),
        "items": [
            {
                "phase": phase,
                "avg_ms": round(sum(values) / len(values), 1),
                "max_ms": max(values),
                "min_ms": min(values),
                "count": len(values),
            }
            for phase, values in sorted(sums.items())
        ],
    }


@router.get("/alarms/summary", summary="告警分类统计")
def alarms_summary(
    days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(TZ) - timedelta(days=days)
    rows = db.execute(
        select(Alarm.category, Alarm.level, func.count().label("count"))
        .where(Alarm.created_at >= since)
        .group_by(Alarm.category, Alarm.level)
        .order_by(func.count().desc())
    ).all()
    return {
        "ok": True,
        "items": [{"category": r.category, "level": r.level, "count": int(r.count)} for r in rows],
    }


@router.get("/thermal/trend", summary="体温趋势（用于健康监测）")
def thermal_trend(
    pig_id: int | None = Query(default=None),
    days: int = Query(default=14, ge=1, le=180),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(TZ) - timedelta(days=days)
    stmt = (
        select(ThermalCapture)
        .where(ThermalCapture.captured_at >= since)
        .where(ThermalCapture.body_temp_c.is_not(None))
        .order_by(ThermalCapture.captured_at)
    )
    rows = list(db.scalars(stmt.limit(2000)))
    return {
        "ok": True,
        "pig_id": pig_id,
        "count": len(rows),
        "items": [
            {
                "captured_at": r.captured_at,
                "body_temp_c": float(r.body_temp_c) if r.body_temp_c is not None else None,
                "ambient_temp_c": float(r.ambient_temp_c) if r.ambient_temp_c is not None else None,
                "is_fever": r.is_fever,
                "task_id": r.task_id,
            }
            for r in rows
        ],
    }


@router.get("/obstacles/summary", summary="避障统计")
def obstacles_summary(
    days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(TZ) - timedelta(days=days)
    by_class = db.execute(
        select(ObstacleEvent.obstacle_class, func.count().label("count"))
        .where(ObstacleEvent.detected_at >= since)
        .group_by(ObstacleEvent.obstacle_class)
        .order_by(func.count().desc())
    ).all()
    by_action = db.execute(
        select(ObstacleEvent.action_taken, func.count().label("count"))
        .where(ObstacleEvent.detected_at >= since)
        .group_by(ObstacleEvent.action_taken)
        .order_by(func.count().desc())
    ).all()
    total = int(
        db.scalar(select(func.count()).select_from(ObstacleEvent).where(ObstacleEvent.detected_at >= since)) or 0
    )
    return {
        "ok": True,
        "total": total,
        "by_class": [{"obstacle_class": r.obstacle_class, "count": int(r.count)} for r in by_class],
        "by_action": [{"action_taken": r.action_taken, "count": int(r.count)} for r in by_action],
    }


@router.get("/pig-production", summary="按猪只的注射次数统计")
def pig_production(
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.execute(
        select(
            Pig.id,
            Pig.ear_tag,
            Pig.pen_id,
            Pig.last_injection_at,
            func.count(InjectionTask.id).label("injection_count"),
        )
        .join(InjectionTask, InjectionTask.pig_id == Pig.id, isouter=True)
        .group_by(Pig.id, Pig.ear_tag, Pig.pen_id, Pig.last_injection_at)
        .order_by(func.count(InjectionTask.id).desc())
        .limit(limit)
    ).all()
    return {
        "ok": True,
        "items": [
            {
                "pig_id": r.id,
                "ear_tag": r.ear_tag,
                "pen_id": r.pen_id,
                "last_injection_at": r.last_injection_at,
                "injection_count": int(r.injection_count or 0),
            }
            for r in rows
        ],
    }


@router.get("/vision/recent", summary="最近视觉检测记录")
def vision_recent(
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(db.scalars(select(VisionDetection).order_by(VisionDetection.id.desc()).limit(limit)))
    return {
        "ok": True,
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "camera_role": r.camera_role,
                "class_name": r.class_name,
                "detected": r.detected,
                "confidence": float(r.confidence) if r.confidence is not None else None,
                "bbox": r.bbox,
                "injection_point_pixel": r.injection_point_pixel,
                "task_id": r.task_id,
                "captured_at": r.captured_at,
            }
            for r in rows
        ],
    }
