# aiword Docker 混合部署手册

在 Linux 服务器运行 **aiword + aicheckword（API）**；**aiprintword** 留在 Windows。**推荐流程：本机构建镜像 → 导出 tar.gz → Linux 仅 load + 启动（无需源码、无需服务器 build）。**

### 镜像瘦身说明（API 生产镜像）

| 优化项 | 说明 |
|--------|------|
| 依赖拆分 | aiword 用 `requirements-docker.txt`（无 PyInstaller）；aicheckword 用 `requirements-api.txt`（无 Streamlit/altair） |
| 多阶段 + BuildKit | Dockerfile 两阶段构建，`DOCKER_BUILDKIT=1` + pip 缓存，改代码重建更快 |
| 并行 build | `build-images-docker.bat` 同时构建两个镜像 |
| gzip 导出 | 默认 `*.tar.gz`，部署 zip 体积显著减小 |
| Streamlit 按需 | 知识库训练 UI 用 `Dockerfile.streamlit` + compose profile `admin`，不进默认生产包 |
| **禁止打进镜像** | `deploy/` 整目录（含 `ollama-docker.tar`、导出的 `*.tar`）、迁移用 `*.tar.gz`、aicheckword 根目录 `uploads.tar.gz` 等；见各仓库 `.dockerignore`。正常 aiword 镜像约 **300MB 级**，若到 GB 级说明 build context 混入了离线包 |

---

## 零、GitHub → Windows 打包服务器 → Linux 生产（推荐流程）

> 适用：开发机 + 独立 Windows 打包机 + Linux 生产服务器。本机不再直接 build，所有镜像都在打包机出。

```mermaid
flowchart LR
  Dev[开发机<br/>release.bat 1.0.2] -->|push + tag v1.0.2| GH[GitHub<br/>aiword + aicheckword]
  GH -->|git clone/fetch tag| Build[Windows 打包机<br/>server-build-from-git.bat 1.0.2]
  Build -->|aiword-stack-1.0.2.zip| Prod[Linux 生产<br/>server-deploy.sh / upgrade.sh]
```

### 0.1 开发机：发版（双仓库同名 tag）

`F:\wzl\learning\python\aiword\release.bat` 会**同时处理 aiword 与同级的 aicheckword 两个仓库**：同步前端模板 → add → commit（无变更则跳过）→ push → 打 `v<version>` tag → push tag。aiprintword 不在打包链中，需要时单独跑该仓库 `commit_push.bat`。

```cmd
cd /d F:\wzl\learning\python\aiword
release.bat 1.0.2
release.bat 1.0.2 "fix audit pagination"
```

### 0.2 打包机：首次准备

