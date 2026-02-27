# 项目目录结构说明

本文档说明项目的目录组织原则和优化建议。

## 当前目录结构

```
aiword/
├── webapp/              # 后端应用核心代码
├── web/                 # 前端资源
├── scripts/             # 辅助脚本
├── data/                # 数据文件（自动生成）
├── uploads/             # 上传文件（自动生成）
├── outputs/             # 生成文件（自动生成）
├── build/               # 构建产物（可删除）
├── dist/                # 打包产物（可删除）
├── __pycache__/         # Python 缓存（可删除）
├── core/                # 旧代码目录（可删除）
├── templates/           # 旧模板目录（可删除）
│
├── app.py               # 应用入口
├── run_web.py          # 启动脚本
├── requirements.txt     # 依赖列表
├── README.md            # 项目文档
└── ...                  # 其他文件
```

## 目录分类

### 核心代码目录

| 目录 | 说明 | 是否版本控制 |
|------|------|------------|
| `webapp/` | Flask 后端应用包 | ✅ 是 |
| `web/` | 前端模板和静态资源 | ✅ 是 |
| `scripts/` | 数据库脚本、工具脚本 | ✅ 是 |

### 运行时目录（自动创建）

| 目录 | 说明 | 是否版本控制 |
|------|------|------------|
| `data/` | SQLite 数据库文件 | ❌ 否（应加入 .gitignore） |
| `uploads/` | 用户上传的模板文件 | ❌ 否（应加入 .gitignore） |
| `outputs/` | 生成的文档文件 | ❌ 否（应加入 .gitignore） |
| `__pycache__/` | Python 字节码缓存 | ❌ 否（应加入 .gitignore） |

### 构建产物目录（可删除）

| 目录 | 说明 | 是否版本控制 |
|------|------|------------|
| `build/` | PyInstaller 构建临时文件 | ❌ 否 |
| `dist/` | 打包后的可执行文件 | ❌ 否 |

### 遗留目录（可清理）

| 目录 | 说明 | 建议 |
|------|------|------|
| `core/` | 旧代码目录（空） | 可删除 |
| `templates/` | 旧模板目录（空） | 可删除 |

## 文件分类

### 核心文件

| 文件 | 说明 | 是否版本控制 |
|------|------|------------|
| `app.py` | Flask 应用入口 | ✅ 是 |
| `run_web.py` | Web 服务器启动脚本 | ✅ 是 |
| `requirements.txt` | Python 依赖列表 | ✅ 是 |
| `README.md` | 项目说明文档 | ✅ 是 |
| `PROJECT_STRUCTURE.md` | 本文档 | ✅ 是 |

### 启动脚本

| 文件 | 说明 | 是否版本控制 |
|------|------|------------|
| `start_server.bat` | Windows 启动脚本 | ✅ 是 |
| `stop_server.bat` | Windows 停止脚本 | ✅ 是 |
| `start_server_background.py` | 后台启动 Python 脚本 | ✅ 是 |
| `stop_server.py` | 停止服务 Python 脚本 | ✅ 是 |

### 配置文件

| 文件 | 说明 | 是否版本控制 |
|------|------|------------|
| `server.log` | 服务器日志 | ❌ 否（应加入 .gitignore） |
| `server.pid` | 进程 ID 文件 | ❌ 否（应加入 .gitignore） |

### 测试/开发文件（可删除或移至 tests/）

| 文件 | 说明 | 建议 |
|------|------|------|
| `aiword.py` | 旧的桌面版代码 | 可移至 `legacy/` 或删除 |
| `build_exe.py` | 打包脚本 | 可移至 `scripts/` |
| `debug_template.py` | 调试脚本 | 可移至 `scripts/` 或 `tests/` |
| `test_template.py` | 测试脚本 | 可移至 `tests/` |
| `find_placeholders.py` | 工具脚本 | 可移至 `scripts/` |
| `verify_placeholders.py` | 工具脚本 | 可移至 `scripts/` |

## 优化建议

