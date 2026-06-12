(function () {
    "use strict";

    const MODULE_BY_PATH = {
        "/company": "page0",
        "/upload": "page1_upload",
        "/generate": "page2",
        "/dashboard": "page3",
        "/draft-gen": "page1_draft",
        "/audit": "page1_audit",
        "/audit-modify": "page1_audit_modify",
        "/audit/report-edit": "page1_audit",
        "/translate": "page1_translate",
    };

    const EXAM_CENTER_PREFIX = "/exam-center";

    function detectExamCenterModule() {
        const cx = window.__EXAM_CENTER_CONTEXT__;
        if (cx && cx.role) {
            const r = String(cx.role).toLowerCase().trim();
            if (r === "teacher") return "page1_exam_teacher";
            if (r === "analytics") return "page1_exam_analytics";
            return "page1_exam_student";
        }
        const role = String(new URLSearchParams(window.location.search || "").get("role") || "student")
            .toLowerCase()
            .trim();
        if (role === "teacher") return "page1_exam_teacher";
        if (role === "analytics") return "page1_exam_analytics";
        return "page1_exam_student";
    }

    function appPath(path) {
        const root = (window.__SCRIPT_ROOT__ != null ? String(window.__SCRIPT_ROOT__) : "").replace(/\/+$/, "");
        if (!path.startsWith("/")) path = "/" + path;
        return root ? root + path : path;
    }

    function apiRequest(url, options) {
        if (window.App && typeof window.App.request === "function") {
            return window.App.request(url, options);
        }
        const root = (window.__SCRIPT_ROOT__ != null ? String(window.__SCRIPT_ROOT__) : "").replace(/\/+$/, "");
        if (root && url.startsWith("/") && !url.startsWith(root + "/")) {
            url = root + url;
        }
        return fetch(url, { credentials: "include", ...options }).then(async (res) => {
            const text = await res.text();
            let data = {};
            try {
                data = text ? JSON.parse(text) : {};
            } catch (e) {
                /* ignore */
            }
            if (!res.ok) throw new Error(data.message || `请求失败 (${res.status})`);
            return data;
        });
    }

    function notify(msg, variant) {
        if (window.App && typeof window.App.notify === "function") {
            window.App.notify(msg, variant || "success");
            return;
        }
        window.alert(msg);
    }

    function escapeHtml(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function detectDefaultModule() {
        const path = (window.location.pathname || "").replace(/\/+$/, "") || "/";
        const root = (window.__SCRIPT_ROOT__ || "").replace(/\/+$/, "");
        let rel = path;
        if (root && path.startsWith(root)) {
            rel = path.slice(root.length) || "/";
        }
        if (rel === EXAM_CENTER_PREFIX || rel.startsWith(EXAM_CENTER_PREFIX + "/")) {
            return detectExamCenterModule();
        }
        for (const [prefix, key] of Object.entries(MODULE_BY_PATH)) {
            if (rel === prefix || rel.startsWith(prefix + "/")) return key;
        }
        return "other";
    }

    const TERMINAL_STATUSES = new Set(["resolved", "closed", "wont_fix"]);

    function statusBadgeClass(status) {
        if (status === "resolved") return "bg-success";
        if (status === "processing") return "bg-info text-dark";
        if (status === "closed") return "bg-secondary";
        if (status === "wont_fix") return "bg-dark";
        return "bg-warning text-dark";
    }

    let mineItemsCache = [];

    async function prefillResubmitForm(item) {
        await populateSubmitForm();
        const modSel = document.getElementById("feedbackFeatureModule");
        const priSel = document.getElementById("feedbackPriority");
        const descEl = document.getElementById("feedbackDescription");
        if (!modSel || !priSel || !descEl) return;
        if (modSel.querySelector(`option[value="${item.featureModule}"]`)) {
            modSel.value = item.featureModule;
        }
        if (priSel.querySelector(`option[value="${item.priority}"]`)) {
            priSel.value = item.priority;
        }
        const base = (item.description || "").trim();
        descEl.value = base.startsWith("[跟进反馈]") ? base : `[跟进反馈] ${base}`;
        document.getElementById("feedback-tab-submit-btn")?.click();
        descEl.focus();
    }

    function renderMineItem(item) {
        const shot = item.hasScreenshot
            ? `<div class="mt-2"><a href="${appPath("/api/feedback/" + encodeURIComponent(item.id) + "/screenshot")}" target="_blank" rel="noopener">查看截图</a></div>`
            : (item.screenshotUploadError
                ? `<div class="mt-1 text-warning">截图上传失败：${escapeHtml(item.screenshotUploadError)}</div>`
                : "");
        const resolution = item.resolution
            ? `<div class="mt-2"><strong>处理方案：</strong>${escapeHtml(item.resolution)}</div>`
            : "";
        const resolvedAt = item.resolvedAt
            ? `<div class="text-muted">处理时间：${escapeHtml(item.resolvedAt)}</div>`
            : "";
        const resubmit = item.canResubmit || TERMINAL_STATUSES.has(item.status)
            ? `<button type="button" class="btn btn-sm btn-outline-primary mt-2 feedback-resubmit-btn" data-feedback-id="${escapeHtml(item.id)}">问题仍存在，再次提交</button>`
            : "";
        return `
            <div class="border rounded p-3 mb-2 bg-white">
                <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
                    <div>
                        <span class="badge ${statusBadgeClass(item.status)}">${escapeHtml(item.statusLabel)}</span>
                        <span class="ms-2 fw-semibold">${escapeHtml(item.featureModuleLabel)}</span>
                        <span class="badge bg-light text-dark border ms-1">${escapeHtml(item.priorityLabel)}</span>
                    </div>
                    <div class="text-muted">${escapeHtml(item.createdAt || "")}</div>
                </div>
                <div class="mt-2">${escapeHtml(item.description)}</div>
                ${resolution}
                ${resolvedAt}
                ${shot}
                ${resubmit}
            </div>`;
    }

    let metaCache = null;

    async function loadMeta() {
        if (metaCache) return metaCache;
        metaCache = await apiRequest("/api/feedback/meta");
        return metaCache;
    }

    async function populateSubmitForm() {
        const meta = await loadMeta();
        const modSel = document.getElementById("feedbackFeatureModule");
        const priSel = document.getElementById("feedbackPriority");
        if (!modSel || !priSel) return;

        modSel.innerHTML = (meta.featureModules || [])
            .map((m) => `<option value="${escapeHtml(m.key)}">${escapeHtml(m.label)}</option>`)
            .join("");
        priSel.innerHTML = (meta.priorities || [])
            .map((p) => `<option value="${escapeHtml(p.key)}">${escapeHtml(p.label)}</option>`)
            .join("");

        const def = detectDefaultModule();
        if (modSel.querySelector(`option[value="${def}"]`)) {
            modSel.value = def;
        }
        if (priSel.querySelector('option[value="normal"]')) {
            priSel.value = "normal";
        }
    }

    async function loadMineList() {
        const box = document.getElementById("feedbackMineList");
        if (!box) return;
        box.textContent = "加载中…";
        try {
            const data = await apiRequest("/api/feedback/mine");
            const items = data.items || [];
            mineItemsCache = items;
            if (!items.length) {
                box.innerHTML = '<div class="text-muted">暂无反馈记录</div>';
                return;
            }
            box.innerHTML = items.map(renderMineItem).join("");
        } catch (e) {
            box.innerHTML = `<div class="text-danger">${escapeHtml(e.message || "加载失败")}</div>`;
        }
    }

    function initFeedbackFabDrag(fab) {
        const STORAGE_KEY = "aiword_feedback_fab_pos";
        const DRAG_THRESHOLD = 8;

        function applyPos(left, top) {
            const size = fab.offsetWidth || 56;
            const maxL = Math.max(8, window.innerWidth - size - 8);
            const maxT = Math.max(8, window.innerHeight - size - 8);
            const l = Math.max(8, Math.min(maxL, left));
            const t = Math.max(8, Math.min(maxT, top));
            fab.style.right = "auto";
            fab.style.bottom = "auto";
            fab.style.left = l + "px";
            fab.style.top = t + "px";
            return { left: l, top: t };
        }

        try {
            const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
            if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
                applyPos(saved.left, saved.top);
            }
        } catch (e) {
            /* ignore */
        }

        let dragging = false;
        let moved = false;
        let startX = 0;
        let startY = 0;
        let startLeft = 0;
        let startTop = 0;

        fab.addEventListener("pointerdown", (e) => {
            if (e.button !== undefined && e.button !== 0) return;
            dragging = true;
            moved = false;
            fab.setPointerCapture(e.pointerId);
            const rect = fab.getBoundingClientRect();
            startX = e.clientX;
            startY = e.clientY;
            startLeft = rect.left;
            startTop = rect.top;
            fab.classList.add("feedback-fab-dragging");
        });

        fab.addEventListener("pointermove", (e) => {
            if (!dragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) {
                moved = true;
            }
            applyPos(startLeft + dx, startTop + dy);
        });

        function endDrag(e) {
            if (!dragging) return;
            dragging = false;
            fab.classList.remove("feedback-fab-dragging");
            try {
                fab.releasePointerCapture(e.pointerId);
            } catch (err) {
                /* ignore */
            }
            const rect = fab.getBoundingClientRect();
            localStorage.setItem(STORAGE_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
            fab._feedbackFabMoved = moved;
        }

        fab.addEventListener("pointerup", endDrag);
        fab.addEventListener("pointercancel", endDrag);

        window.addEventListener("resize", () => {
            const rect = fab.getBoundingClientRect();
            const next = applyPos(rect.left, rect.top);
            localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        });
    }

    function initFeedbackFab() {
        const fab = document.getElementById("feedbackFabBtn");
        const modalEl = document.getElementById("feedbackModal");
        if (!fab || !modalEl || !window.bootstrap) return;

        initFeedbackFabDrag(fab);

        const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl);
        fab.addEventListener("click", async () => {
            if (fab._feedbackFabMoved) {
                fab._feedbackFabMoved = false;
                return;
            }
            try {
                await populateSubmitForm();
            } catch (e) {
                notify(e.message || "加载表单失败", "danger");
            }
            modal.show();
        });

        document.getElementById("feedback-tab-mine-btn")?.addEventListener("shown.bs.tab", loadMineList);

        document.getElementById("feedbackMineList")?.addEventListener("click", async (ev) => {
            const btn = ev.target.closest(".feedback-resubmit-btn");
            if (!btn) return;
            const id = btn.getAttribute("data-feedback-id");
            const item = mineItemsCache.find((x) => x.id === id);
            if (!item) return;
            try {
                await prefillResubmitForm(item);
            } catch (e) {
                notify(e.message || "无法打开提交表单", "danger");
            }
        });

        const shotInput = document.getElementById("feedbackScreenshot");
        const previewWrap = document.getElementById("feedbackScreenshotPreview");
        shotInput?.addEventListener("change", () => {
            if (!previewWrap) return;
            const img = previewWrap.querySelector("img");
            const file = shotInput.files && shotInput.files[0];
            if (!file) {
                previewWrap.classList.add("d-none");
                if (img) img.src = "";
                return;
            }
            const url = URL.createObjectURL(file);
            if (img) img.src = url;
            previewWrap.classList.remove("d-none");
        });

        const form = document.getElementById("feedbackSubmitForm");
        form?.addEventListener("submit", async (ev) => {
            ev.preventDefault();
            const btn = document.getElementById("feedbackSubmitBtn");
            if (btn) {
                btn.disabled = true;
                btn.textContent = "提交中…";
            }
            try {
                const fd = new FormData(form);
                await apiRequest("/api/feedback", { method: "POST", body: fd });
                notify("反馈已提交，感谢你的帮助！", "success");
                form.reset();
                previewWrap?.classList.add("d-none");
                const img = previewWrap?.querySelector("img");
                if (img) img.src = "";
                await populateSubmitForm();
                document.getElementById("feedback-tab-mine-btn")?.click();
                await loadMineList();
            } catch (e) {
                notify(e.message || "提交失败", "danger");
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = "提交";
                }
            }
        });
    }

    function renderAdminRow(item) {
        const shot = item.hasScreenshot
            ? `<a href="${appPath("/api/feedback/" + encodeURIComponent(item.id) + "/screenshot")}" target="_blank" rel="noopener" class="small">截图</a>`
            : (item.screenshotUploadError ? `<span class="text-warning small" title="${escapeHtml(item.screenshotUploadError)}">截图失败</span>` : "—");
        const descShort = (item.description || "").length > 120
            ? escapeHtml(item.description.slice(0, 120)) + "…"
            : escapeHtml(item.description);
        return `
            <tr data-feedback-id="${escapeHtml(item.id)}">
                <td class="small text-muted">${escapeHtml(item.createdAt || "")}</td>
                <td class="small">${escapeHtml(item.submitterLabel || item.submitterDisplayName || item.submitterUsername || "—")}</td>
                <td class="small">${escapeHtml(item.featureModuleLabel)}</td>
                <td class="small"><span class="badge bg-light text-dark border">${escapeHtml(item.priorityLabel)}</span></td>
                <td class="small" title="${escapeHtml(item.description)}">${descShort}</td>
                <td class="small">${shot}</td>
                <td class="small">
                    <select class="form-select form-select-sm feedback-admin-status">
                        ${(window.__FEEDBACK_STATUSES__ || []).map((s) =>
                            `<option value="${escapeHtml(s.key)}"${s.key === item.status ? " selected" : ""}>${escapeHtml(s.label)}</option>`
                        ).join("")}
                    </select>
                </td>
                <td class="small">
                    <textarea class="form-control form-control-sm feedback-admin-resolution" rows="2" placeholder="处理方案">${escapeHtml(item.resolution || "")}</textarea>
                    ${item.resolvedAt ? `<div class="text-muted mt-1">处理：${escapeHtml(item.resolvedAt)}</div>` : ""}
                </td>
                <td class="small text-nowrap">
                    <button type="button" class="btn btn-sm btn-primary feedback-admin-save">保存</button>
                    <button type="button" class="btn btn-sm btn-outline-danger feedback-admin-delete ms-1">删除</button>
                </td>
            </tr>`;
    }

    async function loadAdminFeedbackList() {
        const tbody = document.getElementById("adminFeedbackTableBody");
        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="9" class="text-muted text-center small py-3">加载中…</td></tr>';
        try {
            const statusFilter = document.getElementById("adminFeedbackStatusFilter")?.value || "";
            const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
            const data = await apiRequest("/api/feedback" + qs);
            const items = data.items || [];
            if (!items.length) {
                tbody.innerHTML = '<tr><td colspan="9" class="text-muted text-center small py-3">暂无反馈</td></tr>';
                return;
            }
            tbody.innerHTML = items.map(renderAdminRow).join("");
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-danger text-center small py-3">${escapeHtml(e.message || "加载失败")}</td></tr>`;
        }
    }

    function initAdminFeedbackPanel() {
        const root = document.getElementById("adminFeedbackPanel");
        if (!root) return;

        loadMeta().then((meta) => {
            window.__FEEDBACK_STATUSES__ = meta.statuses || [];
        }).catch(() => {});

        document.getElementById("btnRefreshAdminFeedback")?.addEventListener("click", loadAdminFeedbackList);
        document.getElementById("adminFeedbackStatusFilter")?.addEventListener("change", loadAdminFeedbackList);
        document.getElementById("tab-feedback-btn")?.addEventListener("shown.bs.tab", loadAdminFeedbackList);

        root.addEventListener("click", async (ev) => {
            const delBtn = ev.target.closest(".feedback-admin-delete");
            if (delBtn) {
                const tr = delBtn.closest("tr[data-feedback-id]");
                if (!tr) return;
                const id = tr.getAttribute("data-feedback-id");
                if (!window.confirm("确定删除该反馈记录？删除后不可恢复（含 FTP 截图）。")) return;
                delBtn.disabled = true;
                try {
                    await apiRequest(`/api/feedback/${encodeURIComponent(id)}`, { method: "DELETE" });
                    notify("已删除", "success");
                    await loadAdminFeedbackList();
                } catch (e) {
                    notify(e.message || "删除失败", "danger");
                    delBtn.disabled = false;
                }
                return;
            }

            const btn = ev.target.closest(".feedback-admin-save");
            if (!btn) return;
            const tr = btn.closest("tr[data-feedback-id]");
            if (!tr) return;
            const id = tr.getAttribute("data-feedback-id");
            const status = tr.querySelector(".feedback-admin-status")?.value;
            const resolution = tr.querySelector(".feedback-admin-resolution")?.value || "";
            btn.disabled = true;
            try {
                await apiRequest(`/api/feedback/${encodeURIComponent(id)}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ status, resolution }),
                });
                notify("已保存处理结果", "success");
                await loadAdminFeedbackList();
            } catch (e) {
                notify(e.message || "保存失败", "danger");
            } finally {
                btn.disabled = false;
            }
        });
    }

    function boot() {
        initFeedbackFab();
        initAdminFeedbackPanel();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
