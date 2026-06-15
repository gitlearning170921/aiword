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

参见 [第三节 · 版本升级速查](#三版本升级速查已有-linux-服务器)。把 zip 上传到 Linux 后跑 `upgrade.sh` 即可。

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

等价于：`docker load` 两个 tar.gz（或 tar）→ `docker compose -f docker-compose.prod.yml up -d`（含 **nginx + aiword + aicheckword**）

访问：`http://aiword.yuwell.com`（Nginx 80 → 容器内 aiword:5000）

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

### 步骤 A — Windows 本机打新包

将下面 `1.0.2` 换成本次版本号（需与旧版不同）：

```powershell
cd F:\wzl\learning\python\aiword\deploy

# 确认 Docker Desktop 已启动（docker version 无报错）
.\verify-scripts.bat
.\build-all.bat 1.0.2
```

产物：`dist\aiword-stack-1.0.2.zip`（内含 `images/*.tar.gz`、`docker-compose.prod.yml`、`nginx/`、`upgrade.sh` 等）。

### 步骤 B — 上传到 Linux

**方式 1（推荐，含 nginx 配置更新）**：上传整个 zip，解压覆盖配置、仅替换镜像：

```bash
# 本机
scp F:/wzl/learning/python/aiword/deploy/dist/aiword-stack-1.0.2.zip user@linux-server:/opt/

# 服务器
cd /opt/aiword-stack          # 已有部署目录
./backup.sh                   # 升级前备份

cd /opt
unzip -o aiword-stack-1.0.2.zip -d aiword-stack-new
cp -a aiword-stack-new/images/*.tar.gz aiword-stack/images/
cp -a aiword-stack-new/nginx/nginx.conf aiword-stack/nginx/nginx.conf
cp -a aiword-stack-new/upgrade.sh aiword-stack-new/server-load-images.sh aiword-stack/
chmod +x aiword-stack/*.sh
cd aiword-stack
```

**方式 2（仅换镜像）**：只 scp 两个 tar.gz 到 `aiword-stack/images/` 即可（nginx 配置未改时）。

```bash
scp deploy/dist/aiword-1.0.2.tar.gz deploy/dist/aicheckword-1.0.2.tar.gz user@linux-server:/opt/aiword-stack/images/
```

### 步骤 C — 服务器改版本并升级

```bash
cd /opt/aiword-stack
vi .env
```

至少修改（版本号与本次 build 一致）：

```env
IMAGE_VERSION=1.0.2
AIWORD_IMAGE=aiword:1.0.2
AICHECKWORD_IMAGE=aicheckword:1.0.2
BASE_URL=http://aiword.yuwell.com
```

执行升级（自动 backup → load tar.gz → 重建 aiword / aicheckword / **nginx**）：

```bash
NEW_IMAGE_VERSION=1.0.2 ./upgrade.sh
```

### 步骤 D — 验证

```bash
docker compose -f docker-compose.prod.yml ps
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/api/integration/health   # 期望 200
```

浏览器访问：`http://aiword.yuwell.com`  
页面3 确认 `BASE_URL`；Windows `aiprintword` 的 `AIWORD_BASE_URL=http://aiword.yuwell.com`。

### 回滚

`.env` 改回上一版本 tag → 再执行 `NEW_IMAGE_VERSION=旧版本 ./upgrade.sh`（旧版 tar 需在 `images/` 中）。

### 严禁

```bash
docker compose down -v    # 会删命名卷，uploads/knowledge_store/instance 全丢
```

---

## 三（附）、升级（简略）

### 本机

```powershell
.\build-all.bat 1.0.2
# 上传 dist\aiword-stack-1.0.2.zip 或 images\*.tar.gz
```

### Linux 服务器

```bash
cd /opt/aiword-stack
./backup.sh
# 更新 images/ 与 .env 中 AIWORD_IMAGE / AICHECKWORD_IMAGE
NEW_IMAGE_VERSION=1.0.2 ./upgrade.sh
```

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
| `docker-compose.prod.yml` | **Linux 生产**，仅 `image`；**默认 nginx:80 → aiword:5000** |

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

### 生产架构（域名不带端口）

```mermaid
flowchart LR
  Browser[浏览器 aiword.yuwell.com] -->|80| Nginx[nginx 容器]
  Nginx -->|appnet 5000| Aiword[aiword 容器]
  Aiword --> Aicheck[aicheckword:8000]
```

- 生产 `docker-compose.prod.yml` **默认启动 nginx**，aiword **不映射宿主机 5000**，仅内网可达。
- 本机开发仍可用 `docker-compose.yml` 直连 `http://127.0.0.1:5000`；模拟生产域名时：`docker compose --profile nginx up -d`。

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
| `build-all.bat` | Windows 本机 | 一键 build + export + pack |
| `build-images-docker.bat` 等 | Windows 本机 | 分步纯 cmd 脚本 |
| `build-images.bat` | Windows 本机 | 转调 `*-docker.bat` |
| `server-deploy.sh` | Linux | load + 首次启动 |
| `server-load-images.sh` | Linux | 仅 load 镜像 |
| `backup.sh` / `upgrade.sh` | Linux | 备份 / 升级 |

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
| 去签字失败 | Linux → Windows:5050 网络与密钥 |

---

## 十、回归脚本（需运行中环境）

```bash
cd aiword && python scripts/multi_tenant_smoke.py
python scripts/exam_center_smoke.py
```