1. 装 Git for Windows + Docker Desktop（WSL2、Linux 容器），保持与开发机一致；
2. 配置 GitHub 凭据（HTTPS PAT 或 SSH key，能 `git clone` 私有仓库即可）；
3. 准备一个**独立的 driver 目录**，把 `aiword/deploy/server-build-from-git.bat` 和 `server-build.config.bat.example` 拷到这里。**注意**：driver 目录不能落在 `BUILD_ROOT` 里面（脚本会自检拦截），否则 `git clean` 会把自己清掉。

   推荐布局：

   ```
   D:\aiword-build-driver\         ← driver 目录（独立，不在 BUILD_ROOT 内）
     deploy\
       server-build-from-git.bat
       server-build.config.bat     ← 自己创建，填 GIT URL
       build-images-docker.bat     ← 一并拷过来；或脚本会调用 BUILD_ROOT\aiword 里的（已存在）
       ...
   
   %USERPROFILE%\aiword-build\     ← BUILD_ROOT（由脚本自动维护）
     aiword\
     aicheckword\
   ```

   实际上**最省事的做法**：先用 `git clone` 把 aiword 拉一份到 driver 目录（如 `D:\aiword-build-driver\aiword\`），进入 `deploy\` 编辑配置即可；这一份 driver clone 只为驱动脚本，后续 build 用的是 `BUILD_ROOT\aiword`。

4. 复制配置模板：

```cmd
cd D:\aiword-build-driver\aiword\deploy
copy server-build.config.bat.example server-build.config.bat
notepad server-build.config.bat
```

`server-build.config.bat` 必填：

```bat
set "GIT_AIWORD_URL=https://github.com/YOUR-ORG/aiword.git"
set "GIT_AICHECKWORD_URL=https://github.com/YOUR-ORG/aicheckword.git"
set "BUILD_ROOT=%USERPROFILE%\aiword-build"
```

`server-build.config.bat` 已被 `deploy/.gitignore` 排除，**含 PAT 也不会被推**。

### 0.3 打包机：一键打镜像

```cmd
cd D:\aiword-build-driver\aiword\deploy
server-build-from-git.bat 1.0.2
```

脚本流程：

1. clone 或 `git fetch --all --tags --prune` 两个仓库到 `BUILD_ROOT\aiword` 与 `BUILD_ROOT\aicheckword`；
2. 校验远程是否有 tag `v1.0.2`，否则中止（提示先去开发机跑 `release.bat`）；
3. `git checkout -f v1.0.2` + `git reset --hard` + `git clean -fdx`（aiword 保留 `deploy/dist`）；
4. 调用现有 `build-all.bat 1.0.2`（build → export gzip → pack zip）；
5. 产物：`BUILD_ROOT\aiword\deploy\dist\aiword-stack-1.0.2.zip`。

### 0.4 生产：scp + 升级

参见 [第三节 · 版本升级速查](#三版本升级速查已有-linux-服务器)。日常发版用 `build-apps-all.bat` + `UPGRADE_APPS_ONLY=1 ./upgrade.sh`；首次或升 Chroma 时用完整 `build-all.bat`。

### 0.5 排错（专属于此流程）

| 现象 | 排查 |
|------|------|
| `aiword 仓库不存在 tag v1.0.2` | 开发机没跑 `release.bat <ver>`，或 tag 没 push 到远程；本地确认 `git ls-remote --tags origin v1.0.2` |
| `git clone` 提示 403/401 | GitHub 凭据未生效；HTTPS 用 PAT、或改 SSH URL；私有仓库账户需有访问权 |
| `aicheckword push tag 失败 (远程已存在同名 tag)` | 同版本号已发过；要么换 `1.0.3`，要么手动 `git push -f origin v1.0.2`（**谨慎**） |
| `build-all.bat` 在打包机上比开发机慢 | 第一次跑无 BuildKit 缓存属正常；后续重复同版本应秒级；不要清 `BUILD_ROOT` 里的 `node_modules/` 之类（实际不存在，仅作示例） |
| 打包机 Docker Desktop 未启动 | 脚本会用 `docker version` 检测并中止；启动后重跑 |

---

## 一、本机（Windows）构建镜像

### 1. 安装 Docker Desktop

1. 下载安装 [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
2. 使用 **WSL2 后端**，模式为 **Linux 容器**（默认）
3. 重启终端，确认：

```powershell
docker version
```

### 2. 目录结构

本机构建时 **aiword** 与 **aicheckword** 需同级：

```
F:\wzl\learning\python\
  aiword\
  aicheckword\
```

### 3. 构建 Linux 镜像

### 3. 自检 + 一键构建

> **必须在 `aiword\deploy` 目录执行**，不要在 `deploy\dist\aiword-stack-*`（那是给 Linux load 用的旧脚本副本）。

```powershell
cd F:\wzl\learning\python\aiword\deploy

# 自检（路径、docker、脚本语法；不构建镜像）
.\verify-scripts.bat

