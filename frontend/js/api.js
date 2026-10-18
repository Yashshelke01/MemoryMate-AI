/**
 * MemoryMate AI — Backend API Client (js/api.js)
 *
 * Strictly implements the HTTP/JSON contracts defined in PROJECT_CONTRACT.md
 * Section 4 and backend/app/models/api.py.
 *
 * Endpoints:
 *   - GET    /health
 *   - POST   /chat
 *   - GET    /memories/{user_id}?limit=50&offset=0
 *   - PATCH  /memories/{memory_id}
 *   - DELETE /memories/{memory_id}
 *   - GET    /graph/{user_id}
 */
(function (global) {
  "use strict";

  const CATEGORIES = Object.freeze([
    "goal",
    "skill",
    "project",
    "task",
    "preference",
    "commitment",
    "decision",
    "other",
  ]);

  const USER_ID_PATTERN = /^[A-Za-z0-9_.\-]{1,64}$/;
  const MEMORY_ID_PATTERN = /^mem_[A-Za-z0-9\-]{1,64}$/;
  const CONVERSATION_ID_PATTERN = /^conv_[A-Za-z0-9\-]{1,64}$/;

  const MAX_MESSAGE_CHARS = 4000;
  const MAX_CONTENT_CHARS = 500;
  const MAX_SUBJECT_CHARS = 200;

  /**
   * Determine the default FastAPI base URL.
   * - Honours ?apiBaseUrl= or ?api= query parameter if present.
   * - If served on port 8000 (same origin as FastAPI), uses window.location.origin.
   * - Otherwise targets port 8000 on the same loopback host (localhost or 127.0.0.1)
   *   so CORS origins in backend/app/config.py match cleanly.
   */
  function resolveDefaultApiBaseUrl() {
    try {
      const params = new URLSearchParams(global.location.search || "");
      const override = params.get("apiBaseUrl") || params.get("api");
      if (override && /^https?:\/\//i.test(override.trim())) {
        return override.trim().replace(/\/+$/, "");
      }
      const loc = global.location;
      if (loc && (loc.protocol === "http:" || loc.protocol === "https:")) {
        const staticDevPorts = new Set(["3000", "5500", "8080", "5173", "4173"]);
        if (loc.port && !staticDevPorts.has(loc.port)) {
          return loc.origin.replace(/\/+$/, "");
        }
        const host = loc.hostname === "127.0.0.1" ? "127.0.0.1" : "localhost";
        return `http://${host}:8000`;
      }
    } catch (_err) {
      // Fallback to standard local FastAPI address
    }
    return "http://localhost:8000";
  }

  const state = {
    apiBaseUrl: resolveDefaultApiBaseUrl(),
    userId: "",
  };

  /**
   * Structured error returned by the backend or raised on network failure.
   */
  class ApiError extends Error {
    constructor({ status = 0, code = "network_error", message = "Request failed.", details = null }) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.details = details;
    }
  }

  /**
   * Format an ApiError or unknown error into a clear, safe user-facing string.
   */
  function formatErrorMessage(err) {
    if (!(err instanceof ApiError)) {
      return err && typeof err.message === "string" && err.message.trim()
        ? err.message.trim()
        : "An unexpected client error occurred.";
    }

    let base = err.message || "Request could not be completed.";
    if (
      err.code === "validation_error" &&
      err.details &&
      Array.isArray(err.details.errors) &&
      err.details.errors.length > 0
    ) {
      const fieldMessages = err.details.errors
        .map((item) => {
          const field = item && item.field ? String(item.field).replace(/^body\./, "") : "field";
          const msg = item && item.message ? String(item.message) : "Invalid value.";
          return `${field}: ${msg}`;
        })
        .join("; ");
      base = `${base} (${fieldMessages})`;
    }
    return base;
  }

  /**
   * Low-level JSON Fetch wrapper that enforces Content-Type and parses
   * the backend's {"error": {"code", "message", "details"}} contract.
   */
  async function requestJson(path, { method = "GET", body = undefined, signal = undefined } = {}) {
    const url = `${state.apiBaseUrl}${path}`;
    const headers = {};
    const fetchOptions = {
      method,
      headers,
      signal,
      credentials: "include",
    };

    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      fetchOptions.body = JSON.stringify(body);
    }

    let response;
    try {
      response = await fetch(url, fetchOptions);
    } catch (_networkErr) {
      throw new ApiError({
        status: 0,
        code: "network_unreachable",
        message: `Cannot reach backend API at ${state.apiBaseUrl}. Ensure the FastAPI server is running and CORS permits this origin.`,
        details: null,
      });
    }

    let parsed = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try {
        parsed = await response.json();
      } catch (_parseErr) {
        parsed = null;
      }
    } else {
      try {
        const text = await response.text();
        if (text) {
          parsed = JSON.parse(text);
        }
      } catch (_ignore) {
        parsed = null;
      }
    }

    if (!response.ok) {
      const errObj = parsed && typeof parsed === "object" && parsed.error ? parsed.error : null;
      const code = errObj && typeof errObj.code === "string" ? errObj.code : `http_${response.status}`;
      const message =
        errObj && typeof errObj.message === "string"
          ? errObj.message
          : `Backend returned HTTP ${response.status}.`;
      const details = errObj && errObj.details ? errObj.details : null;
      throw new ApiError({
        status: response.status,
        code,
        message,
        details,
      });
    }

    if (parsed === null || typeof parsed !== "object") {
      throw new ApiError({
        status: response.status,
        code: "invalid_response",
        message: "Backend returned a non-JSON response.",
      });
    }

    return parsed;
  }

  function getConfig() {
    return {
      apiBaseUrl: state.apiBaseUrl,
      userId: state.userId,
    };
  }

  function setConfig({ apiBaseUrl } = {}) {
    if (apiBaseUrl !== undefined) {
      const cleaned = String(apiBaseUrl).trim().replace(/\/+$/, "");
      if (!/^https?:\/\/.+/i.test(cleaned)) {
        throw new Error("API Base URL must start with http:// or https://");
      }
      state.apiBaseUrl = cleaned;
    }
    return getConfig();
  }

  function resetConfig() {
    state.apiBaseUrl = resolveDefaultApiBaseUrl();
    return getConfig();
  }

  function setAuthenticatedUser(userId) {
    const cleaned = String(userId || "").trim();
    if (!USER_ID_PATTERN.test(cleaned)) {
      throw new ApiError({ status: 500, code: "invalid_identity", message: "Backend returned an invalid account identity." });
    }
    state.userId = cleaned;
  }

  function clearAuthenticatedUser() {
    state.userId = "";
  }

  async function signUp({ fullName, email, mobileNumber, age, password }) {
    return requestJson("/auth/signup", {
      method: "POST",
      body: { full_name: fullName, email, mobile_number: mobileNumber, age, password },
    });
  }

  async function login({ email, password }) {
    return requestJson("/auth/login", { method: "POST", body: { email, password } });
  }

  async function logout() {
    const result = await requestJson("/auth/logout", { method: "POST" });
    state.userId = "";
    return result;
  }

  async function getCurrentUser() {
    return requestJson("/auth/me", { method: "GET" });
  }

  /**
   * GET /health
   * Response: { status: "ok" | "degraded", dependencies: { falkordb: "ok" | "unavailable", llm: "configured" | "not_configured" } }
   */
  async function getHealth() {
    return requestJson("/health", { method: "GET" });
  }

  /**
   * POST /chat
   * Request:  { message, conversation_id }; identity is derived from the session.
   * Response: { conversation_id, answer, memories_used: [...], memory_operations: { created, updated, superseded } }
   */
  async function sendChat({ message, conversationId = null }) {
    const trimmedMessage = typeof message === "string" ? message.trim() : "";
    if (!trimmedMessage) {
      throw new ApiError({
        status: 400,
        code: "blank_message",
        message: "Message must not be blank.",
      });
    }
    if (trimmedMessage.length > MAX_MESSAGE_CHARS) {
      throw new ApiError({
        status: 400,
        code: "message_too_long",
        message: `Message must be at most ${MAX_MESSAGE_CHARS} characters.`,
      });
    }

    const payload = {
      message: trimmedMessage,
      conversation_id:
        conversationId && CONVERSATION_ID_PATTERN.test(conversationId) ? conversationId : null,
    };

    return requestJson("/chat", {
      method: "POST",
      body: payload,
    });
  }

  /**
   * GET /memories/{user_id}?limit=50&offset=0
   * Response: { items: [...], limit, offset, total }
   */
  async function listMemories({ userId = state.userId, limit = 50, offset = 0 } = {}) {
    const safeLimit = Math.min(100, Math.max(1, Number(limit) || 50));
    const safeOffset = Math.max(0, Number(offset) || 0);
    const encodedUser = encodeURIComponent(userId);
    return requestJson(`/memories/${encodedUser}?limit=${safeLimit}&offset=${safeOffset}`, {
      method: "GET",
    });
  }

  /**
   * PATCH /memories/{memory_id}
   * Request:  { content?, category?, subject? }; owner comes from the session.
   * Response: { memory: { memory_id, user_id, content, category, subject, updated_at } }
   */
  async function patchMemory({ memoryId, content, category, subject }) {
    if (!memoryId || !MEMORY_ID_PATTERN.test(memoryId)) {
      throw new ApiError({
        status: 422,
        code: "validation_error",
        message: "Invalid memory identifier format.",
      });
    }

    const payload = {};
    if (content !== undefined && content !== null) {
      payload.content = String(content).trim();
    }
    if (category !== undefined && category !== null) {
      payload.category = String(category).trim();
    }
    if (subject !== undefined && subject !== null) {
      payload.subject = String(subject).trim();
    }

    const encodedId = encodeURIComponent(memoryId);
    return requestJson(`/memories/${encodedId}`, {
      method: "PATCH",
      body: payload,
    });
  }

  /**
   * DELETE /memories/{memory_id}
   * Request:  {} ; owner comes from the session.
   * Response: { deleted: true, memory_id }
   */
  async function deleteMemory({ memoryId }) {
    if (!memoryId || !MEMORY_ID_PATTERN.test(memoryId)) {
      throw new ApiError({
        status: 422,
        code: "validation_error",
        message: "Invalid memory identifier format.",
      });
    }

    const encodedId = encodeURIComponent(memoryId);
    return requestJson(`/memories/${encodedId}`, {
      method: "DELETE",
      body: {},
    });
  }

  /**
   * GET /graph/{user_id}
   * Response: { nodes: [{ id, label, type }], edges: [{ source, target, type }] }
   */
  async function getGraph({ userId = state.userId } = {}) {
    const encodedUser = encodeURIComponent(userId);
    return requestJson(`/graph/${encodedUser}`, {
      method: "GET",
    });
  }

  async function listConversations() {
    return requestJson("/conversations", { method: "GET" });
  }

  async function getConversation(conversationId) {
    if (!conversationId || !CONVERSATION_ID_PATTERN.test(conversationId)) {
      throw new ApiError({ status: 422, code: "validation_error", message: "Invalid conversation identifier." });
    }
    return requestJson(`/conversations/${encodeURIComponent(conversationId)}`, { method: "GET" });
  }

  global.MemoryMateAPI = Object.freeze({
    CATEGORIES,
    USER_ID_PATTERN,
    MEMORY_ID_PATTERN,
    CONVERSATION_ID_PATTERN,
    MAX_MESSAGE_CHARS,
    MAX_CONTENT_CHARS,
    MAX_SUBJECT_CHARS,
    ApiError,
    formatErrorMessage,
    getConfig,
    setConfig,
    resetConfig,
    setAuthenticatedUser,
    clearAuthenticatedUser,
    signUp,
    login,
    logout,
    getCurrentUser,
    getHealth,
    sendChat,
    listMemories,
    patchMemory,
    deleteMemory,
    getGraph,
    listConversations,
    getConversation,
  });
})(window);
