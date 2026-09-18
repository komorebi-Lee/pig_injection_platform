"""遥测轮询：后端定时向机械臂要状态，落库 + 推送 + 触发告警。

这是"后端负责存储机械臂返回信息"的主干：
    机械臂 /status  ->  arm_status_samples（每轮一行）
                    ->  device_heartbeats（在线率与延迟）
                    ->  thermal_captures（热成像）
                    ->  obstacle_events（避障）
                    ->  alarms（急停/故障/超温）
                    ->  WebSocket 推给前端
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete

from ..config import settings
from ..db import session_scope
from ..models import (
    ArmStatusSample,
    Device,
    DeviceHeartbeat,
    ObstacleEvent,
    ThermalCapture,
    ThermalRoi,
)
from . import alarms, registry, ws
from .arm_gateway import ArmGatewayError

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now(TZ)


class TelemetryPoller:
    def __init__(self, interval_s: float | None = None) -> None:
        self.interval_s = interval_s or settings.telemetry_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_obstacle_id: int | None = None
        self.last_sample: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.cycles = 0

    # -- 生命周期 --
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="telemetry-poller", daemon=True)
        self._thread.start()
        logger.info("遥测轮询已启动，间隔 %.1fs", self.interval_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.perf_counter()
            try:
                self.tick()
                self.last_error = None
            except ArmGatewayError as exc:
                self.last_error = str(exc)
                self._record_offline(exc)
            except Exception as exc:
                self.last_error = repr(exc)
                logger.exception("遥测轮询异常")
            elapsed = time.perf_counter() - started
            self._stop.wait(max(0.05, self.interval_s - elapsed))

    # -- 单轮 --
    def tick(self) -> dict[str, Any] | None:
        adapter = registry.get_adapter()
        t0 = time.perf_counter()
        status = adapter.get_status()
        latency_ms = int((time.perf_counter() - t0) * 1000)
        self.cycles += 1

        with session_scope() as db:
            device = registry.get_arm_device(db)
            if device is None:
                logger.warning("台账中找不到机械臂设备，跳过本轮落库")
                return status

            self._persist_sample(db, device, status)
            self._persist_heartbeat(db, device, status, latency_ms)
            self._handle_thermal(db, device)
            self._handle_obstacle(db, device)
            self._handle_alarms(db, device, status)

            device.status = "online" if status.get("device_online", True) else "offline"
            device.last_seen_at = _now()
            if status.get("firmware_version"):
                device.firmware_version = str(status["firmware_version"])

        self.last_sample = status
        ws.broadcast_threadsafe(
            {
                "type": "arm_status",
                "data": {k: v for k, v in status.items() if k != "raw"},
                "sampled_at": _now().isoformat(),
            }
        )
        return status

    # -- 落库细节 --
    def _persist_sample(self, db, device: Device, status: dict[str, Any]) -> None:
        sample = ArmStatusSample(
            device_id=device.id,
            control_mode=str(status.get("control_mode") or "unknown")[:24],
            servo_power_on=status.get("servo_power_on"),
            estop_pressed=status.get("estop_pressed"),
            is_moving=status.get("is_moving"),
            motion_done=status.get("motion_done"),
            speed_override_pct=_dec(status.get("speed_override_pct")),
            safety_state=(str(status["safety_state"])[:32] if status.get("safety_state") else None),
            joint_angles_deg=status.get("joint_angles_deg"),
            joint_velocities=status.get("joint_velocities"),
            joint_torques=status.get("joint_torques"),
            joint_currents_a=status.get("joint_currents_a"),
            joint_temps_c=status.get("joint_temps_c"),
            tcp_pose=status.get("tcp_pose"),
            tcp_quaternion=status.get("tcp_quaternion"),
            tcp_linear_velocity=status.get("tcp_linear_velocity"),
            tcp_force=status.get("tcp_force"),
            tool_frame=status.get("tool_frame"),
            base_frame=status.get("base_frame"),
            payload_kg=_dec(status.get("payload_kg")),
            obstacle_avoidance_enabled=status.get("obstacle_avoidance_enabled"),
            obstacle_distance_mm=_dec(status.get("obstacle_distance_mm")),
            error_code=(str(status["error_code"])[:64] if status.get("error_code") else None),
            error_message=status.get("error_message"),
            warning_codes=status.get("warning_codes"),
            queue_len=status.get("queue_len"),
            raw=status.get("raw"),
            sampled_at=_now(),
        )
        db.add(sample)

    def _persist_heartbeat(self, db, device: Device, status: dict[str, Any], latency_ms: int) -> None:
        db.add(
            DeviceHeartbeat(
                device_id=device.id,
                online=bool(status.get("device_online", True)),
                latency_ms=latency_ms,
                firmware_version=status.get("firmware_version"),
                controller_temp_c=_dec(status.get("controller_temp_c")),
                uptime_s=status.get("uptime_s"),
                error_code=status.get("error_code"),
                error_message=status.get("error_message"),
                raw=None,
                sampled_at=_now(),
            )
        )

    def _record_offline(self, exc: ArmGatewayError) -> None:
        try:
            with session_scope() as db:
                device = registry.get_arm_device(db)
                if device is None:
                    return
                device.status = "offline"
                db.add(
                    DeviceHeartbeat(
                        device_id=device.id,
                        online=False,
                        error_code=exc.code,
                        error_message=str(exc)[:500],
                        sampled_at=_now(),
                    )
                )
                alarms.raise_alarm(
                    db,
                    level="critical",
                    category="communication",
                    code=exc.code,
                    title="机械臂通讯中断",
                    message=str(exc),
                    device_id=device.id,
                    dedup_key=f"comm:{exc.code}",
                )
        except Exception:
            logger.exception("记录离线状态失败")

    def _handle_thermal(self, db, device: Device) -> None:
        adapter = registry.get_adapter()
        try:
            thermal = adapter.get_thermal()
        except ArmGatewayError:
            return
        capture = ThermalCapture(
            device_id=device.id,
            capture_no=f"T{_now().strftime('%Y%m%d%H%M%S')}",
            emissivity=_dec(thermal.get("emissivity")),
            distance_m=_dec(thermal.get("distance_m")),
            reflected_temp_c=_dec(thermal.get("reflected_temp_c")),
            atmospheric_temp_c=_dec(thermal.get("atmospheric_temp_c")),
            humidity_pct=_dec(thermal.get("humidity_pct")),
            temp_range_min_c=_dec(thermal.get("temp_range_min_c")),
            temp_range_max_c=_dec(thermal.get("temp_range_max_c")),
            temp_max_c=_dec(thermal.get("temp_max_c")),
            temp_min_c=_dec(thermal.get("temp_min_c")),
            temp_avg_c=_dec(thermal.get("temp_avg_c")),
            temp_center_c=_dec(thermal.get("temp_center_c")),
            matrix_width=thermal.get("matrix_width"),
            matrix_height=thermal.get("matrix_height"),
            body_temp_c=_dec(thermal.get("body_temp_c")),
            injected_site_temp_c=_dec(thermal.get("injected_site_temp_c")),
            ambient_temp_c=_dec(thermal.get("ambient_temp_c")),
            is_fever=(
                None
                if thermal.get("body_temp_c") is None
                else float(thermal["body_temp_c"]) >= settings.fever_temp_c
            ),
            raw=None,
            captured_at=_now(),
        )
        db.add(capture)
        db.flush()
        for roi in thermal.get("rois") or []:
            db.add(
                ThermalRoi(
                    thermal_capture_id=capture.id,
                    roi_name=str(roi.get("roi_name"))[:64],
                    shape=roi.get("shape"),
                    geometry=roi.get("geometry"),
                    temp_max_c=_dec(roi.get("temp_max_c")),
                    temp_min_c=_dec(roi.get("temp_min_c")),
                    temp_avg_c=_dec(roi.get("temp_avg_c")),
                )
            )

    def _handle_obstacle(self, db, device: Device) -> None:
        adapter = registry.get_adapter()
        try:
            obstacle = adapter.get_obstacle_status()
        except ArmGatewayError:
            return
        event = obstacle.get("event") or obstacle.get("cleared_event")
        if not event:
            return
        obstacle_id = event.get("obstacle_id")
        if obstacle.get("active") and obstacle_id == self._last_obstacle_id:
            return  # 同一次障碍不重复记录
        self._last_obstacle_id = obstacle_id if obstacle.get("active") else None
        cleared = obstacle.get("cleared_event") is not None

        db.add(
            ObstacleEvent(
                device_id=device.id,
                event_type="cleared" if cleared else "detected",
                sensor_type=obstacle.get("sensor_type") or "depth_camera",
                obstacle_distance_mm=_dec(event.get("distance_mm")),
                obstacle_direction=event.get("direction"),
                obstacle_class=event.get("class"),
                detection_confidence=_dec(event.get("confidence")),
                action_taken=event.get("action_taken"),
                speed_after_pct=_dec(event.get("speed_after_pct")),
                resumed=cleared,
                detected_at=_now(),
                cleared_at=_now() if cleared else None,
                raw=event,
            )
        )
        if not cleared:
            ws.broadcast_threadsafe({"type": "obstacle", "data": event})

    def _handle_alarms(self, db, device: Device, status: dict[str, Any]) -> None:
        if status.get("estop_pressed"):
            alarms.raise_alarm(
                db,
                level="critical",
                category="estop",
                code="estop_pressed",
                title="机械臂急停触发",
                message="急停按钮处于按下状态，所有运动指令被拒绝。",
                device_id=device.id,
                dedup_key="estop",
            )
        else:
            alarms.clear_by_category(db, "estop", code="estop_pressed", device_id=device.id)

        error_code = status.get("error_code")
        if error_code:
            alarms.raise_alarm(
                db,
                level="critical",
                category="system",
                code=str(error_code),
                title="机械臂报错",
                message=str(status.get("error_message") or error_code),
                device_id=device.id,
                dedup_key=f"arm_error:{error_code}",
            )

        temps = status.get("joint_temps_c") or []
        hot = [float(t) for t in temps if isinstance(t, (int, float)) and float(t) >= 75.0]
        if hot:
            alarms.raise_alarm(
                db,
                level="warning",
                category="temperature",
                code="joint_overheat",
                title="关节电机温度偏高",
                message=f"最高关节温度 {max(hot):.1f} ℃",
                value=max(hot),
                threshold=75.0,
                device_id=device.id,
                dedup_key="joint_overheat",
            )

    # -- 维护 --
    def purge_old_samples(self, retention_days: int | None = None) -> int:
        days = retention_days or settings.telemetry_retention_days
        cutoff = _now() - timedelta(days=days)
        removed = 0
        with session_scope() as db:
            for model in (ArmStatusSample, DeviceHeartbeat):
                result = db.execute(delete(model).where(model.sampled_at < cutoff))
                removed += result.rowcount or 0
        if removed:
            logger.info("清理 %d 条过期遥测（早于 %s）", removed, cutoff.date())
        return removed


poller = TelemetryPoller()
