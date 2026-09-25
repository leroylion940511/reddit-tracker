const $ = (selector) => document.querySelector(selector);
let activeLog = "newsroom";

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
    const needsDeploy = service.label.endsWith(".newsroom") && service.schema_ready === false;
    const badge = service.running ? "running" : service.disabled || needsDeploy ? "disabled" : "";
    const state = service.running ? "運行中" : needsDeploy ? "需要部署" : service.disabled ? "已停止" : "未載入";
    const action = service.running ? "stop" : "start";
    const label = service.running ? "停止" : "啟動";
    const serviceKey = service.label.split(".").at(-1);
    const isNewsroom = serviceKey === "newsroom";
    const detail = isNewsroom ? (needsDeploy ? service.schema_detail : service.plist_installed ? "服務設定已就緒。" : "首次啟動時會安裝本專案的服務設定。") : "v5 新聞室不使用此服務；保留狀態供遷移與除錯查閱。";
    const control = isNewsroom && (service.running || !needsDeploy) ? `<button data-service="${serviceKey}" data-action="${action}">${label} ${service.name}</button>` : "";
    return `<article class="service"><div class="service-top"><h3>${service.name}</h3><span class="badge ${badge}">${state}</span></div><p>${detail}</p>${control}</article>`;
  }).join("");
  document.querySelectorAll("[data-service]").forEach((button) => button.addEventListener("click", () => serviceAction(button.dataset.action, button.dataset.service)));
}

