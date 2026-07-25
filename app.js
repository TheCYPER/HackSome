const STORAGE_KEY = "relay-rehearsal-demo-v1";
const AUTHORITY_KEY = "relay-rehearsal-consent-authority-v1";
const COMPANION_KEY = "relay-rehearsal-companion-v1";
const COMPANION_REVOCATION_KEY = "relay-rehearsal-companion-revocation-v1";
const SCHEMA_VERSION = 7;
const SafetyPolicy = window.RelaySafetyPolicy;
if (!SafetyPolicy?.VERSION) throw new Error("Matching safety policy failed to load");
const OutcomeModel = window.RelayOutcomeModel;
if (!OutcomeModel?.VERSION) throw new Error("Outcome model failed to load");
const SOURCE_IDS = Object.freeze({
  CAREGIVER: "caregiver",
  RECIPIENT: "recipient",
  RELAY: "relay",
  PROFESSIONAL: "professional-community-nurse",
});
const APP_BUILD = "2026.07.25-production-v2";

function isLocalExperienceHost(hostname = location.hostname) {
  const host = String(hostname || "").replace(/^\[|\]$/g, "").toLowerCase();
  if (!host || host === "localhost" || host === "::1" || host.endsWith(".local")) return true;
  if (/^127\./.test(host) || /^10\./.test(host) || /^192\.168\./.test(host) || /^172\.(1[6-9]|2\d|3[01])\./.test(host)) return true;
  return /^(fc|fd|fe[89ab])/i.test(host);
}

const DEPLOYMENT_MODE = new URLSearchParams(location.search).get("deployment") === "static-review" || !isLocalExperienceHost()
  ? "hosted-static-review"
  : "local-full";
const HOSTED_STATIC_REVIEW = DEPLOYMENT_MODE === "hosted-static-review";
document.documentElement.dataset.deploymentMode = DEPLOYMENT_MODE;
document.documentElement.dataset.build = APP_BUILD;

function demoOutcomeRecords() {
  const participants = { caregiver: { id: SOURCE_IDS.CAREGIVER, label: "周岚" }, substitute: { id: SOURCE_IDS.RELAY, label: "林珊" }, careRecipient: { id: SOURCE_IDS.RECIPIENT, label: "周琴" } };
  const base = { consentRevision: 1, guideScope: [{ id: "meal", version: 1, title: "她说不饿时", source: "周琴本人", actorId: SOURCE_IDS.RECIPIENT, level: "here", rule: "现场可处理" }], redLines: ["跌倒", "走失", "无法唤醒"], participants, policyVersion: SafetyPolicy.VERSION, safetyRevision: "demo-scope-v1", demo: true };
  const facts = (endedAt, seconds, steps, queued = 0, gaps = [], alerts = 0, contacts = []) => ({ endedAt, recordedAt: endedAt, actualElapsedSeconds: seconds, completedSteps: steps, routineUpdatesQueued: queued, pendingGaps: gaps, urgentAlertsRaised: alerts, contactActionsOpened: contacts });
  const caregiver = (submittedAt, choice, confidence, overrides = {}) => ({ submittedAt, restHappened: "yes", phoneChecks: "1-2", nonurgentInterrupted: "no", confidence, feltUnsafe: false, choice, partial: false, ...overrides });
  const substitute = (submittedAt, choice, overrides = {}) => ({ submittedAt, ableToHandle: "yes", uncertainStep: "没有仍不确定的步骤", contactedCaregiver: "no", feltUnsafe: false, choice, partial: false, ...overrides });
  return [
    OutcomeModel.createSession({ ...base, id: "demo-session-observe-20260718", stage: "observe", plannedDurationMinutes: 5, mode: "single-device", startedAt: "2026-07-18T09:00:00.000Z", status: "completed", facts: facts("2026-07-18T09:05:12.000Z", 312, [true, true, true]), checkIns: { caregiver: caregiver("2026-07-18T09:07:00.000Z", "extend", 3, { restHappened: "not-planned", phoneChecks: "0" }), substitute: substitute("2026-07-18T09:06:00.000Z", "extend"), careRecipient: { submittedAt: "2026-07-18T09:08:00.000Z", response: "answered", comfort: "comfortable", preference: "希望下次仍先说明谁会陪我。", partial: false } } }),
    OutcomeModel.createSession({ ...base, id: "demo-session-interrupted-20260720", stage: "short-leave", plannedDurationMinutes: 20, mode: "two-device", startedAt: "2026-07-20T08:40:00.000Z", status: "interrupted", facts: facts("2026-07-20T08:47:24.000Z", 444, [true, false, false], 1, [{ id: "demo-gap-medical", risk: "medical", status: "resolved" }], 1, [{ at: "2026-07-20T08:46:40.000Z", target: "caregiver" }]), checkIns: { caregiver: caregiver("2026-07-20T08:52:00.000Z", "step-back", 2, { restHappened: "no", nonurgentInterrupted: "yes", feltUnsafe: true }), substitute: substitute("2026-07-20T08:50:00.000Z", "step-back", { ableToHandle: "no", uncertainStep: "出现脸色变化时停止彩排并直接联系", contactedCaregiver: "yes", feltUnsafe: true }), careRecipient: { submittedAt: "2026-07-20T08:55:00.000Z", response: "not-asked", partial: true } } }),
    OutcomeModel.createSession({ ...base, id: "demo-session-repeat-20260722", stage: "short-leave", plannedDurationMinutes: 20, mode: "two-device", startedAt: "2026-07-22T08:30:00.000Z", status: "completed", facts: facts("2026-07-22T08:50:20.000Z", 1220, [true, true, true], 2), checkIns: { caregiver: caregiver("2026-07-22T08:55:00.000Z", "repeat", 3), substitute: substitute("2026-07-22T08:53:00.000Z", "extend", { ableToHandle: "partly", uncertainStep: "仍想再练一次普通记录的收尾" }), careRecipient: { submittedAt: "2026-07-22T08:58:00.000Z", response: "declined", partial: false } } }),
    OutcomeModel.createSession({ ...base, id: "demo-session-repeat-20260724", stage: "short-leave", plannedDurationMinutes: 20, mode: "two-device", startedAt: "2026-07-24T08:30:00.000Z", status: "completed", facts: facts("2026-07-24T08:50:36.000Z", 1236, [true, true, true], 3), checkIns: { caregiver: caregiver("2026-07-24T08:55:00.000Z", "repeat", 4, { phoneChecks: "1-2" }), substitute: substitute("2026-07-24T08:53:00.000Z", "repeat"), careRecipient: { submittedAt: "2026-07-24T08:58:00.000Z", response: "answered", comfort: "comfortable", preference: "下次可以保持同样的晚饭安排。", partial: false } } }),
  ];
}

const icons = {
  home: "i-home", guides: "i-book", rehearsal: "i-route", rest: "i-moon",
};

const navItems = [
  { id: "home", label: "现在", title: "现在由谁接班", eyebrow: "家庭当前状态" },
  { id: "guides", label: "已确认做法", title: "只用有来源的做法", eyebrow: "可用范围与缺口" },
  { id: "rehearsal", label: "三档彩排", title: "下一次练哪一档", eyebrow: "在旁 → 短时 → 安静" },
  { id: "rest", label: "安静离班", title: "普通事情结束后再看", eyebrow: "受保护的休息时间" },
];

const demoState = {
  schemaVersion: SCHEMA_VERSION,
  mode: "demo",
  meta: { updatedAt: 0 },
  onboarding: { status: "complete", step: 6, consentDecision: "granted", redLinesReviewedAt: "2026-07-20T09:00:00.000Z" },
  guideFilter: "all",
  stageOneCompleted: true,
  rehearsalCompleted: false,
  quietInbox: 2,
  activeRest: null,
  activeRehearsal: null,
  sessions: demoOutcomeRecords(),
  recommendationOverride: null,
  demoJourney: { step: 0, role: "caregiver", knownSeen: false, ordinarySeen: false, medicalSeen: false, sampleSessionId: null, finished: false },
  appliedRemoteSessionIds: [],
  debriefs: [],
  gaps: [],
  revokedGuideIds: [],
  confirmations: [
    { id: "seed-consent-1", type: "participation", status: "current", actorId: SOURCE_IDS.RECIPIENT, consentRevision: 1, confirmedAt: "2026-07-20T09:00:00.000Z" },
    { id: "seed-confirm-meal", type: "guide", status: "current", actorId: SOURCE_IDS.RECIPIENT, guideId: "meal", consentRevision: 1, confirmedAt: "2026-07-21T09:00:00.000Z" },
    { id: "seed-confirm-walk", type: "guide", status: "current", actorId: SOURCE_IDS.CAREGIVER, guideId: "walk", confirmedAt: "2026-07-19T09:00:00.000Z" },
    { id: "seed-confirm-tea", type: "guide", status: "current", actorId: SOURCE_IDS.RECIPIENT, guideId: "tea", consentRevision: 1, confirmedAt: "2026-07-24T09:00:00.000Z" },
    { id: "seed-confirm-mood", type: "guide", status: "current", actorId: SOURCE_IDS.RECIPIENT, guideId: "mood", consentRevision: 1, confirmedAt: "2026-07-17T09:00:00.000Z" },
    { id: "seed-confirm-fall", type: "guide", status: "current", actorId: SOURCE_IDS.PROFESSIONAL, guideId: "fall", confirmedAt: "2026-06-30T09:00:00.000Z" },
  ],
  recipientConsent: { status: "granted", revision: 1, grantedAt: "2026-07-20T09:00:00.000Z", withdrawnAt: null },
  family: {
    caregiverName: "周岚",
    caregiverPhone: "13800138000",
    recipientName: "周琴",
    recipientConsented: true,
    relayName: "林珊",
    emergencyContactName: "林珊",
    emergencyContactPhone: "13900139000",
    emergencyService: "120",
    redLines: ["跌倒", "走失", "无法唤醒"],
    restGoal: { title: "一个人去河边散步", date: "周六 16:00", duration: 60 },
  },
  activity: [
    { title: "演示记录 · 在旁观察晚餐", note: "应用记录 3/3 步；参与者自报见结果历史", date: "7月18日", score: "演示" },
    { title: "演示记录 · 短时离开", note: "应用记录 20分36秒；参与者都选择重复本级", date: "7月24日", score: "演示" },
  ],
  guides: [
    { id: "meal", version: 1, status: "usable", confirmationId: "seed-confirm-meal", provenance: { actorId: SOURCE_IDS.RECIPIENT, actorType: "careRecipient", labelAtConfirmation: "周琴本人", consentRevision: 1 }, icon: "i-chef", tone: "coral", category: "daily", title: "她说不饿时", summary: "先把汤放在桌上，给她十分钟。不要反复劝，也不用换一道菜。", source: "周琴本人", sourceAvatar: "琴", sourceClass: "avatar-caregiver", updated: "3天前确认", level: "here", rule: "现场可处理", audio: true },
    { id: "walk", version: 1, status: "usable", confirmationId: "seed-confirm-walk", provenance: { actorId: SOURCE_IDS.CAREGIVER, actorType: "caregiver", labelAtConfirmation: "周岚" }, icon: "i-walk", tone: "mint", category: "daily", title: "拒绝出门散步", summary: "问她想去楼下看花，还是只在走廊走一圈；两个都不愿意就取消。", source: "周岚", sourceAvatar: "岚", sourceClass: "avatar-caregiver", updated: "5天前确认", level: "here", rule: "现场可处理", audio: true },
    { id: "tea", version: 1, status: "usable", confirmationId: "seed-confirm-tea", provenance: { actorId: SOURCE_IDS.RECIPIENT, actorType: "careRecipient", labelAtConfirmation: "周琴本人", consentRevision: 1 }, icon: "i-cup", tone: "yellow", category: "daily", title: "下午加餐与喝水", summary: "三点半把温水放在右手边。她喜欢用蓝色杯子，不需要提醒喝完。", source: "周琴本人", sourceAvatar: "琴", sourceClass: "avatar-caregiver", updated: "今天确认", level: "here", rule: "现场可处理", audio: false },
    { id: "mood", version: 1, status: "usable", confirmationId: "seed-confirm-mood", provenance: { actorId: SOURCE_IDS.RECIPIENT, actorType: "careRecipient", labelAtConfirmation: "周琴本人", consentRevision: 1 }, icon: "i-user", tone: "blue", category: "preference", title: "她想一个人待着", summary: "告诉她你会在客厅，二十分钟后再来。不要一直站在门口询问。", source: "周琴本人", sourceAvatar: "琴", sourceClass: "avatar-caregiver", updated: "1周前确认", level: "later", rule: "稍后告知", audio: true },
    { id: "fall", version: 1, professionalReferenceId: "demo-fall-immediate-v1", status: "usable", confirmationId: "seed-confirm-fall", provenance: { actorId: SOURCE_IDS.PROFESSIONAL, actorType: "professional", labelAtConfirmation: "内置演示专业引用" }, icon: "i-alert", tone: "red", category: "urgent", title: "发生跌倒", summary: "立即联系主要照护者；有紧急危险时使用本房间显示的当地紧急服务号码。", source: "内置演示专业引用", sourceAvatar: "专", sourceClass: "avatar-relay", updated: "随安全策略提供", level: "now", rule: "立即联系", audio: false, highRisk: true, policyVersion: SafetyPolicy.VERSION },
  ],
};

function emptyState(mode = null) {
  return {
    schemaVersion: SCHEMA_VERSION,
    mode,
    meta: { updatedAt: 0 },
    onboarding: { status: mode === "real" ? "in-progress" : "not-started", step: 1, consentDecision: "pending", redLinesReviewedAt: null },
    guideFilter: "all",
    stageOneCompleted: false,
    rehearsalCompleted: false,
    quietInbox: 0,
    activeRest: null,
    activeRehearsal: null,
    sessions: [],
    recommendationOverride: null,
    demoJourney: mode === "demo" ? { step: 0, role: "caregiver", knownSeen: false, ordinarySeen: false, medicalSeen: false, sampleSessionId: null, finished: false } : null,
    appliedRemoteSessionIds: [],
    debriefs: [],
    gaps: [],
    revokedGuideIds: [],
    confirmations: [],
    recipientConsent: { status: "withdrawn", revision: 1, grantedAt: null, withdrawnAt: null },
    family: {
      caregiverName: "",
      caregiverPhone: "",
      recipientName: "",
      recipientConsented: false,
      relayName: "",
      emergencyContactName: "",
      emergencyContactPhone: "",
      emergencyService: "",
      redLines: [],
      restGoal: { title: "", date: "", duration: 20 },
    },
    activity: [],
    guides: [],
  };
}

let state = loadState();
let currentPage = state.activeRest ? "rest" : normalizePage(location.hash.slice(1));
let session = state.activeRehearsal ? { ...state.activeRehearsal, tasks: [...(state.activeRehearsal.tasks || [false, false, false])] } : null;
let restSession = state.activeRest ? { ...state.activeRest } : null;
let tickHandle = null;
let previousFocus = null;
let companionSession = loadCompanionSession();
let companionRoom = null;
let companionPollHandle = null;
let companionCountdownHandle = null;
let companionSnapshotSyncHandle = null;
let companionDegraded = false;
let companionPending = false;
let companionPolicyBlocked = false;
let companionRefreshPromise = null;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const icon = (name, className = "") => `<svg class="${className}" aria-hidden="true"><use href="#${name}"></use></svg>`;
const escapeHTML = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
const phoneHref = (value = "") => `tel:${String(value).replace(/[^\d+]/g, "")}`;

