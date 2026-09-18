"""机械臂网关：把"外包方的机械臂控制服务"抽象成一个统一接口。

为什么要这一层：
- 外包方的接口路径/协议/字段随时可能变，业务代码不应该跟着改，只改这里的适配器。
- 没有硬件时用 MockArmAdapter，前端可以立刻开始联调。
- 所有指令出口唯一，便于加幂等、超时、审计、熔断。

对接真实机械臂时只需要在 .env 里设置 ARM_DRIVER=http 并按其文档调整
ARM_PATH_* 路径映射与下方 HttpArmAdapter 的字段转换。
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")


def _now() -> datetime:
    return datetime.now(TZ)


class ArmGatewayError(RuntimeError):
    """网关层异常。携带 code 便于前端区分"网络不通"和"机械臂拒绝"。"""

    def __init__(self, message: str, code: str = "gateway_error", status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class ArmAdapter(ABC):
    """机械臂能力接口。四类功能：热成像、手动控制、自动注射、自动避障。"""

    name = "abstract"

    # --- 状态 ---
    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """返回实时状态：模式、关节、TCP 位姿、安全、错误码、避障开关。"""

    # --- 手动控制 ---
    @abstractmethod
    def jog(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def move_pose(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def move_joint(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def home(self) -> dict[str, Any]: ...

    @abstractmethod
    def stop(self) -> dict[str, Any]: ...

    @abstractmethod
    def estop(self) -> dict[str, Any]: ...

    @abstractmethod
    def estop_reset(self) -> dict[str, Any]: ...

    @abstractmethod
    def set_mode(self, mode: str, origin: str = "web") -> dict[str, Any]: ...

    # --- 自动注射 ---
    @abstractmethod
    def inject_start(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def inject_abort(self, task_id: str, reason: str = "operator_abort") -> dict[str, Any]: ...

    # --- 热成像 ---
    @abstractmethod
    def get_thermal(self) -> dict[str, Any]: ...

    # --- 自动避障 ---
    @abstractmethod
    def get_obstacle_status(self) -> dict[str, Any]: ...

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Mock 机械臂：无硬件时的完整仿真，前后端联调、演示、自动化测试都用它
# ---------------------------------------------------------------------------


class MockArmAdapter(ArmAdapter):
    """6 轴协作臂仿真。行为刻意做得"像真的"：有模式、有到位判断、有急停、有避障偶发。"""

    name = "mock"

    def __init__(self, *, obstacle_probability: float = 0.02, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._obstacle_probability = obstacle_probability

        self._joints = [0.0, -35.0, 62.0, 0.0, 48.0, 0.0]
        self._joint_vel = [0.0] * 6
        self._control_mode = "idle"
        self._servo_on = False
        self._estop = False
        self._speed_override = 30.0
        self._obstacle_enabled = True
        self._obstacle_active: dict[str, Any] | None = None
        self._error_code: str | None = None
        self._error_message: str | None = None
        self._active_command_id: str | None = None
        self._queue_len = 0
        self._boot_at = time.time()
        self._last_motion_at = time.time()
        self._payload_kg = 1.2
        self._injection: dict[str, Any] | None = None

    # -- 内部工具 --
    def _tcp_pose(self) -> dict[str, float]:
        j = self._joints
        reach = 620.0
        x = reach * math.cos(math.radians(j[1] + j[2]))
        y = reach * math.sin(math.radians(j[0])) * 0.4
        z = 380.0 + reach * math.sin(math.radians(j[1] + j[2])) * 0.5
        return {
            "x": round(x, 2),
            "y": round(y, 2),
            "z": round(z, 2),
            "rx": round(180.0 + j[4], 2),
            "ry": round(j[3], 2),
            "rz": round(j[5], 2),
        }

    def _maybe_obstacle(self) -> None:
        if not self._obstacle_enabled or self._obstacle_active is not None:
            return
        if self._rng.random() < self._obstacle_probability:
            distance = round(self._rng.uniform(60.0, 220.0), 1)
            self._obstacle_active = {
                "obstacle_id": f"OBS-{int(time.time())}",
                "distance_mm": distance,
                "direction": self._rng.choice(["front", "left", "right"]),
                "class": self._rng.choice(["person", "rail", "equipment", "unknown"]),
                "confidence": round(self._rng.uniform(0.72, 0.97), 3),
                "action_taken": "slowdown" if distance > 150 else "stop",
                "speed_after_pct": 15.0 if distance > 150 else 0.0,
                "detected_at": _now().isoformat(),
            }

    # -- 状态 --
    def get_status(self) -> dict[str, Any]:
        with self._lock:
            self._maybe_obstacle()
            now = time.time()
            moving = self._control_mode in {"manual", "auto", "homing"} and (
                now - self._last_motion_at < 0.6
            )
            if self._estop:
                mode = "estop"
            elif self._error_code:
                mode = "fault"
            else:
                mode = self._control_mode
            safety = "emergency_stop" if self._estop else (
                "protective_stop" if self._obstacle_active and self._obstacle_active["action_taken"] == "stop"
                else "normal"
            )
            return {
                "device_online": True,
                "control_mode": mode,
                "servo_power_on": self._servo_on,
                "estop_pressed": self._estop,
                "is_moving": moving,
                "motion_done": not moving,
                "speed_override_pct": self._speed_override,
                "safety_state": safety,
                "joint_angles_deg": [round(v, 3) for v in self._joints],
                "joint_velocities": [round(v, 3) for v in self._joint_vel],
                "joint_torques": [round(3.5 + abs(v) * 0.15, 3) for v in self._joints],
                "joint_currents_a": [round(0.8 + abs(v) * 0.02, 3) for v in self._joints],
                "joint_temps_c": [round(38.0 + abs(v) * 0.05, 2) for v in self._joints],
                "tcp_pose": self._tcp_pose(),
                "tcp_quaternion": {"qw": 0.707, "qx": 0.0, "qy": 0.707, "qz": 0.0},
                "tcp_linear_velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
                "tcp_force": {"fx": 0.0, "fy": 0.0, "fz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0},
                "tool_frame": "TOOL-01",
                "base_frame": "BASE-01",
                "payload_kg": self._payload_kg,
                "obstacle_avoidance_enabled": self._obstacle_enabled,
                "obstacle_distance_mm": (self._obstacle_active or {}).get("distance_mm"),
                "error_code": self._error_code,
                "error_message": self._error_message,
                "warning_codes": [],
                "queue_len": self._queue_len,
                "active_command_id": self._active_command_id,
                "uptime_s": int(time.time() - self._boot_at),
                "firmware_version": "mock-1.0.0",
                "controller_temp_c": round(46.0 + self._rng.uniform(-1.5, 1.5), 2),
                "injection": dict(self._injection) if self._injection else None,
            }

    # -- 手动控制 --
    def _require_operable(self) -> None:
        if self._estop:
            raise ArmGatewayError("急停状态下不接受运动指令", code="estop_active", status=409)
        if self._error_code:
            raise ArmGatewayError(
                f"机械臂处于故障状态：{self._error_message or self._error_code}",
                code="arm_fault",
                status=409,
            )

    def jog(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._require_operable()
            axis = str(payload.get("axis", "x")).lower()
            direction = int(payload.get("direction", 1))
            step = float(payload.get("step", 1.0))
            speed = float(payload.get("speed_pct", self._speed_override))
            speed = max(1.0, min(speed, 100.0))
            self._speed_override = speed
            delta = direction * step * (speed / 100.0)

            if axis in {"j1", "j2", "j3", "j4", "j5", "j6"}:
                idx = int(axis[1]) - 1
                self._joints[idx] = round(self._joints[idx] + delta, 3)
            elif axis in {"x", "y", "z"}:
                self._joints[1] = round(self._joints[1] + delta * 0.05, 3)
            else:
                raise ArmGatewayError(f"不支持的点动轴：{axis}", code="bad_axis", status=400)

            self._control_mode = "manual"
            self._servo_on = True
            self._last_motion_at = time.time()
            return {
                "accepted": True,
                "arm_command_id": f"JOG-{int(time.time() * 1000)}",
                "motion_done": True,
                "target": {"axis": axis, "direction": direction, "step": step, "speed_pct": speed},
            }

    def move_pose(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._require_operable()
            pose = payload.get("pose") or {}
            if not pose:
                raise ArmGatewayError("缺少 pose 参数", code="bad_request", status=400)
            self._control_mode = "manual"
            self._servo_on = True
            self._speed_override = float(payload.get("speed_pct", self._speed_override))
            self._joints[1] = round(self._joints[1] - 2.0, 3)
            self._last_motion_at = time.time()
            return {
                "accepted": True,
                "arm_command_id": f"MOVE-{int(time.time() * 1000)}",
                "motion_done": True,
                "target_pose": pose,
            }

    def move_joint(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._require_operable()
            angles = payload.get("joint_angles_deg")
            if not isinstance(angles, list) or not angles:
                raise ArmGatewayError("缺少 joint_angles_deg", code="bad_request", status=400)
            for idx, value in enumerate(angles[: len(self._joints)]):
                self._joints[idx] = round(float(value), 3)
            self._control_mode = "manual"
            self._servo_on = True
            self._last_motion_at = time.time()
            return {
                "accepted": True,
                "arm_command_id": f"JOINT-{int(time.time() * 1000)}",
                "motion_done": True,
                "joint_angles_deg": [round(v, 3) for v in self._joints],
            }

    def home(self) -> dict[str, Any]:
        with self._lock:
            self._require_operable()
            self._control_mode = "homing"
            self._joints = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            self._servo_on = True
            self._last_motion_at = time.time()
            return {"accepted": True, "arm_command_id": f"HOME-{int(time.time())}", "homed": True}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._control_mode = "idle"
            self._joint_vel = [0.0] * 6
            self._last_motion_at = 0.0
            return {"accepted": True, "stopped": True}

    def estop(self) -> dict[str, Any]:
        with self._lock:
            self._estop = True
            self._control_mode = "estop"
            self._servo_on = False
            self._obstacle_active = None
            if self._injection:
                self._injection = {**self._injection, "phase": "aborted", "fail_reason": "estop"}
            return {"accepted": True, "estop_pressed": True, "arm_command_id": f"ESTOP-{int(time.time())}"}

    def estop_reset(self) -> dict[str, Any]:
        with self._lock:
            self._estop = False
            self._error_code = None
            self._error_message = None
            self._control_mode = "idle"
            return {"accepted": True, "estop_pressed": False, "requires_home": True}

    def set_mode(self, mode: str, origin: str = "web") -> dict[str, Any]:
        with self._lock:
            if mode not in {"idle", "manual", "auto"}:
                raise ArmGatewayError(f"不支持的模式：{mode}", code="bad_mode", status=400)
            if self._estop and mode != "idle":
                raise ArmGatewayError("急停状态下只能切到 idle", code="estop_active", status=409)
            self._control_mode = mode
            self._servo_on = mode in {"manual", "auto"}
            return {"accepted": True, "control_mode": mode, "origin": origin}

    # -- 自动注射 --
    def inject_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._require_operable()
            if self._injection and self._injection.get("phase") not in {"completed", "failed", "aborted"}:
                raise ArmGatewayError(
                    "机械臂已有注射流程在执行", code="injection_busy", status=409
                )
            self._control_mode = "auto"
            self._servo_on = True
            now = _now().isoformat()
            self._injection = {
                "arm_task_id": f"INJ-{int(time.time() * 1000)}",
                "phase": "locating",
                "started_at": now,
                "target_point": payload.get("target_point"),
                "dose_ml": payload.get("dose_ml"),
                "depth_mm": payload.get("depth_mm"),
                "progress_pct": 0.0,
            }
            self._last_motion_at = time.time()
            return {"accepted": True, **self._injection}

    def inject_abort(self, task_id: str, reason: str = "operator_abort") -> dict[str, Any]:
        with self._lock:
            if self._injection:
                self._injection = {**self._injection, "phase": "aborted", "fail_reason": reason}
            self._control_mode = "idle"
            return {"accepted": True, "aborted": True, "reason": reason, "task_id": task_id}

    # -- 热成像 --
    def get_thermal(self) -> dict[str, Any]:
        with self._lock:
            ambient = round(26.5 + self._rng.uniform(-1.0, 1.0), 2)
            body = round(38.6 + self._rng.uniform(-0.6, 0.9), 2)
            site = round(body + self._rng.uniform(-0.3, 0.4), 2)
            tmax = round(body + self._rng.uniform(1.0, 2.0), 2)
            tmin = round(ambient - self._rng.uniform(0.5, 2.0), 2)
            tavg = round((body + ambient) / 2 + self._rng.uniform(-0.5, 0.5), 2)
            return {
                "captured_at": _now().isoformat(),
                "emissivity": 0.95,
                "distance_m": round(self._rng.uniform(0.5, 1.2), 3),
                "reflected_temp_c": ambient,
                "atmospheric_temp_c": ambient,
                "humidity_pct": round(self._rng.uniform(45.0, 65.0), 1),
                "temp_range_min_c": -20.0,
                "temp_range_max_c": 150.0,
                "temp_max_c": tmax,
                "temp_min_c": tmin,
                "temp_avg_c": tavg,
                "temp_center_c": round(body + self._rng.uniform(-0.5, 0.5), 2),
                "matrix_width": 640,
                "matrix_height": 480,
                "body_temp_c": body,
                "injected_site_temp_c": site,
                "ambient_temp_c": ambient,
                "rois": [
                    {
                        "roi_name": "injection_site",
                        "shape": "rect",
                        "geometry": {"x1": 300, "y1": 220, "x2": 360, "y2": 280},
                        "temp_max_c": round(site + 0.4, 2),
                        "temp_min_c": round(site - 0.5, 2),
                        "temp_avg_c": site,
                    },
                    {
                        "roi_name": "back_average",
                        "shape": "rect",
                        "geometry": {"x1": 180, "y1": 160, "x2": 460, "y2": 320},
                        "temp_max_c": tmax,
                        "temp_min_c": round(body - 1.2, 2),
                        "temp_avg_c": body,
                    },
                ],
            }

    # -- 自动避障 --
    def get_obstacle_status(self) -> dict[str, Any]:
        with self._lock:
            if self._obstacle_active is not None and self._rng.random() < 0.25:
                cleared = dict(self._obstacle_active)
                self._obstacle_active = None
                return {
                    "enabled": self._obstacle_enabled,
                    "active": False,
                    "cleared_event": {**cleared, "cleared_at": _now().isoformat()},
                }
            active = self._obstacle_active
            return {
                "enabled": self._obstacle_enabled,
                "active": active is not None,
                "sensor_type": "depth_camera",
                "min_distance_mm": (active or {}).get("distance_mm"),
                "event": active,
            }

    def set_obstacle_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._obstacle_enabled = bool(enabled)
            if not enabled:
                self._obstacle_active = None
            return {"enabled": self._obstacle_enabled}


# ---------------------------------------------------------------------------
# HTTP 机械臂：对接外包方的真实控制服务
# ---------------------------------------------------------------------------


class HttpArmAdapter(ArmAdapter):
    """按 .env 中的 ARM_PATH_* 映射调用外包方 REST 接口。

    拿到外包方文档后，通常只需要调整这里 _pick() 的字段名映射。
    """

    name = "http"

    def __init__(self, base_url: str, paths: dict[str, str], timeout_s: float = 8.0, token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.paths = paths
        self.timeout_s = timeout_s
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s, headers=headers)

    # -- 内部 --
    def _call(self, key: str, method: str = "POST", json_body: dict[str, Any] | None = None,
              timeout: float | None = None) -> dict[str, Any]:
        path = self.paths.get(key)
        if not path:
            raise ArmGatewayError(f"未配置接口路径：{key}", code="path_not_configured", status=500)
        try:
            resp = self._client.request(method, path, json=json_body, timeout=timeout or self.timeout_s)
        except httpx.TimeoutException as exc:
            raise ArmGatewayError(f"机械臂接口超时：{path}", code="arm_timeout", status=504) from exc
        except httpx.RequestError as exc:
            raise ArmGatewayError(f"无法连接机械臂服务：{exc}", code="arm_unreachable", status=503) from exc
        if resp.status_code >= 400:
            detail = resp.text[:300]
            raise ArmGatewayError(
                f"机械臂返回 HTTP {resp.status_code}: {detail}",
                code="arm_rejected",
                status=409 if resp.status_code in (400, 409) else 502,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ArmGatewayError("机械臂返回内容不是 JSON", code="arm_bad_response", status=502) from exc
        return payload if isinstance(payload, dict) else {"data": payload}

    def get_status(self) -> dict[str, Any]:
        raw = self._call("status", "GET")
        # 字段归一化：把外包方的命名映射成内部统一结构
        return {
            "device_online": bool(raw.get("online", True)),
            "control_mode": raw.get("mode") or raw.get("control_mode") or "idle",
            "servo_power_on": raw.get("servo_on"),
            "estop_pressed": bool(raw.get("estop") or raw.get("estop_pressed") or False),
            "is_moving": raw.get("moving"),
            "motion_done": raw.get("motion_done", raw.get("in_position")),
            "speed_override_pct": raw.get("speed_override", raw.get("speed_override_pct")),
            "safety_state": raw.get("safety_state"),
            "joint_angles_deg": raw.get("joints") or raw.get("joint_angles_deg"),
            "joint_velocities": raw.get("joint_velocities"),
            "joint_torques": raw.get("joint_torques"),
            "joint_currents_a": raw.get("joint_currents"),
            "joint_temps_c": raw.get("joint_temps"),
            "tcp_pose": raw.get("tcp") or raw.get("tcp_pose"),
            "tcp_quaternion": raw.get("tcp_quaternion"),
            "tcp_linear_velocity": raw.get("tcp_velocity"),
            "tcp_force": raw.get("tcp_force") or raw.get("force"),
            "tool_frame": raw.get("tool_frame"),
            "base_frame": raw.get("base_frame"),
            "payload_kg": raw.get("payload_kg"),
            "obstacle_avoidance_enabled": raw.get("obstacle_avoidance_enabled"),
            "obstacle_distance_mm": raw.get("obstacle_distance_mm"),
            "error_code": raw.get("error_code"),
            "error_message": raw.get("error_message") or raw.get("message"),
            "warning_codes": raw.get("warnings") or [],
            "queue_len": raw.get("queue_len"),
            "active_command_id": raw.get("active_command_id"),
            "uptime_s": raw.get("uptime_s"),
            "firmware_version": raw.get("firmware_version"),
            "controller_temp_c": raw.get("controller_temp_c"),
            "injection": raw.get("injection"),
            "raw": raw,
        }

    def jog(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("jog", "POST", payload)

    def move_pose(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("move_pose", "POST", payload)

    def move_joint(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("move_joint", "POST", payload)

    def home(self) -> dict[str, Any]:
        return self._call("home", "POST", {})

    def stop(self) -> dict[str, Any]:
        return self._call("stop", "POST", {})

    def estop(self) -> dict[str, Any]:
        return self._call("estop", "POST", {}, timeout=2.0)

    def estop_reset(self) -> dict[str, Any]:
        return self._call("estop_reset", "POST", {})

    def set_mode(self, mode: str, origin: str = "web") -> dict[str, Any]:
        return self._call("set_mode", "POST", {"mode": mode, "origin": origin})

    def inject_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("inject_start", "POST", payload)

    def inject_abort(self, task_id: str, reason: str = "operator_abort") -> dict[str, Any]:
        return self._call("inject_abort", "POST", {"task_id": task_id, "reason": reason})

    def get_thermal(self) -> dict[str, Any]:
        return self._call("thermal", "GET")

    def get_obstacle_status(self) -> dict[str, Any]:
        return self._call("obstacle", "GET")

    def close(self) -> None:
        self._client.close()
