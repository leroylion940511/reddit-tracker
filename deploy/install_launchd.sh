#!/usr/bin/env bash
# Install / reload / uninstall reddit_tracker launchd agents on macOS.
#
# 用法:
#   deploy/install_launchd.sh install    # 第一次安裝 + 啟動
#   deploy/install_launchd.sh reload     # 改完 plist 後重新載入
#   deploy/install_launchd.sh uninstall  # 停止 + 移除
#   deploy/install_launchd.sh status     # 查看是否在跑
#
# 設計理由 (為何要 launchd 而非 nohup): 看任一支 plist 開頭的註解

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.leroy.reddit-tracker.scheduler com.leroy.reddit-tracker.bot)
UID_NUM="$(id -u)"

cmd="${1:-status}"

_kill_legacy() {
    # 把之前 nohup / 前景跑的 process 收掉, 避免 telegram bot 雙開搶 long polling
    local pids
    pids="$(pgrep -f "python.*-m reddit_tracker\.(scheduler|bot)" || true)"
    if [[ -n "$pids" ]]; then
        echo "→ killing legacy reddit_tracker processes: $pids"
        echo "$pids" | xargs kill 2>/dev/null || true
        sleep 1
        # 還賴著就 SIGKILL
        pids="$(pgrep -f "python.*-m reddit_tracker\.(scheduler|bot)" || true)"
        [[ -n "$pids" ]] && echo "$pids" | xargs kill -9 2>/dev/null || true
    fi
}

_install_one() {
    local label="$1"
    local src="$SCRIPT_DIR/${label}.plist"
    local dst="$USER_AGENTS/${label}.plist"
    [[ -f "$src" ]] || { echo "ERROR: 找不到 $src"; exit 1; }

    mkdir -p "$USER_AGENTS"
    cp "$src" "$dst"
    # 已經載入過就先 bootout (idempotent install)
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_NUM" "$dst"
    launchctl enable "gui/$UID_NUM/$label"
    echo "✓ installed $label"
}

_uninstall_one() {
    local label="$1"
    local dst="$USER_AGENTS/${label}.plist"
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    [[ -f "$dst" ]] && rm "$dst" && echo "✓ removed $dst"
}

case "$cmd" in
    install)
        _kill_legacy
        for l in "${LABELS[@]}"; do _install_one "$l"; done
        echo
        echo "完成. 用以下指令查狀態 / log:"
        echo "  deploy/install_launchd.sh status"
        echo "  tail -f scheduler.log bot.log"
        ;;
    reload)
        for l in "${LABELS[@]}"; do _install_one "$l"; done
        ;;
    uninstall)
        for l in "${LABELS[@]}"; do _uninstall_one "$l"; done
        ;;
    status)
        echo "=== launchctl list (僅 reddit-tracker) ==="
        launchctl list | grep -E "reddit-tracker" || echo "(沒有 service 在跑)"
        echo
        echo "=== process tree ==="
        pgrep -lf "python.*reddit_tracker\.(scheduler|bot)" || echo "(沒有 python process)"
        echo
        echo "=== log mtime (越接近 now 越好) ==="
        for f in scheduler.log bot.log; do
            [[ -f "$f" ]] && stat -f "%N: mtime=%Sm size=%z" "$f"
        done
        ;;
    *)
        echo "用法: $0 {install|reload|uninstall|status}"
        exit 1
        ;;
esac
