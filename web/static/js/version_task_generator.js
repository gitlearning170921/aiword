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
    previewBody: byId("vtgPreviewBody"),
    previewCount: byId("vtgPreviewCount"),
    applyBtn: byId("vtgApplyBtn"),
    savePreviewEditsBtn: byId("vtgSavePreviewEditsBtn"),
    projectId: byId("vtgProjectId"),
    applyMsg: byId("vtgApplyMsg"),
  };

  const PRODUCT_NAME_LS_PREFIX = "vtg.productName.";

  let currentJobId = "";
  let originalPreviewItems = [];
  let previewItems = [];
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

  function loadSavedRecordsToChain() {
    syncSavedRecordsFromDom();
    const versions = savedRecords
      .map((r) => String(r.version || "").trim())
      .filter(Boolean)
      .sort(compareVersion);
    if (!versions.length) {
      toast("没有可加载的版本记录", "warning");
      return;
    }
    els.fromVersion.value = versions[0];
    els.toVersion.value = versions[versions.length - 1];
    els.intermediate.value = versions.length > 2 ? versions.slice(1, -1).join(", ") : "";
    applySavedRecordsToChainMaps(savedRecords);
    const withProduct = savedRecords.find((r) => String(r.productName || "").trim());
    if (withProduct) els.productName.value = withProduct.productName;
    renderVersionDatesTable();
    toast(`已加载 ${versions.length} 个版本到链路表单`, "success");
  }

  function productNameStorageKey(projectId) {
    return `${PRODUCT_NAME_LS_PREFIX}${projectId}`;
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
    });
  }

  function renderPreviewTable(items) {
    previewItems = Array.isArray(items) ? items.map((x) => ({ ...x })) : [];
    if (els.previewCount) {
      els.previewCount.textContent = `${previewItems.length} 条`;
    }
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.disabled = !currentJobId || !previewItems.length;
    }
    if (!els.previewBody) return;
    if (!previewItems.length) {
      els.previewBody.innerHTML =
        '<tr><td colspan="11" class="text-muted small text-center py-3">预览后将在此显示任务清单</td></tr>';
      return;
    }
    const rows = previewItems
      .map((item, idx) => {
        const triggers = formatTriggerBits(item.triggeredBy);
        const targetVersion = item.targetVersion || item.fileVersion || "";
        return `<tr data-vtg-preview-idx="${idx}">
          <td class="text-muted small">${idx + 1}</td>
          <td><input class="form-control form-control-sm" data-vtg-field="fileName" value="${escapeHtml(item.fileName || "")}"></td>
          <td><input class="form-control form-control-sm" data-vtg-field="taskType" value="${escapeHtml(item.taskType || "")}"></td>
          <td><input class="form-control form-control-sm font-monospace" data-vtg-field="targetVersion" value="${escapeHtml(targetVersion)}"></td>
          <td><input class="form-control form-control-sm" data-vtg-field="author" value="${escapeHtml(item.author || "")}"></td>
          <td><input type="date" class="form-control form-control-sm" data-vtg-field="dueDate" value="${escapeHtml(item.dueDate || "")}"></td>
          <td><input type="date" class="form-control form-control-sm" data-vtg-field="documentDisplayDate" value="${escapeHtml(item.documentDisplayDate || "")}"></td>
          <td><input class="form-control form-control-sm" data-vtg-field="belongingModule" value="${escapeHtml(item.belongingModule || "")}"></td>
          <td><input class="form-control form-control-sm" data-vtg-field="notes" value="${escapeHtml(item.notes || "")}"></td>
          <td class="small text-muted" title="版本号格式 X.Y.Z.B，按最高变化位：X&gt;Y&gt;Z&gt;B">${triggers}</td>
          <td><button type="button" class="btn btn-outline-danger btn-sm py-0 px-1" data-vtg-remove-preview="${idx}" title="删除">×</button></td>
        </tr>`;
      })
      .join("");
    els.previewBody.innerHTML = rows;
    Array.from(els.previewBody.querySelectorAll("button[data-vtg-remove-preview]")).forEach((btn) => {
      btn.addEventListener("click", () => {
        syncPreviewItemsFromDom();
        const idx = Number(btn.getAttribute("data-vtg-remove-preview"));
        if (Number.isNaN(idx)) return;
        previewItems.splice(idx, 1);
        renderPreviewTable(previewItems);
      });
    });
  }

  function getPreviewItems() {
    syncPreviewItemsFromDom();
    return previewItems.map((x) => ({ ...x }));
  }

  function taskIdentity(item) {
    const fileName = String(item.fileName || "").trim().toLowerCase();
    const taskType = String(item.taskType || "").trim().toLowerCase();
    const fileVersion = String(item.fileVersion || item.targetVersion || "").trim().toLowerCase();
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
      const originStr = JSON.stringify(origin);
      const editedStr = JSON.stringify(item);
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
    syncChainVersionsIntoSavedRecords();
    if (!savedRecords.length) {
      toast("请先填写版本号，或在下方表格新增版本后再保存", "warning");
      return;
    }
    renderSavedRecordsTable();
    await saveBatchSavedRecords();
  }

  function buildPreviewMetaText(data, prefix) {
    const dateSummary = Object.entries(data.versionReleaseDates || {})
      .map(([v, d]) => `${v}:${d}`)
      .join("；");
    const updatedAt = data.updatedAt
      ? String(data.updatedAt).replace("T", " ").slice(0, 19)
      : "";
    const branchSummary = Array.isArray(data.processBranches)
      ? data.processBranches
          .map((row) => `${row.version}:${row.label || row.branch || ""}`)
          .join("；")
      : "";
    return [
      prefix || "预览",
      updatedAt ? `保存时间：${updatedAt}` : "",
      `规则依据：${data.ruleSource || data.ruleBasis || "-"}`,
      `版本链路：${(data.versionChain || []).join(" -> ") || "-"}`,
      `各版本发布时间：${dateSummary || "-"}`,
      `触发位：${(data.dominantChanges || []).join(", ") || "无"}`,
      branchSummary ? `章节/流程：${branchSummary}` : "",
      `说明：${data.note || "-"}`,
      `反馈命中：${data.feedbackHitCount || 0}`,
    ]
      .filter(Boolean)
      .join(" | ");
  }

  function applyPreviewPayload(data, options) {
    const opts = options || {};
    currentJobId = data.jobId || "";
    originalPreviewItems = Array.isArray(data.items) ? JSON.parse(JSON.stringify(data.items)) : [];
    renderPreviewTable(originalPreviewItems);
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
    if (els.previewMeta) {
      els.previewMeta.textContent = buildPreviewMetaText(data, opts.metaPrefix || "预览");
    }
    if (els.savePreviewEditsBtn) {
      els.savePreviewEditsBtn.disabled = !currentJobId || !previewItems.length;
    }
  }

  function clearPreviewPanel(message) {
    currentJobId = "";
    originalPreviewItems = [];
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
      els.previewMeta.textContent =
        `已保存预览修改${stamp ? `（${stamp}）` : ""}` +
        (data.feedbackSaved
          ? ` | 反馈 ${data.feedbackSaved} 条将在下次「生成预览」时生效`
          : " | 无相对上次原表的字段差异");
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
    const { out } = collectVersionReleaseDates();
    const saved = await saveFeedbackIfNeeded(items);
    const data = await requestJson("/api/document-control/version-tasks/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceJobId: currentJobId || null,
        projectId,
        items,
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
    await loadSavedRecords();
    const projectId = String(els.projectId.value || "").trim();
    if (!projectId) {
      clearPreviewPanel("请选择项目后查看该项目上次预览，或直接生成新预览。");
      return;
    }
    await loadLatestPreview({ projectId, clearIfEmpty: true });
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
      const latest = await loadLatestPreview({ clearIfEmpty: false });
      if (latest && latest.projectId) {
        if (String(els.projectId.value || "").trim() !== String(latest.projectId)) {
          els.projectId.value = latest.projectId;
        }
        await loadSavedRecords();
      } else if (!latest) {
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
