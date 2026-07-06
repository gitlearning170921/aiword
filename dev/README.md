# 发版与部署全流程

> 三台机器：**开发机** → **Windows 打包机** → **Linux 生产**  
> 三个仓库脚本结构一致，均在 **`dev/`** 下。

---

## 零、三仓库统一目录（看文件夹名即知用途）

```
python/
├── aiword/                 主应用
│   ├── webapp/ web/        ★ 产品代码
│   ├── deploy/             ★ Docker 打包 + Linux 部署
│   └── dev/
│       ├── git-no_tag/     ◆ 日常 push，不打 tag
│       ├── git-tag_release/◆ 发版 v1.0.x（aiword+aicheckword 双仓库）
│       └── local-run/      ◆ 本机启停 5000
│
├── aicheckword/            审核 API
│   ├── src/                ★ 产品代码
│   └── dev/                ◆ 同上三层（tag 由 aiword release 打）
│
└── aiprintword/            签批/批量打印（Windows 独立部署）
    ├── app.py sign_handlers/  ★ 产品代码
    └── dev/                ◆ git-no_tag + local-run（不进 Docker 发版链）
```

| 标记 | 含义 |
|------|------|
| ★ | 产品代码，进 Git |
| ◆ | 开发机 bat，进 Git，不进 Docker 镜像 |

**根目录不再有 submit/release/start 等 bat**，一律进 `dev\` 对应子目录。

---

## 一、开发机脚本对照（三仓库）

| 用途 | aiword | aicheckword | aiprintword |
|------|--------|-------------|-------------|
| 日常提交 | `dev\git-no_tag\submit.bat` | `dev\git-no_tag\commit.bat` | `dev\git-no_tag\commit_push.bat` |
| 补 push | `submit_push_retry.bat` | `push_only.bat` | `push_only.bat` |
| **发版 tag** | `dev\git-tag_release\release.bat 1.0.5` | （由 aiword 一并处理） | 不参与 |
| 本机运行 | `dev\local-run\start_server.bat` | `dev\local-run\start_api.bat` | `dev\local-run\start_server.bat` |

各仓库细节见各自 `dev/README.md`（aicheckword、aiprintword 目录下也有）。

---

## 二、目录怎么认（aiword 展开）

### 1. 开发机 — aiword 仓库

```
F:\wzl\learning\python\
├── aiword\                          ← 主应用仓库
│   ├── webapp\                      ★ 后端 Python 代码
│   ├── web\                         ★ 前端 HTML / JS / CSS（与 webapp 一起发）
│   ├── scripts\                     ★ Python 工具（门禁、测试脚本等）
│   ├── deploy\                      ★ Docker 打包 + Linux 部署脚本（进 Git）
│   ├── dev\                         ◆ 见上文「三仓库统一目录」
│   ├── instance\ uploads\ outputs\  ✗ 运行时数据
│   └── app.py run_web.py ...
```

> 根目录 **已无** submit/release/start 等 bat。

### 2. 打包机 — 固定布局

```
d:\aicode\                           ◆ 打包机 driver（不在 Git 里，可手拷脚本）
  git_clone_repo_aiword.bat          ◆◆ 按 tag 拉双仓库 + 可选 build
  build_aiword_stack.bat             ◆◆ 拉代码 + build-all 一键
  aiword\                            ★ checkout 到 v<version>（脚本自动维护）
    deploy\
      build-all.bat                  ★ 完整包（含 chroma）
      build-apps-all.bat             ★ 日常：仅 aiword + aicheckword
  aicheckword\                       ★ checkout 到 v<version>（同级，Docker 构建需要）
```

> 旧目录 `aiword_20260526_时间戳\` 是历史 clone，**不能**用来打 Docker 包；请用固定 `d:\aicode\aiword`。

### 3. Linux 生产 — 部署目录

```
/aiword/aiworddocker/aiword-stack/   ← 运行中的部署包（无源码）
  docker-compose.prod.yml
  .env                               ✗ 服务器本地配置，升级时不覆盖
  images\
    aiword-1.0.5.tar.gz
    aicheckword-1.0.5.tar.gz
    chroma-1.0.5.tar.gz              （首次部署才有，日常可跳过）
  upgrade.sh server-deploy.sh ...
```

---

## 三、脚本对照表（aiword 明细）

### 开发机 — 什么时候用哪个 bat？

| 场景 | 目录 | 脚本 | 是否打 tag |
|------|------|------|-----------|
| 日常改完代码推送 | `dev\git-no_tag\` | `submit.bat "说明"` | **否** |
| 本地有提交但没推上去 | `dev\git-no_tag\` | `submit_push_retry.bat` | **否** |
| 只 push | `dev\git-no_tag\` | `push_only.bat` | **否** |
| **正式发版** | `dev\git-tag_release\` | `release.bat 1.0.5 "发版说明"` | **是** `v1.0.5` |
| 本机跑服务 | `dev\local-run\` | `start_server.bat` | — |

aicheckword / aiprintword 见上文表格。

### 打包机

| 脚本 | 作用 |
|------|------|
| `git_clone_repo_aiword.bat 1.0.5` | 拉双仓库到 `d:\aicode\aiword` + `aicheckword`，checkout `v1.0.5` |
| `git_clone_repo_aiword.bat 1.0.5 build` | 上一步 + `deploy\build-all.bat` 打完整 zip |
| `git_clone_repo_aiword.bat 1.0.5 build-apps` | 上一步 + 仅业务镜像（日常推荐） |
| `build_aiword_stack.bat 1.0.5` | 等同 `... build` |

### Linux

| 脚本 | 作用 |
|------|------|
| `server-deploy.sh 1.0.5` | **首次**部署：load 镜像 + 启动 |
| `upgrade.sh` | **升级**已有环境（见下文） |

---

## 三、完整步骤（从零到上线）

### 阶段 A — 开发机：日常开发（不打 tag）

```cmd
cd /d F:\wzl\learning\python\aiword
dev\git-no_tag\submit.bat "修复初稿页按钮"

