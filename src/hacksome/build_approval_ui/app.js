"use strict";

const ui = {
  runId: document.querySelector("#run-id"),
  routeId: document.querySelector("#route-id"),
  catalogId: document.querySelector("#catalog-id"),
  approvalState: document.querySelector("#approval-state"),
  availableCount: document.querySelector("#available-count"),
  selectNext: document.querySelector("#select-next"),
  clearSelection: document.querySelector("#clear-selection"),
  ticketList: document.querySelector("#ticket-list"),
  emptyState: document.querySelector("#empty-state"),
  detailHash: document.querySelector("#detail-hash"),
  detailProvenance: document.querySelector("#detail-provenance"),
  cardDetail: document.querySelector("#card-detail"),
  activeSlots: document.querySelector("#active-slots"),
  queueCount: document.querySelector("#queue-count"),
  launchQueue: document.querySelector("#launch-queue"),
  retryHandoffs: document.querySelector("#retry-handoffs"),
  selectedCount: document.querySelector("#selected-count"),
  launchEstimate: document.querySelector("#launch-estimate"),
  batchWarning: document.querySelector("#batch-warning"),
  closeApproval: document.querySelector("#close-approval"),
  approveBatch: document.querySelector("#approve-batch"),
  approveDialog: document.querySelector("#approve-dialog"),
  approveSummary: document.querySelector("#approve-summary"),
  approveList: document.querySelector("#approve-list"),
  confirmApprove: document.querySelector("#confirm-approve"),
  closeDialog: document.querySelector("#close-dialog"),
  confirmClose: document.querySelector("#confirm-close"),
  liveRegion: document.querySelector("#live-region"),
};

const state = {
  snapshot: null,
  selected: new Set(),
  detailOrdinal: null,
  lastFocus: null,
  busy: false,
  refreshing: false,
};

function announce(message) {
  ui.liveRegion.textContent = "";
  window.requestAnimationFrame(() => {
    ui.liveRegion.textContent = message;
  });
}

function shortHash(value) {
  return typeof value === "string" ? `${value.slice(0, 10)}…${value.slice(-6)}` : "—";
}

function requestId(prefix) {
  const value = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${value}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
    headers: options.body ? { "Content-Type": "application/json; charset=utf-8" } : undefined,
  });
  const payload = await response.json().catch(() => ({ code: "invalid_response", message: "The server returned invalid JSON." }));
  if (!response.ok) {
    const error = new Error(payload.message || "The request failed.");
    error.code = payload.code || "request_failed";
    throw error;
  }
  return payload;
}

function selectedCards() {
  if (!state.snapshot) return [];
  return state.snapshot.cards.filter((card) => state.selected.has(card.card_id));
}

function launchCounts() {
  if (!state.snapshot) return { immediate: 0, queued: 0 };
  const occupying = state.snapshot.cards.filter((card) => ["starting", "active"].includes(card.status)).length;
  const capacity = Math.max(0, state.snapshot.max_active_teams - occupying);
  const selected = state.selected.size;
  const immediate = Math.min(selected, capacity);
  return { immediate, queued: selected - immediate };
}

function node(tag, className, text) {
  const value = document.createElement(tag);
  if (className) value.className = className;
  if (text !== undefined) value.textContent = text;
  return value;
}

function renderTickets() {
  const snapshot = state.snapshot;
  const fragment = document.createDocumentFragment();
  const available = snapshot.cards.filter((card) => card.status === "available");
  ui.availableCount.textContent = `${available.length} ready`;
  ui.emptyState.hidden = snapshot.cards.length !== 0;
  ui.ticketList.hidden = snapshot.cards.length === 0;

  snapshot.cards.forEach((card) => {
    const item = node("li", "ticket");
    item.dataset.status = card.status;
    item.dataset.selected = String(state.selected.has(card.card_id));

    item.append(node("span", "ticket-number", String(card.ordinal + 1).padStart(2, "0")));
    const inspect = node("button", "ticket-body");
    inspect.type = "button";
    inspect.append(node("span", "ticket-title", card.title));
    inspect.append(node("span", "ticket-meta", `${snapshot.route_id.toUpperCase()} · ${shortHash(card.card_sha256)}`));
    inspect.append(node("span", "status-word", card.status.replace("_", " ")));
    if (card.team_id) inspect.append(node("span", "ticket-team", card.team_id));
    if (card.error) {
      inspect.append(node("span", "ticket-error", `${card.error.code}: ${card.error.message}`));
    }
    inspect.addEventListener("click", () => loadDetail(card.ordinal));
    item.append(inspect);

    const checkWrap = node("label", "ticket-check");
    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = state.selected.has(card.card_id);
    check.disabled = card.status !== "available" || snapshot.approval_status === "closed" || Boolean(snapshot.source_integrity_error);
    check.setAttribute("aria-label", `Select ${card.title} for this Build batch`);
    check.addEventListener("change", () => toggleCard(card, check.checked));
    checkWrap.append(check);
    item.append(checkWrap);
    fragment.append(item);
  });
  ui.ticketList.replaceChildren(fragment);
  ui.ticketList.setAttribute("aria-busy", "false");
}

