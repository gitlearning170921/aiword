---
name: aiword-system-config
description: >-
  Use when changing aiword deployable settings, scheduler behavior, DingTalk, or
  page-3 system configuration. Teaches AppConfig / SYSTEM_CONFIG_KEYS patterns
  and discourages ad-hoc environment variables for business-tunable values.
---

# aiword 系统配置（Skill）

## 原则

1. **页面 3 系统配置**与表 `AppConfig` 是运营可调参数的主存储；元数据在 `webapp/app_settings.py` 的 `SYSTEM_CONFIG_KEYS`（键名、中文说明、是否敏感）。
2. **新增可调项**：在 `SYSTEM_CONFIG_KEYS` 增加一项；`ensure_schema` / `init_default_configs` 会通过现有循环补空行；API 与前端从 `keys_meta` 渲染，一般无需硬编码字段列表。
3. **定时任务、无 request 上下文**：使用 `get_setting_for_scheduler(key, default="", app=app)`，并传入 `scheduler` 模块里的全局 `_app` 或当前 `Flask` 实例。
4. **不要用环境变量承载业务开关**（与本项目约定一致）：多实例钉钉去重等用系统配置键（例如 `SCHEDULER_INSTANCE_ID`）；环境变量留给部署层或已有兼容（如数据库 URI）。
5. **保存逻辑**：`save_system_settings` 对非敏感键默认「空串不覆盖已有值」；若某键必须允许清空，在 `save_system_settings` 里为该 `config_key` 单独 `continue` 前写库（见 `SCHEDULER_INSTANCE_ID`）。

## 示例：读取实例标识

在 `webapp/scheduler.py` 中通过 `get_setting_for_scheduler("SCHEDULER_INSTANCE_ID", default="", app=_app)` 读取；留空表示全库同 job 同分钟去重一条；各部署填不同值则共库多套各发一条钉钉。