function loadCompanionSession() {
  try {
    const parsed = JSON.parse(localStorage.getItem(COMPANION_KEY));
    if (!parsed?.roomId || !parsed?.caregiverToken) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveCompanionSession() {
  if (companionSession) localStorage.setItem(COMPANION_KEY, JSON.stringify(companionSession));
  else localStorage.removeItem(COMPANION_KEY);
}

function acceptCompanionRoomSnapshot(nextRoom, { force = false } = {}) {
  if (!nextRoom || typeof nextRoom !== "object") return false;
  const currentRevision = Number(companionRoom?.revision);
  const nextRevision = Number(nextRoom.revision);
  if (
    !force
    && companionRoom?.id === nextRoom.id
    && Number.isFinite(currentRevision)
    && Number.isFinite(nextRevision)
    && nextRevision < currentRevision
  ) {
    return false;
  }
  companionRoom = nextRoom;
  if (companionSession) {
    companionSession.sessionId = nextRoom.sessionId;
    companionSession.participantId = nextRoom.participantId;
    saveCompanionSession();
  }
  return true;
}

function clearCompanionLocal() {
  clearInterval(companionPollHandle);
  clearInterval(companionCountdownHandle);
  clearTimeout(companionSnapshotSyncHandle);
  companionPollHandle = null;
  companionCountdownHandle = null;
  companionSnapshotSyncHandle = null;
  companionSession = null;
  companionRoom = null;
  companionDegraded = false;
  companionPending = false;
  saveCompanionSession();
}

function companionSafetyRevision(candidateState = state) {
  const guides = usableGuides(candidateState).map((guide) => {
    const highRisk = SafetyPolicy.classifyFields([guide.title, guide.summary]).highRisk;
    return {
      id: guide.id,
      version: guide.version,
      title: guide.title,
      summary: guide.summary,
      actorId: guide.provenance?.actorId,
      professionalReferenceId: guide.professionalReferenceId || null,
      level: highRisk ? SafetyPolicy.IMMEDIATE_LEVEL : guide.level,
      rule: highRisk ? SafetyPolicy.IMMEDIATE_RULE : guide.rule,
      highRisk,
    };
  }).sort((left, right) => String(left.id).localeCompare(String(right.id)));
  const material = JSON.stringify({
    policyVersion: SafetyPolicy.VERSION,
    redLines: (candidateState.family.redLines || []).filter(Boolean),
    caregiverPhone: candidateState.family.caregiverPhone || "",
    emergencyService: candidateState.family.emergencyService || "",
    guides,
  });
  let hash = 2166136261;
  for (let index = 0; index < material.length; index += 1) {
    hash ^= material.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `scope-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function companionActionContext(room = companionRoom) {
  if (!room) return {};
  return {
    expectedRevision: room.revision,
    actionId: companionActionId(),
    sessionId: room.sessionId,
    participantId: room.participantId,
    consentRevision: room.consentRevision,
    guideVersion: room.guideVersion,
    safetyRevision: room.safetyRevision,
  };
}

function companionCountdown(room = companionRoom) {
  if (!room?.startedAt) return `${String(room?.duration || 0).padStart(2, "0")}:00`;
  const elapsed = Math.max(0, Math.floor((Date.now() - new Date(room.startedAt).getTime()) / 1000));
  const remaining = Math.max(0, room.duration * 60 - elapsed);
  return `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
}

function startCompanionCountdown() {
  clearInterval(companionCountdownHandle);
  if (companionRoom?.status !== "active") return;
  const update = () => {
    const timer = document.getElementById("companion-countdown");
    if (timer) timer.textContent = companionCountdown();
  };
  update();
  companionCountdownHandle = setInterval(update, 1000);
}

function companionActionId() {
  return crypto.randomUUID ? crypto.randomUUID() : `caregiver-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function companionRequest(pathname, options = {}) {
  if (HOSTED_STATIC_REVIEW) {
    const error = new Error("公开评审版不连接临时双机房间服务；请在本地完整体验中配对");
    error.status = 503;
    error.code = "hosted_static_review";
    throw error;
  }
  const headers = { "Content-Type": "application/json", [SafetyPolicy.HEADER]: SafetyPolicy.VERSION, ...(options.headers || {}) };
  if (companionSession?.caregiverToken) headers.Authorization = `Bearer ${companionSession.caregiverToken}`;
  const response = await fetch(pathname, { ...options, headers, cache: "no-store" });
  let result = {};
  try { result = await response.json(); } catch { /* The status below remains authoritative. */ }
  if (!response.ok) {
    const error = new Error(result.error?.message || `连接服务返回 ${response.status}`);
    error.status = response.status;
    error.code = result.error?.code || "request_failed";
    if (error.code === "policy_update_required") companionPolicyBlocked = true;
    throw error;
  }
  if (result.room && result.room.policyVersion !== SafetyPolicy.VERSION) {
    companionPolicyBlocked = true;
    const error = new Error("安全策略版本已变化，请刷新页面后继续");
    error.status = 409;
    error.code = "policy_update_required";
    throw error;
  }
  companionPolicyBlocked = false;
  return result;
}

function companionStatusLabel(status) {
  return {
    waiting: "等待替班者核对",
    paired: "替班者已配对",
    active: "双机彩排进行中",
    debrief: "现场结束 · 等待来源复盘",
    ended: "双机彩排已结束",
    invalidated: "家庭内容变化 · 房间已失效",
    revoked: "连接已撤销",
    expired: "邀请已到期",
  }[status] || "正在恢复连接";
}

function companionStageDetails(stageOverride = "") {
  const offDutyPreparation = currentPage === "rest" && (state.mode === "demo" || state.rehearsalCompleted);
  const stage = stageOverride || (offDutyPreparation ? "quiet-handoff" : state.stageOneCompleted ? (state.rehearsalCompleted ? "quiet-handoff" : "short-leave") : "observe");
  const shortMinutes = state.mode === "real"
    ? Math.max(10, Math.min(60, Number(state.family.restGoal.duration) || 20))
    : 20;
  return {
    stage,
    duration: stage === "observe" ? 5 : stage === "quiet-handoff" ? 90 : shortMinutes,
    label: stage === "observe" ? "在旁观察" : stage === "quiet-handoff" ? "安静接班" : `短时离开 ${shortMinutes} 分钟`,
  };
}

function companionTimelineMarkup(room) {
  const events = (room?.timeline || []).filter((event) => !["room.created"].includes(event.type)).slice(-5).reverse();
  if (!events.length) return `<p class="companion-empty">配对和现场操作会在这里实时出现。</p>`;
  return `<div class="companion-events">${events.map((event) => `<div class="${event.urgent ? "urgent" : ""}"><span><b>${event.urgent ? "红线 · " : ""}${escapeHTML(event.text)}</b><small>${escapeHTML(event.actor === "relay" ? state.family.relayName : event.actor === "caregiver" ? state.family.caregiverName : "系统")}</small></span><time>${new Date(event.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time></div>`).join("")}</div>`;
}

function caregiverDirectCallMarkup(className = "") {
  const contactName = state.family.emergencyContactName || "紧急联系人";
  const contactPhone = state.family.emergencyContactPhone || state.family.caregiverPhone;
  return `<div class="direct-call-row ${className}" aria-label="始终可用的直接电话"><a class="btn btn-secondary btn-small" href="${phoneHref(contactPhone)}">${icon("i-phone")}联系${escapeHTML(contactName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(state.family.emergencyService)}">${icon("i-alert")}拨打 ${escapeHTML(state.family.emergencyService)}</a></div>`;
}

function reviewedGuideScopeMarkup(room = companionRoom) {
  const guides = room?.searchGuides || [];
  return `<div class="companion-reviewed-guides" aria-label="本次完整可搜索指导范围">${guides.map((guide) => `<article data-reviewed-guide="${escapeHTML(guide.id)}"><span><b>${escapeHTML(guide.title)}</b><small>${escapeHTML(guide.summary)}</small></span><span><strong>v${Number(guide.version)}</strong><small>${escapeHTML(guide.source)} · ${escapeHTML(guide.rule)}</small></span></article>`).join("")}</div>`;
}

function companionCardMarkup() {
  const guide = focusGuide();
  const room = companionRoom;
  const details = companionStageDetails(room?.stage || "");
  const recommended = details.stage !== "observe";
  const status = room?.status;
  const connection = companionDegraded
    ? `<span class="companion-health degraded">连接中断 · 保留只读画面</span>`
    : room ? `<span class="companion-health">${room.relayOnline ? "两台手机在线" : status === "waiting" ? "邀请待使用" : "正在等待对方重连"}</span>` : "";

  if (HOSTED_STATIC_REVIEW) {
    return `<article class="card companion-card hosted-boundary" id="companion-card">
      <div class="companion-heading"><span class="companion-device">${icon("i-lock")}</span><span><small>PUBLIC REVIEW BUILD · ${APP_BUILD}</small><h3>公开评审版不创建双机房间</h3></span><span class="status-pill recommended">静态边界</span></div>
      <p>这条公开链接可完整体验演示导览、单机彩排、严格匹配、结果历史与撤回；它不会把静态页面伪装成在线房间服务，也不会向 <code>/api/rooms</code> 发请求。</p>
      <div class="companion-scope"><span>${icon("i-check")}公开版：脚本化演示与本机数据</span><span>${icon("i-phone")}双机版：同一局域网内本地运行</span></div>
      <button class="btn btn-primary btn-wide" data-action="show-local-full-experience">${icon("i-home")}本地完整体验 · 查看启动与手机加入方法</button>
      ${caregiverDirectCallMarkup("companion-call-links")}
    </article>`;
  }

  if (companionPolicyBlocked) {
    return `<article class="card companion-card" id="companion-card"><div class="companion-heading"><span class="companion-device">${icon("i-alert")}</span><span><small>SAFETY POLICY UPDATE REQUIRED</small><h3>刷新更新后再继续双机彩排</h3></span></div><p>浏览器与房间服务的安全策略版本不一致。创建、加入、写入和搜索都已关闭；刷新并取得匹配版本前不会显示或沿用房间指导。</p>${caregiverDirectCallMarkup("companion-live-calls")}</article>`;
  }

  if (!companionSession) {
    return `<article class="card companion-card" id="companion-card">
      <div class="companion-heading"><span class="companion-device">${icon("i-phone")}</span><span><small>TWO-DEVICE REHEARSAL</small><h3>${recommended ? "推荐：让替班者用自己的手机加入" : "让替班者用自己的手机加入"}</h3></span><span class="status-pill ${recommended ? "recommended" : ""}">${recommended ? "推荐路径" : "双机"}</span></div>
      <p>创建 15 分钟有效的一次性链接，再当面核对姓名和短语。开始前替班者会逐条看到并确认本次完整可搜索指导范围、版本、来源、红线和直接联系。</p>
      <div class="companion-scope"><span>${icon("i-lock")}看不到家庭主页和本次范围外指导</span><span>${icon("i-route")}${escapeHTML(details.label)}</span></div>
      <button class="btn ${guide && isRecipientAuthorized() ? "btn-primary" : "btn-secondary"} btn-wide" data-action="create-companion" ${guide && isRecipientAuthorized() ? "" : "disabled"}>${icon("i-plus")}${recommended ? "推荐 · " : ""}邀请替班者的手机</button>
      ${caregiverDirectCallMarkup("companion-call-links")}
    </article>`;
  }

  if (!room) {
    return `<article class="card companion-card" id="companion-card"><div class="companion-heading"><span class="companion-device">${icon("i-phone")}</span><span><small>TWO-DEVICE REHEARSAL</small><h3>正在恢复双机连接…</h3></span></div><p>家庭页面仍可使用；连接恢复前不会接受现场操作。</p><button class="btn btn-secondary btn-wide" data-action="refresh-companion">重新连接</button></article>`;
  }

  const invitation = companionSession.invitation;
  const waitingMarkup = status === "waiting" ? `
    <div class="invite-proof"><div><small>核对短语</small><strong>${escapeHTML(invitation?.phrase || "请重新签发")}</strong></div><div><small>有效至</small><strong>${invitation?.expiresAt ? new Date(invitation.expiresAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "已遗失"}</strong></div></div>
    <button class="btn btn-primary btn-wide" data-action="show-companion-invite">${icon("i-phone")}查看链接与核对短语</button>` : "";
  const pairedMarkup = status === "paired" ? `<div class="paired-proof"><span>${icon("i-check")}</span><span><b>${escapeHTML(state.family.relayName)}已通过姓名与短语核对</b><small>${room.relayOnline ? "替班者手机在线" : "对方暂时离线，仍可等待自动重连"}</small></span></div><div class="role-confirmations"><span class="${room.confirmations.caregiver ? "done" : ""}">${room.confirmations.caregiver ? icon("i-check") : icon("i-lock")}照护者确认</span><span class="${room.confirmations.relay ? "done" : ""}">${room.confirmations.relay ? icon("i-check") : icon("i-lock")}替班者确认</span></div>${room.confirmations.caregiver ? "" : `<button class="btn btn-secondary btn-wide" data-action="acknowledge-companion-caregiver">${icon("i-shield")}核对并确认本次范围</button>`}<button class="btn btn-coral btn-wide" data-action="start-companion" ${room.relayOnline && room.confirmations.caregiver && room.confirmations.relay && !companionPending ? "" : "disabled"}>${icon("i-play")}${room.confirmations.caregiver && room.confirmations.relay ? "开始双机彩排" : "等待双方逐项确认"}</button>` : "";
  const activeMarkup = status === "active" ? `<div class="companion-live-metrics"><div><small>两端共享倒计时</small><strong id="companion-countdown">${companionCountdown(room)}</strong></div><div><small>${room.stage === "quiet-handoff" ? "安静队列" : "普通记录"}</small><strong>${room.quietCount || 0}</strong></div><div><small>待确认缺口</small><strong>${room.pendingGapCount || 0}</strong></div></div><div class="companion-task-progress">${room.tasks.map((done, index) => `<span class="${done ? "done" : ""}">${done ? icon("i-check") : index + 1}</span>`).join("")}<strong>${room.tasks.filter(Boolean).length} / 3 步已同步</strong></div>${companionTimelineMarkup(room)}${caregiverDirectCallMarkup("companion-live-calls")}<button class="btn btn-secondary btn-wide" data-action="end-companion">${icon("i-close")}结束现场并进入复盘</button>` : "";
  const debriefMarkup = status === "debrief" ? `<div class="companion-summary"><div><strong>${room.summary?.completedTasks || 0}/3</strong><small>完成步骤</small></div><div><strong>${room.summary?.notes || 0}</strong><small>普通记录</small></div><div><strong>${room.summary?.facts?.urgentAlertsRaised || 0}</strong><small>紧急事件</small></div></div><p class="companion-end-note">应用记录：${escapeHTML(OutcomeModel.STATUS_LABELS[room.summary?.status] || room.summary?.status || "已结束")} · 联系操作只表示页面已打开，不代表电话接通。</p>${companionTimelineMarkup(room)}<div class="role-confirmations"><span class="${room.checkIns?.caregiver ? "done" : ""}">${room.checkIns?.caregiver ? icon("i-check") : icon("i-lock")}照护者自报</span><span class="${room.checkIns?.substitute ? "done" : ""}">${room.checkIns?.substitute ? icon("i-check") : icon("i-lock")}替班者自报</span></div><button class="btn btn-secondary btn-wide" data-action="open-companion-caregiver-checkin">${room.checkIns?.caregiver ? "补充照护者回看" : "填写照护者自己的回看"}</button><button class="btn btn-primary btn-wide" data-action="open-companion-debrief">完成来源复盘</button>` : "";
  const ended = room.summary;
  const endedMarkup = status === "ended" ? `<div class="companion-summary"><div><strong>${ended?.completedTasks || 0}/3</strong><small>完成步骤</small></div><div><strong>${ended?.notes || 0}</strong><small>普通记录</small></div><div><strong>${ended?.facts?.urgentAlertsRaised || 0}</strong><small>紧急事件</small></div></div><p class="companion-end-note">应用记录：${escapeHTML(OutcomeModel.STATUS_LABELS[ended?.status] || ended?.status || "已结束")}</p><div class="role-confirmations"><span class="${room.checkIns?.caregiver ? "done" : ""}">${room.checkIns?.caregiver ? icon("i-check") : icon("i-lock")}照护者自报</span><span class="${room.checkIns?.substitute ? "done" : ""}">${room.checkIns?.substitute ? icon("i-check") : icon("i-lock")}替班者自报</span></div>${ended?.debrief ? `<p class="companion-end-note">${ended.debrief.outcome === "confirmed-guide" ? `复盘来源：${escapeHTML(ended.debrief.sourceLabel)} · ${escapeHTML(ended.debrief.gap)}` : `待确认缺口：${escapeHTML(ended.debrief.gap)}`}</p>` : ""}${ended?.caregiverNote ? `<p class="companion-end-note">照护者现场备注：${escapeHTML(ended.caregiverNote)}</p>` : ""}<button class="btn btn-secondary btn-wide" data-action="open-companion-caregiver-checkin">${room.checkIns?.caregiver ? "补充照护者回看" : "填写照护者自己的回看"}</button><button class="btn btn-secondary btn-wide" data-action="open-companion-recipient-checkin">记录本人可选回答</button><button class="btn btn-primary btn-wide" data-action="replace-companion-room">${icon("i-plus")}按建议档位创建新房间</button>` : "";
  const terminalMarkup = ["revoked", "expired"].includes(status) ? `<div class="paired-proof terminal"><span>${icon("i-lock")}</span><span><b>旧链接与旧替班者凭证均已失效</b><small>可以在同一房间重新签发一次性邀请。</small></span></div><button class="btn btn-primary btn-wide" data-action="reissue-companion">${icon("i-plus")}重新签发邀请</button>` : status === "invalidated" ? `<div class="paired-proof terminal"><span>${icon("i-lock")}</span><span><b>同意、指导、红线或电话已变化</b><small>旧房间保持关闭；请按当前家庭内容创建全新房间。</small></span></div><button class="btn btn-primary btn-wide" data-action="replace-companion-room">${icon("i-plus")}按当前内容创建新房间</button>` : "";

  return `<article class="card companion-card ${status === "active" ? "is-live" : ""}" id="companion-card">
    <div class="companion-heading"><span class="companion-device">${icon("i-phone")}</span><span><small>TWO-DEVICE REHEARSAL · v${room.revision}</small><h3>${companionStatusLabel(status)}</h3></span>${connection}</div>
    <p>本房间主要练“${escapeHTML(room.guide.title)}”，并允许搜索开始前双方确认的 ${room.searchGuides?.length || 0} 条版本化指导。每次操作都由服务器按角色和版本校验。</p>
    ${waitingMarkup}${pairedMarkup}${activeMarkup}${debriefMarkup}${endedMarkup}${terminalMarkup}
    ${!["ended", "revoked", "expired", "invalidated"].includes(status) ? `<div class="companion-danger-row"><button data-action="reissue-companion" ${["active", "debrief"].includes(status) ? "disabled" : ""}>作废并重发</button><button data-action="revoke-companion">撤销连接</button></div>` : ""}
  </article>`;
}

function updateCompanionCard() {
  const existing = document.getElementById("companion-card");
  if (existing) existing.outerHTML = companionCardMarkup();
}

function syncCompanionActiveOutcome() {
  if (!companionRoom?.startSnapshot || outcomeRecord(companionRoom.sessionId)) return;
  replaceOutcomeRecord(OutcomeModel.createSession({
    id: companionRoom.sessionId,
    stage: companionRoom.startSnapshot.stage,
    plannedDurationMinutes: companionRoom.startSnapshot.plannedDurationMinutes,
    consentRevision: companionRoom.startSnapshot.consentRevision,
    guideScope: companionRoom.startSnapshot.guideScope,
    redLines: companionRoom.startSnapshot.redLines,
    participants: companionRoom.startSnapshot.participants,
    mode: "two-device",
    startedAt: companionRoom.startSnapshot.startedAt,
    safetyRevision: companionRoom.startSnapshot.safetyRevision,
    policyVersion: companionRoom.startSnapshot.policyVersion,
  }));
  saveState();
}

function applyCompanionCompletion() {
  if (!companionRoom?.summary?.facts || !companionRoom?.startSnapshot) return;
  const debrief = companionRoom.summary?.debrief;
  const durableGapFacts = new Map();
  for (const gap of [
    ...(companionRoom.summary.facts.pendingGaps || []),
    ...(companionRoom.pendingGaps || []),
  ]) {
    const id = String(gap?.id || `room-gap-${durableGapFacts.size}`);
    const existing = durableGapFacts.get(id);
    durableGapFacts.set(id, {
      id,
      risk: gap?.risk === "medical" || existing?.risk === "medical" ? "medical" : "ordinary",
      status: gap?.status === "resolved" && existing?.status !== "pending" ? "resolved" : "pending",
      query: String(gap?.query || existing?.query || ""),
    });
  }
  if (debrief?.outcome === "pending-gap") {
    const debriefKey = normalizedQuery(debrief.gap);
    const alreadyAssociated = [...durableGapFacts.values()].some((gap) => gap.query && normalizedQuery(gap.query) === debriefKey);
    if (!alreadyAssociated) {
      durableGapFacts.set(`debrief-${companionRoom.id}`, {
        id: `debrief-${companionRoom.id}`,
        risk: debrief.risk === "medical" || SafetyPolicy.classifyText(debrief.gap).highRisk ? "medical" : "ordinary",
        status: "pending",
        query: debrief.gap,
      });
    }
  }
  const durableFacts = {
    ...companionRoom.summary.facts,
    pendingGaps: [...durableGapFacts.values()].map(({ id, risk, status }) => ({ id, risk, status })),
  };
  const serverRecord = OutcomeModel.createSession({
    id: companionRoom.sessionId,
    stage: companionRoom.startSnapshot.stage,
    plannedDurationMinutes: companionRoom.startSnapshot.plannedDurationMinutes,
    consentRevision: companionRoom.startSnapshot.consentRevision,
    guideScope: companionRoom.startSnapshot.guideScope,
    redLines: companionRoom.startSnapshot.redLines,
    participants: companionRoom.startSnapshot.participants,
    mode: "two-device",
    startedAt: companionRoom.startSnapshot.startedAt,
    safetyRevision: companionRoom.startSnapshot.safetyRevision,
    policyVersion: companionRoom.startSnapshot.policyVersion,
    status: companionRoom.summary.status || "interrupted",
    facts: durableFacts,
    checkIns: {
      caregiver: companionRoom.checkIns?.caregiver,
      substitute: companionRoom.checkIns?.substitute,
      careRecipient: outcomeRecord(companionRoom.sessionId)?.checkIns?.careRecipient,
    },
  });
  replaceOutcomeRecord(serverRecord);
  saveState();
  if (companionRoom?.status !== "ended" || companionSession?.completionApplied || state.appliedRemoteSessionIds.includes(companionRoom.sessionId)) return;
  const guide = usableGuideById(companionRoom.guide?.id);
  if (!guide || guide.version !== companionRoom.guide.version || !isRecipientAuthorized() || !debrief) return;
  for (const incoming of companionRoom.pendingGaps || []) {
    const key = incoming.normalizedQuery || normalizedQuery(incoming.query);
    const existing = state.gaps.find((gap) => gap.status === "pending" && gap.normalizedQuery === key);
    if (existing) {
      existing.encounters = Math.max(existing.encounters || 1, incoming.encounters || 1);
      existing.lastSeenAt = Date.now();
      existing.risk = incoming.risk === "medical" ? "medical" : existing.risk;
    } else {
      state.gaps.unshift({
        id: `companion-${companionRoom.id}-${incoming.id}`,
        query: incoming.query,
        normalizedQuery: key,
        status: "pending",
        risk: incoming.risk === "medical" ? "medical" : "ordinary",
        encounters: Math.max(1, Number(incoming.encounters) || 1),
        createdAt: Number(incoming.createdAt) || Date.now(),
        lastSeenAt: Date.now(),
        roomId: companionRoom.id,
      });
    }
  }
  state.debriefs.unshift({
    gap: debrief.gap,
    instruction: debrief.instruction,
    outcome: debrief.outcome,
    provenance: debrief.sourceId ? {
      actorId: debrief.sourceId,
      actorType: sourceDefinition(debrief.sourceId)?.actorType || "unverified",
      labelAtConfirmation: debrief.sourceLabel,
    } : null,
    risk: debrief.risk === "medical" ? "medical" : "ordinary",
    urgent: Boolean(debrief.urgent),
    policyVersion: debrief.policyVersion,
    createdAt: Date.now(),
    roomId: companionRoom.id,
  });
  if (debrief.outcome !== "confirmed-guide") {
    state.appliedRemoteSessionIds.push(companionRoom.sessionId);
    companionSession.completionApplied = true;
    saveCompanionSession();
    saveState();
    toast("这次没有升级接班阶段；复盘问题已进入待确认缺口");
    return;
  }
  if (debrief.policyVersion !== SafetyPolicy.VERSION || SafetyPolicy.classifyFields([debrief.gap, debrief.instruction]).highRisk) return;
  const source = sourceDefinition(debrief.sourceId);
  if (!source?.authorized) return;
  const existingGuide = usableGuides().find((item) => item.title === debrief.gap);
  const confirmationId = addConfirmation({
    type: "guide",
    actorId: debrief.sourceId,
    guideId: existingGuide?.id || null,
    consentRevision: debrief.sourceId === SOURCE_IDS.RECIPIENT ? state.recipientConsent.revision : null,
  });
  if (existingGuide) {
    const prior = state.confirmations.find((item) => item.id === existingGuide.confirmationId);
    if (prior) prior.status = "superseded";
    existingGuide.summary = debrief.instruction;
    existingGuide.updated = "刚刚由双机复盘确认";
    existingGuide.source = source.label;
    existingGuide.sourceAvatar = source.avatar;
    existingGuide.sourceClass = source.className;
    existingGuide.version += 1;
    existingGuide.confirmationId = confirmationId;
    existingGuide.provenance = {
      actorId: debrief.sourceId,
      actorType: source.actorType,
      labelAtConfirmation: debrief.sourceLabel,
      ...(debrief.sourceId === SOURCE_IDS.RECIPIENT ? { consentRevision: state.recipientConsent.revision } : {}),
    };
    existingGuide.level = "here";
    existingGuide.rule = "现场可处理";
    existingGuide.category = "daily";
    existingGuide.highRisk = false;
    existingGuide.policyVersion = SafetyPolicy.VERSION;
  } else {
    const guideId = `companion-debrief-${Date.now()}`;
    state.confirmations.find((item) => item.id === confirmationId).guideId = guideId;
    state.guides.unshift({
      id: guideId,
      version: 1,
      status: "usable",
      confirmationId,
      provenance: {
        actorId: debrief.sourceId,
        actorType: source.actorType,
        labelAtConfirmation: debrief.sourceLabel,
        ...(debrief.sourceId === SOURCE_IDS.RECIPIENT ? { consentRevision: state.recipientConsent.revision } : {}),
      },
      icon: "i-spark",
      tone: "mint",
      category: "daily",
      title: debrief.gap,
      summary: debrief.instruction,
      source: source.label,
      sourceAvatar: source.avatar,
      sourceClass: source.className,
      updated: "刚刚由双机复盘确认",
      level: "here",
      rule: "现场可处理",
      audio: false,
      highRisk: false,
      policyVersion: SafetyPolicy.VERSION,
      fromDebrief: true,
      roomId: companionRoom.id,
    });
  }
  const summary = companionRoom.summary || {};
  const date = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date());
  if (companionRoom.stage === "observe" && serverRecord.status === "completed") state.onboarding.status = "complete";
  if (!state.activity.some((item) => item.sessionId === companionRoom.sessionId)) state.activity.unshift({
    title: `双机${companionRoom.stage === "observe" ? "在旁观察" : companionRoom.stage === "short-leave" ? "短时离开" : "安静接班"} · ${guide.title}`,
    note: `应用记录：${OutcomeModel.STATUS_LABELS[serverRecord.status] || serverRecord.status}；完成 ${summary.completedTasks || 0}/3 步，普通记录 ${summary.notes || 0} 条，紧急事件 ${serverRecord.facts?.urgentAlertsRaised || 0} 条`,
    date,
    score: OutcomeModel.STATUS_LABELS[serverRecord.status] || serverRecord.status,
    stage: companionRoom.stage,
    focus: guide.title,
    guideId: guide.id,
    guideDependency: guideDependencySnapshot(guide),
    consentRevision: state.recipientConsent.revision,
    roomId: companionRoom.id,
    sessionId: companionRoom.sessionId,
  });
  companionSession.completionApplied = true;
  if (!state.appliedRemoteSessionIds.includes(companionRoom.sessionId)) state.appliedRemoteSessionIds.push(companionRoom.sessionId);
  saveCompanionSession();
  saveState();
}

async function refreshCompanionOnce({ announce = false } = {}) {
  if (!companionSession?.roomId || companionPending) return;
  try {
    const result = await companionRequest(`/api/rooms/${encodeURIComponent(companionSession.roomId)}`);
    const changed = !companionRoom || result.room.revision !== companionRoom.revision || result.room.relayOnline !== companionRoom.relayOnline;
    const accepted = acceptCompanionRoomSnapshot(result.room);
    companionDegraded = false;
    if (accepted) {
      syncCompanionActiveOutcome();
      applyCompanionCompletion();
    }
    if (accepted && changed) {
      updateCompanionCard();
      startCompanionCountdown();
    }
    if (announce) toast("双机状态已同步");
  } catch (error) {
    companionDegraded = true;
    updateCompanionCard();
    if (announce) toast(error.status === 401 ? "照护者凭证失效，请建立新房间" : "暂时无法连接双机服务");
  }
}

function refreshCompanion(options = {}) {
  if (companionRefreshPromise) return companionRefreshPromise;
  const pendingRefresh = refreshCompanionOnce(options).finally(() => {
    if (companionRefreshPromise === pendingRefresh) companionRefreshPromise = null;
  });
  companionRefreshPromise = pendingRefresh;
  return pendingRefresh;
}

function startCompanionPolling() {
  clearInterval(companionPollHandle);
  if (!companionSession) return;
  refreshCompanion();
  companionPollHandle = setInterval(refreshCompanion, 900);
  startCompanionCountdown();
}

async function createCompanionRoom() {
  const guide = focusGuide();
  if (!guide || !isRecipientAuthorized() || companionPending) return;
  companionPending = true;
  try {
    const details = companionStageDetails();
    const result = await companionRequest("/api/rooms", {
      method: "POST",
      body: JSON.stringify({
        family: {
          caregiverName: state.family.caregiverName,
          relayName: state.family.relayName,
          recipientName: state.family.recipientName,
          caregiverPhone: state.family.caregiverPhone,
          emergencyService: state.family.emergencyService,
        },
        stage: details.stage,
        duration: details.duration,
        consentRevision: state.recipientConsent.revision,
        guide: {
          id: guide.id,
          version: guide.version,
          title: guide.title,
          summary: guide.summary,
          source: sourceView(guide).label,
          rule: guide.rule,
          level: guide.level,
          actorId: guide.provenance.actorId,
          highRisk: Boolean(guide.highRisk),
          ...(guide.professionalReferenceId ? { professionalReferenceId: guide.professionalReferenceId } : {}),
        },
        searchGuides: usableGuides().map((item) => ({
          id: item.id,
          version: item.version,
          title: item.title,
          summary: item.summary,
          source: sourceView(item).label,
          rule: item.rule,
          level: item.level,
          actorId: item.provenance.actorId,
          highRisk: SafetyPolicy.classifyFields([item.title, item.summary]).highRisk,
          ...(item.professionalReferenceId ? { professionalReferenceId: item.professionalReferenceId } : {}),
        })),
        redLines: state.family.redLines.filter(Boolean),
        safetyRevision: companionSafetyRevision(),
      }),
    });
    acceptCompanionRoomSnapshot(result.room, { force: true });
    companionSession = {
      roomId: result.room.id,
      caregiverToken: result.caregiverToken,
      invitation: result.invitation,
      sessionId: result.room.sessionId,
      participantId: result.room.participantId,
      completionApplied: false,
    };
    saveCompanionSession();
    companionDegraded = false;
    startCompanionPolling();
    updateCompanionCard();
    showCompanionInvite();
  } catch (error) {
    toast(error.code === "policy_update_required" ? "安全策略已更新，请刷新页面后继续；直接电话仍可使用" : error.code === "unsafe_companion_scope" ? "高风险内容不能进入双机日常彩排" : `无法创建双机邀请：${error.message}`);
  } finally {
    companionPending = false;
    updateCompanionCard();
  }
}

function showCompanionInvite() {
  const invitation = companionSession?.invitation;
  if (!invitation || companionRoom?.status !== "waiting") {
    toast(companionRoom?.status === "paired" ? "替班者已经使用这份邀请完成配对" : "当前邀请不可用，请重新签发");
    return;
  }
  openModal(`${modalHead("TWO-DEVICE INVITE", `推荐：邀请${escapeHTML(state.family.relayName)}使用自己的手机`)}<div class="modal-body"><div class="invite-modal-step"><span>1</span><div><b>把一次性链接发到替班者手机</b><p>链接 15 分钟有效且只能成功加入一次。不要公开发布。</p></div></div><div class="copy-field"><input id="companion-link" readonly value="${escapeHTML(invitation.joinUrl)}"><button class="btn btn-secondary btn-small" data-action="copy-companion-link">复制链接</button></div><div class="invite-modal-step"><span>2</span><div><b>再通过当面或原本可信的通话核对姓名与短语</b><p>对方必须输入家庭中预先填写的替班者姓名“${escapeHTML(state.family.relayName)}”，并核对下方两组词。姓名只是预期参与者检查，不是证件或生物身份验证。</p></div></div><div class="human-phrase"><small>本次核对短语</small><strong>${escapeHTML(invitation.phrase)}</strong><span>有效至 ${new Date(invitation.expiresAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span></div><div class="safety-note">${icon("i-lock")}推荐使用两台手机在线配对，这样角色、版本和同步状态都由服务器校验。配对后替班者还要逐条确认完整可搜索指导范围、版本、来源、红线和联系电话。</div><div class="fallback-note"><b>只有暂时没有第二台设备？</b><span>可以作废这份邀请并使用原有同机彩排：三人同处一处，把这台手机交给替班者，仍需重新完成三方安全确认。</span></div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="reissue-companion">作废并重发</button><button class="btn btn-secondary" data-action="use-same-device-fallback">没有第二台设备 · 使用同机备用</button><button class="btn btn-primary" data-action="close-modal">我会单独核对短语</button></footer>`, "companion-modal");
}

async function companionMutation(type, extra = {}) {
  if (!companionRoom) return false;
  // A click can arrive just as a previous room action is finishing (most
  // commonly when the other phone submits its check-in). Queue briefly instead
  // of silently dropping the user's answer.
  for (let attempt = 0; companionPending && attempt < 40; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  if (companionPending) {
    toast("上一项双机操作仍在同步，请稍后再保存");
    return false;
  }
  if (companionDegraded) {
    await refreshCompanion();
    if (companionDegraded || !companionRoom) {
      toast("双机连接尚未恢复，回答没有丢失，请联网后再保存");
      return false;
    }
  }
  companionPending = true;
  updateCompanionCard();
  let retried = false;
  try {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const result = await companionRequest(`/api/rooms/${encodeURIComponent(companionRoom.id)}/actions`, {
          method: "POST",
          body: JSON.stringify({ type, ...companionActionContext(), ...extra }),
        });
        acceptCompanionRoomSnapshot(result.room);
        companionDegraded = false;
        syncCompanionActiveOutcome();
        applyCompanionCompletion();
        updateCompanionCard();
        startCompanionCountdown();
        if (retried) toast("另一台手机刚更新了房间；已自动同步并完成本次操作");
        return true;
      } catch (error) {
        if (error.code !== "stale_revision" || attempt === 2) throw error;
        retried = true;
        const latest = await companionRequest(`/api/rooms/${encodeURIComponent(companionRoom.id)}`);
        acceptCompanionRoomSnapshot(latest.room);
        companionDegraded = false;
      }
    }
  } catch (error) {
    toast(error.code === "stale_revision" ? "房间连续变化，正在自动同步；请稍后再试" : error.message);
    if (error.code === "stale_revision") {
      companionPending = false;
      await refreshCompanion();
      companionPending = true;
    }
    return false;
  } finally {
    companionPending = false;
    updateCompanionCard();
  }
  return false;
}

async function reissueCompanion() {
  if (!companionRoom || companionPending || ["active", "debrief"].includes(companionRoom.status)) return;
  companionPending = true;
  try {
    const result = await companionRequest(`/api/rooms/${encodeURIComponent(companionRoom.id)}/reissue`, {
      method: "POST",
      body: JSON.stringify({ ...companionActionContext() }),
    });
    acceptCompanionRoomSnapshot(result.room);
    companionSession.invitation = result.invitation;
    companionSession.sessionId = result.room.sessionId;
    companionSession.participantId = result.room.participantId;
    companionSession.completionApplied = false;
    saveCompanionSession();
    closeModal();
    updateCompanionCard();
    showCompanionInvite();
  } catch (error) {
    toast(error.code === "stale_revision" ? "房间已变化，先同步后再重发" : error.message);
    await refreshCompanion();
  } finally {
    companionPending = false;
    updateCompanionCard();
  }
}

function queueCompanionRevocation() {
  if (!companionRoom || !companionSession?.caregiverToken || ["revoked", "expired", "invalidated"].includes(companionRoom.status)) return null;
  const record = {
    roomId: companionRoom.id,
    caregiverToken: companionSession.caregiverToken,
    body: companionActionContext(),
    queuedAt: Date.now(),
  };
  localStorage.setItem(COMPANION_REVOCATION_KEY, JSON.stringify(record));
  return record;
}

async function executeCompanionRevocation(record, { retries = 3, announce = true } = {}) {
  if (!record) return true;
  for (let attempt = 0; attempt < retries; attempt += 1) {
    try {
      const response = await fetch(`/api/rooms/${encodeURIComponent(record.roomId)}/revoke`, {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${record.caregiverToken}`, [SafetyPolicy.HEADER]: SafetyPolicy.VERSION },
        body: JSON.stringify(record.body),
      });
      const result = await response.json().catch(() => ({}));
      if (response.ok || [401, 404].includes(response.status)) {
        localStorage.removeItem(COMPANION_REVOCATION_KEY);
        if (result.room && companionRoom?.id === record.roomId) {
          acceptCompanionRoomSnapshot(result.room);
          syncCompanionActiveOutcome();
          applyCompanionCompletion();
        }
        if (announce) toast("双机连接已撤销，替班者旧凭证立即失效");
        return true;
      }
      if (response.status === 409 && result.error?.code === "stale_revision") {
        const latestResponse = await fetch(`/api/rooms/${encodeURIComponent(record.roomId)}`, {
          cache: "no-store",
          headers: { Authorization: `Bearer ${record.caregiverToken}`, [SafetyPolicy.HEADER]: SafetyPolicy.VERSION },
        });
        if (latestResponse.ok) {
          const latest = (await latestResponse.json()).room;
          record.body = {
            expectedRevision: latest.revision,
            actionId: companionActionId(),
            sessionId: latest.sessionId,
            participantId: latest.participantId,
            consentRevision: latest.consentRevision,
            guideVersion: latest.guideVersion,
            safetyRevision: latest.safetyRevision,
          };
          localStorage.setItem(COMPANION_REVOCATION_KEY, JSON.stringify(record));
        }
      }
    } catch { /* Retried below and then persisted for the next online event. */ }
    await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }
  if (announce) toast("本机撤回已生效；远端撤销会在连接恢复后自动重试");
  return false;
}

async function retryPendingCompanionRevocation() {
  try {
    const record = JSON.parse(localStorage.getItem(COMPANION_REVOCATION_KEY));
    if (record?.roomId && record?.caregiverToken && record?.body) await executeCompanionRevocation(record, { retries: 3, announce: false });
  } catch {
    localStorage.removeItem(COMPANION_REVOCATION_KEY);
  }
}

async function revokeCompanion({ retries = 3, announce = true } = {}) {
  if (companionPending) return false;
  const record = queueCompanionRevocation();
  if (!record) return true;
  companionPending = true;
  const revoked = await executeCompanionRevocation(record, { retries, announce });
  companionPending = false;
  closeModal();
  updateCompanionCard();
  return revoked;
}

function currentCompanionSnapshot() {
  const guide = companionRoom ? usableGuideById(companionRoom.guide?.id) : null;
  return {
    valid: Boolean(isRecipientAuthorized() && guide),
    consentRevision: Math.max(1, Number(state.recipientConsent.revision) || 1),
    guideVersion: Math.max(1, Number(guide?.version || companionRoom?.guideVersion) || 1),
    safetyRevision: companionSafetyRevision(),
  };
}

async function syncCompanionSnapshot() {
  clearTimeout(companionSnapshotSyncHandle);
  companionSnapshotSyncHandle = null;
  if (!companionRoom || companionPending || !["waiting", "paired", "active", "debrief"].includes(companionRoom.status)) return;
  const current = currentCompanionSnapshot();
  if (current.valid && current.consentRevision === companionRoom.consentRevision && current.guideVersion === companionRoom.guideVersion && current.safetyRevision === companionRoom.safetyRevision) return;
  companionPending = true;
  try {
    const result = await companionRequest(`/api/rooms/${encodeURIComponent(companionRoom.id)}/snapshot`, {
      method: "POST",
      body: JSON.stringify({ ...companionActionContext(), current }),
    });
    acceptCompanionRoomSnapshot(result.room);
    syncCompanionActiveOutcome();
    applyCompanionCompletion();
    companionDegraded = false;
    updateCompanionCard();
    if (result.changed) toast("家庭内容已变化，进行中的双机房间已安全失效");
  } catch {
    companionSnapshotSyncHandle = setTimeout(syncCompanionSnapshot, 1800);
  } finally {
    companionPending = false;
  }
}

function scheduleCompanionSnapshotSync() {
  if (!companionRoom || !["waiting", "paired", "active", "debrief"].includes(companionRoom.status)) return;
  if (localStorage.getItem(COMPANION_REVOCATION_KEY)) return;
  clearTimeout(companionSnapshotSyncHandle);
  companionSnapshotSyncHandle = setTimeout(syncCompanionSnapshot, 120);
}

function nowISO() {
  return new Date().toISOString();
}

function normalizedQuery(value) {
  return SafetyPolicy.canonicalizeText(value);
}

function authorityRecordFromConsent(consent) {
  return {
    schemaVersion: 1,
    status: consent?.status === "withdrawn" ? "withdrawn" : "granted",
    revision: Math.max(1, Number(consent?.revision) || 1),
    changedAt: consent?.withdrawnAt || consent?.grantedAt || nowISO(),
    grantedAt: consent?.grantedAt || null,
    withdrawnAt: consent?.withdrawnAt || null,
  };
}

function readAuthorityRecord() {
  try {
    const parsed = JSON.parse(localStorage.getItem(AUTHORITY_KEY));
    if (!parsed || !["granted", "withdrawn"].includes(parsed.status) || !Number.isFinite(Number(parsed.revision)) || Number(parsed.revision) < 1) return null;
    return { ...parsed, schemaVersion: 1, revision: Number(parsed.revision) };
  } catch {
    return null;
  }
}

function writeAuthorityRecord(consent) {
  const next = authorityRecordFromConsent(consent);
  const current = readAuthorityRecord();
  if (current && (current.revision > next.revision || (current.revision === next.revision && current.status === "withdrawn" && next.status !== "withdrawn"))) return current;
  localStorage.setItem(AUTHORITY_KEY, JSON.stringify(next));
  return next;
}

function resolveAuthorityRecord(consent) {
  const local = authorityRecordFromConsent(consent);
  const stored = readAuthorityRecord();
  if (!stored || local.revision > stored.revision || (local.revision === stored.revision && local.status === "withdrawn" && stored.status !== "withdrawn")) return writeAuthorityRecord(local);
  return stored;
}

function applyAuthorityRecord(candidateState, authority) {
  if (!authority) return candidateState;
  const priorRevision = Number(candidateState.recipientConsent?.revision) || 1;
  const priorStatus = candidateState.recipientConsent?.status;
  const authorityChanged = priorRevision !== authority.revision || priorStatus !== authority.status;
  candidateState.recipientConsent = {
    status: authority.status,
    revision: authority.revision,
    grantedAt: authority.grantedAt || null,
    withdrawnAt: authority.withdrawnAt || null,
  };
  candidateState.family.recipientConsented = authority.status === "granted" && Boolean(candidateState.family.recipientName);
  const revoked = new Set(candidateState.revokedGuideIds || []);
  candidateState.guides = (candidateState.guides || []).filter((guide) => {
    if (guide?.provenance?.actorId !== SOURCE_IDS.RECIPIENT) return true;
    const usableAtAuthority = authority.status === "granted" && guide.provenance.consentRevision === authority.revision;
    if (!usableAtAuthority) revoked.add(String(guide.id));
    return usableAtAuthority;
  });
  candidateState.revokedGuideIds = [...revoked];
  candidateState.confirmations = (candidateState.confirmations || []).map((record) => {
    const staleRecipientRecord = record.actorId === SOURCE_IDS.RECIPIENT && record.consentRevision !== authority.revision;
    const staleHandoff = (record.type === "rehearsal" || record.type === "offDuty") && (authority.status === "withdrawn" || record.consentRevision !== authority.revision);
    if (record.status === "current" && (staleRecipientRecord || staleHandoff || (authority.status === "withdrawn" && record.actorId === SOURCE_IDS.RECIPIENT))) return { ...record, status: "revoked", revokedAt: authority.changedAt || nowISO() };
    return record;
  });
  candidateState.activity = visibleActivities(candidateState);
  if (authority.status === "withdrawn" || authorityChanged) {
    const endedAt = nowISO();
    candidateState.sessions = normalizeOutcomeSessions(candidateState.sessions).map((record) => {
      const ended = record.status === "active" ? OutcomeModel.endSession(record, {
        status: authority.status === "withdrawn" ? "revoked" : "interrupted",
        endedAt,
        actualElapsedSeconds: Math.max(0, Math.floor((Date.now() - new Date(record.startSnapshot?.startedAt || endedAt).getTime()) / 1000)),
        completedSteps: candidateState.activeRehearsal?.sessionRecordId === record.id ? candidateState.activeRehearsal.tasks || [] : [],
        routineUpdatesQueued: candidateState.activeRest?.sessionRecordId === record.id ? candidateState.activeRest.queued || 0 : 0,
        pendingGaps: [],
        urgentAlertsRaised: 0,
        contactActionsOpened: record.facts?.contactActionsOpened || [],
      }) : record;
      return authority.status === "withdrawn" && ended.startSnapshot?.consentRevision !== authority.revision
        ? OutcomeModel.redactSession({ ...ended, redacted: true }, candidateState.revokedGuideIds || [])
        : ended;
    });
    candidateState.activeRest = null;
    candidateState.activeRehearsal = null;
    candidateState.rehearsalCompleted = false;
    if (candidateState.mode === "real") candidateState.stageOneCompleted = false;
  }
  return candidateState;
}

function sourceDefinition(sourceId, candidateState = state) {
  const family = candidateState.family;
  const definitions = {
    [SOURCE_IDS.CAREGIVER]: { id: SOURCE_IDS.CAREGIVER, actorType: "caregiver", label: family.caregiverName, avatar: family.caregiverName?.slice(-1) || "护", className: "avatar-caregiver", authorized: Boolean(family.caregiverName) },
    [SOURCE_IDS.RECIPIENT]: { id: SOURCE_IDS.RECIPIENT, actorType: "careRecipient", label: family.recipientName ? `${family.recipientName}本人` : "被照护者本人", avatar: family.recipientName?.slice(-1) || "本", className: "avatar-caregiver", authorized: isRecipientAuthorized(candidateState) },
    [SOURCE_IDS.RELAY]: { id: SOURCE_IDS.RELAY, actorType: "relay", label: family.relayName, avatar: family.relayName?.slice(-1) || "替", className: "avatar-relay", authorized: Boolean(family.relayName) },
    [SOURCE_IDS.PROFESSIONAL]: { id: SOURCE_IDS.PROFESSIONAL, actorType: "professional", label: "内置演示专业引用", avatar: "专", className: "avatar-relay", authorized: true },
  };
  return definitions[sourceId] || null;
}

function isRecipientAuthorized(candidateState = state) {
  return Boolean(candidateState?.family?.recipientName && candidateState?.family?.recipientConsented === true && candidateState?.recipientConsent?.status === "granted");
}

function inferLegacySource(rawGuide, family) {
  const existingId = rawGuide?.provenance?.actorId;
  const aliases = { "care-recipient": SOURCE_IDS.RECIPIENT, careRecipient: SOURCE_IDS.RECIPIENT };
  if ([SOURCE_IDS.CAREGIVER, SOURCE_IDS.RECIPIENT, SOURCE_IDS.RELAY].includes(existingId)) return existingId;
  if (aliases[existingId]) return aliases[existingId];
  const label = String(rawGuide?.source || rawGuide?.provenance?.labelAtConfirmation || "").trim();
  if (label === family.caregiverName) return SOURCE_IDS.CAREGIVER;
  if (label === family.relayName) return SOURCE_IDS.RELAY;
  if (label === "妈妈本人" || label === "本人" || label === family.recipientName || label === `${family.recipientName}本人`) return SOURCE_IDS.RECIPIENT;
  return null;
}

function registeredProfessionalReference(rawGuide) {
  if (!SafetyPolicy.matchesProfessionalReference(rawGuide)) return null;
  return SafetyPolicy.getProfessionalReference(rawGuide.professionalReferenceId);
}

function normalizeConsent(saved, family) {
  const record = saved?.recipientConsent || {};
  const revision = Math.max(1, Number(record.revision) || 1);
  const explicitLegacyWithdrawal = saved?.family?.recipientConsented === false;
  const status = explicitLegacyWithdrawal || record.status === "withdrawn" || !family.recipientName ? "withdrawn" : "granted";
  return {
    status,
    revision,
    grantedAt: status === "granted" ? (record.grantedAt || "legacy-migrated") : (record.grantedAt || null),
    withdrawnAt: status === "withdrawn" ? (record.withdrawnAt || "legacy-migrated") : null,
  };
}

function normalizeGaps(rawGaps) {
  const byId = new Map();
  for (const raw of Array.isArray(rawGaps) ? rawGaps : []) {
    const query = String(raw?.query || "").trim();
    if (!query) continue;
    const key = normalizedQuery(query);
    const normalized = {
      ...raw,
      id: String(raw.id || `gap-${Date.now()}-${byKey.size}`),
      query,
      normalizedQuery: key,
      status: raw.status === "resolved" ? "resolved" : "pending",
      risk: SafetyPolicy.classifyFields([query, raw.lastProposedTitle, raw.lastProposedInstruction]).risk,
      encounters: Math.max(1, Number(raw.encounters) || 1),
      createdAt: Number(raw.createdAt) || Date.now(),
      lastSeenAt: Number(raw.lastSeenAt) || Number(raw.createdAt) || Date.now(),
    };
    const existing = byId.get(normalized.id);
    if (!existing) {
      byId.set(normalized.id, normalized);
      continue;
    }
    // A gap can move from pending to resolved while another tab still has the
    // pending snapshot. Resolution is monotonic for that stable record ID: a
    // stale persisted copy must not recreate the pending item beside it.
    const preferred = existing.status === "resolved"
      ? existing
      : normalized.status === "resolved"
        ? normalized
        : normalized.lastSeenAt >= existing.lastSeenAt
          ? normalized
          : existing;
    const other = preferred === existing ? normalized : existing;
    byId.set(normalized.id, {
      ...other,
      ...preferred,
      encounters: Math.max(existing.encounters, normalized.encounters),
      createdAt: Math.min(existing.createdAt, normalized.createdAt),
      lastSeenAt: Math.max(existing.lastSeenAt, normalized.lastSeenAt),
    });
  }

  const byKey = new Map();
  for (const normalized of byId.values()) {
    const key = normalized.normalizedQuery;
    const duplicate = byKey.get(`${normalized.status}:${key}`);
    if (duplicate) {
      duplicate.encounters += normalized.encounters;
      duplicate.lastSeenAt = Math.max(duplicate.lastSeenAt, normalized.lastSeenAt);
    } else {
      byKey.set(`${normalized.status}:${key}`, normalized);
    }
  }
  return [...byKey.values()].sort((a, b) => b.lastSeenAt - a.lastSeenAt);
}

function mergeGapStates(localGaps, externalGaps) {
  return normalizeGaps([...(externalGaps || []), ...(localGaps || [])]);
}

function mergeGuides(localGuides, externalGuides) {
  const byId = new Map();
  for (const guide of [...(externalGuides || []), ...(localGuides || [])]) {
    const existing = byId.get(String(guide.id));
    if (!existing || Number(guide.version || 0) >= Number(existing.version || 0)) byId.set(String(guide.id), guide);
  }
  return [...byId.values()];
}

function mergeConfirmations(localRecords, externalRecords) {
  const priority = { current: 0, "needs-review": 1, completed: 2, superseded: 3, revoked: 4 };
  const byId = new Map();
  for (const record of [...(externalRecords || []), ...(localRecords || [])]) {
    const existing = byId.get(String(record.id));
    if (!existing || (priority[record.status] || 0) >= (priority[existing.status] || 0)) byId.set(String(record.id), record);
  }
  return [...byId.values()];
}

function mergeOutcomeSessions(localRecords, externalRecords) {
  const byId = new Map(normalizeOutcomeSessions(externalRecords).map((record) => [record.id, record]));
  for (const record of normalizeOutcomeSessions(localRecords)) {
    const existing = byId.get(record.id);
    if (!existing) byId.set(record.id, record);
    else byId.set(record.id, {
      ...existing,
      ...record,
      facts: record.facts || existing.facts,
      checkIns: {
        caregiver: record.checkIns?.caregiver || existing.checkIns?.caregiver || null,
        substitute: record.checkIns?.substitute || existing.checkIns?.substitute || null,
        careRecipient: record.checkIns?.careRecipient || existing.checkIns?.careRecipient || null,
      },
    });
  }
  return [...byId.values()].sort((a, b) => String(a.startSnapshot?.startedAt || "").localeCompare(String(b.startSnapshot?.startedAt || "")));
}

function normalizeActivities(rawActivities, guides) {
  return (Array.isArray(rawActivities) ? rawActivities : []).filter((item) => item && typeof item === "object").map((item) => {
    const classification = SafetyPolicy.classifyFields([item.title, item.note, item.focus]);
    if (item.guideDependency || item.guideId == null) return { ...item, risk: classification.risk, urgent: classification.highRisk };
    const guide = (guides || []).find((candidate) => String(candidate.id) === String(item.guideId));
    return guide ? { ...item, guideDependency: guideDependencySnapshot(guide), risk: classification.risk, urgent: classification.highRisk } : { ...item, risk: classification.risk, urgent: classification.highRisk };
  });
}

function outcomeSafeActivities(rawActivities, guides, savedVersion, mode) {
  const normalized = normalizeActivities(rawActivities, guides);
  if (mode !== "real" || Number(savedVersion) >= SCHEMA_VERSION) return normalized;
  return normalized.map((item) => ({
    ...item,
    title: `${item.stage && OutcomeModel.STAGE_LABELS[item.stage] ? OutcomeModel.STAGE_LABELS[item.stage] : "较早彩排"} · 较早完成`,
    note: "详细结果未记录；旧活动文字没有转换为时长、休息或信心结论",
    score: "详细未记录",
  }));
}

function normalizeDebriefs(rawDebriefs) {
  return (Array.isArray(rawDebriefs) ? rawDebriefs : []).filter((item) => item && typeof item === "object").map((item) => {
    const gap = String(item.gap || "").trim();
    const instruction = String(item.instruction || "").trim();
    const classification = SafetyPolicy.classifyFields([gap, instruction]);
    if (classification.highRisk) {
      return { ...item, gap, instruction: "", outcome: "pending-gap", provenance: null, risk: "medical", urgent: true, policyVersion: SafetyPolicy.VERSION };
    }
    return { ...item, gap, instruction, risk: "ordinary", urgent: false, policyVersion: SafetyPolicy.VERSION };
  });
}

function normalizeOutcomeSessions(rawSessions) {
  const seen = new Set();
  return (Array.isArray(rawSessions) ? rawSessions : []).map(OutcomeModel.normalizeSession).filter((record) => {
    if (!record || seen.has(record.id)) return false;
    seen.add(record.id);
    return true;
  });
}

function legacyOutcomeRecords(saved, consentRevision) {
  const records = [];
  if (saved?.stageOneCompleted) records.push(OutcomeModel.normalizeSession({ id: "legacy-observe-completion", status: "legacy", startSnapshot: { stage: "observe", consentRevision }, legacyNote: "较早完成，详细结果未记录" }));
  if (saved?.rehearsalCompleted) records.push(OutcomeModel.normalizeSession({ id: "legacy-short-leave-completion", status: "legacy", startSnapshot: { stage: "short-leave", consentRevision }, legacyNote: "较早完成，详细结果未记录" }));
  return records.filter(Boolean);
}

function outcomeContext(candidateState = state) {
  return {
    consentRevision: candidateState.recipientConsent?.revision,
    guides: usableGuides(candidateState).map((guide) => ({ id: guide.id, version: guide.version })),
    overrideStage: candidateState.recommendationOverride?.stage || null,
  };
}

function householdRecommendation(candidateState = state) {
  return OutcomeModel.recommendation(candidateState.sessions || [], outcomeContext(candidateState));
}

function syncCompatibilityProgress(candidateState = state) {
  const recommendation = householdRecommendation(candidateState);
  candidateState.stageOneCompleted = isRecipientAuthorized(candidateState) && OutcomeModel.stageIndex(recommendation.stage) >= 1;
  candidateState.rehearsalCompleted = isRecipientAuthorized(candidateState) && OutcomeModel.stageIndex(recommendation.stage) >= 2;
  return recommendation;
}

function currentStage() {
  return householdRecommendation().stage;
}

function sessionGuideScope(candidateState = state) {
  return usableGuides(candidateState).map((guide) => ({
    id: guide.id,
    version: guide.version,
    title: guide.title,
    source: sourceView(guide).label,
    actorId: guide.provenance?.actorId,
    level: guide.level,
    rule: guide.rule,
  }));
}

function startOutcomeRecord({ id = null, stage, duration, mode = "single-device", startedAt = nowISO() }) {
  const record = OutcomeModel.createSession({
    id: id || OutcomeModel.stableId(),
    stage,
    plannedDurationMinutes: duration,
    consentRevision: state.recipientConsent.revision,
    guideScope: sessionGuideScope(),
    redLines: [...state.family.redLines],
    participants: {
      caregiver: { id: SOURCE_IDS.CAREGIVER, label: state.family.caregiverName },
      substitute: { id: SOURCE_IDS.RELAY, label: state.family.relayName },
      careRecipient: { id: SOURCE_IDS.RECIPIENT, label: state.family.recipientName },
    },
    mode,
    startedAt,
    safetyRevision: companionSafetyRevision(),
    policyVersion: SafetyPolicy.VERSION,
  });
  const existing = state.sessions.findIndex((item) => item.id === record.id);
  if (existing >= 0) return state.sessions[existing];
  state.sessions.push(record);
  return record;
}

function outcomeRecord(id) {
  return state.sessions.find((record) => record.id === id) || null;
}

function replaceOutcomeRecord(record) {
  const index = state.sessions.findIndex((item) => item.id === record?.id);
  if (index >= 0) state.sessions[index] = record;
  else if (record) state.sessions.push(record);
  return record;
}

function finishOutcomeRecord(id, { status = "completed", tasks = [], routineUpdatesQueued = 0, pendingGaps = [], urgentAlertsRaised = 0, contactActionsOpened = null, endedAt = nowISO() } = {}) {
  const record = outcomeRecord(id);
  if (!record || record.status !== "active") return record;
  return replaceOutcomeRecord(OutcomeModel.endSession(record, {
    status,
    endedAt,
    actualElapsedSeconds: Math.max(0, Math.floor((new Date(endedAt).getTime() - new Date(record.startSnapshot.startedAt).getTime()) / 1000)),
    completedSteps: tasks,
    routineUpdatesQueued,
    pendingGaps,
    urgentAlertsRaised,
    contactActionsOpened: contactActionsOpened || record.facts?.contactActionsOpened || [],
  }));
}

function addContactAction(target = "caregiver", recordId = session?.sessionRecordId || restSession?.sessionRecordId) {
  const record = outcomeRecord(recordId);
  if (!record || record.status !== "active") return;
  const contactActionsOpened = [...(record.facts?.contactActionsOpened || []), { at: nowISO(), target, label: "已打开联系操作（不代表通话接通）" }];
  replaceOutcomeRecord({ ...record, facts: { ...(record.facts || {}), contactActionsOpened } });
  saveState();
}

function migrateState(saved, isDefault = false) {
  const legacyHousehold = !["real", "demo"].includes(saved?.mode) && Number(saved?.schemaVersion) !== SCHEMA_VERSION && Boolean(saved?.family?.caregiverName || saved?.family?.recipientName || saved?.rehearsalCompleted || saved?.stageOneCompleted || saved?.guides?.length || saved?.activity?.length);
  const mode = saved?.mode === "real" ? "real" : saved?.mode === "demo" ? "demo" : legacyHousehold ? "real" : null;
  const defaults = mode === "real" ? emptyState("real") : mode === "demo" ? structuredClone(demoState) : emptyState(null);
  const family = {
    ...defaults.family,
    ...(saved?.family || {}),
    restGoal: { ...defaults.family.restGoal, ...(saved?.family?.restGoal || {}) },
    redLines: Array.isArray(saved?.family?.redLines) ? saved.family.redLines.filter(Boolean) : defaults.family.redLines,
  };
  const consent = normalizeConsent(saved || defaults, family);
  family.recipientConsented = consent.status === "granted" && Boolean(family.recipientName);
  const revokedGuideIds = new Set(Array.isArray(saved?.revokedGuideIds) ? saved.revokedGuideIds.map(String) : []);
  const rawConfirmations = Array.isArray(saved?.confirmations) ? structuredClone(saved.confirmations) : [];
  const confirmationIds = new Set(rawConfirmations.map((item) => item.id));
  const rawGuides = Array.isArray(saved?.guides) ? saved.guides : (isDefault && mode === "demo" ? defaults.guides : []);
  const guides = [];

  rawGuides.forEach((raw, index) => {
    if (!raw || !String(raw.title || "").trim() || !String(raw.summary || "").trim()) return;
    const professionalReference = registeredProfessionalReference(raw);
    const id = professionalReference?.id || String(raw.id || `legacy-guide-${index}`);
    const title = professionalReference?.title || String(raw.title).trim();
    const summary = professionalReference?.summary || String(raw.summary).trim();
    const sourceId = professionalReference ? SOURCE_IDS.PROFESSIONAL : inferLegacySource(raw, family);
    const source = sourceDefinition(sourceId, { family, recipientConsent: consent, mode });
    const legacyStatus = raw.status || "usable";
    const legacyConsentRevision = saved?.schemaVersion === SCHEMA_VERSION ? Number(raw.provenance?.consentRevision) : consent.revision;
    const consentRevision = sourceId === SOURCE_IDS.RECIPIENT ? Math.max(0, legacyConsentRevision || 0) : undefined;
    const recipientUsable = sourceId !== SOURCE_IDS.RECIPIENT || (family.recipientConsented && consentRevision === consent.revision);
    if (sourceId === SOURCE_IDS.RECIPIENT && !recipientUsable) {
      revokedGuideIds.add(id);
      return;
    }
    const risk = SafetyPolicy.classifyFields([title, summary]).highRisk;
    const requestedLevel = professionalReference?.level || (["here", "later", "now"].includes(raw.level) ? raw.level : "here");
    const level = risk ? SafetyPolicy.IMMEDIATE_LEVEL : requestedLevel;
    const rule = { here: "现场可处理", later: "稍后告知", now: SafetyPolicy.IMMEDIATE_RULE }[level];
    const immediateProfessional = Boolean(professionalReference && SafetyPolicy.isImmediateReference(professionalReference));
    const status = legacyStatus === "usable" && source?.authorized && !revokedGuideIds.has(id) && (!risk || immediateProfessional) ? "usable" : "needs-review";
    const confirmationId = String(raw.confirmationId || `legacy-confirm-${id}`);
    const guide = {
      ...raw,
      id,
      version: professionalReference?.version || Math.max(1, Number(raw.version) || 1),
      professionalReferenceId: professionalReference?.professionalReferenceId || null,
      status,
      confirmationId,
      provenance: {
        actorId: sourceId || "unverified-legacy",
        actorType: source?.actorType || "unverified",
        labelAtConfirmation: raw.provenance?.labelAtConfirmation || raw.source || "旧数据来源待复核",
        ...(sourceId === SOURCE_IDS.RECIPIENT ? { consentRevision } : {}),
      },
      source: source?.label || "旧数据来源待复核",
      sourceAvatar: source?.avatar || "?",
      sourceClass: source?.className || "avatar-relay",
      title,
      summary,
      level,
      rule,
      category: level === "now" ? "urgent" : "daily",
      highRisk: risk,
      policyVersion: SafetyPolicy.VERSION,
    };
    guides.push(guide);
    const existingConfirmation = rawConfirmations.find((item) => String(item.id) === confirmationId);
    if (existingConfirmation) {
      existingConfirmation.actorId = guide.provenance.actorId;
      existingConfirmation.guideId = id;
      if (status !== "usable" && existingConfirmation.status === "current") existingConfirmation.status = "needs-review";
    } else if (!confirmationIds.has(confirmationId)) {
      rawConfirmations.push({ id: confirmationId, type: "guide", status: status === "usable" ? "current" : "needs-review", actorId: guide.provenance.actorId, guideId: id, ...(consentRevision ? { consentRevision } : {}), confirmedAt: "legacy-migrated" });
      confirmationIds.add(confirmationId);
    }
  });

  if (!family.recipientConsented) {
    rawConfirmations.forEach((record) => {
      if (record.actorId === SOURCE_IDS.RECIPIENT || record.type === "rehearsal" || record.type === "offDuty") record.status = record.status === "superseded" ? record.status : "revoked";
    });
  }
  const migrated = {
    ...defaults,
    ...(saved || {}),
    schemaVersion: SCHEMA_VERSION,
    mode,
    onboarding: { ...defaults.onboarding, ...(saved?.onboarding || {}) },
    meta: { ...(saved?.meta || {}), migratedAt: saved?.schemaVersion === SCHEMA_VERSION ? saved?.meta?.migratedAt : nowISO() },
    family,
    recipientConsent: consent,
    revokedGuideIds: [...revokedGuideIds],
    confirmations: rawConfirmations,
    guides,
    activity: outcomeSafeActivities(Array.isArray(saved?.activity) ? saved.activity : (mode === "demo" ? defaults.activity : []), guides, saved?.schemaVersion, mode),
    gaps: normalizeGaps(saved?.gaps),
    debriefs: normalizeDebriefs(saved?.debriefs),
    sessions: normalizeOutcomeSessions(Array.isArray(saved?.sessions) ? saved.sessions : (mode === "demo" ? defaults.sessions : legacyOutcomeRecords(saved, consent.revision))),
    recommendationOverride: saved?.recommendationOverride && OutcomeModel.STAGES.includes(saved.recommendationOverride.stage) ? saved.recommendationOverride : null,
    demoJourney: mode === "demo" ? {
      ...defaults.demoJourney,
      ...(saved?.demoJourney || {}),
      step: Math.max(0, Math.min(6, Number(saved?.demoJourney?.step) || 0)),
      role: ["caregiver", "substitute", "careRecipient"].includes(saved?.demoJourney?.role) ? saved.demoJourney.role : "caregiver",
    } : null,
    appliedRemoteSessionIds: Array.isArray(saved?.appliedRemoteSessionIds) ? [...new Set(saved.appliedRemoteSessionIds.map(String))] : [],
  };
  syncCompatibilityProgress(migrated);
  if (!family.recipientConsented || !saved?.activeRest?.consentRevision || saved.activeRest.consentRevision !== consent.revision) migrated.activeRest = null;
  if (!family.recipientConsented || !saved?.activeRehearsal?.consentRevision || saved.activeRehearsal.consentRevision !== consent.revision) migrated.activeRehearsal = null;
  return migrated;
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      const fresh = emptyState(null);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(fresh));
      return fresh;
    }
    let migrated = migrateState(JSON.parse(raw));
    const authority = resolveAuthorityRecord(migrated.recipientConsent);
    migrated = applyAuthorityRecord(migrated, authority);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
    return migrated;
  } catch {
    const fallback = emptyState(null);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(fallback));
    return fallback;
  }
}

function saveState({ ignorePersisted = false } = {}) {
  const authority = resolveAuthorityRecord(state.recipientConsent);
  state = applyAuthorityRecord(state, authority);
  try {
    const persistedRaw = localStorage.getItem(STORAGE_KEY);
    if (persistedRaw && !ignorePersisted) {
      const parsed = JSON.parse(persistedRaw);
      if (parsed?.schemaVersion === SCHEMA_VERSION) {
        const persisted = applyAuthorityRecord(migrateState(parsed), authority);
        state.revokedGuideIds = [...new Set([...(state.revokedGuideIds || []), ...(persisted.revokedGuideIds || [])])];
        state.guides = mergeGuides(state.guides, persisted.guides);
        state.confirmations = mergeConfirmations(state.confirmations, persisted.confirmations);
        state.gaps = mergeGapStates(state.gaps, persisted.gaps);
        state.sessions = mergeOutcomeSessions(state.sessions, persisted.sessions);
      }
    }
  } catch { /* Keep the in-memory state, then overwrite malformed storage safely. */ }
  state = applyAuthorityRecord(state, authority);
  enforceAuthorization();
  syncCompatibilityProgress(state);
  state.schemaVersion = SCHEMA_VERSION;
  state.meta = { ...(state.meta || {}), updatedAt: Date.now() };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  scheduleCompanionSnapshotSync();
}

function enforceAuthorization() {
  const authority = resolveAuthorityRecord(state.recipientConsent);
  if (authority) state = applyAuthorityRecord(state, authority);
  const revoked = new Set(state.revokedGuideIds || []);
  state.family.recipientConsented = isRecipientAuthorized(state);
  state.guides = (Array.isArray(state.guides) ? state.guides : []).filter((guide) => {
    if (guide?.provenance?.actorId === SOURCE_IDS.RECIPIENT && (!isRecipientAuthorized(state) || guide.provenance.consentRevision !== state.recipientConsent.revision)) {
      revoked.add(String(guide.id));
      return false;
    }
    return true;
  });
  state.revokedGuideIds = [...revoked];
  state.sessions = normalizeOutcomeSessions(state.sessions).map((record) => OutcomeModel.redactSession(record, state.revokedGuideIds));
  state.activity = visibleActivities(state);
  if (!isRecipientAuthorized(state)) {
    state.activeRest = null;
    state.activeRehearsal = null;
    state.rehearsalCompleted = false;
    if (state.mode === "real") state.stageOneCompleted = false;
    state.confirmations.forEach((record) => {
      if (record.status === "current" && (record.actorId === SOURCE_IDS.RECIPIENT || record.type === "rehearsal" || record.type === "offDuty")) record.status = "revoked";
    });
    if (typeof session !== "undefined") session = null;
    if (typeof restSession !== "undefined") restSession = null;
  }
}

function guideIsUsable(guide, candidateState = state) {
  if (!guide || guide.status !== "usable" || (candidateState.revokedGuideIds || []).includes(String(guide.id))) return false;
  const source = sourceDefinition(guide.provenance?.actorId, candidateState);
  if (!source?.authorized || source.actorType !== guide.provenance?.actorType) return false;
  const confirmation = (candidateState.confirmations || []).find((record) => record.id === guide.confirmationId);
  if (!confirmation || confirmation.status !== "current" || confirmation.actorId !== guide.provenance?.actorId || String(confirmation.guideId) !== String(guide.id)) return false;
  if (source.id === SOURCE_IDS.RECIPIENT && guide.provenance.consentRevision !== candidateState.recipientConsent.revision) return false;
  const contentIsHighRisk = SafetyPolicy.classifyFields([guide.title, guide.summary]).highRisk;
  if (Boolean(guide.highRisk) !== contentIsHighRisk || guide.policyVersion !== SafetyPolicy.VERSION) return false;
  const canonicalRule = { here: "现场可处理", later: "稍后告知", now: SafetyPolicy.IMMEDIATE_RULE }[guide.level];
  if (!canonicalRule || guide.rule !== canonicalRule || guide.category !== (guide.level === "now" ? "urgent" : "daily")) return false;
  if (source.id === SOURCE_IDS.PROFESSIONAL && !SafetyPolicy.isImmediateReference(guide)) return false;
  if (contentIsHighRisk && (source.id !== SOURCE_IDS.PROFESSIONAL || !SafetyPolicy.isImmediateReference(guide))) return false;
  return Boolean(String(guide.title || "").trim() && String(guide.summary || "").trim() && guide.confirmationId);
}

function usableGuides(candidateState = state) {
  return (candidateState.guides || []).filter((guide) => guideIsUsable(guide, candidateState));
}

function usableGuideById(id) {
  return usableGuides().find((guide) => guide.id === id) || null;
}

function guideScopeSummary(level, candidateState = state) {
  const guides = usableGuides(candidateState).filter((guide) => guide.level === level);
  if (!guides.length) return "暂无当前可用指导";
  const titles = guides.slice(0, 3).map((guide) => guide.title);
  return `${titles.join("、")}${guides.length > titles.length ? `等 ${guides.length} 条` : ""}`;
}

function guideDependencySnapshot(guide) {
  return {
    guideId: String(guide.id),
    guideVersion: Math.max(1, Number(guide.version) || 1),
    actorId: guide.provenance.actorId,
    actorType: guide.provenance.actorType,
    confirmationId: guide.confirmationId,
    ...(guide.professionalReferenceId ? { professionalReferenceId: guide.professionalReferenceId } : {}),
    ...(guide.provenance.actorId === SOURCE_IDS.RECIPIENT ? { consentRevision: guide.provenance.consentRevision } : {}),
  };
}

function activityIsAuthorized(item, candidateState = state) {
  if (!item || typeof item !== "object") return false;
  if (item.consentRevision != null && (!isRecipientAuthorized(candidateState) || Number(item.consentRevision) !== candidateState.recipientConsent.revision)) return false;
  const dependency = item.guideDependency;
  const legacyGuideId = item.guideId == null ? "" : String(item.guideId);
  const dependencyGuideId = dependency?.guideId == null ? "" : String(dependency.guideId);
  if (dependency && !dependencyGuideId) return false;
  if (legacyGuideId && dependencyGuideId && legacyGuideId !== dependencyGuideId) return false;
  const guideId = dependencyGuideId || legacyGuideId;
  if (!guideId) return !dependency;
  if ((candidateState.revokedGuideIds || []).includes(guideId)) return false;
  const guide = (candidateState.guides || []).find((candidate) => String(candidate.id) === guideId);
  if (!guide || !guideIsUsable(guide, candidateState)) return false;
  const actorId = dependency?.actorId || guide.provenance?.actorId;
  if (!actorId || actorId !== guide.provenance?.actorId) return false;
  if (dependency?.actorType && dependency.actorType !== guide.provenance?.actorType) return false;
  if (actorId === SOURCE_IDS.RECIPIENT) {
    const consentRevision = Number(dependency?.consentRevision ?? guide.provenance?.consentRevision);
    if (!isRecipientAuthorized(candidateState) || !Number.isFinite(consentRevision) || consentRevision !== candidateState.recipientConsent.revision) return false;
  }
  return true;
}

function visibleActivities(candidateState = state) {
  return (Array.isArray(candidateState.activity) ? candidateState.activity : []).filter((item) => activityIsAuthorized(item, candidateState));
}

function focusGuide() {
  return (state.mode === "demo" ? usableGuideById("meal") : null) || usableGuides().find((guide) => !guide.highRisk && guide.level !== "now") || null;
}

function sourceView(guide) {
  const source = sourceDefinition(guide?.provenance?.actorId);
  return source || { label: "来源待复核", avatar: "?", className: "avatar-relay" };
}

function guideSourceRow(guide, prefix = "") {
  const source = sourceView(guide);
  return `<div class="source-row"><span class="avatar ${source.className}">${escapeHTML(source.avatar)}</span><span><b>${escapeHTML(prefix)}${escapeHTML(source.label)}</b><br>${escapeHTML(guide.updated)}</span><span class="verified">${icon("i-shield")}来源已记录</span></div>`;
}

function availableGuideSources({ professionalOnly = false } = {}) {
  // Browser-authored content can never acquire professional provenance. The
  // professional source exists only for immutable references bundled with the
  // matching policy version.
  const ids = professionalOnly ? [] : [SOURCE_IDS.CAREGIVER, SOURCE_IDS.RECIPIENT, SOURCE_IDS.RELAY];
  return ids.map((id) => sourceDefinition(id)).filter((source) => source?.authorized);
}

function addConfirmation({ type, actorId, guideId = null, consentRevision = null }) {
  const id = `${type}-confirmation-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  state.confirmations.push({ id, type, status: "current", actorId, ...(guideId ? { guideId } : {}), ...(consentRevision ? { consentRevision } : {}), confirmedAt: nowISO() });
  return id;
}

function normalizePage(page) {
  return navItems.some((item) => item.id === page) ? page : "home";
}

function renderNav() {
  const currentGuides = usableGuides();
  const markup = navItems.map((item) => `
    <button class="nav-link ${currentPage === item.id ? "active" : ""}" data-nav="${item.id}" aria-current="${currentPage === item.id ? "page" : "false"}">
      ${icon(icons[item.id])}<span>${item.label}</span>${item.id === "guides" ? `<span class="nav-badge">${currentGuides.length}</span>` : ""}
    </button>`).join("");
  $(".desktop-nav").innerHTML = markup;
  $(".mobile-nav").innerHTML = markup;
  const householdLabel = state.mode === "demo" ? `${state.family.caregiverName}的家庭` : (state.family.caregiverName ? `${state.family.caregiverName}的家庭` : "我的家庭");
  $(".profile-mini b").textContent = householdLabel;
  $(".profile-mini small").textContent = state.mode === "real" && state.onboarding?.status !== "complete" ? "设置中 · 可暂停" : "主要照护者 · 可编辑";
  $$(".top-avatar, .profile-mini .avatar").forEach((avatar) => { avatar.textContent = state.family.caregiverName.slice(-1) || "家"; });
  const modeChip = $(".topbar .demo-chip");
  if (modeChip) {
    modeChip.innerHTML = state.mode === "demo"
      ? `${icon("i-play")}<span>演示模式 · 重播</span>`
      : `${icon("i-home")}<span>我的家庭 · 真实本机</span>`;
    modeChip.dataset.action = state.mode === "demo" ? "restart-judge" : "profile";
    modeChip.setAttribute("aria-label", state.mode === "demo" ? "演示模式：从头重播三分钟评审导览" : "真实家庭：打开家庭设置");
    modeChip.classList.toggle("demo-active", state.mode === "demo");
  }
  $(".notification-dot")?.classList.toggle("hidden", !Number(state.quietInbox));
}

function render() {
  clearInterval(tickHandle);
  tickHandle = null;
  document.body.classList.toggle("mode-choice", !state.mode);
  document.body.classList.toggle("onboarding-mode", state.mode === "real" && state.onboarding?.status !== "complete" && !session);
  document.body.classList.toggle("hosted-static", HOSTED_STATIC_REVIEW);
  if (!state.mode) { renderModeChoice(); return; }
  renderNav();
  const meta = navItems.find((item) => item.id === currentPage);
  $("#page-title").textContent = meta.title;
  $("#page-eyebrow").textContent = currentPage === "home" ? (state.mode === "demo" ? `${state.family.caregiverName}的家庭` : `${state.family.caregiverName || "我的"}家庭`) : meta.eyebrow;

  if (session) renderActiveRehearsal();
  else if (state.mode === "real" && state.onboarding?.status !== "complete") renderOnboarding();
  else if (restSession) renderActiveRest();
  else {
    if (currentPage === "guides") renderGuides();
    else if (currentPage === "rehearsal") renderRehearsal();
    else if (currentPage === "rest") renderRest();
    else renderHome();
    if (!(state.mode === "demo" && currentPage === "home")) {
      $("#app")?.insertAdjacentHTML("afterbegin", householdStatusBarMarkup());
    }
  }
}

function householdStatusBarMarkup() {
  const recommendation = householdRecommendation();
  const authorized = isRecipientAuthorized();
  const guides = usableGuides();
  return `<section class="household-status-bar" aria-label="当前角色、授权、下一步与直接联系">
    <div><small>这台设备由谁操作</small><b>${escapeHTML(state.family.caregiverName || "主要照护者")} · 主要照护者</b></div>
    <div><small>当前获授权范围</small><b>${authorized ? `本人同意 v${state.recipientConsent.revision} · ${guides.length} 条做法` : "本人参与已撤回 · 彩排暂停"}</b></div>
    <div><small>接下来</small><b>${authorized ? `建议${OutcomeModel.STAGE_LABELS[recommendation.stage]}` : "先由本人当面决定是否重新同意"}</b></div>
    <div class="household-status-actions"><small>停止或联系</small><span><a href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}照护者</a><a class="urgent" href="${phoneHref(state.family.emergencyService)}">${icon("i-alert")}${escapeHTML(state.family.emergencyService || "紧急服务")}</a></span></div>
  </section>`;
}

function renderModeChoice() {
  const realModeAction = HOSTED_STATIC_REVIEW ? "show-local-full-experience" : "choose-real";
  const realModeTag = HOSTED_STATIC_REVIEW ? "本地完整体验 · 不上传家庭数据" : "真实家庭 · 诚实空白";
  const realModeTitle = HOSTED_STATIC_REVIEW ? "在电脑上建立我的接班彩排" : "建立我的接班彩排";
  const realModeCopy = HOSTED_STATIC_REVIEW ? "真实家庭设置和双机房间只在你自己的电脑与局域网中运行。查看两步启动方法；公开评审版不会收集真实家庭信息。" : "没有预填成员、演示消息、完成记录或成功结论。约 8 分钟，只准备第一次低风险在旁练习。";
  $("#app").innerHTML = `<div class="choice-page">
    <header class="choice-brand"><span class="brand-mark"><span></span><span></span></span><span><b>接班彩排</b><small>把大交班拆成可以撤回的小练习</small></span></header>
    <main class="choice-main">
      <div class="choice-copy"><span class="page-kicker">第一次使用</span><h1>先选一条适合现在的路</h1><h2>把“愿意帮忙”，练成一次可撤回的接班</h2><p>接班彩排不替代微信、电话或紧急服务。它把口头意愿变成有来源、可归属、可撤回的低风险交接证据，再用这些证据保护一小段真正不被普通消息打断的休息。</p></div>
      <div class="mode-grid">
        <button class="mode-card demo-mode-card" data-action="choose-demo"><span class="mode-icon">${icon("i-play")}</span><span class="mode-tag">2–3 分钟 · 一键进入</span><h2>体验演示家庭 · 周岚家庭</h2><p>带着角色说明走完“在旁观察 → 短时离开 → 安静离班”，现场看到匹配、缺口、红线、回看与下一档建议。</p><strong>开始评审导览 ${icon("i-arrow")}</strong></button>
        <button class="mode-card real-mode-card" data-action="${realModeAction}"><span class="mode-icon">${icon("i-home")}</span><span class="mode-tag">${realModeTag}</span><h2>${realModeTitle}</h2><p>${realModeCopy}</p><strong>${HOSTED_STATIC_REVIEW ? "查看本地启动方法" : "从空白开始"} ${icon("i-arrow")}</strong></button>
      </div>
      <div class="choice-safety">${icon("i-shield")}${HOSTED_STATIC_REVIEW ? `公开评审版 · ${APP_BUILD} · 只使用脚本化样本，不创建远端房间或收集真实家庭资料。` : "演示数据始终标为“演示”；真实家庭长期内容留在照护者设备。直接联系电话不会被通知规则屏蔽，本应用不生成医疗决定。"}</div>
    </main>
  </div>`;
}

function onboardingGuide() {
  return state.onboarding?.guideId ? usableGuideById(state.onboarding.guideId) : focusGuide();
}

function setupBasicsReady() {
  return [state.family.caregiverName, state.family.caregiverPhone, state.family.recipientName, state.family.relayName, state.family.emergencyContactName, state.family.emergencyContactPhone, state.family.emergencyService].every((value) => String(value || "").trim());
}

function onboardingReady() {
  return setupBasicsReady() && Boolean(state.family.restGoal?.title && state.family.restGoal?.date && Number(state.family.restGoal?.duration)) && isRecipientAuthorized() && Boolean(onboardingGuide()) && Boolean(state.onboarding?.redLinesReviewedAt);
}

function onboardingShell(step, title, intro, body) {
  const calls = state.family.emergencyService ? `<div class="setup-direct-calls"><span>紧急联系始终可用</span><a href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}${escapeHTML(state.family.caregiverName || "主要照护者")}</a><a class="urgent" href="${phoneHref(state.family.emergencyService)}">${icon("i-alert")}当地紧急服务 ${escapeHTML(state.family.emergencyService)}</a></div>` : "";
  return `<div class="setup-page"><header class="setup-header"><div><span class="page-kicker">我的家庭 · 第 ${step} / 6 步</span><h1>${title}</h1><p>${intro}</p></div><div class="setup-progress" aria-label="设置进度 ${step} / 6"><span style="width:${step / 6 * 100}%"></span></div></header>${body}${calls}<p class="setup-persist">${icon("i-shield")}每一步都会保存在本设备。现在关掉页面，下次会从这里继续。</p></div>`;
}

function setupFooter(step, nextLabel = "保存并继续") {
  return `<footer class="setup-footer">${step > 1 ? `<button type="button" class="btn btn-secondary" data-action="onboarding-back">上一步</button>` : `<span></span>`}<button class="btn btn-primary" type="submit">${nextLabel}${icon("i-arrow")}</button></footer>`;
}

function renderOnboarding() {
  const step = Math.min(6, Math.max(1, Number(state.onboarding?.step) || 1));
  $("#page-title").textContent = "建立我的接班彩排";
  $("#page-eyebrow").textContent = `设置进度 · ${step} / 6`;
  if (step === 1) renderOnboardingPeople();
  else if (step === 2) renderOnboardingGoal();
  else if (step === 3) renderOnboardingConsent();
  else if (step === 4) renderOnboardingGuide();
  else if (step === 5) renderOnboardingRules();
  else renderOnboardingReadiness();
}

function renderOnboardingPeople() {
  const family = state.family;
  $("#app").innerHTML = onboardingShell(1, "先把需要联系的人放进来", "只填写第一次在旁练习必须知道的人和电话。当地紧急服务号码由你填写，不默认假设是 120。", `<form id="onboarding-people" class="card setup-card"><div class="form-grid">
    <div class="field"><label for="setup-caregiver">主要照护者姓名</label><input id="setup-caregiver" name="caregiverName" required autocomplete="name" value="${escapeHTML(family.caregiverName)}"></div>
    <div class="field"><label for="setup-caregiver-phone">主要照护者电话</label><input id="setup-caregiver-phone" name="caregiverPhone" type="tel" required autocomplete="tel" value="${escapeHTML(family.caregiverPhone)}"></div>
    <div class="field"><label for="setup-recipient">被照护者姓名</label><input id="setup-recipient" name="recipientName" required value="${escapeHTML(family.recipientName)}"></div>
    <div class="field"><label for="setup-relay">这次替班者姓名</label><input id="setup-relay" name="relayName" required value="${escapeHTML(family.relayName)}"></div>
    <div class="field"><label for="setup-emergency-name">另一位紧急联系人</label><input id="setup-emergency-name" name="emergencyContactName" required value="${escapeHTML(family.emergencyContactName)}"></div>
    <div class="field"><label for="setup-emergency-phone">紧急联系人电话</label><input id="setup-emergency-phone" name="emergencyContactPhone" type="tel" required value="${escapeHTML(family.emergencyContactPhone)}"></div>
    <div class="field field-full"><label for="setup-emergency-service">当地紧急服务号码</label><input id="setup-emergency-service" name="emergencyService" type="tel" required inputmode="tel" placeholder="请按所在地填写，例如当地急救或综合紧急号码" value="${escapeHTML(family.emergencyService)}"><span class="field-help">请核对所在地的真实号码；应用不会替你判断或自动填写。</span></div>
  </div>${setupFooter(1)}</form>`);
  $("#onboarding-people").addEventListener("submit", saveOnboardingPeople);
}

function saveOnboardingPeople(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const oldRecipientName = state.family.recipientName;
  state.family = {
    ...state.family,
    caregiverName: String(data.get("caregiverName") || "").trim(),
    caregiverPhone: String(data.get("caregiverPhone") || "").trim(),
    recipientName: String(data.get("recipientName") || "").trim(),
    relayName: String(data.get("relayName") || "").trim(),
    emergencyContactName: String(data.get("emergencyContactName") || "").trim(),
    emergencyContactPhone: String(data.get("emergencyContactPhone") || "").trim(),
    emergencyService: String(data.get("emergencyService") || "").trim(),
  };
  if (oldRecipientName && oldRecipientName !== state.family.recipientName && isRecipientAuthorized()) {
    revokeRecipientAuthorization({ persist: false });
    state.onboarding.consentDecision = "pending";
  }
  state.onboarding.step = 2;
  saveState();
  render();
}

function renderOnboardingGoal() {
  const goal = state.family.restGoal;
  $("#app").innerHTML = onboardingShell(2, "只定一个能实现的小休息", "写下一个具体休息目标和很短的目标窗口。第一次彩排仍会从大家都在场开始。", `<form id="onboarding-goal" class="card setup-card"><div class="form-grid">
    <div class="field field-full"><label for="setup-goal">我想把这段时间留给</label><input id="setup-goal" name="title" required maxlength="40" placeholder="例如：独自在楼下散步" value="${escapeHTML(goal.title)}"></div>
    <div class="field"><label for="setup-window">大概什么时候</label><input id="setup-window" name="date" required maxlength="30" placeholder="例如：周六下午" value="${escapeHTML(goal.date)}"></div>
    <div class="field"><label for="setup-duration">短目标（分钟）</label><input id="setup-duration" name="duration" type="number" min="10" max="60" required value="${Number(goal.duration) || 20}"><span class="field-help">先选 10–60 分钟，完成在旁观察后再尝试离开。</span></div>
  </div>${setupFooter(2)}</form>`);
  $("#onboarding-goal").addEventListener("submit", saveOnboardingGoal);
}

function saveOnboardingGoal(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  state.family.restGoal = { title: String(data.get("title") || "").trim(), date: String(data.get("date") || "").trim(), duration: Number(data.get("duration")) };
  state.onboarding.step = 3;
  saveState();
  render();
}

function renderOnboardingConsent() {
  const family = state.family;
  const decision = state.onboarding.consentDecision;
  const decisionMarkup = decision === "declined"
    ? `<div class="decision-banner declined">已记录：本人目前不同意。不会开始彩排，也不会把这当成照护者确认。</div>`
    : decision === "skipped" ? `<div class="decision-banner">已记录：这一步暂时跳过。完成其他设置后仍会回到这里。</div>` : "";
  $("#app").innerHTML = onboardingShell(3, `请把手机交给${escapeHTML(family.recipientName || "被照护者")}`, "这一页请由本人当面看过并作选择。照护者不能替对方预先勾选。不同意、暂时跳过或之后撤回，都不会解锁彩排。", `<form id="onboarding-consent" class="card setup-card consent-step"><div class="handoff-callout"><span>${icon("i-phone")}</span><div><b>现在由本人阅读，或请照护者逐句读出</b><p>“接班彩排会保存我们明确提供的日常做法，让${escapeHTML(family.relayName || "替班者")}在练习时查看。我可以不同意、跳过，之后也可以随时撤回。”</p></div></div>
    ${decisionMarkup}
    <label class="confirm-item consent-control"><input type="checkbox" name="recipientConsent" required><span><b>我本人现在同意参与第一次“在旁观察”彩排</b><small>这不是长期承诺；开始每次彩排仍会再次询问。</small></span></label>
    <div class="consent-actions"><button type="button" class="btn btn-secondary" data-action="consent-decline">本人不同意</button><button type="button" class="btn btn-ghost" data-action="consent-skip">暂时跳过</button><button class="btn btn-primary" type="submit">本人同意，继续${icon("i-arrow")}</button></div></form>`);
  $("#onboarding-consent").addEventListener("submit", saveOnboardingConsent);
}

function saveOnboardingConsent(event) {
  event.preventDefault();
  if (!event.currentTarget.elements.recipientConsent.checked) return;
  if (!state.family.recipientName) { state.onboarding.step = 1; saveState(); render(); toast("请先填写被照护者姓名，再由本人当面确认"); return; }
  if (!isRecipientAuthorized()) grantRecipientAuthorization();
  state.onboarding.consentDecision = "granted";
  state.onboarding.step = 4;
  saveState();
  render();
}

function recordOnboardingConsentDecision(decision) {
  if (isRecipientAuthorized()) revokeRecipientAuthorization({ persist: false });
  state.onboarding.consentDecision = decision;
  state.onboarding.step = 4;
  saveState();
  render();
  toast(decision === "declined" ? "已记录本人不同意；彩排保持锁定" : "已暂时跳过；稍后仍需本人当面确认");
}

function renderOnboardingGuide() {
  const family = state.family;
  const guide = onboardingGuide();
  const sources = availableGuideSources();
  $("#app").innerHTML = onboardingShell(4, "准备一个低风险的日常片段", "只写眼前会遇到的普通生活情境，以及某个人明确说过的处理方式。语音只是设备输入，保存前请核对文字。", `<form id="onboarding-guide" class="card setup-card"><div class="form-grid">
    <div class="field field-full"><label for="setup-situation">低风险情境</label><div class="speech-field"><input id="setup-situation" name="title" required maxlength="40" placeholder="例如：整理照片时想停下来" value="${escapeHTML(guide?.title || "")}"><button type="button" class="mic-btn" data-action="record-setup-situation" aria-label="用语音输入低风险情境">${icon("i-mic")}</button></div></div>
    <div class="field field-full"><label for="setup-instruction">已经明确说过的处理方式</label><div class="speech-field"><textarea id="setup-instruction" name="summary" required maxlength="220" placeholder="逐字写下家庭成员或已有专业指示的做法，不要猜测">${escapeHTML(guide?.summary || "")}</textarea><button type="button" class="mic-btn" data-action="record-setup-instruction" aria-label="用语音输入处理方式">${icon("i-mic")}</button></div><span class="field-help" id="setup-speech-status">可直接输入；若设备支持，也可点麦克风。</span></div>
    <div class="field field-full"><label for="setup-source">这段处理方式来自谁</label><select id="setup-source" name="sourceId" required><option value="">请选择真实来源</option>${sources.map((source) => `<option value="${source.id}" ${guide?.provenance?.actorId === source.id ? "selected" : ""}>${escapeHTML(source.label)}</option>`).join("")}</select><span class="field-help">浏览器不能把录入内容标为专业来源；内置专业引用由安全策略只读提供。</span></div>
  </div><div class="safety-note">${icon("i-alert")}胸痛、呼吸困难、血压变化、脸色发白、跌倒、意识或用药等高风险内容不作为第一次练习的前提。请使用下方联系电话并取得专业指示。</div><div class="direct-call-row"><a class="btn btn-secondary btn-small" href="${phoneHref(family.caregiverPhone)}">${icon("i-phone")}联系${escapeHTML(family.caregiverName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(family.emergencyService)}">拨打 ${escapeHTML(family.emergencyService)}</a></div>${setupFooter(4)}</form>`);
  $("#onboarding-guide").addEventListener("submit", saveOnboardingGuide);
}

function saveOnboardingGuide(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const title = String(data.get("title") || "").trim();
  const summary = String(data.get("summary") || "").trim();
  const sourceId = String(data.get("sourceId") || "");
  if (SafetyPolicy.classifyFields([title, summary]).highRisk) {
    toast("这属于医疗或高风险内容，不作为第一次练习；请使用直接联系并另行取得专业指示");
    return;
  }
  const source = sourceDefinition(sourceId);
  if (!source?.authorized || !availableGuideSources().some((item) => item.id === sourceId)) {
    toast("请选择当前获授权的真实来源");
    return;
  }
  const current = state.onboarding.guideId ? state.guides.find((item) => item.id === state.onboarding.guideId) : null;
  if (current) {
    const oldConfirmation = state.confirmations.find((record) => record.id === current.confirmationId);
    if (oldConfirmation) oldConfirmation.status = "superseded";
  }
  const guideId = current?.id || `onboarding-guide-${Date.now()}`;
  const confirmationId = addConfirmation({ type: "guide", actorId: sourceId, guideId, consentRevision: sourceId === SOURCE_IDS.RECIPIENT ? state.recipientConsent.revision : null });
  const nextGuide = {
    ...(current || {}), id: guideId, version: (current?.version || 0) + 1, status: "usable", confirmationId,
    provenance: { actorId: sourceId, actorType: source.actorType, labelAtConfirmation: source.label, ...(sourceId === SOURCE_IDS.RECIPIENT ? { consentRevision: state.recipientConsent.revision } : {}) },
    icon: "i-spark", tone: "mint", category: "daily", title, summary, source: source.label, sourceAvatar: source.avatar, sourceClass: source.className,
    updated: "设置时刚刚确认", level: "here", rule: "现场可处理", audio: false, highRisk: false, policyVersion: SafetyPolicy.VERSION, fromOnboarding: true,
  };
  if (current) state.guides = state.guides.map((item) => item.id === current.id ? nextGuide : item);
  else state.guides.unshift(nextGuide);
  state.onboarding.guideId = guideId;
  state.onboarding.step = 5;
  saveState();
  render();
}

function renderOnboardingRules() {
  const family = state.family;
  const lines = [...family.redLines, "", ""].slice(0, 3);
  $("#app").innerHTML = onboardingShell(5, "一起看清红线和直接联系", "下面是保守示例，不是你家的既定事实。只有点选或亲自填写并保存，才会成为本家庭红线。联系电话始终保留。", `<form id="onboarding-rules" class="card setup-card"><div class="example-box"><b>可点选的示例</b><div><button type="button" data-action="use-redline-example" data-value="无法唤醒">无法唤醒</button><button type="button" data-action="use-redline-example" data-value="走失或找不到人">走失或找不到人</button><button type="button" data-action="use-redline-example" data-value="胸痛或呼吸困难">胸痛或呼吸困难</button></div><small>这些只是建议；请根据家庭已有安排修改。</small></div><div class="form-grid">${lines.map((line, index) => `<div class="field field-full"><label for="setup-redline-${index}">本家庭红线 ${index + 1}（可留空）</label><input id="setup-redline-${index}" name="redline" maxlength="36" value="${escapeHTML(line)}" placeholder="点上方示例，或填写需要立即联系的事件"></div>`).join("")}</div>
    <div class="call-review"><a href="${phoneHref(family.caregiverPhone)}">${icon("i-phone")}<span>主要照护者<br><b>${escapeHTML(family.caregiverPhone)}</b></span></a><a href="${phoneHref(family.emergencyContactPhone)}">${icon("i-phone")}<span>紧急联系人<br><b>${escapeHTML(family.emergencyContactPhone)}</b></span></a><a class="urgent" href="${phoneHref(family.emergencyService)}">${icon("i-alert")}<span>当地紧急服务<br><b>${escapeHTML(family.emergencyService)}</b></span></a></div>
    <label class="confirm-item"><input type="checkbox" name="rulesReviewed" required>我们现在已核对红线文字和三条直接联系路径；示例不会被静默确认。</label>${setupFooter(5, "保存并查看准备情况")}</form>`);
  $("#onboarding-rules").addEventListener("submit", saveOnboardingRules);
}

function saveOnboardingRules(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  state.family.redLines = data.getAll("redline").map((value) => String(value).trim()).filter(Boolean);
  state.onboarding.redLinesReviewedAt = nowISO();
  state.onboarding.step = 6;
  saveState();
  render();
}

function redLinesText() {
  return state.family.redLines.length ? state.family.redLines.join("、") : "家庭尚未添加具体红线；任何不确定或紧急情况都可直接联系";
}

function renderOnboardingReadiness() {
  const family = state.family;
  const guide = onboardingGuide();
  const ready = onboardingReady();
  const checks = [
    [setupBasicsReady(), "成员与本地联系电话", 1],
    [Boolean(family.restGoal.title && family.restGoal.date), "一个短休息目标", 2],
    [isRecipientAuthorized(), `${family.recipientName || "被照护者"}本人当面同意`, 3],
    [Boolean(guide), "一条有明确来源的低风险指导", 4],
    [Boolean(state.onboarding.redLinesReviewedAt), "红线示例与直接联系已核对", 5],
  ];
  $("#app").innerHTML = onboardingShell(6, ready ? "准备好了：第一次只在旁观察" : "还差一步，不会勉强开始", ready ? `第一次练习中，${escapeHTML(family.caregiverName)}、${escapeHTML(family.recipientName)}和${escapeHTML(family.relayName)}都在场。约 5 分钟，照护者不会离家。` : "未完成的项目不会被当作家庭事实，也不会解锁彩排。可以回去补充或重新询问本人。", `<section class="card setup-card readiness-review"><div class="readiness-list">${checks.map(([done, label, jumpStep]) => `<button type="button" class="readiness-row ${done ? "done" : "missing"}" data-action="onboarding-jump" data-step="${jumpStep}"><span>${icon(done ? "i-check" : "i-lock")}</span><b>${escapeHTML(label)}</b><small>${done ? "已完成" : "返回补充"}</small></button>`).join("")}</div>${guide ? `<div class="first-guide-review"><small>本次只练</small><h3>${escapeHTML(guide.title)}</h3><p>${escapeHTML(guide.summary)}</p>${guideSourceRow(guide)}</div>` : ""}<div class="handoff-callout"><span>${icon("i-phone")}</span><div><b>开始后由${escapeHTML(family.relayName || "替班者")}拿这台手机</b><p>${escapeHTML(family.caregiverName || "照护者")}留在旁边观察；任何人都可以立即结束。下一页还会再次确认交接手机。</p></div></div><div class="setup-footer"><button type="button" class="btn btn-secondary" data-action="onboarding-back">上一步</button><button type="button" class="btn ${ready ? "btn-coral" : "btn-secondary"}" data-action="start-rehearsal">${icon(ready ? "i-play" : "i-lock")}${ready ? "开始第一次在旁观察" : "完成上方项目后开始"}</button></div></section>`);
}

function pageHeader(kicker, title, description, actions = "") {
  return `<header class="page-head">
    <div><div class="page-kicker">${kicker}</div><h1>${title}</h1><p>${description}</p></div>
    ${actions ? `<div class="head-actions">${actions}</div>` : ""}
  </header>`;
}

function choiceLabel(choice) {
  return { extend: "延长一级", repeat: "重复本级", "step-back": "退回一级" }[choice] || "尚未回答";
}

function sessionTrendMarkup(records = state.sessions) {
  const actual = normalizeOutcomeSessions(records).filter((record) => record.status !== "legacy" && record.facts).slice(-6);
  if (!actual.length) return `<div class="empty-outcomes"><b>还没有可画出的实际记录</b><span>完成一次新的可测量彩排后，这里只按记录展示时长与自报信心，不解释原因。</span></div>`;
  const maximum = Math.max(1, ...actual.map((record) => record.facts.actualElapsedSeconds || 0));
  return `<div class="outcome-trend" aria-label="最近 ${actual.length} 次实际记录趋势">${actual.map((record) => `<button data-action="session-detail" data-session-id="${escapeHTML(record.id)}" style="--actual:${Math.max(8, Math.round((record.facts.actualElapsedSeconds || 0) / maximum * 100))}%"><span class="trend-bar"></span><b>${Math.floor((record.facts.actualElapsedSeconds || 0) / 60)}分</b><small>${escapeHTML(OutcomeModel.STAGE_LABELS[record.startSnapshot.stage])}</small><em>${record.checkIns.caregiver?.confidence ? `信心 ${record.checkIns.caregiver.confidence}/5` : "信心未答"}</em></button>`).join("")}</div><p class="trend-caveat">只展示实际保存的先后记录；不表示彩排造成了信心、休息或健康变化。</p>`;
}

function demoJourneyState() {
  if (state.mode !== "demo") return null;
  state.demoJourney = {
    step: 0,
    role: "caregiver",
    knownSeen: false,
    ordinarySeen: false,
    medicalSeen: false,
    sampleSessionId: null,
    finished: false,
    ...(state.demoJourney || {}),
  };
  return state.demoJourney;
}

function demoJourneyStage(step = demoJourneyState()?.step || 0) {
  if (step <= 1) return "observe";
  if (step <= 4) return "short-leave";
  return "quiet-handoff";
}

function demoRoleDefinition(role = demoJourneyState()?.role) {
  return {
    caregiver: {
      label: state.family.caregiverName || "主要照护者",
      role: "主要照护者",
      icon: "岚",
      action: "说明本次边界、保留直接联系，并只填写自己的休息与选择。",
    },
    substitute: {
      label: state.family.relayName || "替班者",
      role: "替班者",
      icon: "珊",
      action: "只处理本次获授权的低风险范围；不知道就留缺口，红线就直接联系。",
    },
    careRecipient: {
      label: state.family.recipientName || "被照护者",
      role: "被照护者",
      icon: "琴",
      action: "决定是否参与，可随时撤回；舒适度与偏好由本人选择是否回答。",
    },
  }[role];
}

function createJudgeDemoOutcome() {
  const id = "judge-demo-short-leave-20260725";
  const guide = focusGuide();
  const existing = outcomeRecord(id);
  if (existing) return existing;
  const participants = {
    caregiver: { id: SOURCE_IDS.CAREGIVER, label: state.family.caregiverName },
    substitute: { id: SOURCE_IDS.RELAY, label: state.family.relayName },
    careRecipient: { id: SOURCE_IDS.RECIPIENT, label: state.family.recipientName },
  };
  const record = OutcomeModel.createSession({
    id,
    stage: "short-leave",
    plannedDurationMinutes: 20,
    mode: "two-device",
    startedAt: "2026-07-25T08:30:00.000Z",
    status: "completed",
    consentRevision: state.recipientConsent.revision,
    guideScope: [{
      id: guide.id,
      version: guide.version,
      title: guide.title,
      source: sourceView(guide).label,
      actorId: guide.provenance.actorId,
      level: guide.level,
      rule: guide.rule,
    }],
    redLines: [...state.family.redLines],
    participants,
    policyVersion: SafetyPolicy.VERSION,
    safetyRevision: companionSafetyRevision(),
    demo: true,
    facts: {
      endedAt: "2026-07-25T08:50:08.000Z",
      recordedAt: "2026-07-25T08:50:08.000Z",
      actualElapsedSeconds: 1208,
      completedSteps: [true, true, true],
      routineUpdatesQueued: 1,
      pendingGaps: [],
      urgentAlertsRaised: 0,
      contactActionsOpened: [],
    },
    checkIns: {
      caregiver: {
        submittedAt: "2026-07-25T08:54:00.000Z",
        restHappened: "yes",
        phoneChecks: "1-2",
        nonurgentInterrupted: "no",
        confidence: 4,
        feltUnsafe: false,
        choice: "extend",
        partial: false,
      },
      substitute: {
        submittedAt: "2026-07-25T08:52:00.000Z",
        ableToHandle: "yes",
        uncertainStep: "没有仍不确定的步骤",
        contactedCaregiver: "no",
        feltUnsafe: false,
        choice: "extend",
        partial: false,
      },
      careRecipient: {
        submittedAt: "2026-07-25T08:55:00.000Z",
        response: "answered",
        comfort: "comfortable",
        preference: "下次仍请先告诉我谁会留下来。",
        partial: false,
      },
    },
  });
  state.sessions = [...state.sessions.filter((item) => item.id !== id), record];
  state.recommendationOverride = null;
  syncCompatibilityProgress(state);
  return record;
}

function demoJourneyMarkup() {
  const journey = demoJourneyState();
  const step = journey.step;
  const activeStage = demoJourneyStage(step);
  const role = demoRoleDefinition();
  const guide = focusGuide();
  const ordinaryGap = state.gaps.find((gap) => gap.id === journey.ordinaryGapId);
  const medicalGap = state.gaps.find((gap) => gap.id === journey.medicalGapId);
  const sample = journey.sampleSessionId ? outcomeRecord(journey.sampleSessionId) : null;
  const recommendation = householdRecommendation();
  const steps = [
    ["observe", "在旁观察", "三人都在场"],
    ["short-leave", "短时离开", "只接低风险范围"],
    ["quiet-handoff", "安静离班", "普通事情结束后再看"],
  ];
  const activeIndex = OutcomeModel.stageIndex(activeStage);
  const roleButtons = [
    ["caregiver", state.family.caregiverName, "主要照护者"],
    ["substitute", state.family.relayName, "替班者"],
    ["careRecipient", state.family.recipientName, "被照护者"],
  ].map(([id, name, label]) => `<button type="button" class="${journey.role === id ? "active" : ""}" data-action="judge-role" data-role="${id}" aria-pressed="${journey.role === id}"><span>${escapeHTML(String(name || label).slice(-1))}</span><b>${escapeHTML(name || label)}</b><small>${label}</small></button>`).join("");
  let content;

  if (step === 0) {
    content = `<div class="judge-intro"><span class="judge-step-label">起点 · 30 秒</span><h2 id="judge-step-title" tabindex="-1">2–3 分钟看懂：从愿意帮忙，到有证据的安静离班</h2><p>这是一条脚本化演示，不是周岚家庭的真实结果。你会看到休息有没有发生如何由应用事实和参与者回答共同决定，而不是由“完成”按钮或营销文案决定。</p><div class="judge-wedge"><b>产品楔子</b><span>不替代微信、电话或紧急服务；把非正式帮忙变成演练过、有来源、可归属、可撤回的低风险交接证据和受保护休息。</span></div><div class="judge-role-explainer" aria-label="三种角色的简短说明">${["caregiver", "substitute", "careRecipient"].map((id) => { const item = demoRoleDefinition(id); return `<article><span>${escapeHTML(item.icon)}</span><div><b>${escapeHTML(item.role)}</b><p>${escapeHTML(item.action)}</p></div></article>`; }).join("")}</div><button class="btn btn-primary" data-action="judge-next">开始：先在旁看一次${icon("i-arrow")}</button></div>`;
  } else if (step === 1) {
    content = `<div class="judge-story"><span class="judge-step-label">第 1 站 · 在旁观察</span><h2 id="judge-step-title" tabindex="-1">已知低风险问题，只返回当前有来源的做法</h2><p>${escapeHTML(state.family.relayName)}拿着设备，${escapeHTML(state.family.caregiverName)}仍在旁边。演示提问：“她说不饿，不愿意吃午饭。”</p>${journey.knownSeen ? `<div class="judge-result safe"><span>${icon("i-check")}找到 1 条当前可用指导</span><h3>${escapeHTML(guide.title)}</h3><p>${escapeHTML(guide.summary)}</p><small>${icon("i-shield")}来源：${escapeHTML(sourceView(guide).label)} · v${guide.version} · ${escapeHTML(guide.rule)}</small></div><button class="btn btn-primary" data-action="judge-next">继续：照护者短时离开${icon("i-arrow")}</button>` : `<button class="btn btn-coral" data-action="judge-known">${icon("i-spark")}演示这次安全匹配</button>`}</div>`;
  } else if (step === 2) {
    content = `<div class="judge-story"><span class="judge-step-label">第 2 站 · 短时离开</span><h2 id="judge-step-title" tabindex="-1">普通未知，也不会被“相似答案”糊弄过去</h2><p>${escapeHTML(state.family.relayName)}问：“她想把收音机搬到窗边。”当前没有逐字确认过的处理方式。</p>${journey.ordinarySeen && ordinaryGap ? `<div class="judge-result pending"><span>${icon("i-lock")}普通待确认缺口</span><h3>已记录，但没有混入可用指导</h3><p>第 ${ordinaryGap.encounters || 1} 次遇到 · 来源待家庭复核 · 现场仍可直接联系照护者。</p></div><button class="btn btn-primary" data-action="judge-next">继续：看红线怎么升级${icon("i-arrow")}</button>` : `<button class="btn btn-coral" data-action="judge-ordinary">${icon("i-plus")}记录这个普通未知</button>`}</div>`;
  } else if (step === 3) {
    content = `<div class="judge-story"><span class="judge-step-label">第 3 站 · 红线升级</span><h2 id="judge-step-title" tabindex="-1">医疗或红线问题停在这里，直接找人</h2><p>演示提问：“她说胸口发紧。”关键词护栏只是保守原型筛查，不是诊断或临床分诊。</p>${journey.medicalSeen && medicalGap ? `<div class="judge-result danger"><span>${icon("i-alert")}医疗 / 高风险待确认</span><h3>没有生成现场处理建议</h3><p>这条记录与普通缺口分开；应用不会把家庭文字伪装成专业来源。这是一张独立的安全分支演示卡，不会被并入下一步那条无红线的成功样本。</p><div class="direct-call-row judge-direct-calls" aria-label="真实可用的直接联系电话"><a class="btn btn-secondary btn-small" href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}拨给${escapeHTML(state.family.caregiverName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(state.family.emergencyService)}">${icon("i-alert")}紧急危险 · ${escapeHTML(state.family.emergencyService)}</a></div><small>电话按钮会打开设备拨号；不代表通话已经接通。</small></div><button class="btn btn-primary" data-action="judge-next">继续：看另一条无红线样本的回看${icon("i-arrow")}</button>` : `<button class="btn btn-coral" data-action="judge-medical">${icon("i-alert")}查看保守升级结果</button>`}</div>`;
  } else if (step === 4) {
    content = `<div class="judge-story"><span class="judge-step-label">第 4 站 · 短时离开收尾</span><h2 id="judge-step-title" tabindex="-1">“现场完成”不等于“可以升级”</h2><p>下面载入的是另一条明确标注的、没有红线事件的短时离开演示样本。应用只记录它看得到的事实；照护者、替班者和被照护者各自署名回答。</p>${sample ? `<div class="judge-checkin-complete"><div><span class="source-chip app-source">应用记录</span><b>20 分 08 秒 · 3 / 3 步</b><small>普通更新 1 · 紧急事件 0 · 未解决医疗缺口 0</small></div><div><span class="source-chip self-source">参与者自报</span><b>照护者：4/5 · 选择延长</b><small>休息发生 · 1–2 次看手机 · 未感到不安全</small></div><div><span class="source-chip self-source">参与者自报</span><b>替班者：能处理 · 选择延长</b><small>未联系照护者 · 未感到不安全</small></div><div><span class="source-chip self-source">本人可选回答</span><b>本人回答：舒服</b><small>这不是照护者或应用替本人填写的结论</small></div></div><button class="btn btn-primary" data-action="judge-next">让规则给出下一档${icon("i-arrow")}</button>` : `<button class="btn btn-coral" data-action="judge-checkin">${icon("i-check")}载入已署名的演示回看</button>`}</div>`;
  } else if (step === 5) {
    content = `<div class="judge-story"><span class="judge-step-label">第 5 站 · 证据给出下一档</span><h2 id="judge-step-title" tabindex="-1">建议：${escapeHTML(OutcomeModel.STAGE_LABELS[recommendation.stage])}</h2><p>没有隐藏分数。建议来自刚才那条演示会话的固定范围、结束事实和双方选择；照护者仍可下调到更保守的档位。</p><div class="judge-recommendation"><span class="decision-pill decision-${escapeHTML(recommendation.decision)}">${recommendation.decision === "extend" ? "满足保守延长条件" : "保持更保守档位"}</span><ul>${recommendation.reasons.map((reason) => `<li>${escapeHTML(reason)}</li>`).join("")}</ul><small>来源会话：${escapeHTML(recommendation.sourceSessionId || "无")} · 演示样本</small></div><button class="btn btn-primary" data-action="judge-next">看看安静离班保护什么${icon("i-arrow")}</button></div>`;
  } else {
    content = `<div class="judge-story"><span class="judge-step-label">终点 · 安静离班预览</span><h2 id="judge-step-title" tabindex="-1">普通事情排队，停止与直接联系一直看得见</h2><p>这不是“失联模式”，也不是通知服务承诺。浏览器在后台或设备休眠时不能保证提醒；真正紧急时仍应使用直接电话与当地紧急服务。</p><div class="judge-quiet-preview"><div><small>演示休息窗口</small><strong>90:00</strong><span>尚未真实开始</span></div><div><small>普通更新</small><strong>1</strong><span>结束后再看文字</span></div><div><small>当前接班者</small><strong>${escapeHTML(state.family.relayName)}</strong><span>范围仍可撤回</span></div></div><div class="direct-call-row judge-direct-calls"><a class="btn btn-secondary btn-small" href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}联系${escapeHTML(state.family.caregiverName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(state.family.emergencyService)}">${icon("i-alert")}当地紧急服务 ${escapeHTML(state.family.emergencyService)}</a></div><div class="judge-finish-actions"><button class="btn btn-secondary" data-action="judge-restart">${icon("i-play")}从头重播</button><button class="btn btn-primary" data-action="judge-finish">查看完整演示家庭${icon("i-arrow")}</button></div></div>`;
  }

  return `<section class="judge-demo" aria-labelledby="judge-step-title" data-judge-step="${step}">
    <header class="judge-demo-top"><div><span class="demo-beacon"><i></i>演示模式 · 脚本化样本 · 非真实家庭</span><small>评审导览 ${Math.min(step + 1, 6)} / 6 · 约 ${step < 2 ? "2 分钟" : "1 分钟"}剩余</small></div><button type="button" class="text-button" data-action="judge-restart">${icon("i-play")}重新开始</button></header>
    <ol class="judge-stage-track" aria-label="三档彩排路径">${steps.map(([id, label, hint], index) => `<li class="${index < activeIndex ? "done" : index === activeIndex ? "current" : ""}" ${index === activeIndex ? `aria-current="step"` : ""}><span>${index < activeIndex ? icon("i-check") : index + 1}</span><div><b>${label}</b><small>${hint}</small></div></li>`).join("")}</ol>
    <div class="judge-context" aria-label="当前角色、授权和下一步"><div><small>现在谁在操作</small><b>${escapeHTML(role.label)} · ${escapeHTML(role.role)}</b></div><div><small>当前获授权范围</small><b>${isRecipientAuthorized() ? `本人同意 v${state.recipientConsent.revision} · ${usableGuides().length} 条有来源做法` : `本人参与已撤回 · 旧建议已失效 · 剩余 ${usableGuides().length} 条其他来源做法`}</b></div><div><small>随时可以</small><b>停止 · 撤回 · 直接联系</b></div></div>
    <div class="judge-role-switcher" role="group" aria-label="切换角色视角">${roleButtons}</div>
    <div class="judge-role-status" role="status" aria-live="polite"><b>${escapeHTML(role.role)}此刻要做什么：</b>${escapeHTML(role.action)}</div>
    <div class="judge-content">${content}</div>
    <footer class="judge-demo-footer"><div><span>${icon("i-shield")}所有演示结果都标为演示；真实家庭不会自动获得这些成员、记录或建议。</span><small>可核对：实际完成的离班分钟 · 完成全部步骤的独立交接 · 建议下一次及理由</small></div><div class="judge-shortcuts"><button class="text-button" data-action="start-rehearsal">跳过导览，开始完整彩排</button><button class="text-button" data-action="outcome-history">查看全部记录</button><button class="text-button" data-action="export-report">导出 / 打印</button><button class="text-button" data-nav="guides">全部 ${usableGuides().length} 条已确认做法${icon("i-arrow")}</button></div></footer>
  </section>`;
}

function renderHome() {
  const goal = state.family.restGoal;
  const currentGuides = usableGuides();
  const rehearsalGuide = focusGuide();
  const recommendation = householdRecommendation();
  const summary = OutcomeModel.metrics(state.sessions);
  const stage = recommendation.stage;
  const rehearsalAllowed = isRecipientAuthorized() && Boolean(rehearsalGuide);
  const twoDeviceRecommended = rehearsalAllowed && stage !== "observe";
  const recent = normalizeOutcomeSessions(state.sessions).filter((record) => record.status !== "legacy").at(-1);
  const hasLegacyOnly = state.sessions.length > 0 && !recent;
  const primaryAction = HOSTED_STATIC_REVIEW && stage !== "observe"
    ? `<button class="btn btn-primary" data-action="show-local-full-experience">${icon("i-home")}本地完整体验 · 双机配对</button><button class="btn btn-ghost" data-action="start-rehearsal">公开版单机演示</button>`
    : stage === "quiet-handoff"
    ? `<button class="btn btn-primary" data-action="companion-primary">${icon("i-phone")}双机开始安静接班</button><button class="btn btn-ghost" data-nav="rest">同机安静接班</button>`
    : twoDeviceRecommended
      ? `<button class="btn btn-primary" data-action="companion-primary">${icon("i-phone")}推荐 · 邀请替班者手机</button><button class="btn btn-ghost" data-action="start-rehearsal">同机备用</button>`
      : `<button class="btn btn-primary" data-action="start-rehearsal">${icon(rehearsalAllowed ? "i-play" : "i-lock")}${rehearsalAllowed ? `开始${OutcomeModel.STAGE_LABELS[stage]}` : "查看彩排安全门"}</button>`;
  const demoJourney = state.mode === "demo" ? demoJourneyMarkup() : "";
  const demoWorkspaceStart = state.mode === "demo" ? `<details class="demo-workspace" ${state.demoJourney?.finished ? "open" : ""}><summary><span>${icon("i-home")}</span><div><b>完整演示家庭工作区</b><small>按需展开结果历史、趋势、指导与双机入口</small></div>${icon("i-arrow")}</summary><div class="demo-workspace-body">` : "";
  const demoWorkspaceEnd = state.mode === "demo" ? `</div></details>` : "";
  $("#app").innerHTML = `<div class="page home-page outcome-home">${demoJourney}${demoWorkspaceStart}
    <section class="home-hero outcome-hero">
      <div class="hero-copy"><div class="overline">建议下一次 · ${escapeHTML(OutcomeModel.STAGE_LABELS[stage])}</div><h1>休息是否发生，<em>由记录和本人回答说话。</em></h1><p>${hasLegacyOnly ? "旧完成标记没有时长或参与者回答，先做一次新的可测量彩排。" : recommendation.reasons.map(escapeHTML).join("；")}</p><div class="hero-actions">${primaryAction}<button class="btn btn-ghost" data-action="outcome-history">查看全部记录${icon("i-arrow")}</button></div></div>
      <aside class="recommendation-proof"><small>为什么是这一档</small><strong>${escapeHTML(OutcomeModel.STAGE_LABELS[stage])}</strong><span class="decision-pill decision-${escapeHTML(recommendation.decision)}">${escapeHTML({ extend:"双方选择延长",repeat:"保持本级",stepBack:"退回一级","step-back":"退回一级",hold:"暂缓",measure:"需要一次新记录","medical-hold":"医疗/高风险暂缓","user-override":"照护者下调" }[recommendation.decision] || recommendation.decision)}</span><ul>${recommendation.reasons.map((reason) => `<li>${escapeHTML(reason)}</li>`).join("")}</ul>${OutcomeModel.stageIndex(stage) > 0 ? `<button data-action="override-stage" data-stage="${OutcomeModel.previousStage(stage)}">我想更保守：改为${OutcomeModel.STAGE_LABELS[OutcomeModel.previousStage(stage)]}</button>` : ""}</aside>
    </section>

    <div class="section-row"><div><h2>家庭能核对的结果</h2><p>${state.mode === "demo" ? "演示记录 · 仅用于展示机制" : "只汇总本设备实际保存的数据"}</p></div><div class="section-actions"><button class="text-button" data-action="outcome-history">历史与来源</button><button class="text-button" data-action="export-report">导出 / 打印</button></div></div>
    <section class="outcome-metrics" aria-label="家庭彩排事实摘要"><article><strong>${summary.protectedMinutes}</strong><span>实际完成的离班分钟</span></article><article><strong>${summary.independentHandoffs}</strong><span>完成全部步骤的独立交接</span></article><article><strong>${summary.routineUpdatesDeferred}</strong><span>产品延后的普通更新</span></article><article class="${summary.urgentEvents ? "urgent" : ""}"><strong>${summary.urgentEvents}</strong><span>记录到的紧急事件</span></article><article><strong>${summary.lastCaregiverConfidence || "—"}</strong><span>最近照护者信心${summary.lastCaregiverConfidence ? " / 5" : " · 未答"}</span></article><article><strong>${escapeHTML(choiceLabel(summary.lastChoice))}</strong><span>最近照护者选择</span></article></section>

    ${recent ? `<article class="card latest-outcome"><div><span class="source-chip app-source">应用记录</span><small>${new Date(recent.startSnapshot.startedAt).toLocaleString("zh-CN")}</small><h3>${escapeHTML(OutcomeModel.STAGE_LABELS[recent.startSnapshot.stage])} · ${escapeHTML(OutcomeModel.STATUS_LABELS[recent.status] || recent.status)}</h3><p>${recent.facts ? `实际 ${Math.floor(recent.facts.actualElapsedSeconds / 60)} 分 ${recent.facts.actualElapsedSeconds % 60} 秒；${recent.facts.completedSteps.filter(Boolean).length}/${recent.facts.completedSteps.length || 3} 步；普通更新 ${recent.facts.routineUpdatesQueued}；紧急事件 ${recent.facts.urgentAlertsRaised}` : "详细结果未记录"}</p></div><div class="latest-self-report"><span class="source-chip self-source">自报</span><b>照护者：${recent.checkIns.caregiver ? `${recent.checkIns.caregiver.confidence || "未答"}/5 · ${choiceLabel(recent.checkIns.caregiver.choice)}` : "未填写"}</b><b>替班者：${recent.checkIns.substitute ? choiceLabel(recent.checkIns.substitute.choice) : "未填写"}</b><button class="btn btn-secondary btn-small" data-action="session-detail" data-session-id="${escapeHTML(recent.id)}">查看分来源详情</button></div></article>` : `<article class="card empty-outcomes"><b>还没有真实彩排结果</b><span>开始时会保存固定范围；结束时只记录应用看得到的事实，再由每个人填写自己的感受和选择。</span></article>`}

    <div class="section-row"><div><h2>最近几次的实际记录</h2><p>时长与自报信心并排展示，不推断因果</p></div></div><section class="card trend-card">${sessionTrendMarkup()}</section>
    <div class="section-row"><div><h2>当前可用情境指导</h2><p>只展示来源当前仍获授权的内容</p></div><button class="text-button" data-nav="guides">全部 ${currentGuides.length} 条${icon("i-arrow")}</button></div><section class="guide-strip">${currentGuides.length ? currentGuides.slice(0, 5).map(guideTile).join("") : `<article class="card empty-guides"><h3>暂无当前可用指导</h3><p>紧急联系仍然可用；请在授权后由家庭重新确认日常处理方式。</p></article>`}</section>
  ${demoWorkspaceEnd}</div>`;
}

function guideTile(guide) {
  return `<button class="guide-tile" data-action="guide-detail" data-id="${guide.id}"><span class="guide-icon tone-${guide.tone}">${icon(guide.icon)}</span><h3>${escapeHTML(guide.title)}</h3><p>${escapeHTML(guide.rule)} · ${escapeHTML(sourceView(guide).label)}</p></button>`;
}

function renderGuides() {
  const filters = [
    { id: "all", label: "全部" }, { id: "daily", label: "日常照护" }, { id: "preference", label: "个人偏好" }, { id: "urgent", label: "红线事件" },
  ];
  const currentGuides = usableGuides();
  const filtered = state.guideFilter === "all" ? currentGuides : currentGuides.filter((guide) => guide.category === state.guideFilter);
  const pendingGaps = state.gaps.filter((gap) => gap.status === "pending");
  $("#app").innerHTML = `<div class="page guides-page">
    ${pageHeader("SCENARIO GUIDES", "在需要的那一刻，听见熟悉的做法", "只呈现照护者、被照护者或专业人员明确确认过的内容；系统不会补写医疗和安全建议。", `<button class="btn btn-secondary" data-action="safety-rules">${icon("i-shield")}升级规则</button><button class="btn btn-primary" data-action="add-guide">${icon("i-plus")}新增指导</button>`)}
    <div class="filter-bar">
      <div class="segmented" role="tablist" aria-label="筛选情境">${filters.map((filter) => `<button class="segment ${state.guideFilter === filter.id ? "active" : ""}" role="tab" aria-selected="${state.guideFilter === filter.id}" data-filter="${filter.id}">${filter.label}${filter.id === "all" ? ` · ${currentGuides.length}` : ""}</button>`).join("")}</div>
      <span class="demo-chip"><i></i>内容仅保存在本设备</span>
    </div>
    ${pendingGaps.length ? `<section class="gap-panel"><div><span class="gap-panel-icon">${icon("i-spark")}</span><span><strong>${pendingGaps.length} 个现场问题等待确认</strong><small>每一条记录都可在右侧打开复核；补充明确来源前不会变成指导。</small></span></div><div class="gap-list">${pendingGaps.map((gap) => `<button data-action="review-gap" data-id="${gap.id}" aria-label="复核待确认情境：${escapeHTML(gap.query)}"><span>${escapeHTML(gap.query)}</span><small>${gap.risk === "medical" ? "医疗或高风险 · " : "待确认 · "}现场遇到 ${gap.encounters || 1} 次</small>${icon("i-arrow")}</button>`).join("")}</div></section>` : ""}
    <section class="guide-grid">
      ${filtered.map(guideCard).join("")}
      <button class="card guide-card new-guide-card" data-action="add-guide"><span class="add-circle">${icon("i-plus")}</span><h3>记录一个新情境</h3><p>从一句实际遇到的问题开始</p></button>
    </section>
  </div>`;
}

function guideCard(guide) {
  return `<article class="card guide-card" data-action="guide-detail" data-id="${guide.id}" tabindex="0" role="button" aria-label="查看指导：${escapeHTML(guide.title)}">
    <div class="guide-card-top"><span class="guide-icon tone-${guide.tone}">${icon(guide.icon)}</span><span class="rule-badge rule-${guide.level}">${escapeHTML(guide.rule)}</span></div>
    <h3>${escapeHTML(guide.title)}</h3><p>${escapeHTML(guide.summary)}</p>
    ${guideSourceRow(guide)}
  </article>`;
}

function renderRehearsal() {
  const family = state.family;
  const rehearsalGuide = focusGuide();
  const consented = isRecipientAuthorized();
  const rehearsalAllowed = consented && Boolean(rehearsalGuide);
  const recommendation = householdRecommendation();
  const stage = recommendation.stage;
  const twoDeviceRecommended = rehearsalAllowed && stage !== "observe";
  const shortMinutes = state.mode === "real" ? Math.max(10, Math.min(60, Number(family.restGoal.duration) || 20)) : 20;
  $("#app").innerHTML = `<div class="page rehearsal-page">
    ${pageHeader("REHEARSAL PATH", "下一档由参与者的明确选择决定", "一次现场完成不会自动升级。缺失回答、过期授权、紧急/医疗缺口或不安全感受都会保守地保持或退回。", `<button class="btn btn-secondary" data-action="outcome-history">记录与来源</button>${twoDeviceRecommended ? (HOSTED_STATIC_REVIEW ? `<button class="btn btn-primary" data-action="show-local-full-experience">${icon("i-home")}本地完整体验 · 双机配对</button>` : `<button class="btn btn-primary" data-action="companion-primary">${icon("i-phone")}按建议开始双机彩排</button>`) : `<button class="btn ${rehearsalAllowed ? "btn-coral" : "btn-secondary"}" data-action="start-rehearsal">${icon(rehearsalAllowed ? "i-play" : "i-lock")}${rehearsalAllowed ? `开始${OutcomeModel.STAGE_LABELS[stage]}` : "彩排安全门"}</button>`}`)}
    <section class="rehearsal-layout">
      <div class="stack">
        <article class="card stage-card">
          <div class="stage-header"><div><h2>${escapeHTML(family.relayName)}的下一次彩排</h2><p>${state.mode === "demo" ? "演示家庭 · 结果机制示例" : `${state.sessions.length} 条会话历史`}</p></div><span class="status-pill">建议第 ${OutcomeModel.stageIndex(stage) + 1} / 3 档</span></div>
          <div class="stage-track recommendation-track">${OutcomeModel.STAGES.map((item, index) => `<div class="stage ${item === stage ? "current" : ""}"><span class="stage-node">${index + 1}</span><h3>${OutcomeModel.STAGE_LABELS[item]}</h3><p>${item === "observe" ? "照护者在旁" : item === "short-leave" ? `实际离开约 ${shortMinutes} 分钟` : "普通文字结束后再看"}</p><span class="stage-state">${item === stage ? "建议下一次" : "不是当前建议"}</span></div>`).join("")}</div>
          <div class="recommendation-reasons"><span class="source-chip app-source">规则说明</span><h3>${OutcomeModel.STAGE_LABELS[stage]}</h3><ul>${recommendation.reasons.map((reason) => `<li>${escapeHTML(reason)}</li>`).join("")}</ul>${OutcomeModel.stageIndex(stage) > 0 ? `<button class="text-button" data-action="override-stage" data-stage="${OutcomeModel.previousStage(stage)}">照护者下调为${OutcomeModel.STAGE_LABELS[OutcomeModel.previousStage(stage)]}</button>` : ""}</div>
        </article>
        <article class="card trend-card"><h3>实际记录趋势</h3>${sessionTrendMarkup()}</article>
      </div>
      <div class="stack">
        ${twoDeviceRecommended ? companionCardMarkup() : ""}
        <article class="card schedule-card"><div class="card-topline">${twoDeviceRecommended ? "同机备用路径" : "当前范围"}</div><h3>${!rehearsalAllowed ? "彩排安全门已关闭" : `${OutcomeModel.STAGE_LABELS[stage]} · ${stage === "observe" ? 5 : stage === "short-leave" ? shortMinutes : 90} 分钟`}</h3><p>${!rehearsalAllowed ? "同意或指导失效后，历史事实保留，但旧建议不会沿用。" : "开始会冻结当前同意、指导来源、红线、参与者与计划时长；任何人都可随时结束并如实保留状态。"}</p><div class="detail-list">
          <div class="detail-row"><span>${icon("i-clock")}</span><span><b>${escapeHTML(family.restGoal.date || "时间由家庭决定")}</b><small>实际经过时间会在结束时记录</small></span></div>
          <div class="detail-row"><span>${icon("i-book")}</span><span><b>${escapeHTML(rehearsalGuide?.title || "暂无低风险指导")}</b><small>开始时会冻结版本与来源范围</small></span></div>
          <div class="detail-row"><span>${icon("i-user")}</span><span><b>${isRecipientAuthorized() ? `${escapeHTML(family.caregiverName)} · ${escapeHTML(family.relayName)} · ${escapeHTML(family.recipientName)}` : "被照护者已撤回参与"}</b><small>${isRecipientAuthorized() ? "当前参与授权有效；开始前仍需三方重新确认" : "需要本人明确重新同意后才能彩排"}</small></span></div>
          <div class="detail-row"><span>${icon("i-shield")}</span><span><b>${family.redLines.length} 条家庭红线</b><small>${escapeHTML(redLinesText())}</small></span></div>
        </div>${caregiverDirectCallMarkup("rehearsal-call-links")}${stage === "quiet-handoff" ? `<button class="btn btn-secondary btn-wide" data-nav="rest">使用同机安静接班</button>` : `<button class="btn ${rehearsalAllowed ? "btn-coral" : "btn-secondary"} btn-wide" data-action="start-rehearsal">${icon(rehearsalAllowed ? "i-play" : "i-lock")}${rehearsalAllowed ? `${twoDeviceRecommended ? "同机备用 · " : ""}开始${OutcomeModel.STAGE_LABELS[stage]}` : "处理同意与指导后再彩排"}</button>`}</article>
        ${twoDeviceRecommended ? "" : companionCardMarkup()}
        <article class="card rules-card"><h3>透明、保守的下一步</h3><p>只有当前授权下完成、关键事实齐全、双方都选延长、无人报告不安全且没有未解决紧急/医疗事件，才建议延长。</p><div class="rule-list"><div class="rule-row"><span class="rule-dot"></span><span><h4>任一人选退回</h4><p>立即建议前一级，历史保留</p></span><strong>退回</strong></div><div class="rule-row"><span class="rule-dot"></span><span><h4>没有双方都选延长</h4><p>缺失回答也不推断</p></span><strong>本级</strong></div><div class="rule-row"><span class="rule-dot"></span><span><h4>医疗/高风险未解决</h4><p>直接联系或专业参考</p></span><strong>暂缓</strong></div></div></article>
      </div>
    </section>
  </div>`;
}

function renderRest() {
  const family = state.family;
  const goal = family.restGoal;
  const redLines = redLinesText();
  const currentGuides = usableGuides();
  const hereScope = guideScopeSummary("here");
  const laterScope = guideScopeSummary("later");
  const handoffAllowed = isRecipientAuthorized() && currentGuides.length > 0 && (state.mode === "demo" || state.rehearsalCompleted);
  const evidence = OutcomeModel.metrics(state.sessions);
  $("#app").innerHTML = `<div class="page rest-page">
    ${pageHeader("TRUE OFF-DUTY", "普通事情稍后说，真正紧急才响铃", "“真正离班”不会切断联系，而是让双方预先决定什么能现场处理、什么稍后汇总、什么必须立刻联系。", `<button class="btn btn-secondary" data-action="edit-rules" aria-label="编辑红线">${icon("i-edit")}编辑红线</button>`)}
    <section class="off-layout">
      <article class="card off-duty-hero"><span class="off-shield">${icon("i-shield")}</span><h2>为自己守住一段完整时间</h2><p>接班期间，${escapeHTML(family.relayName)}只看到 ${currentGuides.length} 条当前获授权指导；你的手机保留${escapeHTML(redLines)}等红线事件。</p>
        <div class="filter-flow"><div class="filter-step"><span>现场遇到问题</span><strong>先查确认指导</strong></div><span class="filter-arrow">${icon("i-arrow")}</span><div class="filter-step"><span>非紧急</span><strong>稍后统一说明</strong></div><span class="filter-arrow">${icon("i-arrow")}</span><div class="filter-step"><span>红线事件</span><strong>立即响铃</strong></div></div>
        <div class="off-actions"><button class="btn ${handoffAllowed ? "btn-coral" : "btn-secondary"}" data-action="start-rest">${icon(handoffAllowed ? "i-moon" : "i-lock")}${handoffAllowed ? "开启真正离班" : !isRecipientAuthorized() ? "本人已撤回 · 暂停离班" : state.mode === "real" && !state.rehearsalCompleted ? "先完成短时离开" : "缺少可用指导 · 暂停离班"}</button><button class="btn btn-ghost" data-action="rest-preview">先看照护者会看到什么</button></div>
      </article>
      <div class="stack">
        <article class="card rules-card"><h3>当前通知规则</h3><p>日常范围只从当前可用指导生成；一键联系始终可用。</p><div class="rule-list"><div class="rule-row"><span class="rule-dot"></span><span><h4>现场可处理</h4><p>${escapeHTML(hereScope)}</p></span><strong>不通知</strong></div><div class="rule-row"><span class="rule-dot"></span><span><h4>稍后告知</h4><p>${escapeHTML(laterScope)}</p></span><strong>结束汇总</strong></div><div class="rule-row"><span class="rule-dot"></span><span><h4>立即联系</h4><p>${escapeHTML(redLines)}</p></span><strong>立即响铃</strong></div></div><div class="safety-note">${icon("i-shield")}范围会随来源授权即时变化；紧急情况请优先拨打当地紧急服务。应用不会代替专业医疗判断。</div><div class="direct-call-row"><a class="btn btn-secondary btn-small" href="${phoneHref(family.caregiverPhone)}">${icon("i-phone")}联系${escapeHTML(family.caregiverName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(family.emergencyService)}">拨打 ${escapeHTML(family.emergencyService)}</a></div></article>
        ${companionCardMarkup()}
        <article class="card rest-window-card"><div class="card-topline">下一段休息</div><h3>${escapeHTML(goal.date)}<br>${escapeHTML(goal.title)}</h3><p>计划 ${Number(goal.duration)} 分钟 · 历史实际完成 ${evidence.protectedMinutes} 分钟 · 不代表下一次一定不会被打断</p><button class="text-button" data-action="edit-rest">修改休息目标${icon("i-arrow")}</button></article>
      </div>
    </section>
  </div>`;
}

function renderActiveRehearsal() {
  clearInterval(tickHandle);
  tickHandle = null;
  const rehearsalGuide = session ? usableGuideById(session.guideId) : null;
  const confirmation = state.confirmations.find((item) => item.id === session?.confirmationId && item.status === "current");
  const sessionAuthorized = isRecipientAuthorized() && rehearsalGuide && confirmation && session.consentRevision === state.recipientConsent.revision && session.guideVersion === rehearsalGuide.version;
  if (!sessionAuthorized) {
    finishOutcomeRecord(session?.sessionRecordId, { status: "revoked", tasks: session?.tasks || [], pendingGaps: (session?.pendingGapIds || []).map((id) => state.gaps.find((gap) => gap.id === id)).filter(Boolean), urgentAlertsRaised: session?.urgentAlertsRaised || 0 });
    session = null;
    state.activeRehearsal = null;
    renderRehearsal();
    toast("本人参与或指导已撤回，当前彩排已安全结束");
    return;
  }
  const observe = session.stage === "observe";
  $("#page-title").textContent = "彩排进行中";
  $("#page-eyebrow").textContent = `${state.family.relayName} · ${observe ? "在旁观察" : "短时离开"}`;
  const tasks = observe ? [
    { title: `${state.family.relayName}拿着这台手机`, detail: `${state.family.caregiverName}留在身旁，但由替班者查看指导`, time: "现在" },
    { title: `一起完成：${rehearsalGuide.title}`, detail: rehearsalGuide.summary, time: "在旁" },
    { title: "停下来口头复核", detail: "三人都可以说停；不确定时由照护者接手", time: "收尾" },
  ] : [
    { title: `准备处理：${rehearsalGuide.title}`, detail: "先确认现场事实与当前指导一致", time: "现在" },
    { title: "按当前确认内容处理", detail: rehearsalGuide.summary, time: "+ 5 分" },
    { title: "收尾并简单记录", detail: "普通变化留到结束后统一说明", time: `+ ${Math.max(5, session.duration - 5)} 分` },
  ];
  $("#app").innerHTML = `<div class="page active-session">
    <div class="session-top"><div class="session-state"><span class="pulse-dot"></span>真实彩排进行中</div><button class="btn btn-secondary btn-small" data-action="pause-session">${icon("i-close")}结束彩排</button></div>
    <section class="session-grid">
      <article class="card session-main"><div class="session-clock"><div><h1>${observe ? "第一次 · 在旁观察" : `短时离开 ${session.duration} 分钟`}</h1><p>${observe ? `${escapeHTML(state.family.relayName)}拿手机，${escapeHTML(state.family.caregiverName)}就在身旁` : `${escapeHTML(state.family.caregiverName)}可以离开，但始终可直接联系`}</p></div><div class="timer" id="session-timer">00:00</div></div>
        <div class="task-list">${tasks.map((task, index) => `<div class="task ${session.tasks[index] ? "done" : ""}"><button class="task-check" data-task="${index}" aria-label="${session.tasks[index] ? "取消完成" : "标为完成"}：${task.title}">${icon("i-check")}</button><span><h3>${task.title}</h3><p>${task.detail}</p></span><span class="task-time">${task.time}</span></div>`).join("")}</div>
        <div class="ask-block"><div><h3>遇到预料外的情况？</h3><p>说出发生了什么，只会匹配已确认过的指导。</p></div><button class="mic-btn" data-action="ask-question" aria-label="语音提出问题">${icon("i-mic")}</button></div>
      </article>
      <aside class="session-side"><article class="card now-guide"><div class="now-guide-top"><small>此刻可用的确认指导</small><h3>${escapeHTML(rehearsalGuide.title)}</h3></div><div class="now-guide-body"><p class="quote-guide">“${escapeHTML(rehearsalGuide.summary)}”</p>${rehearsalGuide.audio ? `<button class="play-source" data-action="play-source"><span>${icon("i-volume")}</span><span><b>播放${escapeHTML(sourceView(rehearsalGuide).label)}的原话</b><small>来源录音 · 18 秒</small></span></button>` : ""}${guideSourceRow(rehearsalGuide, "来源：")}</div></article>
        <article class="card emergency-card"><h3>${icon("i-alert")}红线与直接联系</h3><p>${escapeHTML(redLinesText())}。不确定时立即联系${escapeHTML(state.family.caregiverName)}；紧急时优先拨打 ${escapeHTML(state.family.emergencyService)}。</p><div class="direct-call-row"><a class="btn btn-secondary btn-small" href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}联系照护者</a><a class="btn btn-danger btn-small" href="${phoneHref(state.family.emergencyService)}">拨打 ${escapeHTML(state.family.emergencyService)}</a></div></article>
      </aside>
    </section>
  </div>`;
  startSessionClock();
}

function startSessionClock() {
  const update = () => {
    if (!session) { clearInterval(tickHandle); return; }
    const elapsed = Math.max(0, Math.floor((Date.now() - session.startedAt) / 1000));
    const timer = $("#session-timer");
    if (timer) timer.textContent = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
  };
  update();
  tickHandle = setInterval(update, 1000);
}

function renderActiveRest() {
  clearInterval(tickHandle);
  tickHandle = null;
  const restGuidesValid = Array.isArray(restSession?.guideVersions) && restSession.guideVersions.every((snapshot) => {
    const guide = usableGuideById(snapshot.id);
    return guide && guide.version === snapshot.version;
  });
  const confirmation = state.confirmations.find((item) => item.id === restSession?.confirmationId && item.status === "current");
  if (!isRecipientAuthorized() || restSession?.consentRevision !== state.recipientConsent.revision || !restGuidesValid || !confirmation) {
    finishOutcomeRecord(restSession?.sessionRecordId, { status: "revoked", tasks: [true], routineUpdatesQueued: restSession?.queued || 0, urgentAlertsRaised: restSession?.urgentAlertsRaised || 0 });
    restSession = null; state.activeRest = null; saveState();
    renderRest();
    toast("本人参与已撤回，真正离班已安全结束");
    return;
  }
  $("#page-title").textContent = "真正离班中";
  $("#page-eyebrow").textContent = "通知防火墙已开启";
  $("#app").innerHTML = `<div class="page off-active"><div class="off-active-inner">
    <div class="session-state"><span class="pulse-dot"></span>真正离班已开启 · 仅红线事件响铃</div><h1>这段时间，先交给${escapeHTML(state.family.relayName)}。</h1><p class="off-sub">去${escapeHTML(state.family.restGoal.title)}吧。普通事情会在结束后一次告诉你。</p>
    <div class="countdown" id="rest-countdown">60:00</div><div class="countdown-label">剩余休息时间</div>
    <div class="quiet-inbox"><span>${icon("i-bell")}</span><div><b>安静收件箱</b><small>普通消息不会打断这段休息</small></div><strong id="quiet-count">${restSession.queued}</strong></div>
    ${state.mode === "demo" ? `<div class="simulation-tools"><button class="btn btn-small" data-action="simulate-normal">演示：普通询问</button><button class="btn btn-small" data-action="simulate-urgent">演示：红线事件</button></div>` : `<div class="safety-note">${icon("i-shield")}真实家庭不会生成模拟消息；当前计数只来自本次实际保存的数据。</div>`}<div class="rest-call-links"><a href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}联系${escapeHTML(state.family.caregiverName)}</a><a href="${phoneHref(state.family.emergencyService)}">拨打 ${escapeHTML(state.family.emergencyService)}</a></div>
    <button class="btn end-rest" data-action="end-rest">提前结束离班</button>
  </div></div>`;
  startRestClock();
}

function startRestClock() {
  const update = () => {
    if (!restSession) { clearInterval(tickHandle); return; }
    const passed = Math.max(0, Math.floor((Date.now() - restSession.startedAt) / 1000));
    const left = Math.max(0, restSession.duration * 60 - passed);
    const countdown = $("#rest-countdown");
    if (countdown) countdown.textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
  };
  update();
  tickHandle = setInterval(update, 1000);
}

function openModal(content, className = "") {
  previousFocus = document.activeElement;
  $("#modal-root").innerHTML = `<div class="modal-backdrop" data-action="backdrop-close"><section class="modal ${className}" role="dialog" aria-modal="true" aria-labelledby="modal-title">${content}</section></div>`;
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => $(".modal button, .modal input, .modal textarea, .modal select")?.focus());
}

function closeModal() {
  $("#modal-root").innerHTML = "";
  document.body.style.overflow = "";
  previousFocus?.focus?.();
}

function modalHead(kicker, title) {
  return `<header class="modal-head"><div><span class="modal-kicker">${kicker}</span><h2 id="modal-title">${title}</h2></div><button class="close-button" data-action="close-modal" aria-label="关闭">${icon("i-close")}</button></header>`;
}

function showGuideDetail(id) {
  const guide = usableGuideById(id);
  if (!guide) { toast("这条指导当前没有授权，已停止展示"); return; }
  const readOnlyProfessional = guide.provenance?.actorId === SOURCE_IDS.PROFESSIONAL;
  openModal(`${modalHead(guide.rule, escapeHTML(guide.title))}<div class="modal-body">
    <div class="question-result"><span class="result-label">已确认的做法</span><h3>${escapeHTML(guide.summary)}</h3>${guide.highRisk ? `<p><strong>安全提醒：</strong>这里只引用已有专业指示，仍需立即联系；应用不判断伤情、搬运或用药。</p>` : `<p>替班者在现场遇到相似情境时，可以查看这一条；它不代表临床保证。</p>`}${guideSourceRow(guide)}</div>
    ${guide.audio ? `<button class="play-source" data-action="play-source"><span>${icon("i-volume")}</span><span><b>播放原始录音</b><small>演示音频 · ${escapeHTML(sourceView(guide).label)}提供</small></span></button>` : ""}
  </div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">返回</button>${readOnlyProfessional ? `<span class="verified">${icon("i-lock")}随安全策略提供 · 只读</span>` : `<button class="btn btn-primary" data-action="edit-guide" data-id="${guide.id}">${icon("i-edit")}更新指导</button>`}</footer>`);
}

function showGuideForm(editId = null) {
  const guide = editId ? usableGuideById(editId) : null;
  if (editId && !guide) { toast("这条指导当前不可用，不能继续编辑"); return; }
  if (guide?.provenance?.actorId === SOURCE_IDS.PROFESSIONAL) { toast("内置专业引用由安全策略只读提供，不能在浏览器中编辑"); return; }
  const lockedHighRisk = Boolean(guide?.highRisk);
  const sources = availableGuideSources({ professionalOnly: lockedHighRisk });
  openModal(`${modalHead(guide ? "UPDATE GUIDE" : "NEW GUIDE", guide ? "更新这条指导" : "从一个真实情境开始")}<form id="guide-form"><div class="modal-body"><div class="form-grid">
    <div class="field field-full"><label for="guide-title">发生了什么？</label><input id="guide-title" name="title" required maxlength="40" placeholder="例如：她不愿意吃午饭" value="${escapeHTML(guide?.title || "")}"></div>
    <div class="field field-full"><label for="guide-summary">已经确认的处理方式</label><textarea id="guide-summary" name="summary" required maxlength="220" placeholder="只记录当事人或专业人员明确说过的做法">${escapeHTML(guide?.summary || "")}</textarea><span class="field-help">系统不会补全或改写医疗、安全相关建议。</span></div>
    <div class="field"><label for="guide-source">内容来自谁？</label><select id="guide-source" name="sourceId">${sources.map((source) => `<option value="${source.id}">${escapeHTML(source.label)}</option>`).join("")}</select>${!isRecipientAuthorized() ? `<span class="field-help">本人已撤回参与，因此不能选择被照护者本人作为来源。</span>` : ""}</div>
    <div class="field"><label for="guide-rule">需要何时联系？</label><select id="guide-rule" name="level" ${lockedHighRisk ? "disabled" : ""}><option value="here">现场可处理</option><option value="later">稍后告知</option><option value="now">立即联系</option></select>${lockedHighRisk ? `<input type="hidden" name="level" value="now">` : ""}</div>
  </div><div class="source-proof">${icon(lockedHighRisk ? "i-alert" : "i-shield")}${lockedHighRisk ? "这条高风险指导不能在浏览器中修改。" : "保存后会保留来源与确认时间。医疗或高风险内容只能保持待确认；浏览器不能创建专业来源。"}</div></div>
  <footer class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">取消</button><button class="btn btn-primary" type="submit">${guide ? "保存更新" : "保存并加入彩排"}</button></footer></form>`, "modal-wide");
  const form = $("#guide-form");
  if (guide) {
    form.sourceId.value = guide.provenance.actorId;
    form.level.value = guide.level;
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const currentGuide = editId ? usableGuideById(editId) : null;
    if (editId && (!currentGuide || currentGuide.version !== guide.version || currentGuide.confirmationId !== guide.confirmationId)) { toast("指导状态已经变化，请重新打开后再编辑"); return; }
    const sourceId = String(data.get("sourceId") || "");
    const source = sourceDefinition(sourceId);
    if (!source?.authorized || !availableGuideSources().some((item) => item.id === sourceId)) { toast("这个来源当前没有授权，无法保存"); return; }
    const title = String(data.get("title") || "").trim();
    const summary = String(data.get("summary") || "").trim();
    if (!title || !summary) { toast("请完整填写情境和确认内容"); return; }
    const medicalRisk = lockedHighRisk || SafetyPolicy.classifyFields([title, summary]).highRisk;
    if (medicalRisk) { toast("医疗或高风险内容不能保存为浏览器指导；请保留待确认并使用直接联系"); return; }
    if (!availableGuideSources({ professionalOnly: medicalRisk }).some((item) => item.id === sourceId)) { toast("这个来源不符合当前内容的授权范围"); return; }
    const requestedLevel = String(data.get("level") || "");
    if (!medicalRisk && !["here", "later", "now"].includes(requestedLevel)) { toast("联系级别无效，请重新选择"); return; }
    const level = medicalRisk ? "now" : requestedLevel;
    const ruleMap = { here: "现场可处理", later: "稍后告知", now: "立即联系" };
    const category = level === "now" ? "urgent" : "daily";
    if (currentGuide) {
      const prior = state.confirmations.find((item) => item.id === currentGuide.confirmationId);
      if (prior) prior.status = "superseded";
    }
    const confirmationId = addConfirmation({ type: "guide", actorId: sourceId, guideId: currentGuide?.id || null, consentRevision: sourceId === SOURCE_IDS.RECIPIENT ? state.recipientConsent.revision : null });
    const update = {
      ...(currentGuide || {}), id: currentGuide?.id || `guide-${Date.now()}`, version: (currentGuide?.version || 0) + 1, status: "usable", confirmationId,
      provenance: { actorId: sourceId, actorType: source.actorType, labelAtConfirmation: source.label, ...(sourceId === SOURCE_IDS.RECIPIENT ? { consentRevision: state.recipientConsent.revision } : {}) },
      icon: currentGuide?.icon || "i-spark", tone: level === "now" ? "red" : currentGuide?.tone || "mint", category,
      title, summary, source: source.label, sourceAvatar: source.avatar, sourceClass: source.className,
      updated: "刚刚确认", level, rule: ruleMap[level], audio: currentGuide?.audio || false, highRisk: medicalRisk, policyVersion: SafetyPolicy.VERSION,
    };
    const confirmation = state.confirmations.find((item) => item.id === confirmationId);
    confirmation.guideId = update.id;
    if (currentGuide) state.guides = state.guides.map((item) => item.id === currentGuide.id ? update : item);
    else state.guides.unshift(update);
    saveState(); closeModal(); render(); toast(currentGuide ? "指导已更新，并保留了本次确认记录" : "新指导已加入情境库");
  });
}

function showRehearsalSetup() {
  const family = state.family;
  const rehearsalGuide = focusGuide();
  const firstStage = state.mode === "real" && !state.stageOneCompleted;
  if (firstStage && !onboardingReady()) {
    state.onboarding.step = 6;
    saveState();
    render();
    toast("准备项目还不完整，彩排保持锁定");
    return;
  }
  if (!isRecipientAuthorized() || !rehearsalGuide) {
    const consentMissing = !isRecipientAuthorized();
    openModal(`${modalHead("SAFETY GATE", "彩排暂不能开始")}<div class="modal-body"><div class="question-result no-match-result"><span class="result-label">安全门已关闭</span><h3>${consentMissing ? `${escapeHTML(family.recipientName || "被照护者")}已撤回参与` : "没有当前可用的低风险指导"}</h3><p>${consentMissing ? "撤回立即生效。应用不会继续显示本人同意、不会调用本人提供的内容，也不会让替班者进入彩排。重新同意不会恢复已撤回内容或旧确认。" : "请由当前获授权的人重新提供并确认处理方式；已撤回的内容和旧的已阅声明不能沿用。"}</p></div><div class="confirm-list"><div class="confirm-item">${icon("i-lock")}${consentMissing ? "本人同意：已撤回" : "可用低风险指导：缺失"}</div><div class="confirm-item">${icon("i-check")}照护者电话、紧急服务和红线仍然保留</div></div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">返回</button><button class="btn btn-primary" data-action="${consentMissing ? "open-family-from-gate" : "go-guides-from-gate"}">${consentMissing ? "查看同意设置" : "前往情境指导"}</button></footer>`);
    return;
  }
  const shortMinutes = state.mode === "real" ? Math.max(10, Math.min(60, Number(family.restGoal.duration) || 20)) : 20;
  const stageMarkup = firstStage
    ? `<div class="setup-summary"><h3>在旁观察 · ${escapeHTML(rehearsalGuide.title)}</h3><div class="setup-grid"><div><small>手机交给</small><strong>${escapeHTML(family.relayName)}</strong></div><div><small>本次时长</small><strong>约 5 分钟</strong></div><div><small>照护者距离</small><strong>就在身旁</strong></div></div></div><div class="confirm-list"><label class="confirm-item"><input type="checkbox" name="guideReviewed" required>${escapeHTML(family.relayName)}现在拿着这台手机，并已看过本条指导</label><label class="confirm-item"><input type="checkbox" name="redLinesConfirmed" required>${escapeHTML(family.caregiverName)}会留在身旁；不确定时立即接手或使用直接联系</label><label class="confirm-item"><input type="checkbox" name="recipientAgreed" required>${escapeHTML(family.recipientName)}现在知道三人都在场，并明确同意这次在旁练习</label></div>`
    : `<div class="setup-summary"><h3>短时离开 · ${escapeHTML(rehearsalGuide.title)}</h3><div class="setup-grid"><div><small>替班者</small><strong>${escapeHTML(family.relayName)}</strong></div><div><small>本次时长</small><strong>${shortMinutes} 分钟</strong></div><div><small>照护者距离</small><strong>可立即联系</strong></div></div></div><div class="confirm-list"><label class="confirm-item"><input type="checkbox" name="guideReviewed" required>${escapeHTML(family.relayName)}现在拿着这台手机，并已看过“${escapeHTML(rehearsalGuide.title)}”</label><label class="confirm-item"><input type="checkbox" name="redLinesConfirmed" required>双方现在核对直接联系，并看过本家庭红线：${escapeHTML(redLinesText())}</label><label class="confirm-item"><input type="checkbox" name="recipientAgreed" required>${escapeHTML(family.recipientName)}现在知道由${escapeHTML(family.relayName)}陪伴，并明确同意本次安排</label></div>`;
  openModal(`${modalHead(firstStage ? "OBSERVE TOGETHER" : "SHORT-LEAVE REHEARSAL", "开始前，三方再对齐一次")}<form id="rehearsal-setup-form" data-stage="${firstStage ? "observe" : "short-leave"}" data-rehearsal-duration="${firstStage ? 5 : shortMinutes}" data-guide-id="${rehearsalGuide.id}" data-guide-version="${rehearsalGuide.version}" data-consent-revision="${state.recipientConsent.revision}"><div class="modal-body">${stageMarkup}<div class="safety-note">${icon("i-alert")}每次开始都要重新确认。本安全门不代表临床保证；急救、搬运或用药变化需立即联系并遵循已有专业指示。</div><div class="direct-call-row"><a class="btn btn-secondary btn-small" href="${phoneHref(family.caregiverPhone)}">${icon("i-phone")}联系照护者</a><a class="btn btn-danger btn-small" href="${phoneHref(family.emergencyService)}">拨打 ${escapeHTML(family.emergencyService)}</a></div></div><footer class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">稍后再练</button><button type="button" class="btn btn-coral" data-action="confirm-rehearsal" disabled>${icon("i-play")}三方现在确认，开始</button></footer></form>`);
  const setupForm = $("#rehearsal-setup-form");
  setupForm.addEventListener("change", () => {
    const complete = ["guideReviewed", "redLinesConfirmed", "recipientAgreed"].every((name) => setupForm.elements[name]?.checked);
    setupForm.querySelector("[data-action='confirm-rehearsal']").disabled = !complete;
  });
}

function showQuestionModal() {
  const initial = state.mode === "demo" ? "她说不饿，不愿意吃午饭" : "";
  openModal(`${modalHead("ASK IN THE MOMENT", "说出眼前发生了什么")}<div class="modal-body"><div class="field"><label for="question-input">只描述事实，不需要判断</label><div style="display:flex;gap:8px"><input id="question-input" value="${escapeHTML(initial)}" placeholder="描述现场实际发生的事" style="flex:1"><button class="mic-btn" id="record-question" data-action="record-question" aria-label="开始语音输入">${icon("i-mic")}</button></div><span class="field-help" id="speech-status">可以直接修改文字，或使用设备语音输入。</span></div><div id="matched-result"></div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">取消</button><button class="btn btn-primary" data-action="match-question">查找已确认指导</button></footer>`);
}

function matchConfirmedGuide(query) {
  const text = String(query || "").trim().toLowerCase();
  if (!text) return null;
  const highRiskQuery = SafetyPolicy.classifyText(text).highRisk;
  const matches = [
    ["meal", ["不饿", "午饭", "吃饭", "拒绝吃", "饭菜"]],
    ["walk", ["散步", "出门", "走廊"]],
    ["tea", ["喝水", "加餐", "蓝色杯"]],
    ["mood", ["一个人", "独处", "门口"]],
    ["fall", ["跌倒", "摔倒", "滑倒", "跌落"]],
  ];
  for (const [id, terms] of matches) {
    if (terms.some((term) => text.includes(term))) {
      const guide = usableGuideById(id);
      if (guide && (!highRiskQuery || SafetyPolicy.isImmediateReference(guide))) return guide;
    }
  }
  const candidates = usableGuides().filter((guide) => !highRiskQuery || SafetyPolicy.isImmediateReference(guide));
  return candidates.find((guide) => {
    const key = normalizedQuery(guide.title).replace(/[她他时的了·]/g, "");
    const queryKey = normalizedQuery(text).replace(/[她他时的了·]/g, "");
    return key.length >= (highRiskQuery ? 2 : 4) && (queryKey.includes(key) || (highRiskQuery && key.includes(queryKey)));
  }) || null;
}

function matchedGuideMarkup(guide) {
  if (!guideIsUsable(guide)) return noMatchMarkup(null, "ordinary");
  const highRisk = guide.highRisk;
  return `<div class="question-result"><span class="result-label">找到 1 条当前可用指导</span><h3>${escapeHTML(guide.title)}</h3><p>${escapeHTML(guide.summary)}</p>${highRisk ? `<div class="safety-note">${icon("i-alert")}这只是已有专业指示的引用，仍属于“立即联系”。应用不作诊断或临床保证。</div><div class="direct-call-row"><a class="btn btn-secondary btn-small" href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}立即联系${escapeHTML(state.family.caregiverName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(state.family.emergencyService)}">紧急危险 · ${escapeHTML(state.family.emergencyService)}</a></div>` : ""}${guideSourceRow(guide, "来源：")}</div>`;
}

function logGap(query) {
  const clean = String(query || "").trim();
  if (!clean) return null;
  const key = normalizedQuery(clean);
  let gap = state.gaps.find((item) => item.status === "pending" && (item.normalizedQuery || normalizedQuery(item.query)) === key);
  if (gap) {
    gap.encounters = (gap.encounters || 1) + 1;
    gap.lastSeenAt = Date.now();
    gap.query = clean;
  } else {
    gap = { id: `gap-${Date.now()}`, query: clean, normalizedQuery: key, risk: SafetyPolicy.classifyText(clean).risk, status: "pending", encounters: 1, createdAt: Date.now(), lastSeenAt: Date.now(), reportedBy: { actorId: SOURCE_IDS.RELAY, labelAtReport: state.family.relayName } };
    state.gaps.unshift(gap);
  }
  if (session && !session.pendingGapIds.includes(gap.id)) {
    session.pendingGapIds.push(gap.id);
    state.activeRehearsal = { ...session, tasks: [...session.tasks], pendingGapIds: [...session.pendingGapIds] };
  }
  saveState();
  return gap;
}

function noMatchMarkup(gap, risk = gap?.risk || "ordinary") {
  const family = state.family;
  const medical = risk === "medical";
  return `<div class="question-result no-match-result"><span class="result-label">没有安全匹配</span><h3>没有找到已确认指导</h3><p>${medical ? `这是医疗或高风险情境。应用不会给出诊断、加减药量或自创应急建议，请立即联系${escapeHTML(family.caregiverName)}；有紧急危险时直接拨打 ${escapeHTML(family.emergencyService)}。` : `这个普通情境也不会被猜测处理。你可以现在联系${escapeHTML(family.caregiverName)}，或在确保现场安全后稍后补充；有紧急危险时直接拨打 ${escapeHTML(family.emergencyService)}。`}</p>${gap ? `<div class="gap-recorded">${icon("i-check")}已记录为待确认情境 · 第 ${gap.encounters} 次遇到 · 尚不能作为指导</div>` : ""}<div class="direct-call-row" aria-label="升级选择"><a class="btn btn-secondary btn-small" href="${phoneHref(family.caregiverPhone)}">${icon("i-phone")}${medical ? "立即" : "联系"}${escapeHTML(family.caregiverName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(family.emergencyService)}">紧急危险 · ${escapeHTML(family.emergencyService)}</a>${gap ? `<button class="btn btn-secondary btn-small" data-action="review-gap" data-id="${gap.id}">${icon("i-edit")}查看已记录缺口</button>` : ""}</div></div>`;
}

function showGapReview(id) {
  const gap = state.gaps.find((item) => item.id === id && item.status === "pending");
  if (!gap) { toast("这条情境已经处理"); return; }
  const medicalRisk = SafetyPolicy.classifyFields([gap.query, gap.lastProposedTitle, gap.lastProposedInstruction]).highRisk;
  const sources = availableGuideSources({ professionalOnly: medicalRisk });
  openModal(`${modalHead("CONFIRM A GAP", medicalRisk ? "保持医疗待确认并立即联系" : "把待确认问题变成可用指导")}<form id="gap-form"><div class="modal-body"><div class="form-grid"><div class="field field-full"><label for="gap-title">现场遇到的情境</label><input id="gap-title" name="title" required maxlength="40" value="${escapeHTML(gap.query.slice(0, 40))}"></div><div class="field field-full"><label for="gap-answer">${medicalRisk ? "补充现场记录（不会成为指导）" : "明确确认的处理方式"}</label><textarea id="gap-answer" name="answer" required maxlength="220" placeholder="${medicalRisk ? "可记录已联系情况；这里填写的文字不会变成可搜索指导" : "由当前获授权的人明确说明后再填写"}"></textarea></div><div class="field"><label for="gap-source">内容来源</label><select id="gap-source" name="sourceId" ${medicalRisk ? "disabled" : ""}><option value="">${medicalRisk ? "浏览器无可创建的专业引用" : "请选择真实来源"}</option>${sources.map((source) => `<option value="${source.id}">${escapeHTML(source.label)}</option>`).join("")}</select></div><div class="field"><label for="gap-level">何时联系</label><select id="gap-level" name="level" ${medicalRisk ? "disabled" : ""}><option value="here">现场可处理</option><option value="later">稍后告知</option><option value="now" ${medicalRisk ? "selected" : ""}>立即联系</option></select></div></div><div class="source-proof" id="gap-risk-proof">${icon(medicalRisk ? "i-alert" : "i-shield")}${medicalRisk ? "这是医疗或高风险问题。浏览器不能把任意文字标成专业来源；它会继续留在待确认清单并保持立即联系。" : "保存后才会进入指导库，并保留稳定来源、确认记录和时间。"}</div><div class="direct-call-row"><a class="btn btn-secondary btn-small" href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}立即联系${escapeHTML(state.family.caregiverName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(state.family.emergencyService)}">紧急危险 · ${escapeHTML(state.family.emergencyService)}</a></div></div><footer class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">继续待确认</button><button type="submit" class="btn btn-primary">${medicalRisk ? "保存记录并继续待确认" : "确认并加入指导库"}</button></footer></form>`, "modal-wide");
  const gapForm = $("#gap-form");
  const gapLevelField = $("#gap-level");
  const gapSourceField = $("#gap-source");
  const updateGapRiskHint = () => {
    const editedRisk = medicalRisk || gapLevelField?.value === "now" || SafetyPolicy.classifyFields([gapForm.elements.title?.value, gapForm.elements.answer?.value]).highRisk;
    $("#gap-risk-proof").innerHTML = editedRisk ? `${icon("i-alert")}当前编辑内容已按医疗或高风险处理：不能在浏览器中创建专业引用，只能继续待确认并立即联系。` : `${icon("i-shield")}保存后才会进入指导库，并保留稳定来源、确认记录和时间。`;
    if (!medicalRisk) {
      [...gapSourceField.options].forEach((option) => { if (option.value) option.disabled = editedRisk; });
      [...gapLevelField.options].forEach((option) => { option.disabled = editedRisk && option.value !== "now"; });
      if (editedRisk) {
        const prompt = gapSourceField.querySelector("option[value='']");
        prompt.textContent = "医疗内容只能继续待确认";
        prompt.selected = true;
        gapSourceField.disabled = true;
        gapLevelField.value = "now";
      } else {
        gapSourceField.disabled = false;
        gapSourceField.querySelector("option[value='']").textContent = "请选择真实来源";
      }
    }
  };
  gapForm.elements.title.addEventListener("input", updateGapRiskHint);
  gapForm.elements.answer.addEventListener("input", updateGapRiskHint);
  gapLevelField?.addEventListener("change", updateGapRiskHint);
  gapForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const currentGap = state.gaps.find((item) => item.id === id && item.status === "pending");
    if (!currentGap) { toast("这条缺口已经在其他页面处理"); return; }
    const title = String(data.get("title") || "").trim();
    const answer = String(data.get("answer") || "").trim();
    if (!title || !answer) { toast("请完整填写情境和现场记录"); return; }
    const requestedLevel = String(gapLevelField?.value || "");
    const submittedMedicalRisk = medicalRisk || requestedLevel === "now" || SafetyPolicy.classifyFields([title, answer]).highRisk;
    if (submittedMedicalRisk) {
      currentGap.risk = "medical";
      currentGap.lastProposedTitle = title;
      currentGap.lastProposedInstruction = answer;
      currentGap.lastSeenAt = Date.now();
      saveState();
      closeModal();
      render();
      toast("医疗或高风险内容仍在待确认清单；请使用直接联系");
      return;
    }
    if (!["here", "later"].includes(requestedLevel)) { toast("普通指导只能选择现场处理或稍后告知"); return; }
    const sourceId = String(data.get("sourceId") || "");
    const source = sourceDefinition(sourceId);
    if (!source?.authorized || !availableGuideSources().some((item) => item.id === sourceId)) { toast("这个来源当前没有授权，无法保存"); return; }
    const level = requestedLevel;
    const ruleMap = { here: "现场可处理", later: "稍后告知", now: "立即联系" };
    const guideId = `gap-guide-${Date.now()}`;
    const confirmationId = addConfirmation({ type: "guide", actorId: sourceId, guideId, consentRevision: sourceId === SOURCE_IDS.RECIPIENT ? state.recipientConsent.revision : null });
    state.guides.unshift({ id: guideId, version: 1, professionalReferenceId: null, status: "usable", confirmationId, provenance: { actorId: sourceId, actorType: source.actorType, labelAtConfirmation: source.label, ...(sourceId === SOURCE_IDS.RECIPIENT ? { consentRevision: state.recipientConsent.revision } : {}) }, icon: "i-spark", tone: "mint", category: "daily", title, summary: answer, source: source.label, sourceAvatar: source.avatar, sourceClass: source.className, updated: "刚刚由待确认记录转入", level, rule: ruleMap[level], audio: false, highRisk: false, policyVersion: SafetyPolicy.VERSION, fromGap: gap.id });
    currentGap.status = "resolved"; currentGap.resolvedAt = Date.now(); currentGap.resolvedBy = { actorId: sourceId, labelAtResolution: source.label, confirmationId };
    saveState(); closeModal(); currentPage = "guides"; history.replaceState(null, "", "#guides"); render(); toast("待确认问题已由明确来源确认并加入指导库");
  });
}

function showSafetyRules() {
  const currentGuides = usableGuides();
  const hereScope = guideScopeSummary("here");
  const laterScope = guideScopeSummary("later");
  openModal(`${modalHead("ESCALATION RULES", "什么事，什么时候联系")}<div class="modal-body"><div class="rule-list"><div class="rule-row"><span class="rule-dot"></span><span><h4>现场可处理</h4><p>${escapeHTML(hereScope)}</p></span><strong>不打扰</strong></div><div class="rule-row"><span class="rule-dot"></span><span><h4>稍后告知</h4><p>${escapeHTML(laterScope)}</p></span><strong>结束汇总</strong></div><div class="rule-row"><span class="rule-dot"></span><span><h4>立即联系</h4><p>${escapeHTML(redLinesText())}</p></span><strong>立即响铃</strong></div></div><div class="source-proof">${icon("i-shield")}以上日常范围来自 ${currentGuides.length} 条当前可用指导，并随授权即时更新；每条指导分别保留自己的来源。这不代表临床保证，一键联系和紧急服务入口不会被屏蔽。</div><div class="direct-call-row"><a class="btn btn-secondary btn-small" href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}联系照护者</a><a class="btn btn-danger btn-small" href="${phoneHref(state.family.emergencyService)}">拨打 ${escapeHTML(state.family.emergencyService)}</a></div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">返回</button><button class="btn btn-primary" data-action="edit-rules">${icon("i-edit")}编辑红线</button></footer>`);
}

function showRulesEditor() {
  const lines = [...state.family.redLines, "", ""].slice(0, 3);
  openModal(`${modalHead("EDIT RED LINES", "编辑立即联系的红线事件")}<form id="rules-form"><div class="modal-body"><div class="form-grid">${lines.map((line, index) => `<div class="field field-full"><label for="redline-${index}">红线事件 ${index + 1}（可留空）</label><input id="redline-${index}" name="redline" maxlength="28" value="${escapeHTML(line)}" placeholder="示例：无法唤醒（请按家庭安排填写）"></div>`).join("")}</div><div class="source-proof">${icon("i-alert")}占位文字只是保守示例，不是家庭事实。留空也不会影响直接联系电话；保存后只同步亲自填写的内容。</div></div><footer class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">取消</button><button type="submit" class="btn btn-primary">保存红线规则</button></footer></form>`);
  $("#rules-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget).getAll("redline").map((value) => value.trim()).filter(Boolean);
    state.family.redLines = values;
    saveState(); closeModal(); render(); toast("红线规则已更新并同步给双方");
  });
}

function showRestGoalForm() {
  const goal = state.family.restGoal;
  openModal(`${modalHead("REST GOAL", "修改想夺回的休息")}<form id="rest-goal-form"><div class="modal-body"><div class="form-grid"><div class="field field-full"><label for="rest-title">这段时间只想为自己做什么？</label><input id="rest-title" name="title" required maxlength="40" value="${escapeHTML(goal.title)}"></div><div class="field"><label for="rest-date">计划时间</label><input id="rest-date" name="date" required maxlength="30" value="${escapeHTML(goal.date)}"></div><div class="field"><label for="rest-duration">目标时长（分钟）</label><input id="rest-duration" name="duration" type="number" min="10" max="180" required value="${Number(goal.duration)}"></div></div><div class="source-proof">${icon("i-moon")}这不是办事时间。写下一件只为恢复自己而做的事。</div></div><footer class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">取消</button><button type="submit" class="btn btn-primary">保存休息目标</button></footer></form>`);
  $("#rest-goal-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    state.family.restGoal = { title: data.get("title").trim(), date: data.get("date").trim(), duration: Number(data.get("duration")) };
    saveState(); closeModal(); render(); toast("休息目标已更新");
  });
}

