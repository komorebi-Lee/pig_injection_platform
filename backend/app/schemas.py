"""Pydantic 请求/响应模型。前端契约以此为准，与 docs/02_后端接口契约_v1.md 一一对应。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------


class Envelope(BaseModel):
    ok: bool = True
    data: Any = None
    message: str | None = None


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    ok: Literal[False] = False
    error: str = Field(description="机器可读的错误码")
    message: str = Field(description="中文可读的错误说明")
    detail: Any | None = None


# ---------------------------------------------------------------------------
# 台账
# ---------------------------------------------------------------------------


class PenIn(BaseModel):
    pen_code: str = Field(max_length=64)
    pen_name: str | None = None
    barn: str | None = None
    area_name: str | None = None
    capacity: int | None = None
    guardrail_camera_code: str | None = None
    arm_camera_code: str | None = None
    arm_device_code: str | None = None
    status: str = "active"
    remark: str | None = None


class PenOut(ORMModel):
    id: int
    pen_code: str
    pen_name: str | None
    barn: str | None
    area_name: str | None
    capacity: int | None
    guardrail_camera_code: str | None
    arm_camera_code: str | None
    arm_device_code: str | None
    status: str
    remark: str | None
    created_at: datetime
    updated_at: datetime


class PigIn(BaseModel):
    ear_tag: str | None = Field(default=None, max_length=64)
    pen_id: int | None = None
    breed: str | None = None
    sex: str | None = None
    birth_date: datetime | None = None
    weight_kg: float | None = None
    health_status: str = "healthy"
    remark: str | None = None


class PigOut(ORMModel):
    id: int
    ear_tag: str | None
    pen_id: int | None
    breed: str | None
    sex: str | None
    weight_kg: float | None
    health_status: str
    last_injection_at: datetime | None
    remark: str | None


class DeviceOut(ORMModel):
    id: int
    device_code: str
    device_type: str
    vendor: str | None
    model: str | None
    serial_number: str | None
    firmware_version: str | None
    protocol: str | None
    endpoint: str | None
    mounted_on: str | None
    pen_id: int | None
    status: str
    last_seen_at: datetime | None
    remark: str | None


# ---------------------------------------------------------------------------
# 机械臂：状态与手动控制
# ---------------------------------------------------------------------------


class JointVector(BaseModel):
    values: list[float]


class Pose(BaseModel):
    x: float
    y: float
    z: float
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0


class ArmStatusOut(BaseModel):
    """机械臂实时状态。前端实时面板直接渲染这些字段。"""

    device_code: str
    device_online: bool
    control_mode: str = Field(description="idle|manual|auto|homing|estop|fault")
    servo_power_on: bool | None = None
    estop_pressed: bool | None = None
    is_moving: bool | None = None
    motion_done: bool | None = None
    speed_override_pct: float | None = None
    safety_state: str | None = None
    joint_angles_deg: list[float] | None = None
    joint_torques: list[float] | None = None
    joint_currents_a: list[float] | None = None
    joint_temps_c: list[float] | None = None
    tcp_pose: dict[str, float] | None = None
    tcp_force: dict[str, float] | None = None
    tool_frame: str | None = None
    payload_kg: float | None = None
    obstacle_avoidance_enabled: bool | None = None
    obstacle_distance_mm: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    warning_codes: list[Any] | None = None
    queue_len: int | None = None
    uptime_s: int | None = None
    firmware_version: str | None = None
    controller_temp_c: float | None = None
    injection: dict[str, Any] | None = None
    sampled_at: datetime | None = None


class RequestMeta(BaseModel):
    """所有控制类接口都建议带上的公共字段。"""

    request_id: str | None = Field(
        default=None,
        max_length=64,
        description="幂等键。前端生成 UUID；相同值重复提交只会下发一次。不传则由后端生成。",
    )
    operator_id: int | None = None
    operator_name: str | None = None
    device_code: str | None = Field(default=None, description="默认 ARM-01")


class JogRequest(RequestMeta):
    axis: Literal["x", "y", "z", "j1", "j2", "j3", "j4", "j5", "j6"]
    direction: Literal[1, -1] = 1
    step: float = Field(default=1.0, gt=0, le=100, description="单次点动步长")
    speed_pct: float = Field(default=20.0, gt=0, le=100, description="速度倍率 %")


class MovePoseRequest(RequestMeta):
    pose: Pose
    speed_pct: float = Field(default=20.0, gt=0, le=100)
    frame: str = "base"


class MoveJointRequest(RequestMeta):
    joint_angles_deg: list[float] = Field(min_length=1, max_length=12)
    speed_pct: float = Field(default=20.0, gt=0, le=100)


class DeviceRequest(RequestMeta):
    """无参数指令的请求体（回零 / 停止 / 急停 / 急停复位）。

    只带公共字段，前端传 {} 或 {"request_id": "..."} 即可。
    """


class ModeRequest(RequestMeta):
    mode: Literal["idle", "manual", "auto"]


class ObstacleToggleRequest(RequestMeta):
    enabled: bool


class CommandAck(BaseModel):
    request_id: str
    command_type: str
    accepted: bool
    result: str
    arm_command_id: str | None = None
    message: str | None = None
    duration_ms: int | None = None
    response: dict[str, Any] | None = None


class CommandLogOut(ORMModel):
    id: int
    request_id: Any
    device_id: int
    operator_id: int | None
    command_type: str
    source: str
    result: str
    accepted: bool | None
    reject_reason: str | None
    error_code: str | None
    duration_ms: int | None
    payload: dict[str, Any] | None
    response: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None


# ---------------------------------------------------------------------------
# 热成像
# ---------------------------------------------------------------------------


class ThermalRoiOut(ORMModel):
    id: int
    roi_name: str
    shape: str | None
    geometry: dict[str, Any] | None
    temp_max_c: float | None
    temp_min_c: float | None
    temp_avg_c: float | None


class ThermalOut(ORMModel):
    id: int
    device_id: int | None
    task_id: int | None
    capture_no: str | None
    emissivity: float | None
    distance_m: float | None
    reflected_temp_c: float | None
    atmospheric_temp_c: float | None
    humidity_pct: float | None
    temp_range_min_c: float | None
    temp_range_max_c: float | None
    temp_max_c: float | None
    temp_min_c: float | None
    temp_avg_c: float | None
    temp_center_c: float | None
    matrix_width: int | None
    matrix_height: int | None
    body_temp_c: float | None
    injected_site_temp_c: float | None
    ambient_temp_c: float | None
    is_fever: bool | None
    thermal_asset_id: int | None
    visible_asset_id: int | None
    raw_asset_id: int | None
    captured_at: datetime


# ---------------------------------------------------------------------------
# 避障
# ---------------------------------------------------------------------------


class ObstacleEventOut(ORMModel):
    id: int
    device_id: int | None
    task_id: int | None
    event_type: str
    sensor_type: str | None
    obstacle_distance_mm: float | None
    obstacle_direction: str | None
    obstacle_class: str | None
    detection_confidence: float | None
    action_taken: str | None
    speed_before_pct: float | None
    speed_after_pct: float | None
    resumed: bool | None
    detected_at: datetime
    cleared_at: datetime | None
    duration_ms: int | None


# ---------------------------------------------------------------------------
# 注射任务
# ---------------------------------------------------------------------------


class InjectionCreateRequest(RequestMeta):
    pen_id: int | None = None
    pig_id: int | None = None
    mode: Literal["auto", "manual"] = "auto"
    batch_no: str | None = None
    drug_name: str | None = None
    drug_batch_no: str | None = None
    dose_target_ml: float | None = Field(default=None, ge=0, le=100)
    depth_mm: float | None = Field(default=None, gt=0, le=60)
    needle_id: str | None = None
    target_source: Literal["guardrail_camera", "arm_camera", "manual_teach"] = "guardrail_camera"
    target_point_base: dict[str, Any] | None = None
    target_point_pixel: dict[str, Any] | None = None
    target_confidence: float | None = Field(default=None, ge=0, le=1)
    auto_start: bool = True


class InjectionTaskOut(ORMModel):
    id: int
    task_no: str
    batch_no: str | None
    device_id: int
    pen_id: int | None
    pig_id: int | None
    ear_tag_snapshot: str | None
    operator_name: str | None
    mode: str
    status: str
    fail_reason: str | None
    fail_message: str | None
    target_source: str | None
    target_point_base: dict[str, Any] | None
    target_point_pixel: dict[str, Any] | None
    target_confidence: float | None
    target_depth_mm: float | None
    actual_entry_point: dict[str, Any] | None
    actual_depth_mm: float | None
    position_error_mm: float | None
    needle_id: str | None
    drug_name: str | None
    drug_batch_no: str | None
    dose_target_ml: float | None
    dose_ml: float | None
    peak_force_n: float | None
    body_temp_c: float | None
    ambient_temp_c: float | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    phase_durations_ms: dict[str, Any] | None
    obstacle_triggered: bool
    retry_count: int
    created_at: datetime
    updated_at: datetime


class InjectionEventOut(ORMModel):
    id: int
    task_id: int
    event_type: str
    phase: str | None
    message: str | None
    payload: dict[str, Any] | None
    occurred_at: datetime


class InjectionAbortRequest(RequestMeta):
    reason: str = "operator_abort"


# ---------------------------------------------------------------------------
# 告警 / 媒体 / 系统
# ---------------------------------------------------------------------------


class AlarmOut(ORMModel):
    id: int
    alarm_no: str
    device_id: int | None
    task_id: int | None
    level: str
    category: str
    code: str | None
    title: str
    message: str | None
    value: float | None
    threshold: float | None
    status: str
    acknowledged_by: int | None
    acknowledged_at: datetime | None
    cleared_at: datetime | None
    created_at: datetime


class MediaAssetOut(ORMModel):
    id: int
    asset_type: str
    category: str
    task_id: int | None
    device_id: int | None
    file_name: str
    mime_type: str | None
    file_size_bytes: int | None
    width: int | None
    height: int | None
    duration_ms: int | None
    captured_at: datetime | None
    created_at: datetime


class SystemHealth(BaseModel):
    ok: bool
    app_version: str
    database: str
    arm_driver: str
    arm_online: bool
    websocket_clients: int
    telemetry_cycles: int
    telemetry_last_error: str | None
    server_time: datetime
