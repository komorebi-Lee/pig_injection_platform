"""自动注射流程编排（后端状态机）。

为什么要放在后端而不是外包的机械臂服务里：
- 前端要能实时看到"现在走到哪一步"，这必须是后端持有的权威状态；
- 每一步都要落库（injection_events），失败要能定位到具体阶段；
- 机械臂服务重启/掉线后，后端能判断任务是否悬挂并给出结论。

阶段：created -> locating -> aligning -> inserting -> injecting -> retracting
      -> completed / failed / aborted
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..db import session_scope
from ..models import Device, InjectionEvent, InjectionTask, Pig
from . import alarms, registry, ws
from .arm_gateway import ArmGatewayError

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")

PHASE_ORDER = ["locating", "aligning", "inserting", "injecting", "retracting"]
PHASE_LABELS = {
    "locating": "定位注射点",
    "aligning": "机械臂对位",
    "inserting": "进针",
    "injecting": "注药",
    "retracting": "退针",
    "completed": "完成",
    "failed": "失败",
    "aborted": "已中止",
}

# Mock 模式下每个阶段的模拟耗时（秒），让前端能看到真实的阶段流转
MOCK_PHASE_SECONDS = {"locating": 1.2, "aligning": 1.5, "inserting": 1.0, "injecting": 1.0, "retracting": 0.8}

_ACTIVE: dict[int, threading.Thread] = {}
_ACTIVE_LOCK = threading.Lock()


class InjectionError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(TZ)


def next_task_no(db) -> str:
    today = _now().strftime("%Y%m%d")
    prefix = f"T{today}-"
    last = db.scalar(
        select(InjectionTask.task_no).where(InjectionTask.task_no.like(f"{prefix}%")).order_by(InjectionTask.task_no.desc()).limit(1)
    )
    seq = 1 if last is None else int(last.split("-")[-1]) + 1
    return f"{prefix}{seq:04d}"


def record_event(
    db,
    task_id: int,
    event_type: str,
    *,
    phase: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> InjectionEvent:
    event = InjectionEvent(
        task_id=task_id,
        event_type=event_type,
        phase=phase,
        message=message,
        payload=payload,
        occurred_at=_now(),
    )
    db.add(event)
    return event


def create_task(
    db,
    *,
    device: Device,
    pen_id: int | None,
    pig_id: int | None,
    operator_id: int | None,
    operator_name: str | None,
    mode: str = "auto",
    dose_target_ml: float | None = None,
    depth_mm: float | None = None,
    drug_name: str | None = None,
    drug_batch_no: str | None = None,
    needle_id: str | None = None,
    target_point_base: dict[str, Any] | None = None,
    target_point_pixel: dict[str, Any] | None = None,
    target_source: str = "guardrail_camera",
    target_confidence: float | None = None,
    batch_no: str | None = None,
) -> InjectionTask:
    task = InjectionTask(
        task_no=next_task_no(db),
        batch_no=batch_no,
        device_id=device.id,
        pen_id=pen_id,
        pig_id=pig_id,
        ear_tag_snapshot=None,
        operator_id=operator_id,
        operator_name=operator_name,
        mode=mode,
        status="created",
        target_source=target_source,
        target_point_base=target_point_base,
        target_point_pixel=target_point_pixel,
        target_confidence=None if target_confidence is None else Decimal(str(target_confidence)),
        target_depth_mm=None if depth_mm is None else Decimal(str(depth_mm)),
        dose_target_ml=None if dose_target_ml is None else Decimal(str(dose_target_ml)),
        drug_name=drug_name,
        drug_batch_no=drug_batch_no,
        needle_id=needle_id,
    )
    if pig_id is not None:
        pig = db.get(Pig, pig_id)
        if pig is not None:
            task.ear_tag_snapshot = pig.ear_tag
    db.add(task)
    db.flush()
    record_event(db, task.id, "created", phase="created", message="任务已创建")
    return task


def start_task(task_id: int) -> None:
    """异步启动注射流程。接口层立即返回，前端靠 WebSocket / 轮询看进度。"""
    with _ACTIVE_LOCK:
        if task_id in _ACTIVE and _ACTIVE[task_id].is_alive():
            raise InjectionError("该任务已在执行中")
        thread = threading.Thread(target=_run_task, args=(task_id,), name=f"injection-{task_id}", daemon=True)
        _ACTIVE[task_id] = thread
        thread.start()


def abort_task(task_id: int, reason: str = "operator_abort") -> dict[str, Any]:
    adapter = registry.get_adapter()
    with session_scope() as db:
        task = db.get(InjectionTask, task_id)
        if task is None:
            raise InjectionError("任务不存在")
        if task.status in {"completed", "failed", "aborted"}:
            return {"task_id": task_id, "status": task.status, "note": "任务已结束，无需中止"}
        try:
            adapter.inject_abort(task.task_no, reason)
        except ArmGatewayError as exc:
            logger.warning("中止指令下发失败（继续本地标记中止）：%s", exc)
        task.status = "aborted"
        task.fail_reason = reason
        task.finished_at = _now()
        record_event(db, task.id, "abort", phase="aborted", message=f"任务中止：{reason}")
    ws.broadcast_threadsafe({"type": "injection_task", "data": {"task_id": task_id, "status": "aborted"}})
    return {"task_id": task_id, "status": "aborted", "reason": reason}


def _set_phase(task_id: int, phase: str) -> None:
    """更新任务当前阶段并记一条时间线事件。"""
    with session_scope() as db:
        task = db.get(InjectionTask, task_id)
        if task is None:
            return
        task.status = phase
        record_event(
            db, task.id, "phase_change",
            phase=phase,
            message=f"进入阶段：{PHASE_LABELS.get(phase, phase)}",
        )
    ws.broadcast_threadsafe(
        {"type": "injection_phase", "data": {"task_id": task_id, "phase": phase}}
    )


def _close_phase(durations: dict[str, int], phase: str, phase_started: float) -> float:
    """结算一个阶段的真实耗时，返回下一阶段的起点。"""
    now = time.perf_counter()
    durations[phase] = int((now - phase_started) * 1000)
    return now


def _run_task(task_id: int) -> None:
    adapter = registry.get_adapter()
    durations: dict[str, int] = {}
    try:
        with session_scope() as db:
            task = db.get(InjectionTask, task_id)
            if task is None:
                return
            payload = {
                "task_no": task.task_no,
                "target_point": task.target_point_base,
                "depth_mm": float(task.target_depth_mm) if task.target_depth_mm is not None else 3.0,
                "dose_ml": float(task.dose_target_ml) if task.dose_target_ml is not None else 2.0,
                "pen_id": task.pen_id,
                "pig_id": task.pig_id,
            }
            task.status = "queued"
            task.started_at = _now()

        total_started = time.perf_counter()
        phase_started = total_started

        # ---- 1) 定位注射点 ----
        _set_phase(task_id, "locating")
        with session_scope() as db:
            task = db.get(InjectionTask, task_id)
            if task.target_point_base is None:
                # 没有上游视觉结果时生成一个默认目标点；真实场景应由护栏相机写入
                task.target_point_base = {"x": 420.0, "y": 30.0, "z": 760.0, "frame": "base"}
                task.target_source = task.target_source or "auto_generated"
                record_event(
                    db, task.id, "vision_detect", phase="locating",
                    message="未收到上游视觉目标点，已生成默认目标点",
                    payload=task.target_point_base,
                )
        time.sleep(MOCK_PHASE_SECONDS["locating"])
        phase_started = _close_phase(durations, "locating", phase_started)

        # ---- 2) 机械臂对位 ----
        _set_phase(task_id, "aligning")
        adapter.move_pose({"pose": {"x": 400.0, "y": 20.0, "z": 700.0}, "speed_pct": 20})
        time.sleep(MOCK_PHASE_SECONDS["aligning"])
        phase_started = _close_phase(durations, "aligning", phase_started)

        # ---- 3) 进针 ----
        _set_phase(task_id, "inserting")
        arm_result = adapter.inject_start(payload)
        with session_scope() as db:
            task = db.get(InjectionTask, task_id)
            if task is not None:
                task.raw = arm_result
                record_event(
                    db, task.id, "needle_insert", phase="inserting",
                    message="机械臂开始进针", payload=arm_result,
                )
        time.sleep(MOCK_PHASE_SECONDS["inserting"])
        phase_started = _close_phase(durations, "inserting", phase_started)

        # ---- 4) 注药 ----
        _set_phase(task_id, "injecting")
        with session_scope() as db:
            task = db.get(InjectionTask, task_id)
            if task is not None:
                record_event(
                    db, task.id, "drug_inject", phase="injecting",
                    message=f"注入 {payload['dose_ml']} ml",
                    payload={"dose_ml": payload["dose_ml"]},
                )
        time.sleep(MOCK_PHASE_SECONDS["injecting"])
        phase_started = _close_phase(durations, "injecting", phase_started)

        # ---- 5) 退针 ----
        _set_phase(task_id, "retracting")
        with session_scope() as db:
            task = db.get(InjectionTask, task_id)
            if task is not None:
                record_event(db, task.id, "needle_retract", phase="retracting", message="退针完成")
        time.sleep(MOCK_PHASE_SECONDS["retracting"])
        phase_started = _close_phase(durations, "retracting", phase_started)

        # ---- 6) 收尾：读热成像与力反馈，写回结果 ----
        try:
            thermal = adapter.get_thermal()
        except ArmGatewayError:
            thermal = {}
        final_status = adapter.get_status()
        total_ms = int((time.perf_counter() - total_started) * 1000)

        with session_scope() as db:
            task = db.get(InjectionTask, task_id)
            if task is None:
                return
            task.status = "completed"
            task.finished_at = _now()
            task.duration_ms = total_ms
            task.phase_durations_ms = durations
            task.actual_entry_point = task.target_point_base
            task.actual_depth_mm = task.target_depth_mm
            task.dose_ml = task.dose_target_ml
            task.body_temp_c = None if thermal.get("body_temp_c") is None else Decimal(str(thermal["body_temp_c"]))
            task.ambient_temp_c = (
                None if thermal.get("ambient_temp_c") is None else Decimal(str(thermal["ambient_temp_c"]))
            )
            force = (final_status.get("tcp_force") or {}) if isinstance(final_status, dict) else {}
            task.peak_force_n = Decimal(str(abs(float(force.get("fz", 0.0)))))
            task.obstacle_triggered = bool(final_status.get("obstacle_distance_mm"))
            record_event(
                db, task.id, "phase_change", phase="completed",
                message=f"注射完成，总耗时 {total_ms} ms",
                payload={"duration_ms": total_ms, "phase_durations_ms": durations},
            )
            if task.pig_id is not None:
                pig = db.get(Pig, task.pig_id)
                if pig is not None:
                    pig.last_injection_at = task.finished_at

        ws.broadcast_threadsafe(
            {"type": "injection_task", "data": {"task_id": task_id, "status": "completed", "duration_ms": total_ms}}
        )

    except ArmGatewayError as exc:
        _fail(task_id, durations, fail_reason=exc.code, message=str(exc))
    except Exception as exc:
        logger.exception("注射流程异常")
        _fail(task_id, durations, fail_reason="internal_error", message=repr(exc))

def _fail(task_id: int, durations: dict[str, int], *, fail_reason: str, message: str) -> None:
    with session_scope() as db:
        task = db.get(InjectionTask, task_id)
        if task is None:
            return
        task.status = "failed"
        task.fail_reason = fail_reason
        task.fail_message = message[:500]
        task.finished_at = _now()
        task.phase_durations_ms = durations
        record_event(db, task.id, "error", phase=task.status, message=f"注射失败：{message}")
        alarms.raise_alarm(
            db,
            level="critical",
            category="injection_failed",
            code=fail_reason,
            title="注射失败",
            message=f"任务 {task.task_no} 失败：{message}",
            device_id=task.device_id,
            task_id=task.id,
        )
    ws.broadcast_threadsafe(
        {"type": "injection_task", "data": {"task_id": task_id, "status": "failed", "reason": fail_reason}}
    )


def active_task_ids() -> list[int]:
    with _ACTIVE_LOCK:
        return [tid for tid, th in _ACTIVE.items() if th.is_alive()]