function showRestSetup() {
  const currentGuides = usableGuides();
  const stageMissing = state.mode === "real" && !state.rehearsalCompleted;
  if (!isRecipientAuthorized() || !currentGuides.length || stageMissing) {
    const consentMissing = !isRecipientAuthorized();
    openModal(`${modalHead("SAFETY GATE", "真正离班暂不能开始")}<div class="modal-body"><div class="question-result no-match-result"><span class="result-label">安全门已关闭</span><h3>${consentMissing ? "不会在没有本人同意时继续接班" : stageMissing ? "当前建议还不是安静接班" : "没有当前可用指导"}</h3><p>${consentMissing ? "进行中的离班已经结束，新的离班也不会开启。重新同意不会恢复已撤回内容；家庭还需重新确认本次安排。" : stageMissing ? "请先查看最近一次应用事实和双方各自回答。只有当前授权下完成、双方都明确选择延长、无人报告不安全且没有未解决紧急/医疗事件，才会建议安静接班。" : "请先由当前获授权的人重新建立至少一条可用指导，再确认本次离班安排。"}</p></div><div class="direct-call-row"><a class="btn btn-secondary btn-small" href="${phoneHref(state.family.caregiverPhone)}">${icon("i-phone")}联系${escapeHTML(state.family.caregiverName)}</a><a class="btn btn-danger btn-small" href="${phoneHref(state.family.emergencyService)}">拨打 ${escapeHTML(state.family.emergencyService)}</a></div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">返回</button><button class="btn btn-primary" data-action="${consentMissing ? "open-family-from-gate" : stageMissing ? "go-rehearsal-from-gate" : "go-guides-from-gate"}">${consentMissing ? "查看同意设置" : stageMissing ? "查看结果与建议" : "前往情境指导"}</button></footer>`);
    return;
  }
  const target = Number(state.family.restGoal.duration) || 60;
  const choices = [...new Set([20, target, 90])].sort((a, b) => a - b);
  openModal(`${modalHead("START OFF-DUTY", "这次想完整休息多久？")}<form id="rest-setup-form" data-consent-revision="${state.recipientConsent.revision}"><div class="modal-body"><div class="duration-options">${choices.map((minutes) => `<button type="button" class="duration-option ${minutes === target ? "active" : ""}" data-duration="${minutes}"><strong>${minutes}</strong><small>分钟${minutes === target ? " · 本次目标" : ""}</small></button>`).join("")}</div><div class="setup-summary" style="margin-top:15px"><h3>开启后</h3><div class="confirm-list"><div class="confirm-item">${icon("i-check")}普通询问仅查 ${currentGuides.length} 条当前可用指导</div><div class="confirm-item">${icon("i-check")}稍后告知的事情会集中进入收件箱</div><div class="confirm-item">${icon("i-check")}${state.family.redLines.length} 类红线事件仍会立刻响铃</div><label class="confirm-item"><input type="checkbox" name="handoffConfirmed" required>家庭现在确认本次参与、可用指导与联系安排</label></div></div><div class="safety-note">${icon("i-phone")}这道门不提供临床保证；替班者始终可以一键联系照护者或拨打当地紧急服务。</div></div><footer class="modal-footer"><button type="button" class="btn btn-secondary" data-action="close-modal">取消</button><button type="button" class="btn btn-coral" data-action="confirm-rest" data-duration-value="${target}" disabled>${icon("i-moon")}确认并开启真正离班</button></footer></form>`);
  const form = $("#rest-setup-form");
  form.elements.handoffConfirmed.addEventListener("change", () => { form.querySelector("[data-action='confirm-rest']").disabled = !form.elements.handoffConfirmed.checked; });
}

