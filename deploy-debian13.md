# 部署指南（Debian 13）

<!-- markdownlint-disable MD013 -->

本文档给出一套可复制的 **Debian 13** 生产部署流程：独立系统用户、Python venv、PostgreSQL 17、systemd，以及可选的 Nginx HTTPS、Telegram Mini App、Cloudflare Temp Email 和 Gmail 登录邮箱保护。每个收件域名可以独立选择 Cloudflare 或 Gmail 后端。

> **Debian 13 注意事项**
>
> - Python 默认版本为 **3.13**，`python3-pip` 在 venv 外受 PEP 668 限制，不能直接 `pip install`；所有依赖安装必须在 venv 内执行（本文已统一使用 `.venv/bin/python -m pip`）。
> - PostgreSQL 默认版本为 **17**，软件包名为 `postgresql`，行为与 Debian 12 一致。
> - `useradd` 参数与 Debian 12 相同，无需修改。

示例部署目录为 `/opt/tg-account-bot`，服务用户为 `tg-account-bot`。命令中的域名、用户 ID、密码和 Token 都是占位值，必须替换。

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

## 2. 安装系统依赖和代码

```bash
sudo apt-get update
sudo apt-get install -y \
  git python3 python3-venv build-essential libpq-dev \
  postgresql postgresql-client
```

> **说明**：Debian 13 上 `python3-pip` 受 PEP 668 保护，系统级 pip 无法安装第三方包。本文所有依赖均在 venv 内安装，因此不需要安装 `python3-pip`。

创建不允许交互登录的服务用户：

```bash
sudo useradd --system --user-group \
  --home-dir /opt/tg-account-bot \
  --shell /usr/sbin/nologin \
  tg-account-bot
```

如果该用户已存在，可跳过 `useradd`。克隆项目并设置权限：

```bash
sudo git clone https://github.com/openhomek/tgmag.git /opt/tg-account-bot
sudo chown -R tg-account-bot:tg-account-bot /opt/tg-account-bot
```

创建 venv 并安装依赖（所有后续操作均在 venv 内进行）：

```bash
sudo -u tg-account-bot python3 -m venv /opt/tg-account-bot/.venv
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pip install --upgrade pip wheel
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pip install \
  -r /opt/tg-account-bot/requirements.txt
sudo install -d -o tg-account-bot -g tg-account-bot -m 700 \
  /opt/tg-account-bot/data/sessions \
  /opt/tg-account-bot/data/backups
```

> **说明**：后续所有命令均使用绝对路径 `/opt/tg-account-bot/.venv/bin/...`，避免因工作目录不同导致找不到 venv。

---

## 3. 创建 PostgreSQL 数据库

创建数据库用户时会交互式要求输入两次新密码，避免把明文密码写进 Shell 历史：

```bash
sudo -u postgres createuser --pwprompt tg_bot
sudo -u postgres createdb --owner=tg_bot tg_account_bot
```

确认数据库存在：

```bash
sudo -u postgres psql -c '\l tg_account_bot'
```

对应连接串格式：

```env
DATABASE_URL=postgresql+asyncpg://tg_bot:数据库密码@127.0.0.1:5432/tg_account_bot
```

如果密码包含 `@`、`:`、`/`、`#`、`%` 等字符，必须先进行 URL 百分号编码。为减少配置错误，建议使用足够长的纯字母数字密码。

---

## 4. 创建 `.env`

```bash
sudo install -o tg-account-bot -g tg-account-bot -m 600 \
  /opt/tg-account-bot/.env.example \
  /opt/tg-account-bot/.env
sudoedit /opt/tg-account-bot/.env
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

`.env` 由 Pydantic 在进程启动时读取，注意：

- 布尔值使用 `true`/`false`。
- 列表值（如 `LOGIN_EMAIL_ALIAS_DOMAINS`）使用英文逗号分隔，不要对整行套引号。
- 密码等纯字符串值若含特殊字符，可用单引号包裹整个值，例如 `KEY='pa$$word'`。

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

每个 TG 账号的等待窗口在 Mini App 账号详情的"登录邮箱保护"中独立设置，单位为整数小时，允许 `0–720`，默认 `0`（收到有效登录提醒后立即换绑）。大于 `0` 时，窗口内的新提醒仍逐条转发给管理员，只累计次数且不会延长窗口；到期后执行一次换绑并发送汇总结果。修改只影响之后的新窗口，服务重启后会恢复尚未结束的窗口。catch-all 转发可能延迟，系统在等待邮件期间不会重复发码，避免触发 Telegram 尝试次数限制。

---

## 5. 生成并保管 Fernet 密钥

**先保存并关闭上一步打开的 `.env` 编辑器**，再执行以下命令生成密钥：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

把输出完整写入 `.env` 的 `FERNET_KEY`：

```bash
sudoedit /opt/tg-account-bot/.env
# 找到 FERNET_KEY= 这一行，把上面的输出粘贴进去
```

注意：

- 不要提交到 Git，也不要和数据库备份放在同一个位置。
- 运行后随意更换密钥会导致已有手机号、Session、2FA 和邮箱数据无法解密。
- 迁移服务器时必须同时安全迁移此密钥。

---

## 6. 初始化数据库并运行检查

应用不会自动创建或升级表。首次部署和每次升级代码后，都必须执行：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  upgrade head
```

