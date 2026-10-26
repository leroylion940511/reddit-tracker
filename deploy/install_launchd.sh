#!/usr/bin/env bash
# Install / reload / uninstall reddit_tracker launchd agents on macOS.
#
# 用法:
#   deploy/install_launchd.sh newsroom-reload  # 重載收集＋綜合日報 scheduler
#   deploy/install_launchd.sh newsroom-deploy  # 備份 SQLite、migration 後重載 scheduler
#   deploy/install_launchd.sh newsroom-uninstall
#   deploy/install_launchd.sh legacy-uninstall  # 停止並移除已退役的 v4 scheduler／Telegram bot
#   deploy/install_launchd.sh rsshub-install    # 安裝/重載本機 RSSHub（只綁 127.0.0.1）
#   deploy/install_launchd.sh rsshub-uninstall  # 停止 + 移除本機 RSSHub
#   deploy/install_launchd.sh status     # 查看是否在跑
#
# 設計理由 (為何要 launchd 而非 nohup): 看任一支 plist 開頭的註解

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
USER_AGENTS="$HOME/Library/LaunchAgents"
# 已退役，只保留給 legacy-uninstall 清掉舊 LaunchAgent。
LEGACY_LABELS=(
    com.leroy.reddit-tracker.scheduler
    com.leroy.reddit-tracker.bot
)
NEWSROOM_LABELS=(
    com.leroy.reddit-tracker.newsroom
)
RSSHUB_LABEL=com.leroy.reddit-tracker.rsshub
UID_NUM="$(id -u)"

cmd="${1:-status}"

_kill_matching() {
    # 收掉同一種舊的 nohup / 前景 Python process，避免重載後重複排程。不可同時 kill uv/caffeinate wrapper：它們與 Python
    # 子程序各送一次 SIGTERM 會讓 scheduler 的 signal handler 重入。
    local pattern="$1"
    local candidates pids pid executable
    candidates="$(pgrep -f "$pattern" || true)"
    pids=""
    for pid in $candidates; do
        executable="$(ps -o comm= -p "$pid" 2>/dev/null || true)"
        case "$executable" in
            *python|*python[0-9]*)
                pids+="${pids:+ }$pid"
                ;;
        esac
    done
    if [[ -n "$pids" ]]; then
        echo "→ killing orphaned reddit_tracker Python processes: $pids"
        echo "$pids" | xargs kill 2>/dev/null || true
        sleep 1
        # 還賴著才 SIGKILL；再次只取 Python child，不碰 launchd wrapper。
        candidates="$(pgrep -f "$pattern" || true)"
        pids=""
        for pid in $candidates; do
            executable="$(ps -o comm= -p "$pid" 2>/dev/null || true)"
            case "$executable" in
                *python|*python[0-9]*)
                    pids+="${pids:+ }$pid"
                    ;;
            esac
        done
        [[ -n "$pids" ]] && echo "$pids" | xargs kill -9 2>/dev/null || true
    fi
}

_quiesce_loaded() {
    # Stop launchd before killing a child.  KeepAlive=true would otherwise
    # race with pgrep/kill and briefly start a second scheduler, which can
    # duplicate the first RSS discovery request after a reload.
    local label
    for label in "$@"; do
        launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    done
    sleep 1
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
    # bootout 與 bootstrap 間留 buffer: launchd 對同 label 連續操作偶爾會回
    # `Bootstrap failed: 5: Input/output error` (ratelimit), sleep 2 後穩定
    sleep 2
    # A disabled LaunchAgent must be enabled before bootstrap.  The reverse
    # order leaves it unloaded on current macOS launchd.
    launchctl enable "gui/$UID_NUM/$label"
    launchctl bootstrap "gui/$UID_NUM" "$dst"
    echo "✓ installed $label"
}

_uninstall_one() {
    local label="$1"
    local dst="$USER_AGENTS/${label}.plist"
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    [[ -f "$dst" ]] && rm "$dst" && echo "✓ removed $dst"
}

case "$cmd" in
    legacy-uninstall)
        # v4 scheduler and the Telegram bot were removed from the codebase.
        for l in "${LEGACY_LABELS[@]}"; do _uninstall_one "$l"; done
        _kill_matching "python.*-m reddit_tracker\.(scheduler|bot)"
        ;;
    newsroom-install|newsroom-reload)
        # launchd bootout occasionally leaves a caffeinate/uv child orphaned;
        # kill it so there is never a duplicate scheduler.
        _quiesce_loaded "${NEWSROOM_LABELS[@]}"
        _kill_matching "python.*-m reddit_tracker\.newsroom\.scheduler"
        for l in "${NEWSROOM_LABELS[@]}"; do _install_one "$l"; done
        ;;
    newsroom-deploy)
        # Upgrade before stopping the old service.  If backup or migration
        # fails, the currently running newsroom keeps serving its old schema.
        (
            cd "$PROJECT_ROOT"
            uv run python -m reddit_tracker.newsroom.deploy
            uv run python -m alembic upgrade head
        )
        _quiesce_loaded "${NEWSROOM_LABELS[@]}"
        _kill_matching "python.*-m reddit_tracker\.newsroom\.scheduler"
        for l in "${NEWSROOM_LABELS[@]}"; do _install_one "$l"; done
        ;;
    newsroom-uninstall)
        for l in "${NEWSROOM_LABELS[@]}"; do _uninstall_one "$l"; done
        ;;
    rsshub-install|rsshub-reload)
        [[ -f "$HOME/rsshub/dist/index.mjs" ]] || { echo "ERROR: ~/rsshub 尚未 build"; exit 1; }
        grep -q '^ACCESS_KEY=.' "$HOME/rsshub/.env" || { echo "ERROR: ~/rsshub/.env 缺 ACCESS_KEY"; exit 1; }
        _install_one "$RSSHUB_LABEL"
        ;;
    rsshub-uninstall)
        _uninstall_one "$RSSHUB_LABEL"
        ;;
    status)
        echo "=== launchctl list (僅 reddit-tracker) ==="
        launchctl list | grep -E "reddit-tracker" || echo "(沒有 service 在跑)"
        echo
        echo "=== process tree ==="
        pgrep -lf "python.*reddit_tracker\.newsroom\.scheduler" || echo "(沒有 python process)"
        lsof -nP -iTCP:1200 -sTCP:LISTEN 2>/dev/null | tail -n +2 || true
        echo
        echo "=== log mtime (越接近 now 越好) ==="
        for f in newsroom.log; do
            [[ -f "$f" ]] && stat -f "%N: mtime=%Sm size=%z" "$f"
        done
        ;;
    *)
        echo "用法: $0 {newsroom-install|newsroom-reload|newsroom-deploy|newsroom-uninstall|legacy-uninstall|rsshub-install|rsshub-uninstall|status}"
        exit 1
        ;;
esac
