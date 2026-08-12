(function () {
    const PAGE_SIZE = 100;
    let currentPage = 1;

    function getApp() {
        return window.App || null;
    }

    function notify(msg, variant) {
        const App = getApp();
        if (App && App.notify) App.notify(msg, variant || "info");
        else window.alert(msg);
    }

    function esc(text) {
        return String(text == null ? "" : text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function setButtonBusy(btn, busy, busyText) {
        if (!btn) return;
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

    function pageOrgId() {
        const sp = new URLSearchParams(window.location.search || "");
        return (sp.get("organizationId") || "").trim();
    }

    const TYPE_LABEL = {
        import_success: "导入成功",
        import_update: "增量更新",
        import_skip: "跳过",
        import_fail: "失败",
    };

    function formatTime(iso) {
        if (!iso) return "-";
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleString();
    }

    function getFilterParams() {
        const query = new URLSearchParams();
        const batchId = (document.getElementById("defImportBatchId")?.value || "").trim();
        const eventType = (document.getElementById("defImportEventType")?.value || "").trim();
        const orgId = pageOrgId();
        if (orgId) query.set("organizationId", orgId);
        if (batchId) query.set("batchId", batchId);
        if (eventType) query.set("eventType", eventType);
        query.set("page", String(currentPage));
        query.set("pageSize", String(PAGE_SIZE));
        return query;
    }

    function renderBatchSummaries(batches) {
        const body = document.getElementById("defImportBatchSummaryBody");
        const hint = document.getElementById("defImportBatchSummaryHint");
        if (!body) return;
        const list = batches || [];
        if (!list.length) {
            body.innerHTML = '<tr><td colspan="9" class="text-muted p-3">暂无批次汇总</td></tr>';
            if (hint) hint.textContent = "";
            return;
        }
        body.innerHTML = list
            .map(
                (x) => `<tr>
                    <td class="text-nowrap">${formatTime(x.startedAt)}</td>
                    <td><code class="small">${esc(x.batchId || "-")}</code></td>
                    <td class="small">${esc(x.sourceFilename || "-")}</td>
                    <td>${Number(x.total) || 0}</td>
                    <td class="text-success">${Number(x.success) || 0}</td>
                    <td class="text-primary">${Number(x.updated) || 0}</td>
                    <td class="text-warning">${Number(x.skip) || 0}</td>
                    <td class="text-danger">${Number(x.fail) || 0}</td>
                    <td>
                        <button type="button" class="btn btn-link btn-sm p-0 def-batch-filter-btn" data-batch-id="${esc(x.batchId || "")}">只看本批</button>
                    </td>
                </tr>`
            )
            .join("");
        if (hint) {
            const batchFilter = (document.getElementById("defImportBatchId")?.value || "").trim();
            hint.textContent = batchFilter
                ? `共 ${list.length} 个导入批次`
                : `最近 ${list.length} 个导入批次（最多 100 批）`;
        }
    }

    function renderLogRows(rows) {
        const body = document.getElementById("defImportLogsBody");
        if (!body) return;
        const list = rows || [];
        if (!list.length) {
            body.innerHTML = '<tr><td colspan="6" class="text-muted p-3">暂无导入操作日志</td></tr>';
            return;
        }
        body.innerHTML = list
            .map(
                (x) => `<tr>
                    <td class="text-nowrap">${formatTime(x.createdAt)}</td>
                    <td><code class="small">${esc(x.batchId || "-")}</code></td>
                    <td>${TYPE_LABEL[x.eventType] || x.eventType || "-"}</td>
                    <td>${x.rowIndex != null ? esc(String(x.rowIndex)) : "-"}</td>
                    <td class="small">${esc(x.projectName || "-")}</td>
                    <td class="small">${esc(x.reason || "-")}</td>
                </tr>`
            )
            .join("");
    }

    function updatePagination(total, page) {
        const hint = document.getElementById("defImportLogsHint");
        const prevBtn = document.getElementById("defImportLogsPrev");
        const nextBtn = document.getElementById("defImportLogsNext");
        const totalPages = Math.max(1, Math.ceil((Number(total) || 0) / PAGE_SIZE));
        if (hint) {
            hint.textContent = total
                ? `第 ${page} / ${totalPages} 页，共 ${total} 条（每页 ${PAGE_SIZE} 条）`
                : "共 0 条";
        }
        if (prevBtn) prevBtn.disabled = page <= 1;
        if (nextBtn) nextBtn.disabled = page >= totalPages;
    }

    async function loadImportLogs() {
        const body = document.getElementById("defImportLogsBody");
        const batchBody = document.getElementById("defImportBatchSummaryBody");
        if (!body) return;
        const query = getFilterParams();
        body.innerHTML =
            '<tr><td colspan="6" class="text-muted p-3 text-center"><span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>加载中…</td></tr>';
        if (batchBody) {
            batchBody.innerHTML =
                '<tr><td colspan="8" class="text-muted p-3 text-center"><span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>加载中…</td></tr>';
        }
        const res = await req(`/api/company/deficiency/import/logs?${query.toString()}`);
        renderBatchSummaries(res.batches || []);
        renderLogRows(res.items || []);
        updatePagination(res.total || 0, res.page || currentPage);
        currentPage = Number(res.page) || currentPage;
    }

    function bindActions() {
        document.getElementById("defImportLogsBtn")?.addEventListener("click", () => {
            currentPage = 1;
            const btn = document.getElementById("defImportLogsBtn");
            withButtonBusy(btn, "查询中…", () => loadImportLogs());
        });
        document.getElementById("defImportLogsResetBtn")?.addEventListener("click", () => {
            const batchEl = document.getElementById("defImportBatchId");
            const typeEl = document.getElementById("defImportEventType");
            if (batchEl) batchEl.value = "";
            if (typeEl) typeEl.value = "";
            currentPage = 1;
            const btn = document.getElementById("defImportLogsResetBtn");
            withButtonBusy(btn, "重置中…", () => loadImportLogs());
        });
        document.getElementById("defImportLogsPrev")?.addEventListener("click", async () => {
            if (currentPage <= 1) return;
            currentPage -= 1;
            await loadImportLogs();
        });
        document.getElementById("defImportLogsNext")?.addEventListener("click", async () => {
            currentPage += 1;
            await loadImportLogs();
        });
        document.getElementById("defImportBatchSummaryBody")?.addEventListener("click", (e) => {
            const btn = e.target.closest(".def-batch-filter-btn");
            if (!btn) return;
            const batchId = btn.getAttribute("data-batch-id") || "";
            const batchEl = document.getElementById("defImportBatchId");
            if (batchEl) batchEl.value = batchId;
            currentPage = 1;
            loadImportLogs();
        });
    }

    async function boot() {
        try {
            const sp = new URLSearchParams(window.location.search || "");
            const batchId = (sp.get("batchId") || "").trim();
            if (batchId) {
                const el = document.getElementById("defImportBatchId");
                if (el) el.value = batchId;
            }
            bindActions();
            await loadImportLogs();
        } catch (e) {
            notify(e.message || "导入日志加载失败", "danger");
        }
    }

    if (typeof registerPageInit === "function") registerPageInit(boot);
    else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
})();
