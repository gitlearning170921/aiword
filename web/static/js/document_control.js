(function () {
    const PAGE_SIZE = 50;
    let schemes = [];
    let previewResult = null;
    const categoryPages = {};
    let ledgerLoading = false;
    const selectedDocIds = new Set();

    function getApp() {
        return window.App || null;
    }

    function notify(msg, variant) {
        const App = getApp();
        if (App && App.notify) App.notify(msg, variant || "info");
        else window.alert(msg);
    }

    function setImportButtonBusy(busy, busyText) {
        const label = document.getElementById("dcExcelImportBtn");
        const input = document.getElementById("dcExcelInput");
        const textEl = document.getElementById("dcExcelImportBtnText");
        if (!label) return;
        if (busy) {
            label.classList.add("disabled");
            label.setAttribute("aria-busy", "true");
            label.style.pointerEvents = "none";
            if (input) input.disabled = true;
            if (textEl) {
                if (textEl.dataset.origText == null) {
                    textEl.dataset.origText = textEl.textContent || "导入Excel";
                }
                textEl.innerHTML =
                    '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
                    (busyText || "处理中…");
            }
        } else {
            label.classList.remove("disabled");
            label.removeAttribute("aria-busy");
            label.style.pointerEvents = "";
            if (input) input.disabled = false;
            if (textEl && textEl.dataset.origText != null) {
                textEl.textContent = textEl.dataset.origText;
                delete textEl.dataset.origText;
            }
        }
    }

    function setButtonBusy(btn, busy, busyText) {
        if (!btn) return;
        if (btn.id === "dcExcelImportBtn") {
            setImportButtonBusy(busy, busyText);
            return;
        }
        if (busy) {
            if (btn.dataset.origHtml == null) btn.dataset.origHtml = btn.innerHTML;
            btn.disabled = true;
            btn.setAttribute("aria-busy", "true");
            const label = busyText || "处理中…";
            btn.innerHTML =
                '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
                label;
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
        setButtonBusy(btn, true, busyText);
        try {
            return await fn();
        } finally {
            setButtonBusy(btn, false);
        }
    }

    async function req(url, options) {
        const App = getApp();
        if (!App || !App.request) throw new Error("页面未就绪，请刷新重试");
        return App.request(url, options);
    }

    function esc(text) {
        return String(text == null ? "" : text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function getFilterParams() {
        const query = new URLSearchParams();
        const keyword = (document.getElementById("dcKeyword")?.value || "").trim();
        const sheetCategory = (document.getElementById("dcSheetCategory")?.value || "").trim();
        const projectCode = (document.getElementById("dcProjectCode")?.value || "").trim();
        const projectName = (document.getElementById("dcProjectName")?.value || "").trim();
        const registeredCountry = (document.getElementById("dcRegisteredCountry")?.value || "").trim();
        const status = (document.getElementById("dcStatus")?.value || "").trim();
        const registrationSubmitted = (document.getElementById("dcRegistrationSubmitted")?.value || "").trim();
        if (keyword) query.set("keyword", keyword);
        if (sheetCategory) query.set("sheetCategory", sheetCategory);
        if (projectCode) query.set("projectCode", projectCode);
        if (projectName) query.set("projectName", projectName);
        if (registeredCountry) query.set("registeredCountry", registeredCountry);
        if (status) query.set("status", status);
        if (registrationSubmitted) query.set("registrationSubmitted", registrationSubmitted);
        return query;
    }

    let sheetCategoryOptions = [];

    function updateBatchToolbar() {
        const bar = document.getElementById("dcBatchBar");
        const countEl = document.getElementById("dcBatchCount");
        const n = selectedDocIds.size;
        if (bar) bar.classList.toggle("d-none", n <= 0);
        if (countEl) countEl.textContent = String(n);
    }

    function clearDocSelection() {
        selectedDocIds.clear();
        document.querySelectorAll(".dc-doc-select:checked").forEach((el) => {
            el.checked = false;
        });
        document.querySelectorAll(".dc-cat-select-all:checked").forEach((el) => {
            el.checked = false;
        });
        updateBatchToolbar();
    }

    function syncCategorySelectAll(category) {
        const block = document.querySelector(`.dc-category-block[data-category="${CSS.escape(category)}"]`);
        if (!block) return;
        const boxes = block.querySelectorAll(".dc-doc-select");
        const allBox = block.querySelector(".dc-cat-select-all");
        if (!allBox || !boxes.length) return;
        const checked = Array.from(boxes).filter((x) => x.checked).length;
        allBox.checked = checked > 0 && checked === boxes.length;
        allBox.indeterminate = checked > 0 && checked < boxes.length;
    }

    function getSelectedDocIds() {
        return Array.from(selectedDocIds);
    }

    function renderScopeColumn(items, field, fallback) {
        const list = Array.isArray(items) ? items : [];
        const tokens = [];
        const seen = new Set();
        list.forEach((e) => {
            const token = String((e && e[field]) || "").trim();
            if (!token || seen.has(token)) return;
            seen.add(token);
            tokens.push(token);
        });
        if (tokens.length > 1) {
            return `<span class="dc-meta-multi">${esc(tokens.join(", "))}</span>`;
        }
        const single = tokens.length === 1 ? tokens[0] : "";
        const fb = String(fallback || "").trim();
        if (!single && fb) {
            const split = fb.split(/\s*[,，、]\s*|\s*\/\s*/).map((x) => x.trim()).filter(Boolean);
            if (split.length > 1) {
                return `<span class="dc-meta-multi">${esc(split.join(", "))}</span>`;
            }
        }
        return esc(single || fb || "-");
    }

    function renderDocRows(rows) {
        const list = rows || [];
        if (!list.length) {
            return '<tr><td colspan="10" class="text-muted p-3">暂无匹配记录</td></tr>';
        }
        return list
            .map(
                (x) => {
                    const checked = selectedDocIds.has(x.id) ? "checked" : "";
                    return `<tr data-doc-id="${esc(x.id)}">
                    <td class="text-center" style="width:2rem">
                        <input type="checkbox" class="form-check-input dc-doc-select m-0" data-doc-id="${esc(x.id)}" ${checked} aria-label="选择记录">
                    </td>
                    <td>${esc(x.documentNumber || "-")}</td>
                    <td>${esc(x.title || "-")}</td>
                    <td>${esc(x.titleEn || "-")}</td>
                    <td>${esc(x.version || "-")}</td>
                    <td>${renderScopeColumn(x.registrationProjects, "projectName", x.projectName)}</td>
                    <td>${renderScopeColumn(x.registrationProjects, "registeredCountry", x.registeredCountry)}</td>
                    <td>${esc(x.statusLabel || "-")}</td>
                    <td>${x.registrationSubmitted ? "已递交" : "-"}</td>
                    <td class="text-nowrap">
                        <button type="button" class="btn btn-link btn-sm p-0 me-2 dc-edit-doc"
                            data-doc-id="${esc(x.id)}"
                            data-document-number="${esc(x.documentNumber || "")}"
                            data-title="${esc(x.title || "")}"
                            data-title-en="${esc(x.titleEn || "")}"
                            data-version="${esc(x.version || "")}"
                            data-project-code="${esc(x.projectCode || "")}"
                            data-project-name="${esc(x.projectName || "")}"
                            data-registered-country="${esc(x.registeredCountry || "")}"
                            data-sheet-category="${esc(x.sheetCategory || "")}"
                            data-status="${esc(x.status || "controlled")}"
                            data-registration-submitted="${x.registrationSubmitted ? "1" : "0"}">编辑</button>
                        <button type="button" class="btn btn-link btn-sm p-0 text-danger dc-delete-doc" data-doc-id="${esc(x.id)}">删除</button>
                    </td>
                </tr>`;
                }
            )
            .join("");
    }

    function renderCategorySection(category, data) {
        const total = Number(data.total) || 0;
        if (!total) return "";
        const page = Number(data.page) || 1;
        const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
        const pageInfo = total ? `第 ${page} / ${totalPages} 页，共 ${total} 条` : "共 0 条";
        const prevDisabled = page <= 1 ? "disabled" : "";
        const nextDisabled = page >= totalPages ? "disabled" : "";
        return `<div class="card mb-3 dc-category-block" data-category="${esc(category)}">
            <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2 py-2">
                <div class="fw-semibold">${esc(category)} <span class="badge text-bg-light border">${total}</span></div>
                <div class="d-flex align-items-center gap-2">
                    <span class="small text-muted">${pageInfo}</span>
                    <div class="btn-group btn-group-sm">
                        <button type="button" class="btn btn-outline-secondary dc-cat-prev" data-category="${esc(category)}" ${prevDisabled}>上一页</button>
                        <button type="button" class="btn btn-outline-secondary dc-cat-next" data-category="${esc(category)}" ${nextDisabled}>下一页</button>
                    </div>
                </div>
            </div>
            <div class="card-body p-0 dc-category-scroll">
                <table class="table table-sm table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th class="text-center" style="width:2rem">
                                <input type="checkbox" class="form-check-input dc-cat-select-all m-0" data-category="${esc(category)}" aria-label="全选本分类">
                            </th>
                            <th>文件编号</th>
                            <th>文件名称</th>
                            <th>英文名</th>
                            <th>版本</th>
                            <th>所属项目</th>
                            <th>注册国家</th>
                            <th>状态</th>
                            <th>注册递交</th>
                            <th style="width:5.5rem">操作</th>
                        </tr>
                    </thead>
                    <tbody>${renderDocRows(data.items)}</tbody>
                </table>
            </div>
        </div>`;
    }

    async function loadCategorySection(category) {
        const query = getFilterParams();
        query.set("sheetCategory", category);
        query.set("page", String(categoryPages[category] || 1));
        query.set("pageSize", String(PAGE_SIZE));
        return req(`/api/document-control/documents?${query.toString()}`);
    }

    async function loadGroupedLedger(opts) {
        opts = opts || {};
        if (ledgerLoading) return;
        ledgerLoading = true;
        const wrap = document.getElementById("dcCategorySections");
        const summary = document.getElementById("dcListSummary");
        const searchBtn = document.getElementById("dcSearchBtn");
        const resetBtn = document.getElementById("dcResetBtn");
        const sheetSel = document.getElementById("dcSheetCategory");
        if (!wrap) {
            ledgerLoading = false;
            return;
        }
        setButtonBusy(searchBtn, opts.busySearch, "查询中…");
        if (opts.busyReset) setButtonBusy(resetBtn, true, "重置中…");
        if (sheetSel) sheetSel.disabled = true;
        wrap.innerHTML =
            '<div class="text-muted p-4 text-center"><span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>加载台账中…</div>';
        try {
            const catQuery = getFilterParams();
            const catRes = await req(`/api/document-control/categories?${catQuery.toString()}`);
            const counts = catRes.counts || {};
            const categories = (catRes.items || []).filter(
                (name) => (Number(counts[name]) || 0) > 0
            );
            const allItems = catRes.allItems || categories;
            sheetCategoryOptions = allItems;
            updateDocSheetCategoryDatalist();
            if (sheetSel) {
                const current = sheetSel.value;
                sheetSel.innerHTML =
                    '<option value="">全部分类</option>' +
                    allItems.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
                if (current && allItems.includes(current)) sheetSel.value = current;
            }
            if (!categories.length) {
                wrap.innerHTML =
                    '<div class="alert alert-light border mb-0">暂无匹配记录，可调整筛选条件或先导入 Excel。</div>';
                if (summary) summary.textContent = "";
                return;
            }
            categories.forEach((name) => {
                if (!categoryPages[name]) categoryPages[name] = 1;
            });
            const blocks = await Promise.all(
                categories.map(async (name) => {
                    const data = await loadCategorySection(name);
                    if (!(Number(data.total) || 0)) return "";
                    return renderCategorySection(name, data);
                })
            );
            wrap.innerHTML = blocks.filter(Boolean).join("") ||
                '<div class="alert alert-light border mb-0">暂无匹配记录，可调整筛选条件或先导入 Excel。</div>';
            const totalAll = categories.reduce((sum, name) => sum + (Number(counts[name]) || 0), 0);
            if (summary) {
                summary.textContent = `显示 ${categories.length} 个分类，合计 ${totalAll} 条记录（每分类每页 ${PAGE_SIZE} 条，区域内可滚动查看）`;
            }
            bindCategoryPagination(wrap);
            wrap.querySelectorAll(".dc-category-block").forEach((block) => {
                const cat = block.getAttribute("data-category") || "";
                if (cat) syncCategorySelectAll(cat);
            });
            updateBatchToolbar();
        } finally {
            ledgerLoading = false;
            setButtonBusy(searchBtn, false);
            setButtonBusy(resetBtn, false);
            if (sheetSel) sheetSel.disabled = false;
        }
    }

    function bindCategoryPagination(root) {
        const scope = root || document;
        scope.querySelectorAll(".dc-cat-prev").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const cat = btn.getAttribute("data-category") || "";
                const page = categoryPages[cat] || 1;
                if (page <= 1) return;
                categoryPages[cat] = page - 1;
                await refreshCategoryBlock(cat, btn);
            });
        });
        scope.querySelectorAll(".dc-cat-next").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const cat = btn.getAttribute("data-category") || "";
                const page = categoryPages[cat] || 1;
                categoryPages[cat] = page + 1;
                await refreshCategoryBlock(cat, btn);
            });
        });
    }

    async function refreshCategoryBlock(category, triggerBtn) {
        const block = document.querySelector(`.dc-category-block[data-category="${CSS.escape(category)}"]`);
        if (!block) {
            await loadGroupedLedger();
            return;
        }
        const prevBtn = block.querySelector(".dc-cat-prev");
        const nextBtn = block.querySelector(".dc-cat-next");
        if (triggerBtn) setButtonBusy(triggerBtn, true, "加载中…");
        else {
            setButtonBusy(prevBtn, true, "…");
            setButtonBusy(nextBtn, true, "…");
        }
        try {
            const data = await loadCategorySection(category);
            if (!(Number(data.total) || 0)) {
                block.remove();
                return;
            }
            const replacement = document.createElement("div");
            replacement.innerHTML = renderCategorySection(category, data);
            const newBlock = replacement.firstElementChild;
            if (newBlock) {
                block.replaceWith(newBlock);
                bindCategoryPagination(newBlock);
            }
        } finally {
            if (triggerBtn) setButtonBusy(triggerBtn, false);
            else {
                setButtonBusy(prevBtn, false);
                setButtonBusy(nextBtn, false);
            }
        }
    }

    function resetCategoryPages() {
        Object.keys(categoryPages).forEach((k) => delete categoryPages[k]);
    }

    function updateDocSheetCategoryDatalist() {
        const list = document.getElementById("dcDocSheetCategoryList");
        if (!list) return;
        list.innerHTML = sheetCategoryOptions.map((x) => `<option value="${esc(x)}"></option>`).join("");
    }

    function readDocForm() {
        return {
            documentNumber: (document.getElementById("dcDocNumber")?.value || "").trim(),
            title: (document.getElementById("dcDocTitle")?.value || "").trim(),
            titleEn: (document.getElementById("dcDocTitleEn")?.value || "").trim(),
            version: (document.getElementById("dcDocVersion")?.value || "").trim(),
            projectCode: (document.getElementById("dcDocProjectCode")?.value || "").trim(),
            projectName: (document.getElementById("dcDocProjectName")?.value || "").trim(),
            registeredCountry: (document.getElementById("dcDocRegisteredCountry")?.value || "").trim(),
            sheetCategory: (document.getElementById("dcDocSheetCategory")?.value || "").trim(),
            status: (document.getElementById("dcDocStatus")?.value || "controlled").trim(),
            registrationSubmitted:
                (document.getElementById("dcDocRegistrationSubmitted")?.value || "0") === "1",
        };
    }

    function fillDocForm(item) {
        const data = item || {};
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.value = val == null ? "" : String(val);
        };
        set("dcDocId", data.id || "");
        set("dcDocNumber", data.documentNumber || "");
        set("dcDocTitle", data.title || "");
        set("dcDocTitleEn", data.titleEn || "");
        set("dcDocVersion", data.version || "");
        set("dcDocProjectCode", data.projectCode || "");
        set("dcDocProjectName", data.projectName || "");
        set("dcDocRegisteredCountry", data.registeredCountry || "");
        set("dcDocSheetCategory", data.sheetCategory || "");
        set("dcDocStatus", data.status || "controlled");
        set("dcDocRegistrationSubmitted", data.registrationSubmitted ? "1" : "0");
    }

    function openDocModal(item) {
        const modalEl = document.getElementById("dcDocModal");
        if (!modalEl) return;
        const isEdit = !!(item && item.id);
        fillDocForm(
            item || {
                status: "controlled",
                registrationSubmitted: false,
            }
        );
        const titleEl = document.getElementById("dcDocModalTitle");
        if (titleEl) titleEl.textContent = isEdit ? "编辑台账" : "新增台账";
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    async function saveDocModal() {
        const docId = (document.getElementById("dcDocId")?.value || "").trim();
        const payload = readDocForm();
        if (!payload.documentNumber || !payload.title) {
            notify("请填写文件编号与文件名称", "warning");
            return;
        }
        const btn = document.getElementById("dcDocSaveBtn");
        await withButtonBusy(btn, "保存中…", async () => {
            if (docId) {
                await req(`/api/document-control/documents/${encodeURIComponent(docId)}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                notify("已保存", "success");
            } else {
                await req("/api/document-control/documents", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                notify("已新增", "success");
            }
            const modalEl = document.getElementById("dcDocModal");
            if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
            resetCategoryPages();
            await loadGroupedLedger();
        });
    }

    async function deleteDocument(docId) {
        if (!docId) return;
        if (!window.confirm("确定删除该台账记录？")) return;
        await req(`/api/document-control/documents/${encodeURIComponent(docId)}`, {
            method: "DELETE",
        });
        selectedDocIds.delete(docId);
        notify("已删除", "success");
        resetCategoryPages();
        await loadGroupedLedger();
    }

    function bindBatchFieldToggle(chkId, fieldId) {
        const chk = document.getElementById(chkId);
        const field = document.getElementById(fieldId);
        if (!chk || !field) return;
        chk.addEventListener("change", () => {
            field.disabled = !chk.checked;
        });
    }

    function openBatchEditModal() {
        const ids = getSelectedDocIds();
        if (!ids.length) {
            notify("请先勾选要编辑的记录", "warning");
            return;
        }
        const countEl = document.getElementById("dcBatchModalCount");
        if (countEl) countEl.textContent = String(ids.length);
        ["dcBatchChkStatus", "dcBatchChkRegistration", "dcBatchChkProjectName", "dcBatchChkRegisteredCountry"].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.checked = false;
        });
        ["dcBatchStatus", "dcBatchRegistration", "dcBatchProjectName", "dcBatchRegisteredCountry"].forEach((id) => {
            const el = document.getElementById(id);
            if (el) {
                el.disabled = true;
                if (el.tagName === "SELECT" && id === "dcBatchStatus") el.value = "voided";
            }
        });
        const modalEl = document.getElementById("dcBatchModal");
        if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }

    async function saveBatchEdit() {
        const ids = getSelectedDocIds();
        if (!ids.length) {
            notify("请先勾选要编辑的记录", "warning");
            return;
        }
        const payload = { ids };
        if (document.getElementById("dcBatchChkStatus")?.checked) {
            payload.status = (document.getElementById("dcBatchStatus")?.value || "").trim();
        }
        if (document.getElementById("dcBatchChkRegistration")?.checked) {
            payload.registrationSubmitted =
                (document.getElementById("dcBatchRegistration")?.value || "") === "1";
        }
        if (document.getElementById("dcBatchChkProjectName")?.checked) {
            payload.projectName = (document.getElementById("dcBatchProjectName")?.value || "").trim();
        }
        if (document.getElementById("dcBatchChkRegisteredCountry")?.checked) {
            payload.registeredCountry = (document.getElementById("dcBatchRegisteredCountry")?.value || "").trim();
        }
        if (
            !("status" in payload) &&
            !("registrationSubmitted" in payload) &&
            !("projectName" in payload) &&
            !("registeredCountry" in payload)
        ) {
            notify("请至少勾选一项要修改的内容", "warning");
            return;
        }
        const btn = document.getElementById("dcBatchSaveBtn");
        await withButtonBusy(btn, "保存中…", async () => {
            const res = await req("/api/document-control/documents/batch-update", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const failed = (res.failed || []).length;
            notify(res.message || (failed ? "部分更新失败" : "已批量更新"), failed ? "warning" : "success");
            const modalEl = document.getElementById("dcBatchModal");
            if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
            clearDocSelection();
            resetCategoryPages();
            await loadGroupedLedger();
        });
    }

    async function batchDeleteDocuments() {
        const ids = getSelectedDocIds();
        if (!ids.length) {
            notify("请先勾选要删除的记录", "warning");
            return;
        }
        if (!window.confirm(`确定删除已选的 ${ids.length} 条台账记录？此操作不可恢复。`)) return;
        const btn = document.getElementById("dcBatchDeleteBtn");
        await withButtonBusy(btn, "删除中…", async () => {
            const res = await req("/api/document-control/documents/batch-delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ids }),
            });
            notify(res.message || "已批量删除", "success");
            clearDocSelection();
            resetCategoryPages();
            await loadGroupedLedger();
        });
    }

    function bindBatchActions() {
        bindBatchFieldToggle("dcBatchChkStatus", "dcBatchStatus");
        bindBatchFieldToggle("dcBatchChkRegistration", "dcBatchRegistration");
        bindBatchFieldToggle("dcBatchChkProjectName", "dcBatchProjectName");
        bindBatchFieldToggle("dcBatchChkRegisteredCountry", "dcBatchRegisteredCountry");
        document.getElementById("dcBatchEditBtn")?.addEventListener("click", openBatchEditModal);
        document.getElementById("dcBatchSaveBtn")?.addEventListener("click", saveBatchEdit);
        document.getElementById("dcBatchDeleteBtn")?.addEventListener("click", batchDeleteDocuments);
        document.getElementById("dcBatchClearBtn")?.addEventListener("click", clearDocSelection);
        document.getElementById("dcCategorySections")?.addEventListener("change", (e) => {
            const rowBox = e.target.closest(".dc-doc-select");
            if (rowBox) {
                const docId = rowBox.getAttribute("data-doc-id") || "";
                if (rowBox.checked) selectedDocIds.add(docId);
                else selectedDocIds.delete(docId);
                const block = rowBox.closest(".dc-category-block");
                const cat = block?.getAttribute("data-category") || "";
                if (cat) syncCategorySelectAll(cat);
                updateBatchToolbar();
                return;
            }
            const allBox = e.target.closest(".dc-cat-select-all");
            if (allBox) {
                const block = allBox.closest(".dc-category-block");
                block?.querySelectorAll(".dc-doc-select").forEach((box) => {
                    const docId = box.getAttribute("data-doc-id") || "";
                    box.checked = allBox.checked;
                    if (allBox.checked) selectedDocIds.add(docId);
                    else selectedDocIds.delete(docId);
                });
                allBox.indeterminate = false;
                updateBatchToolbar();
            }
        });
    }

    function bindDocModal() {
        document.getElementById("dcAddDocBtn")?.addEventListener("click", () => openDocModal(null));
        document.getElementById("dcDocSaveBtn")?.addEventListener("click", saveDocModal);
        document.getElementById("dcCategorySections")?.addEventListener("click", async (e) => {
            const editBtn = e.target.closest(".dc-edit-doc");
            if (editBtn) {
                openDocModal({
                    id: editBtn.getAttribute("data-doc-id") || "",
                    documentNumber: editBtn.getAttribute("data-document-number") || "",
                    title: editBtn.getAttribute("data-title") || "",
                    titleEn: editBtn.getAttribute("data-title-en") || "",
                    version: editBtn.getAttribute("data-version") || "",
                    projectCode: editBtn.getAttribute("data-project-code") || "",
                    projectName: editBtn.getAttribute("data-project-name") || "",
                    registeredCountry: editBtn.getAttribute("data-registered-country") || "",
                    sheetCategory: editBtn.getAttribute("data-sheet-category") || "",
                    status: editBtn.getAttribute("data-status") || "controlled",
                    registrationSubmitted: editBtn.getAttribute("data-registration-submitted") === "1",
                });
                return;
            }
            const delBtn = e.target.closest(".dc-delete-doc");
            if (delBtn) {
                await deleteDocument(delBtn.getAttribute("data-doc-id") || "");
            }
        });
    }

    function renderSchemes(rows) {
        const body = document.getElementById("dcSchemesBody");
        const sel = document.getElementById("dcIssueScheme");
        if (!body || !sel) return;
        schemes = rows || [];
        if (!schemes.length) {
            body.innerHTML = '<tr><td colspan="6" class="text-muted p-3">暂无规则</td></tr>';
            sel.innerHTML = '<option value="">请先新增规则</option>';
            return;
        }
        body.innerHTML = schemes
            .map(
                (x) => `<tr>
                    <td>${esc(x.name || "-")}</td>
                    <td>${esc(x.docTypeCode || "-")}</td>
                    <td>${esc(x.renderTemplate || "-")}</td>
                    <td>${esc(x.prefixSource || "-")}</td>
                    <td>${esc(x.seqStart || "-")}</td>
                    <td>${esc(x.seqPad || "-")}</td>
                </tr>`
            )
            .join("");
        sel.innerHTML = schemes
            .map((x) => `<option value="${esc(x.id)}">${esc(x.name)} (${esc(x.docTypeCode || "-")})</option>`)
            .join("");
    }

    async function loadSchemes() {
        const res = await req("/api/document-control/schemes");
        renderSchemes(res.items || []);
    }

    function bindIssueModal() {
        const modalEl = document.getElementById("dcIssueModal");
        if (!modalEl) return;
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        document.getElementById("dcOpenIssueModalBtn")?.addEventListener("click", () => {
            previewResult = null;
            const resultEl = document.getElementById("dcPreviewResult");
            if (resultEl) resultEl.textContent = "尚未预览";
            modal.show();
        });
        document.getElementById("dcPreviewBtn")?.addEventListener("click", async () => {
            const btn = document.getElementById("dcPreviewBtn");
            await withButtonBusy(btn, "预览中…", async () => {
                const schemeId = (document.getElementById("dcIssueScheme")?.value || "").trim();
                const projectCode = (document.getElementById("dcIssueProjectCode")?.value || "").trim();
                const res = await req("/api/document-control/allocate/preview", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ schemeId, projectCode }),
                });
                previewResult = res.item || null;
                const resultEl = document.getElementById("dcPreviewResult");
                if (resultEl) {
                    resultEl.textContent = previewResult
                        ? `建议编号：${previewResult.document_number}`
                        : "未获取到建议编号";
                }
            });
        });
        document.getElementById("dcReserveBtn")?.addEventListener("click", async () => {
            const schemeId = (document.getElementById("dcIssueScheme")?.value || "").trim();
            const title = (document.getElementById("dcIssueTitle")?.value || "").trim();
            const projectCode = (document.getElementById("dcIssueProjectCode")?.value || "").trim();
            if (!schemeId || !title) {
                notify("请先选择规则并填写文件名称", "warning");
                return;
            }
            const btn = document.getElementById("dcReserveBtn");
            await withButtonBusy(btn, "提交中…", async () => {
                await req("/api/document-control/allocate/reserve", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ schemeId, title, projectCode }),
                });
                notify("编号预留成功", "success");
                modal.hide();
                resetCategoryPages();
                await loadGroupedLedger();
            });
        });
    }

    function bindActions() {
        document.getElementById("dcSearchBtn")?.addEventListener("click", () => {
            resetCategoryPages();
            loadGroupedLedger({ busySearch: true });
        });
        document.getElementById("dcResetBtn")?.addEventListener("click", () => {
            ["dcKeyword", "dcSheetCategory", "dcProjectCode", "dcProjectName", "dcRegisteredCountry"].forEach((id) => {
                const el = document.getElementById(id);
                if (el) el.value = "";
            });
            const statusEl = document.getElementById("dcStatus");
            const regEl = document.getElementById("dcRegistrationSubmitted");
            if (statusEl) statusEl.value = "";
            if (regEl) regEl.value = "";
            clearDocSelection();
            resetCategoryPages();
            loadGroupedLedger({ busyReset: true });
        });
        document.getElementById("dcSheetCategory")?.addEventListener("change", () => {
            resetCategoryPages();
            loadGroupedLedger();
        });
        document.getElementById("dcSyncRuleBtn")?.addEventListener("click", async () => {
            const btn = document.getElementById("dcSyncRuleBtn");
            await withButtonBusy(btn, "同步中…", async () => {
                const res = await req("/api/document-control/schemes/sync-from-kb", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ query: "文件控制程序 编号规则" }),
                });
                notify(res.message || "已拉取候选规则，请手工新增需要的规则", "info");
            });
        });
        document.getElementById("dcAddSchemeBtn")?.addEventListener("click", async () => {
            const name = window.prompt("规则名称（例如：质量体系 SOP）");
            if (!name) return;
            const docTypeCode = window.prompt("类型码（例如：SOP）");
            if (!docTypeCode) return;
            const btn = document.getElementById("dcAddSchemeBtn");
            await withButtonBusy(btn, "保存中…", async () => {
                await req("/api/document-control/schemes", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        name: name.trim(),
                        docTypeCode: docTypeCode.trim().toUpperCase(),
                        renderTemplate: "{prefix}-{type}-{seq:03d}",
                        prefixSource: "from_project_code",
                        seqStart: 1,
                        seqPad: 3,
                    }),
                });
                notify("规则已新增", "success");
                await loadSchemes();
            });
        });
        document.getElementById("dcExcelInput")?.addEventListener("change", async (e) => {
            const input = e.target;
            const file = input.files && input.files[0];
            if (!file) return;
            const fd = new FormData();
            fd.append("file", file);
            let preview;
            try {
                setImportButtonBusy(true, "解析中…");
                preview = await req("/api/document-control/import/excel", {
                    method: "POST",
                    body: fd,
                });
            } catch (err) {
                notify(err.message || "Excel 解析失败", "danger");
                input.value = "";
                return;
            } finally {
                setImportButtonBusy(false);
            }
            const rows = preview.preview || [];
            const summary = preview.summary || {};
            if (!rows.length) {
                notify("未识别到可导入记录，请检查表头与数据行", "warning");
                input.value = "";
                return;
            }
            const importable = summary.new || rows.filter((x) => x.status === "new").length;
            const toUpdate = summary.update || rows.filter((x) => x.status === "update").length;
            const regUpdate = summary.registrationUpdate || rows.filter((x) => x.status === "registration_update").length;
            const blocked =
                rows.length - importable - toUpdate - regUpdate;
            let msg = `共 ${rows.length} 条：新增 ${importable} 条`;
            if (toUpdate) msg += `，增量更新 ${toUpdate} 条`;
            if (regUpdate) msg += `，注册关联 ${regUpdate} 条`;
            if (summary.sheetOrder && summary.sheetOrder.length) {
                msg += `（Sheet：${summary.sheetOrder.join("、")}）`;
            }
            if (blocked) msg += `，跳过 ${blocked} 条（作废/非受控/文件内重复等）`;
            if (!importable && !toUpdate && !regUpdate) {
                notify(msg + "，无可处理记录", "warning");
                input.value = "";
                return;
            }
            if (!window.confirm(msg + "，是否确认导入？")) {
                input.value = "";
                return;
            }
            const confirmFd = new FormData();
            confirmFd.append("file", file);
            confirmFd.append("confirm", "1");
            let result;
            try {
                setImportButtonBusy(true, "导入中…");
                result = await req("/api/document-control/import/excel", {
                    method: "POST",
                    body: confirmFd,
                });
            } catch (err) {
                notify(err.message || "导入失败", "danger");
                input.value = "";
                return;
            } finally {
                setImportButtonBusy(false);
                input.value = "";
            }
            const skipped = (result.skipped || []).length;
            const regDone = result.registrationUpdated || 0;
            const updatedDone = result.updated || 0;
            let doneMsg = `导入完成：新增 ${result.imported || 0} 条`;
            if (updatedDone) doneMsg += `，更新 ${updatedDone} 条`;
            if (regDone) doneMsg += `，注册关联 ${regDone} 条`;
            if (skipped) doneMsg += `，跳过 ${skipped} 条`;
            notify(doneMsg, skipped ? "warning" : "success");
            resetCategoryPages();
            await loadGroupedLedger();
            if (result.batchId) {
                const goLogs = window.confirm("是否查看本次导入操作日志？");
                if (goLogs) {
                    window.location.href = `/document-control/import-logs?batchId=${encodeURIComponent(result.batchId)}`;
                }
            }
        });
    }

    async function boot() {
        try {
            const sp = new URLSearchParams(window.location.search || "");
            const qProjectCode = (sp.get("projectCode") || "").trim();
            const qKeyword = (sp.get("keyword") || "").trim();
            const qCategory = (sp.get("sheetCategory") || "").trim();
            if (qProjectCode) {
                const el = document.getElementById("dcProjectCode");
                if (el) el.value = qProjectCode;
            }
            if (qKeyword) {
                const el = document.getElementById("dcKeyword");
                if (el) el.value = qKeyword;
            }
            if (qCategory) {
                const el = document.getElementById("dcSheetCategory");
                if (el) el.value = qCategory;
            }
            await loadSchemes();
            bindActions();
            bindDocModal();
            bindBatchActions();
            bindIssueModal();
            await loadGroupedLedger();
        } catch (e) {
            notify(e.message || "文控中心加载失败", "danger");
        }
    }

    if (typeof registerPageInit === "function") registerPageInit(boot);
    else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
})();
