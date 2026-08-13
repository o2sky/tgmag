# 部署指南（Debian 13 Trixie · root 用户）

<!-- markdownlint-disable MD013 -->

本文档给出一套可复制的 Debian 13 生产部署流程：独立系统用户、Python venv、PostgreSQL 17、systemd，以及可选的 Nginx HTTPS、Telegram Mini App、Cloudflare Temp Email 和 Gmail 登录邮箱保护。每个收件域名可以独立选择 Cloudflare 或 Gmail 后端。

示例部署目录为 `/opt/tg-account-bot`，服务用户为 `tg-account-bot`。命令中的域名、用户 ID、密码和 Token 都是占位值，必须替换。

> **说明**：本指南在 root 用户下执行，所有命令均不含 `sudo` 前缀。

---

## 1. 部署前需要准备的值

必需项：

| 配置 | 获取方式 |
| --- | --- |
| `BOT_TOKEN` | 在 Telegram 中通过 `@BotFather` 创建 Bot 后取得 |
| `TG_API_ID` / `TG_API_HASH` | 登录 `https://my.telegram.org`，在 API development tools 创建应用 |
| `ADMIN_IDS` | 允许管理此 Bot 的 Telegram 数值用户 ID；多个 ID 用英文逗号分隔 |
| `DATABASE_URL` | 本文第 3 节创建的 PostgreSQL 用户、密码和数据库 |
| `FERNET_KEY` | 按本文第 6 节生成；生成后不可随意更换 |

可选项：

| 功能 | 还需要准备 |
| --- | --- |
| Mini App | 指向服务器的域名、开放的 80/443 端口、有效 HTTPS 证书 |
| 登录邮箱保护 | 一个或多个 catch-all 域名；按域名准备 Cloudflare Temp Email + Webhook secret，或 Gmail + 应用专用密码 |

---

## 2. 安装系统依赖

```bash
apt update && apt upgrade -y
apt install -y \
  git python3 python3-venv python3-pip build-essential libpq-dev \
  curl ca-certificates
```

---

## 3. 安装 PostgreSQL 17

Debian 13 默认仓库已包含 PostgreSQL 17，直接安装：

```bash
apt install -y postgresql postgresql-client postgresql-contrib
```

确认服务已启动：

```bash
systemctl status postgresql --no-pager
```

看到 `active (running)` 即为正常。

### 3.1 创建数据库用户和数据库

切换到 postgres 系统用户：

```bash
su - postgres
```

创建用户（交互式输入密码，不会写入 Shell 历史）并创建数据库，**两条命令都要执行**：

```bash
createuser --pwprompt tg_bot
createdb --owner=tg_bot tg_account_bot
```

确认数据库存在（`tg_account_bot` 应出现在列表中）：

```bash
psql -c '\l'
```

退出 postgres 用户，回到 root：

```bash
exit
```

对应连接串格式（填入第 5 节的 `.env`）：

```
DATABASE_URL=postgresql+asyncpg://tg_bot:数据库密码@127.0.0.1:5432/tg_account_bot
```

> 密码只使用字母和数字可避免 URL 编码问题。

---

## 4. 安装代码

创建服务用户（已存在则跳过）：

```bash
useradd --system --user-group \
  --home-dir /opt/tg-account-bot \
  --shell /usr/sbin/nologin \
  tg-account-bot
```

克隆项目并设置权限：

```bash
git clone https://github.com/o2sky/tgmag.git /opt/tg-account-bot
chown -R tg-account-bot:tg-account-bot /opt/tg-account-bot
```

创建 venv 并安装依赖：

```bash
su -s /bin/bash tg-account-bot -c "python3 -m venv /opt/tg-account-bot/.venv"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pip install --upgrade pip wheel"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pip install -r /opt/tg-account-bot/requirements.txt"
```

创建数据目录：

```bash
install -d -o tg-account-bot -g tg-account-bot -m 700 \
  /opt/tg-account-bot/data/sessions \
  /opt/tg-account-bot/data/backups
```

---

## 5. 创建 `.env`

复制模板并编辑：

```bash
install -o tg-account-bot -g tg-account-bot -m 600 \
  /opt/tg-account-bot/.env.example \
  /opt/tg-account-bot/.env
nano /opt/tg-account-bot/.env
```

### 5.1 不使用登录邮箱保护（最简配置）

暂时不用邮箱保护时，填写以下内容即可启动：