function showEmergency() {
  previousFocus = document.activeElement;
  const report = state.mode === "demo" ? `<strong>${escapeHTML(state.family.relayName)}报告：</strong>${escapeHTML(state.family.recipientName || "被照护者")}在客厅跌倒，目前有回应。请立即联系确认。` : `<strong>这是通知样式预览，不是实际家庭事件。</strong>现场发生任何已约定红线或无法判断的紧急情况时，请立即直接联系。`;
  $("#modal-root").innerHTML = `<div class="modal-backdrop emergency-backdrop"><section class="emergency-modal" role="alertdialog" aria-modal="true" aria-labelledby="emergency-title"><div class="emergency-icon">${icon("i-alert")}</div><h2 id="emergency-title">${state.mode === "demo" ? "红线事件 · 立即联系" : "红线通知预览 · 不会记入记录"}</h2><p>${report} 如有紧急危险，请优先拨打 ${escapeHTML(state.family.emergencyService)}。</p><div class="emergency-actions"><button class="btn btn-secondary" data-action="dismiss-emergency">我已收到</button><a class="btn btn-secondary" href="${phoneHref(state.family.emergencyContactPhone)}">${icon("i-phone")}联系${escapeHTML(state.family.emergencyContactName)}</a><a class="btn btn-danger" href="${phoneHref(state.family.emergencyService)}">拨打 ${escapeHTML(state.family.emergencyService)}</a></div></section></div>`;
  document.body.style.overflow = "hidden";
}

