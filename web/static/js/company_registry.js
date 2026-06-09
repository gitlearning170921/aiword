(function () {
    const body = document.getElementById("companyProjectsBody");
    const modalEl = document.getElementById("companyProjectModal");
    const batchModalEl = document.getElementById("companyBatchEditModal");
    const linkModalEl = document.getElementById("companyLinkPage1Modal");
    const teamSel = document.getElementById("cpTeamId");
    const orgSel = document.getElementById("cpOrganizationId");
    const batchOrgSel = document.getElementById("batchCpOrganizationId");
    const batchTeamSel = document.getElementById("batchCpTeamId");
    const teamsDictList = document.getElementById("teamsDictList");
    const dictEditModalEl = document.getElementById("dictEditModal");
    const selectAllCb = document.getElementById("companyProjectSelectAll");
    const btnBatchEdit = document.getElementById("btnBatchEditCompanyProjects");
    const btnBatchRemove = document.getElementById("btnBatchRemoveCompanyProjects");
    const projectOrgFilterSel = document.getElementById("companyProjectOrgFilter");
    let teams = [];
    let organizations = [];
    let adminOrganizations = [];
    let activeOrganizationId = "";
    let projectsCache = [];
    const GROUP_BY_STORAGE_KEY = "companyRegistryGroupBy";
    const STAR_FILTER_STORAGE_KEY = "companyRegistryStarFilter";
    const ORG_FILTER_STORAGE_KEY = "companyRegistryOrgFilter";
    const canOverridePage1Lock = !!window.__PAGE13_SUPER_ADMIN__;
    const TEAM_LOCK_HINT =
        "页面1 已下发任务，公司管理员不可修改所属项目组；仅超级管理员（页面4 访问密码）可改。";
    const STATUS_LOCK_HINT =
        "页面1 已下发任务，公司管理员不可在页面0 修改项目状态；请由项目管理员在页面1 修改，或联系超级管理员。";
    const ORG_LOCK_HINT =
        "页面1 已绑定任务，不可修改所属公司；仅超级管理员（页面4 访问密码）可改。";

    const COLS = 15;
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

    function dictDeleteConfirmMessage(kind, name, item) {
        const usage = (item && item.usage) || {};
        const parts = [];
        if (usage.companyProjects) {
            parts.push(
                `${usage.companyProjects} 个公司总览项目的${kind === "country" ? "注册国家" : "项目组归属"}`
            );
        }
        if (usage.projects) {
            parts.push(`${usage.projects} 个页面1 项目的${kind === "country" ? "注册国家" : "项目组归属"}`);
        }
        if (kind === "country" && usage.userScopes) {
            parts.push(`${usage.userScopes} 条账号国家维度绑定`);
        }
        if (kind === "team" && usage.userMemberships) {
            parts.push(`${usage.userMemberships} 条账号项目组绑定`);
        }
        const label = kind === "country" ? `注册国家「${name || ""}」` : `项目组「${name || ""}」`;
        if (!parts.length) {
            return `确定删除${label}？`;
        }
        return `当前操作${label}及其关联的 ${parts.join("、")} 都会被删除，是否确认？`;
    }

    function projectHasPage1Tasks(project) {
        return !!(
            project &&
            (project.organizationIdLocked ||
                project.page1UploadTasksLocked ||
                project.page1HasUploadTasks)
        );
    }

    function companyProjectCascadeConfirmMessage(editing, payload) {
        if (!editing || !canOverridePage1Lock || !projectHasPage1Tasks(editing)) return "";
        const msgs = [];
        const orgChanged =
            payload.organizationId !== undefined &&
            String(payload.organizationId || "").trim() !== String(editing.organizationId || "").trim();
        const teamChanged =
            payload.assignedTeamId !== undefined &&
            String(payload.assignedTeamId || "").trim() !== String(editing.assignedTeamId || "").trim();
        if (orgChanged) {
            msgs.push("所属公司及关联页面1 项目、任务记录、审核/翻译/初稿任务");
        }
        if (teamChanged) {
            msgs.push("所属项目组及关联页面1 项目");
        }
        if (!msgs.length) return "";
        return `当前操作${msgs.join("与")}都会被更新，是否确认？`;
    }

    function batchCompanyProjectCascadeConfirmMessage(ids, payload) {
        if (!canOverridePage1Lock || !ids.length) return "";
        const selected = projectsCache.filter((p) => ids.includes(p.id));
        if (!selected.some(projectHasPage1Tasks)) return "";
        const orgChanged = payload.organizationId !== undefined && String(payload.organizationId || "").trim() !== "";
        const teamChanged = payload.assignedTeamId !== undefined;
        const msgs = [];
        if (orgChanged) {
            msgs.push("所属公司及关联页面1 项目、任务记录、审核/翻译/初稿任务");
        }
        if (teamChanged) {
            msgs.push("所属项目组及关联页面1 项目");
        }
        if (!msgs.length) return "";
        const n = selected.filter(projectHasPage1Tasks).length;
        const scope = n > 1 ? `已选 ${n} 个含任务项目的` : "该项目的";
        return `当前操作${scope}${msgs.join("与")}都会被更新，是否确认？`;
    }

    function selectedProjectIds() {
        const body = document.getElementById("companyProjectsBody");
        if (!body) return [];
        return [...body.querySelectorAll(".cp-row-checkbox:checked")]
            .map((cb) => cb.dataset.id)
            .filter(Boolean);
    }

    function isOrganizationIdLocked(project) {
        if (!project || canOverridePage1Lock) return false;
        return !!(
            project.organizationIdLocked ||
            project.page1UploadTasksLocked ||
            project.page1HasUploadTasks
        );
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

    function fillOrganizationSelect(sel, includeNoChange, selectedId) {
        if (!sel) return;
        const keep = selectedId != null ? String(selectedId) : sel.value;
        sel.innerHTML = "";
        if (includeNoChange) {
            const o0 = document.createElement("option");
            o0.value = "";
            o0.textContent = "— 不修改 —";
            sel.appendChild(o0);
        }
        (organizations || []).forEach((o) => {
            const id = String(o.id || "").trim();
            if (!id) return;
            const opt = document.createElement("option");
            opt.value = id;
            const kc = String(o.knowledgeCollection || "regulations");
            opt.textContent = `${o.name || id} (${kc})`;
            sel.appendChild(opt);
        });
        if (keep) sel.value = keep;
        if (organizations.length === 1 && !includeNoChange) {
            sel.value = String(organizations[0].id || "").trim();
            sel.disabled = true;
        }
    }

    function selectedProjectOrganizationFilter() {
        const v = String(projectOrgFilterSel?.value || "").trim();
        return v || "__all__";
    }

    function fillProjectOrgFilterSelect(selectedId) {
        if (!projectOrgFilterSel) return;
        const keep = selectedId != null ? String(selectedId || "").trim() : selectedProjectOrganizationFilter();
        projectOrgFilterSel.innerHTML = "";
        const allOpt = document.createElement("option");
        allOpt.value = "__all__";
        allOpt.textContent = "全部公司（并集）";
        projectOrgFilterSel.appendChild(allOpt);
        (organizations || []).forEach((o) => {
            const id = String(o.id || "").trim();
            if (!id) return;
            const opt = document.createElement("option");
            opt.value = id;
            const kc = String(o.knowledgeCollection || "regulations");
            opt.textContent = `${o.name || id} (${kc})`;
            projectOrgFilterSel.appendChild(opt);
        });
        const values = new Set([...projectOrgFilterSel.options].map((x) => String(x.value || "").trim()));
        const pick = values.has(keep) ? keep : "__all__";
        projectOrgFilterSel.value = pick;
        try {
            window.localStorage.setItem(ORG_FILTER_STORAGE_KEY, pick);
        } catch (_) {}
    }

    async function loadOrganizationsContext() {
        try {
            const ctx = await apiRequest("/api/company/context");
            organizations = Array.isArray(ctx?.organizations) ? ctx.organizations : [];
            activeOrganizationId = String(ctx?.activeOrganizationId || "").trim();
        } catch (_) {
            organizations = [];
            activeOrganizationId = "";
        }
        fillOrganizationSelect(orgSel, false, activeOrganizationId);
        fillOrganizationSelect(batchOrgSel, true, "");
        let savedFilter = "__all__";
        try {
            savedFilter = String(window.localStorage.getItem(ORG_FILTER_STORAGE_KEY) || "__all__").trim() || "__all__";
        } catch (_) {}
        fillProjectOrgFilterSelect(savedFilter);
    }

    async function loadAdminOrganizationsForDict() {
        if (!document.getElementById("teamsDictList")) return;
        try {
            const res = await apiRequest("/api/organizations");
            adminOrganizations = Array.isArray(res?.organizations) ? res.organizations : [];
        } catch (_) {
            adminOrganizations = [];
        }
    }

    function renderTeamOrgPicker(selectedIds) {
        const wrap = document.getElementById("dictEditTeamOrgsWrap");
        const picker = document.getElementById("dictEditTeamOrgsPicker");
        if (!wrap || !picker) return;
        const selected = new Set((selectedIds || []).map((x) => String(x || "").trim()).filter(Boolean));
        const rows = (adminOrganizations || []).filter((o) => o.isActive !== false);
        if (!rows.length) {
            wrap.classList.remove("d-none");
            picker.innerHTML = '<span class="text-muted">暂无公司，请先在「公司管理」维护</span>';
            return;
        }
        wrap.classList.remove("d-none");
        picker.innerHTML = rows
            .map((o) => {
                const id = String(o.id || "").trim();
                const checked = selected.has(id) ? " checked" : "";
                return `<div class="form-check mb-1">
                    <input class="form-check-input dict-edit-org-cb" type="checkbox" value="${esc(id)}" id="dictEditOrg_${esc(id)}"${checked}>
                    <label class="form-check-label" for="dictEditOrg_${esc(id)}">${esc(o.name || id)}</label>
                </div>`;
            })
            .join("");
    }

    function readTeamOrgPickerValues() {
        return [...document.querySelectorAll("#dictEditTeamOrgsPicker .dict-edit-org-cb:checked")]
            .map((el) => String(el.value || "").trim())
            .filter(Boolean);
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
                const orgNames =
                    kind === "team" && Array.isArray(item.organizations) && item.organizations.length
                        ? item.organizations.map((o) => o.name).join("、")
                        : "";
                const orgBadge = orgNames
                    ? `<span class="badge bg-info text-dark dict-org-badge" title="关联公司">${esc(orgNames)}</span>`
                    : kind === "team"
                      ? '<span class="badge bg-light text-muted dict-org-badge">未关联公司</span>'
                      : "";
                const usageBadge =
                    item.usageCount > 0
                        ? `<span class="badge bg-secondary dict-usage-badge" title="${esc(usageText)}">已引用 ${item.usageCount}</span>`
                        : '<span class="badge bg-light text-muted dict-usage-badge">未引用</span>';
                const delTitle =
                    item.usageCount > 0
                        ? ` title="${esc(dictDeleteConfirmMessage(kind, item.name, item))}"`
                        : "";
                return `<li class="list-group-item dict-item-row d-flex justify-content-between align-items-center flex-wrap" data-dict-id="${esc(item.id)}">
                    <div class="d-flex align-items-center gap-2 flex-wrap">
                        <span class="fw-medium">${esc(item.name)}</span>
                        ${orgBadge}
                        ${usageBadge}
                    </div>
                    <div class="dict-item-actions btn-group btn-group-sm">
                        <button type="button" class="btn btn-outline-secondary btn-dict-edit" data-kind="${esc(kind)}" data-id="${esc(item.id)}" data-name="${esc(item.name)}" data-org-ids="${esc((item.organizationIds || []).join(","))}">编辑</button>
                        <button type="button" class="btn btn-outline-danger btn-dict-delete"${delTitle} data-kind="${esc(kind)}" data-id="${esc(item.id)}" data-name="${esc(item.name)}" data-usage-count="${Number(item.usageCount) || 0}">删除</button>
                    </div>
                </li>`;
            })
            .join("");
        ul.querySelectorAll(".btn-dict-edit").forEach((btn) => {
            btn.addEventListener("click", () => {
                const orgRaw = (btn.dataset.orgIds || "").trim();
                const orgIds = orgRaw ? orgRaw.split(",").map((x) => x.trim()).filter(Boolean) : [];
                openDictEditModal(btn.dataset.kind, btn.dataset.id, btn.dataset.name, orgIds);
            });
        });
        ul.querySelectorAll(".btn-dict-delete").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const { kind, id, name } = btn.dataset;
                if (!id) return;
                const usageCount = Number(btn.dataset.usageCount || 0);
                const list = kind === "country" ? registeredCountriesDictFull : teams;
                const item = (list || []).find((x) => String(x.id) === String(id)) || {
                    name,
                    usageCount,
                };
                const msg = dictDeleteConfirmMessage(kind, name, item);
                if (!window.confirm(msg)) return;
                try {
                    const url =
                        kind === "country"
                            ? `/api/company/registered-countries/${id}`
                            : `/api/teams/${id}`;
                    await apiRequest(url, {
                        method: "DELETE",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ cascade: usageCount > 0 }),
                    });
                    notify("已删除", "success");
                    if (kind === "country") await loadRegisteredCountriesDict();
                    else await loadTeams();
                } catch (e) {
                    notify(e.message || "删除失败", "danger");
                }
            });
        });
    }

    function openDictEditModal(kind, id, name, organizationIds) {
        if (!dictEditModalEl) return;
        document.getElementById("dictEditKind").value = kind || "";
        document.getElementById("dictEditId").value = id || "";
        document.getElementById("dictEditName").value = name || "";
        const title = document.getElementById("dictEditModalTitle");
        const label = document.getElementById("dictEditNameLabel");
        const orgWrap = document.getElementById("dictEditTeamOrgsWrap");
        if (kind === "country") {
            if (title) title.textContent = "编辑注册国家";
            if (label) label.textContent = "注册国家名称";
            if (orgWrap) orgWrap.classList.add("d-none");
        } else {
            if (title) title.textContent = "编辑项目组";
            if (label) label.textContent = "项目组名称";
            renderTeamOrgPicker(organizationIds || []);
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
        const orgLocked = isOrganizationIdLocked(project);
        fillOrganizationSelect(orgSel, false, project?.organizationId || activeOrganizationId);
        applyFieldLock(orgSel, orgLocked, document.getElementById("cpOrganizationLockHint"), ORG_LOCK_HINT);
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
        if (!isOrganizationIdLocked(editing) && orgSel && !orgSel.disabled) {
            payload.organizationId = String(orgSel.value || "").trim() || null;
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
            const orgFilter = selectedProjectOrganizationFilter();
            const q =
                orgFilter && orgFilter !== "__all__"
                    ? `?organizationId=${encodeURIComponent(orgFilter)}`
                    : "";
            const candidates = await apiRequest(`/api/company/page1-project-candidates${q}`);
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
        const subCls = header.level === 2 ? " cp-group-header--sub" : "";
        const badge = `<span class="text-muted fw-normal ms-1">(${header.count})</span>`;
        return `<tr class="cp-group-header">
            <td colspan="${COLS}" class="small fw-semibold${subCls}">${esc(header.title)}：${esc(header.label)}${badge}</td>
        </tr>`;
    }

    function renderLockBadge(hint, label) {
        return `<span class="badge bg-warning text-dark" title="${esc(hint)}">${esc(label || "已锁定")}</span>`;
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
        const orgBadges = isOrganizationIdLocked(p) ? renderLockBadge(ORG_LOCK_HINT, "已锁定") : "";
        const teamBadges = isPage1TasksLocked(p) ? renderLockBadge(TEAM_LOCK_HINT, "已锁定") : "";
        const statusBadges = isPage1TasksLocked(p) ? renderLockBadge(STATUS_LOCK_HINT, "状态锁定") : "";
        return `<tr data-project-id="${esc(p.id)}" class="${rowCls.trim()}">
                <td class="text-center align-middle">${renderStarCell(p)}</td>
                <td class="text-center align-middle"><input type="checkbox" class="form-check-input cp-row-checkbox" data-id="${esc(p.id)}"></td>
                <td class="cp-cell-text fw-medium">${esc(p.name)}</td>
                <td class="cp-cell-text">${esc(p.productType || "—")}</td>
                <td class="cp-cell-text"><span>${esc(p.registeredCountry || "—")}</span><span class="cp-cell-meta">${esc(p.registeredCategory || "—")}</span></td>
                <td>
                    <input type="text" class="form-control form-control-sm cp-registration-owner-input"
                           data-id="${esc(p.id)}" value="${esc(p.registrationOwner || "")}" placeholder="—">
                </td>
                <td class="cp-cell-text"><div class="cp-cell-badges"><span>${esc(p.organizationName || "—")}</span>${orgBadges}</div></td>
                <td class="cp-cell-text"><div class="cp-cell-badges"><span>${esc(p.assignedTeamName || "—")}</span>${teamBadges}</div></td>
                <td class="cp-cell-text">${esc(p.priorityLabel || p.priority)}</td>
                <td class="cp-cell-text"><div class="cp-cell-badges"><span>${esc(p.statusLabel || p.status)}</span>${statusBadges}</div></td>
                <td class="cp-cell-text text-nowrap">${esc(p.expectedCertificationDate || "—")}</td>
                <td class="cp-cell-text text-nowrap">${esc(p.expectedSubmissionDate || "—")}</td>
                <td class="cp-cell-text cp-progress-cell" title="${esc(p.progressDescription || "")}">${esc(p.progressDescription || "—")}</td>
                <td class="text-center cp-cell-text">${Number(p.linkedPage1Count) || 0}</td>
                <td class="cp-actions-cell text-end">
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
                : "暂无项目。可点击「登记新项目」，或在页面1 使用「同步页面0项目」导入所属项目组下的公司总览项目。";
            body.innerHTML =
                window.ScopeBar && ScopeBar.emptyTableRow
                    ? ScopeBar.emptyTableRow(COLS, "page0_projects", [hint])
                    : `<tr><td colspan="${COLS}" class="text-muted small p-3">${esc(hint)}</td></tr>`;
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
            const params = new URLSearchParams();
            if (syncLegacy) params.set("syncLegacy", "1");
            const orgFilter = selectedProjectOrganizationFilter();
            if (orgFilter && orgFilter !== "__all__") {
                params.set("organizationId", orgFilter);
            }
            const q = params.toString() ? `?${params.toString()}` : "";
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
            if (batchOrgSel) batchOrgSel.value = "";
            const batchLocked = selectedHasPage1TasksLock();
            applyFieldLock(batchOrgSel, batchLocked, document.getElementById("batchCpOrganizationLockHint"), ORG_LOCK_HINT);
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
            const orgId = batchOrgSel?.value;
            if (orgId !== "" && !selectedHasPage1TasksLock()) {
                payload.organizationId = orgId;
            } else if (orgId !== "" && selectedHasPage1TasksLock()) {
                notify(ORG_LOCK_HINT, "warning");
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
            const cascadeMsg = batchCompanyProjectCascadeConfirmMessage(ids, payload);
            if (cascadeMsg && !window.confirm(cascadeMsg)) return;
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

        projectOrgFilterSel?.addEventListener("change", () => {
            const pick = selectedProjectOrganizationFilter();
            try {
                window.localStorage.setItem(ORG_FILTER_STORAGE_KEY, pick);
            } catch (_) {}
            loadProjects(false);
        });

        document.getElementById("btnRefreshCompanyProjects")?.addEventListener("click", () => loadProjects(false));
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
            const editing = id ? projectsCache.find((x) => x.id === id) : null;
            const cascadeMsg = companyProjectCascadeConfirmMessage(editing, payload);
            if (cascadeMsg && !window.confirm(cascadeMsg)) return;
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
    }

    function companyLoginUrl() {
        const root = (window.__SCRIPT_ROOT__ || "").replace(/\/+$/, "");
        return `${root}/login`;
    }

    function wireCompanyLogoutButton() {
        const logoutBtn = document.getElementById("companyLogoutBtn");
        if (!logoutBtn || logoutBtn.getAttribute("data-wired") === "1") return;
        logoutBtn.setAttribute("data-wired", "1");
        logoutBtn.addEventListener("click", async () => {
            try {
                await apiRequest("/api/logout", { method: "POST" });
            } catch (_) { /* ignore */ }
            window.location.href = companyLoginUrl();
        });
    }

    async function initCompanySessionBar() {
        wireCompanyLogoutButton();
        const info = document.getElementById("companyUserInfo");
        const logoutBtn = document.getElementById("companyLogoutBtn");
        try {
            const me = await apiRequest("/api/me");
            const isPage13Super = Boolean(me?.page13SuperAdmin);
            if (!me?.loggedIn) {
                if (isPage13Super) {
                    if (info) info.textContent = "超级管理员（页面4 访问密码）· 可见全部公司";
                    if (logoutBtn) logoutBtn.textContent = "退出超级管理员";
                } else {
                    window.location.href = companyLoginUrl();
                    return;
                }
            } else if (me.user?.adminRole !== "company" && !isPage13Super) {
                notify("仅公司管理员可访问本页", "danger");
            } else {
                const u = me.user || {};
                const countries = (u.registeredCountries || []).join("、");
                if (info) {
                    const roleHint = isPage13Super ? " · 超级管理员" : "";
                    info.textContent = `${u.displayName || u.username || ""}${countries ? " · " + countries : ""}${roleHint}`;
                }
            }
        } catch (e) {
            if ((e.message || "").includes("登录")) return;
            if (info) info.textContent = "";
        }
    }

    async function initCompanyTrainingPanel() {
        const orgSel = document.getElementById("companyActiveOrgSelect");
        const categorySel = document.getElementById("companyTrainCategory");
        const filesInput = document.getElementById("companyTrainFiles");
        const uploadBtn = document.getElementById("btnCompanyTrainUpload");
        const hint = document.getElementById("companyTrainHint");
        const casePanel = document.getElementById("companyTrainCasePanel");
        const caseModeSel = document.getElementById("companyTrainCaseMode");
        const existingCaseWrap = document.getElementById("companyTrainExistingCaseWrap");
        const existingCaseSel = document.getElementById("companyTrainExistingCase");
        const copyFromWrap = document.getElementById("companyTrainCopyFromWrap");
        const copyFromSel = document.getElementById("companyTrainCopyFrom");
        const newCaseFields = document.getElementById("companyTrainNewCaseFields");
        const caseNameInput = document.getElementById("companyTrainCaseName");
        const caseNameEnInput = document.getElementById("companyTrainCaseNameEn");
        const productNameInput = document.getElementById("companyTrainProductName");
        const productNameEnInput = document.getElementById("companyTrainProductNameEn");
        const docLangSel = document.getElementById("companyTrainDocLang");
        const regCountrySel = document.getElementById("companyTrainRegCountry");
        const regCountryEnInput = document.getElementById("companyTrainRegCountryEn");
        const regTypeSel = document.getElementById("companyTrainRegType");
        const regComponentSel = document.getElementById("companyTrainRegComponent");
        const projectFormSel = document.getElementById("companyTrainProjectForm");
        const scopeInput = document.getElementById("companyTrainScope");
        if (!orgSel || !categorySel || !filesInput || !uploadBtn) return;

        let trainingMeta = { cases: [] };

        const setHint = (msg) => {
            if (hint) hint.textContent = msg || "";
        };

        function formatTrainCaseLabel(c) {
            const name = String(c?.caseName || c?.case_name || c?.name || "").trim() || "—";
            const product = String(c?.productName || c?.product_name || "").trim();
            const country = String(c?.registrationCountry || c?.registration_country || "").trim();
            const lang = String(c?.documentLanguage || c?.document_language || "").trim();
            const parts = [name];
            if (product) parts.push(product);
            if (country) parts.push(country);
            if (lang) parts.push(lang);
            return parts.join(" · ");
        }

        function fillMetaSelect(sel, rows, emptyLabel) {
            if (!sel) return;
            const keep = String(sel.value || "").trim();
            sel.innerHTML = "";
            if (emptyLabel != null) {
                const opt = document.createElement("option");
                opt.value = "";
                opt.textContent = emptyLabel;
                sel.appendChild(opt);
            }
            (rows || []).forEach((row) => {
                const val = String(row?.value ?? row?.id ?? row?.name ?? "").trim();
                if (!val) return;
                const opt = document.createElement("option");
                opt.value = val;
                opt.textContent = String(row?.label ?? row?.name ?? val);
                sel.appendChild(opt);
            });
            const values = new Set([...sel.options].map((o) => String(o.value || "").trim()));
            if (keep && values.has(keep)) sel.value = keep;
        }

        function applyTrainingMetaToForm() {
            fillMetaSelect(docLangSel, trainingMeta.documentLanguages, null);
            if (docLangSel && !docLangSel.value) docLangSel.value = "zh";
            const countries = trainingMeta.registrationCountries?.length
                ? trainingMeta.registrationCountries
                : (registeredCountriesDict || []).map((name) => ({ value: name, label: name }));
            fillMetaSelect(regCountrySel, countries, "—");
            fillMetaSelect(regTypeSel, trainingMeta.registrationTypes, "—");
            fillMetaSelect(regComponentSel, trainingMeta.registrationComponents, "—");
            fillMetaSelect(projectFormSel, trainingMeta.projectForms, "—");

            const caseRows = Array.isArray(trainingMeta.cases) ? trainingMeta.cases : [];
            if (existingCaseSel) {
                existingCaseSel.innerHTML = caseRows.length
                    ? caseRows
                          .map((c) => {
                              const id = String(c?.id || c?.caseId || "").trim();
                              return `<option value="${esc(id)}">${esc(formatTrainCaseLabel(c))}</option>`;
                          })
                          .join("")
                    : '<option value="">（暂无已有案例，请新建）</option>';
            }
            if (copyFromSel) {
                copyFromSel.innerHTML = '<option value="">不复制</option>';
                caseRows.forEach((c) => {
                    const id = String(c?.id || c?.caseId || "").trim();
                    if (!id) return;
                    const opt = document.createElement("option");
                    opt.value = id;
                    opt.textContent = formatTrainCaseLabel(c);
                    copyFromSel.appendChild(opt);
                });
            }
        }

        async function loadTrainingMeta() {
            const orgId = String(orgSel.value || "").trim();
            if (!orgId) return;
            try {
                trainingMeta = await apiRequest(
                    `/api/company/training/meta?organizationId=${encodeURIComponent(orgId)}`
                );
                applyTrainingMetaToForm();
            } catch (e) {
                trainingMeta = { cases: [] };
                applyTrainingMetaToForm();
                setHint(e.message || "训练字典加载失败");
            }
        }

        function findCaseById(id) {
            const cid = String(id || "").trim();
            return (trainingMeta.cases || []).find(
                (c) => String(c?.id || c?.caseId || "").trim() === cid
            );
        }

        function prefillFromCase(c) {
            if (!c) return;
            if (caseNameInput) caseNameInput.value = String(c.caseName || c.case_name || "").trim();
            if (caseNameEnInput) caseNameEnInput.value = String(c.caseNameEn || c.case_name_en || "").trim();
            if (productNameInput) productNameInput.value = String(c.productName || c.product_name || "").trim();
            if (productNameEnInput) productNameEnInput.value = String(c.productNameEn || c.product_name_en || "").trim();
            if (docLangSel) {
                docLangSel.value = String(c.documentLanguage || c.document_language || "zh").trim() || "zh";
            }
            if (regCountrySel) {
                regCountrySel.value = String(c.registrationCountry || c.registration_country || "").trim();
            }
            if (regCountryEnInput) {
                regCountryEnInput.value = String(c.registrationCountryEn || c.registration_country_en || "").trim();
            }
            if (regTypeSel) regTypeSel.value = String(c.registrationType || c.registration_type || "").trim();
            if (regComponentSel) {
                regComponentSel.value = String(c.registrationComponent || c.registration_component || "").trim();
            }
            if (projectFormSel) projectFormSel.value = String(c.projectForm || c.project_form || "").trim();
            if (scopeInput) scopeInput.value = String(c.scopeOfApplication || c.scope_of_application || "").trim();
        }

        function syncCasePanel() {
            const isCase = String(categorySel.value || "") === "project_case";
            if (casePanel) casePanel.style.display = isCase ? "" : "none";
            if (!isCase) return;
            const mode = String(caseModeSel?.value || "new").trim() || "new";
            const existing = mode === "existing";
            if (existingCaseWrap) existingCaseWrap.style.display = existing ? "" : "none";
            if (copyFromWrap) copyFromWrap.style.display = existing ? "none" : "";
            if (newCaseFields) newCaseFields.style.display = existing ? "none" : "";
        }

        function buildProjectCaseCreateBody(copyFromId) {
            const copyCase = copyFromId ? findCaseById(copyFromId) : null;
            let projectKey = "";
            if (copyCase) {
                projectKey = String(copyCase.projectKey || copyCase.project_key || copyCase.id || "").trim();
            }
            return {
                organizationId: String(orgSel.value || "").trim(),
                caseName: String(caseNameInput?.value || "").trim(),
                caseNameEn: String(caseNameEnInput?.value || "").trim(),
                productName: String(productNameInput?.value || "").trim(),
                productNameEn: String(productNameEnInput?.value || "").trim(),
                documentLanguage: String(docLangSel?.value || "zh").trim() || "zh",
                registrationCountry: String(regCountrySel?.value || "").trim(),
                registrationCountryEn: String(regCountryEnInput?.value || "").trim(),
                registrationType: String(regTypeSel?.value || "").trim(),
                registrationComponent: String(regComponentSel?.value || "").trim(),
                projectForm: String(projectFormSel?.value || "").trim(),
                scopeOfApplication: String(scopeInput?.value || "").trim(),
                projectKey,
            };
        }

        const loadContext = async () => {
            const ctx = await apiRequest("/api/company/context");
            const orgs = Array.isArray(ctx?.organizations) ? ctx.organizations : [];
            const active = String(ctx?.activeOrganizationId || "").trim();
            orgSel.innerHTML = orgs
                .map((o) => {
                    const id = String(o.id || "").trim();
                    const kc = String(o.knowledgeCollection || "regulations");
                    return `<option value="${esc(id)}">${esc(`${o.name || id} (${kc})`)}</option>`;
                })
                .join("");
            if (active) orgSel.value = active;
            const row = orgs.find((x) => String(x.id || "").trim() === String(orgSel.value || "").trim());
            setHint(row ? `当前知识库：${row.knowledgeCollection || "regulations"}` : "");
            syncTrainHubOrgSelects(orgs, active);
            await loadTrainingMeta();
        };

        try {
            await loadRegisteredCountriesDict().catch(() => {});
            await loadContext();
        } catch (e) {
            setHint("");
            notify(e.message || "公司上下文加载失败", "danger");
        }

        orgSel.addEventListener("change", async () => {
            const id = String(orgSel.value || "").trim();
            if (!id) return;
            try {
                const res = await apiRequest("/api/company/context/active", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ organizationId: id }),
                });
                setHint(`当前知识库：${res?.activeKnowledgeCollection || ""}`);
                notify("已切换当前公司", "success");
                await loadTrainingMeta();
                if (projectOrgFilterSel) {
                    projectOrgFilterSel.value = id;
                    try {
                        window.localStorage.setItem(ORG_FILTER_STORAGE_KEY, id);
                    } catch (_) {}
                    loadProjects(false);
                }
                if (window.ScopeBar && ScopeBar.refresh) ScopeBar.refresh(true);
            } catch (e) {
                notify(e.message || "切换公司失败", "danger");
            }
        });

        categorySel.addEventListener("change", () => {
            syncCasePanel();
            if (String(categorySel.value || "") === "project_case") loadTrainingMeta();
        });
        caseModeSel?.addEventListener("change", syncCasePanel);
        copyFromSel?.addEventListener("change", () => {
            const cid = String(copyFromSel.value || "").trim();
            if (cid) prefillFromCase(findCaseById(cid));
        });
        syncCasePanel();

        uploadBtn.addEventListener("click", async () => {
            const selected = filesInput.files ? Array.from(filesInput.files) : [];
            if (!selected.length) {
                notify("请先选择要训练的文件", "warning");
                return;
            }
            const category = String(categorySel.value || "regulation");
            uploadBtn.disabled = true;
            setHint("训练中，请稍候...");
            try {
                let res = null;
                if (category === "project_case") {
                    let caseId = 0;
                    const mode = String(caseModeSel?.value || "new").trim() || "new";
                    if (mode === "existing") {
                        caseId = Number(String(existingCaseSel?.value || "").trim()) || 0;
                        if (!caseId) {
                            notify("请选择已有案例，或切换为「新建案例」", "warning");
                            return;
                        }
                    } else {
                        const body = buildProjectCaseCreateBody(String(copyFromSel?.value || "").trim());
                        if (!body.caseName) {
                            notify("请填写案例名称", "warning");
                            return;
                        }
                        const created = await apiRequest("/api/company/training/project-cases/create", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(body),
                        });
                        caseId =
                            Number(created?.upstream?.data?.case_id || created?.upstream?.data?.case?.id || 0) || 0;
                        if (!caseId) {
                            throw new Error("创建项目案例失败：未返回 case_id");
                        }
                    }
                    const fd = new FormData();
                    fd.append("organizationId", String(orgSel.value || "").trim());
                    fd.append("caseId", String(caseId));
                    selected.forEach((f) => fd.append("files", f));
                    res = await apiRequest("/api/company/training/project-cases/upload", {
                        method: "POST",
                        body: fd,
                    });
                    await loadTrainingMeta();
                } else {
                    const fd = new FormData();
                    fd.append("organizationId", String(orgSel.value || "").trim());
                    fd.append("category", category);
                    selected.forEach((f) => fd.append("files", f));
                    res = await apiRequest("/api/company/training/upload", {
                        method: "POST",
                        body: fd,
                    });
                }
                const files = Number(
                    res?.upstream?.files_processed ||
                    res?.upstream?.data?.files_processed ||
                    0
                );
                const chunks = Number(
                    res?.upstream?.total_chunks_added ||
                    res?.upstream?.data?.total_chunks_added ||
                    0
                );
                setHint(`训练完成：文件 ${files}，新增块 ${chunks}`);
                notify(`训练完成（${files} 个文件，${chunks} 个块）`, "success");
                filesInput.value = "";
            } catch (e) {
                setHint("");
                notify(e.message || "训练失败", "danger");
            } finally {
                uploadBtn.disabled = false;
            }
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
        document.getElementById("btnAddTeam")?.addEventListener("click", async () => {
            const name = (document.getElementById("newTeamName")?.value || "").trim();
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
                const nameInput = document.getElementById("newTeamName");
                if (nameInput) nameInput.value = "";
                await loadTeams();
                notify("已添加", "success");
            } catch (e) {
                notify(e.message || "添加失败", "danger");
            }
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
                const body = { name };
                if (kind === "team") {
                    body.organizationIds = readTeamOrgPickerValues();
                }
                await apiRequest(url, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
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

    function syncTrainHubOrgSelects(orgs, activeId) {
        ["checklistOrgSelect", "knowledgeOrgSelect"].forEach((id) => {
            const sel = document.getElementById(id);
            if (!sel) return;
            sel.innerHTML = (orgs || [])
                .map((o) => {
                    const oid = String(o.id || "").trim();
                    const kc = String(o.knowledgeCollection || "regulations");
                    return `<option value="${esc(oid)}">${esc(`${o.name || oid} (${kc})`)}</option>`;
                })
                .join("");
            if (activeId) sel.value = activeId;
        });
    }

    function initTrainingHubExtras() {
        const checklistEditor = document.getElementById("checklistJsonEditor");
        const checklistHint = document.getElementById("checklistHint");
        const knowledgeBox = document.getElementById("knowledgeStatusBox");
        const orgSel = document.getElementById("companyActiveOrgSelect");

        const readHubOrg = () => {
            const tabCheck = document.getElementById("checklistOrgSelect");
            const tabKnow = document.getElementById("knowledgeOrgSelect");
            const activePane = document.querySelector("#trainTabChecklist.show.active,#trainTabChecklist.active")
                ? tabCheck
                : tabKnow;
            return String(
                (activePane && activePane.value) ||
                (tabCheck && tabCheck.value) ||
                (orgSel && orgSel.value) ||
                ""
            ).trim();
        };

        document.getElementById("btnGenerateChecklist")?.addEventListener("click", async () => {
            const orgId = readHubOrg();
            if (!orgId) {
                notify("请先选择公司", "warning");
                return;
            }
            if (checklistHint) checklistHint.textContent = "生成中…";
            try {
                const res = await apiRequest("/api/company/training/checklist/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ organizationId: orgId }),
                });
                const list = res.checklist || [];
                if (checklistEditor) {
                    checklistEditor.value = JSON.stringify(list, null, 2);
                }
                if (checklistHint) {
                    checklistHint.textContent = res.message || `已生成 ${list.length} 条`;
                }
                notify(res.message || "审核点已生成", "success");
            } catch (e) {
                if (checklistHint) checklistHint.textContent = "";
                notify(e.message || "生成失败", "danger");
            }
        });

        document.getElementById("btnTrainChecklist")?.addEventListener("click", async () => {
            const orgId = readHubOrg();
            if (!orgId) {
                notify("请先选择公司", "warning");
                return;
            }
            let parsed = null;
            try {
                parsed = JSON.parse(String(checklistEditor?.value || "").trim() || "[]");
            } catch (_) {
                notify("审核点 JSON 格式无效", "warning");
                return;
            }
            if (checklistHint) checklistHint.textContent = "训练入库中…";
            try {
                const res = await apiRequest("/api/company/training/checklist/train", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ organizationId: orgId, checklist: parsed }),
                });
                if (checklistHint) checklistHint.textContent = res.message || "已入库";
                notify(res.message || "审核点已入库", "success");
            } catch (e) {
                if (checklistHint) checklistHint.textContent = "";
                notify(e.message || "入库失败", "danger");
            }
        });

        async function refreshKnowledgeStatus() {
            const orgId = readHubOrg();
            if (!orgId || !knowledgeBox) return;
            knowledgeBox.textContent = "加载中…";
            try {
                const res = await apiRequest(
                    `/api/company/training/status?organizationId=${encodeURIComponent(orgId)}`
                );
                knowledgeBox.textContent = JSON.stringify(res.status || res, null, 2);
            } catch (e) {
                knowledgeBox.textContent = e.message || "加载失败";
            }
        }

        document.getElementById("btnRefreshKnowledgeStatus")?.addEventListener("click", refreshKnowledgeStatus);
        document.getElementById("btnClearKnowledge")?.addEventListener("click", async () => {
            const orgId = readHubOrg();
            if (!orgId) {
                notify("请先选择公司", "warning");
                return;
            }
            if (!window.confirm("确定清空当前公司知识库？此操作不可恢复。")) return;
            try {
                await apiRequest("/api/company/training/knowledge/clear", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ organizationId: orgId }),
                });
                notify("知识库已清空", "success");
                refreshKnowledgeStatus();
            } catch (e) {
                notify(e.message || "清空失败", "danger");
            }
        });

        document.getElementById("btnTrainDirectory")?.addEventListener("click", async () => {
            const orgId = readHubOrg();
            const dirPath = String(document.getElementById("trainDirPath")?.value || "").trim();
            const category = String(document.getElementById("trainDirCategory")?.value || "regulation");
            if (!orgId || !dirPath) {
                notify("请填写公司与目录路径", "warning");
                return;
            }
            try {
                const res = await apiRequest("/api/company/training/directory", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ organizationId: orgId, dirPath, category }),
                });
                notify(res.message || "目录训练已完成", "success");
                refreshKnowledgeStatus();
            } catch (e) {
                notify(e.message || "目录训练失败", "danger");
            }
        });

        document.querySelector('[data-bs-target="#trainTabKnowledge"]')?.addEventListener("shown.bs.tab", refreshKnowledgeStatus);
    }

    function initDictMaintenanceOnly() {
        bindDictMaintenanceEvents();
        loadAdminOrganizationsForDict().then(() => loadRegisteredCountriesDict()).then(() => loadTeams());
    }

    function boot() {
        if (body) {
            wireCompanyLogoutButton();
            initCompanySessionBar();
            initCompanyTrainingPanel();
            initTrainingHubExtras();
            initStarFilterSelect();
            initGroupBySelect();
            bindEvents();
            bindDictMaintenanceEvents();
            loadRegisteredCountriesDict().then(() => {
                loadOrganizationsContext();
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