# 一键：构建 + 导出 tar.gz + 打 zip 部署包
.\build-all.bat 1.0.0
```

分步执行：

```powershell
.\build-images-docker.bat 1.0.0
.\export-images-docker.bat 1.0.0
.\pack-for-server-docker.bat 1.0.0
```

`build-images.bat` / `export-images.bat` / `pack-for-server.bat` 会自动转调上述 `*-docker.bat`（纯 cmd，无 PowerShell 编码问题）。

> **说明**：Windows 批处理与 PowerShell 5.1 对 UTF-8 中文支持差，部署脚本统一使用 **ASCII 的 .bat**；`.ps1` 仅作备用且已为纯英文。

若在 **cmd.exe** 中，可省略 `.\`：

```cmd
build-images.bat 1.0.0
```

等价的 PowerShell（若本机已允许运行脚本）：

```powershell
.\build-images.ps1 -Version 1.0.0
.\export-images.ps1 -Version 1.0.0
.\pack-for-server.ps1 -Version 1.0.0
```

若直接运行 `.ps1` 报「禁止运行脚本」，任选其一：

```powershell
# 仅当前窗口临时放行
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build-images.ps1 -Version 1.0.0
```

```powershell
# 单次调用，不改系统策略
powershell -ExecutionPolicy Bypass -File .\build-images.ps1 -Version 1.0.0
```

产物：

| 文件 | 说明 |
|------|------|
| `dist/aiword-1.0.0.tar.gz` | aiword 镜像（gzip；无 gzip 时回退 `.tar`） |
| `dist/aicheckword-1.0.0.tar.gz` | aicheckword 镜像 |
| `dist/aiword-stack-1.0.0.zip` | **上传到 Linux 的完整部署包** |

> ARM 服务器（如部分云 ARM 实例）构建时：`.\build-images.ps1 -Version 1.0.0 -Platform linux/arm64`

### 4. 本机验证（可选）

```powershell
cd deploy
copy .env.example .env
# 编辑 .env 填 MySQL 等

# Linux / Git Bash：
# gunzip -c dist/aiword-1.0.0.tar.gz | docker load
# gunzip -c dist/aicheckword-1.0.0.tar.gz | docker load
# 或使用 server-load-images.sh（自动识别 .tar.gz / .tar）

docker compose -f docker-compose.prod.yml up -d
```

Linux 服务器 load 见 [`server-load-images.sh`](server-load-images.sh)（自动识别 `.tar.gz` / `.tar`）。

---

## 二、Linux 服务器部署（无需源码）

### 1. 上传部署包

```bash
scp deploy/dist/aiword-stack-1.0.0.zip user@linux-server:/opt/
```

### 2. 解压并配置

```bash
cd /opt
unzip aiword-stack-1.0.0.zip -d aiword-stack
cd aiword-stack   # 进入解压后的目录（含 docker-compose.prod.yml、images/）

cp .env.example .env
vi .env           # MySQL、LLM 密钥、AIPRINTWORD_BASE_URL 等
```

`.env` 中镜像 tag 与对外域名（**80 反代，无需 :5000**）：

```env
IMAGE_VERSION=1.0.0
AIWORD_IMAGE=aiword:1.0.0
AICHECKWORD_IMAGE=aicheckword:1.0.0
BASE_URL=http://aiword.yuwell.com
NGINX_HTTP_PORT=80
AIWORD_BOOTSTRAP_DATABASE_URL=mysql+pymysql://user:pass@mysql-host:3306/aiword?charset=utf8mb4
```

DNS 将 `aiword.yuwell.com` **A 记录** 解析到 Linux 服务器 IP（CNAME 指到同域网关亦可）；防火墙放行 **80**（上 HTTPS 时再放行 **443**）。

### 3. 一键启动

```bash
chmod +x server-deploy.sh server-load-images.sh backup.sh upgrade.sh
./server-deploy.sh 1.0.0
```

等价于：`docker load` 镜像 tar.gz → `docker compose -f docker-compose.prod.yml up -d`（**chroma + aicheckword + aiword**，不含 nginx 容器）

访问：`http://aiword.yuwell.com`（**宿主机 nginx** 80 → `127.0.0.1:5000` → aiword 容器）

### 4. 页面3 核对

| 配置项 | 值 |
|--------|-----|
| `BASE_URL` | `http://aiword.yuwell.com` |
| `QUIZ_API_BASE_URL` | `http://aicheckword:8000` |
| `AICHECKWORD_DRAFT_API_BASE` | `http://aicheckword:8000` |
| `AIPRINTWORD_BASE_URL` | `http://<Windows IP>:5050` |

