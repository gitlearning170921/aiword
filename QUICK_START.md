# 快速入门指南

本文档帮助新手快速理解项目结构和开始使用。

## 5 分钟快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

**Windows 用户**：
- 双击 `start_server.bat`

**命令行用户**：
```bash
python run_web.py
```

### 3. 访问页面

打开浏览器访问：http://localhost:5000/upload

## 项目结构速览

```
aiword/
│
├── 📁 webapp/          ← 后端代码（Flask）
│   ├── models.py       ← 数据库模型
│   ├── routes.py       ← API 路由
│   └── doc_service.py  ← 文档处理服务
│
├── 📁 web/             ← 前端代码
│   ├── templates/      ← HTML 模板
│   └── static/         ← CSS/JS 文件
│
├── 📁 scripts/         ← 数据库脚本
│
├── 📄 app.py           ← 应用入口
├── 📄 run_web.py       ← 启动脚本
└── 📄 requirements.txt ← 依赖列表
```

## 核心文件说明

### 后端文件

| 文件 | 作用 | 修改频率 |
|------|------|---------|
| `webapp/models.py` | 定义数据库表结构 | 低 |
| `webapp/routes.py` | 定义 API 接口 | 中 |
| `webapp/doc_service.py` | 文档解析和生成 | 低 |

### 前端文件

| 文件 | 作用 | 修改频率 |
|------|------|---------|
| `web/templates/*.html` | 页面模板 | 中 |
| `web/static/js/app.js` | 前端交互逻辑 | 高 |
| `web/static/css/app.css` | 页面样式 | 中 |

## 开发流程

### 添加新功能

1. **修改后端** → 编辑 `webapp/routes.py`
2. **修改前端** → 编辑 `web/templates/*.html` 和 `web/static/js/app.js`
3. **测试** → 刷新浏览器查看效果

### 修改数据库

1. **修改模型** → 编辑 `webapp/models.py`
2. **重启服务** → 自动创建/更新表结构

### 修改样式

1. **编辑 CSS** → `web/static/css/app.css`
2. **刷新页面** → 按 `Ctrl+F5` 强制刷新缓存

## 常见操作

### 查看日志

- 开发模式：查看控制台输出
- 后台模式：查看 `server.log` 文件

### 停止服务

- Windows：双击 `stop_server.bat`
- 命令行：按 `Ctrl+C`

### 清空数据

删除以下目录中的文件：
- `data/` - 数据库文件
- `uploads/` - 上传的模板
- `outputs/` - 生成的文档

## 下一步

- 阅读 [README.md](README.md) 了解详细文档
- 阅读 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) 了解目录结构
- 查看代码注释了解实现细节

## 获取帮助

遇到问题？
1. 查看 `README.md` 的"常见问题"章节
2. 检查浏览器控制台（F12）的错误信息
3. 查看 `server.log` 日志文件



