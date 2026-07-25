"use strict";

const SafetyPolicy = window.RelaySafetyPolicy;
if (!SafetyPolicy?.VERSION) throw new Error("Matching safety policy failed to load");
const app = document.getElementById("join-app");
const banner = document.getElementById("connection-banner");
const APP_BUILD = "2026.07.25-production-v8";
function isLocalExperienceHost(hostname = location.hostname) {
  const host = String(hostname || "").replace(/^\[|\]$/g, "").toLowerCase();
  if (!host || host === "localhost" || host === "::1" || host.endsWith(".local")) return true;
  if (/^127\./.test(host) || /^10\./.test(host) || /^192\.168\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)) return true;
  return /^(fc|fd|fe[89ab])/i.test(host);
}
const HOSTED_STATIC_REVIEW = new URLSearchParams(location.search).get("deployment") === "static-review" || !isLocalExperienceHost();
document.documentElement.dataset.deploymentMode = HOSTED_STATIC_REVIEW ? "hosted-static-review" : "local-full";
document.documentElement.dataset.build = APP_BUILD;
const fragment = new URLSearchParams(location.hash.replace(/^#/, ""));
let roomId = fragment.get("room") || new URLSearchParams(location.search).get("room") || "";
let inviteToken = fragment.get("invite") || "";
let relayToken = "";
let relayParticipantId = "";
let relaySessionId = "";
let room = null;
let pending = false;
let degraded = false;
let accessEnded = false;
let accessEndedReason = "";
let snapshotVerified = false;
let policyBlocked = false;
let pollHandle = null;
let countdownHandle = null;
let refreshInFlight = false;
let refreshQueued = false;

const escapeHTML = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char]));
const phoneHref = (value = "") => `tel:${String(value).replace(/[^\d+]/g, "")}`;
const credentialKey = () => `relay-companion-credential:${roomId}`;
const pendingKey = () => `relay-companion-invite:${roomId}`;
const snapshotKey = () => `relay-companion-safe-snapshot:${roomId}`;

if (roomId && inviteToken) {
  sessionStorage.setItem(pendingKey(), inviteToken);
  history.replaceState(null, "", `./join.html?room=${encodeURIComponent(roomId)}`);
}
if (roomId && !inviteToken) inviteToken = sessionStorage.getItem(pendingKey()) || "";
if (roomId) {
  try {
    const credential = JSON.parse(localStorage.getItem(credentialKey()));
    relayToken = credential?.token || "";
    relayParticipantId = credential?.participantId || "";
    relaySessionId = credential?.sessionId || "";
  } catch {
    relayToken = localStorage.getItem(credentialKey()) || "";
  }
  try { room = JSON.parse(localStorage.getItem(snapshotKey())) || null; } catch { room = null; }
}

function persistRelayState() {
  if (relayToken) {
    localStorage.setItem(credentialKey(), JSON.stringify({
      token: relayToken,
      participantId: relayParticipantId,
      sessionId: relaySessionId,
      policyVersion: SafetyPolicy.VERSION,
    }));
  }
  if (room) localStorage.setItem(snapshotKey(), JSON.stringify(room));
}

function acceptRoomSnapshot(nextRoom, { force = false } = {}) {
  if (!nextRoom || typeof nextRoom !== "object") return false;
  const currentRevision = Number(room?.revision);
  const nextRevision = Number(nextRoom.revision);
  if (
    !force
    && room?.id === nextRoom.id
    && Number.isFinite(currentRevision)
    && Number.isFinite(nextRevision)
    && nextRevision < currentRevision
  ) {
    return false;
  }
  room = nextRoom;
  relayParticipantId = nextRoom.participantId || relayParticipantId;
  relaySessionId = nextRoom.sessionId || relaySessionId;
  persistRelayState();
  return true;
}