function showLocalFullExperience() {
  openModal(`${modalHead("LOCAL FULL EXPERIENCE", "本地完整体验 · 两台手机真实配对")}<div class="modal-body"><div class="deployment-callout"><span>${icon("i-home")}</span><div><b>公开版不会假装提供远端配对</b><p>完整双机房间需要这份仓库中的短时 Node 服务。它只在运行进程的内存中保存房间；真实家庭长期数据仍留在照护者浏览器。</p></div></div><ol class="local-run-steps"><li><span>1</span><div><b>在项目目录启动</b><code>npm start</code><small>电脑本机打开 http://localhost:4173</small></div></li><li><span>2</span><div><b>让两台手机访问同一局域网地址</b><code>http://这台电脑的局域网IP:4173</code><small>照护者创建一次性邀请；替班者再核对姓名和短语。</small></div></li></ol><div class="safety-note">${icon("i-lock")}不要把本地房间服务直接暴露到公网。生产级远端配对仍需要 HTTPS、持久会话、速率限制和受管部署；本次公开评审版明确不提供这些能力。</div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="review-brief">查看评审说明</button><button class="btn btn-primary" data-action="close-modal">知道了</button></footer>`, "modal-wide");
}

function showReviewBrief() {
  openModal(`${modalHead("REVIEW BRIEF", "评审说明 · 先看什么、哪里是真边界")}<div class="modal-body review-brief"><div class="review-build-row"><span class="status-pill recommended">${HOSTED_STATIC_REVIEW ? "公开评审版" : "本地完整体验"}</span><code>${APP_BUILD}</code></div><div class="review-route"><b>建议 2–3 分钟路径</b><ol><li>选择“体验演示家庭”，看三种角色与当前授权。</li><li>依次查看严格匹配、普通缺口、医疗/红线升级与三方署名回看。</li><li>确认下一档理由、安静队列、撤回和脱敏导出。</li></ol></div><div class="capability-matrix"><div><small>公开链接</small><b>演示导览 · 单机逻辑 · 历史与撤回</b></div><div><small>本地 npm start</small><b>以上全部 + 同一局域网双机房间</b></div><div><small>公开版明确不含</small><b>远端配对 · 后台推送 · 临床判断</b></div></div><p class="review-boundary">${HOSTED_STATIC_REVIEW ? "当前页面不会请求 /api/rooms；所有双机入口都改为本地完整体验说明。" : "当前为本地完整体验；房间仍是黑客松级短时内存服务，不是生产远端照护基础设施。"}</p></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="show-local-full-experience">本地完整体验</button><button class="btn btn-primary" data-action="close-modal">开始查看</button></footer>`, "modal-wide");
}