async function loadOverview() {
  const data = await api("/api/overview");
  renderServices(data.services);
  const metricLabels = { candidates: "候選貼文", newsroom_editions: "新聞版次", newsroom_published: "已發行報紙", tracked_active: "活躍追蹤", qa_sessions: "QA Sessions", related_events: "後續事件" };
  $("#metrics").innerHTML = Object.entries(metricLabels).map(([key, label]) => `<article class="metric"><span>${label}</span><strong>${data.counts[key]}</strong></article>`).join("");
  $("#latest").innerHTML = [["最近發現", data.latest.candidate], ["最近版次", data.latest.edition], ["最近問答", data.latest.qa], ["最近 LLM 呼叫", data.latest.llm]].map(([label, value]) => `<dt>${label}</dt><dd>${format(value)}</dd>`).join("");
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

function newsroomStatus(status) {
  return { published: "已發行", drafted: "已完稿", planned: "已規劃", planning_failed: "選題未完成", publishing: "發行中", delivery_failed: "發行需確認" }[status] || status;
}

function newsroomSources(sources) {
  if (!sources.length) return "";
  return `<ul class="sources">${sources.map((source) => `<li><a href="${escapeHtml(source.permalink)}" target="_blank" rel="noreferrer">r/${escapeHtml(source.subreddit)}｜${escapeHtml(source.original_title)}</a></li>`).join("")}</ul>`;
}

async function loadNewsroom() {
  const [editions, profile, pilot, sourceHealth, overview] = await Promise.all([api("/api/newsroom/editions"), api("/api/newsroom/reader-profile"), api("/api/newsroom/pilot"), api("/api/newsroom/source-health"), api("/api/overview")]);
  loadReaderProfile(profile);
  renderPilot(pilot);
  renderSourceHealth(sourceHealth);
  renderFeedbackChannel(overview.services);
  $("#edition-list").innerHTML = editions.length ? editions.map((edition) => `<button class="edition" data-edition="${edition.id}"><strong>${escapeHtml(edition.edition_date)}</strong><small>${newsroomStatus(edition.status)} · ${edition.item_count} 則</small></button>`).join("") : "<p class=\"empty\">尚無新聞版次。</p>";
  document.querySelectorAll("[data-edition]").forEach((button) => button.addEventListener("click", () => loadNewsroomEdition(button.dataset.edition, button)));
  if (editions.length) await loadNewsroomEdition(editions[0].id, document.querySelector("[data-edition]"));
}

function renderPilot(pilot) {
  if (pilot.pilot_complete) {
    const gate = pilot.gate_passed_window;
    const range = gate ? `${gate.start_date} 至 ${gate.end_date}` : "歷史紀錄";
    const rolling = pilot.current_window_complete ? "近七日也全數符合。" : "下方仍顯示近七日的營運狀態。";
    $("#pilot-summary").textContent = `七日試刊 gate 已通過（${range}）；${rolling}`;
  } else {
    $("#pilot-summary").textContent = `近七日已出刊 ${pilot.published_days} / 7 天；來源完整 ${pilot.source_complete_days} / 7 天。`;
  }
  $("#pilot-days").innerHTML = pilot.days.map((day) => `<article class="pilot-day ${day.status === "published" && day.sources_complete ? "ready" : ""}"><strong>${escapeHtml(day.date)}</strong><small>${newsroomStatus(day.status)} · ${day.item_count} 則</small><span>${day.sources_complete ? "來源完整" : "待補來源／版次"} · ❤️ ${day.positive_feedback}</span></article>`).join("");
}

function localTime(value) {
  if (!value) return "尚未記錄";
  return new Intl.DateTimeFormat("zh-TW", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function renderSourceHealth(health) {
  const stateLabel = { current: "近期已輪詢", stale: "輪詢過期", never: "尚未輪詢" };
  $("#source-health-summary").textContent = `${health.enabled_source_count} 個啟用來源；${health.current_source_count} 個在 ${health.poll_interval_minutes * 2 + 5} 分鐘內已輪詢；24 小時新增 ${health.recent_candidate_count} 篇候選。`;
  $("#source-health-list").innerHTML = health.sources.map((source) => `<article class="source-card ${escapeHtml(source.poll_state)}"><div><strong>r/${escapeHtml(source.name)}</strong><span>${escapeHtml(stateLabel[source.poll_state] || source.poll_state)}</span></div><small>最後輪詢：${escapeHtml(localTime(source.last_polled_at))}</small><small>最新候選：${escapeHtml(localTime(source.latest_candidate_at))} · 24h ${source.recent_candidate_count} 篇</small></article>`).join("") || "<p class=\"empty\">尚未設定啟用來源。</p>";
}

function renderFeedbackChannel(services) {
  const bot = services.find((service) => service.label.endsWith(".bot"));
  const text = bot?.running
    ? "Telegram Bot receiver 正在運行；Telegram 按鈕回饋可被接收。"
    : "Telegram Bot receiver 目前停用；Telegram 按鈕尚不會寫入回饋，請先使用網頁回饋。";
  $("#feedback-channel-status").textContent = text;
}

function listValue(values) { return (values || []).join(", "); }
function parseList(value) { return value.split(",").map((entry) => entry.trim()).filter(Boolean); }

function loadReaderProfile(profile) {
  const form = $("#reader-profile-form");
  ["preference_prompt", "included_topics", "excluded_topics", "included_subreddits", "excluded_subreddits", "included_keywords", "excluded_keywords"].forEach((key) => { form.elements[key].value = Array.isArray(profile[key]) ? listValue(profile[key]) : profile[key] || ""; });
  $("#reader-delivery").textContent = `${profile.timezone} ${profile.delivery_time}`;
}

async function saveReaderProfile(event) {
  event.preventDefault(); const form = event.target;
  const payload = { preference_prompt: form.elements.preference_prompt.value.trim(), included_topics: parseList(form.elements.included_topics.value), excluded_topics: parseList(form.elements.excluded_topics.value), included_subreddits: parseList(form.elements.included_subreddits.value), excluded_subreddits: parseList(form.elements.excluded_subreddits.value), included_keywords: parseList(form.elements.included_keywords.value), excluded_keywords: parseList(form.elements.excluded_keywords.value) };
  try { const profile = await api("/api/newsroom/reader-profile", { method: "PUT", body: JSON.stringify(payload) }); loadReaderProfile(profile); notice("讀者設定已儲存，將套用到下一期選題。"); } catch (error) { notice(error.message, true); }
}

async function loadNewsroomEdition(id, selected) {
  const edition = await api(`/api/newsroom/editions/${id}`);
  document.querySelectorAll(".edition").forEach((button) => button.classList.remove("selected"));
  if (selected) selected.classList.add("selected");
  const view = edition.view;
  const kindLabel = (kind) => ({ feature: "專題", breaking: "早報快訊" }[kind] || "短報");
  const articles = view.items.length ? view.items.map((item) => `<article class="paper-item"><div class="item-meta">${item.position.toString().padStart(2, "0")} · ${kindLabel(item.kind)} · 信心 ${escapeHtml(item.confidence || "未標示")}</div><h3>${escapeHtml(item.headline_zh)}</h3><p>${escapeHtml(item.body_zh)}</p><p class="why">為什麼值得看：${escapeHtml(item.why_it_matters)}</p>${item.warnings.map((warning) => `<p class="warning">⚠️ ${escapeHtml(warning)}</p>`).join("")}${newsroomSources(item.sources)}<div class="feedback-actions"><span>這類內容：</span><button data-feedback="more" data-item="${item.id}">❤️ 多看</button><button data-feedback="less" data-item="${item.id}">🚫 少看</button><button data-feedback="follow" data-item="${item.id}">👀 追後續</button></div></article>`).join("") : "<p class=\"empty\">此版次尚未產生可閱讀稿件。</p>";
  const artifacts = view.artifacts.length ? view.artifacts.map((artifact) => { const sourceNote = artifact.source_count > artifact.sources.length ? `<p class="source-note">顯示 ${artifact.sources.length} / ${artifact.source_count} 個來源</p>` : ""; return `<article class="artifact ${artifact.status === "failed" ? "failed" : ""}"><strong>${escapeHtml(artifact.stage)}</strong><small>${escapeHtml(artifact.status)} · attempt ${artifact.attempt}</small><p>${escapeHtml(artifact.error_message || artifact.summary || "未產生可展示摘要。")}</p>${sourceNote}${newsroomSources(artifact.sources)}</article>`; }).join("") : "<p class=\"empty\">尚無可展示的編輯紀錄。</p>";
  $("#edition-detail").innerHTML = `<header class="edition-head"><div><p class="eyebrow">${newsroomStatus(edition.status)}</p><h2>${escapeHtml(edition.edition_date)} 的每日報紙</h2><p>${escapeHtml(edition.editor_summary || view.reader_summary)}</p></div></header><div class="edition-columns"><section><h3>報紙內容</h3>${articles}</section><aside><h3>編輯室紀錄</h3>${artifacts}</aside></div>`;
  document.querySelectorAll("[data-feedback]").forEach((button) => button.addEventListener("click", () => submitFeedback(button)));
}

async function submitFeedback(button) {
  try {
    const result = await api(`/api/newsroom/items/${button.dataset.item}/feedback`, { method: "POST", body: JSON.stringify({ action: button.dataset.feedback }) });
    notice(result.duplicate ? "這個回饋已記錄。" : "回饋已記錄，會用於下一期選題。");
  } catch (error) { notice(error.message, true); }
}

async function loadLog() { const data = await api(`/api/logs/${activeLog}`); $("#log-output").textContent = data.content; }

const fieldMeta = {
  reddit_scraper: ["Reddit 抓取器", "public_json / praw / fake"], llm_provider: ["LLM provider", "gemini / web / minimax / anthropic / fake"], gemini_scoring_model: ["Gemini 評分模型", "建議 Flash-Lite"], gemini_qa_model: ["Gemini 問答模型", "建議 2.5 Flash"], gemini_scoring_daily_limit: ["Gemini 每日評分上限", "Pacific date；預設 450"], gemini_qa_daily_limit: ["Gemini 每日問答上限", "Pacific date；預設 50"], gemini_requests_per_minute: ["Gemini 每分鐘上限", "跨 scheduler / bot；預設 5"], gemini_fallback_provider: ["Gemini 額度耗盡 fallback", "web 或 fake"], web_llm_provider: ["網頁 LLM", "chatgpt 或 gemini"], web_llm_cdp_url: ["Chrome DevTools 位址", "僅允許 127.0.0.1"], web_llm_timeout_seconds: ["網頁 LLM 逾時秒數", "10–600 秒"], newsroom_writer: ["新聞室撰稿器", "gemini 或 template"], newsroom_preparation_hour: ["新聞室編採開始時", "0–23 時；預設 05:30"], newsroom_preparation_minute: ["新聞室編採開始分", "0–59 分；預設 05:30"], newsroom_discovery_interval_minutes: ["新聞室抓取間隔", "5–1440 分鐘；僅擷取候選"], poll_subreddit_minutes: ["v4 Subreddit 抓取間隔", "5–1440 分鐘"], poll_keyword_hours: ["關鍵字抓取間隔", "1–168 小時"], scoring_minutes: ["評分間隔", "5–1440 分鐘"], scoring_batch_limit: ["每批評分數", "1–200"], polling_minutes: ["追蹤輪詢間隔", "5–1440 分鐘"], detection_minutes: ["後續偵測間隔", "5–1440 分鐘"], log_level: ["日誌等級", "DEBUG / INFO / WARNING / ERROR"]
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

const viewTitles = { overview: "系統總覽", newsroom: "每日報紙", data: "資料庫", conversations: "歷史問答", logs: "服務日誌", settings: "專案設定" };
async function selectView(name) {
  document.querySelectorAll(".nav").forEach((button) => button.classList.toggle("active", button.dataset.view === name)); document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`)); $("#page-title").textContent = viewTitles[name];
  try { if (name === "overview") await loadOverview(); if (name === "newsroom") await loadNewsroom(); if (name === "data") await loadData(); if (name === "conversations") await loadSessions(); if (name === "logs") await loadLog(); if (name === "settings") await loadSettings(); } catch (error) { notice(error.message, true); }
}

document.querySelectorAll(".nav").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
$("#refresh").addEventListener("click", () => selectView(document.querySelector(".nav.active").dataset.view));
$("#start-newsroom").addEventListener("click", () => serviceAction("start", "newsroom")); $("#stop-newsroom").addEventListener("click", () => serviceAction("stop", "newsroom"));
$("#data-kind").addEventListener("change", loadData); $("#settings-form").addEventListener("submit", saveSettings);
$("#reader-profile-form").addEventListener("submit", saveReaderProfile);
document.querySelectorAll("[data-log]").forEach((button) => button.addEventListener("click", async () => { activeLog = button.dataset.log; document.querySelectorAll("[data-log]").forEach((item) => item.classList.toggle("selected", item === button)); await loadLog(); }));
$("#doctor").addEventListener("click", async () => { try { const result = await api("/api/llm/doctor", { method: "POST" }); const output = $("#doctor-output"); output.hidden = false; output.textContent = result.output; notice(result.ready ? "LLM 工作階段已就緒。" : "LLM 工作階段尚未就緒。", !result.ready); } catch (error) { notice(error.message, true); } });
selectView("overview");