function toast(message) {
  const node = document.getElementById("join-toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.handle);
  toast.handle = setTimeout(() => node.classList.remove("show"), 2600);
}

function actionId() {
  return crypto.randomUUID ? crypto.randomUUID() : `action-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function actionContext() {
  return {
    expectedRevision: room.revision,
    actionId: actionId(),
    sessionId: room.sessionId || relaySessionId,
    participantId: room.participantId || relayParticipantId,
    consentRevision: room.consentRevision,
    guideVersion: room.guideVersion,
    safetyRevision: room.safetyRevision,
  };
}

function countdownText() {
  if (!room?.startedAt) return `${String(room?.duration || 0).padStart(2, "0")}:00`;
  const elapsed = Math.max(0, Math.floor((Date.now() - new Date(room.startedAt).getTime()) / 1000));
  const remaining = Math.max(0, room.duration * 60 - elapsed);
  return `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
}

function startCountdown() {
  clearInterval(countdownHandle);
  if (room?.status !== "active") return;
  const update = () => {
    const timer = document.getElementById("relay-countdown");
    if (timer) timer.textContent = countdownText();
  };
  update();
  countdownHandle = setInterval(update, 1000);
}

async function request(path, options = {}) {
  if (HOSTED_STATIC_REVIEW) {
    const error = new Error("公开评审版不连接临时双机房间服务");
    error.status = 503;
    error.code = "hosted_static_review";
    throw error;
  }
  const headers = { "Content-Type": "application/json", [SafetyPolicy.HEADER]: SafetyPolicy.VERSION, ...(options.headers || {}) };
  if (relayToken) headers.Authorization = `Bearer ${relayToken}`;
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  let body = {};
  try { body = await response.json(); } catch { /* status below carries the failure */ }
  if (!response.ok) {
    const error = new Error(body.error?.message || `请求失败 (${response.status})`);
    error.status = response.status;
    error.code = body.error?.code || "request_failed";
    if (error.code === "policy_update_required") policyBlocked = true;
    throw error;
  }
  if (body.room && body.room.policyVersion !== SafetyPolicy.VERSION) {
    policyBlocked = true;
    const error = new Error("安全策略版本已变化，请刷新页面后继续");
    error.status = 409;
    error.code = "policy_update_required";
    throw error;
  }
  policyBlocked = false;
  return body;
}

function setDegraded(value) {
  degraded = value;
  banner.classList.toggle("hidden", !value);
  banner.textContent = value ? "连接暂时中断：保留最后一次只读画面，恢复网络后会自动同步；当前操作已暂停。" : "";
  document.body.classList.toggle("is-degraded", value);
  if (value) {
    document.querySelectorAll("[data-relay-action], #note-form button, #search-form button").forEach((node) => {
      node.disabled = true;
    });
  }
}

function statusLabel(value) {
  return {
    waiting: "等待核对",
    paired: "已配对 · 等待开始",
    active: "双机彩排进行中",
    debrief: "现场结束 · 照护者复盘中",
    ended: "本次彩排已结束",
    invalidated: "家庭内容变化 · 房间已失效",
    revoked: "连接已撤销",
    expired: "连接已到期",
  }[value] || value;
}

function taskCopy(index) {
  const observe = room?.stage === "observe";
  return observe ? [
    ["拿好自己的手机", `${room.family.caregiverName}在旁，但这页只由你操作`],
    [`一起完成：${room.guide.title}`, room.guide.summary],
    ["停下来口头复核", "任何人都可以说停；不确定时立即联系照护者"],
  ][index] : [
    [`先确认现场：${room?.guide.title || ""}`, "只在现场事实与当前确认指导一致时继续"],
    ["按已确认内容处理", room?.guide.summary || ""],
    ["收尾并留下普通记录", "普通变化写在下方；红线事件使用立即联系"],
  ][index];
}

function timelineMarkup() {
  const visible = (room.timeline || []).filter((event) => !["room.created"].includes(event.type)).slice(-8).reverse();
  if (!visible.length) return `<p>开始后，这里只显示本次双机彩排的操作记录。</p>`;
  return `<div class="timeline">${visible.map((event) => `<div class="timeline-item ${event.urgent ? "urgent" : ""}"><b>${event.urgent ? "立即联系 · " : ""}${escapeHTML(event.text)}</b><time>${new Date(event.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>${event.type === "relay.note" ? `<p>普通记录会在结束总结中保留。</p>` : ""}</div>`).join("")}</div>`;
}

function callOnlyMarkup() {
  if (!room?.family) return "";
  return `<article class="join-card urgent-panel call-only"><span class="join-kicker">ALWAYS AVAILABLE CALL PATHS</span><h2>只保留红线与直接联系</h2><p>${escapeHTML(room.redLines?.join("、") || "不确定或出现紧急危险")}。连接不可用时不显示旧指导，也不接受记录；请直接联系${escapeHTML(room.family.caregiverName)}，紧急时拨打当地紧急服务。</p><div class="call-links"><a href="${phoneHref(room.family.caregiverPhone)}">联系${escapeHTML(room.family.caregiverName)}</a><a href="${phoneHref(room.family.emergencyService)}">拨打 ${escapeHTML(room.family.emergencyService)}</a></div></article>`;
}

function relayCheckInMarkup() {
  const saved = room?.checkIns?.substitute || {};
  const option = (value, label, current) => `<option value="${value}" ${current === value ? "selected" : ""}>${label}</option>`;
  return `<article class="join-card relay-checkin-card"><span class="join-kicker">替班者自报 · SUBSTITUTE SELF-REPORT · 可分次保存</span><h2>刚才的范围，你接得住吗？</h2><p>只填现在记得的内容。空白不会被当成安全、放心或已经准备好。</p><form id="relay-checkin-form"><label for="relay-able">能处理刚才练过的范围吗？</label><select id="relay-able"><option value="">可先不填</option>${option("yes","能",saved.ableToHandle)}${option("partly","一部分能",saved.ableToHandle)}${option("no","不能",saved.ableToHandle)}${option("unsure","说不清",saved.ableToHandle)}</select><label for="relay-uncertain">哪一步仍不确定？</label><textarea id="relay-uncertain" maxlength="500" placeholder="如果没有，也请写“没有”">${escapeHTML(saved.uncertainStep || "")}</textarea><label for="relay-contacted">有没有联系照护者？</label><select id="relay-contacted"><option value="">可先不填</option>${option("no","没有",saved.contactedCaregiver)}${option("yes","有",saved.contactedCaregiver)}${option("unsure","说不清",saved.contactedCaregiver)}</select><label for="relay-unsafe">这次有没有感到不安全？</label><select id="relay-unsafe"><option value="">可先不填</option>${option("false","没有",saved.feltUnsafe == null ? null : String(saved.feltUnsafe))}${option("true","有",saved.feltUnsafe == null ? null : String(saved.feltUnsafe))}</select><label for="relay-choice">下一次怎么练？</label><select id="relay-choice"><option value="">请选择</option>${option("extend","延长一级",saved.choice)}${option("repeat","重复本级",saved.choice)}${option("step-back","退回一级",saved.choice)}</select><label for="relay-checkin-notes">想留给家庭复盘的话（可选）</label><textarea id="relay-checkin-notes" maxlength="500">${escapeHTML(saved.notes || "")}</textarea><button class="join-button" type="submit" ${pending || degraded ? "disabled" : ""}>${saved.submittedAt ? "补充我的回答" : "保存我的回答"}</button></form></article>`;
}

function renderDegraded() {
  clearInterval(countdownHandle);
  app.innerHTML = `<section class="join-page"><article class="join-card"><span class="join-kicker">AUTHORIZATION FRESHNESS UNKNOWN</span><h1>连接中断，已暂停全部指导</h1><p>当前无法向服务器确认同意、指导版本或安全范围仍然有效。缓存的指导、来源、搜索结果和任务说明已经隐藏；恢复连接并取得新快照前不要继续按应用指导处理。</p><div class="join-safety"><span>◎</span><div><strong>失败时关闭指导，而不是沿用旧内容</strong>下面只保留最后同步的红线和直接电话；它们不依赖房间写入。</div></div></article>${callOnlyMarkup()}</section>`;
}

function renderInvite() {
  app.innerHTML = `<section class="join-page"><article class="join-card">
    <span class="join-kicker">PAIR ON THIS DEVICE</span>
    <h1>先和照护者核对一句短语</h1>
    <p>请当面或通过你们原本可信的通话方式，向${room?.family?.caregiverName || "照护者"}询问邀请页上的两组词。链接和短语缺一不可。</p>
    <form class="phrase-form" id="phrase-form">
      <label for="expected-relay-name">你的姓名（必须与照护者预先填写的一致）</label>
      <input id="expected-relay-name" name="expectedRelayName" autocomplete="name" maxlength="60" placeholder="输入照护者邀请的替班者姓名" required>
      <label for="human-phrase">核对短语</label>
      <input id="human-phrase" name="phrase" autocomplete="off" maxlength="40" placeholder="例如：青松 · 暖灯" required>
      <button class="join-button" type="submit" ${pending ? "disabled" : ""}>${pending ? "正在核对…" : "核对并连接"}</button>
    </form>
    <div class="join-safety"><span>◎</span><div><strong>姓名检查不是证件身份验证</strong>系统只比较照护者预先填写的替班者姓名，再核对一次性链接与短语；不会验证身份证件、生物特征或现实身份。</div></div>
  </article></section>`;
}

function renderPaired() {
  const relayConfirmed = room.confirmations?.relay;
  const reviewedGuides = room.searchGuides || [];
  const reviewedGuideMarkup = `<div class="reviewed-guide-scope" aria-label="本次完整可搜索指导范围">${reviewedGuides.map((guide) => `<article data-reviewed-guide="${escapeHTML(guide.id)}"><span><b>${escapeHTML(guide.title)}</b><small>${escapeHTML(guide.summary)}</small></span><span><strong>v${Number(guide.version)}</strong><small>${escapeHTML(guide.source)} · ${escapeHTML(guide.rule)}</small></span></article>`).join("")}</div>`;
  app.innerHTML = `<section class="join-page"><article class="join-card center">
    <div class="pair-orbit"><span></span></div>
    <span class="join-kicker">SECURELY PAIRED</span>
    <h1>姓名与短语已核对</h1>
    <p>你以“${escapeHTML(room.family.relayName)}”加入。还需要你和照护者各自在自己的手机逐项确认本次范围，服务器才允许开始。</p>
    <div class="pair-meta"><div><small>你的参与者 ID</small><strong>${escapeHTML((room.participantId || "").slice(0, 18))}</strong></div><div><small>连接状态</small><strong>${degraded ? "正在重连" : "在线 · 自动同步"}</strong></div></div>
  </article><article class="join-card"><span class="join-kicker">REQUIRED ACKNOWLEDGEMENT</span><h2>开始前逐项核对</h2><div class="relay-ack-list">
    <label><input type="checkbox" name="relayAck" value="scope" ${relayConfirmed ? "checked disabled" : ""}><span><b>受限范围</b><small>只进入本次“${escapeHTML(room.stage === "quiet-handoff" ? "安静接班" : room.stage === "observe" ? "在旁观察" : "短时离开")}”，看不到家庭主页和设置</small></span></label>
    <label><input type="checkbox" name="relayAck" value="guide" ${relayConfirmed ? "checked disabled" : ""}><span><b>完整可搜索指导范围 · ${reviewedGuides.length} 条</b><small>逐条核对下方标题、处理文字、版本、来源和升级层级；开始后搜索只会返回这里的内容</small></span></label>
    ${reviewedGuideMarkup}
    <label><input type="checkbox" name="relayAck" value="redlines" ${relayConfirmed ? "checked disabled" : ""}><span><b>红线</b><small>${escapeHTML(room.redLines.join("、") || "不确定时立即联系")}</small></span></label>
    <label><input type="checkbox" name="relayAck" value="contacts" ${relayConfirmed ? "checked disabled" : ""}><span><b>直接联系</b><small>可联系${escapeHTML(room.family.caregiverName)}；紧急时拨打 ${escapeHTML(room.family.emergencyService)}</small></span></label>
  </div>${relayConfirmed ? `<div class="join-safety"><span>✓</span><div><strong>你的确认已绑定当前版本</strong>若同意、指导、红线或联系电话改变，本房间会失效并要求新邀请。</div></div>` : `<button class="join-button" style="width:100%;margin-top:14px" data-relay-action="acknowledge" ${pending || degraded ? "disabled" : ""}>四项都确认</button>`}</article><article class="join-card center"><h3>${room.confirmations?.caregiver ? "照护者也已确认" : "等待照护者在自己的手机确认"}</h3><p>双方确认完成后，只有照护者可以按下开始。</p></article></section>`;
}

function renderActive() {
  app.innerHTML = `<section class="join-page">
    <div class="live-strip"><i></i><strong>${statusLabel(room.status)}</strong><span>版本 ${room.revision}</span></div>
    <article class="join-card relay-metrics"><div><small>两端共享倒计时</small><strong id="relay-countdown">${countdownText()}</strong></div><div><small>${room.stage === "quiet-handoff" ? "安静队列" : "普通记录"}</small><strong>${room.quietCount || 0}</strong></div><div><small>待确认缺口</small><strong>${room.pendingGapCount || 0}</strong></div></article>
    <article class="join-card"><span class="join-kicker">CURRENT CONFIRMED GUIDE</span><h2>${escapeHTML(room.guide.title)}</h2><p class="guide-quote">“${escapeHTML(room.guide.summary)}”</p><div class="guide-proof"><span>来源：${escapeHTML(room.guide.source)}</span><span>${escapeHTML(room.guide.rule)}</span></div></article>
    <article class="join-card"><h2>这台手机上的三步</h2><p>完成状态会同步到照护者手机；服务器只接受替班者凭证更新这些步骤。</p><div class="relay-tasks">${room.tasks.map((done, index) => {
      const copy = taskCopy(index);
      return `<button class="relay-task ${done ? "done" : ""}" data-relay-action="task" data-index="${index}" ${done || pending || degraded ? "disabled" : ""}><span>✓</span><span><b>${escapeHTML(copy[0])}</b><small>${escapeHTML(copy[1])}</small></span></button>`;
    }).join("")}</div></article>
    <article class="join-card"><form class="note-form" id="search-form"><label for="relay-search">遇到预料外的情况？先查当前获授权指导</label><textarea id="relay-search" maxlength="240" placeholder="只描述现场事实；未知问题会进入待确认缺口"></textarea><button type="submit" class="join-button secondary" ${pending || degraded ? "disabled" : ""}>查找已确认指导</button></form>${room.lastSearch ? room.lastSearch.status === "matched" ? `<div class="search-result matched ${room.lastSearch.urgent ? "urgent" : ""}"><small>${room.lastSearch.urgent ? "医疗或高风险 · 只引用专业指示并立即联系" : "找到当前获授权指导"}</small><h3>${escapeHTML(room.lastSearch.guide.title)}</h3><p>${escapeHTML(room.lastSearch.guide.summary)}</p><strong>${escapeHTML(room.lastSearch.guide.rule)} · ${escapeHTML(room.lastSearch.guide.source)}</strong></div>` : `<div class="search-result pending ${room.lastSearch.risk === "medical" ? "urgent" : ""}"><small>${room.lastSearch.risk === "medical" ? "医疗或高风险 · 立即联系" : "没有匹配 · 已记录待确认缺口"}</small><p>${room.lastSearch.risk === "medical" ? "不会生成诊断、用药或急救建议。请使用下方直接联系路径。" : "照护者会在复盘中看到这条缺口；补充真实来源前不会变成指导。"}</p></div>` : ""}</article>
    <article class="join-card"><form class="note-form" id="note-form"><label for="relay-note">${room.stage === "quiet-handoff" ? "普通变化进入安静队列，不会立即显示文字" : "普通变化，留到结束统一说明"}</label><textarea id="relay-note" maxlength="240" placeholder="只写现场事实；医疗、用药或红线事件请用下方立即联系"></textarea><div class="action-grid"><button type="submit" class="join-button secondary" ${pending || degraded ? "disabled" : ""}>加入${room.stage === "quiet-handoff" ? "安静队列" : "普通记录"}</button><button type="button" class="join-button coral" data-relay-action="ready" ${pending || degraded ? "disabled" : ""}>现场步骤已完成</button></div></form></article>
    <article class="join-card urgent-panel"><h2>红线与直接联系</h2><p>${escapeHTML(room.redLines.join("、") || "不确定或出现紧急危险")}。应用不作医疗决定；不确定时联系${escapeHTML(room.family.caregiverName)}，紧急时拨打当地紧急服务。</p><div class="call-links"><a href="${phoneHref(room.family.caregiverPhone)}">联系${escapeHTML(room.family.caregiverName)}</a><a href="${phoneHref(room.family.emergencyService)}">拨打 ${escapeHTML(room.family.emergencyService)}</a></div><button class="join-button danger" style="width:100%;margin-top:9px" data-relay-action="alert" ${pending || degraded ? "disabled" : ""}>标记红线并立即联系</button></article>
    <article class="join-card"><h2>本次同步记录</h2>${timelineMarkup()}</article>
  </section>`;
  startCountdown();
}

function renderDebrief() {
  const summary = room.summary || { completedTasks: room.tasks.filter(Boolean).length, notes: room.quietCount || 0, alerts: 0 };
  app.innerHTML = `<section class="join-page"><article class="join-card"><span class="join-kicker">FACTUAL SESSION END</span><h1>现场事实已同步，请填写你自己的回看</h1><p>应用记录为“${escapeHTML({ completed: "现场完成", interrupted: "中途结束", disconnected: "连接中断后结束", revoked: "授权撤回", expired: "连接到期" }[summary.status] || summary.status || "已结束")}”。这不会自动升级阶段。</p><div class="summary-grid"><div><strong>${summary.completedTasks}/3</strong><small>完成步骤</small></div><div><strong>${summary.notes}</strong><small>普通记录</small></div><div><strong>${summary.facts?.urgentAlertsRaised || 0}</strong><small>紧急事件</small></div></div></article>${relayCheckInMarkup()}<article class="join-card"><h2>现场记录现已公开给双方</h2>${timelineMarkup()}</article>${callOnlyMarkup()}</section>`;
}

function renderEnded() {
  const summary = room.summary || { completedTasks: room.tasks.filter(Boolean).length, notes: 0, alerts: 0, durationSeconds: 0, caregiverNote: "" };
  app.innerHTML = `<section class="join-page"><article class="join-card"><div class="ended-stamp">✓</div><span class="join-kicker">SHARED FACTUAL END</span><h1>双机彩排已结束 · 共同结束事实</h1><p>${escapeHTML(room.family.caregiverName)}和你看到同一份应用事实；你们的自报回答由服务器分开署名。联系操作只表示页面打开，不证明电话接通。</p><div class="summary-grid"><div><strong>${summary.completedTasks}/3</strong><small>完成步骤</small></div><div><strong>${summary.notes}</strong><small>普通记录</small></div><div><strong>${summary.facts?.urgentAlertsRaised || 0}</strong><small>紧急事件</small></div></div>${summary.debrief ? `<p class="summary-note">${summary.debrief.outcome === "confirmed-guide" ? `来源复盘：${escapeHTML(summary.debrief.sourceLabel)} · ${escapeHTML(summary.debrief.gap)}` : `待确认缺口：${escapeHTML(summary.debrief.gap)}`}</p>` : ""}</article>${relayCheckInMarkup()}<article class="join-card"><h2>共同记录</h2>${timelineMarkup()}</article>${callOnlyMarkup()}</section>`;
}

function renderTerminal() {
  app.innerHTML = `<section class="join-page"><article class="join-card"><span class="join-kicker">SAFE CALL-ONLY STATE</span><h1>${accessEndedReason === "room_missing" ? "房间服务已重启或记录不可用" : accessEnded ? "此替班者凭证已失效" : statusLabel(room?.status || "revoked")}</h1><p>旧指导和记录操作已隐藏，旧凭证不会再次写入。下面只保留最后一次同步的红线和直接电话联系路径；如仍需彩排，请让照护者创建新邀请。</p><div class="join-safety"><span>◎</span><div><strong>不会假装仍在线</strong>此状态不能接收后台或关页推送，也不会继续倒计时或同步；直接电话不依赖房间服务。</div></div></article>${callOnlyMarkup()}</section>`;
}

function renderMissing() {
  app.innerHTML = `<section class="join-page"><article class="join-card"><span class="join-kicker">INVALID LINK</span><h1>这个连接链接不完整</h1><p>请让照护者在“彩排路径”里重新签发邀请。不要从家庭主页自行建立替班者身份。</p></article></section>`;
}

function renderPolicyUpdateRequired() {
  clearInterval(countdownHandle);
  app.innerHTML = `<section class="join-page"><article class="join-card"><span class="join-kicker">SAFETY POLICY UPDATE REQUIRED</span><h1>刷新更新后再继续</h1><p>这台浏览器与房间服务的安全策略版本不一致。加入、记录、搜索和指导显示都已关闭；刷新取得匹配版本后才能继续。</p><div class="join-safety"><span>◎</span><div><strong>版本不一致时失败关闭</strong>已经收到的直接电话仍保留在下方，不依赖房间写入。</div></div></article>${callOnlyMarkup()}</section>`;
}

function renderHostedBoundary() {
  clearInterval(pollHandle);
  clearInterval(countdownHandle);
  banner.classList.add("hidden");
  app.innerHTML = `<section class="join-page"><article class="join-card"><span class="join-kicker">PUBLIC REVIEW BUILD · ${APP_BUILD}</span><h1>公开评审版不连接临时双机房间</h1><p>这个页面不会读取邀请、恢复凭证或请求 <code>/api/rooms</code>。公开链接提供真实家庭单机流程与脚本化演示，但不会假装替班者已经在线。</p><div class="join-safety"><span>◎</span><div><strong>本地完整体验</strong>在项目目录运行 <code>npm start</code>，再让照护者与替班者手机访问同一个 <code>http://电脑局域网IP:4173</code> 地址。</div></div><a class="join-button coral" href="./index.html?deployment=static-review">返回公开版</a></article><article class="join-card urgent-panel"><h2>为什么这样分开</h2><p>当前 Node 房间服务只适合黑客松期间同一局域网内的短时内存彩排。真正的公网双机服务还需要 HTTPS、持久会话、速率限制与受管部署。</p></article></section>`;
}

function render() {
  if (HOSTED_STATIC_REVIEW) return renderHostedBoundary();
  if (!roomId) return renderMissing();
  if (policyBlocked) return renderPolicyUpdateRequired();
  if (accessEnded) return renderTerminal();
  if (!relayToken) return inviteToken ? renderInvite() : renderTerminal();
  if (room && !snapshotVerified) {
    app.innerHTML = `<section class="join-page"><article class="join-card center"><div class="pair-orbit"><span></span></div><span class="join-kicker">VERIFYING LIVE ROOM</span><h2>正在核验房间，只保留直接联系</h2><p>服务确认当前会话前，不显示缓存指导，也不接受记录操作。</p></article>${callOnlyMarkup()}</section>`;
    return;
  }
  if (!room) {
    app.innerHTML = `<section class="join-page"><article class="join-card center"><div class="pair-orbit"><span></span></div><h2>正在恢复受限连接…</h2></article></section>`;
    return;
  }
  if (degraded) return renderDegraded();
  if (["revoked", "expired", "invalidated"].includes(room.status)) return renderTerminal();
  if (room.status === "paired" || room.status === "waiting") return renderPaired();
  if (room.status === "active") return renderActive();
  if (room.status === "debrief") return renderDebrief();
  if (room.status === "ended") return renderEnded();
  renderTerminal();
}

async function refresh() {
  if (!relayToken || !roomId || accessEnded) return;
  if (refreshInFlight) {
    refreshQueued = true;
    return;
  }
  refreshInFlight = true;
  try {
    const result = await request(`/api/rooms/${encodeURIComponent(roomId)}`);
    const wasDegraded = degraded;
    const accepted = acceptRoomSnapshot(result.room);
    snapshotVerified = true;
    setDegraded(false);
    if (accepted && (!document.activeElement || !["TEXTAREA", "INPUT"].includes(document.activeElement.tagName) || wasDegraded)) render();
  } catch (error) {
    if (error.status === 401 || error.status === 403 || error.status === 404) {
      accessEnded = true;
      accessEndedReason = error.status === 404 ? "room_missing" : "capability_closed";
      clearInterval(pollHandle);
      render();
    } else {
      setDegraded(true);
      render();
    }
  } finally {
    refreshInFlight = false;
    if (refreshQueued && !accessEnded) {
      refreshQueued = false;
      queueMicrotask(refresh);
    }
  }
}

async function mutate(type, extra = {}) {
  if (!room || pending || degraded) return false;
  pending = true;
  render();
  let retried = false;
  try {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const result = await request(`/api/rooms/${encodeURIComponent(roomId)}/actions`, {
          method: "POST",
          body: JSON.stringify({ type, ...actionContext(), ...extra }),
        });
        acceptRoomSnapshot(result.room);
        setDegraded(false);
        if (retried) toast("房间刚刚更新；已自动同步并完成本次操作");
        return true;
      } catch (error) {
        if (error.code !== "stale_revision" || attempt === 2) throw error;
        retried = true;
        const latest = await request(`/api/rooms/${encodeURIComponent(roomId)}`);
        acceptRoomSnapshot(latest.room);
        setDegraded(false);
      }
    }
  } catch (error) {
    toast(error.code === "stale_revision" ? "房间连续变化，正在自动同步；请稍后再试" : error.message);
    if (error.code === "stale_revision") await refresh();
    else if (!error.status) setDegraded(true);
    return false;
  } finally {
    pending = false;
    render();
  }
  return false;
}

document.addEventListener("submit", async (event) => {
  if (event.target.id === "phrase-form") {
    event.preventDefault();
    const data = new FormData(event.target);
    const phraseValue = data.get("phrase");
    const expectedRelayName = data.get("expectedRelayName");
    pending = true;
    renderInvite();
    try {
      const result = await request(`/api/rooms/${encodeURIComponent(roomId)}/join`, {
        method: "POST",
        body: JSON.stringify({ inviteToken, phrase: phraseValue, expectedRelayName }),
      });
      relayToken = result.relayToken;
      relayParticipantId = result.participantId;
      relaySessionId = result.sessionId;
      acceptRoomSnapshot(result.room, { force: true });
      snapshotVerified = true;
      sessionStorage.removeItem(pendingKey());
      inviteToken = "";
      setDegraded(false);
      startPolling();
      toast("核对成功，已建立替班者受限连接");
    } catch (error) {
      toast(error.code === "phrase_mismatch" ? "短语不一致，请重新向照护者核对" : error.code === "relay_name_mismatch" ? "姓名与照护者预先填写的替班者不一致" : error.message);
    } finally {
      pending = false;
      render();
    }
  } else if (event.target.id === "note-form") {
    event.preventDefault();
    const field = document.getElementById("relay-note");
    const text = field?.value.trim() || "";
    if (!text) return toast("请先写下一个现场事实");
    await mutate("relay.note", { text });
  } else if (event.target.id === "search-form") {
    event.preventDefault();
    const query = document.getElementById("relay-search")?.value.trim() || "";
    if (!query) return toast("请先描述眼前实际发生的事");
    await mutate("relay.search", { query });
  } else if (event.target.id === "relay-checkin-form") {
    event.preventDefault();
    const response = {
      ableToHandle: document.getElementById("relay-able")?.value || null,
      uncertainStep: document.getElementById("relay-uncertain")?.value.trim() || "",
      contactedCaregiver: document.getElementById("relay-contacted")?.value || null,
      feltUnsafe: document.getElementById("relay-unsafe")?.value === "" ? null : document.getElementById("relay-unsafe")?.value === "true",
      choice: document.getElementById("relay-choice")?.value || null,
      notes: document.getElementById("relay-checkin-notes")?.value.trim() || "",
    };
    response.partial = [response.ableToHandle, response.contactedCaregiver, response.feltUnsafe, response.choice].some((value) => value == null) || (!response.uncertainStep && response.ableToHandle !== "yes");
    await mutate("relay.checkin", { response });
  }
});

document.addEventListener("click", async (event) => {
  const phoneLink = event.target.closest("a[href^='tel:']");
  if (phoneLink && room?.status === "active" && !pending && !degraded) {
    event.preventDefault();
    const target = phoneLink.getAttribute("href") === phoneHref(room.family.emergencyService) ? "emergency-service" : "caregiver";
    await mutate("relay.contact-opened", { target });
    location.href = phoneLink.href;
    return;
  }
  const trigger = event.target.closest("[data-relay-action]");
  if (!trigger) return;
  const action = trigger.dataset.relayAction;
  if (action === "acknowledge") {
    const acknowledgements = [...document.querySelectorAll("input[name='relayAck']")];
    if (acknowledgements.length !== 4 || !acknowledgements.every((input) => input.checked)) return toast("请逐项核对四项内容后再确认");
    await mutate("relay.acknowledge", {
      scopeAcknowledged: true,
      currentGuideAcknowledged: true,
      redLinesAcknowledged: true,
      contactsAcknowledged: true,
    });
  } else if (action === "task") await mutate("relay.task", { index: Number(trigger.dataset.index) });
  else if (action === "ready") await mutate("relay.ready");
  else if (action === "alert") {
    const text = room.redLines[0] || "出现本家庭红线或不确定的紧急情况";
    const raised = await mutate("relay.alert", { text });
    if (raised) await mutate("relay.contact-opened", { target: "caregiver" });
    location.href = phoneHref(room.family.caregiverPhone);
  }
});

function startPolling() {
  clearInterval(pollHandle);
  pollHandle = setInterval(refresh, 900);
  startCountdown();
}

render();
if (relayToken && !HOSTED_STATIC_REVIEW) {
  refresh();
  startPolling();
}
