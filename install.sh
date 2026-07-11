#!/bin/bash
#
# f2b-manager 一键安装脚本
# ─────────────────────────────────────────────────────────────
# 部署路径:
#   程序:    /opt/f2b-manager
#   配置:    /etc/f2b-manager/config.yaml   (权限 600)
#   虚拟环境: /opt/f2b-manager/venv
#   服务:    /etc/systemd/system/f2b-manager.service
#   桥接脚本: /usr/local/bin/f2b-notify.sh
#   CLI 包装: /usr/local/bin/f2b-manager
#
# 用法:
#   sudo bash install.sh                交互式安装
#   sudo bash install.sh --no-fail2ban 跳过 fail2ban 安装（已装好时）
#   sudo bash install.sh --help         查看帮助
#
set -euo pipefail

# ── 路径常量 ──────────────────────────────────────────────
INSTALL_DIR="/opt/f2b-manager"
CONFIG_DIR="/etc/f2b-manager"
VENV_DIR="${INSTALL_DIR}/venv"
BIN_DIR="/usr/local/bin"
WRAPPER="${BIN_DIR}/f2b-manager"
NOTIFY_DST="${BIN_DIR}/f2b-notify.sh"
SERVICE_SRC_REL="systemd/f2b-manager.service"
SERVICE_DST="/etc/systemd/system/f2b-manager.service"
CONFIG_SRC_REL="config/config.example.yaml"
CONFIG_DST="${CONFIG_DIR}/config.yaml"

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
SKIP_FAIL2BAN=0
for a in "$@"; do
    case "$a" in
        --no-fail2ban) SKIP_FAIL2BAN=1 ;;
        --help|-h) echo "用法: sudo bash install.sh [--no-fail2ban]"; exit 0 ;;
        *) err "未知参数: $a"; exit 1 ;;
    esac
done

# ── 定位脚本所在目录（兼容 curl|bash 和本地执行）────────
REPO_URL="https://github.com/rl0226-cyber/f2b-manager.git"
CLONED=0

# 尝试获取脚本所在目录（本地执行时有效）
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# 如果脚本目录不存在或目录下没有 f2b_manager/，说明是 curl|bash 模式
# 需要先 git clone 仓库到临时目录
if [ -z "$SCRIPT_DIR" ] || [ ! -d "${SCRIPT_DIR}/f2b_manager" ]; then
    log "检测到远程安装模式，正在下载项目代码..."
    SCRIPT_DIR="/tmp/f2b-manager-install"
    rm -rf "$SCRIPT_DIR"
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 "$REPO_URL" "$SCRIPT_DIR"
        CLONED=1
    else
        # 无 git 时用 curl 下载 tarball
        log "未检测到 git，使用 tarball 下载..."
        curl -fsSL "https://github.com/rl0226-cyber/f2b-manager/archive/refs/heads/main.tar.gz" \
            | tar xz -C /tmp/
        mv /tmp/f2b-manager-main "$SCRIPT_DIR"
    fi
    ok "项目代码已下载到 $SCRIPT_DIR"
fi

echo -e "${C_BOLD}=== f2b-manager 安装程序 ===${C_RESET}"

# ── 0. 运行环境检查 ─────────────────────────────────────
if [ "$(uname -s)" != "Linux" ]; then
    err "本安装脚本仅支持 Linux 系统"
    exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
    err "请使用 root 权限运行: sudo bash install.sh"
    exit 1
fi
ok "运行环境检查通过 (root / Linux)"

# ── 1. Python 3.10+ 检查 ────────────────────────────────
PY_BIN=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PY_BIN="$cand"; break
        fi
    fi
done
if [ -z "$PY_BIN" ]; then
    err "未检测到 Python 3.10+，请先安装 Python 3.10 或更高版本"
    echo "  Debian/Ubuntu: apt-get install -y python3 python3-venv python3-pip"
    echo "  CentOS/RHEL:   dnf install -y python3"
    exit 1
fi
PY_VER="$("$PY_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

# ── 检测包管理器 ─────────────────────────────────────────
PKG_MGR=""
if command -v apt-get >/dev/null 2>&1; then
    PKG_MGR="apt-get"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MGR="dnf"
