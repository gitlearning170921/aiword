(function () {
    const body = document.getElementById("companyProjectsBody");
    const modalEl = document.getElementById("companyProjectModal");
    const batchModalEl = document.getElementById("companyBatchEditModal");
    const linkModalEl = document.getElementById("companyLinkPage1Modal");
    const teamSel = document.getElementById("cpTeamId");
    const batchTeamSel = document.getElementById("batchCpTeamId");
    const teamsDictList = document.getElementById("teamsDictList");
    const dictEditModalEl = document.getElementById("dictEditModal");
    const selectAllCb = document.getElementById("companyProjectSelectAll");
    const btnBatchEdit = document.getElementById("btnBatchEditCompanyProjects");
    const btnBatchRemove = document.getElementById("btnBatchRemoveCompanyProjects");
    let teams = [];
    let projectsCache = [];
    const GROUP_BY_STORAGE_KEY = "companyRegistryGroupBy";
    const STAR_FILTER_STORAGE_KEY = "companyRegistryStarFilter";
    const canOverridePage1Lock = !!window.__PAGE13_SUPER_ADMIN__;
    const TEAM_LOCK_HINT =
        "页面1 已下发任务，公司管理员不可修改所属项目组；仅超级管理员（页面1·3 访问密码）可改。";
    const STATUS_LOCK_HINT =
        "页面1 已下发任务，公司管理员不可在页面0 修改项目状态；请由项目管理员在页面1 修改，或联系超级管理员。";

    const COLS = 14;
    const EMPTY_COUNTRY_LABEL = "（未填写注册国家）";
    const EMPTY_PRODUCT_TYPE_LABEL = "（未填写产品类型）";
    let registeredCountriesDict = [];
    let registeredCountriesDictFull = [];

    function esc(s) {
        const d = document.createElement("div");
        d.textContent = s == null ? "" : String(s);
        return d.innerHTML;
    }

    function getApp() {
        return window.App || null;
    }

    function notify(msg, variant) {
        const App = getApp();
        if (App && App.notify) App.notify(msg, variant);
        else window.alert(msg);
    }

    async function apiRequest(url, options) {
        const App = getApp();
        if (!App || !App.request) {
            throw new Error("页面脚本未就绪，请刷新后重试");
        }
        return App.request(url, options);
    }

    function normalizeProjectsResponse(res) {
        if (Array.isArray(res)) {
            return { projects: res, synced: 0, total: res.length };
        }
        return {
            projects: Array.isArray(res?.projects) ? res.projects : [],
            synced: Number(res?.synced) || 0,
            total: Number(res?.total) || (Array.isArray(res?.projects) ? res.projects.length : 0),
        };
    }

    function selectedProjectIds() {
        if (!body) return [];
        return [...body.querySelectorAll(".cp-row-checkbox:checked")]
            .map((cb) => cb.dataset.id)
            .filter(Boolean);
    }

    function isPage1TasksLocked(project) {
        if (!project || canOverridePage1Lock) return false;
        return !!(
            project.page1UploadTasksLocked ||
            project.assignedTeamIdLocked ||
            project.projectStatusLocked ||
            project.page1HasUploadTasks
        );
    }

    function applyFieldLock(sel, locked, hintEl, hintText) {
        if (!sel) return;
        sel.disabled = !!locked;
        if (hintEl) {
            if (locked) {
                hintEl.textContent = hintText || "";
                hintEl.classList.remove("d-none");
            } else {
                hintEl.textContent = "";
                hintEl.classList.add("d-none");
            }
        }
    }

    function selectedHasPage1TasksLock() {
        const ids = new Set(selectedProjectIds());
        return projectsCache.some((p) => ids.has(p.id) && isPage1TasksLocked(p));
    }

    function updateBatchButtons() {
        const n = selectedProjectIds().length;
        if (btnBatchEdit) btnBatchEdit.disabled = n === 0;
        if (btnBatchRemove) btnBatchRemove.disabled = n === 0;
        const hint = document.getElementById("companyBatchEditHint");
        if (hint) hint.textContent = `已选 ${n} 项；留空表示不修改该字段。`;
    }

    function fillTeamSelect(sel, includeNoChange, includeClear) {
        if (!sel) return;
        const keep = sel.value;
        sel.innerHTML = "";
        if (includeNoChange) {
            const o0 = document.createElement("option");
            o0.value = "";
            o0.textContent = "— 不修改 —";
            sel.appendChild(o0);
        } else {
            const o0 = document.createElement("option");
            o0.value = "";
            o0.textContent = "— 未分配 —";
            sel.appendChild(o0);
        }
        if (includeClear) {
            const ox = document.createElement("option");
            ox.value = "__none__";
            ox.textContent = "— 取消分配 —";
            sel.appendChild(ox);
        }
        (teams || []).forEach((t) => {
            if (t.isActive === false) return;
            const o = document.createElement("option");
            o.value = t.id;
            o.textContent = t.name;
            sel.appendChild(o);
        });
        if (keep) sel.value = keep;
    }

    async function loadRegisteredCountriesDict() {
        try {
            const res = await apiRequest("/api/company/registered-countries");
            registeredCountriesDictFull = Array.isArray(res?.countries) ? res.countries : [];
            registeredCountriesDict = registeredCountriesDictFull
                .filter((c) => c.isActive !== false)
                .map((c) => c.name)
                .filter(Boolean);
        } catch (_) {
            registeredCountriesDictFull = [];
            registeredCountriesDict = [];
        }
        fillCpCountrySelect("");
        renderDictItemList(
            document.getElementById("countryDictList"),
            registeredCountriesDictFull,
            "country"
        );
    }

    function dictUsageLabel(item) {
        const u = item?.usage || {};
        const parts = [];
        if (u.companyProjects) parts.push(`总览${u.companyProjects}`);
        if (u.projects) parts.push(`页面1 ${u.projects}`);
        if (u.userScopes) parts.push(`账号${u.userScopes}`);
        if (u.userMemberships) parts.push(`账号${u.userMemberships}`);
        return parts.length ? parts.join(" · ") : "";
    }

    function renderDictItemList(ul, items, kind) {
        if (!ul) return;
        const rows = (items || []).filter((x) => x.isActive !== false);
        if (!rows.length) {
            ul.innerHTML =
                '<li class="list-group-item text-muted">暂无字典项，请在上方添加</li>';
            return;
        }
        ul.innerHTML = rows
            .map((item) => {
                const usageText = dictUsageLabel(item);
                const usageBadge =
                    item.usageCount > 0
                        ? `<span class="badge bg-secondary dict-usage-badge" title="${esc(usageText)}">已引用 ${item.usageCount}</span>`
                        : '<span class="badge bg-light text-muted dict-usage-badge">未引用</span>';
                const delDisabled = item.canDelete === false ? " disabled" : "";
                const delTitle = item.canDelete === false
                    ? ` title="${esc(usageText ? `已绑定：${usageText}` : "已有绑定数据，不可删除")}"`
                    : "";
                return `<li class="list-group-item dict-item-row d-flex justify-content-between align-items-center flex-wrap">
                    <div class="d-flex align-items-center gap-2 flex-wrap">
                        <span class="fw-medium">${esc(item.name)}</span>
                        ${usageBadge}
                    </div>
                    <div class="dict-item-actions btn-group btn-group-sm">
                        <button type="button" class="btn btn-outline-secondary btn-dict-edit" data-kind="${esc(kind)}" data-id="${esc(item.id)}" data-name="${esc(item.name)}">编辑</button>
                        <button type="button" class="btn btn-outline-danger btn-dict-delete"${delDisabled}${delTitle} data-kind="${esc(kind)}" data-id="${esc(item.id)}" data-name="${esc(item.name)}">删除</button>
                    </div>
                </li>`;
            })
            .join("");
        ul.querySelectorAll(".btn-dict-edit").forEach((btn) => {
            btn.addEventListener("click", () => {
                openDictEditModal(btn.dataset.kind, btn.dataset.id, btn.dataset.name);
            });
        });
        ul.querySelectorAll(".btn-dict-delete").forEach((btn) => {
            btn.addEventListener("click", async () => {
                if (btn.disabled) return;
                const { kind, id, name } = btn.dataset;
                if (!id || !window.confirm(`确定删除「${name || ""}」？`)) return;
                try {
                    const url =
                        kind === "country"
                            ? `/api/company/registered-countries/${id}`
                            : `/api/teams/${id}`;
                    await apiRequest(url, { method: "DELETE" });
                    notify("已删除", "success");
                    if (kind === "country") await loadRegisteredCountriesDict();
                    else await loadTeams();
                } catch (e) {
                    notify(e.message || "删除失败", "danger");
                }
            });
        });
    }

    function openDictEditModal(kind, id, name) {
        if (!dictEditModalEl) return;
        document.getElementById("dictEditKind").value = kind || "";
        document.getElementById("dictEditId").value = id || "";
        document.getElementById("dictEditName").value = name || "";
        const title = document.getElementById("dictEditModalTitle");
        const label = document.getElementById("dictEditNameLabel");
        if (kind === "country") {
            if (title) title.textContent = "编辑注册国家";
            if (label) label.textContent = "注册国家名称";
        } else {
            if (title) title.textContent = "编辑项目组";
            if (label) label.textContent = "项目组名称";
        }
        bootstrap.Modal.getOrCreateInstance(dictEditModalEl).show();
    }

    function fillCpCountrySelect(value) {
        const sel = document.getElementById("cpCountry");
        if (!sel) return;
        const v = (value || "").trim();
        sel.innerHTML = '<option value="">—</option>';
        registeredCountriesDict.forEach((name) => {
            const o = document.createElement("option");
            o.value = name;
            o.textContent = name;
            sel.appendChild(o);
        });
        sel.value = v;
    }

    async function loadTeams() {
        try {
            const res = await apiRequest("/api/teams");
            teams = Array.isArray(res) ? res : res?.teams || [];
        } catch (e) {
            teams = [];
            if (teamsDictList) {
                teamsDictList.innerHTML = `<li class="list-group-item text-warning small">${esc(e.message || "项目组加载失败")}</li>`;
            }
            return;
        }
        fillTeamSelect(teamSel, false, false);
        fillTeamSelect(batchTeamSel, true, true);
        renderDictItemList(teamsDictList, teams, "team");
    }

    function openModal(project) {
        document.getElementById("cpEditId").value = project?.id || "";
        document.getElementById("companyProjectModalTitle").textContent = project?.id ? "编辑项目" : "登记新项目";
        document.getElementById("cpName").value = project?.name || "";
        document.getElementById("cpProductType").value = project?.productType || "";
        fillCpCountrySelect(project?.registeredCountry || "");
        document.getElementById("cpCategory").value = project?.registeredCategory || "";
        document.getElementById("cpTeamId").value = project?.assignedTeamId || "";
        const locked = isPage1TasksLocked(project);
        applyFieldLock(teamSel, locked, document.getElementById("cpTeamLockHint"), TEAM_LOCK_HINT);
        document.getElementById("cpPriority").value = String(project?.priority ?? 2);
        document.getElementById("cpStatus").value = project?.status || "active";
        applyFieldLock(
            document.getElementById("cpStatus"),
            locked,
            document.getElementById("cpStatusLockHint"),
            STATUS_LOCK_HINT
        );
        document.getElementById("cpCertDate").value = project?.expectedCertificationDate || "";
        document.getElementById("cpSubmitDate").value = project?.expectedSubmissionDate || "";
        document.getElementById("cpProgress").value = project?.progressDescription || "";
        const ownerEl = document.getElementById("cpRegistrationOwner");
        if (ownerEl) ownerEl.value = project?.registrationOwner || "";
        const starredCb = document.getElementById("cpStarred");
        if (starredCb) starredCb.checked = !!project?.isStarred;
        if (modalEl) new bootstrap.Modal(modalEl).show();
    }

    function payloadFromForm() {
        const payload = {
            name: (document.getElementById("cpName").value || "").trim(),
            productType: (document.getElementById("cpProductType").value || "").trim() || null,
            registeredCountry: (document.getElementById("cpCountry")?.value || "").trim() || null,
            registeredCategory: (document.getElementById("cpCategory").value || "").trim() || null,
            priority: Number(document.getElementById("cpPriority").value) || 2,
            expectedCertificationDate: document.getElementById("cpCertDate").value || null,
            expectedSubmissionDate: document.getElementById("cpSubmitDate").value || null,
            progressDescription: (document.getElementById("cpProgress").value || "").trim() || null,
            registrationOwner: (document.getElementById("cpRegistrationOwner")?.value || "").trim() || null,
            isStarred: !!document.getElementById("cpStarred")?.checked,
        };
        const editId = (document.getElementById("cpEditId")?.value || "").trim();
        const editing = editId
            ? projectsCache.find((x) => x.id === editId)
            : null;
        if (!isPage1TasksLocked(editing)) {
            payload.assignedTeamId = document.getElementById("cpTeamId").value || null;
            payload.status = document.getElementById("cpStatus").value || "active";
        }
        return payload;
    }

    async function saveRegistrationOwner(id, value) {
        try {
            const res = await apiRequest(`/api/company/projects/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    registrationOwner: (value || "").trim() || null,
                }),
            });
            const item = projectsCache.find((x) => x.id === id);
            if (item) item.registrationOwner = (value || "").trim() || null;
            if (res?.project) {
                const idx = projectsCache.findIndex((x) => x.id === id);
                if (idx >= 0) projectsCache[idx] = res.project;
            }
            notify("注册负责人已保存", "success");
        } catch (e) {
            notify(e.message || "保存失败", "danger");
            renderProjects(projectsCache);
        }
    }

    function getStarFilterMode() {
        const sel = document.getElementById("companyProjectStarFilter");
        return (sel?.value || "all") === "starred" ? "starred" : "all";
    }

    function initStarFilterSelect() {
        const sel = document.getElementById("companyProjectStarFilter");
        if (!sel) return;
        try {
            const saved = localStorage.getItem(STAR_FILTER_STORAGE_KEY);
            if (saved && [...sel.options].some((o) => o.value === saved)) {
                sel.value = saved;
            }
        } catch (_) { /* ignore */ }
        sel.addEventListener("change", () => {
            try {
                localStorage.setItem(STAR_FILTER_STORAGE_KEY, sel.value);
            } catch (_) { /* ignore */ }
            renderProjects(projectsCache);
        });
    }

    function prepareRowsForDisplay(rows) {
        let list = [...(rows || [])];
        if (getStarFilterMode() === "starred") {
            list = list.filter((p) => !!p.isStarred);
        }
        list.sort((a, b) => {
            const sa = a.isStarred ? 1 : 0;
            const sb = b.isStarred ? 1 : 0;
            if (sa !== sb) return sb - sa;
            const pa = Number(a.priority) || 0;
            const pb = Number(b.priority) || 0;
            if (pa !== pb) return pb - pa;
            return String(a.name || "").localeCompare(String(b.name || ""), "zh-CN");
        });
        return list;
    }

    async function setProjectStarred(id, starred) {
        try {
            const res = await apiRequest(`/api/company/projects/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ isStarred: !!starred }),
            });
            const item = projectsCache.find((x) => x.id === id);
            if (item) item.isStarred = !!starred;
            if (res?.project) {
                const idx = projectsCache.findIndex((x) => x.id === id);
                if (idx >= 0) projectsCache[idx] = res.project;
            }
            renderProjects(projectsCache);
            notify(starred ? "已设为特别关注" : "已取消特别关注", "success");
        } catch (e) {
            notify(e.message || "操作失败", "danger");
        }
    }

    async function openLinkModal(companyProject) {
        const cid = companyProject?.id;
        if (!cid) return;
        document.getElementById("linkPage1CompanyId").value = cid;
        const title = document.getElementById("companyLinkPage1ModalTitle");
        if (title) title.textContent = `关联页面1 项目 · ${companyProject.name || ""}`;
        const box = document.getElementById("linkPage1Candidates");
        if (box) box.innerHTML = '<div class="text-muted small">加载中…</div>';
        if (linkModalEl) new bootstrap.Modal(linkModalEl).show();
        try {
            const candidates = await apiRequest("/api/company/page1-project-candidates");
            const linkedIds = new Set(
                (companyProject.linkedPage1Projects || []).map((x) => x.id)
            );
            if (!Array.isArray(candidates) || !candidates.length) {
                if (box) box.innerHTML = '<div class="text-muted small">暂无页面1 项目，请先在页面1 创建。</div>';
                return;
            }
            if (box) {
                box.innerHTML = candidates.map((c) => {
                    const checked = linkedIds.has(c.id) ? " checked" : "";
                    const bound = c.companyProjectId && c.companyProjectId !== cid
                        ? ` <span class="text-warning">(已属其它总览)</span>` : "";
                    return `<label class="d-block small mb-1">
                        <input type="checkbox" class="form-check-input link-page1-cb me-1" value="${esc(c.id)}"${checked}>
                        ${esc(c.projectKey || c.name)}${bound}
                    </label>`;
                }).join("");
            }
        } catch (e) {
            if (box) box.innerHTML = `<div class="text-danger small">${esc(e.message || "加载失败")}</div>`;
        }
    }

    async function removeFromRegistry(ids, confirmMsg) {
        if (!ids.length) {
            notify("请先勾选项目", "warning");
            return;
        }
        if (!window.confirm(confirmMsg)) return;
        try {
            let res;
            if (ids.length === 1) {
                res = await apiRequest(`/api/company/projects/${ids[0]}`, { method: "DELETE" });
            } else {
                res = await apiRequest("/api/company/projects/remove-from-registry", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ projectIds: ids }),
                });
            }
            notify(res.message || "已移出", "success");
            if (selectAllCb) selectAllCb.checked = false;
            await loadProjects(false);
        } catch (e) {
            notify(e.message || "操作失败", "danger");
        }
    }

    function getGroupByMode() {
        const sel = document.getElementById("companyProjectGroupBy");
        const v = (sel?.value || "none").trim();
        if (v === "country" || v === "productType" || v === "country_productType") return v;
        return "none";
    }

    function initGroupBySelect() {
        const sel = document.getElementById("companyProjectGroupBy");
        if (!sel) return;
        try {
            const saved = localStorage.getItem(GROUP_BY_STORAGE_KEY);
            if (saved && [...sel.options].some((o) => o.value === saved)) {
                sel.value = saved;
            }
        } catch (_) { /* ignore */ }
        sel.addEventListener("change", () => {
            try {
                localStorage.setItem(GROUP_BY_STORAGE_KEY, sel.value);
            } catch (_) { /* ignore */ }
            renderProjects(projectsCache);
        });
    }

    function groupLabel(value, emptyLabel) {
        const s = (value == null ? "" : String(value)).trim();
        return s || emptyLabel;
    }

    function sortGroupKeys(keys, emptyLabels) {
        const emptySet = new Set(emptyLabels);
        const rest = keys.filter((k) => !emptySet.has(k));
        const empty = keys.filter((k) => emptySet.has(k));
        rest.sort((a, b) => a.localeCompare(b, "zh-CN"));
        return [...rest, ...empty];
    }

    function bucketBy(rows, keyFn) {
        const map = new Map();
        rows.forEach((p) => {
            const k = keyFn(p);
            if (!map.has(k)) map.set(k, []);
            map.get(k).push(p);
        });
        return map;
    }

    function buildDisplayGroups(rows, mode) {
        if (mode === "none" || !rows.length) {
            return [{ rows }];
        }
        if (mode === "country") {
            const map = bucketBy(rows, (p) => groupLabel(p.registeredCountry, EMPTY_COUNTRY_LABEL));
            return sortGroupKeys([...map.keys()], [EMPTY_COUNTRY_LABEL]).map((k) => ({
                header: { level: 1, title: "注册国家", label: k, count: map.get(k).length },
                rows: map.get(k),
            }));
        }
        if (mode === "productType") {
            const map = bucketBy(rows, (p) => groupLabel(p.productType, EMPTY_PRODUCT_TYPE_LABEL));
            return sortGroupKeys([...map.keys()], [EMPTY_PRODUCT_TYPE_LABEL]).map((k) => ({
                header: { level: 1, title: "产品类型", label: k, count: map.get(k).length },
                rows: map.get(k),
            }));
        }
        const countryMap = bucketBy(rows, (p) => groupLabel(p.registeredCountry, EMPTY_COUNTRY_LABEL));
        return sortGroupKeys([...countryMap.keys()], [EMPTY_COUNTRY_LABEL]).map((countryKey) => {
            const inCountry = countryMap.get(countryKey);
            const ptMap = bucketBy(inCountry, (p) => groupLabel(p.productType, EMPTY_PRODUCT_TYPE_LABEL));
            const subgroups = sortGroupKeys([...ptMap.keys()], [EMPTY_PRODUCT_TYPE_LABEL]).map((ptKey) => ({
                header: { level: 2, title: "产品类型", label: ptKey, count: ptMap.get(ptKey).length },
                rows: ptMap.get(ptKey),
            }));
            return {
                header: {
                    level: 1,
                    title: "注册国家",
                    label: countryKey,
                    count: inCountry.length,
                },
                subgroups,
            };
        });
    }

    function renderGroupHeaderRow(header) {
        const indent = header.level === 2 ? " ps-4" : "";
        const badge = `<span class="text-muted fw-normal ms-1">(${header.count})</span>`;
        return `<tr class="cp-group-header table-secondary">
            <td colspan="${COLS}" class="small fw-semibold${indent}">${esc(header.title)}：${esc(header.label)}${badge}</td>
        </tr>`;
    }

    function renderStarCell(p) {
        const on = !!p.isStarred;
        const cls = on ? "text-warning" : "text-muted";
        const sym = on ? "★" : "☆";
        const title = on ? "取消特别关注" : "设为特别关注";
        return `<button type="button" class="btn btn-link btn-sm p-0 cp-star-btn ${cls}" data-id="${esc(p.id)}" data-starred="${on ? "1" : "0"}" title="${title}" aria-label="${title}">${sym}</button>`;
    }

    function renderProjectRow(p) {
        const rowCls = p.isStarred ? " cp-row-starred" : "";
        return `<tr data-project-id="${esc(p.id)}" class="${rowCls.trim()}">
                <td class="text-center">${renderStarCell(p)}</td>
                <td><input type="checkbox" class="form-check-input cp-row-checkbox" data-id="${esc(p.id)}"></td>
                <td>${esc(p.name)}</td>
                <td>${esc(p.productType || "—")}</td>
                <td class="small">${esc(p.registeredCountry || "—")} / ${esc(p.registeredCategory || "—")}</td>
                <td>
                    <input type="text" class="form-control form-control-sm cp-registration-owner-input"
                           data-id="${esc(p.id)}" value="${esc(p.registrationOwner || "")}" placeholder="—">
                </td>
                <td>${esc(p.assignedTeamName || "—")}${
                    isPage1TasksLocked(p)
                        ? ' <span class="badge bg-warning text-dark" title="' +
                          esc(TEAM_LOCK_HINT) +
                          '">已锁定</span>'
                        : ""
                }</td>
                <td>${esc(p.priorityLabel || p.priority)}</td>
                <td>${esc(p.statusLabel || p.status)}${
                    isPage1TasksLocked(p)
                        ? ' <span class="badge bg-warning text-dark" title="' +
                          esc(STATUS_LOCK_HINT) +
                          '">状态锁定</span>'
                        : ""
                }</td>
                <td class="small">${esc(p.expectedCertificationDate || "—")}</td>
                <td class="small">${esc(p.expectedSubmissionDate || "—")}</td>
                <td class="small text-truncate" style="max-width:200px" title="${esc(p.progressDescription || "")}">${esc(p.progressDescription || "—")}</td>
                <td class="small">${Number(p.linkedPage1Count) || 0} 个</td>
                <td class="text-nowrap">
                    <button type="button" class="btn btn-sm btn-outline-secondary btn-link-cp" data-id="${esc(p.id)}">关联</button>
                    <button type="button" class="btn btn-sm btn-outline-primary btn-edit-cp" data-id="${esc(p.id)}">编辑</button>
                    <button type="button" class="btn btn-sm btn-outline-danger btn-remove-cp" data-id="${esc(p.id)}">移出</button>
                </td>
            </tr>`;
    }

    function bindProjectRowActions() {
        if (!body) return;
        body.querySelectorAll(".cp-star-btn").forEach((btn) => {
            btn.addEventListener("click", (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                const id = btn.dataset.id;
                if (!id) return;
                const next = btn.dataset.starred !== "1";
                setProjectStarred(id, next);
            });
        });
        body.querySelectorAll(".cp-registration-owner-input").forEach((inp) => {
            let valueOnFocus = inp.value;
            inp.addEventListener("focus", () => {
                valueOnFocus = inp.value;
            });
            inp.addEventListener("blur", () => {
                const id = inp.dataset.id;
                if (!id) return;
                if ((inp.value || "").trim() === (valueOnFocus || "").trim()) return;
                saveRegistrationOwner(id, inp.value);
            });
            inp.addEventListener("keydown", (ev) => {
                if (ev.key === "Enter") {
                    ev.preventDefault();
                    inp.blur();
                }
            });
        });
        body.querySelectorAll(".cp-row-checkbox").forEach((cb) => {
            cb.addEventListener("change", updateBatchButtons);
        });
        body.querySelectorAll(".btn-link-cp").forEach((btn) => {
            btn.addEventListener("click", () => {
                const p = projectsCache.find((x) => x.id === btn.dataset.id);
                if (p) openLinkModal(p);
            });
        });
        body.querySelectorAll(".btn-edit-cp").forEach((btn) => {
            btn.addEventListener("click", () => {
                const p = projectsCache.find((x) => x.id === btn.dataset.id);
                if (p) openModal(p);
            });
        });
        body.querySelectorAll(".btn-remove-cp").forEach((btn) => {
            btn.addEventListener("click", () => {
                removeFromRegistry(
                    [btn.dataset.id],
                    "确定移出该公司总览记录？\n仅删除公司层数据并解除与页面1 的关联，页面1/2/3 的项目与任务均保留。"
                );
            });
        });
    }

    function renderProjects(rows) {
        if (!body) return;
        projectsCache = rows || [];
        if (selectAllCb) selectAllCb.checked = false;
        updateBatchButtons();
        const displayRows = prepareRowsForDisplay(projectsCache);
        if (!displayRows.length) {
            const hint = getStarFilterMode() === "starred"
                ? "暂无特别关注项目。点击列表左侧 ☆ 可标记关注。"
                : "暂无项目。可点击「登记新项目」，或先在页面1 创建项目后点「同步已有项目」。";
            body.innerHTML = `<tr><td colspan="${COLS}" class="text-muted small p-3">${esc(hint)}</td></tr>`;
            return;
        }
        const mode = getGroupByMode();
        const groups = buildDisplayGroups(displayRows, mode);
        const parts = [];
        groups.forEach((g) => {
            if (g.header) parts.push(renderGroupHeaderRow(g.header));
            if (g.subgroups) {
                g.subgroups.forEach((sg) => {
                    parts.push(renderGroupHeaderRow(sg.header));
                    (sg.rows || []).forEach((p) => parts.push(renderProjectRow(p)));
                });
            } else {
                (g.rows || []).forEach((p) => parts.push(renderProjectRow(p)));
            }
        });
        body.innerHTML = parts.join("");
        bindProjectRowActions();
    }

    async function loadProjects(syncLegacy) {
        if (!body) return;
        body.innerHTML = `<tr><td colspan="${COLS}" class="text-muted small p-3">加载中…</td></tr>`;
        try {
            const q = syncLegacy ? "?syncLegacy=1" : "";
            const res = await apiRequest(`/api/company/projects${q}`);
            const { projects, synced } = normalizeProjectsResponse(res);
            renderProjects(projects);
            if (synced > 0) {
                notify(`已从页面1 同步 ${synced} 个已有项目，可直接编辑`, "success");
            }
        } catch (e) {
            body.innerHTML = `<tr><td colspan="${COLS}" class="text-danger small p-3">${esc(e.message || "加载失败")} <button type="button" class="btn btn-link btn-sm p-0" id="btnRetryLoadProjects">重试</button></td></tr>`;
            document.getElementById("btnRetryLoadProjects")?.addEventListener("click", () => loadProjects(true));
        }
    }

    function bindEvents() {
        selectAllCb?.addEventListener("change", () => {
            const on = !!selectAllCb.checked;
            body?.querySelectorAll(".cp-row-checkbox").forEach((cb) => { cb.checked = on; });
            updateBatchButtons();
        });

        const batchPtEnable = document.getElementById("batchCpProductTypeEnable");
        const batchPtInput = document.getElementById("batchCpProductType");
        batchPtEnable?.addEventListener("change", () => {
            if (batchPtInput) {
                batchPtInput.disabled = !batchPtEnable.checked;
                if (!batchPtEnable.checked) batchPtInput.value = "";
            }
        });

        btnBatchEdit?.addEventListener("click", () => {
            const ids = selectedProjectIds();
            if (!ids.length) return;
            document.getElementById("batchCpPriority").value = "";
            document.getElementById("batchCpStatus").value = "";
            if (batchTeamSel) batchTeamSel.value = "";
            const batchLocked = selectedHasPage1TasksLock();
            applyFieldLock(batchTeamSel, batchLocked, document.getElementById("batchCpTeamLockHint"), TEAM_LOCK_HINT);
            applyFieldLock(
                document.getElementById("batchCpStatus"),
                batchLocked,
                document.getElementById("batchCpStatusLockHint"),
                STATUS_LOCK_HINT
            );
            if (batchPtEnable) batchPtEnable.checked = false;
            if (batchPtInput) {
                batchPtInput.value = "";
                batchPtInput.disabled = true;
            }
            const batchStarSel = document.getElementById("batchCpStarred");
            if (batchStarSel) batchStarSel.value = "";
            updateBatchButtons();
            if (batchModalEl) new bootstrap.Modal(batchModalEl).show();
        });

        document.getElementById("btnApplyCompanyBatchEdit")?.addEventListener("click", async () => {
            const ids = selectedProjectIds();
            if (!ids.length) return;
            const payload = { projectIds: ids };
            const pr = document.getElementById("batchCpPriority")?.value;
            const st = document.getElementById("batchCpStatus")?.value;
            const tid = batchTeamSel?.value;
            if (pr !== "") payload.priority = Number(pr);
            if (st !== "" && !selectedHasPage1TasksLock()) {
                payload.status = st;
            } else if (st !== "" && selectedHasPage1TasksLock()) {
                notify(STATUS_LOCK_HINT, "warning");
                return;
            }
            if (tid !== "" && !selectedHasPage1TasksLock()) {
                payload.assignedTeamId = tid === "__none__" ? null : tid;
            } else if (tid !== "" && selectedHasPage1TasksLock()) {
                notify(TEAM_LOCK_HINT, "warning");
                return;
            }
            if (batchPtEnable?.checked) {
                payload.productType = (batchPtInput?.value || "").trim() || null;
            }
            const batchStar = document.getElementById("batchCpStarred")?.value;
            if (batchStar !== "") payload.isStarred = batchStar === "1";
            if (Object.keys(payload).length <= 1) {
                notify("请至少选择一项要修改的字段", "warning");
                return;
            }
            try {
                const res = await apiRequest("/api/company/projects/batch", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                bootstrap.Modal.getInstance(batchModalEl)?.hide();
                notify(res.message || "已更新", "success");
                if (selectAllCb) selectAllCb.checked = false;
                await loadProjects(false);
            } catch (e) {
                notify(e.message || "批量更新失败", "danger");
            }
        });

        btnBatchRemove?.addEventListener("click", () => {
            const ids = selectedProjectIds();
            removeFromRegistry(
                ids,
                `确定将选中的 ${ids.length} 条公司总览记录移出？\n仅解除关联，页面1/2/3 数据均保留。`
            );
        });

        document.getElementById("btnRefreshCompanyProjects")?.addEventListener("click", () => loadProjects(false));
        document.getElementById("btnSyncLegacyProjects")?.addEventListener("click", async () => {
            try {
                const res = await apiRequest("/api/company/projects/sync-legacy", { method: "POST" });
                notify(res.message || "已同步", "success");
                await loadProjects(false);
            } catch (e) {
                notify(e.message || "同步失败", "danger");
            }
        });
        document.getElementById("btnNewCompanyProject")?.addEventListener("click", () => openModal(null));
        body?.addEventListener("change", (ev) => {
            if (ev.target && ev.target.classList.contains("cp-row-checkbox")) {
                updateBatchButtons();
            }
        });
        document.getElementById("btnSaveCompanyProject")?.addEventListener("click", async () => {
            const payload = payloadFromForm();
            if (!payload.name) {
                notify("请填写项目名称", "warning");
                return;
            }
            const id = (document.getElementById("cpEditId").value || "").trim();
            try {
                if (id) {
                    await apiRequest(`/api/company/projects/${id}`, {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                } else {
                    await apiRequest("/api/company/projects", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                }
                bootstrap.Modal.getInstance(modalEl)?.hide();
                notify("已保存", "success");
                await loadProjects(false);
            } catch (e) {
                notify(e.message || "保存失败", "danger");
            }
        });
        document.getElementById("btnSavePage1Links")?.addEventListener("click", async () => {
            const cid = (document.getElementById("linkPage1CompanyId")?.value || "").trim();
            if (!cid) return;
            const ids = [...document.querySelectorAll(".link-page1-cb:checked")].map((el) => el.value);
            try {
                const res = await apiRequest(`/api/company/projects/${cid}/page1-links`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ page1ProjectIds: ids }),
                });
                bootstrap.Modal.getInstance(linkModalEl)?.hide();
                notify(res.message || "已保存关联", "success");
                await loadProjects(false);
            } catch (e) {
                notify(e.message || "保存关联失败", "danger");
            }
        });

        document.getElementById("btnAddTeam")?.addEventListener("click", async () => {
            const name = (document.getElementById("newTeamName").value || "").trim();
            if (!name) {
                notify("请输入组名", "warning");
                return;
            }
            try {
                await apiRequest("/api/teams", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name }),
                });
                document.getElementById("newTeamName").value = "";
                await loadTeams();
                notify("已添加", "success");
            } catch (e) {
                notify(e.message || "添加失败", "danger");
            }
        });
    }

    async function initCompanySessionBar() {
        const info = document.getElementById("companyUserInfo");
        const logoutBtn = document.getElementById("companyLogoutBtn");
        try {
            const me = await apiRequest("/api/me");
            if (!me?.loggedIn) {
                window.location.href = `${(window.__SCRIPT_ROOT__ || "").replace(/\/+$/, "")}/login?next=${encodeURIComponent("/company")}`;
                return;
            }
            if (me.user?.adminRole !== "company") {
                notify("仅公司管理员可访问本页", "danger");
                return;
            }
            const u = me.user || {};
            const countries = (u.registeredCountries || []).join("、");
            if (info) {
                info.textContent = `${u.displayName || u.username || ""}${countries ? " · " + countries : ""}`;
            }
        } catch (e) {
            if ((e.message || "").includes("登录")) return;
            if (info) info.textContent = "";
        }
        logoutBtn?.addEventListener("click", async () => {
            try {
                await apiRequest("/api/logout", { method: "POST" });
            } catch (_) { /* ignore */ }
            window.location.href = `${(window.__SCRIPT_ROOT__ || "").replace(/\/+$/, "")}/login?next=${encodeURIComponent("/company")}`;
        });
    }

    function bindDictMaintenanceEvents() {
        document.getElementById("btnAddCountryDict")?.addEventListener("click", async () => {
            const name = (document.getElementById("newCountryDictName")?.value || "").trim();
            if (!name) {
                notify("请输入国家名称", "warning");
                return;
            }
            try {
                await apiRequest("/api/company/registered-countries", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name }),
                });
                document.getElementById("newCountryDictName").value = "";
                notify("已添加", "success");
                await loadRegisteredCountriesDict();
            } catch (e) {
                notify(e.message || "添加失败", "danger");
            }
        });
        document.getElementById("btnRefreshCountryDict")?.addEventListener("click", () => {
            loadRegisteredCountriesDict();
        });
        document.getElementById("btnRefreshTeamDict")?.addEventListener("click", () => {
            loadTeams();
        });
        document.getElementById("btnSaveDictEdit")?.addEventListener("click", async () => {
            const kind = (document.getElementById("dictEditKind")?.value || "").trim();
            const id = (document.getElementById("dictEditId")?.value || "").trim();
            const name = (document.getElementById("dictEditName")?.value || "").trim();
            if (!id || !name) {
                notify("名称不能为空", "warning");
                return;
            }
            try {
                const url =
                    kind === "country"
                        ? `/api/company/registered-countries/${id}`
                        : `/api/teams/${id}`;
                await apiRequest(url, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name }),
                });
                bootstrap.Modal.getInstance(dictEditModalEl)?.hide();
                notify("已更新", "success");
                if (kind === "country") await loadRegisteredCountriesDict();
                else await loadTeams();
            } catch (e) {
                notify(e.message || "保存失败", "danger");
            }
        });
    }

    function initDictMaintenanceOnly() {
        bindDictMaintenanceEvents();
        loadRegisteredCountriesDict().then(() => loadTeams());
    }

    function boot() {
        if (body) {
            initCompanySessionBar();
            initStarFilterSelect();
            initGroupBySelect();
            bindEvents();
            bindDictMaintenanceEvents();
            loadRegisteredCountriesDict().then(() => {
                loadTeams();
                loadProjects(true);
            });
            return;
        }
        if (document.getElementById("countryDictList")) {
            initDictMaintenanceOnly();
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
