#!/bin/bash
#
# geoip-update.sh - 更新 MaxMind GeoLite2 Country 数据库
# ─────────────────────────────────────────────────────────────
# 部署后路径: /usr/local/bin/geoip-update.sh
# 数据库路径: /var/lib/GeoIP/GeoLite2-Country.mmdb
#
# 功能:
#   - 从 MaxMind 官方下载 GeoLite2-Country 数据库 (需 License Key)
#   - 或从 P3TERX 公益镜像下载 (无需 Key，--mirror)
#   - 下载前自动备份旧库
#   - 支持 --cron 一键注册每周自动更新
#
# 关于 MaxMind License Key:
#   GeoLite2 数据库免费，但需注册 MaxMind 账号并创建 License Key:
#     1. 打开 https://www.maxmind.com/ 注册免费账号
#     2. 登录后进入 Account → Services → My License Key
#     3. 点击 "Generate new license key"，复制 Key
#     4. 通过环境变量或密钥文件提供本脚本:
#          export GEOIP_LICENSE_KEY="你的KEY"
#        或写入文件: echo "你的KEY" > /etc/f2b-manager/geoip.key
#
# 用法:
#   sudo bash geoip-update.sh                使用环境变量/密钥文件中的 License Key 更新
#   sudo bash geoip-update.sh --mirror       使用 P3TERX 镜像 (无需 Key)
#   sudo bash geoip-update.sh --setup        仅输出如何配置 + 注册每周 cron
#   sudo bash geoip-update.sh --cron         注册每周自动更新 (crontab)
#   sudo bash geoip-update.sh --help         查看帮助
#
set -uo pipefail

GEOIP_DIR="/var/lib/GeoIP"
DB_NAME="GeoLite2-Country.mmdb"
DB_PATH="${GEOIP_DIR}/${DB_NAME}"
TMP_DIR="$(mktemp -d)"
ARCHIVE="${TMP_DIR}/geo.tar.gz"
LICENSE_KEY="${GEOIP_LICENSE_KEY:-}"
KEY_FILE="${GEOIP_KEY_FILE:-/etc/f2b-manager/geoip.key}"

MODE="official"   # official | mirror
SETUP_ONLY=0
INSTALL_CRON=0

# ── 颜色 ─────────────────────────────────────────────────
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

cleanup() { rm -rf "$TMP_DIR" 2>/dev/null || true; }
trap cleanup EXIT

# ── 参数解析 ─────────────────────────────────────────────
for a in "$@"; do
    case "$a" in
        --mirror) MODE="mirror" ;;
        --setup) SETUP_ONLY=1 ;;
        --cron) INSTALL_CRON=1 ;;
        --help|-h) echo "用法: sudo bash geoip-update.sh [--mirror|--setup|--cron]"; exit 0 ;;
        *) err "未知参数: $a"; exit 1 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    err "请使用 root 权限运行: sudo bash geoip-update.sh"
    exit 1
fi

# ── 仅打印配置说明 ──────────────────────────────────────
if [ "$SETUP_ONLY" -eq 1 ]; then
    echo -e "${C_BOLD}GeoIP 数据库配置说明${C_RESET}"
    echo
    echo "1) 获取 MaxMind License Key:"
    echo "   https://www.maxmind.com/ 注册 → Account → My License Key → Generate"
    echo
    echo "2) 提供 Key 的方式 (任选其一):"
    echo "   a) 环境变量:  export GEOIP_LICENSE_KEY=\"你的KEY\""
    echo "   b) 密钥文件:   echo \"你的KEY\" > /etc/f2b-manager/geoip.key"
    echo
    echo "3) 执行更新:  sudo bash geoip-update.sh"
    echo "   或使用镜像: sudo bash geoip-update.sh --mirror  (无需 Key)"
    echo
    echo "4) 注册每周自动更新:  sudo bash geoip-update.sh --cron"
    echo
    echo "config.yaml 中需确保:"
    echo "  notify.geoip.enabled: true"
    echo "  notify.geoip.method: local"
    echo "  notify.geoip.db_path: /var/lib/GeoIP/GeoLite2-Country.mmdb"
    exit 0
fi