elif command -v yum >/dev/null 2>&1; then
    PKG_MGR="yum"
elif command -v apk >/dev/null 2>&1; then
    PKG_MGR="apk"
fi

# ── 安装系统依赖的函数 ─────────────────────────────────
install_sys_pkg() {
    local pkgs_apt="$1" pkgs_dnf="$2" pkgs_apk="$3"
    if [ -z "$PKG_MGR" ]; then
        warn "未检测到包管理器，请手动安装: $pkgs_apt"
        return 1
    fi
    log "安装系统依赖: $pkgs_apt (via $PKG_MGR)..."
    case "$PKG_MGR" in
        apt-get) apt-get update -qq && apt-get install -y $pkgs_apt ;;
        dnf|yum) $PKG_MGR install -y $pkgs_dnf ;;
        apk)     apk add --no-cache $pkgs_apk ;;
    esac
}

# ── 自动安装系统依赖 ─────────────────────────────────────
# git (提前安装，远程模式需要)
if ! command -v git >/dev/null 2>&1; then
    warn "git 不可用，尝试自动安装..."
    if install_sys_pkg "git" "git" "git"; then
        ok "git 安装成功"
    else
        warn "git 安装失败，部分功能可能受限"
    fi
fi

ok "Python 版本检查通过: $PY_VER ($PY_BIN)"

# ── 2. 创建目录 ─────────────────────────────────────────
log "创建目录: $INSTALL_DIR / $CONFIG_DIR"
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
ok "目录已创建"

# ── 3. 复制程序文件 ─────────────────────────────────────
log "复制程序文件到 $INSTALL_DIR"
cp -r "${SCRIPT_DIR}/f2b_manager" "${INSTALL_DIR}/"
cp "${SCRIPT_DIR}/pyproject.toml" "${SCRIPT_DIR}/requirements.txt" "${INSTALL_DIR}/"
ok "程序文件已复制"

# ── 4. 创建虚拟环境并安装依赖 ─────────────────────────
# 尝试创建 venv，失败时自动安装 python3-venv 后重试
create_venv() {
    "$PY_BIN" -m venv "$VENV_DIR" 2>/dev/null
}

if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/pip" ]; then
    rm -rf "$VENV_DIR"
    log "创建虚拟环境: $VENV_DIR"
    if create_venv; then
        ok "虚拟环境创建成功"
    else
        # venv 创建失败，通常是缺少 python3-venv / ensurepip
        warn "虚拟环境创建失败，自动安装 python3-venv..."
        # 根据版本号确定包名 (如 python3.11-venv)
        PY_MAJOR_MINOR="$("$PY_BIN" -c 'import sys; print(f"python{sys.version_info[0]}.{sys.version_info[1]}")')"
        if install_sys_pkg "${PY_MAJOR_MINOR}-venv python3-pip" "python3-virtualenv python3-pip" "py3-virtualenv py3-pip"; then
            ok "python3-venv 安装成功，重试创建虚拟环境..."
            rm -rf "$VENV_DIR"
            if create_venv; then
                ok "虚拟环境创建成功"
            else
                err "虚拟环境创建仍然失败，请手动运行: apt install ${PY_MAJOR_MINOR}-venv"
                exit 1
            fi
        else
            err "python3-venv 安装失败，请手动安装后重试"
            echo "  Debian/Ubuntu: apt-get install -y ${PY_MAJOR_MINOR}-venv python3-pip"
            echo "  CentOS/RHEL:   dnf install -y python3-virtualenv"
            exit 1
        fi
    fi
else
    log "虚拟环境已存在，复用: $VENV_DIR"
fi
log "升级 pip..."
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null 2>&1 \
    || warn "pip 升级失败（不影响后续安装）"
log "安装 Python 依赖 (可能需要几分钟，请稍候)..."
"$VENV_DIR/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"
ok "依赖安装完成"