function showStageOneReview() {
  const liveGuide = usableGuideById(session?.guideId);
  if (!liveGuide) { finishOutcomeRecord(session?.sessionRecordId, { status: "revoked", tasks: session?.tasks || [], pendingGaps: (session?.pendingGapIds || []).map((id) => state.gaps.find((gap) => gap.id === id)).filter(Boolean) }); session = null; state.activeRehearsal = null; saveState(); render(); toast("当前指导已不可用，本次已记录为授权撤回"); return; }
  const complete = session.tasks.every(Boolean);
  openModal(`${modalHead("OBSERVE TOGETHER FACTUAL END", "只记录刚刚真的发生过的事")}<div class="modal-body"><div class="question-result"><span class="result-label">第一次在旁观察</span><h3>${escapeHTML(liveGuide.title)}</h3><p>${complete ? `${escapeHTML(state.family.relayName)}已在拿着手机时逐项标记完成，${escapeHTML(state.family.caregiverName)}始终在旁。` : "还有现场步骤没有标记完成；可以返回继续，也可以如实记录为中途结束。"}</p></div><div class="source-proof">${icon("i-shield")}这里只冻结时长、步骤、缺口、紧急事件和打开的联系操作。完成本身不会升级；稍后要由照护者和替班者分别选择下一步。</div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="retry-rehearsal">记录为中途结束</button><button class="btn btn-primary" data-action="complete-stage-one" ${complete ? "" : "disabled"}>保存现场完成事实</button></footer>`);
}

function showDebrief() {
  const liveGuide = usableGuideById(session?.guideId);
  if (!liveGuide) { finishOutcomeRecord(session?.sessionRecordId, { status: "revoked", tasks: session?.tasks || [], pendingGaps: (session?.pendingGapIds || []).map((id) => state.gaps.find((gap) => gap.id === id)).filter(Boolean) }); session = null; state.activeRehearsal = null; saveState(); render(); toast("当前指导已不可用，本次已记录为授权撤回"); return; }
  openModal(`${modalHead("2-MINUTE PROVENANCE REVIEW", "把刚才确认过的现场答案留给下次")}<div class="modal-body"><div class="field"><label for="debrief-one">哪一步仍不确定？</label><textarea id="debrief-one" required>关于“${escapeHTML(liveGuide.title)}”仍不确定的步骤</textarea><span class="field-help">这会成为一条可再次找到的情境标题。</span></div><div class="field" style="margin-top:13px"><label for="debrief-two">${escapeHTML(state.family.caregiverName)}现在确认的处理方式</label><textarea id="debrief-two" required>${escapeHTML(liveGuide.summary)}</textarea><span class="field-help">请核对并只保存现在明确确认的低风险内容；系统不会补写。</span></div><div class="source-proof">${icon("i-spark")}来源复盘只更新指导；是否延长由双方稍后的明确选择决定。</div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="retry-rehearsal">中途结束并回看</button><button class="btn btn-primary" data-action="complete-rehearsal">保存来源事实并结束现场</button></footer>`);
}

function showRestSummary() {
  const queued = restSession?.queued || 0;
  const availableTitles = (restSession?.guideVersions || []).map((snapshot) => usableGuideById(snapshot.id)?.title).filter(Boolean);
  const recordTitle = state.mode === "demo" ? "演示离班由这台设备结束" : "本次离班由这台设备结束";
  const recordSource = "本设备应用记录";
  const elapsed = Math.max(0, Math.floor((Date.now() - (restSession?.startedAt || Date.now())) / 1000));
  openModal(`${modalHead("OFF-DUTY FACTUAL END", "先保存应用看得到的结束事实")}<div class="modal-body"><div class="setup-grid"><div><small>实际经过</small><strong>${Math.floor(elapsed / 60)}分${elapsed % 60}秒</strong></div><div><small>延后普通更新</small><strong>${queued} 条</strong></div><div><small>紧急事件</small><strong>${restSession?.urgentAlertsRaised || 0} 条</strong></div></div><div class="question-result"><span class="result-label">应用记录</span><h3>${recordTitle}</h3><p>本次可调用范围：${escapeHTML(availableTitles.join("、") || "无")}。应用不知道休息活动是否真的发生，也不会从没有消息推断“未被打断”；下一步请由参与者自己回答。</p><div class="source-row"><span class="avatar avatar-relay">应</span><span><b>${recordSource}</b><br>结束时汇总</span><span class="verified">${icon("i-shield")}仅应用事实</span></div></div></div><footer class="modal-footer"><button class="btn btn-primary" data-action="finish-rest-summary">保存事实并填写回看</button></footer>`);
}

function selectOptions(options, selected, placeholder = "可先不填") {
  return `<option value="">${placeholder}</option>${options.map(([value, label]) => `<option value="${value}" ${selected === value ? "selected" : ""}>${label}</option>`).join("")}`;
}

function showOutcomeCheckIn(recordId, role = "caregiver", { companion = false } = {}) {
  const record = outcomeRecord(recordId);
  if (!record || !record.facts) { toast("请先保存本次现场结束事实"); return; }
  const existing = record.checkIns?.[role] || {};
  const commonChoice = selectOptions([["extend", "下一次延长一级"], ["repeat", "下一次重复本级"], ["step-back", "下一次退回一级"]], existing.choice, "请选择下一次怎么练");
  let title;
  let body;
  if (role === "caregiver") {
    title = "照护者：这段时间真的休息到了吗？";
    body = `<div class="form-grid outcome-form-grid"><div class="field"><label for="outcome-rest">原本想做的休息活动发生了吗？</label><select id="outcome-rest">${selectOptions([["yes","发生了"],["partly","发生了一部分"],["no","没有发生"],["not-planned","本档没有计划离开"],["unsure","说不清"]], existing.restHappened)}</select></div><div class="field"><label for="outcome-phone">大约看了几次手机？</label><select id="outcome-phone">${selectOptions([["0","0 次"],["1-2","1–2 次"],["3-5","3–5 次"],["6+","6 次以上"],["unsure","记不清"]], existing.phoneChecks)}</select></div><div class="field"><label for="outcome-interrupt">有普通事情实际打断你吗？</label><select id="outcome-interrupt">${selectOptions([["no","没有"],["yes","有"],["unsure","说不清"]], existing.nonurgentInterrupted)}</select></div><div class="field"><label for="outcome-confidence">现在重复相似时间窗的信心</label><select id="outcome-confidence">${selectOptions([["1","1 · 很低"],["2","2"],["3","3 · 一般"],["4","4"],["5","5 · 很高"]], existing.confidence == null ? null : String(existing.confidence))}</select></div><div class="field"><label for="outcome-unsafe">这次有没有感到不安全？</label><select id="outcome-unsafe">${selectOptions([["false","没有"],["true","有"]], existing.feltUnsafe == null ? null : String(existing.feltUnsafe))}</select></div><div class="field"><label for="outcome-choice">下一次怎么练？</label><select id="outcome-choice">${commonChoice}</select></div><div class="field field-full"><label for="outcome-notes">想留给家庭复盘的话（敏感备注，可选）</label><textarea id="outcome-notes" maxlength="500" placeholder="导出时默认不包含，可由照护者选择">${escapeHTML(existing.notes || "")}</textarea></div></div>`;
  } else if (role === "substitute") {
    title = "替班者：刚才的范围能接得住吗？";
    body = `<div class="form-grid outcome-form-grid"><div class="field"><label for="outcome-able">能处理练过的范围吗？</label><select id="outcome-able">${selectOptions([["yes","能"],["partly","一部分能"],["no","不能"],["unsure","说不清"]], existing.ableToHandle)}</select></div><div class="field"><label for="outcome-contacted">有没有联系照护者？</label><select id="outcome-contacted">${selectOptions([["no","没有"],["yes","有"],["unsure","说不清"]], existing.contactedCaregiver)}</select></div><div class="field field-full"><label for="outcome-uncertain">哪一步仍不确定？</label><input id="outcome-uncertain" maxlength="500" value="${escapeHTML(existing.uncertainStep || "")}" placeholder="如果没有，也请写“没有”"></div><div class="field"><label for="outcome-unsafe">这次有没有感到不安全？</label><select id="outcome-unsafe">${selectOptions([["false","没有"],["true","有"]], existing.feltUnsafe == null ? null : String(existing.feltUnsafe))}</select></div><div class="field"><label for="outcome-choice">下一次怎么练？</label><select id="outcome-choice">${commonChoice}</select></div><div class="field field-full"><label for="outcome-notes">想留给家庭复盘的话（敏感备注，可选）</label><textarea id="outcome-notes" maxlength="500">${escapeHTML(existing.notes || "")}</textarea></div></div>`;
  } else {
    title = `${state.family.recipientName || "被照护者"}：可选的舒适度 / 偏好`;
    body = `<div class="form-grid outcome-form-grid"><div class="field"><label for="outcome-response">本人这次是否回答？</label><select id="outcome-response">${selectOptions([["answered","本人回答了"],["not-asked","没有询问本人"],["declined","本人不想回答"]], existing.response, "可暂时不记录")}</select></div><div class="field"><label for="outcome-comfort">如果回答了，感觉如何？</label><select id="outcome-comfort">${selectOptions([["comfortable","舒服"],["mixed","有好有坏"],["uncomfortable","不舒服"],["unsure","说不清"]], existing.comfort)}</select></div><div class="field field-full"><label for="outcome-preference">本人说的偏好（可选）</label><textarea id="outcome-preference" maxlength="500">${escapeHTML(existing.preference || "")}</textarea></div></div><div class="safety-note">${icon("i-user")}这是单独署名的本人自报；不是照护者或应用的判断。可以不问，也可以选择不回答，绝不会由缺失答案自动补全。</div>`;
  }
  openModal(`${modalHead("END-OF-SESSION CHECK-IN · SELF-REPORT", title)}<div class="modal-body"><div class="outcome-fact-banner"><b>应用记录</b><span>${Math.floor((record.facts.actualElapsedSeconds || 0) / 60)} 分 ${String((record.facts.actualElapsedSeconds || 0) % 60).padStart(2,"0")} 秒 · ${record.facts.completedSteps.filter(Boolean).length}/${record.facts.completedSteps.length || 3} 步 · ${record.facts.urgentAlertsRaised} 个紧急事件</span></div>${body}<p class="partial-note">可以只填现在记得的内容并保存。空白不会被解释为更放心、已准备好或更安全。</p></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">稍后再填</button><button class="btn btn-primary" data-action="save-outcome-checkin" data-session-id="${escapeHTML(recordId)}" data-role="${role}" data-companion="${companion ? "true" : "false"}">保存这位参与者的回答</button></footer>`, "modal-wide outcome-checkin-modal");
}

function formatTimestamp(value) {
  if (!value || value === "legacy-migrated") return "时间未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
}

function showOutcomeHistory() {
  const records = normalizeOutcomeSessions(state.sessions).slice().reverse();
  openModal(`${modalHead("SESSION HISTORY", "每一次都保留真实结局")}<div class="modal-body"><div class="history-source-legend"><span class="source-chip app-source">应用记录</span><span>时长、步骤、队列、缺口、紧急事件、打开联系操作</span><span class="source-chip self-source">参与者自报</span><span>休息、感受、信心与下一步选择</span></div><div class="outcome-history-list">${records.length ? records.map((record) => `<button data-action="session-detail" data-session-id="${escapeHTML(record.id)}"><span class="history-status status-${escapeHTML(record.status)}">${escapeHTML(OutcomeModel.STATUS_LABELS[record.status] || record.status)}</span><span><b>${escapeHTML(record.startSnapshot ? OutcomeModel.STAGE_LABELS[record.startSnapshot.stage] : "较早记录")}${record.demo ? " · 演示" : ""}</b><small>${record.startSnapshot ? formatTimestamp(record.startSnapshot.startedAt) : "时间与范围未记录"}</small></span><span>${record.facts ? `${Math.floor(record.facts.actualElapsedSeconds / 60)}分 · ${record.facts.completedSteps.filter(Boolean).length}步` : "详细结果未记录"}</span>${icon("i-arrow")}</button>`).join("") : `<div class="empty-outcomes"><b>还没有记录</b><span>真实首次启动不会用旧文案或布尔标记制造结果。</span></div>`}</div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="export-report">导出 / 打印家庭复盘</button><button class="btn btn-primary" data-action="close-modal">返回</button></footer>`, "modal-wide history-modal");
}