### 1. 创建 `.gitignore` 文件

建议创建 `.gitignore` 排除以下内容：

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/

# 数据文件
data/
uploads/
outputs/
*.db
*.sqlite

# 日志和临时文件
*.log
*.pid
.DS_Store
Thumbs.db

# 构建产物
build/
dist/
*.spec

# IDE
.vscode/
.idea/
*.swp
*.swo

# 测试文件
.pytest_cache/
.coverage
htmlcov/
```

### 2. 创建 `tests/` 目录

将测试相关文件移至 `tests/` 目录：

```
tests/
├── test_models.py
├── test_routes.py
├── test_doc_service.py
└── fixtures/
    └── sample_template.docx
```

### 3. 创建 `legacy/` 目录

将旧代码移至 `legacy/` 目录：

```
legacy/
├── aiword.py          # 旧的桌面版代码
└── README.md          # 说明旧代码用途
```

### 4. 创建 `docs/` 目录

将文档集中管理：

```
docs/
├── API.md             # API 文档
├── DEPLOYMENT.md      # 部署文档
└── DEVELOPMENT.md     # 开发文档
```

### 5. 统一脚本位置

将所有脚本移至 `scripts/` 目录：

```
scripts/
├── mysql_schema.sql
├── build_exe.py
├── debug_template.py
├── find_placeholders.py
└── verify_placeholders.py
```

## 推荐的项目结构

```
aiword/
├── webapp/                    # 后端核心代码
│   ├── __init__.py
│   ├── models.py
│   ├── routes.py
│   └── doc_service.py
│
├── web/                       # 前端资源
│   ├── templates/
│   └── static/
│       ├── css/
│       └── js/
│
├── scripts/                   # 辅助脚本
│   ├── mysql_schema.sql
│   ├── build_exe.py
│   └── ...
│
├── tests/                     # 测试代码（新建）
│   ├── test_models.py
│   ├── test_routes.py
│   └── fixtures/
│
├── docs/                      # 文档（新建）
│   ├── API.md
│   └── ...
│
├── legacy/                    # 旧代码（新建）
│   └── aiword.py
│
├── data/                      # 数据文件（.gitignore）
├── uploads/                   # 上传文件（.gitignore）
├── outputs/                   # 生成文件（.gitignore）
│
├── app.py                     # 应用入口
├── run_web.py                 # 启动脚本
├── start_server.bat           # Windows 启动
├── stop_server.bat            # Windows 停止
├── start_server_background.py # 后台启动
├── stop_server.py             # 停止服务
├── requirements.txt           # 依赖列表
├── README.md                  # 项目文档
├── PROJECT_STRUCTURE.md       # 本文档
└── .gitignore                 # Git 忽略规则
```

## 文件命名规范

### Python 文件
- 使用小写字母和下划线：`doc_service.py`
- 模块名应具有描述性：`models.py`, `routes.py`

### HTML 模板
- 使用小写字母和连字符：`base.html`, `upload.html`

### CSS/JS 文件
- 使用小写字母和连字符：`app.css`, `app.js`

### 配置文件
- 使用全大写：`README.md`, `.gitignore`

## 目录权限建议

| 目录 | 权限 | 说明 |
|------|------|------|
| `data/` | 读写 | 数据库文件需要写入 |
| `uploads/` | 读写 | 上传文件需要写入 |
| `outputs/` | 读写 | 生成文件需要写入 |
| `webapp/` | 只读 | 代码文件不需要写入 |
| `web/` | 只读 | 静态资源不需要写入 |

## 总结

- **核心代码**：集中在 `webapp/` 和 `web/`
- **运行时数据**：`data/`, `uploads/`, `outputs/` 应加入 `.gitignore`
- **辅助脚本**：统一放在 `scripts/`
- **测试代码**：建议创建 `tests/` 目录
- **文档**：建议创建 `docs/` 目录集中管理
- **旧代码**：移至 `legacy/` 或删除

遵循以上结构可以提高项目的可维护性和可读性。



