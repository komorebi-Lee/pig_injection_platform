"""运行期配置。全部通过环境变量 / .env 覆盖，代码里不写死任何凭据。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 应用 ---
    app_name: str = "机械臂猪只背部注射系统 - 后端"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # --- 数据库 ---
    database_url: str = "postgresql+psycopg://pigadmin:piginject2026@127.0.0.1:55432/pig_injection"
    db_echo: bool = False

    # --- 存储 ---
    media_root: Path = BACKEND_DIR / "storage"
    max_upload_mb: int = 50

    # --- 机械臂网关 ---
    # mock: 内置模拟机械臂（无硬件时前后端联调用）
    # http: 真实机械臂控制服务（外包方提供）
    arm_driver: str = Field(default="mock", description="mock | http")
    arm_base_url: str = "http://192.168.1.50:6000"
    arm_timeout_s: float = 8.0
    arm_estop_timeout_s: float = 2.0

    # 外包方接口路径映射：拿到对方文档后只需要改这里，不用动业务代码
    arm_path_status: str = "/api/arm/status"
    arm_path_jog: str = "/api/arm/jog"
    arm_path_move_pose: str = "/api/arm/move/pose"
    arm_path_move_joint: str = "/api/arm/move/joint"
    arm_path_home: str = "/api/arm/home"
    arm_path_stop: str = "/api/arm/stop"
    arm_path_estop: str = "/api/arm/estop"
    arm_path_estop_reset: str = "/api/arm/estop/reset"
    arm_path_set_mode: str = "/api/arm/mode"
    arm_path_inject_start: str = "/api/arm/injection/start"
    arm_path_inject_abort: str = "/api/arm/injection/abort"
    arm_path_thermal: str = "/api/arm/thermal/latest"
    arm_path_obstacle: str = "/api/arm/obstacle/status"
    arm_api_token: str = ""

    # --- 遥测轮询 ---
    telemetry_enabled: bool = True
    telemetry_interval_s: float = 1.0
    telemetry_retention_days: int = 30

    # --- 业务阈值（超过就产生告警） ---
    fever_temp_c: float = 40.5
    min_dose_ml: float = 0.5
    max_dose_ml: float = 20.0
    needle_max_uses: int = 100
    default_device_code: str = "ARM-01"

    # --- CORS ---
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
