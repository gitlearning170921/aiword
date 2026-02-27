# AI Word 文档生成工具

基于 Flask + python-docx 的 Web 文档生成系统，支持 Word 模板上传、占位符识别、批量生成等功能。

## 📋 目录

- [项目概述](#项目概述)
- [设计思路](#设计思路)
- [目录结构](#目录结构)
- [编码结构](#编码结构)
- [核心功能说明](#核心功能说明)
- [安装与使用](#安装与使用)
- [开发指南](#开发指南)
- [常见问题](#常见问题)

---

## 项目概述

### 功能特性

1. **页面1 - 模板上传**
   - 上传 Word 模板文件（.docx）
   - 自动识别模板中的占位符（格式：`{{占位符名称}}`）
   - 保存项目名称、文件名称、编写人员等元信息
   - 支持重复检测（项目+文件联合主键）

2. **页面2 - 文档生成**
   - 三级联动下拉框（项目 → 文件 → 编写人员）
   - 自动加载对应模板的占位符输入框
   - 填写占位符内容后生成 Word 文档
   - 支持重复生成确认机制

3. **页面3 - 统计看板**
   - 整体生成完成率统计
   - 按项目名称、编写人员、项目+人员组合统计
   - 生成记录明细表

### 技术栈

- **后端**: Flask 3.0+、SQLAlchemy、python-docx
- **前端**: Bootstrap 5.3、原生 JavaScript
- **数据库**: SQLite（默认）/ MySQL（可选）
- **部署**: Windows BAT 脚本

---

## 设计思路

### 架构设计

采用 **MVC 分层架构**：

```
┌─────────────────────────────────────┐
│         前端层 (Web UI)              │
│  - Bootstrap 5 响应式布局            │
│  - 原生 JS 异步交互                   │
└──────────────┬──────────────────────┘
               │ HTTP/JSON
┌──────────────▼──────────────────────┐
│        路由层 (Flask Routes)         │
│  - RESTful API 设计                  │
│  - 请求验证与错误处理                 │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│       业务逻辑层 (Services)           │
│  - 文档解析与生成                     │
│  - 占位符提取与替换                   │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│       数据访问层 (Models)             │
│  - SQLAlchemy ORM                    │
│  - 数据库表结构定义                   │
└──────────────────────────────────────┘
```

### 数据流设计

1. **上传流程**
   ```
   用户上传文件 → 保存到 uploads/ → 解析占位符 → 存入数据库 → 返回结果
   ```

2. **生成流程**
   ```
   选择模板 → 加载占位符 → 填写内容 → 验证完整性 → 生成文档 → 保存记录
   ```

3. **重复检测机制**
   - **上传阶段**: 以 `(project_name, file_name)` 为联合主键
   - **生成阶段**: 以 `(upload_id, output_name)` 为联合主键
   - 检测到重复时返回 409 状态码，前端弹出确认对话框

### 数据库设计

**三张核心表**：

1. **upload_records** - 模板上传记录
   - 存储模板文件路径、元信息、占位符列表
   - 联合主键：`(project_name, file_name)`

2. **generate_records** - 生成记录
   - 记录每次文档生成的参数、输出路径
   - 外键关联 `upload_records.id`

3. **generation_summary** - 生成统计汇总
   - 按模板聚合生成次数、完成状态
   - 一对一关联 `upload_records`

---

## 目录结构

```
aiword/
├── webapp/                    # 后端应用包
│   ├── __init__.py           # Flask 应用工厂、数据库初始化
│   ├── models.py             # SQLAlchemy 数据模型
│   ├── routes.py             # 路由与 API 端点
│   └── doc_service.py        # 文档解析与生成服务
│
├── web/                       # 前端资源
│   ├── templates/            # Jinja2 模板
│   │   ├── base.html         # 基础布局
│   │   ├── upload.html       # 页面1：上传
│   │   ├── generate.html     # 页面2：生成
│   │   └── dashboard.html    # 页面3：统计
│   └── static/               # 静态资源
│       ├── css/
│       │   └── app.css       # 自定义样式
│       └── js/
│           └── app.js        # 前端交互逻辑
│
├── scripts/                   # 脚本与工具
│   └── mysql_schema.sql      # MySQL 建表脚本
│
├── data/                      # 数据目录（自动创建）
│   └── aiword.db             # SQLite 数据库文件
│
├── uploads/                   # 上传文件存储（自动创建）
│   └── *.docx                # 用户上传的模板文件
│
├── outputs/                   # 生成文件输出（自动创建）
│   └── *.docx                # 生成的文档文件
│
├── app.py                     # 应用入口（导入 webapp）
├── run_web.py                 # Web 服务器启动脚本
├── start_server.bat          # Windows 启动脚本
├── stop_server.bat           # Windows 停止脚本
├── start_server_background.py # 后台启动 Python 脚本
├── stop_server.py             # 停止服务 Python 脚本
├── requirements.txt           # Python 依赖
└── README.md                  # 本文档
```

### 文件说明

| 文件/目录 | 说明 |
|----------|------|
| `webapp/` | 核心后端代码，采用 Flask Blueprint 组织 |
| `web/templates/` | HTML 模板，使用 Jinja2 语法 |
| `web/static/` | CSS/JS 静态资源，不经过后端处理 |
| `data/` | 数据库文件目录，`.gitignore` 应排除 |
| `uploads/` | 用户上传的模板文件，按时间戳命名 |
| `outputs/` | 生成的文档文件，支持自定义命名 |
| `scripts/` | 数据库初始化、测试等辅助脚本 |

---

## 编码结构

### 后端模块 (`webapp/`)

#### 1. `__init__.py` - 应用工厂

**职责**：
- 创建 Flask 应用实例
- 初始化 SQLAlchemy 数据库连接
- 自动检测并补充缺失的数据库列（向后兼容）
- 注册路由蓝图

**关键函数**：
```python
def create_app() -> Flask:
    """应用工厂模式，返回配置好的 Flask 实例"""
    
def ensure_schema(app: Flask):
    """确保数据库表结构完整，自动添加缺失列"""
```

**配置项**：
- `SQLALCHEMY_DATABASE_URI`: 数据库连接字符串（支持 SQLite/MySQL）
- `UPLOAD_FOLDER`: 上传文件存储目录
- `OUTPUT_FOLDER`: 生成文件输出目录
- `MAX_CONTENT_LENGTH`: 文件大小限制（25MB）

#### 2. `models.py` - 数据模型

**三个核心模型**：

```python
class UploadRecord(db.Model):
    """模板上传记录"""
    id: str                    # UUID 主键
    project_name: str          # 项目名称
    file_name: str             # 文件名称
    author: str                # 编写人员
    placeholders: list         # 占位符列表（JSON）
    storage_path: str          # 文件存储路径
    # ... 其他字段

class GenerateRecord(db.Model):
    """文档生成记录"""
    id: str
    upload_id: str             # 外键 → UploadRecord
    placeholder_payload: dict  # 占位符填充值（JSON）
    output_path: str           # 生成文件路径
    # ... 其他字段

class GenerationSummary(db.Model):
    """生成统计汇总"""
    id: str
    upload_id: str             # 一对一关联 UploadRecord
    total_generate_clicks: int  # 生成次数
    has_generated: bool        # 是否已生成
    # ... 其他字段
```

**关系设计**：
- `UploadRecord` 一对多 `GenerateRecord`（级联删除）
- `UploadRecord` 一对一 `GenerationSummary`（级联删除）

#### 3. `routes.py` - 路由与 API

**页面路由**：
```python
@bp.route("/upload")      # GET  - 上传页面
@bp.route("/generate")    # GET  - 生成页面
@bp.route("/dashboard")   # GET  - 统计页面
```

**API 端点**：
```python
POST   /api/upload              # 上传模板并解析占位符
GET    /api/upload-options      # 获取下拉框选项树
GET    /api/uploads/<id>        # 获取模板详情（含占位符）
POST   /api/generate            # 生成文档
GET    /api/summary             # 获取统计汇总数据
```

**关键逻辑**：
- **重复检测**: 使用 `filter_by()` 查询联合主键，返回 409 状态码
- **占位符解析**: 调用 `doc_service.extract_placeholders()`
- **文档生成**: 调用 `doc_service.generate_document()`
- **统计聚合**: 使用 Python 字典分组计算完成率

#### 4. `doc_service.py` - 文档服务

**核心函数**：

```python
def extract_placeholders(template_path: str) -> List[str]:
    """
    从 Word 文档中提取所有占位符
    
    支持范围：
    - 正文段落（包括跨 run 的占位符）
    - 表格单元格
    - 页眉页脚
    
    占位符格式：{{key}}（双花括号，中间为键名）
    """

def generate_document(
    template_path: str,
    output_dir: str,
    data: Dict[str, str],
    output_name: str | None = None
) -> str:
    """
    根据模板和数据生成 Word 文档
    
    参数：
    - template_path: 模板文件路径
    - output_dir: 输出目录
    - data: 占位符键值对字典
    - output_name: 输出文件名（可选，默认自动生成）
    
    返回：生成文件的完整路径
    """
```

**技术细节**：
- 使用 `python-docx` 库解析 `.docx` 文件
- 通过正则表达式 `\{\{\s*([^{}\n\r]+?)\s*\}\}` 匹配占位符
- 处理跨 run 的占位符（合并所有 run 文本后替换）
- 支持页眉页脚、嵌套表格等复杂结构

### 前端模块 (`web/`)

#### 1. `templates/base.html` - 基础布局

**结构**：
```html
<!DOCTYPE html>
<html>
<head>
    <!-- Bootstrap 5.3 CDN -->
    <!-- 自定义 CSS -->
</head>
<body>
    <nav>...</nav>          <!-- 导航栏（页面2隐藏） -->
    <main>
        {% block content %}{% endblock %}
    </main>
    <!-- Bootstrap JS -->
    <!-- 自定义 JS -->
</body>
</html>
```

#### 2. `static/js/app.js` - 前端交互

**核心对象**：
```javascript
const App = {
    async request(url, options) {
        // 统一请求封装，处理 409 确认逻辑
    },
    notify(message, variant) {
        // 消息提示（Bootstrap Alert）
    }
}
```

**页面初始化函数**：
- `initUploadPage()`: 文件选择自动填充文件名、表单提交
- `initGeneratePage()`: 三级联动下拉、占位符动态加载、生成提交
- `initDashboardPage()`: 统计数据加载与渲染

**关键特性**：
- **409 处理**: 自动弹出确认对话框，用户确认后自动重试
- **联动逻辑**: 项目选择 → 更新文件列表 → 更新人员列表 → 加载占位符
- **动态渲染**: 根据占位符列表动态创建输入框

#### 3. `static/css/app.css` - 样式定制

**主要样式类**：
- `.hero-bar`: 页面顶部标题区域
- `.workflow-steps`: 流程步骤条（带进度填充）
- `.mini-stat`: 小型统计卡片
- `.card`: 增强的卡片样式（阴影、圆角）
- `.form-control`, `.form-select`: 统一的表单控件样式

---

## 核心功能说明

### 1. 占位符识别

**识别规则**：
- 格式：`{{占位符名称}}`
- 支持中文、英文、数字、下划线
- 不支持换行符、特殊符号

**提取流程**：
1. 遍历文档所有段落（正文、页眉、页脚）
2. 遍历所有表格单元格
3. 使用正则表达式匹配 `{{...}}` 模式
4. 去重并保持顺序

**示例**：
```docx
文档内容：登录{{产品名称}}系统后，可查看{{用户数量}}个用户。
识别结果：['产品名称', '用户数量']
```

### 2. 文档生成

**生成流程**：
1. 加载模板文件（`Document()`）
2. 遍历所有段落，替换占位符
3. 遍历所有表格，替换单元格中的占位符
4. 处理页眉页脚
5. 保存到输出目录

**文件命名**：
- 用户指定：使用用户输入的文件名
- 自动生成：`{模板名}_{时间戳}.docx`

### 3. 重复检测

**上传阶段**：
```python
existing = UploadRecord.query.filter_by(
    project_name=project_name,
    file_name=file_name
).first()
```
- 联合主键：`(project_name, file_name)`
- 检测到重复 → 返回 409 → 前端确认 → 用户选择替换或取消

**生成阶段**：
```python
existing = GenerateRecord.query.filter_by(
    upload_id=upload_id,
    output_file_name=output_name
).first()
```
- 联合主键：`(upload_id, output_file_name)`
- 允许同一模板生成多个不同名称的文件
- 相同名称时提示替换

### 4. 统计汇总

**聚合维度**：
- 整体：所有文件的完成率
- 按项目：每个项目的完成率
- 按人员：每个编写人员的完成率
- 按组合：项目+人员的组合完成率

**计算逻辑**：
```python
# 遍历所有 summary 记录
for row in summaries:
    # 按维度分组统计
    stats["total"] += 1
    if row.has_generated:
        stats["completed"] += 1
# 计算完成率
rate = completed / total
```

---

## 安装与使用

### 环境要求

- Python 3.8+
- pip（Python 包管理器）

### 安装步骤

1. **克隆或下载项目**
   ```bash
   cd F:\wzl\learning\python\aiword
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **（可选）配置 MySQL**
   - 执行 `scripts/mysql_schema.sql` 创建数据库和表
   - 设置环境变量：
     ```bash
     set DATABASE_URL=mysql+pymysql://user:password@host:3306/aiword
     ```

### 启动服务

**方式1：直接运行（开发模式）**
```bash
python run_web.py
```

**方式2：后台运行（生产模式）**
- 双击 `start_server.bat` 启动
- 双击 `stop_server.bat` 停止

**访问地址**：
- 页面1（上传）：http://localhost:5000/upload
- 页面2（生成）：http://localhost:5000/generate
- 页面3（统计）：http://localhost:5000/dashboard

若需让其他人通过域名或内网 IP 打开（如催办通知里的链接），请设置环境变量 **BASE_URL**，例如：`set BASE_URL=http://your-server.com` 或 `set BASE_URL=http://192.168.1.100:5000`。详见 `docs/DINGTALK.md`。

### 使用流程

1. **上传模板**（页面1）
   - 填写项目名称、文件名称、编写人员
   - 选择 Word 模板文件（.docx）
   - 点击"保存"，系统自动识别占位符

2. **生成文档**（页面2）
   - 依次选择项目、文件、编写人员
   - 系统自动加载占位符输入框
   - 填写所有占位符内容
   - （可选）指定输出文件名
   - 点击"保存并生成文档"

3. **查看统计**（页面3）
   - 查看整体完成率
   - 查看各维度统计表
   - 查看生成记录明细

---

## 开发指南

### 添加新功能

#### 1. 添加新的 API 端点

在 `webapp/routes.py` 中添加：

```python
@bp.post("/api/your-endpoint")
def your_endpoint():
    data = request.get_json()
    # 处理逻辑
    return jsonify({"message": "成功"})
```

#### 2. 修改数据库模型

在 `webapp/models.py` 中添加字段：

```python
class YourModel(db.Model):
    new_field: Mapped[str] = mapped_column(db.String(128))
```

然后运行应用，SQLAlchemy 会自动创建表（SQLite）或使用迁移工具（MySQL）。

#### 3. 修改前端页面

编辑 `web/templates/your_page.html`，使用 Jinja2 语法：

```html
{% extends "base.html" %}
{% block title %}页面标题{% endblock %}
{% block content %}
    <!-- 你的内容 -->
{% endblock %}
```

#### 4. 添加前端交互

在 `web/static/js/app.js` 中添加函数：

```javascript
function initYourPage() {
    // 初始化逻辑
}

// 在 DOMContentLoaded 中调用
document.addEventListener("DOMContentLoaded", () => {
    initYourPage();
});
```

### 调试技巧

1. **查看日志**
   - 开发模式：控制台输出
   - 后台模式：查看 `server.log` 文件

2. **数据库调试**
   ```python
   from webapp import app, db
   from webapp.models import UploadRecord
   
   with app.app_context():
       records = UploadRecord.query.all()
       for r in records:
           print(r.project_name, r.file_name)
   ```

3. **前端调试**
   - 打开浏览器开发者工具（F12）
   - 查看 Console 标签页的错误信息
   - 查看 Network 标签页的 API 请求/响应

### 代码规范

- **Python**: 遵循 PEP 8，使用类型注解
- **JavaScript**: 使用 ES6+ 语法，避免全局变量污染
- **HTML**: 使用语义化标签，保持缩进一致
- **CSS**: 使用 BEM 命名规范（如需要）

---

## 常见问题

### Q1: 占位符识别失败

**可能原因**：
- 占位符格式不正确（不是 `{{...}}`）
- 占位符被换行符分割
- 文件不是 `.docx` 格式

**解决方法**：
- 检查模板文件，确保占位符格式正确
- 使用 Word 打开模板，检查是否有特殊格式
- 将 `.doc` 文件另存为 `.docx`

### Q2: 中文乱码

**可能原因**：
- 数据库字符集配置错误（MySQL）
- JSON 序列化时使用了 ASCII 编码

**解决方法**：
- 确保 MySQL 数据库使用 `utf8mb4` 字符集
- 检查 `app.json.ensure_ascii = False` 配置

### Q3: 文件上传失败

**可能原因**：
- 文件大小超过 25MB 限制
- 上传目录权限不足

**解决方法**：
- 检查文件大小
- 确保 `uploads/` 目录有写入权限

### Q4: 生成文档失败

**可能原因**：
- 占位符未全部填写
- 模板文件损坏
- 输出目录权限不足

**解决方法**：
- 检查所有占位符是否已填写
- 重新上传模板文件
- 确保 `outputs/` 目录有写入权限

### Q5: 数据库连接失败（MySQL）

**可能原因**：
- 数据库服务未启动
- 连接字符串配置错误
- 用户权限不足

**解决方法**：
- 检查 MySQL 服务状态
- 验证 `DATABASE_URL` 环境变量
- 确认用户有创建表、插入数据的权限

---

## 版本历史

- **v1.0.0** (2025-11-24)
  - 初始版本
  - 支持模板上传、占位符识别、文档生成
  - 支持 SQLite/MySQL 数据库
  - 完整的统计看板功能

---

## 许可证

本项目仅供学习使用。

---

## 联系方式

如有问题或建议，请通过项目 Issue 反馈。



