/**
 * MemoryMate AI — Main Application Bootstrap & Coordinator (js/app.js)
 *
 * Coordinates:
 *   - Backend & database connection status indicator (GET /health)
 *   - API endpoint configuration popover
 *   - Cross-module synchronization between Chat, Evidence, Saved Memories, and Graph
 *   - Responsive mobile/tablet pane navigation
 */
(function (global) {
  "use strict";

  const API = global.MemoryMateAPI;
  const Chat = global.MemoryMateChat;
  const Memories = global.MemoryMateMemories;

  const HEALTH_POLL_INTERVAL_MS = 30000;
  const LAYOUT_STORAGE_KEY = "memorymate-workspace-layout-v1";
  const DEFAULT_LAYOUT = Object.freeze({ chat: 56, evidence: 38 });

  const state = {
    activeMobilePane: "chat",
    healthTimer: null,
    authMode: "login",
    currentUser: null,
  };

  const els = {};

  function cacheElements() {
    els.authScreen = document.getElementById("auth-screen");
    els.appShell = document.getElementById("app-shell");
    els.authForm = document.getElementById("auth-form");
    els.authSignupFields = document.getElementById("auth-signup-fields");
    els.authFullName = document.getElementById("auth-full-name");
    els.authCountryCode = document.getElementById("auth-country-code");
    els.authMobileNumber = document.getElementById("auth-mobile-number");
    els.authAge = document.getElementById("auth-age");
    els.authIdentifier = document.getElementById("auth-identifier");
    els.authIdentifierLabel = document.getElementById("auth-identifier-label");
    els.authPassword = document.getElementById("auth-password");
    els.authError = document.getElementById("auth-error");
    els.authSubmit = document.getElementById("auth-submit");
    els.authModeToggle = document.getElementById("auth-mode-toggle");
    els.authHeading = document.getElementById("auth-heading");
    els.authDescription = document.getElementById("auth-description");
    els.signedInUser = document.getElementById("signed-in-user");
    els.logoutBtn = document.getElementById("logout-btn");
    els.accountMenuBtn = document.getElementById("account-menu-btn");
    els.accountMenu = document.getElementById("account-menu-popover");
    els.accountMenuName = document.getElementById("account-menu-name");
    els.conversationHistory = document.getElementById("conversation-history-select");
    els.historyError = document.getElementById("history-error");
    els.workspaceLayout = document.getElementById("workspace-layout");
    els.inspectorColumn = document.querySelector(".inspector-column");
    els.mainSplitter = document.getElementById("main-layout-splitter");
    els.inspectorSplitter = document.getElementById("inspector-layout-splitter");
    els.resetLayoutBtn = document.getElementById("reset-layout-btn");

    // Health Bar Elements
    els.overallPill = document.getElementById("health-overall-pill");
    els.overallDot = document.getElementById("health-overall-dot");
    els.overallText = document.getElementById("health-overall-text");
    els.falkordbDot = document.getElementById("health-falkordb-dot");
    els.falkordbValue = document.getElementById("health-falkordb-value");
    els.llmDot = document.getElementById("health-llm-dot");
    els.llmValue = document.getElementById("health-llm-value");
    els.refreshHealthBtn = document.getElementById("refresh-health-btn");

    // Identity & Connection Settings Popover
    els.settingsBtn = document.getElementById("connection-settings-btn");
    els.activeUserBadge = document.getElementById("active-user-badge");
    els.settingsPopover = document.getElementById("connection-settings-popover");
    els.closeSettingsBtn = document.getElementById("close-settings-popover-btn");
    els.settingsForm = document.getElementById("connection-settings-form");
    els.settingUserId = document.getElementById("setting-user-id");
    els.settingApiBase = document.getElementById("setting-api-base");
    els.settingsError = document.getElementById("settings-form-error");
    els.resetSettingsBtn = document.getElementById("reset-settings-btn");

    // Mobile Navigation Tabs
    els.mobileTabs = document.querySelectorAll(".mobile-nav-tab[data-mobile-pane]");
  }

  /**
   * Poll GET /health and update the connection status bar.
   */
  async function checkHealth() {
    if (!els.overallPill) return;

    try {
      const data = await API.getHealth();
      const overallStatus = data && typeof data.status === "string" ? data.status : "degraded";
      const deps = (data && data.dependencies) || {};
      const falkordb = typeof deps.falkordb === "string" ? deps.falkordb : "unavailable";
      const llm = typeof deps.llm === "string" ? deps.llm : "not_configured";

      // Update Overall Pill
      els.overallPill.className =
        overallStatus === "ok"
          ? "status-pill status-ok"
          : "status-pill status-degraded";
      els.overallDot.className =
        overallStatus === "ok" ? "status-dot dot-ok" : "status-dot dot-warn";
      els.overallText.textContent =
        overallStatus === "ok" ? "Backend: ok" : `Backend: ${overallStatus}`;

      // Update FalkorDB Badge
      els.falkordbValue.textContent = falkordb;
      els.falkordbDot.className =
        falkordb === "ok" ? "status-dot dot-ok" : "status-dot dot-err";

      // Update LLM Badge
      els.llmValue.textContent = llm;
      els.llmDot.className =
        llm === "configured" ? "status-dot dot-ok" : "status-dot dot-warn";
    } catch (_err) {
      els.overallPill.className = "status-pill status-offline";
      els.overallDot.className = "status-dot dot-err";
      els.overallText.textContent = "Backend: unreachable";

      els.falkordbValue.textContent = "unreachable";
      els.falkordbDot.className = "status-dot dot-err";

      els.llmValue.textContent = "unreachable";
      els.llmDot.className = "status-dot dot-err";
    }
  }

  function syncSettingsUI() {
    const { apiBaseUrl, userId } = API.getConfig();
    if (els.activeUserBadge) {
      els.activeUserBadge.textContent = state.currentUser ? state.currentUser.user_id : userId;
    }
    if (els.accountMenuName) {
      els.accountMenuName.textContent = state.currentUser?.full_name || "Your account";
    }
    if (els.settingApiBase) {
      els.settingApiBase.value = apiBaseUrl;
    }
    if (els.signedInUser && state.currentUser) {
      els.signedInUser.textContent = state.currentUser.email;
    }
  }

  function toggleSettingsPopover(forceOpen) {
    if (!els.settingsPopover || !els.settingsBtn) return;
    const willOpen =
      typeof forceOpen === "boolean" ? forceOpen : els.settingsPopover.hidden;
    if (willOpen) {
      syncSettingsUI();
      if (els.settingsError) {
        els.settingsError.hidden = true;
        els.settingsError.textContent = "";
      }
    }
    els.settingsPopover.hidden = !willOpen;
    els.settingsBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
  }

  function toggleAccountMenu(forceOpen) {
    if (!els.accountMenu || !els.accountMenuBtn) return;
    const willOpen = typeof forceOpen === "boolean" ? forceOpen : els.accountMenu.hidden;
    els.accountMenu.hidden = !willOpen;
    els.accountMenuBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
    if (willOpen) syncSettingsUI();
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function applyWorkspaceLayout(layout) {
    if (!els.workspaceLayout) return;
    const chat = clamp(Number(layout.chat) || DEFAULT_LAYOUT.chat, 32, 72);
    const evidence = clamp(Number(layout.evidence) || DEFAULT_LAYOUT.evidence, 25, 75);
    els.workspaceLayout.style.setProperty("--chat-pane-size", `${chat}fr`);
    els.workspaceLayout.style.setProperty("--inspector-pane-size", `${100 - chat}fr`);
    els.workspaceLayout.style.setProperty("--evidence-pane-size", `${evidence}fr`);
    els.workspaceLayout.style.setProperty("--memories-pane-size", `${100 - evidence}fr`);
    if (els.mainSplitter) els.mainSplitter.setAttribute("aria-valuenow", String(Math.round(chat)));
    if (els.inspectorSplitter) els.inspectorSplitter.setAttribute("aria-valuenow", String(Math.round(evidence)));
  }

  function saveWorkspaceLayout() {
    if (!els.workspaceLayout) return;
    const style = getComputedStyle(els.workspaceLayout);
    const chat = Number.parseFloat(style.getPropertyValue("--chat-pane-size")) || DEFAULT_LAYOUT.chat;
    const evidence = Number.parseFloat(style.getPropertyValue("--evidence-pane-size")) || DEFAULT_LAYOUT.evidence;
    try { localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify({ chat, evidence })); } catch (_error) { /* Storage may be disabled. */ }
  }

  function resetWorkspaceLayout() {
    try { localStorage.removeItem(LAYOUT_STORAGE_KEY); } catch (_error) { /* Storage may be disabled. */ }
    applyWorkspaceLayout(DEFAULT_LAYOUT);
  }

  function splitterWidth(splitter) {
    const rect = splitter.getBoundingClientRect();
    return splitter.classList.contains("layout-splitter-column") ? rect.width : rect.height;
  }

  function initWorkspaceLayout() {
    if (!els.workspaceLayout) return;
    try {
      const saved = JSON.parse(localStorage.getItem(LAYOUT_STORAGE_KEY) || "null");
      applyWorkspaceLayout(saved && typeof saved === "object" ? saved : DEFAULT_LAYOUT);
    } catch (_error) {
      applyWorkspaceLayout(DEFAULT_LAYOUT);
    }

    const bindSplitter = (splitter, axis, update) => {
      if (!splitter) return;
      splitter.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        splitter.classList.add("is-dragging");
        splitter.setPointerCapture(event.pointerId);
        const move = (nextEvent) => update(axis === "x" ? nextEvent.clientX : nextEvent.clientY);
        const stop = () => {
          splitter.classList.remove("is-dragging");
          splitter.removeEventListener("pointermove", move);
          splitter.removeEventListener("pointerup", stop);
          splitter.removeEventListener("pointercancel", stop);
          saveWorkspaceLayout();
        };
        splitter.addEventListener("pointermove", move);
        splitter.addEventListener("pointerup", stop, { once: true });
        splitter.addEventListener("pointercancel", stop, { once: true });
      });
      splitter.addEventListener("keydown", (event) => {
        const negative = axis === "x" ? "ArrowLeft" : "ArrowUp";
        const positive = axis === "x" ? "ArrowRight" : "ArrowDown";
        if (event.key !== negative && event.key !== positive) return;
        event.preventDefault();
        const current = Number(splitter.getAttribute("aria-valuenow")) || 50;
        const value = clamp(current + (event.key === positive ? 2 : -2), Number(splitter.getAttribute("aria-valuemin")), Number(splitter.getAttribute("aria-valuemax")));
        const chat = axis === "x" ? value : Number(els.mainSplitter?.getAttribute("aria-valuenow")) || DEFAULT_LAYOUT.chat;
        const evidence = axis === "y" ? value : Number(els.inspectorSplitter?.getAttribute("aria-valuenow")) || DEFAULT_LAYOUT.evidence;
        applyWorkspaceLayout({ chat, evidence });
        saveWorkspaceLayout();
      });
    };

    bindSplitter(els.mainSplitter, "x", (clientX) => {
      const rect = els.workspaceLayout.getBoundingClientRect();
      const style = getComputedStyle(els.workspaceLayout);
      const padding = Number.parseFloat(style.paddingLeft) + Number.parseFloat(style.paddingRight);
      const available = Math.max(1, rect.width - padding - splitterWidth(els.mainSplitter));
      const ratio = ((clientX - rect.left - Number.parseFloat(style.paddingLeft)) / available) * 100;
      applyWorkspaceLayout({ chat: ratio, evidence: Number(els.inspectorSplitter?.getAttribute("aria-valuenow")) || DEFAULT_LAYOUT.evidence });
    });
    bindSplitter(els.inspectorSplitter, "y", (clientY) => {
      const rect = els.inspectorColumn.getBoundingClientRect();
      const available = Math.max(1, rect.height - splitterWidth(els.inspectorSplitter));
      const ratio = ((clientY - rect.top) / available) * 100;
      applyWorkspaceLayout({ chat: Number(els.mainSplitter?.getAttribute("aria-valuenow")) || DEFAULT_LAYOUT.chat, evidence: ratio });
    });
  }

  function setMobilePane(paneName) {
    const validPanes = new Set(["chat", "evidence", "memories", "graph"]);
    const target = validPanes.has(paneName) ? paneName : "chat";
    state.activeMobilePane = target;

    if (els.workspaceLayout) {
      els.workspaceLayout.setAttribute("data-active-pane", target);
    }

    if (els.mobileTabs) {
      els.mobileTabs.forEach((tab) => {
        const tabPane = tab.getAttribute("data-mobile-pane");
        const isActive = tabPane === target;
        tab.classList.toggle("is-active", isActive);
        tab.setAttribute("aria-selected", isActive ? "true" : "false");
      });
    }

    if (target === "graph") {
      Memories.switchSubview("graph");
    } else if (target === "memories") {
      Memories.switchSubview("list");
    }
  }

  function bindEvents() {
    if (els.authModeToggle) {
      els.authModeToggle.addEventListener("click", () => {
        state.authMode = state.authMode === "login" ? "signup" : "login";
        updateAuthModeUI();
      });
    }
    if (els.authForm) {
      els.authForm.addEventListener("submit", submitAuthForm);
    }
  }

  function updateAuthModeUI() {
    const signup = state.authMode === "signup";
    els.authHeading.textContent = signup ? "Create your account" : "Welcome to MemoryMate AI";
    els.authDescription.textContent = signup
      ? "Create an account to keep your memories and conversations private."
      : "Sign in to your private memory workspace.";
    els.authSubmit.textContent = signup ? "Create account" : "Sign in";
    els.authModeToggle.textContent = signup ? "Already have an account? Sign in" : "Create an account";
    els.authPassword.autocomplete = signup ? "new-password" : "current-password";
    els.authPassword.minLength = signup ? 10 : 1;
    els.authSignupFields.hidden = !signup;
    els.authFullName.required = signup;
    els.authCountryCode.required = signup;
    els.authMobileNumber.required = signup;
    els.authAge.required = signup;
    els.authIdentifierLabel.textContent = "Email";
    els.authIdentifier.placeholder = "you@example.com";
    els.authIdentifier.type = "email";
    els.authIdentifier.autocomplete = signup ? "email" : "username";
  }

  async function submitAuthForm(event) {
    event.preventDefault();
    if (!els.authForm.reportValidity()) return;
    els.authError.hidden = true;
    els.authSubmit.disabled = true;
    try {
      const password = els.authPassword.value;
      let account;
      if (state.authMode === "signup") {
        const digits = els.authMobileNumber.value.replace(/\D/g, "").replace(/^0+/, "");
        account = await API.signUp({
          fullName: els.authFullName.value.trim(),
          email: els.authIdentifier.value.trim(),
          mobileNumber: `${els.authCountryCode.value}${digits}`,
          age: Number(els.authAge.value),
          password,
        });
      } else {
        account = await API.login({ email: els.authIdentifier.value.trim(), password });
      }
      els.authPassword.value = "";
      await openWorkspace(account);
    } catch (error) {
      els.authError.textContent = API.formatErrorMessage(error);
      els.authError.hidden = false;
    } finally {
      els.authSubmit.disabled = false;
    }
  }

  async function loadWorkspaceData() {
    await Promise.all([
      checkHealth(),
      Memories.loadMemories({ resetOffset: true }),
      Memories.loadGraph({ silent: true }),
      refreshConversationHistory(),
    ]);
  }

  async function refreshConversationHistory() {
    if (!els.conversationHistory) return;
    try {
      const { items } = await API.listConversations();
      els.conversationHistory.replaceChildren();
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Conversation history";
      els.conversationHistory.appendChild(placeholder);
      (items || []).forEach((item) => {
        const option = document.createElement("option");
        option.value = item.conversation_id;
        option.textContent = `${item.title} (${item.message_count})`;
        els.conversationHistory.appendChild(option);
      });
      if (els.historyError) els.historyError.hidden = true;
    } catch (_error) {
      // Chat and memory panels remain usable if the history service is unavailable.
    }
  }

  async function openWorkspace(account) {
    state.currentUser = account;
    API.setAuthenticatedUser(account.user_id);
    els.authScreen.hidden = true;
    els.appShell.hidden = false;
    syncSettingsUI();

    if (!state.workspaceInitialized) {
      setMobilePane("chat");
      Memories.init();
      Chat.init({
        onTurnCompleted: async () => {
          await Promise.all([
            Memories.loadMemories({ resetOffset: false, silent: true }),
            Memories.loadGraph({ silent: true }),
            refreshConversationHistory(),
          ]);
        },
        onLocateMemory: (memoryId) => Memories.locateMemoryById(memoryId),
        onDependencyError: () => checkHealth(),
      });
      bindWorkspaceEvents();
      state.workspaceInitialized = true;
      if (state.healthTimer) clearInterval(state.healthTimer);
      state.healthTimer = setInterval(checkHealth, HEALTH_POLL_INTERVAL_MS);
    }
    Chat.setWelcomeName(account.full_name);
    await loadWorkspaceData();
  }

  function bindWorkspaceEvents() {
    // Keep general app controls separate from the sign-in form wiring.
    bindHeaderEvents();
  }

  function bindHeaderEvents() {
    if (els.refreshHealthBtn) els.refreshHealthBtn.addEventListener("click", checkHealth);
    if (els.accountMenuBtn) els.accountMenuBtn.addEventListener("click", () => toggleAccountMenu());
    if (els.settingsBtn) els.settingsBtn.addEventListener("click", () => toggleSettingsPopover());
    if (els.resetLayoutBtn) els.resetLayoutBtn.addEventListener("click", resetWorkspaceLayout);
    initWorkspaceLayout();
    if (els.closeSettingsBtn) els.closeSettingsBtn.addEventListener("click", () => toggleSettingsPopover(false));
    if (els.resetSettingsBtn) {
      els.resetSettingsBtn.addEventListener("click", () => {
        API.resetConfig();
        global.location.reload();
      });
    }
    if (els.logoutBtn) {
      els.logoutBtn.addEventListener("click", async () => {
        try { await API.logout(); } finally { global.location.reload(); }
      });
    }
    if (els.conversationHistory) {
      els.conversationHistory.addEventListener("change", async () => {
        if (!els.conversationHistory.value) return;
        try {
          await Chat.openConversation(els.conversationHistory.value);
        } catch (error) {
          if (els.historyError) {
            els.historyError.textContent = API.formatErrorMessage(error);
            els.historyError.hidden = false;
          }
        } finally {
          els.conversationHistory.value = "";
        }
      });
    }
    const newConversationBtn = document.getElementById("new-conversation-btn");
    if (newConversationBtn) newConversationBtn.addEventListener("click", () => {
      if (els.conversationHistory) els.conversationHistory.value = "";
      Chat.startNewConversation();
    });
    if (els.settingsForm) {
      els.settingsForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
          API.setConfig({ apiBaseUrl: els.settingApiBase.value });
          Chat.startNewConversation();
          Memories.clearForIdentityChange();
          API.clearAuthenticatedUser();
          state.currentUser = null;
          els.appShell.hidden = true;
          const account = await API.getCurrentUser();
          toggleSettingsPopover(false);
          await openWorkspace(account);
        } catch (error) {
          els.authScreen.hidden = false;
          if (els.settingsError) {
            els.settingsError.textContent = API.formatErrorMessage(error);
            els.settingsError.hidden = false;
          }
          if (els.authError) {
            els.authError.textContent = API.formatErrorMessage(error);
            els.authError.hidden = false;
          }
        }
      });
    }
    document.addEventListener("click", (event) => {
      if (els.settingsPopover && !els.settingsPopover.hidden && !els.settingsPopover.contains(event.target) &&
          els.settingsBtn && !els.settingsBtn.contains(event.target)) toggleSettingsPopover(false);
      if (els.accountMenu && !els.accountMenu.hidden &&
          !els.accountMenu.contains(event.target) && els.accountMenuBtn && !els.accountMenuBtn.contains(event.target)) {
        toggleAccountMenu(false);
      }
    });
    if (els.mobileTabs) {
      els.mobileTabs.forEach((tab) => tab.addEventListener("click", () => {
        setMobilePane(tab.getAttribute("data-mobile-pane") || "chat");
      }));
    }
  }

  async function init() {
    cacheElements();
    updateAuthModeUI();
    bindEvents();
    try {
      const account = await API.getCurrentUser();
      await openWorkspace(account);
    } catch (error) {
      els.appShell.hidden = true;
      els.authScreen.hidden = false;
      if (error && error.status !== 401) {
        els.authError.textContent = API.formatErrorMessage(error);
        els.authError.hidden = false;
      }
    }
  }

  global.MemoryMateApp = Object.freeze({
    init,
    checkHealth,
    setMobilePane,
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