```env
BOT_TOKEN=1234567890:replace_with_real_bot_token
TG_API_ID=123456
TG_API_HASH=replace_with_real_api_hash
ADMIN_IDS=123456789
DATABASE_URL=postgresql+asyncpg://tg_bot:数据库密码@127.0.0.1:5432/tg_account_bot
FERNET_KEY=（第 6 节生成后填入）

SESSION_DIR=./data/sessions
BACKUP_DIR=./data/backups
LOG_LEVEL=INFO

MINI_APP_ENABLED=false
LOGIN_EMAIL_PROTECTION_ENABLED=false
```

### 5.2 使用登录邮箱保护

`LOGIN_EMAIL_DOMAIN_BACKENDS` 必须与 `LOGIN_EMAIL_ALIAS_DOMAINS` 中的域名完全对应，格式为 `域名=后端`，后端只能是 `cloudflare` 或 `gmail`：

**单域名 Cloudflare 示例：**

```env
LOGIN_EMAIL_PROTECTION_ENABLED=true
LOGIN_EMAIL_ALIAS_DOMAINS=mail.example.com
LOGIN_EMAIL_DOMAIN_BACKENDS=mail.example.com=cloudflare
TEMP_MAIL_WEBHOOK_SECRET=（openssl rand -hex 32 生成）
```

**单域名 Gmail 示例：**

```env
LOGIN_EMAIL_PROTECTION_ENABLED=true
LOGIN_EMAIL_ALIAS_DOMAINS=mail.example.com
LOGIN_EMAIL_DOMAIN_BACKENDS=mail.example.com=gmail
LOGIN_EMAIL_GMAIL_USERNAME=your-account@gmail.com
LOGIN_EMAIL_GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

**多域名混合示例：**

```env
LOGIN_EMAIL_PROTECTION_ENABLED=true
LOGIN_EMAIL_ALIAS_DOMAINS=cf.example.com,gm.example.com
LOGIN_EMAIL_DOMAIN_BACKENDS=cf.example.com=cloudflare,gm.example.com=gmail
TEMP_MAIL_WEBHOOK_SECRET=（openssl rand -hex 32 生成）
LOGIN_EMAIL_GMAIL_USERNAME=your-account@gmail.com
LOGIN_EMAIL_GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

> **常见错误**：`LOGIN_EMAIL_DOMAIN_BACKENDS` 的写法不是域名列表，而是 `域名=后端` 的映射，且每个域名必须出现在 `LOGIN_EMAIL_ALIAS_DOMAINS` 中。

其余可选配置：

```env
LOGIN_EMAIL_IMAP_HOST=imap.gmail.com
LOGIN_EMAIL_IMAP_PORT=993
LOGIN_EMAIL_IMAP_FOLDER=INBOX
LOGIN_EMAIL_SENDER=noreply@telegram.org
LOGIN_EMAIL_POLL_TIMEOUT_SECONDS=300
LOGIN_EMAIL_POLL_INTERVAL_SECONDS=3
LOGIN_EMAIL_CATCHUP_SECONDS=180
```

### 5.3 环境变量完整说明

