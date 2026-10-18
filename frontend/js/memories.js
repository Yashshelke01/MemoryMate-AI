/**
 * MemoryMate AI — Saved Memories & Graph Controller (js/memories.js)
 *
 * Manages:
 *   - Authoritative memory list fetched from GET /memories/{user_id}
 *   - Category filtering (8 contract enums) and text search
 *   - Memory editing via PATCH /memories/{memory_id} (refreshing after confirmation)
 *   - Memory deletion via DELETE /memories/{memory_id} (refreshing after confirmation)
 *   - Graph visualization powered by GET /graph/{user_id}
 */
(function (global) {
  "use strict";

  const API = global.MemoryMateAPI;

  const CATEGORY_COLORS = Object.freeze({
    user: { fill: "#D98252", stroke: "#E7A47E", text: "#17191B" },
    goal: { fill: "#dbeafe", stroke: "#3b82f6", text: "#1e40af" },
    skill: { fill: "#dcfce7", stroke: "#22c55e", text: "#166534" },
    project: { fill: "#f3e8ff", stroke: "#a855f7", text: "#6b21a8" },
    task: { fill: "#fef3c7", stroke: "#f59e0b", text: "#92400e" },
    preference: { fill: "#fce7f3", stroke: "#ec4899", text: "#9d174d" },
    commitment: { fill: "#ccfbf1", stroke: "#14b8a6", text: "#115e59" },
    decision: { fill: "#e0e7ff", stroke: "#6366f1", text: "#3730a3" },
    other: { fill: "#f1f5f9", stroke: "#94a3b8", text: "#334155" },
  });

  const state = {
    items: [],
    total: 0,
    limit: 50,
    offset: 0,
    selectedCategory: "all",
    searchQuery: "",
    isLoading: false,
    activeSubview: "list", // "list" | "graph"
    confirmingDeleteId: null,
    deletingId: null,
    editingMemory: null,
    isSavingEdit: false,
    highlightedMemoryId: null,

    // Graph state
    graphNodes: [],
    graphEdges: [],
    isLoadingGraph: false,
    graphZoom: 1,
    selectedGraphNode: null,
    toastTimer: null,
  };

  // Invalidates pending requests when the configured identity changes. A late
  // response for the previous identity must never repopulate the visible UI.
  let identityVersion = 0;

  const els = {};

  function cacheElements() {
    els.totalBadge = document.getElementById("saved-memories-total-badge");
    els.mobileMemoriesCount = document.getElementById("mobile-memories-count");
    els.graphNodesCountBadge = document.getElementById("graph-nodes-count-badge");

    els.tabBtnList = document.getElementById("tab-btn-list");
    els.tabBtnGraph = document.getElementById("tab-btn-graph");
    els.subviewList = document.getElementById("subview-list");
    els.subviewGraph = document.getElementById("subview-graph");
    els.refreshBtn = document.getElementById("refresh-memories-btn");

    els.searchInput = document.getElementById("memory-search-input");
    els.categoryBar = document.getElementById("category-filter-bar");

    els.errorBanner = document.getElementById("memories-error-banner");
    els.errorTitle = document.getElementById("memories-error-title");
    els.errorMessage = document.getElementById("memories-error-message");
    els.retryBtn = document.getElementById("retry-memories-btn");
    els.statusToast = document.getElementById("memories-status-toast");

    els.loadingIndicator = document.getElementById("memories-loading");
    els.emptyState = document.getElementById("memories-empty-state");
    els.emptyTitle = document.getElementById("memories-empty-title");
    els.emptyDesc = document.getElementById("memories-empty-desc");
    els.clearFiltersBtn = document.getElementById("clear-memory-filters-btn");
    els.listContainer = document.getElementById("memories-list");

    els.paginationBar = document.getElementById("memories-pagination");
    els.paginationInfo = document.getElementById("memories-pagination-info");
    els.prevPageBtn = document.getElementById("memories-prev-btn");
    els.nextPageBtn = document.getElementById("memories-next-btn");

    // Edit Modal
    els.editModal = document.getElementById("edit-memory-modal");
    els.editForm = document.getElementById("edit-memory-form");
    els.editIdInput = document.getElementById("edit-memory-id");
    els.editIdDisplay = document.getElementById("edit-modal-memory-id-display");
    els.editCategorySelect = document.getElementById("edit-memory-category");
    els.editSubjectInput = document.getElementById("edit-memory-subject");
    els.editContentInput = document.getElementById("edit-memory-content");
    els.editContentCounter = document.getElementById("edit-content-counter");
    els.editModalError = document.getElementById("edit-modal-error");
    els.editModalErrorTitle = document.getElementById("edit-modal-error-title");
    els.editModalErrorMessage = document.getElementById("edit-modal-error-message");
    els.closeEditModalBtn = document.getElementById("close-edit-modal-btn");
    els.cancelEditModalBtn = document.getElementById("cancel-edit-modal-btn");
    els.saveEditModalBtn = document.getElementById("save-edit-modal-btn");

    // Graph Elements
    els.graphZoomInBtn = document.getElementById("graph-zoom-in-btn");
    els.graphZoomOutBtn = document.getElementById("graph-zoom-out-btn");
    els.graphResetBtn = document.getElementById("graph-reset-btn");
    els.graphRefreshBtn = document.getElementById("graph-refresh-btn");
    els.graphErrorBanner = document.getElementById("graph-error-banner");
    els.graphErrorMessage = document.getElementById("graph-error-message");
    els.retryGraphBtn = document.getElementById("retry-graph-btn");
    els.graphLoading = document.getElementById("graph-loading");
    els.graphEmptyState = document.getElementById("graph-empty-state");
    els.graphSvg = document.getElementById("memory-graph-svg");
    els.graphNodeInspector = document.getElementById("graph-node-inspector");
    els.graphSelectedType = document.getElementById("graph-selected-type");
    els.graphSelectedId = document.getElementById("graph-selected-id");
    els.graphSelectedLabel = document.getElementById("graph-selected-label");
    els.closeGraphInspectorBtn = document.getElementById("close-graph-inspector-btn");
  }

  function safeCategory(rawCat) {
    const val = String(rawCat || "other").toLowerCase().trim();
    return API.CATEGORIES.includes(val) ? val : "other";
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

  function showToast(message) {
    if (!els.statusToast) return;
    if (state.toastTimer) {
      clearTimeout(state.toastTimer);
    }
    els.statusToast.textContent = message;
    els.statusToast.hidden = false;
    state.toastTimer = setTimeout(() => {
      els.statusToast.hidden = true;
    }, 4000);
  }

  function clearMemoriesError() {
    if (!els.errorBanner) return;
    els.errorBanner.hidden = true;
    els.errorMessage.textContent = "";
  }

  function showMemoriesError(title, err) {
    if (!els.errorBanner) return;
    els.errorTitle.textContent = title || "Memory operation failed";
    els.errorMessage.textContent = API.formatErrorMessage(err);
    els.errorBanner.hidden = false;
  }

  function getFilteredItems() {
    const query = state.searchQuery.trim().toLowerCase();
    return state.items.filter((item) => {
      if (state.selectedCategory !== "all" && item.category !== state.selectedCategory) {
        return false;
      }
      if (query) {
        const subjectMatch = (item.subject || "").toLowerCase().includes(query);
        const contentMatch = (item.content || "").toLowerCase().includes(query);
        const idMatch = (item.memory_id || "").toLowerCase().includes(query);
        return subjectMatch || contentMatch || idMatch;
      }
      return true;
    });
  }

  function updateCategoryPills() {
    if (!els.categoryBar) return;
    const counts = { all: state.items.length };
    API.CATEGORIES.forEach((cat) => {
      counts[cat] = 0;
    });
    state.items.forEach((item) => {
      const cat = safeCategory(item.category);
      counts[cat] = (counts[cat] || 0) + 1;
    });

    const buttons = els.categoryBar.querySelectorAll(".cat-filter-btn");
    buttons.forEach((btn) => {
      const cat = btn.getAttribute("data-category") || "all";
      const count = counts[cat] || 0;
      const isActive = state.selectedCategory === cat;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
      if (cat === "all") {
        btn.textContent = `All (${count})`;
      } else {
        btn.textContent = count > 0 ? `${cat} (${count})` : cat;
      }
    });
  }

  function buildMemoryCard(item) {
    const card = document.createElement("article");
    card.className =
      "memory-card" + (state.highlightedMemoryId === item.memory_id ? " is-highlighted" : "");
    card.setAttribute("role", "listitem");
    card.id = `memory-card-${item.memory_id}`;
    card.dataset.memoryId = item.memory_id;

    // Top Row: Category + Subject + Actions
    const topRow = document.createElement("div");
    topRow.className = "card-top-row";

    const subjectGroup = document.createElement("div");
    subjectGroup.className = "card-subject-group";

    const cat = safeCategory(item.category);
    const badge = document.createElement("span");
    badge.className = `cat-badge cat-${cat}`;
    badge.textContent = cat;

    const subjectEl = document.createElement("span");
    subjectEl.className = "card-subject";
    subjectEl.textContent = item.subject || "Untitled";

    subjectGroup.appendChild(badge);
    subjectGroup.appendChild(subjectEl);

    const actionsGroup = document.createElement("div");
    actionsGroup.className = "card-actions";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn-ghost btn-xs";
    editBtn.textContent = "Edit";
    editBtn.disabled = state.deletingId === item.memory_id;
    editBtn.setAttribute("aria-label", `Edit memory ${item.subject}`);
    editBtn.addEventListener("click", () => {
      openEditModal(item);
    });

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "btn btn-ghost btn-xs";
    deleteBtn.textContent = "Delete";
    deleteBtn.disabled = state.deletingId === item.memory_id;
    deleteBtn.setAttribute("aria-label", `Delete memory ${item.subject}`);
    deleteBtn.addEventListener("click", () => {
      state.confirmingDeleteId = item.memory_id;
      renderMemoriesList();
    });

    actionsGroup.appendChild(editBtn);
    actionsGroup.appendChild(deleteBtn);

    topRow.appendChild(subjectGroup);
    topRow.appendChild(actionsGroup);

    // Content Paragraph
    const contentP = document.createElement("p");
    contentP.className = "card-content";
    contentP.textContent = item.content || "";

    // Metadata Footer Row
    const footerRow = document.createElement("div");
    footerRow.className = "card-footer-row";

    const metaGroup = document.createElement("div");
    metaGroup.className = "card-meta-group";

    const idCode = document.createElement("code");
    idCode.className = "mono-id";
    idCode.textContent = item.memory_id;

    const updatedSpan = document.createElement("span");
    updatedSpan.textContent = `Updated ${formatDateTimeShort(item.updated_at)}`;
    updatedSpan.title = `Created: ${item.created_at || "N/A"} | Updated: ${item.updated_at || "N/A"}`;

    metaGroup.appendChild(idCode);
    metaGroup.appendChild(updatedSpan);

    if (item.provenance && item.provenance.supersedes_memory_id) {
      const supBadge = document.createElement("span");
      supBadge.className = "supersedes-badge";
      supBadge.textContent = `Supersedes ${item.provenance.supersedes_memory_id}`;
      metaGroup.appendChild(supBadge);
    }

    footerRow.appendChild(metaGroup);

    card.appendChild(topRow);
    card.appendChild(contentP);
    card.appendChild(footerRow);

    // Inline Delete Confirmation Bar
    if (state.confirmingDeleteId === item.memory_id) {
      const confirmBar = document.createElement("div");
      confirmBar.className = "delete-confirm-bar";
      confirmBar.setAttribute("role", "region");
      confirmBar.setAttribute("aria-label", "Confirm memory deletion");

      const promptSpan = document.createElement("span");
      promptSpan.textContent =
        state.deletingId === item.memory_id
          ? "Deleting memory from FalkorDB…"
          : "Delete this memory permanently from FalkorDB?";

      const btnGroup = document.createElement("div");
      btnGroup.className = "delete-confirm-actions";

      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "btn btn-secondary btn-xs";
      cancelBtn.textContent = "Cancel";
      cancelBtn.disabled = state.deletingId === item.memory_id;
      cancelBtn.addEventListener("click", () => {
        state.confirmingDeleteId = null;
        renderMemoriesList();
      });

      const confirmBtn = document.createElement("button");
      confirmBtn.type = "button";
      confirmBtn.className = "btn btn-danger btn-xs";
      confirmBtn.textContent =
        state.deletingId === item.memory_id ? "Deleting…" : "Confirm Delete";
      confirmBtn.disabled = state.deletingId === item.memory_id;
      confirmBtn.addEventListener("click", () => {
        executeDeleteMemory(item.memory_id);
      });

      btnGroup.appendChild(cancelBtn);
      btnGroup.appendChild(confirmBtn);
      confirmBar.appendChild(promptSpan);
      confirmBar.appendChild(btnGroup);
      card.appendChild(confirmBar);
    }

    return card;
  }

  function renderMemoriesList() {
    if (!els.listContainer) return;

    els.totalBadge.textContent = String(state.total);
    if (els.mobileMemoriesCount) {
      els.mobileMemoriesCount.textContent = String(state.total);
    }

    updateCategoryPills();

    const filtered = getFilteredItems();
    const hasFilters = state.selectedCategory !== "all" || state.searchQuery.trim().length > 0;

    if (state.isLoading && state.items.length === 0) {
      els.loadingIndicator.hidden = false;
      els.emptyState.hidden = true;
      els.listContainer.replaceChildren();
      els.paginationBar.hidden = true;
      return;
    }

    els.loadingIndicator.hidden = true;

    if (filtered.length === 0) {
      els.listContainer.replaceChildren();
      els.emptyState.hidden = false;
      if (state.items.length > 0 && hasFilters) {
        els.emptyTitle.textContent = "No matching memories";
        els.emptyDesc.textContent =
          "No active memories on this page match your current category or search filter.";
        els.clearFiltersBtn.hidden = false;
      } else {
        els.emptyTitle.textContent = "No saved memories yet";
        els.emptyDesc.textContent =
          "Active facts extracted from your conversations and stored in FalkorDB for this user will appear here.";
        els.clearFiltersBtn.hidden = true;
      }
    } else {
      els.emptyState.hidden = true;
      const fragment = document.createDocumentFragment();
      filtered.forEach((item) => {
        fragment.appendChild(buildMemoryCard(item));
      });
      els.listContainer.replaceChildren(fragment);
    }

    // Pagination controls
    if (state.total > state.limit || state.offset > 0) {
      els.paginationBar.hidden = false;
      const start = state.total === 0 ? 0 : state.offset + 1;
      const end = Math.min(state.total, state.offset + state.items.length);
      els.paginationInfo.textContent = `Showing ${start}–${end} of ${state.total}`;
      els.prevPageBtn.disabled = state.isLoading || state.offset <= 0;
      els.nextPageBtn.disabled = state.isLoading || state.offset + state.limit >= state.total;
    } else {
      els.paginationBar.hidden = true;
    }
  }

  /**
   * Fetch active memories from GET /memories/{user_id}.
   */
  async function loadMemories({ resetOffset = false, silent = false } = {}) {
    if (resetOffset) {
      state.offset = 0;
    }
    if (!silent) {
      state.isLoading = true;
      renderMemoriesList();
    }
    clearMemoriesError();

    const { userId } = API.getConfig();
    const requestIdentityVersion = identityVersion;
    try {
      const data = await API.listMemories({
        userId,
        limit: state.limit,
        offset: state.offset,
      });

      if (requestIdentityVersion !== identityVersion || API.getConfig().userId !== userId) {
        return;
      }

      state.items = Array.isArray(data.items) ? data.items : [];
      state.total = typeof data.total === "number" ? data.total : state.items.length;
      state.limit = typeof data.limit === "number" ? data.limit : state.limit;
      state.offset = typeof data.offset === "number" ? data.offset : state.offset;
    } catch (err) {
      if (requestIdentityVersion !== identityVersion || API.getConfig().userId !== userId) {
        return;
      }
      // Never leave another identity's last successful list visible when this
      // identity is rejected or its request fails.
      state.items = [];
      state.total = 0;
      showMemoriesError("Failed to load saved memories", err);
    } finally {
      if (requestIdentityVersion === identityVersion && API.getConfig().userId === userId) {
        state.isLoading = false;
        renderMemoriesList();
      }
    }
  }

  function clearForIdentityChange() {
    identityVersion += 1;
    state.items = [];
    state.total = 0;
    state.offset = 0;
    state.isLoading = false;
    state.confirmingDeleteId = null;
    state.deletingId = null;
    state.editingMemory = null;
    state.isSavingEdit = false;
    state.graphNodes = [];
    state.graphEdges = [];
    state.isLoadingGraph = false;
    state.selectedGraphNode = null;
    state.highlightedMemoryId = null;
    if (els.editModal) els.editModal.hidden = true;
    clearMemoriesError();
    if (els.graphErrorBanner) els.graphErrorBanner.hidden = true;
    if (els.graphNodesCountBadge) els.graphNodesCountBadge.textContent = "0";
    renderMemoriesList();
    renderGraphNodeInspector();
    renderGraphSvg();
  }

  /**
   * Execute DELETE /memories/{memory_id} and refresh only after backend confirmation.
   */
  async function executeDeleteMemory(memoryId) {
    if (!memoryId || state.deletingId) return;
    state.deletingId = memoryId;
    clearMemoriesError();
    renderMemoriesList();

    const { userId } = API.getConfig();
    try {
      const res = await API.deleteMemory({ memoryId, userId });
      if (res && res.deleted === true) {
        state.confirmingDeleteId = null;
        state.deletingId = null;
        showToast(`Deleted memory ${res.memory_id} from FalkorDB.`);
        await loadMemories({ resetOffset: false });
        await loadGraph({ silent: true });
      }
    } catch (err) {
      state.deletingId = null;
      state.confirmingDeleteId = null;
      renderMemoriesList();
      showMemoriesError("Memory deletion failed", err);
    }
  }

  /**
   * Edit Memory Modal Handling (PATCH /memories/{memory_id})
   */
  function updateEditCounter() {
    if (!els.editContentInput || !els.editContentCounter) return;
    const len = (els.editContentInput.value || "").length;
    els.editContentCounter.textContent = `${len} / ${API.MAX_CONTENT_CHARS}`;
    els.editContentCounter.classList.toggle("is-over-limit", len > API.MAX_CONTENT_CHARS);
  }

  function openEditModal(memory) {
    if (!els.editModal || !memory) return;
    state.editingMemory = memory;
    els.editIdInput.value = memory.memory_id;
    els.editIdDisplay.textContent = memory.memory_id;
    els.editCategorySelect.value = safeCategory(memory.category);
    els.editSubjectInput.value = memory.subject || "";
    els.editContentInput.value = memory.content || "";
    els.editModalError.hidden = true;
    els.editModalErrorMessage.textContent = "";
    state.isSavingEdit = false;
    els.saveEditModalBtn.disabled = false;
    els.saveEditModalBtn.textContent = "Save Changes";
    updateEditCounter();

    els.editModal.hidden = false;
    els.editContentInput.focus();
  }

  function closeEditModal() {
    if (!els.editModal || state.isSavingEdit) return;
    els.editModal.hidden = true;
    state.editingMemory = null;
  }

  async function submitEditForm(event) {
    event.preventDefault();
    if (state.isSavingEdit || !state.editingMemory) return;

    const memoryId = els.editIdInput.value;
    const category = safeCategory(els.editCategorySelect.value);
    const subject = (els.editSubjectInput.value || "").trim();
    const content = (els.editContentInput.value || "").trim();

    if (!subject || subject.length > API.MAX_SUBJECT_CHARS) {
      els.editModalErrorTitle.textContent = "Validation error";
      els.editModalErrorMessage.textContent = `Subject must be between 1 and ${API.MAX_SUBJECT_CHARS} characters.`;
      els.editModalError.hidden = false;
      return;
    }

    if (!content || content.length > API.MAX_CONTENT_CHARS) {
      els.editModalErrorTitle.textContent = "Validation error";
      els.editModalErrorMessage.textContent = `Content must be between 1 and ${API.MAX_CONTENT_CHARS} characters.`;
      els.editModalError.hidden = false;
      return;
    }

    els.editModalError.hidden = true;
    state.isSavingEdit = true;
    els.saveEditModalBtn.disabled = true;
    els.saveEditModalBtn.textContent = "Saving…";

    const { userId } = API.getConfig();
    try {
      const response = await API.patchMemory({
        memoryId,
        userId,
        content,
        category,
        subject,
      });

      state.isSavingEdit = false;
      closeEditModal();

      const updatedId =
        response && response.memory && response.memory.memory_id
          ? response.memory.memory_id
          : memoryId;
      state.highlightedMemoryId = updatedId;
      showToast(`Updated memory ${updatedId} in FalkorDB.`);

      await loadMemories({ resetOffset: false });
      await loadGraph({ silent: true });

      setTimeout(() => {
        if (state.highlightedMemoryId === updatedId) {
          state.highlightedMemoryId = null;
          const cardEl = document.getElementById(`memory-card-${updatedId}`);
          if (cardEl) {
            cardEl.classList.remove("is-highlighted");
          }
        }
      }, 3000);
    } catch (err) {
      state.isSavingEdit = false;
      els.saveEditModalBtn.disabled = false;
      els.saveEditModalBtn.textContent = "Save Changes";
      els.editModalErrorTitle.textContent = "Update failed";
      els.editModalErrorMessage.textContent = API.formatErrorMessage(err);
      els.editModalError.hidden = false;
    }
  }

  /**
   * Locate and highlight a specific memory_id in the Saved Memories panel.
   */
  function locateMemoryById(memoryId) {
    if (!memoryId) return;
    switchSubview("list");
    state.selectedCategory = "all";
    state.searchQuery = "";
    if (els.searchInput) {
      els.searchInput.value = "";
    }
    state.highlightedMemoryId = memoryId;
    renderMemoriesList();

    if (global.MemoryMateApp && typeof global.MemoryMateApp.setMobilePane === "function") {
      global.MemoryMateApp.setMobilePane("memories");
    }

    const card = document.getElementById(`memory-card-${memoryId}`);
    if (card && typeof card.scrollIntoView === "function") {
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  /**
   * Graph Visualization (GET /graph/{user_id})
   */
  async function loadGraph({ silent = false } = {}) {
    if (!els.graphSvg) return;
    if (!silent) {
      state.isLoadingGraph = true;
      els.graphLoading.hidden = false;
    }
    els.graphErrorBanner.hidden = true;

    const { userId } = API.getConfig();
    const requestIdentityVersion = identityVersion;
    try {
      const data = await API.getGraph({ userId });
      if (requestIdentityVersion !== identityVersion || API.getConfig().userId !== userId) {
        return;
      }
      state.graphNodes = Array.isArray(data.nodes) ? data.nodes : [];
      state.graphEdges = Array.isArray(data.edges) ? data.edges : [];
      const memNodeCount = state.graphNodes.filter((n) => n.type !== "user").length;
      if (els.graphNodesCountBadge) {
        els.graphNodesCountBadge.textContent = String(memNodeCount);
      }
      renderGraphSvg();
    } catch (err) {
      if (requestIdentityVersion !== identityVersion || API.getConfig().userId !== userId) {
        return;
      }
      state.graphNodes = [];
      state.graphEdges = [];
      els.graphErrorMessage.textContent = API.formatErrorMessage(err);
      els.graphErrorBanner.hidden = false;
      if (els.graphNodesCountBadge) els.graphNodesCountBadge.textContent = "0";
      renderGraphSvg();
    } finally {
      if (requestIdentityVersion === identityVersion && API.getConfig().userId === userId) {
        state.isLoadingGraph = false;
        els.graphLoading.hidden = true;
      }
    }
  }

  function renderGraphSvg() {
    if (!els.graphSvg) return;
    const svgNS = "http://www.w3.org/2000/svg";
    els.graphSvg.replaceChildren();

    const nodes = state.graphNodes || [];
    const edges = state.graphEdges || [];
    const memoryNodes = nodes.filter((n) => n.type !== "user");

    if (memoryNodes.length === 0) {
      els.graphEmptyState.hidden = false;
      els.graphSvg.hidden = true;
      return;
    }

    els.graphEmptyState.hidden = true;
    els.graphSvg.hidden = false;

    const width = 600;
    const height = 380;
    const cx = width / 2;
    const cy = height / 2;

    // Apply zoom via viewBox
    const zoomedW = width / state.graphZoom;
    const zoomedH = height / state.graphZoom;
    const vx = cx - zoomedW / 2;
    const vy = cy - zoomedH / 2;
    els.graphSvg.setAttribute("viewBox", `${vx} ${vy} ${zoomedW} ${zoomedH}`);

    // Compute positions: user node in center, memory nodes on radial ring(s)
    const positions = new Map();
    const userNode = nodes.find((n) => n.type === "user") || {
      id: `user:${API.getConfig().userId}`,
      label: API.getConfig().userId,
      type: "user",
    };
    positions.set(userNode.id, { x: cx, y: cy, node: userNode });

    const count = memoryNodes.length;
    const radius = count <= 6 ? 128 : 145;
    memoryNodes.forEach((node, idx) => {
      const angle = (2 * Math.PI * idx) / count - Math.PI / 2;
      const r = count > 10 && idx % 2 === 1 ? radius * 0.68 : radius;
      positions.set(node.id, {
        x: cx + r * Math.cos(angle),
        y: cy + r * Math.sin(angle),
        node,
      });
    });

    const edgesGroup = document.createElementNS(svgNS, "g");
    edges.forEach((edge) => {
      const src = positions.get(edge.source);
      const tgt = positions.get(edge.target);
      if (!src || !tgt) return;

      const line = document.createElementNS(svgNS, "line");
      line.setAttribute("x1", String(src.x));
      line.setAttribute("y1", String(src.y));
      line.setAttribute("x2", String(tgt.x));
      line.setAttribute("y2", String(tgt.y));

      if (edge.type === "RELATED_TO") {
        line.setAttribute("stroke", "#D98252");
        line.setAttribute("stroke-width", "2");
        line.setAttribute("stroke-dasharray", "5,4");
      } else {
        line.setAttribute("stroke", "#cbd5e1");
        line.setAttribute("stroke-width", "1.5");
      }

      const title = document.createElementNS(svgNS, "title");
      title.textContent = `${edge.source} -[${edge.type}]-> ${edge.target}`;
      line.appendChild(title);
      edgesGroup.appendChild(line);
    });
    els.graphSvg.appendChild(edgesGroup);

    const nodesGroup = document.createElementNS(svgNS, "g");
    positions.forEach(({ x, y, node }) => {
      const g = document.createElementNS(svgNS, "g");
      const isSelected = state.selectedGraphNode && state.selectedGraphNode.id === node.id;
      g.setAttribute("class", "graph-node-group" + (isSelected ? " is-selected" : ""));
      g.setAttribute("transform", `translate(${x}, ${y})`);
      g.setAttribute("tabindex", "0");
      g.setAttribute("role", "button");
      g.setAttribute("aria-label", `${node.type} node: ${node.label}`);

      const palette = CATEGORY_COLORS[node.type] || CATEGORY_COLORS.other;
      const circle = document.createElementNS(svgNS, "circle");
      circle.setAttribute("class", "graph-node-circle");
      circle.setAttribute("r", node.type === "user" ? "22" : "16");
      circle.setAttribute("fill", palette.fill);
      circle.setAttribute("stroke", palette.stroke);
      circle.setAttribute("stroke-width", "2");

      const typeLabel = document.createElementNS(svgNS, "text");
      typeLabel.setAttribute("text-anchor", "middle");
      typeLabel.setAttribute("dy", "4");
      typeLabel.setAttribute("fill", palette.text);
      typeLabel.setAttribute("font-size", node.type === "user" ? "10" : "9");
      typeLabel.setAttribute("font-weight", "700");
      typeLabel.textContent =
        node.type === "user" ? "USER" : String(node.type || "mem").slice(0, 4).toUpperCase();

      const caption = document.createElementNS(svgNS, "text");
      caption.setAttribute("text-anchor", "middle");
      caption.setAttribute("dy", node.type === "user" ? "35" : "29");
      caption.setAttribute("fill", "#334155");
      caption.setAttribute("font-size", "10.5");
      caption.setAttribute("font-weight", "500");
      const rawText = String(node.label || node.id);
      caption.textContent = rawText.length > 24 ? `${rawText.slice(0, 22)}…` : rawText;

      const selectHandler = () => {
        state.selectedGraphNode = node;
        renderGraphNodeInspector();
        renderGraphSvg();
      };
      g.addEventListener("click", selectHandler);
      g.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectHandler();
        }
      });

      g.appendChild(circle);
      g.appendChild(typeLabel);
      g.appendChild(caption);
      nodesGroup.appendChild(g);
    });
    els.graphSvg.appendChild(nodesGroup);
  }

  function renderGraphNodeInspector() {
    if (!els.graphNodeInspector) return;
    const node = state.selectedGraphNode;
    if (!node) {
      els.graphNodeInspector.hidden = true;
      return;
    }
    const cat = node.type === "user" ? "user" : safeCategory(node.type);
    els.graphSelectedType.className = `cat-badge cat-${cat}`;
    els.graphSelectedType.textContent = cat;
    els.graphSelectedId.textContent = node.id;
    els.graphSelectedLabel.textContent = node.label;
    els.graphNodeInspector.hidden = false;
  }

  function switchSubview(subview) {
    state.activeSubview = subview === "graph" ? "graph" : "list";
    const isGraph = state.activeSubview === "graph";

    if (els.tabBtnList && els.tabBtnGraph) {
      els.tabBtnList.classList.toggle("is-active", !isGraph);
      els.tabBtnList.setAttribute("aria-selected", !isGraph ? "true" : "false");
      els.tabBtnGraph.classList.toggle("is-active", isGraph);
      els.tabBtnGraph.setAttribute("aria-selected", isGraph ? "true" : "false");
    }

    if (els.subviewList && els.subviewGraph) {
      els.subviewList.hidden = isGraph;
      els.subviewGraph.hidden = !isGraph;
    }

    if (isGraph) {
      loadGraph();
    }
  }

  function bindEvents() {
    if (els.tabBtnList) {
      els.tabBtnList.addEventListener("click", () => switchSubview("list"));
    }
    if (els.tabBtnGraph) {
      els.tabBtnGraph.addEventListener("click", () => switchSubview("graph"));
    }

    if (els.refreshBtn) {
      els.refreshBtn.addEventListener("click", () => {
        loadMemories({ resetOffset: false });
        loadGraph({ silent: true });
      });
    }

    if (els.retryBtn) {
      els.retryBtn.addEventListener("click", () => loadMemories({ resetOffset: false }));
    }

    if (els.searchInput) {
      els.searchInput.addEventListener("input", () => {
        state.searchQuery = els.searchInput.value || "";
        renderMemoriesList();
      });
    }

    if (els.categoryBar) {
      const catButtons = els.categoryBar.querySelectorAll(".cat-filter-btn");
      catButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
          state.selectedCategory = btn.getAttribute("data-category") || "all";
          renderMemoriesList();
        });
      });
    }

    if (els.clearFiltersBtn) {
      els.clearFiltersBtn.addEventListener("click", () => {
        state.selectedCategory = "all";
        state.searchQuery = "";
        if (els.searchInput) els.searchInput.value = "";
        renderMemoriesList();
      });
    }

    if (els.prevPageBtn) {
      els.prevPageBtn.addEventListener("click", () => {
        if (state.offset >= state.limit) {
          state.offset -= state.limit;
          loadMemories();
        }
      });
    }

    if (els.nextPageBtn) {
      els.nextPageBtn.addEventListener("click", () => {
        if (state.offset + state.limit < state.total) {
          state.offset += state.limit;
          loadMemories();
        }
      });
    }

    // Edit Modal Events
    if (els.editContentInput) {
      els.editContentInput.addEventListener("input", updateEditCounter);
    }
    if (els.editForm) {
      els.editForm.addEventListener("submit", submitEditForm);
    }
    if (els.closeEditModalBtn) {
      els.closeEditModalBtn.addEventListener("click", closeEditModal);
    }
    if (els.cancelEditModalBtn) {
      els.cancelEditModalBtn.addEventListener("click", closeEditModal);
    }
    if (els.editModal) {
      els.editModal.addEventListener("click", (event) => {
        if (event.target === els.editModal) {
          closeEditModal();
        }
      });
    }
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && els.editModal && !els.editModal.hidden) {
        closeEditModal();
      }
    });

    // Graph Controls
    if (els.graphZoomInBtn) {
      els.graphZoomInBtn.addEventListener("click", () => {
        state.graphZoom = Math.min(2.2, Number((state.graphZoom + 0.2).toFixed(2)));
        renderGraphSvg();
      });
    }
    if (els.graphZoomOutBtn) {
      els.graphZoomOutBtn.addEventListener("click", () => {
        state.graphZoom = Math.max(0.6, Number((state.graphZoom - 0.2).toFixed(2)));
        renderGraphSvg();
      });
    }
    if (els.graphResetBtn) {
      els.graphResetBtn.addEventListener("click", () => {
        state.graphZoom = 1;
        state.selectedGraphNode = null;
        renderGraphNodeInspector();
        renderGraphSvg();
      });
    }
    if (els.graphRefreshBtn) {
      els.graphRefreshBtn.addEventListener("click", () => loadGraph());
    }
    if (els.retryGraphBtn) {
      els.retryGraphBtn.addEventListener("click", () => loadGraph());
    }
    if (els.closeGraphInspectorBtn) {
      els.closeGraphInspectorBtn.addEventListener("click", () => {
        state.selectedGraphNode = null;
        renderGraphNodeInspector();
        renderGraphSvg();
      });
    }
  }

  function init() {
    cacheElements();
    bindEvents();
  }

  global.MemoryMateMemories = Object.freeze({
    init,
    loadMemories,
    loadGraph,
    clearForIdentityChange,
    locateMemoryById,
    switchSubview,
  });
})(window);
