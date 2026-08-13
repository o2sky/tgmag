# 部署指南（Debian 13 Trixie · root 用户）

<!-- markdownlint-disable MD013 -->

本文档给出一套可复制的 Debian 13 生产部署流程：独立系统用户、Python venv、PostgreSQL 17、systemd，以及可选的 Nginx HTTPS、Telegram Mini App、Cloudflare Temp Email 和 Gmail 登录邮箱保护。每个收件域名可以独立选择 Cloudflare 或 Gmail 后端。

示例部署目录为 `/opt/tg-account-bot`，服务用户为 `tg-account-bot`。命令中的域名、用户 ID、密码和 Token 都是占位值，必须替换。

> **说明**：本指南在 root 用户下执行，所有命令均去掉了 `sudo` 前缀。

---

## 1. 部署前需要准备的值

必需项：

| 配置 | 获取方式 |
| --- | --- |
| `BOT_TOKEN` | 在 Telegram 中通过 `@BotFather` 创建 Bot 后取得 |
| `TG_API_ID` / `TG_API_HASH` | 登录 `https://my.telegram.org`，在 API development tools 创建应用 |
| `ADMIN_IDS` | 允许管理此 Bot 的 Telegram 数值用户 ID；多个 ID 用英文逗号分隔 |
| `DATABASE_URL` | 本文第 3 节创建的 PostgreSQL 用户、密码和数据库 |
| `FERNET_KEY` | 按本文第 5 节生成；生成后不可随意更换 |

可选项：

| 功能 | 还需要准备 |
| --- | --- |
| Mini App | 指向服务器的域名、开放的 80/443 端口、有效 HTTPS 证书 |
| 登录邮箱保护 | 一个或多个 catch-all 域名；按域名准备 Cloudflare Temp Email + Webhook secret，或 Gmail + 应用专用密码 |

---

## 2. 安装系统依赖

更新系统并安装所需软件包：

```bash
apt update && apt upgrade -y
apt install -y \
  git python3 python3-venv python3-pip build-essential libpq-dev \
  curl ca-certificates
```

---

## 3. 安装 PostgreSQL 17

Debian 13 默认仓库已包含 PostgreSQL 17，直接安装即可：

```bash
apt install -y postgresql postgresql-client postgresql-contrib
```

安装完成后确认服务已启动：

```bash
systemctl status postgresql --no-pager
```

看到 `active (running)` 即为正常。确认版本：

```bash
psql --version
```

### 3.1 创建数据库用户和数据库

切换到 `postgres` 系统用户，进行数据库操作：

```bash
su - postgres
```

在 postgres shell 中创建用户（会交互式要求输入两次密码，避免密码写入 Shell 历史）：

```bash
createuser --pwprompt tg_bot
createdb --owner=tg_bot tg_account_bot
```

确认数据库存在：

```bash
psql -c '\l tg_account_bot'
```

退出 postgres 用户：

```bash
exit
```

对应连接串格式：

```env
DATABASE_URL=postgresql+asyncpg://tg_bot:数据库密码@127.0.0.1:5432/tg_account_bot
```

如果密码包含 `@`、`:`、`/`、`#`、`%` 等字符，必须先进行 URL 百分号编码。为减少配置错误，建议使用足够长的字母数字密码。

---

## 4. 安装代码

创建不允许交互登录的服务用户：

```bash
useradd --system --user-group \
  --home-dir /opt/tg-account-bot \
  --shell /usr/sbin/nologin \
  tg-account-bot
```

如果该用户已存在，可跳过 `useradd`。克隆项目并设置权限：

```bash
git clone https://github.com/o2sky/tgmag.git /opt/tg-account-bot
chown -R tg-account-bot:tg-account-bot /opt/tg-account-bot
cd /opt/tg-account-bot
```

创建 venv 并安装依赖：

```bash
su -s /bin/bash tg-account-bot -c "python3 -m venv /opt/tg-account-bot/.venv"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pip install --upgrade pip wheel"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pip install -r /opt/tg-account-bot/requirements.txt"
install -d -o tg-account-bot -g tg-account-bot -m 700 \
  /opt/tg-account-bot/data/sessions \
  /opt/tg-account-bot/data/backups
```

