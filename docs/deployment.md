# f2b-manager 部署文档

> 适用对象：新手用户 / 运维人员
> 目标：在一台 Linux VPS 上完整部署 f2b-manager（Fail2ban 管理 + Telegram 机器人 + 实时预警）

---

## 一、系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Debian / Ubuntu / CentOS / RHEL / Rocky / AlmaLinux |
| 权限 | **root**（安装与管理 fail2ban 必需） |
| Python | **3.10 及以上** |
| 进程管理 | systemd |
| 网络 | 可访问 `api.telegram.org`（出站 443） |
| 其他 | 一个 Telegram 账号（用于接收通知） |

---

## 二、准备 Telegram Bot

### 步骤 1：创建 Bot 并获取 Token

1. 在 Telegram 中搜索 **@BotFather** 并打开对话。
2. 发送命令 `/newbot`。
3. 按提示输入 **Bot 显示名称**（如 `My VPS Guard`）。
4. 再输入 **Bot 用户名**（必须以 `bot` 结尾，如 `my_vps_guard_bot`）。
5. BotFather 会返回一段类似下面的 **Token**（这就是 `bot_token`）：

```
Use this token to access the HTTP API:
123456789:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890
```

> ⚠️ **Token 等同于 Bot 的密码，切勿泄露或提交到公开仓库。**

### 步骤 2：获取你的 chat_id

`chat_id` 是 Telegram 用来标识「你和 Bot 的私聊会话」的数字 ID。获取方法：

1. 打开你刚创建的 Bot，点击 **START**（或发送任意消息，如 `/start`）。
2. 在浏览器访问下面的 URL（把 `TOKEN` 替换成你的真实 Token）：

```
https://api.telegram.org/botTOKEN/getUpdates
```

> 注意：`bot` 后面**没有斜杠**，是 `botTOKEN`（连在一起）。

3. 在返回的 JSON 中找到 `result[0].message.chat.id`，例如：

```json
{
  "ok": true,
  "result": [
    {
      "message": {
        "chat": { "id": 123456789, "type": "private" }
      }
    }
  ]
}
```

这里的 `123456789` 就是你的 **chat_id**（`admin_chat_ids` 和 `notify_chat_id` 都填它）。

> 💡 如果 `result` 为空 `[]`，说明你还没给 Bot 发消息，先发一条再刷新页面。

---

## 三、上传项目到服务器

把本项目（整个 `Fail2ban脚本` 目录）传到 VPS，例如用 `scp`：

```bash
# 在你的本地电脑上执行
scp -r ./Fail2ban脚本 root@你的服务器IP:/root/
```

SSH 登录服务器后，进入项目目录：

```bash
ssh root@你的服务器IP
cd /root/Fail2ban脚本
```

> 也可以 `git clone` 你的仓库，只要最终服务器上有 `install.sh`、`f2b_manager/`、`config/`、`systemd/`、`scripts/` 这些文件即可。

---

## 四、一键安装

```bash
sudo bash install.sh
```

脚本会自动完成以下事情：

1. ✅ 检查 **root 权限** 与 **Python 3.10+**
2. ✅ 创建目录 `/opt/f2b-manager`、`/etc/f2b-manager`
3. ✅ 复制程序代码到 `/opt/f2b-manager`
4. ✅ 创建 Python 虚拟环境并安装依赖
5. ✅ 创建 CLI 包装器 `/usr/local/bin/f2b-manager`
6. ✅ 生成配置文件 `/etc/f2b-manager/config.yaml`（权限 600）
7. ✅ 安装并配置 fail2ban（`f2b-manager fail2ban install`）
8. ✅ 部署 systemd 服务并设为开机自启
9. ✅ 部署桥接脚本 `/usr/local/bin/f2b-notify.sh`

> 如果 fail2ban 已经装好，想跳过这一步，可加参数：
> ```bash
> sudo bash install.sh --no-fail2ban
> ```

安装成功的结尾会显示：

```
✅ f2b-manager 安装完成！

下一步操作:
  1. 编辑配置:   vim /etc/f2b-manager/config.yaml
     将 bot_token / admin_chat_ids / notify_chat_id 替换为你的真实值
  2. 启动服务:   systemctl start f2b-manager
  3. 查看日志:   journalctl -u f2b-manager -f
  4. Telegram 测试: 给 Bot 发送 /start
```

