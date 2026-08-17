(function () {
  "use strict";

  function byId(id) {
    return document.getElementById(id);
  }

  function toast(msg, level) {
    if (window.showPageToast) {
      window.showPageToast(msg, level || "info");
      return;
    }
    window.alert(msg);
  }

  async function requestJson(url, options) {
    const resp = await fetch(url, options || {});
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(String((data && (data.message || data.detail)) || `请求失败(${resp.status})`));
    }
    return data;
  }

  const els = {
    projectId: byId("pkbProjectId"),
    backToStatsBtn: byId("pkbBackToStatsBtn"),
    refreshBtn: byId("pkbRefreshBtn"),
    ingestAllBtn: byId("pkbIngestAllBtn"),
    retryBtn: byId("pkbRetryBtn"),
    backfillBtn: byId("pkbBackfillBtn"),
    promoteBtn: byId("pkbPromoteBtn"),
    trainHistorical: byId("pkbTrainHistorical"),
    syncMsg: byId("pkbSyncMsg"),
    missingDocHint: byId("pkbMissingDocHint"),
    statsCard: byId("pkbStatsCard"),
    statsCount: byId("pkbStatsCount"),
    statsBody: byId("pkbStatsBody"),
    detailCard: byId("pkbDetailCard"),
    count: byId("pkbCount"),
    body: byId("pkbBody"),
    historyWrap: byId("pkbHistoryWrap"),
    history: byId("pkbHistory"),
  };

  let latestItems = [];
  let statsItems = [];
  let actionBusy = false;

  function selectedProjectId() {
    return String((els.projectId && els.projectId.value) || "").trim();
  }

  function setProjectActionsEnabled(enabled) {
    [els.retryBtn, els.backfillBtn, els.promoteBtn, els.trainHistorical].forEach((el) => {
      if (el) el.disabled = !enabled;
    });
  }

  function setViewMode(projectId) {
    const hasProject = !!projectId;
    if (els.statsCard) els.statsCard.classList.toggle("d-none", hasProject);
    if (els.detailCard) els.detailCard.classList.toggle("d-none", !hasProject);
    if (els.backToStatsBtn) els.backToStatsBtn.classList.toggle("d-none", !hasProject);
    if (els.ingestAllBtn) els.ingestAllBtn.classList.toggle("d-none", hasProject);
    if (els.refreshBtn) els.refreshBtn.textContent = hasProject ? "刷新记录" : "刷新统计";
    setProjectActionsEnabled(hasProject);
    if (!hasProject) {
      if (els.missingDocHint) {
        els.missingDocHint.textContent = "";
        els.missingDocHint.classList.add("d-none");
      }
      if (els.historyWrap) els.historyWrap.classList.add("d-none");
    }
  }

  function syncBadge(state) {
    const s = String(state || "").toLowerCase();
    if (s === "synced") return '<span class="badge text-bg-success">已同步</span>';
    if (s === "failed") return '<span class="badge text-bg-danger">失败</span>';
    if (s === "syncing") return '<span class="badge text-bg-info">同步中</span>';
    if (s === "pending") return '<span class="badge text-bg-secondary">待同步</span>';
    if (s === "ready") return '<span class="badge text-bg-primary">待入库</span>';
    if (s === "missing_number") return '<span class="badge text-bg-warning">缺编号</span>';
    if (s === "no_file") return '<span class="badge text-bg-light text-muted border">无文件</span>';
    return '<span class="badge text-bg-secondary">待同步</span>';
  }

  function statusBadge(label, status) {
    const ended = String(status || "").toLowerCase() === "ended";
    const cls = ended ? "text-bg-secondary" : "text-bg-primary";
    return `<span class="badge ${cls}">${escapeHtml(label || (ended ? "已结束" : "进行中"))}</span>`;
  }

  function formatTime(value) {
    return String(value || "").replace("T", " ").slice(0, 19) || "-";
  }

  function renderStats(totals) {
    const t = totals || {};
    const projectCount = Number(t.projectCount || statsItems.length || 0);
    const taskCount = Number(t.taskCount || 0);
    const syncedCount = Number(t.syncedCount || 0);
    const failedCount = Number(t.failedCount || 0);
    const pendingCount = Number(t.pendingCount || 0);
    const readyCount = Number(t.readyCount || 0);
    const missingCount = Number(t.missingDocumentNumberCount || 0);
    const noFileCount = Number(t.noFileCount || 0);
    if (els.statsCount) {
      els.statsCount.textContent = `${projectCount} 个项目 · 任务 ${taskCount} 条`;
    }
    if (!els.statsBody) return;
    if (!statsItems.length) {
      els.statsBody.innerHTML = '<tr><td colspan="11" class="text-muted small text-center py-3">当前没有可查看的项目</td></tr>';
      return;
    }
    const rowsHtml = statsItems
      .map((item) => {
        const pid = String(item.projectId || "");
        const name = String(item.projectName || "-");
        const code = String(item.projectCode || "").trim();
        const country = String(item.registeredCountry || "").trim();
        const extra = [code, country].filter(Boolean).join(" · ");
        const failed = Number(item.failedCount || 0);
        const missing = Number(item.missingDocumentNumberCount || 0);
        const ready = Number(item.readyCount || 0);
        const noFile = Number(item.noFileCount || 0);
        const pending = Number(item.pendingCount || 0);
        const canIngest = ready + pending + failed > 0;
        const actions = [];
        if (canIngest) {
          actions.push(`<button type="button" class="btn btn-primary btn-sm py-0" data-ingest-project="${escapeHtml(pid)}">入库并同步</button>`);
        }
        if (failed > 0) {
          actions.push(`<button type="button" class="btn btn-outline-warning btn-sm py-0" data-retry-project="${escapeHtml(pid)}">重试失败</button>`);
        }
        actions.push(`<button type="button" class="btn btn-outline-primary btn-sm py-0" data-select-project="${escapeHtml(pid)}">查看记录</button>`);
        return `<tr data-select-project="${escapeHtml(pid)}" style="cursor:pointer;">
          <td>
            <div class="small fw-semibold">${escapeHtml(name)}</div>
            ${extra ? `<div class="small text-muted">${escapeHtml(extra)}</div>` : ""}
          </td>
          <td>${statusBadge(item.statusLabel, item.status)}</td>
          <td class="small fw-semibold">${Number(item.taskCount || 0)}</td>
          <td class="small text-success">${Number(item.syncedCount || 0)}</td>
          <td class="small ${failed ? "text-danger fw-semibold" : ""}">${failed}</td>
          <td class="small">${pending}</td>
          <td class="small ${ready ? "text-primary fw-semibold" : ""}">${ready}</td>
          <td class="small ${missing ? "text-warning fw-semibold" : ""}">${missing}</td>
          <td class="small text-muted">${noFile}</td>
          <td class="small text-muted">${escapeHtml(formatTime(item.lastUpdatedAt))}</td>
          <td><div class="d-flex flex-wrap gap-1">${actions.join("")}</div></td>
        </tr>`;
      })
      .join("");
    const foot = `<tr class="table-light">
      <td class="small fw-semibold">合计</td>
      <td></td>
      <td class="small fw-semibold">${taskCount}</td>
      <td class="small">${syncedCount}</td>
      <td class="small">${failedCount}</td>
      <td class="small">${pendingCount}</td>
      <td class="small">${readyCount}</td>
      <td class="small">${missingCount}</td>
      <td class="small">${noFileCount}</td>
      <td></td>
      <td></td>
    </tr>`;
    els.statsBody.innerHTML = rowsHtml + foot;
    if (els.syncMsg) {
      els.syncMsg.textContent = `共 ${projectCount} 个项目，任务 ${taskCount} 条 = 已同步 ${syncedCount} + 失败 ${failedCount} + 待同步 ${pendingCount} + 待入库 ${readyCount} + 缺编号 ${missingCount} + 无文件 ${noFileCount}`;
    }
  }

  function renderTable() {
    if (els.count) els.count.textContent = `${latestItems.length} 条`;
    if (!els.body) return;
    const projectId = selectedProjectId();
    if (!projectId) {
      els.body.innerHTML = '<tr><td colspan="7" class="text-muted small text-center py-3">请选择项目后查看</td></tr>';
      return;
    }
    if (!latestItems.length) {
      els.body.innerHTML = '<tr><td colspan="7" class="text-muted small text-center py-3">该项目暂无任务记录</td></tr>';
      return;
    }
    els.body.innerHTML = latestItems
      .map((item, idx) => {
        const updated = formatTime(item.sourceUpdatedAt || item.updatedAt);
        const err = String(item.syncError || "").trim();
        const docNo = String(item.documentNumber || "").trim();
        const canHistory = !!String(item.normalizedDocumentNumber || docNo).trim();
        const bucket = String(item.syncState || item.bucket || "").toLowerCase();
        const canIngest = bucket === "ready" || bucket === "pending" || bucket === "failed";
        const rowActions = [];
        if (canIngest) {
          rowActions.push(`<button type="button" class="btn btn-primary btn-sm py-0" data-ingest-current="1">入库/同步</button>`);
        }
        if (canHistory) {
          rowActions.push(`<button type="button" class="btn btn-outline-secondary btn-sm py-0" data-history="${idx}">历史</button>`);
        }
        return `<tr>
          <td class="font-monospace small">${escapeHtml(docNo || "（缺编号）")}</td>
          <td class="small">${escapeHtml(item.title || "-")}</td>
          <td class="font-monospace small">${escapeHtml(item.version || "-")}</td>
          <td class="small">${escapeHtml(item.status || "-")}</td>
          <td class="small">${syncBadge(item.syncState || item.bucket)}${err ? `<div class="text-danger mt-1">${escapeHtml(err)}</div>` : ""}</td>
          <td class="small text-muted">${escapeHtml(updated)}</td>
          <td>${rowActions.length ? `<div class="d-flex flex-wrap gap-1">${rowActions.join("")}</div>` : '<span class="text-muted small">-</span>'}</td>
        </tr>`;
      })
      .join("");
    Array.from(els.body.querySelectorAll("button[data-history]")).forEach((btn) => {
      btn.addEventListener("click", async () => {
        const idx = Number(btn.getAttribute("data-history"));
        if (Number.isNaN(idx) || !latestItems[idx]) return;
        try {
          const p = selectedProjectId();
          const d = String(latestItems[idx].normalizedDocumentNumber || latestItems[idx].documentNumber || "").trim();
          const data = await requestJson(`/api/project-kb/documents/history?projectId=${encodeURIComponent(p)}&documentNumber=${encodeURIComponent(d)}`);
          if (els.historyWrap) els.historyWrap.classList.remove("d-none");
          if (els.history) els.history.textContent = JSON.stringify(data.items || [], null, 2);
        } catch (e) {
          toast(e.message || "加载历史失败", "danger");
        }
      });
    });
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function loadProjects() {
    const arr = await requestJson("/api/projects");
    const current = selectedProjectId();
    const options = ['<option value="">全部项目（统计概览）</option>'];
    (Array.isArray(arr) ? arr : []).forEach((p) => {
      const id = String(p.id || "");
      const name = String(p.name || "");
      if (!id || !name) return;
      const selected = id === current ? " selected" : "";
      options.push(`<option value="${escapeHtml(id)}"${selected}>${escapeHtml(name)}</option>`);
    });
    els.projectId.innerHTML = options.join("");
  }

  async function loadStats() {
    const data = await requestJson("/api/project-kb/stats");
    statsItems = Array.isArray(data.items) ? data.items : [];
    renderStats(data.totals || {});
  }

  async function loadLatest(opts) {
    const projectId = selectedProjectId();
    const refresh = !!(opts && opts.refresh);
    setViewMode(projectId);
    if (!projectId) {
      latestItems = [];
      renderTable();
      await loadStats();
      return;
    }
    const qs = [`projectId=${encodeURIComponent(projectId)}`];
    if (refresh) qs.push("refresh=1");
    const data = await requestJson(`/api/project-kb/documents/latest?${qs.join("&")}`);
    latestItems = Array.isArray(data.items) ? data.items : [];
    renderTable();
    if (els.syncMsg) {
      const queued = Number(data.queued || 0);
      const taskCount = Number(data.taskCount || latestItems.length || 0);
      const failed = Number(data.failedCount || 0);
      const ready = Number(data.readyCount || 0);
      const missing = Number(data.missingDocumentNumberCount || 0);
      const noFile = Number(data.noFileCount || 0);
      const parts = [`任务 ${taskCount} 条`];
      if (refresh) parts.unshift(`已入队 ${queued} 条`);
      if (failed > 0) parts.push(`失败 ${failed}`);
      if (ready > 0) parts.push(`待入库 ${ready}`);
      if (missing > 0) parts.push(`缺编号 ${missing}`);
      if (noFile > 0) parts.push(`无文件 ${noFile}`);
      els.syncMsg.textContent = parts.join("，");
    }
    if (els.missingDocHint) {
      const missCount = Number(data.missingDocumentNumberCount || 0);
      if (missCount > 0) {
        const names = (Array.isArray(data.missingDocumentNumberItems) ? data.missingDocumentNumberItems : [])
          .slice(0, 5)
          .map((x) => String((x && x.fileName) || "").trim())
          .filter(Boolean);
        const preview = names.length ? `（例如：${names.join("、")}）` : "";
        els.missingDocHint.textContent = `有 ${missCount} 条任务因缺少文件编号未入项目知识库，请先在页面1补齐文件编号后再同步。${preview}`;
        els.missingDocHint.classList.remove("d-none");
      } else {
        els.missingDocHint.textContent = "";
        els.missingDocHint.classList.add("d-none");
      }
    }
  }

  function selectProject(projectId) {
    if (!els.projectId) return;
    els.projectId.value = String(projectId || "");
    loadLatest().catch((e) => toast(e.message || "加载失败", "danger"));
  }

  async function retrySync(projectId) {
    const pid = String(projectId || selectedProjectId() || "").trim();
    if (!pid) throw new Error("请先选择项目");
    if (actionBusy) return;
    actionBusy = true;
    setActionBusy(true);
    try {
      const data = await requestJson("/api/project-kb/sync/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId: pid, forceRetry: true }),
      });
      const msg = data.message || `已处理 ${data.processed || 0} 条，成功 ${data.succeeded || 0} 条`;
      if (els.syncMsg) els.syncMsg.textContent = msg;
      toast(msg, Number(data.failed || 0) > 0 ? "warning" : "success");
      if (selectedProjectId()) await loadLatest();
      else await loadStats();
    } finally {
      actionBusy = false;
      setActionBusy(false);
    }
  }

  async function ingestProject(projectId) {
    const pid = String(projectId || selectedProjectId() || "").trim();
    if (!pid) throw new Error("请先选择项目");
    if (actionBusy) return;
    actionBusy = true;
    setActionBusy(true);
    try {
      const data = await requestJson("/api/project-kb/backfill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId: pid }),
      });
      const msg = data.message || `已入库并同步到项目知识库：处理 ${data.processed || 0} 条，成功 ${data.succeeded || 0} 条`;
      if (els.syncMsg) els.syncMsg.textContent = msg;
      toast(msg, Number(data.failed || 0) > 0 ? "warning" : "success");
      if (selectedProjectId()) await loadLatest();
      else await loadStats();
    } finally {
      actionBusy = false;
      setActionBusy(false);
    }
  }

  async function ingestAllReady() {
    const targets = statsItems.filter((item) => {
      return (
        Number(item.readyCount || 0) + Number(item.pendingCount || 0) + Number(item.failedCount || 0) > 0
      );
    });
    if (!targets.length) throw new Error("当前没有待入库或待同步的项目");
    if (actionBusy) return;
    actionBusy = true;
    setActionBusy(true);
    try {
      let ok = 0;
      for (let i = 0; i < targets.length; i += 1) {
        const item = targets[i];
        if (els.syncMsg) {
          els.syncMsg.textContent = `正在入库并同步（${i + 1}/${targets.length}）：${item.projectName || ""}`;
        }
        await requestJson("/api/project-kb/backfill", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projectId: item.projectId }),
        });
        ok += 1;
      }
      toast(`已对 ${ok} 个项目执行入库并同步`, "success");
      await loadStats();
    } finally {
      actionBusy = false;
      setActionBusy(false);
    }
  }

  function setActionBusy(busy) {
    if (els.ingestAllBtn) els.ingestAllBtn.disabled = busy;
    if (els.backfillBtn) els.backfillBtn.disabled = busy || !selectedProjectId();
    if (els.retryBtn) els.retryBtn.disabled = busy || !selectedProjectId();
    if (els.refreshBtn) els.refreshBtn.disabled = busy;
    if (els.promoteBtn) els.promoteBtn.disabled = busy || !selectedProjectId();
  }

  async function backfillSync() {
    await ingestProject(selectedProjectId());
  }

  async function promoteToControlled() {
    const projectId = selectedProjectId();
    if (!projectId) throw new Error("请先选择项目");
    const trainHistorical = !!(els.trainHistorical && els.trainHistorical.checked);
    const data = await requestJson("/api/project-kb/promote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, trainHistorical }),
    });
    if (els.syncMsg) {
      const hs = data.historicalSync || {};
      if (trainHistorical) {
        els.syncMsg.textContent = `${data.message || "同步完成"}（历史库成功 ${hs.succeeded || 0} 条）`;
      } else {
        els.syncMsg.textContent = data.message || "同步完成";
      }
    }
  }

  function bind() {
    els.projectId.addEventListener("change", () => {
      loadLatest().catch((e) => toast(e.message || "加载失败", "danger"));
    });
    if (els.backToStatsBtn) {
      els.backToStatsBtn.addEventListener("click", () => selectProject(""));
    }
    if (els.statsBody) {
      els.statsBody.addEventListener("click", (ev) => {
        const target = ev.target;
        if (!target || !target.closest) return;
        const ingestHit = target.closest("[data-ingest-project]");
        if (ingestHit) {
          ev.preventDefault();
          ev.stopPropagation();
          ingestProject(ingestHit.getAttribute("data-ingest-project") || "").catch((e) => toast(e.message || "入库失败", "danger"));
          return;
        }
        const retryHit = target.closest("[data-retry-project]");
        if (retryHit) {
          ev.preventDefault();
          ev.stopPropagation();
          retrySync(retryHit.getAttribute("data-retry-project") || "").catch((e) => toast(e.message || "重试失败", "danger"));
          return;
        }
        const hit = target.closest("[data-select-project]");
        if (!hit) return;
        ev.preventDefault();
        selectProject(hit.getAttribute("data-select-project") || "");
      });
    }
    if (els.body) {
      els.body.addEventListener("click", (ev) => {
        const target = ev.target;
        if (!target || !target.closest) return;
        if (target.closest("[data-ingest-current]")) {
          ev.preventDefault();
          ingestProject(selectedProjectId()).catch((e) => toast(e.message || "入库失败", "danger"));
        }
      });
    }
    if (els.ingestAllBtn) {
      els.ingestAllBtn.addEventListener("click", () => {
        ingestAllReady().catch((e) => toast(e.message || "入库失败", "danger"));
      });
    }
    els.refreshBtn.addEventListener("click", () => {
      const refresh = !!selectedProjectId();
      loadLatest({ refresh }).catch((e) => toast(e.message || "刷新失败", "danger"));
    });
    els.retryBtn.addEventListener("click", () => {
      retrySync().catch((e) => toast(e.message || "重试失败", "danger"));
    });
    els.backfillBtn.addEventListener("click", () => {
      backfillSync().catch((e) => toast(e.message || "回填失败", "danger"));
    });
    if (els.promoteBtn) {
      els.promoteBtn.addEventListener("click", () => {
        promoteToControlled().catch((e) => toast(e.message || "同步失败", "danger"));
      });
    }
  }

  async function init() {
    setViewMode("");
    renderTable();
    bind();
    await loadProjects();
    await loadLatest();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => init().catch((e) => toast(e.message || "初始化失败", "danger")));
  } else {
    init().catch((e) => toast(e.message || "初始化失败", "danger"));
  }
})();