安装开发依赖并运行检查：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pip install \
  -r /opt/tg-account-bot/requirements-dev.txt

sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pytest \
  --rootdir=/opt/tg-account-bot -q

sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m compileall -q \
  /opt/tg-account-bot/app \
  /opt/tg-account-bot/tests \
  /opt/tg-account-bot/alembic

sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  current
```

需要前台排错时：

```bash
sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python \
  -m app.main \
  --directory /opt/tg-account-bot
```

看到 Bot 开始 polling 且无数据库迁移错误后，用 `Ctrl+C` 停止，再配置 systemd。

---

## 7. 配置 systemd

仓库内服务文件已经使用 `/opt/tg-account-bot` 和 `tg-account-bot`：

```bash
sudo install -m 644 /opt/tg-account-bot/ops/systemd/tg-account-bot.service \
  /etc/systemd/system/tg-account-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now tg-account-bot
```

检查服务：

```bash
sudo systemctl status tg-account-bot --no-pager
sudo journalctl -u tg-account-bot -n 100 --no-pager
sudo journalctl -u tg-account-bot -f
```

如果改变部署目录或服务用户，必须同步修改 unit 中的 `WorkingDirectory`、`EnvironmentFile`、`ExecStart`、`User`、`Group` 和 `ReadWritePaths`。

---

## 8. 配置 Telegram Mini App 与 HTTPS（可选）

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
sudo apt-get install -y nginx certbot python3-certbot-nginx
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
sudo ln -s /etc/nginx/sites-available/tg-account-bot \
  /etc/nginx/sites-enabled/tg-account-bot
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d bot.example.com
sudo systemctl restart tg-account-bot
```

验证公网响应：

```bash
curl -I https://bot.example.com/mini-app
```

验证 Mini App 内部端口只在本机监听：

```bash
ss -lntp | grep 8080
```

### 8.1 配置机器人资料页的"打开应用"按钮

聊天内的菜单按钮和机器人资料页按钮是两个不同入口。要实现类似 `@BotFather` 的效果，让用户无需先进入对话就能从资料页直接打开：

1. 打开 `@BotFather`，发送 `/mybots` 并选择对应机器人。
2. 进入 `Bot Settings` → `Configure Mini App` → `Enable Mini App`。
3. 按提示填写上面的 `MINI_APP_PUBLIC_URL`，并上传适合手机页面的预览图。
4. 返回机器人资料页，确认出现 `Launch app` 或"打开应用"按钮。

配置完成后也可以使用 `https://t.me/<bot_username>?startapp` 直接打开主 Mini App；需要传递场景参数时使用 `?startapp=<command>`。这个资料页按钮只能通过 `@BotFather` 配置，Bot API 无法代替管理员启用它。

聊天内仍可发送 `/app` 打开同一个页面。Mini App API 会校验 Telegram `initData` 签名和管理员身份，因此直接用普通浏览器访问页面后出现未授权 API 响应是正常现象。

---

## 9. 配置登录邮箱保护（可选）

### 9.1 邮件侧准备

先为每个域名决定接收后端；同一部署可以混合使用：

| 后端 | 邮件路由平台的 Catch-all | 程序读取方式 |
| --- | --- | --- |
| `cloudflare` | Send to Worker → Cloudflare Temp Email | Worker POST Webhook，程序读 PostgreSQL |
| `gmail` | Send to email → 已验证的 Gmail 地址 | 程序通过 Gmail IMAP 读取 |

**Cloudflare 后端**：先生成随机 secret：

```bash
openssl rand -hex 32
```