:: aicheckword 有单独改动时（可选）
cd /d F:\wzl\learning\python\aicheckword
dev\git-no_tag\commit.bat "审核 API 调整"
```

### 阶段 B — 开发机：发版（打 tag，打包机靠这个拉代码）

```cmd
cd /d F:\wzl\learning\python\aiword
dev\git-tag_release\release.bat 1.0.5 "增加 OpenAI 集成；按身份考试"
```

脚本会自动：

1. aiword：同步 `web\templates` → `webapp\templates` → commit → push → tag `v1.0.5` → push tag  
2. aicheckword：commit → push → tag `v1.0.5` → push tag  

**验证 tag 已上 GitHub：**

```cmd
git ls-remote --tags origin v1.0.5
:: 在 aicheckword 目录再执行一次
```

### 阶段 C — 打包机：拉代码 + 打镜像

**前置（首次）**：Git、Docker Desktop 已装；`d:\aicode\git_clone_repo_aiword.bat` 里 URL 已配对。

**日常发版（推荐，不含 chroma）：**

```cmd
cd /d d:\aicode
git_clone_repo_aiword.bat 1.0.5 build-apps
```

**首次部署包或需升 chroma：**

```cmd
git_clone_repo_aiword.bat 1.0.5 build
:: 或
build_aiword_stack.bat 1.0.5
```

**产物位置：**

```
d:\aicode\aiword\deploy\dist\
  aiword-1.0.5.tar.gz
  aicheckword-1.0.5.tar.gz
  aiword-stack-1.0.5.zip          （build 全量时有）
```

### 阶段 D — 上传到 Linux

**方式 1 — 只传两个 tar.gz（日常升级，推荐）**

```powershell
scp d:\aicode\aiword\deploy\dist\aiword-1.0.5.tar.gz user@服务器:/aiword/aiworddocker/aiword-stack/images/
scp d:\aicode\aiword\deploy\dist\aicheckword-1.0.5.tar.gz user@服务器:/aiword/aiworddocker/aiword-stack/images/
```

**方式 2 — 传 zip 部署包（可同时更新 upgrade.sh 等脚本）**

```powershell
scp d:\aicode\aiword\deploy\dist\aiword-stack-1.0.5.zip user@服务器:/aiword/aiworddocker/
```

### 阶段 E — Linux：部署 / 升级

**首次部署：**

```bash
cd /aiword/aiworddocker
unzip aiword-stack-1.0.5.zip -d aiword-stack
cd aiword-stack
cp .env.example .env
vi .env    # MySQL、LLM 密钥、BASE_URL 等
chmod +x *.sh
./server-deploy.sh 1.0.5
```

`.env` 镜像版本与域名示例：

```env
IMAGE_VERSION=1.0.5
AIWORD_IMAGE=aiword:1.0.5
AICHECKWORD_IMAGE=aicheckword:1.0.5
BASE_URL=http://aiword.yuwell.com
```

**日常升级（已有环境，只换业务镜像）：**

```bash
cd /aiword/aiworddocker/aiword-stack

# 确认 tar 已在 images/ 下，然后：
vi .env   # 改 IMAGE_VERSION / AIWORD_IMAGE / AICHECKWORD_IMAGE 为 1.0.5

UPGRADE_APPS_ONLY=1 NEW_IMAGE_VERSION=1.0.5 ./upgrade.sh
```

升级后浏览器 **Ctrl+F5** 强刷；宿主机 nginx 反代 `127.0.0.1:5000`。

---

## 四、流程图

```
开发机                          GitHub                    打包机                    Linux
──────                          ──────                    ──────                    ─────
dev\git-no_tag\submit.bat  ──►  main 分支
       │
dev\git-tag_release\
  release.bat 1.0.5        ──►  main + tag v1.0.5  ──►  git_clone_repo_aiword.bat
                                                          checkout v1.0.5
                                                          build-apps-all.bat
                                                               │
                                                               ▼
                                                         tar.gz / zip  ──scp──►  upgrade.sh
```

---

## 五、常见问题

| 问题 | 处理 |
|------|------|
| 打包机报「不存在 tag v1.0.5」 | 开发机先跑 `release.bat 1.0.5`，并确认 `git ls-remote --tags` 有输出 |
| 打包机只有 aiword 没有时间戳目录 | 设 `CLONE_TO_NEW_FOLDER=0`，用 `d:\aicode\aiword` 固定目录 |
| Linux 升级后页面像旧的 | 只保留一个 aiword 进程；升级后 Ctrl+F5 |
| 只改了 aiword 没改 aicheckword | 仍可发同一版本号；`build-apps` 会重建两个镜像 |

---

更细的 Docker / nginx / 排错见 `deploy\README.md`。