---

## 五、填写配置

编辑配置文件：

```bash
vim /etc/f2b-manager/config.yaml
```

**必须修改的三处**（其余保持默认即可）：

```yaml
telegram:
  bot_token: "123456789:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890"  # ← 替换为你的 Token
  admin_chat_ids: [123456789]        # ← 替换为你的 chat_id
  notify_chat_id: 123456789          # ← 替换为你的 chat_id（接收报告的会话）
```

保存退出后，确认文件权限仍是 `600`：

```bash
ls -l /etc/f2b-manager/config.yaml
# -rw------- 1 root root ... config.yaml
```

---

## 六、启动服务

```bash
systemctl start f2b-manager
systemctl status f2b-manager --no-pager
```

预期看到 `active (running)`。

查看实时日志（验证是否成功连接 Telegram）：

```bash
journalctl -u f2b-manager -f
```

---

## 七、验证部署

在 Telegram 中给你的 Bot 发送命令：

| 命令 | 预期结果 |
|------|----------|
| `/start` | 返回欢迎语，并显示你的 chat_id |
| `/status` | 显示 fail2ban 版本、运行状态、jail 数量、封禁总数 |
| `/jails` | 列出当前启用的 jail |

如果三条命令都正常返回，说明部署成功 🎉

---

## 八、首次配置检查清单

部署完成后，请逐项核对：

- [ ] 已创建 Telegram Bot 并拿到 `bot_token`
- [ ] 已给 Bot 发过消息并拿到 `chat_id`
- [ ] `/etc/f2b-manager/config.yaml` 中 `bot_token` 已替换
- [ ] `admin_chat_ids` 与 `notify_chat_id` 已替换
- [ ] 配置文件权限为 `600`（root 可读）
- [ ] `systemctl status f2b-manager` 显示 `active (running)`
- [ ] `/start` 能收到欢迎消息
- [ ] `/status` 能返回 fail2ban 状态
- [ ] fail2ban 服务本身在运行：`systemctl status fail2ban`
- [ ] 桥接脚本就位：`ls -l /usr/local/bin/f2b-notify.sh`

---

## 九、（可选）启用 IP 归属地显示

实时预警消息默认会显示攻击 IP 的国家/地区，需要 GeoLite2 数据库。

```bash
# 查看如何获取 License Key 并注册自动更新
sudo bash scripts/geoip-update.sh --setup

# 方式一：使用 MaxMind 官方（需 Key）
export GEOIP_LICENSE_KEY="你的KEY"
sudo bash scripts/geoip-update.sh

# 方式二：使用公益镜像（无需 Key，数据略有延迟）
sudo bash scripts/geoip-update.sh --mirror

# 注册每周自动更新（推荐）
sudo bash scripts/geoip-update.sh --cron
```

确认 `config.yaml` 中：

```yaml
notify:
  geoip:
    enabled: true
    method: local
    db_path: "/var/lib/GeoIP/GeoLite2-Country.mmdb"
```

---

## 十、升级与重装

### 升级程序

```bash
cd /root/Fail2ban脚本
git pull            # 或重新上传最新代码
sudo bash install.sh --no-fail2ban   # 复用已有 fail2ban，仅更新程序
systemctl restart f2b-manager
```

### 完全卸载

```bash
sudo bash uninstall.sh
```

脚本会交互式询问是否删除程序目录、配置、状态库与日志。**默认保留配置**，便于重装。

---

## 十一、目录与路径速查

| 用途 | 路径 |
|------|------|
| 程序目录 | `/opt/f2b-manager` |
| 虚拟环境 | `/opt/f2b-manager/venv` |
| 配置文件 | `/etc/f2b-manager/config.yaml`（权限 600） |
| systemd 服务 | `/etc/systemd/system/f2b-manager.service` |
| 桥接脚本 | `/usr/local/bin/f2b-notify.sh` |
| CLI 包装器 | `/usr/local/bin/f2b-manager` |
| 状态库 (SQLite) | `/var/lib/f2b-manager/state.db` |
| 日志 | `/var/log/f2b-manager.log` |
| GeoIP 库 | `/var/lib/GeoIP/GeoLite2-Country.mmdb` |
| fail2ban action | `/etc/fail2ban/action.d/telegram-notify.conf` |