| 变量 | 必需 | 默认值/作用 |
| --- | --- | --- |
| `BOT_TOKEN` | 是 | Telegram Bot Token |
| `TG_API_ID` | 是 | Telegram API ID，整数 |
| `TG_API_HASH` | 是 | Telegram API Hash |
| `ADMIN_IDS` | 是 | 管理员 Telegram 用户 ID 列表，逗号分隔 |
| `DATABASE_URL` | 是 | SQLAlchemy asyncpg PostgreSQL 连接串 |
| `FERNET_KEY` | 是 | 应用层敏感字段加密密钥 |
| `SESSION_DIR` | 否 | `./data/sessions` |
| `BACKUP_DIR` | 否 | `./data/backups` |
| `DEFAULT_RATE_MAX_ACTIONS` | 否 | `8`，默认窗口内最大动作数 |
| `DEFAULT_RATE_PER_SECONDS` | 否 | `60`，默认窗口秒数 |
| `DEFAULT_JITTER_MIN` / `MAX` | 否 | `2` / `6`，批量动作随机等待秒数 |
| `SERVICE_MONITOR_INTERVAL_SECONDS` | 否 | `300`，服务监控周期；最小 30 秒 |
| `LOG_LEVEL` | 否 | `INFO` |
| `MINI_APP_ENABLED` | 否 | `false` |
| `MINI_APP_HOST` / `PORT` | 否 | `127.0.0.1` / `8080` |
| `MINI_APP_PUBLIC_URL` | 启用 Mini App 时 | 完整 HTTPS 地址，以 `/mini-app` 结尾 |
| `MINI_APP_AUTH_MAX_AGE_SECONDS` | 否 | `3600` |
| `LOGIN_EMAIL_PROTECTION_ENABLED` | 否 | `true`；不使用时显式设为 `false` |
| `LOGIN_EMAIL_ALIAS_DOMAINS` | 启用保护时 | catch-all 域名列表，逗号分隔 |
| `LOGIN_EMAIL_DOMAIN_BACKENDS` | 启用保护时 | `域名=cloudflare` 或 `域名=gmail`，逗号分隔多个 |
| `TEMP_MAIL_WEBHOOK_SECRET` | 使用 Cloudflare 时 | 至少 32 位随机字符串 |
| `LOGIN_EMAIL_GMAIL_USERNAME` | 使用 Gmail 时 | 接收 catch-all 转发的 Gmail 地址 |
| `LOGIN_EMAIL_GMAIL_APP_PASSWORD` | 使用 Gmail 时 | Gmail 应用专用密码 |
| `LOGIN_EMAIL_IMAP_HOST` / `PORT` | 否 | `imap.gmail.com` / `993` |
| `LOGIN_EMAIL_IMAP_FOLDER` | 否 | `INBOX` |
| `LOGIN_EMAIL_SENDER` | 否 | `noreply@telegram.org` |
| `LOGIN_EMAIL_POLL_TIMEOUT_SECONDS` | 否 | `300`（30–7200） |
| `LOGIN_EMAIL_POLL_INTERVAL_SECONDS` | 否 | `3`（1–30） |
| `LOGIN_EMAIL_CATCHUP_SECONDS` | 否 | `180` |

---

## 6. 生成 Fernet 密钥

```bash
/opt/tg-account-bot/.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

把输出完整填入 `.env` 的 `FERNET_KEY`。

> 不要提交到 Git。随意更换密钥会导致已有数据无法解密。迁移服务器时必须一并迁移。

---

## 7. 初始化数据库

应用不会自动建表，首次部署和每次升级后都必须执行：

```bash
su -s /bin/bash tg-account-bot -c "cd /opt/tg-account-bot && .venv/bin/alembic upgrade head"
```

前台验证启动（看到 Bot 开始 polling 且无报错后按 `Ctrl+C`）：

```bash
su -s /bin/bash tg-account-bot -c "cd /opt/tg-account-bot && .venv/bin/python -m app.main"
```

---

## 8. 配置 systemd

```bash
install -m 644 /opt/tg-account-bot/ops/systemd/tg-account-bot.service \
  /etc/systemd/system/tg-account-bot.service
