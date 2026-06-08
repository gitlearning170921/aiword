# aiword Docker 混合部署手册

在 Linux 服务器运行 **aiword + aicheckword（API）**；**aiprintword** 留在 Windows。**推荐流程：本机构建镜像 → 导出 tar → Linux 仅 load + 启动（无需源码、无需服务器 build）。**

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

```powershell
cd F:\wzl\learning\python\aiword\deploy

# 自检（路径、docker、脚本语法；不构建镜像）
.\verify-scripts.bat

# 一键：构建 + 导出 tar + 打 zip 部署包
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
| `dist/aiword-1.0.0.tar` | aiword 镜像 |
| `dist/aicheckword-1.0.0.tar` | aicheckword 镜像 |
| `dist/aiword-stack-1.0.0.zip` | **上传到 Linux 的完整部署包** |

> ARM 服务器（如部分云 ARM 实例）构建时：`.\build-images.ps1 -Version 1.0.0 -Platform linux/arm64`

### 4. 本机验证（可选）

```powershell
cd deploy
copy .env.example .env
# 编辑 .env 填 MySQL 等

docker load -i dist\aiword-1.0.0.tar
docker load -i dist\aicheckword-1.0.0.tar
docker compose -f docker-compose.prod.yml up -d
```

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

`.env` 中镜像 tag 需与版本一致：

```env
IMAGE_VERSION=1.0.0
AIWORD_IMAGE=aiword:1.0.0
AICHECKWORD_IMAGE=aicheckword:1.0.0
AIWORD_BOOTSTRAP_DATABASE_URL=mysql+pymysql://user:pass@mysql-host:3306/aiword?charset=utf8mb4
```

### 3. 一键启动

```bash
chmod +x server-deploy.sh server-load-images.sh backup.sh upgrade.sh
./server-deploy.sh 1.0.0
```

等价于：`docker load` 两个 tar → `docker compose -f docker-compose.prod.yml up -d`

访问：`http://<服务器IP>:5000`

### 4. 页面3 核对

| 配置项 | 值 |
|--------|-----|
| `QUIZ_API_BASE_URL` | `http://aicheckword:8000` |
| `AICHECKWORD_DRAFT_API_BASE` | `http://aicheckword:8000` |
| `AIPRINTWORD_BASE_URL` | `http://<Windows IP>:5050` |

保存后：`docker compose -f docker-compose.prod.yml restart aiword`

---

## 三、升级（本机重新构建 → 服务器 load）

### 本机

```powershell
.\build-images.ps1 -Version 1.0.1
.\export-images.ps1 -Version 1.0.1
# 只需上传新的 images/*.tar 或重新 pack
```

### Linux 服务器

```bash
cd /opt/aiword-stack
./backup.sh

# 上传新 tar 到 images/
./server-load-images.sh 1.0.1

# 修改 .env 中 AIWORD_IMAGE / AICHECKWORD_IMAGE 为 1.0.1
NEW_IMAGE_VERSION=1.0.1 ./upgrade.sh
# 或：docker compose -f docker-compose.prod.yml up -d --force-recreate
```

### 严禁

```bash
docker compose down -v    # 删除命名卷，数据全丢
```

---

## 四、Windows aiprintword 联调

```env
AIWORD_BASE_URL=http://<Linux服务器>:5000
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
| `docker-compose.yml` | 本机开发，含 `build`，可 `--build` |
| `docker-compose.prod.yml` | **Linux 生产**，仅 `image`，无源码 |

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
| `failed to resolve python:3.11-slim-bookworm` | Docker Hub 网络不通；Docker Desktop 配置国内 `registry-mirrors` 或 VPN |
| pip 安装非常慢 / 卡住 | Dockerfile 已默认使用清华 pip 源；如内网另有源，设置 `PIP_INDEX_URL` 构建参数覆盖 |
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
