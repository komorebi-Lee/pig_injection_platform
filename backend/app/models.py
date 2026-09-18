"""SQLAlchemy ORM 模型：机械臂猪只背部注射系统的全部业务表。

本文件是数据库结构的**唯一权威来源**（single source of truth）。
`schema.sql` 由 scripts/dump_schema.py 从这些模型生成，请勿手工改 SQL。

命名约定：
- 主键统一 `id` (BIGSERIAL)，业务编号统一 `*_no` / `*_code` 并加唯一索引
- 时间统一 `TIMESTAMPTZ`（带时区），服务端按 Asia/Shanghai 写入
- 机械臂/相机的原始报文一律用 JSONB 保留，便于事后排查与前端展示
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# 1. 台账：栏位 / 猪只 / 操作员 / 设备
# ---------------------------------------------------------------------------


class Pen(Base, TimestampMixin):
    """栏位（护栏围出的猪栏）。一个栏位对应一套"护栏相机 + 臂上相机 + 机械臂"。"""

    __tablename__ = "pens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pen_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="栏位编号，如 A-01")
    pen_name: Mapped[str | None] = mapped_column(String(128))
    barn: Mapped[str | None] = mapped_column(String(64), comment="栋舍")
    area_name: Mapped[str | None] = mapped_column(String(128), comment="区域/单元")
    capacity: Mapped[int | None] = mapped_column(Integer, comment="设计存栏头数")
    guardrail_camera_code: Mapped[str | None] = mapped_column(String(64), comment="护栏相机 device_code")
    arm_camera_code: Mapped[str | None] = mapped_column(String(64), comment="臂上相机 device_code")
    arm_device_code: Mapped[str | None] = mapped_column(String(64), comment="该栏位机械臂 device_code")
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, comment="active|inactive|maintenance")
    remark: Mapped[str | None] = mapped_column(Text)

    pigs: Mapped[list[Pig]] = relationship(back_populates="pen")


class Pig(Base, TimestampMixin):
    """猪只档案。允许耳标体识别失败时留空，靠 pen_id + 时间定位。"""

    __tablename__ = "pigs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ear_tag: Mapped[str | None] = mapped_column(String(64), unique=True, comment="耳标号")
    pen_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pens.id", ondelete="SET NULL"))
    breed: Mapped[str | None] = mapped_column(String(64), comment="品种")
    sex: Mapped[str | None] = mapped_column(String(16))
    birth_date: Mapped[date | None] = mapped_column(Date)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), comment="体重 kg")
    health_status: Mapped[str] = mapped_column(String(24), default="healthy", nullable=False, comment="healthy|abnormal|isolated|treated")
    last_injection_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)

    pen: Mapped[Pen | None] = relationship(back_populates="pigs")


class Operator(Base, TimestampMixin):
    """操作员。手动控制、注射指令、告警确认都要记录到人。"""

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(24), default="operator", nullable=False, comment="admin|operator|viewer")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Device(Base, TimestampMixin):
    """设备台账：机械臂、护栏相机、臂上相机、工控机。外包方交付的设备信息填这里。"""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="内部唯一编号，如 ARM-01")
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="arm|camera_guardrail|camera_arm|camera_thermal|controller")
    vendor: Mapped[str | None] = mapped_column(String(64), comment="厂商/外包方")
    model: Mapped[str | None] = mapped_column(String(64))
    serial_number: Mapped[str | None] = mapped_column(String(128))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    protocol: Mapped[str | None] = mapped_column(String(32), comment="http|websocket|modbus_tcp|ros2|serial")
    endpoint: Mapped[str | None] = mapped_column(String(255), comment="如 http://192.168.1.50:6000")
    mounted_on: Mapped[str | None] = mapped_column(String(32), comment="guardrail|arm|fixed|mobile")
    pen_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pens.id", ondelete="SET NULL"))
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="offline", nullable=False, comment="online|offline|fault|maintenance")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# 2. 实时状态：心跳 / 机械臂遥测
# ---------------------------------------------------------------------------


class DeviceHeartbeat(Base):
    """设备心跳历史。后端网关心跳轮询一次写一行，用于画在线率曲线与排查掉线。"""

    __tablename__ = "device_heartbeats"
    __table_args__ = (Index("ix_device_heartbeats_device_time", "device_id", "sampled_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    online: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, comment="网关到设备的往返耗时")
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    controller_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="控制柜/主板温度")
    uptime_s: Mapped[int | None] = mapped_column(BigInteger, comment="设备本次上电运行时长")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="原始心跳报文")
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ArmStatusSample(Base):
    """机械臂遥测采样（高频表，后端轮询写入）。

    这是"机械臂返回了哪些数据"的落地表，覆盖姿态、关节、力/电流、温度、
    安全状态、避障开关、错误码。前端实时面板、历史曲线、故障复盘都查它。
    """

    __tablename__ = "arm_status_samples"
    __table_args__ = (
        Index("ix_arm_status_device_time", "device_id", "sampled_at"),
        Index("ix_arm_status_sampled_at", "sampled_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)

    # --- 运行模式与安全 ---
    control_mode: Mapped[str] = mapped_column(String(24), nullable=False, comment="idle|manual|auto|homing|estop|fault")
    servo_power_on: Mapped[bool | None] = mapped_column(Boolean, comment="伺服使能")
    estop_pressed: Mapped[bool | None] = mapped_column(Boolean, comment="急停是否按下")
    is_moving: Mapped[bool | None] = mapped_column(Boolean)
    motion_done: Mapped[bool | None] = mapped_column(Boolean, comment="是否运动到位")
    speed_override_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="速度倍率 0-100")
    safety_state: Mapped[str | None] = mapped_column(String(32), comment="normal|reduced|protective_stop|emergency_stop")

    # --- 关节（6 轴，统一用 JSONB 数组，避免轴数变化时改表） ---
    joint_angles_deg: Mapped[list[Any] | None] = mapped_column(JSONB, comment="[J1..J6] 角度")
    joint_velocities: Mapped[list[Any] | None] = mapped_column(JSONB, comment="各轴角速度 deg/s")
    joint_torques: Mapped[list[Any] | None] = mapped_column(JSONB, comment="各轴力矩 N·m")
    joint_currents_a: Mapped[list[Any] | None] = mapped_column(JSONB, comment="各轴电流 A")
    joint_temps_c: Mapped[list[Any] | None] = mapped_column(JSONB, comment="各轴电机温度 ℃")

    # --- 末端位姿 ---
    tcp_pose: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="{x,y,z,rx,ry,rz} mm/deg")
    tcp_quaternion: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="{qw,qx,qy,qz}")
    tcp_linear_velocity: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="{vx,vy,vz} mm/s")
    tcp_force: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="末端六维力/力矩 {fx,fy,fz,tx,ty,tz}")
    tool_frame: Mapped[str | None] = mapped_column(String(32), comment="工具坐标系编号")
    base_frame: Mapped[str | None] = mapped_column(String(32), comment="基坐标系编号")
    payload_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), comment="负载")

    # --- 避障与错误 ---
    obstacle_avoidance_enabled: Mapped[bool | None] = mapped_column(Boolean)
    obstacle_distance_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), comment="最近障碍物距离")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    warning_codes: Mapped[list[Any] | None] = mapped_column(JSONB, comment="告警码列表")
    queue_len: Mapped[int | None] = mapped_column(Integer, comment="机械臂内部指令队列长度")
    active_command_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="正在执行的 control_commands.request_id")

    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="机械臂 status 接口原始返回")
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# 3. 指令审计：所有下发到机械臂的指令
# ---------------------------------------------------------------------------


class ControlCommand(Base):
    """指令审计表。前端每一次操作（点动、回零、急停、注射）都在这里留痕。

    `request_id` 是幂等键：前端可自带，后端也会生成。相同 request_id 重复提交
    直接返回上一次结果，不重复下发——这是防止"双击打两针"的第一道闸门。
    """

    __tablename__ = "control_commands"
    __table_args__ = (
        Index("ix_control_commands_device_time", "device_id", "created_at"),
        Index("ix_control_commands_type_time", "command_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operators.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(BigInteger, comment="若该指令属于某次注射任务")
    command_type: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        comment="estop|estop_reset|home|jog|move_pose|move_joint|stop|set_mode|inject_start|inject_abort|thermal_capture|obstacle_enable|obstacle_disable",
    )
    source: Mapped[str] = mapped_column(String(24), default="web", nullable=False, comment="web|api|system|local")
    client_ip: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="下发给机械臂的参数原文")
    result: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, comment="pending|running|success|failed|rejected|timeout")
    accepted: Mapped[bool | None] = mapped_column(Boolean, comment="机械臂是否受理")
    reject_reason: Mapped[str | None] = mapped_column(Text)
    arm_command_id: Mapped[str | None] = mapped_column(String(128), comment="机械臂返回的指令号")
    error_code: Mapped[str | None] = mapped_column(String(64))
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="机械臂原始返回")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManualControlSession(Base):
    """手动控制会话。一次"进入手动模式 -> 离开手动模式"记一条。"""

    __tablename__ = "manual_control_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operators.id", ondelete="SET NULL"))
    operator_name: Mapped[str | None] = mapped_column(String(64))
    client_ip: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(32), comment="normal|estop|timeout|disconnect|auto_takeover")
    jog_command_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_speed_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="本次会话用过的最大速度倍率")
    estop_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    remark: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# 4. 注射业务主线
# ---------------------------------------------------------------------------


class InjectionTask(Base, TimestampMixin):
    """一次注射任务 = 对一头猪完成一次进针给药（成功或失败都留记录）。"""

    __tablename__ = "injection_tasks"
    __table_args__ = (
        Index("ix_injection_tasks_status_time", "status", "created_at"),
        Index("ix_injection_tasks_pig_time", "pig_id", "created_at"),
        CheckConstraint("dose_ml IS NULL OR dose_ml >= 0", name="ck_injection_tasks_dose_nonnegative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="业务编号 T20260917-0001")
    batch_no: Mapped[str | None] = mapped_column(String(64), comment="批次巡视编号，一次巡视含多条注射任务")
    device_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False)
    pen_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pens.id", ondelete="SET NULL"))
    pig_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pigs.id", ondelete="SET NULL"))
    ear_tag_snapshot: Mapped[str | None] = mapped_column(String(64), comment="执行时读到的耳标，避免后续档案被改")
    operator_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operators.id", ondelete="SET NULL"))
    operator_name: Mapped[str | None] = mapped_column(String(64))

    mode: Mapped[str] = mapped_column(String(24), default="auto", nullable=False, comment="auto|manual")
    status: Mapped[str] = mapped_column(
        String(24),
        default="created",
        nullable=False,
        comment="created|queued|locating|aligning|inserting|injecting|retracting|completed|failed|aborted",
    )
    fail_reason: Mapped[str | None] = mapped_column(String(64), comment="结构化的失败原因码")
    fail_message: Mapped[str | None] = mapped_column(Text)

    # --- 目标点（机械臂视觉/热成像定位结果） ---
    target_source: Mapped[str | None] = mapped_column(String(32), comment="guardrail_camera|arm_camera|manual_teach")
    target_point_base: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="基坐标系目标 {x,y,z} mm")
    target_point_pixel: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="图像像素坐标 {u,v,width,height,frame_id}")
    target_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), comment="定位置信度 0-1")
    target_depth_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), comment="计划进针深度")
    target_angle_deg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), comment="计划进针角度")

    # --- 实际执行结果 ---
    actual_entry_point: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="实际进针点 {x,y,z}")
    actual_depth_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), comment="实际进针深度")
    actual_angle_deg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    position_error_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), comment="目标与实际偏差")

    # --- 耗材与药品 ---
    needle_id: Mapped[str | None] = mapped_column(String(64), comment="针头编号，用于计数更换")
    drug_name: Mapped[str | None] = mapped_column(String(128))
    drug_batch_no: Mapped[str | None] = mapped_column(String(64))
    dose_ml: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), comment="实际注射剂量 ml")
    dose_target_ml: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), comment="计划剂量")

    # --- 力学与温度 ---
    peak_force_n: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), comment="进针阻力峰值 N")
    peak_torque_nm: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    body_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="注射部位体表温度 ℃")
    ambient_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="环境温度 ℃")

    # --- 时间 ---
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    phase_durations_ms: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="{locating, aligning, inserting, injecting, retracting} 各阶段耗时"
    )

    obstacle_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="机械臂 start_injection 的原始返回")


class InjectionEvent(Base):
    """注射过程时间线。前端"过程回放"和时间轴图表直接查这张表。"""

    __tablename__ = "injection_events"
    __table_args__ = (Index("ix_injection_events_task_time", "task_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("injection_tasks.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        comment="phase_change|needle_insert|drug_inject|needle_retract|force_sample|vision_detect|obstacle_hit|thermal_sample|alarm|abort|error",
    )
    phase: Mapped[str | None] = mapped_column(String(24))
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# 5. 感知：视觉 / 热成像 / 避障
# ---------------------------------------------------------------------------


class VisionDetection(Base):
    """视觉检测结果（护栏相机全局限位 + 臂上相机局部对位）。"""

    __tablename__ = "vision_detections"
    __table_args__ = (
        Index("ix_vision_detections_device_time", "device_id", "captured_at"),
        Index("ix_vision_detections_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="SET NULL"))
    camera_role: Mapped[str] = mapped_column(String(24), nullable=False, comment="guardrail|arm")
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("injection_tasks.id", ondelete="CASCADE"))
    frame_seq: Mapped[int | None] = mapped_column(BigInteger)
    class_name: Mapped[str] = mapped_column(String(48), nullable=False, comment="pig|back_line|injection_point|needle|obstacle|person")
    detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    pig_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pigs.id", ondelete="SET NULL"))
    track_id: Mapped[str | None] = mapped_column(String(64), comment="跟踪 ID")
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="{x1,y1,x2,y2} 像素坐标")
    keypoints: Mapped[list[Any] | None] = mapped_column(JSONB, comment="关键点/背脊线折线")
    injection_point_pixel: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="{u,v} 建议注射点")
    distance_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), comment="相机到目标距离（深度）")
    image_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联 media_assets.id")
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ThermalCapture(Base):
    """热成像采集记录。测温参数 + 全幅统计 + 目标区域温度。"""

    __tablename__ = "thermal_captures"
    __table_args__ = (
        Index("ix_thermal_captures_device_time", "device_id", "captured_at"),
        Index("ix_thermal_captures_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("injection_tasks.id", ondelete="CASCADE"))
    capture_no: Mapped[str | None] = mapped_column(String(64))
    frame_seq: Mapped[int | None] = mapped_column(BigInteger)

    # --- 测温参数（不做记录就没法复现温度，这几项必须有） ---
    emissivity: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), comment="发射率，猪体表一般 0.95-0.98")
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="测温距离 m")
    reflected_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="反射温度补偿")
    atmospheric_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    humidity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="相对湿度")
    temp_range_min_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="量程下限")
    temp_range_max_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="量程上限")

    # --- 全幅统计 ---
    temp_max_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    temp_min_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    temp_avg_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    temp_center_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="画面中心点温度")
    matrix_width: Mapped[int | None] = mapped_column(Integer, comment="原始温度矩阵宽")
    matrix_height: Mapped[int | None] = mapped_column(Integer, comment="原始温度矩阵高")

    # --- 业务温度 ---
    body_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="猪体表 ROI 平均温度")
    injected_site_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="注射点温度")
    ambient_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), comment="环境温度")
    is_fever: Mapped[bool | None] = mapped_column(Boolean, comment="是否判定为发热异常")

    thermal_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="伪彩图 media_assets.id")
    visible_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="同帧可见光图 media_assets.id")
    raw_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="16bit 原始温度数据 media_assets.id")
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ThermalRoi(Base):
    """热成像 ROI 明细。同一帧可以有多个测温框（注射点、背部平均、耳根…）。"""

    __tablename__ = "thermal_rois"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thermal_capture_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("thermal_captures.id", ondelete="CASCADE"), nullable=False)
    roi_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="injection_site|back_average|ear_root|max_region")
    shape: Mapped[str | None] = mapped_column(String(16), comment="rect|polygon|point")
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="像素坐标几何")
    temp_max_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    temp_min_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    temp_avg_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ObstacleEvent(Base):
    """自动避障事件。一次"发现障碍 -> 减速/停止/绕行 -> 恢复"记一条。"""

    __tablename__ = "obstacle_events"
    __table_args__ = (Index("ix_obstacle_events_device_time", "device_id", "detected_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("injection_tasks.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="detected|slowdown|stop|reroute|cleared")
    sensor_type: Mapped[str | None] = mapped_column(String(32), comment="depth_camera|lidar|ultrasonic|force|vision")
    obstacle_distance_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), comment="最近障碍物距离")
    obstacle_direction: Mapped[str | None] = mapped_column(String(24), comment="front|left|right|top|bottom|unknown")
    obstacle_position: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="{x,y,z} 障碍物位置")
    obstacle_bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB, comment="视觉检测框")
    obstacle_class: Mapped[str | None] = mapped_column(String(48), comment="障碍物类别：person|rail|pig|equipment|unknown")
    detection_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    point_cloud_asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="点云/深度图 media_assets.id")
    action_taken: Mapped[str | None] = mapped_column(String(32), comment="slowdown|stop|retreat|reroute|wait")
    speed_before_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    speed_after_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    resumed: Mapped[bool | None] = mapped_column(Boolean, comment="是否已恢复作业")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer, comment="避障导致的停顿总时长")
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


# ---------------------------------------------------------------------------
# 6. 媒体与告警
# ---------------------------------------------------------------------------


class MediaAsset(Base, TimestampMixin):
    """统一媒体库。图片/视频/温度原始文件都登记在这里，业务表只存 asset_id。"""

    __tablename__ = "media_assets"
    __table_args__ = (Index("ix_media_assets_category_time", "category", "captured_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(24), nullable=False, comment="image|video|thermal_raw|depth|log|other")
    category: Mapped[str] = mapped_column(
        String(48), nullable=False, comment="injection_evidence|thermal|obstacle|snapshot|recording|needle|calibration"
    )
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("injection_tasks.id", ondelete="SET NULL"))
    device_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="SET NULL"))
    file_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="服务器相对路径")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(64))
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer, comment="视频时长")
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)


class Alarm(Base, TimestampMixin):
    """告警。急停、避障、温度异常、注射失败、通讯中断统一进这张表。"""

    __tablename__ = "alarms"
    __table_args__ = (
        UniqueConstraint("alarm_no", name="uq_alarms_alarm_no"),
        Index("ix_alarms_status_time", "status", "created_at"),
        Index("ix_alarms_level_time", "level", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alarm_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="告警编号 AL20260917-0001")
    device_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("devices.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("injection_tasks.id", ondelete="SET NULL"))
    level: Mapped[str] = mapped_column(String(16), nullable=False, comment="info|warning|critical")
    category: Mapped[str] = mapped_column(
        String(48), nullable=False, comment="estop|obstacle|temperature|injection_failed|communication|needle|drug|system"
    )
    code: Mapped[str | None] = mapped_column(String(64), comment="设备错误码")
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), comment="触发值")
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), comment="阈值")
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False, comment="active|acknowledged|cleared")
    acknowledged_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operators.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    asset_id: Mapped[int | None] = mapped_column(BigInteger, comment="关联证据 media_assets.id")
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SystemEvent(Base):
    """系统级事件日志：服务启停、网关异常、配置变更、接口慢请求。"""

    __tablename__ = "system_events"
    __table_args__ = (Index("ix_system_events_time", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, comment="service_start|service_stop|gateway_error|config_change|slow_api|scheduler")
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info", comment="debug|info|warning|error|critical")
    source: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
