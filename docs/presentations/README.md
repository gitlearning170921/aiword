# 演示文稿（PPT）

## AI Word 前台项目介绍（推荐）

只讲 AI Word 前台全部当前功能；后台智能能力用一页文字说明，不配后台截图。

```bash
pip install python-pptx
python scripts/generate_aiword_frontend_pptx.py
```

默认输出：`docs/presentations/aiword_frontend_overview.pptx`

关键界面图来自当前前台实拍（`docs/presentations/screenshots/frontend/`），公司名、人名、项目名、地址等已打码，便于外发。刷新截图：

```bash
python scripts/capture_aiword_frontend_screenshots.py
python scripts/generate_aiword_frontend_pptx.py
```

需本机已启动 `python run_web.py`（默认 http://127.0.0.1:5000）。

## 系统全景介绍（含审核引擎界面）

```bash
python scripts/generate_system_overview_pptx.py
```

默认输出：`docs/presentations/system_overview.pptx`

## 考试训练中心功能介绍

见 aicheckword 仓库：`python scripts/generate_exam_center_pptx.py`
