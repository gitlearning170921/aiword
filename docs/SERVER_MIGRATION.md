# 服务迁机说明（数据库集中存储）

模板 Word、生成结果、备注附件已改为**主要存 MySQL**（`MEDIUMBLOB`），迁机时一般只需**备份并恢复数据库** + 配置新环境变量。

## 迁机前（仍在旧服务器时）

1. 部署本版本并**启动服务至少一次**，使启动任务将磁盘上的旧文件迁入数据库：
   - `upload_records.storage_path` 指向的模板 → `template_file_blob`
   - `generate_records.output_path` → `output_file_blob`
   - `uploads/notes/*` → `note_attachment_files`
2. 查看日志，若有大量 `迁入模板失败` / `迁入生成文件失败`，说明对应文件已丢失或超过单字段限制（约 16MB），需单独处理。

## 新机器上

1. 恢复数据库：`mysqldump` / 导入备份。
2. 配置 `DATABASE_URL` 或系统设置里的数据库连接（与 `app_settings` 一致）。
3. 安装依赖后启动应用；`uploads/`、`outputs/` 可为空目录。
4. **不必**再拷贝旧机的 `uploads/`、`outputs/`（数据已在库内）。

## 仍依赖本机的项（非业务数据）

**每次启动会自动处理：**

- 创建 `instance/scheduler_locks/`，并**删除其中全部 `*.lock`**，避免从旧机拷贝项目后锁文件导致定时任务被误跳过。
- 删除 `uploads/_dbtpl_*.docx` 模板磁盘缓存，需要时从数据库或链接自动重建。

**首次启动**会在控制台打印横幅提示（核对数据库与系统设置）；同机再次启动不再打印，除非删除 `instance/.aiword_startup_banner` 或设置环境变量 `AIWORD_SHOW_STARTUP_HINT=1`。静默模式：`AIWORD_QUIET_STARTUP=1`。

| 项 | 说明 |
|----|------|
| `instance/scheduler_locks/` | 见上，启动时自动清空锁文件并保证目录存在 |
| `.env` / 页面13 系统设置 | 需在新机自行配置数据库 URI、钉钉、BASE_URL 等 |
| `_dbtpl_<uuid>.docx` | 见上，启动时自动清理 |

## 单文件大小

MySQL 使用 `MEDIUMBLOB`（约 16MB）。超过限制的模板/附件需压缩或改为链接模板。
