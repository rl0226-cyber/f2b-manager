# f2b-manager 故障排查指南

> 遇到问题时，按「现象 → 原因 → 解决」的顺序排查。
> 文末附 **诊断命令速查**。

---

## 一、服务启动失败

### 现象
```bash
systemctl start f2b-manager
# Job failed. See "systemctl status f2b-manager" and "journalctl"
```

### 排查步骤

**1. 查看详细日志**
```bash
journalctl -u f2b-manager -n 50 --no-pager
```

**2. 常见原因**

| 原因 | 表现 | 解决 |
|------|------|------|
| Python 版本过低 | `module ... requires Python '>=3.10'` | 升级 Python 到 3.10+ 后重跑 `install.sh` |
| 虚拟环境缺失 | `No such file or directory: /opt/f2b-manager/venv/bin/python` | 重新执行 `sudo bash install.sh` |
| 配置文件不存在 | `配置文件未找到` | `cp /opt/f2b-manager/config.example.yaml /etc/f2b-manager/config.yaml` |
| 配置校验失败 | `配置错误: bot_token 未设置` | 编辑 `config.yaml` 填入真实 `bot_token` |
| 依赖未装全 | `ModuleNotFoundError: No module named 'telegram'` | `sudo /opt/f2b-manager/venv/bin/pip install -r /opt/f2b-manager/requirements.txt` |
| 端口/权限冲突 | `Permission denied` | 确认以 root 运行（`User=root`） |

**3. 快速自检**
```bash
# 1) 直接用 venv python 试运行（会打印配置校验结果）
sudo /opt/f2b-manager/venv/bin/python -m f2b_manager run --dry-run

# 2) 确认服务文件存在且已 enable
systemctl cat f2b-manager
```

---

## 二、Bot 无响应（发命令没反应）

### 现象
Telegram 中给 Bot 发 `/status` 没有任何回复。

### 排查步骤

**1. 确认服务在运行**
```bash
systemctl status f2b-manager --no-pager
```

**2. 检查 bot_token 是否正确**
```bash
# 在日志中搜索 token 相关错误
journalctl -u f2b-manager -n 100 --no-pager | grep -i "token\|unauthorized\|401"
```
- `401 Unauthorized` → `bot_token` 填错或失效，重新从 @BotFather 复制。
- 注意 Token 中间是冒号 `:`，整段都要复制，前后不要有空格。

**3. 确认 Bot 未被停用**
在 Telegram 给 Bot 发 `/start`，如果连 `/start` 都没反应，通常是上述 token 问题或进程未运行。

**4. 检查 chat_id 是否授权**
```bash
journalctl -u f2b-manager -n 100 --no-pager | grep -i "unauthorized\|not authorized\|chat"
```
- 若提示「未授权」，把你的 `chat_id` 加入 `config.yaml` 的 `admin_chat_ids`，然后：
  ```bash
  systemctl restart f2b-manager
  ```
- 用 `/start` 可查看自己的 chat_id。

**5. 检查是否存在多个实例（polling 冲突）**
同一 Token 同时跑两个进程会导致「一个收消息、另一个抢走」，表现为时灵时不灵。
```bash
ps aux | grep "python -m f2b_manager" | grep -v grep
```
确认只有一个进程。若有多余，杀掉后 `systemctl restart f2b-manager`。

**6. 检查服务器能否访问 Telegram**
```bash
curl -s https://api.telegram.org/bot<TOKEN>/getMe
```
返回含 `"ok":true` 且 bot 用户名正确 → 网络正常；超时 → 检查防火墙 / 出网策略。

---

## 三、fail2ban 未安装 / 安装失败

### 现象
- `/status` 提示 fail2ban 不可用
- `install.sh` 中 `f2b-manager fail2ban install` 报错

### 排查步骤

**1. 确认 fail2ban 是否安装**
```bash
which fail2ban-server fail2ban-client
fail2ban-client --version
systemctl status fail2ban --no-pager
```

**2. 手动安装（如自动安装失败）**
```bash
# Debian / Ubuntu
apt-get update && apt-get install -y fail2ban

# CentOS / RHEL / Rocky
dnf install -y fail2ban

systemctl enable --now fail2ban
```

**3. 安装后让 f2b-manager 接管配置**
```bash
f2b-manager fail2ban install     # 生成 jail.local + 部署 telegram action
systemctl restart fail2ban
systemctl restart f2b-manager
```

**4. 发行版检测异常**
若 `install.sh` 报「无法识别发行版」，确认 `/etc/os-release` 存在且正常。极端情况下可手动安装后跳过：`sudo bash install.sh --no-fail2ban`。

---

## 四、通知不到达（封禁了但 Telegram 没收到预警）

### 现象
fail2ban 实际封禁了 IP（日志可见 `Ban 1.2.3.4`），但 Telegram 没收到封禁预警。

