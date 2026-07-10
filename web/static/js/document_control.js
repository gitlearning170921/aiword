(function () {
    const PAGE_SIZE = 50;
    let schemes = [];
    let issueCategories = [];
    let page1Projects = [];
    let previewResult = null;
    let issueDuplicateState = null;
    let issueResolvedTitleEn = null;
    let issueForceNew = false;
    let issuePreviewSeq = 0;
    let issuePreviewTitle = null;
    let issueBatchItems = [];
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

    async function reqJson(url, options) {
        const root = (window.__SCRIPT_ROOT__ != null ? String(window.__SCRIPT_ROOT__) : "").replace(/\/+$/, "");
        let fullUrl = url;
        if (root && typeof url === "string" && url.startsWith("/") && !url.startsWith(root + "/")) {
            fullUrl = root + url;
        }
        const response = await fetch(fullUrl, { credentials: "include", ...(options || {}) });
        const text = await response.text();
        let data = {};
        if (text) {
            try {
                data = JSON.parse(text);
            } catch (_) {
                data = { message: text.slice(0, 200) };
            }
        }
        if (!response.ok) {
            const err = new Error(data.message || `请求失败 (${response.status})`);
            err.status = response.status;
            err.data = data;
            throw err;
        }
        return data;
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
                        <button type="button" class="btn btn-link btn-sm p-0 me-2 dc-copy-doc"
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
                            data-registration-submitted="${x.registrationSubmitted ? "1" : "0"}">复制</button>
                        <button type="button" class="btn btn-link btn-sm p-0 text-danger dc-delete-doc" data-doc-id="${esc(x.id)}">删除</button>
                    </td>
                </tr>`;
                }
            )
            .join("");
    }

    function renderCategoryShell(category, count) {
        return `<div class="card mb-3 dc-category-block dc-category-collapsed" data-category="${esc(category)}" data-loaded="0">
            <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2 py-2 dc-category-toggle" role="button" tabindex="0" aria-expanded="false">
                <div class="fw-semibold">
                    <span class="text-muted me-1 dc-category-chevron" aria-hidden="true">▸</span>
                    ${esc(category)}
                    <span class="badge text-bg-light border">${Number(count) || 0}</span>
                </div>
                <span class="small text-muted dc-category-hint">点击展开加载明细</span>
            </div>
            <div class="dc-category-content"></div>
        </div>`;
    }

    function renderCategorySection(category, data) {
        const total = Number(data.total) || 0;
        if (!total) return "";
        const page = Number(data.page) || 1;
        const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
        const pageInfo = total ? `第 ${page} / ${totalPages} 页，共 ${total} 条` : "共 0 条";
        const prevDisabled = page <= 1 ? "disabled" : "";
        const nextDisabled = page >= totalPages ? "disabled" : "";
        return `<div class="card mb-3 dc-category-block" data-category="${esc(category)}" data-loaded="1">
            <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2 py-2">
                <div class="fw-semibold">${esc(category)} <span class="badge text-bg-light border">${total}</span></div>
                <div class="d-flex align-items-center gap-2 flex-wrap">
                    <span class="small text-muted">${pageInfo}</span>
                    <div class="btn-group btn-group-sm">
                        <button type="button" class="btn btn-outline-secondary dc-cat-prev" data-category="${esc(category)}" ${prevDisabled}>上一页</button>
                        <button type="button" class="btn btn-outline-secondary dc-cat-next" data-category="${esc(category)}" ${nextDisabled}>下一页</button>
                    </div>
                    <div class="d-flex align-items-center gap-1">
                        <input type="number" class="form-control form-control-sm dc-cat-page-input"
                            data-category="${esc(category)}" min="1" max="${totalPages}" value="${page}"
                            style="width:4.2rem" aria-label="页码">
                        <button type="button" class="btn btn-outline-secondary btn-sm dc-cat-go"
                            data-category="${esc(category)}" data-total-pages="${totalPages}">跳转</button>
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
                            <th style="width:7.5rem">操作</th>
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

    function shouldAutoLoadCategories(categories) {
        const sheetFilter = (document.getElementById("dcSheetCategory")?.value || "").trim();
        return !!sheetFilter || categories.length <= 1;
    }

    async function mountCategoryBlock(category, count, loadNow) {
        if (!loadNow) return renderCategoryShell(category, count);
        const data = await loadCategorySection(category);
        if (!(Number(data.total) || 0)) return "";
        return renderCategorySection(category, data);
    }

    async function expandCategoryBlock(category, triggerEl) {
        const block = document.querySelector(
            `.dc-category-block[data-category="${CSS.escape(category)}"]`
        );
        if (!block) return;
        if (block.getAttribute("data-loaded") === "1") return;
        const hint = block.querySelector(".dc-category-hint");
        if (hint) hint.textContent = "加载中…";
        if (triggerEl) setButtonBusy(triggerEl, true, "加载中…");
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
                bindCategoryPaginationOnce();
                syncCategorySelectAll(category);
                updateBatchToolbar();
            }
        } finally {
            if (triggerEl) setButtonBusy(triggerEl, false);
        }
    }

    function bindCategoryToggle(root) {
        const scope = root || document;
        scope.querySelectorAll(".dc-category-toggle").forEach((header) => {
            if (header.dataset.bound === "1") return;
            header.dataset.bound = "1";
            const activate = async () => {
                const block = header.closest(".dc-category-block");
                const category = block?.getAttribute("data-category") || "";
                if (!category || block?.getAttribute("data-loaded") === "1") return;
                await expandCategoryBlock(category, header);
            };
            header.addEventListener("click", activate);
            header.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    activate();
                }
            });
        });
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
            const autoLoad = shouldAutoLoadCategories(categories);
            const blocks = await Promise.all(
                categories.map(async (name) => mountCategoryBlock(name, counts[name], autoLoad))
            );
            wrap.innerHTML = blocks.filter(Boolean).join("") ||
                '<div class="alert alert-light border mb-0">暂无匹配记录，可调整筛选条件或先导入 Excel。</div>';
            const totalAll = categories.reduce((sum, name) => sum + (Number(counts[name]) || 0), 0);
            if (summary) {
                summary.textContent = autoLoad
                    ? `显示 ${categories.length} 个分类，合计 ${totalAll} 条记录（每分类每页 ${PAGE_SIZE} 条）`
                    : `匹配 ${categories.length} 个分类，合计 ${totalAll} 条；点击分类标题展开加载明细（每页 ${PAGE_SIZE} 条）`;
            }
            bindCategoryPaginationOnce();
            if (!autoLoad) bindCategoryToggle(wrap);
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

    function clampCategoryPage(page, totalPages) {
        const total = Math.max(1, Number(totalPages) || 1);
        const n = parseInt(String(page), 10);
        const p = Number.isFinite(n) ? n : 1;
        return Math.max(1, Math.min(total, p));
    }

    function bindCategoryPaginationOnce() {
        const wrap = document.getElementById("dcCategorySections");
        if (!wrap || wrap.dataset.catPaginationBound === "1") return;
        wrap.dataset.catPaginationBound = "1";
        wrap.addEventListener("click", async (e) => {
            const prev = e.target.closest(".dc-cat-prev");
            if (prev && !prev.disabled) {
                const cat = prev.getAttribute("data-category") || "";
                const page = categoryPages[cat] || 1;
                if (page <= 1) return;
                categoryPages[cat] = page - 1;
                await refreshCategoryBlock(cat, prev);
                return;
            }
            const next = e.target.closest(".dc-cat-next");
            if (next && !next.disabled) {
                const cat = next.getAttribute("data-category") || "";
                categoryPages[cat] = (categoryPages[cat] || 1) + 1;
                await refreshCategoryBlock(cat, next);
                return;
            }
            const go = e.target.closest(".dc-cat-go");
            if (go) {
                const cat = go.getAttribute("data-category") || "";
                const block = go.closest(".dc-category-block");
                const input = block?.querySelector(".dc-cat-page-input");
                const totalPages = Number(go.getAttribute("data-total-pages")) || 1;
                categoryPages[cat] = clampCategoryPage(input?.value, totalPages);
                await refreshCategoryBlock(cat, go);
            }
        });
        wrap.addEventListener("keydown", async (e) => {
            if (e.key !== "Enter") return;
            const input = e.target.closest(".dc-cat-page-input");
            if (!input) return;
            e.preventDefault();
            const block = input.closest(".dc-category-block");
            const cat = block?.getAttribute("data-category") || input.getAttribute("data-category") || "";
            const go = block?.querySelector(".dc-cat-go");
            const totalPages = Number(go?.getAttribute("data-total-pages")) || 1;
            categoryPages[cat] = clampCategoryPage(input.value, totalPages);
            await refreshCategoryBlock(cat, input);
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
                categoryPages[category] = Number(data.page) || categoryPages[category] || 1;
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

    function updateDocSheetCategorySelect(selected) {
        const sel = document.getElementById("dcDocSheetCategory");
        if (!sel) return;
        const cur = (selected || "").trim();
        const options = [...sheetCategoryOptions];
        if (cur && !options.includes(cur)) options.push(cur);
        sel.innerHTML =
            '<option value="">请选择</option>' +
            options.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join("");
        sel.value = cur;
    }

    function updateDocSheetCategoryDatalist() {
        updateDocSheetCategorySelect("");
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
        updateDocSheetCategorySelect(data.sheetCategory || "");
        set("dcDocStatus", data.status || "controlled");
        set("dcDocRegistrationSubmitted", data.registrationSubmitted ? "1" : "0");
    }

    function docItemFromRowBtn(btn) {
        if (!btn) return {};
        return {
            id: btn.getAttribute("data-doc-id") || "",
            documentNumber: btn.getAttribute("data-document-number") || "",
            title: btn.getAttribute("data-title") || "",
            titleEn: btn.getAttribute("data-title-en") || "",
            version: btn.getAttribute("data-version") || "",
            projectCode: btn.getAttribute("data-project-code") || "",
            projectName: btn.getAttribute("data-project-name") || "",
            registeredCountry: btn.getAttribute("data-registered-country") || "",
            sheetCategory: btn.getAttribute("data-sheet-category") || "",
            status: btn.getAttribute("data-status") || "controlled",
            registrationSubmitted: btn.getAttribute("data-registration-submitted") === "1",
        };
    }

    function openDocModal(item) {
        const modalEl = document.getElementById("dcDocModal");
        if (!modalEl || !item?.id) return;
        const open = async () => {
            await ensureSheetCategoryOptions();
            fillDocForm(item);
            const titleEl = document.getElementById("dcDocModalTitle");
            if (titleEl) titleEl.textContent = "编辑台账";
            bootstrap.Modal.getOrCreateInstance(modalEl).show();
        };
        open().catch((e) => notify(e.message || "打开编辑失败", "danger"));
    }

    function openDocCopyModal(source) {
        const data = source || {};
        openBatchCreateModal({
            title: "复制新增",
            rows: [
                {
                    documentNumber: "",
                    title: data.title || "",
                    titleEn: data.titleEn || "",
                    version: data.version || "",
                    sheetCategory: data.sheetCategory || "",
                    projectCode: data.projectCode || "",
                    projectName: data.projectName || "",
                    registeredCountry: data.registeredCountry || "",
                    status: "controlled",
                    registrationSubmitted: "0",
                },
            ],
        });
    }

    async function saveDocModal() {
        const docId = (document.getElementById("dcDocId")?.value || "").trim();
        if (!docId) return;
        const payload = readDocForm();
        if (!payload.documentNumber || !payload.title) {
            notify("请填写文件编号与文件名称", "warning");
            return;
        }
        const btn = document.getElementById("dcDocSaveBtn");
        try {
            await withButtonBusy(btn, "保存中…", async () => {
                await req(`/api/document-control/documents/${encodeURIComponent(docId)}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                notify("已保存", "success");
                const modalEl = document.getElementById("dcDocModal");
                if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
                resetCategoryPages();
                await loadGroupedLedger();
            });
        } catch (e) {
            notify(e.message || "保存失败", "danger");
        }
    }

    async function deleteDocument(docId) {
        if (!docId) return;
        if (!window.confirm("确定删除该台账记录？")) return;
        try {
            await req(`/api/document-control/documents/${encodeURIComponent(docId)}`, {
                method: "DELETE",
            });
            selectedDocIds.delete(docId);
            notify("已删除", "success");
            resetCategoryPages();
            await loadGroupedLedger();
        } catch (e) {
            notify(e.message || "删除失败", "danger");
        }
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

    const BATCH_CREATE_HEADER_ALIASES = {
        文件编号: "documentNumber",
        编号: "documentNumber",
        文件号: "documentNumber",
        受控编号: "documentNumber",
        文档编号: "documentNumber",
        "document number": "documentNumber",
        documentnumber: "documentNumber",
        文件名称: "title",
        名称: "title",
        文档名称: "title",
        文件名: "title",
        "文件名称（中文）": "title",
        title: "title",
        英文名: "titleEn",
        "文件名称（英文）": "titleEn",
        版本号: "version",
        版本: "version",
        version: "version",
        分类: "sheetCategory",
        "分类（sheet）": "sheetCategory",
        项目编号: "projectCode",
        项目号: "projectCode",
        所属项目: "projectName",
        注册国家: "registeredCountry",
        状态: "status",
        受控状态: "status",
        文件状态: "status",
        status: "status",
        注册递交: "registrationSubmitted",
        是否注册递交: "registrationSubmitted",
        registrationSubmitted: "registrationSubmitted",
    };
    const BATCH_CREATE_FIELD_ORDER = [
        "documentNumber",
        "title",
        "titleEn",
        "version",
        "sheetCategory",
        "projectCode",
        "projectName",
        "registeredCountry",
        "status",
        "registrationSubmitted",
    ];
    const BATCH_CREATE_FORM_LABELS = {
        documentNumber: "文件编号",
        title: "文件名称",
        titleEn: "英文名",
        version: "版本",
        sheetCategory: "分类",
        projectCode: "项目编号",
        projectName: "所属项目",
        registeredCountry: "注册国家",
        status: "状态",
        registrationSubmitted: "注册递交",
    };
    let batchCreateFormRows = [];

    function emptyBatchCreateRow() {
        return {
            documentNumber: "",
            title: "",
            titleEn: "",
            version: "",
            sheetCategory: "",
            projectCode: "",
            projectName: "",
            registeredCountry: "",
            status: "controlled",
            registrationSubmitted: "0",
        };
    }

    function inheritBatchCreateRow(prev) {
        if (!prev) return emptyBatchCreateRow();
        return {
            documentNumber: "",
            title: prev.title || "",
            titleEn: prev.titleEn || "",
            version: prev.version || "",
            sheetCategory: prev.sheetCategory || "",
            projectCode: prev.projectCode || "",
            projectName: prev.projectName || "",
            registeredCountry: prev.registeredCountry || "",
            status: prev.status || "controlled",
            registrationSubmitted: prev.registrationSubmitted || "0",
        };
    }

    function normalizeBatchCreateParsedValue(field, value) {
        const v = (value || "").trim();
        if (!v) return "";
        if (field === "status") {
            const lower = v.toLowerCase();
            if (lower === "voided" || v === "作废") return "voided";
            return "controlled";
        }
        if (field === "registrationSubmitted") {
            const lower = v.toLowerCase();
            if (lower === "1" || lower === "true" || lower === "yes" || v === "已递交") return "1";
            return "0";
        }
        return v;
    }

    function normalizeBatchCreateItem(row) {
        const status = (row.status || "controlled").trim() || "controlled";
        return {
            ...row,
            status: status === "voided" ? "voided" : "controlled",
            registrationSubmitted:
                row.registrationSubmitted === "1" ||
                row.registrationSubmitted === true ||
                String(row.registrationSubmitted || "").toLowerCase() === "true",
        };
    }

    function fillDownBatchCreateRows(rows) {
        const out = [];
        let prev = emptyBatchCreateRow();
        (rows || []).forEach((row) => {
            const merged = inheritBatchCreateRow(prev);
            BATCH_CREATE_FIELD_ORDER.forEach((field) => {
                const val = normalizeBatchCreateParsedValue(field, row[field] || "");
                if (val) merged[field] = val;
            });
            out.push(merged);
            prev = merged;
        });
        return out;
    }

    function splitBatchCreateRow(line) {
        if (line.includes("\t")) return line.split("\t");
        return line.split(/\s{2,}/);
    }

    function parseBatchCreateText(text) {
        const lines = (text || "")
            .split(/\r?\n/)
            .map((l) => l.trim())
            .filter(Boolean);
        if (!lines.length) return [];
        const firstCells = splitBatchCreateRow(lines[0]).map((c) => c.trim());
        const docHeaderKeys = new Set([
            "文件编号",
            "编号",
            "文件号",
            "documentnumber",
            "document number",
        ]);
        const isHeader = firstCells.some((c) => docHeaderKeys.has(c.toLowerCase()) || docHeaderKeys.has(c));
        const dataLines = isHeader ? lines.slice(1) : lines;
        const colIndex = {};
        if (isHeader) {
            firstCells.forEach((header, idx) => {
                const key =
                    BATCH_CREATE_HEADER_ALIASES[header] ||
                    BATCH_CREATE_HEADER_ALIASES[header.toLowerCase()];
                if (key) colIndex[key] = idx;
            });
        }
        const items = [];
        for (const line of dataLines) {
            const cells = splitBatchCreateRow(line).map((c) => c.trim());
            const item = {};
            if (isHeader) {
                Object.entries(colIndex).forEach(([field, idx]) => {
                    if (cells[idx]) item[field] = cells[idx];
                });
            } else {
                BATCH_CREATE_FIELD_ORDER.forEach((field, idx) => {
                    if (cells[idx]) item[field] = cells[idx];
                });
            }
            if ((item.documentNumber || "").trim() && (item.title || "").trim()) {
                items.push(item);
            }
        }
        return fillDownBatchCreateRows(items);
    }

    function syncBatchCreateFormFromDom() {
        const body = document.getElementById("dcBatchCreateRowsBody");
        if (!body) return;
        const rows = [];
        body.querySelectorAll("tr").forEach((tr, rowIndex) => {
            const item = emptyBatchCreateRow();
            tr.querySelectorAll("[data-field]").forEach((inp) => {
                const field = inp.getAttribute("data-field") || "";
                if (field) item[field] = (inp.value || "").trim();
            });
            rows[rowIndex] = item;
        });
        if (rows.length) batchCreateFormRows = rows;
    }

    function batchCreateStatusSelectHtml(selected, rowIndex) {
        const sel = (selected || "controlled").trim() || "controlled";
        const options = [
            { value: "controlled", label: "受控" },
            { value: "voided", label: "作废" },
        ];
        const opts = options
            .map((opt) => {
                const active = opt.value === sel ? " selected" : "";
                return `<option value="${opt.value}"${active}>${opt.label}</option>`;
            })
            .join("");
        return `<select class="form-select form-select-sm" data-field="status" data-row="${rowIndex}" aria-label="状态">${opts}</select>`;
    }

    function batchCreateRegistrationSelectHtml(selected, rowIndex) {
        const sel =
            selected === "1" || selected === true || String(selected || "").toLowerCase() === "true"
                ? "1"
                : "0";
        const options = [
            { value: "0", label: "未递交" },
            { value: "1", label: "已递交" },
        ];
        const opts = options
            .map((opt) => {
                const active = opt.value === sel ? " selected" : "";
                return `<option value="${opt.value}"${active}>${opt.label}</option>`;
            })
            .join("");
        return `<select class="form-select form-select-sm" data-field="registrationSubmitted" data-row="${rowIndex}" aria-label="注册递交">${opts}</select>`;
    }

    function batchCreateCategorySelectHtml(selected, rowIndex) {
        const sel = (selected || "").trim();
        const options = [...sheetCategoryOptions];
        if (sel && !options.includes(sel)) options.push(sel);
        const opts = ['<option value="">请选择</option>']
            .concat(
                options.map((name) => {
                    const active = name === sel ? " selected" : "";
                    return `<option value="${esc(name)}"${active}>${esc(name)}</option>`;
                })
            )
            .join("");
        return `<select class="form-select form-select-sm" data-field="sheetCategory" data-row="${rowIndex}" aria-label="分类">
            ${opts}
        </select>`;
    }

    function renderBatchCreateFieldCell(field, row, rowIndex) {
        const label = BATCH_CREATE_FORM_LABELS[field] || field;
        const required = field === "documentNumber" || field === "title";
        if (field === "sheetCategory") {
            return `<td>${batchCreateCategorySelectHtml(row[field] || "", rowIndex)}</td>`;
        }
        if (field === "status") {
            return `<td>${batchCreateStatusSelectHtml(row[field] || "controlled", rowIndex)}</td>`;
        }
        if (field === "registrationSubmitted") {
            return `<td>${batchCreateRegistrationSelectHtml(row.registrationSubmitted, rowIndex)}</td>`;
        }
        return `<td>
            <input type="text" class="form-control form-control-sm"
                data-field="${esc(field)}" data-row="${rowIndex}"
                value="${esc(row[field] || "")}"
                aria-label="${esc(label)}${required ? "（必填）" : ""}">
        </td>`;
    }

    function renderBatchCreateFormRows() {
        const body = document.getElementById("dcBatchCreateRowsBody");
        if (!body) return;
        if (!batchCreateFormRows.length) batchCreateFormRows = [emptyBatchCreateRow()];
        body.innerHTML = batchCreateFormRows
            .map((row, rowIndex) => {
                const cells = BATCH_CREATE_FIELD_ORDER.map((field) =>
                    renderBatchCreateFieldCell(field, row, rowIndex)
                ).join("");
                const canRemove = batchCreateFormRows.length > 1;
                return `<tr data-row-index="${rowIndex}">
                    ${cells}
                    <td class="text-center">
                        <button type="button" class="btn btn-link btn-sm p-0 text-danger dc-batch-create-remove-row"
                            data-row-index="${rowIndex}" ${canRemove ? "" : "disabled"}
                            title="删除本行">×</button>
                    </td>
                </tr>`;
            })
            .join("");
        updateBatchCreatePreview();
    }

    function updateBatchCreatePreview() {
        const el = document.getElementById("dcBatchCreatePreview");
        if (!el) return;
        const valid = batchCreateFormRows.filter(
            (x) => (x.documentNumber || "").trim() && (x.title || "").trim()
        ).length;
        el.textContent = `共 ${batchCreateFormRows.length} 行，可提交 ${valid} 条（需填写文件编号与文件名称）`;
    }

    function collectBatchCreateFormItems() {
        syncBatchCreateFormFromDom();
        return batchCreateFormRows
            .filter((x) => (x.documentNumber || "").trim() && (x.title || "").trim())
            .map((row) => normalizeBatchCreateItem(row));
    }

    function addBatchCreateRow({ inheritFromLast = true } = {}) {
        syncBatchCreateFormFromDom();
        const last = batchCreateFormRows[batchCreateFormRows.length - 1];
        batchCreateFormRows.push(inheritFromLast && last ? inheritBatchCreateRow(last) : emptyBatchCreateRow());
        renderBatchCreateFormRows();
        const body = document.getElementById("dcBatchCreateRowsBody");
        const lastRow = body?.querySelector(`tr[data-row-index="${batchCreateFormRows.length - 1}"]`);
        const numInput = lastRow?.querySelector('[data-field="documentNumber"]');
        if (numInput) {
            numInput.focus();
            numInput.select?.();
        }
    }

    function removeBatchCreateRow(rowIndex) {
        if (batchCreateFormRows.length <= 1) return;
        syncBatchCreateFormFromDom();
        batchCreateFormRows.splice(rowIndex, 1);
        renderBatchCreateFormRows();
    }

    function appendParsedRowsToForm(parsedRows) {
        if (!parsedRows.length) return 0;
        syncBatchCreateFormFromDom();
        const last = batchCreateFormRows[batchCreateFormRows.length - 1];
        const tailEmpty =
            last &&
            !BATCH_CREATE_FIELD_ORDER.some((field) => (last[field] || "").trim());
        if (tailEmpty) {
            batchCreateFormRows.pop();
        }
        let prev = batchCreateFormRows[batchCreateFormRows.length - 1] || emptyBatchCreateRow();
        parsedRows.forEach((row) => {
            const merged = inheritBatchCreateRow(prev);
            BATCH_CREATE_FIELD_ORDER.forEach((field) => {
                const val = normalizeBatchCreateParsedValue(field, row[field] || "");
                if (val) merged[field] = val;
            });
            batchCreateFormRows.push(merged);
            prev = merged;
        });
        renderBatchCreateFormRows();
        return parsedRows.length;
    }

    async function ensureSheetCategoryOptions() {
        if (sheetCategoryOptions.length) return;
        const catRes = await req("/api/document-control/categories");
        sheetCategoryOptions = catRes.allItems || catRes.items || [];
        updateDocSheetCategoryDatalist();
    }

    function openBatchCreateModal(options) {
        const opts = options || {};
        const modalEl = document.getElementById("dcBatchCreateModal");
        if (!modalEl) return;
        const open = async () => {
            await ensureSheetCategoryOptions();
            const input = document.getElementById("dcBatchCreateInput");
            if (input) input.value = "";
            const titleEl = document.getElementById("dcBatchCreateModalTitle");
            if (titleEl) titleEl.textContent = opts.title || "批量新增台账";
            if (opts.rows && opts.rows.length) {
                batchCreateFormRows = opts.rows.map((row) => ({
                    ...emptyBatchCreateRow(),
                    ...row,
                    documentNumber: (row.documentNumber || "").trim(),
                }));
            } else {
                batchCreateFormRows = [emptyBatchCreateRow()];
            }
            renderBatchCreateFormRows();
            bootstrap.Modal.getOrCreateInstance(modalEl).show();
            window.setTimeout(() => {
                const firstNum = document.querySelector(
                    '#dcBatchCreateRowsBody [data-field="documentNumber"]'
                );
                if (firstNum) firstNum.focus();
            }, 300);
        };
        open().catch((e) => notify(e.message || "加载分类列表失败", "danger"));
    }

    function getSelectedDocItems() {
        const items = [];
        selectedDocIds.forEach((id) => {
            const tr = document.querySelector(`tr[data-doc-id="${CSS.escape(id)}"]`);
            const btn = tr?.querySelector(".dc-edit-doc");
            if (btn) items.push(docItemFromRowBtn(btn));
        });
        return items;
    }

    function openBatchCopyFromSelection() {
        const sources = getSelectedDocItems();
        if (!sources.length) {
            notify("请先勾选要复制的记录", "warning");
            return;
        }
        const rows = sources.map((src) => ({
            documentNumber: "",
            title: src.title || "",
            titleEn: src.titleEn || "",
            version: src.version || "",
            sheetCategory: src.sheetCategory || "",
            projectCode: src.projectCode || "",
            projectName: src.projectName || "",
            registeredCountry: src.registeredCountry || "",
            status: "controlled",
            registrationSubmitted: "0",
        }));
        openBatchCreateModal({ rows, title: "批量复制新增" });
    }

    function previewBatchCreate() {
        const text = document.getElementById("dcBatchCreateInput")?.value || "";
        const parsed = parseBatchCreateText(text);
        if (!parsed.length) {
            notify("未解析到有效记录", "warning");
            return;
        }
        const added = appendParsedRowsToForm(parsed);
        notify(`已追加 ${added} 行到表单`, "success");
        const input = document.getElementById("dcBatchCreateInput");
        if (input) input.value = "";
    }

    async function saveBatchCreate() {
        const items = collectBatchCreateFormItems();
        if (!items.length) {
            notify("请至少填写一行有效的文件编号与文件名称", "warning");
            return;
        }
        if (items.length > 500) {
            notify("单次最多新增 500 条", "warning");
            return;
        }
        const btn = document.getElementById("dcBatchCreateSaveBtn");
        try {
            await withButtonBusy(btn, "提交中…", async () => {
                const res = await req("/api/document-control/documents/batch-create", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ items }),
                });
                const failed = res.failed || [];
                notify(res.message || "已批量新增", failed.length ? "warning" : "success");
                if (failed.length) {
                    const el = document.getElementById("dcBatchCreatePreview");
                    if (el) {
                        const lines = failed
                            .slice(0, 10)
                            .map(
                                (x) =>
                                    `第 ${Number(x.index) + 1} 行 ${x.documentNumber || "-"}：${x.message || "失败"}`
                            )
                            .join("\n");
                        el.textContent = `${res.message || ""}\n${lines}${failed.length > 10 ? "\n…" : ""}`;
                    }
                } else {
                    const modalEl = document.getElementById("dcBatchCreateModal");
                    if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
                    clearDocSelection();
                }
                resetCategoryPages();
                await loadGroupedLedger();
            });
        } catch (e) {
            notify(e.message || "批量新增失败", "danger");
        }
    }

    function bindBatchCreateModal() {
        document.getElementById("dcBatchAddDocBtn")?.addEventListener("click", () => openBatchCreateModal());
        document.getElementById("dcBatchCreateAddRowBtn")?.addEventListener("click", () => addBatchCreateRow());
        document.getElementById("dcBatchCreateClearRowsBtn")?.addEventListener("click", () => {
            batchCreateFormRows = [emptyBatchCreateRow()];
            renderBatchCreateFormRows();
        });
        document.getElementById("dcBatchCreateParseBtn")?.addEventListener("click", previewBatchCreate);
        document.getElementById("dcBatchCreateSaveBtn")?.addEventListener("click", saveBatchCreate);
        document.getElementById("dcBatchCreateRowsBody")?.addEventListener("input", () => {
            syncBatchCreateFormFromDom();
            updateBatchCreatePreview();
        });
        document.getElementById("dcBatchCreateRowsBody")?.addEventListener("change", () => {
            syncBatchCreateFormFromDom();
            updateBatchCreatePreview();
        });
        document.getElementById("dcBatchCreateRowsBody")?.addEventListener("click", (e) => {
            const btn = e.target.closest(".dc-batch-create-remove-row");
            if (!btn || btn.disabled) return;
            const idx = Number(btn.getAttribute("data-row-index"));
            if (Number.isFinite(idx)) removeBatchCreateRow(idx);
        });
    }

    function bindBatchActions() {
        bindBatchFieldToggle("dcBatchChkStatus", "dcBatchStatus");
        bindBatchFieldToggle("dcBatchChkRegistration", "dcBatchRegistration");
        bindBatchFieldToggle("dcBatchChkProjectName", "dcBatchProjectName");
        bindBatchFieldToggle("dcBatchChkRegisteredCountry", "dcBatchRegisteredCountry");
        document.getElementById("dcBatchEditBtn")?.addEventListener("click", openBatchEditModal);
        document.getElementById("dcBatchCopyDocBtn")?.addEventListener("click", openBatchCopyFromSelection);
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
        document.getElementById("dcDocSaveBtn")?.addEventListener("click", saveDocModal);
        document.getElementById("dcCategorySections")?.addEventListener("click", async (e) => {
            const editBtn = e.target.closest(".dc-edit-doc");
            if (editBtn) {
                openDocModal(docItemFromRowBtn(editBtn));
                return;
            }
            const copyBtn = e.target.closest(".dc-copy-doc");
            if (copyBtn) {
                openDocCopyModal(docItemFromRowBtn(copyBtn));
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
        if (!body) return;
        schemes = rows || [];
        if (!schemes.length) {
            body.innerHTML =
                '<tr><td colspan="5" class="text-muted p-3">暂无规则，请点击「从知识库更新规则」</td></tr>';
            return;
        }
        body.innerHTML = schemes
            .map((x) => {
                const ex = x.kbRuleExcerpt || "";
                const m = ex.match(/例如[：:]\s*([^\s；;。]+)/);
                const example = m ? m[1] : x.docTypeCode || "-";
                const auto = x.autoAllocatable
                    ? '<span class="badge text-bg-success">支持</span>'
                    : '<span class="badge text-bg-secondary">手工</span>';
                const sheetCat = x.sheetCategory || "-";
                return `<tr>
                    <td>${esc(x.name || x.docTypeCode || "-")}</td>
                    <td>${esc(sheetCat)}</td>
                    <td>${esc(example)}</td>
                    <td class="small text-muted">${esc(ex.slice(0, 120) || "-")}</td>
                    <td>${auto}</td>
                </tr>`;
            })
            .join("");
    }

    function renderIssueProjectSelect() {
        const sel = document.getElementById("dcIssueProject");
        if (!sel) return;
        const opts = ['<option value="">请选择项目</option>'];
        (page1Projects || []).forEach((p) => {
            const id = (p.id || "").trim();
            if (!id) return;
            opts.push(
                `<option value="${esc(id)}" data-code="${esc(p.projectCode || "")}" data-name="${esc(p.projectName || p.name || "")}" data-country="${esc(p.registeredCountry || "")}">${esc(p.label || p.name || id)}</option>`
            );
        });
        sel.innerHTML = opts.join("");
    }

    function renderIssueCategorySelect(preferred) {
        const sel = document.getElementById("dcIssueSheetCategory");
        if (!sel) return;
        const cats = issueCategories || [];
        if (!cats.length) {
            sel.innerHTML = '<option value="">请先更新编号规则</option>';
            return;
        }
        sel.innerHTML = cats
            .map((x) => {
                const suffix = x.disabledReason ? `（${x.disabledReason}）` : "";
                return `<option value="${esc(x.sheetCategory || "")}">${esc(x.label || x.sheetCategory || "")}${esc(suffix)}</option>`;
            })
            .join("");
        const want = (preferred || "").trim();
        if (want && cats.some((x) => x.sheetCategory === want)) {
            sel.value = want;
        }
    }

    function syncIssueProjectFields() {
        const sel = document.getElementById("dcIssueProject");
        const opt = sel?.selectedOptions?.[0];
        const idEl = document.getElementById("dcIssueProjectId");
        const codeEl = document.getElementById("dcIssueProjectCode");
        const nameEl = document.getElementById("dcIssueProjectName");
        const countryEl = document.getElementById("dcIssueRegisteredCountry");
        if (!opt || !opt.value) {
            if (idEl) idEl.value = "";
            if (codeEl) codeEl.value = "";
            if (nameEl) nameEl.value = "";
            if (countryEl) countryEl.value = "";
            return;
        }
        if (idEl) idEl.value = opt.value;
        if (codeEl) codeEl.value = opt.getAttribute("data-code") || "";
        if (nameEl) nameEl.value = opt.getAttribute("data-name") || "";
        if (countryEl) countryEl.value = opt.getAttribute("data-country") || "";
    }

    function preselectIssueProject(projectId, projectCode) {
        const sel = document.getElementById("dcIssueProject");
        if (!sel) return;
        const pid = (projectId || "").trim();
        const pcode = (projectCode || "").trim();
        if (pid) {
            const hit = Array.from(sel.options).find((o) => o.value === pid);
            if (hit) {
                sel.value = pid;
                syncIssueProjectFields();
                return;
            }
        }
        if (pcode) {
            const hit = Array.from(sel.options).find(
                (o) => (o.getAttribute("data-code") || "").trim() === pcode
            );
            if (hit) {
                sel.value = hit.value;
                syncIssueProjectFields();
            }
        }
    }

    function restoreIssueApplyButtonState() {
        const applyBtn = document.getElementById("dcApplyBtn");
        const resultEl = document.getElementById("dcPreviewResult");
        resultEl?.removeAttribute("aria-busy");
        if (!applyBtn) return;
        applyBtn.removeAttribute("aria-busy");
        const cfg = selectedIssueCategory();
        const canAuto = !!cfg?.autoAllocatable && !cfg?.disabledReason;
        applyBtn.disabled = !canAuto || (!!issueDuplicateState && !issueForceNew);
    }

    function setIssuePreviewBusy(busy) {
        const resultEl = document.getElementById("dcPreviewResult");
        const applyBtn = document.getElementById("dcApplyBtn");
        if (!busy) return;
        if (resultEl) {
            resultEl.innerHTML =
                '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>正在翻译并预览编号…';
            resultEl.setAttribute("aria-busy", "true");
        }
        if (applyBtn) {
            applyBtn.disabled = true;
            applyBtn.setAttribute("aria-busy", "true");
        }
    }

    function selectedIssueCategory() {
        const cat = (document.getElementById("dcIssueSheetCategory")?.value || "").trim();
        return (issueCategories || []).find((x) => x.sheetCategory === cat) || null;
    }

    function updateIssueModalFields() {
        const cfg = selectedIssueCategory();
        const projectWrap = document.getElementById("dcIssueProjectWrap");
        const subtypeWrap = document.getElementById("dcIssueSubtypeWrap");
        const hintEl = document.getElementById("dcIssueSchemeHint");
        const applyBtn = document.getElementById("dcApplyBtn");
        if (!cfg) {
            if (hintEl) hintEl.textContent = "请选择台账分类";
            if (applyBtn) {
                applyBtn.disabled = true;
                applyBtn.textContent = "申请编号并登记";
            }
            previewResult = null;
            const resultEl = document.getElementById("dcPreviewResult");
            if (resultEl) resultEl.textContent = "选择分类后自动预览建议编号";
            return;
        }
        const needsProject = !!cfg.needsProjectCode;
        const autoSubtype = !!cfg.subtypeFromTitle;
        const needsSubtype = !!cfg.needsSubtype && !autoSubtype;
        projectWrap?.classList.toggle("d-none", !needsProject);
        subtypeWrap?.classList.toggle("d-none", !needsSubtype);
        if (hintEl) {
            let hint = cfg.disabledReason || cfg.kbRuleExcerpt || cfg.manualHint || "";
            if (autoSubtype) {
                hint =
                    "子类由英文单词首字母自动生成；同名文件子类不变、流水号递增。纯中文将自动翻译为英文。";
            }
            hintEl.textContent = hint.slice(0, 240);
        }
        if (applyBtn) {
            const canAuto = !!cfg.autoAllocatable && !cfg.disabledReason;
            applyBtn.disabled = !canAuto;
            applyBtn.textContent = canAuto ? "申请编号并登记" : "不支持自动取号";
        }
        const titleNow = (document.getElementById("dcIssueTitle")?.value || "").trim();
        if (titleNow) {
            refreshIssuePreview();
        } else {
            const resultEl = document.getElementById("dcPreviewResult");
            if (resultEl) resultEl.textContent = "填写文件名称后移出输入框将预览建议编号";
            previewResult = null;
        }
    }

    function resetIssueModalForm() {
        const fields = ["dcIssueTitle", "dcIssueVersion", "dcIssueTitleEn"];
        fields.forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.value = "";
        });
        previewResult = null;
        issueForceNew = false;
        issueResolvedTitleEn = null;
        issuePreviewTitle = null;
        issueBatchItems = [];
        clearIssueDuplicateUi();
        renderIssueBatchResults([]);
        const batchTa = document.getElementById("dcIssueBatchTitles");
        if (batchTa) batchTa.value = "";
        updateIssueTitleEnPreview("", "");
        const resultEl = document.getElementById("dcPreviewResult");
        if (resultEl) resultEl.textContent = "填写文件名称后移出输入框将预览建议编号";
    }

    function syncIssueTitleEnHidden(titleEn) {
        const el = document.getElementById("dcIssueTitleEn");
        if (el) el.value = (titleEn || "").trim();
    }

    function clearIssueDuplicateUi() {
        issueDuplicateState = null;
        document.getElementById("dcIssueDuplicatePanel")?.classList.add("d-none");
        const applyBtn = document.getElementById("dcApplyBtn");
        if (applyBtn) applyBtn.disabled = false;
    }

    function formatIssueDuplicateMessage(res) {
        const existing = res.existingDocument || {};
        const num = existing.documentNumber || "-";
        const ver = existing.version ? `，版本 ${existing.version}` : "";
        const titleEn = res.titleEn || existing.titleEn || "";
        return (
            (res.message || `已存在同名文件，编号 ${num}`) +
            (titleEn ? `；英文名：${titleEn}` : "") +
            ver
        );
    }

    function showIssueDuplicate(res) {
        issueDuplicateState = res.existingDocument || null;
        const msg = formatIssueDuplicateMessage(res);
        const panel = document.getElementById("dcIssueDuplicatePanel");
        const textEl = document.getElementById("dcIssueDuplicateText");
        if (textEl) textEl.textContent = msg;
        panel?.classList.remove("d-none");
        const applyBtn = document.getElementById("dcApplyBtn");
        if (applyBtn) applyBtn.disabled = true;
    }

    function titleEnSourceLabel(source) {
        switch (source) {
            case "translated":
                return "（已自动翻译）";
            case "embedded":
                return "（取自名称中的英文）";
            case "ledger":
                return "（台账同名）";
            case "cache":
                return "（翻译缓存）";
            case "cached":
                return "（已指定）";
            default:
                return "";
        }
    }

    function escHtml(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function parseBatchTitlesText() {
        const raw = document.getElementById("dcIssueBatchTitles")?.value || "";
        return raw
            .split(/\r?\n/)
            .map((line) => line.trim())
            .filter((line) => line && !line.startsWith("#"));
    }

    function renderIssueBatchResults(items) {
        issueBatchItems = items || [];
        const wrap = document.getElementById("dcIssueBatchResultWrap");
        const body = document.getElementById("dcIssueBatchResultBody");
        if (!wrap || !body) return;
        if (!issueBatchItems.length) {
            wrap.classList.add("d-none");
            body.innerHTML = "";
            return;
        }
        wrap.classList.remove("d-none");
        body.innerHTML = issueBatchItems
            .map((row) => {
                const title = escHtml(row.title || "");
                const te = escHtml(row.titleEn || "-");
                const teSrc = titleEnSourceLabel(row.titleEnSource);
                let num = "-";
                let status = "";
                if (row.error) {
                    status = `<span class="text-danger">${escHtml(row.error)}</span>`;
                } else if (row.duplicateTitle) {
                    num = escHtml(row.existingDocument?.documentNumber || "-");
                    status = '<span class="text-warning">需确认同名</span>';
                } else {
                    num = escHtml(row.documentNumber || row.preview?.document_number || "-");
                    status = '<span class="text-success">可申请</span>';
                }
                const srcLine = teSrc ? `<div class="text-muted">${escHtml(teSrc)}</div>` : "";
                return `<tr><td>${title}</td><td>${te}${srcLine}</td><td>${num}</td><td>${status}</td></tr>`;
            })
            .join("");
    }

    async function batchIssuePreview(busyBtn) {
        const cfg = selectedIssueCategory();
        if (!cfg) {
            notify("请选择台账分类", "warning");
            return;
        }
        if (!cfg.autoAllocatable || cfg.disabledReason) {
            notify(cfg.manualHint || cfg.disabledReason || "该分类不支持自动取号", "warning");
            return;
        }
        if (cfg.needsProjectCode && !(document.getElementById("dcIssueProjectCode")?.value || "").trim()) {
            notify("请选择含项目编号的页面1项目", "warning");
            return;
        }
        const titles = parseBatchTitlesText();
        if (!titles.length) {
            notify("请在批量区域填写至少一个文件名称", "warning");
            return;
        }
        await withButtonBusy(busyBtn, "预览中…", async () => {
            const res = await reqJson("/api/document-control/allocate/batch/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    ...buildIssuePayload(cfg),
                    titlesText: document.getElementById("dcIssueBatchTitles")?.value || "",
                }),
            });
            renderIssueBatchResults(res.items || []);
            const el = document.getElementById("dcPreviewResult");
            if (el) {
                el.textContent = `批量预览：共 ${res.total || 0} 条，可申请 ${res.readyCount || 0} 条，同名 ${res.duplicateCount || 0} 条，失败 ${res.errorCount || 0} 条`;
            }
        });
    }

    async function batchIssueApply(busyBtn) {
        const cfg = selectedIssueCategory();
        if (!cfg) return;
        if (!cfg.autoAllocatable || cfg.disabledReason) {
            notify(cfg.manualHint || cfg.kbRuleExcerpt || "该分类须手工编号", "warning");
            return;
        }
        let items = issueBatchItems;
        if (!items.length) {
            await batchIssuePreview(document.getElementById("dcIssueBatchPreviewBtn"));
            items = issueBatchItems;
        }
        const applyItems = items.filter((r) => !r.error && !r.duplicateTitle);
        if (!applyItems.length) {
            notify("没有可直接申请的项目（请先批量预览，或处理同名项）", "warning");
            return;
        }
        const modalEl = document.getElementById("dcIssueModal");
        const modal = modalEl ? bootstrap.Modal.getOrCreateInstance(modalEl) : null;
        await withButtonBusy(busyBtn, "提交中…", async () => {
            const res = await reqJson("/api/document-control/allocate/batch/apply", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    ...buildIssuePayload(cfg),
                    items: applyItems.map((r) => ({
                        title: r.title,
                        titleEn: r.titleEn,
                    })),
                }),
            });
            notify(res.message || "批量申请完成", res.failCount ? "warning" : "success");
            issueBatchItems = [];
            renderIssueBatchResults([]);
            const batchTa = document.getElementById("dcIssueBatchTitles");
            if (batchTa) batchTa.value = "";
            modal?.hide();
            resetCategoryPages();
            await loadGroupedLedger();
        });
    }

    function dismissIssueAsSameDocument() {
        issueForceNew = false;
        issueDuplicateState = null;
        issuePreviewTitle = null;
        previewResult = null;
        clearIssueDuplicateUi();
        const titleEl = document.getElementById("dcIssueTitle");
        if (titleEl) titleEl.value = "";
        issueResolvedTitleEn = null;
        syncIssueTitleEnHidden("");
        updateIssueTitleEnPreview("", "");
        const resultEl = document.getElementById("dcPreviewResult");
        if (resultEl) resultEl.textContent = "填写文件名称后移出输入框将预览建议编号";
        restoreIssueApplyButtonState();
    }

    function updateIssueTitleEnPreview(titleEn, source) {
        const el = document.getElementById("dcIssueTitleEnPreview");
        const val = (titleEn || "").trim();
        issueResolvedTitleEn = val || null;
        syncIssueTitleEnHidden(val);
        if (!el) return;
        if (!val) {
            el.classList.add("d-none");
            el.textContent = "";
            return;
        }
        const srcLabel = titleEnSourceLabel(source);
        el.textContent = `英文名：${val}${srcLabel}`;
        el.classList.remove("d-none");
    }

    function buildIssuePayload(cfg, extra) {
        syncIssueProjectFields();
        const title = (document.getElementById("dcIssueTitle")?.value || "").trim();
        const hiddenTitleEn = (document.getElementById("dcIssueTitleEn")?.value || "").trim();
        return {
            sheetCategory: cfg.sheetCategory,
            schemeId: cfg.schemeId || null,
            title,
            projectId: (document.getElementById("dcIssueProjectId")?.value || "").trim() || null,
            projectCode: (document.getElementById("dcIssueProjectCode")?.value || "").trim() || null,
            projectName: (document.getElementById("dcIssueProjectName")?.value || "").trim() || null,
            registeredCountry: (document.getElementById("dcIssueRegisteredCountry")?.value || "").trim() || null,
            version: (document.getElementById("dcIssueVersion")?.value || "").trim() || null,
            titleEn: issueResolvedTitleEn || hiddenTitleEn || null,
            forceNew: !!issueForceNew,
            ...(extra || {}),
        };
    }

    async function refreshIssuePreview() {
        const cfg = selectedIssueCategory();
        const resultEl = document.getElementById("dcPreviewResult");
        if (!cfg || !resultEl) return;
        if (!cfg.autoAllocatable || cfg.disabledReason) {
            resultEl.textContent =
                cfg.manualHint || cfg.disabledReason || cfg.kbRuleExcerpt || "该分类请手工填写编号后通过「新增」录入台账";
            previewResult = null;
            clearIssueDuplicateUi();
            updateIssueTitleEnPreview("", "");
            return;
        }
        syncIssueProjectFields();
        const projectCode = (document.getElementById("dcIssueProjectCode")?.value || "").trim();
        const title = (document.getElementById("dcIssueTitle")?.value || "").trim();
        if (cfg.needsProjectCode && !projectCode) {
            resultEl.textContent = "请选择页面1项目（须含项目编号）后预览建议编号";
            previewResult = null;
            clearIssueDuplicateUi();
            return;
        }
        if (cfg.subtypeFromTitle && !title) {
            resultEl.textContent = "请填写文件名称后移出输入框预览建议编号";
            previewResult = null;
            clearIssueDuplicateUi();
            return;
        }
        if (!issueForceNew) {
            clearIssueDuplicateUi();
        }
        const seq = ++issuePreviewSeq;
        setIssuePreviewBusy(true);
        try {
            const res = await reqJson("/api/document-control/allocate/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(buildIssuePayload(cfg)),
            });
            if (seq !== issuePreviewSeq) return;
            issueResolvedTitleEn = res.titleEn || res.item?.title_en || null;
            updateIssueTitleEnPreview(issueResolvedTitleEn, res.titleEnSource);
            if (res.duplicateTitle) {
                previewResult = null;
                issuePreviewTitle = title;
                resultEl.textContent = "发现名称匹配的文件，请确认是否为同一份。";
                showIssueDuplicate(res);
                return;
            }
            clearIssueDuplicateUi();
            previewResult = res.item || null;
            issuePreviewTitle = title;
            const subLabel = previewResult?.subtype ? `，子类 ${previewResult.subtype}` : "";
            resultEl.textContent = previewResult?.document_number
                ? `建议编号：${previewResult.document_number}${subLabel}`
                : "未获取到建议编号";
        } catch (e) {
            if (seq !== issuePreviewSeq) return;
            previewResult = null;
            resultEl.textContent = e.message || "预览失败";
            if (!issueForceNew) clearIssueDuplicateUi();
        } finally {
            if (seq === issuePreviewSeq) restoreIssueApplyButtonState();
        }
    }

    async function submitIssueApply(cfg, extra, busyBtn) {
        const btn = busyBtn || document.getElementById("dcApplyBtn");
        const modalEl = document.getElementById("dcIssueModal");
        const modal = modalEl ? bootstrap.Modal.getOrCreateInstance(modalEl) : null;
        await withButtonBusy(btn, "提交中…", async () => {
            try {
                const res = await reqJson("/api/document-control/allocate/apply", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(buildIssuePayload(cfg, extra)),
                });
                if (res.confirmedSameDocument) {
                    notify(res.message || "该文件已在台账中", "info");
                } else {
                    notify(res.message || "编号已申请", "success");
                }
                issueForceNew = false;
                issueResolvedTitleEn = null;
                syncIssueTitleEnHidden("");
                clearIssueDuplicateUi();
                modal?.hide();
                resetCategoryPages();
                await loadGroupedLedger();
            } catch (e) {
                if (e.status === 409 && e.data?.duplicateTitle) {
                    showIssueDuplicate(e.data);
                    const resultEl = document.getElementById("dcPreviewResult");
                    if (resultEl) resultEl.textContent = "发现名称匹配的文件，请确认是否为同一份。";
                    return;
                }
                notify(e.message || "申请失败", "danger");
            }
        });
    }

    async function loadSchemes() {
        const res = await req("/api/document-control/schemes");
        renderSchemes(res.items || []);
    }

    async function loadIssueOptions(preferredCategory) {
        const res = await req("/api/document-control/allocate/options");
        issueCategories = res.categories || [];
        page1Projects = res.projects || [];
        renderIssueProjectSelect();
        renderIssueCategorySelect(preferredCategory);
    }

    function bindIssueModal() {
        const modalEl = document.getElementById("dcIssueModal");
        if (!modalEl) return;
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        document.getElementById("dcOpenIssueModalBtn")?.addEventListener("click", async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const openBtn = document.getElementById("dcOpenIssueModalBtn");
            await withButtonBusy(openBtn, "打开中…", async () => {
                resetIssueModalForm();
                const sp = new URLSearchParams(window.location.search || "");
                const qCat = (sp.get("sheetCategory") || "DHF").trim();
                await loadIssueOptions(qCat);
                const qPid = (sp.get("projectId") || "").trim();
                const qPcode =
                    (sp.get("projectCode") || "").trim() ||
                    (document.getElementById("dcProjectCode")?.value || "").trim();
                preselectIssueProject(qPid, qPcode);
                updateIssueModalFields();
                modal.show();
            });
        });
        document.getElementById("dcIssueSheetCategory")?.addEventListener("change", updateIssueModalFields);
        document.getElementById("dcIssueProject")?.addEventListener("change", () => {
            syncIssueProjectFields();
            clearTimeout(window._dcIssuePreviewTimer);
            window._dcIssuePreviewTimer = setTimeout(refreshIssuePreview, 200);
        });
        document.getElementById("dcIssueSubtype")?.addEventListener("input", () => {
            clearTimeout(window._dcIssuePreviewTimer);
            window._dcIssuePreviewTimer = setTimeout(refreshIssuePreview, 300);
        });
        document.getElementById("dcIssueTitle")?.addEventListener("input", () => {
            issueForceNew = false;
            issueResolvedTitleEn = null;
            issuePreviewTitle = null;
            previewResult = null;
            issuePreviewSeq += 1;
            clearIssueDuplicateUi();
            updateIssueTitleEnPreview("", "");
            const resultEl = document.getElementById("dcPreviewResult");
            const title = (document.getElementById("dcIssueTitle")?.value || "").trim();
            if (resultEl) {
                resultEl.textContent = title
                    ? "填写完成后移出输入框将预览建议编号"
                    : "填写文件名称后移出输入框将预览建议编号";
            }
            restoreIssueApplyButtonState();
        });
        document.getElementById("dcIssueTitle")?.addEventListener("blur", () => {
            const title = (document.getElementById("dcIssueTitle")?.value || "").trim();
            if (title) refreshIssuePreview();
        });
        document.getElementById("dcIssueConfirmSameBtn")?.addEventListener("click", () => {
            dismissIssueAsSameDocument();
        });
        document.getElementById("dcIssueForceNewBtn")?.addEventListener("click", async () => {
            const cfg = selectedIssueCategory();
            if (!cfg) return;
            issueForceNew = true;
            clearIssueDuplicateUi();
            await withButtonBusy(
                document.getElementById("dcIssueForceNewBtn"),
                "处理中…",
                async () => refreshIssuePreview()
            );
        });
        document.getElementById("dcApplyBtn")?.addEventListener("click", async () => {
            const cfg = selectedIssueCategory();
            const title = (document.getElementById("dcIssueTitle")?.value || "").trim();
            if (!cfg?.sheetCategory || !title) {
                notify("请选择台账分类并填写文件名称", "warning");
                return;
            }
            if (!cfg.autoAllocatable || cfg.disabledReason) {
                notify(cfg.manualHint || cfg.kbRuleExcerpt || "该分类须手工编号", "warning");
                return;
            }
            if (cfg.needsProjectCode && !(document.getElementById("dcIssueProjectCode")?.value || "").trim()) {
                notify("请选择含项目编号的页面1项目", "warning");
                return;
            }
            if (issuePreviewTitle !== title) {
                await refreshIssuePreview();
            }
            if (issueDuplicateState && !issueForceNew) {
                return;
            }
            await submitIssueApply(cfg, null, document.getElementById("dcApplyBtn"));
        });
        document.getElementById("dcIssueBatchPreviewBtn")?.addEventListener("click", () => {
            batchIssuePreview(document.getElementById("dcIssueBatchPreviewBtn"));
        });
        document.getElementById("dcIssueBatchApplyBtn")?.addEventListener("click", () => {
            batchIssueApply(document.getElementById("dcIssueBatchApplyBtn"));
        });
    }

    function bindActions() {
        document.getElementById("dcFilterForm")?.addEventListener("submit", (e) => {
            e.preventDefault();
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
            await withButtonBusy(btn, "更新中…", async () => {
                const res = await req("/api/document-control/schemes/sync-from-kb", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ query: "文件控制程序 编号规则" }),
                });
                notify(res.message || "规则已更新", (res.items || []).length ? "success" : "warning");
                renderSchemes(res.items || []);
                const summaryEl = document.getElementById("dcKbSyncSummary");
                if (summaryEl) {
                    const src = (res.sourceFile || "").trim();
                    summaryEl.textContent = src ? `规则来源：${src}` : "";
                    summaryEl.classList.toggle("d-none", !src);
                }
                const tabBtn = document.getElementById("dc-tab-schemes-btn");
                if (tabBtn) bootstrap.Tab.getOrCreateInstance(tabBtn).show();
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
            const qProjectId = (sp.get("projectId") || "").trim();
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
            await loadIssueOptions(qCategory || "");
            if (qProjectId || qProjectCode) {
                preselectIssueProject(qProjectId, qProjectCode);
            }
            bindActions();
            bindDocModal();
            bindBatchActions();
            bindBatchCreateModal();
            bindCategoryPaginationOnce();
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
