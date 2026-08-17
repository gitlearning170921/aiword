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
    function ufText(adminText, userText) {
        return typeof window.ufText === "function"
            ? window.ufText(adminText, userText)
            : (window.__PAGE13_SUPER_ADMIN__ ? adminText : userText);
    }
    const TEAM_LOCK_HINT = ufText(
        "页面1 已下发任务，公司管理员不可修改所属项目组；仅超级管理员（页面4 访问密码）可改。",
        "已有下发任务时，不可修改所属项目组；请联系超级管理员。"
    );
    const STATUS_LOCK_HINT = ufText(
        "页面1 已下发任务，公司管理员不可在页面0 修改项目状态；请由项目管理员在页面1 修改，或联系超级管理员。",
        "已有下发任务时，不可在此修改项目状态；请在任务管理中修改，或联系超级管理员。"
    );
    const ORG_LOCK_HINT = ufText(
        "页面1 已绑定任务，不可修改所属公司；仅超级管理员（页面4 访问密码）可改。",
        "已绑定任务时，不可修改所属公司；请联系超级管理员。"
    );

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
            parts.push(ufText(`${usage.projects} 个页面1 项目的${kind === "country" ? "注册国家" : "项目组归属"}`, `${usage.projects} 个任务项目的${kind === "country" ? "注册国家" : "项目组归属"}`));
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
            msgs.push(ufText("所属公司及关联页面1 项目、任务记录、审核/翻译/初稿任务", "所属公司及关联任务、任务记录、审核/翻译/初稿任务"));
        }
        if (teamChanged) {
            msgs.push(ufText("所属项目组及关联页面1 项目", "所属项目组及关联任务项目"));
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
            msgs.push(ufText("所属公司及关联页面1 项目、任务记录、审核/翻译/初稿任务", "所属公司及关联任务、任务记录、审核/翻译/初稿任务"));
        }
        if (teamChanged) {
            msgs.push(ufText("所属项目组及关联页面1 项目", "所属项目组及关联任务项目"));
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
        if (u.projects) parts.push(ufText(`页面1 ${u.projects}`, `任务 ${u.projects}`));
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
        if (title) title.textContent = ufText(`关联页面1 项目 · ${companyProject.name || ""}`, `关联任务项目 · ${companyProject.name || ""}`);
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
                if (box) box.innerHTML = '<div class="text-muted small">' + esc(ufText("暂无页面1 项目，请先在页面1 创建。", "暂无任务项目，请先在任务管理中创建。")) + '</div>';
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
                    ufText(
                        "确定移出该公司总览记录？\n仅删除公司层数据并解除与页面1 的关联，页面1/2/3 的项目与任务均保留。",
                        "确定移出该公司总览记录？\n仅删除公司层数据并解除与任务的关联，任务数据均保留。"
                    )
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
                : ufText(
                    "暂无项目。可点击「登记新项目」，或在页面1 使用「同步页面0项目」导入所属项目组下的公司总览项目。",
                    "暂无项目。可点击「登记新项目」，或使用「同步公司总览项目」导入所属项目组下的公司总览项目。"
                  );
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
                notify(ufText(`已从页面1 同步 ${synced} 个已有项目，可直接编辑`, `已同步 ${synced} 个已有任务项目，可直接编辑`), "success");
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
                ufText(
                    `确定将选中的 ${ids.length} 条公司总览记录移出？\n仅解除关联，页面1/2/3 数据均保留。`,
                    `确定将选中的 ${ids.length} 条公司总览记录移出？\n仅解除关联，任务数据均保留。`
                )
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
            let overwriteMode = String(
                document.getElementById("companyTrainOverwriteMode")?.value || "overwrite"
            ).trim();
            if (overwriteMode !== "skip" && overwriteMode !== "overwrite") {
                overwriteMode = "overwrite";
            }

            // 覆盖前弹窗确认：查询同名已存在文件
            const resolveDisplayName = (f) => {
                const n = String(f?.name || "upload.bin").replace(/\\/g, "/");
                const parts = n.split("/");
                return parts[parts.length - 1] || "upload.bin";
            };
            const selectedNames = selected.map(resolveDisplayName);
            const hasArchive = selected.some((f) =>
                /\.(zip|tar|tgz|gz|rar)$/i.test(String(f?.name || ""))
            );
            let existingCaseIdForCheck = 0;
            if (category === "project_case") {
                const mode0 = String(caseModeSel?.value || "new").trim() || "new";
                if (mode0 === "existing") {
                    existingCaseIdForCheck = Number(String(existingCaseSel?.value || "").trim()) || 0;
                }
            }
            try {
                const q = new URLSearchParams({
                    organizationId: String(orgSel.value || "").trim(),
                    category,
                });
                if (existingCaseIdForCheck) q.set("caseId", String(existingCaseIdForCheck));
                const existRes = await apiRequest(
                    `/api/company/training/existing-files?${q.toString()}`
                );
                const existing = new Set(
                    (Array.isArray(existRes?.fileNames) ? existRes.fileNames : []).map((x) =>
                        String(x || "").trim()
                    )
                );
                const dups = selectedNames.filter((n) => existing.has(n));
                if (dups.length || (overwriteMode === "overwrite" && hasArchive)) {
                    let msg = "";
                    if (dups.length) {
                        const shown = dups.slice(0, 15).join("\n");
                        const more = dups.length > 15 ? `\n…（共 ${dups.length} 个）` : "";
                        msg =
                            `以下文件已在知识库中存在，是否用本次上传覆盖旧版？\n\n${shown}${more}\n\n` +
                            `【确定】覆盖（最新替换旧版）\n【取消】跳过重名，仅训练其余文件`;
                    } else {
                        msg =
                            `压缩包内若有与知识库同名的文件，将覆盖旧版。\n\n` +
                            `【确定】允许覆盖\n【取消】同名时跳过`;
                    }
                    if (window.confirm(msg)) {
                        overwriteMode = "overwrite";
                    } else {
                        overwriteMode = "skip";
                        if (dups.length && dups.length >= selectedNames.length && !hasArchive) {
                            notify("已取消：全部为重名且选择跳过，无需训练", "warning");
                            return;
                        }
                    }
                }
            } catch (_) {
                // 查重失败时仍允许训练，但覆盖模式再确认一次
                if (overwriteMode === "overwrite") {
                    if (
                        !window.confirm(
                            "无法确认知识库中是否已有同名文件。\n\n【确定】仍按覆盖模式训练\n【取消】改为跳过同名"
                        )
                    ) {
                        overwriteMode = "skip";
                    }
                }
            }

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
                    fd.append("overwriteMode", overwriteMode);
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
                    fd.append("overwriteMode", overwriteMode);
                    selected.forEach((f) => fd.append("files", f));
                    res = await apiRequest("/api/company/training/upload", {
                        method: "POST",
                        body: fd,
                    });
                    const jobId = String(res?.jobId || res?.job_id || "").trim();
                    if (jobId) {
                        const progressWrap = document.getElementById("companyTrainProgressWrap");
                        const progressBar = document.getElementById("companyTrainProgressBar");
                        if (progressWrap) progressWrap.style.display = "";
                        const poll = async () => {
                            const st = await apiRequest(
                                `/api/company/training/jobs/${encodeURIComponent(jobId)}?organizationId=${encodeURIComponent(String(orgSel.value || "").trim())}`
                            );
                            const prog = Math.max(0, Math.min(100, Math.round(Number(st?.progress || 0) * 100)));
                            if (progressBar) progressBar.style.width = `${prog}%`;
                            const msg = String(st?.message || "").trim();
                            const cur = String(st?.currentFile || "").trim();
                            setHint(cur ? `${msg}（${cur}）` : msg || `进度 ${prog}%`);
                            const status = String(st?.status || "").toLowerCase();
                            if (status === "succeeded" || status === "failed") {
                                if (progressWrap) progressWrap.style.display = "none";
                                const errs = Array.isArray(st?.errors) ? st.errors : [];
                                if (status === "failed") {
                                    throw new Error(st?.error || msg || "训练失败");
                                }
                                const result = st?.result || {};
                                const files = Number(result?.files_processed || st?.filesDone || 0);
                                const chunks = Number(result?.total_chunks_added || 0);
                                let hintMsg = `训练完成：文件 ${files}，新增块 ${chunks}`;
                                if (errs.length) {
                                    hintMsg += `；失败 ${errs.length}：` + errs.map((e) => `${e.fileName}:${e.message}`).join("；");
                                }
                                setHint(hintMsg);
                                notify(errs.length ? `训练完成（含 ${errs.length} 个失败）` : `训练完成（${files} 个文件，${chunks} 个块）`, errs.length ? "warning" : "success");
                                filesInput.value = "";
                                return;
                            }
                            await new Promise((r) => setTimeout(r, 1500));
                            return poll();
                        };
                        await poll();
                        return;
                    }
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
                const progressWrap = document.getElementById("companyTrainProgressWrap");
                if (progressWrap) progressWrap.style.display = "none";
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
            const box = document.getElementById("knowledgeStatusBox");
            const orgId = readHubOrg();
            if (!orgId || !box) return;
            box.innerHTML = `<p class="small text-muted mb-0">加载中…</p>`;
            try {
                const res = await apiRequest(
                    `/api/company/training/status?organizationId=${encodeURIComponent(orgId)}`
                );
                box.innerHTML = renderKnowledgeStatusHtml(res?.status || res);
            } catch (e) {
                box.innerHTML = `<p class="small text-danger mb-0">${esc(e.message || "加载失败")}</p>`;
            }
        }

        function renderKnowledgeStatusHtml(raw) {
            const st = raw && typeof raw === "object" ? raw : {};
            const kb = st.knowledge_stats && typeof st.knowledge_stats === "object" ? st.knowledge_stats : {};
            const byCat = kb.by_category && typeof kb.by_category === "object" ? kb.by_category : {};
            const reg = st.regulations_kb && typeof st.regulations_kb === "object" ? st.regulations_kb : {};
            const cp = st.checkpoints_kb && typeof st.checkpoints_kb === "object" ? st.checkpoints_kb : {};
            const fb = st.audit_feedback_kb && typeof st.audit_feedback_kb === "object" ? st.audit_feedback_kb : {};
            const n = (v) => {
                const x = Number(v);
                return Number.isFinite(x) ? x : 0;
            };
            const totalFiles = n(kb.total_files != null ? kb.total_files : reg.file_count);
            const totalChunks = n(kb.total_chunks != null ? kb.total_chunks : reg.document_count);
            const catRows = [
                ["regulation", "法规文件"],
                ["program", "程序文件"],
                ["project_case", "项目案例文件"],
                ["glossary", "词条"],
                ["internal_control", "内部管控文件"],
            ];
            const isAdmin = Boolean(window.__PAGE13_SUPER_ADMIN__);
            const collName = String(st.collection_name || reg.collection_name || "").trim();
            const caption = isAdmin && collName
                ? (typeof window.ufText === "function"
                    ? window.ufText(`当前知识库 collection：${collName}`, "当前知识库")
                    : `当前知识库 collection：${collName}`)
                : "当前知识库（以数据库为准）";
            const metric = (title, value, sub) =>
                `<div class="col-sm-6 col-lg-3">
                    <div class="border rounded p-3 h-100 bg-white">
                        <div class="small text-muted">${esc(title)}</div>
                        <div class="fs-4 fw-semibold">${esc(String(value))}</div>
                        ${sub ? `<div class="small text-muted">${esc(sub)}</div>` : ""}
                    </div>
                </div>`;
            const catTableRows = catRows
                .map(([key, label]) => {
                    const c = byCat[key] && typeof byCat[key] === "object" ? byCat[key] : {};
                    return `<tr>
                        <td>${esc(label)}</td>
                        <td class="text-end">${n(c.files)}</td>
                        <td class="text-end">${n(c.chunks)}</td>
                    </tr>`;
                })
                .join("");
            const extraCatLabels = {
                project_doc: "初稿产出文档（主知识库，不是项目知识库）",
                project_kb: "误写入主库的项目知识库条目",
                deficiency: "缺陷记录",
            };
            const extraCats = Object.keys(byCat).filter(
                (k) => !catRows.some(([key]) => key === k) && k
            );
            const extraRows = extraCats
                .map((key) => {
                    const c = byCat[key] && typeof byCat[key] === "object" ? byCat[key] : {};
                    const label = extraCatLabels[key] || key;
                    return `<tr>
                        <td>${esc(label)}</td>
                        <td class="text-end">${n(c.files)}</td>
                        <td class="text-end">${n(c.chunks)}</td>
                    </tr>`;
                })
                .join("");
            return `
                <p class="small text-muted mb-2">${esc(caption)}</p>
                <div class="row g-2 mb-3">
                    ${metric("法规知识库", `${totalFiles} 文件 / ${totalChunks} 块`, "第一步训练（以数据库为准）")}
                    ${metric("审核点清单", `${n(cp.file_count)} 文件 / ${n(cp.document_count)} 块`, "第二步训练入库")}
                    ${metric("误报/纠正反馈", `${n(fb.document_count)} 块`, "独立反馈库，不随清单清空")}
                </div>
                <div class="small fw-semibold mb-2">训练统计（按类型，仅主知识库）</div>
                <p class="small text-muted mb-2">项目知识库按项目单独存放，不计入本表；入库数量请到「项目知识库协同」查看。</p>
                <div class="table-responsive">
                    <table class="table table-sm table-bordered align-middle mb-0 bg-white">
                        <thead class="table-light">
                            <tr>
                                <th>分类</th>
                                <th class="text-end">文件数</th>
                                <th class="text-end">向量块</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${catTableRows}
                            ${extraRows}
                            <tr class="table-light">
                                <td>全部</td>
                                <td class="text-end">${totalFiles}</td>
                                <td class="text-end">${totalChunks}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            `;
        }

        document.getElementById("btnRefreshKnowledgeStatus")?.addEventListener("click", refreshKnowledgeStatus);

        document.getElementById("btnTrainDirectory")?.addEventListener("click", async () => {
            const orgId = String(document.getElementById("companyActiveOrgSelect")?.value || "").trim()
                || String(document.getElementById("knowledgeOrgSelect")?.value || "").trim();
            const dirPath = String(document.getElementById("trainDirPath")?.value || "").trim();
            let category = String(document.getElementById("trainDirCategory")?.value || "").trim();
            if (!category) {
                category = String(document.getElementById("companyTrainCategory")?.value || "regulation").trim() || "regulation";
            }
            if (!orgId || !dirPath) {
                notify("请填写公司与目录路径", "warning");
                return;
            }
            const btn = document.getElementById("btnTrainDirectory");
            if (btn) btn.disabled = true;
            try {
                const res = await apiRequest("/api/company/training/directory", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ organizationId: orgId, dirPath, category }),
                });
                notify(res.message || "目录训练已完成", "success");
                if (typeof refreshKnowledgeStatus === "function") refreshKnowledgeStatus();
            } catch (e) {
                notify(e.message || "目录训练失败", "danger");
            } finally {
                if (btn) btn.disabled = false;
            }
        });

        document.querySelector('[data-bs-target="#trainTabKnowledge"]')?.addEventListener("shown.bs.tab", refreshKnowledgeStatus);
    }

    function initDeficiencyPanel() {
        const orgSel = document.getElementById("defOrgSelect");
        let sectionsEl = document.getElementById("defGroupSections");
        const summaryEl = document.getElementById("defListSummary");
        const modalEl = document.getElementById("defDocModal");
        if (!orgSel) return;
        // 兼容旧缓存页：无分组容器时兜底创建，避免整段导入逻辑不绑定
        if (!sectionsEl) {
            const hint = document.getElementById("defImportHint");
            sectionsEl = document.createElement("div");
            sectionsEl.id = "defGroupSections";
            if (hint && hint.parentNode) hint.parentNode.insertBefore(sectionsEl, hint.nextSibling);
            else orgSel.parentNode?.appendChild(sectionsEl);
        }

        const PAGE_SIZE = 50;
        const selectedIds = new Set();
        const groupPages = Object.create(null);
        const expandedGroups = new Set();
        let opinionDupMap = new Map();
        let cachedRows = [];
        let defEditorSeq = 0;
        let projectsCacheOrgId = "";
        let projectsCacheRows = null;
        let projectsLoadPromise = null;
        let defModal = null;
        try {
            if (modalEl && window.bootstrap?.Modal) {
                defModal = bootstrap.Modal.getOrCreateInstance(modalEl);
            }
        } catch (_) {
            defModal = null;
        }

        const todayIso = () => {
            const d = new Date();
            const m = String(d.getMonth() + 1).padStart(2, "0");
            const day = String(d.getDate()).padStart(2, "0");
            return `${d.getFullYear()}-${m}-${day}`;
        };

        const typeLabel = (t) =>
            t === "type_testing" ? "体考" : t === "registration_review" ? "注册审评" : t || "—";
        const priLabel = (p) => ({ high: "高", medium: "中", low: "低" }[p] || p || "—");
        const stLabel = (s) => (s === "done" ? "已完成" : "未完成");
        const trainLabel = (s) =>
            ({ trained: "已训练", stale: "待重训", not_trained: "未训练" }[s] || s || "—");

        function renderEllipsis(text) {
            const full = String(text || "").trim() || "—";
            if (full === "—") return esc(full);
            return `<span class="def-cell-ellipsis" title="${esc(full)}">${esc(full)}</span>`;
        }

        function updateBatchBar() {
            const bar = document.getElementById("defBatchBar");
            const countEl = document.getElementById("defBatchCount");
            const n = selectedIds.size;
            if (countEl) countEl.textContent = String(n);
            if (bar) bar.classList.toggle("d-none", n === 0);
        }

        async function syncOrgOptions() {
            const src = document.getElementById("companyActiveOrgSelect");
            if (!src) return;
            orgSel.innerHTML = src.innerHTML;
            if (!orgSel.value && src.value) orgSel.value = src.value;
        }

        async function loadProjectsForOrg(opts) {
            const options = opts && typeof opts === "object" ? opts : {};
            const force = !!options.force;
            const projectSel = document.getElementById("defProjectId");
            const projectFilter = document.getElementById("defProjectFilter");
            const orgId = String(orgSel.value || "").trim();
            const fillEmpty = (el, msg) => {
                if (el) el.innerHTML = `<option value="">${esc(msg)}</option>`;
            };
            if (!orgId) {
                projectsCacheOrgId = "";
                projectsCacheRows = null;
                fillEmpty(projectSel, "请先选择公司");
                if (projectFilter) projectFilter.innerHTML = '<option value="">全部项目</option>';
                return [];
            }
            if (!force && projectsCacheOrgId === orgId && Array.isArray(projectsCacheRows)) {
                applyProjectOptions(projectsCacheRows);
                return projectsCacheRows;
            }
            if (!force && projectsLoadPromise && projectsCacheOrgId === orgId) {
                return projectsLoadPromise;
            }
            if (projectSel && !Array.isArray(projectsCacheRows)) {
                projectSel.innerHTML = '<option value="">加载中…</option>';
            }
            projectsCacheOrgId = orgId;
            projectsLoadPromise = (async () => {
                try {
                    const res = await apiRequest(
                        `/api/company/projects?organizationId=${encodeURIComponent(orgId)}&light=1`
                    );
                    const rows = Array.isArray(res?.projects) ? res.projects : Array.isArray(res) ? res : [];
                    projectsCacheRows = rows;
                    applyProjectOptions(rows);
                    return rows;
                } catch (e) {
                    projectsCacheRows = null;
                    if (projectSel) {
                        projectSel.innerHTML = `<option value="">加载失败：${esc(e.message || "")}</option>`;
                    }
                    return [];
                } finally {
                    projectsLoadPromise = null;
                }
            })();
            return projectsLoadPromise;
        }

        function applyProjectOptions(rows) {
            const projectSel = document.getElementById("defProjectId");
            const projectFilter = document.getElementById("defProjectFilter");
            const list = Array.isArray(rows) ? rows : [];
            if (projectSel) {
                projectSel.innerHTML = list.length
                    ? list
                          .map((p) => {
                              const id = String(p.id || "").trim();
                              const name = String(p.name || "").trim() || id;
                              const country = String(p.registeredCountry || p.registered_country || "").trim();
                              const cat = String(p.registeredCategory || p.registered_category || "").trim();
                              return `<option value="${esc(id)}" data-country="${esc(country)}" data-category="${esc(cat)}">${esc(name)}（${esc(country || "—")}/${esc(cat || "—")}）</option>`;
                          })
                          .join("")
                    : '<option value="">（该公司暂无项目）</option>';
            }
            if (projectFilter) {
                const keep = String(projectFilter.value || "");
                projectFilter.innerHTML =
                    '<option value="">全部项目</option>' +
                    list
                        .map((p) => {
                            const id = String(p.id || "").trim();
                            const name = String(p.name || "").trim() || id;
                            return `<option value="${esc(id)}">${esc(name)}</option>`;
                        })
                        .join("");
                if (keep) projectFilter.value = keep;
            }
            const batchProject = document.getElementById("defBatchProjectId");
            if (batchProject) {
                const keepB = String(batchProject.value || "");
                batchProject.innerHTML = list.length
                    ? list
                          .map((p) => {
                              const id = String(p.id || "").trim();
                              const name = String(p.name || "").trim() || id;
                              const country = String(p.registeredCountry || p.registered_country || "").trim();
                              const cat = String(p.registeredCategory || p.registered_category || "").trim();
                              return `<option value="${esc(id)}">${esc(name)}（${esc(country || "—")}/${esc(cat || "—")}）</option>`;
                          })
                          .join("")
                    : '<option value="">（该公司暂无项目）</option>';
                if (keepB) batchProject.value = keepB;
            }
            updateDimReadonly();
        }

        function updateDimReadonly() {
            const projectSel = document.getElementById("defProjectId");
            const dim = document.getElementById("defDimReadonly");
            if (!projectSel || !dim) return;
            const opt = projectSel.selectedOptions?.[0];
            const country = opt?.getAttribute("data-country") || "";
            const cat = opt?.getAttribute("data-category") || "";
            dim.textContent = country || cat ? `${country || "—"} / ${cat || "—"}` : "—";
        }

        function withButtonBusy(btn, busyText, fn) {
            if (!btn) return Promise.resolve().then(fn);
            const orig = btn.innerHTML;
            btn.disabled = true;
            btn.setAttribute("aria-busy", "true");
            btn.innerHTML =
                '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
                (busyText || "处理中…");
            return Promise.resolve()
                .then(fn)
                .finally(() => {
                    btn.disabled = false;
                    btn.removeAttribute("aria-busy");
                    btn.innerHTML = orig;
                });
        }

        function opinionKey(text) {
            return String(text || "")
                .replace(/\s+/g, " ")
                .trim()
                .toLowerCase();
        }

        function rebuildOpinionDupMap(rows) {
            const m = new Map();
            (rows || []).forEach((r) => {
                const k = opinionKey(r.opinion_text);
                if (!k) return;
                m.set(k, (m.get(k) || 0) + 1);
            });
            opinionDupMap = m;
            return m;
        }

        function isUnlinkedRecord(r) {
            return !String(r?.linked_company_project_id || "").trim();
        }

        function setProjectEditorMode(r, isNew) {
            const selWrap = document.getElementById("defProjectSelectWrap");
            const roWrap = document.getElementById("defProjectReadonlyWrap");
            const ro = document.getElementById("defProjectReadonly");
            const projectSel = document.getElementById("defProjectId");
            const dimRoWrap = document.getElementById("defDimReadonlyWrap");
            const dimEditWrap = document.getElementById("defDimEditWrap");
            const unlinked = !isNew && isUnlinkedRecord(r || {});
            if (selWrap) selWrap.classList.toggle("d-none", !!unlinked);
            if (roWrap) roWrap.classList.toggle("d-none", !unlinked);
            if (projectSel) projectSel.disabled = !!unlinked;
            if (dimRoWrap) dimRoWrap.classList.toggle("d-none", !!unlinked);
            if (dimEditWrap) dimEditWrap.classList.toggle("d-none", !unlinked);
            if (unlinked && ro) {
                const pname = String(r.project_name || r.projectName || "—").trim() || "—";
                ro.textContent = pname;
            }
            if (unlinked) {
                const cEl = document.getElementById("defRegCountry");
                const catEl = document.getElementById("defRegCategory");
                if (cEl) cEl.value = String(r.registration_country || "").trim();
                if (catEl) catEl.value = String(r.registration_category || "").trim();
            }
        }

        function groupKey(row) {
            return (
                String(row.projectName || row.project_name || row.linked_company_project_id || "未关联项目").trim() ||
                "未关联项目"
            );
        }

        function excelRowIndex(row) {
            const v = row?.excel_row_index ?? row?.excelRowIndex;
            const n = Number(v);
            return Number.isFinite(n) && n > 0 ? n : null;
        }

        function sortRowsInPlace(rows) {
            const sortBy = String(document.getElementById("defSortBy")?.value || "import");
            const list = rows || [];
            list.sort((a, b) => {
                if (sortBy === "dup") {
                    const da = opinionDupMap.get(opinionKey(a.opinion_text)) || 1;
                    const db = opinionDupMap.get(opinionKey(b.opinion_text)) || 1;
                    if (db !== da) return db - da;
                }
                if (sortBy === "issued") {
                    const ia = String(a.issued_on || "");
                    const ib = String(b.issued_on || "");
                    if (ia !== ib) return ib.localeCompare(ia);
                    return Number(b.id || 0) - Number(a.id || 0);
                }
                // 默认 / import：对齐文控 — 有 Excel 行号在前并按行号升序；手工在后
                const ea = excelRowIndex(a);
                const eb = excelRowIndex(b);
                const ta = ea == null ? 1 : 0;
                const tb = eb == null ? 1 : 0;
                if (ta !== tb) return ta - tb;
                if (ea != null && eb != null && ea !== eb) return ea - eb;
                return Number(a.id || 0) - Number(b.id || 0);
            });
            return list;
        }

        function groupRows(rows) {
            const map = new Map();
            (rows || []).forEach((r) => {
                const k = groupKey(r);
                if (!map.has(k)) map.set(k, []);
                map.get(k).push(r);
            });
            for (const [, list] of map) sortRowsInPlace(list);
            const sortBy = String(document.getElementById("defSortBy")?.value || "import");
            return [...map.entries()].sort((a, b) => {
                if (sortBy === "import") {
                    // 组顺序按组内最早 Excel 行号（与整表 Excel 先后一致）
                    const minRow = (list) => {
                        let m = Infinity;
                        (list || []).forEach((r) => {
                            const n = excelRowIndex(r);
                            if (n != null && n < m) m = n;
                        });
                        return m;
                    };
                    const ma = minRow(a[1]);
                    const mb = minRow(b[1]);
                    if (ma !== mb) return ma - mb;
                }
                return a[0].localeCompare(b[0], "zh");
            });
        }

        function renderStats(rows) {
            const el = document.getElementById("defStatsBar");
            if (!el) return;
            const list = rows || [];
            if (!list.length) {
                el.innerHTML = "";
                return;
            }
            const byProject = new Map();
            const byType = new Map();
            list.forEach((r) => {
                const pk = groupKey(r);
                byProject.set(pk, (byProject.get(pk) || 0) + 1);
                const tk = typeLabel(r.deficiency_type);
                byType.set(tk, (byType.get(tk) || 0) + 1);
            });
            const projHtml = [...byProject.entries()]
                .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh"))
                .map(([n, c]) => `<span title="${esc(n)}">${esc(n.length > 12 ? n.slice(0, 12) + "…" : n)} <strong>${c}</strong></span>`)
                .join("");
            const typeHtml = [...byType.entries()]
                .sort((a, b) => b[1] - a[1])
                .map(([n, c]) => `<span>${esc(n)} <strong>${c}</strong></span>`)
                .join("");
            el.innerHTML = `<div class="mb-1"><span class="me-1">按项目：</span>${projHtml}</div><div><span class="me-1">按类型：</span>${typeHtml}</div>`;
        }

        function renderRows(rows) {
            if (!rows.length) {
                return '<tr><td colspan="9" class="text-muted p-3">暂无匹配记录</td></tr>';
            }
            return rows
                .map((r) => {
                    const id = String(r.id || "").trim();
                    const checked = selectedIds.has(id) ? "checked" : "";
                    const opinion = String(r.opinion_text || "").trim();
                    const dup = opinionDupMap.get(opinionKey(opinion)) || 1;
                    const dupHtml =
                        dup > 1
                            ? ` <span class="badge text-bg-warning def-dup-badge" title="含跨项目，相同意见共 ${dup} 条">重复×${dup}</span>`
                            : "";
                    return `<tr data-def-id="${esc(id)}">
                        <td class="text-center" style="width:2rem">
                            <input type="checkbox" class="form-check-input def-row-select m-0" data-def-id="${esc(id)}" ${checked} aria-label="选择记录">
                        </td>
                        <td class="text-nowrap">${esc(String(r.issued_on || "").slice(0, 10) || "—")}</td>
                        <td>${esc(typeLabel(r.deficiency_type))}</td>
                        <td>${renderEllipsis(opinion)}${dupHtml}</td>
                        <td class="small">${esc(r.deficiency_source || "—")}</td>
                        <td>${esc(priLabel(r.priority))}</td>
                        <td><span class="badge ${r.remediation_status === "done" ? "text-bg-success" : "text-bg-warning"}">${esc(stLabel(r.remediation_status))}</span></td>
                        <td class="small">${esc(trainLabel(r.train_status))}</td>
                        <td class="text-nowrap" style="width:7.5rem">
                            <button type="button" class="btn btn-link btn-sm p-0 me-2 def-edit-btn" data-id="${esc(id)}">编辑</button>
                            <button type="button" class="btn btn-link btn-sm p-0 text-danger def-delete-btn" data-id="${esc(id)}">删除</button>
                        </td>
                    </tr>`;
                })
                .join("");
        }

        function renderGroupShell(projectName, count) {
            const gkey = esc(projectName);
            return `<div class="card mb-3 def-group-block def-group-collapsed" data-group="${gkey}" data-loaded="0">
                <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2 py-2 def-group-toggle" role="button" tabindex="0" aria-expanded="false">
                    <div class="fw-semibold">
                        <span class="text-muted me-1 def-group-chevron" aria-hidden="true">▸</span>
                        ${renderEllipsis(projectName)}
                        <span class="badge text-bg-light border">${Number(count) || 0}</span>
                    </div>
                    <span class="small text-muted def-group-hint">点击展开加载明细</span>
                </div>
                <div class="def-group-content"></div>
            </div>`;
        }

        function renderGroupCard(projectName, rows, page) {
            const total = rows.length;
            const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
            const p = Math.min(Math.max(1, page || 1), totalPages);
            const slice = rows.slice((p - 1) * PAGE_SIZE, p * PAGE_SIZE);
            const pageInfo = `第 ${p} / ${totalPages} 页，共 ${total} 条`;
            const prevDisabled = p <= 1 ? "disabled" : "";
            const nextDisabled = p >= totalPages ? "disabled" : "";
            const gkey = esc(projectName);
            return `<div class="card mb-3 def-group-block" data-group="${gkey}" data-page="${p}" data-loaded="1">
                <div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2 py-2 def-group-toggle" role="button" tabindex="0" aria-expanded="true">
                    <div class="fw-semibold">
                        <span class="text-muted me-1 def-group-chevron" aria-hidden="true">▾</span>
                        ${renderEllipsis(projectName)}
                        <span class="badge text-bg-light border">${total}</span>
                    </div>
                    <div class="d-flex align-items-center gap-2 flex-wrap def-group-pager" onclick="event.stopPropagation()">
                        <span class="small text-muted">${pageInfo}</span>
                        <div class="btn-group btn-group-sm">
                            <button type="button" class="btn btn-outline-secondary def-group-prev" data-group="${gkey}" ${prevDisabled}>上一页</button>
                            <button type="button" class="btn btn-outline-secondary def-group-next" data-group="${gkey}" ${nextDisabled}>下一页</button>
                        </div>
                        <div class="d-flex align-items-center gap-1">
                            <input type="number" class="form-control form-control-sm def-group-page-input"
                                data-group="${gkey}" min="1" max="${totalPages}" value="${p}"
                                style="width:4.2rem" aria-label="页码">
                            <button type="button" class="btn btn-outline-secondary btn-sm def-group-go"
                                data-group="${gkey}" data-total-pages="${totalPages}">跳转</button>
                        </div>
                    </div>
                </div>
                <div class="card-body p-0 def-group-scroll def-group-content">
                    <table class="table table-sm table-hover mb-0 align-middle">
                        <thead class="table-light">
                            <tr>
                                <th class="text-center" style="width:2rem">
                                    <input type="checkbox" class="form-check-input def-group-select-all m-0" data-group="${gkey}" aria-label="全选本项目">
                                </th>
                                <th>发补日期</th>
                                <th>类型</th>
                                <th>发补意见</th>
                                <th>来源</th>
                                <th>优先级</th>
                                <th>状态</th>
                                <th>训练</th>
                                <th style="width:7.5rem">操作</th>
                            </tr>
                        </thead>
                        <tbody>${renderRows(slice)}</tbody>
                    </table>
                </div>
            </div>`;
        }

        function bindListEvents() {
            sectionsEl.querySelectorAll(".def-group-toggle").forEach((header) => {
                const toggle = () => {
                    const card = header.closest(".def-group-block");
                    const g = String(card?.getAttribute("data-group") || "");
                    if (!g) return;
                    if (expandedGroups.has(g)) expandedGroups.delete(g);
                    else expandedGroups.add(g);
                    renderGrouped(cachedRows);
                };
                header.addEventListener("click", (ev) => {
                    if (ev.target.closest(".def-group-pager, button, input, a")) return;
                    toggle();
                });
                header.addEventListener("keydown", (ev) => {
                    if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        toggle();
                    }
                });
            });
            sectionsEl.querySelectorAll(".def-edit-btn").forEach((btn) => {
                btn.addEventListener("click", () => openEditor(String(btn.getAttribute("data-id") || "")));
            });
            sectionsEl.querySelectorAll(".def-delete-btn").forEach((btn) => {
                btn.addEventListener("click", () => deleteOne(String(btn.getAttribute("data-id") || ""), btn));
            });
            sectionsEl.querySelectorAll(".def-row-select").forEach((chk) => {
                chk.addEventListener("change", () => {
                    const id = String(chk.getAttribute("data-def-id") || "");
                    if (!id) return;
                    if (chk.checked) selectedIds.add(id);
                    else selectedIds.delete(id);
                    updateBatchBar();
                });
            });
            sectionsEl.querySelectorAll(".def-group-select-all").forEach((chk) => {
                chk.addEventListener("change", () => {
                    const card = chk.closest(".def-group-block");
                    card?.querySelectorAll(".def-row-select").forEach((rowChk) => {
                        rowChk.checked = chk.checked;
                        const id = String(rowChk.getAttribute("data-def-id") || "");
                        if (!id) return;
                        if (chk.checked) selectedIds.add(id);
                        else selectedIds.delete(id);
                    });
                    updateBatchBar();
                });
            });
            sectionsEl.querySelectorAll(".def-group-prev, .def-group-next").forEach((btn) => {
                btn.addEventListener("click", (ev) => {
                    ev.stopPropagation();
                    const g = String(btn.getAttribute("data-group") || "");
                    const delta = btn.classList.contains("def-group-prev") ? -1 : 1;
                    groupPages[g] = Math.max(1, (groupPages[g] || 1) + delta);
                    expandedGroups.add(g);
                    renderGrouped(cachedRows);
                });
            });
            sectionsEl.querySelectorAll(".def-group-go").forEach((btn) => {
                btn.addEventListener("click", (ev) => {
                    ev.stopPropagation();
                    const g = String(btn.getAttribute("data-group") || "");
                    const max = Number(btn.getAttribute("data-total-pages") || 1);
                    const input = sectionsEl.querySelector(`.def-group-page-input[data-group="${CSS.escape(g)}"]`);
                    let page = Number(input?.value || 1);
                    if (!Number.isFinite(page)) page = 1;
                    page = Math.min(Math.max(1, Math.floor(page)), max);
                    groupPages[g] = page;
                    expandedGroups.add(g);
                    renderGrouped(cachedRows);
                });
            });
        }

        function renderGrouped(rows) {
            cachedRows = Array.isArray(rows) ? rows : [];
            rebuildOpinionDupMap(cachedRows);
            const groups = groupRows(cachedRows);
            if (summaryEl) {
                summaryEl.textContent = cachedRows.length
                    ? `共 ${cachedRows.length} 条，按所属项目 ${groups.length} 组（默认收起；每组每页 ${PAGE_SIZE} 条）`
                    : "共 0 条";
            }
            renderStats(cachedRows);
            if (!cachedRows.length) {
                sectionsEl.innerHTML =
                    '<div class="card mb-3"><div class="card-body text-muted small">暂无发补记录，可点「新增」或「导入Excel」</div></div>';
                updateBatchBar();
                return;
            }
            sectionsEl.innerHTML = groups
                .map(([name, list]) => {
                    if (expandedGroups.has(name)) {
                        return renderGroupCard(name, list, groupPages[name] || 1);
                    }
                    return renderGroupShell(name, list.length);
                })
                .join("");
            bindListEvents();
            updateBatchBar();
        }

        async function refreshList() {
            const orgId = String(orgSel.value || "").trim();
            if (!orgId) {
                sectionsEl.innerHTML =
                    '<div class="card mb-3"><div class="card-body text-muted small">请选择公司后查询</div></div>';
                if (summaryEl) summaryEl.textContent = "";
                return;
            }
            sectionsEl.innerHTML =
                '<div class="card mb-3"><div class="card-body text-muted small">加载中…</div></div>';
            try {
                const q = new URLSearchParams();
                q.set("organizationId", orgId);
                q.set("limit", "1000");
                const st = String(document.getElementById("defStatusFilter")?.value || "").trim();
                const dtype = String(document.getElementById("defTypeFilter")?.value || "").trim();
                const priority = String(document.getElementById("defPriorityFilter")?.value || "").trim();
                const train = String(document.getElementById("defTrainFilter")?.value || "").trim();
                const projectId = String(document.getElementById("defProjectFilter")?.value || "").trim();
                const keyword = String(document.getElementById("defKeyword")?.value || "").trim();
                if (st) q.set("remediationStatus", st);
                if (dtype) q.set("deficiencyType", dtype);
                if (priority) q.set("priority", priority);
                if (train) q.set("trainStatus", train);
                if (projectId) q.set("projectId", projectId);
                if (keyword) q.set("keyword", keyword);
                const res = await apiRequest(`/api/company/deficiency/records?${q.toString()}`);
                const rows = Array.isArray(res?.records) ? res.records : [];
                const alive = new Set(rows.map((r) => String(r.id || "")));
                [...selectedIds].forEach((id) => {
                    if (!alive.has(id)) selectedIds.delete(id);
                });
                renderGrouped(rows);
            } catch (e) {
                sectionsEl.innerHTML = `<div class="card mb-3"><div class="card-body text-danger small">${esc(
                    e.message || "加载失败"
                )}</div></div>`;
            }
        }

        function resetEditor() {
            document.getElementById("defEditId").value = "";
            const title = document.getElementById("defDocModalTitle");
            if (title) title.textContent = "新建发补记录";
            setProjectEditorMode({}, true);
            document.getElementById("defOpinion").value = "";
            document.getElementById("defPlan").value = "";
            document.getElementById("defSource").value = "";
            document.getElementById("defIssuedOn").value = todayIso();
            document.getElementById("defRemediationStatus").value = "open";
            document.getElementById("defCompletedOn").value = "";
            document.getElementById("defPriority").value = "medium";
            document.getElementById("defType").value = "registration_review";
            renderAssetsList([]);
            document.getElementById("defTrainHint").textContent = "";
            document.getElementById("defBeforeFiles").value = "";
            document.getElementById("defAfterFiles").value = "";
            const wrap = document.getElementById("defTrainProgressWrap");
            if (wrap) wrap.style.display = "none";
        }

        function defAssetRoleLabel(role) {
            const r = String(role || "").trim();
            if (r === "before_doc") return "整改前";
            if (r === "after_doc") return "整改后";
            if (r === "opinion_file") return "意见文件";
            if (r === "plan_file") return "方案文件";
            return r || "附件";
        }

        function renderAssetsList(assets) {
            const list = Array.isArray(assets) ? assets : [];
            const hint = document.getElementById("defAssetsHint");
            const ul = document.getElementById("defAssetsList");
            if (hint) {
                hint.textContent = list.length ? "" : "尚无整改前/后文档附件";
                hint.classList.toggle("d-none", list.length > 0);
            }
            if (!ul) return;
            if (!list.length) {
                ul.innerHTML = "";
                ul.classList.add("d-none");
                return;
            }
            ul.classList.remove("d-none");
            const esc = (s) =>
                String(s ?? "")
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;");
            ul.innerHTML = list
                .map((a) => {
                    const id = String(a.id || "").trim();
                    const name = String(a.display_name || a.displayName || "附件").trim();
                    const role = String(a.role || "").trim();
                    return (
                        `<li class="list-group-item d-flex justify-content-between align-items-center gap-2 flex-wrap py-2" data-asset-id="${esc(id)}">` +
                        `<span class="text-break"><span class="badge bg-secondary me-1">${esc(defAssetRoleLabel(role))}</span>${esc(name)}</span>` +
                        `<span class="btn-group btn-group-sm">` +
                        `<button type="button" class="btn btn-outline-primary btn-def-asset-download" data-asset-id="${esc(id)}" title="下载">下载</button>` +
                        `<button type="button" class="btn btn-outline-secondary btn-def-asset-replace" data-asset-id="${esc(id)}" title="用新文件替换">替换</button>` +
                        `<button type="button" class="btn btn-outline-danger btn-def-asset-delete" data-asset-id="${esc(id)}" title="删除附件">删除</button>` +
                        `</span></li>`
                    );
                })
                .join("");
        }

        function fillEditorFromRecord(r, id) {
            document.getElementById("defEditId").value = String(r.id || id || "");
            const title = document.getElementById("defDocModalTitle");
            if (title) title.textContent = r.id || id ? `编辑发补 #${r.id || id}` : "新建发补记录";
            setProjectEditorMode(r || {}, !(r && (r.id || id)));
            const projectSel = document.getElementById("defProjectId");
            const linkedId = String(r.linked_company_project_id || "").trim();
            if (!isUnlinkedRecord(r) && projectSel && linkedId) {
                projectSel.value = linkedId;
                if (projectSel.value !== linkedId) {
                    const pname = String(r.project_name || r.projectName || linkedId).trim();
                    const opt = document.createElement("option");
                    opt.value = linkedId;
                    opt.textContent = `${pname}（未在当前下拉）`;
                    projectSel.appendChild(opt);
                    projectSel.value = linkedId;
                }
            }
            if (!isUnlinkedRecord(r)) {
                updateDimReadonly();
                const dim = document.getElementById("defDimReadonly");
                if (dim && !(projectSel?.selectedOptions?.[0]?.getAttribute("data-country"))) {
                    const country = String(r.registration_country || "").trim();
                    const cat = String(r.registration_category || "").trim();
                    if (country || cat) dim.textContent = `${country || "—"} / ${cat || "—"}`;
                }
            } else {
                const cEl = document.getElementById("defRegCountry");
                const catEl = document.getElementById("defRegCategory");
                if (cEl) cEl.value = String(r.registration_country || "").trim();
                if (catEl) catEl.value = String(r.registration_category || "").trim();
            }
            document.getElementById("defType").value = r.deficiency_type || "registration_review";
            document.getElementById("defPriority").value = r.priority || "medium";
            document.getElementById("defIssuedOn").value = String(r.issued_on || "").slice(0, 10);
            document.getElementById("defRemediationStatus").value = r.remediation_status || "open";
            document.getElementById("defCompletedOn").value = String(r.completed_on || "").slice(0, 10);
            document.getElementById("defSource").value = r.deficiency_source || "";
            document.getElementById("defOpinion").value = r.opinion_text || "";
            document.getElementById("defPlan").value = r.remediation_plan || "";
            renderAssetsList(Array.isArray(r.assets) ? r.assets : []);
        }

        function softUpdateEditorMeta(r) {
            renderAssetsList(Array.isArray(r?.assets) ? r.assets : []);
            const trainHint = document.getElementById("defTrainHint");
            if (trainHint && r && r.train_status) {
                trainHint.textContent = `训练状态：${trainLabel(r.train_status)}`;
            }
        }

        async function openEditor(id) {
            const orgId = String(orgSel.value || "").trim();
            const seq = ++defEditorSeq;
            if (!id) {
                resetEditor();
                defModal?.show();
                await loadProjectsForOrg();
                return;
            }
            const cached = (cachedRows || []).find((x) => String(x.id || "") === String(id));
            defModal?.show();
            try {
                const projectsReady = loadProjectsForOrg();
                if (cached) {
                    await projectsReady;
                    if (seq !== defEditorSeq) return;
                    fillEditorFromRecord(cached, id);
                } else {
                    const title = document.getElementById("defDocModalTitle");
                    if (title) title.textContent = `加载发补 #${id}…`;
                }
                const [, res] = await Promise.all([
                    projectsReady,
                    apiRequest(
                        `/api/company/deficiency/records/${encodeURIComponent(id)}?organizationId=${encodeURIComponent(orgId)}`
                    ),
                ]);
                if (seq !== defEditorSeq) return;
                const record = res?.record || {};
                if (cached) {
                    // 避免详情晚到覆盖用户已改的项目/字段（导致需选两次）
                    softUpdateEditorMeta(record);
                    if (record.id) document.getElementById("defEditId").value = String(record.id);
                } else {
                    fillEditorFromRecord(record, id);
                }
            } catch (e) {
                if (seq !== defEditorSeq) return;
                notify(e.message || "加载发补失败", "danger");
            }
        }

        async function deleteOne(id, triggerBtn) {
            if (!id) return;
            if (!window.confirm("确定删除该发补记录？删除后不再参与下游注入。")) return;
            const orgId = String(orgSel.value || "").trim();
            await withButtonBusy(triggerBtn, "删除中…", async () => {
                try {
                    await apiRequest(
                        `/api/company/deficiency/records/${encodeURIComponent(id)}?organizationId=${encodeURIComponent(
                            orgId
                        )}`,
                        { method: "DELETE" }
                    );
                    selectedIds.delete(id);
                    notify("已删除", "success");
                    await refreshList();
                } catch (e) {
                    notify(e.message || "删除失败", "danger");
                }
            });
        }

        document.getElementById("defRemediationStatus")?.addEventListener("change", () => {
            const st = String(document.getElementById("defRemediationStatus")?.value || "");
            const completed = document.getElementById("defCompletedOn");
            if (st === "done" && completed && !completed.value) completed.value = todayIso();
            if (st === "open" && completed) completed.value = "";
        });
        document.getElementById("defProjectId")?.addEventListener("change", updateDimReadonly);

        document.getElementById("defFilterForm")?.addEventListener("submit", (ev) => {
            ev.preventDefault();
            Object.keys(groupPages).forEach((k) => delete groupPages[k]);
            expandedGroups.clear();
            const btn = document.getElementById("btnDefSearch");
            withButtonBusy(btn, "查询中…", () => refreshList());
        });
        document.getElementById("btnDefReset")?.addEventListener("click", () => {
            const kw = document.getElementById("defKeyword");
            if (kw) kw.value = "";
            ["defStatusFilter", "defTypeFilter", "defPriorityFilter", "defTrainFilter", "defProjectFilter", "defSortBy"].forEach(
                (id) => {
                    const el = document.getElementById(id);
                    if (el) el.value = id === "defSortBy" ? "import" : "";
                }
            );
            Object.keys(groupPages).forEach((k) => delete groupPages[k]);
            expandedGroups.clear();
            const btn = document.getElementById("btnDefReset");
            withButtonBusy(btn, "重置中…", () => refreshList());
        });
        document.getElementById("defSortBy")?.addEventListener("change", () => {
            renderGrouped(cachedRows);
        });
        document.getElementById("btnDefNew")?.addEventListener("click", () => openEditor(""));
        document.getElementById("btnDefBatchClear")?.addEventListener("click", () => {
            selectedIds.clear();
            sectionsEl.querySelectorAll(".def-row-select, .def-group-select-all").forEach((c) => {
                c.checked = false;
            });
            updateBatchBar();
        });

        function wireBatchFieldToggle(chkId, fieldId) {
            document.getElementById(chkId)?.addEventListener("change", (ev) => {
                const el = document.getElementById(fieldId);
                if (el) el.disabled = !ev.target.checked;
            });
        }
        wireBatchFieldToggle("defBatchChkProject", "defBatchProjectId");
        wireBatchFieldToggle("defBatchChkCountry", "defBatchCountry");
        wireBatchFieldToggle("defBatchChkCategory", "defBatchCategory");
        wireBatchFieldToggle("defBatchChkStatus", "defBatchStatus");
        wireBatchFieldToggle("defBatchChkPriority", "defBatchPriority");
        wireBatchFieldToggle("defBatchChkType", "defBatchType");
        wireBatchFieldToggle("defBatchChkSource", "defBatchSource");

        document.getElementById("btnDefBatchEdit")?.addEventListener("click", async () => {
            if (!selectedIds.size) {
                notify("请先勾选要编辑的记录", "warning");
                return;
            }
            const countEl = document.getElementById("defBatchModalCount");
            if (countEl) countEl.textContent = String(selectedIds.size);
            [
                "defBatchChkProject",
                "defBatchChkCountry",
                "defBatchChkCategory",
                "defBatchChkStatus",
                "defBatchChkPriority",
                "defBatchChkType",
                "defBatchChkSource",
            ].forEach((id) => {
                const el = document.getElementById(id);
                if (el) el.checked = false;
            });
            [
                "defBatchProjectId",
                "defBatchCountry",
                "defBatchCategory",
                "defBatchStatus",
                "defBatchPriority",
                "defBatchType",
                "defBatchSource",
            ].forEach((id) => {
                const el = document.getElementById(id);
                if (el) el.disabled = true;
            });
            const src = document.getElementById("defBatchSource");
            if (src) src.value = "";
            const bc = document.getElementById("defBatchCountry");
            if (bc) bc.value = "";
            const bcat = document.getElementById("defBatchCategory");
            if (bcat) bcat.value = "";
            await loadProjectsForOrg();
            const modalEl = document.getElementById("defBatchModal");
            if (modalEl && window.bootstrap?.Modal) {
                window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
            }
        });

        document.getElementById("btnDefBatchSave")?.addEventListener("click", async () => {
            const ids = [...selectedIds];
            if (!ids.length) return;
            const orgId = String(orgSel.value || "").trim();
            const payload = { organizationId: orgId, ids };
            let any = false;
            if (document.getElementById("defBatchChkProject")?.checked) {
                const pid = String(document.getElementById("defBatchProjectId")?.value || "").trim();
                if (!pid) {
                    notify("请选择所属项目", "warning");
                    return;
                }
                payload.companyProjectId = pid;
                any = true;
            }
            if (document.getElementById("defBatchChkCountry")?.checked) {
                payload.registrationCountry = String(document.getElementById("defBatchCountry")?.value || "").trim();
                any = true;
            }
            if (document.getElementById("defBatchChkCategory")?.checked) {
                payload.registrationCategory = String(document.getElementById("defBatchCategory")?.value || "").trim();
                any = true;
            }
            if (document.getElementById("defBatchChkStatus")?.checked) {
                payload.remediationStatus = String(document.getElementById("defBatchStatus")?.value || "open");
                any = true;
            }
            if (document.getElementById("defBatchChkPriority")?.checked) {
                payload.priority = String(document.getElementById("defBatchPriority")?.value || "medium");
                any = true;
            }
            if (document.getElementById("defBatchChkType")?.checked) {
                payload.deficiencyType = String(document.getElementById("defBatchType")?.value || "registration_review");
                any = true;
            }
            if (document.getElementById("defBatchChkSource")?.checked) {
                payload.deficiencySource = String(document.getElementById("defBatchSource")?.value || "").trim();
                any = true;
            }
            if (!any) {
                notify("请至少勾选一项要修改的字段", "warning");
                return;
            }
            const btn = document.getElementById("btnDefBatchSave");
            await withButtonBusy(btn, "保存中…", async () => {
                try {
                    const res = await apiRequest("/api/company/deficiency/records/batch-update", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    });
                    notify(res?.message || "批量更新完成", res?.failed ? "warning" : "success");
                    const modalEl = document.getElementById("defBatchModal");
                    if (modalEl && window.bootstrap?.Modal) {
                        window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
                    }
                    selectedIds.clear();
                    await refreshList();
                } catch (e) {
                    notify(e.message || "批量更新失败", "danger");
                }
            });
        });

        document.getElementById("btnDefBatchDelete")?.addEventListener("click", async () => {
            const ids = [...selectedIds];
            if (!ids.length) return;
            if (!window.confirm(`确定删除已选的 ${ids.length} 条发补记录？`)) return;
            const orgId = String(orgSel.value || "").trim();
            const btn = document.getElementById("btnDefBatchDelete");
            await withButtonBusy(btn, "删除中…", async () => {
                let ok = 0;
                let fail = 0;
                for (const id of ids) {
                    try {
                        await apiRequest(
                            `/api/company/deficiency/records/${encodeURIComponent(id)}?organizationId=${encodeURIComponent(
                                orgId
                            )}`,
                            { method: "DELETE" }
                        );
                        selectedIds.delete(id);
                        ok += 1;
                    } catch (_) {
                        fail += 1;
                    }
                }
                notify(`批量删除完成：成功 ${ok}${fail ? `，失败 ${fail}` : ""}`, fail ? "warning" : "success");
                await refreshList();
            });
        });

        document.getElementById("btnDefDownloadTemplate")?.addEventListener("click", (ev) => {
            ev.preventDefault();
            window.location.href = "/api/company/deficiency/import-template";
        });

        const excelInput = document.getElementById("defExcelFile");
        const excelBtn = document.getElementById("defExcelImportBtn");
        const setImportBusy = (busy, busyText) => {
            const textEl = document.getElementById("defExcelImportBtnText");
            if (excelBtn) {
                excelBtn.disabled = !!busy;
                excelBtn.classList.toggle("disabled", !!busy);
                excelBtn.setAttribute("aria-busy", busy ? "true" : "false");
            }
            if (excelInput) excelInput.disabled = !!busy;
            if (!textEl) return;
            if (busy) {
                if (textEl.dataset.origText == null) {
                    textEl.dataset.origText = textEl.textContent || "导入Excel";
                }
                textEl.innerHTML =
                    '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
                    (busyText || "处理中…");
            } else if (textEl.dataset.origText != null) {
                textEl.textContent = textEl.dataset.origText;
                delete textEl.dataset.origText;
            }
        };

        excelBtn?.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            if (excelBtn.disabled) return;
            const orgId = String(orgSel.value || "").trim();
            if (!orgId) {
                notify("请先选择公司再导入", "warning");
                return;
            }
            if (!excelInput) {
                notify("未找到文件选择控件，请刷新页面后重试", "danger");
                return;
            }
            excelInput.value = "";
            excelInput.click();
        });

        const syncImportLogsLink = () => {
            const a = document.getElementById("btnDefImportLogs");
            if (!a) return;
            const orgId = String(orgSel.value || "").trim();
            a.href = orgId
                ? `/company/deficiency/import-logs?organizationId=${encodeURIComponent(orgId)}`
                : "/company/deficiency/import-logs";
        };
        orgSel.addEventListener("change", syncImportLogsLink);
        syncImportLogsLink();

        excelInput?.addEventListener("change", async (ev) => {
            const input = ev.target;
            const file = input?.files?.[0];
            const orgId = String(orgSel.value || "").trim();
            const hint = document.getElementById("defImportHint");
            const progressWrap = document.getElementById("defImportProgressWrap");
            const progressBar = document.getElementById("defImportProgressBar");
            const progressLabel = document.getElementById("defImportProgressLabel");
            const progressPct = document.getElementById("defImportProgressPct");
            let progressTimer = null;
            const setProgress = (percent, label) => {
                const pct = Math.max(0, Math.min(100, Number(percent) || 0));
                if (progressWrap) progressWrap.classList.remove("d-none");
                if (progressBar) {
                    progressBar.style.width = `${pct}%`;
                    progressBar.setAttribute("aria-valuenow", String(pct));
                }
                if (progressPct) progressPct.textContent = `${pct}%`;
                if (progressLabel && label) progressLabel.textContent = label;
            };
            const hideProgress = () => {
                if (progressTimer) {
                    clearInterval(progressTimer);
                    progressTimer = null;
                }
                if (progressWrap) progressWrap.classList.add("d-none");
                if (progressBar) {
                    progressBar.style.width = "0%";
                    progressBar.setAttribute("aria-valuenow", "0");
                }
                if (progressPct) progressPct.textContent = "0%";
            };
            const startProgressEstimate = (label, estSec) => {
                const sec = Math.max(2, Number(estSec) || 8);
                let shown = 8;
                const t0 = Date.now();
                setProgress(shown, `${label}…预计约 ${sec} 秒`);
                progressTimer = setInterval(() => {
                    const elapsed = (Date.now() - t0) / 1000;
                    const ratio = Math.min(0.9, elapsed / sec);
                    shown = Math.max(shown, Math.round(ratio * 100));
                    const remain = Math.max(1, Math.ceil(sec - elapsed));
                    setProgress(shown, `${label}…约剩余 ${remain} 秒`);
                }, 400);
            };

            if (!file) return;
            if (!orgId) {
                notify("请先选择公司再导入", "warning");
                input.value = "";
                return;
            }

            const buildFd = (extra) => {
                const fd = new FormData();
                fd.append("organizationId", orgId);
                fd.append("file", file);
                if (extra && typeof extra === "object") {
                    Object.keys(extra).forEach((k) => fd.append(k, String(extra[k])));
                }
                return fd;
            };

            let preview;
            try {
                setImportBusy(true, "解析中…");
                notify(`已选择「${file.name}」，正在解析…`, "info");
                if (hint) hint.textContent = `已选择「${file.name}」，正在解析 Excel…`;
                startProgressEstimate("正在解析 Excel", Math.max(3, Math.ceil((file.size || 0) / (200 * 1024))));
                preview = await apiRequest("/api/company/deficiency/import-excel", {
                    method: "POST",
                    body: buildFd(),
                    timeoutMs: 180000,
                });
            } catch (e) {
                if (hint) hint.textContent = "";
                hideProgress();
                notify(e.message || "Excel 解析失败", "danger");
                input.value = "";
                setImportBusy(false);
                return;
            } finally {
                if (progressTimer) {
                    clearInterval(progressTimer);
                    progressTimer = null;
                }
                setImportBusy(false);
            }

            const summary = preview?.summary || {};
            const importable = Number(summary.importable || 0);
            const failedPreview = Number(summary.failed || 0);
            const total = Number(summary.total || 0);
            const newCount = Number(summary.new || 0);
            const systemDup = Number(summary.systemDup || 0);
            if (!importable) {
                hideProgress();
                const msg =
                    preview?.message ||
                    `未识别到可导入记录（共 ${total} 行，跳过 ${failedPreview} 条）`;
                if (hint) hint.textContent = msg;
                notify(msg, "warning");
                input.value = "";
                return;
            }

            setProgress(100, "解析完成，等待确认");
            let duplicateMode = "create";
            if (systemDup > 0) {
                const tipUpdate =
                    `共 ${total} 行：可导入 ${importable} 条` +
                    (failedPreview ? `，跳过 ${failedPreview} 条` : "") +
                    `。其中 ${systemDup} 条与系统已有重复。\n\n` +
                    `【确定】覆盖更新已有记录\n` +
                    `【取消】改为「新增重复」或放弃导入`;
                if (hint) hint.textContent = tipUpdate.replace(/\n/g, " ");
                if (window.confirm(tipUpdate)) {
                    duplicateMode = "update";
                } else {
                    const tipAdd =
                        `将以【新增重复】导入全部 ${importable} 条（重复次数会增加）。\n\n` +
                        `确定继续？取消则放弃导入。`;
                    if (!window.confirm(tipAdd)) {
                        if (hint) hint.textContent = "已取消导入";
                        hideProgress();
                        input.value = "";
                        return;
                    }
                    duplicateMode = "create";
                }
            } else {
                let confirmMsg = `共 ${total} 行：将新增 ${importable} 条`;
                if (failedPreview) confirmMsg += `，跳过 ${failedPreview} 条`;
                confirmMsg += "。是否继续？";
                if (hint) hint.textContent = confirmMsg;
                if (!window.confirm(confirmMsg)) {
                    if (hint) hint.textContent = "已取消导入";
                    hideProgress();
                    input.value = "";
                    return;
                }
            }
            if (hint) {
                hint.textContent =
                    duplicateMode === "update"
                        ? `已选择：覆盖更新；准备写入 ${importable} 条…`
                        : `已选择：新增（含重复）；准备写入 ${importable} 条…`;
            }

            try {
                setImportBusy(true, "导入中…");
                startProgressEstimate(`正在批量写入约 ${importable} 条`, Math.max(3, Math.ceil(importable / 100)));
                if (hint) {
                    hint.textContent =
                        duplicateMode === "update"
                            ? `正在覆盖更新/新增约 ${importable} 条…`
                            : `正在新增约 ${importable} 条…`;
                }
                const res = await apiRequest("/api/company/deficiency/import-excel", {
                    method: "POST",
                    body: buildFd({ confirm: "1", duplicateMode }),
                    timeoutMs: 300000,
                });
                if (progressTimer) {
                    clearInterval(progressTimer);
                    progressTimer = null;
                }
                setProgress(100, "导入完成");
                const created = Number(res?.created || 0);
                const updatedDone = Number(res?.updated || 0);
                const failedCount = Number(res?.failedCount || 0);
                const batchId = String(res?.importBatchId || "").trim();
                let msg =
                    res?.message ||
                    `导入完成：新增 ${created}${updatedDone ? `，更新 ${updatedDone}` : ""}，失败/跳过 ${failedCount}`;
                const fails = Array.isArray(res?.failed) ? res.failed : [];
                if (fails.length) {
                    msg +=
                        "；明细：" +
                        fails
                            .slice(0, 5)
                            .map((x) => `第${x.excelRow}行 ${x.projectName || ""}:${x.message}`)
                            .join("；");
                }
                if (batchId) {
                    const logsUrl = `/company/deficiency/import-logs?batchId=${encodeURIComponent(batchId)}&organizationId=${encodeURIComponent(orgId)}`;
                    msg += `；批次 ${batchId.slice(0, 8)}…`;
                    if (hint) {
                        hint.innerHTML = `${esc(msg)} <a href="${esc(logsUrl)}">查看导入日志</a>`;
                    }
                    notify(msg + "（可打开导入操作日志查看明细）", failedCount ? "warning" : "success");
                } else {
                    if (hint) hint.textContent = msg;
                    notify(msg, failedCount ? "warning" : "success");
                }
                await refreshList();
            } catch (e) {
                if (hint) hint.textContent = "";
                hideProgress();
                notify(e.message || "导入失败", "danger");
            } finally {
                setImportBusy(false);
                input.value = "";
                setTimeout(() => hideProgress(), 1800);
            }
        });

        orgSel.addEventListener("change", async () => {
            selectedIds.clear();
            Object.keys(groupPages).forEach((k) => delete groupPages[k]);
            expandedGroups.clear();
            projectsCacheOrgId = "";
            projectsCacheRows = null;
            await loadProjectsForOrg({ force: true });
            await refreshList();
        });
        document.getElementById("companyActiveOrgSelect")?.addEventListener("change", async () => {
            await syncOrgOptions();
            await loadProjectsForOrg();
            await refreshList();
        });

        document.getElementById("btnDefSave")?.addEventListener("click", async () => {
            const orgId = String(orgSel.value || "").trim();
            const projectSel = document.getElementById("defProjectId");
            const projectReadonly = !!(
                projectSel?.disabled ||
                document.getElementById("defProjectSelectWrap")?.classList.contains("d-none")
            );
            const projectId = String(projectSel?.value || "").trim();
            const opinion = String(document.getElementById("defOpinion")?.value || "").trim();
            const issuedOn = String(document.getElementById("defIssuedOn")?.value || "").trim();
            const editId = String(document.getElementById("defEditId")?.value || "").trim();
            if (!orgId || !opinion || !issuedOn) {
                notify("请填写公司、发补意见与发补日期", "warning");
                return;
            }
            if (!editId && !projectId) {
                notify("请填写公司、项目、发补意见与发补日期", "warning");
                return;
            }
            if (editId && !projectReadonly && !projectId) {
                notify("请选择所属项目", "warning");
                return;
            }
            const remStatus = String(document.getElementById("defRemediationStatus")?.value || "open");
            let completedOn = String(document.getElementById("defCompletedOn")?.value || "").trim();
            if (remStatus === "done" && !completedOn) completedOn = todayIso();
            const payload = {
                organizationId: orgId,
                opinionText: opinion,
                remediationPlan: String(document.getElementById("defPlan")?.value || "").trim(),
                priority: String(document.getElementById("defPriority")?.value || "medium"),
                issuedOn,
                remediationStatus: remStatus,
                completedOn: remStatus === "done" ? completedOn : null,
                deficiencyType: String(document.getElementById("defType")?.value || "registration_review"),
                deficiencySource: String(document.getElementById("defSource")?.value || "").trim(),
            };
            if (!projectReadonly && projectId) {
                payload.companyProjectId = projectId;
            }
            if (projectReadonly) {
                payload.registrationCountry = String(document.getElementById("defRegCountry")?.value || "").trim();
                payload.registrationCategory = String(document.getElementById("defRegCategory")?.value || "").trim();
            }
            // 新建且意见已存在：按批次提示，可选新增重复或覆盖更新
            let saveAsEditId = editId;
            if (!editId) {
                try {
                    const dupQ = new URLSearchParams();
                    dupQ.set("organizationId", orgId);
                    dupQ.set("opinionText", opinion);
                    const dupRes = await apiRequest(`/api/company/deficiency/records/duplicates?${dupQ.toString()}`);
                    const totalDup = Number(dupRes?.total || 0);
                    if (totalDup > 0) {
                        const batches = Array.isArray(dupRes?.batches) ? dupRes.batches : [];
                        const lines = batches
                            .map((b) => `- ${b.label || "批次"}：${Number(b.count) || 0} 条`)
                            .join("\n");
                        const tipAdd =
                            `系统中已有 ${totalDup} 条相同发补意见：\n${lines || "- （无批次明细）"}\n\n` +
                            `【确定】新增重复（重复次数变为 ${totalDup + 1}）\n` +
                            `【取消】改为覆盖更新或放弃`;
                        if (window.confirm(tipAdd)) {
                            // 新增重复
                        } else {
                            const records = Array.isArray(dupRes?.records) ? dupRes.records : [];
                            const latest = records[0];
                            const latestId = String(latest?.id || "").trim();
                            if (
                                !latestId ||
                                !window.confirm(
                                    `【确定】覆盖更新最近一条记录 #${latestId}` +
                                        `${latest?.project_name ? `（${latest.project_name}）` : ""}\n` +
                                        `【取消】放弃保存`
                                )
                            ) {
                                return;
                            }
                            saveAsEditId = latestId;
                        }
                    }
                } catch (e) {
                    notify(e.message || "重复检查失败，将继续保存", "warning");
                }
            }
            const btn = document.getElementById("btnDefSave");
            let saveOk = false;
            await withButtonBusy(btn, "保存中…", async () => {
                try {
                    let res;
                    if (saveAsEditId) {
                        res = await apiRequest(`/api/company/deficiency/records/${encodeURIComponent(saveAsEditId)}`, {
                            method: "PATCH",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(payload),
                        });
                    } else {
                        res = await apiRequest("/api/company/deficiency/records", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(payload),
                        });
                    }
                    const rid = String(res?.record?.id || saveAsEditId || "").trim();
                    if (rid) {
                        document.getElementById("defEditId").value = rid;
                        const before = document.getElementById("defBeforeFiles")?.files;
                        const after = document.getElementById("defAfterFiles")?.files;
                        const uploadRole = async (fileList, role) => {
                            if (!fileList || !fileList.length) return;
                            const fd = new FormData();
                            fd.append("organizationId", orgId);
                            fd.append("role", role);
                            [...fileList].forEach((f) => fd.append("files", f));
                            await apiRequest(`/api/company/deficiency/records/${encodeURIComponent(rid)}/assets`, {
                                method: "POST",
                                body: fd,
                            });
                        };
                        await uploadRole(before, "before_doc");
                        await uploadRole(after, "after_doc");
                        if (document.getElementById("defBeforeFiles")) document.getElementById("defBeforeFiles").value = "";
                        if (document.getElementById("defAfterFiles")) document.getElementById("defAfterFiles").value = "";
                        try {
                            const detail = await apiRequest(
                                `/api/company/deficiency/records/${encodeURIComponent(rid)}?organizationId=${encodeURIComponent(orgId)}`
                            );
                            softUpdateEditorMeta(detail?.record || {});
                        } catch (_e) { /* ignore */ }
                    }
                    notify(res?.message || "已保存", "success");
                    saveOk = true;
                } catch (e) {
                    notify(e.message || "保存失败", "danger");
                }
            });
            if (saveOk) {
                defEditorSeq += 1;
                defModal?.hide();
                await refreshList();
            }
        });

        let pendingReplaceAssetId = "";
        const defAssetsListEl = document.getElementById("defAssetsList");
        const defAssetReplaceInput = document.getElementById("defAssetReplaceInput");
        defAssetsListEl?.addEventListener("click", async (ev) => {
            const btn = ev.target?.closest?.("button");
            if (!btn || !defAssetsListEl.contains(btn)) return;
            const orgId = String(orgSel.value || "").trim();
            const rid = String(document.getElementById("defEditId")?.value || "").trim();
            const assetId = String(btn.dataset.assetId || "").trim();
            if (!orgId || !rid || !assetId) {
                notify("请先保存发补记录后再操作附件", "warning");
                return;
            }
            if (btn.classList.contains("btn-def-asset-download")) {
                const q = new URLSearchParams();
                q.set("organizationId", orgId);
                const url =
                    `/api/company/deficiency/records/${encodeURIComponent(rid)}/assets/${encodeURIComponent(assetId)}/download?${q.toString()}`;
                window.open(url, "_blank", "noopener");
                return;
            }
            if (btn.classList.contains("btn-def-asset-replace")) {
                pendingReplaceAssetId = assetId;
                if (defAssetReplaceInput) {
                    defAssetReplaceInput.value = "";
                    defAssetReplaceInput.click();
                }
                return;
            }
            if (btn.classList.contains("btn-def-asset-delete")) {
                if (!window.confirm("确定删除该附件？删除后需重新训练才会更新知识库。")) return;
                try {
                    await apiRequest(
                        `/api/company/deficiency/records/${encodeURIComponent(rid)}/assets/${encodeURIComponent(assetId)}?organizationId=${encodeURIComponent(orgId)}`,
                        { method: "DELETE" }
                    );
                    notify("附件已删除", "success");
                    const detail = await apiRequest(
                        `/api/company/deficiency/records/${encodeURIComponent(rid)}?organizationId=${encodeURIComponent(orgId)}`
                    );
                    softUpdateEditorMeta(detail?.record || {});
                    await refreshList();
                } catch (e) {
                    notify(e.message || "删除失败", "danger");
                }
            }
        });
        defAssetReplaceInput?.addEventListener("change", async () => {
            const file = defAssetReplaceInput.files && defAssetReplaceInput.files[0];
            const assetId = pendingReplaceAssetId;
            pendingReplaceAssetId = "";
            defAssetReplaceInput.value = "";
            if (!file || !assetId) return;
            const orgId = String(orgSel.value || "").trim();
            const rid = String(document.getElementById("defEditId")?.value || "").trim();
            if (!orgId || !rid) {
                notify("请先保存发补记录后再替换附件", "warning");
                return;
            }
            if (!window.confirm(`确定用「${file.name}」替换该附件？`)) return;
            const fd = new FormData();
            fd.append("organizationId", orgId);
            fd.append("file", file);
            try {
                await apiRequest(
                    `/api/company/deficiency/records/${encodeURIComponent(rid)}/assets/${encodeURIComponent(assetId)}/replace`,
                    { method: "POST", body: fd }
                );
                notify("附件已替换", "success");
                const detail = await apiRequest(
                    `/api/company/deficiency/records/${encodeURIComponent(rid)}?organizationId=${encodeURIComponent(orgId)}`
                );
                softUpdateEditorMeta(detail?.record || {});
                await refreshList();
            } catch (e) {
                notify(e.message || "替换失败", "danger");
            }
        });

        document.getElementById("btnDefTrain")?.addEventListener("click", async () => {
            const orgId = String(orgSel.value || "").trim();
            const editId = String(document.getElementById("defEditId")?.value || "").trim();
            if (!orgId || !editId) {
                notify("请先保存发补记录再训练", "warning");
                return;
            }
            const btn = document.getElementById("btnDefTrain");
            const hint = document.getElementById("defTrainHint");
            const wrap = document.getElementById("defTrainProgressWrap");
            const bar = document.getElementById("defTrainProgressBar");
            await withButtonBusy(btn, "训练中…", async () => {
                if (hint) hint.textContent = "训练中…";
                if (wrap) wrap.style.display = "";
                if (bar) bar.style.width = "40%";
                try {
                    const res = await apiRequest(`/api/company/deficiency/records/${encodeURIComponent(editId)}/train`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ organizationId: orgId }),
                    });
                    if (bar) bar.style.width = "100%";
                    if (hint) hint.textContent = res?.message || "训练完成";
                    notify(res?.message || "训练完成", "success");
                    await refreshList();
                    await openEditor(editId);
                } catch (e) {
                    if (hint) hint.textContent = e.message || "训练失败";
                    notify(e.message || "训练失败", "danger");
                } finally {
                    if (wrap) wrap.style.display = "none";
                    if (bar) bar.style.width = "0%";
                }
            });
        });

        document.querySelector('[data-bs-target="#trainTabDeficiency"]')?.addEventListener("shown.bs.tab", async () => {
            await syncOrgOptions();
            await loadProjectsForOrg();
            await refreshList();
        });
        syncOrgOptions();
    }

    async function initDictMaintenanceOnly() {
        bindDictMaintenanceEvents();
        await loadAdminOrganizationsForDict();
        await loadRegisteredCountriesDict();
        await loadTeams();
    }

    async function boot() {
        if (body) {
            wireCompanyLogoutButton();
            initCompanySessionBar();
            initCompanyTrainingPanel();
            initTrainingHubExtras();
            initDeficiencyPanel();
            initStarFilterSelect();
            initGroupBySelect();
            bindEvents();
            bindDictMaintenanceEvents();
            await loadRegisteredCountriesDict();
            await Promise.all([
                loadOrganizationsContext(),
                loadTeams(),
                loadProjects(true),
            ]);
            return;
        }
        if (document.getElementById("countryDictList")) {
            await initDictMaintenanceOnly();
        }
    }

    if (typeof registerPageInit === "function") {
        registerPageInit(boot);
    } else if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
