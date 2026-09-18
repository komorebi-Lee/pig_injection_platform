"""服务层包。

这里刻意不 import 子模块：各子模块之间（registry / commands / telemetry /
injection / alarms / media / ws）互相引用，父包提前导入容易形成循环依赖。
使用时请显式 `from app.services import xxx`。
"""