保存后：`docker compose -f docker-compose.prod.yml restart aiword`

---

## 三、版本升级速查（已有 Linux 服务器）

> 适用：服务器已跑通过，只需换新版镜像（及可选 nginx 配置）。**数据在 MySQL 与 Docker 卷里，升级不丢。**  
> **Chroma 向量库已在 `chroma_data` 卷中持久化，日常发版不必每次升 chroma 镜像。**

### 升什么？（先看这张表）

| 组件 | 日常功能发版 | 何时需要一起升 |
|------|-------------|----------------|
| **aiword** | ✅ 每次 | — |
| **aicheckword** | ✅ 每次（API 有改动时） | — |
| **chroma** | ❌ 通常跳过 | 首次部署；或修改了 `deploy/chroma-image.tag`（如 0.6.3→0.7.x）；Chroma 服务异常需换官方镜像 |
| **knowledge_store 迁移** | ❌ 跳过 | 仅**新环境**或**换服务器**且向量在旧机本地目录时，用 `migrate-knowledge-store.sh`（一次性） |

`chroma:x.y.z` 中的 `x.y.z` 只是部署包版本号；实际镜像是 `chromadb/chroma:<chroma-image.tag>`（当前 `0.6.3`）。**随意升 Chroma 大版本可能导致与 aicheckword 内 `chromadb` 客户端不兼容。**

---

### 3.1 日常升级（推荐：仅 aiword + aicheckword）

#### 步骤 A — Windows 本机构建并导出

将 `1.0.3` 换成本次版本号：

```powershell
cd F:\wzl\learning\python\aiword\deploy

.\verify-scripts.bat
.\build-apps-all.bat 1.0.3
```

等价分步：`build-apps-docker.bat` → `export-apps-docker.bat`（**不**构建/导出 chroma）。

产物（只需这两个）：

- `dist\aiword-1.0.3.tar.gz`
- `dist\aicheckword-1.0.3.tar.gz`

> 若仍用 `build-all.bat`，会顺带打 chroma 镜像，上传时可忽略 `chroma-*.tar.gz`。

#### 步骤 B — 上传到 Linux（二选一）

**方式 1 — 上传 zip 部署包（推荐：可同时更新 `upgrade.sh` / nginx 等）**

本机：

```powershell
scp F:\wzl\learning\python\aiword\deploy\dist\aiword-stack-1.0.3.zip user@10.26.1.221:/aiword/aiworddocker/
```

服务器解压并只替换镜像与脚本（**不要覆盖 `.env`**）：

```bash
cd /aiword/aiworddocker

# 解压到临时目录（zip 内层目录名一般为 aiword-stack-1.0.3）
unzip -o aiword-stack-1.0.3.zip -d aiword-stack-staging

# 进入解压出的目录（若 VERSION 与 zip 名不一致，以实际目录名为准）
cd aiword-stack-staging/aiword-stack-1.0.3

# 仅复制业务镜像 tar.gz 到现有部署目录（日常升级不含 chroma）
cp -a images/aiword-1.0.3.tar.gz images/aicheckword-1.0.3.tar.gz \
  /aiword/aiworddocker/aiword-stack/images/

# 同步升级脚本（含 UPGRADE_APPS_ONLY 支持）
cp -a upgrade.sh server-load-apps-only.sh server-load-images.sh \
  /aiword/aiworddocker/aiword-stack/
chmod +x /aiword/aiworddocker/aiword-stack/*.sh

# 若 nginx 样例有更新（按需）
# cp -a nginx/nginx.conf /aiword/aiworddocker/aiword-stack/nginx/nginx.conf

cd /aiword/aiworddocker/aiword-stack
```

> 若用 `build-apps-all.bat` 只打了两个 tar.gz、没有 zip，用下面的方式 2。

**方式 2 — 只上传镜像 tar.gz（最快，不解压 zip）**

