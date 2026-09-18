"""指令通道：所有发往机械臂的控制指令都必须经过这里。

它负责四件事，缺一不可：
1. 幂等 —— 相同 request_id 重复提交直接返回首次结果，不动机械臂（防双击打两针）；
2. 审计 —— control_commands 表留下指令原文、机械臂原文返回、耗时、结果；
3. 错误归一 —— 把网关异常翻译成统一错误码给前端；
4. 广播 —— 成功后通过 WebSocket 通知所有页面，避免多标签页状态不一致。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ControlCommand, Device
from . import registry, ws
from .arm_gateway import ArmGatewayError

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")


class CommandRejected(RuntimeError):
    def __init__(self, message: str, code: str = "rejected", status: int = 409, request_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.request_id = request_id


@dataclass
class CommandResult:
    request_id: str
    command_type: str
    accepted: bool
    result: str
    arm_command_id: str | None
    message: str | None
    duration_ms: int
    response: dict[str, Any] | None
    idempotent_replay: bool = False


def _parse_uuid(value: str | None) -> uuid.UUID:
    if not value:
        return uuid.uuid4()
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        # 允许前端传任意字符串做幂等键，哈希成 UUID 保证列类型一致
        return uuid.uuid5(uuid.NAMESPACE_URL, str(value))


def dispatch(
    db: Session,
    *,
    device: Device,
    command_type: str,
    payload: dict[str, Any] | None,
    call: Callable[[], dict[str, Any]],
    request_id: str | None = None,
    operator_id: int | None = None,
    client_ip: str | None = None,
    source: str = "web",
    task_id: int | None = None,
) -> CommandResult:
    rid = _parse_uuid(request_id)

    existing = db.scalar(select(ControlCommand).where(ControlCommand.request_id == rid))
    if existing is not None:
        logger.info("幂等命中：request_id=%s command=%s", rid, existing.command_type)
        return CommandResult(
            request_id=str(rid),
            command_type=existing.command_type,
            accepted=bool(existing.accepted),
            result=existing.result,
            arm_command_id=existing.arm_command_id,
            message="重复请求，返回首次结果（未重复下发指令）",
            duration_ms=existing.duration_ms or 0,
            response=existing.response,
            idempotent_replay=True,
        )

    record = ControlCommand(
        request_id=rid,
        device_id=device.id,
        operator_id=operator_id,
        task_id=task_id,
        command_type=command_type,
        source=source,
        client_ip=client_ip,
        payload=payload,
        result="running",
        created_at=datetime.now(TZ),
    )
    db.add(record)
    db.flush()

    started = time.perf_counter()
    try:
        response = call()
    except ArmGatewayError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        record.result = "failed"
        record.accepted = False
        record.error_code = exc.code
        record.reject_reason = str(exc)
        record.duration_ms = elapsed
        record.completed_at = datetime.now(TZ)
        db.flush()
        raise CommandRejected(str(exc), code=exc.code, status=exc.status, request_id=str(rid)) from exc
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        record.result = "failed"
        record.accepted = False
        record.error_code = "internal_error"
        record.reject_reason = repr(exc)
        record.duration_ms = elapsed
        record.completed_at = datetime.now(TZ)
        db.flush()
        raise CommandRejected(f"下发指令失败：{exc}", code="internal_error", status=500, request_id=str(rid)) from exc

    elapsed = int((time.perf_counter() - started) * 1000)
    accepted = bool(response.get("accepted", True))
    record.accepted = accepted
    record.result = "success" if accepted else "rejected"
    record.arm_command_id = response.get("arm_command_id")
    record.response = response
    record.duration_ms = elapsed
    record.completed_at = datetime.now(TZ)
    if not accepted:
        record.reject_reason = str(response.get("message") or "机械臂拒绝执行")
    db.flush()

    ws.broadcast_threadsafe(
        {
            "type": "control_command",
            "data": {
                "request_id": str(rid),
                "command_type": command_type,
                "accepted": accepted,
                "result": record.result,
                "duration_ms": elapsed,
            },
        }
    )
    return CommandResult(
        request_id=str(rid),
        command_type=command_type,
        accepted=accepted,
        result=record.result,
        arm_command_id=record.arm_command_id,
        message=None if accepted else record.reject_reason,
        duration_ms=elapsed,
        response=response,
    )


def resolve_device(db: Session, device_code: str | None) -> Device:
    device = registry.get_arm_device(db, device_code)
    if device is None:
        raise CommandRejected(
            "台账中不存在机械臂设备，请先在 /api/v1/devices 登记", code="device_not_found", status=404
        )
    return device
