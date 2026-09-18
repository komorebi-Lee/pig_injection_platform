"""设备台账接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Device, DeviceHeartbeat
from ..schemas import DeviceOut

router = APIRouter(prefix="/devices", tags=["设备"])


@router.get("", summary="设备列表")
def list_devices(
    device_type: str | None = Query(default=None, description="arm|camera_guardrail|camera_arm|camera_thermal|controller"),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Device).order_by(Device.id)
    if device_type:
        stmt = stmt.where(Device.device_type == device_type)
    items = list(db.scalars(stmt))
    return {"ok": True, "count": len(items), "items": [DeviceOut.model_validate(i) for i in items]}


@router.get("/{device_code}", summary="设备详情")
def get_device(device_code: str, db: Session = Depends(get_db)) -> dict:
    device = db.scalar(select(Device).where(Device.device_code == device_code))
    if device is None:
        raise HTTPException(status_code=404, detail=f"设备不存在：{device_code}")
    return {"ok": True, "data": DeviceOut.model_validate(device)}


@router.get("/{device_code}/heartbeats", summary="设备心跳历史")
def device_heartbeats(
    device_code: str,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    device = db.scalar(select(Device).where(Device.device_code == device_code))
    if device is None:
        raise HTTPException(status_code=404, detail=f"设备不存在：{device_code}")
    rows = list(
        db.scalars(
            select(DeviceHeartbeat)
            .where(DeviceHeartbeat.device_id == device.id)
            .order_by(DeviceHeartbeat.id.desc())
            .limit(limit)
        )
    )
    online = sum(1 for r in rows if r.online)
    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
    return {
        "ok": True,
        "device_code": device_code,
        "count": len(rows),
        "online_ratio": round(online / len(rows), 4) if rows else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "items": [
            {
                "id": r.id,
                "online": r.online,
                "latency_ms": r.latency_ms,
                "firmware_version": r.firmware_version,
                "controller_temp_c": float(r.controller_temp_c) if r.controller_temp_c is not None else None,
                "uptime_s": r.uptime_s,
                "error_code": r.error_code,
                "error_message": r.error_message,
                "sampled_at": r.sampled_at,
            }
            for r in rows
        ],
    }