function renderRail() {
  const snapshot = state.snapshot;
  const running = snapshot.cards.filter((card) => ["starting", "active"].includes(card.status));
  const slots = document.createDocumentFragment();
  for (let index = 0; index < snapshot.max_active_teams; index += 1) {
    const slot = node("div", "rail-slot");
    slot.dataset.slot = `S${index + 1}`;
    const card = running[index];
    slot.dataset.filled = String(Boolean(card));
    slot.append(node("strong", "", card ? card.title : "Slot available"));
    slot.append(node("span", "", card ? `${card.status.toUpperCase()} · ${card.team_id || "handoff pending"}` : "Next FIFO Team starts here"));
    slots.append(slot);
  }
  ui.activeSlots.replaceChildren(slots);

  const queued = snapshot.cards
    .filter((card) => card.status === "queued")
    .sort((left, right) => (left.queue_position || 0) - (right.queue_position || 0));
  ui.queueCount.textContent = String(queued.length);
  const queue = document.createDocumentFragment();
  queued.forEach((card) => {
    const item = node("li", "queue-ticket");
    item.append(node("b", "", String(card.queue_position || "—").padStart(2, "0")));
    const body = node("div");
    body.append(node("strong", "", card.title));
    body.append(node("span", "", card.team_id || "Team identity pending"));
    item.append(body);
    queue.append(item);
  });
  ui.launchQueue.replaceChildren(queue);
}

function renderTray() {
  const snapshot = state.snapshot;
  const count = state.selected.size;
  const counts = launchCounts();
  ui.selectedCount.textContent = `${count} selected`;
  ui.launchEstimate.textContent = `${counts.immediate} start now · ${counts.queued} queue`;
  ui.approveBatch.textContent = `Approve ${count} and start Build`;
  ui.approveBatch.disabled = count < 1 || state.busy || snapshot.approval_status === "closed" || Boolean(snapshot.source_integrity_error);
  ui.selectNext.disabled = snapshot.approval_status === "closed" || Boolean(snapshot.source_integrity_error);
  ui.clearSelection.disabled = count === 0;
  ui.closeApproval.disabled = snapshot.approval_status === "closed" || state.busy || Boolean(snapshot.source_integrity_error);
  ui.retryHandoffs.disabled = state.busy;
}

function renderHeader() {
  const snapshot = state.snapshot;
  ui.runId.textContent = snapshot.run_id;
  ui.routeId.textContent = `${snapshot.route_id}/${snapshot.route_contract_version}`;
  ui.catalogId.textContent = shortHash(snapshot.catalog_sha256);
  ui.approvalState.textContent = snapshot.source_integrity_error ? "SOURCE ERROR" : snapshot.approval_status.toUpperCase();
  ui.batchWarning.textContent = snapshot.source_integrity_error || "";
}

function render() {
  if (!state.snapshot) return;
  for (const cardId of [...state.selected]) {
    const card = state.snapshot.cards.find((candidate) => candidate.card_id === cardId);
    if (!card || card.status !== "available") state.selected.delete(cardId);
  }
  renderHeader();
  renderTickets();
  renderRail();
  renderTray();
}

function toggleCard(card, checked) {
  ui.batchWarning.textContent = "";
  if (checked) {
    if (state.selected.size >= 10) {
      ui.batchWarning.textContent = "Each batch can contain at most 10 Cards.";
      announce("Batch limit reached. Clear a Card before selecting another.");
      renderTickets();
      return;
    }
    state.selected.add(card.card_id);
  } else {
    state.selected.delete(card.card_id);
  }
  render();
}

async function loadDetail(ordinal) {
  try {
    const detail = await api(`/api/cards/${ordinal}`);
    state.detailOrdinal = ordinal;
    ui.detailHash.textContent = shortHash(detail.card_sha256);
    ui.detailProvenance.textContent = `${state.snapshot.route_id}/${state.snapshot.route_contract_version} · ${detail.source_artifact_ref.artifact_type} · ${detail.card_id}`;
    ui.cardDetail.textContent = detail.card_markdown;
  } catch (error) {
    announce(error.message);
  }
}