systemctl daemon-reload
systemctl enable --now tg-account-bot
```

检查服务状态：

```bash
systemctl status tg-account-bot --no-pager
journalctl -u tg-account-bot -n 100 --no-pager
```

实时查看日志：

```bash
journalctl -u tg-account-bot -f
```

---

## 9. 配置 Nginx 与 HTTPS（Mini App 可选）

若需要 Mini App，在 `.env` 中追加：

```env
MINI_APP_ENABLED=true
MINI_APP_HOST=127.0.0.1
MINI_APP_PORT=8080
MINI_APP_PUBLIC_URL=https://bot.example.com/mini-app
```

安装 Nginx 与 Certbot：

```bash
apt install -y nginx certbot python3-certbot-nginx
```

创建站点配置（替换 `bot.example.com` 为实际域名）：

```bash
cat > /etc/nginx/sites-available/tg-account-bot << 'EOF'
server {
    listen 80;
    server_name bot.example.com;

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

启用站点并申请证书：

```bash
ln -s /etc/nginx/sites-available/tg-account-bot /etc/nginx/sites-enabled/tg-account-bot
nginx -t
systemctl reload nginx
certbot --nginx -d bot.example.com
systemctl restart tg-account-bot
```

验证：

```bash
curl -I https://bot.example.com/mini-app
```

### 9.1 在 BotFather 中启用资料页按钮

1. 向 `@BotFather` 发送 `/mybots`，选择对应机器人。
2. 进入 `Bot Settings` → `Configure Mini App` → `Enable Mini App`。
3. 填写 `MINI_APP_PUBLIC_URL`。
4. 资料页出现"打开应用"按钮即完成。

---

## 10. 配置登录邮箱保护（可选）

### 10.1 后端选择

| 后端 | Cloudflare Email Routing Catch-all 设置 | 程序读取方式 |
| --- | --- | --- |
| `cloudflare` | Send to Worker → Cloudflare Temp Email | Worker POST Webhook → PostgreSQL |
| `gmail` | Send to email → 已验证 Gmail 地址 | Gmail IMAP |

Cloudflare 后端生成 Webhook secret：

```bash
openssl rand -hex 32
```

填入 `TEMP_MAIL_WEBHOOK_SECRET`，并在 Cloudflare Worker 的全局 Webhook 中设置请求头 `X-Temp-Mail-Secret`。

Gmail 后端需为该账号启用两步验证并创建应用专用密码。

### 10.2 Bot 内验证

1. 发送 `/security`。
2. 打开"邮箱域名管理"，确认域名和后端与 Email Routing 实际设置一致。
3. 使用"检查邮件接收"验证。
4. 把会主动登录的账号加入白名单。
5. 对测试账号触发真实登录提醒，观察结果通知。

---

## 11. 备份与恢复

Bot 中发送 `/backup` 可手动触发备份。也可以命令行执行：

```bash
su -s /bin/bash tg-account-bot -c "pg_dump \
  --format=custom \
  --file=/opt/tg-account-bot/data/backups/manual.dump \
  --dbname=tg_account_bot \
  --host=127.0.0.1 \
  --username=tg_bot"
```

检查备份完整性：

```bash
pg_restore --list /opt/tg-account-bot/data/backups/manual.dump
```

恢复时需原 `FERNET_KEY`，恢复前先停止服务。

---

## 12. 升级

```bash
cd /opt/tg-account-bot
su -s /bin/bash tg-account-bot -c "git pull --ff-only"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pip install -r /opt/tg-account-bot/requirements.txt"
su -s /bin/bash tg-account-bot -c "cd /opt/tg-account-bot && .venv/bin/alembic upgrade head"
systemctl restart tg-account-bot
systemctl status tg-account-bot --no-pager
```

---

## 13. 常见故障

### 服务启动后立即退出

```bash
journalctl -u tg-account-bot -n 200 --no-pager
```

**`ValidationError: LOGIN_EMAIL_DOMAIN_BACKENDS entries must use domain=backend`**

格式必须是 `域名=后端`，不是域名列表：

```env
# 错误
LOGIN_EMAIL_DOMAIN_BACKENDS=mail.example.com

# 正确
LOGIN_EMAIL_DOMAIN_BACKENDS=mail.example.com=cloudflare
```

**`LOGIN_EMAIL_DOMAIN_BACKENDS contains a domain not listed in LOGIN_EMAIL_ALIAS_DOMAINS`**

两个变量的域名必须完全一致：

```env
# 错误（域名不匹配）
LOGIN_EMAIL_ALIAS_DOMAINS=mail.example.com
LOGIN_EMAIL_DOMAIN_BACKENDS=other.example.com=cloudflare

# 正确
LOGIN_EMAIL_ALIAS_DOMAINS=mail.example.com
LOGIN_EMAIL_DOMAIN_BACKENDS=mail.example.com=cloudflare
```

**暂时不用邮箱保护**，直接关掉即可：

```env
LOGIN_EMAIL_PROTECTION_ENABLED=false
```

**其他 `ValidationError`**：`.env` 缺少必需值或格式错误，对照第 5 节检查。

**`数据库尚未初始化`**：执行第 7 节的 alembic 命令。

**`Permission denied`**：

```bash
ls -la /opt/tg-account-bot/
stat /opt/tg-account-bot/.env
```

### PostgreSQL 连接失败

```bash
systemctl status postgresql --no-pager
su - postgres -c "psql -c '\l'"
su - postgres -c "psql -c '\du'"
psql postgresql://tg_bot:密码@127.0.0.1:5432/tg_account_bot -c 'SELECT 1'
```

连接串必须使用 `127.0.0.1` 而非 `localhost`，Debian 默认对 IPv4 使用密码认证。

### Mini App 无法打开

- `MINI_APP_PUBLIC_URL` 必须是完整 HTTPS 地址，以 `/mini-app` 结尾。
- 确认 Nginx 配置正确：`nginx -t`。
- 确认 8080 只在本机监听：`ss -lntp | grep 8080`。
- 直接用浏览器访问返回 401 是正常的，缺少 Telegram `initData`。

### 检查版本与迁移状态

```bash
su -s /bin/bash tg-account-bot -c "cd /opt/tg-account-bot && git rev-parse --short HEAD"
su -s /bin/bash tg-account-bot -c "cd /opt/tg-account-bot && .venv/bin/alembic current"
systemctl show tg-account-bot -p ActiveState -p SubState -p NRestarts
```