```powershell
scp F:\wzl\learning\python\aiword\deploy\dist\aiword-1.0.3.tar.gz user@10.26.1.221:/aiword/aiworddocker/aiword-stack/images/
scp F:\wzl\learning\python\aiword\deploy\dist\aicheckword-1.0.3.tar.gz user@10.26.1.221:/aiword/aiworddocker/aiword-stack/images/
```

服务器确认文件在位：

```bash
ls -lh /aiword/aiworddocker/aiword-stack/images/aiword-1.0.3.tar.gz \
       /aiword/aiworddocker/aiword-stack/images/aicheckword-1.0.3.tar.gz
```

**说明**：`tar.gz` 是 **Docker 镜像**（用 `docker load` 导入），**不是** zip；只有上传 **zip 部署包** 时才需要 `unzip`。日常若脚本已是最新，方式 2 即可。

#### 步骤 C — 服务器改 `.env` 并升级

```bash
cd /aiword/aiworddocker/aiword-stack
./backup.sh
vi .env
```

**只改业务镜像 tag**；`CHROMA_IMAGE` **保持原值不动**（例如仍是 `chroma:1.0.0`）：

```env
IMAGE_VERSION=1.0.3
AIWORD_IMAGE=aiword:1.0.3
AICHECKWORD_IMAGE=aicheckword:1.0.3
# CHROMA_IMAGE=chroma:1.0.0   ← 不要改
BASE_URL=http://aiword.yuwell.com
```

执行（`UPGRADE_APPS_ONLY=1` 只 load/重建 aiword + aicheckword，**不碰 chroma 容器**）：

```bash
UPGRADE_APPS_ONLY=1 NEW_IMAGE_VERSION=1.0.3 ./upgrade.sh
```

等价手动：

```bash
./server-load-apps-only.sh 1.0.3
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate aicheckword aiword
```

#### 步骤 D — 验证

```bash
docker compose -f docker-compose.prod.yml ps
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/api/integration/health   # 期望 200
curl -s http://127.0.0.1:8100/api/v1/heartbeat   # Chroma 未重建时应仍正常
```

浏览器访问 `http://aiword.yuwell.com`，**Ctrl+F5** 强刷。

---

### 3.2 全量升级（含 chroma，少用）

仅在 **首次装 chroma**、**改了 `chroma-image.tag`** 或 **必须换 Chroma 官方镜像** 时使用：

```powershell
cd F:\wzl\learning\python\aiword\deploy
.\build-all.bat 1.0.3
```

**上传 zip 并解压（含 chroma 镜像时）：**

```powershell
scp F:\wzl\learning\python\aiword\deploy\dist\aiword-stack-1.0.3.zip user@10.26.1.221:/aiword/aiworddocker/
```

```bash
cd /aiword/aiworddocker
unzip -o aiword-stack-1.0.3.zip -d aiword-stack-staging
cd aiword-stack-staging/aiword-stack-1.0.3
cp -a images/*.tar.gz /aiword/aiworddocker/aiword-stack/images/
cp -a upgrade.sh server-load-images.sh /aiword/aiworddocker/aiword-stack/
chmod +x /aiword/aiworddocker/aiword-stack/*.sh
cd /aiword/aiworddocker/aiword-stack
```

`.env` 中同步改 `CHROMA_IMAGE`：

```env
CHROMA_IMAGE=chroma:1.0.3
```

```bash
cd /aiword/aiworddocker/aiword-stack
./backup.sh
NEW_IMAGE_VERSION=1.0.3 ./upgrade.sh
```

> 全量升级会 `--force-recreate chroma`，**卷 `chroma_data` 仍在**；但若 Chroma 大版本不兼容，需先评估再升。

---

### 回滚

`.env` 改回上一版本业务 tag（`CHROMA_IMAGE` 可不变）→  
`UPGRADE_APPS_ONLY=1 NEW_IMAGE_VERSION=旧版本 ./upgrade.sh`（旧版 tar 需在 `images/` 中）。

### 严禁

```bash
docker compose down -v    # 会删命名卷，chroma_data / uploads / instance 全丢
```