### 排查步骤

**1. 确认实时预警开关已开**
```bash
# 在 Telegram 发送
/setnotify on
```
并确认 `config.yaml` 中 `notify.enable_ban_alert: true`。

**2. 确认 notify_chat_id 配置正确**
预警发送目标是 `notify_chat_id`，要保证它等于你接收消息的 chat_id。
```bash
grep notify_chat_id /etc/f2b-manager/config.yaml
```

**3. 检查桥接脚本是否就位**
实时预警依赖 fail2ban 的 action 调用 `/usr/local/bin/f2b-notify.sh`。
```bash
ls -l /usr/local/bin/f2b-notify.sh      # 应存在且 755
cat /etc/fail2ban/action.d/telegram-notify.conf | grep actionban
```
- 若 `f2b-notify.sh` 不存在 → 重跑 `install.sh` 或手动：
  ```bash
  cp scripts/f2b-notify.sh /usr/local/bin/f2b-notify.sh
  chmod 755 /usr/local/bin/f2b-notify.sh
  ```
- 若 `telegram-notify.conf` 缺失 → 重跑 `f2b-manager fail2ban install`。

**4. 确认 jail 已挂载 telegram action**
```bash
fail2ban-client get sshd actions
# 输出应包含 telegram-notify
```
若不含，说明 `jail.local` 的 action 未追加 telegram action，重跑 `f2b-manager fail2ban install` 并 `fail2ban-client reload`。

**5. 检查 f2b-manager 守护进程是否在运行**
桥接脚本把事件转给守护进程后才能发消息。若守护进程挂了，事件会丢失（此时轮询兜底每分钟补偿，但需进程存活）。
```bash
systemctl status f2b-manager
journalctl -u f2b-manager -n 50 --no-pager | grep -i "notify\|ban"
```

**6. GeoIP 报错导致发送失败？**
若启用 `geoip.method: local` 但数据库缺失，归属地查询会失败但不应阻断发送。可临时关闭定位以排除：
```yaml
notify:
  geoip:
    enabled: false
```
然后 `systemctl restart f2b-manager`。

---

## 五、实时预警有延迟

- **正常**：hook 实时触发（秒级）；轮询兜底每 5 分钟补偿一次遗漏事件。
- 若完全收不到、只能等报告，通常是 **action 未挂载**（见第四节第 4 步）。
- 若偶尔延迟数分钟，属轮询兜底补偿窗口，属正常设计。

---

## 六、配置文件权限问题

`config.yaml` 权限必须严格为 `600`（仅 root 可读），否则程序可能拒绝启动或告警。

```bash
chmod 600 /etc/f2b-manager/config.yaml
chown root:root /etc/f2b-manager/config.yaml
```

---

## 七、日志查看

```bash
# 守护进程日志（systemd）
journalctl -u f2b-manager -f

# 程序自身日志文件
tail -f /var/log/f2b-manager.log

# fail2ban 日志
tail -f /var/log/fail2ban.log
```

---

## 八、彻底重装

若环境混乱，建议干净重装：

```bash
# 1. 卸载（交互确认删除配置）
sudo bash uninstall.sh -y

# 2. 清理残留（如需）
rm -rf /opt/f2b-manager /etc/f2b-manager /var/lib/f2b-manager

# 3. 重新上传最新代码并安装
sudo bash install.sh
sudo vim /etc/f2b-manager/config.yaml   # 填 token / chat_id
systemctl start f2b-manager
```

---

## 九、诊断命令速查

```bash
# 服务状态
systemctl status f2b-manager --no-pager
systemctl status fail2ban --no-pager

# 日志
journalctl -u f2b-manager -n 100 --no-pager
journalctl -u f2b-manager -f

# 配置校验
sudo /opt/f2b-manager/venv/bin/python -m f2b_manager run --dry-run

# fail2ban 状态
f2b-manager status
fail2ban-client status
fail2ban-client banned
fail2ban-client get sshd actions

# 文件检查
ls -l /usr/local/bin/f2b-manager /usr/local/bin/f2b-notify.sh
ls -l /etc/f2b-manager/config.yaml
cat /etc/fail2ban/action.d/telegram-notify.conf | grep actionban

# 网络检查
curl -s https://api.telegram.org/bot<TOKEN>/getMe

# 进程检查（避免多实例）
ps aux | grep "python -m f2b_manager" | grep -v grep
```

---

## 十、仍无法解决？

收集以下信息后反馈：
1. `journalctl -u f2b-manager -n 200 --no-pager` 的输出
2. `systemctl status f2b-manager --no-pager` 的输出
3. `config.yaml`（**请先删除 bot_token 等敏感字段**）
4. 发行版与 Python 版本：`cat /etc/os-release | head -n3; python3 --version`
