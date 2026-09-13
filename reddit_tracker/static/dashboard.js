const $ = (selector) => document.querySelector(selector);
let activeLog = "scheduler";

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "操作失敗");
  return body;
}

function notice(text, error = false) {
  const box = $("#notice"); box.textContent = text; box.className = `notice${error ? " error" : ""}`;
  window.clearTimeout(notice.timer); notice.timer = window.setTimeout(() => { box.className = ""; box.textContent = ""; }, 5200);
}

function format(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function short(value, max = 190) { const text = format(value); return text.length > max ? `${text.slice(0, max)}…` : text; }
function escapeHtml(value) { return format(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;"); }

function renderServices(services) {
  $("#services").innerHTML = services.map((service) => {
    const badge = service.running ? "running" : service.disabled ? "disabled" : "";
    const state = service.running ? "運行中" : service.disabled ? "已停止" : "未載入";
    const action = service.running ? "stop" : "start";
    const label = service.running ? "停止" : "啟動";
    return `<article class="service"><div class="service-top"><h3>${service.name}</h3><span class="badge ${badge}">${state}</span></div><p>${service.plist_installed ? "服務設定已就緒。" : "首次啟動時會安裝本專案的服務設定。"}</p><button data-service="${service.label.endsWith("scheduler") ? "scheduler" : "bot"}" data-action="${action}">${label} ${service.name}</button></article>`;
  }).join("");
  document.querySelectorAll("[data-service]").forEach((button) => button.addEventListener("click", () => serviceAction(button.dataset.action, button.dataset.service)));
}

async function loadOverview() {
  const data = await api("/api/overview");
  renderServices(data.services);
  const metricLabels = { candidates: "候選貼文", tracked_active: "活躍追蹤", qa_sessions: "QA Sessions", qa_messages: "對話訊息", related_events: "後續事件" };
  $("#metrics").innerHTML = Object.entries(metricLabels).map(([key, label]) => `<article class="metric"><span>${label}</span><strong>${data.counts[key]}</strong></article>`).join("");
  $("#latest").innerHTML = [["最近發現", data.latest.candidate], ["最近問答", data.latest.qa], ["最近 LLM 呼叫", data.latest.llm]].map(([label, value]) => `<dt>${label}</dt><dd>${format(value)}</dd>`).join("");
  $("#llm-summary").textContent = `累積成本 $${Number(data.llm_cost_usd || 0).toFixed(4)}`;
}

async function serviceAction(action, service) {
  if (action === "stop" && !window.confirm("停止後，背景服務不會在下次登入時自動重新啟動。要繼續嗎？")) return;
  try { await api(`/api/services/${action}`, { method: "POST", body: JSON.stringify({ service }) }); notice(action === "start" ? "服務已啟動。" : "服務已停止並停用自動重啟。"); await loadOverview(); } catch (error) { notice(error.message, true); }
}

async function loadData() {
  const rows = await api(`/api/data/${$("#data-kind").value}?limit=100`);
  const keys = rows.length ? Object.keys(rows[0]) : [];
  $("#data-head").innerHTML = `<tr>${keys.map((key) => `<th>${key}</th>`).join("")}</tr>`;
  $("#data-body").innerHTML = rows.length ? rows.map((row) => `<tr>${keys.map((key) => `<td title="${escapeHtml(row[key])}">${escapeHtml(short(row[key]))}</td>`).join("")}</tr>`).join("") : "<tr><td>尚無資料。</td></tr>";
}

async function loadSessions() {
  const sessions = await api("/api/qa-sessions");
  $("#session-list").innerHTML = sessions.length ? sessions.map((session) => `<button class="session" data-session="${session.id}"><strong>#${session.id} ${escapeHtml(short(session.title, 55))}</strong><small>r/${escapeHtml(session.subreddit || "—")} · ${escapeHtml(session.state)} · ${escapeHtml(session.started_at)}</small></button>`).join("") : "<p class=\"empty\">尚無 QA 對話。</p>";
  document.querySelectorAll("[data-session]").forEach((button) => button.addEventListener("click", () => loadMessages(button.dataset.session, button)));
}

async function loadMessages(id, selected) {
  const messages = await api(`/api/qa-sessions/${id}/messages`);
  document.querySelectorAll(".session").forEach((button) => button.classList.remove("selected")); selected.classList.add("selected");
  $("#messages").innerHTML = messages.length ? messages.map((message) => `<div class="message ${message.role}">${escapeHtml(message.content)}<time>${message.role === "user" ? "使用者" : "助理"} · ${escapeHtml(message.sent_at)}</time></div>`).join("") : "<p class=\"empty\">此 session 尚無訊息。</p>";
}

async function loadLog() { const data = await api(`/api/logs/${activeLog}`); $("#log-output").textContent = data.content; }

const fieldMeta = {
  reddit_scraper: ["Reddit 抓取器", "public_json / praw / fake"], llm_provider: ["LLM provider", "gemini / web / minimax / anthropic / fake"], gemini_scoring_model: ["Gemini 評分模型", "建議 Flash-Lite"], gemini_qa_model: ["Gemini 問答模型", "建議 2.5 Flash"], gemini_scoring_daily_limit: ["Gemini 每日評分上限", "Pacific date；預設 450"], gemini_qa_daily_limit: ["Gemini 每日問答上限", "Pacific date；預設 50"], gemini_requests_per_minute: ["Gemini 每分鐘上限", "跨 scheduler / bot；預設 5"], gemini_fallback_provider: ["Gemini 額度耗盡 fallback", "web 或 fake"], web_llm_provider: ["網頁 LLM", "chatgpt 或 gemini"], web_llm_cdp_url: ["Chrome DevTools 位址", "僅允許 127.0.0.1"], web_llm_timeout_seconds: ["網頁 LLM 逾時秒數", "10–600 秒"], poll_subreddit_minutes: ["Subreddit 抓取間隔", "5–1440 分鐘"], poll_keyword_hours: ["關鍵字抓取間隔", "1–168 小時"], scoring_minutes: ["評分間隔", "5–1440 分鐘"], scoring_batch_limit: ["每批評分數", "1–200"], polling_minutes: ["追蹤輪詢間隔", "5–1440 分鐘"], detection_minutes: ["後續偵測間隔", "5–1440 分鐘"], log_level: ["日誌等級", "DEBUG / INFO / WARNING / ERROR"]
};

async function loadSettings() {
  const data = await api("/api/config");
  $("#settings-form").innerHTML = Object.entries(data.values).map(([key, value]) => { const [label, hint] = fieldMeta[key]; const type = typeof value === "number" ? "number" : "text"; return `<div class="field"><label for="setting-${key}">${label}</label><input id="setting-${key}" name="${key}" type="${type}" value="${escapeHtml(value)}" required /><small>${hint}</small></div>`; }).join("");
  $("#restart-hint").textContent = data.restart_hint;
  $("#secret-status").innerHTML = Object.entries(data.secrets).map(([key, ready]) => `<span>${key.replaceAll("_", " ")}：${ready ? "已設定" : "未設定"}</span>`).join("");
}

async function saveSettings(event) {
  event.preventDefault(); const values = {};
  new FormData(event.target).forEach((value, key) => { values[key] = value; });
  try { await api("/api/config", { method: "PUT", body: JSON.stringify({ values }) }); notice("設定已儲存；如背景服務正在執行，請停止後重新啟動以套用。 "); await loadSettings(); } catch (error) { notice(error.message, true); }
}

const viewTitles = { overview: "系統總覽", data: "資料庫", conversations: "歷史問答", logs: "服務日誌", settings: "專案設定" };
async function selectView(name) {
  document.querySelectorAll(".nav").forEach((button) => button.classList.toggle("active", button.dataset.view === name)); document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`)); $("#page-title").textContent = viewTitles[name];
  try { if (name === "overview") await loadOverview(); if (name === "data") await loadData(); if (name === "conversations") await loadSessions(); if (name === "logs") await loadLog(); if (name === "settings") await loadSettings(); } catch (error) { notice(error.message, true); }
}

document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
$("#refresh").addEventListener("click", () => selectView(document.querySelector(".nav.active").dataset.view));
$("#start-all").addEventListener("click", () => serviceAction("start", "all")); $("#stop-all").addEventListener("click", () => serviceAction("stop", "all"));
$("#data-kind").addEventListener("change", loadData); $("#settings-form").addEventListener("submit", saveSettings);
document.querySelectorAll("[data-log]").forEach((button) => button.addEventListener("click", async () => { activeLog = button.dataset.log; document.querySelectorAll("[data-log]").forEach((item) => item.classList.toggle("selected", item === button)); await loadLog(); }));
$("#doctor").addEventListener("click", async () => { try { const result = await api("/api/llm/doctor", { method: "POST" }); const output = $("#doctor-output"); output.hidden = false; output.textContent = result.output; notice(result.ready ? "LLM 工作階段已就緒。" : "LLM 工作階段尚未就緒。", !result.ready); } catch (error) { notice(error.message, true); } });
selectView("overview");