---

## 5. 创建 `.env`

```bash
cd /opt/tg-account-bot
install -o tg-account-bot -g tg-account-bot -m 600 .env.example .env
nano .env
```

最小可启动配置如下：

```env
BOT_TOKEN=1234567890:replace_with_real_bot_token
TG_API_ID=123456
TG_API_HASH=replace_with_real_api_hash
ADMIN_IDS=123456789
DATABASE_URL=postgresql+asyncpg://tg_bot:replace_with_db_password@127.0.0.1:5432/tg_account_bot
FERNET_KEY=replace_with_generated_fernet_key

SESSION_DIR=./data/sessions
BACKUP_DIR=./data/backups
LOG_LEVEL=INFO

MINI_APP_ENABLED=false
LOGIN_EMAIL_PROTECTION_ENABLED=true
LOGIN_EMAIL_ALIAS_DOMAINS=mail-a.example.com,mail-b.example.net
LOGIN_EMAIL_DOMAIN_BACKENDS=mail-a.example.com=cloudflare,mail-b.example.net=gmail
TEMP_MAIL_WEBHOOK_SECRET=replace_with_at_least_32_random_characters
LOGIN_EMAIL_GMAIL_USERNAME=your-account@gmail.com
LOGIN_EMAIL_GMAIL_APP_PASSWORD=replace_with_google_app_password
```

`.env` 由 Pydantic 在进程启动时读取。布尔值使用 `true`/`false`；列表使用英文逗号分隔，不要给整行额外套引号。
登录邮箱保护默认开启，因此至少需要一个 catch-all 域名，并完整配置该域名所选后端的凭据。只用 Cloudflare 时可省略 Gmail 凭据，只用 Gmail 时可省略 Webhook secret；明确不使用该功能时将开关设为 `false`。

### 环境变量完整说明

| 变量 | 必需 | 默认值/作用 |
| --- | --- | --- |
| `BOT_TOKEN` | 是 | Telegram Bot Token |
| `TG_API_ID` | 是 | Telegram API ID，整数 |
| `TG_API_HASH` | 是 | Telegram API Hash |
| `ADMIN_IDS` | 是 | 管理员 Telegram 用户 ID 列表 |
| `DATABASE_URL` | 是 | SQLAlchemy asyncpg PostgreSQL 连接串 |
| `FERNET_KEY` | 是 | 应用层敏感字段加密密钥 |
| `SESSION_DIR` | 否 | `./data/sessions`，本地 Session 目录 |
| `BACKUP_DIR` | 否 | `./data/backups`，数据库备份目录 |
| `DEFAULT_RATE_MAX_ACTIONS` | 否 | `8`，默认窗口内最大动作数 |
| `DEFAULT_RATE_PER_SECONDS` | 否 | `60`，默认窗口秒数 |
| `DEFAULT_JITTER_MIN` / `MAX` | 否 | `2` / `6`，批量动作随机等待秒数 |
| `SERVICE_MONITOR_INTERVAL_SECONDS` | 否 | `300`，服务监控周期；最小 30 秒 |
| `LOG_LEVEL` | 否 | `INFO` |
| `MINI_APP_ENABLED` | 否 | `false`，是否启动内置 HTTP 服务 |
| `MINI_APP_HOST` / `PORT` | 否 | `127.0.0.1` / `8080` |
| `MINI_APP_PUBLIC_URL` | 启用 Mini App 时 | 客户端可访问的完整 HTTPS `/mini-app` 地址 |
| `MINI_APP_AUTH_MAX_AGE_SECONDS` | 否 | `3600`，Telegram initData 最大有效期 |
| `LOGIN_EMAIL_PROTECTION_ENABLED` | 否 | `true`，是否自动更换登录邮箱；不使用时显式设为 `false` |
| `LOGIN_EMAIL_ALIAS_DOMAINS` | 启用邮箱保护时 | catch-all 域名列表，第一个为初始默认值 |
| `LOGIN_EMAIL_DOMAIN_BACKENDS` | 推荐 | 初始按域名路由：`domain=cloudflare` 或 `domain=gmail`；运行后可在 Telegram 中切换 |
| `TEMP_MAIL_WEBHOOK_SECRET` | 使用 Cloudflare 时 | Cloudflare Temp Email Webhook 随机共享密钥 |
| `LOGIN_EMAIL_GMAIL_USERNAME` | 使用 Gmail 时 | 接收 catch-all 转发的 Gmail 地址 |
| `LOGIN_EMAIL_GMAIL_APP_PASSWORD` | 使用 Gmail 时 | Gmail 应用专用密码 |
| `LOGIN_EMAIL_IMAP_HOST` / `PORT` | 否 | `imap.gmail.com` / `993` |
| `LOGIN_EMAIL_IMAP_FOLDER` | 否 | `INBOX` |
| `LOGIN_EMAIL_SENDER` | 否 | `noreply@telegram.org` |
| `LOGIN_EMAIL_POLL_TIMEOUT_SECONDS` | 否 | `300`，等待 catch-all 转发验证码；允许 30–7200 秒 |
| `LOGIN_EMAIL_POLL_INTERVAL_SECONDS` | 否 | `3`，数据库轮询间隔；允许 1–30 秒 |
| `LOGIN_EMAIL_CATCHUP_SECONDS` | 否 | `180`，服务重连时补拉近期登录提醒的时间窗口 |