function selfReportBlock(label, checkIn, lines, redacted = false) {
  return `<section class="source-detail self-report-detail"><header><span class="source-chip self-source">参与者自报</span><b>${escapeHTML(label)}</b><time>${redacted ? "内容已遮盖" : formatTimestamp(checkIn?.submittedAt)}</time></header>${checkIn ? `<dl>${lines.filter(([, value]) => value !== null && value !== "").map(([term, value]) => `<div><dt>${escapeHTML(term)}</dt><dd>${escapeHTML(value)}</dd></div>`).join("") || `<p>只保存了部分回答。</p>`}</dl>` : `<p>${redacted ? "已按撤回 / 来源失效规则遮盖；只保留适当的非识别汇总事实。" : "未填写；不会被解释为放心、安全或同意延长。"}</p>`}</section>`;
}

function showSessionDetail(id) {
  const record = outcomeRecord(id);
  if (!record) { toast("找不到这次记录"); return; }
  if (record.status === "legacy") {
    openModal(`${modalHead("EARLIER COMPLETION", "较早完成，详细结果未记录")}<div class="modal-body"><div class="empty-outcomes"><b>不会从旧布尔标记补造时长、休息或信心</b><span>这条历史只说明旧版本曾标记完成。请进行一次当前授权下的新彩排，得到可核对的事实和参与者回答。</span></div></div><footer class="modal-footer"><button class="btn btn-primary" data-action="close-modal">知道了</button></footer>`);
    return;
  }
  const facts = record.facts;
  const caregiver = record.checkIns.caregiver;
  const substitute = record.checkIns.substitute;
  const recipient = record.checkIns.careRecipient;
  const contacts = facts?.contactActionsOpened || [];
  const companion = companionRoom?.sessionId === id;
  openModal(`${modalHead(record.demo ? "DEMO OUTCOME · SESSION DETAIL" : "SESSION DETAIL", `${OutcomeModel.STAGE_LABELS[record.startSnapshot.stage]} · ${OutcomeModel.STATUS_LABELS[record.status] || record.status}`)}<div class="modal-body session-detail-body"><section class="source-detail app-record-detail"><header><span class="source-chip app-source">应用记录</span><b>本次固定范围与结束事实</b><time>${formatTimestamp(facts?.recordedAt || record.startSnapshot.startedAt)}</time></header><dl><div><dt>稳定会话 ID</dt><dd>${escapeHTML(record.id)}</dd></div><div><dt>计划 / 实际</dt><dd>${record.startSnapshot.plannedDurationMinutes} 分钟 / ${facts ? `${Math.floor(facts.actualElapsedSeconds / 60)}分${facts.actualElapsedSeconds % 60}秒` : "未记录"}</dd></div><div><dt>完成步骤</dt><dd>${facts ? `${facts.completedSteps.filter(Boolean).length}/${facts.completedSteps.length || 3}` : "未记录"}</dd></div><div><dt>普通更新延后</dt><dd>${facts?.routineUpdatesQueued ?? "未记录"}</dd></div><div><dt>待确认缺口</dt><dd>${facts?.pendingGaps?.length ?? "未记录"}${facts?.pendingGaps?.some((gap) => gap.risk === "medical" && gap.status !== "resolved") ? " · 含未解决医疗/高风险" : ""}</dd></div><div><dt>紧急事件</dt><dd>${facts?.urgentAlertsRaised ?? "未记录"}</dd></div><div><dt>联系操作</dt><dd>${contacts.length ? `${contacts.length} 次已打开（不代表通话接通）` : "没有记录到打开操作"}</dd></div><div><dt>开始授权</dt><dd>同意修订 ${record.startSnapshot.consentRevision} · ${record.startSnapshot.mode === "two-device" ? "双机" : "同机"}</dd></div><div><dt>指导范围</dt><dd>${record.redacted ? "内容已按撤回规则遮盖" : record.startSnapshot.guideScope.map((guide) => `${guide.title || guide.id} v${guide.version} · ${guide.source}`).join("；") || "无"}</dd></div></dl></section>${selfReportBlock(state.family.caregiverName || "照护者", caregiver, [["休息活动", { yes:"发生了",partly:"发生一部分",no:"没有发生","not-planned":"本档未计划",unsure:"说不清" }[caregiver?.restHappened]], ["看手机", { "0":"0 次", "1-2":"1–2 次", "3-5":"3–5 次", "6+":"6 次以上", unsure:"记不清" }[caregiver?.phoneChecks]], ["普通事情打断", { yes:"有",no:"没有",unsure:"说不清" }[caregiver?.nonurgentInterrupted]], ["重复信心", caregiver?.confidence ? `${caregiver.confidence}/5` : null], ["感到不安全", caregiver?.feltUnsafe == null ? null : caregiver.feltUnsafe ? "有" : "没有"], ["下一步", choiceLabel(caregiver?.choice)], ["备注", caregiver?.notes]], record.redacted)}${selfReportBlock(state.family.relayName || "替班者", substitute, [["能处理练过范围", { yes:"能",partly:"一部分能",no:"不能",unsure:"说不清" }[substitute?.ableToHandle]], ["仍不确定", substitute?.uncertainStep], ["联系照护者", { yes:"有",no:"没有",unsure:"说不清" }[substitute?.contactedCaregiver]], ["感到不安全", substitute?.feltUnsafe == null ? null : substitute.feltUnsafe ? "有" : "没有"], ["下一步", choiceLabel(substitute?.choice)], ["备注", substitute?.notes]], record.redacted)}${selfReportBlock(state.family.recipientName || "被照护者", recipient, [["回答状态", { answered:"本人回答", "not-asked":"没有询问", declined:"本人不想回答" }[recipient?.response]], ["舒适度", { comfortable:"舒服",mixed:"有好有坏",uncomfortable:"不舒服",unsure:"说不清" }[recipient?.comfort]], ["偏好", recipient?.preference]], record.redacted)}</div><footer class="modal-footer detail-actions">${record.redacted ? "" : `<button class="btn btn-secondary" data-action="fill-session-role" data-session-id="${escapeHTML(id)}" data-role="caregiver" data-companion="${companion}">照护者${caregiver ? "补充" : "填写"}</button>${record.startSnapshot.mode === "single-device" ? `<button class="btn btn-secondary" data-action="fill-session-role" data-session-id="${escapeHTML(id)}" data-role="substitute">替班者${substitute ? "补充" : "填写"}</button>` : ""}<button class="btn btn-secondary" data-action="fill-session-role" data-session-id="${escapeHTML(id)}" data-role="careRecipient" data-companion="${companion}">本人可选回答</button>`}<button class="btn btn-primary" data-action="close-modal">完成</button></footer>`, "modal-wide session-detail-modal");
}

function sanitizedFamilyReport(includeSensitiveNotes = false) {
  const sessions = normalizeOutcomeSessions(state.sessions).map((record) => OutcomeModel.redactSession(record, state.revokedGuideIds)).filter(Boolean).map((record) => {
    const clean = structuredClone(record);
    for (const role of ["caregiver", "substitute"]) if (clean.checkIns?.[role] && !includeSensitiveNotes) clean.checkIns[role].notes = "";
    if (clean.checkIns?.careRecipient && !includeSensitiveNotes) clean.checkIns.careRecipient.preference = "";
    return clean;
  });
  return {
    schemaVersion: OutcomeModel.VERSION,
    generatedAt: nowISO(),
    reportType: "接班彩排家庭复盘（本地生成）",
    household: { caregiverName: state.family.caregiverName, substituteName: state.family.relayName, careRecipientName: state.family.recipientName },
    exclusions: ["邀请能力与令牌", "原始紧急电话号码", ...(includeSensitiveNotes ? [] : ["敏感会话备注与本人偏好"])],
    sensitiveSessionNotes: includeSensitiveNotes ? "included-by-caregiver" : "excluded-by-default",
    recommendation: householdRecommendation(),
    metrics: OutcomeModel.metrics(sessions),
    sessions,
  };
}

function familyReportMarkup(report) {
  const restLabel = (value) => ({ yes: "发生了", partly: "发生一部分", no: "没有发生", "not-planned": "本档未计划", unsure: "说不清" }[value] || "未答");
  const ableLabel = (value) => ({ yes: "能", partly: "一部分能", no: "不能", unsure: "说不清" }[value] || "未答");
  const responseLabel = (value) => ({ answered: "本人回答", "not-asked": "没有询问", declined: "本人不想回答" }[value] || "未记录");
  const phoneLabel = (value) => ({ "0": "0 次", "1-2": "1–2 次", "3-5": "3–5 次", "6+": "6 次以上", unsure: "记不清" }[value] || "未答");
  const yesNoLabel = (value) => ({ yes: "有", no: "没有", unsure: "说不清" }[value] || "未答");
  const unsafeLabel = (value) => value == null ? "未答" : value ? "有" : "没有";
  const comfortLabel = (value) => ({ comfortable: "舒服", mixed: "有好有坏", uncomfortable: "不舒服", unsure: "说不清" }[value] || "未答");
  return `<article class="family-report"><header><small>本地生成 · ${formatTimestamp(report.generatedAt)}</small><h1>接班彩排家庭复盘</h1><p>应用事实与参与者自报分开列出。记录之间的变化不代表因果，也不构成临床安全或心理健康结论。</p></header><section class="report-exclusions"><b>默认不包含</b><span>${report.exclusions.join("、")}</span></section><section><h2>家庭摘要</h2><div class="report-metrics"><span><b>${report.metrics.protectedMinutes}</b>实际完成离班分钟</span><span><b>${report.metrics.independentHandoffs}</b>独立交接</span><span><b>${report.metrics.routineUpdatesDeferred}</b>延后普通更新</span><span><b>${report.metrics.urgentEvents}</b>紧急事件</span></div><p><b>建议下一档：</b>${OutcomeModel.STAGE_LABELS[report.recommendation.stage]}。${report.recommendation.reasons.map(escapeHTML).join("；")}</p></section><section><h2>逐次记录</h2>${report.sessions.length ? report.sessions.slice().reverse().map((record) => `<article class="report-session"><h3>${record.startSnapshot ? OutcomeModel.STAGE_LABELS[record.startSnapshot.stage] : "较早记录"} · ${OutcomeModel.STATUS_LABELS[record.status] || record.status}${record.demo ? " · 演示" : ""}${record.redacted ? " · 内容已遮盖" : ""}</h3><p class="report-source"><b>应用记录 · ${formatTimestamp(record.facts?.recordedAt || record.startSnapshot?.startedAt)}</b>${record.facts ? `实际 ${Math.floor(record.facts.actualElapsedSeconds / 60)}分${record.facts.actualElapsedSeconds % 60}秒；步骤 ${record.facts.completedSteps.filter(Boolean).length}/${record.facts.completedSteps.length || 3}；普通更新 ${record.facts.routineUpdatesQueued}；紧急事件 ${record.facts.urgentAlertsRaised}；打开联系操作 ${record.facts.contactActionsOpened.length} 次（不代表接通）` : "较早完成，详细结果未记录"}</p><p class="report-source"><b>照护者自报 · ${formatTimestamp(record.checkIns?.caregiver?.submittedAt)}</b>${record.checkIns?.caregiver ? `休息活动 ${restLabel(record.checkIns.caregiver.restHappened)}；看手机 ${phoneLabel(record.checkIns.caregiver.phoneChecks)}；普通事情实际打断 ${yesNoLabel(record.checkIns.caregiver.nonurgentInterrupted)}；信心 ${record.checkIns.caregiver.confidence || "未答"}/5；感到不安全 ${unsafeLabel(record.checkIns.caregiver.feltUnsafe)}；选择 ${choiceLabel(record.checkIns.caregiver.choice)}${record.checkIns.caregiver.notes ? `；备注 ${escapeHTML(record.checkIns.caregiver.notes)}` : ""}` : record.redacted ? "已按撤回规则遮盖" : "未填写"}</p><p class="report-source"><b>替班者自报 · ${formatTimestamp(record.checkIns?.substitute?.submittedAt)}</b>${record.checkIns?.substitute ? `能处理 ${ableLabel(record.checkIns.substitute.ableToHandle)}；仍不确定 ${escapeHTML(record.checkIns.substitute.uncertainStep || "未答")}；联系照护者 ${yesNoLabel(record.checkIns.substitute.contactedCaregiver)}；感到不安全 ${unsafeLabel(record.checkIns.substitute.feltUnsafe)}；选择 ${choiceLabel(record.checkIns.substitute.choice)}${record.checkIns.substitute.notes ? `；备注 ${escapeHTML(record.checkIns.substitute.notes)}` : ""}` : record.redacted ? "已按撤回规则遮盖" : "未填写"}</p><p class="report-source"><b>本人自报 · ${formatTimestamp(record.checkIns?.careRecipient?.submittedAt)}</b>${record.checkIns?.careRecipient ? `${responseLabel(record.checkIns.careRecipient.response)}；舒适度 ${comfortLabel(record.checkIns.careRecipient.comfort)}${record.checkIns.careRecipient.preference ? `；偏好 ${escapeHTML(record.checkIns.careRecipient.preference)}` : ""}` : record.redacted ? "已按撤回规则遮盖" : "未记录（不是默认同意）"}</p></article>`).join("") : "<p>没有实际记录。</p>"}</section></article>`;
}

function showExportReport() {
  const report = sanitizedFamilyReport(false);
  openModal(`${modalHead("LOCAL FAMILY REVIEW", "导出 / 打印家庭复盘")}<div class="modal-body"><label class="confirm-item report-sensitive"><input type="checkbox" id="include-sensitive-notes">由照护者选择：包含敏感会话备注与本人偏好</label><div class="safety-note">${icon("i-lock")}报告永远排除邀请能力、令牌和原始紧急电话号码；撤回或来源失效的内容按当前遮盖规则处理。</div><div id="family-report-preview">${familyReportMarkup(report)}</div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="download-report">下载本地 JSON</button><button class="btn btn-primary" data-action="print-report">打印 / 存为 PDF</button></footer>`, "modal-wide report-modal");
  $("#include-sensitive-notes").addEventListener("change", (event) => { $("#family-report-preview").innerHTML = familyReportMarkup(sanitizedFamilyReport(event.currentTarget.checked)); });
}

function showNotifications() {
  if (state.mode === "real") {
    const activities = visibleActivities().slice(0, 3);
    const body = activities.length ? activities.map((item) => `<div class="history-item"><span class="history-check">${icon("i-check")}</span><span><b>${escapeHTML(item.title)}</b><small>${escapeHTML(item.note)}</small></span><small>${escapeHTML(item.date)}</small></div>`).join("") : `<div class="empty-notice">${icon("i-bell")}还没有家庭消息或练习记录。完成的真实活动会出现在这里。</div>`;
    openModal(`${modalHead("HOUSEHOLD ACTIVITY", `${state.quietInbox} 件稍后消息`)}<div class="modal-body"><div class="history-list">${body}</div></div><footer class="modal-footer"><button class="btn btn-primary" data-action="close-modal">知道了</button></footer>`);
    return;
  }
  const currentRecipientGuide = usableGuides().find((guide) => guide.provenance.actorId === SOURCE_IDS.RECIPIENT);
  const second = currentRecipientGuide ? `<div class="history-item"><span class="history-check">${icon("i-book")}</span><span><b>“${escapeHTML(currentRecipientGuide.title)}”当前可用</b><small>来源：${escapeHTML(sourceView(currentRecipientGuide).label)}</small></span><small>${escapeHTML(currentRecipientGuide.updated)}</small></div>` : isRecipientAuthorized() ? `<div class="history-item"><span class="history-check">${icon("i-shield")}</span><span><b>本人已重新同意参与</b><small>先前撤回的内容和已阅声明没有恢复</small></span><small>当前</small></div>` : `<div class="history-item"><span class="history-check">${icon("i-shield")}</span><span><b>本人参与和内容已撤回</b><small>本人来源指导已停用，新的接班已暂停</small></span><small>当前</small></div>`;
  openModal(`${modalHead("QUIET INBOX", "2 件事情，等你方便时再看")}<div class="modal-body"><div class="history-list"><div class="history-item"><span class="history-check">${icon("i-check")}</span><span><b>${escapeHTML(state.family.relayName)}确认了红线规则</b><small>紧急联系路径仍然保留</small></span><small>10:24</small></div>${second}</div></div><footer class="modal-footer"><button class="btn btn-primary" data-action="close-modal">知道了</button></footer>`);
}

function showProfile() {
  const family = state.family;
  const consentRevisionAtOpen = state.recipientConsent.revision;
  const consentControl = state.mode === "real" && !isRecipientAuthorized()
    ? `<div class="confirm-item consent-control"><span>${icon("i-lock")}</span><span><b>被照护者本人当前未同意</b><small>不能在照护者设置里代勾同意。请回到专用的当面确认页，把手机交给本人。</small></span><button type="button" class="btn btn-secondary btn-small" data-action="reconsent-in-person">请本人当面确认</button></div>`
    : `<label class="confirm-item consent-control"><input type="checkbox" name="recipientConsented" ${isRecipientAuthorized() ? "checked" : ""} ${family.recipientName ? "" : "disabled"}><span><b>被照护者本人明确同意参与彩排</b><small>${isRecipientAuthorized() ? "当前已同意；取消勾选并保存会立即撤回。" : "当前未同意。勾选是一次新的明确同意，不会恢复旧内容或旧确认。"}</small></span></label>`;
  openModal(`${modalHead("FAMILY SETUP", "家庭与紧急联系设置")}<form id="family-form" data-consent-revision="${consentRevisionAtOpen}"><div class="modal-body">
    <div class="form-grid">
      <div class="field"><label for="caregiver-name">主要照护者</label><input id="caregiver-name" name="caregiverName" required value="${escapeHTML(family.caregiverName)}"></div>
      <div class="field"><label for="caregiver-phone">照护者电话</label><input id="caregiver-phone" name="caregiverPhone" type="tel" required value="${escapeHTML(family.caregiverPhone)}"></div>
      <div class="field"><label for="recipient-name">被照护者姓名</label><input id="recipient-name" name="recipientName" value="${escapeHTML(family.recipientName)}" placeholder="尚未设置"></div>
      <div class="field"><label for="relay-name">替班者姓名</label><input id="relay-name" name="relayName" required value="${escapeHTML(family.relayName)}"></div>
      <div class="field"><label for="emergency-name">紧急联系人</label><input id="emergency-name" name="emergencyContactName" required value="${escapeHTML(family.emergencyContactName)}"></div>
      <div class="field"><label for="emergency-phone">紧急联系人电话</label><input id="emergency-phone" name="emergencyContactPhone" type="tel" required value="${escapeHTML(family.emergencyContactPhone)}"></div>
      <div class="field field-full"><label for="emergency-service">当地紧急服务号码</label><input id="emergency-service" name="emergencyService" type="tel" required value="${escapeHTML(family.emergencyService)}"><span class="field-help">请按所在地核对，应用不会默认假设是 120。</span></div>
    </div>
    ${consentControl}
    <div class="source-proof">${icon("i-shield")}被照护者当前状态：${isRecipientAuthorized() ? `已同意参与 · 授权版本 ${state.recipientConsent.revision}` : `已撤回参与 · 撤回版本 ${state.recipientConsent.revision}`}。重新同意后仍需重新建立指导并确认每次接班。</div>
    <div class="danger-zone"><span><b>被照护者自主权</b><small>撤回会删除由本人提供的指导；移除会同时清空姓名。</small></span><div><button type="button" class="text-button danger-text" data-action="withdraw-recipient">撤回本人内容与参与</button><button type="button" class="text-button danger-text" data-action="remove-recipient">从家庭中移除</button></div></div>
  </div><footer class="modal-footer"><button type="button" class="btn btn-ghost danger-text" data-action="request-mode-reset">${state.mode === "demo" ? "重置或退出演示" : "清空家庭 / 返回模式选择"}</button><button type="button" class="btn btn-secondary" data-action="close-modal">取消</button><button class="btn btn-primary" type="submit">保存家庭设置</button></footer></form>`, "modal-wide");
  $("#family-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (state.recipientConsent.revision !== consentRevisionAtOpen) { closeModal(); render(); toast("同意状态已在其他页面变化，请重新打开设置"); return; }
    const recipientName = String(data.get("recipientName") || "").trim();
    const priorRecipientName = state.family.recipientName;
    const wasAuthorized = isRecipientAuthorized();
    const wantsConsent = Boolean(recipientName && data.has("recipientConsented"));
    state.family = { ...state.family, caregiverName: String(data.get("caregiverName") || "").trim(), caregiverPhone: String(data.get("caregiverPhone") || "").trim(), recipientName, relayName: String(data.get("relayName") || "").trim(), emergencyContactName: String(data.get("emergencyContactName") || "").trim(), emergencyContactPhone: String(data.get("emergencyContactPhone") || "").trim(), emergencyService: String(data.get("emergencyService") || "").trim() };
    if (wasAuthorized && recipientName !== priorRecipientName) {
      revokeRecipientAuthorization({ remove: !recipientName, persist: false });
    } else if (wasAuthorized && !wantsConsent) {
      revokeRecipientAuthorization({ remove: !recipientName, persist: false });
    } else if (!wasAuthorized && wantsConsent && state.mode !== "real") {
      grantRecipientAuthorization();
    } else {
      state.family.recipientConsented = wasAuthorized && wantsConsent;
    }
    saveState(); closeModal(); render(); toast("家庭与紧急联系设置已保存");
  });
}

function grantRecipientAuthorization() {
  if (!state.family.recipientName || isRecipientAuthorized()) return false;
  const currentAuthority = readAuthorityRecord();
  const revision = Math.max(Number(state.recipientConsent.revision) || 0, Number(currentAuthority?.revision) || 0) + 1;
  state.recipientConsent = { status: "granted", revision, grantedAt: nowISO(), withdrawnAt: null };
  writeAuthorityRecord(state.recipientConsent);
  state.family.recipientConsented = true;
  state.rehearsalCompleted = false;
  if (state.mode === "real") state.stageOneCompleted = false;
  state.activeRest = null;
  state.activeRehearsal = null;
  state.confirmations.forEach((record) => {
    if ((record.type === "rehearsal" || record.type === "offDuty") && record.status === "current") record.status = "superseded";
  });
  addConfirmation({ type: "participation", actorId: SOURCE_IDS.RECIPIENT, consentRevision: state.recipientConsent.revision });
  return true;
}

function revokeRecipientAuthorization({ remove = false, persist = true } = {}) {
  const wasAuthorized = state.recipientConsent?.status === "granted";
  const currentAuthority = readAuthorityRecord();
  const baseRevision = Math.max(Number(state.recipientConsent.revision) || 0, Number(currentAuthority?.revision) || 0);
  const revision = wasAuthorized || currentAuthority?.status === "granted" ? baseRevision + 1 : baseRevision;
  state.recipientConsent = { ...state.recipientConsent, status: "withdrawn", revision: Math.max(1, revision), withdrawnAt: nowISO() };
  writeAuthorityRecord(state.recipientConsent);
  state.family.recipientConsented = false;
  const revoked = new Set(state.revokedGuideIds || []);
  state.guides = state.guides.filter((guide) => {
    if (guide?.provenance?.actorId === SOURCE_IDS.RECIPIENT) {
      revoked.add(String(guide.id));
      return false;
    }
    return true;
  });
  state.revokedGuideIds = [...revoked];
  state.confirmations.forEach((record) => {
    if (record.status === "current" && (record.actorId === SOURCE_IDS.RECIPIENT || record.type === "rehearsal" || record.type === "offDuty")) {
      record.status = "revoked";
      record.revokedAt = nowISO();
    }
  });
  state.activity = visibleActivities(state);
  state.debriefs = state.debriefs.filter((item) => item?.provenance?.actorId !== SOURCE_IDS.RECIPIENT);
  state.rehearsalCompleted = false;
  if (state.mode === "real") {
    state.stageOneCompleted = false;
    state.onboarding = { ...state.onboarding, status: "in-progress", step: 3, consentDecision: "withdrawn" };
  }
  state.activeRest = null;
  state.activeRehearsal = null;
  session = null;
  restSession = null;
  if (remove) state.family.recipientName = "";
  if (persist) saveState();
}

function resetDemoState() {
  const currentAuthority = readAuthorityRecord();
  const fresh = migrateState(structuredClone(demoState), true);
  const revision = Math.max(1, Number(currentAuthority?.revision) || 0) + 1;
  fresh.recipientConsent = { status: "granted", revision, grantedAt: nowISO(), withdrawnAt: null };
  fresh.family.recipientConsented = true;
  fresh.revokedGuideIds = [];
  fresh.guides.forEach((guide) => {
    if (guide.provenance?.actorId === SOURCE_IDS.RECIPIENT) guide.provenance.consentRevision = revision;
  });
  fresh.confirmations.forEach((record) => {
    if (record.actorId === SOURCE_IDS.RECIPIENT) {
      record.consentRevision = revision;
      record.status = "current";
    }
  });
  fresh.sessions = demoOutcomeRecords().map((record) => ({ ...record, startSnapshot: { ...record.startSnapshot, consentRevision: revision } }));
  state = fresh;
  writeAuthorityRecord(state.recipientConsent);
  session = null;
  restSession = null;
  clearCompanionLocal();
  saveState({ ignorePersisted: true });
}

function startRealHousehold() {
  const currentAuthority = readAuthorityRecord();
  const fresh = emptyState("real");
  const revision = Math.max(1, Number(currentAuthority?.revision) || 1);
  fresh.recipientConsent.revision = revision;
  state = fresh;
  session = null;
  restSession = null;
  clearCompanionLocal();
  saveState({ ignorePersisted: true });
}

