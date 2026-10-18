/**
 * MemoryMate AI — Chat & Grounding Evidence Controller (js/chat.js)
 *
 * Manages:
 *   - Visible conversation state (never stored as authoritative memory in localStorage)
 *   - POST /chat submission, duplicate-send prevention, and loading indicator
 *   - Safe text rendering (textContent only) for user and assistant messages
 *   - "Memories used for this answer" evidence panel and confirmed memory_operations counts
 *   - New conversation reset action
 */
(function (global) {
  "use strict";

  const API = global.MemoryMateAPI;

  const state = {
    conversationId: null,
    turns: [], // { id, turnNumber, userMessage, answer, memoriesUsed, memoryOperations, timestamp }
    selectedTurnId: null,
    isPending: false,
    callbacks: {
      onTurnCompleted: null,
      onLocateMemory: null,
      onDependencyError: null,
    },
  };

  const els = {};

  function cacheElements() {
    els.convBadge = document.getElementById("conversation-id-badge");
    els.errorBanner = document.getElementById("chat-error-banner");
    els.errorTitle = document.getElementById("chat-error-title");
    els.errorCode = document.getElementById("chat-error-code");
    els.errorMessage = document.getElementById("chat-error-message");
    els.errorMeta = document.getElementById("chat-error-meta");
    els.dismissErrorBtn = document.getElementById("dismiss-chat-error-btn");

    els.chatStream = document.getElementById("chat-messages");
    els.emptyState = document.getElementById("chat-empty-state");
    els.welcomeTitle = document.getElementById("chat-welcome-title");
    els.messagesList = document.getElementById("messages-list");
    els.loadingIndicator = document.getElementById("chat-loading");

    els.form = document.getElementById("chat-form");
    els.input = document.getElementById("chat-input");
    els.sendBtn = document.getElementById("chat-send-btn");
    els.sendBtnText = document.getElementById("chat-send-btn-text");
    els.charCounter = document.getElementById("chat-char-counter");
    els.newConvBtn = document.getElementById("new-conversation-btn");

    // Evidence Panel ("Memories used for this answer")
    els.evidenceCountBadge = document.getElementById("evidence-count-badge");
    els.mobileEvidenceCount = document.getElementById("mobile-evidence-count");
    els.evidenceTurnLabel = document.getElementById("evidence-turn-label");
    els.evidenceOpsBar = document.getElementById("evidence-ops-bar");
    els.opCreatedPill = document.getElementById("op-created-pill");
    els.opCreatedCount = document.getElementById("op-created-count");
    els.opUpdatedPill = document.getElementById("op-updated-pill");
    els.opUpdatedCount = document.getElementById("op-updated-count");
    els.opSupersededPill = document.getElementById("op-superseded-pill");
    els.opSupersededCount = document.getElementById("op-superseded-count");

    els.evidenceInitialEmpty = document.getElementById("evidence-initial-empty");
    els.evidenceZeroEmpty = document.getElementById("evidence-zero-empty");
    els.evidenceList = document.getElementById("evidence-list");
  }

  function formatTimestamp(isoString) {
    if (!isoString) return "";
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) {
      return String(isoString);
    }
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatDateTimeShort(isoString) {
    if (!isoString) return "";
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) {
      return String(isoString);
    }
    return date.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function safeCategory(rawType) {
    const val = String(rawType || "other").toLowerCase().trim();
    return API.CATEGORIES.includes(val) ? val : "other";
  }

  function updateComposerState() {
    if (!els.input || !els.sendBtn || !els.charCounter) return;
    const raw = els.input.value || "";
    const length = raw.length;
    const trimmedLength = raw.trim().length;
    const maxChars = API.MAX_MESSAGE_CHARS;

    els.charCounter.textContent = `${length.toLocaleString()} / ${maxChars.toLocaleString()}`;
    const isOverLimit = length > maxChars;
    els.charCounter.classList.toggle("is-over-limit", isOverLimit);

    els.sendBtn.disabled = state.isPending || trimmedLength === 0 || isOverLimit;
    els.sendBtnText.textContent = state.isPending ? "Sending…" : "Send Message";
  }

  function autoResizeTextarea() {
    if (!els.input) return;
    els.input.style.height = "auto";
    const nextHeight = Math.min(160, Math.max(52, els.input.scrollHeight));
    els.input.style.height = `${nextHeight}px`;
  }

  function clearError() {
    if (!els.errorBanner) return;
    els.errorBanner.hidden = true;
    els.errorTitle.textContent = "";
    els.errorCode.textContent = "";
    els.errorMessage.textContent = "";
    els.errorMeta.textContent = "";
    els.errorMeta.hidden = true;
  }

  function showError(err, { partialOps = null } = {}) {
    if (!els.errorBanner) return;
    const isApiErr = err instanceof API.ApiError;
    els.errorTitle.textContent =
      isApiErr && err.status === 503
        ? "Backend service unavailable"
        : isApiErr && err.status === 403
          ? "User identity not permitted"
          : "Message request failed";

    els.errorCode.textContent = isApiErr && err.code ? err.code : "error";
    els.errorMessage.textContent = API.formatErrorMessage(err);

    if (partialOps && typeof partialOps === "object") {
      const c = Number(partialOps.created) || 0;
      const u = Number(partialOps.updated) || 0;
      const s = Number(partialOps.superseded) || 0;
      if (c + u + s > 0) {
        els.errorMeta.textContent = `Note: Before answer generation failed, the backend confirmed memory operations (created: ${c}, updated: ${u}, superseded: ${s}).`;
      } else {
        els.errorMeta.textContent =
          "Backend confirmed 0 memory changes were persisted before the error occurred.";
      }
      els.errorMeta.hidden = false;
    } else {
      els.errorMeta.textContent =
        "No memories from this message were confirmed saved by the backend.";
      els.errorMeta.hidden = false;
    }

    els.errorBanner.hidden = false;
  }

  function updateConversationBadge() {
    if (!els.convBadge) return;
    if (state.conversationId) {
      els.convBadge.textContent = state.conversationId;
      els.convBadge.title = `Active conversation ID: ${state.conversationId}`;
    } else {
      els.convBadge.textContent = "New session (no ID yet)";
      els.convBadge.title = "A conversation_id will be assigned by the backend on your first message";
    }
  }

  function formatOperationsSummaryText(ops) {
    if (!ops) return "0 memory changes";
    const parts = [];
    const created = Number(ops.created) || 0;
    const updated = Number(ops.updated) || 0;
    const superseded = Number(ops.superseded) || 0;

    if (created > 0) parts.push(`${created} saved`);
    if (updated > 0) parts.push(`${updated} updated`);
    if (superseded > 0) parts.push(`${superseded} superseded`);

    return parts.length > 0 ? `Confirmed: ${parts.join(", ")}` : "0 memory changes";
  }

  function hasAnyMemoryOperation(ops) {
    if (!ops) return false;
    return (
      (Number(ops.created) || 0) > 0 ||
      (Number(ops.updated) || 0) > 0 ||
      (Number(ops.superseded) || 0) > 0
    );
  }

  /**
   * Create a user message DOM node safely using textContent.
   */
  function buildUserMessageNode( { userMessage, timestamp } ) {
    const row = document.createElement("article");
    row.className = "message-row role-user";

    const meta = document.createElement("div");
    meta.className = "message-meta";

    const author = document.createElement("span");
    author.className = "message-author";
    author.textContent = "You";

    const timeEl = document.createElement("time");
    timeEl.dateTime = timestamp;
    timeEl.textContent = formatTimestamp(timestamp);

    meta.appendChild(author);
    meta.appendChild(timeEl);

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = userMessage;

    row.appendChild(meta);
    row.appendChild(bubble);
    return row;
  }

  /**
   * Create an assistant message DOM node safely using textContent, including
   * confirmed memory_operations and evidence inspection button.
   */
  function buildAssistantMessageNode(turn) {
    const row = document.createElement("article");
    row.className = "message-row role-assistant";
    row.dataset.turnId = turn.id;

    const meta = document.createElement("div");
    meta.className = "message-meta";

    const author = document.createElement("span");
    author.className = "message-author";
    author.textContent = "MemoryMate AI";

    const timeEl = document.createElement("time");
    timeEl.dateTime = turn.timestamp;
    timeEl.textContent = formatTimestamp(turn.timestamp);

    meta.appendChild(author);
    meta.appendChild(timeEl);

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = turn.answer;

    const footer = document.createElement("div");
    footer.className = "assistant-turn-footer";

    // Confirmed backend memory operations badge
    const opsBadge = document.createElement("span");
    const changed = hasAnyMemoryOperation(turn.memoryOperations);
    opsBadge.className = changed ? "turn-ops-badge" : "turn-ops-badge ops-none";
    opsBadge.textContent = formatOperationsSummaryText(turn.memoryOperations);
    footer.appendChild(opsBadge);

    // Evidence inspection trigger button
    const usedCount = Array.isArray(turn.memoriesUsed) ? turn.memoriesUsed.length : 0;
    const evidenceBtn = document.createElement("button");
    evidenceBtn.type = "button";
    evidenceBtn.className =
      "turn-evidence-btn" + (state.selectedTurnId === turn.id ? " is-selected" : "");
    evidenceBtn.dataset.selectTurnId = turn.id;
    evidenceBtn.textContent =
      usedCount === 1
        ? "1 memory used for this answer"
        : `${usedCount} memories used for this answer`;
    evidenceBtn.addEventListener("click", () => {
      selectTurnForEvidence(turn.id, { switchMobilePane: true });
    });

    footer.appendChild(evidenceBtn);

    row.appendChild(meta);
    row.appendChild(bubble);
    row.appendChild(footer);
    return row;
  }

  function syncTurnSelectionButtons() {
    if (!els.messagesList) return;
    const buttons = els.messagesList.querySelectorAll(".turn-evidence-btn");
    buttons.forEach((btn) => {
      const isSelected = btn.dataset.selectTurnId === state.selectedTurnId;
      btn.classList.toggle("is-selected", isSelected);
      btn.setAttribute("aria-pressed", isSelected ? "true" : "false");
    });
  }

  /**
   * Render the "Memories used for this answer" evidence panel for the selected turn.
   */
  function renderEvidencePanel() {
    if (!els.evidenceList) return;

    const activeTurn = state.turns.find((t) => t.id === state.selectedTurnId) || null;
    if (!activeTurn) {
      els.evidenceCountBadge.textContent = "0";
      if (els.mobileEvidenceCount) els.mobileEvidenceCount.textContent = "0";
      els.evidenceTurnLabel.textContent = "No answer yet";
      els.evidenceOpsBar.hidden = true;
      els.evidenceInitialEmpty.hidden = false;
      els.evidenceZeroEmpty.hidden = true;
      els.evidenceList.hidden = true;
      els.evidenceList.replaceChildren();
      return;
    }

    const memoriesUsed = Array.isArray(activeTurn.memoriesUsed) ? activeTurn.memoriesUsed : [];
    const ops = activeTurn.memoryOperations || { created: 0, updated: 0, superseded: 0 };

    els.evidenceCountBadge.textContent = String(memoriesUsed.length);
    if (els.mobileEvidenceCount) els.mobileEvidenceCount.textContent = String(memoriesUsed.length);
    els.evidenceTurnLabel.textContent = `Turn #${activeTurn.turnNumber} (${formatTimestamp(activeTurn.timestamp)})`;

    // Populate operation counts
    const c = Number(ops.created) || 0;
    const u = Number(ops.updated) || 0;
    const s = Number(ops.superseded) || 0;
    els.opCreatedCount.textContent = String(c);
    els.opUpdatedCount.textContent = String(u);
    els.opSupersededCount.textContent = String(s);
    els.opCreatedPill.classList.toggle("has-change", c > 0);
    els.opUpdatedPill.classList.toggle("has-change", u > 0);
    els.opSupersededPill.classList.toggle("has-change", s > 0);
    els.evidenceOpsBar.hidden = false;

    els.evidenceInitialEmpty.hidden = true;

    if (memoriesUsed.length === 0) {
      els.evidenceZeroEmpty.hidden = false;
      els.evidenceList.hidden = true;
      els.evidenceList.replaceChildren();
      return;
    }

    els.evidenceZeroEmpty.hidden = true;
    els.evidenceList.hidden = false;

    const fragment = document.createDocumentFragment();
    memoriesUsed.forEach((mem) => {
      const card = document.createElement("div");
      card.className = "evidence-card";
      card.setAttribute("role", "listitem");
      card.dataset.memoryId = mem.memory_id || "";

      const topRow = document.createElement("div");
      topRow.className = "card-top-row";

      const subjectGroup = document.createElement("div");
      subjectGroup.className = "card-subject-group";

      // In POST /chat -> memories_used, the category field is named `type`
      const category = safeCategory(mem.type || mem.category);
      const badge = document.createElement("span");
      badge.className = `cat-badge cat-${category}`;
      badge.textContent = category;

      const subject = document.createElement("span");
      subject.className = "card-subject";
      subject.textContent = mem.subject || "Untitled subject";

      subjectGroup.appendChild(badge);
      subjectGroup.appendChild(subject);

      const idSpan = document.createElement("code");
      idSpan.className = "mono-id";
      idSpan.textContent = mem.memory_id || "";

      topRow.appendChild(subjectGroup);
      topRow.appendChild(idSpan);

      const contentP = document.createElement("p");
      contentP.className = "card-content";
      contentP.textContent = mem.content || "";

      card.appendChild(topRow);
      card.appendChild(contentP);

      if (mem.relationship) {
        const relBox = document.createElement("div");
        relBox.className = "evidence-relationship";

        const relLabel = document.createElement("span");
        relLabel.className = "evidence-relationship-label";
        relLabel.textContent = "Graph relationship:";

        const relText = document.createElement("span");
        relText.textContent = mem.relationship;

        relBox.appendChild(relLabel);
        relBox.appendChild(relText);
        card.appendChild(relBox);
      }

      const footerRow = document.createElement("div");
      footerRow.className = "card-footer-row";

      const updatedEl = document.createElement("span");
      updatedEl.textContent = mem.updated_at
        ? `Updated ${formatDateTimeShort(mem.updated_at)}`
        : "";
      updatedEl.title = mem.updated_at || "";

      const locateBtn = document.createElement("button");
      locateBtn.type = "button";
      locateBtn.className = "btn btn-ghost btn-xs";
      locateBtn.textContent = "Locate in Saved Memories";
      locateBtn.addEventListener("click", () => {
        if (typeof state.callbacks.onLocateMemory === "function" && mem.memory_id) {
          state.callbacks.onLocateMemory(mem.memory_id);
        }
      });

      footerRow.appendChild(updatedEl);
      footerRow.appendChild(locateBtn);
      card.appendChild(footerRow);

      fragment.appendChild(card);
    });

    els.evidenceList.replaceChildren(fragment);
  }

  function selectTurnForEvidence(turnId, { switchMobilePane = false } = {}) {
    state.selectedTurnId = turnId;
    syncTurnSelectionButtons();
    renderEvidencePanel();
    if (switchMobilePane && global.MemoryMateApp && typeof global.MemoryMateApp.setMobilePane === "function") {
      global.MemoryMateApp.setMobilePane("evidence");
    }
  }

  function scrollToBottom() {
    if (!els.chatStream) return;
    els.chatStream.scrollTop = els.chatStream.scrollHeight;
  }

  /**
   * Submit a chat message to POST /chat.
   */
  async function sendMessage(rawMessage) {
    if (state.isPending) return;
    const message = typeof rawMessage === "string" ? rawMessage.trim() : "";
    if (!message || message.length > API.MAX_MESSAGE_CHARS) return;

    clearError();

    const userTimestamp = new Date().toISOString();
    els.emptyState.hidden = true;

    // Render user's message bubble in the visible conversation stream
    const userNode = buildUserMessageNode({
      userMessage: message,
      timestamp: userTimestamp,
    });
    els.messagesList.appendChild(userNode);

    // Clear input and lock composer while awaiting backend confirmation
    els.input.value = "";
    autoResizeTextarea();
    state.isPending = true;
    updateComposerState();
    els.loadingIndicator.hidden = false;
    scrollToBottom();

    const { userId } = API.getConfig();

    try {
      const response = await API.sendChat({
        userId,
        message,
        conversationId: state.conversationId,
      });

      if (response && typeof response.conversation_id === "string") {
        state.conversationId = response.conversation_id;
        updateConversationBadge();
      }

      const turn = {
        id: `turn_${state.turns.length + 1}_${Date.now()}`,
        turnNumber: state.turns.length + 1,
        userMessage: message,
        answer: typeof response.answer === "string" ? response.answer : "",
        memoriesUsed: Array.isArray(response.memories_used) ? response.memories_used : [],
        memoryOperations: response.memory_operations || {
          created: 0,
          updated: 0,
          superseded: 0,
        },
        timestamp: new Date().toISOString(),
      };

      state.turns.push(turn);
      state.selectedTurnId = turn.id;

      const assistantNode = buildAssistantMessageNode(turn);
      els.messagesList.appendChild(assistantNode);
      syncTurnSelectionButtons();
      renderEvidencePanel();

      if (typeof state.callbacks.onTurnCompleted === "function") {
        state.callbacks.onTurnCompleted(response);
      }
    } catch (err) {
      const partialOps =
        err && err.details && err.details.memory_operations
          ? err.details.memory_operations
          : null;
      showError(err, { partialOps });

      if (err && (err.status === 503 || err.status === 0)) {
        if (typeof state.callbacks.onDependencyError === "function") {
          state.callbacks.onDependencyError(err);
        }
      }

      // If facts were saved before answer generation failed, refresh the memory list
      // so the Saved Memories panel remains truthful to FalkorDB.
      if (partialOps && hasAnyMemoryOperation(partialOps)) {
        if (typeof state.callbacks.onTurnCompleted === "function") {
          state.callbacks.onTurnCompleted({ memory_operations: partialOps });
        }
      }
    } finally {
      state.isPending = false;
      els.loadingIndicator.hidden = true;
      updateComposerState();
      scrollToBottom();
      if (els.input) {
        els.input.focus();
      }
    }
  }

  /**
   * Reset visible conversation state and start fresh without replaying old turns.
   * Saved memories remain persisted in FalkorDB.
   */
  function startNewConversation() {
    if (state.isPending) return;
    state.conversationId = null;
    state.turns = [];
    state.selectedTurnId = null;

    clearError();
    updateConversationBadge();

    if (els.messagesList) {
      els.messagesList.replaceChildren();
    }
    if (els.emptyState) {
      els.emptyState.hidden = false;
    }
    renderEvidencePanel();
    updateComposerState();

    if (els.input) {
      els.input.focus();
    }
  }

  function setWelcomeName(name) {
    if (!els.welcomeTitle) return;
    const firstName = String(name || "").trim().split(/\s+/)[0];
    els.welcomeTitle.textContent = firstName
      ? `Good to see you, ${firstName}.`
      : "Start a memory-grounded conversation";
  }

  async function openConversation(conversationId) {
    if (state.isPending) return;
    const conversation = await API.getConversation(conversationId);
    state.conversationId = conversation.conversation_id;
    state.turns = [];
    state.selectedTurnId = null;
    clearError();
    if (els.messagesList) els.messagesList.replaceChildren();

    let pendingUser = null;
    (conversation.messages || []).forEach((message) => {
      if (message.role === "user") {
        pendingUser = message;
        return;
      }
      if (message.role !== "assistant" || !pendingUser) return;
      const metadata = message.metadata || {};
      const turn = {
        id: message.message_id,
        turnNumber: state.turns.length + 1,
        userMessage: pendingUser.content,
        answer: message.content,
        memoriesUsed: Array.isArray(metadata.memories_used) ? metadata.memories_used : [],
        memoryOperations: metadata.memory_operations || { created: 0, updated: 0, superseded: 0 },
        timestamp: message.created_at,
      };
      state.turns.push(turn);
      els.messagesList.appendChild(buildUserMessageNode({
        userMessage: pendingUser.content,
        timestamp: pendingUser.created_at,
      }));
      els.messagesList.appendChild(buildAssistantMessageNode(turn));
      pendingUser = null;
    });
    state.selectedTurnId = state.turns.length ? state.turns[state.turns.length - 1].id : null;
    updateConversationBadge();
    syncTurnSelectionButtons();
    renderEvidencePanel();
    if (els.emptyState) els.emptyState.hidden = state.turns.length > 0;
    scrollToBottom();
  }

  function bindEvents() {
    if (els.form) {
      els.form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!state.isPending && els.input) {
          sendMessage(els.input.value);
        }
      });
    }

    if (els.input) {
      els.input.addEventListener("input", () => {
        autoResizeTextarea();
        updateComposerState();
      });

      // Enter sends; Shift+Enter inserts a newline
      els.input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
          event.preventDefault();
          if (!state.isPending && !els.sendBtn.disabled) {
            sendMessage(els.input.value);
          }
        }
      });
    }

    if (els.newConvBtn) {
      els.newConvBtn.addEventListener("click", () => {
        startNewConversation();
      });
    }

    if (els.dismissErrorBtn) {
      els.dismissErrorBtn.addEventListener("click", () => {
        clearError();
      });
    }

    // Starter prompt chips populate the input and focus it (or send)
    const starterChips = document.querySelectorAll(".starter-chip[data-prompt]");
    starterChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        if (state.isPending || !els.input) return;
        const promptText = chip.getAttribute("data-prompt") || "";
        els.input.value = promptText;
        autoResizeTextarea();
        updateComposerState();
        els.input.focus();
      });
    });
  }

  function init(callbacks = {}) {
    state.callbacks = { ...state.callbacks, ...callbacks };
    cacheElements();
    bindEvents();
    updateConversationBadge();
    renderEvidencePanel();
    updateComposerState();
  }

  global.MemoryMateChat = Object.freeze({
    init,
    sendMessage,
    startNewConversation,
    setWelcomeName,
    openConversation,
    getConversationId: () => state.conversationId,
    isPending: () => state.isPending,
  });
})(window);
