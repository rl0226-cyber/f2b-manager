#!/bin/bash
#
# f2b-manager 卸载脚本
# ─────────────────────────────────────────────────────────────
# 流程:
#   1. 停止并禁用 f2b-manager systemd 服务
#   2. 删除 systemd 服务文件
#   3. 删除程序目录 /opt/f2b-manager (交互确认)
#   4. 删除 CLI 包装器 /usr/local/bin/f2b-manager 与桥接脚本
#   5. 交互选择是否删除配置目录 /etc/f2b-manager (默认保留)
#   6. 交互选择是否删除状态库与日志 (默认保留)
#
# 说明:
#   - 本脚本只卸载 f2b-manager 自身，不会卸载 fail2ban。
#     如需卸载 fail2ban，请在 Telegram 中执行 /uninstall，
#     或手动执行: f2b-manager fail2ban uninstall
#
# 用法:
#   sudo bash uninstall.sh        交互式卸载
#   sudo bash uninstall.sh -y     全部使用默认(保留配置)自动确认
#   sudo bash uninstall.sh --help 查看帮助
#
set -uo pipefail

# ── 路径常量 ──────────────────────────────────────────────
INSTALL_DIR="/opt/f2b-manager"
CONFIG_DIR="/etc/f2b-manager"
BIN_DIR="/usr/local/bin"
WRAPPER="${BIN_DIR}/f2b-manager"
NOTIFY_DST="${BIN_DIR}/f2b-notify.sh"
SERVICE_DST="/etc/systemd/system/f2b-manager.service"
STATE_DIR="/var/lib/f2b-manager"
LOG_FILE="/var/log/f2b-manager.log"

# ── 颜色输出 ─────────────────────────────────────────────
if [ -t 1 ]; then
    C_RED='\033[0;31m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'
    C_CYAN='\033[0;36m'; C_BOLD='\033[1m'; C_RESET='\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_BOLD=''; C_RESET=''
fi

log()  { echo -e "${C_CYAN}[INFO]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARN]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }
ok()   { echo -e "${C_GREEN}[ OK ]${C_RESET} $*"; }

# ── 参数解析 ─────────────────────────────────────────────
FORCE=0
for a in "$@"; do
    case "$a" in
        -y|--yes) FORCE=1 ;;
        --help|-h) echo "用法: sudo bash uninstall.sh [-y]"; exit 0 ;;
        *) err "未知参数: $a"; exit 1 ;;
    esac
done

echo -e "${C_BOLD}=== f2b-manager 卸载程序 ===${C_RESET}"

if [ "$(id -u)" -ne 0 ]; then
    err "请使用 root 权限运行: sudo bash uninstall.sh"
    exit 1
fi

# 交互确认函数: 默认 No（除非 -y）
confirm() {
    if [ "$FORCE" -eq 1 ]; then return 0; fi
    local ans
    read -r -p "$1 [y/N] " ans
    case "$ans" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

# ── 1. 停止并禁用服务 ───────────────────────────────────
log "停止 f2b-manager 服务..."
if command -v systemctl >/dev/null 2>&1; then
    systemctl stop f2b-manager 2>/dev/null && ok "服务已停止" \
        || warn "服务未运行或无法停止（可能尚未安装）"
    systemctl disable f2b-manager 2>/dev/null && ok "服务已禁用" \
        || warn "服务未启用，跳过 disable"
else
    # 非 systemd: 尝试通过 pidof / pkill 停止
    pkill -f "python -m f2b_manager" 2>/dev/null && ok "已尝试终止运行中的进程" \
        || warn "未发现运行中的进程"
fi

# ── 2. 删除 systemd 服务文件 ────────────────────────────
if [ -f "$SERVICE_DST" ]; then
    rm -f "$SERVICE_DST"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload 2>/dev/null || true
    fi
    ok "已删除 systemd 服务文件: $SERVICE_DST"
else
    log "服务文件不存在 (跳过): $SERVICE_DST"
fi

# ── 3. 删除程序目录 ─────────────────────────────────────
if [ -d "$INSTALL_DIR" ]; then
    if confirm "确认删除程序目录 $INSTALL_DIR ?"; then
        rm -rf "$INSTALL_DIR"
        ok "已删除: $INSTALL_DIR"
    else
        warn "已保留: $INSTALL_DIR"
    fi
else
    log "程序目录不存在 (跳过): $INSTALL_DIR"
fi

# ── 4. 删除 CLI 包装器与桥接脚本 ───────────────────────
[ -f "$WRAPPER" ] && rm -f "$WRAPPER" && ok "已删除: $WRAPPER"
[ -f "$NOTIFY_DST" ] && rm -f "$NOTIFY_DST" && ok "已删除: $NOTIFY_DST"
# 旧版兼容：删除可能存在的 python 软链接
[ -L "${BIN_DIR}/f2b-manager-python" ] && rm -f "${BIN_DIR}/f2b-manager-python"

# ── 5. 配置文件 ─────────────────────────────────────────
if [ -d "$CONFIG_DIR" ]; then
    if confirm "是否删除配置目录 $CONFIG_DIR (含 config.yaml) ? 选 N 可保留配置以便日后重装"; then
        # 删除前先备份，防误操作
        BACKUP="${CONFIG_DIR}.backup.$(date +%Y%m%d%H%M%S)"
        cp -r "$CONFIG_DIR" "$BACKUP" 2>/dev/null || true
        rm -rf "$CONFIG_DIR"
        ok "已删除配置目录 (备份位于: $BACKUP)"
    else
        warn "已保留配置目录: $CONFIG_DIR"
    fi
fi

# ── 6. 状态库与日志（可选）─────────────────────────────
if [ -d "$STATE_DIR" ] || [ -f "$LOG_FILE" ]; then
    if confirm "是否同时删除状态库 ($STATE_DIR) 和日志 ($LOG_FILE) ? 选 N 可保留历史数据"; then
        [ -d "$STATE_DIR" ] && rm -rf "$STATE_DIR"
        [ -f "$LOG_FILE" ] && rm -f "$LOG_FILE"
        ok "已删除状态库与日志"
    else
        warn "已保留状态库与日志"
    fi
fi

echo
echo -e "${C_GREEN}${C_BOLD}✅ 卸载完成。${C_RESET}"
echo
echo "提示: fail2ban 服务仍由系统管理，未受影响。"
echo "      如需卸载 fail2ban，请执行: f2b-manager fail2ban uninstall"