# ── 注册 cron ───────────────────────────────────────────
if [ "$INSTALL_CRON" -eq 1 ]; then
    CRON_LINE="0 3 * * 0 /usr/local/bin/geoip-update.sh >> /var/log/geoip-update.log 2>&1"
    # 确保脚本已部署
    if [ ! -f /usr/local/bin/geoip-update.sh ]; then
        SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
        cp "$SRC" /usr/local/bin/geoip-update.sh 2>/dev/null || cp "${BASH_SOURCE[0]}" /usr/local/bin/geoip-update.sh
        chmod 755 /usr/local/bin/geoip-update.sh
        ok "已部署: /usr/local/bin/geoip-update.sh"
    fi
    if command -v crontab >/dev/null 2>&1; then
        ( crontab -l 2>/dev/null | grep -v "geoip-update.sh"; echo "$CRON_LINE" ) | crontab -
        ok "已注册每周日 03:00 自动更新 (crontab)"
        echo "   日志: /var/log/geoip-update.log"
    else
        err "未检测到 crontab 命令，请手动添加: $CRON_LINE"
        exit 1
    fi
    exit 0
fi

# ── 准备目录 ────────────────────────────────────────────
mkdir -p "$GEOIP_DIR"

# ── 备份旧库 ────────────────────────────────────────────
if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "${DB_PATH}.bak.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
    log "已备份旧数据库"
fi

# ── 下载 ────────────────────────────────────────────────
download_official() {
    # 读 Key: 环境变量优先，其次密钥文件
    if [ -z "$LICENSE_KEY" ] && [ -f "$KEY_FILE" ]; then
        LICENSE_KEY="$(head -n1 "$KEY_FILE" | tr -d '[:space:]')"
    fi
    if [ -z "$LICENSE_KEY" ]; then
        err "未提供 MaxMind License Key。"
        echo "  请先执行: sudo bash geoip-update.sh --setup  查看获取方式"
        echo "  或临时指定: sudo GEOIP_LICENSE_KEY=你的KEY bash geoip-update.sh"
        return 1
    fi
    local url="https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country&license_key=${LICENSE_KEY}&suffix=tar.gz"
    log "从 MaxMind 官方下载 GeoLite2-Country..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$ARCHIVE" || return 1
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$ARCHIVE" "$url" || return 1
    else
        err "未找到 curl 或 wget"; return 1
    fi
    return 0
}

download_mirror() {
    # P3TERX 公益镜像 (无需 Key，更新略滞后)
    local url="https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
    log "从 P3TERX 镜像下载 GeoLite2-Country.mmdb..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$DB_PATH" || return 1
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$DB_PATH" "$url" || return 1
    else
        err "未找到 curl 或 wget"; return 1
    fi
    # 镜像直接给出 mmdb，无需解压
    if [ -s "$DB_PATH" ]; then
        chmod 644 "$DB_PATH"
        ok "GeoIP 数据库已更新: $DB_PATH"
        return 0
    fi
    return 1
}

if [ "$MODE" = "mirror" ]; then
    if download_mirror; then
        echo -e "${C_GREEN}${C_BOLD}✅ GeoIP 数据库更新完成 (镜像)${C_RESET}"
        exit 0
    else
        err "镜像下载失败"
        exit 1
    fi
fi

# 官方模式: 下载 tar.gz 后解压
if ! download_official; then
    err "官方下载失败。可改用镜像: sudo bash geoip-update.sh --mirror"
    exit 1
fi

log "解压数据库..."
tar -xzf "$ARCHIVE" -C "$TMP_DIR" 2>/dev/null || { err "解压失败，文件可能损坏"; exit 1; }
EXTRACTED="$(find "$TMP_DIR" -name "$DB_NAME" | head -n1)"
if [ -z "$EXTRACTED" ] || [ ! -s "$EXTRACTED" ]; then
    err "未找到解压后的数据库文件"
    exit 1
fi

mv "$EXTRACTED" "$DB_PATH"
chmod 644 "$DB_PATH"
ok "GeoIP 数据库已更新: $DB_PATH"

# 清理多余备份 (仅保留最近 3 份)
ls -1t "${DB_PATH}".bak.* 2>/dev/null | tail -n +4 | xargs -r rm -f 2>/dev/null || true

echo -e "${C_GREEN}${C_BOLD}✅ GeoIP 数据库更新完成${C_RESET}"
echo "   路径: $DB_PATH"
echo "   建议注册每周自动更新: sudo bash geoip-update.sh --cron"