---

## 6. 生成并保管 Fernet 密钥

```bash
cd /opt/tg-account-bot
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY"
```

把输出完整写入 `.env` 的 `FERNET_KEY`。注意：

- 不要提交到 Git，也不要和数据库备份放在同一个位置。
- 运行后随意更换密钥会导致已有手机号、Session、2FA 和邮箱数据无法解密。
- 迁移服务器时必须同时安全迁移此密钥。

---

## 7. 初始化数据库并运行检查

应用不会自动创建或升级表。首次部署和每次升级代码后，都必须执行：

```bash
cd /opt/tg-account-bot
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/alembic upgrade head"
```

运行测试和静态编译检查：

```bash
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pip install -r /opt/tg-account-bot/requirements-dev.txt"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pytest -q"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m compileall -q app tests alembic"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/alembic current"
```

需要前台排错时：

```bash
su -s /bin/bash tg-account-bot -c "cd /opt/tg-account-bot && .venv/bin/python -m app.main"
```

看到 Bot 开始 polling 且无数据库迁移错误后，用 `Ctrl+C` 停止，再配置 systemd。

---

## 8. 配置 systemd

仓库内服务文件已经使用 `/opt/tg-account-bot` 和 `tg-account-bot`：

```bash
install -m 644 /opt/tg-account-bot/ops/systemd/tg-account-bot.service \
  /etc/systemd/system/tg-account-bot.service
systemctl daemon-reload
systemctl enable --now tg-account-bot
```

检查服务：

```bash
systemctl status tg-account-bot --no-pager
journalctl -u tg-account-bot -n 100 --no-pager
journalctl -u tg-account-bot -f
```

如果改变部署目录或服务用户，必须同步修改 unit 中的 `WorkingDirectory`、`EnvironmentFile`、`ExecStart`、`User`、`Group` 和 `ReadWritePaths`。

---

## 9. 配置 Telegram Mini App 与 HTTPS（可选）

Mini App 必须通过 Telegram 客户端可访问的 HTTPS 地址打开。应用本身建议只监听回环地址：

```env
MINI_APP_ENABLED=true
MINI_APP_HOST=127.0.0.1
MINI_APP_PORT=8080
MINI_APP_PUBLIC_URL=https://bot.example.com/mini-app
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
```

安装 Nginx 与 Certbot：

```bash
apt install -y nginx certbot python3-certbot-nginx
```

创建 `/etc/nginx/sites-available/tg-account-bot`：

```nginx
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
```

启用站点并申请证书：

