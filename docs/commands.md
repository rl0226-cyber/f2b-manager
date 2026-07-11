# f2b-manager 命令手册

> 所有命令均在 Telegram 私聊 Bot 中发送。
> **权限等级**：`admin`（管理员，全权限）> `operator`（操作员，查询+通知）> 未授权（仅 `/start`、`/help`）。
> 未授权用户发送任何受保护命令都会被静默拒绝。

---

## 权限总览

| 等级 | chat_id 来源 | 可执行命令 |
|------|--------------|------------|
| **admin** | `config.yaml` → `telegram.admin_chat_ids` | 全部 17 条 |
| **operator** | `telegram.operator_chat_ids` | `/start` `/help` `/status` `/jails` `/banned` `/jail` `/report` `/setnotify` `/stats` |
| 未授权 | — | `/start` `/help`（其余拒绝） |

---

## 命令详解

### 1. `/start`
- **权限**：所有用户
- **功能**：显示欢迎语，并回显你当前的 `chat_id`（用于把它加入 `admin_chat_ids`）。
- **参数**：无
- **示例**：`/start`
- **返回**：
  ```
  👋 欢迎使用 f2b-manager！
  你的 chat_id: 123456789
  请将此 ID 加入配置文件的管理员列表。
  ```

### 2. `/help`
- **权限**：所有用户
- **功能**：列出当前用户有权使用的命令清单。
- **参数**：无
- **示例**：`/help`

### 3. `/status`
- **权限**：授权用户（admin / operator）
- **功能**：fail2ban 运行状态总览（版本、运行状态、运行时长、jail 数、总封禁数）。
- **参数**：无
- **示例**：`/status`

### 4. `/jails`
- **权限**：授权用户
- **功能**：列出所有启用的 jail 及其当前封禁数量、失败次数。
- **参数**：无
- **示例**：`/jails`

### 5. `/banned`
- **权限**：授权用户
- **功能**：列出当前所有 jail 中被封禁的 IP（跨全部 jail 汇总）。
- **参数**：无
- **示例**：`/banned`

### 6. `/jail <name>`
- **权限**：授权用户
- **功能**：查看指定 jail 的详情（当前封禁 IP、失败次数、findtime、bantime 等）。
- **参数**：
  - `<name>`：jail 名称，必填（如 `sshd`）
- **示例**：`/jail sshd`

### 7. `/ban <ip>`
- **权限**：**admin**
- **功能**：手动封禁指定 IP（立即生效，走 fail2ban `set <jail> banip`）。
- **参数**：
  - `<ip>`：要封禁的 IPv4/IPv6 地址，必填
  - 默认 jail 为 `sshd`，可用 `@jail` 指定，如 `/ban 1.2.3.4@nginx-http-auth`
- **示例**：`/ban 1.2.3.4`
- **注意**：错误格式会被拒绝并提示。

### 8. `/unban <ip>`
- **权限**：**admin**
- **功能**：解封指定 IP（fail2ban `unban`）。
- **参数**：
  - `<ip>`：要解封的 IP，必填
- **示例**：`/unban 1.2.3.4`

### 9. `/install`
- **权限**：**admin**
- **功能**：安装 fail2ban（自动识别发行版并用包管理器安装，生成 `jail.local` 与 Telegram action）。
- **参数**：无
- **示例**：`/install`
- **说明**：长耗时操作，会先发送「安装中…」进度提示，完成后汇报结果。

### 10. `/uninstall`
- **权限**：**admin**
- **功能**：卸载 fail2ban（停止服务、禁用、卸载包，可选保留配置备份）。
- **参数**：无
- **示例**：`/uninstall`
- **注意**：**危险操作**，会触发二次确认对话（点「确认卸载」才执行）。

### 11. `/update`
- **权限**：**admin**
- **功能**：更新 fail2ban 到最新版本（包管理器升级 + 重启服务）。
- **参数**：无
- **示例**：`/update`

### 12. `/reload`
- **权限**：**admin**
- **功能**：重载 fail2ban 配置（`fail2ban-client reload`）。修改 jail 配置后使用。
- **参数**：无
- **示例**：`/reload`

### 13. `/report`
- **权限**：授权用户
- **功能**：立即生成并发送一份当前封禁情况报告（等效于每日报告的即时版）。
- **参数**：无
- **示例**：`/report`

### 14. `/whitelist`
- **权限**：**admin**
- **功能**：查看 / 管理 fail2ban 白名单（`ignoreip`）。
- **参数**：
  - `add <ip>`：添加白名单 IP/CIDR
  - `del <ip>`：移除白名单
  - 不带参数：列出当前白名单
- **示例**：
  - `/whitelist` → 列出
  - `/whitelist add 203.0.113.5` → 添加
  - `/whitelist del 203.0.113.5` → 删除

### 15. `/setnotify <on|off>`
- **权限**：授权用户（admin / operator）
- **功能**：开关实时预警通知（封禁/解封事件是否推送到 Telegram）。
- **参数**：
  - `on`：开启
  - `off`：关闭
- **示例**：`/setnotify off`

### 16. `/setschedule`
- **权限**：**admin**
- **功能**：设置定时报告的频率与时间。
- **参数**：
  - `daily <HH:MM>`：每日报告时间
  - `weekly <day> <HH:MM>`：每周报告（day 为 monday~sunday）
  - `off`：关闭定时报告
- **示例**：
  - `/setschedule daily 08:00`
  - `/setschedule weekly monday 08:00`
  - `/setschedule off`

### 17. `/stats [days]`
- **权限**：授权用户
- **功能**：统计最近 N 天的封禁情况（封禁次数、独立 IP 数、Top 来源国家）。
- **参数**：
  - `[days]`：统计天数，可选，默认 7
- **示例**：
  - `/stats` → 最近 7 天
  - `/stats 30` → 最近 30 天

---

## 命令速查表

| # | 命令 | 权限 | 参数 | 示例 |
|---|------|------|------|------|
| 1 | `/start` | 所有 | — | `/start` |
| 2 | `/help` | 所有 | — | `/help` |
| 3 | `/status` | 授权 | — | `/status` |
| 4 | `/jails` | 授权 | — | `/jails` |
| 5 | `/banned` | 授权 | — | `/banned` |
| 6 | `/jail` | 授权 | `<name>` | `/jail sshd` |
| 7 | `/ban` | admin | `<ip>[@jail]` | `/ban 1.2.3.4` |
| 8 | `/unban` | admin | `<ip>` | `/unban 1.2.3.4` |
| 9 | `/install` | admin | — | `/install` |
| 10 | `/uninstall` | admin | — | `/uninstall` |
| 11 | `/update` | admin | — | `/update` |
| 12 | `/reload` | admin | — | `/reload` |
| 13 | `/report` | 授权 | — | `/report` |
| 14 | `/whitelist` | admin | `[add|del] <ip>` | `/whitelist add 1.2.3.4` |
| 15 | `/setnotify` | 授权 | `<on|off>` | `/setnotify off` |
| 16 | `/setschedule` | admin | `daily|weekly|off ...` | `/setschedule daily 08:00` |
| 17 | `/stats` | 授权 | `[days]` | `/stats 7` |
