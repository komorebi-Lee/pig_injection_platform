"""建表 + 灌种子数据。

用法（在 backend 目录下）：
    uv run python scripts/init_db.py            # 建表（已存在则跳过）+ 种子数据
    uv run python scripts/init_db.py --drop     # 先删光再重建（危险，仅开发用）
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, select

from app.db import SessionLocal, engine
from app.models import Base, Device, Operator, Pen, Pig

TZ = ZoneInfo("Asia/Shanghai")


def create_schema(drop: bool = False) -> None:
    if drop:
        print("[init_db] drop_all() ...")
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    tables = sorted(inspect(engine).get_table_names())
    print(f"[init_db] 表就绪，共 {len(tables)} 张：")
    for name in tables:
        print(f"    - {name}")


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(Pen).limit(1)) is not None:
            print("[init_db] 已存在业务数据，跳过种子。")
            return

        op = Operator(
            username="admin",
            display_name="系统管理员",
            role="admin",
            active=True,
        )
        db.add(op)

        pen = Pen(
            pen_code="A-01",
            pen_name="育肥一栏",
            barn="1号舍",
            area_name="东区",
            capacity=15,
            guardrail_camera_code="CAM-GR-01",
            arm_camera_code="CAM-ARM-01",
            arm_device_code="ARM-01",
            status="active",
            remark="演示用栏位",
        )
        db.add(pen)
        db.flush()

        db.add(
            Pig(ear_tag="PIG-0001", pen_id=pen.id, breed="杜长大", sex="female", health_status="healthy")
        )
        db.add(
            Pig(ear_tag="PIG-0002", pen_id=pen.id, breed="杜长大", sex="male", health_status="healthy")
        )

        now = datetime.now(TZ)
        devices = [
            Device(
                device_code="ARM-01",
                device_type="arm",
                vendor="（待填：外包方）",
                model="6-DOF 协作臂",
                firmware_version="0.0.0",
                protocol="http",
                endpoint="http://192.168.1.50:6000",
                mounted_on="fixed",
                pen_id=pen.id,
                installed_at=now,
                status="offline",
                remark="注射执行机构",
            ),
            Device(
                device_code="CAM-GR-01",
                device_type="camera_guardrail",
                vendor="（待填）",
                protocol="rtsp",
                endpoint="rtsp://192.168.1.61:554/stream1",
                mounted_on="guardrail",
                pen_id=pen.id,
                status="offline",
                remark="护栏相机：全局定位猪只与背脊线",
            ),
            Device(
                device_code="CAM-ARM-01",
                device_type="camera_arm",
                vendor="（待填）",
                protocol="rtsp",
                endpoint="rtsp://192.168.1.62:554/stream1",
                mounted_on="arm",
                pen_id=pen.id,
                status="offline",
                remark="臂上相机：局部对位与进针点确认",
            ),
            Device(
                device_code="CAM-IR-01",
                device_type="camera_thermal",
                vendor="（待填）",
                protocol="http",
                endpoint="http://192.168.1.63:8080",
                mounted_on="arm",
                pen_id=pen.id,
                status="offline",
                remark="热成像模块",
            ),
        ]
        db.add_all(devices)
        db.commit()
        print(f"[init_db] 种子数据完成：1 操作员 / 1 栏位 / 2 猪只 / {len(devices)} 设备")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="先删除所有表再重建")
    parser.add_argument("--no-seed", action="store_true", help="只建表，不灌种子数据")
    args = parser.parse_args()

    create_schema(drop=args.drop)
    if not args.no_seed:
        seed()


if __name__ == "__main__":
    main()