---

## 三（附）、升级（一页纸）

**日常：**

```powershell
# Windows — 二选一
.\build-apps-all.bat 1.0.3          # 只出两个 tar.gz
# 或
.\build-all.bat 1.0.3               # 出 zip + 三个 tar.gz（含 chroma）
```

```bash
# Linux — zip 路径需先 unzip，见 3.1 步骤 B 方式 1
# 仅 tar.gz 则 scp 到 images/ 后直接：
cd /aiword/aiworddocker/aiword-stack
./backup.sh
# .env: 只改 AIWORD_IMAGE / AICHECKWORD_IMAGE
UPGRADE_APPS_ONLY=1 NEW_IMAGE_VERSION=1.0.3 ./upgrade.sh
```

**含 chroma（少见）：** `build-all.bat` → 三个 tar.gz → `NEW_IMAGE_VERSION=... ./upgrade.sh`（不设 `UPGRADE_APPS_ONLY`）。

---

## 四、Windows aiprintword 联调

```env
AIWORD_BASE_URL=http://aiword.yuwell.com
AIWORD_HANDOFF_SECRET=<与 aiword 相同>
AIWORD_INTEGRATION_SECRET=<与 aiword 相同>
```

验证：页面1「去签字」、初稿/审核页、签字页「同步项目」。

---

## 五、数据持久化

| 数据 | 位置 |
|------|------|
| 业务主数据 | 外部 MySQL |
| 冷启动/锁 | 卷 `aiword-stack_aiword_instance` |
| 向量库 | 卷 `aicheck_knowledge` |
| 作业文件 | 卷 `aicheck_uploads` / `aiword_uploads` |

**镜像只含代码；升级换镜像，卷与 MySQL 不动。**

---

## 六、compose 文件说明

| 文件 | 用途 |
|------|------|
| `docker-compose.yml` | 本机开发，含 `build`，可 `--build`；profile `admin` 可启 Streamlit |
| `docker-compose.prod.yml` | **Linux 生产**，仅 `image`；**宿主机 nginx** → `127.0.0.1:5000`（compose 不含 nginx 容器） |

### Streamlit 运维 UI（可选）

本机需先构建 API 镜像，再叠加 Streamlit 层：

```powershell
.\build-images-docker.bat 1.0.0
cd ..\..\aicheckword
docker build --build-arg AICHECKWORD_BASE_TAG=1.0.0 -t aicheckword-streamlit:1.0.0 -f Dockerfile.streamlit .
cd ..\aiword\deploy
docker compose --profile admin up -d aicheckword-streamlit
```

访问：`http://localhost:8501`

### 生产架构（域名不带端口，宿主机 nginx）

```mermaid
flowchart LR
  Browser[浏览器 aiword.yuwell.com] -->|80| HostNginx[宿主机 nginx]
  HostNginx -->|127.0.0.1:5000| Aiword[aiword 容器]
  Aiword --> Aicheck[aicheckword:8000]
  Aiword --> Chroma[chroma:8000]
```

- 生产 `docker-compose.prod.yml` **不启动 nginx 容器**；`deploy/nginx/nginx.conf` 仅作宿主机配置样例。
- aiword 映射 **`127.0.0.1:5000:5000`**，仅供本机 nginx 反代，勿暴露公网 5000。
- 本机开发仍可用 `docker-compose.yml` 直连 `http://127.0.0.1:5000`；模拟容器 nginx 时：`docker compose --profile nginx up -d`。

### HTTPS（可选）

1. 证书放入 `deploy/nginx/certs/fullchain.pem` 与 `privkey.pem`
2. 取消 `deploy/nginx/nginx.conf` 中 443 `server` 注释
3. `.env` 中 `BASE_URL=https://aiword.yuwell.com`，放行防火墙 443

---

## 七、私有 Registry（可选，替代 tar）

本机 push 后，Linux 上 `.env` 填 Registry 地址，`docker compose pull` 即可：