# ── 5. 创建 CLI 包装器 ─────────────────────────────────
log "创建 CLI 包装器: $WRAPPER"
cat > "$WRAPPER" <<'EOF'
#!/bin/bash
# f2b-manager CLI 包装器
# 设置 PYTHONPATH 使 f2b_manager 包可被导入，再调用主程序
export PYTHONPATH="/opt/f2b-manager:${PYTHONPATH:-}"
# 无参数时默认打开管理菜单
if [ $# -eq 0 ]; then
    set -- menu
fi
exec /opt/f2b-manager/venv/bin/python -m f2b_manager "$@"
EOF
chmod 755 "$WRAPPER"
ok "CLI 包装器已创建"

# ── 6. 部署配置文件 ─────────────────────────────────────
if [ ! -f "$CONFIG_DST" ]; then
    log "生成配置文件: $CONFIG_DST (从模板复制)"
    cp "${SCRIPT_DIR}/${CONFIG_SRC_REL}" "$CONFIG_DST"
    chmod 600 "$CONFIG_DST"
    warn "配置文件已生成，请先编辑 $CONFIG_DST 填入 bot_token 后再启动服务"
else
    log "配置文件已存在，跳过生成: $CONFIG_DST"
fi

# ── 7. 安装并配置 fail2ban ─────────────────────────────
if [ "$SKIP_FAIL2BAN" -eq 1 ]; then
    log "跳过 fail2ban 安装 (--no-fail2ban)"
else
    log "安装并配置 fail2ban (f2b-manager fail2ban install)..."
    if "$WRAPPER" fail2ban install; then
        ok "fail2ban 安装完成"
    else
        warn "fail2ban 安装失败，可稍后通过 Telegram /install 或手动安装后重试"
    fi
fi

# ── 8. 部署 systemd 服务 ───────────────────────────────
log "部署 systemd 服务"
if [ -f "${SCRIPT_DIR}/${SERVICE_SRC_REL}" ]; then
    cp "${SCRIPT_DIR}/${SERVICE_SRC_REL}" "$SERVICE_DST"
    chmod 644 "$SERVICE_DST"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
        systemctl enable f2b-manager >/dev/null 2>&1 \
            || warn "systemctl enable 失败（非 systemd 环境？）"
        ok "systemd 服务已部署并设为开机自启"
    else
        warn "未检测到 systemctl，跳过服务注册（请手动管理进程）"
    fi
else
    err "未找到 systemd 服务文件: ${SCRIPT_DIR}/${SERVICE_SRC_REL}"
fi

# ── 9. 部署 notify 桥接脚本 ────────────────────────────
log "部署 notify 桥接脚本: $NOTIFY_DST"
if [ -f "${SCRIPT_DIR}/scripts/f2b-notify.sh" ]; then
    cp "${SCRIPT_DIR}/scripts/f2b-notify.sh" "$NOTIFY_DST"
    chmod 755 "$NOTIFY_DST"
    ok "notify 脚本已部署"
else
    err "未找到 scripts/f2b-notify.sh"
fi

# ── 创建 f2b 快捷指令 ─────────────────────────────────
log "部署 f2b 快捷指令"
ln -sf "$WRAPPER" /usr/local/bin/f2b
ok "快捷指令已创建：输入 f2b 即可启动管理菜单"

# ── 完成 ───────────────────────────────────────────────
echo
echo -e "${C_GREEN}${C_BOLD}✅ f2b-manager 安装完成！${C_RESET}"
echo

# ── 启动配置向导 ───────────────────────────────────────
log "启动配置向导..."
"$WRAPPER" menu || warn "菜单启动失败，可稍后运行 f2b 命令"

echo
echo -e "${C_GREEN}配置完成！${C_RESET}"
echo -e "启动服务: ${C_YELLOW}systemctl start f2b-manager${C_RESET}"
echo -e "查看日志: ${C_YELLOW}journalctl -u f2b-manager -f${C_RESET}"
echo -e "再次打开菜单: ${C_YELLOW}f2b${C_RESET}"
echo
echo "如需使用 IP 归属地功能，请运行: f2b 然后选择相关选项"
echo "如需卸载，请运行: bash /opt/f2b-manager/uninstall.sh"

# ── 清理临时下载目录 ───────────────────────────────────
if [ "$CLONED" -eq 1 ] && [ -d "$SCRIPT_DIR" ]; then
    rm -rf "$SCRIPT_DIR"
fi
