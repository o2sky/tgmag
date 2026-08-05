# tgmag

面向自有或已授权 Telegram 账号的多账号管理 Bot，基于 aiogram、Telethon、PostgreSQL 和 aiohttp。

## 运行要求

- Debian 12（推荐）
- Python 3.11+
- PostgreSQL 14+
- Telegram Bot Token
- Telegram API ID 与 API Hash
- 公网 HTTPS 域名（仅 Mini App 需要）
- Gmail 应用专用密码和 catch-all 域名（仅登录邮箱保护需要）

## 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/yuuheu/tgmag.git
cd tgmag
./ops/install_debian12.sh
cp .env.example .env
```

该脚本适用于 Debian 12，会安装系统依赖并在当前目录创建 `.venv`。

### 2. 配置必填环境变量

编辑 `.env`，以下配置缺一不可：

| 环境变量 | 说明 |
| --- | --- |
| `BOT_TOKEN` | 从 `@BotFather` 获取的 Telegram Bot Token。 |
| `TG_API_ID` | 从 `https://my.telegram.org` 获取的 Telegram API ID。 |
| `TG_API_HASH` | 与 API ID 对应的 Telegram API Hash。 |
| `ADMIN_IDS` | 允许管理 Bot 的 Telegram 数值用户 ID，多个 ID 用英文逗号分隔。 |
| `DATABASE_URL` | PostgreSQL asyncpg 连接串。 |
| `FERNET_KEY` | 加密手机号、Session、2FA 和登录邮箱等敏感数据的主密钥。 |

可选功能使用以下配置：

| 环境变量 | 说明 |
| --- | --- |
| `MINI_APP_ENABLED` | 是否启用 Mini App；启用时还要配置公开 HTTPS 地址。 |
| `MINI_APP_PUBLIC_URL` | Telegram 客户端可访问的完整 `/mini-app` HTTPS 地址。 |
| `LOGIN_EMAIL_PROTECTION_ENABLED` | 是否启用自动登录邮箱保护，默认开启；不使用时显式设为 `false`。 |
| `LOGIN_EMAIL_ALIAS_DOMAINS` | catch-all 域名列表，多个域名用英文逗号分隔，第一个为初始默认域名。 |
| `LOGIN_EMAIL_GMAIL_USERNAME` | 接收 catch-all 转发邮件的 Gmail 地址。 |
| `LOGIN_EMAIL_GMAIL_APP_PASSWORD` | Gmail 应用专用密码，不是 Google 账号的普通登录密码。 |

完整字段、默认值和允许范围见 [DEPLOY.md 的环境变量说明](DEPLOY.md#环境变量完整说明)。

### 3. 生成 Fernet 密钥

每个新部署应生成自己的密钥：

```bash
.venv/bin/python -c \
'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

将完整输出写入 `.env`：

```env
FERNET_KEY=粘贴刚才生成的完整密钥
```

注意：

- 服务存入数据后不要直接更换此密钥，否则已有加密数据将无法解密。
- 迁移服务器时必须安全迁移原密钥，而不是重新生成。
- 不要把密钥提交到 Git，建议另外保存在密码管理器中。

### 4. 初始化并启动

```bash
. .venv/bin/activate
alembic upgrade head
python -m app.main
```

前台启动适合首次验证；生产环境应使用 [systemd 部署步骤](DEPLOY.md#7-配置-systemd)。

## 检查

Bot 启动后建议按以下顺序操作：

 发送 `/status` 检查服务状态。


## 快捷更新仓库

部署在默认目录时，可用下面这条命令仅拉取仓库的最新代码：

```bash
cd /opt/tg-account-bot && sudo -u tg-account-bot git pull --ff-only
```

## License

[MIT](LICENSE)
