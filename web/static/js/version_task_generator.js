(function () {
  "use strict";

  function byId(id) {
    return document.getElementById(id);
  }

  function toast(msg, level) {
    const lv = level || "info";
    if (lv === "info") {
      note(msg);
      return;
    }
    if (window.showPageToast) {
      window.showPageToast(msg, lv);
      return;
    }
    note(msg);
  }

  function note(msg) {
    const el = document.getElementById("vtgPreviewOpStatus");
    if (el) el.textContent = msg || "";
  }

  function setButtonBusy(btn, busy, busyText) {
    if (!btn) return;
    if (busy) {
      if (btn.dataset.origHtml == null) btn.dataset.origHtml = btn.innerHTML;
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
      btn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
        (busyText || "处理中…");
    } else {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      if (btn.dataset.origHtml != null) {
        btn.innerHTML = btn.dataset.origHtml;
        delete btn.dataset.origHtml;
      }
    }
  }

  async function withButtonBusy(btn, busyText, fn) {
    if (btn && btn.getAttribute("aria-busy") === "true") {
      return undefined;
    }
    setButtonBusy(btn, true, busyText);
    try {
      return await fn();
    } finally {
      setButtonBusy(btn, false);
    }
  }

  const els = {
    fromVersion: byId("vtgFromVersion"),
    toVersion: byId("vtgToVersion"),
    productName: byId("vtgProductName"),
    intermediate: byId("vtgIntermediateVersions"),
    versionDatesBody: byId("vtgVersionDatesBody"),
    saveRecordsBtn: byId("vtgSaveRecordsBtn"),
    reloadRecordsBtn: byId("vtgReloadRecordsBtn"),
    addRecordBtn: byId("vtgAddRecordBtn"),
    loadRecordsToChainBtn: byId("vtgLoadRecordsToChainBtn"),
    syncChainToRecordsBtn: byId("vtgSyncChainToRecordsBtn"),
    batchProjectId: byId("vtgBatchProjectId"),
    batchStatus: byId("vtgBatchStatus"),
    batchApplyBtn: byId("vtgBatchApplyBtn"),
    batchSaveBtn: byId("vtgBatchSaveBtn"),
    savedRecordsBody: byId("vtgSavedRecordsBody"),
    savedRecordsCount: byId("vtgSavedRecordsCount"),
    suggestBtn: byId("vtgSuggestDateBtn"),
    diagnoseBtn: byId("vtgDiagnoseBtn"),
    diagnoseWrap: byId("vtgDiagnoseWrap"),
    diagnoseJson: byId("vtgDiagnoseJson"),
    previewBtn: byId("vtgPreviewBtn"),
    suggestWrap: byId("vtgSuggestWrap"),
    suggestList: byId("vtgSuggestList"),
    previewMeta: byId("vtgPreviewMeta"),
    previewSaveBanner: byId("vtgPreviewSaveBanner"),
    previewVersionBar: byId("vtgPreviewVersionBar"),
    previewBody: byId("vtgPreviewBody"),
    previewTableWrap: byId("vtgPreviewTableWrap"),
    previewCount: byId("vtgPreviewCount"),
    previewOpStatus: byId("vtgPreviewOpStatus"),
    previewSelectAll: byId("vtgPreviewSelectAll"),
    previewUnselectAll: byId("vtgPreviewUnselectAll"),
    previewUnselectVisible: byId("vtgPreviewUnselectVisible"),
    previewSelectHint: byId("vtgPreviewSelectHint"),
    previewHeadCheck: byId("vtgPreviewHeadCheck"),
    applyBtn: byId("vtgApplyBtn"),
    exportMasterListBtn: byId("vtgExportMasterListBtn"),
    exportTechListBtn: byId("vtgExportTechListBtn"),
    exportPreviewExcelBtn: byId("vtgExportPreviewExcelBtn"),
    applyModeReplace: byId("vtgApplyModeReplace"),
    applyModeIncrement: byId("vtgApplyModeIncrement"),
    savePreviewEditsBtn: byId("vtgSavePreviewEditsBtn"),
    syncDocMetaBtn: byId("vtgSyncDocMetaBtn"),
    addPreviewRowBtn: byId("vtgAddPreviewRowBtn"),
    addPreviewPanel: byId("vtgAddPreviewPanel"),
    addPreviewHint: byId("vtgAddPreviewHint"),
    addAnchorSelect: byId("vtgAddAnchorSelect"),
    addPlaceSelect: byId("vtgAddPlaceSelect"),
    addPreviewConfirmBtn: byId("vtgAddPreviewConfirmBtn"),
    addPreviewCancelBtn: byId("vtgAddPreviewCancelBtn"),
    movePreviewBtn: byId("vtgMovePreviewBtn"),
    movePreviewPanel: byId("vtgMovePreviewPanel"),
    movePreviewHint: byId("vtgMovePreviewHint"),
    moveAnchorFilter: byId("vtgMoveAnchorFilter"),
    moveAnchorSelect: byId("vtgMoveAnchorSelect"),
    movePlaceSelect: byId("vtgMovePlaceSelect"),
    movePreviewConfirmBtn: byId("vtgMovePreviewConfirmBtn"),
    movePreviewCancelBtn: byId("vtgMovePreviewCancelBtn"),
    copyPreviewBtn: byId("vtgCopyPreviewBtn"),
    copyPreviewPanel: byId("vtgCopyPreviewPanel"),
    copyPreviewHint: byId("vtgCopyPreviewHint"),
    copyFromVersion: byId("vtgCopyFromVersion"),
    copyToVersion: byId("vtgCopyToVersion"),
    copySelectedOnly: byId("vtgCopySelectedOnly"),
    copyPreviewConfirmBtn: byId("vtgCopyPreviewConfirmBtn"),
    copyPreviewCancelBtn: byId("vtgCopyPreviewCancelBtn"),
    batchDueDateBtn: byId("vtgBatchDueDateBtn"),
    batchDueDatePanel: byId("vtgBatchDueDatePanel"),
    batchDueDateHint: byId("vtgBatchDueDateHint"),
    batchDueDateInput: byId("vtgBatchDueDateInput"),
    batchDueDateConfirmBtn: byId("vtgBatchDueDateConfirmBtn"),
    batchDueDateCancelBtn: byId("vtgBatchDueDateCancelBtn"),
    deleteVersionBtn: byId("vtgDeleteVersionBtn"),
    deleteVersionPanel: byId("vtgDeleteVersionPanel"),
    deleteVersionHint: byId("vtgDeleteVersionHint"),
    deleteVersionSelect: byId("vtgDeleteVersionSelect"),
    deleteVersionConfirmBtn: byId("vtgDeleteVersionConfirmBtn"),
    deleteVersionCancelBtn: byId("vtgDeleteVersionCancelBtn"),
    clearColFiltersBtn: byId("vtgClearColFiltersBtn"),
    locateHint: byId("vtgLocateHint"),
    changeLog: byId("vtgChangeLog"),
    changeLogPager: byId("vtgChangeLogPager"),
    projectId: byId("vtgProjectId"),
    applyMsg: byId("vtgApplyMsg"),
    applyCount: byId("vtgApplyCount"),
    applyPendingList: byId("vtgApplyPendingList"),
    applyBatchList: byId("vtgApplyBatchList"),
    applyBatchReload: byId("vtgApplyBatchReload"),
    changeLogCount: byId("vtgChangeLogCount"),
    authorConflictModal: byId("vtgAuthorConflictModal"),
    authorConflictList: byId("vtgAuthorConflictList"),
    authorConflictCancel: byId("vtgAuthorConflictCancel"),
    authorConflictCreate: byId("vtgAuthorConflictCreate"),
    authorConflictReplace: byId("vtgAuthorConflictReplace"),
  };

  const PRODUCT_NAME_LS_PREFIX = "vtg.productName.";
  const LAST_PROJECT_LS_KEY = "vtg.lastProjectId";
  const PREVIEW_SELECTED_LS_PREFIX = "vtg.previewSelected.v1.";

  let currentJobId = "";
  let originalPreviewItems = [];
  let rulePreviewItems = [];
  let previewItems = [];
  let previewVersionFilter = "";
  const previewCollapsedVersions = new Set();
  const previewSelectedKeys = new Set();
  let previewSelectionPersistMuted = false;
  let applyLedgerCache = { groups: [], batches: [], issuedItems: [] };
  let applyLedgerLoaded = false;
  const issuedKeySet = new Set();
  const applyLedgerExpandedKeys = new Set();
  let previewColSort = null;
  let previewColFilters = {};
  let previewFilterTimer = 0;
  let previewLocateOriginKey = "";
  let previewLocateCandidateIdx = -1;
  let previewLocateTimer = 0;
  const PREVIEW_COLSPAN = 21;
  const DEFAULT_VERSION_TASK_TYPE = "初稿待编写";
  const LEGACY_AUTO_VERSION_TASK_TYPES = {
    版本变更任务: true,
    归档文件: true,
    变更控制流程: true,
    缺陷管理流程: true,
    生产发布流程: true,
  };
  const PREVIEW_COL_KEYS = [
    "check",
    "sortOrder",
    "recordStatus",
    "applied",
    "isSystemRecord",
    "changeKind",
    "fileName",
    "taskType",
    "targetVersion",
    "author",
    "dueDate",
    "documentDisplayDate",
    "belongingModule",
    "archiveFrequency",
    "triggeredBy",
    "changeReason",
    "documentNumber",
    "fileVersion",
    "explanation",
    "notes",
    "action",
  ];
  const PREVIEW_COL_ORDER_LS = "vtg.previewColOrder.v4";
  let previewColOrder = [];
  let previewColDragKey = "";
  let previewColDropKey = "";
  let previewColDragMoved = false;
  let previewColDragOrigin = null;
  let previewColSuppressSort = false;
  const PREVIEW_VISIBLE_ROWS = 10;
  const PREVIEW_CHAPTER_ORDER = [
    "软件变更管理",
    "系统追溯",
    "缺陷管理",
    "软件生产/发布管理",
  ];
  const COLLECTION_PAGE_SIZE = 20;
  let previewRulesOpen = false;
  let collectionHistory = [];
  let collectionPage = 1;
  let collectionLoadError = "";
  const CHANGE_KIND_LABELS = {
    add: "新增",
    update: "已修改",
    delete: "已删除",
  };
  const CHANGE_FIELD_LABELS = {
    fileName: "文件名",
    documentNumber: "文件编号",
    fileVersion: "文件版本号",
    taskType: "任务类型",
    targetVersion: "目标版本",
    author: "责任人",
    dueDate: "完成日期",
    documentDisplayDate: "文档日期",
    belongingModule: "模块",
    explanation: "说明",
    notes: "备注",
    recordStatus: "状态",
    chapter: "章节分类",
    isSystemRecord: "体系记录",
  };
  const RECORD_STATUS_LABELS = {
    adopt: "选用",
    discard: "弃用",
    pending: "待定",
  };
  let savedRecords = [];
  const projectsById = new Map();
  const versionDateValues = new Map();
  const projectVersionStatus = new Map();

  function inputValue(el) {
    return String((el && el.value) || "").trim();
  }

  function selectedProjectId() {
    return inputValue(els.projectId);
  }

  function setProjectSelectValue(id) {
    if (!els.projectId) return "";
    const pid = String(id || "").trim();
    if (!pid) {
      els.projectId.value = "";
      return "";
    }
    const ok = Array.from(els.projectId.options).some((opt) => opt.value === pid);
    if (!ok) return "";
    els.projectId.value = pid;
    return pid;
  }

  function currentRegistrationCountry() {
    const p = projectsById.get(selectedProjectId());
    return String((p && (p.registeredCountry || p.country)) || "").trim();
  }

  function buildSuggestPayload(targetVersion) {
    const projectId = selectedProjectId() || null;
    let productName = inputValue(els.productName);
    // 未填产品名时用所选项目名称回填（与后端兜底一致）
    if (!productName && projectId) {
      const p = projectsById.get(projectId);
      const fromProject = String((p && p.name) || "").trim();
      if (fromProject) {
        productName = fromProject;
        if (els.productName && !inputValue(els.productName)) {
          els.productName.value = fromProject;
        }
      }
    }
    return {
      productName,
      fromVersion: inputValue(els.fromVersion),
      toVersion: inputValue(els.toVersion),
      intermediateVersions: parseIntermediateVersions(),
      targetVersion: targetVersion || null,
      projectId,
      registrationCountry: currentRegistrationCountry(),
    };
  }

  function parseIntermediateVersions() {
    const raw = String((els.intermediate && els.intermediate.value) || "");
    return raw
      .split(/[\n,，;]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function buildVersionChainInputs() {
    const from = inputValue(els.fromVersion);
    const to = inputValue(els.toVersion);
    if (!from || !to) {
      return [];
    }
    const mids = parseIntermediateVersions();
    const chain = [from];
    mids.forEach((v) => {
      if (v && chain[chain.length - 1] !== v) {
        chain.push(v);
      }
    });
    if (chain[chain.length - 1] !== to) {
      chain.push(to);
    }
    return chain;
  }

  function statusLabel(status) {
    const key = String(status || "none").toLowerCase();
    if (key === "generated") {
      return '<span class="badge text-bg-success">已下发</span>';
    }
    if (key === "previewed") {
      return '<span class="badge text-bg-info">已预览</span>';
    }
    return '<span class="badge text-bg-secondary">未生成</span>';
  }


  function syncVersionDateValuesFromDom() {
    if (!els.versionDatesBody) return;
    Array.from(els.versionDatesBody.querySelectorAll("tr[data-vtg-version]")).forEach((row) => {
      const version = String(row.getAttribute("data-vtg-version") || "").trim();
      const input = row.querySelector("input[data-vtg-date]");
      if (!version || !input) return;
      versionDateValues.set(version, String(input.value || "").trim());
    });
  }

  function renderVersionDatesTable() {
    if (!els.versionDatesBody) return;
    syncVersionDateValuesFromDom();
    const chain = buildVersionChainInputs();
    if (!chain.length) {
      els.versionDatesBody.innerHTML =
        '<tr><td colspan="4" class="text-muted small">请先填写开始版本号与最新版本号</td></tr>';
      return;
    }
    const rows = chain
      .map((version) => {
        const safeVersion = version.replace(/"/g, "&quot;");
        const dateValue = String(versionDateValues.get(version) || "");
        const status = projectVersionStatus.get(version) || "none";
        return `<tr data-vtg-version="${safeVersion}">
          <td class="font-monospace small">${safeVersion}</td>
          <td data-vtg-status>${statusLabel(status)}</td>
          <td>
            <input type="date" class="form-control form-control-sm" data-vtg-date value="${dateValue}">
          </td>
          <td>
            <button type="button" class="btn btn-outline-secondary btn-sm" data-vtg-suggest-one="${safeVersion}">检索</button>
          </td>
        </tr>`;
      })
      .join("");
    els.versionDatesBody.innerHTML = rows;
    Array.from(els.versionDatesBody.querySelectorAll("button[data-vtg-suggest-one]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const version = String(btn.getAttribute("data-vtg-suggest-one") || "").trim();
        if (!version) return;
        withButtonBusy(btn, "检索中…", () => suggestReleaseDate(version)).catch((e) =>
          toast(e.message || "检索失败", "danger")
        );
      });
    });
  }

  function projectOptionsHtml(selectedId) {
    const selected = String(selectedId || "").trim();
    const options = ['<option value="">请选择项目</option>'];
    projectsById.forEach((p, id) => {
      const name = String((p && p.name) || id);
      const country = String((p && (p.registeredCountry || p.country)) || "").trim();
      const label = country ? `${name}（${country}）` : name;
      options.push(
        `<option value="${escapeHtml(id)}"${id === selected ? " selected" : ""}>${escapeHtml(label)}</option>`
      );
    });
    return options.join("");
  }

  function collectVersionReleaseDates() {
    syncVersionDateValuesFromDom();
    const chain = buildVersionChainInputs();
    const out = {};
    const missing = [];
    chain.forEach((version) => {
      const value = String(versionDateValues.get(version) || "").trim();
      if (!value) {
        missing.push(version);
        return;
      }
      out[version] = value;
    });
    return { out, missing, chain };
  }

  function compareVersion(a, b) {
    const pa = String(a || "")
      .split(".")
      .map((x) => Number(x) || 0);
    const pb = String(b || "")
      .split(".")
      .map((x) => Number(x) || 0);
    for (let i = 0; i < 4; i += 1) {
      if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
    }
    return 0;
  }

  function generationStatusOptions(selected) {
    const cur = String(selected || "none").toLowerCase();
    return [
      ["none", "未生成"],
      ["previewed", "已预览"],
      ["generated", "已下发"],
    ]
      .map(
        ([val, label]) =>
          `<option value="${val}"${cur === val ? " selected" : ""}>${label}</option>`
      )
      .join("");
  }

  function syncSavedRecordsFromDom() {
    if (!els.savedRecordsBody) return;
    Array.from(els.savedRecordsBody.querySelectorAll("tr[data-vtg-record-idx]")).forEach((row) => {
      const idx = Number(row.getAttribute("data-vtg-record-idx"));
      if (Number.isNaN(idx) || !savedRecords[idx]) return;
      const item = savedRecords[idx];
      const val = (field) => {
        const el = row.querySelector(`[data-vtg-rec-field="${field}"]`);
        return el ? String(el.value || "").trim() : "";
      };
      item.projectId = val("projectId");
      item.version = val("version");
      item.releasedAt = val("releasedAt");
      item.generationStatus = val("generationStatus") || "none";
      item.productName = val("productName");
    });
  }

  function renderSavedRecordsTable() {
    if (els.savedRecordsCount) {
      els.savedRecordsCount.textContent = `${savedRecords.length} 条`;
    }
    if (!els.savedRecordsBody) return;
    const projectId = selectedProjectId();
    if (!projectId) {
      els.savedRecordsBody.innerHTML =
        '<tr><td colspan="7" class="text-muted small text-center py-3">请先选择项目</td></tr>';
      return;
    }
    if (!savedRecords.length) {
      els.savedRecordsBody.innerHTML =
        '<tr><td colspan="7" class="text-muted small text-center py-3">暂无记录，可点「新增版本」或「当前链路写入库」</td></tr>';
      return;
    }
    const rows = savedRecords
      .map((item, idx) => {
        const updated = item.updatedAt ? String(item.updatedAt).replace("T", " ").slice(0, 19) : "-";
        const rowProjectId = String(item.projectId || projectId || "").trim();
        return `<tr data-vtg-record-idx="${idx}">
          <td><select class="form-select form-select-sm" data-vtg-rec-field="projectId">${projectOptionsHtml(rowProjectId)}</select></td>
          <td><input class="form-control form-control-sm font-monospace" data-vtg-rec-field="version" value="${escapeHtml(item.version || "")}" placeholder="X.Y.Z.B"></td>
          <td><input type="date" class="form-control form-control-sm" data-vtg-rec-field="releasedAt" value="${escapeHtml(item.releasedAt || "")}"></td>
          <td><select class="form-select form-select-sm" data-vtg-rec-field="generationStatus">${generationStatusOptions(item.generationStatus)}</select></td>
          <td><input class="form-control form-control-sm" data-vtg-rec-field="productName" value="${escapeHtml(item.productName || "")}"></td>
          <td class="small text-muted">${escapeHtml(updated)}</td>
          <td class="d-flex gap-1 flex-wrap">
            <button type="button" class="btn btn-outline-primary btn-sm py-0" data-vtg-save-record="${idx}">保存</button>
            <button type="button" class="btn btn-outline-danger btn-sm py-0" data-vtg-delete-record="${idx}">删除</button>
          </td>
        </tr>`;
      })
      .join("");
    els.savedRecordsBody.innerHTML = rows;
    Array.from(els.savedRecordsBody.querySelectorAll("button[data-vtg-save-record]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-vtg-save-record"));
        withButtonBusy(btn, "保存中…", () => saveSavedRecordRow(idx)).catch((e) =>
          toast(e.message || "保存失败", "danger")
        );
      });
    });
    Array.from(els.savedRecordsBody.querySelectorAll("button[data-vtg-delete-record]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-vtg-delete-record"));
        withButtonBusy(btn, "删除中…", () => deleteSavedRecordRow(idx)).catch((e) =>
          toast(e.message || "删除失败", "danger")
        );
      });
    });
    Array.from(els.savedRecordsBody.querySelectorAll('select[data-vtg-rec-field="projectId"]')).forEach(
      (sel) => {
        sel.addEventListener("change", () => {
          const val = String(sel.value || "").trim();
          Array.from(
            els.savedRecordsBody.querySelectorAll('select[data-vtg-rec-field="projectId"]')
          ).forEach((other) => {
            other.value = val;
          });
          syncSavedRecordsFromDom();
        });
      }
    );
  }

  function applySavedRecordsToChainMaps(items) {
    (items || []).forEach((row) => {
      const version = String(row.version || "").trim();
      if (!version) return;
      if (row.releasedAt) versionDateValues.set(version, String(row.releasedAt));
      projectVersionStatus.set(version, String(row.generationStatus || "none"));
    });
  }

  function applySavedRecordsToChainForm() {
    const versions = savedRecords
      .map((r) => String(r.version || "").trim())
      .filter(Boolean)
      .sort(compareVersion);
    if (!versions.length) return 0;
    const storedFrom = savedRecords
      .map((r) => String(r.chainFromVersion || "").trim())
      .find(Boolean);
    const storedTo = savedRecords
      .map((r) => String(r.chainToVersion || "").trim())
      .find(Boolean);
    const fromV = storedFrom || versions[0];
    const toV = storedTo || versions[versions.length - 1];
    if (els.fromVersion) els.fromVersion.value = fromV;
    if (els.toVersion) els.toVersion.value = toV;
    if (els.intermediate) {
      els.intermediate.value = versions.filter((v) => v !== fromV && v !== toV).join(", ");
    }
    applySavedRecordsToChainMaps(savedRecords);
    const withProduct = savedRecords.find((r) => String(r.productName || "").trim());
    if (withProduct && els.productName && !String(els.productName.value || "").trim()) {
      els.productName.value = withProduct.productName;
    }
    renderVersionDatesTable();
    return versions.length;
  }

  function loadSavedRecordsToChain() {
    syncSavedRecordsFromDom();
    const n = applySavedRecordsToChainForm();
    if (!n) {
      toast("没有可加载的版本记录", "warning");
      return;
    }
    toast(`已加载 ${n} 个版本到链路表单`, "success");
  }

  function productNameStorageKey(projectId) {
    return `${PRODUCT_NAME_LS_PREFIX}${projectId}`;
  }

  function readLastProjectId() {
    try {
      return String(localStorage.getItem(LAST_PROJECT_LS_KEY) || "").trim();
    } catch (e) {
      return "";
    }
  }

  function writeLastProjectId(projectId) {
    const pid = String(projectId || "").trim();
    try {
      if (pid) localStorage.setItem(LAST_PROJECT_LS_KEY, pid);
      else localStorage.removeItem(LAST_PROJECT_LS_KEY);
    } catch (e) {
      /* ignore quota / private mode */
    }
  }

  function restoreLastProject() {
    const current = selectedProjectId();
    if (current && projectsById.has(current)) return current;
    const last = readLastProjectId();
    if (last && projectsById.has(last)) return setProjectSelectValue(last);
    return "";
  }

  function readLocalProductName(projectId) {
    if (!projectId) return "";
    try {
      return String(localStorage.getItem(productNameStorageKey(projectId)) || "").trim();
    } catch (e) {
      return "";
    }
  }

  function writeLocalProductName(projectId, productName) {
    if (!projectId) return;
    try {
      const name = String(productName || "").trim();
      if (name) localStorage.setItem(productNameStorageKey(projectId), name);
      else localStorage.removeItem(productNameStorageKey(projectId));
    } catch (e) {
      /* ignore quota / private mode */
    }
  }

  function fillProductNameForProject(projectId, preferredName) {
    if (!els.productName) return;
    const pid = String(projectId || "").trim();
    const preferred = String(preferredName || "").trim();
    if (preferred) {
      els.productName.value = preferred;
      writeLocalProductName(pid, preferred);
      return;
    }
    const fromRecords = (savedRecords || []).find((r) => String(r.productName || "").trim());
    if (fromRecords) {
      els.productName.value = fromRecords.productName;
      writeLocalProductName(pid, fromRecords.productName);
      return;
    }
    const local = readLocalProductName(pid);
    if (local) {
      els.productName.value = local;
      return;
    }
    const p = projectsById.get(pid);
    const hint = String(
      (p && (p.registeredProductName || p.productName || p.name)) || ""
    ).trim();
    els.productName.value = hint || "";
  }

  async function persistProductName() {
    const projectId = String(els.projectId && els.projectId.value || "").trim();
    const productName = String(els.productName && els.productName.value || "").trim();
    if (!projectId) return;
    writeLocalProductName(projectId, productName);
    try {
      await requestJson("/api/document-control/version-tasks/project-product-name", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId, productName }),
      });
    } catch (e) {
      // 后端失败时仍保留本机缓存，避免刷新完全丢失
      toast(e.message || "产品名称已缓存在本机，服务端暂未写入", "warning");
    }
  }

  async function loadSavedRecords() {
    const projectId = String(els.projectId.value || "").trim();
    if (!projectId) {
      savedRecords = [];
      projectVersionStatus.clear();
      if (els.productName) els.productName.value = "";
      renderSavedRecordsTable();
      renderVersionDatesTable();
      return;
    }
    const data = await requestJson(
      `/api/document-control/version-tasks/project-records?projectId=${encodeURIComponent(projectId)}`
    );
    savedRecords = Array.isArray(data.items) ? data.items.map((x) => ({ ...x })) : [];
    projectVersionStatus.clear();
    applySavedRecordsToChainMaps(savedRecords);
    fillProductNameForProject(projectId, data.productName || "");
    renderSavedRecordsTable();
    renderVersionDatesTable();
  }

  async function saveSavedRecordRow(idx) {
    const filterProjectId = String(els.projectId.value || "").trim();
    syncSavedRecordsFromDom();
    const row = savedRecords[idx];
    if (!row) return;
    const projectId = String(row.projectId || filterProjectId || "").trim();
    if (!projectId) {
      toast("请选择关联项目", "warning");
      return;
    }
    const version = String(row.version || "").trim();
    if (!version) {
      toast("版本号不能为空", "warning");
      return;
    }
    const payload = {
      projectId,
      version,
      releasedAt: String(row.releasedAt || "").trim(),
      productName: String(row.productName || els.productName.value || "").trim(),
      generationStatus: String(row.generationStatus || "none").trim(),
      chainFromVersion: String(els.fromVersion.value || "").trim(),
      chainToVersion: String(els.toVersion.value || "").trim(),
      allowDowngradeStatus: true,
    };
    let data;
    if (row.id) {
      data = await requestJson(
        `/api/document-control/version-tasks/project-records/${encodeURIComponent(row.id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
    } else {
      data = await requestJson("/api/document-control/version-tasks/project-records/item", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    const saved = data.item || row;
    if (data.moved) {
      const recCount = Number(data.movedRecordCount || (data.movedItems || []).length || 1);
      const jobCount = Number(data.movedJobCount || 0);
      toast(
        `已同步改绑 ${recCount} 条版本记录` +
          (jobCount ? `及 ${jobCount} 个预览批次` : "") +
          "到新项目",
        "success"
      );
      await loadSavedRecords();
      return;
    }
    if (filterProjectId && String(saved.projectId || "") !== filterProjectId) {
      savedRecords.splice(idx, 1);
      toast("版本记录已改绑到其他项目，已从当前列表移除", "success");
    } else {
      savedRecords[idx] = saved;
      applySavedRecordsToChainMaps([savedRecords[idx]]);
      writeLastProjectId(projectId);
      toast("版本记录已保存", "success");
    }
    renderSavedRecordsTable();
    renderVersionDatesTable();
  }

  async function deleteSavedRecordRow(idx) {
    syncSavedRecordsFromDom();
    const row = savedRecords[idx];
    if (!row) return;
    if (!row.id) {
      savedRecords.splice(idx, 1);
      renderSavedRecordsTable();
      return;
    }
    if (!window.confirm(`确定删除版本 ${row.version} 的记录？`)) return;
    await requestJson(
      `/api/document-control/version-tasks/project-records/${encodeURIComponent(row.id)}`,
      { method: "DELETE" }
    );
    savedRecords.splice(idx, 1);
    versionDateValues.delete(row.version);
    projectVersionStatus.delete(row.version);
    renderSavedRecordsTable();
    renderVersionDatesTable();
    toast("已删除", "success");
  }

  function addSavedRecordRow() {
    const projectId = String(els.projectId.value || "").trim();
    if (!projectId) {
      toast("请先选择项目", "warning");
      return;
    }
    savedRecords.push({
      id: "",
      projectId: String(els.projectId.value || "").trim(),
      version: "",
      releasedAt: "",
      generationStatus: "none",
      productName: String(els.productName.value || "").trim(),
    });
    renderSavedRecordsTable();
  }

  function applyProjectRecords(items) {
    if (Array.isArray(items) && items.length) {
      savedRecords = items.map((x) => ({ ...x }));
      renderSavedRecordsTable();
    }
    applySavedRecordsToChainMaps(items);
    (items || []).forEach((row) => {
      if (row.productName && !String(els.productName.value || "").trim()) {
        els.productName.value = row.productName;
      }
      if (row.chainFromVersion && !String(els.fromVersion.value || "").trim()) {
        els.fromVersion.value = row.chainFromVersion;
      }
      if (row.chainToVersion && !String(els.toVersion.value || "").trim()) {
        els.toVersion.value = row.chainToVersion;
      }
    });
    renderVersionDatesTable();
  }

  function applyVersionReleaseDatesFromPreview(map) {
    if (!map || typeof map !== "object") return;
    Object.keys(map).forEach((version) => {
      versionDateValues.set(version, String(map[version] || "").trim());
    });
    renderVersionDatesTable();
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatTriggerBits(raw) {
    const labels = { X: "X位", Y: "Y位", Z: "Z位", B: "B位" };
    const bits = Array.isArray(raw) ? raw : String(raw || "").split(/[,，\s]+/).filter(Boolean);
    return bits.map((b) => labels[String(b).toUpperCase()] || String(b)).join("、");
  }

  function syncPreviewItemsFromDom() {
    if (!els.previewBody) return;
    Array.from(els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]")).forEach((row) => {
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      if (Number.isNaN(idx) || !previewItems[idx]) return;
      const item = previewItems[idx];
      const val = (field) => {
        const el = row.querySelector(`[data-vtg-field="${field}"]`);
        return el ? String(el.value || "").trim() : "";
      };
      item.fileName = val("fileName");
      item.documentNumber = val("documentNumber");
      item.fileVersion = val("fileVersion");
      item.taskType = val("taskType");
      item.targetVersion = val("targetVersion");
      item.registrationVersion = val("targetVersion") || item.registrationVersion;
      item.author = val("author");
      item.dueDate = val("dueDate");
      item.documentDisplayDate = val("documentDisplayDate");
      item.belongingModule = val("belongingModule");
      item.explanation = val("explanation");
      item.notes = val("notes");
      item.recordStatus = recordStatusOf({ recordStatus: val("recordStatus") });
      const sysEl = row.querySelector('[data-vtg-field="isSystemRecord"]');
      if (sysEl) item.isSystemRecord = Boolean(sysEl.checked);
      const reasonEl = row.querySelector('[data-vtg-field="changeReason"]');
      if (reasonEl) item.changeReason = String(reasonEl.value || "").trim();
      ensureOriginKey(item);
      refreshItemChangeMark(item);
    });
  }

  function recordStatusOf(item) {
    const key = String((item && item.recordStatus) || "").trim().toLowerCase();
    if (key === "discard" || key === "弃用" || key === "deprecated" || key === "rejected") {
      return "discard";
    }
    if (key === "pending" || key === "待定") return "pending";
    return "adopt";
  }

  function isSystemRecordOf(item) {
    const raw = item && item.isSystemRecord;
    if (raw === false || raw === 0 || raw === "0") return false;
    const key = String(raw == null ? "" : raw).trim().toLowerCase();
    if (key === "false" || key === "no" || key === "n" || key === "否" || key === "非体系") return false;
    if (raw === true || raw === 1 || raw === "1") return true;
    if (key === "true" || key === "yes" || key === "y" || key === "是" || key === "体系" || key === "体系记录") {
      return true;
    }
    return false;
  }

  function isSystemRecordSelectHtml(item, disabled) {
    const on = isSystemRecordOf(item);
    return `<label class="vtg-system-check"><input type="checkbox" class="form-check-input" data-vtg-field="isSystemRecord"${
      on ? " checked" : ""
    }${disabled ? " disabled" : ""} title="勾选表示为质量管理体系记录"><span>${on ? "是" : "否"}</span></label>`;
  }

  function recordStatusSelectHtml(status, disabled) {
    const cur = recordStatusOf({ recordStatus: status });
    const opts = [
      ["adopt", "选用"],
      ["pending", "待定"],
      ["discard", "弃用"],
    ];
    return `<select class="form-select form-select-sm vtg-status-select" data-vtg-field="recordStatus"${disabled ? " disabled" : ""}>${opts
      .map(
        ([value, label]) =>
          `<option value="${value}"${cur === value ? " selected" : ""}>${label}</option>`
      )
      .join("")}</select>`;
  }

  function changeKindOf(item) {
    const key = String((item && item.changeKind) || "").trim().toLowerCase();
    if (key === "add" || key === "update" || key === "delete") return key;
    return "";
  }

  function isPreviewDeleted(item) {
    return changeKindOf(item) === "delete";
  }

  function isHiddenPreviewItem(item) {
    return isPreviewDeleted(item) || Boolean(item && item.hideInPreview);
  }

  function previewDedupeKey(item) {
    const a = String((item && (item.taskKey || item.fileName)) || "").trim().toLowerCase();
    const b = String((item && (item.targetVersion || item.registrationVersion)) || "").trim().toLowerCase();
    const c = String((item && item.taskType) || "").trim().toLowerCase();
    return `${a}\t${b}\t${c}`;
  }

  function combinePreviewPayloadItems(data, fallbackItems) {
    const live = Array.isArray(data && data.items)
      ? data.items
      : Array.isArray(fallbackItems)
        ? fallbackItems
        : [];
    const deleted = Array.isArray(data && data.deletedItems) ? data.deletedItems : [];
    return live.concat(deleted);
  }

  function hydrateDeletedMarkers(items, manualDeletedKeys) {
    const deleted = new Set();
    (manualDeletedKeys || []).forEach((raw) => {
      if (!Array.isArray(raw) || raw.length !== 3) return;
      deleted.add(
        `${String(raw[0] || "").toLowerCase()}\t${String(raw[1] || "").toLowerCase()}\t${String(raw[2] || "").toLowerCase()}`
      );
    });
    return (items || []).map((item) => {
      const rec = { ...item };
      if (isPreviewDeleted(rec) || rec.hideInPreview || deleted.has(previewDedupeKey(rec))) {
        rec.changeKind = "delete";
        rec.hideInPreview = true;
      }
      return rec;
    });
  }

  function visiblePreviewItems(items) {
    return (items || previewItems).filter((item) => !isHiddenPreviewItem(item));
  }

  function canCheckPreview(item) {
    return !isPreviewDeleted(item);
  }

  function canSelectPreview(item) {
    return recordStatusOf(item) === "adopt" && !isPreviewDeleted(item);
  }

  function makeOriginKey(item) {
    const a = String((item && (item.taskKey || item.fileName)) || "").trim();
    const b = String((item && (item.targetVersion || item.registrationVersion)) || "").trim();
    const c = String((item && item.taskType) || "").trim();
    return `${a}||${b}||${c}`;
  }

  function originKeyOf(item) {
    const existing = String((item && item.originKey) || "").trim();
    if (existing) return existing;
    return makeOriginKey(item);
  }

  function ensureOriginKey(item) {
    if (!item) return "";
    if (!String(item.originKey || "").trim()) item.originKey = originKeyOf(item);
    return item.originKey;
  }

  function ruleItemOf(item) {
    const rules = rulePreviewItems || [];
    const key = originKeyOf(item);
    const byOrigin = rules.find((x) => originKeyOf(x) === key);
    if (byOrigin) return byOrigin;
    const ident = taskIdentity(item);
    return rules.find((x) => taskIdentity(x) === ident) || null;
  }

  function cloneNormalizedPreviewItem(item) {
    const copy = { ...(item || {}) };
    normalizePreviewDocFields(copy);
    return copy;
  }

  function summarizeItemDiff(original, adjusted) {
    const before = cloneNormalizedPreviewItem(original);
    const after = cloneNormalizedPreviewItem(adjusted);
    const out = [];
    Object.keys(CHANGE_FIELD_LABELS).forEach((key) => {
      let left = String(before[key] || "").trim();
      let right = String(after[key] || "").trim();
      if (key === "targetVersion") {
        left = left || String(before.registrationVersion || "").trim();
        right = right || String(after.registrationVersion || "").trim();
      }
      if (key === "recordStatus") {
        left = RECORD_STATUS_LABELS[recordStatusOf({ recordStatus: left })] || left;
        right = RECORD_STATUS_LABELS[recordStatusOf({ recordStatus: right })] || right;
      }
      if (key === "chapter") {
        left = left || String(before.processBranchLabel || "").trim();
        right = right || String(after.processBranchLabel || "").trim();
      }
      if (key === "isSystemRecord") {
        left = isSystemRecordOf(before) ? "是" : "否";
        right = isSystemRecordOf(after) ? "是" : "否";
      }
      if (left === right) return;
      out.push({
        field: key,
        label: CHANGE_FIELD_LABELS[key],
        from: left,
        to: right,
      });
    });
    return out;
  }

  function formatChangeValue(field, raw) {
    const text = String(raw || "").trim();
    if (!text) return "空";
    if (field === "recordStatus") {
      if (text === "选用" || text === "弃用" || text === "待定") return text;
      return RECORD_STATUS_LABELS[recordStatusOf({ recordStatus: text })] || text;
    }
    if (field === "isSystemRecord") {
      return isSystemRecordOf({ isSystemRecord: raw }) ? "是" : "否";
    }
    return text;
  }

  function formatChangeSummary(summary) {
    if (!Array.isArray(summary) || !summary.length) return "";
    return summary
      .map((row) => {
        const label = String((row && (row.label || CHANGE_FIELD_LABELS[row.field])) || row.field || "");
        const from = formatChangeValue(row && row.field, row && row.from);
        const to = formatChangeValue(row && row.field, row && row.to);
        return `${label}：「${from}」→「${to}」`;
      })
      .join("；");
  }

  function changeKindBadgeHtml(item) {
    const kind = changeKindOf(item);
    if (kind === "add") return '<span class="vtg-kind vtg-kind-add">新增</span>';
    if (kind === "delete") return '<span class="vtg-kind vtg-kind-del">已删除</span>';
    if (kind === "update") {
      const detail = formatChangeSummary(item && item.changeFields);
      return `<span class="vtg-kind vtg-kind-upd" title="${escapeHtml(detail)}">已修改</span>`;
    }
    return '<span class="text-muted">—</span>';
  }

  function refreshItemChangeMark(item) {
    if (!item) return;
    ensureOriginKey(item);
    const kind = changeKindOf(item);
    if (kind === "delete" || kind === "add") {
      if (kind === "add") item.changeFields = [];
      return;
    }
    const baseline = ruleItemOf(item);
    if (!baseline) {
      item.changeKind = "add";
      item.changeFields = [];
      return;
    }
    const summary = summarizeItemDiff(baseline, item);
    if (summary.length) {
      item.changeKind = "update";
      item.changeFields = summary;
    } else {
      item.changeKind = "";
      item.changeFields = [];
    }
  }

  function itemForFeedbackCompare(item) {
    const copy = { ...(item || {}) };
    copy.recordStatus = recordStatusOf(copy);
    delete copy.changeKind;
    delete copy.changeReason;
    delete copy.changeFields;
    delete copy.originKey;
    delete copy.sortOrder;
    return copy;
  }

  function previewSelectionScope(override) {
    const o = override || {};
    return {
      projectId: String(o.projectId != null ? o.projectId : selectedProjectId() || "").trim(),
      fromVersion: String(
        o.fromVersion != null ? o.fromVersion : inputValue(els.fromVersion) || ""
      ).trim(),
      toVersion: String(
        o.toVersion != null ? o.toVersion : inputValue(els.toVersion) || ""
      ).trim(),
    };
  }

  function previewSelectionStorageKey(scope) {
    const s = previewSelectionScope(scope);
    if (!s.projectId || !s.fromVersion || !s.toVersion) return "";
    return `${PREVIEW_SELECTED_LS_PREFIX}${s.projectId}|${s.fromVersion}|${s.toVersion}`;
  }

  function readStoredPreviewSelection(scope) {
    const key = previewSelectionStorageKey(scope);
    if (!key) return null;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || typeof data !== "object") return null;
      const identities = Array.isArray(data.identities) ? data.identities.map(String) : [];
      const originKeys = Array.isArray(data.originKeys) ? data.originKeys.map(String) : [];
      return { identities, originKeys };
    } catch (err) {
      return null;
    }
  }

  function savePreviewSelection(scope) {
    const key = previewSelectionStorageKey(scope);
    if (!key) return;
    const identities = [];
    const originKeys = [];
    const seenIdent = new Set();
    const seenOrigin = new Set();
    (previewItems || []).forEach((item) => {
      if (!canCheckPreview(item)) return;
      const ident = taskIdentity(item);
      if (!previewSelectedKeys.has(ident)) return;
      if (!seenIdent.has(ident)) {
        seenIdent.add(ident);
        identities.push(ident);
      }
      const origin = originKeyOf(item);
      if (origin && !seenOrigin.has(origin)) {
        seenOrigin.add(origin);
        originKeys.push(origin);
      }
    });
    try {
      localStorage.setItem(key, JSON.stringify({ identities, originKeys }));
    } catch (err) {
      /* ignore quota */
    }
  }

  function restorePreviewSelection(items, scope) {
    previewSelectedKeys.clear();
    const stored = readStoredPreviewSelection(scope);
    if (!stored) return false;
    const idSet = new Set(stored.identities);
    const originSet = new Set(stored.originKeys);
    (items || []).forEach((item) => {
      if (!canCheckPreview(item)) return;
      const ident = taskIdentity(item);
      const origin = originKeyOf(item);
      if (idSet.has(ident) || (origin && originSet.has(origin))) {
        previewSelectedKeys.add(ident);
      }
    });
    return true;
  }

  function remapPreviewSelectionKey(oldIdent, item) {
    const nextIdent = taskIdentity(item);
    if (!oldIdent || oldIdent === nextIdent) return;
    if (!previewSelectedKeys.has(oldIdent)) return;
    previewSelectedKeys.delete(oldIdent);
    if (canCheckPreview(item)) previewSelectedKeys.add(nextIdent);
  }

  function prunePreviewSelection(items) {
    const next = new Set();
    (items || []).forEach((item) => {
      const ident = taskIdentity(item);
      if (previewSelectedKeys.has(ident) && canCheckPreview(item)) next.add(ident);
    });
    previewSelectedKeys.clear();
    next.forEach((key) => previewSelectedKeys.add(key));
  }

  function visiblePreviewRows() {
    if (!els.previewBody) return [];
    return Array.from(els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]")).filter(
      (tr) => !tr.classList.contains("vtg-preview-hidden")
    );
  }

  function syncPreviewSelectionFromDom() {
    if (!els.previewBody) return;
    Array.from(els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]")).forEach((row) => {
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      if (Number.isNaN(idx) || !previewItems[idx]) return;
      const key = taskIdentity(previewItems[idx]);
      const cb = row.querySelector("[data-vtg-select-row]");
      const adopted = canSelectPreview(previewItems[idx]);
      const checkable = canCheckPreview(previewItems[idx]);
      if (cb && cb.checked && checkable) previewSelectedKeys.add(key);
      else previewSelectedKeys.delete(key);
    });
  }

  function selectVisibleAdopt() {
    syncPreviewItemsFromDom();
    visiblePreviewRows().forEach((row) => {
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      if (Number.isNaN(idx) || !previewItems[idx]) return;
      if (!canSelectPreview(previewItems[idx])) return;
      previewSelectedKeys.add(taskIdentity(previewItems[idx]));
    });
    updatePreviewSelectionUi();
  }

  function unselectAllPreview() {
    previewSelectedKeys.clear();
    updatePreviewSelectionUi();
  }

  function unselectVisiblePreview() {
    visiblePreviewRows().forEach((row) => {
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      if (Number.isNaN(idx) || !previewItems[idx]) return;
      previewSelectedKeys.delete(taskIdentity(previewItems[idx]));
    });
    updatePreviewSelectionUi();
  }

  function currentApplyMode() {
    if (els.applyModeIncrement && els.applyModeIncrement.checked) return "increment";
    return "replace";
  }

  function updatePreviewSelectionUi() {
    if (!els.previewBody) return;
    const visible = visiblePreviewRows();
    let visibleAdopt = 0;
    let visibleSelected = 0;
    visible.forEach((row) => {
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      const item = previewItems[idx];
      if (!item) return;
      const status = recordStatusOf(item);
      const adopted = canSelectPreview(item);
      const checkable = canCheckPreview(item);
      const key = taskIdentity(item);
      if (!checkable) previewSelectedKeys.delete(key);
      const selected = checkable && previewSelectedKeys.has(key);
      const cb = row.querySelector("[data-vtg-select-row]");
      if (cb) {
        cb.disabled = !checkable;
        cb.checked = selected;
      }
      row.classList.toggle("vtg-status-discard", status === "discard");
      row.classList.toggle("vtg-status-pending", status === "pending");
      row.classList.toggle("vtg-change-delete", changeKindOf(item) === "delete");
      row.classList.toggle("vtg-change-add", changeKindOf(item) === "add");
      row.classList.toggle("vtg-change-update", changeKindOf(item) === "update");
      if (adopted) visibleAdopt += 1;
      if (selected && adopted) visibleSelected += 1;
    });
    if (els.previewHeadCheck) {
      els.previewHeadCheck.disabled = !previewItems.length || visibleAdopt === 0;
      els.previewHeadCheck.checked = visibleAdopt > 0 && visibleSelected === visibleAdopt;
      els.previewHeadCheck.indeterminate = visibleSelected > 0 && visibleSelected < visibleAdopt;
    }
    const adoptCount = previewItems.filter((item) => canSelectPreview(item)).length;
    const selectedCount = previewItems.filter(
      (item) => canSelectPreview(item) && previewSelectedKeys.has(taskIdentity(item))
    ).length;
    const addCount = previewItems.filter((item) => changeKindOf(item) === "add").length;
    const updateCount = previewItems.filter((item) => changeKindOf(item) === "update").length;
    const deleteCount = previewItems.filter((item) => changeKindOf(item) === "delete").length;
    const changeBit = addCount || updateCount || deleteCount
      ? ` · 新增 ${addCount} / 改 ${updateCount} / 删 ${deleteCount}`
      : "";
    if (els.previewCount) {
      if (!previewItems.length) {
        els.previewCount.textContent = "0 条";
      } else if (previewVersionFilter || hasPreviewColFilters()) {
        const n = visiblePreviewItems().filter(
          (item) =>
            itemMatchesColFilters(item) &&
            (!previewVersionFilter || previewVersionKey(item) === previewVersionFilter)
        ).length;
        els.previewCount.textContent = `${n} / ${visiblePreviewItems().length} 条 · 已选 ${selectedCount} · 选用 ${adoptCount}${changeBit}`;
      } else {
        els.previewCount.textContent = `${visiblePreviewItems().length} 条 · 已选 ${selectedCount} · 选用 ${adoptCount}${changeBit}`;
      }
    }
    if (els.previewSelectHint) {
      els.previewSelectHint.textContent = previewItems.length
        ? `勾选后可下发（仅选用）、批量调整顺序或设置完成日期。当前可见选用已选 ${visibleSelected} / ${visibleAdopt}。刷新后会记住勾选。`
        : "勾选后可下发（仅选用）、批量调整顺序或设置完成日期。已删除记录不能勾选。";
    }
    updateApplyIssueCount();
    refreshPreviewAppliedBadges();
    if (!previewSelectionPersistMuted) savePreviewSelection();
  }

  function splitTaskAuthors(raw) {
    const text = String(raw || "").trim();
    if (!text) return ["待分配"];
    const names = [];
    const seen = new Set();
    String(text).split(",").forEach((part) => {
      const name = String(part || "").trim();
      if (!name) return;
      const key = name.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      names.push(name);
    });
    return names.length ? names : ["待分配"];
  }

  function selectedIssueItems() {
    return (previewItems || []).filter(
      (item) => canSelectPreview(item) && previewSelectedKeys.has(taskIdentity(item))
    );
  }

  function countIssueRecords(items) {
    return (items || []).reduce((n, item) => n + splitTaskAuthors(item && item.author).length, 0);
  }

  function displayTargetVersion(value) {
    const text = String(value == null ? "" : value).trim();
    return text || "未指定";
  }

  function issuedIdentityKey(fileName, taskType, author, targetVersion) {
    return [
      String(fileName || "").trim().toLowerCase(),
      String(taskType || "").trim().toLowerCase(),
      (String(author || "").trim() || "待分配").toLowerCase(),
      displayTargetVersion(targetVersion).toLowerCase(),
    ].join("|");
  }

  function canonicalTaskType(value) {
    const text = String(value || "").trim();
    if (!text || LEGACY_AUTO_VERSION_TASK_TYPES[text]) return DEFAULT_VERSION_TASK_TYPE;
    return text;
  }

  function issuedFileNames(item) {
    const fileName = String((item && item.fileName) || "").trim();
    return fileName ? [fileName] : [];
  }

  function issuedIdentityKeysForAuthor(item, author) {
    const names = issuedFileNames(item);
    const rawType = String((item && item.taskType) || "").trim();
    const types = [];
    const seen = new Set();
    [rawType, canonicalTaskType(rawType)].forEach((tp) => {
      const key = String(tp || "").trim().toLowerCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      types.push(tp || canonicalTaskType(rawType));
    });
    const ver = (item && (item.targetVersion || item.registrationVersion)) || "";
    const keys = [];
    names.forEach((name) => {
      types.forEach((tp) => {
        keys.push(issuedIdentityKey(name, tp, author, ver));
      });
    });
    return keys;
  }

  function syncIssuedKeySet(items) {
    issuedKeySet.clear();
    (items || []).forEach((row) => {
      const extra = Array.isArray(row && row.keys) ? row.keys : [];
      extra.forEach((key) => {
        const text = String(key || "").trim();
        if (text) issuedKeySet.add(text);
      });
      const key = String((row && row.key) || "").trim() || issuedIdentityKey(
        row && row.fileName,
        row && row.taskType,
        row && row.author,
        row && row.targetVersion
      );
      if (key) issuedKeySet.add(key);
      issuedIdentityKeysForAuthor(row, (row && row.author) || "待分配").forEach((itemKey) => {
        if (itemKey) issuedKeySet.add(itemKey);
      });
    });
  }

  function previewApplyState(item) {
    if (!issuedKeySet.size) return "none";
    const authors = splitTaskAuthors(item && item.author);
    let hit = 0;
    authors.forEach((author) => {
      const keys = issuedIdentityKeysForAuthor(item, author);
      if (keys.some((key) => issuedKeySet.has(key))) hit += 1;
    });
    if (authors.length && hit >= authors.length) return "applied";
    if (hit) return "partial";
    return "none";
  }

  function previewAppliedBadgeHtml(item) {
    const state = previewApplyState(item);
    if (state === "applied") return '<span class="badge text-bg-success">已下发</span>';
    if (state === "partial") return '<span class="badge text-bg-warning text-dark">部分下发</span>';
    return '<span class="badge text-bg-light text-muted">未下发</span>';
  }

  function refreshPreviewAppliedBadges() {
    if (!els.previewBody) return;
    els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]").forEach((row) => {
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      const cell = row.querySelector('[data-vtg-col="applied"]');
      if (Number.isNaN(idx) || !previewItems[idx] || !cell) return;
      cell.innerHTML = previewAppliedBadgeHtml(previewItems[idx]);
    });
  }

  function selectedProjectLabel() {
    if (!els.projectId) return "";
    const opt = els.projectId.selectedOptions && els.projectId.selectedOptions[0];
    const text = String((opt && opt.textContent) || "").trim();
    if (!text || text.indexOf("请选择") === 0 || text.indexOf("加载") >= 0) return "";
    return text;
  }

  function pendingCountsByVersion() {
    const map = new Map();
    selectedIssueItems().forEach((item) => {
      const ver = displayTargetVersion((item && (item.targetVersion || item.registrationVersion)) || "");
      map.set(ver, (map.get(ver) || 0) + splitTaskAuthors(item && item.author).length);
    });
    return map;
  }

  function applyLedgerVersionKey(projectId, projectName, ver) {
    return `${String(projectId || "").trim() || String(projectName || "").trim()}::${ver}`;
  }

  function renderApplyLedger() {
    if (!els.applyBatchList) return;
    if (!applyLedgerLoaded) return;
    const pending = pendingCountsByVersion();
    const projectId = selectedProjectId();
    const projectLabel = selectedProjectLabel();
    const groups = (applyLedgerCache.groups || []).map((group) => ({
      projectId: group.projectId || "",
      projectName: group.projectName || "（空项目）",
      taskCount: Number(group.taskCount || 0),
      versions: Array.isArray(group.versions) ? group.versions.slice() : [],
    }));
    const isCurrentGroup = (group) =>
      (projectId && String(group.projectId || "") === String(projectId)) ||
      (!projectId && projectLabel && String(group.projectName || "") === projectLabel);
    if (pending.size) {
      let group = groups.find((row) => isCurrentGroup(row));
      if (!group && (projectId || projectLabel)) {
        group = {
          projectId,
          projectName: projectLabel || "当前项目",
          taskCount: 0,
          versions: [],
        };
        groups.unshift(group);
      }
      if (group) {
        pending.forEach((_count, ver) => {
          const exists = group.versions.some((row) => displayTargetVersion(row.targetVersion) === ver);
          if (!exists) group.versions.push({ targetVersion: ver, taskCount: 0, records: [] });
        });
      }
    }
    if (!groups.length) {
      els.applyBatchList.innerHTML = projectId
        ? '<p class="text-muted mb-0">该项目还没有与当前版本清单对应的已下发记录。</p>'
        : '<p class="text-muted mb-0">请选择项目后查看已下发的最新记录。</p>';
      return;
    }
    const html = [];
    groups.forEach((group, groupIdx) => {
      html.push('<div class="vtg-apply-group">');
      html.push(
        `<div class="vtg-apply-group-title">项目：${escapeHtml(group.projectName)} <span class="vtg-apply-muted">已下发 ${Number(group.taskCount || 0)} 条</span></div>`
      );
      (group.versions || []).forEach((row, verIdx) => {
        const ver = displayTargetVersion(row && row.targetVersion);
        const records = Array.isArray(row && row.records) ? row.records : [];
        const taskN = Number((row && row.taskCount) || records.length || 0);
        const pendingN = isCurrentGroup(group) ? pending.get(ver) || 0 : 0;
        const pendingBit = pendingN ? ` · 本次即将下发 ${pendingN} 条` : "";
        const recKey = applyLedgerVersionKey(group.projectId, group.projectName, ver);
        const expanded = applyLedgerExpandedKeys.has(recKey);
        if (records.length) {
          const recsId = `vtgApplyRecs-${groupIdx}-${verIdx}`;
          html.push(
            `<button type="button" class="vtg-apply-ver" data-vtg-apply-key="${escapeHtml(recKey)}" aria-expanded="${expanded ? "true" : "false"}" aria-controls="${recsId}">` +
              `<span class="vtg-caret" aria-hidden="true">${expanded ? "▼" : "▶"}</span>` +
              `目标版本 ${escapeHtml(ver)}：已下发 <strong>${taskN}</strong> 条${pendingBit}` +
              `<span class="vtg-apply-muted" data-vtg-apply-ver-hint> ${expanded ? "收起" : "展开"}</span>` +
            `</button>`
          );
          html.push(`<div class="vtg-apply-recs${expanded ? "" : " is-collapsed"}" id="${recsId}">`);
          records.forEach((item) => {
            const name = String((item && item.fileName) || "").trim() || "未命名";
            const type = String((item && item.taskType) || "").trim() || DEFAULT_VERSION_TASK_TYPE;
            const author = String((item && item.author) || "").trim() || "待分配";
            html.push(
              `<div class="vtg-apply-rec">${escapeHtml(name)} · ${escapeHtml(type)} · ${escapeHtml(author)}</div>`
            );
          });
          html.push("</div>");
        } else {
          html.push(
            `<div class="vtg-apply-ver">目标版本 ${escapeHtml(ver)}：已下发 <strong>${taskN}</strong> 条${pendingBit}</div>`
          );
        }
      });
      html.push("</div>");
    });
    els.applyBatchList.innerHTML = html.join("");
  }

  async function loadApplyBatches() {
    const projectId = selectedProjectId();
    if (!projectId) {
      applyLedgerCache = { groups: [], batches: [], issuedItems: [] };
      issuedKeySet.clear();
      applyLedgerLoaded = true;
      renderApplyLedger();
      refreshPreviewAppliedBadges();
      return;
    }
    try {
      const data = await requestJson(
        `/api/document-control/version-tasks/apply-batches?projectId=${encodeURIComponent(projectId)}`
      );
      applyLedgerCache = {
        groups: Array.isArray(data.groups) ? data.groups : [],
        batches: Array.isArray(data.batches) ? data.batches : [],
        issuedItems: Array.isArray(data.issuedItems) ? data.issuedItems : [],
      };
      syncIssuedKeySet(applyLedgerCache.issuedItems);
      applyLedgerLoaded = true;
      renderApplyLedger();
      refreshPreviewAppliedBadges();
    } catch (err) {
      applyLedgerCache = { groups: [], batches: [], issuedItems: [] };
      issuedKeySet.clear();
      applyLedgerLoaded = true;
      if (els.applyBatchList) {
        els.applyBatchList.innerHTML = `<p class="text-danger mb-0">${escapeHtml(
          err.message || "加载已下发记录失败"
        )}</p>`;
      }
    }
  }

  function updateApplyIssueCount() {
    if (!els.applyCount) return;
    if (els.previewBody) {
      Array.from(els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]")).forEach((row) => {
        const idx = Number(row.getAttribute("data-vtg-preview-idx"));
        const el = row.querySelector('[data-vtg-field="author"]');
        if (Number.isNaN(idx) || !previewItems[idx] || !el) return;
        previewItems[idx].author = String(el.value || "").trim();
      });
    }
    const rows = selectedIssueItems();
    const n = countIssueRecords(rows);
    if (els.applyPendingList) {
      if (!n) {
        els.applyPendingList.innerHTML = "";
      } else {
        els.applyPendingList.innerHTML = Array.from(pendingCountsByVersion().entries())
          .map(([ver, count]) => `<li>目标版本 ${escapeHtml(ver)}：${count} 条</li>`)
          .join("");
      }
    }
    if (!n) {
      els.applyCount.textContent = "尚未勾选可下发记录";
    } else if (n === rows.length) {
      els.applyCount.textContent = `即将下发 ${n} 条`;
    } else {
      els.applyCount.textContent = `即将下发 ${n} 条（勾选 ${rows.length} 行，按责任人拆分）`;
    }
    renderApplyLedger();
  }

  function previewVersionKey(item) {
    return String(
      (item && (item.targetVersion || item.registrationVersion)) || ""
    ).trim() || "未指定版本";
  }

  function looksLikeSoftwareVersion(value) {
    return /^v?\s*\d+\.\d+\.\d+\.\d+$/i.test(String(value || "").trim());
  }

  function normalizePreviewDocFields(item) {
    if (!item) return item;
    const tv = String(item.targetVersion || item.registrationVersion || "").trim();
    const fv = String(item.fileVersion || "").trim();
    if (!tv && looksLikeSoftwareVersion(fv)) {
      item.targetVersion = fv;
      item.fileVersion = "";
      if (!String(item.registrationVersion || "").trim()) item.registrationVersion = fv;
    } else if (fv && tv && fv === tv && looksLikeSoftwareVersion(fv)) {
      item.fileVersion = "";
    }
    item.documentNumber = String(item.documentNumber || "").trim();
    item.fileVersion = String(item.fileVersion || "").trim();
    const kind = String(item.taskType || "").trim();
    if (!kind || LEGACY_AUTO_VERSION_TASK_TYPES[kind]) {
      item.taskType = DEFAULT_VERSION_TASK_TYPE;
    }
    if (item.explanation == null) {
      item.explanation = String(item.notes || item.reason || "").trim();
      item.notes = "";
    } else {
      item.explanation = String(item.explanation || "").trim();
      item.notes = String(item.notes || "").trim();
    }
    return item;
  }

  function previewFileNameKey(name) {
    return String(name || "").trim().toLowerCase();
  }

  function listPreviewFilenameConflicts(items) {
    const groups = new Map();
    (items || []).forEach((item) => {
      if (isPreviewDeleted(item)) return;
      const name = previewFileNameKey(item && item.fileName);
      if (!name) return;
      const key = `${previewVersionKey(item)}\0${name}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    const out = [];
    groups.forEach((rows) => {
      if (rows.length < 2) return;
      out.push({
        version: previewVersionKey(rows[0]),
        fileName: String((rows[0] && rows[0].fileName) || "").trim(),
        count: rows.length,
        items: rows,
      });
    });
    return out;
  }

  function formatFilenameConflicts(conflicts) {
    if (!conflicts || !conflicts.length) return "同一项目、同一版本下文件名不能重复";
    return (
      "同一项目、同一版本下文件名不能重复：" +
      conflicts
        .map((row) => `版本 ${row.version} 的「${row.fileName}」有 ${row.count} 条`)
        .join("；")
    );
  }

  function findSameNameInVersion(item, items) {
    const name = previewFileNameKey(item && item.fileName);
    if (!name) return null;
    const ver = previewVersionKey(item);
    const selfKey = originKeyOf(item);
    return (
      (items || []).find((row) => {
        if (!row || row === item) return false;
        if (originKeyOf(row) === selfKey) return false;
        if (isPreviewDeleted(row)) return false;
        if (previewFileNameKey(row.fileName) !== name) return false;
        return previewVersionKey(row) === ver;
      }) || null
    );
  }

  function findMoveFilenameConflict(moving, destVer, items) {
    const movingKeys = new Set((moving || []).map((item) => originKeyOf(item)));
    const counts = new Map();
    const add = (item) => {
      if (!item || isPreviewDeleted(item)) return;
      const name = previewFileNameKey(item.fileName);
      if (!name) return;
      const cur = counts.get(name) || {
        count: 0,
        fileName: String(item.fileName || "").trim(),
        fromOtherVersion: false,
      };
      cur.count += 1;
      if (previewVersionKey(item) !== destVer) cur.fromOtherVersion = true;
      counts.set(name, cur);
    };
    (items || []).forEach((item) => {
      if (!item || movingKeys.has(originKeyOf(item))) return;
      if (previewVersionKey(item) !== destVer) return;
      add(item);
    });
    (moving || []).forEach((item) => add(item));
    let found = null;
    counts.forEach((row) => {
      if (found || row.count < 2) return;
      found = {
        fileName: row.fileName,
        version: destVer,
        count: row.count,
        crossVersion: row.fromOtherVersion,
      };
    });
    return found;
  }

  function movingItemsForAnchor(moving, anchor) {
    const list = moving || [];
    if (!anchor) return { toMove: list, ignoredOther: 0, destVer: "" };
    const destVer = previewVersionKey(anchor);
    const sameVer = [];
    const otherVer = [];
    list.forEach((item) => {
      if (previewVersionKey(item) === destVer) sameVer.push(item);
      else otherVer.push(item);
    });
    if (sameVer.length && otherVer.length) {
      return { toMove: sameVer, ignoredOther: otherVer.length, destVer };
    }
    return { toMove: list, ignoredOther: 0, destVer };
  }

  function markPreviewFilenameConflicts() {
    const conflicts = listPreviewFilenameConflicts(previewItems);
    const dupKeys = new Set();
    conflicts.forEach((row) => {
      (row.items || []).forEach((item) => dupKeys.add(originKeyOf(item)));
    });
    if (els.previewBody) {
      els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]").forEach((tr) => {
        const idx = Number(tr.getAttribute("data-vtg-preview-idx"));
        const item = previewItems[idx];
        const dup = Boolean(item && dupKeys.has(originKeyOf(item)));
        tr.classList.toggle("vtg-name-dup", dup);
        const input = tr.querySelector(".vtg-filename-input");
        if (input) input.classList.toggle("vtg-name-dup-input", dup);
      });
    }
    return conflicts;
  }

  function comparePreviewVersions(a, b) {
    const parse = (s) => {
      const m = String(s || "").trim().match(/^v?\s*(\d+)\.(\d+)\.(\d+)\.(\d+)$/i);
      return m ? [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])] : null;
    };
    if (a === "未指定版本" && b !== "未指定版本") return 1;
    if (b === "未指定版本" && a !== "未指定版本") return -1;
    const pa = parse(a);
    const pb = parse(b);
    if (pa && pb) {
      for (let i = 0; i < 4; i += 1) {
        if (pa[i] !== pb[i]) return pa[i] - pb[i];
      }
      return 0;
    }
    return String(a).localeCompare(String(b), "zh");
  }

  function previewChapterKey(item) {
    return String((item && (item.chapter || item.processBranchLabel)) || "其它").trim() || "其它";
  }

  function isReleaseRecordName(name) {
    return String(name || "").trim() === "发布记录";
  }

  function applyReleaseRecordDateUi(row, fileName) {
    if (!row) return;
    const input = row.querySelector('[data-vtg-field="documentDisplayDate"]');
    if (!input) return;
    const hit = isReleaseRecordName(fileName);
    input.classList.toggle("vtg-doc-date-alert", hit);
    if (hit) {
      input.title = "发布记录的文档日期需与发布日对齐，请核对";
    } else if (input.getAttribute("data-vtg-field") === "documentDisplayDate") {
      input.removeAttribute("title");
    }
  }

  function previewArchiveFrequency(item) {
    return (
      String((item && item.archiveFrequency) || "").trim() ||
      (String((item && item.taskType) || "").includes("流程") ? "流程" : "")
    );
  }

  function previewColValue(item, key) {
    if (key === "sortOrder") return String(Number((item && item.sortOrder) || 0) + 1);
    if (key === "recordStatus") return RECORD_STATUS_LABELS[recordStatusOf(item)] || "";
    if (key === "applied") {
      const state = previewApplyState(item);
      if (state === "applied") return "已下发";
      if (state === "partial") return "部分下发";
      return "未下发";
    }
    if (key === "changeKind") return CHANGE_KIND_LABELS[changeKindOf(item)] || "无变更";
    if (key === "targetVersion") {
      const ver = previewVersionKey(item);
      return ver === "未指定版本" ? "" : ver;
    }
    if (key === "archiveFrequency") return previewArchiveFrequency(item);
    if (key === "triggeredBy") return formatTriggerBits(item && item.triggeredBy);
    if (key === "chapter") return previewChapterKey(item);
    if (key === "isSystemRecord") return isSystemRecordOf(item) ? "是" : "否";
    return String((item && item[key]) || "").trim();
  }

  function previewColSortValue(item, key) {
    if (key === "sortOrder") return Number((item && item.sortOrder) || 0);
    if (key === "recordStatus") {
      const order = { adopt: 0, pending: 1, discard: 2 };
      return order[recordStatusOf(item)] ?? 9;
    }
    if (key === "applied") {
      const order = { applied: 0, partial: 1, none: 2 };
      return order[previewApplyState(item)] ?? 9;
    }
    if (key === "changeKind") {
      const order = { "": 0, add: 1, update: 2, delete: 3 };
      return order[changeKindOf(item)] ?? 0;
    }
    if (key === "isSystemRecord") return isSystemRecordOf(item) ? 0 : 1;
    if (key === "dueDate" || key === "documentDisplayDate") return String((item && item[key]) || "");
    if (key === "targetVersion") return previewVersionKey(item);
    return previewColValue(item, key).toLowerCase();
  }

  function comparePreviewCol(a, b, key) {
    if (key === "targetVersion") {
      return comparePreviewVersions(previewVersionKey(a), previewVersionKey(b));
    }
    const va = previewColSortValue(a, key);
    const vb = previewColSortValue(b, key);
    if (typeof va === "number" && typeof vb === "number") return va - vb;
    return String(va).localeCompare(String(vb), "zh", { numeric: true, sensitivity: "base" });
  }

  function hasPreviewColFilters() {
    return Object.keys(previewColFilters).some((key) => String(previewColFilters[key] || "").trim());
  }

  function itemMatchesColFilters(item) {
    return Object.keys(previewColFilters).every((key) => {
      const q = String(previewColFilters[key] || "").trim();
      if (!q) return true;
      if (key === "recordStatus") return recordStatusOf(item) === q;
      if (key === "applied") return previewApplyState(item) === q;
      if (key === "isSystemRecord") {
        if (q === "1" || q === "yes" || q === "是") return isSystemRecordOf(item);
        if (q === "0" || q === "no" || q === "否") return !isSystemRecordOf(item);
        return true;
      }
      if (key === "changeKind") {
        if (q === "none") return !changeKindOf(item);
        return changeKindOf(item) === q;
      }
      return previewColValue(item, key).toLowerCase().includes(q.toLowerCase());
    });
  }

  function updatePreviewHeadUi() {
    document.querySelectorAll("[data-vtg-sort]").forEach((btn) => {
      const key = btn.getAttribute("data-vtg-sort") || "";
      const ind = btn.querySelector(".vtg-sort-ind");
      const active = Boolean(previewColSort && previewColSort.key === key);
      btn.classList.toggle("is-active", active);
      btn.setAttribute(
        "aria-sort",
        active ? (previewColSort.dir === "desc" ? "descending" : "ascending") : "none"
      );
      if (ind) ind.textContent = active ? (previewColSort.dir === "desc" ? "▼" : "▲") : "⇅";
    });
    if (els.clearColFiltersBtn) {
      els.clearColFiltersBtn.classList.toggle(
        "d-none",
        !previewColSort && !hasPreviewColFilters()
      );
    }
  }

  function clearPreviewColFilters() {
    previewColSort = null;
    previewColFilters = {};
    document.querySelectorAll("[data-vtg-filter]").forEach((el) => {
      el.value = "";
    });
    updatePreviewHeadUi();
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    renderPreviewTable(previewItems);
  }

  function togglePreviewColSort(key) {
    if (!key) return;
    if (previewColSort && previewColSort.key === key) {
      previewColSort = previewColSort.dir === "asc" ? { key, dir: "desc" } : null;
    } else {
      previewColSort = { key, dir: "asc" };
    }
    updatePreviewHeadUi();
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    renderPreviewTable(previewItems);
  }

  function applyPreviewColFilter(el) {
    const key = el && el.getAttribute("data-vtg-filter");
    if (!key) return;
    previewColFilters[key] = el.value;
    updatePreviewHeadUi();
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    renderPreviewTable(previewItems);
  }

  function loadPreviewColOrder() {
    let stored = [];
    try {
      stored = JSON.parse(localStorage.getItem(PREVIEW_COL_ORDER_LS) || "[]");
    } catch (err) {
      stored = [];
    }
    const next = [];
    if (Array.isArray(stored)) {
      stored.forEach((key) => {
        if (PREVIEW_COL_KEYS.indexOf(key) >= 0 && next.indexOf(key) < 0) next.push(key);
      });
    }
    PREVIEW_COL_KEYS.forEach((key) => {
      if (next.indexOf(key) < 0) next.push(key);
    });
    return next;
  }

  function savePreviewColOrder(order) {
    previewColOrder = order.slice();
    try {
      localStorage.setItem(PREVIEW_COL_ORDER_LS, JSON.stringify(previewColOrder));
    } catch (err) {
      /* ignore */
    }
  }

  function applyPreviewColOrder() {
    const table = els.previewTableWrap && els.previewTableWrap.querySelector(".vtg-preview-table");
    if (!table) return;
    const order = previewColOrder.length ? previewColOrder : PREVIEW_COL_KEYS;
    table.querySelectorAll("tr").forEach((tr) => {
      if (tr.querySelector("[colspan]")) return;
      const byKey = new Map();
      Array.from(tr.children).forEach((cell) => {
        const key = cell.getAttribute("data-vtg-col");
        if (key) byKey.set(key, cell);
      });
      if (!byKey.size) return;
      order.forEach((key) => {
        const cell = byKey.get(key);
        if (cell) tr.appendChild(cell);
      });
    });
  }

  function movePreviewCol(fromKey, toKey) {
    if (!fromKey || !toKey || fromKey === toKey) return false;
    const order = previewColOrder.slice();
    const from = order.indexOf(fromKey);
    const to = order.indexOf(toKey);
    if (from < 0 || to < 0) return false;
    order.splice(from, 1);
    order.splice(to, 0, fromKey);
    savePreviewColOrder(order);
    applyPreviewColOrder();
    return true;
  }

  function clearPreviewColDragUi(thead) {
    if (!thead) return;
    thead.classList.remove("vtg-col-reordering");
    thead.querySelectorAll(".vtg-col-dragging, .vtg-col-drop").forEach((el) => {
      el.classList.remove("vtg-col-dragging", "vtg-col-drop");
    });
  }

  function previewColThKey(el) {
    const cell = el && el.closest ? el.closest("#vtgPreviewTableWrap [data-vtg-col]") : null;
    return cell ? cell.getAttribute("data-vtg-col") || "" : "";
  }

  function bindPreviewHead() {
    const table = els.previewTableWrap && els.previewTableWrap.querySelector("table");
    const thead = table && table.querySelector("thead");
    if (!thead || thead.dataset.vtgHeadBound) return;
    thead.dataset.vtgHeadBound = "1";
    thead.querySelectorAll("th[data-vtg-col]").forEach((th) => {
      th.draggable = false;
    });
    thead.addEventListener("click", (ev) => {
      if (previewColSuppressSort) {
        previewColSuppressSort = false;
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }
      const btn = ev.target.closest("[data-vtg-sort]");
      if (!btn) return;
      ev.preventDefault();
      togglePreviewColSort(btn.getAttribute("data-vtg-sort") || "");
    });
    thead.addEventListener("change", (ev) => {
      const el = ev.target.closest("[data-vtg-filter]");
      if (!el) return;
      applyPreviewColFilter(el);
    });
    thead.addEventListener("input", (ev) => {
      const el = ev.target.closest("input[data-vtg-filter]");
      if (!el) return;
      window.clearTimeout(previewFilterTimer);
      previewFilterTimer = window.setTimeout(() => applyPreviewColFilter(el), 180);
    });
    thead.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      if (ev.target.closest("input, select, textarea")) return;
      const th = ev.target.closest("th[data-vtg-col]");
      if (!th) return;
      previewColDragKey = th.getAttribute("data-vtg-col") || "";
      previewColDragMoved = false;
      previewColDropKey = "";
      previewColDragOrigin = {
        x: ev.clientX,
        y: ev.clientY,
        pointerId: ev.pointerId,
        th,
      };
    });
    window.addEventListener(
      "pointermove",
      (ev) => {
        if (!previewColDragKey || !previewColDragOrigin) return;
        const dx = ev.clientX - previewColDragOrigin.x;
        const dy = ev.clientY - previewColDragOrigin.y;
        if (!previewColDragMoved && Math.hypot(dx, dy) < 8) return;
        if (!previewColDragMoved) {
          previewColDragMoved = true;
          thead.classList.add("vtg-col-reordering");
          thead.querySelectorAll(`th[data-vtg-col="${previewColDragKey}"]`).forEach((el) => {
            el.classList.add("vtg-col-dragging");
          });
          try {
            previewColDragOrigin.th.setPointerCapture(previewColDragOrigin.pointerId);
          } catch (err) {
            /* ignore */
          }
        }
        ev.preventDefault();
        const overKey = previewColThKey(document.elementFromPoint(ev.clientX, ev.clientY));
        previewColDropKey = overKey && overKey !== previewColDragKey ? overKey : "";
        thead.querySelectorAll(".vtg-col-drop").forEach((el) => el.classList.remove("vtg-col-drop"));
        if (previewColDropKey) {
          thead.querySelectorAll(`th[data-vtg-col="${previewColDropKey}"]`).forEach((el) => {
            el.classList.add("vtg-col-drop");
          });
        }
      },
      { passive: false }
    );
    const endPreviewColPointer = (ev) => {
      if (!previewColDragKey || !previewColDragOrigin) return;
      if (ev && ev.pointerId !== previewColDragOrigin.pointerId) return;
      const fromKey = previewColDragKey;
      const toKey = previewColDropKey;
      const moved = previewColDragMoved;
      try {
        if (moved) previewColDragOrigin.th.releasePointerCapture(previewColDragOrigin.pointerId);
      } catch (err) {
        /* ignore */
      }
      clearPreviewColDragUi(thead);
      previewColDragKey = "";
      previewColDropKey = "";
      previewColDragMoved = false;
      previewColDragOrigin = null;
      if (!moved) return;
      previewColSuppressSort = true;
      window.setTimeout(() => {
        previewColSuppressSort = false;
      }, 0);
      if (movePreviewCol(fromKey, toKey)) note("已调整列顺序");
    };
    window.addEventListener("pointerup", endPreviewColPointer);
    window.addEventListener("pointercancel", endPreviewColPointer);
  }

  function ensureSortOrders(items) {
    const groups = new Map();
    (items || []).forEach((item) => {
      const ver = previewVersionKey(item);
      if (!groups.has(ver)) groups.set(ver, []);
      groups.get(ver).push(item);
    });
    groups.forEach((list) => {
      const assigned = [];
      const missing = [];
      list.forEach((item) => {
        if (Number.isFinite(Number(item.sortOrder))) assigned.push(item);
        else missing.push(item);
      });
      assigned.sort((a, b) => Number(a.sortOrder) - Number(b.sortOrder));
      if (!assigned.length) {
        missing.sort((a, b) => {
          const ca = previewChapterKey(a);
          const cb = previewChapterKey(b);
          const ia = PREVIEW_CHAPTER_ORDER.indexOf(ca);
          const ib = PREVIEW_CHAPTER_ORDER.indexOf(cb);
          const ra = ia < 0 ? 1000 : ia;
          const rb = ib < 0 ? 1000 : ib;
          if (ra !== rb) return ra - rb;
          return 0;
        });
        missing.forEach((item, i) => {
          item.sortOrder = i;
        });
        return;
      }
      let next = Math.max(...assigned.map((x) => Number(x.sortOrder))) + 1;
      missing.forEach((item) => {
        item.sortOrder = next;
        next += 1;
      });
      assigned.concat(missing).forEach((item, i) => {
        item.sortOrder = i;
      });
    });
    const ordered = [];
    Array.from(groups.keys())
      .sort(comparePreviewVersions)
      .forEach((ver) => {
        const list = groups.get(ver) || [];
        list.sort((a, b) => Number(a.sortOrder) - Number(b.sortOrder));
        list.forEach((item) => ordered.push(item));
      });
    items.length = 0;
    ordered.forEach((item) => items.push(item));
  }

  function listPreviewVersionStats() {
    const map = new Map();
    visiblePreviewItems().forEach((item) => {
      const key = previewVersionKey(item);
      map.set(key, (map.get(key) || 0) + 1);
    });
    return Array.from(map.entries()).sort((left, right) => comparePreviewVersions(left[0], right[0]));
  }

  function resetPreviewVersionUi() {
    previewVersionFilter = "";
    previewCollapsedVersions.clear();
  }

  function renderPreviewVersionBar() {
    if (!els.previewVersionBar) return;
    const stats = listPreviewVersionStats();
    if (!stats.length) {
      els.previewVersionBar.classList.add("d-none");
      els.previewVersionBar.innerHTML = "";
      return;
    }
    if (previewVersionFilter && !stats.some((row) => row[0] === previewVersionFilter)) {
      previewVersionFilter = "";
    }
    const chips = [
      `<button type="button" class="vtg-version-chip${previewVersionFilter ? "" : " is-active"}" data-vtg-ver-filter="">全部<span class="vtg-chip-n">${visiblePreviewItems().length}</span></button>`,
      ...stats.map(([ver, count]) => {
        const active = previewVersionFilter === ver ? " is-active" : "";
        return `<button type="button" class="vtg-version-chip${active}" data-vtg-ver-filter="${escapeHtml(ver)}"><span class="font-monospace">${escapeHtml(ver)}</span><span class="vtg-chip-n">${count}</span></button>`;
      }),
    ];
    els.previewVersionBar.innerHTML = `
      <span class="vtg-version-bar-label">按版本</span>
      ${chips.join("")}
      <span class="vtg-version-bar-actions">
        <button type="button" class="btn btn-outline-secondary btn-sm py-0" data-vtg-ver-expand-all>全部展开</button>
        <button type="button" class="btn btn-outline-secondary btn-sm py-0" data-vtg-ver-collapse-all>全部收起</button>
      </span>`;
    els.previewVersionBar.classList.remove("d-none");
  }

  function applyPreviewVersionUi() {
    if (!els.previewBody) {
      updatePreviewSelectionUi();
      return;
    }
    els.previewBody.querySelectorAll("tr[data-vtg-ver]").forEach((tr) => {
      const ver = tr.getAttribute("data-vtg-ver") || "";
      const isHeader = tr.classList.contains("vtg-version-row");
      const filteredOut = Boolean(previewVersionFilter && ver !== previewVersionFilter);
      const collapsed = !isHeader && previewCollapsedVersions.has(ver);
      tr.classList.toggle("vtg-preview-hidden", filteredOut || collapsed);
    });
    els.previewBody.querySelectorAll("tr.vtg-version-row").forEach((tr) => {
      const ver = tr.getAttribute("data-vtg-ver") || "";
      const expanded = !previewCollapsedVersions.has(ver);
      tr.setAttribute("aria-expanded", expanded ? "true" : "false");
      const caret = tr.querySelector(".vtg-caret");
      if (caret) caret.textContent = expanded ? "▼" : "▶";
    });
    if (els.previewVersionBar) {
      els.previewVersionBar.querySelectorAll("[data-vtg-ver-filter]").forEach((btn) => {
        const val = btn.getAttribute("data-vtg-ver-filter") || "";
        btn.classList.toggle("is-active", val === (previewVersionFilter || ""));
      });
    }
    updatePreviewSelectionUi();
    fitFilenameInputs();
    fitPreviewTableViewport();
    markPreviewFilenameConflicts();
    applyPreviewLocateUi();
  }

  function renderPreviewTable(items, options) {
    const opts = options || {};
    previewItems = Array.isArray(items)
      ? items.map((x) => {
          const rec = { ...x };
          normalizePreviewDocFields(rec);
          rec.recordStatus = recordStatusOf(rec);
          ensureOriginKey(rec);
          return rec;
        })
      : [];
    if (opts.restoreSelection) {
      restorePreviewSelection(previewItems, opts.selectionScope);
    } else {
      prunePreviewSelection(previewItems);
    }
    setPreviewSaveEnabled();
    if (!els.previewBody) return;
    if (!previewItems.length) {
      previewSelectedKeys.clear();
      if (!opts.skipPersist && currentJobId) savePreviewSelection(opts.selectionScope);
      resetPreviewVersionUi();
      renderPreviewVersionBar();
      if (els.previewCount) els.previewCount.textContent = "0 条";
      if (els.previewHeadCheck) {
        els.previewHeadCheck.checked = false;
        els.previewHeadCheck.indeterminate = false;
        els.previewHeadCheck.disabled = true;
      }
      if (els.previewSelectHint) {
        els.previewSelectHint.textContent = "仅「选用」可勾选下发。全选作用于当前可见行。";
      }
      els.previewBody.innerHTML =
        `<tr><td colspan="${PREVIEW_COLSPAN}" class="text-muted small text-center py-3">${
          currentJobId
            ? "当前没有记录，可点「添加记录」或保存空清单"
            : "预览后将在此显示任务清单"
        }</td></tr>`;
      renderChangeLog([]);
      fitPreviewTableViewport();
      updatePreviewHeadUi();
      return;
    }
    ensureSortOrders(previewItems);
    const byVersion = new Map();
    previewItems.forEach((item, idx) => {
      if (isHiddenPreviewItem(item)) return;
      if (!itemMatchesColFilters(item)) return;
      const ver = previewVersionKey(item);
      if (!byVersion.has(ver)) byVersion.set(ver, []);
      byVersion.get(ver).push({ item, idx });
    });
    if (!byVersion.size) {
      renderPreviewVersionBar();
      const hiddenDeletes = previewItems.filter((item) => isHiddenPreviewItem(item)).length;
      const onlyHidden = hiddenDeletes && !visiblePreviewItems().length;
      if (els.previewCount) {
        els.previewCount.textContent = onlyHidden ? `0 条（已隐藏 ${hiddenDeletes} 条）` : "0 条";
      }
      if (els.previewSelectHint) {
        els.previewSelectHint.textContent = onlyHidden
          ? "已删除记录已从列表隐藏，不占行；可在下方采集区查看。"
          : "没有符合表头筛选的记录，可点「清除筛选/排序」。";
      }
      els.previewBody.innerHTML =
        `<tr><td colspan="${PREVIEW_COLSPAN}" class="text-muted small text-center py-3">${
          onlyHidden
            ? "清单已加载。该范围内记录已删除，不再显示。可在下方采集区查看。"
            : "没有符合表头筛选的记录，可点「清除筛选/排序」"
        }</td></tr>`;
      renderChangeLog(previewItems);
      applyPreviewVersionUi();
      updatePreviewHeadUi();
      return;
    }
    byVersion.forEach((rows) => {
      rows.sort((a, b) => {
        if (previewColSort && previewColSort.key) {
          const cmp = comparePreviewCol(a.item, b.item, previewColSort.key);
          if (cmp) return previewColSort.dir === "desc" ? -cmp : cmp;
        }
        return Number(a.item.sortOrder) - Number(b.item.sortOrder) || a.idx - b.idx;
      });
    });
    const versionKeys = Array.from(byVersion.keys()).sort(comparePreviewVersions);
    const html = [];
    versionKeys.forEach((ver) => {
      const versionRows = byVersion.get(ver) || [];
      const triggerBits = Array.from(
        new Set(
          versionRows.flatMap(({ item }) =>
            Array.isArray(item.triggeredBy) ? item.triggeredBy : []
          )
        )
      );
      const triggerText = triggerBits.length ? ` · ${formatTriggerBits(triggerBits)}` : "";
      html.push(
        `<tr class="vtg-version-row" data-vtg-ver="${escapeHtml(ver)}" role="button" tabindex="0" aria-expanded="true">
          <td colspan="${PREVIEW_COLSPAN}"><div class="vtg-ver-head">
            <span class="vtg-ver-head-label"><span class="vtg-caret">▼</span>版本 <span class="font-monospace">${escapeHtml(ver)}</span>（${versionRows.length}）${escapeHtml(triggerText)}</span>
            <span class="vtg-ver-actions">
              <button type="button" class="btn btn-outline-secondary btn-sm py-0" data-vtg-copy-ver="${escapeHtml(ver)}">复制本版</button>
              <button type="button" class="btn btn-outline-danger btn-sm py-0" data-vtg-delete-ver="${escapeHtml(ver)}">删除本版</button>
            </span>
          </div></td>
        </tr>`
      );
      let lastChapter = null;
      const useChapterHeads = !previewColSort;
      versionRows.forEach(({ item, idx }) => {
        const chapter = previewChapterKey(item);
        if (useChapterHeads && chapter !== lastChapter) {
          const chapterCount = versionRows.filter((row) => previewChapterKey(row.item) === chapter).length;
          html.push(
            `<tr class="vtg-chapter-row" data-vtg-ver="${escapeHtml(ver)}" data-vtg-chapter="${escapeHtml(chapter)}"><td colspan="${PREVIEW_COLSPAN}">${escapeHtml(chapter)}（${chapterCount}）</td></tr>`
          );
          lastChapter = chapter;
        }
        const triggers = formatTriggerBits(item.triggeredBy);
        const targetVersion = item.targetVersion || item.registrationVersion || "";
        const freq = previewArchiveFrequency(item) || "—";
        const status = recordStatusOf(item);
        const deleted = isPreviewDeleted(item);
        const adopted = canSelectPreview(item);
        const checkable = canCheckPreview(item);
        const selected = checkable && previewSelectedKeys.has(taskIdentity(item));
        const disabledAttr = deleted ? " disabled" : "";
        const rowClass = [
          status === "discard" ? "vtg-status-discard" : "",
          status === "pending" ? "vtg-status-pending" : "",
          changeKindOf(item) === "delete" ? "vtg-change-delete" : "",
          changeKindOf(item) === "add" ? "vtg-change-add" : "",
          changeKindOf(item) === "update" ? "vtg-change-update" : "",
        ]
          .filter(Boolean)
          .join(" ");
        const actionBtn = deleted
          ? `<button type="button" class="btn btn-outline-secondary btn-sm py-0 px-1" data-vtg-restore-preview="${idx}" title="撤销删除">还原</button>`
          : `<button type="button" class="btn btn-outline-danger btn-sm py-0 px-1" data-vtg-remove-preview="${idx}" title="标记删除">×</button>`;
        html.push(`<tr data-vtg-preview-idx="${idx}" data-vtg-ver="${escapeHtml(ver)}" class="${rowClass}">
          <td class="text-center" data-vtg-col="check"><input type="checkbox" class="form-check-input" data-vtg-select-row ${selected ? "checked" : ""} ${checkable ? "" : "disabled"} title="${deleted ? "已删除，不能勾选" : adopted ? "勾选后可下发或批量调整顺序" : "勾选后可批量调整顺序；仅选用会下发"}"></td>
          <td class="vtg-col-idx" data-vtg-col="sortOrder"><span class="vtg-drag-handle" draggable="true" title="拖动调整顺序，也可拖到其他版本或章节">⋮⋮</span><span class="text-muted small">${Number(item.sortOrder) + 1}</span></td>
          <td data-vtg-col="recordStatus">${recordStatusSelectHtml(status, deleted)}</td>
          <td class="text-center" data-vtg-col="applied">${previewAppliedBadgeHtml(item)}</td>
          <td class="vtg-col-system text-center" data-vtg-col="isSystemRecord">${isSystemRecordSelectHtml(item, deleted)}</td>
          <td class="vtg-change-cell" data-vtg-col="changeKind">${changeKindBadgeHtml(item)}</td>
          <td class="vtg-col-filename" data-vtg-col="fileName"><textarea class="form-control form-control-sm vtg-filename-input" data-vtg-field="fileName" rows="2" title="${escapeHtml(item.fileName || "")}"${disabledAttr}>${escapeHtml(item.fileName || "")}</textarea></td>
          <td data-vtg-col="taskType"><input class="form-control form-control-sm" data-vtg-field="taskType" value="${escapeHtml(item.taskType || "")}"${disabledAttr}></td>
          <td data-vtg-col="targetVersion"><input class="form-control form-control-sm font-monospace" data-vtg-field="targetVersion" value="${escapeHtml(targetVersion)}"${disabledAttr}></td>
          <td data-vtg-col="author"><input class="form-control form-control-sm" data-vtg-field="author" value="${escapeHtml(item.author || "")}" placeholder="张三,李四"${disabledAttr} title="多人用英文逗号分隔，下发时拆成多条"></td>
          <td data-vtg-col="dueDate"><input type="date" class="form-control form-control-sm" data-vtg-field="dueDate" value="${escapeHtml(item.dueDate || "")}"${disabledAttr}></td>
          <td data-vtg-col="documentDisplayDate"><input type="date" class="form-control form-control-sm${
            isReleaseRecordName(item.fileName) ? " vtg-doc-date-alert" : ""
          }" data-vtg-field="documentDisplayDate" value="${escapeHtml(item.documentDisplayDate || "")}"${
            isReleaseRecordName(item.fileName)
              ? ' title="发布记录的文档日期需与发布日对齐，请核对"'
              : ""
          }${disabledAttr}></td>
          <td data-vtg-col="belongingModule"><input class="form-control form-control-sm" data-vtg-field="belongingModule" value="${escapeHtml(item.belongingModule || "")}"${disabledAttr}></td>
          <td class="small text-muted" data-vtg-col="archiveFrequency">${escapeHtml(freq)}</td>
          <td class="small text-muted" data-vtg-col="triggeredBy" title="版本号格式 X.Y.Z.B，按最高变化位：X&gt;Y&gt;Z&gt;B">${triggers}</td>
          <td data-vtg-col="changeReason"><input class="form-control form-control-sm" data-vtg-field="changeReason" value="${escapeHtml(item.changeReason || "")}" placeholder="可后补"></td>
          <td class="vtg-col-docno" data-vtg-col="documentNumber"><input class="form-control form-control-sm font-monospace" data-vtg-field="documentNumber" value="${escapeHtml(item.documentNumber || "")}" placeholder="可从文控同步"${disabledAttr}></td>
          <td class="vtg-col-filever" data-vtg-col="fileVersion"><input class="form-control form-control-sm" data-vtg-field="fileVersion" value="${escapeHtml(item.fileVersion || "")}" placeholder="如 V1.0"${disabledAttr}></td>
          <td class="vtg-col-explanation" data-vtg-col="explanation"><input class="form-control form-control-sm" data-vtg-field="explanation" value="${escapeHtml(item.explanation || "")}" placeholder="说明"${disabledAttr}></td>
          <td class="vtg-col-notes" data-vtg-col="notes"><input class="form-control form-control-sm" data-vtg-field="notes" value="${escapeHtml(item.notes || "")}" placeholder="下发到任务"${disabledAttr}></td>
          <td data-vtg-col="action">${actionBtn}</td>
        </tr>`);
      });
    });
    els.previewBody.innerHTML = html.join("");
    renderPreviewVersionBar();
    applyPreviewVersionUi();
    renderChangeLog(previewItems);
    if (els.addPreviewPanel && !els.addPreviewPanel.classList.contains("d-none")) {
      fillAddPreviewAnchorOptions();
    }
    if (els.movePreviewPanel && !els.movePreviewPanel.classList.contains("d-none")) {
      fillMoveAnchorOptions();
      updateMovePreviewHint();
    }
    if (els.copyPreviewPanel && !els.copyPreviewPanel.classList.contains("d-none")) {
      fillCopyVersionOptions({ keepSelection: true });
      updateCopyPreviewHint();
    }
    if (els.batchDueDatePanel && !els.batchDueDatePanel.classList.contains("d-none")) {
      updateBatchDueDateHint();
    }
    if (els.deleteVersionPanel && !els.deleteVersionPanel.classList.contains("d-none")) {
      fillDeleteVersionOptions({ keepSelection: true });
      updateDeleteVersionHint();
    }
    updatePreviewHeadUi();
    applyPreviewColOrder();
  }

  function locatePreviewItem() {
    if (!previewLocateOriginKey) return null;
    return previewItems.find((item) => originKeyOf(item) === previewLocateOriginKey) || null;
  }

  function locatePreviewRowEl() {
    const item = locatePreviewItem();
    if (!item || !els.previewBody) return null;
    return (
      Array.from(els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]")).find((tr) => {
        const idx = Number(tr.getAttribute("data-vtg-preview-idx"));
        return previewItems[idx] && originKeyOf(previewItems[idx]) === originKeyOf(item);
      }) || null
    );
  }

  function applyPreviewLocateUi() {
    if (!els.previewBody) return;
    const key = previewLocateOriginKey;
    els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]").forEach((tr) => {
      const idx = Number(tr.getAttribute("data-vtg-preview-idx"));
      const item = previewItems[idx];
      tr.classList.toggle("vtg-row-locate", Boolean(item && key && originKeyOf(item) === key));
    });
    updatePreviewLocateHint();
  }

  function updatePreviewLocateHint() {
    const item = locatePreviewItem();
    const text = item
      ? `参照：${previewRecordLabel(item)}。点「添加记录」会插到这行后面。`
      : "点一下目标行或把鼠标停在上面，该行会标蓝条；再点「添加记录」会插到这行后面。";
    if (els.locateHint) {
      els.locateHint.textContent = text;
      els.locateHint.classList.toggle("is-empty", !item);
    }
    if (els.addPreviewHint) {
      els.addPreviewHint.textContent = item
        ? `将添加到「${previewRecordLabel(item)}」旁边（可改参照和前/后）。`
        : "尚未锁定参照行。请先把鼠标在目标行上停一会儿，或在下方列表里选择。";
    }
  }

  function queuePreviewLocate(idx) {
    if (!Number.isFinite(idx) || !previewItems[idx]) return;
    previewLocateCandidateIdx = idx;
    if (previewLocateTimer) window.clearTimeout(previewLocateTimer);
    previewLocateTimer = window.setTimeout(() => {
      previewLocateTimer = 0;
      setPreviewLocateByIdx(idx);
    }, 220);
  }

  function flushPreviewLocate() {
    if (previewLocateTimer) {
      window.clearTimeout(previewLocateTimer);
      previewLocateTimer = 0;
    }
    if (previewLocateOriginKey) return;
    if (previewLocateCandidateIdx >= 0) setPreviewLocateByIdx(previewLocateCandidateIdx);
  }

  function setPreviewLocateByIdx(idx) {
    const item = previewItems[idx];
    if (!item) return;
    previewLocateCandidateIdx = idx;
    previewLocateOriginKey = originKeyOf(item);
    applyPreviewLocateUi();
  }

  function setPreviewLocateByItem(item) {
    if (!item) return;
    previewLocateOriginKey = originKeyOf(item);
    previewLocateCandidateIdx = previewItems.indexOf(item);
    applyPreviewLocateUi();
  }

  function scrollPreviewItemIntoView(originKey) {
    const key = String(originKey || previewLocateOriginKey || "").trim();
    if (!key || !els.previewBody) return;
    const tr = Array.from(els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]")).find((row) => {
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      return previewItems[idx] && originKeyOf(previewItems[idx]) === key;
    });
    if (!tr) return;
    try {
      tr.scrollIntoView({ block: "nearest", inline: "nearest" });
    } catch (err) {
      tr.scrollIntoView();
    }
  }

  function preferredAnchorIdxFromList(source) {
    const locate = locatePreviewItem();
    if (locate) {
      const hit = (source || []).find((item) => originKeyOf(item) === originKeyOf(locate));
      if (hit) return previewItems.indexOf(hit);
    }
    return -1;
  }

  function getPreviewItems() {
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    return previewItems.map((x) => ({ ...x, recordStatus: recordStatusOf(x) }));
  }

  function fitFilenameInputs() {
    if (!els.previewBody) return;
    Array.from(els.previewBody.querySelectorAll(".vtg-filename-input")).forEach((el) => {
      el.style.height = "auto";
      el.style.height = `${Math.max(38, el.scrollHeight)}px`;
    });
  }

  let previewDragRow = null;
  let previewDropTarget = null;
  let previewDragScrollSpeed = 0;
  let previewDragRaf = 0;
  let previewDragLastY = 0;

  function stopPreviewDragScroll() {
    previewDragScrollSpeed = 0;
    if (previewDragRaf) {
      cancelAnimationFrame(previewDragRaf);
      previewDragRaf = 0;
    }
  }

  function tickPreviewDragScroll() {
    previewDragRaf = 0;
    if (!previewDragRow || !previewDragScrollSpeed) return;
    const wrap = els.previewTableWrap;
    if (wrap) wrap.scrollTop += previewDragScrollSpeed;
    placePreviewDragRowAt(previewDragLastY);
    previewDragRaf = requestAnimationFrame(tickPreviewDragScroll);
  }

  function updatePreviewDragScroll(clientY) {
    const wrap = els.previewTableWrap;
    if (!wrap || !previewDragRow) {
      stopPreviewDragScroll();
      return;
    }
    const rect = wrap.getBoundingClientRect();
    const edge = 56;
    let speed = 0;
    if (clientY < rect.top + edge) {
      speed = -Math.max(8, (edge - (clientY - rect.top)) * 0.45);
    } else if (clientY > rect.bottom - edge) {
      speed = Math.max(8, (edge - (rect.bottom - clientY)) * 0.45);
    }
    previewDragScrollSpeed = speed;
    if (speed && !previewDragRaf) {
      previewDragRaf = requestAnimationFrame(tickPreviewDragScroll);
    }
    if (!speed) stopPreviewDragScroll();
  }

  function clearPreviewDropTarget() {
    if (previewDropTarget) {
      previewDropTarget.classList.remove("vtg-drop-target");
      previewDropTarget = null;
    }
  }

  function setPreviewDropTarget(tr) {
    if (previewDropTarget === tr) return;
    clearPreviewDropTarget();
    if (tr && tr !== previewDragRow) {
      tr.classList.add("vtg-drop-target");
      previewDropTarget = tr;
    }
  }

  function revealPreviewVersion(ver) {
    if (!ver || !els.previewBody) return;
    previewCollapsedVersions.delete(ver);
    Array.from(els.previewBody.querySelectorAll("tr[data-vtg-ver]")).forEach((tr) => {
      if ((tr.getAttribute("data-vtg-ver") || "") !== ver) return;
      const filteredOut = Boolean(previewVersionFilter && ver !== previewVersionFilter);
      const isHeader = tr.classList.contains("vtg-version-row");
      tr.classList.toggle("vtg-preview-hidden", filteredOut || (!isHeader && previewCollapsedVersions.has(ver)));
    });
  }

  function visiblePreviewDataRows() {
    if (!els.previewBody) return [];
    return Array.from(els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]")).filter(
      (tr) => !tr.classList.contains("vtg-preview-hidden") && tr !== previewDragRow
    );
  }

  function insertDragRowAfter(node) {
    if (!node || !previewDragRow || !node.parentNode) return;
    node.parentNode.insertBefore(previewDragRow, node.nextSibling);
  }

  function insertDragRowBefore(node) {
    if (!node || !previewDragRow || !node.parentNode) return;
    node.parentNode.insertBefore(previewDragRow, node);
  }

  function placePreviewDragRowAt(clientY) {
    if (!previewDragRow || !els.previewBody) return;
    const wrap = els.previewTableWrap;
    const probeX = wrap
      ? Math.min(wrap.getBoundingClientRect().right - 8, wrap.getBoundingClientRect().left + 36)
      : 36;
    const under = document.elementFromPoint(probeX, clientY);
    if (under && under.closest && under.closest("thead")) {
      const first = visiblePreviewDataRows()[0];
      if (first) insertDragRowBefore(first);
      setPreviewDropTarget(first || null);
      return;
    }
    const targetRow = under && under.closest ? under.closest("tr[data-vtg-ver]") : null;
    if (!targetRow || targetRow === previewDragRow) {
      if (wrap && clientY > wrap.getBoundingClientRect().bottom - 40) {
        const visibles = visiblePreviewDataRows();
        const last = visibles[visibles.length - 1];
        if (last) insertDragRowAfter(last);
        setPreviewDropTarget(last || null);
        return;
      }
      const locateEl = locatePreviewRowEl();
      if (locateEl && locateEl !== previewDragRow && !locateEl.classList.contains("vtg-preview-hidden")) {
        setPreviewDropTarget(locateEl);
        previewDragRow.setAttribute("data-vtg-ver", locateEl.getAttribute("data-vtg-ver") || "");
        const rect = locateEl.getBoundingClientRect();
        if (clientY < rect.top + rect.height / 2) insertDragRowBefore(locateEl);
        else insertDragRowAfter(locateEl);
      }
      return;
    }
    if (targetRow.classList.contains("vtg-preview-hidden")) return;
    const destVer = targetRow.getAttribute("data-vtg-ver") || "";
    if (destVer) revealPreviewVersion(destVer);
    setPreviewDropTarget(targetRow);
    previewDragRow.setAttribute("data-vtg-ver", destVer);
    if (targetRow.classList.contains("vtg-version-row")) {
      let after = targetRow.nextElementSibling;
      if (after === previewDragRow) after = after.nextElementSibling;
      if (
        after &&
        after.classList.contains("vtg-chapter-row") &&
        (after.getAttribute("data-vtg-ver") || "") === destVer
      ) {
        insertDragRowAfter(after);
      } else {
        insertDragRowAfter(targetRow);
      }
      return;
    }
    if (targetRow.classList.contains("vtg-chapter-row")) {
      insertDragRowAfter(targetRow);
      return;
    }
    if (!targetRow.hasAttribute("data-vtg-preview-idx")) return;
    const rect = targetRow.getBoundingClientRect();
    if (clientY < rect.top + rect.height / 2) {
      insertDragRowBefore(targetRow);
    } else {
      insertDragRowAfter(targetRow);
    }
  }

  function onPreviewDragOver(ev) {
    if (!previewDragRow) return;
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = "move";
    previewDragLastY = ev.clientY;
    updatePreviewDragScroll(ev.clientY);
    placePreviewDragRowAt(ev.clientY);
  }

  function snapshotPreviewLayout() {
    return previewItems
      .map(
        (item) =>
          `${originKeyOf(item)}|${previewVersionKey(item)}|${previewChapterKey(item)}|${Number(item.sortOrder)}`
      )
      .join("\n");
  }

  function applyDroppedCategory(row, item) {
    const prevVer = previewVersionKey(item);
    const prevChapter = previewChapterKey(item);
    let ver = "";
    let chapter = "";
    let neighbor = null;
    let cursor = row.previousElementSibling;
    while (cursor) {
      if (!neighbor && cursor.hasAttribute("data-vtg-preview-idx") && cursor !== row) {
        const nidx = Number(cursor.getAttribute("data-vtg-preview-idx"));
        if (!Number.isNaN(nidx) && previewItems[nidx]) neighbor = previewItems[nidx];
      }
      if (!chapter && cursor.classList.contains("vtg-chapter-row")) {
        chapter = String(cursor.getAttribute("data-vtg-chapter") || "").trim();
      }
      if (cursor.classList.contains("vtg-version-row")) {
        ver = cursor.getAttribute("data-vtg-ver") || "";
        break;
      }
      cursor = cursor.previousElementSibling;
    }
    if (!chapter || !neighbor) {
      let nxt = row.nextElementSibling;
      while (nxt && nxt === previewDragRow) nxt = nxt.nextElementSibling;
      if (nxt && nxt.classList.contains("vtg-chapter-row")) {
        if (!chapter) chapter = String(nxt.getAttribute("data-vtg-chapter") || "").trim();
      } else if (nxt && nxt.hasAttribute("data-vtg-preview-idx")) {
        const nidx = Number(nxt.getAttribute("data-vtg-preview-idx"));
        if (!Number.isNaN(nidx) && previewItems[nidx]) {
          if (!neighbor) neighbor = previewItems[nidx];
          if (!chapter) chapter = previewChapterKey(previewItems[nidx]);
        }
      }
    }
    if (ver && ver !== "未指定版本") {
      item.targetVersion = ver;
      item.registrationVersion = ver;
    } else if (ver === "未指定版本") {
      item.targetVersion = "";
      item.registrationVersion = "";
    }
    if (chapter) {
      item.chapter = chapter;
      item.processBranchLabel = chapter;
    }
    if (ver && ver !== prevVer && neighbor) {
      if (neighbor.dueDate) item.dueDate = neighbor.dueDate;
      if (neighbor.documentDisplayDate) item.documentDisplayDate = neighbor.documentDisplayDate;
    }
    refreshItemChangeMark(item);
    return previewVersionKey(item) !== prevVer || previewChapterKey(item) !== prevChapter;
  }

  function capturePreviewDupBackup(items) {
    return (items || []).map((item) => ({
      targetVersion: item.targetVersion,
      fileVersion: item.fileVersion,
      registrationVersion: item.registrationVersion,
      chapter: item.chapter,
      processBranchLabel: item.processBranchLabel,
      dueDate: item.dueDate,
      documentDisplayDate: item.documentDisplayDate,
      sortOrder: item.sortOrder,
      changeKind: item.changeKind,
      changeFields: item.changeFields,
    }));
  }

  function restorePreviewDupBackup(items, backup) {
    (items || []).forEach((item, i) => {
      if (!backup || !backup[i]) return;
      Object.assign(item, backup[i]);
    });
  }

  function commitPreviewRowOrder() {
    if (!els.previewBody || !previewDragRow) return { changed: false, movedCategory: false };
    syncPreviewItemsFromDom();
    const backupItems = previewItems.slice();
    const backupFields = capturePreviewDupBackup(previewItems);
    const before = snapshotPreviewLayout();
    const dragIdx = Number(previewDragRow.getAttribute("data-vtg-preview-idx"));
    const dragItem =
      Number.isFinite(dragIdx) && previewItems[dragIdx] ? previewItems[dragIdx] : null;
    const rows = Array.from(els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]"));
    const next = [];
    const used = new Set();
    let movedCategory = false;
    rows.forEach((tr) => {
      const idx = Number(tr.getAttribute("data-vtg-preview-idx"));
      if (Number.isNaN(idx) || used.has(idx) || !previewItems[idx]) return;
      used.add(idx);
      const item = previewItems[idx];
      if (tr === previewDragRow && applyDroppedCategory(tr, item)) movedCategory = true;
      next.push(item);
    });
    const leftovers = previewItems.filter((item, idx) => !used.has(idx));
    if (next.length + leftovers.length !== previewItems.length) {
      return { changed: false, movedCategory: false };
    }
    const counts = new Map();
    next.concat(leftovers).forEach((item) => {
      const ver = previewVersionKey(item);
      const n = counts.get(ver) || 0;
      item.sortOrder = n;
      counts.set(ver, n + 1);
    });
    previewItems = next.concat(leftovers);
    ensureSortOrders(previewItems);
    if (movedCategory && dragItem) {
      const other = findSameNameInVersion(dragItem, previewItems);
      if (other) {
        const conflicts = [
          {
            version: previewVersionKey(dragItem),
            fileName: String(dragItem.fileName || "").trim(),
            count: 2,
            items: [dragItem, other],
          },
        ];
        previewItems = backupItems;
        restorePreviewDupBackup(previewItems, backupFields);
        return { changed: false, movedCategory: false, duplicate: true, conflicts };
      }
    }
    return { changed: before !== snapshotPreviewLayout() || movedCategory, movedCategory };
  }

  function bindPreviewDrag() {
    if (!els.previewBody || els.previewBody.dataset.vtgDragBound) return;
    els.previewBody.dataset.vtgDragBound = "1";
    const wrap = els.previewTableWrap;
    els.previewBody.addEventListener("mouseover", (ev) => {
      if (previewDragRow) return;
      const row = ev.target.closest("tr[data-vtg-preview-idx]");
      if (!row) return;
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      if (Number.isNaN(idx) || !previewItems[idx]) return;
      if (ev.target.closest(".vtg-drag-handle") && previewLocateOriginKey) return;
      queuePreviewLocate(idx);
    });
    els.previewBody.addEventListener("mousedown", (ev) => {
      if (previewDragRow) return;
      if (ev.target.closest("button, a, .vtg-drag-handle")) return;
      const row = ev.target.closest("tr[data-vtg-preview-idx]");
      if (!row) return;
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      if (Number.isNaN(idx) || !previewItems[idx]) return;
      if (previewLocateTimer) {
        window.clearTimeout(previewLocateTimer);
        previewLocateTimer = 0;
      }
      setPreviewLocateByIdx(idx);
    });
    els.previewBody.addEventListener("dragstart", (ev) => {
      if (!ev.target.closest(".vtg-drag-handle")) return;
      const row = ev.target.closest("tr[data-vtg-preview-idx]");
      if (!row) return;
      previewDragRow = row;
      previewDragLastY = ev.clientY;
      row.classList.add("vtg-dragging");
      if (previewColSort) {
        previewColSort = null;
        updatePreviewHeadUi();
      }
      if (previewVersionFilter) {
        previewVersionFilter = "";
        applyPreviewVersionUi();
      }
      ev.dataTransfer.effectAllowed = "move";
      try {
        ev.dataTransfer.setData("text/plain", row.getAttribute("data-vtg-preview-idx") || "");
      } catch (err) {
        /* ignore */
      }
      try {
        ev.dataTransfer.setDragImage(row, 24, 16);
      } catch (err) {
        /* ignore */
      }
    });
    els.previewBody.addEventListener("dragend", () => {
      const row = previewDragRow;
      const dragIdx = row ? Number(row.getAttribute("data-vtg-preview-idx")) : NaN;
      const dragKey =
        Number.isFinite(dragIdx) && previewItems[dragIdx] ? originKeyOf(previewItems[dragIdx]) : "";
      if (row) row.classList.remove("vtg-dragging");
      stopPreviewDragScroll();
      const result = commitPreviewRowOrder();
      clearPreviewDropTarget();
      previewDragRow = null;
      if (result.duplicate) {
        renderPreviewTable(previewItems);
        toast(formatFilenameConflicts(result.conflicts), "warning");
      } else if (result.changed) {
        if (dragKey) previewLocateOriginKey = dragKey;
        renderPreviewTable(previewItems);
        scrollPreviewItemIntoView(dragKey);
        toast(
          result.movedCategory
            ? "已调整分类和顺序，请点「保存预览修改」"
            : "已调整顺序，请点「保存预览修改」",
          "info"
        );
      }
    });
    els.previewBody.addEventListener("dragover", onPreviewDragOver);
    if (wrap) {
      wrap.addEventListener("dragover", onPreviewDragOver);
      wrap.addEventListener(
        "wheel",
        (ev) => {
          if (!previewDragRow) return;
          wrap.scrollTop += ev.deltaY;
          previewDragLastY = ev.clientY;
          ev.preventDefault();
          placePreviewDragRowAt(ev.clientY);
        },
        { passive: false }
      );
    }
    document.addEventListener("dragover", onPreviewDragOver);
    document.addEventListener(
      "wheel",
      (ev) => {
        if (!previewDragRow || !wrap) return;
        wrap.scrollTop += ev.deltaY;
        previewDragLastY = ev.clientY;
        ev.preventDefault();
        placePreviewDragRowAt(ev.clientY);
      },
      { passive: false, capture: true }
    );
    els.previewBody.addEventListener("drop", (ev) => {
      ev.preventDefault();
    });
    if (wrap) {
      wrap.addEventListener("drop", (ev) => ev.preventDefault());
      wrap.addEventListener("mouseleave", () => {
        if (previewLocateTimer) {
          window.clearTimeout(previewLocateTimer);
          previewLocateTimer = 0;
        }
      });
    }
  }

  function fitPreviewTableViewport() {
    const wrap = els.previewTableWrap;
    if (!wrap) return;
    const dataRows = Array.from(
      (els.previewBody && els.previewBody.querySelectorAll("tr[data-vtg-preview-idx]")) || []
    ).filter((tr) => !tr.classList.contains("vtg-preview-hidden"));
    if (dataRows.length <= PREVIEW_VISIBLE_ROWS) {
      wrap.style.maxHeight = "";
      return;
    }
    const last = dataRows[PREVIEW_VISIBLE_ROWS - 1];
    const thead = wrap.querySelector("thead");
    const theadH = thead ? thead.offsetHeight : 0;
    let rowBottom = last.offsetTop + last.offsetHeight;
    const parentTag = last.offsetParent && String(last.offsetParent.tagName || "").toLowerCase();
    if (parentTag === "tbody") {
      rowBottom += theadH;
    }
    wrap.style.maxHeight = `${Math.max(160, Math.ceil(rowBottom + 8))}px`;
  }

  function taskIdentity(item) {
    const fileName = String((item && (item.taskKey || item.fileName)) || "").trim().toLowerCase();
    const taskType = String((item && item.taskType) || "").trim().toLowerCase();
    const fileVersion = String((item && (item.targetVersion || item.registrationVersion)) || "").trim().toLowerCase();
    return `${fileName}__${taskType}__${fileVersion}`;
  }

  function withScriptRoot(url) {
    const root = String(window.__SCRIPT_ROOT__ || "").replace(/\/+$/, "");
    if (!url || typeof url !== "string" || !url.startsWith("/")) return url;
    if (root && url.startsWith(`${root}/`)) return url;
    return root ? root + url : url;
  }

  async function requestJson(url, options) {
    const resp = await fetch(withScriptRoot(url), {
      credentials: "include",
      ...(options || {}),
    });
    let data = {};
    try {
      data = await resp.json();
    } catch (e) {
      data = {};
    }
    if (!resp.ok) {
      const msg = data.message || `请求失败（${resp.status}）`;
      const err = new Error(msg);
      err.status = resp.status;
      err.payload = data;
      throw err;
    }
    return data;
  }

  function itemForSaveCompare(item) {
    return {
      fileName: String((item && item.fileName) || "").trim(),
      documentNumber: String((item && item.documentNumber) || "").trim(),
      fileVersion: String((item && item.fileVersion) || "").trim(),
      taskType: String((item && item.taskType) || "").trim(),
      targetVersion: String((item && (item.targetVersion || item.registrationVersion)) || "").trim(),
      author: String((item && item.author) || "").trim(),
      dueDate: String((item && item.dueDate) || "").trim(),
      documentDisplayDate: String((item && item.documentDisplayDate) || "").trim(),
      belongingModule: String((item && item.belongingModule) || "").trim(),
      explanation: String((item && item.explanation) || "").trim(),
      notes: String((item && item.notes) || "").trim(),
      recordStatus: recordStatusOf(item),
      isSystemRecord: isSystemRecordOf(item),
      chapter: String((item && (item.chapter || item.processBranchLabel)) || "").trim(),
      archiveFrequency: String((item && item.archiveFrequency) || "").trim(),
      changeKind: (() => {
        const kind = changeKindOf(item);
        return kind === "add" || kind === "delete" ? kind : "";
      })(),
      changeReason: String((item && item.changeReason) || "").trim(),
      sortOrder: Number(item && item.sortOrder) || 0,
      triggeredBy: Array.isArray(item && item.triggeredBy)
        ? item.triggeredBy.map((x) => String(x)).join(",")
        : String((item && item.triggeredBy) || ""),
    };
  }

  function collectChangedPreviewItems(items) {
    const originalMap = new Map();
    originalPreviewItems.forEach((x) => originalMap.set(originKeyOf(x), x));
    const changedItems = [];
    const seen = new Set();
    (items || []).forEach((item) => {
      const origin = findOriginalPreviewItem(item, originalMap);
      if (origin) {
        seen.add(originKeyOf(origin));
      }
      seen.add(originKeyOf(item));
      if (!origin) {
        changedItems.push(item);
        return;
      }
      if (isPreviewDeleted(item) || item.hideInPreview) {
        changedItems.push(item);
        return;
      }
      if (JSON.stringify(itemForSaveCompare(origin)) !== JSON.stringify(itemForSaveCompare(item))) {
        changedItems.push(item);
      }
    });
    const removedOriginKeys = [];
    originalPreviewItems.forEach((x) => {
      const key = originKeyOf(x);
      if (!seen.has(key)) removedOriginKeys.push(key);
    });
    return { changedItems, removedOriginKeys };
  }

  function findOriginalPreviewItem(item, originalMap) {
    const key = originKeyOf(item);
    if (originalMap.has(key)) return originalMap.get(key);
    const ident = taskIdentity(item);
    return (originalPreviewItems || []).find((x) => taskIdentity(x) === ident) || null;
  }

  function collectAdjustments(editedItems) {
    const originalMap = new Map();
    originalPreviewItems.forEach((x) => originalMap.set(originKeyOf(x), x));

    const adjustments = [];
    editedItems.forEach((item) => {
      const origin = findOriginalPreviewItem(item, originalMap);
      const kind = changeKindOf(item);
      const reason = String((item && item.changeReason) || "").trim();
      if (kind === "delete") {
        if (origin && changeKindOf(origin) === "delete" && String(origin.changeReason || "").trim() === reason) {
          return;
        }
        adjustments.push({
          type: "delete",
          originalItem: origin || item,
          adjustedItem: item,
          reason,
          changeSummary: [],
        });
        return;
      }
      if (!origin) {
        adjustments.push({
          type: "add",
          adjustedItem: item,
          reason,
          changeSummary: [],
        });
        return;
      }
      const summary = summarizeItemDiff(origin, item);
      const reasonChanged = String(origin.changeReason || "").trim() !== reason;
      if (!summary.length && !reasonChanged) return;
      adjustments.push({
        type: "update",
        originalItem: origin,
        adjustedItem: item,
        reason,
        changeSummary: summary,
      });
    });
    return adjustments;
  }

  function collectionRowFromAdjustment(adj) {
    const item = (adj && (adj.adjustedItem || adj.originalItem)) || {};
    const kind = adj && adj.type === "replace" ? "update" : (adj && adj.type) || "";
    return {
      pending: true,
      type: kind,
      typeLabel: CHANGE_KIND_LABELS[kind] || kind,
      fileName: String(item.fileName || "").trim() || "未命名",
      targetVersion: String(item.targetVersion || item.registrationVersion || "").trim(),
      reason: String((adj && adj.reason) || item.changeReason || "").trim(),
      changeSummary: Array.isArray(adj && adj.changeSummary)
        ? adj.changeSummary
        : item.changeFields || [],
      createdAt: "",
    };
  }

  function collectionRowFromHistory(row) {
    const kind = row && row.type === "replace" ? "update" : (row && row.type) || "";
    return {
      pending: false,
      type: kind,
      typeLabel: String((row && (row.typeLabel || CHANGE_KIND_LABELS[kind] || kind)) || ""),
      fileName: String((row && row.fileName) || "").trim() || "未命名",
      targetVersion: String((row && row.targetVersion) || "").trim(),
      reason: String((row && row.reason) || "").trim(),
      changeSummary: Array.isArray(row && row.changeSummary) ? row.changeSummary : [],
      createdAt: String((row && row.createdAt) || "").replace("T", " ").slice(0, 19),
    };
  }

  function collectionRowHtml(row) {
    const badge = row.pending
      ? '<span class="badge text-bg-primary me-1">本次</span>'
      : '<span class="badge text-bg-secondary me-1">已采集</span>';
    const reason = String(row.reason || "").trim() || "（原因可后补）";
    const fields = formatChangeSummary(row.changeSummary);
    const extra = fields ? `；${escapeHtml(fields)}` : "";
    const stamp = row.pending ? "未保存" : row.createdAt || "";
    return `<li>${badge}${
      stamp ? `<span class="text-muted">${escapeHtml(stamp)}</span> ` : ""
    }<strong>${escapeHtml(row.typeLabel || "")}</strong> ${escapeHtml(row.fileName)}${
      row.targetVersion ? ` <span class="font-monospace">${escapeHtml(row.targetVersion)}</span>` : ""
    }：${escapeHtml(reason)}${extra}</li>`;
  }

  function renderCollectionPanel() {
    if (!els.changeLog) return;
    const pending = collectAdjustments(previewItems || []).map(collectionRowFromAdjustment);
    const saved = (collectionHistory || []).map(collectionRowFromHistory);
    const rows = pending.concat(saved);
    const total = rows.length;
    if (els.changeLogCount) els.changeLogCount.textContent = `${total} 条`;
    const totalPages = Math.max(1, Math.ceil(total / COLLECTION_PAGE_SIZE) || 1);
    if (collectionPage > totalPages) collectionPage = totalPages;
    if (collectionPage < 1) collectionPage = 1;
    if (!total) {
      const empty = collectionLoadError
        ? collectionLoadError
        : "暂无增删改。对预览表操作或保存后将在此列出。";
      els.changeLog.innerHTML = `<p class="vtg-changelog-empty">${escapeHtml(empty)}</p>`;
      if (els.changeLogPager) {
        els.changeLogPager.classList.add("d-none");
        els.changeLogPager.innerHTML = "";
      }
      return;
    }
    const start = (collectionPage - 1) * COLLECTION_PAGE_SIZE;
    const pageRows = rows.slice(start, start + COLLECTION_PAGE_SIZE);
    els.changeLog.innerHTML = `<ul class="vtg-changelog-list">${pageRows.map(collectionRowHtml).join("")}</ul>`;
    if (els.changeLogPager) {
      els.changeLogPager.classList.remove("d-none");
      if (totalPages <= 1) {
        els.changeLogPager.innerHTML = `<span>共 ${total} 条</span>`;
      } else {
        const prevDisabled = collectionPage <= 1 ? " disabled" : "";
        const nextDisabled = collectionPage >= totalPages ? " disabled" : "";
        els.changeLogPager.innerHTML = `
          <span>共 ${total} 条 · 第 ${collectionPage}/${totalPages} 页</span>
          <button type="button" class="btn btn-outline-secondary btn-sm py-0" data-vtg-collection-page="${
            collectionPage - 1
          }"${prevDisabled}>上一页</button>
          <button type="button" class="btn btn-outline-secondary btn-sm py-0" data-vtg-collection-page="${
            collectionPage + 1
          }"${nextDisabled}>下一页</button>`;
      }
    }
  }

  function renderChangeLog() {
    renderCollectionPanel();
  }

  async function loadFeedbackHistory() {
    collectionLoadError = "";
    const projectId = String(els.projectId && els.projectId.value || "").trim();
    if (!projectId) {
      collectionHistory = [];
      renderCollectionPanel();
      return;
    }
    try {
      const data = await requestJson(
        `/api/document-control/version-tasks/preview/feedbacks?projectId=${encodeURIComponent(
          projectId
        )}&limit=200`
      );
      collectionHistory = Array.isArray(data.items) ? data.items : [];
      collectionPage = 1;
    } catch (e) {
      collectionHistory = [];
      collectionLoadError = e.message || "加载采集记录失败";
    }
    renderCollectionPanel();
  }

  function setVersionDate(version, dateValue) {
    if (!version || !dateValue) return;
    versionDateValues.set(version, dateValue);
    const row = els.versionDatesBody.querySelector(`tr[data-vtg-version="${version}"]`);
    if (row) {
      const input = row.querySelector("input[data-vtg-date]");
      if (input) input.value = dateValue;
    }
  }

  function renderSuggestList(data, targetVersion) {
    const candidates = Array.isArray(data && data.candidates) ? data.candidates : [];
    const perVersion = Array.isArray(data && data.perVersion) ? data.perVersion : [];
    const missing = Array.isArray(data && data.diagnostics && data.diagnostics.versionsMissing)
      ? data.diagnostics.versionsMissing
      : perVersion.filter((x) => !(x.candidates || []).length).map((x) => x.version);

    els.suggestWrap.classList.remove("d-none");
    const summaryBits = [];
    if (perVersion.length) {
      summaryBits.push(`共检索 ${perVersion.length} 个版本`);
    }
    summaryBits.push(`候选 ${candidates.length} 条`);
    if (missing.length) {
      summaryBits.push(`未找到 ${missing.length} 个（${missing.join("、")}）`);
    }
    if (data && data.source) {
      summaryBits.push(`来源 ${data.source}`);
    }
    const summaryHtml = `<div class="small mb-2"><strong>检索汇总：</strong>${escapeHtml(
      summaryBits.join("；")
    )}</div>`;

    let perVersionHtml = "";
    if (perVersion.length) {
      perVersionHtml =
        '<div class="table-responsive mb-2"><table class="table table-sm table-bordered mb-0">' +
        "<thead><tr><th>版本</th><th>结果</th><th>说明</th></tr></thead><tbody>" +
        perVersion
          .map((block) => {
            const ver = String(block.version || "");
            const count = Array.isArray(block.candidates) ? block.candidates.length : 0;
            const status = count
              ? `<span class="text-success">找到 ${count} 条</span>`
              : '<span class="text-muted">无结果</span>';
            const msg = String(block.message || "").trim() || "-";
            return `<tr><td class="font-monospace small">${escapeHtml(
              ver
            )}</td><td class="small">${status}</td><td class="small text-muted">${escapeHtml(
              msg
            )}</td></tr>`;
          })
          .join("") +
        "</tbody></table></div>";
    }

    if (!candidates.length) {
      els.suggestList.innerHTML =
        summaryHtml +
        perVersionHtml +
        '<div class="text-muted">未检索到可采用的候选日期，请手动填写各版本发布时间。</div>';
      return;
    }

    const html = candidates
      .map((row, idx) => {
        const title = String(row.sourceTitle || row.sourceUrl || "");
        const snippet = String(row.snippet || "");
        const version = String(row.version || targetVersion || "");
        const isLlm = String(row.sourceKind || "") === "llm";
        const sourceLink = row.sourceUrl
          ? `<a class="small" href="${row.sourceUrl}" target="_blank" rel="noopener">查看来源</a>`
          : "";
        return `<div class="border rounded p-2 mb-2">
          <div><strong>${escapeHtml(row.date)}</strong>
            <span class="text-muted">(${escapeHtml(row.confidence || "low")})</span>
            ${isLlm ? '<span class="badge text-bg-warning ms-1">AI推断</span>' : ""}
          </div>
          ${version ? `<div class="small">版本：<span class="font-monospace">${escapeHtml(version)}</span></div>` : ""}
          <div class="small text-muted">${escapeHtml(title)}</div>
          <div class="small">${escapeHtml(snippet)}</div>
          <div class="mt-1">
            ${sourceLink}
            <button type="button" class="btn btn-sm btn-outline-primary ${sourceLink ? "ms-2" : ""}" data-vtg-date-idx="${idx}">采用该日期</button>
          </div>
        </div>`;
      })
      .join("");
    els.suggestList.innerHTML = summaryHtml + perVersionHtml + html;
    Array.from(els.suggestList.querySelectorAll("button[data-vtg-date-idx]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-vtg-date-idx"));
        if (Number.isNaN(idx) || !candidates[idx]) return;
        const row = candidates[idx];
        const version = String(row.version || targetVersion || "").trim();
        if (!version) {
          toast("候选结果缺少版本号，请手动填写", "warning");
          return;
        }
        setVersionDate(version, row.date);
      });
    });
  }

  function ensureVersionInputsForSuggest() {
    const from = String(els.fromVersion.value || "").trim();
    const to = String(els.toVersion.value || "").trim();
    if (!from || !to) {
      throw new Error("请先填写开始版本号和最新版本号");
    }
  }

  let suggestInFlight = null;

  async function suggestReleaseDate(targetVersion) {
    if (suggestInFlight) {
      return suggestInFlight;
    }
    ensureVersionInputsForSuggest();
    const payload = buildSuggestPayload(targetVersion);
    if (!payload.productName) {
      toast("请先填写产品名称（检索按产品名精确匹配，并跟随项目注册国家）", "warning");
      return null;
    }
    if (!payload.registrationCountry) {
      toast("未选项目或项目无注册国家：将无法按国家过滤检索，建议先选项目", "warning");
    }
    suggestInFlight = (async () => {
      const data = await requestJson("/api/document-control/version-tasks/release-date-suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const candidates = Array.isArray(data.candidates) ? data.candidates : [];
      const perVersion = Array.isArray(data.perVersion) ? data.perVersion : [];
      const missing = Array.isArray(data.diagnostics && data.diagnostics.versionsMissing)
        ? data.diagnostics.versionsMissing
        : [];
      renderSuggestList(data, targetVersion || null);

      // App Store 高置信结果自动填入日期表（可再手工改）；LLM/网页仅展示候选，避免编造日期污染
      let autoFilled = 0;
      perVersion.forEach((block) => {
        const ver = String(block.version || "").trim();
        const list = Array.isArray(block.candidates) ? block.candidates : [];
        const preferred =
          list.find((c) => String(c.sourceKind || "") === "app_store" && c.date) ||
          (list[0] &&
          String(list[0].sourceKind || "") !== "llm" &&
          String(list[0].confidence || "") === "high"
            ? list[0]
            : null);
        if (!ver || !preferred || !preferred.date) return;
        setVersionDate(ver, String(preferred.date));
        autoFilled += 1;
      });

      const versionCount = perVersion.length || (targetVersion ? 1 : buildVersionChainInputs().length);
      const foundVersions = perVersion.filter((x) => (x.candidates || []).length).length;
      let summaryMsg = data.message || "";
      if (!summaryMsg) {
        if (!candidates.length) {
          summaryMsg = `检索完成：${versionCount} 个版本均未找到发布时间，请手动填写`;
        } else if (missing.length) {
          summaryMsg = `检索完成：${foundVersions}/${versionCount} 个版本有候选；其余请手动填写`;
        } else {
          summaryMsg = `检索完成：找到 ${candidates.length} 条候选，请确认后采用`;
        }
      }
      if (autoFilled) {
        summaryMsg += `；已自动填入 ${autoFilled} 个 App Store 日期（请对照商店页确认）`;
      }
      const region =
        (data.diagnostics && (data.diagnostics.registrationRegion || data.diagnostics.registrationCountry)) ||
        payload.registrationCountry ||
        "";
      const productUsed = (data.diagnostics && data.diagnostics.productName) || payload.productName || "";
      if (region || productUsed) {
        summaryMsg += `（注册：${region || "未指定"}${
          region && payload.registrationCountry && region !== payload.registrationCountry
            ? `←${payload.registrationCountry}`
            : ""
        }；产品：${productUsed || "未指定"}）`;
      } else {
        summaryMsg += "（未选注册国家/产品，结果可能不准）";
      }
      const queriesTried = perVersion.reduce((n, block) => {
        const q = Array.isArray(block.queries) ? block.queries.length : 0;
        return n + q;
      }, 0);
      if (queriesTried > 1 && versionCount <= 1) {
        summaryMsg += `（该版本尝试 ${queriesTried} 条搜索词）`;
      }
      if (
        (data.source === "local_fallback" || data.source === "upstream_unreachable") &&
        data.upstreamWarning &&
        window.__PAGE13_SUPER_ADMIN__
      ) {
        summaryMsg += `；上游：${data.upstreamWarning}`;
      }
      toast(
        summaryMsg,
        !candidates.length || String(data.source || "").includes("llm") ? "warning" : "success"
      );
      return data;
    })();
    try {
      return await suggestInFlight;
    } finally {
      suggestInFlight = null;
    }
  }

  function renderDiagnoseResult(data) {
    if (!els.diagnoseWrap || !els.diagnoseJson) return;
    els.diagnoseWrap.classList.remove("d-none");
    els.diagnoseJson.textContent = JSON.stringify(data, null, 2);
  }

  async function diagnoseReleaseDate(targetVersion) {
    ensureVersionInputsForSuggest();
    const payload = buildSuggestPayload(targetVersion);
    const data = await requestJson("/api/document-control/version-tasks/release-date-suggest/diagnose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderDiagnoseResult(data);
    const summary = data.diagnostics || data.diagnosticsSummary || {};
    const route = data.route || summary.source || "unknown";
    const rawHits = summary.totalRawHits;
    const candidateCount = summary.candidateCount ?? (data.candidates || []).length;
    toast(
      `诊断完成：路由=${route}，原始命中=${rawHits ?? "-"}，候选=${candidateCount ?? 0}`,
      candidateCount ? "success" : "warning"
    );
    return data;
  }

  async function loadProjectRecords() {
    await loadSavedRecords();
  }

  function syncChainVersionsIntoSavedRecords() {
    const projectId = String(els.projectId.value || "").trim();
    if (!projectId) return;
    syncVersionDateValuesFromDom();
    syncSavedRecordsFromDom();
    const chain = buildVersionChainInputs();
    const productName = String(els.productName.value || "").trim();
    const chainFrom = String(els.fromVersion.value || "").trim();
    const chainTo = String(els.toVersion.value || "").trim();
    const byVersion = new Map();
    savedRecords.forEach((row) => {
      const ver = String(row.version || "").trim();
      if (ver) byVersion.set(ver, row);
    });
    chain.forEach((version) => {
      const existing = byVersion.get(version);
      const dateVal = String(versionDateValues.get(version) || "").trim();
      if (existing) {
        if (dateVal) existing.releasedAt = dateVal;
        if (!existing.projectId) existing.projectId = projectId;
        if (productName) {
          existing.productName = productName;
        }
        existing.chainFromVersion = chainFrom;
        existing.chainToVersion = chainTo;
        return;
      }
      const row = {
        id: "",
        projectId,
        version,
        releasedAt: dateVal,
        generationStatus: projectVersionStatus.get(version) || "none",
        productName,
        chainFromVersion: chainFrom,
        chainToVersion: chainTo,
      };
      savedRecords.push(row);
      byVersion.set(version, row);
    });
  }

  async function saveProjectRecords() {
    const projectId = String(els.projectId.value || "").trim();
    if (!projectId) {
      toast("请先选择项目再保存版本记录", "warning");
      return;
    }
    writeLastProjectId(projectId);
    syncChainVersionsIntoSavedRecords();
    if (!savedRecords.length) {
      toast("请先填写版本号，或在下方表格新增版本后再保存", "warning");
      return;
    }
    renderSavedRecordsTable();
    await saveBatchSavedRecords();
  }

  function renderPreviewMeta(data, prefix) {
    if (!els.previewMeta) return;
    const exp = data && data.explanation && typeof data.explanation === "object"
      ? data.explanation
      : null;
    const updatedAt = data && data.updatedAt
      ? String(data.updatedAt).replace("T", " ").slice(0, 19)
      : "";
    const dates = Object.entries((data && data.versionReleaseDates) || {})
      .map(([v, d]) => `<span class="font-monospace">${escapeHtml(v)}</span> ${escapeHtml(String(d))}`)
      .join("、");
    const steps = exp && Array.isArray(exp.steps) ? exp.steps : [];
    const versions = exp && Array.isArray(exp.versions) ? exp.versions : [];
    const versionHtml = versions.length
      ? versions
          .map((row) => {
            const chs = Array.isArray(row.applicableChapters)
              ? row.applicableChapters.join("、")
              : "";
            const market = row.archiveMarketLabel
              ? ` · ${row.archiveMarketLabel}`
              : "";
            return `<li><span class="font-monospace">${escapeHtml(
              row.fromVersion || ""
            )}</span> → <span class="font-monospace">${escapeHtml(
              row.version || ""
            )}</span>
              主导 <strong>${escapeHtml(row.dominantChange || "")}</strong> 位${escapeHtml(market)}<br>
              <span class="text-muted">适用章节：${escapeHtml(chs || "—")}；主章节 ${escapeHtml(
              row.primaryChapter || "-"
            )}；生成 ${Number(row.itemCount || 0)} 条</span></li>`;
          })
          .join("")
      : "";
    const stepHtml = steps.length
      ? `<ol class="mb-2 ps-3">${steps
          .map((s) => `<li>${escapeHtml(s)}</li>`)
          .join("")}</ol>`
      : "";
    els.previewMeta.innerHTML = `
      <details class="vtg-explain vtg-explain-details"${previewRulesOpen ? " open" : ""}>
        <summary class="vtg-explain-summary">
          <span>规则说明</span>
          <span class="vtg-explain-summary-hint">${escapeHtml(prefix || "预览")}${
            updatedAt ? ` · 保存 ${escapeHtml(updatedAt)}` : ""
          } · ${escapeHtml((data && (data.ruleSource || data.ruleBasis)) || "-")}${
            data && data.sourceVersion ? ` ${escapeHtml(String(data.sourceVersion))}` : ""
          } · 点此展开</span>
        </summary>
        <div class="vtg-explain-body">
        <div class="vtg-explain-grid">
          <div><span>依据</span>${escapeHtml((data && (data.ruleSource || data.ruleBasis)) || "-")}</div>
          ${
            data && data.sourceVersion
              ? `<div><span>制度版次</span>${escapeHtml(String(data.sourceVersion))}${
                  data.sourceFile ? ` · ${escapeHtml(String(data.sourceFile))}` : ""
                }</div>`
              : ""
          }
          <div><span>版本链路</span>${escapeHtml(((data && data.versionChain) || []).join(" → ") || "-")}</div>
          <div><span>发布时间</span>${dates || "-"}</div>
          <div><span>触发位</span>${escapeHtml(((data && data.dominantChanges) || []).join("、") || "无")}</div>
          <div><span>反馈命中</span>${escapeHtml(String((data && data.feedbackHitCount) || 0))}</div>
        </div>
        ${stepHtml ? `<div class="vtg-explain-sub">匹配步骤</div>${stepHtml}` : ""}
        ${versionHtml ? `<div class="vtg-explain-sub">各版本命中</div><ul class="mb-2 ps-3">${versionHtml}</ul>` : ""}
        ${
          exp && exp.chainNote
            ? `<p class="mb-1">${escapeHtml(exp.chainNote)}</p>`
            : ""
        }
        ${
          exp && exp.supplementHint
            ? `<p class="mb-0 text-muted">${escapeHtml(exp.supplementHint)}</p>`
            : ""
        }
        </div>
      </details>`;
    const details = els.previewMeta.querySelector("details.vtg-explain-details");
    if (details) {
      details.addEventListener("toggle", () => {
        previewRulesOpen = details.open;
      });
    }
  }

  function buildPreviewMetaText(data, prefix) {
    renderPreviewMeta(data, prefix);
    return "";
  }

  function adoptPreviewBaselines(items, ruleItems, deletedKeys) {
    originalPreviewItems = hydrateDeletedMarkers(
      Array.isArray(items) ? JSON.parse(JSON.stringify(items)) : [],
      deletedKeys
    );
    originalPreviewItems.forEach((item) => {
      normalizePreviewDocFields(item);
      ensureOriginKey(item);
    });
    const sourceRules =
      Array.isArray(ruleItems) && ruleItems.length
        ? ruleItems
        : originalPreviewItems.filter((item) => changeKindOf(item) !== "add" && changeKindOf(item) !== "delete");
    rulePreviewItems = sourceRules.map((item) => {
      const copy = { ...item, changeKind: "", changeReason: "", changeFields: [], hideInPreview: false };
      delete copy.hideInPreview;
      normalizePreviewDocFields(copy);
      ensureOriginKey(copy);
      return copy;
    });
  }

  function applyPreviewPayload(data, options) {
    const opts = options || {};
    currentJobId = data.jobId || "";
    const rows = combinePreviewPayloadItems(data, []);
    adoptPreviewBaselines(rows, data.ruleItems, data.manualDeletedKeys);
    resetPreviewVersionUi();
    if (opts.fillForm !== false) {
      if (data.fromVersion && els.fromVersion) els.fromVersion.value = data.fromVersion;
      if (data.toVersion && els.toVersion) els.toVersion.value = data.toVersion;
      const chain = Array.isArray(data.versionChain) ? data.versionChain : [];
      if (els.intermediate) {
        if (chain.length > 2) {
          els.intermediate.value = chain.slice(1, -1).join(", ");
        } else if (chain.length <= 2 && opts.clearIntermediate) {
          els.intermediate.value = "";
        }
      }
      applyVersionReleaseDatesFromPreview(data.versionReleaseDates || {});
      renderVersionDatesTable();
    } else {
      applyVersionReleaseDatesFromPreview(data.versionReleaseDates || {});
    }
    try {
      renderPreviewTable(originalPreviewItems, {
        restoreSelection: true,
        selectionScope: {
          projectId: data.projectId || selectedProjectId(),
          fromVersion: data.fromVersion || inputValue(els.fromVersion),
          toVersion: data.toVersion || inputValue(els.toVersion),
        },
      });
    } catch (err) {
      if (els.previewBody) {
        els.previewBody.innerHTML = `<tr><td colspan="${PREVIEW_COLSPAN}" class="text-danger small text-center py-3">清单渲染失败：${escapeHtml(
          err.message || "未知错误"
        )}</td></tr>`;
      }
      toast(err.message || "渲染清单失败", "danger");
    }
    if (Array.isArray(data.savedRecords) && data.savedRecords.length) {
      applyProjectRecords(data.savedRecords);
    }
    if (opts.fillForm !== false && data.productName && els.productName) {
      els.productName.value = data.productName;
      writeLocalProductName(String(data.projectId || selectedProjectId()).trim(), data.productName);
    }
    renderPreviewMeta(data, opts.metaPrefix || "预览");
    setPreviewSaveEnabled();
  }

  function clearPreviewPanel(message) {
    currentJobId = "";
    originalPreviewItems = [];
    rulePreviewItems = [];
    previewSelectedKeys.clear();
    previewSelectionPersistMuted = true;
    try {
      renderPreviewTable([], { skipPersist: true });
    } finally {
      previewSelectionPersistMuted = false;
    }
    if (els.previewMeta) {
      els.previewMeta.textContent = message || "尚未生成预览。";
    }
    if (els.previewSaveBanner) els.previewSaveBanner.innerHTML = "";
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.disabled = true;
    }
    if (els.syncDocMetaBtn) {
      els.syncDocMetaBtn.disabled = true;
    }
    if (els.addPreviewRowBtn) {
      els.addPreviewRowBtn.disabled = true;
    }
    if (els.movePreviewBtn) {
      els.movePreviewBtn.disabled = true;
    }
    if (els.copyPreviewBtn) {
      els.copyPreviewBtn.disabled = true;
    }
    if (els.batchDueDateBtn) {
      els.batchDueDateBtn.disabled = true;
    }
    if (els.deleteVersionBtn) {
      els.deleteVersionBtn.disabled = true;
    }
    hideAddPreviewPanel();
    hideMovePreviewPanel();
    hideCopyPreviewPanel();
    hideBatchDueDatePanel();
    hideDeleteVersionPanel();
  }

  function setPreviewSaveEnabled() {
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.disabled = !currentJobId;
    }
    if (els.syncDocMetaBtn) {
      els.syncDocMetaBtn.disabled = !visiblePreviewItems().length;
    }
    if (els.addPreviewRowBtn) {
      els.addPreviewRowBtn.disabled = !currentJobId;
    }
    if (els.movePreviewBtn) {
      els.movePreviewBtn.disabled = !currentJobId;
    }
    if (els.copyPreviewBtn) {
      els.copyPreviewBtn.disabled = !currentJobId || !visiblePreviewItems().length;
    }
    if (els.batchDueDateBtn) {
      els.batchDueDateBtn.disabled = !currentJobId || !visiblePreviewItems().length;
    }
    if (els.deleteVersionBtn) {
      els.deleteVersionBtn.disabled = !currentJobId || !visiblePreviewItems().length;
    }
  }

  function newManualTaskKey() {
    const rand = Math.random().toString(36).slice(2, 10);
    return `manual:${Date.now().toString(36)}:${rand}`;
  }

  function previewRecordLabel(item) {
    const name = String((item && item.fileName) || "").trim() || "（未命名）";
    const deleted = isPreviewDeleted(item) ? " · 已删除" : "";
    return `${previewVersionKey(item)} · ${previewChapterKey(item)} · #${
      Number((item && item.sortOrder) || 0) + 1
    } ${name}${deleted}`;
  }

  function hideAddPreviewPanel() {
    if (els.addPreviewPanel) els.addPreviewPanel.classList.add("d-none");
  }

  function hideMovePreviewPanel() {
    if (els.movePreviewPanel) els.movePreviewPanel.classList.add("d-none");
  }

  function hideCopyPreviewPanel() {
    if (els.copyPreviewPanel) els.copyPreviewPanel.classList.add("d-none");
  }

  function hideDeleteVersionPanel() {
    if (els.deleteVersionPanel) els.deleteVersionPanel.classList.add("d-none");
  }

  function hideBatchDueDatePanel() {
    if (els.batchDueDatePanel) els.batchDueDatePanel.classList.add("d-none");
  }

  function hidePreviewOpPanels() {
    hideAddPreviewPanel();
    hideMovePreviewPanel();
    hideCopyPreviewPanel();
    hideBatchDueDatePanel();
    hideDeleteVersionPanel();
  }

  function listPreviewVersionChoices() {
    const seen = new Set();
    const out = [];
    const add = (raw) => {
      const key = String(raw || "").trim() || "未指定版本";
      if (seen.has(key)) return;
      seen.add(key);
      out.push(key);
    };
    buildVersionChainInputs().forEach(add);
    previewItems.forEach((item) => add(previewVersionKey(item)));
    return out.sort(comparePreviewVersions);
  }

  function destVersionDateHints(ver) {
    const key = String(ver || "").trim() || "未指定版本";
    const live = previewItems.find(
      (item) => previewVersionKey(item) === key && !isPreviewDeleted(item)
    );
    const chainDate = key === "未指定版本" ? "" : String(versionDateValues.get(key) || "").trim();
    return {
      dueDate: (live && live.dueDate) || "",
      documentDisplayDate: (live && live.documentDisplayDate) || chainDate,
    };
  }

  function clonePreviewItemToVersion(item, destVer, hints) {
    const destValue = destVer === "未指定版本" ? "" : String(destVer || "").trim();
    const copy = { ...item };
    copy.taskKey = newManualTaskKey();
    copy.originKey = copy.taskKey;
    copy.targetVersion = destValue;
    copy.registrationVersion = destValue;
    copy.sortOrder = 0;
    copy.changeKind = "add";
    copy.changeReason = "";
    copy.changeFields = [];
    delete copy.hideInPreview;
    copy.triggeredBy = Array.isArray(item.triggeredBy) ? item.triggeredBy.slice() : [];
    if (hints && hints.dueDate) copy.dueDate = hints.dueDate;
    if (hints && hints.documentDisplayDate) copy.documentDisplayDate = hints.documentDisplayDate;
    return copy;
  }

  function livePreviewItemsForVersion(ver) {
    const key = String(ver || "").trim() || "未指定版本";
    return previewItems.filter(
      (item) => previewVersionKey(item) === key && !isPreviewDeleted(item)
    );
  }

  function selectedLiveItemsForVersion(ver) {
    const key = String(ver || "").trim() || "未指定版本";
    return livePreviewItemsForVersion(key).filter((item) =>
      previewSelectedKeys.has(taskIdentity(item))
    );
  }

  function fillVersionSelect(selectEl, versions, selected, options) {
    if (!selectEl) return;
    const opts = options || {};
    const exclude = new Set(opts.exclude || []);
    const list = (versions || []).filter((ver) => !exclude.has(ver));
    const keep = selected && list.includes(selected) ? selected : list[0] || "";
    selectEl.innerHTML = list.length
      ? list
          .map(
            (ver) =>
              `<option value="${escapeHtml(ver)}"${ver === keep ? " selected" : ""}>${escapeHtml(
                ver
              )}</option>`
          )
          .join("")
      : `<option value="">暂无版本</option>`;
    if (keep) selectEl.value = keep;
  }

  function fillCopyVersionOptions(options) {
    const keep = Boolean(options && options.keepSelection);
    const versions = listPreviewVersionChoices();
    const prevFrom = keep ? String((els.copyFromVersion && els.copyFromVersion.value) || "") : "";
    const prevTo = keep ? String((els.copyToVersion && els.copyToVersion.value) || "") : "";
    const preferredFrom =
      String((options && options.sourceVer) || "").trim() ||
      prevFrom ||
      previewVersionFilter ||
      (locatePreviewItem() ? previewVersionKey(locatePreviewItem()) : "") ||
      versions[0] ||
      "";
    fillVersionSelect(els.copyFromVersion, versions, preferredFrom);
    const sourceVer = String((els.copyFromVersion && els.copyFromVersion.value) || "");
    const destChoices = versions.filter((ver) => ver !== sourceVer);
    const preferredTo =
      destChoices.includes(prevTo) && prevTo !== sourceVer ? prevTo : destChoices[0] || "";
    fillVersionSelect(els.copyToVersion, destChoices, preferredTo);
    if (els.copySelectedOnly && !keep) {
      const sourceHasSel = selectedLiveItemsForVersion(sourceVer).length > 0;
      els.copySelectedOnly.checked = sourceHasSel;
    }
    updateCopyPreviewHint();
  }

  function updateCopyPreviewHint() {
    if (!els.copyPreviewHint) return;
    const sourceVer = String((els.copyFromVersion && els.copyFromVersion.value) || "").trim();
    const destVer = String((els.copyToVersion && els.copyToVersion.value) || "").trim();
    if (!sourceVer || !destVer) {
      els.copyPreviewHint.textContent = "请选择源版本和另一个目标版本。";
      return;
    }
    if (sourceVer === destVer) {
      els.copyPreviewHint.textContent = "源版本和目标版本不能相同。";
      return;
    }
    const selectedOnly = Boolean(els.copySelectedOnly && els.copySelectedOnly.checked);
    const live = livePreviewItemsForVersion(sourceVer);
    const picked = selectedLiveItemsForVersion(sourceVer);
    const usingSelected = selectedOnly && picked.length;
    if (selectedOnly && !picked.length) {
      els.copyPreviewHint.textContent = `已勾选「仅复制已勾选记录」，但「${sourceVer}」下没有勾选。请勾选或取消该选项。`;
      return;
    }
    const count = usingSelected ? picked.length : live.length;
    if (!live.length) {
      els.copyPreviewHint.textContent = `版本 ${sourceVer} 没有可复制的未删除记录。`;
      return;
    }
    els.copyPreviewHint.textContent = usingSelected
      ? `将把「${sourceVer}」已勾选的 ${count} 条复制到「${destVer}」，原版本保留。`
      : `将把「${sourceVer}」全部 ${count} 条未删除记录复制到「${destVer}」，原版本保留。`;
  }

  function copyPreviewItemsToVersion(items, destVer) {
    const destKey = String(destVer || "").trim() || "未指定版本";
    const incoming = (items || []).filter((item) => previewVersionKey(item) !== destKey);
    if (!incoming.length) {
      toast("没有可复制到该版本的记录（可能已在目标版本）", "info");
      return [];
    }
    const destNames = new Set(
      livePreviewItemsForVersion(destKey)
        .map((item) => previewFileNameKey(item.fileName))
        .filter(Boolean)
    );
    const conflicts = [];
    incoming.forEach((item) => {
      const name = previewFileNameKey(item.fileName);
      if (name && destNames.has(name)) conflicts.push(String(item.fileName || "").trim());
      if (name) destNames.add(name);
    });
    if (conflicts.length) {
      toast(
        `无法复制到版本 ${destKey}：已存在「${conflicts.slice(0, 5).join("」「")}」${
          conflicts.length > 5 ? " 等" : ""
        }`,
        "warning"
      );
      return [];
    }
    const hints = destVersionDateHints(destKey);
    const copies = incoming.map((item) => clonePreviewItemToVersion(item, destKey, hints));
    const destLive = livePreviewItemsForVersion(destKey).slice().sort(
      (a, b) => Number(a.sortOrder) - Number(b.sortOrder)
    );
    let anchor = destLive.length ? destLive[destLive.length - 1] : null;
    copies.forEach((copy) => {
      insertPreviewItemRelative(copy, anchor, "after");
      previewSelectedKeys.add(taskIdentity(copy));
      anchor = copy;
    });
    return copies;
  }

  function confirmCopyPreviewRows() {
    if (!currentJobId) {
      toast("请先生成预览后再复制", "warning");
      return;
    }
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    const sourceVer = String((els.copyFromVersion && els.copyFromVersion.value) || "").trim();
    const destVer = String((els.copyToVersion && els.copyToVersion.value) || "").trim();
    if (!sourceVer || !destVer) {
      toast("请选择源版本和目标版本", "warning");
      return;
    }
    if (sourceVer === destVer) {
      toast("请复制到另一个目标版本", "warning");
      return;
    }
    const selectedOnly = Boolean(els.copySelectedOnly && els.copySelectedOnly.checked);
    let sourceItems;
    if (selectedOnly) {
      sourceItems = selectedLiveItemsForVersion(sourceVer);
      if (!sourceItems.length) {
        toast("当前源版本没有已勾选记录，请勾选或取消「仅复制已勾选记录」", "warning");
        return;
      }
    } else {
      sourceItems = livePreviewItemsForVersion(sourceVer);
    }
    if (!sourceItems.length) {
      toast(`版本 ${sourceVer} 没有可复制的未删除记录`, "warning");
      return;
    }
    const copies = copyPreviewItemsToVersion(sourceItems, destVer);
    if (!copies.length) return;
    hideCopyPreviewPanel();
    previewVersionFilter = destVer;
    previewCollapsedVersions.delete(destVer);
    if (copies[0]) setPreviewLocateByItem(copies[0]);
    renderPreviewTable(previewItems);
    toast(
      `已将 ${copies.length} 条从「${sourceVer}」复制到「${destVer}」，请点「保存预览修改」`,
      "info"
    );
  }

  function openCopyPreviewPanel(sourceVer) {
    if (!currentJobId) {
      toast("请先生成预览后再复制", "warning");
      return;
    }
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    flushPreviewLocate();
    hidePreviewOpPanels();
    const preferred = String(sourceVer || "").trim();
    fillCopyVersionOptions({ sourceVer: preferred });
    if (preferred && els.copySelectedOnly) {
      els.copySelectedOnly.checked = false;
      updateCopyPreviewHint();
    }
    if (els.copyPreviewPanel) {
      els.copyPreviewPanel.classList.remove("d-none");
      try {
        els.copyPreviewPanel.scrollIntoView({ block: "nearest" });
      } catch (err) {
        els.copyPreviewPanel.scrollIntoView();
      }
    }
  }

  function fillDeleteVersionOptions(options) {
    const keep = Boolean(options && options.keepSelection);
    const versions = listPreviewVersionChoices().filter(
      (ver) => livePreviewItemsForVersion(ver).length || previewItems.some((item) => previewVersionKey(item) === ver)
    );
    const prev = keep ? String((els.deleteVersionSelect && els.deleteVersionSelect.value) || "") : "";
    const preferred =
      String((options && options.version) || "").trim() ||
      prev ||
      previewVersionFilter ||
      versions[0] ||
      "";
    fillVersionSelect(els.deleteVersionSelect, versions, preferred);
    updateDeleteVersionHint();
  }

  function updateDeleteVersionHint() {
    if (!els.deleteVersionHint) return;
    const ver = String((els.deleteVersionSelect && els.deleteVersionSelect.value) || "").trim();
    if (!ver) {
      els.deleteVersionHint.textContent = "请选择要清空的目标版本。";
      return;
    }
    const live = livePreviewItemsForVersion(ver);
    const already = previewItems.filter(
      (item) => previewVersionKey(item) === ver && isPreviewDeleted(item)
    ).length;
    if (!live.length) {
      els.deleteVersionHint.textContent = already
        ? `版本 ${ver} 的记录都已标记删除。`
        : `版本 ${ver} 没有可删除的记录。`;
      return;
    }
    els.deleteVersionHint.textContent = `将标记删除「${ver}」的 ${live.length} 条未删除记录${
      already ? `（另有 ${already} 条已删除）` : ""
    }。`;
  }

  function markPreviewItemDeleted(item) {
    const inRules = Boolean(ruleItemOf(item));
    const savedAlready = originalPreviewItems.some(
      (x) => originKeyOf(x) === originKeyOf(item)
    );
    previewSelectedKeys.delete(taskIdentity(item));
    if (!inRules && !savedAlready) return "remove";
    item.changeKind = "delete";
    item.hideInPreview = true;
    return "mark";
  }

  function deletePreviewItemsByVersion(ver) {
    const key = String(ver || "").trim() || "未指定版本";
    const targets = livePreviewItemsForVersion(key);
    if (!targets.length) {
      toast(`版本 ${key} 没有可删除的记录`, "info");
      return 0;
    }
    if (
      !window.confirm(
        `确定删除版本 ${key} 的 ${targets.length} 条记录？它们将从列表中隐藏，尚未保存的新增会直接移除。`
      )
    ) {
      return 0;
    }
    const removeKeys = new Set();
    let marked = 0;
    targets.forEach((item) => {
      const mode = markPreviewItemDeleted(item);
      if (mode === "remove") removeKeys.add(originKeyOf(item));
      else {
        item.hideInPreview = true;
        marked += 1;
      }
    });
    if (removeKeys.size) {
      previewItems = previewItems.filter((item) => !removeKeys.has(originKeyOf(item)));
    }
    return marked + removeKeys.size;
  }

  function confirmDeletePreviewVersion() {
    if (!currentJobId) {
      toast("请先生成预览后再删除", "warning");
      return;
    }
    syncPreviewItemsFromDom();
    const ver = String((els.deleteVersionSelect && els.deleteVersionSelect.value) || "").trim();
    if (!ver) {
      toast("请选择要删除的目标版本", "warning");
      return;
    }
    const count = deletePreviewItemsByVersion(ver);
    if (!count) return;
    hideDeleteVersionPanel();
    renderPreviewTable(previewItems);
    toast(`已删除版本 ${ver} 的 ${count} 条记录，已从列表隐藏`, "info");
    persistPreviewEdits({ quietSuccess: true }).catch((e) =>
      toast(e.message || "删除已生效，但保存失败，请点「保存预览修改」", "warning")
    );
  }

  function openDeleteVersionPanel(version) {
    if (!currentJobId) {
      toast("请先生成预览后再删除", "warning");
      return;
    }
    syncPreviewItemsFromDom();
    hidePreviewOpPanels();
    fillDeleteVersionOptions({ version: String(version || "").trim() });
    if (els.deleteVersionPanel) {
      els.deleteVersionPanel.classList.remove("d-none");
      try {
        els.deleteVersionPanel.scrollIntoView({ block: "nearest" });
      } catch (err) {
        els.deleteVersionPanel.scrollIntoView();
      }
    }
  }

  function fillAddPreviewAnchorOptions() {
    if (!els.addAnchorSelect) return;
    const live = visiblePreviewItems();
    const filtered = live.filter((item) => {
      if (previewVersionFilter && previewVersionKey(item) !== previewVersionFilter) return false;
      return itemMatchesColFilters(item);
    });
    const source = filtered.length ? filtered : live;
    els.addAnchorSelect.innerHTML = source
      .map((item) => {
        const idx = previewItems.indexOf(item);
        return `<option value="${idx}">${escapeHtml(previewRecordLabel(item))}</option>`;
      })
      .join("");
    if (source.length) {
      const locateIdx = preferredAnchorIdxFromList(source);
      els.addAnchorSelect.value = String(
        locateIdx >= 0 ? locateIdx : previewItems.indexOf(source[source.length - 1])
      );
      const opt = els.addAnchorSelect.selectedOptions && els.addAnchorSelect.selectedOptions[0];
      if (opt && typeof opt.scrollIntoView === "function") {
        try {
          opt.scrollIntoView({ block: "nearest" });
        } catch (err) {
          opt.scrollIntoView();
        }
      }
    }
    updatePreviewLocateHint();
  }

  function openAddPreviewPanel() {
    if (!currentJobId) {
      toast("请先生成预览后再添加记录", "warning");
      return;
    }
    syncPreviewItemsFromDom();
    flushPreviewLocate();
    if (!visiblePreviewItems().length) {
      addPreviewRow(null, "after");
      return;
    }
    const locate = locatePreviewItem();
    if (locate) {
      hidePreviewOpPanels();
      addPreviewRow(locate, "after");
      return;
    }
    hidePreviewOpPanels();
    fillAddPreviewAnchorOptions();
    if (els.addPlaceSelect) els.addPlaceSelect.value = "after";
    if (els.addPreviewPanel) {
      els.addPreviewPanel.classList.remove("d-none");
      try {
        els.addPreviewPanel.scrollIntoView({ block: "nearest" });
      } catch (err) {
        els.addPreviewPanel.scrollIntoView();
      }
    }
    if (els.addPreviewConfirmBtn) els.addPreviewConfirmBtn.focus();
  }

  function buildBlankPreviewItem(anchor) {
    const filtered = String(previewVersionFilter || "").trim();
    const fallback = String((els.toVersion && els.toVersion.value) || "").trim();
    let version = "";
    let chapter = "";
    if (anchor) {
      const verKey = previewVersionKey(anchor);
      version = verKey === "未指定版本" ? "" : verKey;
      chapter = previewChapterKey(anchor);
      if (chapter === "其它") chapter = String(anchor.chapter || "").trim();
    } else {
      version = filtered && filtered !== "未指定版本" ? filtered : fallback;
    }
    const item = {
      taskKey: newManualTaskKey(),
      originKey: "",
      fileName: "",
      taskType: DEFAULT_VERSION_TASK_TYPE,
      targetVersion: version,
      fileVersion: "",
      documentNumber: "",
      registrationVersion: version,
      author: "",
      dueDate: (anchor && anchor.dueDate) || "",
      documentDisplayDate: (anchor && anchor.documentDisplayDate) || "",
      belongingModule: "",
      explanation: "",
      notes: "",
      recordStatus: "adopt",
      isSystemRecord: false,
      archiveFrequency: "",
      triggeredBy: [],
      chapter,
      processBranchLabel: chapter,
      changeKind: "add",
      changeReason: "",
      changeFields: [],
    };
    item.originKey = originKeyOf(item);
    return item;
  }

  function insertPreviewItemRelative(item, anchor, place) {
    ensureSortOrders(previewItems);
    if (!anchor) {
      const verKey = previewVersionKey(item);
      const maxOrder = previewItems
        .filter((row) => previewVersionKey(row) === verKey)
        .reduce((max, row) => Math.max(max, Number(row.sortOrder)), -1);
      item.sortOrder = maxOrder + 1;
      previewItems.push(item);
      ensureSortOrders(previewItems);
      return;
    }
    const ver = previewVersionKey(item);
    const group = [];
    const rest = [];
    previewItems.forEach((row) => {
      if (previewVersionKey(row) === ver) group.push(row);
      else rest.push(row);
    });
    group.sort((a, b) => Number(a.sortOrder) - Number(b.sortOrder));
    let at = group.findIndex((row) => originKeyOf(row) === originKeyOf(anchor));
    if (at < 0) at = group.length;
    else if (place !== "before") at += 1;
    group.splice(at, 0, item);
    group.forEach((row, i) => {
      row.sortOrder = i;
    });
    previewItems = rest.concat(group);
    ensureSortOrders(previewItems);
  }

  function listSelectedItemsForMove() {
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    return visiblePreviewRows()
      .map((tr) => previewItems[Number(tr.getAttribute("data-vtg-preview-idx"))])
      .filter((item) => item && canCheckPreview(item) && previewSelectedKeys.has(taskIdentity(item)));
  }

  function sharedSelectedDueDate(items) {
    const dates = (items || [])
      .map((item) => String((item && item.dueDate) || "").trim())
      .filter(Boolean);
    if (!dates.length) return "";
    const first = dates[0];
    return dates.every((d) => d === first) ? first : "";
  }

  function updateBatchDueDateHint() {
    if (!els.batchDueDateHint) return;
    const selected = listSelectedItemsForMove();
    if (!selected.length) {
      els.batchDueDateHint.textContent = "请先勾选要设置完成日期的记录。";
      return;
    }
    const current = sharedSelectedDueDate(selected);
    els.batchDueDateHint.textContent = current
      ? `将把已勾选的 ${selected.length} 条完成日期设为同一天（当前同为 ${current}）。`
      : `将把已勾选的 ${selected.length} 条完成日期设为同一天。`;
  }

  function openBatchDueDatePanel() {
    if (!currentJobId) {
      toast("请先生成预览后再设置完成日期", "warning");
      return;
    }
    const selected = listSelectedItemsForMove();
    if (!selected.length) {
      toast("请先勾选要设置完成日期的记录", "warning");
      return;
    }
    hidePreviewOpPanels();
    if (els.batchDueDateInput) els.batchDueDateInput.value = sharedSelectedDueDate(selected);
    updateBatchDueDateHint();
    if (els.batchDueDatePanel) {
      els.batchDueDatePanel.classList.remove("d-none");
      try {
        els.batchDueDatePanel.scrollIntoView({ block: "nearest" });
      } catch (err) {
        els.batchDueDatePanel.scrollIntoView();
      }
    }
    if (els.batchDueDateInput) els.batchDueDateInput.focus();
  }

  function confirmBatchDueDate() {
    if (!currentJobId) {
      toast("请先生成预览后再设置完成日期", "warning");
      return;
    }
    const selected = listSelectedItemsForMove();
    if (!selected.length) {
      toast("请先勾选要设置完成日期的记录", "warning");
      return;
    }
    const next = String((els.batchDueDateInput && els.batchDueDateInput.value) || "").trim();
    if (next && !/^\d{4}-\d{2}-\d{2}$/.test(next)) {
      toast("完成日期格式无效", "warning");
      return;
    }
    if (!next && !window.confirm(`确定清空已勾选 ${selected.length} 条的完成日期？`)) {
      return;
    }
    let changed = 0;
    selected.forEach((item) => {
      const prev = String((item && item.dueDate) || "").trim();
      if (prev === next) return;
      item.dueDate = next;
      refreshItemChangeMark(item);
      changed += 1;
    });
    hideBatchDueDatePanel();
    renderPreviewTable(previewItems);
    if (!changed) {
      toast("勾选记录的完成日期已是该值，无需修改", "info");
      return;
    }
    toast(
      next
        ? `已将 ${changed} 条完成日期设为 ${next}`
        : `已清空 ${changed} 条完成日期`,
      "info"
    );
    persistPreviewEdits({ quietSuccess: true }).catch((e) =>
      toast(e.message || "完成日期已写入表格，但保存失败，请点「保存预览修改」", "warning")
    );
  }

  function applyCategoryFromAnchor(item, anchor) {
    if (!item || !anchor) return;
    const prevVer = previewVersionKey(item);
    const ver = previewVersionKey(anchor);
    const chapter = previewChapterKey(anchor);
    if (ver && ver !== "未指定版本") {
      item.targetVersion = ver;
      item.registrationVersion = ver;
    } else if (ver === "未指定版本") {
      item.targetVersion = "";
      item.registrationVersion = "";
    }
    if (chapter) {
      item.chapter = chapter === "其它" ? String(anchor.chapter || "").trim() || chapter : chapter;
      item.processBranchLabel = item.chapter;
    }
    if (ver !== prevVer) {
      if (anchor.dueDate) item.dueDate = anchor.dueDate;
      if (anchor.documentDisplayDate) item.documentDisplayDate = anchor.documentDisplayDate;
    }
    refreshItemChangeMark(item);
  }

  function movePreviewItemsRelative(moving, anchor, place) {
    if (!moving.length || !anchor) return false;
    const movingKeys = new Set(moving.map((item) => originKeyOf(item)));
    if (movingKeys.has(originKeyOf(anchor))) return false;
    const destVer = previewVersionKey(anchor);
    const nameConflict = findMoveFilenameConflict(moving, destVer, previewItems);
    if (nameConflict) {
      toast(
        nameConflict.crossVersion
          ? `无法移动到版本 ${nameConflict.version}：「${nameConflict.fileName}」在该版本已存在。同版本内调序请只勾选该版本的记录。`
          : `同一版本下文件名不能重复：版本 ${nameConflict.version} 已有「${nameConflict.fileName}」`,
        "warning"
      );
      return false;
    }
    moving.forEach((item) => applyCategoryFromAnchor(item, anchor));
    ensureSortOrders(previewItems);
    const rest = previewItems.filter((item) => !movingKeys.has(originKeyOf(item)));
    const destGroup = rest.filter((item) => previewVersionKey(item) === destVer);
    const other = rest.filter((item) => previewVersionKey(item) !== destVer);
    destGroup.sort((a, b) => Number(a.sortOrder) - Number(b.sortOrder));
    let at = destGroup.findIndex((row) => originKeyOf(row) === originKeyOf(anchor));
    if (at < 0) at = destGroup.length;
    else if (place !== "before") at += 1;
    destGroup.splice(at, 0, ...moving);
    destGroup.forEach((row, i) => {
      row.sortOrder = i;
    });
    previewItems = other.concat(destGroup);
    ensureSortOrders(previewItems);
    return true;
  }

  function updateMovePreviewHint() {
    if (!els.movePreviewHint) return;
    const moving = listSelectedItemsForMove();
    if (!moving.length) {
      els.movePreviewHint.textContent = "请先勾选要移动的记录。";
      return;
    }
    const idx = Number(els.moveAnchorSelect && els.moveAnchorSelect.value);
    const anchor = Number.isFinite(idx) ? previewItems[idx] : null;
    if (!anchor) {
      els.movePreviewHint.textContent = `已勾选 ${moving.length} 条，请选择参照文件。`;
      return;
    }
    const planned = movingItemsForAnchor(moving, anchor);
    if (planned.ignoredOther) {
      els.movePreviewHint.textContent = `将调整「${planned.destVer}」内已勾选的 ${planned.toMove.length} 条顺序（另外 ${planned.ignoredOther} 条属于其它版本，本次不改版本、不移动）。`;
      return;
    }
    const cross = planned.toMove.filter((item) => previewVersionKey(item) !== planned.destVer);
    els.movePreviewHint.textContent = cross.length
      ? `将把已勾选的 ${planned.toMove.length} 条移到版本 ${planned.destVer}，并保持它们当前相对顺序。`
      : `将调整已勾选的 ${planned.toMove.length} 条在「${planned.destVer}」内的顺序。`;
  }

  function fillMoveAnchorOptions(options) {
    if (!els.moveAnchorSelect) return;
    const keepSelection = Boolean(options && options.keepSelection);
    const moving = listSelectedItemsForMove();
    const movingKeys = new Set(moving.map((item) => originKeyOf(item)));
    const q = String((els.moveAnchorFilter && els.moveAnchorFilter.value) || "")
      .trim()
      .toLowerCase();
    const prev = String((els.moveAnchorSelect && els.moveAnchorSelect.value) || "");
    const source = previewItems.filter((item) => {
      if (isHiddenPreviewItem(item)) return false;
      if (movingKeys.has(originKeyOf(item))) return false;
      if (!q) return true;
      return previewRecordLabel(item).toLowerCase().includes(q);
    });
    els.moveAnchorSelect.innerHTML = source
      .map((item) => {
        const idx = previewItems.indexOf(item);
        return `<option value="${idx}">${escapeHtml(previewRecordLabel(item))}</option>`;
      })
      .join("");
    if (!source.length) {
      els.moveAnchorSelect.innerHTML = `<option value="">没有可作参照的记录</option>`;
      updateMovePreviewHint();
      return;
    }
    const locateIdx = preferredAnchorIdxFromList(source);
    if (!keepSelection && locateIdx >= 0) {
      els.moveAnchorSelect.value = String(locateIdx);
    } else if (prev && source.some((item) => String(previewItems.indexOf(item)) === prev)) {
      els.moveAnchorSelect.value = prev;
    } else if (locateIdx >= 0) {
      els.moveAnchorSelect.value = String(locateIdx);
    } else {
      els.moveAnchorSelect.value = String(previewItems.indexOf(source[0]));
    }
    updateMovePreviewHint();
  }

  function openMovePreviewPanel() {
    if (!currentJobId) {
      toast("请先生成预览后再调整顺序", "warning");
      return;
    }
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    flushPreviewLocate();
    const moving = listSelectedItemsForMove();
    if (!moving.length) {
      toast("请先勾选要调整顺序的记录", "warning");
      return;
    }
    hidePreviewOpPanels();
    if (els.movePlaceSelect) els.movePlaceSelect.value = "after";
    if (els.moveAnchorFilter) els.moveAnchorFilter.value = "";
    fillMoveAnchorOptions();
    updateMovePreviewHint();
    if (els.movePreviewPanel) els.movePreviewPanel.classList.remove("d-none");
    const locate = locatePreviewItem();
    if (locate) scrollPreviewItemIntoView(originKeyOf(locate));
  }

  function confirmMovePreviewRows() {
    if (!currentJobId) {
      toast("请先生成预览后再调整顺序", "warning");
      return;
    }
    const moving = listSelectedItemsForMove();
    if (!moving.length) {
      toast("请先勾选要调整顺序的记录", "warning");
      return;
    }
    const idx = Number(els.moveAnchorSelect && els.moveAnchorSelect.value);
    const anchor = Number.isFinite(idx) ? previewItems[idx] : null;
    if (!anchor) {
      toast("请选择参照文件", "warning");
      return;
    }
    if (moving.some((item) => originKeyOf(item) === originKeyOf(anchor))) {
      toast("参照文件不能包含在要移动的勾选里", "warning");
      return;
    }
    const planned = movingItemsForAnchor(moving, anchor);
    const toMove = planned.toMove;
    const place = String((els.movePlaceSelect && els.movePlaceSelect.value) || "after");
    const ok = movePreviewItemsRelative(toMove, anchor, place === "before" ? "before" : "after");
    if (!ok) {
      return;
    }
    previewColSort = null;
    updatePreviewHeadUi();
    hideMovePreviewPanel();
    setPreviewLocateByItem(toMove[0] || anchor);
    renderPreviewTable(previewItems);
    scrollPreviewItemIntoView(originKeyOf(toMove[0] || anchor));
    const ignoredBit = planned.ignoredOther
      ? `（已忽略其它版本 ${planned.ignoredOther} 条）`
      : "";
    toast(
      `已将 ${toMove.length} 条移到「${previewRecordLabel(anchor)}」${
        place === "before" ? "前面" : "后面"
      }${ignoredBit}，请点「保存预览修改」`,
      "info"
    );
  }

  function addPreviewRow(anchor, place) {
    if (!currentJobId) {
      toast("请先生成预览后再添加记录", "warning");
      return;
    }
    syncPreviewItemsFromDom();
    syncPreviewSelectionFromDom();
    const item = buildBlankPreviewItem(anchor || null);
    insertPreviewItemRelative(item, anchor || null, place || "after");
    previewSelectedKeys.add(taskIdentity(item));
    hideAddPreviewPanel();
    setPreviewLocateByItem(item);
    renderPreviewTable(previewItems);
    scrollPreviewItemIntoView(originKeyOf(item));
    const where = anchor
      ? `${place === "before" ? "前面" : "后面"}（${previewVersionKey(item)} / ${previewChapterKey(item)}）`
      : "末尾";
    toast(`已在${where}添加一条空白记录，请填写后点「保存预览修改」`, "info");
  }

  function confirmAddPreviewRow() {
    if (!currentJobId) {
      toast("请先生成预览后再添加记录", "warning");
      return;
    }
    syncPreviewItemsFromDom();
    if (!previewItems.length) {
      addPreviewRow(null, "after");
      return;
    }
    const idx = Number(els.addAnchorSelect && els.addAnchorSelect.value);
    const anchor = Number.isFinite(idx) ? previewItems[idx] : null;
    if (!anchor) {
      toast("请选择参照记录", "warning");
      return;
    }
    const place = String((els.addPlaceSelect && els.addPlaceSelect.value) || "after");
    addPreviewRow(anchor, place === "before" ? "before" : "after");
  }

  async function syncPreviewDocMeta() {
    syncPreviewItemsFromDom();
    if (!previewItems.length) {
      toast("请先生成预览", "warning");
      return;
    }
    const data = await requestJson("/api/document-control/version-tasks/sync-document-meta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId: String((els.projectId && els.projectId.value) || "").trim() || null,
        items: previewItems.map((item) => ({
          originKey: originKeyOf(item),
          fileName: item.fileName || "",
          documentNumber: item.documentNumber || "",
          fileVersion: item.fileVersion || "",
        })),
      }),
    });
    const byKey = new Map();
    (Array.isArray(data.items) ? data.items : []).forEach((row) => {
      if (row && row.originKey) byKey.set(String(row.originKey), row);
    });
    previewItems.forEach((item) => {
      const hit = byKey.get(originKeyOf(item));
      if (!hit) return;
      item.documentNumber = String(hit.documentNumber || "").trim();
      item.fileVersion = String(hit.fileVersion || "").trim();
      refreshItemChangeMark(item);
    });
    renderPreviewTable(previewItems);
    toast(data.message || "已从文控台账同步", "info");
  }

  async function persistPreviewEdits(options) {
    const opts = options || {};
    if (!currentJobId) {
      if (!opts.quietSuccess) toast("请先生成预览后再保存修改", "warning");
      return false;
    }
    const items = getPreviewItems();
    const conflicts = listPreviewFilenameConflicts(items);
    if (conflicts.length) {
      markPreviewFilenameConflicts();
      toast(formatFilenameConflicts(conflicts), "warning");
      return false;
    }
    const { changedItems, removedOriginKeys } = collectChangedPreviewItems(items);
    if (!changedItems.length && !removedOriginKeys.length) {
      if (!opts.quietSuccess) toast("没有需要保存的增删改", "info");
      return false;
    }
    const adjustments = collectAdjustments(items);
    const data = await requestJson("/api/document-control/version-tasks/preview/save-edits", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jobId: currentJobId,
        projectId: String(els.projectId.value || "").trim() || null,
        items,
        adjustments,
      }),
    });
    const savedItems = combinePreviewPayloadItems(data, items);
    adoptPreviewBaselines(savedItems, data.ruleItems, data.manualDeletedKeys);
    renderPreviewTable(originalPreviewItems);
    loadFeedbackHistory().catch(() => {});
    const addCount = adjustments.filter((row) => row && row.type === "add").length;
    const updateCount = adjustments.filter((row) => row && row.type === "update").length;
    const deletedCount = adjustments.filter((row) => row && row.type === "delete").length;
    if (els.previewSaveBanner) {
      const stamp = data.updatedAt
        ? String(data.updatedAt).replace("T", " ").slice(0, 19)
        : "";
      const extraBits = [`当前可见 ${visiblePreviewItems(savedItems).length} 条`];
      const patchedN = Number(data.patchedCount || changedItems.length);
      if (patchedN) extraBits.push(`增量 ${patchedN}`);
      if (addCount) extraBits.push(`新增 ${addCount}`);
      if (updateCount) extraBits.push(`修改 ${updateCount}`);
      if (deletedCount) extraBits.push(`删除 ${deletedCount}`);
      const extra = extraBits.join("，") + "（刷新后仍隐藏；再次生成预览会按规则加回来）";
      els.previewSaveBanner.innerHTML = `<div class="alert alert-success py-2 px-3 mb-2 small">已保存预览修改${
        stamp ? `（${escapeHtml(stamp)}）` : ""
      } · ${escapeHtml(extra)}${
        data.feedbackSaved ? ` · 采集 ${Number(data.feedbackSaved)} 条` : ""
      }</div>`;
    }
    if (!opts.quietSuccess) {
      toast(data.message || `已保存预览清单（可见 ${visiblePreviewItems(savedItems).length} 条）`, "success");
    }
    return true;
  }

  async function savePreviewEdits() {
    await persistPreviewEdits({});
  }

  async function loadLatestPreview(options) {
    const opts = options || {};
    const projectId =
      opts.projectId != null ? String(opts.projectId || "").trim() : selectedProjectId();
    let url = "/api/document-control/version-tasks/latest-preview";
    if (projectId) {
      url += `?projectId=${encodeURIComponent(projectId)}`;
    }
    const data = await requestJson(url);
    if (!data || !data.jobId) {
      if (opts.clearIfEmpty !== false) {
        clearPreviewPanel(
          projectId ? "该项目暂无已保存的预览结果。" : "暂无已保存的预览结果。"
        );
      }
      return null;
    }
    if (data.projectId && !selectedProjectId()) {
      setProjectSelectValue(data.projectId);
    }
    applyPreviewPayload(data, {
      metaPrefix: "已加载上次预览",
      fillForm: opts.fillForm !== false,
      clearIntermediate: true,
    });
    return data;
  }

  async function doPreview(overwrite) {
    const { out, missing } = collectVersionReleaseDates();
    if (missing.length) {
      throw new Error(
        `以下版本缺少发布时间：${missing.join("、")}。请先填写，或点「检索候选发布日期」后再预览`
      );
    }
    const fromVersion = inputValue(els.fromVersion);
    const toVersion = inputValue(els.toVersion);
    if (!fromVersion || !toVersion) {
      throw new Error("请先填写开始版本号和最新版本号");
    }
    const payload = {
      fromVersion,
      toVersion,
      intermediateVersions: parseIntermediateVersions(),
      versionReleaseDates: out,
      projectId: selectedProjectId() || null,
      productName: inputValue(els.productName),
      registrationCountry: currentRegistrationCountry(),
      overwrite: Boolean(overwrite),
    };
    const sendPreview = (ow) =>
      requestJson("/api/document-control/version-tasks/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, overwrite: Boolean(ow) }),
      });
    let data;
    try {
      data = await sendPreview(overwrite);
    } catch (e) {
      if (e.status === 409 && e.payload && e.payload.duplicatePreview) {
        const ok = window.confirm(
          e.payload.message || "该项目该版本已有预览快照，是否覆盖？"
        );
        if (!ok) {
          toast("已取消，未覆盖已有快照", "info");
          return;
        }
        data = await sendPreview(true);
      } else {
        throw e;
      }
    }
    applyPreviewPayload(data, {
      metaPrefix: data.previewUpdated ? "已覆盖既有预览快照" : "已新建预览快照",
      fillForm: false,
    });
    const projectId = selectedProjectId();
    const productName = inputValue(els.productName);
    if (projectId && productName) {
      writeLocalProductName(projectId, productName);
      persistProductName().catch(() => {});
    }
    toast(
      data.previewUpdated
        ? "已覆盖该项目该版本的预览快照"
        : "已生成并保存为新的预览快照",
      "success"
    );
  }

  async function loadProjects() {
    if (!els.projectId) return;
    const previous = selectedProjectId() || readLastProjectId();
    els.projectId.innerHTML = '<option value="">项目加载中…</option>';
    if (els.batchProjectId) {
      els.batchProjectId.innerHTML = '<option value="">项目加载中…</option>';
    }
    const data = await requestJson("/api/projects");
    const arr = Array.isArray(data)
      ? data
      : Array.isArray(data && data.items)
        ? data.items
        : Array.isArray(data && data.projects)
          ? data.projects
          : [];
    projectsById.clear();
    const options = ['<option value="">请选择项目</option>'];
    arr.forEach((p) => {
      const id = String((p && p.id) || "");
      const name = String((p && p.name) || "");
      if (!id || !name) return;
      projectsById.set(id, p);
      const country = String((p && (p.registeredCountry || p.country)) || "").trim();
      const label = country ? `${name}（${country}）` : name;
      options.push(`<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`);
    });
    if (!projectsById.size) {
      const emptyHtml = '<option value="">暂无可见项目</option>';
      els.projectId.innerHTML = emptyHtml;
      if (els.batchProjectId) els.batchProjectId.innerHTML = emptyHtml;
      toast("未获取到项目。请确认当前账号对该公司有可见项目，或到任务管理查看。", "warning");
      return;
    }
    els.projectId.innerHTML = options.join("");
    if (els.batchProjectId) {
      els.batchProjectId.innerHTML = options.join("");
    }
    if (!setProjectSelectValue(previous)) restoreLastProject();
  }


  function applyBatchFieldsToRows() {
    if (!savedRecords.length) {
      toast("没有可应用的版本记录", "warning");
      return;
    }
    syncSavedRecordsFromDom();
    const batchProject = els.batchProjectId
      ? String(els.batchProjectId.value || "").trim()
      : "";
    const batchStatus = els.batchStatus ? String(els.batchStatus.value || "").trim() : "";
    if (!batchProject && !batchStatus) {
      toast("请先选择要批量设置的关联项目或生成状态", "warning");
      return;
    }
    savedRecords.forEach((row) => {
      if (batchProject) row.projectId = batchProject;
      if (batchStatus) row.generationStatus = batchStatus;
    });
    renderSavedRecordsTable();
    toast(
      `已应用到 ${savedRecords.length} 行` +
        (batchProject ? "（关联项目）" : "") +
        (batchStatus ? "（生成状态）" : "") +
        "，请点「批量保存」落库",
      "success"
    );
  }

  async function saveBatchSavedRecords() {
    syncSavedRecordsFromDom();
    if (!savedRecords.length) {
      toast("没有可保存的版本记录", "warning");
      return;
    }
    const filterProjectId = String(els.projectId.value || "").trim();
    const chainFrom = String(els.fromVersion.value || "").trim();
    const chainTo = String(els.toVersion.value || "").trim();
    const items = [];
    for (let i = 0; i < savedRecords.length; i += 1) {
      const row = savedRecords[i];
      const projectId = String(row.projectId || filterProjectId || "").trim();
      const version = String(row.version || "").trim();
      if (!projectId) {
        throw new Error(`第 ${i + 1} 行请选择关联项目`);
      }
      if (!version) {
        throw new Error(`第 ${i + 1} 行版本号不能为空`);
      }
      items.push({
        id: String(row.id || "").trim() || null,
        projectId,
        version,
        releasedAt: String(row.releasedAt || "").trim(),
        productName: String(row.productName || els.productName.value || "").trim(),
        generationStatus: String(row.generationStatus || "none").trim(),
        chainFromVersion: chainFrom,
        chainToVersion: chainTo,
      });
    }
    const data = await requestJson("/api/document-control/version-tasks/project-records/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items,
        chainFromVersion: chainFrom,
        chainToVersion: chainTo,
      }),
    });
    const savedCount = Number(data.saved || items.length);
    if (data.moved) {
      toast(
        `已批量保存 ${savedCount} 条，并同步改绑 ` +
          `${Number(data.movedRecordCount || 0)} 条版本记录` +
          (data.movedJobCount ? `及 ${data.movedJobCount} 个预览批次` : ""),
        "success"
      );
    } else {
      toast(`已批量保存 ${savedCount} 条版本记录`, "success");
    }
    await loadSavedRecords();
  }

  async function saveFeedbackIfNeeded(editedItems) {
    const adjustments = collectAdjustments(editedItems);
    if (!adjustments.length) {
      return 0;
    }
    const data = await requestJson("/api/document-control/version-tasks/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceJobId: currentJobId || null,
        projectId: String(els.projectId.value || "").trim() || null,
        adjustments,
      }),
    });
    loadFeedbackHistory().catch(() => {});
    return Number(data.saved || 0);
  }

  async function applyTasks(authorConflictAction) {
    const projectId = String(els.projectId.value || "").trim();
    if (!projectId) {
      toast("请先选择项目再下发任务", "warning");
      return;
    }
    const items = getPreviewItems();
    if (!items.length) {
      toast("预览任务清单为空，请先生成预览", "warning");
      return;
    }
    const selectedItems = items.filter(
      (item) => canSelectPreview(item) && previewSelectedKeys.has(taskIdentity(item))
    );
    if (!selectedItems.length) {
      toast("请勾选至少一条「选用」且未删除的记录再下发", "warning");
      return;
    }
    const conflicts = listPreviewFilenameConflicts(selectedItems);
    if (conflicts.length) {
      markPreviewFilenameConflicts();
      toast(formatFilenameConflicts(conflicts), "warning");
      return;
    }
    const applyMode = currentApplyMode();
    const { out } = collectVersionReleaseDates();
    const saved = await saveFeedbackIfNeeded(items);
    let data;
    try {
      data = await requestJson("/api/document-control/version-tasks/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceJobId: currentJobId || null,
          projectId,
          items: selectedItems,
          previewItems: items,
          applyMode,
          authorConflictAction: authorConflictAction || "",
          versionReleaseDates: out,
          fromVersion: String(els.fromVersion.value || "").trim(),
          toVersion: String(els.toVersion.value || "").trim(),
          productName: String(els.productName.value || "").trim(),
        }),
      });
    } catch (err) {
      const payload = err && err.payload;
      if (err && err.status === 409 && payload && payload.needsAuthorChoice) {
        const choice = await askAuthorConflictChoice(payload.authorConflicts || [], payload.message);
        if (!choice) {
          toast("已取消下发", "info");
          return;
        }
        return applyTasks(choice);
      }
      throw err;
    }
    await loadProjectRecords();
    await loadApplyBatches();
    if (els.applyMsg) {
      els.applyMsg.textContent = `${data.message || "下发完成"}${saved ? `（已记录反馈 ${saved} 条）` : ""}`;
    }
    toast(data.message || "下发完成", "success");
  }

  function collectListExportItems() {
    syncPreviewItemsFromDom();
    return (previewItems || [])
      .filter((item) => !isHiddenPreviewItem(item) && recordStatusOf(item) !== "discard")
      .map((item) => ({
        fileName: String((item && item.fileName) || "").trim(),
        documentNumber: String((item && item.documentNumber) || "").trim(),
        fileVersion: String((item && item.fileVersion) || "").trim(),
        documentDisplayDate: String((item && item.documentDisplayDate) || "").trim(),
        targetVersion: String((item && (item.targetVersion || item.registrationVersion)) || "").trim(),
        notes: String((item && item.notes) || "").trim(),
        explanation: String((item && item.explanation) || "").trim(),
      }))
      .filter((item) => item.fileName);
  }

  function parseDispositionFilename(header, fallback) {
    const cd = String(header || "");
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    if (star && star[1]) {
      try {
        return decodeURIComponent(star[1]);
      } catch (e) {
        return star[1];
      }
    }
    const plain = /filename="?([^";]+)"?/i.exec(cd);
    return (plain && plain[1]) || fallback;
  }

  async function exportVersionTaskList(kind) {
    const items = collectListExportItems();
    if (!items.length) {
      toast("请先生成预览清单再导出", "warning");
      return;
    }
    const fallback =
      kind === "tech" ? "QR-QP4.2.4-07 技术文件清单.docx" : "QR-QP4.2.3-01 医疗器械主文档清单.docx";
    const resp = await fetch(withScriptRoot("/api/document-control/version-tasks/export-list"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        items,
        productName: String((els.productName && els.productName.value) || "").trim(),
      }),
    });
    if (!resp.ok) {
      let msg = `导出失败（${resp.status}）`;
      try {
        const data = await resp.json();
        if (data && data.message) msg = data.message;
      } catch (e) {
        /* ignore */
      }
      throw new Error(msg);
    }
    const blob = await resp.blob();
    const filename = parseDispositionFilename(resp.headers.get("Content-Disposition"), fallback);
    downloadBlob(blob, filename);
    toast(`已导出：${filename}`, "success");
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "download";
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      if (a.parentNode) a.parentNode.removeChild(a);
      URL.revokeObjectURL(url);
    }, 300);
  }

  function collectPreviewExcelItems() {
    return getPreviewItems()
      .filter((item) => !isHiddenPreviewItem(item))
      .map((item) => ({
        fileName: String((item && item.fileName) || "").trim(),
        taskType: String((item && item.taskType) || "").trim(),
        targetVersion: String((item && (item.targetVersion || item.registrationVersion)) || "").trim(),
        author: String((item && item.author) || "").trim(),
        dueDate: String((item && item.dueDate) || "").trim(),
        documentDisplayDate: String((item && item.documentDisplayDate) || "").trim(),
        belongingModule: String((item && item.belongingModule) || "").trim(),
        archiveFrequency: String((item && item.archiveFrequency) || "").trim(),
        triggeredBy: Array.isArray(item && item.triggeredBy)
          ? item.triggeredBy
          : String((item && item.triggeredBy) || "").trim(),
        changeReason: String((item && item.changeReason) || "").trim(),
        documentNumber: String((item && item.documentNumber) || "").trim(),
        fileVersion: String((item && item.fileVersion) || "").trim(),
        explanation: String((item && item.explanation) || "").trim(),
        notes: String((item && item.notes) || "").trim(),
        recordStatus: recordStatusOf(item),
        isSystemRecord: isSystemRecordOf(item),
        changeKind: changeKindOf(item),
        chapter: String((item && (item.chapter || item.processBranchLabel)) || "").trim(),
        applied: previewApplyState(item),
      }));
  }

  async function exportPreviewExcel() {
    await loadApplyBatches();
    const items = collectPreviewExcelItems();
    if (!items.length) {
      toast("请先生成预览清单再导出", "warning");
      return;
    }
    const resp = await fetch(withScriptRoot("/api/document-control/version-tasks/export-excel"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items,
        projectId: selectedProjectId() || "",
        productName: String((els.productName && els.productName.value) || "").trim(),
        fromVersion: String((els.fromVersion && els.fromVersion.value) || "").trim(),
        toVersion: String((els.toVersion && els.toVersion.value) || "").trim(),
      }),
    });
    if (!resp.ok) {
      let msg = `导出失败（${resp.status}）`;
      try {
        const data = await resp.json();
        if (data && data.message) msg = data.message;
      } catch (e) {
        /* ignore */
      }
      throw new Error(msg);
    }
    const blob = await resp.blob();
    const filename = parseDispositionFilename(
      resp.headers.get("Content-Disposition"),
      "版本任务清单.xlsx"
    );
    downloadBlob(blob, filename);
    toast(`已导出：${filename}`, "success");
  }

  function askAuthorConflictChoice(conflicts, message) {
    return new Promise((resolve) => {
      const modal = els.authorConflictModal;
      const list = els.authorConflictList;
      if (!modal || !list) {
        const ok = window.confirm(
          `${message || "存在责任人不同的已有任务。"}确定替换原记录？取消则新增为新任务。`
        );
        resolve(ok ? "replace" : "create");
        return;
      }
      const rows = Array.isArray(conflicts) ? conflicts : [];
      list.innerHTML = rows.length
        ? rows
            .map((row) => {
              const fileName = escapeHtml((row && row.fileName) || "");
              const ver = escapeHtml((row && row.targetVersion) || "未指定");
              const from = escapeHtml(((row && row.existingAuthors) || []).join("、") || "空");
              const to = escapeHtml((row && row.newAuthor) || "");
              return `<li>${fileName}（${ver}）：责任人 ${from} → ${to}</li>`;
            })
            .join("")
        : `<li>${escapeHtml(message || "责任人不同")}</li>`;
      modal.classList.remove("d-none");
      const finish = (value) => {
        modal.classList.add("d-none");
        els.authorConflictCancel && els.authorConflictCancel.removeEventListener("click", onCancel);
        els.authorConflictCreate && els.authorConflictCreate.removeEventListener("click", onCreate);
        els.authorConflictReplace && els.authorConflictReplace.removeEventListener("click", onReplace);
        resolve(value);
      };
      const onCancel = () => finish("");
      const onCreate = () => finish("create");
      const onReplace = () => finish("replace");
      if (els.authorConflictCancel) els.authorConflictCancel.addEventListener("click", onCancel);
      if (els.authorConflictCreate) els.authorConflictCreate.addEventListener("click", onCreate);
      if (els.authorConflictReplace) els.authorConflictReplace.addEventListener("click", onReplace);
    });
  }

  async function onProjectChanged() {
    const projectId = selectedProjectId();
    writeLastProjectId(projectId);
    await loadSavedRecords();
    if (!projectId) {
      clearPreviewPanel("请选择项目后查看该项目上次预览，或直接生成新预览。");
      loadFeedbackHistory().catch(() => {});
      loadApplyBatches().catch(() => {});
      return;
    }
    const latest = await loadLatestPreview({ projectId, clearIfEmpty: true });
    if (!latest) {
      applySavedRecordsToChainForm();
    }
    loadFeedbackHistory().catch(() => {});
    loadApplyBatches().catch(() => {});
  }

  function bindEvents() {
    window.addEventListener("resize", () => {
      fitPreviewTableViewport();
    });
    bindPreviewDrag();
    bindPreviewHead();
    previewColOrder = loadPreviewColOrder();
    applyPreviewColOrder();
    if (els.clearColFiltersBtn) {
      els.clearColFiltersBtn.addEventListener("click", () => clearPreviewColFilters());
    }
    if (els.changeLogPager) {
      els.changeLogPager.addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-vtg-collection-page]");
        if (!btn || btn.disabled) return;
        const page = Number(btn.getAttribute("data-vtg-collection-page"));
        if (Number.isNaN(page) || page < 1) return;
        collectionPage = page;
        renderCollectionPanel();
      });
    }
    [els.fromVersion, els.toVersion, els.intermediate].forEach((el) => {
      if (!el) return;
      el.addEventListener("input", renderVersionDatesTable);
      el.addEventListener("change", renderVersionDatesTable);
    });
    if (els.projectId) {
      els.projectId.addEventListener("change", () => {
        onProjectChanged().catch((e) => toast(e.message || "加载失败", "danger"));
      });
    }
    if (els.productName) {
      els.productName.addEventListener("change", () => {
        persistProductName().catch((e) =>
          toast(e.message || "产品名称保存失败", "danger")
        );
      });
      els.productName.addEventListener("blur", () => {
        const projectId = String(els.projectId && els.projectId.value || "").trim();
        const productName = String(els.productName.value || "").trim();
        if (projectId) writeLocalProductName(projectId, productName);
      });
    }
    if (els.reloadRecordsBtn) {
      els.reloadRecordsBtn.addEventListener("click", () => {
        withButtonBusy(els.reloadRecordsBtn, "刷新中…", () => loadSavedRecords()).catch((e) =>
          toast(e.message || "刷新失败", "danger")
        );
      });
    }
    if (els.addRecordBtn) {
      els.addRecordBtn.addEventListener("click", addSavedRecordRow);
    }
    if (els.batchApplyBtn) {
      els.batchApplyBtn.addEventListener("click", applyBatchFieldsToRows);
    }
    if (els.batchSaveBtn) {
      els.batchSaveBtn.addEventListener("click", () => {
        withButtonBusy(els.batchSaveBtn, "批量保存中…", () => saveBatchSavedRecords()).catch(
          (e) => toast(e.message || "批量保存失败", "danger")
        );
      });
    }
    if (els.loadRecordsToChainBtn) {
      els.loadRecordsToChainBtn.addEventListener("click", loadSavedRecordsToChain);
    }
    if (els.syncChainToRecordsBtn) {
      els.syncChainToRecordsBtn.addEventListener("click", () => {
        withButtonBusy(els.syncChainToRecordsBtn, "保存中…", () => saveProjectRecords()).catch(
          (e) => toast(e.message || "保存失败", "danger")
        );
      });
    }
    if (els.saveRecordsBtn) {
      els.saveRecordsBtn.addEventListener("click", () => {
        withButtonBusy(els.saveRecordsBtn, "保存中…", () => saveProjectRecords()).catch((e) =>
          toast(e.message || "保存失败", "danger")
        );
      });
    }
    if (els.suggestBtn) {
      els.suggestBtn.addEventListener("click", () => {
        if (suggestInFlight) {
          toast("检索进行中，请稍候…", "info");
          return;
        }
        withButtonBusy(els.suggestBtn, "检索中…", () => suggestReleaseDate(null)).catch((e) =>
          toast(e.message || "检索失败", "danger")
        );
      });
    }
    if (els.diagnoseBtn) {
      els.diagnoseBtn.addEventListener("click", () => {
        withButtonBusy(els.diagnoseBtn, "诊断中…", () => diagnoseReleaseDate(null)).catch((e) =>
          toast(e.message || "诊断失败", "danger")
        );
      });
    }
    if (els.previewBtn) {
      els.previewBtn.addEventListener("click", () => {
        withButtonBusy(els.previewBtn, "预览中…", () => doPreview()).catch((e) =>
          toast(e.message || "预览失败", "danger")
        );
      });
    }
    if (els.applyBtn) {
      els.applyBtn.addEventListener("click", () => {
        withButtonBusy(els.applyBtn, "下发中…", () => applyTasks()).catch((e) =>
          toast(e.message || "下发失败", "danger")
        );
      });
    }
    if (els.exportMasterListBtn) {
      els.exportMasterListBtn.addEventListener("click", () => {
        withButtonBusy(els.exportMasterListBtn, "导出中…", () => exportVersionTaskList("master")).catch((e) =>
          toast(e.message || "导出失败", "danger")
        );
      });
    }
    if (els.exportTechListBtn) {
      els.exportTechListBtn.addEventListener("click", () => {
        withButtonBusy(els.exportTechListBtn, "导出中…", () => exportVersionTaskList("tech")).catch((e) =>
          toast(e.message || "导出失败", "danger")
        );
      });
    }
    if (els.exportPreviewExcelBtn) {
      els.exportPreviewExcelBtn.addEventListener("click", () => {
        withButtonBusy(els.exportPreviewExcelBtn, "导出中…", () => exportPreviewExcel()).catch((e) =>
          toast(e.message || "导出失败", "danger")
        );
      });
    }
    if (els.applyBatchReload) {
      els.applyBatchReload.addEventListener("click", () => {
        withButtonBusy(els.applyBatchReload, "刷新中…", () => loadApplyBatches()).catch((e) =>
          toast(e.message || "刷新条数失败", "danger")
        );
      });
    }
    if (els.applyBatchList) {
      els.applyBatchList.addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-vtg-apply-key]");
        if (!btn || !els.applyBatchList.contains(btn)) return;
        const key = btn.getAttribute("data-vtg-apply-key") || "";
        if (!key) return;
        if (applyLedgerExpandedKeys.has(key)) applyLedgerExpandedKeys.delete(key);
        else applyLedgerExpandedKeys.add(key);
        const expanded = applyLedgerExpandedKeys.has(key);
        btn.setAttribute("aria-expanded", expanded ? "true" : "false");
        const caret = btn.querySelector(".vtg-caret");
        if (caret) caret.textContent = expanded ? "▼" : "▶";
        const hint = btn.querySelector("[data-vtg-apply-ver-hint]");
        if (hint) hint.textContent = expanded ? " 收起" : " 展开";
        const recs = btn.nextElementSibling;
        if (recs && recs.classList.contains("vtg-apply-recs")) {
          recs.classList.toggle("is-collapsed", !expanded);
        }
      });
    }
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.addEventListener("click", () => {
        withButtonBusy(els.savePreviewEditsBtn, "保存中…", () => savePreviewEdits()).catch(
          (e) => toast(e.message || "保存预览修改失败", "danger")
        );
      });
    }
    if (els.syncDocMetaBtn) {
      els.syncDocMetaBtn.addEventListener("click", () => {
        withButtonBusy(els.syncDocMetaBtn, "同步中…", () => syncPreviewDocMeta()).catch((e) =>
          toast(e.message || "从文控同步编号失败", "danger")
        );
      });
    }
    if (els.addPreviewRowBtn) {
      els.addPreviewRowBtn.addEventListener("click", () => openAddPreviewPanel());
    }
    if (els.addAnchorSelect) {
      els.addAnchorSelect.addEventListener("change", () => {
        const idx = Number(els.addAnchorSelect.value);
        if (!els.addPreviewHint || !previewItems[idx]) return;
        els.addPreviewHint.textContent = `将添加到「${previewRecordLabel(previewItems[idx])}」旁边（可改参照和前/后）。`;
      });
    }
    if (els.addPreviewConfirmBtn) {
      els.addPreviewConfirmBtn.addEventListener("click", () => confirmAddPreviewRow());
    }
    if (els.addPreviewCancelBtn) {
      els.addPreviewCancelBtn.addEventListener("click", () => hideAddPreviewPanel());
    }
    if (els.movePreviewBtn) {
      els.movePreviewBtn.addEventListener("click", () => openMovePreviewPanel());
    }
    if (els.movePreviewConfirmBtn) {
      els.movePreviewConfirmBtn.addEventListener("click", () => confirmMovePreviewRows());
    }
    if (els.movePreviewCancelBtn) {
      els.movePreviewCancelBtn.addEventListener("click", () => hideMovePreviewPanel());
    }
    if (els.copyPreviewBtn) {
      els.copyPreviewBtn.addEventListener("click", () => openCopyPreviewPanel());
    }
    if (els.copyFromVersion) {
      els.copyFromVersion.addEventListener("change", () => fillCopyVersionOptions({ keepSelection: true }));
    }
    if (els.copyToVersion) {
      els.copyToVersion.addEventListener("change", () => updateCopyPreviewHint());
    }
    if (els.copySelectedOnly) {
      els.copySelectedOnly.addEventListener("change", () => updateCopyPreviewHint());
    }
    if (els.copyPreviewConfirmBtn) {
      els.copyPreviewConfirmBtn.addEventListener("click", () => confirmCopyPreviewRows());
    }
    if (els.copyPreviewCancelBtn) {
      els.copyPreviewCancelBtn.addEventListener("click", () => hideCopyPreviewPanel());
    }
    if (els.batchDueDateBtn) {
      els.batchDueDateBtn.addEventListener("click", () => openBatchDueDatePanel());
    }
    if (els.batchDueDateConfirmBtn) {
      els.batchDueDateConfirmBtn.addEventListener("click", () => confirmBatchDueDate());
    }
    if (els.batchDueDateCancelBtn) {
      els.batchDueDateCancelBtn.addEventListener("click", () => hideBatchDueDatePanel());
    }
    if (els.batchDueDateInput) {
      els.batchDueDateInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          confirmBatchDueDate();
        }
      });
    }
    if (els.deleteVersionBtn) {
      els.deleteVersionBtn.addEventListener("click", () => openDeleteVersionPanel());
    }
    if (els.deleteVersionSelect) {
      els.deleteVersionSelect.addEventListener("change", () => updateDeleteVersionHint());
    }
    if (els.deleteVersionConfirmBtn) {
      els.deleteVersionConfirmBtn.addEventListener("click", () => confirmDeletePreviewVersion());
    }
    if (els.deleteVersionCancelBtn) {
      els.deleteVersionCancelBtn.addEventListener("click", () => hideDeleteVersionPanel());
    }
    if (els.moveAnchorFilter) {
      els.moveAnchorFilter.addEventListener("input", () => fillMoveAnchorOptions({ keepSelection: true }));
    }
    if (els.moveAnchorSelect) {
      els.moveAnchorSelect.addEventListener("change", () => updateMovePreviewHint());
    }
    if (els.previewSelectAll) {
      els.previewSelectAll.addEventListener("click", () => selectVisibleAdopt());
    }
    if (els.previewUnselectAll) {
      els.previewUnselectAll.addEventListener("click", () => unselectAllPreview());
    }
    if (els.previewUnselectVisible) {
      els.previewUnselectVisible.addEventListener("click", () => unselectVisiblePreview());
    }
    if (els.previewHeadCheck) {
      els.previewHeadCheck.addEventListener("change", () => {
        if (els.previewHeadCheck.checked) selectVisibleAdopt();
        else unselectVisiblePreview();
      });
    }
    if (els.previewVersionBar) {
      els.previewVersionBar.addEventListener("click", (ev) => {
        const filterBtn = ev.target.closest("[data-vtg-ver-filter]");
        if (filterBtn) {
          previewVersionFilter = filterBtn.getAttribute("data-vtg-ver-filter") || "";
          if (previewVersionFilter) previewCollapsedVersions.delete(previewVersionFilter);
          applyPreviewVersionUi();
          return;
        }
        if (ev.target.closest("[data-vtg-ver-expand-all]")) {
          previewCollapsedVersions.clear();
          applyPreviewVersionUi();
          return;
        }
        if (ev.target.closest("[data-vtg-ver-collapse-all]")) {
          listPreviewVersionStats().forEach(([ver]) => previewCollapsedVersions.add(ver));
          applyPreviewVersionUi();
        }
      });
    }
    if (els.previewBody) {
      els.previewBody.addEventListener("input", (ev) => {
        if (ev.target.matches("[data-vtg-field=\"author\"]")) {
          const row = ev.target.closest("tr[data-vtg-preview-idx]");
          const idx = row ? Number(row.getAttribute("data-vtg-preview-idx")) : NaN;
          if (!Number.isNaN(idx) && previewItems[idx]) {
            previewItems[idx].author = String(ev.target.value || "").trim();
            updateApplyIssueCount();
          }
        }
        if (!ev.target.matches(".vtg-filename-input")) return;
        ev.target.title = ev.target.value || "";
        ev.target.style.height = "auto";
        ev.target.style.height = `${Math.max(38, ev.target.scrollHeight)}px`;
        const row = ev.target.closest("tr[data-vtg-preview-idx]");
        applyReleaseRecordDateUi(row, ev.target.value);
      });
      els.previewBody.addEventListener("change", (ev) => {
        const row = ev.target.closest("tr[data-vtg-preview-idx]");
        if (!row) return;
        const idx = Number(row.getAttribute("data-vtg-preview-idx"));
        if (Number.isNaN(idx) || !previewItems[idx]) return;
        if (ev.target.matches("[data-vtg-field=\"recordStatus\"]")) {
          const status = recordStatusOf({ recordStatus: ev.target.value });
          previewItems[idx].recordStatus = status;
          const key = taskIdentity(previewItems[idx]);
          if (canSelectPreview(previewItems[idx])) previewSelectedKeys.add(key);
          else if (isPreviewDeleted(previewItems[idx])) previewSelectedKeys.delete(key);
        }
        if (ev.target.matches("[data-vtg-select-row]")) {
          const key = taskIdentity(previewItems[idx]);
          if (ev.target.checked && canCheckPreview(previewItems[idx])) {
            previewSelectedKeys.add(key);
          } else {
            previewSelectedKeys.delete(key);
          }
          updatePreviewSelectionUi();
          return;
        }
        if (ev.target.matches("[data-vtg-field]")) {
          const field = ev.target.getAttribute("data-vtg-field") || "";
          const oldIdent = taskIdentity(previewItems[idx]);
          const prevItem = {
            fileName: previewItems[idx].fileName,
            targetVersion: previewItems[idx].targetVersion,
            fileVersion: previewItems[idx].fileVersion,
            registrationVersion: previewItems[idx].registrationVersion,
          };
          syncPreviewItemsFromDom();
          const item = previewItems[idx];
          remapPreviewSelectionKey(oldIdent, item);
          if (field === "isSystemRecord") {
            const wrap = ev.target.closest(".vtg-system-check");
            const span = wrap && wrap.querySelector("span");
            if (span) span.textContent = isSystemRecordOf(item) ? "是" : "否";
          }
          if (field === "fileName" || field === "targetVersion") {
            const other = findSameNameInVersion(item, previewItems);
            if (other) {
              if (field === "fileName") {
                item.fileName = prevItem.fileName;
                ev.target.value = prevItem.fileName || "";
              } else {
                item.targetVersion = prevItem.targetVersion;
                item.registrationVersion = prevItem.registrationVersion;
                ev.target.value = prevItem.targetVersion || prevItem.registrationVersion || "";
              }
              toast(
                `同一版本下文件名不能重复：${previewVersionKey(other)} 已有「${String(
                  other.fileName || ""
                ).trim()}」`,
                "warning"
              );
              markPreviewFilenameConflicts();
              return;
            }
          }
          if (field === "fileName") applyReleaseRecordDateUi(row, item.fileName);
          const changeCell = row.querySelector(".vtg-change-cell");
          if (changeCell) changeCell.innerHTML = changeKindBadgeHtml(item);
          row.classList.toggle("vtg-change-delete", changeKindOf(item) === "delete");
          row.classList.toggle("vtg-change-add", changeKindOf(item) === "add");
          row.classList.toggle("vtg-change-update", changeKindOf(item) === "update");
          renderChangeLog(previewItems);
          updatePreviewSelectionUi();
          markPreviewFilenameConflicts();
        }
      });
      els.previewBody.addEventListener("click", (ev) => {
        const restoreBtn = ev.target.closest("button[data-vtg-restore-preview]");
        if (restoreBtn) {
          ev.preventDefault();
          ev.stopPropagation();
          syncPreviewItemsFromDom();
          syncPreviewSelectionFromDom();
          const idx = Number(restoreBtn.getAttribute("data-vtg-restore-preview"));
          if (Number.isNaN(idx) || !previewItems[idx]) return;
          const item = previewItems[idx];
          const other = findSameNameInVersion(item, previewItems);
          if (other) {
            toast(
              `无法还原：同一版本 ${previewVersionKey(item)} 已有文件「${String(other.fileName || "").trim()}」`,
              "warning"
            );
            return;
          }
          item.changeKind = "";
          delete item.hideInPreview;
          refreshItemChangeMark(item);
          if (canSelectPreview(item)) previewSelectedKeys.add(taskIdentity(item));
          renderPreviewTable(previewItems);
          toast("已还原该记录", "info");
          return;
        }
        const removeBtn = ev.target.closest("button[data-vtg-remove-preview]");
        if (removeBtn) {
          ev.preventDefault();
          ev.stopPropagation();
          syncPreviewItemsFromDom();
          syncPreviewSelectionFromDom();
          const idx = Number(removeBtn.getAttribute("data-vtg-remove-preview"));
          if (Number.isNaN(idx) || idx < 0 || idx >= previewItems.length) return;
          const item = previewItems[idx];
          const mode = markPreviewItemDeleted(item);
          if (mode === "remove") {
            previewItems.splice(idx, 1);
            renderPreviewTable(previewItems);
            toast("已移除未保存的新增记录", "info");
            persistPreviewEdits({ quietSuccess: true }).catch((e) =>
              toast(e.message || "移除已生效，但保存失败，请点「保存预览修改」", "warning")
            );
            return;
          }
          renderPreviewTable(previewItems);
          toast("已从列表删除", "info");
          persistPreviewEdits({ quietSuccess: true }).catch((e) =>
            toast(e.message || "删除已生效，但保存失败，请点「保存预览修改」", "warning")
          );
          return;
        }
        if (ev.target.closest(".vtg-drag-handle")) return;
        if (ev.target.closest("input, select, textarea, a")) return;
        const copyVerBtn = ev.target.closest("[data-vtg-copy-ver]");
        if (copyVerBtn) {
          ev.preventDefault();
          ev.stopPropagation();
          openCopyPreviewPanel(copyVerBtn.getAttribute("data-vtg-copy-ver") || "");
          return;
        }
        const delVerBtn = ev.target.closest("[data-vtg-delete-ver]");
        if (delVerBtn) {
          ev.preventDefault();
          ev.stopPropagation();
          openDeleteVersionPanel(delVerBtn.getAttribute("data-vtg-delete-ver") || "");
          return;
        }
        const header = ev.target.closest("tr.vtg-version-row");
        if (!header) return;
        const ver = header.getAttribute("data-vtg-ver") || "";
        if (!ver) return;
        if (previewCollapsedVersions.has(ver)) previewCollapsedVersions.delete(ver);
        else previewCollapsedVersions.add(ver);
        applyPreviewVersionUi();
      });
      els.previewBody.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        if (ev.target.closest("button, input, select, textarea, a")) return;
        const header = ev.target.closest("tr.vtg-version-row");
        if (!header) return;
        ev.preventDefault();
        header.click();
      });
    }
  }

  async function init() {
    if (els.diagnoseBtn && window.__PAGE13_SUPER_ADMIN__) {
      els.diagnoseBtn.classList.remove("d-none");
    }
    if (els.projectId) {
      els.projectId.innerHTML = '<option value="">项目加载中…</option>';
    }
    try {
      renderVersionDatesTable();
      renderSavedRecordsTable();
      bindEvents();
    } catch (err) {
      toast(err.message || "页面初始化失败", "danger");
    }
    try {
      await loadProjects();
    } catch (err) {
      const failHtml = '<option value="">项目加载失败，请刷新</option>';
      if (els.projectId) els.projectId.innerHTML = failHtml;
      if (els.batchProjectId) els.batchProjectId.innerHTML = failHtml;
      toast(err.message || "加载项目列表失败", "danger");
    }
    try {
      let projectId = restoreLastProject();
      if (!projectId) {
        try {
          const hint = await requestJson("/api/document-control/version-tasks/latest-preview");
          const hintId = String((hint && hint.lastRecordProjectId) || "").trim();
          projectId = setProjectSelectValue(hintId);
        } catch (e) {
          /* 仅用于回填项目，失败则保持未选 */
        }
      }
      if (projectId) {
        writeLastProjectId(projectId);
        await loadSavedRecords();
        const latest = await loadLatestPreview({
          projectId,
          clearIfEmpty: false,
          fillForm: true,
        });
        if (!latest) {
          applySavedRecordsToChainForm();
          clearPreviewPanel("尚未生成预览。已回填该项目已保存的版本记录，可直接生成预览。");
        }
      } else {
        clearPreviewPanel("尚未生成预览。选择项目可加载该项目上次结果，或填写版本后生成。");
      }
      loadFeedbackHistory().catch(() => {});
      loadApplyBatches().catch(() => {});
    } catch (err) {
      toast(err.message || "加载上次预览失败", "danger");
      loadApplyBatches().catch(() => {});
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