把输出填入 `.env` 的 `TEMP_MAIL_WEBHOOK_SECRET`。再把 `/webhooks/temp-mail` 通过现有 HTTPS 反向代理转发到内置 Web 服务，并在 Worker 全局 Webhook 中发送 `X-Temp-Mail-Secret`。完整 Worker、D1、KV、Email Routing 和 Apache 实例配置见 [README 的 Cloudflare 部署章节](README.md#tempmail--cloudflare-temp-email-部署backend-only)。

**Gmail 后端**：为接收账号启用两步验证并创建应用专用密码，再把该 Gmail 地址作为 Email Routing 的已验证目标。应用密码只保存在 `.env`，不能提交到仓库。

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
sudo systemctl restart tg-account-bot
sudo journalctl -u tg-account-bot -n 100 --no-pager
```

### 9.2 Bot 内验证

1. 发送 `/security`。
2. 打开"邮箱域名管理"，点击域名可选择默认域名；点击右侧 `CF TempMail` / `Gmail` 可切换该域名的读取后端。
3. 确认 Telegram 显示的后端与邮件路由平台的实际 Catch-all 完全一致。
4. 使用"检查邮件接收"验证当前所有域名使用到的后端。
5. 把本人会主动登录的账号加入白名单；这些账号仅转发提醒，不自动换绑。
6. 对非白名单测试账号触发一次真实登录提醒，观察成功或失败通知。

环境变量提供初始域名、后端映射和凭据。Bot 中增删域名、当前默认域名和逐域名后端选择会保存在 PostgreSQL，后续以数据库值为准。程序不会代替管理员修改 Cloudflare Email Routing：应先手动更改 Catch-all，再在 Telegram 中切换后端。若 Telegram 返回 `EMAIL_NOT_ALLOWED`，说明该域名不被接受；在失败通知下点击快捷换绑按钮，改选其他域名重试。

程序会校验邮件发件人、目标别名、Login 用途、邮件时间，以及标题和正文验证码是否一致。它不会因为白名单账号的提醒而换绑，也不会主动终止其他会话。

---

## 10. 防火墙与权限建议

- 只向公网开放 SSH、80 和 443；不要公开 PostgreSQL 5432 或 Mini App 内部端口 8080。
- `.env`、`data/sessions`、`data/backups` 保持仅服务用户可读写。
- Telegram StringSession 等同于登录凭证，导出后应加密保存并及时删除临时副本。
- 管理员账号应启用 Telegram 2FA，并限制 `ADMIN_IDS`。
- 定期轮换 Bot Token、数据库密码和 Webhook secret；轮换 Fernet 密钥需要专门的数据重加密迁移，不能直接替换。

---

## 11. 备份与恢复

管理员在 Bot 中发送 `/backup` 会在 `BACKUP_DIR` 创建 PostgreSQL custom-format 备份，文件权限为 `0600`。也可以手动执行（执行时会提示输入数据库密码，或提前在 `~tg-account-bot/.pgpass` 中配置免密）：

```bash
sudo -u tg-account-bot pg_dump \
  --format=custom \
  --file=/opt/tg-account-bot/data/backups/manual.dump \
  --dbname=tg_account_bot \
  --host=127.0.0.1 \
  --username=tg_bot
```

检查备份：

```bash
pg_restore --list /opt/tg-account-bot/data/backups/manual.dump
```

恢复前应停止服务，并优先恢复到新数据库进行验证。数据库备份包含加密后的敏感字段，仍必须按敏感数据管理；恢复时还需要原 `FERNET_KEY`。

---

## 12. 升级

先备份数据库和 `.env`，再执行：

```bash
sudo -u tg-account-bot git -C /opt/tg-account-bot pull --ff-only

sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pip install \
  -r /opt/tg-account-bot/requirements.txt

sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  upgrade head

sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/python -m pytest \
  --rootdir=/opt/tg-account-bot -q

sudo systemctl restart tg-account-bot
sudo systemctl status tg-account-bot --no-pager
```

如果新版本迁移失败，不要反复重启服务。保留日志、当前代码版本和迁移输出，再决定修复或从升级前备份恢复。

---

## 13. 常见故障

### 服务启动后立即退出

```bash
sudo journalctl -u tg-account-bot -n 200 --no-pager
```

- `ValidationError`：`.env` 缺少必需值或字段格式错误。
- `数据库尚未初始化` / `迁移版本...`：执行 `alembic upgrade head`（见第 6 节）。
- `Permission denied`：检查 `/opt/tg-account-bot`、`.env` 和 `data/` 的属主与权限。
- Bot polling 冲突：同一 Bot Token 还有另一个实例在调用 `getUpdates`，停止重复实例。
- `externally-managed-environment`：误用了系统 pip 而非 venv 内的 pip；使用本文的绝对路径形式。

### 主 ReplyKeyboard 找不到

发送 `/menu`。服务每次启动也会向管理员发送带主键盘的启动消息。项目不会发送 `ReplyKeyboardRemove`。

### Mini App 无法打开

- `MINI_APP_PUBLIC_URL` 必须是完整 HTTPS 地址，并以 `/mini-app` 结尾。
- 用 `curl -I https://bot.example.com/mini-app` 验证 Nginx 与证书。
- 确认 8080 只在本机监听：`ss -lntp | grep 8080`。
- 直接浏览器调用 API 缺少 Telegram `initData` 时会返回 401，这是预期行为。

### Cloudflare TempMail、Gmail 或取码失败

- 确认 Cloudflare 请求头 `X-Temp-Mail-Secret` 与 `.env` 中的值完全一致。
- 确认 Webhook 返回 HTTP 200，且 `to` 是允许域名下的完整收件地址。
- Gmail 域名确认 catch-all 已投递到配置账号，应用专用密码有效且 IMAP 目录正确。
- 在 Telegram 的"邮箱域名管理"确认每个域名选择的后端与实际 Catch-all 一致。
- 确认发件人为配置的 `LOGIN_EMAIL_SENDER`。
- 检查服务器时间是否准确；取码会校验数据库收件时间窗口。
- Telegram 不接受域名时会通知失败，可从 InlineKeyboard 选择其他配置域名重试。

### 检查当前版本与迁移

```bash
sudo -u tg-account-bot git -C /opt/tg-account-bot rev-parse --short HEAD

sudo -u tg-account-bot /opt/tg-account-bot/.venv/bin/alembic \
  --config /opt/tg-account-bot/alembic.ini \
  current

sudo systemctl show tg-account-bot -p ActiveState -p SubState -p NRestarts
```
