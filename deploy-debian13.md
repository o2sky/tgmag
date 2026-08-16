# tgmag 完整部署指南（Debian 13）

> 适用分支：`feature/cloudflare-temp-mail-webhook`  
> 适用环境：Debian 13 · Python 3.13 · PostgreSQL 17  
> 部署目录：`/opt/tg-account-bot` · 服务用户：`tg-account-bot`

---

## 目录

**基础部署（必须完成）**

1. [准备工作](#1-准备工作)
2. [安装系统依赖](#2-安装系统依赖)
3. [创建服务用户](#3-创建服务用户)
4. [克隆代码](#4-克隆代码)
5. [创建 Python venv 并安装依赖](#5-创建-python-venv-并安装依赖)
6. [配置 PostgreSQL](#6-配置-postgresql)
7. [创建并编辑 .env](#7-创建并编辑-env)
8. [生成 Fernet 密钥](#8-生成-fernet-密钥)
9. [初始化数据库](#9-初始化数据库)
10. [前台测试运行](#10-前台测试运行)
11. [配置 systemd](#11-配置-systemd)
12. [配置 Nginx + HTTPS（可选）](#12-配置-nginx--https可选)
13. [配置 Gmail 登录邮箱保护（可选）](#13-配置-gmail-登录邮箱保护可选)
14. [日常维护](#14-日常维护)
15. [常见报错速查](#15-常见报错速查)

**Cloudflare Temp Email Webhook（可选）**

> 仅在需要通过 Cloudflare 接收登录验证码邮件时才需要配置此部分。  
> 完成第 1～11 节基础部署后再进行。

16. [架构说明](#16-架构说明)
17. [Cloudflare 部署前提](#17-cloudflare-部署前提)
18. [VPS：生成 Webhook Secret](#18-vps生成-webhook-secret)
19. [VPS：更新 .env 启用 Webhook](#19-vps更新-env-启用-webhook)
20. [VPS：执行数据库迁移](#20-vps执行数据库迁移)
21. [VPS：配置 Nginx 反向代理](#21-vps配置-nginx-反向代理)
22. [Cloudflare：创建 D1 数据库](#22-cloudflare创建-d1-数据库)
23. [Cloudflare：创建空 Worker](#23-cloudflare创建空-worker)
24. [本地：安装 Wrangler 并登录](#24-本地安装-wrangler-并登录)
25. [本地：下载并部署 worker.js](#25-本地下载并部署-workerjs)
26. [Cloudflare：配置 Worker Variables 和 Secret](#26-cloudflare配置-worker-variables-和-secret)
27. [Cloudflare：绑定 D1](#27-cloudflare绑定-d1)
28. [Cloudflare：验证 Worker 基础 API](#28-cloudflare验证-worker-基础-api)
29. [Cloudflare：配置 Email Routing](#29-cloudflare配置-email-routing)
30. [Cloudflare：创建并绑定 KV](#30-cloudflare创建并绑定-kv)
31. [Cloudflare：配置全局 Webhook](#31-cloudflare配置全局-webhook)
32. [测试：curl 模拟 Webhook](#32-测试curl-模拟-webhook)
33. [测试：真实邮件端到端](#33-测试真实邮件端到端)
34. [Telegram Bot 内验证](#34-telegram-bot-内验证)
35. [Cloudflare 部署检查清单](#35-cloudflare-部署检查清单)
36. [Cloudflare 常见故障排查](#36-cloudflare-常见故障排查)
37. [升级 Cloudflare Temp Email Worker](#37-升级-cloudflare-temp-email-worker)

---

# 基础部署

## 1. 准备工作

部署前请准备好以下值，后续填入 `.env`：

| 配置项 | 获取方式 |
|---|---|
| `BOT_TOKEN` | `@BotFather` → `/newbot` |
| `TG_API_ID` / `TG_API_HASH` | https://my.telegram.org → API development tools |
| `ADMIN_IDS` | 你自己的 Telegram 数字用户 ID（可发消息给 `@userinfobot` 获取） |
| 数据库密码 | 自行设定，建议纯字母数字，避免特殊字符 |
| `FERNET_KEY` | 第 8 节生成 |

**Debian 13 特别说明：**

- Python 默认为 3.13，`pip` 受 PEP 668 保护，**禁止系统级安装**，所有依赖必须在 venv 内安装。
- `python3` 可执行文件路径为 `/usr/bin/python3`，`sudo -u` 切换用户后需用完整路径。
- PostgreSQL 默认版本为 17，行为与 16 一致。

---

## 2. 安装系统依赖

```bash
sudo apt-get update
sudo apt-get install -y \
  git \
  python3 \
  python3-venv \
  python3-full \
  build-essential \
  libpq-dev \
  postgresql \
  postgresql-client
```

确认关键工具可用：

```bash
git --version
python3 --version
which python3
sudo systemctl status postgresql --no-pager
```

如果 PostgreSQL 未自动启动：

```bash
sudo systemctl enable --now postgresql
```

---

## 3. 创建服务用户

```bash
sudo useradd --system --user-group \
  --home-dir /opt/tg-account-bot \
  --shell /usr/sbin/nologin \
  tg-account-bot
```

如果提示用户已存在可跳过，确认用户存在：

```bash
id tg-account-bot
```

---

## 4. 克隆代码

```bash
sudo git clone \
  --branch feature/cloudflare-temp-mail-webhook \
  https://github.com/openhomek/tgmag.git \
  /opt/tg-account-bot

sudo chown -R tg-account-bot:tg-account-bot /opt/tg-account-bot
```

确认目录权限：

```bash
ls -la /opt/tg-account-bot/
```

输出中属主应为 `tg-account-bot`。

---

## 5. 创建 Python venv 并安装依赖

> **注意**：所有命令使用 `/usr/bin/python3` 完整路径，避免 `sudo -u` 时 PATH 查找失败。

```bash
# 创建 venv
sudo -u tg-account-bot /usr/bin/python3 -m venv /opt/tg-account-bot/.venv

# 升级 pip 和 wheel
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pip install \
  --upgrade pip wheel

# 安装项目依赖
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pip install \
  -r /opt/tg-account-bot/requirements.txt

# 创建数据目录
sudo install -d -o tg-account-bot -g tg-account-bot -m 700 \
  /opt/tg-account-bot/data/sessions \
  /opt/tg-account-bot/data/backups
```

确认 venv 创建成功：

```bash
ls /opt/tg-account-bot/.venv/bin/python
```

---

## 6. 配置 PostgreSQL

创建数据库用户（执行后会交互提示输入两次密码）：

```bash
sudo -u postgres createuser --pwprompt tg_bot
```

创建数据库：

```bash
sudo -u postgres createdb --owner=tg_bot tg_account_bot
```

确认数据库创建成功：

```bash
sudo -u postgres psql -c '\l'
```

列表中应出现 `tg_account_bot`，Owner 为 `tg_bot`。

---

## 7. 创建并编辑 .env

如果仓库内没有 `.env.example`，直接创建：

```bash
sudo -u tg-account-bot touch /opt/tg-account-bot/.env
sudo chmod 600 /opt/tg-account-bot/.env
```

编辑：

```bash
sudoedit /opt/tg-account-bot/.env
```

粘贴以下内容，**替换所有占位值**后保存：

```env
# ===== 必需 =====
BOT_TOKEN=1234567890:replace_with_real_bot_token
TG_API_ID=123456
TG_API_HASH=replace_with_real_api_hash
ADMIN_IDS=123456789
DATABASE_URL=postgresql+asyncpg://tg_bot:replace_with_db_password@127.0.0.1:5432/tg_account_bot
FERNET_KEY=replace_after_step8

# ===== 目录 =====
SESSION_DIR=./data/sessions
BACKUP_DIR=./data/backups

# ===== 日志 =====
LOG_LEVEL=INFO

# ===== Mini App（暂不启用）=====
MINI_APP_ENABLED=false

# ===== 登录邮箱保护（暂不启用，配置好再开）=====
LOGIN_EMAIL_PROTECTION_ENABLED=false
```

> **格式说明：**
> - 布尔值用 `true` / `false`，不加引号。
> - 逗号分隔的列表（如 `ADMIN_IDS=111,222`）不要对整行套引号。
> - 密码若含 `@` `:` `/` `#` `%` 等字符，整个值用单引号包裹：`KEY='pa$$word'`。
> - `DATABASE_URL` 中密码含特殊字符时需做 URL 编码，建议用纯字母数字密码。

---

## 8. 生成 Fernet 密钥

**确保已关闭上一步的编辑器**，再执行：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

复制输出的一行字符串，填入 `.env` 的 `FERNET_KEY`：

```bash
sudoedit /opt/tg-account-bot/.env
# 找到 FERNET_KEY=replace_after_step8 这一行，替换为实际值
```

> ⚠️ **重要**：
> - 密钥不要提交 Git，不要和数据库备份放同一位置。
> - 密钥丢失或随意更换将导致所有加密数据无法解密。
> - 迁移服务器时必须同步迁移此密钥。

---

## 9. 初始化数据库

运行 Alembic 迁移（首次部署和每次升级代码后都要执行）：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  upgrade head
```

确认当前迁移版本：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  current
```

---

## 10. 前台测试运行

配置 systemd 之前，先前台运行确认没有报错：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python \
  -m app.main
```

看到类似以下输出说明正常：

```
INFO  Bot started polling ...
```

确认无误后按 `Ctrl+C` 停止，继续配置 systemd。

常见报错：

| 报错 | 原因 | 解决 |
|---|---|---|
| `ValidationError` | `.env` 缺少必需字段或格式错误 | 检查第 7 节配置 |
| `数据库尚未初始化` | 未执行 alembic | 执行第 9 节 |
| `InvalidFernetKey` | FERNET_KEY 格式错误 | 重新生成第 8 节 |
| `could not connect to server` | PostgreSQL 未启动或密码错误 | 检查第 6 节 |

---

## 11. 配置 systemd

```bash
sudo install -m 644 \
  /opt/tg-account-bot/ops/systemd/tg-account-bot.service \
  /etc/systemd/system/tg-account-bot.service

sudo systemctl daemon-reload
sudo systemctl enable --now tg-account-bot
```

查看服务状态：

```bash
sudo systemctl status tg-account-bot --no-pager
```

实时查看日志：

```bash
sudo journalctl -u tg-account-bot -f
```

查看最近 100 行：

```bash
sudo journalctl -u tg-account-bot -n 100 --no-pager
```

---

## 12. 配置 Nginx + HTTPS（可选）

> 仅在需要 Mini App 或 Cloudflare Webhook 时配置。如果只使用 Gmail 后端，可跳过本节。

### 12.1 安装 Nginx 和 Certbot

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

### 12.2 更新 .env 启用 Mini App

```bash
sudoedit /opt/tg-account-bot/.env
```

追加或修改以下字段：

```env
MINI_APP_ENABLED=true
MINI_APP_HOST=127.0.0.1
MINI_APP_PORT=8080
MINI_APP_PUBLIC_URL=https://bot.example.com/mini-app
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
```

### 12.3 创建 Nginx 配置

```bash
sudo tee /etc/nginx/sites-available/tg-account-bot > /dev/null <<'EOF'
server {
    listen 80;
    server_name bot.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name bot.example.com;

    ssl_certificate     /etc/letsencrypt/live/bot.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.example.com/privkey.pem;

    location /mini-app {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
EOF
```

### 12.4 启用并申请证书

```bash
sudo ln -sf /etc/nginx/sites-available/tg-account-bot \
  /etc/nginx/sites-enabled/tg-account-bot

sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d bot.example.com
```

### 12.5 验证

```bash
curl -I https://bot.example.com/mini-app
ss -lntp | grep 8080
```

### 12.6 在 @BotFather 配置入口

1. 发送 `/mybots` → 选择机器人 → `Bot Settings` → `Configure Mini App` → `Enable Mini App`
2. 填写 `MINI_APP_PUBLIC_URL` 的值
3. 资料页出现"打开应用"按钮即成功

重启服务：

```bash
sudo systemctl restart tg-account-bot
```

---

## 13. 配置 Gmail 登录邮箱保护（可选）

> 仅在使用 Gmail 接收 Telegram 登录验证码时配置。使用 Cloudflare 后端请见第 16～37 节。

### 13.1 准备 Gmail 应用专用密码

1. Gmail 账号开启两步验证
2. 生成应用专用密码（Google 账号 → 安全 → 应用专用密码）
3. 在 Cloudflare Email Routing 中将 catch-all 转发到该 Gmail 地址

### 13.2 更新 .env

```bash
sudoedit /opt/tg-account-bot/.env
```

```env
LOGIN_EMAIL_PROTECTION_ENABLED=true
LOGIN_EMAIL_ALIAS_DOMAINS=mail-a.example.com
LOGIN_EMAIL_DOMAIN_BACKENDS=mail-a.example.com=gmail
LOGIN_EMAIL_GMAIL_USERNAME=your-account@gmail.com
LOGIN_EMAIL_GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
LOGIN_EMAIL_IMAP_HOST=imap.gmail.com
LOGIN_EMAIL_IMAP_PORT=993
LOGIN_EMAIL_IMAP_FOLDER=INBOX
LOGIN_EMAIL_SENDER=noreply@telegram.org
LOGIN_EMAIL_POLL_TIMEOUT_SECONDS=300
LOGIN_EMAIL_POLL_INTERVAL_SECONDS=3
LOGIN_EMAIL_CATCHUP_SECONDS=180
```

重启服务：

```bash
sudo systemctl restart tg-account-bot
sudo journalctl -u tg-account-bot -n 50 --no-pager
```

### 13.3 Bot 内验证

1. 发送 `/security` → 打开"邮箱域名管理"
2. 确认域名显示的后端为 **Gmail**
3. 点击"检查邮件接收"测试连通性
4. 将本人常用账号加入白名单（仅转发提醒，不自动换绑）
5. 对测试账号触发一次真实登录提醒，确认流程正常

---

## 14. 日常维护

### 备份数据库

Bot 内发送 `/backup`，或手动执行（会提示输入数据库密码）：

```bash
sudo -u tg-account-bot pg_dump \
  --format=custom \
  --file=/opt/tg-account-bot/data/backups/manual-$(date +%Y%m%d).dump \
  --dbname=tg_account_bot \
  --host=127.0.0.1 \
  --username=tg_bot
```

如需免密码交互，配置 `.pgpass`：

```bash
sudo -u tg-account-bot bash -c \
  'echo "127.0.0.1:5432:tg_account_bot:tg_bot:数据库密码" \
  > /opt/tg-account-bot/.pgpass && \
  chmod 600 /opt/tg-account-bot/.pgpass'
```

检查备份完整性：

```bash
pg_restore --list /opt/tg-account-bot/data/backups/manual-$(date +%Y%m%d).dump
```

### 升级代码

```bash
# 1. 先备份数据库
sudo -u tg-account-bot pg_dump \
  --format=custom \
  --file=/opt/tg-account-bot/data/backups/pre-upgrade-$(date +%Y%m%d).dump \
  --dbname=tg_account_bot --host=127.0.0.1 --username=tg_bot

# 2. 拉取新代码
sudo -u tg-account-bot git -C /opt/tg-account-bot pull --ff-only

# 3. 更新依赖
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pip install \
  -r /opt/tg-account-bot/requirements.txt

# 4. 执行数据库迁移
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  upgrade head

# 5. 重启服务
sudo systemctl restart tg-account-bot
sudo systemctl status tg-account-bot --no-pager
```

---

## 15. 常见报错速查

| 报错信息 | 原因 | 解决方式 |
|---|---|---|
| `sudo: git: command not found` | git 未安装 | 先执行第 2 节 apt-get install |
| `sudo: python3: command not found` | PATH 问题 | 改用 `/usr/bin/python3` 完整路径 |
| `externally-managed-environment` | 用了系统 pip | 改用 `.venv/bin/python -m pip` |
| `Permission denied: '/opt/tg-account-bot/.venv'` | 目录属主是 root | `sudo chown -R tg-account-bot:tg-account-bot /opt/tg-account-bot` |
| `cannot stat '.env.example'` | 仓库无示例文件 | 按第 7 节直接创建 `.env` |
| `ValidationError` | `.env` 缺字段或格式错误 | 对照第 7 节检查每个必需字段 |
| `could not connect to server` | PostgreSQL 未启动或密码错误 | `sudo systemctl start postgresql`，检查密码 |
| `数据库尚未初始化` | 未跑 alembic | 执行第 9 节 |
| `InvalidFernetKey` | FERNET_KEY 不完整或有空格 | 重新生成并确认完整粘贴 |
| `EMAIL_NOT_ALLOWED` | Telegram 不接受该域名 | 在失败通知的 InlineKeyboard 选其他域名重试 |
| `Bot polling 冲突` | 同一 Token 有多个实例 | `ps aux \| grep app.main` 找到并停止重复进程 |

### 查看当前状态

```bash
sudo systemctl status tg-account-bot --no-pager
sudo journalctl -u tg-account-bot -n 100 --no-pager
sudo -u tg-account-bot git -C /opt/tg-account-bot rev-parse --short HEAD
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini current
sudo systemctl show tg-account-bot -p ActiveState -p SubState -p NRestarts
```

---

---

# Cloudflare Temp Email Webhook（可选）

> **本部分为可选配置**，仅在需要通过 Cloudflare 接收 Telegram 登录验证码邮件时才需要完成。  
> 如果只使用 Gmail 后端，可完全跳过第 16～37 节。  
> **前置要求**：已完成第 1～11 节基础部署，Bot 服务正常运行。

---

## 16. 架构说明

本方案是 **Backend-only** 部署，**不部署** Cloudflare Pages 前端，也不需要浏览器邮箱 UI。

```
互联网邮件
  → Cloudflare Email Routing（域名 Catch-all）
  → Cloudflare Worker（temp-mail-worker）
       ├─ Cloudflare D1（Worker 自身邮件存储）
       └─ HTTPS POST → /webhooks/temp-mail
            → Nginx 反向代理
            → Python aiohttp（127.0.0.1:8080）
            → PostgreSQL.temp_mail_messages
```

各组件职责：

| 组件 | 职责 |
|---|---|
| Cloudflare Email Routing | 真正接收互联网来信 |
| Catch-all | 把域名下任意地址的邮件交给 Worker，无需预先创建邮箱 |
| Cloudflare Temp Email Worker | 解析邮件，存入 D1，触发 Webhook |
| Cloudflare KV | 保存全局 Webhook 配置 |
| Cloudflare D1 | Worker 自身的邮件存储 |
| VPS aiohttp `/webhooks/temp-mail` | 接收 Worker POST，校验 secret，写入 PostgreSQL |
| PostgreSQL `temp_mail_messages` | VPS 侧邮件副本，供登录邮箱保护查询 |

> VPS **不**轮询 Worker；每封新邮件由 Worker 主动 POST 到 VPS。

---

## 17. Cloudflare 部署前提

**Cloudflare 侧需要：**
- Cloudflare 账号
- 已托管到 Cloudflare 的域名（例如 `mail.example.com`）
- Email Routing 可用

**本地（Windows/Mac/Linux 均可）需要：**
- Node.js 18+
- npm
- Wrangler（本文用 `npx` 调用，无需全局安装）
- 能访问 GitHub 的网络

检查本地工具：

```bash
node --version
npm --version
npx wrangler --version
```

---

## 18. VPS：生成 Webhook Secret

在 VPS 上执行，生成至少 32 字节的随机 secret：

```bash
openssl rand -hex 32
```

**复制输出备用**，后续同时填入 VPS `.env` 和 Cloudflare KV。  
不要把真实值写进文档、Git、Issue 或聊天记录。

---

## 19. VPS：更新 .env 启用 Webhook

```bash
sudoedit /opt/tg-account-bot/.env
```

在文件中追加或修改以下内容（替换占位值）：

```env
# ===== Mini App + Webhook 监听（必须为 true，aiohttp 才会监听 8080）=====
MINI_APP_ENABLED=true
MINI_APP_HOST=127.0.0.1
MINI_APP_PORT=8080
MINI_APP_PUBLIC_URL=https://bot.example.com/mini-app

# ===== 登录邮箱保护 =====
LOGIN_EMAIL_PROTECTION_ENABLED=true

# 所有 catch-all 收件域名，逗号分隔
LOGIN_EMAIL_ALIAS_DOMAINS=mail.example.com,mail-alt.example.net

# 每个域名对应的后端：cloudflare 或 gmail
LOGIN_EMAIL_DOMAIN_BACKENDS=mail.example.com=cloudflare,mail-alt.example.net=cloudflare

# Webhook 共享密钥（第 18 节生成的值）
TEMP_MAIL_WEBHOOK_SECRET=在这里填入第18节生成的hex字符串
```

> **注意**：`MINI_APP_ENABLED=true` 是 Webhook 接口 `/webhooks/temp-mail` 监听 `127.0.0.1:8080` 的必要条件，两者共用同一个 aiohttp 进程。

保存后**暂不重启**，等第 20 节迁移完成再重启。

---

## 20. VPS：执行数据库迁移

迁移 `0009_temp_mail_messages` 会创建 `temp_mail_messages` 表：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  upgrade head
```

确认迁移版本：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  current
```

重启服务：

```bash
sudo systemctl restart tg-account-bot
sudo systemctl status tg-account-bot --no-pager
```

确认 aiohttp 监听 8080：

```bash
ss -lntp | grep 8080
```

应看到 `127.0.0.1:8080` 处于监听状态。

---

## 21. VPS：配置 Nginx 反向代理

如果第 12 节已创建 Nginx 配置，编辑它追加 Webhook location；否则新建配置文件：

```bash
sudo tee /etc/nginx/sites-available/tg-account-bot > /dev/null <<'EOF'
server {
    listen 80;
    server_name bot.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name bot.example.com;

    ssl_certificate     /etc/letsencrypt/live/bot.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.example.com/privkey.pem;

    # Mini App
    location /mini-app {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    # Cloudflare Temp Email Webhook
    location /webhooks/temp-mail {
        proxy_pass http://127.0.0.1:8080/webhooks/temp-mail;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        client_max_body_size 6m;
    }
}
EOF
```

启用配置：

```bash
sudo ln -sf /etc/nginx/sites-available/tg-account-bot \
  /etc/nginx/sites-enabled/tg-account-bot

sudo nginx -t
sudo systemctl reload nginx
```

如果还没有证书，先申请：

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bot.example.com
sudo systemctl reload nginx
```

验证链路（secret 填错，应返回 401）：

```bash
curl -i -X POST https://bot.example.com/webhooks/temp-mail \
  -H 'Content-Type: application/json' \
  -H 'X-Temp-Mail-Secret: wrong_secret' \
  -d '{"id":"test","from":"a@b.com","to":"x@mail.example.com","subject":"t","raw":"","parsedText":"t","parsedHtml":""}'
```

返回 HTTP 401 说明 Nginx → aiohttp 链路通，secret 校验正常。

---

## 22. Cloudflare：创建 D1 数据库

登录 Cloudflare Dashboard，进入：

```
Storage & Databases → D1 SQL Database → Create Database
```

数据库名称填写：

```
temp-mail
```

创建完成后，进入 `temp-mail → Console`，在浏览器打开上游 Release 页面获取 `schema.sql`：

```
https://github.com/dreamhunter2333/cloudflare_temp_email/releases
```

找到 `schema.sql` 或 `db/schema.sql`，把全部 SQL 粘贴到 D1 Console 执行。

> **注意**：`schema.sql` 只用于首次初始化。升级时不要重新执行，应按 Release/CHANGELOG 执行对应的 migration SQL。

---

## 23. Cloudflare：创建空 Worker

进入：

```
Compute (Workers) → Workers & Pages → Create → Worker
```

名称填写：

```
temp-mail-worker
```

先完成空 Worker 创建，后续用 Wrangler 上传正式代码。

---

## 24. 本地：安装 Wrangler 并登录

```bash
npx wrangler login
```

浏览器会自动打开 Cloudflare 授权页，完成授权后回到终端。

确认登录成功：

```bash
npx wrangler whoami
```

---

## 25. 本地：下载并部署 worker.js

下载最新 Release 的 `worker.js`：

```bash
# Linux/Mac
curl -L https://github.com/dreamhunter2333/cloudflare_temp_email/releases/latest/download/worker.js \
  -o worker.js

# Windows CMD
curl.exe -L https://github.com/dreamhunter2333/cloudflare_temp_email/releases/latest/download/worker.js -o worker.js
```

部署到 Cloudflare（`YYYY-MM-DD` 替换为当天日期）：

```bash
npx wrangler deploy worker.js \
  --name temp-mail-worker \
  --compatibility-date 2025-01-01 \
  --compatibility-flag nodejs_compat
```

成功时应看到：

```
Uploaded temp-mail-worker
Deployed temp-mail-worker triggers
https://temp-mail-worker.<YOUR_ACCOUNT>.workers.dev
```

> **关于 `nodejs_compat`**：必须使用基础 `nodejs_compat`，不能用 `nodejs_compat_v2` 等替代。缺少此 Flag 会报 `No such module "path"`。

---

## 26. Cloudflare：配置 Worker Variables 和 Secret

进入：

```
temp-mail-worker → Settings → Variables and Secrets
```

### DOMAINS（JSON 类型）

```json
[
  "mail.example.com",
  "mail-alt.example.net"
]
```

### JWT_SECRET（Secret 类型）

生成随机值：

```bash
# Linux/Mac
openssl rand -hex 32

# Windows CMD
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

把输出填入 `JWT_SECRET`，类型选 **Secret**。

### 其他变量（JSON 类型）

| 变量名 | 类型 | 值 |
|---|---|---|
| `ENABLE_USER_CREATE_EMAIL` | JSON | `true` |
| `ENABLE_WEBHOOK` | JSON | `true` |

> `ENABLE_WEBHOOK=true` 是 Webhook 功能的必要条件，同时还需要 KV Binding（第 30 节）。  
> Backend-only 部署**不需要**配置 `FRONTEND_URL`。

---

## 27. Cloudflare：绑定 D1

进入：

```
temp-mail-worker → Settings → Bindings → Add Binding → D1 Database
```

填写：

```
Binding name: DB
Database:     temp-mail
```

> **Binding 名称必须是大写 `DB`**，不能写 `db`、`DATABASE` 或 `D1`，否则 Worker 无法找到数据库。

---

## 28. Cloudflare：验证 Worker 基础 API

浏览器访问：

```
https://temp-mail-worker.<YOUR_ACCOUNT>.workers.dev/open_api/settings
```

应返回：

```json
{
  "enableUserCreateEmail": true,
  "enableWebhook": true,
  "domains": [
    "mail.example.com",
    "mail-alt.example.net"
  ]
}
```

如果报错，按以下顺序排查：

1. D1 Binding 名称是否为大写 `DB`
2. `ENABLE_WEBHOOK` 是否为 JSON `true`（不是字符串 `"true"`）
3. `DOMAINS` 是否为合法 JSON 数组
4. `nodejs_compat` Flag 是否已启用

---

## 29. Cloudflare：配置 Email Routing

对每个选择 Cloudflare 后端的域名分别操作。

### 29.1 主域名配置

进入：

```
Cloudflare → example.com → Email → Email Routing
```

确认 Email Routing 已启用，邮件 DNS records 正常，然后进入 **Routing rules → Catch-all address**，设置：

```
Action: Send to a Worker
Worker: temp-mail-worker
Status: Active
```

### 29.2 子域名特别配置

如果收件域是子域（如 `mail.example.com`），子域不会自动继承父域配置，必须单独操作：

进入：

```
Email Routing → Settings → Subdomains
```

添加 `mail.example.com`，确认状态为 **Enabled**，然后针对该子域配置 Catch-all → Send to Worker → `temp-mail-worker` → Active。

---

## 30. Cloudflare：创建并绑定 KV

### 30.1 创建 KV Namespace

进入：

```
Storage & Databases → KV → Create Namespace
```

名称填写：

```
temp-mail-kv
```

### 30.2 绑定到 Worker

进入：

```
temp-mail-worker → Settings → Bindings → Add Binding → KV Namespace
```

填写：

```
Binding name: KV
Namespace:    temp-mail-kv
```

> **Binding 名称必须是大写 `KV`**。Webhook 功能同时依赖 `ENABLE_WEBHOOK=true` 和 KV Binding，两者缺一不可。

---

## 31. Cloudflare：配置全局 Webhook

进入：

```
Storage & Databases → KV → temp-mail-kv → KV Pairs
```

点击 **Add entry**，创建以下 KV：

**Key：**

```
temp-mail-webhook-admin-mail-settings
```

**Value（JSON）**，将 secret 和 URL 替换为真实值：

```json
{
  "enabled": true,
  "url": "https://bot.example.com/webhooks/temp-mail",
  "method": "POST",
  "headers": "{\"Content-Type\":\"application/json\",\"X-Temp-Mail-Secret\":\"在这里填入第18节生成的真实secret\"}",
  "body": "{\"id\":\"${id}\",\"url\":\"${url}\",\"from\":\"${from}\",\"to\":\"${to}\",\"subject\":\"${subject}\",\"raw\":\"${raw}\",\"parsedText\":\"${parsedText}\",\"parsedHtml\":\"${parsedHtml}\",\"aiExtractType\":\"${aiExtractType}\",\"aiExtractResult\":\"${aiExtractResult}\",\"aiExtractResultText\":\"${aiExtractResultText}\"}"
}
```

> **注意**：`headers` 和 `body` 字段的值本身是 JSON 字符串，内部双引号必须用 `\"` 转义，格式必须严格正确，否则 Worker 无法解析。  
> 这是 Admin 全局 Webhook，处理所有 Cloudflare 后端域名的来信，无需为每个域名单独创建。

---

## 32. 测试：curl 模拟 Webhook

在 VPS 上执行，将 secret 和 URL 替换为真实值：

```bash
curl -i \
  -X POST https://bot.example.com/webhooks/temp-mail \
  -H 'Content-Type: application/json' \
  -H 'X-Temp-Mail-Secret: 在这里填入真实secret' \
  -d '{
    "id": "test-curl-001",
    "from": "sender@gmail.com",
    "to": "hooktest@mail.example.com",
    "subject": "Webhook Test",
    "raw": "",
    "parsedText": "Hello from curl test",
    "parsedHtml": "<p>Hello from curl test</p>"
  }'
```

期望响应：**HTTP 200**

然后在 PostgreSQL 确认数据写入：

```bash
sudo -u postgres psql -d tg_account_bot -c "
SELECT id, \"from\", \"to\", domain, subject, received_at
FROM temp_mail_messages
WHERE \"to\" = 'hooktest@mail.example.com'
ORDER BY received_at DESC
LIMIT 5;"
```

重复发送相同 `id + to` 仍返回 200，但不会重复插入（复合主键去重）。

---

## 33. 测试：真实邮件端到端

从外部邮箱（Gmail、Outlook 等）发送：

```
收件人：cftest@mail.example.com
主题：CF-WEBHOOK-E2E-TEST
正文：端到端测试
```

等待 10～30 秒后，在 VPS 查询：

```bash
sudo -u postgres psql -d tg_account_bot -c "
SELECT id, \"from\", \"to\", domain, subject, received_at
FROM temp_mail_messages
WHERE \"to\" = 'cftest@mail.example.com'
ORDER BY received_at DESC
LIMIT 5;"
```

成功标准：PostgreSQL 出现对应记录。

如果查不到记录，按以下顺序排查：

1. 查看 Worker 日志：Cloudflare Dashboard → `temp-mail-worker` → Logs
2. 检查 Email Routing 是否已启用、Catch-all 是否 Active
3. 确认 KV Pair 存在且 `enabled: true`
4. 检查 VPS 服务日志：`sudo journalctl -u tg-account-bot -n 100 --no-pager`
5. 检查 Nginx 日志：`sudo tail -n 50 /var/log/nginx/access.log`

---

## 34. Telegram Bot 内验证

1. 向 Bot 发送 `/security`
2. 进入 **邮箱域名管理**
3. 点击对应域名右侧的按钮，确认显示为 **CF TempMail**
4. 点击 **检查邮件接收**，确认返回成功
5. 将本人常用账号加入白名单（仅转发提醒，不自动换绑）
6. 对测试账号触发一次真实 Telegram 登录提醒，确认验证码被正确接收和处理

---

## 35. Cloudflare 部署检查清单

**Cloudflare 侧：**

- [ ] 域名 DNS 已托管 Cloudflare
- [ ] D1 `temp-mail` 已创建，`schema.sql` 已执行
- [ ] Worker `temp-mail-worker` 已部署，`nodejs_compat` 已启用
- [ ] Worker `DOMAINS` 包含所有 CF TempMail 域名（JSON 数组）
- [ ] `JWT_SECRET` 已作为 Secret 配置
- [ ] `ENABLE_USER_CREATE_EMAIL=true`（JSON 类型）
- [ ] `ENABLE_WEBHOOK=true`（JSON 类型）
- [ ] D1 Binding 名称为大写 `DB`
- [ ] `/open_api/settings` 返回正常 JSON
- [ ] 每个域名的 Email Routing 已启用，邮件 DNS records 正常
- [ ] 每个域名的 Catch-all 指向 `temp-mail-worker`，状态 Active
- [ ] 使用收件子域时，子域 Email Routing 已在 Subdomains 单独启用
- [ ] KV `temp-mail-kv` 已创建
- [ ] KV Binding 名称为大写 `KV`
- [ ] KV Pair `temp-mail-webhook-admin-mail-settings` 已创建，`enabled: true`
- [ ] KV Pair 中的 `url` 与 VPS 实际 Webhook 地址一致
- [ ] KV Pair 中的 secret 与 VPS `.env` 的 `TEMP_MAIL_WEBHOOK_SECRET` 完全一致

**VPS 侧：**

- [ ] `.env` 已配置 `MINI_APP_ENABLED=true`
- [ ] `.env` 已配置 `TEMP_MAIL_WEBHOOK_SECRET`
- [ ] `.env` 已配置 `LOGIN_EMAIL_ALIAS_DOMAINS` 和 `LOGIN_EMAIL_DOMAIN_BACKENDS`
- [ ] `alembic upgrade head` 已执行，`temp_mail_messages` 表存在
- [ ] 服务已重启，`ss -lntp | grep 8080` 确认 aiohttp 监听中
- [ ] Nginx 已配置 `/webhooks/temp-mail` 代理，`nginx -t` 通过
- [ ] `curl -i POST /webhooks/temp-mail` 返回 HTTP 200
- [ ] 真实邮件可在 `temp_mail_messages` 中查到

**Telegram Bot 内：**

- [ ] 每个域名后端显示为 `CF TempMail`
- [ ] "检查邮件接收"验证通过

---

## 36. Cloudflare 常见故障排查

| 现象 | 原因 | 处理方式 |
|---|---|---|
| `No such module "path"` | `nodejs_compat` 未启用 | 重新部署时加 `--compatibility-flag nodejs_compat` |
| `/open_api/settings` 报错 | D1 Binding 名称错误 | 必须是大写 `DB` |
| Webhook 完全不触发 | KV 未配置或 `ENABLE_WEBHOOK` 不对 | 确认 `ENABLE_WEBHOOK=true`（JSON）、KV Binding 为大写 `KV`、KV Pair 存在且 `enabled: true` |
| Webhook 返回 401 | Secret 不匹配 | 核对 `X-Temp-Mail-Secret` 与 VPS `TEMP_MAIL_WEBHOOK_SECRET` 完全一致 |
| Webhook 返回 403 | Nginx/Cloudflare WAF 拦截 | 检查 Nginx 配置，确认未设置额外 IP 白名单限制 |
| Webhook 返回 413 | JSON 超过 5 MiB | 检查邮件是否含大附件 |
| Webhook 返回 502/504 | aiohttp 未启动 | 检查 `ss -lntp \| grep 8080`，确认 `MINI_APP_ENABLED=true` 且服务已重启 |
| 域名收不到信 | Email Routing 未配置 | 检查 Enabled、DNS records、Catch-all Active |
| 子域不收信 | 子域未单独启用 | `Email Routing → Settings → Subdomains` 添加并启用 |
| `url` 字段为空 | 未部署 Pages | Backend-only 架构正常现象，不影响功能 |
| PostgreSQL 无记录但 200 | 域名不在允许列表 | 检查 `LOGIN_EMAIL_ALIAS_DOMAINS` 是否包含该域名 |
| Telegram 换绑失败 | Telegram 域名策略或限流 | 查看 Bot 通知，`EMAIL_NOT_ALLOWED` 是 Telegram 拒绝，与 Webhook 无关 |

**VPS 排障命令：**

```bash
sudo systemctl status tg-account-bot --no-pager
sudo journalctl -u tg-account-bot -n 200 --no-pager
sudo tail -n 100 /var/log/nginx/access.log
ss -lntp | grep 8080
sudo -u postgres psql -d tg_account_bot -c \
  "SELECT id, \"to\", domain, subject, received_at FROM temp_mail_messages ORDER BY received_at DESC LIMIT 10;"
```

---

## 37. 升级 Cloudflare Temp Email Worker

升级前：

1. 记录当前 Worker 版本和所有配置
2. 查看上游 [Release](https://github.com/dreamhunter2333/cloudflare_temp_email/releases) 和 [CHANGELOG](https://github.com/dreamhunter2333/cloudflare_temp_email/blob/main/CHANGELOG.md)
3. 确认是否有 Breaking Changes 或需要执行的 D1 migration SQL
4. 如有 migration，先在 D1 Console 执行，再部署新 Worker

下载新版并重新部署：

```bash
# Linux/Mac
curl -L https://github.com/dreamhunter2333/cloudflare_temp_email/releases/latest/download/worker.js \
  -o worker.js

npx wrangler deploy worker.js \
  --name temp-mail-worker \
  --compatibility-date 2025-01-01 \
  --compatibility-flag nodejs_compat
```

升级时**不要**删除或重建 D1、KV、Email Routing、Catch-all、Variables 和 Secrets。

升级后验证：

```bash
curl https://temp-mail-worker.<YOUR_ACCOUNT>.workers.dev/open_api/settings
```

再发送一封真实测试邮件，确认完整链路正常。