```bash
ln -s /etc/nginx/sites-available/tg-account-bot /etc/nginx/sites-enabled/tg-account-bot
nginx -t
systemctl reload nginx
certbot --nginx -d bot.example.com
systemctl restart tg-account-bot
```

验证公网响应：

```bash
curl -I https://bot.example.com/mini-app
```

### 9.1 配置机器人资料页的"打开应用"按钮

1. 打开 `@BotFather`，发送 `/mybots` 并选择对应机器人。
2. 进入 `Bot Settings` → `Configure Mini App` → `Enable Mini App`。
3. 按提示填写上面的 `MINI_APP_PUBLIC_URL`，并上传适合手机页面的预览图。
4. 返回机器人资料页，确认出现 `Launch app` 或"打开应用"按钮。

---

## 10. 配置登录邮箱保护（可选）

### 10.1 邮件侧准备

先为每个域名决定接收后端；同一部署可以混合使用：

| 后端 | 邮件路由平台的 Catch-all | 程序读取方式 |
| --- | --- | --- |
| `cloudflare` | Send to Worker → Cloudflare Temp Email | Worker POST Webhook，程序读 PostgreSQL |
| `gmail` | Send to email → 已验证的 Gmail 地址 | 程序通过 Gmail IMAP 读取 |

Cloudflare 后端需要生成随机 secret：

```bash
openssl rand -hex 32
```

把输出填入 `TEMP_MAIL_WEBHOOK_SECRET`，并在 Worker 全局 Webhook 中发送 `X-Temp-Mail-Secret`。

Gmail 后端需要为接收账号启用两步验证并创建应用专用密码，再把该 Gmail 地址作为 Email Routing 的已验证目标。

配置示例：

```env
LOGIN_EMAIL_PROTECTION_ENABLED=true
LOGIN_EMAIL_ALIAS_DOMAINS=mail-a.example.com,mail-b.example.net
LOGIN_EMAIL_DOMAIN_BACKENDS=mail-a.example.com=cloudflare,mail-b.example.net=gmail
TEMP_MAIL_WEBHOOK_SECRET=replace_with_at_least_32_random_characters
LOGIN_EMAIL_GMAIL_USERNAME=your-account@gmail.com
LOGIN_EMAIL_GMAIL_APP_PASSWORD=replace_with_google_app_password
LOGIN_EMAIL_IMAP_HOST=imap.gmail.com
LOGIN_EMAIL_IMAP_PORT=993
LOGIN_EMAIL_IMAP_FOLDER=INBOX
LOGIN_EMAIL_SENDER=noreply@telegram.org
LOGIN_EMAIL_POLL_TIMEOUT_SECONDS=300
LOGIN_EMAIL_POLL_INTERVAL_SECONDS=3
LOGIN_EMAIL_CATCHUP_SECONDS=180
```

保存后重启服务：

```bash
systemctl restart tg-account-bot
journalctl -u tg-account-bot -n 100 --no-pager
```

### 10.2 Bot 内验证

1. 发送 `/security`。
2. 打开"邮箱域名管理"，点击域名可选择默认域名；点击右侧 `CF TempMail` / `Gmail` 可切换该域名的读取后端。
3. 确认 Telegram 显示的后端与邮件路由平台的实际 Catch-all 完全一致。
4. 使用"检查邮件接收"验证当前所有域名使用到的后端。
5. 把本人会主动登录的账号加入白名单。
6. 对非白名单测试账号触发一次真实登录提醒，观察成功或失败通知。

---

## 11. 防火墙与权限建议

- 只向公网开放 SSH、80 和 443；不要公开 PostgreSQL 5432 或 Mini App 内部端口 8080。
- `.env`、`data/sessions`、`data/backups` 保持仅服务用户可读写。
- Telegram StringSession 等同于登录凭证，导出后应加密保存并及时删除临时副本。
- 管理员账号应启用 Telegram 2FA，并限制 `ADMIN_IDS`。
- 定期轮换 Bot Token、数据库密码和 Webhook secret；轮换 Fernet 密钥需要专门的数据重加密迁移，不能直接替换。

---

## 12. 备份与恢复