function resetToModeChoice() {
  const currentAuthority = readAuthorityRecord();
  const revision = Math.max(Number(state.recipientConsent?.revision) || 0, Number(currentAuthority?.revision) || 0) + 1;
  const consent = { status: "withdrawn", revision, grantedAt: null, withdrawnAt: nowISO() };
  writeAuthorityRecord(consent);
  state = emptyState(null);
  state.recipientConsent = consent;
  session = null;
  restSession = null;
  clearCompanionLocal();
  currentPage = "home";
  history.replaceState(null, "", "#home");
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function showRecipientConfirm(mode) {
  const remove = mode === "remove";
  openModal(`${modalHead("CARE RECIPIENT CONTROL", remove ? "从家庭中移除被照护者？" : "撤回本人内容与参与？")}<div class="modal-body"><p style="color:var(--ink-2);font-size:11px;line-height:1.7">${remove ? "将清空被照护者姓名，撤销所有稳定标记为本人来源的指导，并结束当前接班。家庭可以稍后重新邀请。" : "将撤销所有稳定标记为本人来源的指导、旧的接班确认与活动接班；这不依赖任何显示名称。其他获授权来源的指导不受影响。"}</p><div class="source-proof">${icon("i-shield")}操作会立即持久化并同步到本设备的其他页面。重新同意也不会恢复这些内容。</div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">保留</button><button class="btn btn-danger" data-action="confirm-recipient-control" data-mode="${mode}">${remove ? "确认移除" : "确认撤回"}</button></footer>`);
}

function showDataResetConfirm() {
  const real = state.mode === "real";
  openModal(`${modalHead("DATA & MODE", real ? "清空这个家庭并返回模式选择？" : "重置或退出演示？")}<div class="modal-body"><div class="question-result no-match-result"><span class="result-label">不可撤销</span><h3>${real ? "成员、同意、指导和真实练习记录都会从本设备删除" : "当前演示修改、练习和待确认问题都会被替换"}</h3><p>必须点击下方红色按钮才会执行。取消或关闭不会更改任何数据。</p></div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">取消，保留数据</button>${real ? "" : `<button class="btn btn-secondary" data-action="confirm-reset-demo">确认重置演示</button>`}<button class="btn btn-danger" data-action="confirm-reset-choice">确认清空并返回选择</button></footer>`);
}

function toast(message) {
  const node = document.createElement("div");
  node.className = "toast";
  node.innerHTML = `${icon("i-check")}<span>${escapeHTML(message)}</span>`;
  $("#toast-root").append(node);
  setTimeout(() => { node.classList.add("out"); setTimeout(() => node.remove(), 260); }, 2800);
}

function navigate(page) {
  if (session) {
    const record = state.confirmations.find((item) => item.id === session.confirmationId);
    if (record?.status === "current") record.status = "superseded";
    finishOutcomeRecord(session.sessionRecordId, { status: "abandoned", tasks: session.tasks, pendingGaps: (session.pendingGapIds || []).map((id) => state.gaps.find((gap) => gap.id === id)).filter(Boolean) });
    state.activeRehearsal = null;
    saveState();
  }
  session = null;
  if (restSession && page !== "rest") { toast("真正离班仍在进行，请先结束本次离班"); return; }
  currentPage = normalizePage(page);
  history.replaceState(null, "", `#${currentPage}`);
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("#app").focus({ preventScroll: true });
}

document.addEventListener("click", async (event) => {
  const phoneLink = event.target.closest("a[href^='tel:']");
  if (phoneLink && (session || restSession)) addContactAction(phoneLink.getAttribute("href") === phoneHref(state.family.emergencyService) ? "emergency-service" : "caregiver");
  if (phoneLink && companionRoom?.status === "active" && phoneLink.closest("#companion-card")) {
    event.preventDefault();
    const target = phoneLink.getAttribute("href") === phoneHref(state.family.emergencyService) ? "emergency-service" : "caregiver";
    await companionMutation("caregiver.contact-opened", { target });
    location.href = phoneLink.href;
    return;
  }
  const nav = event.target.closest("[data-nav]");
  if (nav) { event.preventDefault(); navigate(nav.dataset.nav); return; }
  const filter = event.target.closest("[data-filter]");
  if (filter) { state.guideFilter = filter.dataset.filter; saveState(); renderGuides(); return; }
  const task = event.target.closest("[data-task]");
  if (task && session) { const index = Number(task.dataset.task); session.tasks[index] = !session.tasks[index]; state.activeRehearsal = { ...session, tasks: [...session.tasks] }; saveState(); renderActiveRehearsal(); if (session.tasks.every(Boolean)) toast(session.stage === "observe" ? "在旁步骤已完成，可以一起确认记录" : "本次步骤已全部完成，可以结束并复盘"); return; }
  const duration = event.target.closest("[data-duration]");
  if (duration) { $$(".duration-option").forEach((item) => item.classList.toggle("active", item === duration)); $("[data-duration-value]").dataset.durationValue = duration.dataset.duration; return; }

  const trigger = event.target.closest("[data-action]");
  if (!trigger) return;
  const action = trigger.dataset.action;
  const focusJudgeStep = () => requestAnimationFrame(() => $("#judge-step-title")?.focus({ preventScroll: false }));
  if (action === "choose-demo") { if (companionRoom && !["revoked", "expired", "ended", "invalidated"].includes(companionRoom.status)) await revokeCompanion(); resetDemoState(); currentPage = "home"; history.replaceState(null, "", "#home"); render(); focusJudgeStep(); toast("已进入明确标注的演示家庭"); }
  else if (action === "choose-real") { if (HOSTED_STATIC_REVIEW) { showLocalFullExperience(); return; } if (companionRoom && !["revoked", "expired", "ended", "invalidated"].includes(companionRoom.status)) await revokeCompanion(); startRealHousehold(); render(); }
  else if (action === "show-local-full-experience") showLocalFullExperience();
  else if (action === "review-brief") showReviewBrief();
  else if (action === "restart-judge" || action === "judge-restart") {
    if (state.mode !== "demo") return;
    if (companionRoom && !["revoked", "expired", "ended", "invalidated"].includes(companionRoom.status)) await revokeCompanion();
    resetDemoState();
    currentPage = "home";
    history.replaceState(null, "", "#home");
    render();
    focusJudgeStep();
    toast("演示已恢复到起点；真实家庭数据未被使用");
  }
  else if (action === "judge-role") {
    const journey = demoJourneyState();
    if (!journey || !["caregiver", "substitute", "careRecipient"].includes(trigger.dataset.role)) return;
    journey.role = trigger.dataset.role;
    saveState();
    render();
    requestAnimationFrame(() => $(`[data-action="judge-role"][data-role="${trigger.dataset.role}"]`)?.focus());
  }
  else if (action === "judge-next") {
    const journey = demoJourneyState();
    if (!journey) return;
    journey.step = Math.min(6, Number(journey.step) + 1);
    journey.role = ["caregiver", "substitute", "substitute", "substitute", "caregiver", "caregiver", "caregiver"][journey.step] || "caregiver";
    saveState();
    render();
    focusJudgeStep();
  }
  else if (action === "judge-known") {
    const journey = demoJourneyState();
    if (!journey) return;
    journey.knownSeen = Boolean(matchConfirmedGuide("她说不饿，不愿意吃午饭"));
    saveState();
    render();
    focusJudgeStep();
  }
  else if (action === "judge-ordinary") {
    const journey = demoJourneyState();
    if (!journey) return;
    const gap = logGap("她想把收音机搬到窗边");
    journey.ordinarySeen = Boolean(gap);
    journey.ordinaryGapId = gap?.id || null;
    saveState();
    render();
    focusJudgeStep();
  }
  else if (action === "judge-medical") {
    const journey = demoJourneyState();
    if (!journey) return;
    const gap = logGap("她说胸口发紧");
    journey.medicalSeen = Boolean(gap?.risk === "medical");
    journey.medicalGapId = gap?.id || null;
    saveState();
    render();
    focusJudgeStep();
  }
  else if (action === "judge-checkin") {
    const journey = demoJourneyState();
    if (!journey) return;
    const record = createJudgeDemoOutcome();
    journey.sampleSessionId = record.id;
    saveState();
    render();
    focusJudgeStep();
  }
  else if (action === "judge-finish") {
    const journey = demoJourneyState();
    if (!journey) return;
    journey.finished = true;
    saveState();
    render();
    requestAnimationFrame(() => {
      const details = $(".demo-workspace");
      if (details) details.open = true;
      details?.querySelector("summary")?.focus();
      details?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  else if (action === "onboarding-back") { state.onboarding.step = Math.max(1, Number(state.onboarding.step) - 1); saveState(); render(); }
  else if (action === "onboarding-jump") { state.onboarding.step = Number(trigger.dataset.step) || 1; saveState(); render(); }
  else if (action === "consent-decline") recordOnboardingConsentDecision("declined");
  else if (action === "consent-skip") recordOnboardingConsentDecision("skipped");
  else if (action === "use-redline-example") {
    const fields = $$("#onboarding-rules input[name='redline']");
    const target = fields.find((field) => !field.value.trim()) || fields[fields.length - 1];
    if (target) { target.value = trigger.dataset.value || ""; target.focus(); }
  }
  else if (action === "record-setup-situation") startSpeechForInput("setup-situation", "setup-speech-status", trigger);
  else if (action === "record-setup-instruction") startSpeechForInput("setup-instruction", "setup-speech-status", trigger);
  else if (action === "backdrop-close" && event.target === trigger) closeModal();
  else if (action === "close-modal") closeModal();
  else if (action === "profile") showProfile();
  else if (action === "request-mode-reset") showDataResetConfirm();
  else if (action === "confirm-reset-demo") { if (companionRoom && !["revoked", "expired", "ended", "invalidated"].includes(companionRoom.status)) await revokeCompanion(); resetDemoState(); closeModal(); render(); toast("演示家庭已重置"); }
  else if (action === "confirm-reset-choice") { if (companionRoom && !["revoked", "expired", "ended", "invalidated"].includes(companionRoom.status)) await revokeCompanion(); resetToModeChoice(); closeModal(); render(); }
  else if (action === "reconsent-in-person") { closeModal(); state.onboarding = { ...state.onboarding, status: "in-progress", step: 3, consentDecision: "pending" }; saveState(); render(); }
  else if (action === "notifications") showNotifications();
  else if (action === "outcome-history") showOutcomeHistory();
  else if (action === "session-detail") showSessionDetail(trigger.dataset.sessionId);
  else if (action === "fill-session-role") showOutcomeCheckIn(trigger.dataset.sessionId, trigger.dataset.role, { companion: trigger.dataset.companion === "true" });
  else if (action === "export-report") showExportReport();
  else if (action === "override-stage") {
    const stage = trigger.dataset.stage;
    const current = householdRecommendation().stage;
    if (!OutcomeModel.STAGES.includes(stage) || OutcomeModel.stageIndex(stage) >= OutcomeModel.stageIndex(current)) { toast("只能把建议调到更保守的档位"); return; }
    state.recommendationOverride = { stage, setAt: nowISO(), setBy: SOURCE_IDS.CAREGIVER };
    saveState(); closeModal(); render(); toast(`下一次已由照护者下调为${OutcomeModel.STAGE_LABELS[stage]}`);
  }
  else if (action === "download-report") {
    const includeSensitive = Boolean($("#include-sensitive-notes")?.checked);
    const blob = new Blob([JSON.stringify(sanitizedFamilyReport(includeSensitive), null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `接班彩排-家庭复盘-${new Date().toISOString().slice(0, 10)}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 500);
  }
  else if (action === "print-report") {
    const includeSensitive = Boolean($("#include-sensitive-notes")?.checked);
    const printWindow = window.open("", "_blank");
    if (!printWindow) { toast("浏览器阻止了打印窗口，请允许弹窗后重试"); return; }
    try { printWindow.opener = null; } catch { /* The report contains no capabilities or contact numbers. */ }
    printWindow.document.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>接班彩排家庭复盘</title><style>body{font:14px/1.6 system-ui,sans-serif;color:#203033;max-width:900px;margin:32px auto;padding:0 20px}h1{font-size:28px}h2{margin-top:28px;border-bottom:1px solid #ddd}.report-exclusions,.report-source,.report-session{padding:12px;border:1px solid #ddd;border-radius:10px;margin:10px 0}.report-source b{display:block}.report-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.report-metrics span{padding:10px;background:#f3f3ef}.report-metrics b{display:block;font-size:20px}@media print{body{margin:0}.report-session{break-inside:avoid}}</style></head><body>${familyReportMarkup(sanitizedFamilyReport(includeSensitive))}</body></html>`);
    printWindow.document.close(); printWindow.focus(); printWindow.print();
  }
  else if (action === "guide-detail") showGuideDetail(trigger.dataset.id);
  else if (action === "add-guide") showGuideForm();
  else if (action === "edit-guide") showGuideForm(trigger.dataset.id);
  else if (action === "review-gap") showGapReview(trigger.dataset.id);
  else if (action === "preview-guide") { const guide = focusGuide(); if (guide) showGuideDetail(guide.id); }
  else if (action === "safety-rules") showSafetyRules();
  else if (action === "edit-rules") showRulesEditor();
  else if (action === "create-companion") {
    if (HOSTED_STATIC_REVIEW) { showLocalFullExperience(); return; }
    await createCompanionRoom();
  }
  else if (action === "companion-primary") {
    if (HOSTED_STATIC_REVIEW) { showLocalFullExperience(); return; }
    if (!companionSession) await createCompanionRoom();
    else if (companionRoom?.status === "waiting") showCompanionInvite();
    else {
      currentPage = "rehearsal";
      history.replaceState(null, "", "#rehearsal");
      render();
      requestAnimationFrame(() => document.getElementById("companion-card")?.scrollIntoView({ behavior: "smooth", block: "center" }));
    }
  }
  else if (action === "show-companion-invite") showCompanionInvite();
  else if (action === "use-same-device-fallback") {
    const revoked = await revokeCompanion({ retries: 3, announce: false });
    if (!revoked) { toast("先恢复网络并作废双机邀请，再使用同机备用"); return; }
    clearCompanionLocal();
    showRehearsalSetup();
  }
  else if (action === "refresh-companion") await refreshCompanion({ announce: true });
  else if (action === "copy-companion-link") {
    const field = $("#companion-link");
    try {
      await navigator.clipboard.writeText(field?.value || "");
      toast("一次性链接已复制");
    } catch {
      field?.select();
      document.execCommand("copy");
      toast("一次性链接已复制");
    }
  }
  else if (action === "acknowledge-companion-caregiver") {
    openModal(`${modalHead("CAREGIVER CONFIRMATION", "照护者逐项确认本次双机范围")}<div class="modal-body"><div class="confirm-list"><label class="confirm-item"><input type="checkbox" name="companionCaregiverAck" value="scope">替班者只进入本次“${escapeHTML(companionStageDetails(companionRoom.stage).label)}”，不是家庭主页</label><label class="confirm-item"><input type="checkbox" name="companionCaregiverAck" value="guide">完整可搜索指导范围共 ${companionRoom.searchGuides?.length || 0} 条；已逐条核对下方处理文字、版本、来源和升级层级</label>${reviewedGuideScopeMarkup()}<label class="confirm-item"><input type="checkbox" name="companionCaregiverAck" value="redlines">本次红线是：${escapeHTML(companionRoom.redLines.join("、") || "不确定时立即联系")}</label><label class="confirm-item"><input type="checkbox" name="companionCaregiverAck" value="contacts">照护者电话与当地紧急服务 ${escapeHTML(companionRoom.family.emergencyService)} 可直接拨打</label></div><div class="safety-note">${icon("i-shield")}服务器会把本次完整搜索范围与确认绑定到照护者参与者 ID、房间会话 ID、同意版本、主要指导版本和安全范围版本；任一内容变化都会使房间失效。</div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">返回</button><button class="btn btn-primary" data-action="confirm-companion-caregiver-ack">四项都确认</button></footer>`);
  }
  else if (action === "confirm-companion-caregiver-ack") {
    const complete = $$("input[name='companionCaregiverAck']").length === 4 && $$("input[name='companionCaregiverAck']").every((input) => input.checked);
    if (!complete) { toast("请逐项核对四项范围后再确认"); return; }
    await companionMutation("caregiver.acknowledge", {
      scopeAcknowledged: true,
      currentGuideAcknowledged: true,
      redLinesAcknowledged: true,
      contactsAcknowledged: true,
    });
    if (companionRoom?.confirmations.caregiver) { closeModal(); render(); toast("照护者本次确认已绑定到当前房间版本"); }
  }
  else if (action === "start-companion") {
    await companionMutation("caregiver.start");
    if (companionRoom?.status === "active") toast("双机彩排已开始，替班者手机会自动进入三步任务");
  }
  else if (action === "end-companion") {
    openModal(`${modalHead("END TWO-DEVICE REHEARSAL", "先结束现场，再完成来源复盘")}<div class="modal-body"><div class="field"><label for="companion-caregiver-note">照护者收尾（可选）</label><textarea id="companion-caregiver-note" maxlength="240" placeholder="例如：三步都完成，接下来复核一个仍不放心的问题"></textarea><span class="field-help">这一步只冻结现场步骤、普通记录和红线数量，不会自动升级阶段。下一步仍需确认薄弱点、处理文字与来源，或把问题留在待确认缺口。</span></div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="close-modal">继续彩排</button><button class="btn btn-primary" data-action="confirm-end-companion">结束现场并进入复盘</button></footer>`);
  }
  else if (action === "confirm-end-companion") {
    const caregiverNote = $("#companion-caregiver-note")?.value.trim() || "";
    await companionMutation("caregiver.end", { caregiverNote });
    if (companionRoom?.status === "debrief") {
      closeModal();
      render();
      toast("现场已冻结；完成来源复盘前不会升级接班阶段");
    }
  }
  else if (action === "open-companion-caregiver-checkin") showOutcomeCheckIn(companionRoom.sessionId, "caregiver", { companion: true });
  else if (action === "open-companion-recipient-checkin") showOutcomeCheckIn(companionRoom.sessionId, "careRecipient", { companion: true });
  else if (action === "open-companion-debrief") {
    const options = availableGuideSources().map((source) => `<option value="${source.id}">${escapeHTML(source.label)}</option>`).join("");
    openModal(`${modalHead("PROVENANCE DEBRIEF", "只确认一个仍不放心的情境")}<div class="modal-body"><div class="form-grid"><div class="field field-full"><label for="companion-debrief-gap">薄弱情境 / 未知问题</label><input id="companion-debrief-gap" maxlength="160" placeholder="例如：她整理相册后一直看着窗外"></div><div class="field field-full"><label for="companion-debrief-instruction">已经明确说过的处理方式</label><textarea id="companion-debrief-instruction" maxlength="500" placeholder="逐字写下已确认做法；不知道就不要猜"></textarea></div><div class="field field-full"><label for="companion-debrief-source">这段处理方式的真实来源</label><select id="companion-debrief-source"><option value="">请选择来源</option>${options}</select></div></div><div class="safety-note">${icon("i-alert")}若文字涉及胸痛、生命体征、意识、跌倒、走失或用药，系统不会把家庭复盘变成指导，只会保存为医疗/高风险待确认缺口。</div></div><footer class="modal-footer"><button class="btn btn-secondary" data-action="save-companion-pending-gap">只保存待确认缺口</button><button class="btn btn-primary" data-action="finalize-companion-debrief">确认来源并完成</button></footer>`);
  }
  else if (action === "save-companion-pending-gap" || action === "finalize-companion-debrief") {
    const gap = $("#companion-debrief-gap")?.value.trim() || "";
    const instruction = $("#companion-debrief-instruction")?.value.trim() || "";
    const sourceId = $("#companion-debrief-source")?.value || "";
    if (!gap) { toast("请先写下实际遇到的薄弱情境"); return; }
    const risky = SafetyPolicy.classifyFields([gap, instruction]).highRisk;
    const pendingGap = action === "save-companion-pending-gap" || risky;
    const source = sourceDefinition(sourceId);
    if (!pendingGap && (!instruction || !source?.authorized)) { toast("确认成指导前，需要处理文字和当前获授权的真实来源"); return; }
    await companionMutation("caregiver.finalize", {
      outcome: pendingGap ? "pending-gap" : "confirmed-guide",
      gap,
      instruction: pendingGap ? "" : instruction,
      sourceId: pendingGap ? "" : sourceId,
      sourceLabel: pendingGap ? "" : source.label,
    });
    if (companionRoom?.status === "ended") {
      closeModal();
      render();
      toast(pendingGap ? "问题已进入待确认缺口，本次没有升级阶段" : "来源复盘完成，两端已同步最终总结");
    }
  }
  else if (action === "save-outcome-checkin") {
    const recordId = trigger.dataset.sessionId;
    const role = trigger.dataset.role;
    const companion = trigger.dataset.companion === "true";
    let response;
    if (role === "caregiver") response = {
      restHappened: $("#outcome-rest")?.value || null,
      phoneChecks: $("#outcome-phone")?.value || null,
      nonurgentInterrupted: $("#outcome-interrupt")?.value || null,
      confidence: $("#outcome-confidence")?.value ? Number($("#outcome-confidence").value) : null,
      feltUnsafe: $("#outcome-unsafe")?.value === "" ? null : $("#outcome-unsafe").value === "true",
      choice: $("#outcome-choice")?.value || null,
      notes: $("#outcome-notes")?.value.trim() || "",
    };
    else if (role === "substitute") response = {
      ableToHandle: $("#outcome-able")?.value || null,
      uncertainStep: $("#outcome-uncertain")?.value.trim() || "",
      contactedCaregiver: $("#outcome-contacted")?.value || null,
      feltUnsafe: $("#outcome-unsafe")?.value === "" ? null : $("#outcome-unsafe").value === "true",
      choice: $("#outcome-choice")?.value || null,
      notes: $("#outcome-notes")?.value.trim() || "",
    };
    else response = { response: $("#outcome-response")?.value || null, comfort: $("#outcome-comfort")?.value || null, preference: $("#outcome-preference")?.value.trim() || "" };
    if (role === "careRecipient" && !response.response) { closeModal(); toast("本人回答保持未记录；没有被自动补成任何结果"); return; }
    const filled = Object.values(response).filter((value) => value !== null && value !== "").length;
    response.partial = role === "careRecipient" ? response.response === "answered" && !response.comfort : filled < (role === "caregiver" ? 6 : 5);
    response.submittedAt = nowISO();
    if (companion && role === "caregiver" && companionRoom?.sessionId === recordId) {
      const { submittedAt, ...serverResponse } = response;
      const saved = await companionMutation("caregiver.checkin", { response: serverResponse });
      if (!saved) return;
    } else {
      const record = outcomeRecord(recordId);
      if (!record) { closeModal(); toast("找不到这次记录"); return; }
      replaceOutcomeRecord(OutcomeModel.withCheckIn(record, role, response));
      if (record.startSnapshot?.stage === "observe" && householdRecommendation().decision === "extend") {
        state.onboarding.status = "complete";
        state.onboarding.completedAt = nowISO();
      }
      saveState();
    }
    closeModal();
    render();
    toast("回答已按角色保存；未填项目保持空白");
    if (!companion && role === "caregiver") showOutcomeCheckIn(recordId, "substitute");
    else if (!companion && role === "substitute") showOutcomeCheckIn(recordId, "careRecipient");
    else if (companion && role === "caregiver") showOutcomeCheckIn(recordId, "careRecipient", { companion: true });
  }
  else if (action === "reissue-companion") await reissueCompanion();
  else if (action === "revoke-companion") await revokeCompanion();
  else if (action === "replace-companion-room") { clearCompanionLocal(); updateCompanionCard(); await createCompanionRoom(); }
  else if (action === "start-rehearsal") showRehearsalSetup();
  else if (action === "open-family-from-gate") { closeModal(); showProfile(); }
  else if (action === "go-guides-from-gate") { closeModal(); navigate("guides"); }
  else if (action === "go-rehearsal-from-gate") { closeModal(); navigate("rehearsal"); }
  else if (action === "confirm-rehearsal") {
    const form = $("#rehearsal-setup-form");
    const reviewedNow = form && ["guideReviewed", "redLinesConfirmed", "recipientAgreed"].every((name) => form.elements[name]?.checked);
    const guide = form ? usableGuideById(form.dataset.guideId) : null;
    const currentRevision = Number(form?.dataset.consentRevision);
    if (!reviewedNow || !isRecipientAuthorized() || currentRevision !== state.recipientConsent.revision || !guide || guide.version !== Number(form.dataset.guideVersion)) { toast("当前授权或确认不完整，请重新检查本次安全门"); showRehearsalSetup(); return; }
    const confirmationId = addConfirmation({ type: "rehearsal", actorId: SOURCE_IDS.CAREGIVER, guideId: guide.id, consentRevision: state.recipientConsent.revision });
    const startedAt = Date.now();
    const activeOutcome = startOutcomeRecord({ stage: form.dataset.stage || "short-leave", duration: Number(form.dataset.rehearsalDuration) || 20, mode: "single-device", startedAt: new Date(startedAt).toISOString() });
    session = { stage: form.dataset.stage || "short-leave", duration: Number(form.dataset.rehearsalDuration) || 20, startedAt, tasks: [false, false, false], guideId: guide.id, guideVersion: guide.version, consentRevision: state.recipientConsent.revision, confirmationId, sessionRecordId: activeOutcome.id, pendingGapIds: [], urgentAlertsRaised: 0 };
    state.activeRehearsal = { ...session, tasks: [...session.tasks] };
    saveState(); closeModal(); currentPage = "rehearsal"; history.replaceState(null, "", "#rehearsal"); render(); toast("彩排已开始。本次三方确认已单独记录");
  }
  else if (action === "pause-session") session?.stage === "observe" ? showStageOneReview() : showDebrief();
  else if (action === "ask-question") showQuestionModal();
  else if (action === "match-question") {
    const value = $("#question-input")?.value || "";
    const matched = matchConfirmedGuide(value);
    const gap = !matched && value.trim() ? logGap(value) : null;
    $("#matched-result").innerHTML = !value.trim() ? `<div class="question-result"><p>请先描述发生了什么。</p></div>` : matched ? matchedGuideMarkup(matched) : noMatchMarkup(gap);
  }
  else if (action === "record-question") startSpeechInput();
  else if (action === "play-source") { toast("正在播放来源录音（演示）"); trigger.querySelector("span:first-child")?.classList.add("recording"); setTimeout(() => trigger.querySelector("span:first-child")?.classList.remove("recording"), 1500); }
  else if (action === "emergency" || action === "simulate-urgent") {
    if (session) { session.urgentAlertsRaised = (session.urgentAlertsRaised || 0) + 1; state.activeRehearsal = { ...session, tasks: [...session.tasks] }; saveState(); }
    if (restSession) { restSession.urgentAlertsRaised = (restSession.urgentAlertsRaised || 0) + 1; state.activeRest = { ...restSession }; saveState(); }
    showEmergency();
  }
  else if (action === "dismiss-emergency") { closeModal(); toast("红线事件已标记为收到"); }
  else if (action === "complete-stage-one") {
    const liveGuide = usableGuideById(session?.guideId);
    const sessionConfirmation = state.confirmations.find((item) => item.id === session?.confirmationId && item.status === "current");
    if (session?.stage !== "observe" || !session.tasks.every(Boolean) || !isRecipientAuthorized() || !liveGuide || !sessionConfirmation || session.consentRevision !== state.recipientConsent.revision || session.guideVersion !== liveGuide.version) {
      toast("在旁步骤、授权或指导已经变化，本次没有记为完成");
      return;
    }
    const date = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date());
    const outcomeId = session.sessionRecordId;
    finishOutcomeRecord(outcomeId, { status: "completed", tasks: session.tasks, pendingGaps: (session.pendingGapIds || []).map((id) => state.gaps.find((gap) => gap.id === id)).filter(Boolean), urgentAlertsRaised: session.urgentAlertsRaised || 0 });
    state.activity.unshift({ title: `在旁观察 · ${liveGuide.title}`, note: `应用记录：完成 ${session.tasks.filter(Boolean).length}/3 个现场步骤；参与者回答待分别保存`, date, score: "现场完成 · 待回看", stage: "observe", focus: liveGuide.title, guideId: liveGuide.id, guideDependency: guideDependencySnapshot(liveGuide), consentRevision: state.recipientConsent.revision, confirmationId: sessionConfirmation.id, sessionId: outcomeId });
    sessionConfirmation.status = "completed";
    state.activeRehearsal = null;
    closeModal(); session = null; saveState(); currentPage = "rehearsal"; render(); toast("现场事实已保存；完成双方回看前不会建议延长"); showOutcomeCheckIn(outcomeId, "caregiver");
  }
  else if (action === "retry-rehearsal") { const active = session; const wasObserve = active?.stage === "observe"; const record = state.confirmations.find((item) => item.id === active?.confirmationId); if (record?.status === "current") record.status = "superseded"; const outcomeId = active?.sessionRecordId; finishOutcomeRecord(outcomeId, { status: "interrupted", tasks: active?.tasks || [], pendingGaps: (active?.pendingGapIds || []).map((id) => state.gaps.find((gap) => gap.id === id)).filter(Boolean), urgentAlertsRaised: active?.urgentAlertsRaised || 0 }); closeModal(); session = null; state.activeRehearsal = null; saveState(); render(); toast(wasObserve ? "已记录为中途结束，没有按完成计算" : "已记录为中途结束，建议不会自动前进"); if (outcomeId) showOutcomeCheckIn(outcomeId, "caregiver"); }
  else if (action === "complete-rehearsal") {
    const gap = $("#debrief-one")?.value.trim();
    const instruction = $("#debrief-two")?.value.trim();
    if (!gap || !instruction) { toast("请先写下薄弱情境和确认过的处理方式"); return; }
    const liveGuide = usableGuideById(session?.guideId);
    const sessionConfirmation = state.confirmations.find((item) => item.id === session?.confirmationId && item.status === "current");
    if (!isRecipientAuthorized() || !liveGuide || !sessionConfirmation || session?.consentRevision !== state.recipientConsent.revision || session?.guideVersion !== liveGuide.version) { finishOutcomeRecord(session?.sessionRecordId, { status: "revoked", tasks: session?.tasks || [], pendingGaps: (session?.pendingGapIds || []).map((id) => state.gaps.find((gap) => gap.id === id)).filter(Boolean) }); closeModal(); session = null; state.activeRehearsal = null; saveState(); render(); toast("授权或指导已经变化，本次已记录为授权撤回"); return; }
    if (SafetyPolicy.classifyFields([gap, instruction]).highRisk) { toast("医疗或高风险内容不能由家庭复盘直接转成指导，请先联系并取得专业指示"); return; }
    const outcomeId = session.sessionRecordId;
    const completionStatus = session.tasks.every(Boolean) ? "completed" : "interrupted";
    finishOutcomeRecord(outcomeId, { status: completionStatus, tasks: session.tasks, pendingGaps: (session.pendingGapIds || []).map((id) => state.gaps.find((gap) => gap.id === id)).filter(Boolean), urgentAlertsRaised: session.urgentAlertsRaised || 0 });
    state.activity.unshift({ title: `短时离开 · ${liveGuide.title}`, note: `应用记录：${OutcomeModel.STATUS_LABELS[completionStatus]}；来源复盘新增“${gap}”`, date: new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date()), score: "待双方回看", stage: "short-leave", focus: liveGuide.title, guideId: liveGuide.id, guideDependency: guideDependencySnapshot(liveGuide), consentRevision: state.recipientConsent.revision, sessionId: outcomeId });
    state.debriefs.unshift({ gap, instruction, provenance: { actorId: SOURCE_IDS.CAREGIVER, actorType: "caregiver", labelAtConfirmation: state.family.caregiverName }, createdAt: Date.now() });
    const existing = usableGuides().find((guide) => guide.title === gap);
    const source = sourceDefinition(SOURCE_IDS.CAREGIVER);
    const confirmationId = addConfirmation({ type: "guide", actorId: SOURCE_IDS.CAREGIVER, guideId: existing?.id || null });
    if (existing) {
      const prior = state.confirmations.find((item) => item.id === existing.confirmationId);
      if (prior) prior.status = "superseded";
      existing.summary = instruction; existing.updated = "刚刚由复盘确认"; existing.source = source.label; existing.sourceAvatar = source.avatar; existing.sourceClass = source.className; existing.version += 1; existing.confirmationId = confirmationId; existing.provenance = { actorId: SOURCE_IDS.CAREGIVER, actorType: source.actorType, labelAtConfirmation: source.label }; existing.status = "usable"; existing.level = "here"; existing.rule = "现场可处理"; existing.category = "daily"; existing.highRisk = false; existing.policyVersion = SafetyPolicy.VERSION;
    } else {
      const guideId = `debrief-${Date.now()}`;
      state.confirmations.find((item) => item.id === confirmationId).guideId = guideId;
      state.guides.unshift({ id: guideId, version: 1, status: "usable", confirmationId, provenance: { actorId: SOURCE_IDS.CAREGIVER, actorType: source.actorType, labelAtConfirmation: source.label }, icon: "i-spark", tone: "mint", category: "daily", title: gap, summary: instruction, source: source.label, sourceAvatar: source.avatar, sourceClass: source.className, updated: "刚刚由复盘确认", level: "here", rule: "现场可处理", audio: false, highRisk: false, policyVersion: SafetyPolicy.VERSION, fromDebrief: true });
    }
    sessionConfirmation.status = "completed";
    state.activeRehearsal = null;
    saveState(); closeModal(); session = null; render(); toast("现场与来源事实已保存；阶段要等双方明确选择"); showOutcomeCheckIn(outcomeId, "caregiver");
  }
  else if (action === "start-rest") showRestSetup();
  else if (action === "confirm-rest") {
    const form = $("#rest-setup-form");
    const currentGuides = usableGuides();
    if (!form?.elements.handoffConfirmed?.checked || Number(form.dataset.consentRevision) !== state.recipientConsent.revision || !isRecipientAuthorized() || !currentGuides.length || (state.mode === "real" && !state.rehearsalCompleted)) { toast("当前授权、阶段或接班确认不完整，无法开启离班"); showRestSetup(); return; }
    const durationValue = Number(trigger.dataset.durationValue || state.family.restGoal.duration || 60);
    const confirmationId = addConfirmation({ type: "offDuty", actorId: SOURCE_IDS.CAREGIVER, consentRevision: state.recipientConsent.revision });
    const startedAt = Date.now();
    const activeOutcome = startOutcomeRecord({ stage: "quiet-handoff", duration: durationValue, mode: "single-device", startedAt: new Date(startedAt).toISOString() });
    restSession = { startedAt, duration: durationValue, queued: 0, consentRevision: state.recipientConsent.revision, confirmationId, guideVersions: currentGuides.map((guide) => ({ id: guide.id, version: guide.version })), sessionRecordId: activeOutcome.id, urgentAlertsRaised: 0 };
    state.activeRest = { ...restSession }; saveState(); closeModal(); currentPage = "rest"; history.replaceState(null, "", "#rest"); render(); toast("通知防火墙已开启，本次确认已记录");
  }
  else if (action === "simulate-normal") { if (!restSession) return; restSession.queued += 1; state.activeRest = { ...restSession }; saveState(); const count = $("#quiet-count"); if (count) count.textContent = restSession.queued; toast("普通询问已收进安静收件箱，没有触发响铃"); }
  else if (action === "end-rest") showRestSummary();
  else if (action === "finish-rest-summary") { const active = restSession; const record = state.confirmations.find((item) => item.id === active?.confirmationId); if (record?.status === "current") record.status = "completed"; const outcomeId = active?.sessionRecordId; finishOutcomeRecord(outcomeId, { status: "completed", tasks: [true], routineUpdatesQueued: active?.queued || 0, urgentAlertsRaised: active?.urgentAlertsRaised || 0 }); closeModal(); restSession = null; state.activeRest = null; saveState(); render(); toast("离班现场事实已保存；接下来分别回看"); if (outcomeId) showOutcomeCheckIn(outcomeId, "caregiver"); }
  else if (action === "rest-preview") { toast("照护者只看到休息倒计时和安静收件箱数量"); }
  else if (action === "edit-rest") showRestGoalForm();
  else if (action === "withdraw-recipient") showRecipientConfirm("withdraw");
  else if (action === "remove-recipient") showRecipientConfirm("remove");
  else if (action === "confirm-recipient-control") {
    const remove = trigger.dataset.mode === "remove";
    const pendingRemoteRevocation = executeCompanionRevocation(queueCompanionRevocation(), { retries: 3, announce: false });
    revokeRecipientAuthorization({ remove });
    // Local withdrawal is the immediate safety boundary. Hide revoked content
    // before waiting for any live-room request, which may be slow or offline.
    closeModal();
    render();
    toast(remove ? "被照护者已移除，本人内容已撤销，进行中的接班已结束" : "本人参与和内容已撤回，进行中的接班已安全结束");
    const remoteRevoked = await pendingRemoteRevocation;
    if (!remoteRevoked) toast("本机撤回已生效；双机房间撤销会在连接恢复后自动重试");
  }
  else if (action === "how-it-works") { openModal(`${modalHead("HOW IT WORKS", "彩排不是模拟题，是真实的小接班")}<div class="modal-body"><div class="detail-list"><div class="detail-row"><span>1</span><span><b>选择一个低风险生活片段</b><small>例如一段陪伴或一起整理物品</small></span></div><div class="detail-row"><span>2</span><span><b>主要照护者一点点退远</b><small>在旁、短时离开、安静离班</small></span></div><div class="detail-row"><span>3</span><span><b>只复盘仍不放心的一步</b><small>现场答案变成下次可用的确认指导</small></span></div></div></div><footer class="modal-footer"><button class="btn btn-primary" data-action="close-modal">明白了</button></footer>`); }
  else if (action === "reset-demo") showDataResetConfirm();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("#modal-root").children.length) closeModal();
  if (event.key === "Tab" && $("#modal-root").children.length) {
    const dialog = $("#modal-root [role='dialog'], #modal-root [role='alertdialog']");
    const focusable = dialog ? $$("button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])", dialog).filter((item) => !item.hidden && item.getClientRects().length) : [];
    if (focusable.length) {
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }
  const card = event.target.closest?.("[role='button'][data-action='guide-detail']");
  if (card && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); showGuideDetail(card.dataset.id); }
});

function startSpeechInput() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const button = $("#record-question");
  const status = $("#speech-status");
  if (!SpeechRecognition) { status.textContent = "此浏览器未开放语音识别，可直接在上方输入。"; toast("可直接输入问题，匹配方式相同"); return; }
  const recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = false;
  button.classList.add("recording");
  status.textContent = "正在听…说完后会自动填入。";
  recognition.onresult = (event) => { $("#question-input").value = event.results[0][0].transcript; };
  recognition.onerror = () => { status.textContent = "没有听清，可以直接修改文字。"; };
  recognition.onend = () => { button.classList.remove("recording"); status.textContent = "语音输入结束，你可以先确认文字。"; };
  recognition.start();
}

function startSpeechForInput(inputId, statusId, button) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const input = document.getElementById(inputId);
  const status = document.getElementById(statusId);
  if (!SpeechRecognition) { if (status) status.textContent = "此浏览器未开放语音识别，可继续直接输入。"; toast("可直接输入并在保存前核对文字"); return; }
  const recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = false;
  button?.classList.add("recording");
  if (status) status.textContent = "正在听…说完后会填入，请核对文字。";
  recognition.onresult = (event) => { if (input) input.value = event.results[0][0].transcript; };
  recognition.onerror = () => { if (status) status.textContent = "没有听清，可直接输入或再试一次。"; };
  recognition.onend = () => { button?.classList.remove("recording"); if (status) status.textContent = "语音输入结束，请核对文字后再保存。"; };
  recognition.start();
}

window.addEventListener("hashchange", () => {
  if (session) {
    const record = state.confirmations.find((item) => item.id === session.confirmationId);
    if (record?.status === "current") record.status = "superseded";
    state.activeRehearsal = null;
    saveState();
  }
  session = null; restSession = state.activeRest ? { ...state.activeRest } : null; currentPage = restSession ? "rest" : normalizePage(location.hash.slice(1)); render();
});

function applyPersistedState(rawValue, reason = "external") {
  try {
    const parsed = rawValue ? JSON.parse(rawValue) : null;
    const authority = resolveAuthorityRecord(state.recipientConsent);
    if (reason === "storage" && (!parsed || parsed.schemaVersion !== SCHEMA_VERSION) && state.schemaVersion === SCHEMA_VERSION) {
      state = applyAuthorityRecord(state, authority);
      saveState({ ignorePersisted: true });
      if (!isRecipientAuthorized()) { session = null; restSession = null; }
      closeModal();
      render();
      toast("已忽略旧页面写入；当前撤回与授权状态保持不变");
      return;
    }
    const migratedIncoming = parsed ? migrateState(parsed) : emptyState(null);
    const incomingActivityCount = migratedIncoming.activity.length;
    const next = applyAuthorityRecord(migratedIncoming, authority);
    const activityAuthorizationConflict = next.activity.length !== incomingActivityCount;
    const incomingAuthorityConflict = Boolean(parsed && (
      parsed.recipientConsent?.status !== authority.status ||
      Number(parsed.recipientConsent?.revision || 1) !== authority.revision ||
      parsed.family?.recipientConsented !== (authority.status === "granted" && Boolean(parsed.family?.recipientName)) ||
      (parsed.guides || []).some((guide) => guide?.provenance?.actorId === SOURCE_IDS.RECIPIENT && (authority.status !== "granted" || guide.provenance.consentRevision !== authority.revision)) ||
      (parsed.activeRest && parsed.activeRest.consentRevision !== authority.revision) ||
      activityAuthorizationConflict
    ));
    if (reason === "storage" && incomingAuthorityConflict) {
      state = applyAuthorityRecord(state, authority);
      saveState({ ignorePersisted: true });
      if (!isRecipientAuthorized()) { session = null; restSession = null; }
      closeModal();
      render();
      toast("已拒绝过期授权写入；当前撤回与内容保持不变");
      return;
    }
    const authorityChanged = next.recipientConsent.revision !== state.recipientConsent.revision || next.recipientConsent.status !== state.recipientConsent.status;
    const contentChanged = Number(next.meta?.updatedAt || 0) !== Number(state.meta?.updatedAt || 0);
    if (!authorityChanged && !contentChanged) return;
    state = next;
    if (incomingAuthorityConflict) saveState({ ignorePersisted: true });
    if (isRecipientAuthorized() && state.activeRehearsal && usableGuideById(state.activeRehearsal.guideId)) session = { ...state.activeRehearsal, tasks: [...(state.activeRehearsal.tasks || [false, false, false])] };
    else session = null;
    restSession = state.activeRest ? { ...state.activeRest } : null;
    currentPage = restSession ? "rest" : normalizePage(location.hash.slice(1));
    closeModal();
    render();
    if (authorityChanged) toast(isRecipientAuthorized() ? "本人授权已在另一页面更新；旧内容不会恢复" : "本人撤回已同步，当前接班和本人内容已停止");
    else if (reason === "storage") toast("家庭内容已从另一页面同步");
  } catch { /* Ignore malformed external writes and retain the last valid in-memory state. */ }
}

window.addEventListener("storage", (event) => {
  if (event.key === STORAGE_KEY) applyPersistedState(event.newValue, "storage");
  else if (event.key === AUTHORITY_KEY) applyPersistedState(localStorage.getItem(STORAGE_KEY), "authority");
});

window.addEventListener("pageshow", () => applyPersistedState(localStorage.getItem(STORAGE_KEY), "pageshow"));
window.addEventListener("online", () => {
  retryPendingCompanionRevocation();
  refreshCompanion();
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") applyPersistedState(localStorage.getItem(STORAGE_KEY), "visible");
});

if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  window.addEventListener("load", async () => {
    try {
      const hadController = Boolean(navigator.serviceWorker.controller);
      const registration = await navigator.serviceWorker.register("./sw.js?v=20260725-production-v2", { updateViaCache: "none" });
      await registration.update();
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (hadController && !sessionStorage.getItem("relay-sw-reloaded")) {
          sessionStorage.setItem("relay-sw-reloaded", "1");
          location.reload();
        }
      });
    } catch { /* The network-first app remains usable without offline installation. */ }
  });
}

render();
retryPendingCompanionRevocation();
if (companionSession) startCompanionPolling();