```powershell
docker tag aiword:1.0.0 registry.example.com/aiword:1.0.0
docker push registry.example.com/aiword:1.0.0
```

---

## 八、脚本索引

| 脚本 | 运行位置 | 作用 |
|------|----------|------|
| `verify-scripts.bat` | Windows 本机 | 自检（不构建） |
| `build-all.bat` | Windows 本机 | 一键 build + export + pack（**含 chroma**） |
| `build-apps-all.bat` | Windows 本机 | **日常升级**：仅 build/export aiword + aicheckword |
| `build-apps-docker.bat` / `export-apps-docker.bat` | Windows 本机 | 分步：仅业务镜像 |
| `build-images-docker.bat` 等 | Windows 本机 | 分步纯 cmd 脚本（含 chroma） |
| `server-deploy.sh` | Linux | load + 首次启动 |
| `server-load-images.sh` | Linux | load 三个镜像（含 chroma） |
| `server-load-apps-only.sh` | Linux | **仅 load** aiword + aicheckword |
| `backup.sh` / `upgrade.sh` | Linux | 备份 / 升级（`UPGRADE_APPS_ONLY=1` 跳过 chroma） |

---

## 九、排错

| 现象 | 排查 |
|------|------|
| `docker` 命令不存在 | 安装 Docker Desktop，重启终端 |
| `.ps1` 解析错误 / 乱码 | 不要用 `.ps1`，改用 `.\build-all.bat 1.0.0` |
| `failed to resolve ... docker/dockerfile:1` / `manifests/1`: EOF | 已去掉 Dockerfile 首行 `# syntax=...`；若仍失败则是 `python:3.11-slim-bookworm` 拉取问题，配置 Docker Desktop **registry-mirrors** |
| `failed to resolve python:3.11-slim-bookworm` | Docker Hub 网络不通；Docker Desktop 配置国内 `registry-mirrors` 或 VPN |
| pip 安装非常慢 / 卡住 | Dockerfile 已默认使用清华 pip 源；aicheckword 首次 pip 约 10–20 分钟属正常 |
| build 窗口长时间无输出 | 已改为**串行**构建并实时打印进度；勿把旧镜像放在 `deploy/dist/`（会拖慢 context，已在 .dockerignore 排除） |
| `transferring context` 很多 GB | 检查 aiword 下 `deploy/dist/` 是否过大；应排除后再 build |
| Linux 上镜像架构不对 | 本机构建默认 `linux/amd64`；ARM 服务器需改 PLATFORM |
| aiword 连不上 MySQL | `AIWORD_BOOTSTRAP_DATABASE_URL`、防火墙 |
| 初稿 502 | `docker compose logs aicheckword` |
| **知识库/案例下拉加载失败** | ① 页面4 将 `QUIZ_API_BASE_URL`、`AICHECKWORD_DRAFT_API_BASE` 设为 `http://aicheckword:8000`（**勿**用 `127.0.0.1:8000`）；② `curl 'http://127.0.0.1:5000/api/integration/health?upstream=1'` 看 `upstream.ok`；③ `docker exec aicheckword curl -s 'http://127.0.0.1:8000/status?collection=regulations'` 查 MySQL；④ 核对 `.env` 中 `MYSQL_HOST` 非占位符 `mysql-host` |
| **初稿页空白 / 按钮无反应** | ① 浏览器 F12 → Network 看 `draft_gen.js` 是否 **200**（非 404/304 旧缓存）；② **Ctrl+F5** 强刷；③ 宿主机 nginx 勿对 `/static/` 设 `expires 7d`（见 `deploy/nginx/nginx.conf`）；④ 控制台是否有 JS 语法错误 |
| Streamlit 知识库页打不开 | 默认生产栈不含 Streamlit；需 `Dockerfile.streamlit` + `docker compose --profile admin up -d aicheckword-streamlit` |
| 去签字失败 | Linux → Windows:5050 网络与密钥 |

---

## 十、回归脚本（需运行中环境）

```bash
cd aiword && python scripts/multi_tenant_smoke.py
python scripts/exam_center_smoke.py
```