管理员在 Bot 中发送 `/backup` 会在 `BACKUP_DIR` 创建 PostgreSQL custom-format 备份，文件权限为 `0600`。也可以手动执行：

```bash
su -s /bin/bash tg-account-bot -c "pg_dump \
  --format=custom \
  --file=/opt/tg-account-bot/data/backups/manual.dump \
  --dbname=tg_account_bot \
  --host=127.0.0.1 \
  --username=tg_bot"
```

检查备份：

```bash
pg_restore --list /opt/tg-account-bot/data/backups/manual.dump
```

恢复前应停止服务，并优先恢复到新数据库进行验证。数据库备份包含加密后的敏感字段，仍必须按敏感数据管理；恢复时还需要原 `FERNET_KEY`。

---

## 13. 升级

先备份数据库和 `.env`，再执行：

```bash
cd /opt/tg-account-bot
su -s /bin/bash tg-account-bot -c "git pull --ff-only"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pip install -r /opt/tg-account-bot/requirements.txt"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/alembic upgrade head"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/python -m pytest -q"
systemctl restart tg-account-bot
systemctl status tg-account-bot --no-pager
```

如果新版本迁移失败，不要反复重启服务。保留日志、当前代码版本和迁移输出，再决定修复或从升级前备份恢复。

---

## 14. 常见故障

### 服务启动后立即退出

```bash
journalctl -u tg-account-bot -n 200 --no-pager
```

- `ValidationError`：`.env` 缺少必需值或字段格式错误。
- `数据库尚未初始化` / `迁移版本...`：执行 `.venv/bin/alembic upgrade head`。
- `Permission denied`：检查 `/opt/tg-account-bot`、`.env` 和 `data/` 的属主权限：

  ```bash
  ls -la /opt/tg-account-bot/
  stat /opt/tg-account-bot/.env
  ```

- Bot polling 冲突：同一 Bot Token 还有另一个实例在调用 `getUpdates`，停止重复实例。

### PostgreSQL 连接失败

```bash
# 确认服务运行
systemctl status postgresql --no-pager

# 确认数据库和用户存在
su - postgres -c "psql -c '\l'" 
su - postgres -c "psql -c '\du'"

# 手动测试连接
psql postgresql://tg_bot:密码@127.0.0.1:5432/tg_account_bot -c 'SELECT 1'
```

如果 `pg_hba.conf` 拒绝连接（`Ident authentication failed`），确认连接串使用了 `127.0.0.1` 而非 `localhost`，Debian 默认对 IPv4 本地连接使用 `md5`/`scram-sha-256` 认证。

### 主 ReplyKeyboard 找不到

发送 `/menu`。服务每次启动也会向管理员发送带主键盘的启动消息。

### Mini App 无法打开

- `MINI_APP_PUBLIC_URL` 必须是完整 HTTPS 地址，并以 `/mini-app` 结尾。
- 用 `curl -I` 验证 Nginx 与证书。
- 确认 8080 只在本机监听：`ss -lntp | grep 8080`。
- 直接浏览器调用 API 缺少 Telegram `initData` 时会返回 401，这是预期行为。

### Cloudflare TempMail、Gmail 或取码失败

- 确认 Cloudflare 请求头 `X-Temp-Mail-Secret` 与 `.env` 中的值完全一致。
- 确认 Webhook 返回 HTTP 200，且 `to` 是允许域名下的完整收件地址。
- Gmail 域名确认 catch-all 已投递到配置账号，应用专用密码有效且 IMAP 目录正确。
- 在 Telegram 的"邮箱域名管理"确认每个域名选择的后端与实际 Catch-all 一致。
- 确认发件人为配置的 `LOGIN_EMAIL_SENDER`。
- 检查服务器时间是否准确：`timedatectl status`。

### 检查当前版本与迁移

```bash
cd /opt/tg-account-bot
su -s /bin/bash tg-account-bot -c "git rev-parse --short HEAD"
su -s /bin/bash tg-account-bot -c "/opt/tg-account-bot/.venv/bin/alembic current"
systemctl show tg-account-bot -p ActiveState -p SubState -p NRestarts
```
