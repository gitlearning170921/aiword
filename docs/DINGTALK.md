# 钉钉接入说明

## 功能说明

- **任务分配**：在页面1上传模板并设置负责人时，负责人会收到钉钉群内通知（使用姓名 @）。
- **每周四 16:00**：群内推送本周任务完成情况提醒。
- **逾期前一日 15:00**：对截止日期为「明天」且未完成的任务，向负责人发送催告。
- **每两天 9:30**：周一、三、五 9:30 在群内推送所有项目完成情况统计。

## 配置方式

### 1. 创建钉钉群机器人

1. 在钉钉群中：群设置 → 智能群助手 → 添加机器人 → 自定义。
2. 安全设置建议选择「加签」，并复制 **SEC 开头的密钥**。
3. 复制机器人 **Webhook 地址**。

### 2. 配置环境变量

在运行应用前设置（或在 `webapp/__init__.py` 的 `app.config` 中配置）：

```bash
# Windows CMD
set DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
set DINGTALK_SECRET=SECxxxx

# Linux / Mac
export DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
export DINGTALK_SECRET=SECxxxx
```

或在项目根目录创建 `.env` 文件（若使用 python-dotenv 可自动加载）：

```
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_SECRET=SECxxxx
```

### 3. 催办中的页面链接使用域名（可选）

催办通知里的「页面2（我的任务）」链接默认使用当前请求的地址；若希望其他人通过域名打开，请配置 **BASE_URL** 为对外访问的根地址（不要以 `/` 结尾），例如：

```bash
# Windows CMD
set BASE_URL=http://your-domain.com

# 或带端口
set BASE_URL=http://192.168.1.100:5000

# Linux / Mac
export BASE_URL=http://your-domain.com
```

配置后，钉钉催办中的「点击打开」将使用该域名，同事可直接点击访问。

### 4. 任务分配时 @ 某人

在页面1上传模板时，填写 **负责人姓名**，分配通知中会直接使用该姓名进行 @。

> 注意：钉钉群机器人的 @ 功能需要姓名与群成员昵称一致才能正常触发。

## 定时任务说明

应用启动时会注册 APScheduler 定时任务（需安装 `APScheduler`）。执行时间在**页面3（统计面板）**的「自动通知时间配置」中设置，保存后立即生效，无需重启。

| 任务           | 默认执行时间             | 说明                         |
|----------------|--------------------------|------------------------------|
| 周四提醒       | 每周四 16:00             | 群内发送本周任务完成情况     |
| 逾期催告       | 截止日期前一天 15:00     | 截止日为明天的未完成任务催告 |
| 项目统计       | 周一/三/五 9:30          | 群内发送项目完成率统计       |

格式约定：仅时间如 `15:00`；星期+时间如 `thu 16:00`；多日+时间如 `mon,wed,fri 9:30`（星期为英文缩写）。服务器时区为 **Asia/Shanghai**。

## 未配置钉钉时

不设置 `DINGTALK_WEBHOOK` 时：

- 任务仍可创建，仅不会发送钉钉通知。
- 定时任务会照常执行，但发送接口会因无 webhook 而跳过，不影响其他功能。
