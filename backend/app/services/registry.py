"""机械臂适配器工厂 + 全局单例 + 当前设备解析。"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Device
from .arm_gateway import ArmAdapter, HttpArmAdapter, MockArmAdapter

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_adapter: ArmAdapter | None = None


def _build() -> ArmAdapter:
    if settings.arm_driver == "http":
        paths = {
            "status": settings.arm_path_status,
            "jog": settings.arm_path_jog,
            "move_pose": settings.arm_path_move_pose,
            "move_joint": settings.arm_path_move_joint,
            "home": settings.arm_path_home,
            "stop": settings.arm_path_stop,
            "estop": settings.arm_path_estop,
            "estop_reset": settings.arm_path_estop_reset,
            "set_mode": settings.arm_path_set_mode,
            "inject_start": settings.arm_path_inject_start,
            "inject_abort": settings.arm_path_inject_abort,
            "thermal": settings.arm_path_thermal,
            "obstacle": settings.arm_path_obstacle,
        }
        logger.info("机械臂网关使用 HTTP 适配器：%s", settings.arm_base_url)
        return HttpArmAdapter(
            settings.arm_base_url, paths, timeout_s=settings.arm_timeout_s, token=settings.arm_api_token
        )
    logger.info("机械臂网关使用 Mock 适配器（无硬件联调模式）")
    return MockArmAdapter()


def get_adapter() -> ArmAdapter:
    global _adapter
    if _adapter is None:
        with _lock:
            if _adapter is None:
                _adapter = _build()
    return _adapter


def reset_adapter() -> None:
    """切换驱动或测试时重建适配器。"""
    global _adapter
    with _lock:
        if _adapter is not None:
            _adapter.close()
        _adapter = None


def get_arm_device(db: Session, device_code: str | None = None) -> Device | None:
    """取机械臂设备台账行。默认取 ARM-01，找不到就取第一台 arm 类型设备。"""
    code = device_code or settings.default_device_code
    device = db.scalar(select(Device).where(Device.device_code == code))
    if device is not None:
        return device
    return db.scalar(select(Device).where(Device.device_type == "arm").order_by(Device.id))
