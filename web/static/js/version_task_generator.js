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
    previewVersionBar: byId("vtgPreviewVersionBar"),
    previewBody: byId("vtgPreviewBody"),
    previewCount: byId("vtgPreviewCount"),
    previewSelectAll: byId("vtgPreviewSelectAll"),
    previewUnselectAll: byId("vtgPreviewUnselectAll"),
    previewUnselectVisible: byId("vtgPreviewUnselectVisible"),
    previewSelectHint: byId("vtgPreviewSelectHint"),
    previewHeadCheck: byId("vtgPreviewHeadCheck"),
    applyBtn: byId("vtgApplyBtn"),
    applyModeReplace: byId("vtgApplyModeReplace"),
    applyModeIncrement: byId("vtgApplyModeIncrement"),
    savePreviewEditsBtn: byId("vtgSavePreviewEditsBtn"),
    projectId: byId("vtgProjectId"),
    applyMsg: byId("vtgApplyMsg"),
  };

  const PRODUCT_NAME_LS_PREFIX = "vtg.productName.";
  const LAST_PROJECT_LS_KEY = "vtg.lastProjectId";

  let currentJobId = "";
  let originalPreviewItems = [];
  let previewItems = [];
  let previewVersionFilter = "";
  const previewCollapsedVersions = new Set();
  const previewSelectedKeys = new Set();
  const PREVIEW_COLSPAN = 14;
  let savedRecords = [];
  const projectsById = new Map();
  const versionDateValues = new Map();
  const projectVersionStatus = new Map();

  function currentRegistrationCountry() {
    const projectId = String(els.projectId && els.projectId.value || "").trim();
    const p = projectsById.get(projectId);
    return String((p && (p.registeredCountry || p.country)) || "").trim();
  }

  function buildSuggestPayload(targetVersion) {
    const projectId = String(els.projectId.value || "").trim() || null;
    let productName = String(els.productName.value || "").trim();
    // 未填产品名时用所选项目名称回填（与后端兜底一致）
    if (!productName && projectId) {
      const p = projectsById.get(projectId);
      const fromProject = String((p && p.name) || "").trim();
      if (fromProject) {
        productName = fromProject;
        if (els.productName && !String(els.productName.value || "").trim()) {
          els.productName.value = fromProject;
        }
      }
    }
    return {
      productName,
      fromVersion: String(els.fromVersion.value || "").trim(),
      toVersion: String(els.toVersion.value || "").trim(),
      intermediateVersions: parseIntermediateVersions(),
      targetVersion: targetVersion || null,
      projectId,
      registrationCountry: currentRegistrationCountry(),
    };
  }

  function parseIntermediateVersions() {
    const raw = String(els.intermediate.value || "");
    return raw
      .split(/[\n,，;]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function buildVersionChainInputs() {
    const from = String(els.fromVersion.value || "").trim();
    const to = String(els.toVersion.value || "").trim();
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
    const projectId = String(els.projectId.value || "").trim();
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
    if (!els.projectId) return "";
    const current = String(els.projectId.value || "").trim();
    if (current) return current;
    const last = readLastProjectId();
    if (last && projectsById.has(last)) {
      els.projectId.value = last;
      return last;
    }
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
      item.taskType = val("taskType");
      item.targetVersion = val("targetVersion");
      item.fileVersion = val("targetVersion") || item.fileVersion;
      item.registrationVersion = val("targetVersion") || item.registrationVersion;
      item.author = val("author");
      item.dueDate = val("dueDate");
      item.documentDisplayDate = val("documentDisplayDate");
      item.belongingModule = val("belongingModule");
      item.notes = val("notes");
      item.recordStatus = recordStatusOf({ recordStatus: val("recordStatus") });
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

  function recordStatusSelectHtml(status) {
    const cur = recordStatusOf({ recordStatus: status });
    const opts = [
      ["adopt", "选用"],
      ["pending", "待定"],
      ["discard", "弃用"],
    ];
    return `<select class="form-select form-select-sm vtg-status-select" data-vtg-field="recordStatus">${opts
      .map(
        ([value, label]) =>
          `<option value="${value}"${cur === value ? " selected" : ""}>${label}</option>`
      )
      .join("")}</select>`;
  }

  function itemForFeedbackCompare(item) {
    const copy = { ...(item || {}) };
    delete copy.recordStatus;
    return copy;
  }

  function defaultSelectAdoptItems(items) {
    previewSelectedKeys.clear();
    (items || []).forEach((item) => {
      if (recordStatusOf(item) === "adopt") {
        previewSelectedKeys.add(taskIdentity(item));
      }
    });
  }

  function prunePreviewSelection(items) {
    const live = new Set((items || []).map((item) => taskIdentity(item)));
    Array.from(previewSelectedKeys).forEach((key) => {
      if (!live.has(key)) previewSelectedKeys.delete(key);
    });
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
      const adopted = recordStatusOf(previewItems[idx]) === "adopt";
      if (cb && cb.checked && adopted) previewSelectedKeys.add(key);
      else previewSelectedKeys.delete(key);
    });
  }

  function selectVisibleAdopt() {
    syncPreviewItemsFromDom();
    visiblePreviewRows().forEach((row) => {
      const idx = Number(row.getAttribute("data-vtg-preview-idx"));
      if (Number.isNaN(idx) || !previewItems[idx]) return;
      if (recordStatusOf(previewItems[idx]) !== "adopt") return;
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
      const adopted = status === "adopt";
      const key = taskIdentity(item);
      if (!adopted) previewSelectedKeys.delete(key);
      const selected = adopted && previewSelectedKeys.has(key);
      const cb = row.querySelector("[data-vtg-select-row]");
      if (cb) {
        cb.disabled = !adopted;
        cb.checked = selected;
      }
      row.classList.toggle("vtg-status-discard", status === "discard");
      row.classList.toggle("vtg-status-pending", status === "pending");
      if (adopted) visibleAdopt += 1;
      if (selected) visibleSelected += 1;
    });
    if (els.previewHeadCheck) {
      els.previewHeadCheck.disabled = !previewItems.length || visibleAdopt === 0;
      els.previewHeadCheck.checked = visibleAdopt > 0 && visibleSelected === visibleAdopt;
      els.previewHeadCheck.indeterminate = visibleSelected > 0 && visibleSelected < visibleAdopt;
    }
    const adoptCount = previewItems.filter((item) => recordStatusOf(item) === "adopt").length;
    const selectedCount = previewItems.filter(
      (item) => recordStatusOf(item) === "adopt" && previewSelectedKeys.has(taskIdentity(item))
    ).length;
    if (els.previewCount) {
      if (!previewItems.length) {
        els.previewCount.textContent = "0 条";
      } else if (previewVersionFilter) {
        const n = previewItems.filter((item) => previewVersionKey(item) === previewVersionFilter).length;
        els.previewCount.textContent = `${n} / ${previewItems.length} 条 · 已选 ${selectedCount} · 选用 ${adoptCount}`;
      } else {
        els.previewCount.textContent = `${previewItems.length} 条 · 已选 ${selectedCount} · 选用 ${adoptCount}`;
      }
    }
    if (els.previewSelectHint) {
      els.previewSelectHint.textContent = previewItems.length
        ? `仅「选用」可下发。当前可见已选 ${visibleSelected} / ${visibleAdopt}。`
        : "仅「选用」可勾选下发。全选作用于当前可见行。";
    }
  }

  function previewVersionKey(item) {
    return String(
      (item && (item.targetVersion || item.fileVersion || item.registrationVersion)) || ""
    ).trim() || "未指定版本";
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

  function listPreviewVersionStats() {
    const map = new Map();
    previewItems.forEach((item) => {
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
      `<button type="button" class="vtg-version-chip${previewVersionFilter ? "" : " is-active"}" data-vtg-ver-filter="">全部<span class="vtg-chip-n">${previewItems.length}</span></button>`,
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
  }

  function renderPreviewTable(items, options) {
    const opts = options || {};
    previewItems = Array.isArray(items)
      ? items.map((x) => {
          const rec = { ...x };
          rec.recordStatus = recordStatusOf(rec);
          return rec;
        })
      : [];
    if (opts.resetSelection) {
      defaultSelectAdoptItems(previewItems);
    } else {
      prunePreviewSelection(previewItems);
    }
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.disabled = !currentJobId || !previewItems.length;
    }
    if (!els.previewBody) return;
    if (!previewItems.length) {
      previewSelectedKeys.clear();
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
        `<tr><td colspan="${PREVIEW_COLSPAN}" class="text-muted small text-center py-3">预览后将在此显示任务清单</td></tr>`;
      return;
    }
    const chapterOrder = [
      "软件变更管理",
      "系统追溯",
      "缺陷管理",
      "软件生产/发布管理",
    ];
    const byVersion = new Map();
    previewItems.forEach((item, idx) => {
      const ver = previewVersionKey(item);
      if (!byVersion.has(ver)) byVersion.set(ver, []);
      byVersion.get(ver).push({ item, idx });
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
          <td colspan="${PREVIEW_COLSPAN}"><span class="vtg-caret">▼</span>版本 <span class="font-monospace">${escapeHtml(ver)}</span>（${versionRows.length}）${escapeHtml(triggerText)}</td>
        </tr>`
      );
      const chapterGroups = new Map();
      versionRows.forEach((row) => {
        const key = String(row.item.chapter || row.item.processBranchLabel || "其它").trim() || "其它";
        if (!chapterGroups.has(key)) chapterGroups.set(key, []);
        chapterGroups.get(key).push(row);
      });
      const orderedChapters = [
        ...chapterOrder.filter((k) => chapterGroups.has(k)),
        ...Array.from(chapterGroups.keys()).filter((k) => !chapterOrder.includes(k)),
      ];
      orderedChapters.forEach((chapter) => {
        const rows = chapterGroups.get(chapter) || [];
        html.push(
          `<tr class="vtg-chapter-row" data-vtg-ver="${escapeHtml(ver)}"><td colspan="${PREVIEW_COLSPAN}">${escapeHtml(chapter)}（${rows.length}）</td></tr>`
        );
        rows.forEach(({ item, idx }) => {
          const triggers = formatTriggerBits(item.triggeredBy);
          const targetVersion = item.targetVersion || item.fileVersion || "";
          const freq = String(item.archiveFrequency || "").trim() || (String(item.taskType || "").includes("流程") ? "流程" : "—");
          const status = recordStatusOf(item);
          const adopted = status === "adopt";
          const selected = adopted && previewSelectedKeys.has(taskIdentity(item));
          html.push(`<tr data-vtg-preview-idx="${idx}" data-vtg-ver="${escapeHtml(ver)}" class="${status === "discard" ? "vtg-status-discard" : status === "pending" ? "vtg-status-pending" : ""}">
            <td class="text-center"><input type="checkbox" class="form-check-input" data-vtg-select-row ${selected ? "checked" : ""} ${adopted ? "" : "disabled"} title="${adopted ? "勾选后下发" : "仅选用状态可下发"}"></td>
            <td class="text-muted small">${idx + 1}</td>
            <td>${recordStatusSelectHtml(status)}</td>
            <td class="vtg-col-filename"><textarea class="form-control form-control-sm vtg-filename-input" data-vtg-field="fileName" rows="2" title="${escapeHtml(item.fileName || "")}">${escapeHtml(item.fileName || "")}</textarea></td>
            <td><input class="form-control form-control-sm" data-vtg-field="taskType" value="${escapeHtml(item.taskType || "")}"></td>
            <td><input class="form-control form-control-sm font-monospace" data-vtg-field="targetVersion" value="${escapeHtml(targetVersion)}"></td>
            <td><input class="form-control form-control-sm" data-vtg-field="author" value="${escapeHtml(item.author || "")}"></td>
            <td><input type="date" class="form-control form-control-sm" data-vtg-field="dueDate" value="${escapeHtml(item.dueDate || "")}"></td>
            <td><input type="date" class="form-control form-control-sm" data-vtg-field="documentDisplayDate" value="${escapeHtml(item.documentDisplayDate || "")}"></td>
            <td><input class="form-control form-control-sm" data-vtg-field="belongingModule" value="${escapeHtml(item.belongingModule || "")}"></td>
            <td class="small text-muted">${escapeHtml(freq)}</td>
            <td><input class="form-control form-control-sm" data-vtg-field="notes" value="${escapeHtml(item.notes || "")}"></td>
            <td class="small text-muted" title="版本号格式 X.Y.Z.B，按最高变化位：X&gt;Y&gt;Z&gt;B">${triggers}</td>
            <td><button type="button" class="btn btn-outline-danger btn-sm py-0 px-1" data-vtg-remove-preview="${idx}" title="删除">×</button></td>
          </tr>`);
        });
      });
    });
    els.previewBody.innerHTML = html.join("");
    renderPreviewVersionBar();
    applyPreviewVersionUi();
    fitFilenameInputs();
    Array.from(els.previewBody.querySelectorAll("button[data-vtg-remove-preview]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        syncPreviewItemsFromDom();
        syncPreviewSelectionFromDom();
        const idx = Number(btn.getAttribute("data-vtg-remove-preview"));
        if (Number.isNaN(idx)) return;
        previewItems.splice(idx, 1);
        renderPreviewTable(previewItems);
      });
    });
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

  function taskIdentity(item) {
    const fileName = String((item && (item.taskKey || item.fileName)) || "").trim().toLowerCase();
    const taskType = String((item && item.taskType) || "").trim().toLowerCase();
    const fileVersion = String((item && (item.fileVersion || item.targetVersion)) || "").trim().toLowerCase();
    return `${fileName}__${taskType}__${fileVersion}`;
  }

  async function requestJson(url, options) {
    const resp = await fetch(url, options);
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

  function collectAdjustments(editedItems) {
    const originalMap = new Map();
    originalPreviewItems.forEach((x) => originalMap.set(taskIdentity(x), x));
    const editedMap = new Map();
    editedItems.forEach((x) => editedMap.set(taskIdentity(x), x));

    const adjustments = [];
    editedItems.forEach((item) => {
      const key = taskIdentity(item);
      const origin = originalMap.get(key);
      if (!origin) {
        adjustments.push({ type: "add", adjustedItem: item });
        return;
      }
      const originStr = JSON.stringify(itemForFeedbackCompare(origin));
      const editedStr = JSON.stringify(itemForFeedbackCompare(item));
      if (originStr !== editedStr) {
        adjustments.push({ type: "update", originalItem: origin, adjustedItem: item });
      }
    });
    originalPreviewItems.forEach((item) => {
      const key = taskIdentity(item);
      if (!editedMap.has(key)) {
        adjustments.push({ type: "delete", originalItem: item });
      }
    });
    return adjustments;
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
      <div class="vtg-explain">
        <div class="vtg-explain-h">${escapeHtml(prefix || "预览")}${
          updatedAt ? ` · 保存 ${escapeHtml(updatedAt)}` : ""
        }</div>
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
      </div>`;
  }

  function buildPreviewMetaText(data, prefix) {
    renderPreviewMeta(data, prefix);
    return "";
  }

  function applyPreviewPayload(data, options) {
    const opts = options || {};
    currentJobId = data.jobId || "";
    originalPreviewItems = Array.isArray(data.items) ? JSON.parse(JSON.stringify(data.items)) : [];
    resetPreviewVersionUi();
    renderPreviewTable(originalPreviewItems, { resetSelection: true });
    if (opts.fillForm !== false) {
      if (data.fromVersion) els.fromVersion.value = data.fromVersion;
      if (data.toVersion) els.toVersion.value = data.toVersion;
      const chain = Array.isArray(data.versionChain) ? data.versionChain : [];
      if (chain.length > 2) {
        els.intermediate.value = chain.slice(1, -1).join(", ");
      } else if (chain.length <= 2 && opts.clearIntermediate) {
        els.intermediate.value = "";
      }
      applyVersionReleaseDatesFromPreview(data.versionReleaseDates || {});
      renderVersionDatesTable();
    } else {
      applyVersionReleaseDatesFromPreview(data.versionReleaseDates || {});
    }
    if (Array.isArray(data.savedRecords) && data.savedRecords.length) {
      applyProjectRecords(data.savedRecords);
    }
    if (opts.fillForm !== false && data.productName && els.productName) {
      els.productName.value = data.productName;
      writeLocalProductName(String(data.projectId || els.projectId.value || "").trim(), data.productName);
    }
    renderPreviewMeta(data, opts.metaPrefix || "预览");
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.disabled = !currentJobId || !previewItems.length;
    }
  }

  function clearPreviewPanel(message) {
    currentJobId = "";
    originalPreviewItems = [];
    previewSelectedKeys.clear();
    renderPreviewTable([]);
    if (els.previewMeta) {
      els.previewMeta.textContent = message || "尚未生成预览。";
    }
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.disabled = true;
    }
  }

  async function savePreviewEdits() {
    if (!currentJobId) {
      toast("请先生成预览后再保存修改", "warning");
      return;
    }
    const items = getPreviewItems();
    if (!items.length) {
      toast("预览清单为空，无法保存", "warning");
      return;
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
    originalPreviewItems = JSON.parse(JSON.stringify(items));
    if (els.previewMeta) {
      const stamp = data.updatedAt
        ? String(data.updatedAt).replace("T", " ").slice(0, 19)
        : "";
      const extra = data.feedbackSaved
        ? `反馈 ${data.feedbackSaved} 条将在下次「生成预览」时生效`
        : "无相对上次原表的字段差异";
      const banner = `<div class="alert alert-success py-2 px-3 mb-2 small">已保存预览修改${
        stamp ? `（${escapeHtml(stamp)}）` : ""
      } · ${escapeHtml(extra)}</div>`;
      if (!els.previewMeta.querySelector(".vtg-explain")) {
        els.previewMeta.innerHTML = banner;
      } else {
        els.previewMeta.insertAdjacentHTML("afterbegin", banner);
      }
    }
    toast(data.message || "预览修改已保存", "success");
  }

  async function loadLatestPreview(options) {
    const opts = options || {};
    const projectId =
      opts.projectId != null
        ? String(opts.projectId || "").trim()
        : String(els.projectId.value || "").trim();
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
    if (data.projectId && !String(els.projectId.value || "").trim()) {
      els.projectId.value = data.projectId;
    }
    applyPreviewPayload(data, {
      metaPrefix: "已加载上次预览",
      fillForm: opts.fillForm !== false,
      clearIntermediate: true,
    });
    return data;
  }

  async function doPreview() {
    const { out, missing } = collectVersionReleaseDates();
    if (missing.length) {
      throw new Error(
        `以下版本缺少发布时间：${missing.join("、")}。请先填写，或点「检索候选发布日期」后再预览`
      );
    }
    const fromVersion = String(els.fromVersion.value || "").trim();
    const toVersion = String(els.toVersion.value || "").trim();
    if (!fromVersion || !toVersion) {
      throw new Error("请先填写开始版本号和最新版本号");
    }
    const payload = {
      fromVersion,
      toVersion,
      intermediateVersions: parseIntermediateVersions(),
      versionReleaseDates: out,
      projectId: String(els.projectId.value || "").trim() || null,
      productName: String(els.productName.value || "").trim(),
      registrationCountry: currentRegistrationCountry(),
    };
    const data = await requestJson("/api/document-control/version-tasks/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    applyPreviewPayload(data, {
      metaPrefix: data.previewUpdated ? "已更新既有预览" : "已新建预览",
      fillForm: false,
    });
    const projectId = String(els.projectId.value || "").trim();
    const productName = String(els.productName.value || "").trim();
    if (projectId && productName) {
      writeLocalProductName(projectId, productName);
      persistProductName().catch(() => {});
    }
    toast(
      data.previewUpdated
        ? "预览已更新并自动保存（规则结果；表格手改需点「保存预览修改」）"
        : "预览已生成并自动保存（规则结果；表格手改需点「保存预览修改」）",
      "success"
    );
  }

  async function loadProjects() {
    const data = await requestJson("/api/projects");
    const arr = Array.isArray(data) ? data : [];
    projectsById.clear();
    const options = ['<option value="">请选择项目</option>'];
    arr.forEach((p) => {
      const id = String(p.id || "");
      const name = String(p.name || "");
      if (!id || !name) return;
      projectsById.set(id, p);
      const country = String(p.registeredCountry || "").trim();
      const label = country ? `${name}（${country}）` : name;
      options.push(`<option value="${id}">${escapeHtml(label)}</option>`);
    });
    els.projectId.innerHTML = options.join("");
    if (els.batchProjectId) {
      els.batchProjectId.innerHTML = options.join("");
    }
    restoreLastProject();
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
    return Number(data.saved || 0);
  }

  async function applyTasks() {
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
      (item) => recordStatusOf(item) === "adopt" && previewSelectedKeys.has(taskIdentity(item))
    );
    if (!selectedItems.length) {
      toast("请勾选至少一条「选用」记录再下发（弃用/待定不会下发）", "warning");
      return;
    }
    const applyMode = currentApplyMode();
    const { out } = collectVersionReleaseDates();
    const saved = await saveFeedbackIfNeeded(items);
    const data = await requestJson("/api/document-control/version-tasks/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceJobId: currentJobId || null,
        projectId,
        items: selectedItems,
        previewItems: items,
        applyMode,
        versionReleaseDates: out,
        fromVersion: String(els.fromVersion.value || "").trim(),
        toVersion: String(els.toVersion.value || "").trim(),
        productName: String(els.productName.value || "").trim(),
      }),
    });
    await loadProjectRecords();
    els.applyMsg.textContent = `${data.message || "下发完成"}${saved ? `（已记录反馈 ${saved} 条）` : ""}`;
    toast(data.message || "下发完成", "success");
  }

  async function onProjectChanged() {
    const projectId = String(els.projectId.value || "").trim();
    writeLastProjectId(projectId);
    await loadSavedRecords();
    if (!projectId) {
      clearPreviewPanel("请选择项目后查看该项目上次预览，或直接生成新预览。");
      return;
    }
    const latest = await loadLatestPreview({ projectId, clearIfEmpty: true });
    if (!latest) {
      applySavedRecordsToChainForm();
    }
  }

  function bindEvents() {
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
    els.suggestBtn.addEventListener("click", () => {
      if (suggestInFlight) {
        toast("检索进行中，请稍候…", "info");
        return;
      }
      withButtonBusy(els.suggestBtn, "检索中…", () => suggestReleaseDate(null)).catch((e) =>
        toast(e.message || "检索失败", "danger")
      );
    });
    if (els.diagnoseBtn) {
      els.diagnoseBtn.addEventListener("click", () => {
        withButtonBusy(els.diagnoseBtn, "诊断中…", () => diagnoseReleaseDate(null)).catch((e) =>
          toast(e.message || "诊断失败", "danger")
        );
      });
    }
    els.previewBtn.addEventListener("click", () => {
      withButtonBusy(els.previewBtn, "预览中…", () => doPreview()).catch((e) =>
        toast(e.message || "预览失败", "danger")
      );
    });
    els.applyBtn.addEventListener("click", () => {
      withButtonBusy(els.applyBtn, "下发中…", () => applyTasks()).catch((e) =>
        toast(e.message || "下发失败", "danger")
      );
    });
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.addEventListener("click", () => {
        withButtonBusy(els.savePreviewEditsBtn, "保存中…", () => savePreviewEdits()).catch(
          (e) => toast(e.message || "保存预览修改失败", "danger")
        );
      });
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
        if (!ev.target.matches(".vtg-filename-input")) return;
        ev.target.title = ev.target.value || "";
        ev.target.style.height = "auto";
        ev.target.style.height = `${Math.max(38, ev.target.scrollHeight)}px`;
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
          if (status === "adopt") previewSelectedKeys.add(key);
          else previewSelectedKeys.delete(key);
          updatePreviewSelectionUi();
          return;
        }
        if (ev.target.matches("[data-vtg-select-row]")) {
          const key = taskIdentity(previewItems[idx]);
          if (ev.target.checked && recordStatusOf(previewItems[idx]) === "adopt") {
            previewSelectedKeys.add(key);
          } else {
            previewSelectedKeys.delete(key);
          }
          updatePreviewSelectionUi();
        }
      });
      els.previewBody.addEventListener("click", (ev) => {
        if (ev.target.closest("button[data-vtg-remove-preview], input, select, textarea, a")) return;
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
    renderVersionDatesTable();
    renderSavedRecordsTable();
    bindEvents();
    try {
      await loadProjects();
      let projectId = restoreLastProject();
      if (!projectId) {
        try {
          const hint = await requestJson("/api/document-control/version-tasks/latest-preview");
          const hintId = String((hint && hint.lastRecordProjectId) || "").trim();
          if (hintId && projectsById.has(hintId)) {
            els.projectId.value = hintId;
            projectId = hintId;
          }
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
    } catch (err) {
      toast(err.message || "页面初始化失败", "danger");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
