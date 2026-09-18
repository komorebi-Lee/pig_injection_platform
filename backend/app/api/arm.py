"""机械臂接口：实时状态、手动控制、热成像、自动避障开关、指令日志。

注意：这里没有任何一个接口会让前端绕过本服务直接操作机械臂。
所有指令都经过 services.commands.dispatch()，具备幂等 + 审计。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ArmStatusSample, ControlCommand
from ..schemas import (
    ArmStatusOut,
    CommandAck,
    CommandLogOut,
    DeviceRequest,
    JogRequest,
    ModeRequest,
    MoveJointRequest,
    MovePoseRequest,
    ObstacleToggleRequest,
    ThermalOut,
)
from ..services import commands, registry
from ..services.arm_gateway import ArmGatewayError
from .deps import client_ip

router = APIRouter(prefix="/arm", tags=["机械臂"])


def _ack(result) -> CommandAck:
    return CommandAck(
        request_id=result.request_id,
        command_type=result.command_type,
        accepted=result.accepted,
        result=result.result,
        arm_command_id=result.arm_command_id,
        message=result.message,
        duration_ms=result.duration_ms,
        response=result.response,
    )


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------


@router.get("/status", response_model=ArmStatusOut, summary="机械臂实时状态（直读，不落库）")
def arm_status(device_code: str | None = Query(default=None), db: Session = Depends(get_db)) -> ArmStatusOut:
    device = commands.resolve_device(db, device_code)
    adapter = registry.get_adapter()
    try:
        status = adapter.get_status()
    except ArmGatewayError as exc:
        raise commands.CommandRejected(str(exc), code=exc.code, status=exc.status) from exc
    status.pop("raw", None)
    return ArmStatusOut(device_code=device.device_code, **status)


@router.get("/status/history", summary="机械臂遥测历史（来自数据库，用于画曲线）")
def arm_status_history(
    device_code: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    device = commands.resolve_device(db, device_code)
    rows = list(
        db.scalars(
            select(ArmStatusSample)
            .where(ArmStatusSample.device_id == device.id)
            .order_by(ArmStatusSample.id.desc())
            .limit(limit)
        )
    )
    return {
        "ok": True,
        "device_code": device.device_code,
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "control_mode": r.control_mode,
                "safety_state": r.safety_state,
                "is_moving": r.is_moving,
                "speed_override_pct": float(r.speed_override_pct) if r.speed_override_pct is not None else None,
                "joint_angles_deg": r.joint_angles_deg,
                "joint_temps_c": r.joint_temps_c,
                "tcp_pose": r.tcp_pose,
                "tcp_force": r.tcp_force,
                "payload_kg": float(r.payload_kg) if r.payload_kg is not None else None,
                "obstacle_distance_mm": float(r.obstacle_distance_mm) if r.obstacle_distance_mm is not None else None,
                "error_code": r.error_code,
                "sampled_at": r.sampled_at,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# 手动控制
# ---------------------------------------------------------------------------


@router.post("/jog", response_model=CommandAck, summary="点动（手动控制）")
def arm_jog(payload: JogRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    result = commands.dispatch(
        db,
        device=device,
        command_type="jog",
        payload=payload.model_dump(exclude={"request_id", "operator_id", "operator_name", "device_code"}),
        call=lambda: adapter.jog(
            {
                "axis": payload.axis,
                "direction": payload.direction,
                "step": payload.step,
                "speed_pct": payload.speed_pct,
            }
        ),
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


@router.post("/move/pose", response_model=CommandAck, summary="末端位姿移动")
def arm_move_pose(payload: MovePoseRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    result = commands.dispatch(
        db,
        device=device,
        command_type="move_pose",
        payload=payload.model_dump(exclude={"request_id", "operator_id", "operator_name", "device_code"}),
        call=lambda: adapter.move_pose(
            {"pose": payload.pose.model_dump(), "speed_pct": payload.speed_pct, "frame": payload.frame}
        ),
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


@router.post("/move/joint", response_model=CommandAck, summary="关节角移动")
def arm_move_joint(payload: MoveJointRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    result = commands.dispatch(
        db,
        device=device,
        command_type="move_joint",
        payload=payload.model_dump(exclude={"request_id", "operator_id", "operator_name", "device_code"}),
        call=lambda: adapter.move_joint(
            {"joint_angles_deg": payload.joint_angles_deg, "speed_pct": payload.speed_pct}
        ),
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


@router.post("/home", response_model=CommandAck, summary="回零点")
def arm_home(payload: DeviceRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    result = commands.dispatch(
        db,
        device=device,
        command_type="home",
        payload={},
        call=adapter.home,
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


@router.post("/stop", response_model=CommandAck, summary="停止当前运动")
def arm_stop(payload: DeviceRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    result = commands.dispatch(
        db,
        device=device,
        command_type="stop",
        payload={},
        call=adapter.stop,
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


@router.post(
    "/estop",
    response_model=CommandAck,
    summary="紧急停止（最高优先级、幂等）",
    description="急停在任何状态下都必须可下发，且必须允许重复调用。前端应提供独立的大按钮。",
)
def arm_estop(payload: DeviceRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    result = commands.dispatch(
        db,
        device=device,
        command_type="estop",
        payload={},
        call=adapter.estop,
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


@router.post("/estop/reset", response_model=CommandAck, summary="急停复位（复位后通常需要回零）")
def arm_estop_reset(payload: DeviceRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    result = commands.dispatch(
        db,
        device=device,
        command_type="estop_reset",
        payload={},
        call=adapter.estop_reset,
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


@router.post("/mode", response_model=CommandAck, summary="切换控制模式")
def arm_set_mode(payload: ModeRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    result = commands.dispatch(
        db,
        device=device,
        command_type="set_mode",
        payload={"mode": payload.mode},
        call=lambda: adapter.set_mode(payload.mode),
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


# ---------------------------------------------------------------------------
# 自动避障
# ---------------------------------------------------------------------------


@router.get("/obstacle/status", summary="自动避障实时状态")
def obstacle_status(device_code: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    device = commands.resolve_device(db, device_code)
    adapter = registry.get_adapter()
    try:
        data = adapter.get_obstacle_status()
    except ArmGatewayError as exc:
        raise commands.CommandRejected(str(exc), code=exc.code, status=exc.status) from exc
    return {"ok": True, "device_code": device.device_code, "data": data}


@router.post("/obstacle/enabled", response_model=CommandAck, summary="开启/关闭自动避障")
def obstacle_toggle(payload: ObstacleToggleRequest, request: Request, db: Session = Depends(get_db)) -> CommandAck:
    device = commands.resolve_device(db, payload.device_code)
    adapter = registry.get_adapter()
    setter = getattr(adapter, "set_obstacle_enabled", None)
    if setter is None:
        raise commands.CommandRejected("当前机械臂适配器不支持远程开关避障", code="unsupported", status=501)
    result = commands.dispatch(
        db,
        device=device,
        command_type="obstacle_enable" if payload.enabled else "obstacle_disable",
        payload={"enabled": payload.enabled},
        call=lambda: setter(payload.enabled),
        request_id=payload.request_id,
        operator_id=payload.operator_id,
        client_ip=client_ip(request),
    )
    db.commit()
    return _ack(result)


# ---------------------------------------------------------------------------
# 热成像
# ---------------------------------------------------------------------------


@router.get("/thermal/latest", summary="最新一帧热成像（直读机械臂）")
def thermal_latest(device_code: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    device = commands.resolve_device(db, device_code)
    adapter = registry.get_adapter()
    try:
        data = adapter.get_thermal()
    except ArmGatewayError as exc:
        raise commands.CommandRejected(str(exc), code=exc.code, status=exc.status) from exc
    return {"ok": True, "device_code": device.device_code, "data": data}


@router.get("/thermal/history", summary="热成像历史（来自数据库）")
def thermal_history(
    device_code: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    from ..models import ThermalCapture

    device = commands.resolve_device(db, device_code)
    rows = list(
        db.scalars(
            select(ThermalCapture)
            .where(ThermalCapture.device_id == device.id)
            .order_by(ThermalCapture.id.desc())
            .limit(limit)
        )
    )
    return {
        "ok": True,
        "device_code": device.device_code,
        "count": len(rows),
        "items": [ThermalOut.model_validate(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# 指令日志
# ---------------------------------------------------------------------------


@router.get("/commands", summary="指令审计日志")
def command_log(
    device_code: str | None = Query(default=None),
    command_type: str | None = Query(default=None),
    result: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(ControlCommand).order_by(ControlCommand.id.desc())
    if device_code:
        device = commands.resolve_device(db, device_code)
        stmt = stmt.where(ControlCommand.device_id == device.id)
    if command_type:
        stmt = stmt.where(ControlCommand.command_type == command_type)
    if result:
        stmt = stmt.where(ControlCommand.result == result)
    rows = list(db.scalars(stmt.offset(offset).limit(limit)))
    return {"ok": True, "count": len(rows), "items": [CommandLogOut.model_validate(r) for r in rows]}
