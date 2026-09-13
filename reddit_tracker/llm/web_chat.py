"""零 API-key 的已登入網頁 LLM provider。

靈感來自 `teddashh/multi-ai-chat-desktop` 的核心設計：不呼叫供應商 API，
而是讓使用者自己登入官方網頁後，透過 provider-specific DOM adapter 傳送提示
詞並讀取回答。本實作刻意收斂為 Reddit Tracker 需要的同步單一 provider：

* 只接受 loopback Chrome DevTools endpoint，拒絕遠端 CDP；
* 不管理登入、不讀取 cookie 或 credential、不嘗試繞過使用限制／CAPTCHA；
* 一次只跑一個請求（thread + process lock），避免 scheduler 與 Telegram bot
  搶同一個網頁輸入框；
* 支援免費可用的 ChatGPT 與 Gemini 已登入分頁。服務商的 free-plan quota 與
  條款仍然適用，配額耗盡時將明確 raise，由既有 pipeline 記錄失敗。

Chrome 的 remote-debugging port 必須由使用者在本機啟動；此模組絕不自行開啟
瀏覽器或登入頁面，避免意外建立未受控的帳號／profile 狀態。
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

import requests
import websocket

from ..models import CandidatePost
from .base import HaikuVerdict, LLMScorer
from .haiku import SYSTEM_PROMPT, build_user_prompt, parse_haiku_response, verdict_from_payload
from .minimax_chat import ChatClient, ChatResult

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_THREAD_LOCK = threading.Lock()
_CHATGPT_UI_PREFIX_RE = re.compile(r"^ChatGPT\s*(?:說|said)\s*[:：]\s*", re.IGNORECASE)


class WebSessionError(RuntimeError):
    """使用者可處理的 browser-session 問題（未登入、selector 更新、配額等）。"""


@dataclass(frozen=True)
class WebAdapter:
    """供應商 DOM adapter；selector 與參考專案的 adapter config 對齊。"""

    provider: str
    hosts: tuple[str, ...]
    input_selectors: tuple[str, ...]
    send_button_selectors: tuple[str, ...]
    response_selectors: tuple[str, ...]
    thinking_selectors: tuple[str, ...]
    logged_out_selectors: tuple[str, ...] = ()


ADAPTERS: dict[str, WebAdapter] = {
    "chatgpt": WebAdapter(
        provider="chatgpt",
        hosts=("chatgpt.com", "chat.openai.com"),
        input_selectors=(
            "#mobile-composer-prompt",
            "#prompt-textarea",
            '[id="prompt-textarea"]',
            'textarea[aria-label="與 ChatGPT 對話"]',
            'div[contenteditable="true"][data-placeholder]',
        ),
        send_button_selectors=(
            '[data-testid="send-button"]',
            'button[aria-label="Send prompt"]',
            'button[aria-label="Send message"]',
            'button[aria-label="傳送訊息"]',
            'button[aria-label="Send"]',
        ),
        response_selectors=(
            '[data-message-author-role="assistant"] .markdown',
            '[data-message-author-role="assistant"]',
            # ChatGPT 152 desktop/mobile composer（繁中/英文 UI）；使用含 assistant
            # action 的 turn，而不是 action button 本身，才能取到回覆文字。
            'li._wdUoQG_messageTurn:has(._wdUoQG_assistantMessageActions)',
            'li:has(button[aria-label="複製回應"])',
            'li:has(button[aria-label="Copy response"])',
        ),
        thinking_selectors=(
            '[data-testid="stop-button"]',
            'button[aria-label="Stop generating"]',
            'button[aria-label="Stop streaming"]',
            'button[aria-label="Stop"]',
        ),
        logged_out_selectors=(
            '[data-testid="login-button"]',
            '[data-testid="signup-button"]',
            '[data-testid="login-form"]',
        ),
    ),
    "gemini": WebAdapter(
        provider="gemini",
        hosts=("gemini.google.com",),
        input_selectors=(
            '.ql-editor[contenteditable="true"]',
            "rich-textarea .ql-editor",
            'div[contenteditable="true"][aria-label="Enter a prompt here"]',
            'div[contenteditable="true"][aria-label]',
            '.input-area [contenteditable="true"]',
            'rich-textarea [contenteditable="true"]',
        ),
        send_button_selectors=(
            "button.send-button",
            'button[aria-label="Send message"]',
            'button[aria-label="Send"]',
            'button[aria-label="傳送訊息"]',
            'button[aria-label="送出"]',
            'button[data-mat-icon-name="send"]',
            ".send-button-container button",
            "button mat-icon[data-mat-icon-name=\"send\"]",
        ),
        response_selectors=(
            ".model-response-text .markdown",
            ".model-response-text",
            "model-response .markdown",
            "model-response message-content",
            ".response-content .markdown",
            ".message-content[data-message-id]",
        ),
        thinking_selectors=(
            ".loading-indicator",
            ".thinking-indicator",
            "mat-progress-bar",
            'button[aria-label="Stop response"]',
            'button[aria-label="Stop"]',
            'button[aria-label="停止回應"]',
            ".response-streaming",
            '[data-test-id="response-loading"]',
        ),
    ),
}


def _is_loopback_url(url: str, *, schemes: set[str]) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme in schemes and (parsed.hostname or "").lower() in _LOOPBACK_HOSTS


def _adapter_for(provider: str) -> WebAdapter:
    try:
        return ADAPTERS[provider.lower().strip()]
    except KeyError as exc:
        options = ", ".join(sorted(ADAPTERS))
        raise ValueError(f"WEB_LLM_PROVIDER must be one of: {options}") from exc


def _clean_response_text(text: str) -> str:
    """移除新版 ChatGPT turn container 自帶的展示標籤，不碰模型正文。"""
    return _CHATGPT_UI_PREFIX_RE.sub("", text.strip())


@contextlib.contextmanager
def _process_lock(path: str) -> Iterator[None]:
    """在 macOS launchd 的兩個 process 之間序列化同一個網頁分頁。"""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - 專案部署目標為 macOS
        yield
        return

    lock_file = Path(path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class WebSessionChat(ChatClient):
    """透過一個使用者已登入的 ChatGPT/Gemini 分頁完成同步請求。"""

    provider = "web_session"

    def __init__(
        self,
        *,
        provider: str = "chatgpt",
        cdp_url: str = "http://127.0.0.1:9222",
        timeout: float = 180.0,
        poll_interval: float = 1.0,
        settle_seconds: float = 3.0,
        lock_path: str = "/tmp/reddit-tracker-web-llm.lock",
    ) -> None:
        if not _is_loopback_url(cdp_url, schemes={"http", "https"}):
            raise ValueError("WEB_LLM_CDP_URL must be an http(s) loopback URL")
        if timeout <= 0 or poll_interval <= 0 or settle_seconds < 0:
            raise ValueError("web LLM timeout/poll/settle values must be positive")
        self.adapter = _adapter_for(provider)
        self.cdp_url = cdp_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.settle_seconds = settle_seconds
        self.lock_path = lock_path
        self.provider = f"web_{self.adapter.provider}"
        self.model = f"{self.adapter.provider}-web-session"

    def _find_tab_ws_url(self) -> str:
        try:
            response = requests.get(f"{self.cdp_url}/json/list", timeout=5)
            response.raise_for_status()
            tabs = response.json()
        except requests.RequestException as exc:
            raise WebSessionError(
                "Chrome DevTools 無法連線。請以 --remote-debugging-port=9222 啟動 Chrome，"
                "並在獨立 profile 手動登入 LLM 網頁。"
            ) from exc
        except ValueError as exc:
            raise WebSessionError("Chrome DevTools 回傳非預期 JSON") from exc

        for tab in tabs:
            page_url = str(tab.get("url", ""))
            host = (urlsplit(page_url).hostname or "").lower()
            if tab.get("type") != "page" or not any(host == h or host.endswith(f".{h}") for h in self.adapter.hosts):
                continue
            ws_url = str(tab.get("webSocketDebuggerUrl", ""))
            if _is_loopback_url(ws_url, schemes={"ws", "wss"}):
                return ws_url
        names = " / ".join(self.adapter.hosts)
        raise WebSessionError(f"找不到已開啟的 {names} 分頁；請先在 Chrome 手動登入並保持該分頁開啟")

    def _evaluate(self, ws_url: str, expression: str) -> Any:
        """執行單一 CDP Runtime.evaluate；只接受 CDP 回傳的 by-value 資料。"""
        request_id = 1
        ws: Any | None = None
        try:
            # websocket-client 1.9 的 WebSocket 並非 context manager；明確 close，
            # 才能同時相容 PRAW 目前帶入的既有版本與直接 dependency。
            ws = websocket.create_connection(ws_url, timeout=min(self.timeout, 30.0))
            ws.send(json.dumps({
                "id": request_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                    "userGesture": True,
                },
            }))
            while True:
                raw = ws.recv()
                message = json.loads(raw)
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise WebSessionError(f"Chrome DevTools error: {message['error'].get('message', 'unknown')}")
                result = message.get("result", {}).get("result", {})
                if "value" in result:
                    return result["value"]
                details = message.get("result", {}).get("exceptionDetails") or {}
                raise WebSessionError(f"頁面腳本失敗：{details.get('text', 'unknown error')}")
        except WebSessionError:
            raise
        except websocket.WebSocketBadStatusException as exc:
            # Chrome 111+ 對 remote-debugging WebSocket 強制 Origin allowlist。
            # HTTP /json/list 仍會成功，所以一定要保留這個可操作的錯誤訊息。
            if getattr(exc, "status_code", None) == 403:
                origin = urlsplit(self.cdp_url).geturl()
                raise WebSessionError(
                    "Chrome 拒絕 DevTools WebSocket（403 Origin allowlist）。請關閉這個"
                    "隔離 Chrome profile，並以 --remote-allow-origins="
                    f"{origin} 重新啟動。"
                ) from exc
            raise WebSessionError("Chrome DevTools WebSocket 握手失敗") from exc
        except Exception as exc:  # websocket-client 的 exception hierarchy 依版本不同
            raise WebSessionError("與 Chrome DevTools 的 websocket 中斷") from exc
        finally:
            if ws is not None:
                ws.close()

    def _response_state(
        self,
        ws_url: str,
        *,
        text_after: int | None = None,
    ) -> dict[str, Any]:
        cfg = json.dumps(asdict(self.adapter), ensure_ascii=False)
        text_after_json = json.dumps(text_after)
        expression = f"""(() => {{
          const cfg = {cfg}; const textAfter = {text_after_json};
          const queryAll = (selectors) => {{
            const out = []; const seen = new Set();
            for (const selector of selectors) {{
              try {{ for (const el of document.querySelectorAll(selector)) {{
                if (!seen.has(el)) {{ seen.add(el); out.push(el); }}
              }} }} catch (_) {{}}
            }} return out;
          }};
          const responseEls = queryAll(cfg.response_selectors);
          // Baseline 只回元素數量；正式輪詢只序列化本次送出後新增的元素，
          // 因此不會把既有對話內容送進 Python process。
          const freshEls = textAfter === null ? [] : responseEls.slice(textAfter);
          const responses = freshEls.map((el) => (el.innerText || el.textContent || '').trim()).filter(Boolean);
          return {{ count: responseEls.length, text: responses.at(-1) || '',
            thinking: queryAll(cfg.thinking_selectors).length > 0 }};
        }})()"""
        value = self._evaluate(ws_url, expression)
        if not isinstance(value, dict):
            raise WebSessionError("無法讀取 LLM 回應狀態")
        if isinstance(value.get("text"), str):
            value["text"] = _clean_response_text(value["text"])
        return value

    def _send_prompt(self, ws_url: str, prompt: str) -> None:
        cfg = json.dumps(asdict(self.adapter), ensure_ascii=False)
        prompt_json = json.dumps(prompt, ensure_ascii=False)
        expression = f"""(() => {{
          const cfg = {cfg}; const prompt = {prompt_json};
          const first = (selectors) => {{
            for (const selector of selectors) {{ try {{ const el = document.querySelector(selector); if (el) return el; }} catch (_) {{}} }}
            return null;
          }};
          if (first(cfg.logged_out_selectors)) return {{ ok: false, error: 'provider page is logged out' }};
          const input = first(cfg.input_selectors);
          if (!input) return {{ ok: false, error: 'prompt input selector not found' }};
          input.focus();
          if (input instanceof HTMLTextAreaElement || input instanceof HTMLInputElement) {{
            const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(input, prompt); else input.value = prompt;
          }} else {{
            input.replaceChildren();
            for (const line of prompt.split('\\n')) {{ const p = document.createElement('p'); p.textContent = line || '\\u00a0'; input.appendChild(p); }}
          }}
          input.dispatchEvent(new Event('input', {{ bubbles: true }}));
          input.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: prompt }}));
          const button = first(cfg.send_button_selectors);
          if (button && !button.disabled && button.getAttribute('aria-disabled') !== 'true') {{ button.click(); return {{ ok: true }}; }}
          input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', bubbles: true }}));
          input.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', bubbles: true }}));
          return {{ ok: true }};
        }})()"""
        result = self._evaluate(ws_url, expression)
        if not isinstance(result, dict) or not result.get("ok"):
            error = result.get("error", "unknown send failure") if isinstance(result, dict) else "unknown send failure"
            raise WebSessionError(f"無法傳送 LLM prompt：{error}")

    def probe(self) -> dict[str, Any]:
        """非破壞式檢查，供 setup script 使用；不讀取既有對話內容。"""
        ws_url = self._find_tab_ws_url()
        cfg = json.dumps(asdict(self.adapter), ensure_ascii=False)
        expression = f"""(() => {{
          const cfg = {cfg};
          const found = (selectors) => selectors.some((s) => {{ try {{ return Boolean(document.querySelector(s)); }} catch (_) {{ return false; }} }});
          return {{ ready: found(cfg.input_selectors), logged_out: found(cfg.logged_out_selectors), url: location.origin }};
        }})()"""
        result = self._evaluate(ws_url, expression)
        if not isinstance(result, dict):
            raise WebSessionError("LLM 分頁 readiness 檢查失敗")
        return result

    def complete(self, *, system: str, messages: list[dict]) -> ChatResult:
        if not messages:
            raise ValueError("web LLM requires at least one message")
        formatted_messages = "\n\n".join(
            f"[{str(m.get('role', 'user')).upper()}]\n{str(m.get('content', ''))}"
            for m in messages
        )
        prompt = (
            f"{system}\n\n--- CONVERSATION (complete context for this turn) ---\n"
            f"{formatted_messages}\n\n請只回答最後一則 USER 訊息。"
        )
        # 同時保護同 process 的 thread 與 scheduler/bot 兩個 launchd process。
        with _THREAD_LOCK, _process_lock(self.lock_path):
            ws_url = self._find_tab_ws_url()
            baseline = self._response_state(ws_url)
            baseline_count = int(baseline.get("count", 0))
            self._send_prompt(ws_url, prompt)
            deadline = time.monotonic() + self.timeout
            last_text = ""
            stable_since: float | None = None
            while time.monotonic() < deadline:
                state = self._response_state(ws_url, text_after=baseline_count)
                count = int(state.get("count", 0))
                text = str(state.get("text", "")).strip()
                if count > baseline_count and text:
                    if text != last_text:
                        last_text = text
                        stable_since = time.monotonic()
                    elif not state.get("thinking") and stable_since is not None:
                        if time.monotonic() - stable_since >= self.settle_seconds:
                            # 網頁免費方案不會揭露可計費 usage；明確記為零 API 成本。
                            return ChatResult(content=text, cost_usd=0.0)
                time.sleep(self.poll_interval)
        raise WebSessionError(
            f"{self.adapter.provider} 在 {self.timeout:.0f}s 內沒有完成回應；"
            "請確認免費額度、登入狀態或頁面是否出現人工驗證。"
        )


class WebSessionScorer(LLMScorer):
    """把 browser chat 回覆套入既有五軸 JSON parser，無需改 ScoringService。"""

    def __init__(self, **kwargs: Any) -> None:
        self._chat = WebSessionChat(**kwargs)

    def score(self, post: CandidatePost) -> HaikuVerdict:
        result = self._chat.complete(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(post)}],
        )
        return verdict_from_payload(
            parse_haiku_response(result.content),
            cost_usd=0.0,
        )


__all__ = [
    "ADAPTERS",
    "WebAdapter",
    "WebSessionChat",
    "WebSessionError",
    "WebSessionScorer",
]