async function refresh({ quiet = false } = {}) {
  if (state.refreshing) return;
  state.refreshing = true;
  try {
    state.snapshot = await api("/api/snapshot");
    render();
    if (state.detailOrdinal === null && state.snapshot.cards.length) {
      await loadDetail(state.snapshot.cards[0].ordinal);
    } else if (state.detailOrdinal !== null && state.detailOrdinal < state.snapshot.cards.length) {
      await loadDetail(state.detailOrdinal);
    }
  } catch (error) {
    if (!quiet) announce(error.message);
  } finally {
    state.refreshing = false;
  }
}

function pendingAuthorizePayload() {
  const cards = selectedCards().map((card) => ({ card_id: card.card_id, card_sha256: card.card_sha256 }));
  const signature = JSON.stringify({ catalog: state.snapshot.catalog_sha256, cards });
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem("hacksome-build-pending") || "null");
  } catch {
    localStorage.removeItem("hacksome-build-pending");
  }
  if (saved && saved.signature === signature) return saved.payload;
  const payload = {
    schema_version: 1,
    request_id: requestId("authorize"),
    catalog_sha256: state.snapshot.catalog_sha256,
    cards,
  };
  localStorage.setItem("hacksome-build-pending", JSON.stringify({ signature, payload }));
  return payload;
}

function showApproveDialog() {
  const cards = selectedCards();
  const counts = launchCounts();
  ui.approveSummary.textContent = `${cards.length} isolated Teams will be authorized: ${counts.immediate} can start now and ${counts.queued} will enter the FIFO queue.`;
  const list = document.createDocumentFragment();
  cards.forEach((card) => list.append(node("li", "", card.title)));
  ui.approveList.replaceChildren(list);
  state.lastFocus = document.activeElement;
  ui.approveDialog.returnValue = "";
  ui.approveDialog.showModal();
}

async function authorizeBatch() {
  state.busy = true;
  renderTray();
  const payload = pendingAuthorizePayload();
  try {
    const result = await api("/api/authorize", { method: "POST", body: JSON.stringify(payload) });
    localStorage.removeItem("hacksome-build-pending");
    state.selected.clear();
    announce(`Build batch ${result.batch_id} was authorized.`);
    await refresh();
  } catch (error) {
    announce(`${error.code}: ${error.message}`);
    await refresh({ quiet: true });
  } finally {
    state.busy = false;
    renderTray();
  }
}

function closePayload() {
  const key = `hacksome-build-close-${state.snapshot.catalog_sha256}`;
  let request = localStorage.getItem(key);
  if (!request) {
    request = requestId("close");
    localStorage.setItem(key, request);
  }
  return { schema_version: 1, request_id: request, catalog_sha256: state.snapshot.catalog_sha256 };
}

async function closeApproval() {
  state.busy = true;
  renderTray();
  try {
    await api("/api/close", { method: "POST", body: JSON.stringify(closePayload()) });
    state.selected.clear();
    announce("Approval closed. Existing Teams continue.");
    await refresh();
  } catch (error) {
    announce(`${error.code}: ${error.message}`);
  } finally {
    state.busy = false;
    renderTray();
  }
}

ui.selectNext.addEventListener("click", () => {
  if (!state.snapshot) return;
  const available = state.snapshot.cards.filter((card) => card.status === "available");
  state.selected.clear();
  available.slice(0, 10).forEach((card) => state.selected.add(card.card_id));
  ui.batchWarning.textContent = available.length > 10 ? "Selected the next 10 available Cards; approve another batch for the rest." : "";
  render();
});

ui.clearSelection.addEventListener("click", () => {
  if (!state.snapshot) return;
  state.selected.clear();
  ui.batchWarning.textContent = "";
  render();
});

ui.approveBatch.addEventListener("click", () => {
  if (state.snapshot) showApproveDialog();
});
ui.approveDialog.addEventListener("close", () => {
  if (ui.approveDialog.returnValue === "confirm") authorizeBatch();
  if (state.lastFocus instanceof HTMLElement) state.lastFocus.focus();
});

ui.closeApproval.addEventListener("click", () => {
  if (!state.snapshot) return;
  state.lastFocus = document.activeElement;
  ui.closeDialog.returnValue = "";
  ui.closeDialog.showModal();
});
ui.closeDialog.addEventListener("close", () => {
  if (ui.closeDialog.returnValue === "confirm") closeApproval();
  if (state.lastFocus instanceof HTMLElement) state.lastFocus.focus();
});

ui.retryHandoffs.addEventListener("click", async () => {
  if (!state.snapshot) return;
  state.busy = true;
  renderTray();
  try {
    await api("/api/reconcile", { method: "POST", body: "{}" });
    announce("Pending handoffs were reconciled.");
    await refresh();
  } catch (error) {
    announce(`${error.code}: ${error.message}`);
  } finally {
    state.busy = false;
    renderTray();
  }
});

refresh();
window.setInterval(() => refresh({ quiet: true }), 2000);
