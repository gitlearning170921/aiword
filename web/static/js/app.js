const App = {
    async request(url, options = {}) {
        const root = (window.__SCRIPT_ROOT__ != null ? String(window.__SCRIPT_ROOT__) : "").replace(/\/+$/, "");
        if (root && typeof url === "string") {
            // 仅对站内绝对路径（/api/xxx）自动加前缀；避免影响 http(s):// 外链与相对路径
            if (url.startsWith("/") && !url.startsWith(root + "/")) {
                url = root + url;
            }
        }
        const timeoutMs = Number(options.timeoutMs) > 0 ? Number(options.timeoutMs) : 0;
        const fetchOpts = { ...options };
        delete fetchOpts.timeoutMs;
        let timer = null;
        let controller = null;
        if (timeoutMs > 0) {
            controller = new AbortController();
            fetchOpts.signal = controller.signal;
            timer = setTimeout(() => controller.abort(), timeoutMs);
        }
        let response;
        try {
            response = await fetch(url, { credentials: "include", ...fetchOpts });
        } catch (networkError) {
            if (networkError && networkError.name === "AbortError") {
                throw new Error(`请求超时（${Math.round(timeoutMs / 1000)} 秒），请稍后重试`);
            }
            throw new Error("网络错误，请检查网络连接");
        } finally {
            if (timer) clearTimeout(timer);
        }
        
        if (!response.ok) {
            let message = `请求失败 (${response.status})`;
            let data = null;
            
            try {
                const text = await response.text();
                if (text) {
                    try {
                        data = JSON.parse(text);
                        message = data.message || message;
                    } catch (jsonError) {
                        if (text.includes("Internal Server Error") || response.status === 500) {
                            message = "服务器内部错误，请联系管理员";
                        }
                    }
                }
            } catch (readError) {}
            
            if (response.status === 401 && data && data.needsLogin) {
                const loginPath = (root || "") + "/login";
                if (window.location.pathname !== loginPath) {
                    window.location.href = loginPath;
                }
                throw new Error("需要登录");
            }
            
            if (response.status === 401 && data && data.needsPage13Auth) {
                const loginPath = (root || "") + "/login";
                if (window.location.pathname !== loginPath) {
                    if (!window._page13Redirecting) {
                        window._page13Redirecting = true;
                        setTimeout(function() {
                            window.location.href = window.location.pathname || ((root || "") + "/upload");
                        }, 50);
                    }
                }
                throw new Error("需要访问密码");
            }
            
            if (response.status === 409 && data && data.needsConfirmation) {
                if (options.body instanceof FormData) {
                    const err = new Error(data.message || "存在重复记录，是否替换？");
                    err.is409Replace = true;
                    throw err;
                }
                const confirmReplace = window.confirm(data.message);
                if (!confirmReplace) {
                    throw new Error("用户取消了替换操作");
                }
                const nextBody = (() => {
                    const payload = JSON.parse(options.body || "{}");
                    payload.replace = true;
                    return JSON.stringify(payload);
                })();
                return this.request(url, { ...options, body: nextBody });
            }
            
            throw new Error(message);
        }
        
        const text = await response.text();
        if (!text) return {};
        try {
            return JSON.parse(text);
        } catch (e) {
            if (response.ok) {
                return { success: false, message: "响应解析异常，若通知已发出请忽略" };
            }
            throw new Error("响应格式异常");
        }
    },
    notify(message, variant = "success") {
        const alert = document.createElement("div");
        alert.className = `alert alert-${variant} position-fixed top-0 end-0 m-3`;
        alert.style.zIndex = 1055;
        alert.textContent = message;
        document.body.appendChild(alert);
        setTimeout(() => alert.remove(), 3000);
    },
};

/** 子路径部署（SCRIPT_NAME）下拼接站内路径，与 App.request 前缀规则一致。 */
function _appPath(path) {
    const root = (window.__SCRIPT_ROOT__ != null ? String(window.__SCRIPT_ROOT__) : "").replace(/\/+$/, "");
    const p = path && path.charAt(0) === "/" ? path : "/" + (path || "");
    return (root || "") + p;
}

function _isLoginPath() {
    const p = window.location.pathname || "";
    return p === "/login" || p === _appPath("/login") || p.endsWith("/login");
}

/** 按钮忙碌态：finally 中传 busy=false 确保「保存中…」不会一直卡住。 */
function _setButtonBusy(btn, busy, busyText) {
    if (!btn) return;
    if (busy) {
        if (btn.dataset.origBtnText == null) btn.dataset.origBtnText = btn.textContent || "";
        btn.disabled = true;
        btn.textContent = busyText || "保存中…";
    } else {
        btn.disabled = false;
        if (btn.dataset.origBtnText != null) {
            btn.textContent = btn.dataset.origBtnText;
            delete btn.dataset.origBtnText;
        }
    }
}

function renderPlaceholderChips(container, values = []) {
    if (!container) return;
    container.innerHTML = "";
    if (!values.length) {
        container.innerHTML = '<p class="mb-0 text-muted">未识别到占位符。</p>';
        return;
    }
    const list = document.createElement("ol");
    list.className = "list-group list-group-numbered placeholder-list";
    values.forEach((item) => {
        const li = document.createElement("li");
        li.className = "list-group-item d-flex justify-content-between align-items-center";
        li.innerHTML = `<span class="placeholder-text">${item}</span>`;
        list.appendChild(li);
    });
    container.appendChild(list);
}

let rowCounter = 0;
let taskTypesCache = [];
let completionStatusesCache = [];
let auditStatusesCache = [];
let allRecordsCache = [];
let lastRenderedRecords = [];

function _escTitle(s) {
    if (s == null || s === undefined) return "";
    return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _renderNotesHtml(notes) {
    if (notes == null || notes === "") return "-";
    var lines = String(notes).split("\n").map(function (l) { return l.trim(); }).filter(Boolean);
    if (!lines.length) return "-";
    var urlRe = /^https?:\/\/\S+/i;
    var localFileRe = /^\/api\/uploads\/note-files\//i;
    var parts = [];
    var fileCount = 0;
    lines.forEach(function (ln) {
        if (urlRe.test(ln) || localFileRe.test(ln)) {
            fileCount++;
            var label;
            var nameMatch = ln.match(/([^/\\?#]+)$/);
            var rawName = nameMatch ? nameMatch[1] : "";
            if (/\.(pdf|doc|docx|xls|xlsx|png|jpg|jpeg)$/i.test(rawName)) {
                var displayName = rawName.replace(/^\d{14,}_/, "");
                label = displayName || "附件" + fileCount;
            } else {
                label = "链接" + fileCount;
            }
            parts.push('<a href="' + ln.replace(/"/g, "&quot;") + '" target="_blank" class="text-primary me-1" title="' + ln.replace(/"/g, "&quot;") + '">📎' + label + '</a>');
        } else {
            parts.push('<span>' + ln.replace(/</g, "&lt;").replace(/>/g, "&gt;") + '</span>');
        }
    });
    return parts.join(" ");
}
let recordsSortKey = "";
let recordsSortDir = "asc";
let recordsGroupBy = "none";
let recordsCollapsedGroups = new Set();

/** 任务类型一级分类：file=文件型；matter=事项型。历史/未识别值按 file 处理。 */
const TASK_TYPE_CATEGORY_FILE = "file";
const TASK_TYPE_CATEGORY_MATTER = "matter";
const TASK_TYPE_CATEGORY_OPTIONS = [
    { value: TASK_TYPE_CATEGORY_FILE, label: "文件型" },
    { value: TASK_TYPE_CATEGORY_MATTER, label: "事项型" },
];

function _normalizeTaskTypeCategory(raw) {
    const v = String(raw == null ? "" : raw).trim().toLowerCase();
    return v === TASK_TYPE_CATEGORY_MATTER ? TASK_TYPE_CATEGORY_MATTER : TASK_TYPE_CATEGORY_FILE;
}

/** 通过任务类型名查所属一级分类（未在配置中的历史/外部值默认按 file 处理）。 */
function taskTypeCategoryOf(name) {
    if (!name) return TASK_TYPE_CATEGORY_FILE;
    const hit = (taskTypesCache || []).find((t) => String(t.name) === String(name));
    return _normalizeTaskTypeCategory(hit ? hit.category : TASK_TYPE_CATEGORY_FILE);
}

const MATTER_EXEC_NOTES_MSG = "请在备注中填写事项完成情况";
const MATTER_EXEC_NOTES_INVALID_MSG = "请在备注中填写有效的事项完成情况，不可仅填空格或符号";

/** 事项型备注：去空白后须含中文/字母/数字，拒绝纯空格或纯符号。 */
function isMeaningfulMatterExecutionNotes(raw) {
    const s = String(raw ?? "").trim();
    if (!s) return false;
    const core = s.replace(/\s+/g, "");
    if (!core) return false;
    return /[\u4e00-\u9fffA-Za-z0-9]/.test(core);
}

async function loadTaskTypes() {
    try {
        const res = await App.request("/api/configs/task-types");
        taskTypesCache = (res.taskTypes || []).map((t) => ({
            ...t,
            category: _normalizeTaskTypeCategory(t && t.category),
        }));
    } catch (e) {
        taskTypesCache = [];
    }
    return taskTypesCache;
}

async function loadCompletionStatuses() {
    try {
        const res = await App.request("/api/configs/completion-statuses");
        completionStatusesCache = res.completionStatuses || [];
    } catch (e) {
        completionStatusesCache = [];
    }
    return completionStatusesCache;
}

async function loadAuditStatuses() {
    try {
        const res = await App.request("/api/configs/audit-statuses");
        auditStatusesCache = res.auditStatuses || [];
    } catch (e) {
        auditStatusesCache = [];
    }
    return auditStatusesCache;
}

/**
 * 渲染「任务类型」下拉。
 * @param {string} category 仅展示该分类（file/matter）下的类型；空/null 表示全部。
 */
function createTaskTypeSelect(category) {
    const select = document.createElement("select");
    select.className = "form-select form-select-sm task-type";
    select.innerHTML = '<option value="">选择类型</option>';
    const wantCat = category ? _normalizeTaskTypeCategory(category) : "";
    (taskTypesCache || []).forEach((t) => {
        if (wantCat && _normalizeTaskTypeCategory(t.category) !== wantCat) return;
        const opt = document.createElement("option");
        opt.value = t.name;
        opt.textContent = t.name;
        select.appendChild(opt);
    });
    return select;
}

/** 渲染「任务类别」下拉（文件型/事项型）。 */
function createTaskCategorySelect(currentCategory) {
    const select = document.createElement("select");
    select.className = "form-select form-select-sm task-category";
    TASK_TYPE_CATEGORY_OPTIONS.forEach((opt) => {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        select.appendChild(o);
    });
    select.value = _normalizeTaskTypeCategory(currentCategory);
    return select;
}

/**
 * 用当前 category 重填 task type 下拉，并尽量保持原值；如原值不属于该 category 则置空。
 * 当 currentValue 不在新选项中（比如老数据/已删除类型）时，附加 option 以保留原值。
 */
function refillTaskTypeOptions(typeSelect, category, currentValue) {
    if (!typeSelect) return;
    const cat = _normalizeTaskTypeCategory(category);
    const keep = (currentValue || "").trim();
    typeSelect.innerHTML = '<option value="">选择类型</option>';
    let matched = false;
    (taskTypesCache || []).forEach((t) => {
        if (_normalizeTaskTypeCategory(t.category) !== cat) return;
        const opt = document.createElement("option");
        opt.value = t.name;
        opt.textContent = t.name;
        if (keep && String(t.name) === keep) matched = true;
        typeSelect.appendChild(opt);
    });
    if (keep && !matched) {
        // 原值不在新类别下：保留为 disabled 提示，让用户重新选择
        const opt = document.createElement("option");
        opt.value = keep;
        opt.textContent = keep + "（不在当前类别）";
        opt.disabled = true;
        typeSelect.appendChild(opt);
        typeSelect.value = "";
    } else if (matched) {
        typeSelect.value = keep;
    } else {
        typeSelect.value = "";
    }
}

/** 联动两个下拉：类别变 → 重填类型；类型变 → 同步反推类别（已在 cache 时）。 */
function bindTaskCategoryAndTypeSelects(categorySelect, typeSelect, initialType) {
    if (!categorySelect || !typeSelect) return;
    const initType = (initialType || "").trim();
    const initCat = initType ? taskTypeCategoryOf(initType) : _normalizeTaskTypeCategory(categorySelect.value);
    categorySelect.value = initCat;
    refillTaskTypeOptions(typeSelect, initCat, initType);
    categorySelect.addEventListener("change", () => {
        const cat = _normalizeTaskTypeCategory(categorySelect.value);
        refillTaskTypeOptions(typeSelect, cat, "");
    });
    typeSelect.addEventListener("change", () => {
        const v = (typeSelect.value || "").trim();
        if (!v) return;
        const realCat = taskTypeCategoryOf(v);
        if (categorySelect.value !== realCat) categorySelect.value = realCat;
    });
}

/** 若下拉中不存在该 value，则追加 option，避免赋 .value 失败导致保存时 taskType 为空。 */
function ensureSelectHasOption(select, value, labelNote) {
    if (!select || value === undefined || value === null) return;
    const v = String(value).trim();
    if (!v) return;
    const exists = Array.from(select.options).some((o) => o.value === v);
    if (!exists) {
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = labelNote ? v + labelNote : v;
        select.appendChild(opt);
    }
}

function createCompletionStatusSelect(currentValue, uploadId) {
    const select = document.createElement("select");
    select.className = "form-select form-select-sm completion-status-select";
    select.dataset.uploadId = uploadId;
    select.innerHTML = '<option value="">选择状态</option>';
    completionStatusesCache.forEach(s => {
        const opt = document.createElement("option");
        opt.value = s.name;
        opt.textContent = s.name;
        if (currentValue === s.name) opt.selected = true;
        select.appendChild(opt);
    });
    return select;
}

function getDueDateStyle(dueDateStr) {
    if (!dueDateStr) return { class: "", text: "-" };
    
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const dueDate = new Date(dueDateStr);
    dueDate.setHours(0, 0, 0, 0);
    
    const diffDays = Math.ceil((dueDate - today) / (1000 * 60 * 60 * 24));
    
    if (diffDays < 0) {
        return { class: "bg-danger text-white", text: dueDateStr, title: `已逾期 ${Math.abs(diffDays)} 天` };
    } else if (diffDays <= 1) {
        return { class: "bg-danger-subtle text-danger", text: dueDateStr, title: diffDays === 0 ? "今天截止" : "明天截止" };
    } else if (diffDays <= 3) {
        return { class: "bg-warning-subtle text-warning-emphasis", text: dueDateStr, title: `还剩 ${diffDays} 天` };
    }
    return { class: "", text: dueDateStr, title: `还剩 ${diffDays} 天` };
}

function normalizeDocLink(value) {
    if (!value || typeof value !== "string") return value || "";
    const s = value.trim();
    if (!s) return "";
    const lower = s.toLowerCase();
    const https = lower.indexOf("https://");
    const http = lower.indexOf("http://");
    if (https !== -1) return s.slice(https);
    if (http !== -1) return s.slice(http);
    return s;
}

function isValidDocLink(value) {
    if (!value || typeof value !== "string") return true;
    const s = value.trim();
    if (!s) return true;
    const lines = s.split("\n").map((ln) => ln.trim()).filter(Boolean);
    for (const line of lines) {
        const normalized = normalizeDocLink(line);
        const lower = normalized.toLowerCase();
        if (!lower.startsWith("http://") && !lower.startsWith("https://")) return false;
    }
    return true;
}

let projectsMetaCache = []; // [{name, priority, status, ...}]

function _projectSelectOptionCaption(p) {
    const prio = p.priorityLabel ? `【${p.priorityLabel}】` : "";
    const nm = (p.name || "").trim() || "未命名";
    const sid = (p.id || "").trim();
    const head = sid ? `${prio}${nm} (ID:${sid})` : `${prio}${nm}`;
    const extras = [];
    const prod = (p.registeredProductName || "").trim();
    if (prod) extras.push(`产品:${prod}`);
    const c = (p.registeredCountry || "").trim();
    if (c) extras.push(`国家:${c}`);
    const cat = (p.registeredCategory || "").trim();
    if (cat) extras.push(`类别:${cat}`);
    if (!extras.length) return head;
    return `${head} | ${extras.join(" | ")}`;
}

function _getProjectOptions(activeOnly) {
    const arr = Array.isArray(projectsMetaCache) ? projectsMetaCache : [];
    return arr
        .filter((p) => {
            const st = (p && p.status) ? String(p.status).toLowerCase() : "active";
            return activeOnly ? st !== "ended" : true;
        })
        .slice()
        .sort((a, b) => {
            const pa = Number.isFinite(Number(a.priority)) ? Number(a.priority) : 2;
            const pb = Number.isFinite(Number(b.priority)) ? Number(b.priority) : 2;
            if (pa !== pb) return pb - pa;
            return String(a.name || "").localeCompare(String(b.name || ""), "zh");
        });
}

function _populateProjectNameSelect(selectEl, selectedName) {
    if (!selectEl) return;
    const current = (selectedName != null ? String(selectedName) : String(selectEl.value || "")).trim();
    const opts = _getProjectOptions(true);
    selectEl.innerHTML = '<option value="">— 请选择项目 —</option>';
    opts.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.id || (p.projectKey || p.name);
        opt.textContent = _projectSelectOptionCaption(p);
        opt.dataset.registeredCountry = p.registeredCountry || "";
        opt.dataset.registeredCategory = p.registeredCategory || "";
        opt.dataset.baseName = p.name || "";
        opt.dataset.projectKey = p.projectKey || p.name || "";
        selectEl.appendChild(opt);
    });
    if (current) {
        // 若当前项目不在列表（历史数据/尚未刷新），临时插入以避免丢值
        const exists = Array.from(selectEl.options).some((o) => String(o.value) === current);
        if (!exists) {
            const opt = document.createElement("option");
            opt.value = current;
            opt.textContent = current;
            opt.dataset.registeredCountry = "";
            opt.dataset.registeredCategory = "";
            selectEl.appendChild(opt);
        }
        selectEl.value = current;
    }
}

const PROJECT_ENTRY_META_LS_PREFIX = "aiword_project_entry_meta_";

function _projectEntryMetaStorageKey(projectSelectValue) {
    return PROJECT_ENTRY_META_LS_PREFIX + String(projectSelectValue || "").trim();
}

function _captureProjectMetaFromBlock(block) {
    if (!block) return {};
    const g = (sel) => (block.querySelector(sel)?.value || "").trim();
    return {
        projectCode: g(".project-code"),
        projectNotes: g(".project-notes"),
        businessSide: g(".project-business-side"),
        product: g(".project-product"),
        country: g(".project-country"),
        registeredProductName: g(".project-registered-product-name"),
        model: g(".project-model"),
        registrationVersion: g(".project-registration-version"),
    };
}

function _applyProjectMetaToBlock(block, meta) {
    if (!block || !meta) return;
    const set = (sel, key) => {
        const el = block.querySelector(sel);
        const v = meta[key];
        if (el && v != null && String(v).trim() !== "") el.value = String(v).trim();
    };
    set(".project-code", "projectCode");
    set(".project-notes", "projectNotes");
    set(".project-business-side", "businessSide");
    set(".project-product", "product");
    set(".project-country", "country");
    set(".project-registered-product-name", "registeredProductName");
    set(".project-model", "model");
    set(".project-registration-version", "registrationVersion");
}

function _loadProjectMetaForEntry(projectSelectValue, projectKey) {
    let meta = null;
    const key = _projectEntryMetaStorageKey(projectSelectValue);
    try {
        const raw = localStorage.getItem(key);
        if (raw) meta = JSON.parse(raw);
    } catch (_) {}
    if (!meta || typeof meta !== "object") meta = {};
    const fromRecords = _loadProjectMetaFromSavedRecords(projectKey);
    if (fromRecords) {
        Object.keys(fromRecords).forEach((k) => {
            if (!meta[k] && fromRecords[k]) meta[k] = fromRecords[k];
        });
    }
    return meta;
}

function _loadProjectMetaFromSavedRecords(projectKey) {
    const name = String(projectKey || "").trim();
    if (!name) return null;
    const canon = _canonicalProjectKeyForPick(name, "");
    const hits = (allRecordsCache || []).filter(
        (r) =>
            _canonicalProjectKeyForPick(r.projectName, r.projectId) === canon ||
            String(r.projectName || "").trim() === name
    );
    if (!hits.length) return null;
    const r = hits.slice().sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")))[0];
    return {
        projectCode: r.projectCode || "",
        projectNotes: r.projectNotes || "",
        businessSide: r.businessSide || "",
        product: r.product || "",
        country: r.country || "",
        registeredProductName: r.registeredProductName || "",
        model: r.model || "",
        registrationVersion: r.registrationVersion || "",
    };
}

function _persistProjectMetaFromBlock(block) {
    const sel = block?.querySelector(".project-name");
    const pid = (sel?.value || "").trim();
    if (!pid) return;
    try {
        localStorage.setItem(_projectEntryMetaStorageKey(pid), JSON.stringify(_captureProjectMetaFromBlock(block)));
    } catch (_) {}
}

function _countTaskRowsInBlock(block) {
    return block ? block.querySelectorAll(".project-task-tbody tr").length : 0;
}

function _countSavableTaskRowsInBlock(block) {
    if (!block) return 0;
    const projectSelect = block.querySelector(".project-name");
    const projectId = (projectSelect?.value || "").trim();
    const projectKey = (projectSelect?.options?.[projectSelect.selectedIndex]?.dataset?.projectKey || "").trim();
    if (!projectId || !projectKey) return 0;
    let n = 0;
    block.querySelectorAll(".project-task-tbody tr").forEach((row) => {
        const fileName = (row.querySelector(".task-filename")?.value || "").trim();
        const author = (row.querySelector(".task-author")?.value || "").trim();
        if (fileName && author) n++;
    });
    return n;
}

function _updateProjectBlockTaskRowCount(block) {
    if (!block) return;
    const el = block.querySelector(".project-entry-task-row-count");
    if (!el) return;
    const total = _countTaskRowsInBlock(block);
    const savable = _countSavableTaskRowsInBlock(block);
    el.textContent =
        total > 0
            ? `已添加 ${total} 行` + (savable !== total ? `（其中 ${savable} 行可保存）` : "（均可保存）")
            : "已添加 0 行";
}

function _copyPrevTaskRowFields(prevRow, newRowEl, newCatSelect) {
    newRowEl.querySelector(".task-filename").value = prevRow.querySelector(".task-filename")?.value ?? "";
    const prevCatSelect = prevRow.querySelector(".task-type-cell .task-category");
    const prevTypeSelect = prevRow.querySelector(".task-type-cell .task-type");
    const newTypeSelect = newRowEl.querySelector(".task-type-cell .task-type");
    if (newCatSelect && prevCatSelect) {
        newCatSelect.value = _normalizeTaskTypeCategory(prevCatSelect.value);
    }
    if (prevTypeSelect && newTypeSelect) {
        const pv = (prevTypeSelect.value || "").trim();
        const pc = newCatSelect ? _normalizeTaskTypeCategory(newCatSelect.value) : TASK_TYPE_CATEGORY_FILE;
        refillTaskTypeOptions(newTypeSelect, pc, pv);
        if (pv) ensureSelectHasOption(newTypeSelect, pv, "（沿用上行）");
        newTypeSelect.value = pv;
    }
    const prevModuleSelect = prevRow.querySelector(".task-module-cell select");
    const newModuleSelect = newRowEl.querySelector(".task-module-cell select");
    if (prevModuleSelect && newModuleSelect) newModuleSelect.value = prevModuleSelect.value || "";
    newRowEl.querySelector(".task-link").value = prevRow.querySelector(".task-link")?.value ?? "";
    newRowEl.querySelector(".task-file-version").value = prevRow.querySelector(".task-file-version")?.value ?? "";
    newRowEl.querySelector(".task-author").value = prevRow.querySelector(".task-author")?.value ?? "";
    newRowEl.querySelector(".task-duedate").value = prevRow.querySelector(".task-duedate")?.value ?? "";
    newRowEl.querySelector(".task-notes").value = prevRow.querySelector(".task-notes")?.value ?? "";
    newRowEl.querySelector(".task-doc-display-date").value = prevRow.querySelector(".task-doc-display-date")?.value ?? "";
    newRowEl.querySelector(".task-reviewer").value = prevRow.querySelector(".task-reviewer")?.value ?? "";
    newRowEl.querySelector(".task-approver").value = prevRow.querySelector(".task-approver")?.value ?? "";
    newRowEl.querySelector(".task-displayed-author").value = prevRow.querySelector(".task-displayed-author")?.value ?? "";
}

/** 将任务记录里的项目名规范为项目库中的标准名称（避免「短名 + 带注册类别全名」在下拉中重复两项）。 */
function _canonicalProjectKeyForPick(rawName, projectId) {
    const id = String(projectId || "").trim();
    if (id) {
        const byId = (projectsMetaCache || []).find((p) => String(p.id || "").trim() === id);
        if (byId) return String(byId.name || "").trim();
    }
    const s = String(rawName || "").trim();
    if (!s) return "";
    const byName = (projectsMetaCache || []).find((p) => {
        const nm = String(p.name || "").trim();
        if (!nm) return false;
        return s === nm || s.startsWith(nm + " (") || s.startsWith(nm + "(");
    });
    if (byName) return String(byName.name || "").trim();
    const m = s.match(/^(.+?)\s*\([^)]*\)\s*$/);
    return m && m[1] ? m[1].trim() : s;
}

function _getSavedProjectPickEntries() {
    const map = new Map();
    (allRecordsCache || []).forEach((r) => {
        const raw = String(r.projectName || "").trim();
        if (!raw) return;
        const canon = _canonicalProjectKeyForPick(raw, r.projectId);
        const key = canon || raw;
        const prev = map.get(key);
        if (prev) prev.count += 1;
        else map.set(key, { canonical: key, count: 1 });
    });
    return [...map.values()].sort((a, b) => a.canonical.localeCompare(b.canonical, "zh"));
}

function refreshSavedProjectPickSelect() {
    const sel = document.getElementById("pickSavedProjectForEntry");
    if (!sel) return;
    const cur = (sel.value || "").trim();
    const curCanon = cur ? _canonicalProjectKeyForPick(cur, "") : "";
    const entries = _getSavedProjectPickEntries();
    sel.innerHTML = '<option value="">— 请选择已有项目 —</option>';
    entries.forEach((ent) => {
        const opt = document.createElement("option");
        opt.value = ent.canonical;
        const meta = (projectsMetaCache || []).find((p) => String(p.name || "").trim() === ent.canonical);
        let label = ent.canonical;
        if (meta && (meta.registeredCategory || meta.registeredCountry)) {
            const bits = [meta.registeredCategory, meta.registeredCountry].filter(Boolean);
            if (bits.length) label += `（${bits.join(" / ")}）`;
        }
        if (ent.count > 0) label += ` · 已保存 ${ent.count} 条`;
        opt.textContent = label;
        sel.appendChild(opt);
    });
    if (curCanon) {
        const hit = entries.find((e) => e.canonical === curCanon);
        if (hit) sel.value = hit.canonical;
    }
}

function _resolveProjectSelectValueForProjectName(projectName) {
    const name = String(projectName || "").trim();
    if (!name) return "";
    const lookup = _canonicalProjectKeyForPick(name, "") || name;
    const hit = (projectsMetaCache || []).find((p) => String(p.name || "").trim() === lookup);
    if (hit && (hit.id || "").trim()) return String(hit.id).trim();
    if (hit) return String(hit.name || "").trim();
    return name;
}

function _selectProjectOnEntryBlock(block, projectName) {
    const sel = block?.querySelector(".project-name");
    const name = String(projectName || "").trim();
    if (!sel || !name) return "";
    const lookup = _canonicalProjectKeyForPick(name, "") || name;
    _populateProjectNameSelect(sel, "");
    let matched = "";
    for (const o of sel.options) {
        const pk = String(o.dataset.projectKey || o.dataset.baseName || "").trim();
        if (pk === lookup || pk === name) {
            sel.value = o.value;
            matched = o.value;
            break;
        }
    }
    if (!matched) {
        const vid = _resolveProjectSelectValueForProjectName(name);
        _populateProjectNameSelect(sel, vid);
        matched = (sel.value || "").trim();
    }
    if (!matched) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        opt.dataset.projectKey = name;
        opt.dataset.baseName = name;
        opt.dataset.registeredCountry = "";
        sel.appendChild(opt);
        sel.value = name;
        matched = name;
    }
    return matched;
}

function appendProjectEntryBlockFromSavedProject(projectName, options) {
    const opts = options || {};
    const container = document.getElementById("projectBlocksContainer");
    const name = String(projectName || "").trim();
    if (!container) return null;
    if (!name) {
        App.notify("请先选择或指定已有项目名称", "warning");
        return null;
    }
    const block = createProjectBlock();
    container.appendChild(block);
    const selectValue = _selectProjectOnEntryBlock(block, name);
    const sel = block.querySelector(".project-name");
    const opt = sel?.options?.[sel.selectedIndex];
    const pk = (opt?.dataset?.projectKey || opt?.dataset?.baseName || name).trim();
    _applyProjectMetaToBlock(block, _loadProjectMetaForEntry(selectValue || name, pk));
    _updateProjectBlockTaskRowCount(block);
    if (opts.scroll !== false) {
        block.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (opts.notify !== false) {
        App.notify(`已为项目「${name}」新建录入块，项目信息已带入`, "success");
    }
    return block;
}

function _bindProjectEntryBlock(block) {
    const tbody = block.querySelector(".project-task-tbody");
    const projectSelectEl = block.querySelector(".project-name");
    const countryInputEl = block.querySelector(".project-country");

    projectSelectEl?.addEventListener("change", () => {
        const opt = projectSelectEl.options[projectSelectEl.selectedIndex];
        const projectKey = (opt?.dataset?.projectKey || opt?.dataset?.baseName || "").trim();
        const pid = (projectSelectEl.value || "").trim();
        if (pid) {
            _applyProjectMetaToBlock(block, _loadProjectMetaForEntry(pid, projectKey));
        }
        const regCountry = opt?.dataset?.registeredCountry || "";
        if (countryInputEl && regCountry && !(countryInputEl.value || "").trim()) {
            countryInputEl.value = regCountry;
        }
        _updateProjectBlockTaskRowCount(block);
    });

    block.querySelectorAll(
        ".project-code, .project-notes, .project-business-side, .project-product, .project-country, .project-registered-product-name, .project-model, .project-registration-version"
    ).forEach((inp) => {
        inp.addEventListener("change", () => _persistProjectMetaFromBlock(block));
        inp.addEventListener("blur", () => _persistProjectMetaFromBlock(block));
    });

    block.querySelector(".add-task-row-btn")?.addEventListener("click", () => {
        const newRow = createTaskRowUnderProject(block);
        tbody.appendChild(newRow);
        const rows = tbody.querySelectorAll("tr");
        if (rows.length >= 2) {
            _copyPrevTaskRowFields(rows[rows.length - 2], rows[rows.length - 1], rows[rows.length - 1].querySelector(".task-type-cell .task-category"));
        }
        _updateProjectBlockTaskRowCount(block);
    });

    block.querySelector(".task-row-select-all")?.addEventListener("change", (e) => {
        const on = !!e.target.checked;
        tbody.querySelectorAll(".task-row-select").forEach((cb) => {
            cb.checked = on;
        });
    });

    block.querySelector(".btn-delete-selected-tasks")?.addEventListener("click", () => {
        const checked = tbody.querySelectorAll(".task-row-select:checked");
        if (!checked.length) {
            App.notify("请先勾选要删除的任务行", "warning");
            return;
        }
        if (!window.confirm(`确定删除所选 ${checked.length} 条任务行吗？`)) return;
        checked.forEach((cb) => cb.closest("tr")?.remove());
        if (!tbody.querySelectorAll("tr").length) {
            tbody.appendChild(createTaskRowUnderProject(block));
        }
        const allCb = block.querySelector(".task-row-select-all");
        if (allCb) allCb.checked = false;
        _updateProjectBlockTaskRowCount(block);
    });

    block.querySelector(".remove-project-btn")?.addEventListener("click", () => block.remove());
}

function createProjectBlock() {
    const block = document.createElement("div");
    block.className = "project-block card border mb-3";
    block.innerHTML = `
        <div class="card-body p-3">
            <div class="project-entry-meta-panel">
                <h6 class="card-subtitle text-muted mb-2">第一层 · 项目信息</h6>
                <div class="row g-2 mb-2">
                    <div class="col-md-3"><label class="form-label small">项目名称 *</label><select class="form-select form-select-sm project-name" required></select></div>
                    <div class="col-md-3"><label class="form-label small">影响业务方</label><input type="text" class="form-control form-control-sm project-business-side" placeholder="影响业务方"></div>
                    <div class="col-md-3"><label class="form-label small">影响产品</label><input type="text" class="form-control form-control-sm project-product" placeholder="影响产品"></div>
                    <div class="col-md-3"><label class="form-label small">国家</label><input type="text" class="form-control form-control-sm project-country" placeholder="国家"></div>
                </div>
                <p class="text-muted small fw-bold mb-2">以下为文档通用及签审批信息</p>
                <div class="row g-2 mb-2">
                    <div class="col-md-2"><label class="form-label small">项目编号</label><input type="text" class="form-control form-control-sm project-code" placeholder="项目编号"></div>
                    <div class="col-md-2"><label class="form-label small">项目备注</label><input type="text" class="form-control form-control-sm project-notes" placeholder="项目备注"></div>
                    <div class="col-md-2"><label class="form-label small">注册产品名称</label><input type="text" class="form-control form-control-sm project-registered-product-name" placeholder="注册产品名称"></div>
                    <div class="col-md-2"><label class="form-label small">型号</label><input type="text" class="form-control form-control-sm project-model" placeholder="型号"></div>
                    <div class="col-md-2"><label class="form-label small">注册版本号</label><input type="text" class="form-control form-control-sm project-registration-version" placeholder="注册版本号"></div>
                    <div class="col-md-2 d-flex align-items-end justify-content-end">
                        <button type="button" class="btn btn-outline-danger btn-sm remove-project-btn w-100">删除本项目块</button>
                    </div>
                </div>
            </div>
            <h6 class="card-subtitle text-muted mb-1">第二层 · 文件/事项任务</h6>
            <div class="project-entry-task-toolbar">
                <span class="project-entry-task-row-count">已添加 0 行</span>
                <button type="button" class="btn btn-outline-secondary btn-sm add-task-row-btn">+ 添加任务行</button>
                <label class="btn btn-outline-secondary btn-sm mb-0">
                    <input type="checkbox" class="form-check-input task-row-select-all me-1">全选
                </label>
                <button type="button" class="btn btn-outline-danger btn-sm btn-delete-selected-tasks">删除所选</button>
            </div>
            <div class="project-entry-table-viewport">
                <table class="table table-bordered table-sm align-middle project-entry-task-table mb-0">
                    <thead class="table-light">
                        <tr class="project-entry-head-row1">
                            <th class="task-row-select-col"></th>
                            <th>文件名称 *</th>
                            <th>任务类型</th>
                            <th>所属模块</th>
                            <th>文档链接/模板</th>
                            <th>编写人员 *</th>
                            <th>截止日期</th>
                            <th>下发任务备注</th>
                            <th colspan="5" class="text-center">以下为文档通用及签审批信息</th>
                            <th style="width:50px">操作</th>
                        </tr>
                        <tr class="project-entry-head-row2">
                            <th class="task-row-select-col"></th>
                            <th></th><th></th><th></th><th></th><th></th><th></th><th></th>
                            <th>文件版本号</th>
                            <th>文档体现日期</th>
                            <th>审核人员</th>
                            <th>批准人员</th>
                            <th>体现编写人员</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody class="project-task-tbody"></tbody>
                </table>
            </div>
        </div>
    `;
    const tbody = block.querySelector(".project-task-tbody");
    _populateProjectNameSelect(block.querySelector(".project-name"));
    _bindProjectEntryBlock(block);
    tbody.appendChild(createTaskRowUnderProject(block));
    _updateProjectBlockTaskRowCount(block);
    return block;
}

function _setSaveAllProgress(btn, hintEl, current, total, fileName, projectKey) {
    const idx = Math.max(0, Number(current) || 0);
    const tot = Math.max(0, Number(total) || 0);
    const file = String(fileName || "").trim();
    const proj = String(projectKey || "").trim();
    const shortBtn = tot > 0 ? `保存中 ${idx}/${tot}` : "保存中…";
    let detail = tot > 0 ? `正在保存第 ${idx}/${tot} 条` : "正在保存…";
    if (proj) detail += ` · 项目：${proj}`;
    if (file) detail += ` · 文件：${file}`;
    if (btn) btn.textContent = shortBtn;
    if (hintEl) {
        hintEl.textContent = detail;
        hintEl.classList.remove("d-none");
    }
}

function _hideSaveAllProgress(hintEl) {
    if (hintEl) {
        hintEl.textContent = "";
        hintEl.classList.add("d-none");
    }
}

function createTaskRowUnderProject(projectBlock) {
    rowCounter++;
    const tr = document.createElement("tr");
    tr.dataset.rowId = rowCounter;
    tr.innerHTML = `
        <td class="task-row-select-col"><input type="checkbox" class="form-check-input task-row-select" title="勾选后可批量删除"></td>
        <td><input type="text" class="form-control form-control-sm task-filename" placeholder="文件名称"></td>
        <td class="task-type-cell">
            <div class="d-flex flex-column gap-1 task-type-cell-inner"></div>
        </td>
        <td class="task-module-cell">
            <select class="form-select form-select-sm task-module">
                <option value="">—</option>
                <option value="产品">产品</option>
                <option value="开发">开发</option>
                <option value="测试">测试</option>
                <option value="全员">全员</option>
            </select>
        </td>
        <td>
            <div class="input-group input-group-sm">
                <input type="text" class="form-control task-link" placeholder="链接">
                <label class="btn btn-outline-secondary btn-sm mb-0">
                    <input type="file" class="d-none task-file" accept=".docx,.doc,.zip,.tar,.gz,.tgz,.rar">
                    文件
                </label>
            </div>
            <small class="task-file-name text-muted d-none"></small>
        </td>
        <td class="task-author-cell"><div class="task-author-picker-host"></div></td>
        <td><input type="date" class="form-control form-control-sm task-duedate"></td>
        <td>
            <div class="input-group input-group-sm">
                <input type="text" class="form-control task-notes" placeholder="下发任务备注">
                <button type="button" class="btn btn-outline-secondary btn-upload-note-pdf" title="上传PDF附件">📎</button>
                <input type="file" class="task-note-file d-none" accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg">
            </div>
            <div class="task-note-files-list small mt-1"></div>
        </td>
        <td><input type="text" class="form-control form-control-sm task-file-version" placeholder="版本号"></td>
        <td><input type="date" class="form-control form-control-sm task-doc-display-date" placeholder="文档体现日期"></td>
        <td><input type="text" class="form-control form-control-sm task-reviewer" placeholder="审核人员"></td>
        <td><input type="text" class="form-control form-control-sm task-approver" placeholder="批准人员"></td>
        <td><input type="text" class="form-control form-control-sm task-displayed-author" placeholder="体现编写人员"></td>
        <td><button type="button" class="btn btn-sm btn-outline-danger btn-remove-row">×</button></td>
    `;
    const _typeCellInner = tr.querySelector(".task-type-cell-inner");
    const _catSel = createTaskCategorySelect(TASK_TYPE_CATEGORY_FILE);
    const _typeSel = createTaskTypeSelect(TASK_TYPE_CATEGORY_FILE);
    _typeCellInner.appendChild(_catSel);
    _typeCellInner.appendChild(_typeSel);
    bindTaskCategoryAndTypeSelects(_catSel, _typeSel, "");
    const fileInput = tr.querySelector(".task-file");
    const fileNameDisplay = tr.querySelector(".task-file-name");
    const linkInput = tr.querySelector(".task-link");
    const filenameInput = tr.querySelector(".task-filename");
    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            fileNameDisplay.textContent = fileInput.files[0].name;
            fileNameDisplay.classList.remove("d-none");
            linkInput.value = "";
            linkInput.disabled = true;
            if (!filenameInput.value) filenameInput.value = fileInput.files[0].name;
        }
    });
    linkInput.addEventListener("input", () => {
        if (linkInput.value.trim()) { fileInput.value = ""; fileNameDisplay.classList.add("d-none"); }
    });
    const notePdfBtn = tr.querySelector(".btn-upload-note-pdf");
    const noteFileInput = tr.querySelector(".task-note-file");
    const noteFilesList = tr.querySelector(".task-note-files-list");
    const notesInput = tr.querySelector(".task-notes");
    notePdfBtn.addEventListener("click", () => noteFileInput.click());
    noteFileInput.addEventListener("change", async () => {
        const f = noteFileInput.files[0];
        noteFileInput.value = "";
        if (!f) return;
        const fd = new FormData();
        fd.append("file", f);
        try {
            const res = await App.request("/api/uploads/note-files", { method: "POST", body: fd });
            const cur = (notesInput.value || "").trim();
            const url = res.url;
            notesInput.value = cur ? cur + "\n" + url : url;
            const tag = document.createElement("span");
            tag.className = "badge bg-secondary me-1";
            tag.innerHTML = '<a href="' + url + '" target="_blank" class="text-white text-decoration-none">' + (res.fileName || f.name) + '</a>';
            noteFilesList.appendChild(tag);
        } catch (e) {
            App.notify(e.message || "上传失败", "danger");
        }
    });
    tr.querySelector(".btn-remove-row").addEventListener("click", () => {
        const pb = tr.closest(".project-block");
        tr.remove();
        if (pb) {
            const tb = pb.querySelector(".project-task-tbody");
            if (tb && !tb.querySelectorAll("tr").length) {
                tb.appendChild(createTaskRowUnderProject(pb));
            }
            _updateProjectBlockTaskRowCount(pb);
        }
    });
    tr.querySelector(".task-row-select")?.addEventListener("change", () => {
        const pb = tr.closest(".project-block");
        if (pb) _updateProjectBlockTaskRowCount(pb);
    });
    tr.querySelector(".task-filename")?.addEventListener("input", () => {
        const pb = tr.closest(".project-block");
        if (pb) _updateProjectBlockTaskRowCount(pb);
    });
    const authorHost = tr.querySelector(".task-author-picker-host");
    mountAuthorPicker(authorHost, {
        showQuickAdd: true,
        hooks: {
            onChange: () => {
                const pb = tr.closest(".project-block");
                if (pb) _updateProjectBlockTaskRowCount(pb);
            },
        },
    });
    return tr;
}

function createTaskRow() {
    return createTaskRowUnderProject(null);
}

function initDragSort(tbody, onReorder) {
    let draggedRow = null;

    tbody.addEventListener("dragstart", (e) => {
        if (!e.target.closest(".drag-handle")) return;
        const row = e.target.closest("tr");
        if (!row || row.classList.contains("group-header-row") || !row.dataset.id) return;
        draggedRow = row;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", "");
        try { e.dataTransfer.setDragImage(row, 0, 0); } catch (err) {}
        row.style.opacity = "0.4";
    });

    tbody.addEventListener("dragend", (e) => {
        const row = e.target.closest("tr");
        if (row) row.style.opacity = "1";
        draggedRow = null;
    });

    tbody.addEventListener("dragover", (e) => {
        e.preventDefault();
        const targetRow = e.target.closest("tr");
        if (targetRow && targetRow.classList.contains("group-header-row")) return;
        if (targetRow && draggedRow && targetRow !== draggedRow && targetRow.dataset.id) {
            const rect = targetRow.getBoundingClientRect();
            const midY = rect.top + rect.height / 2;
            if (e.clientY < midY) {
                targetRow.parentNode.insertBefore(draggedRow, targetRow);
            } else {
                targetRow.parentNode.insertBefore(draggedRow, targetRow.nextSibling);
            }
        }
    });

    tbody.addEventListener("drop", (e) => {
        e.preventDefault();
        if (onReorder && draggedRow) {
            const rows = Array.from(tbody.querySelectorAll("tr")).filter((tr) => tr.dataset.id);
            const orders = rows.map((row, idx) => ({
                id: row.dataset.id,
                sortOrder: idx,
            }));
            onReorder(orders);
        }
    });
}

async function initUploadPage() {
    const projectBlocksContainer = document.getElementById("projectBlocksContainer");
    const addProjectBtn = document.getElementById("addProjectBtn");
    const saveAllBtn = document.getElementById("saveAllBtn");
    const placeholderResult = document.getElementById("placeholderResult");
    const showHistoryEl = document.getElementById("showHistoryProjectsPage1");

    if (!projectBlocksContainer) return;

    // 尽早拉取列表，避免 await loadTaskTypes() 阻塞或失败时「已保存任务列表」一直空白
    loadRecordsList();

    // 进入页面时默认不显示历史项目；防止浏览器回退/表单恢复导致再次进入时仍保持勾选
    if (showHistoryEl) showHistoryEl.checked = false;

    showHistoryEl?.addEventListener("change", () => {
        loadRecordsList();
    });

    // bfcache / 浏览器返回：由 resetGoHandoffPage1Ui（pageshow 全局监听）关闭遮罩并刷新列表

    // 页面1：项目元数据管理（优先级/状态）
    const projectsManageBody = document.getElementById("projectsManageBody");
    const projectSelectAll = document.getElementById("projectSelectAll");
    const batchEditProjectsBtn = document.getElementById("batchEditProjectsBtn");
    const saveAllProjectsBtn = document.getElementById("saveAllProjectsBtn");
    const filterProjectName = document.getElementById("filterProjectName");
    const filterProjectStatus = document.getElementById("filterProjectStatus");
    const clearProjectFilterBtn = document.getElementById("clearProjectFilterBtn");
    const openNewProjectModalBtn = document.getElementById("openNewProjectModalBtn");
    const newProjectModalEl = document.getElementById("newProjectModal");
    const batchEditProjectsModalEl = document.getElementById("batchEditProjectsModal");

    const updateBatchProjectsBtnState = () => {
        if (!projectsManageBody || !batchEditProjectsBtn) return;
        const checked = projectsManageBody.querySelectorAll(".project-row-checkbox:checked").length;
        batchEditProjectsBtn.disabled = checked === 0;
    };

    const applyProjectsFilter = () => {
        if (!projectsManageBody) return;
        const nameKey = String(filterProjectName?.value || "").trim().toLowerCase();
        const st = String(filterProjectStatus?.value || "").trim().toLowerCase();
        projectsManageBody.querySelectorAll("tr[data-project-id]").forEach((tr) => {
            const name = String(tr.dataset.projectName || "").toLowerCase();
            const status = String(tr.dataset.projectStatus || "").toLowerCase();
            const okName = !nameKey || name.includes(nameKey);
            const okStatus = !st || status === st;
            tr.classList.toggle("d-none", !(okName && okStatus));
        });
    };

    const loadProjectsManage = async () => {
        if (!projectsManageBody) return;
        try {
            const rows = await App.request("/api/projects");
            projectsMetaCache = rows || [];
            projectsManageBody.innerHTML = "";
            (rows || []).forEach((p) => {
                const tr = document.createElement("tr");
                const esc = (s) =>
                    String(s == null ? "" : s)
                        .replace(/&/g, "&amp;")
                        .replace(/</g, "&lt;")
                        .replace(/>/g, "&gt;")
                        .replace(/"/g, "&quot;");
                const pr = Number.isFinite(Number(p.priority)) ? Number(p.priority) : 2;
                const st = (p.status || "active");
                tr.dataset.projectId = esc(p.id);
                tr.dataset.projectName = String(p.name || "");
                tr.dataset.projectStatus = String(p.status || "");
                tr.innerHTML = `
                    <td><input type="checkbox" class="form-check-input project-row-checkbox" data-id="${esc(p.id)}"></td>
                    <td title="${esc(p.name)}">${esc(p.name)}</td>
                    <td>
                        <input type="text" class="form-control form-control-sm project-registered-country-input" value="${esc(p.registeredCountry || "")}" placeholder="—">
                    </td>
                    <td>
                        <input type="text" class="form-control form-control-sm project-registered-category-input" value="${esc(p.registeredCategory || "")}" placeholder="—">
                    </td>
                    <td>
                        <select class="form-select form-select-sm project-priority-select" data-id="${esc(p.id)}">
                            <option value="3" ${pr === 3 ? "selected" : ""}>高</option>
                            <option value="2" ${pr === 2 ? "selected" : ""}>中</option>
                            <option value="1" ${pr === 1 ? "selected" : ""}>低</option>
                        </select>
                    </td>
                    <td>
                        <select class="form-select form-select-sm project-status-select" data-id="${esc(p.id)}">
                            <option value="active" ${st === "active" ? "selected" : ""}>进行中</option>
                            <option value="ended" ${st === "ended" ? "selected" : ""}>已结束</option>
                        </select>
                    </td>
                    <td class="small text-muted">${esc(p.updatedAt || "-")}</td>
                    <td class="text-nowrap">
                        <button type="button" class="btn btn-sm btn-outline-primary btn-save-project" data-id="${esc(p.id)}">保存</button>
                        <button type="button" class="btn btn-sm btn-outline-danger ms-1 btn-delete-project" data-id="${esc(p.id)}">删除</button>
                    </td>
                `;
                projectsManageBody.appendChild(tr);
            });
            projectSelectAll && (projectSelectAll.checked = false);
            projectsManageBody.querySelectorAll(".project-row-checkbox").forEach((cb) => {
                cb.addEventListener("change", () => {
                    updateBatchProjectsBtnState();
                });
            });
            projectsManageBody.querySelectorAll(".btn-save-project").forEach((btn) => {
                btn.addEventListener("click", async () => {
                    const id = btn.dataset.id;
                    const prEl = projectsManageBody.querySelector(`.project-priority-select[data-id="${id}"]`);
                    const stEl = projectsManageBody.querySelector(`.project-status-select[data-id="${id}"]`);
                    const tr = projectsManageBody.querySelector(`.btn-save-project[data-id="${id}"]`)?.closest("tr");
                    const rcInput = tr ? tr.querySelector(".project-registered-country-input") : null;
                    const catInput = tr ? tr.querySelector(".project-registered-category-input") : null;
                    try {
                        await App.request(`/api/projects/${id}`, {
                            method: "PATCH",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                priority: prEl ? Number(prEl.value) : 2,
                                status: stEl ? stEl.value : "active",
                                registeredCountry: rcInput ? (rcInput.value || "").trim() : null,
                                registeredCategory: catInput ? (catInput.value || "").trim() : null,
                            }),
                        });
                        App.notify("项目已更新", "success");
                        // 单个保存时不要刷新整张表/任务列表，避免把页面1录入块中已填内容冲掉。
                        // 仅刷新“任务录入”的项目下拉选项（会保持当前已选值）。
                        document.querySelectorAll(".project-block .project-name").forEach((sel) => _populateProjectNameSelect(sel));
                    } catch (e) {
                        App.notify(e.message || "保存失败", "danger");
                    }
                });
            });
            projectsManageBody.querySelectorAll(".btn-delete-project").forEach((btn) => {
                btn.addEventListener("click", async () => {
                    const id = btn.dataset.id;
                    if (!id) return;
                    try {
                        const resBind = await App.request(`/api/projects/${id}/bindings`, { method: "GET" });
                        const bound = resBind?.bound || {};
                        const total = Number(bound.totalCount || 0);
                        if (total > 0) {
                            window.alert(
                                `该项目已绑定记录共 ${total} 条（任务 ${bound.uploadCount || 0}、级联 ${bound.cascadeCount || 0}、生成 ${bound.generationCount || 0}），不允许删除。`
                            );
                            return;
                        }
                        const ok = window.confirm("确认删除该项目？");
                        if (!ok) return;

                        const res = await App.request(`/api/projects/${id}`, { method: "DELETE" });
                        App.notify(res.message || "删除成功", "success");
                        await loadProjectsManage();
                        document.querySelectorAll(".project-block .project-name").forEach((sel) => _populateProjectNameSelect(sel));
                    } catch (e) {
                        // 兜底：若后端未更新 bindings 接口（404），直接尝试 DELETE，让后端 409 返回绑定数量
                        if (e && e.message && String(e.message).includes("(404)")) {
                            try {
                                const ok = window.confirm("确认删除该项目？");
                                if (!ok) return;
                                const res = await App.request(`/api/projects/${id}`, { method: "DELETE" });
                                App.notify(res.message || "删除成功", "success");
                                await loadProjectsManage();
                                document.querySelectorAll(".project-block .project-name").forEach((sel) => _populateProjectNameSelect(sel));
                                return;
                            } catch (e2) {
                                const msg = (e2 && e2.message) ? String(e2.message) : "";
                                const bound = e2 && e2.data && e2.data.bound ? e2.data.bound : null;
                                if (String(msg).includes("(409)") && bound) {
                                    window.alert(
                                        `该项目已绑定记录共 ${bound.totalCount || 0} 条（任务 ${bound.uploadCount || 0}、级联 ${bound.cascadeCount || 0}、生成 ${bound.generationCount || 0}），不允许删除。`
                                    );
                                    return;
                                }
                                App.notify((e2 && e2.message) ? e2.message : "删除失败", "danger");
                                return;
                            }
                        }
                        App.notify(e && e.message ? e.message : "删除失败", "danger");
                    }
                });
            });
            // 同步刷新“任务录入”里的项目下拉（只展示进行中项目）
            document.querySelectorAll(".project-block .project-name").forEach((sel) => _populateProjectNameSelect(sel));
            refreshSavedProjectPickSelect();
            updateBatchProjectsBtnState();
            applyProjectsFilter();
        } catch (e) {
            projectsManageBody.innerHTML = '<tr><td colspan="6" class="text-danger small">加载失败</td></tr>';
        }
    };
    document.getElementById("refreshProjectsBtn")?.addEventListener("click", loadProjectsManage);
    openNewProjectModalBtn?.addEventListener("click", () => {
        if (!newProjectModalEl) return;
        new bootstrap.Modal(newProjectModalEl).show();
    });
    document.getElementById("createProjectBtn")?.addEventListener("click", async () => {
        const nameEl = document.getElementById("newProjectName");
        const prEl = document.getElementById("newProjectPriority");
        const stEl = document.getElementById("newProjectStatus");
        const rcEl = document.getElementById("newProjectRegisteredCountry");
        const catEl = document.getElementById("newProjectRegisteredCategory");
        const name = (nameEl?.value || "").trim();
        if (!name) { App.notify("请输入项目名称", "warning"); return; }
        try {
            await App.request("/api/projects", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name,
                    priority: prEl ? Number(prEl.value) : 2,
                    status: stEl ? stEl.value : "active",
                    registeredCountry: rcEl ? (rcEl.value || "").trim() : null,
                    registeredCategory: catEl ? (catEl.value || "").trim() : null,
                }),
            });
            if (nameEl) nameEl.value = "";
            bootstrap.Modal.getInstance(newProjectModalEl)?.hide();
            App.notify("项目已创建", "success");
            loadProjectsManage();
            loadRecordsList();
        } catch (e) {
            App.notify(e.message || "创建失败", "danger");
        }
    });

    projectSelectAll?.addEventListener("change", () => {
        const checked = !!projectSelectAll.checked;
        projectsManageBody?.querySelectorAll(".project-row-checkbox").forEach((cb) => { cb.checked = checked; });
        updateBatchProjectsBtnState();
    });

    batchEditProjectsBtn?.addEventListener("click", () => {
        if (!batchEditProjectsModalEl) return;
        new bootstrap.Modal(batchEditProjectsModalEl).show();
    });
    document.getElementById("applyBatchEditProjectsBtn")?.addEventListener("click", () => {
        if (!projectsManageBody) return;
        const pr = String(document.getElementById("batchProjectPriority")?.value || "");
        const st = String(document.getElementById("batchProjectStatus")?.value || "");
        if (!pr && !st) { App.notify("请选择要批量修改的字段", "warning"); return; }
        const ids = [];
        projectsManageBody.querySelectorAll(".project-row-checkbox:checked").forEach((cb) => {
            const id = cb.dataset.id;
            if (id) ids.push(id);
        });
        if (!ids.length) { App.notify("请先勾选项目", "warning"); return; }
        ids.forEach((id) => {
            if (pr) {
                const prEl = projectsManageBody.querySelector(`.project-priority-select[data-id="${id}"]`);
                if (prEl) prEl.value = pr;
            }
            if (st) {
                const stEl = projectsManageBody.querySelector(`.project-status-select[data-id="${id}"]`);
                if (stEl) stEl.value = st;
                const tr = projectsManageBody.querySelector(`tr[data-project-id="${id}"]`);
                if (tr) tr.dataset.projectStatus = st;
            }
        });
        applyProjectsFilter();
        bootstrap.Modal.getInstance(batchEditProjectsModalEl)?.hide();
        App.notify("已应用批量修改（未保存）", "info");
    });

    saveAllProjectsBtn?.addEventListener("click", async () => {
        if (!projectsManageBody) return;
        const payload = [];
        projectsManageBody.querySelectorAll("tr[data-project-id]").forEach((tr) => {
            const id = tr.dataset.projectId;
            const prEl = projectsManageBody.querySelector(`.project-priority-select[data-id="${id}"]`);
            const stEl = projectsManageBody.querySelector(`.project-status-select[data-id="${id}"]`);
            const rcInput = tr.querySelector(".project-registered-country-input");
            const catInput = tr.querySelector(".project-registered-category-input");
            if (!id || !prEl || !stEl) return;
            payload.push({
                id,
                priority: Number(prEl.value),
                status: stEl.value,
                registeredCountry: rcInput ? (rcInput.value || "").trim() : null,
                registeredCategory: catInput ? (catInput.value || "").trim() : null,
            });
        });
        if (!payload.length) { App.notify("没有可保存的项目", "warning"); return; }
        try {
            const res = await App.request("/api/projects/batch", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ projects: payload }),
            });
            App.notify(res.message || "已保存", "success");
            loadProjectsManage();
            loadRecordsList();
            if (window.loadMyTasks) window.loadMyTasks();
            if (window.loadSummary) window.loadSummary();
        } catch (e) {
            // 兜底：若后端未接受 PUT（老版本/反向代理限制），改用 POST 重试
            if (e && e.message && String(e.message).includes("(405)")) {
                try {
                    const res2 = await App.request("/api/projects/batch", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ projects: payload }),
                    });
                    App.notify(res2.message || "已保存", "success");
                    loadProjectsManage();
                    loadRecordsList();
                    if (window.loadMyTasks) window.loadMyTasks();
                    if (window.loadSummary) window.loadSummary();
                    return;
                } catch (e2) {
                    App.notify(e2.message || "保存失败", "danger");
                    return;
                }
            }
            App.notify(e && e.message ? e.message : "保存失败", "danger");
        }
    });

    [filterProjectName, filterProjectStatus].forEach((el) => {
        el?.addEventListener("input", applyProjectsFilter);
        el?.addEventListener("change", applyProjectsFilter);
    });
    clearProjectFilterBtn?.addEventListener("click", () => {
        if (filterProjectName) filterProjectName.value = "";
        if (filterProjectStatus) filterProjectStatus.value = "";
        applyProjectsFilter();
    });
    loadProjectsManage();

    try {
        await loadTaskTypes();
        projectBlocksContainer.appendChild(createProjectBlock());
        _populateProjectNameSelect(projectBlocksContainer.querySelector(".project-block .project-name"));
    } catch (e) {
        console.error("initUploadPage task types / project block:", e);
        App.notify(
            "任务类型或录入区初始化失败：" + (e && e.message ? e.message : String(e)) + "；任务列表仍会尝试加载。",
            "warning"
        );
    }

    addProjectBtn?.addEventListener("click", () => {
        projectBlocksContainer.appendChild(createProjectBlock());
        const blocks = projectBlocksContainer.querySelectorAll(".project-block");
        if (blocks.length >= 2) {
            const prev = blocks[blocks.length - 2];
            const curr = blocks[blocks.length - 1];
            const prevSel = prev.querySelector(".project-name");
            const prevVal = (prevSel?.value || "").trim();
            _populateProjectNameSelect(curr.querySelector(".project-name"), prevVal);
            if (prevVal) {
                const opt = prevSel?.options?.[prevSel.selectedIndex];
                const pk = (opt?.dataset?.projectKey || opt?.dataset?.baseName || "").trim();
                _applyProjectMetaToBlock(curr, _loadProjectMetaForEntry(prevVal, pk));
            }
            _updateProjectBlockTaskRowCount(curr);
        }
    });

    document.getElementById("createEntryBlockFromSavedProjectBtn")?.addEventListener("click", () => {
        const pick = (document.getElementById("pickSavedProjectForEntry")?.value || "").trim();
        appendProjectEntryBlockFromSavedProject(pick);
    });

    const recordsTableBody = document.getElementById("recordsTableBody");
    if (recordsTableBody && !recordsTableBody.dataset.entryDblBound) {
        recordsTableBody.dataset.entryDblBound = "1";
        recordsTableBody.addEventListener("dblclick", (e) => {
            const td = e.target.closest("td.project-name-pick-entry, td[data-col='projectName']");
            if (!td || td.closest(".group-header-row")) return;
            const tr = td.closest("tr[data-id]");
            if (!tr || !tr.dataset.id) return;
            const rec = (allRecordsCache || []).find((x) => String(x.id) === String(tr.dataset.id));
            if (!rec || !(rec.projectName || "").trim()) return;
            const canon = _canonicalProjectKeyForPick(rec.projectName, rec.projectId);
            appendProjectEntryBlockFromSavedProject(canon || String(rec.projectName).trim());
            const pickSel = document.getElementById("pickSavedProjectForEntry");
            if (pickSel && canon) pickSel.value = canon;
        });
    }

    const _CSV_HEADERS = [
        "项目名称","项目编号","影响业务方","影响产品","国家","项目备注","注册产品名称","型号","注册版本号",
        "文件名称","任务类型","文档链接","文件版本号","编写人员","负责人",
        "截止日期","下发任务备注","文档体现日期","审核人员","批准人员","所属模块","体现编写人员",
    ];
    function _csvEscape(v) {
        var s = (v == null ? "" : String(v));
        if (s.indexOf(",") !== -1 || s.indexOf('"') !== -1 || s.indexOf("\n") !== -1) {
            return '"' + s.replace(/"/g, '""') + '"';
        }
        return s;
    }
    function _recordToCsvRow(r) {
        return [
            r.projectName, r.projectCode, r.businessSide, r.product, r.country, r.projectNotes,
            r.registeredProductName, r.model, r.registrationVersion,
            r.fileName, r.taskType, r.templateLinks, r.fileVersion, r.author, r.assigneeName || r.author,
            r.dueDate, r.notes, r.documentDisplayDate, r.reviewer, r.approver, r.belongingModule, r.displayedAuthor,
        ].map(_csvEscape).join(",");
    }
    function _downloadCsvString(csvContent, filename) {
        var BOM = "\uFEFF";
        var blob = new Blob([BOM + csvContent], { type: "text/csv;charset=utf-8;" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.style.display = "none";
        document.body.appendChild(a);
        a.click();
        setTimeout(function () {
            if (a.parentNode) document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }, 300);
    }

    document.getElementById("downloadTemplateEmptyBtn")?.addEventListener("click", function () {
        var csv = _CSV_HEADERS.map(_csvEscape).join(",") + "\n";
        _downloadCsvString(csv, "待办导入模板_空.csv");
        App.notify("已下载空模板", "success");
    });

    const sampleModal = document.getElementById("importTemplateSampleModal");
    const sampleSelect = document.getElementById("importTemplateProjectSelect");
    const sampleConfirmBtn = document.getElementById("importTemplateSampleConfirmBtn");
    document.getElementById("downloadTemplateSampleBtn")?.addEventListener("click", function () {
        var names = [];
        var seen = {};
        (allRecordsCache || []).forEach(function (r) {
            var n = (r.projectName || "").trim();
            if (n && !seen[n]) { seen[n] = true; names.push(n); }
        });
        names.sort(function (a, b) { return String(a || "").localeCompare(String(b || ""), "zh"); });
        if (sampleSelect) {
            sampleSelect.innerHTML = '<option value="">（使用系统示例）</option>';
            names.forEach(function (n) {
                var opt = document.createElement("option");
                opt.value = n;
                opt.textContent = n;
                sampleSelect.appendChild(opt);
            });
        }
        var modal = sampleModal ? new bootstrap.Modal(sampleModal) : null;
        modal?.show();
    });
    sampleConfirmBtn?.addEventListener("click", function () {
        var projectName = (sampleSelect?.value || "").trim();
        var rows = [_CSV_HEADERS.map(_csvEscape).join(",")];
        var records = allRecordsCache || [];
        if (projectName) {
            records = records.filter(function (r) { return (r.projectName || "").trim() === projectName; });
        }
        if (records.length > 0) {
            records.forEach(function (r) { rows.push(_recordToCsvRow(r)); });
        }
        rows.push("");
        var filename = projectName ? ("待办导入模板_" + projectName.substring(0, 20) + ".csv") : "待办导入模板_含示例.csv";
        _downloadCsvString(rows.join("\n"), filename);
        var modal = sampleModal ? bootstrap.Modal.getInstance(sampleModal) : null;
        modal?.hide();
        App.notify("已下载示例模板", "success");
    });

    const importTasksBtn = document.getElementById("importTasksBtn");
    const importTasksFile = document.getElementById("importTasksFile");
    importTasksBtn?.addEventListener("click", () => importTasksFile?.click());
    importTasksFile?.addEventListener("change", async (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        const fd = new FormData();
        fd.append("file", file);
        try {
            const result = await App.request("/api/uploads/import", { method: "POST", body: fd });
            let msg = result?.message || (result?.success ? "导入完成" : "导入失败");
            const errs = result?.errors;
            if (Array.isArray(errs) && errs.length > 0) {
                const preview = errs
                    .slice(0, 3)
                    .map((e) => `第${e.row}行：${e.message || ""}`)
                    .join("；");
                msg += ` 详情：${preview}${errs.length > 3 ? "…" : ""}`;
            }
            App.notify(msg, result?.success ? "success" : "danger");
            if (result?.success && typeof loadRecordsList === "function") loadRecordsList();
        } catch (err) {
            const data = err.data || {};
            App.notify(data.message || err.message || "导入失败", "danger");
        }
    });

    const saveAllProgressHint = document.getElementById("saveAllProgressHint");

    saveAllBtn?.addEventListener("click", async () => {
        const blocks = projectBlocksContainer.querySelectorAll(".project-block");
        let successCount = 0;
        let skippedIncomplete = 0;
        let plannedSaveCount = 0;
        let saveProgressIndex = 0;
        let lastPlaceholders = [];
        const btn = saveAllBtn;
        try {
            for (const block of blocks) {
                const projectSelect = block.querySelector(".project-name");
                const projectId = (projectSelect?.value || "").trim();
                const projectKey = (projectSelect?.options?.[projectSelect.selectedIndex]?.dataset?.projectKey || "").trim();
                if (!projectId || !projectKey) continue;
                const rows = block.querySelectorAll(".project-task-tbody tr");
                const dupSeen = new Set();
                rows.forEach((row) => {
                    const fileName = (row.querySelector(".task-filename")?.value || "").trim();
                    const author = (row.querySelector(".task-author")?.value || "").trim();
                    if (!fileName || !author) return;
                    const taskType = (row.querySelector(".task-type-cell .task-type")?.value || "").trim();
                    const dupKey = `${fileName}\t${taskType || ""}\t${author}`;
                    if (dupSeen.has(dupKey)) return;
                    dupSeen.add(dupKey);
                    plannedSaveCount++;
                });
            }
            if (btn) {
                if (btn.dataset.origBtnText == null) btn.dataset.origBtnText = btn.textContent || "";
                btn.disabled = true;
            }
            _setSaveAllProgress(btn, saveAllProgressHint, 0, plannedSaveCount, "", "");
            if (plannedSaveCount > 0) {
                App.notify(`开始保存，共 ${plannedSaveCount} 条`, "info");
            }

            for (const block of blocks) {
                const projectSelect = block.querySelector(".project-name");
                const projectId = (projectSelect?.value || "").trim();
                const projectKey = (projectSelect?.options?.[projectSelect.selectedIndex]?.dataset?.projectKey || "").trim();
                const projectCode = (block.querySelector(".project-code")?.value || "").trim() || "";
                const businessSide = (block.querySelector(".project-business-side")?.value || "").trim() || "";
                const product = (block.querySelector(".project-product")?.value || "").trim() || "";
                const country = (block.querySelector(".project-country")?.value || "").trim() || "";
                const registeredProductName = (block.querySelector(".project-registered-product-name")?.value || "").trim() || "";
                const model = (block.querySelector(".project-model")?.value || "").trim() || "";
                const registrationVersion = (block.querySelector(".project-registration-version")?.value || "").trim() || "";
                const rows = block.querySelectorAll(".project-task-tbody tr");
                const dupSeen = new Set();
                for (const row of rows) {
                    const fileName = (row.querySelector(".task-filename")?.value || "").trim();
                    const taskTypeSelect = row.querySelector(".task-type-cell .task-type");
                    const taskType = taskTypeSelect ? (taskTypeSelect.value || "").trim() : "";
                    const link = (row.querySelector(".task-link")?.value || "").trim();
                    const fileInput = row.querySelector(".task-file");
                    const author = (row.querySelector(".task-author")?.value || "").trim();
                    const dueDate = (row.querySelector(".task-duedate")?.value || "").trim();
                    const notes = (row.querySelector(".task-notes")?.value || "").trim() || "";
                    const fileVersion = (row.querySelector(".task-file-version")?.value || "").trim() || "";
                    const docDisplayDate = (row.querySelector(".task-doc-display-date")?.value || "").trim() || "";
                    const reviewer = (row.querySelector(".task-reviewer")?.value || "").trim() || "";
                    const approver = (row.querySelector(".task-approver")?.value || "").trim() || "";
                    const displayedAuthor = (row.querySelector(".task-displayed-author")?.value || "").trim() || "";
                    const moduleSelect = row.querySelector(".task-module-cell select");
                    const belongingModule = moduleSelect ? (moduleSelect.value || "").trim() : "";

                    if (!projectId || !projectKey || !fileName || !author) {
                        skippedIncomplete++;
                        continue;
                    }

                    const dupKey = `${fileName}\t${taskType || ""}\t${author}`;
                    if (dupSeen.has(dupKey)) {
                        App.notify(
                            `本项目中存在多行「文件名称 + 任务类型 + 编写人员」完全相同（${fileName}）。数据库只允许保留一条，请修改后再保存；若多行共用同一模板文件，请为每行填写不同的文件名称。`,
                            "warning"
                        );
                        _setButtonBusy(btn, false);
                        return;
                    }
                    dupSeen.add(dupKey);
                    saveProgressIndex++;
                    _setSaveAllProgress(btn, saveAllProgressHint, saveProgressIndex, plannedSaveCount, fileName, projectKey);
                    _persistProjectMetaFromBlock(block);

                    const formData = new FormData();
                    formData.append("projectId", projectId);
                    formData.append("projectName", projectKey);
                    formData.append("fileName", fileName);
                    formData.append("projectCode", (block.querySelector(".project-code")?.value || "").trim());
                    formData.append("projectNotes", (block.querySelector(".project-notes")?.value || "").trim());
                    if (taskType) formData.append("taskType", taskType);
                    formData.append("author", author);
                    formData.append("assigneeName", author);
                    if (notes) formData.append("notes", notes);
                    if (dueDate) formData.append("dueDate", dueDate);
                    if (businessSide) formData.append("businessSide", businessSide);
                    if (product) formData.append("product", product);
                    if (country) formData.append("country", country);
                    if (registeredProductName) formData.append("registeredProductName", registeredProductName);
                    if (model) formData.append("model", model);
                    if (registrationVersion) formData.append("registrationVersion", registrationVersion);
                    if (fileVersion) formData.append("fileVersion", fileVersion);
                    if (docDisplayDate) formData.append("documentDisplayDate", docDisplayDate);
                    if (reviewer) formData.append("reviewer", reviewer);
                    if (approver) formData.append("approver", approver);
                    if (displayedAuthor) formData.append("displayedAuthor", displayedAuthor);
                    if (belongingModule) formData.append("belongingModule", belongingModule);
                    if (link) {
                        formData.append("templateLinks", normalizeDocLink(link));
                    } else if (fileInput && fileInput.files.length > 0) {
                        formData.append("file", fileInput.files[0]);
                    }

                    try {
                        const result = await App.request("/api/upload", {
                            method: "POST",
                            body: formData,
                            timeoutMs: 120000,
                        });
                        successCount++;
                        if (result.record && result.record.placeholders) {
                            lastPlaceholders = result.record.placeholders;
                        }
                    } catch (error) {
                        const msg = error && error.message ? error.message : "";
                        const is409Replace = error && error.is409Replace === true;
                        if (is409Replace) {
                            const uploadingFile = fileInput && fileInput.files.length > 0;
                            let replaceMsg =
                                (msg || "存在重复记录，是否替换？") +
                                "\n\n提示：选「确定」将用本行内容覆盖库里已有同一条（同项目+文件名称+任务类型+编写人员）；选「取消」则跳过本行，可继续保存其余行。";
                            if (uploadingFile) {
                                replaceMsg +=
                                    "\n\n若上传了模板文件，将覆盖已有文件或链接，且来源将改为「文件」。";
                            }
                            _setButtonBusy(btn, false);
                            const replaceOk = window.confirm(replaceMsg);
                            if (!replaceOk) {
                                App.notify(`已跳过：${fileName}（与已有记录重复，您选择了不替换）`, "info");
                                continue;
                            }
                            if (btn) {
                                if (btn.dataset.origBtnText == null) btn.dataset.origBtnText = btn.textContent || "";
                                btn.disabled = true;
                            }
                            _setSaveAllProgress(btn, saveAllProgressHint, saveProgressIndex, plannedSaveCount, fileName, projectKey);
                            const formDataReplace = new FormData();
                            formDataReplace.append("projectId", projectId);
                            formDataReplace.append("projectName", projectKey);
                            formDataReplace.append("fileName", fileName);
                            formDataReplace.append("projectCode", (block.querySelector(".project-code")?.value || "").trim());
                            formDataReplace.append("projectNotes", (block.querySelector(".project-notes")?.value || "").trim());
                            if (taskType) formDataReplace.append("taskType", taskType);
                            formDataReplace.append("author", author);
                            formDataReplace.append("assigneeName", author);
                            if (notes) formDataReplace.append("notes", notes);
                            if (dueDate) formDataReplace.append("dueDate", dueDate);
                            if (businessSide) formDataReplace.append("businessSide", businessSide);
                            if (product) formDataReplace.append("product", product);
                            if (country) formDataReplace.append("country", country);
                            if (registeredProductName) formDataReplace.append("registeredProductName", registeredProductName);
                            if (model) formDataReplace.append("model", model);
                            if (registrationVersion) formDataReplace.append("registrationVersion", registrationVersion);
                            if (fileVersion) formDataReplace.append("fileVersion", fileVersion);
                            if (docDisplayDate) formDataReplace.append("documentDisplayDate", docDisplayDate);
                            if (reviewer) formDataReplace.append("reviewer", reviewer);
                            if (approver) formDataReplace.append("approver", approver);
                            if (displayedAuthor) formDataReplace.append("displayedAuthor", displayedAuthor);
                            if (belongingModule) formDataReplace.append("belongingModule", belongingModule);
                            formDataReplace.set("replace", "true");
                            if (fileInput && fileInput.files.length > 0) {
                                formDataReplace.append("file", fileInput.files[0]);
                            } else if (link) {
                                formDataReplace.append("templateLinks", normalizeDocLink(link));
                            }
                            try {
                                const resultReplace = await App.request("/api/upload", {
                                    method: "POST",
                                    body: formDataReplace,
                                    timeoutMs: 120000,
                                });
                                successCount++;
                                if (resultReplace.record && resultReplace.record.placeholders) {
                                    lastPlaceholders = resultReplace.record.placeholders;
                                }
                            } catch (e2) {
                                App.notify(`保存失败 (${projectKey}-${fileName}): ${e2 && e2.message ? e2.message : "请重试"}`, "danger");
                            }
                        } else {
                        App.notify(`保存失败 (${projectKey}-${fileName}): ${msg}`, "danger");
                        }
                    }
                }
            }

            if (successCount > 0) {
                let msg = `成功保存 ${successCount} 条记录`;
                if (skippedIncomplete > 0) {
                    msg += `；另有 ${skippedIncomplete} 行因未选项目或缺少文件名称/编写人员已跳过（未写入数据库）`;
                }
                const allDone = plannedSaveCount > 0 && successCount >= plannedSaveCount;
                if (!allDone && plannedSaveCount > successCount) {
                    msg += `；另有 ${plannedSaveCount - successCount} 条未写入（例如重复记录点了「取消」）。录入表已保留，请改后再次点「保存全部」。`;
                }
                App.notify(msg, allDone ? "success" : "warning");
                loadRecordsList();
                if (allDone) {
                    projectBlocksContainer.innerHTML = "";
                    projectBlocksContainer.appendChild(createProjectBlock());
                }
                if (lastPlaceholders.length > 0 && placeholderResult) {
                    renderPlaceholderChips(placeholderResult, lastPlaceholders);
                }
            } else {
                let hadAnyFilled = false;
                let totalRows = 0;
                blocks.forEach((b) => {
                    const pn = (b.querySelector(".project-name")?.value || "").trim();
                    const tbody = b.querySelector(".project-task-tbody");
                    if (tbody) {
                        tbody.querySelectorAll("tr").forEach((r) => {
                            totalRows++;
                            const fn = (r.querySelector(".task-filename")?.value || "").trim();
                            const au = (r.querySelector(".task-author")?.value || "").trim();
                            if (pn || fn || au) hadAnyFilled = true;
                        });
                    }
                });
                if (totalRows === 0) {
                    App.notify("没有可保存的任务行，请先添加项目并填写任务。", "warning");
                } else if (hadAnyFilled) {
                    let w =
                        "未保存任何记录。请检查每条任务是否已填写：项目名称、文件名称、编写人员（均为必填）。若曾提示重复，请选“确定”以替换。";
                    if (skippedIncomplete > 0) {
                        w += ` 另有 ${skippedIncomplete} 行因未选项目或缺少文件名称/编写人员已跳过（未写入数据库）。`;
                    }
                    App.notify(w, "warning");
                } else {
                    App.notify("请至少填写一条任务：项目名称、文件名称、编写人员为必填项。", "info");
                }
            }
        } catch (err) {
            App.notify("保存过程出错: " + (err && err.message ? err.message : String(err)), "danger");
        } finally {
            _setButtonBusy(btn, false);
            _hideSaveAllProgress(saveAllProgressHint);
        }
    });

    initCreateUserModal();
    initUsersListFilter();
    initQuickUserForm();
    initConfigManagement();
    loadRecordsList();
    refreshSavedProjectPickSelect();
    loadUsersList();
    initRecordsFilter();
    initRecordsTableSort();
    initEditUserMobile();
    initEditRecordModal();
    initBatchEditRecords();
    document.querySelectorAll('input[name="recordsGroupBy"]').forEach((radio) => {
        radio.addEventListener("change", () => {
            renderRecordsTable(lastRenderedRecords);
        });
    });
}

function initEditUserMobile() {
    const saveBtn = document.getElementById("saveUserMobileBtn");
    const modalEl = document.getElementById("editUserMobileModal");
    if (!saveBtn || !modalEl) return;
    saveBtn.addEventListener("click", async () => {
        const id = document.getElementById("editUserMobileId").value;
        const mobile = document.getElementById("editUserMobileValue").value.trim();
        const displayName = (document.getElementById("editUserDisplayName")?.value || "").trim();
        try {
            await App.request(`/api/users/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    mobile: mobile || null,
                    displayName: displayName || null,
                }),
            });
            App.notify("手机号已更新");
            bootstrap.Modal.getInstance(modalEl)?.hide();
            loadUsersList();
        } catch (e) {
            App.notify(e.message || "更新失败", "danger");
        }
    });
}

function initRecordsTableSort() {
    const table = document.getElementById("recordsTable");
    if (!table) return;
    table.querySelectorAll("thead .th-sortable").forEach((th) => {
        th.addEventListener("click", () => {
            const key = th.dataset.sortKey;
            if (!key) return;
            if (recordsSortKey === key) recordsSortDir = recordsSortDir === "asc" ? "desc" : "asc";
            else { recordsSortKey = key; recordsSortDir = "asc"; }
            table.querySelectorAll("thead .sort-indicator").forEach((s) => { s.textContent = ""; });
            const ind = th.querySelector(".sort-indicator");
            if (ind) ind.textContent = recordsSortDir === "asc" ? "↑" : "↓";
            const sorted = sortRows(lastRenderedRecords, recordsSortKey, recordsSortDir);
            renderRecordsTable(sorted);
        });
    });
}

async function openEditRecordModal(r) {
    if (!usersListCache.length) await loadUsersList();
    ensureEditRecordAuthorPicker();
    document.getElementById("editRecordId").value = r.id;
    const prjIdEl = document.getElementById("editRecordProjectId");
    if (prjIdEl) prjIdEl.value = (r.projectId != null && r.projectId !== "") ? String(r.projectId) : "";
    const tplFileEl = document.getElementById("editRecordTemplateFile");
    if (tplFileEl) tplFileEl.value = "";
    document.getElementById("editRecordProject").value = r.projectName || "";
    const projectCodeEl = document.getElementById("editRecordProjectCode");
    if (projectCodeEl) projectCodeEl.value = r.projectCode || "";
    document.getElementById("editRecordFile").value = r.fileName || "";
    const taskTypeEl = document.getElementById("editRecordTaskType");
    const taskCategoryEl = document.getElementById("editRecordTaskCategory");
    if (taskTypeEl) {
        await loadTaskTypes();
        const initType = (r.taskType || "").trim();
        const initCat = initType ? taskTypeCategoryOf(initType) : TASK_TYPE_CATEGORY_FILE;
        if (taskCategoryEl) taskCategoryEl.value = initCat;
        refillTaskTypeOptions(taskTypeEl, initCat, initType);
        ensureSelectHasOption(
            taskTypeEl,
            initType,
            "（当前记录中的类型；若已不在「任务类型」配置中，请补回配置以免保存丢失）"
        );
        if (initType) taskTypeEl.value = initType;
        if (taskCategoryEl && !taskCategoryEl.dataset.bound) {
            taskCategoryEl.addEventListener("change", () => {
                const cat = _normalizeTaskTypeCategory(taskCategoryEl.value);
                refillTaskTypeOptions(taskTypeEl, cat, "");
            });
            taskTypeEl.addEventListener("change", () => {
                const v = (taskTypeEl.value || "").trim();
                if (!v) return;
                const realCat = taskTypeCategoryOf(v);
                if (taskCategoryEl.value !== realCat) taskCategoryEl.value = realCat;
            });
            taskCategoryEl.dataset.bound = "1";
        }
    }
    const editRecordBelongingModuleEl = document.getElementById("editRecordBelongingModule");
    if (editRecordBelongingModuleEl) editRecordBelongingModuleEl.value = r.belongingModule || "";
    setAuthorPickerValue("editRecordAuthorPicker", r.author || "");
    document.getElementById("editRecordDueDate").value = r.dueDate || "";
    document.getElementById("editRecordAssignee").value = r.assigneeName || r.author || "";
    document.getElementById("editRecordBusinessSide").value = r.businessSide || "";
    document.getElementById("editRecordProduct").value = r.product || "";
    document.getElementById("editRecordCountry").value = r.country || "";
    const regProdEl = document.getElementById("editRecordRegisteredProductName");
    if (regProdEl) regProdEl.value = r.registeredProductName || "";
    const modelEl = document.getElementById("editRecordModel");
    if (modelEl) modelEl.value = r.model || "";
    const regVerEl = document.getElementById("editRecordRegistrationVersion");
    if (regVerEl) regVerEl.value = r.registrationVersion || "";
    document.getElementById("editRecordTemplateLinks").value = r.templateLinks || "";
    window.__editRecordTemplateState = {
        hasFile: !!r.hasFile,
        hasLinks: !!r.hasLinks,
    };
    const editTplFile = document.getElementById("editRecordTemplateFile");
    if (editTplFile) editTplFile.value = "";
    document.getElementById("editRecordNotes").value = r.notes || "";
    const editNoteFilesList = document.getElementById("editNoteFilesList");
    if (editNoteFilesList) {
        editNoteFilesList.innerHTML = "";
        var noteLines = (r.notes || "").split("\n").filter(function (l) { return l.trim(); });
        noteLines.forEach(function (ln) {
            if (/^https?:\/\//i.test(ln.trim()) || /^\/api\/uploads\/note-files\//i.test(ln.trim())) {
                var tag = document.createElement("span");
                tag.className = "badge bg-secondary me-1 mb-1";
                var name = ln.trim().match(/([^/\\?#]+)$/);
                tag.innerHTML = '<a href="' + ln.trim() + '" target="_blank" class="text-white text-decoration-none">' + (name ? name[1] : "附件") + '</a>';
                editNoteFilesList.appendChild(tag);
            }
        });
    }
    const projectNotesEl = document.getElementById("editRecordProjectNotes");
    if (projectNotesEl) projectNotesEl.value = r.projectNotes || "";
    const fileVersionEl = document.getElementById("editRecordFileVersion");
    if (fileVersionEl) fileVersionEl.value = r.fileVersion || "";
    const docDisplayDateEl = document.getElementById("editRecordDocDisplayDate");
    if (docDisplayDateEl) docDisplayDateEl.value = r.documentDisplayDate || "";
    const reviewerEl = document.getElementById("editRecordReviewer");
    if (reviewerEl) reviewerEl.value = r.reviewer || "";
    const approverEl = document.getElementById("editRecordApprover");
    if (approverEl) approverEl.value = r.approver || "";
    const displayedAuthorEl = document.getElementById("editRecordDisplayedAuthor");
    if (displayedAuthorEl) displayedAuthorEl.value = r.displayedAuthor || "";
    const statusEl = document.getElementById("editRecordAuditStatus");
    if (statusEl) {
        await loadAuditStatuses();
        statusEl.innerHTML = '<option value="">—</option>';
        (auditStatusesCache || []).forEach(s => {
            const opt = document.createElement("option");
            opt.value = s.name;
            opt.textContent = s.name;
            statusEl.appendChild(opt);
        });
        statusEl.value = r.auditStatus || "";
    }
    document.getElementById("editRecordAssigneeMobileHint").textContent = "";
    const modal = new bootstrap.Modal(document.getElementById("editRecordModal"));
    modal.show();
    updateEditRecordAssigneeMobileHint(r.assigneeName || r.author || "");
}

function findUserForAuthorLabel(users, label) {
    const name = (label || "").trim();
    if (!name) return null;
    return (users || []).find((u) => {
        const dn = (u.displayName || "").trim();
        const un = (u.username || "").trim();
        const pick = dn || un;
        return name === dn || name === un || name === pick;
    }) || null;
}

function updateEditRecordAssigneeMobileHint(assigneeName) {
    const hintEl = document.getElementById("editRecordAssigneeMobileHint");
    if (!hintEl) return;
    if (!assigneeName || !assigneeName.trim()) {
        hintEl.textContent = "填写负责人姓名且需在账号管理中配置手机号，催办时才能@成功";
        hintEl.className = "form-text small text-muted";
        return;
    }
    App.request("/api/users")
        .then((res) => {
            const users = res.users || [];
            const name = assigneeName.trim();
            const user = findUserForAuthorLabel(users, name);
            if (user && user.mobile && String(user.mobile).trim()) {
                const mobile = String(user.mobile).trim();
                const masked = mobile.length > 4 ? mobile.slice(0, 3) + "****" + mobile.slice(-4) : mobile;
                hintEl.textContent = "已配置手机号：" + masked + "，催办时可@";
                hintEl.className = "form-text small text-success";
            } else {
                hintEl.textContent = "该负责人未在账号管理中填写手机号，催办无法@成功。请先在账号管理中添加并填写手机号。";
                hintEl.className = "form-text small text-warning";
            }
        })
        .catch(() => {
            hintEl.textContent = "无法加载账号信息";
            hintEl.className = "form-text small text-muted";
        });
}

function initEditRecordModal() {
    const saveBtn = document.getElementById("saveEditRecordBtn");
    const modalEl = document.getElementById("editRecordModal");
    if (!saveBtn || !modalEl) return;
    const assigneeInput = document.getElementById("editRecordAssignee");
    if (assigneeInput) {
        assigneeInput.addEventListener("blur", () => {
            if (modalEl.classList.contains("show")) updateEditRecordAssigneeMobileHint(assigneeInput.value || "");
        });
    }
    ensureEditRecordAuthorPicker();
    const quickUserBtn = document.getElementById("editRecordQuickUserBtn");
    if (quickUserBtn) {
        quickUserBtn.addEventListener("click", () => {
            const qm = document.getElementById("quickUserModal");
            const un = document.getElementById("quickUsername");
            if (qm && un) {
                un.value = (assigneeInput?.value || "").trim();
                const modal = new bootstrap.Modal(qm);
                modal.show();
            }
        });
    }
    const editNotePdfBtn = document.getElementById("editNoteUploadPdfBtn");
    const editNoteFileInput = document.getElementById("editNoteFileInput");
    if (editNotePdfBtn && editNoteFileInput) {
        editNotePdfBtn.addEventListener("click", () => editNoteFileInput.click());
        editNoteFileInput.addEventListener("change", async () => {
            const f = editNoteFileInput.files[0];
            editNoteFileInput.value = "";
            if (!f) return;
            const fd = new FormData();
            fd.append("file", f);
            try {
                const res = await App.request("/api/uploads/note-files", { method: "POST", body: fd });
                const notesEl = document.getElementById("editRecordNotes");
                const cur = (notesEl.value || "").trim();
                const url = res.url;
                notesEl.value = cur ? cur + "\n" + url : url;
                const listEl = document.getElementById("editNoteFilesList");
                if (listEl) {
                    const tag = document.createElement("span");
                    tag.className = "badge bg-secondary me-1 mb-1";
                    tag.innerHTML = '<a href="' + url + '" target="_blank" class="text-white text-decoration-none">' + (res.fileName || f.name) + '</a>';
                    listEl.appendChild(tag);
                }
                App.notify("附件已上传", "success");
            } catch (e) {
                App.notify(e.message || "上传失败", "danger");
            }
        });
    }
    saveBtn.addEventListener("click", async () => {
        const id = document.getElementById("editRecordId").value;
        const payload = {
            projectName: document.getElementById("editRecordProject").value.trim(),
            fileName: document.getElementById("editRecordFile").value.trim(),
            taskType: document.getElementById("editRecordTaskType").value.trim() || null,
            author: (document.querySelector("#editRecordAuthorPicker .task-author")?.value || "").trim(),
            dueDate: document.getElementById("editRecordDueDate").value || null,
            assigneeName: document.getElementById("editRecordAssignee").value.trim() || null,
            businessSide: document.getElementById("editRecordBusinessSide").value.trim() || null,
            product: document.getElementById("editRecordProduct").value.trim() || null,
            country: document.getElementById("editRecordCountry").value.trim() || null,
            registeredProductName: document.getElementById("editRecordRegisteredProductName")?.value?.trim() || null,
            model: document.getElementById("editRecordModel")?.value?.trim() || null,
            registrationVersion: document.getElementById("editRecordRegistrationVersion")?.value?.trim() || null,
            templateLinks: document.getElementById("editRecordTemplateLinks").value.trim() || null,
            notes: document.getElementById("editRecordNotes").value.trim() || null,
            belongingModule: document.getElementById("editRecordBelongingModule")?.value?.trim() || null,
            projectNotes: document.getElementById("editRecordProjectNotes")?.value?.trim() || null,
        };
        const projectCodeEl = document.getElementById("editRecordProjectCode");
        if (projectCodeEl) payload.projectCode = projectCodeEl.value.trim() || null;
        const fileVersionEl = document.getElementById("editRecordFileVersion");
        if (fileVersionEl) payload.fileVersion = fileVersionEl.value.trim() || null;
        const docDisplayDateEl = document.getElementById("editRecordDocDisplayDate");
        if (docDisplayDateEl) payload.documentDisplayDate = docDisplayDateEl.value || null;
        const reviewerEl = document.getElementById("editRecordReviewer");
        if (reviewerEl) payload.reviewer = reviewerEl.value.trim() || null;
        const approverEl = document.getElementById("editRecordApprover");
        if (approverEl) payload.approver = approverEl.value.trim() || null;
        const displayedAuthorSaveEl = document.getElementById("editRecordDisplayedAuthor");
        if (displayedAuthorSaveEl) payload.displayedAuthor = displayedAuthorSaveEl.value.trim() || null;
        const auditStatusEl = document.getElementById("editRecordAuditStatus");
        if (auditStatusEl) {
            const v = auditStatusEl.value.trim();
            payload.auditStatus = v || null;
        }
        if (!payload.projectName || !payload.fileName || !payload.author) {
            App.notify("项目名称、文件名称、编写人员不能为空", "danger");
            return;
        }
        const tplIn = document.getElementById("editRecordTemplateFile");
        const tplFile = tplIn && tplIn.files && tplIn.files[0];
        try {
            if (tplFile) {
                const prevTpl = window.__editRecordTemplateState || {};
                if (!confirmTemplateFileOverwrite(prevTpl)) return;
                const fd = new FormData();
                fd.append("replace", "true");
                fd.append("uploadRecordId", id);
                const pid = (document.getElementById("editRecordProjectId")?.value || "").trim();
                if (pid) fd.append("projectId", pid);
                fd.append("projectName", payload.projectName);
                fd.append("fileName", payload.fileName);
                fd.append("author", payload.author);
                fd.append("taskType", payload.taskType || "");
                fd.append("notes", (document.getElementById("editRecordNotes").value || "").trim());
                fd.append("projectNotes", payload.projectNotes || "");
                fd.append("assigneeName", payload.assigneeName || "");
                fd.append("dueDate", payload.dueDate || "");
                fd.append("businessSide", payload.businessSide || "");
                fd.append("product", payload.product || "");
                fd.append("country", payload.country || "");
                fd.append("registeredProductName", payload.registeredProductName || "");
                fd.append("model", payload.model || "");
                fd.append("registrationVersion", payload.registrationVersion || "");
                if (projectCodeEl) fd.append("projectCode", projectCodeEl.value.trim());
                if (fileVersionEl) fd.append("fileVersion", fileVersionEl.value.trim());
                if (docDisplayDateEl) fd.append("documentDisplayDate", docDisplayDateEl.value || "");
                if (reviewerEl) fd.append("reviewer", reviewerEl.value.trim());
                if (approverEl) fd.append("approver", approverEl.value.trim());
                if (displayedAuthorSaveEl) fd.append("displayedAuthor", displayedAuthorSaveEl.value.trim());
                if (auditStatusEl) fd.append("auditStatus", auditStatusEl.value.trim());
                fd.append("belongingModule", (document.getElementById("editRecordBelongingModule")?.value || "").trim());
                fd.append("file", tplFile);
                const res = await App.request("/api/upload", { method: "POST", body: fd });
                document.getElementById("editRecordTemplateLinks").value = "";
                window.__editRecordTemplateState = { hasFile: true, hasLinks: false };
                App.notify(res.message || "任务模板已更新并已尝试同步 FTP");
            } else {
                await App.request(`/api/uploads/${id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                App.notify("任务已更新");
            }
            bootstrap.Modal.getInstance(modalEl)?.hide();
            loadRecordsList();
            if (window.loadMyTasks) window.loadMyTasks();
            if (window.loadSummary) window.loadSummary();
        } catch (e) {
            App.notify(e.message || "更新失败", "danger");
        }
    });
}

function initBatchEditRecords() {
    const table = document.getElementById("recordsTable");
    const selectAll = document.getElementById("recordSelectAll");
    const batchEditBtn = document.getElementById("batchEditRecordsBtn");
    const batchGoSignBtn = document.getElementById("batchGoSignBtn");
    const batchGoPrintBtn = document.getElementById("batchGoPrintBtn");
    const batchEditModal = document.getElementById("batchEditRecordModal");
    const batchEditSaveBtn = document.getElementById("batchEditSaveBtn");
    if (!table || !batchEditBtn) return;

    const batchNotePdfBtn = document.getElementById("batchEditNoteUploadPdfBtn");
    const batchNoteFileInput = document.getElementById("batchEditNoteFileInput");
    if (batchNotePdfBtn && batchNoteFileInput) {
        batchNotePdfBtn.addEventListener("click", () => batchNoteFileInput.click());
        batchNoteFileInput.addEventListener("change", async () => {
            const f = batchNoteFileInput.files[0];
            batchNoteFileInput.value = "";
            if (!f) return;
            const fd = new FormData();
            fd.append("file", f);
            try {
                const res = await App.request("/api/uploads/note-files", { method: "POST", body: fd });
                const notesEl = document.getElementById("batchEditNotes");
                const cur = (notesEl.value || "").trim();
                const url = res.url;
                notesEl.value = cur ? cur + "\n" + url : url;
                const listEl = document.getElementById("batchEditNoteFilesList");
                if (listEl) {
                    const tag = document.createElement("span");
                    tag.className = "badge bg-secondary me-1 mb-1";
                    tag.innerHTML = '<a href="' + url + '" target="_blank" class="text-white text-decoration-none">' + (res.fileName || f.name) + '</a>';
                    listEl.appendChild(tag);
                }
                App.notify("附件已上传", "success");
            } catch (e) {
                App.notify(e.message || "上传失败", "danger");
            }
        });
    }

    selectAll?.addEventListener("change", () => {
        const tbody = document.getElementById("recordsTableBody");
        if (!tbody) return;
        const checkboxes = tbody.querySelectorAll(".record-checkbox");
        const checked = !!selectAll?.checked;
        checkboxes.forEach((cb) => { cb.checked = checked; });
        updateBatchEditButtonState();
    });

    table.addEventListener("change", (e) => {
        if (e.target.classList.contains("record-checkbox")) updateBatchEditButtonState();
    });

    const selectByProjectBtn = document.getElementById("selectByProjectBtn");
    const selectByProjectMenu = document.getElementById("selectByProjectMenu");
    if (selectByProjectBtn && selectByProjectMenu) {
        selectByProjectBtn.addEventListener("show.bs.dropdown", () => {
            const projects = [...new Set((lastRenderedRecords || []).map((r) => (r.projectName != null && r.projectName !== "") ? String(r.projectName).trim() : ""))];
            projects.sort((a, b) => (a || "").localeCompare(b || ""));
            selectByProjectMenu.innerHTML = "";
            if (projects.length === 0) {
                const li = document.createElement("li");
                li.innerHTML = '<span class="dropdown-item text-muted">暂无数据</span>';
                selectByProjectMenu.appendChild(li);
            } else {
                projects.forEach((p) => {
                    const li = document.createElement("li");
                    const a = document.createElement("a");
                    a.href = "#";
                    a.className = "dropdown-item";
                    a.textContent = p || "（空）";
                    a.dataset.project = p ?? "";
                    a.addEventListener("click", (e) => {
                        e.preventDefault();
                        const tbody = document.getElementById("recordsTableBody");
                        if (!tbody) return;
                        const val = a.dataset.project;
                        tbody.querySelectorAll("tr[data-id]").forEach((tr) => {
                            if ((tr.dataset.projectName || "") === (val || "")) {
                                const cb = tr.querySelector(".record-checkbox");
                                if (cb) cb.checked = true;
                            }
                        });
                        updateBatchEditButtonState();
                        bootstrap.Dropdown.getInstance(selectByProjectBtn)?.hide();
                    });
                    li.appendChild(a);
                    selectByProjectMenu.appendChild(li);
                });
            }
        });
    }

    batchEditBtn.addEventListener("click", async () => {
        const tbody = document.getElementById("recordsTableBody");
        if (!tbody) return;
        const ids = [];
        tbody.querySelectorAll(".record-checkbox:checked").forEach((cb) => {
            const id = cb.dataset.id;
            if (id) ids.push(id);
        });
        if (ids.length === 0) {
            App.notify("请先勾选要编辑的任务", "warning");
            return;
        }
        const projects = new Set();
        ids.forEach((id) => {
            const r = allRecordsCache.find((x) => String(x.id) === String(id));
            if (r && r.projectName != null) projects.add(String(r.projectName).trim());
            else if (r) projects.add("");
        });
        if (projects.size > 1) {
            App.notify("请只勾选同一项目的任务进行批量编辑", "warning");
            return;
        }
        const records = ids
            .map((id) => allRecordsCache.find((x) => String(x.id) === String(id)))
            .filter(Boolean);
        const first = records[0];
        const projectCodeVal = first ? (first.projectCode || "").trim() : "";
        const sameProjectCode = projectCodeVal !== "" && records.every((r) => ((r.projectCode || "").trim()) === projectCodeVal);
        const taskTypeVal = first ? (first.taskType || "").trim() : "";
        const authorVal = first ? (first.author || "").trim() : "";
        const assigneeVal = first ? (first.assigneeName || first.author || "").trim() : "";
        const dueDateVal = first ? (first.dueDate || "").trim() : "";
        const businessSideVal = first ? (first.businessSide || "").trim() : "";
        const productVal = first ? (first.product || "").trim() : "";
        const countryVal = first ? (first.country || "").trim() : "";
        const projectNotesVal = first ? (first.projectNotes || "").trim() : "";
        const fileVersionVal = first ? (first.fileVersion || "").trim() : "";
        const documentDisplayDateVal = first ? (first.documentDisplayDate || "").trim() : "";
        const reviewerVal = first ? (first.reviewer || "").trim() : "";
        const approverVal = first ? (first.approver || "").trim() : "";
        const belongingModuleVal = first ? (first.belongingModule || "").trim() : "";
        const auditVal = first ? (first.auditStatus || "").trim() : "";
        const sameTaskType = taskTypeVal !== "" && records.every((r) => ((r.taskType || "").trim()) === taskTypeVal);
        const sameAuthor = authorVal !== "" && records.every((r) => ((r.author || "").trim()) === authorVal);
        const sameAssignee = assigneeVal !== "" && records.every((r) => ((r.assigneeName || r.author || "").trim()) === assigneeVal);
        const sameDueDate = dueDateVal !== "" && records.every((r) => ((r.dueDate || "").trim()) === dueDateVal);
        const sameBusinessSide = businessSideVal !== "" && records.every((r) => ((r.businessSide || "").trim()) === businessSideVal);
        const sameProduct = productVal !== "" && records.every((r) => ((r.product || "").trim()) === productVal);
        const sameCountry = countryVal !== "" && records.every((r) => ((r.country || "").trim()) === countryVal);
        const sameProjectNotes = projectNotesVal !== "" && records.every((r) => ((r.projectNotes || "").trim()) === projectNotesVal);
        const sameFileVersion = fileVersionVal !== "" && records.every((r) => ((r.fileVersion || "").trim()) === fileVersionVal);
        const sameBelongingModule = belongingModuleVal !== "" && records.every((r) => ((r.belongingModule || "").trim()) === belongingModuleVal);
        const sameDocumentDisplayDate = documentDisplayDateVal !== "" && records.every((r) => ((r.documentDisplayDate || "").trim()) === documentDisplayDateVal);
        const sameReviewer = reviewerVal !== "" && records.every((r) => ((r.reviewer || "").trim()) === reviewerVal);
        const sameApprover = approverVal !== "" && records.every((r) => ((r.approver || "").trim()) === approverVal);
        const sameAudit = records.every((r) => ((r.auditStatus || "").trim()) === auditVal);
        const sel = document.getElementById("batchEditAuditStatus");
        if (sel) {
            await loadAuditStatuses();
            sel.innerHTML = '<option value="">— 不修改 —</option>';
            (auditStatusesCache || []).forEach((s) => {
                const opt = document.createElement("option");
                opt.value = s.name;
                opt.textContent = s.name;
                sel.appendChild(opt);
            });
            sel.value = sameAudit ? auditVal : "";
        }
        const batchTaskCategorySel = document.getElementById("batchEditTaskCategory");
        const batchTaskTypeSel = document.getElementById("batchEditTaskType");
        if (batchTaskTypeSel) {
            await loadTaskTypes();
            const initType = sameTaskType ? taskTypeVal : "";
            const initCat = initType ? taskTypeCategoryOf(initType) : "";
            if (batchTaskCategorySel) batchTaskCategorySel.value = initCat;
            const fillTypeOptions = (cat) => {
                batchTaskTypeSel.innerHTML = '<option value="">— 不修改 —</option>';
                (taskTypesCache || []).forEach((t) => {
                    if (cat && _normalizeTaskTypeCategory(t.category) !== cat) return;
                    const opt = document.createElement("option");
                    opt.value = t.name;
                    opt.textContent = t.name;
                    batchTaskTypeSel.appendChild(opt);
                });
            };
            fillTypeOptions(initCat);
            if (initType) {
                ensureSelectHasOption(batchTaskTypeSel, initType, "");
                batchTaskTypeSel.value = initType;
            }
            if (batchTaskCategorySel && !batchTaskCategorySel.dataset.bound) {
                batchTaskCategorySel.addEventListener("change", () => {
                    const cat = String(batchTaskCategorySel.value || "");
                    fillTypeOptions(cat ? _normalizeTaskTypeCategory(cat) : "");
                });
                batchTaskTypeSel.addEventListener("change", () => {
                    const v = (batchTaskTypeSel.value || "").trim();
                    if (!v) return;
                    const realCat = taskTypeCategoryOf(v);
                    if (batchTaskCategorySel.value !== realCat) batchTaskCategorySel.value = realCat;
                });
                batchTaskCategorySel.dataset.bound = "1";
            }
        }
        const batchEditProjectCodeEl = document.getElementById("batchEditProjectCode");
        if (batchEditProjectCodeEl) batchEditProjectCodeEl.value = sameProjectCode ? projectCodeVal : "";
        if (!usersListCache.length) await loadUsersList();
        ensureBatchEditAuthorPicker();
        setAuthorPickerValue("batchEditAuthorPicker", sameAuthor ? authorVal : "");
        document.getElementById("batchEditAssignee").value = sameAssignee ? assigneeVal : "";
        document.getElementById("batchEditDueDate").value = sameDueDate ? dueDateVal : "";
        document.getElementById("batchEditBusinessSide").value = sameBusinessSide ? businessSideVal : "";
        document.getElementById("batchEditProduct").value = sameProduct ? productVal : "";
        document.getElementById("batchEditCountry").value = sameCountry ? countryVal : "";
        const registeredProductNameVal = first ? (first.registeredProductName || "").trim() : "";
        const sameRegProd = registeredProductNameVal !== "" && records.every((r) => ((r.registeredProductName || "").trim()) === registeredProductNameVal);
        const batchEditRegProdEl = document.getElementById("batchEditRegisteredProductName");
        if (batchEditRegProdEl) batchEditRegProdEl.value = sameRegProd ? registeredProductNameVal : "";
        const modelVal = first ? (first.model || "").trim() : "";
        const sameModel = modelVal !== "" && records.every((r) => ((r.model || "").trim()) === modelVal);
        const batchEditModelEl = document.getElementById("batchEditModel");
        if (batchEditModelEl) batchEditModelEl.value = sameModel ? modelVal : "";
        const registrationVersionVal = first ? (first.registrationVersion || "").trim() : "";
        const sameRegVer = registrationVersionVal !== "" && records.every((r) => ((r.registrationVersion || "").trim()) === registrationVersionVal);
        const batchEditRegVerEl = document.getElementById("batchEditRegistrationVersion");
        if (batchEditRegVerEl) batchEditRegVerEl.value = sameRegVer ? registrationVersionVal : "";
        const batchEditProjectNotesEl = document.getElementById("batchEditProjectNotes");
        if (batchEditProjectNotesEl) batchEditProjectNotesEl.value = sameProjectNotes ? projectNotesVal : "";
        const batchEditFileVersionEl = document.getElementById("batchEditFileVersion");
        if (batchEditFileVersionEl) batchEditFileVersionEl.value = sameFileVersion ? fileVersionVal : "";
        const batchEditBelongingModuleEl = document.getElementById("batchEditBelongingModule");
        if (batchEditBelongingModuleEl) batchEditBelongingModuleEl.value = sameBelongingModule ? belongingModuleVal : "";
        const batchEditDocumentDisplayDateEl = document.getElementById("batchEditDocumentDisplayDate");
        if (batchEditDocumentDisplayDateEl) batchEditDocumentDisplayDateEl.value = sameDocumentDisplayDate ? documentDisplayDateVal : "";
        const batchEditReviewerEl = document.getElementById("batchEditReviewer");
        if (batchEditReviewerEl) batchEditReviewerEl.value = sameReviewer ? reviewerVal : "";
        const batchEditApproverEl = document.getElementById("batchEditApprover");
        if (batchEditApproverEl) batchEditApproverEl.value = sameApprover ? approverVal : "";
        const notesVal = first ? (first.notes || "").trim() : "";
        const sameNotes = notesVal !== "" && records.every((r) => ((r.notes || "").trim()) === notesVal);
        const batchEditNotesEl = document.getElementById("batchEditNotes");
        if (batchEditNotesEl) batchEditNotesEl.value = sameNotes ? notesVal : "";
        const batchEditNoteFilesListEl = document.getElementById("batchEditNoteFilesList");
        if (batchEditNoteFilesListEl) batchEditNoteFilesListEl.innerHTML = "";
        const displayedAuthorVal = first ? (first.displayedAuthor || "").trim() : "";
        const sameDisplayedAuthor = displayedAuthorVal !== "" && records.every((r) => ((r.displayedAuthor || "").trim()) === displayedAuthorVal);
        const batchEditDisplayedAuthorEl = document.getElementById("batchEditDisplayedAuthor");
        if (batchEditDisplayedAuthorEl) batchEditDisplayedAuthorEl.value = sameDisplayedAuthor ? displayedAuthorVal : "";
        if (batchEditSaveBtn) batchEditSaveBtn.textContent = `应用到所选 (${ids.length}条)`;
        if (batchEditModal) {
            batchEditModal.dataset.batchEditIds = ids.join(",");
            const modal = new bootstrap.Modal(batchEditModal);
            modal.show();
        }
    });

    async function runBatchAiprintword(mode) {
        const tbody = document.getElementById("recordsTableBody");
        if (!tbody) return;
        const ids = [];
        tbody.querySelectorAll(".record-checkbox:checked").forEach((cb) => {
            const id = cb.dataset.id;
            if (id) ids.push(id);
        });
        if (ids.length < 2) {
            App.notify("请至少勾选 2 条任务", "warning");
            return;
        }
        const records = ids
            .map((id) => allRecordsCache.find((x) => String(x.id) === String(id)))
            .filter(Boolean);
        const projects = new Set(records.map((r) => String((r && r.projectName) || "").trim()));
        if (projects.size > 1) {
            App.notify("请只勾选同一项目的任务", "warning");
            return;
        }
        const canHandoff = records.every((r) => !!(r.hasGenerated || r.hasFile || r.hasLinks));
        if (!canHandoff) {
            App.notify("勾选项中存在不可交接任务（需先有模板/链接/已生成文档）", "warning");
            return;
        }
        const btn = mode === "sign" ? batchGoSignBtn : batchGoPrintBtn;
        const original = btn ? btn.innerHTML : "";
        try {
            if (btn) {
                btn.dataset.originalHtml = original;
                btn.disabled = true;
                btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>跳转中`;
            }
            showGoSignLoading(mode === "sign" ? "正在批量打开签字页面并载入任务文件…" : "正在批量打开打印页面并载入任务文件…");
            const url = mode === "sign" ? "/api/go/batch-sign" : "/api/go/batch-print";
            const res = await App.request(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ upload_ids: ids }),
            });
            if (!res || !res.ok || !res.redirect_url) {
                throw new Error((res && res.error) || "批量跳转失败");
            }
            window.location.href = res.redirect_url;
        } catch (e) {
            App.notify(e.message || "批量跳转失败", "danger");
            hideGoSignLoading();
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = original || (mode === "sign" ? "批量去签字" : "批量去打印");
            }
        }
    }

    if (batchGoSignBtn) {
        batchGoSignBtn.addEventListener("click", () => runBatchAiprintword("sign"));
    }
    if (batchGoPrintBtn) {
        batchGoPrintBtn.addEventListener("click", () => runBatchAiprintword("print"));
    }

    ensureBatchEditAuthorPicker();

    batchEditSaveBtn?.addEventListener("click", async () => {
        const idsStr = batchEditModal?.dataset.batchEditIds;
        if (!idsStr) return;
        const ids = idsStr.split(",").filter(Boolean);
        const projectCode = (document.getElementById("batchEditProjectCode")?.value || "").trim();
        const taskType = (document.getElementById("batchEditTaskType")?.value || "").trim();
        const author = (document.querySelector("#batchEditAuthorPicker .task-author")?.value || "").trim();
        const assignee = (document.getElementById("batchEditAssignee")?.value || "").trim();
        const dueDate = (document.getElementById("batchEditDueDate")?.value || "").trim();
        const businessSide = (document.getElementById("batchEditBusinessSide")?.value || "").trim();
        const product = (document.getElementById("batchEditProduct")?.value || "").trim();
        const country = (document.getElementById("batchEditCountry")?.value || "").trim();
        const registeredProductName = (document.getElementById("batchEditRegisteredProductName")?.value || "").trim();
        const model = (document.getElementById("batchEditModel")?.value || "").trim();
        const registrationVersion = (document.getElementById("batchEditRegistrationVersion")?.value || "").trim();
        const projectNotes = (document.getElementById("batchEditProjectNotes")?.value || "").trim();
        const fileVersion = (document.getElementById("batchEditFileVersion")?.value || "").trim();
        const belongingModule = (document.getElementById("batchEditBelongingModule")?.value || "").trim();
        const documentDisplayDate = (document.getElementById("batchEditDocumentDisplayDate")?.value || "").trim();
        const reviewer = (document.getElementById("batchEditReviewer")?.value || "").trim();
        const approver = (document.getElementById("batchEditApprover")?.value || "").trim();
        const auditEl = document.getElementById("batchEditAuditStatus");
        const auditStatus = auditEl?.value?.trim() ?? "";
        const notes = (document.getElementById("batchEditNotes")?.value || "").trim();
        const displayedAuthor = (document.getElementById("batchEditDisplayedAuthor")?.value || "").trim();
        const payload = {};
        if (projectCode !== "") payload.projectCode = projectCode;
        if (taskType !== "") payload.taskType = taskType;
        if (belongingModule !== "") payload.belongingModule = belongingModule;
        if (author !== "") payload.author = author;
        if (assignee !== "") payload.assigneeName = assignee;
        if (dueDate !== "") payload.dueDate = dueDate;
        if (businessSide !== "") payload.businessSide = businessSide;
        if (product !== "") payload.product = product;
        if (country !== "") payload.country = country;
        if (registeredProductName !== "") payload.registeredProductName = registeredProductName;
        if (model !== "") payload.model = model;
        if (registrationVersion !== "") payload.registrationVersion = registrationVersion;
        if (projectNotes !== "") payload.projectNotes = projectNotes;
        if (fileVersion !== "") payload.fileVersion = fileVersion;
        if (documentDisplayDate !== "") payload.documentDisplayDate = documentDisplayDate;
        if (reviewer !== "") payload.reviewer = reviewer;
        if (approver !== "") payload.approver = approver;
        if (auditStatus !== "") payload.auditStatus = auditStatus;
        if (notes !== "") payload.notes = notes;
        if (displayedAuthor !== "") payload.displayedAuthor = displayedAuthor;
        if (Object.keys(payload).length === 0) {
            App.notify("请至少填写一项要修改的内容", "warning");
            return;
        }
        let success = 0;
        try {
            for (const id of ids) {
                await App.request(`/api/uploads/${id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                success++;
            }
            bootstrap.Modal.getInstance(batchEditModal)?.hide();
            loadRecordsList();
            if (window.loadMyTasks) window.loadMyTasks();
            if (window.loadSummary) window.loadSummary();
            App.notify(`已更新 ${success} 条任务`);
        } catch (e) {
            App.notify(e.message || "批量更新失败", "danger");
        }
    });
}

function sortRows(rows, key, dir) {
    if (!key || !rows.length) return [...rows];
    const asc = dir !== "desc";
    return [...rows].sort((a, b) => {
        let va = a[key];
        let vb = b[key];
        if (key === "projectPriority") {
            va = Number.isFinite(Number(va)) ? Number(va) : 0;
            vb = Number.isFinite(Number(vb)) ? Number(vb) : 0;
            return asc ? (va - vb) : (vb - va);
        }
        if (key === "dueDate" || key === "createdAt") {
            va = va || "";
            vb = vb || "";
            return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
        }
        va = (va != null && va !== "") ? String(va) : "";
        vb = (vb != null && vb !== "") ? String(vb) : "";
        const cmp = va.localeCompare(vb, "zh");
        return asc ? cmp : -cmp;
    });
}

function initRecordsFilter() {
    const filterProject = document.getElementById("filterRecordProject");
    const filterFile = document.getElementById("filterRecordFile");
    const filterAuthor = document.getElementById("filterRecordAuthor");
    const filterStatus = document.getElementById("filterRecordStatus");
    
    if (!filterProject) return;
    
    const applyFilter = () => {
        const projectVal = filterProject.value.toLowerCase();
        const fileVal = filterFile.value.toLowerCase();
        const authorVal = filterAuthor.value.toLowerCase();
        const statusVal = filterStatus.value;
        
        const tbody = document.getElementById("recordsTableBody");
        if (!tbody) return;
        
        const filtered = allRecordsCache.filter(r => {
            if (projectVal && !(String(r.projectName || "").toLowerCase().includes(projectVal))) return false;
            if (fileVal && !(String(r.fileName || "").toLowerCase().includes(fileVal))) return false;
            if (authorVal && !(String(r.author || "").toLowerCase().includes(authorVal))) return false;
            if (statusVal === "pending" && (r.completionStatus || r.taskStatus === "completed")) return false;
            if (statusVal === "completed" && !r.completionStatus && r.taskStatus !== "completed") return false;
            return true;
        });
        const sorted = sortRows(filtered, recordsSortKey, recordsSortDir);
        renderRecordsTable(sorted);
    };
    
    [filterProject, filterFile, filterAuthor, filterStatus].forEach(el => {
        el?.addEventListener("input", applyFilter);
        el?.addEventListener("change", applyFilter);
    });
}

function updateBatchEditButtonState() {
    const tbody = document.getElementById("recordsTableBody");
    const btn = document.getElementById("batchEditRecordsBtn");
    const btnGoSign = document.getElementById("batchGoSignBtn");
    const btnGoPrint = document.getElementById("batchGoPrintBtn");
    if (!tbody || !btn) return;
    const checked = tbody.querySelectorAll(".record-checkbox:checked").length;
    btn.disabled = checked === 0;
    if (btnGoSign) btnGoSign.disabled = checked < 2;
    if (btnGoPrint) btnGoPrint.disabled = checked < 2;
    const btnBatchAudit = document.getElementById("batchAuditBtn");
    if (btnBatchAudit) btnBatchAudit.disabled = checked === 0;
}

function _collectSelectedRecordIdsForAudit() {
    const tbody = document.getElementById("recordsTableBody");
    if (!tbody) return [];
    const out = [];
    tbody.querySelectorAll(".record-checkbox:checked").forEach((cb) => {
        const id = (cb.dataset && cb.dataset.id) || cb.value || "";
        if (id) out.push(String(id));
    });
    return out;
}

function _findUploadRecordById(id) {
    const rid = String(id || "").trim();
    if (!rid) return null;
    const pools = [].concat(allRecordsCache || [], lastRenderedMyTasks || []);
    for (let i = 0; i < pools.length; i++) {
        if (String(pools[i].id) === rid) return pools[i];
    }
    return null;
}

/** 页面1/2 任务行 → 审核/翻译/审核后修改 URL（与初稿页 query 一致，供默认选中项目与维度）。 */
function buildIntegrationUrlFromRecord(r, basePath, extraParams) {
    const root = (window.__SCRIPT_ROOT__ || "").replace(/\/$/, "");
    const u = new URLSearchParams();
    u.set("from", "page2");
    if (r && r.id) u.set("upload_id", r.id);
    if (r && r.projectName) u.set("project_name", r.projectName);
    if (r && r.fileName) u.set("file_name", r.fileName);
    const prod = (r && r.product) || (r && r.registeredProductName) || "";
    if (prod) u.set("product", String(prod).trim());
    if (r && r.country) u.set("country", r.country);
    const pid = r && r.projectId != null ? String(r.projectId).trim() : "";
    if (pid && /^\d+$/.test(pid)) u.set("aicheckword_project_id", pid);
    if (extraParams && typeof extraParams === "object") {
        Object.keys(extraParams).forEach((k) => {
            const v = extraParams[k];
            if (v != null && String(v).trim() !== "") u.set(k, String(v));
        });
    }
    return root + basePath + "?" + u.toString();
}

function gotoAuditPage(mode) {
    const ids = _collectSelectedRecordIdsForAudit();
    if (!ids.length) {
        alert("请先勾选至少 1 条任务再发起审核");
        return;
    }
    const m = (mode || "single").toString().toLowerCase();
    if ((m === "multi" || m === "traceability") && ids.length < 2) {
        alert(m + " 模式至少需要 2 条任务，当前选中 " + ids.length + " 条。");
        return;
    }
    if (m === "single" && ids.length > 50) {
        alert("single 模式单次最多 50 条任务，当前选中 " + ids.length + " 条，请分批。");
        return;
    }
    const firstRec = _findUploadRecordById(ids[0]);
    const url = buildIntegrationUrlFromRecord(firstRec, "/audit/", {
        upload_ids: ids.join(","),
        mode: m,
    });
    window.open(url, "_blank", "noopener");
}

(function _wireBatchAuditMenuOnce() {
    if (window._batchAuditMenuBound) return;
    window._batchAuditMenuBound = true;
    document.addEventListener("DOMContentLoaded", () => {
        const mainBtn = document.getElementById("batchAuditBtn");
        if (mainBtn) {
            mainBtn.addEventListener("click", (e) => {
                e.preventDefault();
                gotoAuditPage("single");
            });
        }
        document.querySelectorAll("[data-audit-mode]").forEach((a) => {
            a.addEventListener("click", (e) => {
                e.preventDefault();
                gotoAuditPage(a.getAttribute("data-audit-mode") || "single");
            });
        });
    });
})();

function hideGoSignLoading() {
    const mask = document.getElementById("goSignLoadingMask");
    if (mask) mask.style.display = "none";
}

/** 从签字/打印页返回（含 bfcache）时恢复页面 1 可操作状态 */
function resetGoHandoffPage1Ui() {
    hideGoSignLoading();
    const showHistoryEl = document.getElementById("showHistoryProjectsPage1");
    if (showHistoryEl) showHistoryEl.checked = false;
    const batchGoSignBtn = document.getElementById("batchGoSignBtn");
    const batchGoPrintBtn = document.getElementById("batchGoPrintBtn");
    if (batchGoSignBtn) {
        batchGoSignBtn.disabled = false;
        if (batchGoSignBtn.dataset.originalHtml) {
            batchGoSignBtn.innerHTML = batchGoSignBtn.dataset.originalHtml;
        }
    }
    if (batchGoPrintBtn) {
        batchGoPrintBtn.disabled = false;
        if (batchGoPrintBtn.dataset.originalHtml) {
            batchGoPrintBtn.innerHTML = batchGoPrintBtn.dataset.originalHtml;
        }
    }
    if (typeof loadRecordsList === "function") {
        loadRecordsList();
    } else if (
        typeof renderRecordsTable === "function" &&
        Array.isArray(allRecordsCache) &&
        allRecordsCache.length
    ) {
        renderRecordsTable(allRecordsCache);
    }
}

if (!window._goHandoffPageLifecycleBound) {
    window._goHandoffPageLifecycleBound = true;
    window.addEventListener("pageshow", () => {
        resetGoHandoffPage1Ui();
    });
    window.addEventListener("pagehide", () => {
        hideGoSignLoading();
    });
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            hideGoSignLoading();
        }
    });
}

function showGoSignLoading(message) {
    const msg = (message || "正在跳转签字页面，请稍候…").trim();
    let mask = document.getElementById("goSignLoadingMask");
    if (!mask) {
        mask = document.createElement("div");
        mask.id = "goSignLoadingMask";
        mask.style.position = "fixed";
        mask.style.left = "0";
        mask.style.top = "0";
        mask.style.width = "100vw";
        mask.style.height = "100vh";
        mask.style.background = "rgba(15,23,42,.34)";
        mask.style.backdropFilter = "blur(1px)";
        mask.style.zIndex = "4000";
        mask.style.display = "flex";
        mask.style.alignItems = "center";
        mask.style.justifyContent = "center";
        mask.innerHTML = `
            <div style="background:#fff;padding:16px 20px;border-radius:12px;box-shadow:0 12px 32px rgba(15,23,42,.2);display:flex;align-items:center;gap:10px;max-width:70vw;">
                <span class="spinner-border spinner-border-sm text-primary" aria-hidden="true"></span>
                <span id="goSignLoadingMaskText" style="font-size:.95rem;color:#0f172a;">${msg}</span>
            </div>
        `;
        document.body.appendChild(mask);
    } else {
        const txt = document.getElementById("goSignLoadingMaskText");
        if (txt) txt.textContent = msg;
        mask.style.display = "flex";
    }
    return mask;
}

function buildUploadTemplateFileUrl(uploadId) {
    const root = (window.__SCRIPT_ROOT__ != null ? String(window.__SCRIPT_ROOT__) : "").replace(/\/+$/, "");
    return (root || "") + "/api/uploads/" + encodeURIComponent(uploadId) + "/template-file";
}

/** 来源为「文件」时：左侧文字「文件」，右侧下载按钮 */
function buildTaskFileSourceHtml(uploadId) {
    const base = buildUploadTemplateFileUrl(uploadId);
    return (
        '<span class="d-inline-flex align-items-center justify-content-between gap-1" style="min-width:4.5rem">' +
        '<span>文件</span>' +
        '<a href="' + base + '" class="btn btn-sm btn-outline-primary py-0 px-2" title="下载 Word 模板">下载</a>' +
        '</span>'
    );
}

function renderRecordsTable(records) {
    const tbody = document.getElementById("recordsTableBody");
    if (!tbody) return;
    lastRenderedRecords = records || [];
    const groupBy = (document.querySelector('input[name="recordsGroupBy"]:checked') || {}).value || "none";

    try {
        _renderRecordsTableBody(tbody, lastRenderedRecords, groupBy);
    } catch (e) {
        console.error("renderRecordsTable:", e);
        tbody.innerHTML =
            '<tr><td colspan="27" class="text-danger small">任务列表渲染失败：' +
            _escTitle(e && e.message ? e.message : String(e)) +
            "。请刷新页面或查看浏览器控制台。</td></tr>";
    }
}

function _renderRecordsTableBody(tbody, lastRenderedRecords, groupBy) {
    const makeRow = (r, idx) => {
        const tr = document.createElement("tr");
        tr.dataset.id = r.id;
        tr.dataset.projectName = (r.projectName != null && r.projectName !== "") ? String(r.projectName).trim() : "";
        let sourceHtml;
        if (r.hasFile) {
            sourceHtml = buildTaskFileSourceHtml(r.id);
        } else if (r.hasLinks && r.templateLinks) {
            const firstLink = r.templateLinks.split('\n')[0].trim();
            sourceHtml = `<a href="${firstLink}" target="_blank" class="text-primary">链接(${r.linksCount})</a>`;
        } else {
            sourceHtml = "-";
        }
        const dueDateStyle = getDueDateStyle(r.dueDate);
        const dueDateHtml = dueDateStyle.class 
            ? `<span class="badge ${dueDateStyle.class}" title="${dueDateStyle.title || ''}">${dueDateStyle.text}</span>`
            : dueDateStyle.text;
        const statusBadge = r.completionStatus
            ? `<span class="badge bg-success">${r.completionStatus}</span>`
            : (r.taskStatus === "completed" || r.quickCompleted
                ? '<span class="badge bg-success">完成</span>'
                : '<span class="badge bg-warning text-dark">待办</span>');
        const auditStatusText = (r.auditStatus != null && r.auditStatus !== "") ? r.auditStatus : "-";
        const projectCode = (r.projectCode != null && r.projectCode !== "") ? r.projectCode : "-";
        const fileVersion = (r.fileVersion != null && r.fileVersion !== "") ? r.fileVersion : "-";
        const documentDisplayDate = (r.documentDisplayDate != null && r.documentDisplayDate !== "") ? r.documentDisplayDate : "-";
        const reviewer = (r.reviewer != null && r.reviewer !== "") ? r.reviewer : "-";
        const approver = (r.approver != null && r.approver !== "") ? r.approver : "-";
        const canAiprintHandoff = !!(r.hasGenerated || r.hasFile || r.hasLinks);
        const ahDis = canAiprintHandoff ? "" : " disabled";
        const ahTitle = canAiprintHandoff
            ? "跳转 aiprintword（需系统配置 AIPRINTWORD_BASE_URL 与密钥）"
            : "需先有已保存模板、文档链接或已生成文档";
        // 事项型任务：隐藏文档流转相关按钮（去签字/去打印）。
        const _isMatterRow = taskTypeCategoryOf(r.taskType) === TASK_TYPE_CATEGORY_MATTER;
        const goSignBtnHtml = _isMatterRow ? "" : `<button type="button" class="btn btn-sm btn-outline-secondary btn-go-sign me-1" data-id="${r.id}"${ahDis} title="${_escTitle(ahTitle)}">去签字</button>`;
        const goPrintBtnHtml = _isMatterRow ? "" : `<button type="button" class="btn btn-sm btn-outline-secondary btn-go-print me-1" data-id="${r.id}"${ahDis} title="${_escTitle(ahTitle)}">去打印</button>`;
        tr.innerHTML = `
            <td class="col-drag"><span class="drag-handle" draggable="true" title="拖动排序">⋮⋮</span><input type="checkbox" class="form-check-input record-checkbox" data-id="${r.id}"></td>
            <td class="seq-cell">${idx + 1}</td>
            <td data-col="projectName" class="col-wide project-name-pick-entry" title="${_escTitle(r.projectName)}（双击：新建录入块并带入该项目）">${r.projectName}</td>
            <td data-col="fileName" class="col-wide" title="${_escTitle(r.fileName)}">${r.fileName}</td>
            <td title="${_escTitle(r.taskType)}">${r.taskType || "-"}</td>
            <td title="${_escTitle(r.belongingModule)}">${(r.belongingModule != null && r.belongingModule !== "") ? r.belongingModule : "-"}</td>
            <td>${sourceHtml}</td>
            <td title="${_escTitle(r.author)}">${r.author}</td>
            <td>${dueDateHtml}</td>
            <td title="${_escTitle(r.businessSide)}">${(r.businessSide != null && r.businessSide !== "") ? r.businessSide : "-"}</td>
            <td title="${_escTitle(r.product)}">${(r.product != null && r.product !== "") ? r.product : "-"}</td>
            <td title="${_escTitle(r.country)}">${(r.country != null && r.country !== "") ? r.country : "-"}</td>
            <td>${statusBadge}</td>
            <td title="${_escTitle(r.auditStatus)}">${auditStatusText}</td>
            <td data-wrap style="max-width:180px" title="${_escTitle(r.notes)}">${_renderNotesHtml(r.notes)}</td>
            <td title="${_escTitle(r.executionNotes)}">${(r.executionNotes != null && r.executionNotes !== "") ? r.executionNotes : "-"}</td>
            <td title="${_escTitle(r.projectCode)}">${projectCode}</td>
            <td title="${_escTitle(r.fileVersion)}">${fileVersion}</td>
            <td title="${_escTitle(r.documentDisplayDate)}">${documentDisplayDate}</td>
            <td title="${_escTitle(r.reviewer)}">${reviewer}</td>
            <td title="${_escTitle(r.approver)}">${approver}</td>
            <td title="${_escTitle(r.displayedAuthor)}">${(r.displayedAuthor != null && r.displayedAuthor !== "") ? r.displayedAuthor : "-"}</td>
            <td title="${_escTitle(r.projectNotes)}">${(r.projectNotes != null && r.projectNotes !== "") ? r.projectNotes : "-"}</td>
            <td title="${_escTitle(r.registeredProductName)}">${(r.registeredProductName != null && r.registeredProductName !== "") ? r.registeredProductName : "-"}</td>
            <td title="${_escTitle(r.model)}">${(r.model != null && r.model !== "") ? r.model : "-"}</td>
            <td title="${_escTitle(r.registrationVersion)}">${(r.registrationVersion != null && r.registrationVersion !== "") ? r.registrationVersion : "-"}</td>
            <td class="col-op">
                <button class="btn btn-sm btn-outline-primary btn-edit-task me-1" data-id="${r.id}">编辑</button>
                <button type="button" class="btn btn-sm btn-outline-info btn-audit-task me-1" data-id="${r.id}" title="aicheckword 单文档审核">单审</button>
                ${goSignBtnHtml}
                ${goPrintBtnHtml}
                <button class="btn btn-sm btn-outline-danger btn-delete-task" data-id="${r.id}">删除</button>
            </td>
        `;
        return tr;
    };
    
    tbody.innerHTML = "";
    if (groupBy === "none") {
        lastRenderedRecords.forEach((r, idx) => {
            const tr = makeRow(r, idx);
            tbody.appendChild(tr);
        });
    } else if (groupBy === "project_author") {
        const projectMap = new Map();
        lastRenderedRecords.forEach((r) => {
            const p = r.projectName ?? "";
            const a = r.author ?? "";
            if (!projectMap.has(p)) projectMap.set(p, new Map());
            const authorMap = projectMap.get(p);
            if (!authorMap.has(a)) authorMap.set(a, []);
            authorMap.get(a).push(r);
        });
        let globalIdx = 0;
        let groupIndexL1 = 0;
        let groupIndexL2 = 0;
        projectMap.forEach((authorMap, projectName) => {
            const key1 = "project:" + projectName;
            const totalProject = [...authorMap.values()].reduce((s, arr) => s + arr.length, 0);
            const collapsed1 = recordsCollapsedGroups.has(key1);
            const header1 = document.createElement("tr");
            header1.className = "group-header-row group-header-level1 bg-light" + (collapsed1 ? " group-collapsed" : "");
            header1.dataset.groupKey = key1;
            header1.dataset.groupLevel = "1";
            header1.dataset.groupIndex = String(groupIndexL1++);
            header1.innerHTML = `<td colspan="27" class="cursor-pointer"><span class="group-toggle">${collapsed1 ? "▶" : "▼"}</span> 项目：${projectName || "（空）"} (${totalProject}条)</td>`;
            header1.style.cursor = "pointer";
            tbody.appendChild(header1);
            authorMap.forEach((arr, authorName) => {
                const key2 = key1 + "|author:" + authorName;
                const collapsed2 = recordsCollapsedGroups.has(key2);
                const header2 = document.createElement("tr");
                header2.className = "group-header-row group-header-level2 bg-light" + (collapsed2 ? " group-collapsed" : "");
                header2.dataset.groupKey = key2;
                header2.dataset.groupLevel = "2";
                header2.dataset.groupIndex = String(groupIndexL2);
                header2.innerHTML = `<td colspan="27" class="cursor-pointer ps-4"><span class="group-toggle">${collapsed2 ? "▶" : "▼"}</span> 编写人：${authorName || "（空）"} (${arr.length}条)</td>`;
                header2.style.cursor = "pointer";
                tbody.appendChild(header2);
                const rowHidden = collapsed1 || collapsed2;
                arr.forEach((r) => {
                    const tr = makeRow(r, globalIdx++);
                    tr.classList.add("group-data-row");
                    tr.dataset.groupKey1 = key1;
                    tr.dataset.groupKey2 = key2;
                    tr.dataset.groupIndex = String(groupIndexL2);
                    if (rowHidden) tr.classList.add("d-none");
                    tbody.appendChild(tr);
                });
                groupIndexL2++;
            });
        });
        tbody.querySelectorAll(".group-header-row").forEach((headerTr) => {
            headerTr.addEventListener("click", () => {
                const key = headerTr.dataset.groupKey;
                const level = headerTr.dataset.groupLevel;
                if (recordsCollapsedGroups.has(key)) recordsCollapsedGroups.delete(key);
                else recordsCollapsedGroups.add(key);
                const collapsed = recordsCollapsedGroups.has(key);
                headerTr.classList.toggle("group-collapsed", collapsed);
                headerTr.querySelector(".group-toggle").textContent = collapsed ? "▶" : "▼";
                if (level === "1") {
                    tbody.querySelectorAll(`tr.group-data-row[data-group-key1="${key}"]`).forEach((row) => {
                        const key2 = row.dataset.groupKey2;
                        const collapsed2 = recordsCollapsedGroups.has(key2);
                        row.classList.toggle("d-none", collapsed || collapsed2);
                    });
                } else {
                    tbody.querySelectorAll(`tr.group-data-row[data-group-key2="${key}"]`).forEach((row) => {
                        const key1 = row.dataset.groupKey1;
                        const collapsed1 = recordsCollapsedGroups.has(key1);
                        row.classList.toggle("d-none", collapsed || collapsed1);
                    });
                }
            });
        });
    } else {
        const keyFn = groupBy === "project" ? (r) => r.projectName : (r) => r.author;
        const label = groupBy === "project" ? "项目" : "编写人";
        const groupMap = new Map();
        lastRenderedRecords.forEach((r) => {
            const k = keyFn(r) || "";
            if (!groupMap.has(k)) groupMap.set(k, []);
            groupMap.get(k).push(r);
        });
        let globalIdx = 0;
        let groupIndex = 0;
        groupMap.forEach((arr, key) => {
            const gidx = groupIndex++;
            const collapsed = recordsCollapsedGroups.has(key);
            const headerTr = document.createElement("tr");
            headerTr.className = "group-header-row bg-light" + (collapsed ? " group-collapsed" : "");
            headerTr.dataset.groupKey = key;
            headerTr.dataset.groupIndex = String(gidx);
            headerTr.innerHTML = `<td colspan="27" class="cursor-pointer"><span class="group-toggle">${collapsed ? "▶" : "▼"}</span> ${label}：${key || "（空）"} (${arr.length}条)</td>`;
            headerTr.style.cursor = "pointer";
            tbody.appendChild(headerTr);
            arr.forEach((r) => {
                const tr = makeRow(r, globalIdx++);
                tr.classList.add("group-data-row");
                tr.dataset.groupKey = key;
                tr.dataset.groupIndex = String(gidx);
                if (collapsed) tr.classList.add("d-none");
                tbody.appendChild(tr);
            });
        });
        tbody.querySelectorAll(".group-header-row").forEach((headerTr) => {
            headerTr.addEventListener("click", () => {
                const key = headerTr.dataset.groupKey;
                if (recordsCollapsedGroups.has(key)) {
                    recordsCollapsedGroups.delete(key);
                } else {
                    recordsCollapsedGroups.add(key);
                }
                const collapsed = recordsCollapsedGroups.has(key);
                headerTr.classList.toggle("group-collapsed", collapsed);
                headerTr.querySelector(".group-toggle").textContent = collapsed ? "▶" : "▼";
                tbody.querySelectorAll(`tr.group-data-row[data-group-index="${headerTr.dataset.groupIndex}"]`).forEach((row) => {
                    row.classList.toggle("d-none", collapsed);
                });
            });
        });
    }
    
    tbody.querySelectorAll(".btn-edit-task").forEach((btn) => {
        btn.addEventListener("click", () => {
            const r = allRecordsCache.find(x => x.id === btn.dataset.id);
            if (r) openEditRecordModal(r);
        });
    });

    tbody.querySelectorAll(".btn-go-sign").forEach((btn) => {
        btn.addEventListener("click", () => {
            if (btn.disabled) return;
            tbody.querySelectorAll(".btn-go-sign,.btn-go-print,.btn-edit-task,.btn-delete-task").forEach((b) => {
                b.disabled = true;
            });
            btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>跳转中`;
            showGoSignLoading("正在打开签字页面并载入任务文件…");
            window.location.href = `/go/sign?upload_id=${encodeURIComponent(btn.dataset.id || "")}`;
        });
    });
    tbody.querySelectorAll(".btn-go-print").forEach((btn) => {
        btn.addEventListener("click", () => {
            if (btn.disabled) return;
            tbody.querySelectorAll(".btn-go-sign,.btn-go-print,.btn-edit-task,.btn-delete-task").forEach((b) => {
                b.disabled = true;
            });
            btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>跳转中`;
            showGoSignLoading("正在打开打印页面并载入任务文件…");
            window.location.href = `/go/print?upload_id=${encodeURIComponent(btn.dataset.id || "")}`;
        });
    });
    
    tbody.querySelectorAll(".btn-delete-task").forEach((btn) => {
        btn.addEventListener("click", async () => {
            if (!confirm("确定要删除此任务吗？")) return;
            try {
                await App.request(`/api/uploads/${btn.dataset.id}`, { method: "DELETE" });
                App.notify("任务已删除");
                loadRecordsList();
            } catch (e) {
                App.notify(e.message || "删除失败", "danger");
            }
        });
    });

    tbody.querySelectorAll(".btn-audit-task").forEach((btn) => {
        btn.addEventListener("click", () => {
            const id = btn.dataset.id || "";
            if (!id) return;
            const rec = _findUploadRecordById(id);
            const url = buildIntegrationUrlFromRecord(rec, "/audit/", { upload_ids: id, mode: "single" });
            window.open(url, "_blank", "noopener");
        });
    });
    
    initDragSort(tbody, async (orders) => {
        try {
            await App.request("/api/uploads/reorder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ orders }),
            });
        } catch (e) {
            App.notify(e.message, "danger");
        }
    });

    const selectAllEl = document.getElementById("recordSelectAll");
    if (selectAllEl) selectAllEl.checked = false;
    updateBatchEditButtonState();
    scheduleSyncStickyNameColumns(document.getElementById("recordsTable"));
}

function loadRecordsList() {
    const tbody = document.getElementById("recordsTableBody");
    if (!tbody) return;

    const showHistory = !!document.getElementById("showHistoryProjectsPage1")?.checked;
    const url = showHistory ? "/api/uploads?includeHistory=1" : "/api/uploads";
    App.request(url)
        .then((res) => {
            allRecordsCache = res.records || [];
            renderRecordsTable(allRecordsCache);
            refreshSavedProjectPickSelect();
        })
        .catch((e) => App.notify(e.message || "加载记录失败", "danger"));
}

let usersListCache = [];

function _escUserCell(s) {
    return String(s ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function _getUsersFilterValues() {
    return {
        keyword: (document.getElementById("filterUserKeyword")?.value || "").trim().toLowerCase(),
        mobile: (document.getElementById("filterUserMobile")?.value || "").trim(),
        admin: (document.getElementById("filterUserAdmin")?.value || "").trim(),
    };
}

function _filterUsersList(users) {
    const f = _getUsersFilterValues();
    return (users || []).filter((u) => {
        if (f.keyword) {
            const hay = `${u.username || ""} ${u.displayName || ""}`.toLowerCase();
            if (!hay.includes(f.keyword)) return false;
        }
        if (f.mobile && !(u.mobile || "").includes(f.mobile)) return false;
        if (f.admin === "yes" && !u.isAdmin) return false;
        if (f.admin === "no" && u.isAdmin) return false;
        return true;
    });
}

function _updateUsersListCountHint(total, shown) {
    const el = document.getElementById("usersListCountHint");
    if (!el) return;
    if (total === shown) {
        el.textContent = `共 ${total} 个账号`;
    } else {
        el.textContent = `共 ${total} 个账号，当前筛选显示 ${shown} 个`;
    }
}

function renderUsersList() {
    const tbody = document.getElementById("usersTableBody");
    if (!tbody) return;
    const filtered = _filterUsersList(usersListCache);
    _updateUsersListCountHint(usersListCache.length, filtered.length);
    tbody.innerHTML = "";
    if (!filtered.length) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="5" class="text-center text-muted small py-4">暂无匹配的账号</td>`;
        tbody.appendChild(tr);
        return;
    }
    filtered.forEach((u) => {
        const tr = document.createElement("tr");
        const adminBadge = u.isAdmin
            ? '<span class="badge bg-primary">是</span>'
            : '<span class="text-muted">否</span>';
        const displayName = (u.displayName || "").trim() || "-";
        tr.innerHTML = `
            <td>${_escUserCell(u.username)}</td>
            <td>${_escUserCell(displayName)}</td>
            <td class="user-mobile-cell">${_escUserCell(u.mobile || "-")}</td>
            <td>${adminBadge}</td>
            <td class="text-nowrap">
                <button type="button" class="btn btn-sm btn-outline-info btn-check-at me-1" data-username="${_escUserCell(u.username)}">检查@</button>
                <button type="button" class="btn btn-sm btn-outline-secondary btn-edit-mobile me-1" data-id="${u.id}" data-username="${_escUserCell(u.username)}" data-display-name="${_escUserCell(u.displayName || "")}" data-mobile="${_escUserCell(u.mobile || "")}">编辑</button>
                <button type="button" class="btn btn-sm btn-outline-primary btn-toggle-admin me-1" data-id="${u.id}" data-admin="${u.isAdmin ? "1" : "0"}">${u.isAdmin ? "取消管理员" : "设为管理员"}</button>
                <button type="button" class="btn btn-sm btn-outline-danger btn-delete-user" data-id="${u.id}">删除</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
    tbody.querySelectorAll(".btn-toggle-admin").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const next = btn.dataset.admin !== "1";
            try {
                await App.request(`/api/users/${btn.dataset.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ isAdmin: next }),
                });
                App.notify(next ? "已设为管理员" : "已取消管理员");
                loadUsersList();
            } catch (e) {
                App.notify(e.message || "更新失败", "danger");
            }
        });
    });
    tbody.querySelectorAll(".btn-delete-user").forEach((btn) => {
        btn.addEventListener("click", async () => {
            if (!confirm("确定要删除此用户吗？")) return;
            try {
                await App.request(`/api/users/${btn.dataset.id}`, { method: "DELETE" });
                App.notify("用户已删除");
                loadUsersList();
            } catch (e) {
                App.notify(e.message || "删除失败", "danger");
            }
        });
    });
    tbody.querySelectorAll(".btn-check-at").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const name = (btn.dataset.username || "").trim();
            if (!name) return;
            try {
                const r = await App.request(`/api/notify/at-resolve?author=${encodeURIComponent(name)}`);
                App.notify(r.message || (r.canAt ? "可@" : "无法@"), r.canAt ? "success" : "warning");
            } catch (e) {
                App.notify(e.message || "检查失败", "danger");
            }
        });
    });
    tbody.querySelectorAll(".btn-edit-mobile").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.getElementById("editUserMobileId").value = btn.dataset.id;
            document.getElementById("editUserMobileUsername").value = btn.dataset.username || "";
            const dnEl = document.getElementById("editUserDisplayName");
            if (dnEl) dnEl.value = btn.dataset.displayName || "";
            document.getElementById("editUserMobileValue").value = btn.dataset.mobile || "";
            const modal = new bootstrap.Modal(document.getElementById("editUserMobileModal"));
            modal.show();
        });
    });
}

function loadUsersList() {
    const tbody = document.getElementById("usersTableBody");
    if (!tbody) return Promise.resolve();

    return App.request("/api/users")
        .then((res) => {
            usersListCache = res.users || [];
            renderUsersList();
            refreshAllAuthorPickers();
        })
        .catch((e) => App.notify(e.message || "加载用户失败", "danger"));
}

function initUsersListFilter() {
    ["filterUserKeyword", "filterUserMobile", "filterUserAdmin"].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener("input", renderUsersList);
        el.addEventListener("change", renderUsersList);
    });
}

function userAuthorPickLabel(u) {
    const dn = (u.displayName || "").trim();
    const un = (u.username || "").trim();
    return dn || un;
}

function userAuthorPickHaystack(u) {
    const dn = (u.displayName || "").trim();
    const un = (u.username || "").trim();
    return `${un} ${dn}`.toLowerCase();
}

function filterUsersForAuthorPick(keyword) {
    const k = (keyword || "").trim().toLowerCase();
    const list = Array.isArray(usersListCache) ? usersListCache : [];
    if (!k) return list.slice();
    return list.filter((u) => userAuthorPickHaystack(u).includes(k));
}

function fillAuthorSelectOptions(selectEl, opts) {
    if (!selectEl) return;
    const options = opts || {};
    const filter = options.filter || "";
    const selected = (options.selected != null ? String(options.selected) : selectEl.value || "").trim();
    const placeholder = options.placeholder || "— 请选择编写人 —";
    const allowLegacy = options.allowLegacy !== false;
    const list = filterUsersForAuthorPick(filter);
    selectEl.innerHTML = "";
    const emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = placeholder;
    selectEl.appendChild(emptyOpt);
    const seen = new Set();
    list.forEach((u) => {
        const lab = userAuthorPickLabel(u);
        if (!lab || seen.has(lab)) return;
        seen.add(lab);
        const opt = document.createElement("option");
        opt.value = lab;
        const un = (u.username || "").trim();
        opt.textContent =
            u.displayName && un && u.displayName !== un ? `${u.displayName}（${un}）` : lab;
        selectEl.appendChild(opt);
    });
    if (selected && !seen.has(selected) && allowLegacy) {
        ensureSelectHasOption(selectEl, selected, "（当前记录）");
    }
    if (selected) selectEl.value = selected;
}

function bindAuthorPickerWrapper(wrapper, hooks) {
    const filterEl = wrapper.querySelector(".author-picker-filter");
    const selectEl = wrapper.querySelector(".task-author");
    if (!selectEl) return null;
    const refresh = () => {
        fillAuthorSelectOptions(selectEl, {
            filter: filterEl ? filterEl.value : "",
            selected: selectEl.value,
        });
    };
    if (filterEl && !filterEl.dataset.authorPickerBound) {
        filterEl.dataset.authorPickerBound = "1";
        filterEl.addEventListener("input", refresh);
    }
    if (!selectEl.dataset.authorPickerBound) {
        selectEl.dataset.authorPickerBound = "1";
        selectEl.addEventListener("change", () => {
            hooks?.onChange?.(selectEl.value.trim(), selectEl);
        });
    }
    refresh();
    return { selectEl, refresh };
}

function mountAuthorPicker(host, opts) {
    if (!host) return null;
    const options = opts || {};
    const selected = (options.selected || "").trim();
    const showQuickAdd = !!options.showQuickAdd;
    host.innerHTML = "";
    host.classList.add("author-picker");
    const filterEl = document.createElement("input");
    filterEl.type = "search";
    filterEl.className = "form-control form-control-sm author-picker-filter";
    filterEl.placeholder = "筛选编写人…";
    filterEl.autocomplete = "off";
    const rowEl = document.createElement("div");
    rowEl.className = showQuickAdd ? "input-group input-group-sm author-picker-select-row" : "author-picker-select-row";
    const selectEl = document.createElement("select");
    selectEl.className = "form-select form-select-sm task-author";
    if (options.required) selectEl.required = true;
    rowEl.appendChild(selectEl);
    if (showQuickAdd) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-outline-success btn-create-user";
        btn.title = "快速创建账号";
        btn.textContent = "+";
        btn.addEventListener("click", () => {
            const lab = selectEl.value.trim();
            const hit = (usersListCache || []).find((u) => userAuthorPickLabel(u) === lab);
            window.__authorPickerPendingSelect = selectEl;
            const quickUsername = document.getElementById("quickUsername");
            if (quickUsername) quickUsername.value = hit?.username || lab;
            const qm = document.getElementById("quickUserModal");
            if (qm) bootstrap.Modal.getOrCreateInstance(qm).show();
        });
        rowEl.appendChild(btn);
    }
    host.appendChild(filterEl);
    host.appendChild(rowEl);
    return bindAuthorPickerWrapper(host, options.hooks);
}

function refreshAllAuthorPickers() {
    document.querySelectorAll(".author-picker").forEach((wrapper) => {
        const selectEl = wrapper.querySelector(".task-author");
        const filterEl = wrapper.querySelector(".author-picker-filter");
        if (!selectEl) return;
        fillAuthorSelectOptions(selectEl, {
            filter: filterEl ? filterEl.value : "",
            selected: selectEl.value,
        });
    });
}

function ensureEditRecordAuthorPicker() {
    const host = document.getElementById("editRecordAuthorPicker");
    if (!host) return null;
    if (!host.dataset.mounted) {
        mountAuthorPicker(host, {
            required: true,
            hooks: {
                onChange: (authorVal) => {
                    const assigneeInput = document.getElementById("editRecordAssignee");
                    if (assigneeInput && authorVal) assigneeInput.value = authorVal;
                    updateEditRecordAssigneeMobileHint(assigneeInput?.value || authorVal || "");
                },
            },
        });
        host.dataset.mounted = "1";
    }
    return host.querySelector(".task-author");
}

function ensureBatchEditAuthorPicker() {
    const host = document.getElementById("batchEditAuthorPicker");
    if (!host) return null;
    if (!host.dataset.mounted) {
        mountAuthorPicker(host, { placeholder: "— 不修改 —" });
        host.dataset.mounted = "1";
    }
    return host.querySelector(".task-author");
}

function setAuthorPickerValue(hostOrId, value) {
    const host =
        typeof hostOrId === "string" ? document.getElementById(hostOrId) : hostOrId;
    const selectEl = host?.classList?.contains("author-picker")
        ? host.querySelector(".task-author")
        : host?.classList?.contains("task-author")
          ? host
          : host?.querySelector?.(".task-author");
    if (!selectEl) return;
    const filterEl = host?.querySelector?.(".author-picker-filter");
    fillAuthorSelectOptions(selectEl, {
        filter: filterEl ? filterEl.value : "",
        selected: value || "",
    });
}

async function submitCreateUserForm() {
    const usernameInput = document.getElementById("newUsername");
    const passwordInput = document.getElementById("newPassword");
    const displayNameInput = document.getElementById("newDisplayName");
    const mobileInput = document.getElementById("newMobile");
    const isAdminInput = document.getElementById("newUserIsAdmin");
    const payload = {
        username: (usernameInput?.value || "").trim(),
        password: (passwordInput?.value || "").trim(),
        displayName: displayNameInput ? (displayNameInput.value || "").trim() || null : null,
        mobile: mobileInput ? (mobileInput.value || "").trim() || null : null,
        isAdmin: !!(isAdminInput && isAdminInput.checked),
    };
    if (!payload.username || !payload.password) {
        App.notify("用户名和密码不能为空", "warning");
        return false;
    }
    const result = await App.request("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    App.notify(result.message || "用户创建成功");
    document.getElementById("createUserForm")?.reset();
    bootstrap.Modal.getInstance(document.getElementById("createUserModal"))?.hide();
    loadUsersList();
    return true;
}

function initCreateUserModal() {
    const openBtn = document.getElementById("btnOpenCreateUserModal");
    const modalEl = document.getElementById("createUserModal");
    const form = document.getElementById("createUserForm");
    const submitBtn = document.getElementById("createUserSubmitBtn");
    if (!modalEl) return;

    openBtn?.addEventListener("click", () => {
        form?.reset();
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
        setTimeout(() => document.getElementById("newUsername")?.focus(), 200);
    });

    const onSubmit = async (e) => {
        e?.preventDefault();
        try {
            await submitCreateUserForm();
        } catch (error) {
            App.notify(error.message || "创建失败", "danger");
        }
    };

    form?.addEventListener("submit", onSubmit);
    submitBtn?.addEventListener("click", onSubmit);
}

function initQuickUserForm() {
    const form = document.getElementById("quickUserForm");
    if (!form) return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const usernameInput = document.getElementById("quickUsername");
        const passwordInput = document.getElementById("quickPassword");
        const mobileInput = document.getElementById("quickMobile");
        
        const payload = {
            username: usernameInput.value.trim(),
            password: passwordInput.value.trim(),
            displayName: usernameInput.value.trim(),
            mobile: mobileInput ? mobileInput.value.trim() || null : null,
        };
        
        if (!payload.username || !payload.password) {
            App.notify("用户名和密码不能为空", "warning");
            return;
        }
        
        try {
            const result = await App.request("/api/users", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            App.notify(result.message || "用户创建成功");
            form.reset();
            const newLabel =
                result.user?.displayName || result.user?.username || payload.username || "";
            await loadUsersList();
            if (window.__authorPickerPendingSelect) {
                fillAuthorSelectOptions(window.__authorPickerPendingSelect, { selected: newLabel });
                window.__authorPickerPendingSelect = null;
            }
            bootstrap.Modal.getInstance(document.getElementById("quickUserModal"))?.hide();
            const editId = document.getElementById("editRecordId")?.value;
            const editModal = document.getElementById("editRecordModal");
            if (editId && editModal?.classList.contains("show")) {
                setAuthorPickerValue("editRecordAuthorPicker", newLabel);
                const assigneeInput = document.getElementById("editRecordAssignee");
                if (assigneeInput) {
                    assigneeInput.value = newLabel;
                    updateEditRecordAssigneeMobileHint(assigneeInput.value);
                }
            }
        } catch (error) {
            App.notify(error.message, "danger");
        }
    });
}

function initConfigManagement() {
    const taskTypesList = document.getElementById("taskTypesList");
    const completionStatusesList = document.getElementById("completionStatusesList");
    const auditStatusesList = document.getElementById("auditStatusesList");
    const addTaskTypeBtn = document.getElementById("addTaskTypeBtn");
    const addCompletionStatusBtn = document.getElementById("addCompletionStatusBtn");
    const addAuditStatusBtn = document.getElementById("addAuditStatusBtn");
    const newTaskTypeInput = document.getElementById("newTaskType");
    const newCompletionStatusInput = document.getElementById("newCompletionStatus");
    const newAuditStatusInput = document.getElementById("newAuditStatus");

    if (!taskTypesList) return;

    const loadTaskTypesList = async () => {
        try {
            await loadTaskTypes();
            taskTypesList.innerHTML = "";
            taskTypesCache.forEach((t) => {
                const cat = _normalizeTaskTypeCategory(t.category);
                const catLabel = cat === TASK_TYPE_CATEGORY_MATTER ? "事项型" : "文件型";
                const badge = document.createElement("span");
                badge.className = "badge d-flex align-items-center " + (cat === TASK_TYPE_CATEGORY_MATTER ? "bg-warning text-dark" : "bg-secondary");
                badge.innerHTML = `
                    <button type="button" class="btn btn-sm py-0 px-1 me-1 task-type-cat-btn ${cat === TASK_TYPE_CATEGORY_MATTER ? "btn-outline-light" : "btn-outline-light"}" title="点击在「文件型 ↔ 事项型」间切换" style="font-size:0.65rem;line-height:1;">${catLabel}</button>
                    <span class="me-1">${t.name}</span>
                    <button type="button" class="btn-close ${cat === TASK_TYPE_CATEGORY_MATTER ? "" : "btn-close-white"}" style="font-size:0.6rem;" data-id="${t.id}" title="删除"></button>
                `;
                const catBtn = badge.querySelector(".task-type-cat-btn");
                catBtn?.addEventListener("click", async () => {
                    const next = cat === TASK_TYPE_CATEGORY_MATTER ? TASK_TYPE_CATEGORY_FILE : TASK_TYPE_CATEGORY_MATTER;
                    try {
                        await App.request(`/api/configs/task-types/${t.id}`, {
                            method: "PATCH",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ category: next }),
                        });
                        loadTaskTypesList();
                    } catch (e) {
                        App.notify(e.message || "切换失败", "danger");
                    }
                });
                badge.querySelector(".btn-close").addEventListener("click", async () => {
                    try {
                        await App.request(`/api/configs/task-types/${t.id}`, { method: "DELETE" });
                        loadTaskTypesList();
                    } catch (e) {
                        App.notify(e.message, "danger");
                    }
                });
                taskTypesList.appendChild(badge);
            });
        } catch (e) {
            App.notify(e.message, "danger");
        }
    };

    const loadCompletionStatusesList = async () => {
        try {
            const res = await App.request("/api/configs/completion-statuses");
            const statuses = res.completionStatuses || [];
            completionStatusesList.innerHTML = "";
            statuses.forEach(s => {
                const badge = document.createElement("span");
                badge.className = "badge bg-info text-dark d-flex align-items-center";
                badge.innerHTML = `${s.name} <button class="btn-close ms-1" style="font-size:0.6rem;" data-id="${s.id}"></button>`;
                badge.querySelector("button").addEventListener("click", async () => {
                    try {
                        await App.request(`/api/configs/completion-statuses/${s.id}`, { method: "DELETE" });
                        loadCompletionStatusesList();
                    } catch (e) {
                        App.notify(e.message, "danger");
                    }
                });
                completionStatusesList.appendChild(badge);
            });
        } catch (e) {
            App.notify(e.message, "danger");
        }
    };

    addTaskTypeBtn?.addEventListener("click", async () => {
        const name = newTaskTypeInput.value.trim();
        if (!name) return;
        const newCatSel = document.getElementById("newTaskCategory");
        const category = _normalizeTaskTypeCategory(newCatSel ? newCatSel.value : TASK_TYPE_CATEGORY_FILE);
        try {
            await App.request("/api/configs/task-types", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, category }),
            });
            newTaskTypeInput.value = "";
            loadTaskTypesList();
        } catch (e) {
            App.notify(e.message, "danger");
        }
    });

    addCompletionStatusBtn?.addEventListener("click", async () => {
        const name = newCompletionStatusInput.value.trim();
        if (!name) return;
        try {
            await App.request("/api/configs/completion-statuses", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
            });
            newCompletionStatusInput.value = "";
            loadCompletionStatusesList();
        } catch (e) {
            App.notify(e.message, "danger");
        }
    });

    const loadAuditStatusesList = async () => {
        if (!auditStatusesList) return;
        try {
            const res = await App.request("/api/configs/audit-statuses");
            const statuses = res.auditStatuses || [];
            auditStatusesList.innerHTML = "";
            statuses.forEach(s => {
                const badge = document.createElement("span");
                badge.className = "badge bg-warning text-dark d-flex align-items-center";
                badge.innerHTML = `${s.name} <button class="btn-close ms-1" style="font-size:0.6rem;" data-id="${s.id}"></button>`;
                badge.querySelector("button").addEventListener("click", async () => {
                    try {
                        await App.request(`/api/configs/audit-statuses/${s.id}`, { method: "DELETE" });
                        loadAuditStatusesList();
                    } catch (e) {
                        App.notify(e.message, "danger");
                    }
                });
                auditStatusesList.appendChild(badge);
            });
        } catch (e) {
            App.notify(e.message, "danger");
        }
    };

    addAuditStatusBtn?.addEventListener("click", async () => {
        const name = newAuditStatusInput?.value.trim();
        if (!name) return;
        try {
            await App.request("/api/configs/audit-statuses", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
            });
            if (newAuditStatusInput) newAuditStatusInput.value = "";
            loadAuditStatusesList();
        } catch (e) {
            App.notify(e.message, "danger");
        }
    });

    loadTaskTypesList();
    loadCompletionStatusesList();
    loadAuditStatusesList();
}

function initLoginPage() {
    const form = document.getElementById("loginForm");
    if (!form) return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const payload = {
            username: document.getElementById("loginUsername").value.trim(),
            password: document.getElementById("loginPassword").value,
        };
        try {
            await App.request("/api/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            window.location.href = _appPath("/generate");
        } catch (error) {
            App.notify(error.message, "danger");
        }
    });
}

let myTasksCache = [];
let lastRenderedMyTasks = [];
let myTasksSortKey = "projectPriority";
let myTasksSortDir = "desc";
let myTasksCollapsedGroups = new Set();

async function initGeneratePage() {
    const myTasksBody = document.getElementById("myTasksBody");
    const noTasksAlert = document.getElementById("noTasksAlert");
    const userInfo = document.getElementById("userInfo");
    const logoutBtn = document.getElementById("logoutBtn");
    const placeholderModal = document.getElementById("placeholderModal");
    const showHistoryEl = document.getElementById("showHistoryProjects");

    if (!myTasksBody) return;

    // 进入页面时默认不显示历史项目；防止浏览器回退/表单恢复导致再次进入时仍保持勾选
    if (showHistoryEl) showHistoryEl.checked = false;

    await loadCompletionStatuses();
    await loadTaskTypes();

    App.request("/api/me").then((res) => {
        if (res.loggedIn && userInfo) {
            let label = `欢迎，${res.user.displayName || res.user.username}`;
            if (res.user.isAdmin || res.featureAdminViewer) {
                label += "（管理员）";
            }
            userInfo.textContent = label;
        }
        if (res.featureFlags && typeof res.featureFlags === "object") {
            window.__FEATURE_FLAGS__ = res.featureFlags;
        }
    });

    logoutBtn?.addEventListener("click", async () => {
        await App.request("/api/logout", { method: "POST" });
        window.location.href = _appPath("/login");
    });

    const loadMyTasks = async () => {
        try {
            const showHistory = !!showHistoryEl?.checked;
            const url = showHistory ? "/api/my-tasks?includeHistory=1" : "/api/my-tasks";
            const res = await App.request(url);
            myTasksCache = res.records || [];
            
            if (myTasksCache.length === 0) {
                noTasksAlert?.classList.remove("d-none");
                // 清空旧渲染，避免取消“查看历史项目”后仍残留历史行
                myTasksBody.innerHTML = "";
                lastRenderedMyTasks = [];
                return;
            }
            noTasksAlert?.classList.add("d-none");

            renderMyTasksTable(sortRows(myTasksCache, myTasksSortKey, myTasksSortDir));
        } catch (error) {
            App.notify(error.message, "danger");
        }
    };
    
    initMyTasksFilter();
    initMyTasksTableSort();
    loadMyTasks();

    showHistoryEl?.addEventListener("change", () => {
        loadMyTasks();
    });

    // bfcache 场景：回退/前进时也复位
    if (!window._page2HistoryToggleBound) {
        window._page2HistoryToggleBound = true;
        window.addEventListener("pageshow", () => {
            const el = document.getElementById("showHistoryProjects");
            if (el) el.checked = false;
        });
    }
    
    document.querySelectorAll('input[name="myTasksGroupBy"]').forEach((radio) => {
        radio.addEventListener("change", () => {
            renderMyTasksTable(lastRenderedMyTasks);
        });
    });
    
    window.loadMyTasks = loadMyTasks;
}

function initMyTasksFilter() {
    const filterProject = document.getElementById("filterTaskProject");
    const filterFile = document.getElementById("filterTaskFile");
    const filterType = document.getElementById("filterTaskType");
    const filterStatus = document.getElementById("filterTaskStatus");
    
    if (!filterProject) return;
    
    taskTypesCache.forEach(t => {
        const opt = document.createElement("option");
        opt.value = t.name;
        opt.textContent = t.name;
        filterType?.appendChild(opt);
    });
    
    completionStatusesCache.forEach(s => {
        const opt = document.createElement("option");
        opt.value = s.name;
        opt.textContent = s.name;
        filterStatus?.appendChild(opt);
    });
    
    const applyFilter = () => {
        const projectVal = filterProject.value.toLowerCase();
        const fileVal = filterFile.value.toLowerCase();
        const typeVal = filterType.value;
        const statusVal = filterStatus.value;
        
        const filtered = myTasksCache.filter(r => {
            if (projectVal && !(String(r.projectName || "").toLowerCase().includes(projectVal))) return false;
            if (fileVal && !(String(r.fileName || "").toLowerCase().includes(fileVal))) return false;
            if (typeVal && r.taskType !== typeVal) return false;
            if (statusVal === "未完成" && r.completionStatus) return false;
            if (statusVal && statusVal !== "未完成" && r.completionStatus !== statusVal) return false;
            return true;
        });
        const sorted = sortRows(filtered, myTasksSortKey, myTasksSortDir);
        renderMyTasksTable(sorted);
    };
    
    [filterProject, filterFile, filterType, filterStatus].forEach(el => {
        el?.addEventListener("input", applyFilter);
        el?.addEventListener("change", applyFilter);
    });
}

function initMyTasksTableSort() {
    const table = document.getElementById("myTasksTable");
    if (!table) return;
    table.querySelectorAll("thead .th-sortable").forEach((th) => {
        th.addEventListener("click", () => {
            const key = th.dataset.sortKey;
            if (!key) return;
            if (myTasksSortKey === key) myTasksSortDir = myTasksSortDir === "asc" ? "desc" : "asc";
            else { myTasksSortKey = key; myTasksSortDir = "asc"; }
            table.querySelectorAll("thead .sort-indicator").forEach((s) => { s.textContent = ""; });
            const ind = th.querySelector(".sort-indicator");
            if (ind) ind.textContent = myTasksSortDir === "asc" ? "↑" : "↓";
            const sorted = sortRows(lastRenderedMyTasks, myTasksSortKey, myTasksSortDir);
            renderMyTasksTable(sorted);
        });
    });
}

const PAGE2_TEMPLATE_FILE_ACCEPT = ".docx,.doc,.zip,.tar,.gz,.tgz,.rar";

function confirmTemplateFileOverwrite(r) {
    if (!r || (!r.hasFile && !r.hasLinks)) return true;
    return window.confirm(
        "上传将覆盖该任务已有的模板文件或文档链接。\n" +
            "若当前来源为链接，上传后将改为「文件」来源。\n" +
            "每条任务仅保留一个文件，再次上传会继续覆盖。\n\n是否继续？"
    );
}

function page2ConfirmTemplateFileOverwrite(r) {
    return confirmTemplateFileOverwrite(r);
}

async function uploadPage2TemplateFile(uploadId, file, btn) {
    const fd = new FormData();
    fd.append("file", file);
    if (btn) btn.disabled = true;
    try {
        const res = await App.request(`/api/uploads/${uploadId}/template-file`, {
            method: "POST",
            body: fd,
        });
        App.notify(res.message || "模板文件已上传");
        if (typeof loadMyTasks === "function") loadMyTasks();
        return res;
    } finally {
        if (btn) btn.disabled = false;
    }
}

function bindPage2TemplateFileUpload(tr, r) {
    const input = tr.querySelector(".task-template-file-input");
    const btn = tr.querySelector(".btn-replace-template-file");
    if (!input || !btn) return;
    btn.addEventListener("click", () => input.click());
    input.addEventListener("change", async () => {
        const file = input.files && input.files[0];
        input.value = "";
        if (!file) return;
        if (!page2ConfirmTemplateFileOverwrite(r)) return;
        try {
            await uploadPage2TemplateFile(r.id, file, btn);
        } catch (e) {
            App.notify(e.message || "上传失败", "danger");
        }
    });
}

/** 读取页面2 功能开关：与系统配置「FEATURE_PAGE2_*」一致；未注入时按关闭处理。 */
function _page2Feature(name) {
    const flags = window.__FEATURE_FLAGS__ || {};
    return !!flags[name];
}

/**
 * 渲染页面2「我的任务」每行的操作按钮。
 * 事项型任务隐藏全部文档相关按钮；文件型任务按 FEATURE_PAGE2_* 开关决定每个按钮是否显示。
 */
function _buildPage2ActionButtonsHtml(r) {
    const isMatter = taskTypeCategoryOf(r.taskType) === TASK_TYPE_CATEGORY_MATTER;
    if (isMatter) {
        // 事项型任务：仅做事项跟进；隐藏「上传/替换、填写、初稿生成、审核后修改、翻译」
        return '<span class="small text-muted">事项型任务</span>';
    }
    const parts = [];
    if (_page2Feature("FEATURE_PAGE2_UPLOAD_REPLACE")) {
        parts.push(
            `<input type="file" class="d-none task-template-file-input" accept="${PAGE2_TEMPLATE_FILE_ACCEPT}" data-id="${r.id}">`
        );
        parts.push(
            `<button type="button" class="btn btn-sm btn-outline-secondary btn-replace-template-file" title="上传模板到 FTP；覆盖已有文件或链接">上传/替换</button>`
        );
    }
    if (r.hasFile || (r.placeholders && r.placeholders.length > 0)) {
        parts.push(
            `<button class="btn btn-sm btn-outline-primary btn-fill-placeholders ms-1" data-id="${r.id}">填写</button>`
        );
    }
    if (_page2Feature("FEATURE_PAGE2_DRAFT_GEN")) {
        parts.push(
            `<button type="button" class="btn btn-sm btn-outline-success btn-draft-gen-page2 ms-1" title="打开初稿生成页并带入本行项目/产品/国家/文件名">初稿生成</button>`
        );
    }
    if (_page2Feature("FEATURE_PAGE2_AUDIT_MODIFY")) {
        parts.push(
            `<button type="button" class="btn btn-sm btn-outline-info btn-audit-modify-page2 ms-1" title="基于历史审核报告对本任务做就地修改">审核后修改</button>`
        );
    }
    if (_page2Feature("FEATURE_PAGE2_TRANSLATE")) {
        parts.push(
            `<button type="button" class="btn btn-sm btn-outline-warning btn-translate-page2 ms-1" title="对本任务的模板文件做翻译">翻译</button>`
        );
    }
    return parts.join("\n");
}

/** 页面2任务行 → 初稿生成页，查询参数供 /draft-gen 预填下拉。 */
function buildDraftGenUrlFromTask(r) {
    const root = window.__SCRIPT_ROOT__ || "";
    const u = new URLSearchParams();
    u.set("from", "page2");
    if (r && r.id) u.set("upload_id", r.id);
    if (r && r.projectName) u.set("project_name", r.projectName);
    if (r && r.fileName) u.set("file_name", r.fileName);
    if (r && r.product) u.set("product", r.product);
    if (r && r.country) u.set("country", r.country);
    const pid = r && r.projectId != null ? String(r.projectId).trim() : "";
    if (pid && /^\d+$/.test(pid)) u.set("aicheckword_project_id", pid);
    return root + "/draft-gen/?" + u.toString();
}

function renderMyTasksTable(records) {
    const myTasksBody = document.getElementById("myTasksBody");
    const placeholderModal = document.getElementById("placeholderModal");
    if (!myTasksBody) return;
    lastRenderedMyTasks = records || [];
    const groupBy = (document.querySelector('input[name="myTasksGroupBy"]:checked') || {}).value || "none";
    
    const addOneRow = (r, idx, groupKey, groupIndex, collapsed) => {
        const tr = document.createElement("tr");
        tr.dataset.id = r.id;
        if (groupKey !== undefined) {
            tr.classList.add("group-data-row");
            tr.dataset.groupKey = groupKey;
            tr.dataset.groupIndex = String(groupIndex);
            if (collapsed) tr.classList.add("d-none");
        }
        const firstLink = r.templateLinks ? (r.templateLinks.split("\n")[0] || "").trim() : "";
        let sourceTd;
        if (r.hasFile) {
            sourceTd = buildTaskFileSourceHtml(r.id);
        } else if (r.hasLinks && firstLink) {
            sourceTd = `<a href="${firstLink}" target="_blank" class="text-primary">链接</a>`;
        } else {
            sourceTd = "-";
        }
        const linkCellHtml = r.hasLinks && firstLink
            ? `<a href="${firstLink}" target="_blank" class="text-primary small">打开</a>`
            : `<input type="text" class="form-control form-control-sm task-link-input" placeholder="填入链接" data-id="${r.id}" value="">`;
        const projectNotesDisplay = (r.projectNotes != null && r.projectNotes !== "") ? r.projectNotes : "-";
        const notesDisplay = (r.notes != null && r.notes !== "") ? r.notes : "-";
        const dueDateStyle = getDueDateStyle(r.dueDate);
        const dueDateHtml = dueDateStyle.class
            ? `<span class="badge ${dueDateStyle.class}" title="${dueDateStyle.title || ''}">${dueDateStyle.text}</span>`
            : (r.dueDate || "-");
        const projectCode = (r.projectCode != null && r.projectCode !== "") ? r.projectCode : "-";
        const fileVersion = (r.fileVersion != null && r.fileVersion !== "") ? r.fileVersion : "-";
        const documentDisplayDate = (r.documentDisplayDate != null && r.documentDisplayDate !== "") ? r.documentDisplayDate : "-";
        const reviewer = (r.reviewer != null && r.reviewer !== "") ? r.reviewer : "-";
        const approver = (r.approver != null && r.approver !== "") ? r.approver : "-";
        const isMatterRow = taskTypeCategoryOf(r.taskType) === TASK_TYPE_CATEGORY_MATTER;
        const execNotesPlaceholder = isMatterRow ? "请填写事项完成情况" : "执行备注";
        tr.innerHTML = `
            <td class="col-drag seq-cell"><span class="drag-handle" draggable="true" title="拖动排序">⋮⋮</span>${idx + 1}</td>
            <td data-col="projectName" class="col-wide" title="${_escTitle(r.projectName)}">${r.projectName}</td>
            <td data-col="fileName" class="col-wide" title="${_escTitle(r.fileName)}">${r.fileName}</td>
            <td title="${_escTitle(r.taskType)}">${r.taskType || "-"}</td>
            <td title="${_escTitle(r.belongingModule)}">${(r.belongingModule != null && r.belongingModule !== "") ? r.belongingModule : "-"}</td>
            <td>${sourceTd}</td>
            <td class="task-link-cell">${linkCellHtml}</td>
            <td>${dueDateHtml}</td>
            <td title="${_escTitle(r.businessSide)}">${(r.businessSide != null && r.businessSide !== "") ? r.businessSide : "-"}</td>
            <td title="${_escTitle(r.product)}">${(r.product != null && r.product !== "") ? r.product : "-"}</td>
            <td title="${_escTitle(r.country)}">${(r.country != null && r.country !== "") ? r.country : "-"}</td>
            <td data-wrap style="max-width:180px" title="${_escTitle(r.notes)}">${_renderNotesHtml(r.notes)}</td>
            <td><input type="text" class="form-control form-control-sm execution-notes-input" placeholder="${execNotesPlaceholder}" data-id="${r.id}" value="${(r.executionNotes != null && r.executionNotes !== "") ? String(r.executionNotes).replace(/"/g, "&quot;") : ""}"></td>
            <td class="completion-status-cell"></td>
            <td title="${_escTitle(r.projectCode)}">${projectCode}</td>
            <td title="${_escTitle(r.fileVersion)}">${fileVersion}</td>
            <td title="${_escTitle(r.documentDisplayDate)}">${documentDisplayDate}</td>
            <td title="${_escTitle(r.reviewer)}">${reviewer}</td>
            <td title="${_escTitle(r.approver)}">${approver}</td>
            <td title="${_escTitle(r.displayedAuthor)}">${(r.displayedAuthor != null && r.displayedAuthor !== "") ? r.displayedAuthor : "-"}</td>
            <td title="${_escTitle(r.projectNotes)}">${projectNotesDisplay}</td>
            <td title="${_escTitle(r.registeredProductName)}">${(r.registeredProductName != null && r.registeredProductName !== "") ? r.registeredProductName : "-"}</td>
            <td title="${_escTitle(r.model)}">${(r.model != null && r.model !== "") ? r.model : "-"}</td>
            <td title="${_escTitle(r.registrationVersion)}">${(r.registrationVersion != null && r.registrationVersion !== "") ? r.registrationVersion : "-"}</td>
            <td class="col-op">
                ${_buildPage2ActionButtonsHtml(r)}
            </td>
        `;
        const statusCell = tr.querySelector(".completion-status-cell");
        const statusSelect = createCompletionStatusSelect(r.completionStatus, r.id);
        statusCell.appendChild(statusSelect);
        statusSelect.addEventListener("change", async () => {
            const linkInput = tr.querySelector(".task-link-input");
            const linkVal = linkInput ? linkInput.value.trim() : "";
            const hasTemplate = r.hasFile || r.hasLinks || !!linkVal;
            const newStatus = statusSelect.value;
            const isCompleted = newStatus && newStatus !== "未完成";
            const isMatterComplete = taskTypeCategoryOf(r.taskType) === TASK_TYPE_CATEGORY_MATTER;
            if (isCompleted && isMatterComplete) {
                const execNotesInput = tr.querySelector(".execution-notes-input");
                const execVal = (execNotesInput?.value || r.executionNotes || "").trim();
                if (!isMeaningfulMatterExecutionNotes(execVal)) {
                    statusSelect.value = r.completionStatus || "";
                    App.notify(
                        execVal ? MATTER_EXEC_NOTES_INVALID_MSG : MATTER_EXEC_NOTES_MSG,
                        "danger"
                    );
                    execNotesInput?.focus();
                    return;
                }
            } else if (isCompleted && !hasTemplate) {
                statusSelect.value = r.completionStatus || "";
                App.notify("请先填写文档链接后再标记完成状态", "danger");
                return;
            }
            if (linkVal && !isValidDocLink(linkVal)) {
                statusSelect.value = r.completionStatus || "";
                App.notify("请填写有效的文档链接（需以 http:// 或 https:// 开头）", "danger");
                return;
            }
            const payload = { completionStatus: newStatus };
            if (linkVal) payload.templateLinks = linkVal;
            if (isCompleted && isMatterComplete) {
                const execNotesInput = tr.querySelector(".execution-notes-input");
                payload.executionNotes = (execNotesInput?.value || r.executionNotes || "").trim();
            }
            try {
                await App.request(`/api/uploads/${r.id}/completion-status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
                App.notify("状态已更新");
                if (payload.executionNotes != null) r.executionNotes = payload.executionNotes;
                if (linkVal) { r.templateLinks = linkVal; r.hasLinks = true; loadMyTasks(); }
            } catch (e) {
                statusSelect.value = r.completionStatus || "";
                App.notify(e.message || "状态更新失败", "danger");
            }
        });
        const linkInput = tr.querySelector(".task-link-input");
        if (linkInput) {
            linkInput.addEventListener("blur", async () => {
                const val = linkInput.value.trim();
                if (!val) return;
                if (!isValidDocLink(val)) {
                    App.notify("请填写有效的文档链接（需以 http:// 或 https:// 开头）", "danger");
                    return;
                }
                try {
                    await App.request(`/api/uploads/${r.id}/completion-status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ templateLinks: val }) });
                    r.templateLinks = val; r.hasLinks = true; App.notify("链接已保存");
                } catch (err) { App.notify(err.message, "danger"); }
            });
        }
        const execNotesInput = tr.querySelector(".execution-notes-input");
        if (execNotesInput) {
            execNotesInput.addEventListener("blur", async () => {
                const val = execNotesInput.value.trim();
                const prev = (r.executionNotes || "").trim();
                if (isMatterRow) {
                    if (!val) {
                        execNotesInput.value = r.executionNotes || "";
                        return;
                    }
                    if (!isMeaningfulMatterExecutionNotes(val)) {
                        execNotesInput.value = r.executionNotes || "";
                        App.notify(MATTER_EXEC_NOTES_INVALID_MSG, "danger");
                        return;
                    }
                }
                if (val === prev) return;
                try {
                    await App.request(`/api/uploads/${r.id}/execution-notes`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ executionNotes: val || null }) });
                    r.executionNotes = val || null;
                    if (val) App.notify("执行任务备注已保存");
                } catch (err) { App.notify(err.message || "保存失败", "danger"); }
            });
        }
        bindPage2TemplateFileUpload(tr, r);
        tr.querySelector(".btn-fill-placeholders")?.addEventListener("click", () => openPlaceholderModal(r, placeholderModal));
        tr.querySelector(".btn-draft-gen-page2")?.addEventListener("click", () => {
            window.location.href = buildDraftGenUrlFromTask(r);
        });
        tr.querySelector(".btn-audit-modify-page2")?.addEventListener("click", () => {
            const url = buildIntegrationUrlFromRecord(r, "/audit-modify/", {
                base_upload_id: r.id,
                template_file_name: r.fileName || "",
            });
            window.open(url, "_blank", "noopener");
        });
        tr.querySelector(".btn-translate-page2")?.addEventListener("click", () => {
            const url = buildIntegrationUrlFromRecord(r, "/translate/", { upload_id: r.id });
            window.open(url, "_blank", "noopener");
        });
        myTasksBody.appendChild(tr);
    };
    
    myTasksBody.innerHTML = "";
    
    if (groupBy === "none") {
        const active = [];
        const ended = [];
        lastRenderedMyTasks.forEach((r) => {
            const st = (r.projectStatus || "").toLowerCase();
            if (st === "ended") ended.push(r);
            else active.push(r);
        });
        let idx = 0;
        active.forEach((r) => addOneRow(r, idx++));
        if (ended.length > 0) {
            const sep = document.createElement("tr");
            sep.className = "bg-light";
            sep.innerHTML = `<td colspan="25"><strong>历史项目</strong>（已结束项目）</td>`;
            myTasksBody.appendChild(sep);
            ended.forEach((r) => addOneRow(r, idx++));
        }
    } else {
        const keyFn = groupBy === "project" ? (r) => r.projectName : (r) => r.author;
        const label = groupBy === "project" ? "项目" : "编写人";
        const groupMap = new Map();
        const groupMeta = new Map(); // key -> {priority, status}
        lastRenderedMyTasks.forEach((r) => {
            const k = keyFn(r) || "";
            if (!groupMap.has(k)) groupMap.set(k, []);
            groupMap.get(k).push(r);
            if (groupBy === "project" && !groupMeta.has(k)) {
                groupMeta.set(k, {
                    priority: Number.isFinite(Number(r.projectPriority)) ? Number(r.projectPriority) : 0,
                    status: (r.projectStatus || "").toLowerCase() || "active",
                });
            }
        });

        const sortedKeys = [...groupMap.keys()].sort((a, b) => {
            if (groupBy !== "project") return String(a || "").localeCompare(String(b || ""), "zh");
            const ma = groupMeta.get(a) || { priority: 0, status: "active" };
            const mb = groupMeta.get(b) || { priority: 0, status: "active" };
            const sa = ma.status === "ended" ? 1 : 0;
            const sb = mb.status === "ended" ? 1 : 0;
            if (sa !== sb) return sa - sb; // active first
            if (ma.priority !== mb.priority) return mb.priority - ma.priority; // high first
            return String(a || "").localeCompare(String(b || ""), "zh");
        });

        const hasEnded = groupBy === "project" && sortedKeys.some((k) => (groupMeta.get(k)?.status || "") === "ended");

        let globalIdx = 0;
        let gidx = 0;
        let historyInserted = false;
        sortedKeys.forEach((key) => {
            const arr = groupMap.get(key) || [];
            const st = (groupMeta.get(key)?.status || "").toLowerCase();
            if (hasEnded && !historyInserted && st === "ended") {
                historyInserted = true;
                const sep = document.createElement("tr");
                sep.className = "bg-light";
                sep.innerHTML = `<td colspan="25"><strong>历史项目</strong>（已结束项目）</td>`;
                myTasksBody.appendChild(sep);
            }
            const collapsed = myTasksCollapsedGroups.has(key);
            const headerTr = document.createElement("tr");
            headerTr.className = "group-header-row bg-light" + (collapsed ? " group-collapsed" : "");
            headerTr.dataset.groupKey = key;
            headerTr.dataset.groupIndex = String(gidx);
            const prLabel = groupBy === "project" ? (arr[0]?.projectPriorityLabel ? `【${arr[0].projectPriorityLabel}】` : "") : "";
            headerTr.innerHTML = `<td colspan="25" style="cursor:pointer"><span class="group-toggle">${collapsed ? "▶" : "▼"}</span> ${label}：${prLabel}${key || "（空）"} (${arr.length}条)</td>`;
            headerTr.style.cursor = "pointer";
            myTasksBody.appendChild(headerTr);
            arr.forEach((r) => { addOneRow(r, globalIdx++, key, gidx, collapsed); });
            gidx++;
        });
        myTasksBody.querySelectorAll(".group-header-row").forEach((headerTr) => {
            headerTr.addEventListener("click", () => {
                const key = headerTr.dataset.groupKey;
                if (myTasksCollapsedGroups.has(key)) myTasksCollapsedGroups.delete(key);
                else myTasksCollapsedGroups.add(key);
                const collapsed = myTasksCollapsedGroups.has(key);
                headerTr.classList.toggle("group-collapsed", collapsed);
                headerTr.querySelector(".group-toggle").textContent = collapsed ? "▶" : "▼";
                myTasksBody.querySelectorAll(`tr.group-data-row[data-group-index="${headerTr.dataset.groupIndex}"]`).forEach((row) => row.classList.toggle("d-none", collapsed));
            });
        });
    }
    
    initDragSort(myTasksBody, async (orders) => {
        try {
            await App.request("/api/uploads/reorder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ orders }),
            });
        } catch (e) {
            App.notify(e.message, "danger");
        }
    });
    scheduleSyncStickyNameColumns(document.getElementById("myTasksTable"));
}

function openPlaceholderModal(record, placeholderModal) {
    const modalTitle = document.getElementById("modalTaskTitle");
    const modalUploadId = document.getElementById("modalUploadId");
    const modalPlaceholderFields = document.getElementById("modalPlaceholderFields");
    const modalNoPlaceholders = document.getElementById("modalNoPlaceholders");
    const modalOutputName = document.getElementById("modalOutputName");
    const modalGenerateBtn = document.getElementById("modalGenerateBtn");

    modalTitle.textContent = `${record.projectName} - ${record.fileName}`;
    modalUploadId.value = record.id;
    modalOutputName.value = "";
    modalPlaceholderFields.innerHTML = "";

    const placeholders = record.placeholders || [];
    if (placeholders.length === 0) {
        modalNoPlaceholders.classList.remove("d-none");
        modalPlaceholderFields.classList.add("d-none");
    } else {
        modalNoPlaceholders.classList.add("d-none");
        modalPlaceholderFields.classList.remove("d-none");
        placeholders.forEach(name => {
            const col = document.createElement("div");
            col.className = "col-md-6";
            col.innerHTML = `
                <label class="form-label">${name}</label>
                <textarea class="form-control modal-placeholder-input" data-placeholder="${name}" rows="2" required></textarea>
            `;
            modalPlaceholderFields.appendChild(col);
        });
    }

    modalGenerateBtn.onclick = async () => {
        const values = {};
        document.querySelectorAll(".modal-placeholder-input").forEach(input => {
            values[input.dataset.placeholder] = input.value.trim();
        });

        try {
            const result = await App.request("/api/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    uploadId: modalUploadId.value,
                    values,
                    outputName: modalOutputName.value.trim() || null,
                }),
            });
            App.notify(result.message || "文档生成成功");
            if (result.downloadUrl) {
                window.open(result.downloadUrl, "_blank");
            }
            bootstrap.Modal.getInstance(placeholderModal)?.hide();
            if (window.loadMyTasks) window.loadMyTasks();
        } catch (error) {
            App.notify(error.message, "danger");
        }
    };

    const modal = new bootstrap.Modal(placeholderModal);
    modal.show();
}

let summaryDataCache = null;
let lastRenderedDetailRows = [];
let detailCollapsedGroups = new Set();
let detailSortKey = "";
let detailSortDir = "asc";

function _escHtmlSysCfg(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/</g, "&lt;");
}

/** 后端未返回 sections 时的前端分区（与 app_settings.SYSTEM_CONFIG_SECTIONS 一致） */
const CLIENT_SYSTEM_CONFIG_SECTIONS = [
    {
        id: "feature_flags",
        title: "功能开关",
        hint: "控制页面2 操作按钮与考试训练中心入口；填 1 开启，留空或 0 关闭。",
        defaultExpanded: true,
        keys: [
            "FEATURE_PAGE2_UPLOAD_REPLACE",
            "FEATURE_PAGE2_DRAFT_GEN",
            "FEATURE_PAGE2_AUDIT_MODIFY",
            "FEATURE_PAGE2_TRANSLATE",
            "FEATURE_EXAM_CENTER",
        ],
    },
    {
        id: "core",
        title: "基础与安全",
        hint: "部署、访问控制与对外地址；修改数据库连接后需重启服务。",
        defaultExpanded: true,
        keys: [
            "DATABASE_URL",
            "SECRET_KEY",
            "BASE_URL",
            "PAGE13_ACCESS_PASSWORD",
            "INTEGRATION_SECRET",
            "UPLOAD_FOLDER",
            "OUTPUT_FOLDER",
            "SCHEDULER_INSTANCE_ID",
        ],
    },
    {
        id: "dingtalk",
        title: "钉钉通知",
        hint: "群机器人与工作通知；敏感项留空表示不修改已有值。",
        defaultExpanded: true,
        keys: [
            "DINGTALK_WEBHOOK",
            "DINGTALK_SECRET",
            "DINGTALK_APP_KEY",
            "DINGTALK_APP_SECRET",
            "DINGTALK_AGENT_ID",
        ],
    },
    {
        id: "exam_center",
        title: "考试训练中心",
        hint: "考试中心后端地址、鉴权与录题/及格线等业务参数。",
        defaultExpanded: false,
        keys: [
            "QUIZ_API_BASE_URL",
            "QUIZ_API_BEARER_TOKEN",
            "QUIZ_API_SECRET",
            "QUIZ_API_TIMEOUT_SECONDS",
            "EXAM_PASS_SCORE",
            "EXAM_INGEST_TARGET_COUNT",
            "EXAM_INGEST_KNOWLEDGE_WEIGHTS",
            "EXAM_INGEST_QUESTION_TYPE_WEIGHTS",
            "EXAM_INGEST_MAX_SIMILAR_FRAC",
        ],
    },
    {
        id: "aicheckword",
        title: "aicheckword 集成",
        hint: "初稿、审核、翻译等对接地址与超时。",
        defaultExpanded: false,
        keys: [
            "AICHECKWORD_DRAFT_API_BASE",
            "AICHECKWORD_DRAFT_TIMEOUT_SECONDS",
            "AICHECKWORD_DRAFT_CONNECT_TIMEOUT_SECONDS",
            "AICHECKWORD_AUDIT_TIMEOUT_SECONDS",
            "AICHECKWORD_TRANSLATION_TIMEOUT_SECONDS",
            "AICHECKWORD_DRAFT_COLLECTION_IDS",
        ],
    },
    {
        id: "aiprintword",
        title: "aiprintword 签字/打印",
        hint: "页面1「去签字/去打印」服务端交接用。",
        defaultExpanded: false,
        keys: ["AIPRINTWORD_BASE_URL", "AIPRINTWORD_HANDOFF_SECRET"],
    },
];

/** 单条系统配置输入框 HTML */
function _renderSystemSettingFieldHtml(k, settings) {
    const raw = settings[k.key] != null ? String(settings[k.key]) : "";
    const showVal = _escHtmlSysCfg(raw);
    const isDb = k.key === "DATABASE_URL";
    const unchanged = raw === "(不变)" || raw === "******";
    const webhookLike = k.key === "DINGTALK_WEBHOOK";
    const typ =
        k.sensitive && !unchanged && raw && !webhookLike
            ? "password"
            : "text";
    let ph = "";
    if (isDb) {
        ph = raw
            ? "当前已连接（脱敏）；修改请填写完整 URI"
            : "填写 MySQL/SQLite 连接串";
    } else if (k.sensitive && !raw) {
        ph = "未配置";
    }
    return `<div class="col-md-6"><label class="form-label small mb-0">${_escHtmlSysCfg(k.label)}</label><input type="${typ}" class="form-control form-control-sm sys-cfg-input" data-key="${k.key}" data-sensitive="${k.sensitive ? "1" : "0"}" value="${showVal}" placeholder="${_escHtmlSysCfg(ph)}" autocomplete="off"></div>`;
}

/** 按后端 sections 分区渲染；无 sections 时回退为平铺列表 */
function _renderSystemSettingsFormHtml(keys, settings, sections) {
    const keyMap = Object.fromEntries((keys || []).map((k) => [k.key, k]));
    const esc = _escHtmlSysCfg;
    const secs =
        Array.isArray(sections) && sections.length ? sections : CLIENT_SYSTEM_CONFIG_SECTIONS;
    const intro =
        '<p class="small text-muted mb-2 sys-cfg-form-intro">以下按分区折叠展示，点击分区标题可展开或收起；带「项数」标签的为配置分组。</p>';
    if (secs && secs.length) {
        return (
            intro +
            secs
            .map((sec) => {
                const fieldKeys = sec.keys || [];
                const fields = fieldKeys.map((name) => keyMap[name]).filter(Boolean);
                if (!fields.length) return "";
                const openAttr = sec.defaultExpanded ? " open" : "";
                const hintHtml = sec.hint
                    ? `<p class="sys-cfg-section-hint small text-muted mb-2">${esc(sec.hint)}</p>`
                    : "";
                const fieldsHtml = fields
                    .map((k) => _renderSystemSettingFieldHtml(k, settings))
                    .join("");
                return `<details class="sys-cfg-section"${openAttr} data-section-id="${esc(sec.id || "")}">
<summary class="sys-cfg-section-summary">
<span class="sys-cfg-section-title">${esc(sec.title || "未命名")}</span>
<span class="sys-cfg-section-count">${fields.length} 项</span>
</summary>
${hintHtml}
<div class="row g-2 sys-cfg-section-fields">${fieldsHtml}</div>
</details>`;
            })
            .join("")
        );
    }
    return `<div class="row g-2">${(keys || [])
        .map((k) => _renderSystemSettingFieldHtml(k, settings))
        .join("")}</div>`;
}

function initDashboardPage() {
    const loadSystemSettings = async () => {
        const container = document.getElementById("systemSettingsForm");
        if (!container) return;
        try {
            const res = await App.request("/api/system-settings");
            const keys = res.keys || [];
            const settings = res.settings || {};
            const sections = res.sections || [];
            if (!keys.length) {
                container.innerHTML =
                    '<div class="alert alert-warning mb-0 small">未获取到配置项列表，请刷新页面。</div>';
                return;
            }
            container.innerHTML = _renderSystemSettingsFormHtml(keys, settings, sections);
        } catch (e) {
            console.error(e);
            const escE = (s) =>
                String(s)
                    .replace(/&/g, "&amp;")
                    .replace(/"/g, "&quot;")
                    .replace(/</g, "&lt;");
            container.innerHTML = `<div class="alert alert-danger mb-0 small">系统配置加载失败：${escE(
                (e && e.message) || String(e)
            )}。若提示需要访问密码，请先完成页面验证后再试。</div>`;
        }
    };

    // 系统配置弹窗：默认不展开，点击按钮后再拉取并渲染
    const systemModal = document.getElementById("systemSettingsModal");
    const openSystemSettingsBtn = document.getElementById("openSystemSettingsBtn");
    const closeSystemSettingsBtn = document.getElementById("closeSystemSettingsBtn");
    let systemSettingsLoaded = false;

    const showSystemModal = () => {
        if (!systemModal) return;
        systemModal.classList.add("show");
        systemModal.setAttribute("aria-hidden", "false");
        // 兼容：同时设置内联样式，确保弹窗一定可见
        systemModal.style.display = "block";
        systemModal.style.position = "fixed";
        systemModal.style.left = "0";
        systemModal.style.top = "0";
        systemModal.style.right = "0";
        systemModal.style.bottom = "0";
        systemModal.style.zIndex = "2000";
        document.body.style.overflow = "hidden";
    };

    const hideSystemModal = () => {
        if (!systemModal) return;
        systemModal.classList.remove("show");
        systemModal.setAttribute("aria-hidden", "true");
        systemModal.style.display = "none";
        systemModal.style.position = "";
        systemModal.style.zIndex = "";
        document.body.style.overflow = "";
    };

    if (openSystemSettingsBtn) {
        openSystemSettingsBtn.addEventListener("click", async () => {
            showSystemModal();
            if (!systemSettingsLoaded) {
                const container = document.getElementById("systemSettingsForm");
                if (container) {
                    container.innerHTML =
                        '<div class="alert alert-info mb-0 small">加载中…</div>';
                }
                try {
                    await loadSystemSettings();
                    systemSettingsLoaded = true;
                } catch (_) {
                    // ignore；loadSystemSettings 内部已做提示
                }
            }
        });
        if (systemModal) {
            closeSystemSettingsBtn?.addEventListener("click", hideSystemModal);
            systemModal.addEventListener("click", (e) => {
                if (e.target && e.target.getAttribute && e.target.getAttribute("data-close") === "1") {
                    hideSystemModal();
                }
            });
            window.addEventListener("keydown", (e) => {
                if (e.key === "Escape") hideSystemModal();
            });
        }
    } else {
        // 兼容：若页面尚未包含“打开按钮”，则回退到原先“默认加载”
        loadSystemSettings();
        systemSettingsLoaded = true;
    }

    document.getElementById("saveSystemSettingsBtn")?.addEventListener("click", async () => {
        const container = document.getElementById("systemSettingsForm");
        const saveBtn = document.getElementById("saveSystemSettingsBtn");
        if (!container) return;
        const payload = {};
        container.querySelectorAll(".sys-cfg-input").forEach((inp) => {
            const key = inp.getAttribute("data-key");
            const sens = inp.getAttribute("data-sensitive") === "1";
            const v = (inp.value || "").trim();
            if (key === "DATABASE_URL") {
                if (v && !v.includes("****")) payload[key] = v;
                return;
            }
            if (sens) {
                if (v && v !== "(不变)" && v !== "******") payload[key] = v;
            } else {
                payload[key] = v;
            }
        });
        try {
            _setButtonBusy(saveBtn, true, "保存中…");
            await App.request("/api/system-settings", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                timeoutMs: 60000,
            });
            App.notify("系统配置已保存", "success");
            await loadSystemSettings();
            if (typeof window.__dashboardReloadSchedule === "function") {
                window.__dashboardReloadSchedule();
            }
        } catch (e) {
            App.notify((e.data && e.data.message) || e.message || "保存失败", "danger");
        } finally {
            _setButtonBusy(saveBtn, false);
        }
    });
    // 默认不加载：等用户点击打开弹窗后拉取

    const overallRate = document.getElementById("overallRate");
    if (!overallRate) return;

    const tableBody = document.getElementById("detailTableBody");
    const projectBody = document.getElementById("projectStatsBody");
    const authorBody = document.getElementById("authorStatsBody");
    const projectAuthorBody = document.getElementById("projectAuthorStatsBody");
    const scheduleInfo = document.getElementById("scheduleInfo");

    const formatRate = (rate) => `${(rate * 100).toFixed(2)}%`;
    
    const formatStatusBadges = (byStatus) => {
        if (!byStatus || byStatus.length === 0) return "-";
        return byStatus.map(s => 
            `<span class="badge ${s.status === '未完成' ? 'bg-secondary' : 'bg-info text-dark'} me-1">${s.status}: ${s.count}</span>`
        ).join("");
    };

    const loadSchedule = async () => {
        try {
            const [result, configResult] = await Promise.all([
                App.request("/api/notify/next-schedule"),
                App.request("/api/notify/schedule-config").catch(() => null),
            ]);
            if (configResult) {
                const w = document.getElementById("scheduleWeekly");
                const o = document.getElementById("scheduleOverdue");
                const p = document.getElementById("scheduleProject");
                const mcDelay = document.getElementById("scheduleModuleCascadeDelay");
                if (w) w.value = configResult.weekly || "";
                if (o) o.value = configResult.overdue || "";
                if (p) p.value = configResult.project || "";
                if (mcDelay) mcDelay.value = configResult.moduleCascadeDelayMinutes != null ? configResult.moduleCascadeDelayMinutes : 5;
            }
            loadModuleCascadeStatus();
            if (scheduleInfo) {
                scheduleInfo.innerHTML = "";
                
                const configured = result.dingtalkConfigured;
                const statusDiv = document.createElement("div");
                statusDiv.className = `p-2 border rounded ${configured ? 'bg-success-subtle border-success' : 'bg-warning-subtle border-warning'}`;
                statusDiv.innerHTML = `
                    <div class="fw-bold small">${configured ? '✓ 钉钉已配置' : '⚠ 钉钉未配置'}</div>
                    <div class="text-muted small">${configured ? '可正常发送通知' : '请在弹窗「系统配置」填写钉钉 Webhook'}</div>
                `;
                scheduleInfo.appendChild(statusDiv);
                
                for (const [key, info] of Object.entries(result)) {
                    if (key === "dingtalkConfigured") continue;
                    const div = document.createElement("div");
                    div.className = "p-2 border rounded bg-light";
                    div.innerHTML = `
                        <div class="fw-bold small">${info.description}</div>
                        <div class="text-muted small">${info.nextTime}</div>
                        <div class="text-muted small">${info.cron}</div>
                    `;
                    scheduleInfo.appendChild(div);
                }
            }
        } catch (e) {
            console.error(e);
        }
    };
    window.__dashboardReloadSchedule = loadSchedule;

    document.getElementById("saveScheduleConfigBtn")?.addEventListener("click", async () => {
        const weekly = (document.getElementById("scheduleWeekly")?.value || "").trim() || "thu 16:00";
        const overdue = (document.getElementById("scheduleOverdue")?.value || "").trim() || "15:00";
        const project = (document.getElementById("scheduleProject")?.value || "").trim() || "mon,wed,fri 9:30";
        const delayEl = document.getElementById("scheduleModuleCascadeDelay");
        const moduleCascadeDelayMinutes = delayEl ? Math.max(1, Math.min(1440, parseInt(delayEl.value, 10) || 5)) : 5;
        try {
            await App.request("/api/notify/schedule-config", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ weekly, overdue, project, moduleCascadeDelayMinutes }),
            });
            App.notify("已保存，定时任务已更新", "success");
            loadSchedule();
        } catch (e) {
            const data = e.data || {};
            App.notify(data.message || e.message || "保存失败", "danger");
        }
    });

    const testAutoNotify = async (type) => {
        try {
            const result = await App.request("/api/notify/test-auto", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(type ? { type } : {}),
            });
            const ok = result && result.success === true;
            App.notify(result?.message || (ok ? "测试发送成功" : "发送失败"), ok ? "success" : "danger");
        } catch (e) {
            const data = e.data || {};
            App.notify(data.message || e.message || "测试失败", "danger");
        }
    };
    document.getElementById("testAutoNotifyThu")?.addEventListener("click", () => testAutoNotify("thursday"));
    document.getElementById("testAutoNotifyOverdue")?.addEventListener("click", () => testAutoNotify("overdue"));
    document.getElementById("testAutoNotifyProject")?.addEventListener("click", () => testAutoNotify("project_stats"));
    const loadModuleCascadeStatus = async () => {
        const container = document.getElementById("moduleCascadeStatusContainer");
        if (!container) return;
        try {
            const res = await App.request("/api/notify/module-cascade-status");
            const delay = res.delayMinutes != null ? res.delayMinutes : 5;
            const pending = res.pending || [];
            const recentSent = res.recentSent || [];
            // “已执行”最多展示最近 3 条，避免记录数量过多影响页面阅读
            const recentSentDisplay = recentSent.slice(0, 3);
            let html = `<div class="small mb-2">延迟 <strong>${delay}</strong> 分钟</div>`;
            html += '<div class="mb-2"><span class="fw-bold small">待执行</span>';
            if (pending.length === 0) {
                html += '<span class="text-muted small ms-2">暂无</span>';
            } else {
                html += '<ul class="list-unstyled small mb-0 mt-1">';
                pending.forEach(p => {
                    html += `<li>${(p.projectName || "-").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}：${p.triggerModule || ""}→${p.targetModule || ""}，计划 ${p.runAt || "-"}</li>`;
                });
                html += '</ul>';
            }
            html += '</div><div><span class="fw-bold small">已执行（最近）</span>';
            if (recentSentDisplay.length === 0) {
                html += '<span class="text-muted small ms-2">暂无</span>';
            } else {
                html += '<ul class="list-unstyled small mb-0 mt-1">';
                recentSentDisplay.forEach(s => {
                    html += `<li>${(s.projectName || "-").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}：${s.triggerModule || ""}→${s.targetModule || ""}，${s.sentAt || "-"}</li>`;
                });
                html += '</ul>';
            }
            html += '</div>';
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = '<div class="small text-danger">加载失败</div>';
        }
    };
    document.getElementById("testAutoNotifyModuleCascade")?.addEventListener("click", async () => {
        await testAutoNotify("module_cascade");
        loadModuleCascadeStatus();
    });

    const loadSummary = async () => {
        try {
            const result = await App.request("/api/summary");
            summaryDataCache = result;
            
            const overall = result.overall || { completed: 0, total: 0, rate: 0, pending: 0 };
            overallRate.textContent = formatRate(overall.rate);
            document.getElementById("overallNumbers").textContent = `${overall.completed} / ${overall.total}`;
            
            renderProjectStats(result.byProject || []);
            renderAuthorStats(result.byAuthor || []);
            renderProjectAuthorStats(result.byProjectAuthor || []);
            renderDetailTable(result.detail || []);
            
        } catch (error) {
            App.notify(error.message, "danger");
        }
    };

    const renderProjectStats = (rows) => {
        projectBody.innerHTML = "";
        rows.forEach((row, idx) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${idx + 1}</td>
                <td>${row.label}</td>
                <td class="text-success">${row.completed}</td>
                <td class="${row.pending > 0 ? 'text-danger' : ''}">${row.pending}</td>
                <td>${formatRate(row.rate)}</td>
                <td>${formatStatusBadges(row.byStatus)}</td>
                <td>
                    <button class="btn btn-sm btn-outline-warning btn-notify-project" data-project="${row.label}" ${row.pending === 0 ? 'disabled' : ''}>
                        催办
                    </button>
                </td>
            `;
            projectBody.appendChild(tr);
        });
        
        projectBody.querySelectorAll(".btn-notify-project").forEach(btn => {
            btn.addEventListener("click", async () => {
                const projectName = btn.dataset.project;
                if (!confirm(`确定要向 "${projectName}" 项目未完成人员发送钉钉通知吗？`)) return;
                try {
                    const result = await App.request("/api/notify/by-project", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ projectName }),
                    });
                    const ok = result && result.success === true;
                    App.notify(ok ? (result.message || "通知发送成功") : (result.message || "通知发送失败"), ok ? "success" : "danger");
                } catch (e) {
                    App.notify(e.message, "danger");
                }
            });
        });
    };
    
    const renderAuthorStats = (rows) => {
        authorBody.innerHTML = "";
        rows.forEach((row, idx) => {
            const auditCount = row.auditRejectCount != null ? row.auditRejectCount : 0;
            const auditCellClass = auditCount > 2 ? "text-danger" : "";
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${idx + 1}</td>
                <td>${row.label}</td>
                <td class="text-success">${row.completed}</td>
                <td class="${row.pending > 0 ? 'text-danger' : ''}">${row.pending}</td>
                <td>${formatRate(row.rate)}</td>
                <td>${formatStatusBadges(row.byStatus)}</td>
                <td class="${auditCellClass}">${auditCount}</td>
                <td>
                    <button class="btn btn-sm btn-outline-warning btn-notify-author" data-author="${row.label}" ${row.pending === 0 ? 'disabled' : ''}>
                        催办
                    </button>
                </td>
            `;
            authorBody.appendChild(tr);
        });
        
        authorBody.querySelectorAll(".btn-notify-author").forEach(btn => {
            btn.addEventListener("click", async () => {
                const author = btn.dataset.author;
                if (!confirm(`确定要向 "${author}" 发送钉钉通知吗？`)) return;
                try {
                    const result = await App.request("/api/notify/by-author", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ author }),
                    });
                    const ok = result && result.success === true;
                    App.notify(ok ? (result.message || "通知发送成功") : (result.message || "通知发送失败"), ok ? "success" : "danger");
                } catch (e) {
                    App.notify(e.message, "danger");
                }
            });
        });
    };
    
    const renderProjectAuthorStats = (rows) => {
        projectAuthorBody.innerHTML = "";
        rows.forEach((row, idx) => {
            const tr = document.createElement("tr");
            const projectName = (row.projectName != null && row.projectName !== "") ? row.projectName : "";
            const author = (row.author != null && row.author !== "") ? row.author : "";
            const esc = (s) => String(s || "").replace(/"/g, "&quot;");
            tr.innerHTML = `
                <td>${idx + 1}</td>
                <td>${row.label}</td>
                <td class="text-success">${row.completed}</td>
                <td class="${row.pending > 0 ? 'text-danger' : ''}">${row.pending}</td>
                <td>${formatRate(row.rate)}</td>
                <td>${formatStatusBadges(row.byStatus)}</td>
                <td class="text-nowrap">
                    <button type="button" class="btn btn-sm btn-outline-warning btn-notify-project-author me-1"
                        data-project="${esc(projectName)}" data-author="${esc(author)}"
                        ${row.pending === 0 ? "disabled" : ""} title="仅催办该项目下该编写人员的未完成任务">催办</button>
                    <button type="button" class="btn btn-sm btn-outline-secondary btn-module-cascade"
                        data-project="${esc(projectName)}" title="该项目：产品全部完成→催办开发；开发全部完成→催办测试">级联</button>
                </td>
            `;
            projectAuthorBody.appendChild(tr);
        });
        bindProjectAuthorStatsActions(projectAuthorBody);
    };
    
    const renderDetailTable = (rows) => {
        lastRenderedDetailRows = rows || [];
        tableBody.innerHTML = "";
        const groupBy = (document.querySelector('input[name="detailGroupBy"]:checked') || {}).value || "none";
        
        const addDetailRow = (row, groupKey, groupIndex, collapsed, twoLevelKeys) => {
            const tr = document.createElement("tr");
            tr.dataset.id = row.uploadId;
            if (groupKey !== undefined) {
                tr.classList.add("group-data-row");
                tr.dataset.groupKey = groupKey;
                tr.dataset.groupIndex = String(groupIndex);
                if (twoLevelKeys) {
                    tr.dataset.groupKey1 = twoLevelKeys.key1;
                    tr.dataset.groupKey2 = twoLevelKeys.key2;
                }
                if (collapsed) tr.classList.add("d-none");
            }
            const statusHtml = row.completionStatus ? `<span class="badge bg-success">${row.completionStatus}</span>` : '<span class="badge bg-secondary">未完成</span>';
            const dueDateStyle = getDueDateStyle(row.dueDate);
            const dueDateHtml = dueDateStyle.class ? `<span class="badge ${dueDateStyle.class}" title="${dueDateStyle.title || ''}">${dueDateStyle.text}</span>` : (dueDateStyle.text || "-");
            const projectCode = (row.projectCode != null && row.projectCode !== "") ? row.projectCode : "-";
            const fileVersion = (row.fileVersion != null && row.fileVersion !== "") ? row.fileVersion : "-";
            const documentDisplayDate = (row.documentDisplayDate != null && row.documentDisplayDate !== "") ? row.documentDisplayDate : "-";
            const reviewer = (row.reviewer != null && row.reviewer !== "") ? row.reviewer : "-";
            const approver = (row.approver != null && row.approver !== "") ? row.approver : "-";
            tr.innerHTML = `
                <td class="col-drag seq-cell"><span class="drag-handle" draggable="true" title="拖动排序">⋮⋮</span>${row.seq}</td>
                <td title="${_escTitle(row.projectName)}">${row.projectName}</td>
                <td title="${_escTitle(row.fileName)}">${row.fileName}</td>
                <td title="${_escTitle(row.taskType)}">${row.taskType || "-"}</td>
                <td title="${_escTitle(row.belongingModule)}">${(row.belongingModule != null && row.belongingModule !== "") ? row.belongingModule : "-"}</td>
                <td title="${_escTitle(row.author)}">${row.author}</td>
                <td>${statusHtml}</td>
                <td>${dueDateHtml}</td>
                <td title="${_escTitle(row.businessSide)}">${(row.businessSide != null && row.businessSide !== "") ? row.businessSide : "-"}</td>
                <td title="${_escTitle(row.product)}">${(row.product != null && row.product !== "") ? row.product : "-"}</td>
                <td title="${_escTitle(row.country)}">${(row.country != null && row.country !== "") ? row.country : "-"}</td>
                <td data-wrap style="max-width:180px" title="${_escTitle(row.notes)}">${_renderNotesHtml(row.notes)}</td>
                <td title="${_escTitle(row.executionNotes)}">${(row.executionNotes != null && row.executionNotes !== "") ? row.executionNotes : "-"}</td>
                <td>${row.docLink ? `<a href="${row.docLink}" target="_blank" rel="noopener">打开</a>` : "-"}</td>
                <td title="${_escTitle(row.projectCode)}">${projectCode}</td>
                <td title="${_escTitle(row.fileVersion)}">${fileVersion}</td>
                <td title="${_escTitle(row.documentDisplayDate)}">${documentDisplayDate}</td>
                <td title="${_escTitle(row.reviewer)}">${reviewer}</td>
                <td title="${_escTitle(row.approver)}">${approver}</td>
                <td title="${_escTitle(row.displayedAuthor)}">${(row.displayedAuthor != null && row.displayedAuthor !== "") ? row.displayedAuthor : "-"}</td>
                <td title="${_escTitle(row.projectNotes)}">${(row.projectNotes != null && row.projectNotes !== "") ? row.projectNotes : "-"}</td>
                <td title="${_escTitle(row.registeredProductName)}">${(row.registeredProductName != null && row.registeredProductName !== "") ? row.registeredProductName : "-"}</td>
                <td title="${_escTitle(row.model)}">${(row.model != null && row.model !== "") ? row.model : "-"}</td>
                <td title="${_escTitle(row.registrationVersion)}">${(row.registrationVersion != null && row.registrationVersion !== "") ? row.registrationVersion : "-"}</td>
                <td class="col-op">
                    ${!row.isCompleted ? `<button class="btn btn-sm btn-outline-warning btn-notify-single" data-id="${row.uploadId}">催办</button>` : ''}
                </td>
            `;
            tableBody.appendChild(tr);
        };

        if (groupBy === "none") {
            lastRenderedDetailRows.forEach((row) => addDetailRow(row));
        } else if (groupBy === "project_author") {
            const projectMap = new Map();
            lastRenderedDetailRows.forEach((row) => {
                const p = row.projectName ?? "";
                const a = row.author ?? "";
                if (!projectMap.has(p)) projectMap.set(p, new Map());
                const authorMap = projectMap.get(p);
                if (!authorMap.has(a)) authorMap.set(a, []);
                authorMap.get(a).push(row);
            });
            let groupIndexL1 = 0;
            let groupIndexL2 = 0;
            projectMap.forEach((authorMap, projectName) => {
                const key1 = "project:" + projectName;
                const totalProject = [...authorMap.values()].reduce((s, arr) => s + arr.length, 0);
                const collapsed1 = detailCollapsedGroups.has(key1);
                const header1 = document.createElement("tr");
                header1.className = "group-header-row group-header-level1 bg-light" + (collapsed1 ? " group-collapsed" : "");
                header1.dataset.groupKey = key1;
                header1.dataset.groupLevel = "1";
                header1.dataset.groupIndex = String(groupIndexL1++);
                header1.innerHTML = "<td colspan=\"24\" style=\"cursor:pointer\"><span class=\"group-toggle\">" + (collapsed1 ? "▶" : "▼") + "</span> 项目：" + (projectName || "（空）") + " (" + totalProject + "条)</td>";
                header1.style.cursor = "pointer";
                tableBody.appendChild(header1);
                authorMap.forEach((arr, authorName) => {
                    const key2 = key1 + "|author:" + authorName;
                    const collapsed2 = detailCollapsedGroups.has(key2);
                    const header2 = document.createElement("tr");
                    header2.className = "group-header-row group-header-level2 bg-light" + (collapsed2 ? " group-collapsed" : "");
                    header2.dataset.groupKey = key2;
                    header2.dataset.groupLevel = "2";
                    header2.dataset.groupIndex = String(groupIndexL2);
                    header2.innerHTML = "<td colspan=\"24\" style=\"cursor:pointer\" class=\"ps-4\"><span class=\"group-toggle\">" + (collapsed2 ? "▶" : "▼") + "</span> 编写人：" + (authorName || "（空）") + " (" + arr.length + "条)</td>";
                    header2.style.cursor = "pointer";
                    tableBody.appendChild(header2);
                    const rowHidden = collapsed1 || collapsed2;
                    arr.forEach((row) => addDetailRow(row, key2, groupIndexL2, rowHidden, { key1, key2 }));
                    groupIndexL2++;
                });
            });
            tableBody.querySelectorAll(".group-header-row").forEach((headerTr) => {
                headerTr.addEventListener("click", () => {
                    const key = headerTr.dataset.groupKey;
                    const level = headerTr.dataset.groupLevel;
                    if (detailCollapsedGroups.has(key)) detailCollapsedGroups.delete(key);
                    else detailCollapsedGroups.add(key);
                    const collapsed = detailCollapsedGroups.has(key);
                    headerTr.classList.toggle("group-collapsed", collapsed);
                    headerTr.querySelector(".group-toggle").textContent = collapsed ? "▶" : "▼";
                    if (level === "1") {
                        tableBody.querySelectorAll("tr.group-data-row[data-group-key1]").forEach((row) => {
                            if (row.dataset.groupKey1 !== key) return;
                            const key2 = row.dataset.groupKey2;
                            const collapsed2 = detailCollapsedGroups.has(key2);
                            row.classList.toggle("d-none", collapsed || collapsed2);
                        });
                    } else {
                        tableBody.querySelectorAll("tr.group-data-row[data-group-key2]").forEach((row) => {
                            if (row.dataset.groupKey2 !== key) return;
                            const key1 = row.dataset.groupKey1;
                            const collapsed1 = detailCollapsedGroups.has(key1);
                            row.classList.toggle("d-none", collapsed || collapsed1);
                        });
                    }
                });
            });
        } else {
            const keyFn = groupBy === "project" ? (row) => row.projectName : (row) => row.author;
            const label = groupBy === "project" ? "项目" : "编写人";
            const groupMap = new Map();
            lastRenderedDetailRows.forEach((row) => {
                const k = keyFn(row) || "";
                if (!groupMap.has(k)) groupMap.set(k, []);
                groupMap.get(k).push(row);
            });
            let gidx = 0;
            groupMap.forEach((arr, key) => {
                const collapsed = detailCollapsedGroups.has(key);
                const headerTr = document.createElement("tr");
                headerTr.className = "group-header-row bg-light" + (collapsed ? " group-collapsed" : "");
                headerTr.dataset.groupKey = key;
                headerTr.dataset.groupIndex = String(gidx);
                headerTr.innerHTML = `<td colspan="24" style="cursor:pointer"><span class="group-toggle">${collapsed ? "▶" : "▼"}</span> ${label}：${key || "（空）"} (${arr.length}条)</td>`;
                headerTr.style.cursor = "pointer";
                tableBody.appendChild(headerTr);
                arr.forEach((row) => addDetailRow(row, key, gidx, collapsed));
                gidx++;
            });
            tableBody.querySelectorAll(".group-header-row").forEach((headerTr) => {
                headerTr.addEventListener("click", () => {
                    const key = headerTr.dataset.groupKey;
                    if (detailCollapsedGroups.has(key)) detailCollapsedGroups.delete(key);
                    else detailCollapsedGroups.add(key);
                    const collapsed = detailCollapsedGroups.has(key);
                    headerTr.classList.toggle("group-collapsed", collapsed);
                    headerTr.querySelector(".group-toggle").textContent = collapsed ? "▶" : "▼";
                    tableBody.querySelectorAll(`tr.group-data-row[data-group-index="${headerTr.dataset.groupIndex}"]`).forEach((row) => row.classList.toggle("d-none", collapsed));
                });
            });
        }
        
        tableBody.querySelectorAll(".btn-notify-single").forEach(btn => {
            btn.addEventListener("click", async () => {
                if (!confirm("确定要发送钉钉通知吗？")) return;
                try {
                    const result = await App.request("/api/notify/single-task", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ uploadId: btn.dataset.id }),
                    });
                    const ok = result && result.success === true;
                    App.notify(ok ? (result.message || "通知发送成功") : (result.message || "通知发送失败"), ok ? "success" : "danger");
                } catch (e) {
                    App.notify(e.message, "danger");
                }
            });
        });
        
        initDragSort(tableBody, async (orders) => {
            try {
                await App.request("/api/uploads/reorder", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ orders }),
                });
                loadSummary();
            } catch (e) {
                App.notify(e.message, "danger");
            }
        });
    };

    window.reRenderDetailTable = () => {
        renderDetailTable(sortRows(lastRenderedDetailRows, detailSortKey, detailSortDir));
    };
    window.reRenderDetailTableFromRows = (rows) => {
        lastRenderedDetailRows = rows || [];
        renderDetailTable(lastRenderedDetailRows);
    };

    function initDetailTableSort() {
        const table = document.getElementById("detailTable");
        if (!table) return;
        table.querySelectorAll("thead .th-sortable").forEach((th) => {
            th.addEventListener("click", () => {
                const key = th.dataset.sortKey;
                if (!key) return;
                if (detailSortKey === key) detailSortDir = detailSortDir === "asc" ? "desc" : "asc";
                else { detailSortKey = key; detailSortDir = "asc"; }
                table.querySelectorAll("thead .sort-indicator").forEach((s) => { s.textContent = ""; });
                const ind = th.querySelector(".sort-indicator");
                if (ind) ind.textContent = detailSortDir === "asc" ? "↑" : "↓";
                window.reRenderDetailTable();
            });
        });
    }

    initDetailTableSort();
    document.querySelectorAll('input[name="detailGroupBy"]').forEach((radio) => {
        radio.addEventListener("change", () => { window.reRenderDetailTable(); });
    });
    initDashboardFilters(loadSummary);
    initNotifyTemplateModal();
    
    loadSchedule();
    loadSummary();
    window.loadSummary = loadSummary;
    
    document.getElementById("refreshScheduleBtn")?.addEventListener("click", loadSchedule);
}

function initDashboardFilters(reloadFn) {
    const filterProject = document.getElementById("filterProject");
    const filterAuthor = document.getElementById("filterAuthor");
    const filterProjectAuthor = document.getElementById("filterProjectAuthor");
    const filterDetailProject = document.getElementById("filterDetailProject");
    const filterDetailFile = document.getElementById("filterDetailFile");
    const filterDetailAuthor = document.getElementById("filterDetailAuthor");
    const filterDetailStatus = document.getElementById("filterDetailStatus");
    
    completionStatusesCache.forEach(s => {
        const opt = document.createElement("option");
        opt.value = s.name;
        opt.textContent = s.name;
        filterDetailStatus?.appendChild(opt);
    });
    
    const applyProjectFilter = () => {
        if (!summaryDataCache) return;
        const val = filterProject?.value.toLowerCase() || "";
        const filtered = (summaryDataCache.byProject || []).filter(r => 
            !val || r.label.toLowerCase().includes(val)
        );
        renderFilteredStats(document.getElementById("projectStatsBody"), filtered, "project");
    };
    
    const applyAuthorFilter = () => {
        if (!summaryDataCache) return;
        const val = filterAuthor?.value.toLowerCase() || "";
        const filtered = (summaryDataCache.byAuthor || []).filter(r => 
            !val || r.label.toLowerCase().includes(val)
        );
        renderFilteredStats(document.getElementById("authorStatsBody"), filtered, "author");
    };
    
    const applyProjectAuthorFilter = () => {
        if (!summaryDataCache) return;
        const val = filterProjectAuthor?.value.toLowerCase() || "";
        const filtered = (summaryDataCache.byProjectAuthor || []).filter(r => 
            !val || r.label.toLowerCase().includes(val)
        );
        renderFilteredStats(document.getElementById("projectAuthorStatsBody"), filtered, "projectAuthor");
    };
    
    const applyDetailFilter = () => {
        if (!summaryDataCache) return;
        const projectVal = filterDetailProject?.value.toLowerCase() || "";
        const fileVal = filterDetailFile?.value.toLowerCase() || "";
        const authorVal = filterDetailAuthor?.value.toLowerCase() || "";
        const statusVal = filterDetailStatus?.value || "";
        
        const filtered = (summaryDataCache.detail || []).filter(r => {
            if (projectVal && !r.projectName.toLowerCase().includes(projectVal)) return false;
            if (fileVal && !r.fileName.toLowerCase().includes(fileVal)) return false;
            if (authorVal && !r.author.toLowerCase().includes(authorVal)) return false;
            if (statusVal === "未完成" && r.completionStatus) return false;
            if (statusVal && statusVal !== "未完成" && r.completionStatus !== statusVal) return false;
            return true;
        });
        
        renderFilteredDetailTable(filtered);
    };
    
    filterProject?.addEventListener("input", applyProjectFilter);
    filterAuthor?.addEventListener("input", applyAuthorFilter);
    filterProjectAuthor?.addEventListener("input", applyProjectAuthorFilter);
    [filterDetailProject, filterDetailFile, filterDetailAuthor, filterDetailStatus].forEach(el => {
        el?.addEventListener("input", applyDetailFilter);
        el?.addEventListener("change", applyDetailFilter);
    });
}

function renderFilteredStats(tbody, rows, type) {
    if (!tbody) return;
    const formatRate = (rate) => `${(rate * 100).toFixed(2)}%`;
    const formatStatusBadges = (byStatus) => {
        if (!byStatus || byStatus.length === 0) return "-";
        return byStatus.map(s => 
            `<span class="badge ${s.status === '未完成' ? 'bg-secondary' : 'bg-info text-dark'} me-1">${s.status}: ${s.count}</span>`
        ).join("");
    };
    
    tbody.innerHTML = "";
    rows.forEach((row, idx) => {
        const tr = document.createElement("tr");
        let actionHtml = "";
        if (type === "project") {
            actionHtml = `<td><button class="btn btn-sm btn-outline-warning btn-notify-project" data-project="${row.label}" ${row.pending === 0 ? 'disabled' : ''}>催办</button></td>`;
        } else if (type === "author") {
            const auditCount = row.auditRejectCount != null ? row.auditRejectCount : 0;
            const auditCellClass = auditCount > 2 ? "text-danger" : "";
            actionHtml = `<td class="${auditCellClass}">${auditCount}</td><td><button class="btn btn-sm btn-outline-warning btn-notify-author" data-author="${row.label}" ${row.pending === 0 ? 'disabled' : ''}>催办</button></td>`;
        } else if (type === "projectAuthor") {
            const pn = (row.projectName != null && row.projectName !== "") ? String(row.projectName).replace(/"/g, "&quot;") : "";
            const au = (row.author != null && row.author !== "") ? String(row.author).replace(/"/g, "&quot;") : "";
            actionHtml = `<td class="text-nowrap">
                <button type="button" class="btn btn-sm btn-outline-warning btn-notify-project-author me-1"
                    data-project="${pn}" data-author="${au}" ${row.pending === 0 ? "disabled" : ""}
                    title="仅催办该项目下该编写人员的未完成任务">催办</button>
                <button type="button" class="btn btn-sm btn-outline-secondary btn-module-cascade" data-project="${pn}"
                    title="该项目：产品全部完成→催办开发；开发全部完成→催办测试">级联</button>
            </td>`;
        }
        
        tr.innerHTML = `
            <td>${idx + 1}</td>
            <td>${row.label}</td>
            <td class="text-success">${row.completed}</td>
            <td class="${row.pending > 0 ? 'text-danger' : ''}">${row.pending}</td>
            <td>${formatRate(row.rate)}</td>
            <td>${formatStatusBadges(row.byStatus)}</td>
            ${actionHtml}
        `;
        tbody.appendChild(tr);
    });
    
    if (type === "project") {
        tbody.querySelectorAll(".btn-notify-project").forEach(btn => {
            btn.addEventListener("click", async () => {
                const projectName = btn.dataset.project;
                if (!confirm(`确定要向 "${projectName}" 项目未完成人员发送钉钉通知吗？`)) return;
                try {
                    const result = await App.request("/api/notify/by-project", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ projectName }),
                    });
                    const ok = result && result.success === true;
                    App.notify(ok ? (result.message || "通知发送成功") : (result.message || "通知发送失败"), ok ? "success" : "danger");
                } catch (e) {
                    App.notify(e.message, "danger");
                }
            });
        });
    } else if (type === "author") {
        tbody.querySelectorAll(".btn-notify-author").forEach(btn => {
            btn.addEventListener("click", async () => {
                const author = btn.dataset.author;
                if (!confirm(`确定要向 "${author}" 发送钉钉通知吗？`)) return;
                try {
                    const result = await App.request("/api/notify/by-author", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ author }),
                    });
                    const ok = result && result.success === true;
                    App.notify(ok ? (result.message || "通知发送成功") : (result.message || "通知发送失败"), ok ? "success" : "danger");
                } catch (e) {
                    App.notify(e.message, "danger");
                }
            });
        });
    } else if (type === "projectAuthor") {
        bindProjectAuthorStatsActions(tbody);
    }
}

/** 页面3「按项目+编写人员」表格：个人催办 + 模块级联按钮 */
function bindProjectAuthorStatsActions(container) {
    if (!container) return;
    container.querySelectorAll(".btn-notify-project-author").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const projectName = btn.dataset.project || "";
            const author = btn.dataset.author || "";
            if (!projectName || !author) return;
            if (!confirm(`确定向「${author}」发送项目「${projectName}」下的个人任务催办吗？`)) return;
            try {
                const result = await App.request("/api/notify/by-project-author", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ projectName, author }),
                });
                const ok = result && result.success === true;
                App.notify(
                    ok ? result.message || "通知发送成功" : result.message || "通知发送失败",
                    ok ? "success" : "danger"
                );
            } catch (e) {
                App.notify(e.message, "danger");
            }
        });
    });
    container.querySelectorAll(".btn-module-cascade").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const projectName = btn.dataset.project || "";
            if (!projectName) return;
            if (!confirm(`确定要对「${projectName}」执行模块级联催办吗？\n（产品全部完成→催办开发；开发全部完成→催办测试）`)) return;
            try {
                const result = await App.request("/api/notify/module-cascade-manual", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ projectName }),
                });
                const ok = result && result.success === true;
                App.notify(result?.message || (ok ? "已发送" : "发送失败"), ok ? "success" : "danger");
                if (typeof loadModuleCascadeStatus === "function") loadModuleCascadeStatus();
            } catch (e) {
                const data = e.data || {};
                App.notify(data.message || e.message || "请求失败", "danger");
            }
        });
    });
}

function renderFilteredDetailTable(rows) {
    const tableBody = document.getElementById("detailTableBody");
    if (!tableBody) return;
    if (typeof window.reRenderDetailTableFromRows === "function") {
        window.reRenderDetailTableFromRows(rows || []);
        return;
    }
    lastRenderedDetailRows = rows || [];
    
    tableBody.innerHTML = "";
    lastRenderedDetailRows.forEach((row, idx) => {
        const tr = document.createElement("tr");
        tr.dataset.id = row.uploadId;
        
        const statusHtml = row.completionStatus 
            ? `<span class="badge bg-success">${row.completionStatus}</span>`
            : '<span class="badge bg-secondary">未完成</span>';
        const dueDateStyle = getDueDateStyle(row.dueDate);
        const dueDateHtml = dueDateStyle.class 
            ? `<span class="badge ${dueDateStyle.class}" title="${dueDateStyle.title || ''}">${dueDateStyle.text}</span>`
            : (dueDateStyle.text || "-");
        
        tr.innerHTML = `
            <td class="col-drag seq-cell"><span class="drag-handle" draggable="true" title="拖动排序">⋮⋮</span>${idx + 1}</td>
            <td title="${_escTitle(row.projectName)}">${row.projectName}</td>
            <td title="${_escTitle(row.fileName)}">${row.fileName}</td>
            <td title="${_escTitle(row.taskType)}">${row.taskType || "-"}</td>
            <td title="${_escTitle(row.belongingModule)}">${(row.belongingModule != null && row.belongingModule !== "") ? row.belongingModule : "-"}</td>
            <td title="${_escTitle(row.author)}">${row.author}</td>
            <td>${statusHtml}</td>
            <td>${dueDateHtml}</td>
            <td title="${_escTitle(row.businessSide)}">${(row.businessSide != null && row.businessSide !== "") ? row.businessSide : "-"}</td>
            <td title="${_escTitle(row.product)}">${(row.product != null && row.product !== "") ? row.product : "-"}</td>
            <td title="${_escTitle(row.country)}">${(row.country != null && row.country !== "") ? row.country : "-"}</td>
            <td data-wrap style="max-width:180px" title="${_escTitle(row.notes)}">${_renderNotesHtml(row.notes)}</td>
            <td title="${_escTitle(row.executionNotes)}">${(row.executionNotes != null && row.executionNotes !== "") ? row.executionNotes : "-"}</td>
            <td>${row.docLink ? `<a href="${row.docLink}" target="_blank" rel="noopener">打开</a>` : "-"}</td>
            <td title="${_escTitle(row.projectCode)}">${(row.projectCode != null && row.projectCode !== "") ? row.projectCode : "-"}</td>
            <td title="${_escTitle(row.fileVersion)}">${(row.fileVersion != null && row.fileVersion !== "") ? row.fileVersion : "-"}</td>
            <td title="${_escTitle(row.documentDisplayDate)}">${(row.documentDisplayDate != null && row.documentDisplayDate !== "") ? row.documentDisplayDate : "-"}</td>
            <td title="${_escTitle(row.reviewer)}">${(row.reviewer != null && row.reviewer !== "") ? row.reviewer : "-"}</td>
            <td title="${_escTitle(row.approver)}">${(row.approver != null && row.approver !== "") ? row.approver : "-"}</td>
            <td title="${_escTitle(row.displayedAuthor)}">${(row.displayedAuthor != null && row.displayedAuthor !== "") ? row.displayedAuthor : "-"}</td>
            <td title="${_escTitle(row.projectNotes)}">${(row.projectNotes != null && row.projectNotes !== "") ? row.projectNotes : "-"}</td>
            <td title="${_escTitle(row.registeredProductName)}">${(row.registeredProductName != null && row.registeredProductName !== "") ? row.registeredProductName : "-"}</td>
            <td title="${_escTitle(row.model)}">${(row.model != null && row.model !== "") ? row.model : "-"}</td>
            <td title="${_escTitle(row.registrationVersion)}">${(row.registrationVersion != null && row.registrationVersion !== "") ? row.registrationVersion : "-"}</td>
            <td class="col-op">
                ${!row.isCompleted ? `<button class="btn btn-sm btn-outline-warning btn-notify-single" data-id="${row.uploadId}">催办</button>` : ''}
            </td>
        `;
        tableBody.appendChild(tr);
    });
    
    tableBody.querySelectorAll(".btn-notify-single").forEach(btn => {
        btn.addEventListener("click", async () => {
            if (!confirm("确定要发送钉钉通知吗？")) return;
            try {
                const result = await App.request("/api/notify/single-task", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ uploadId: btn.dataset.id }),
                });
                const ok = result && result.success === true;
                App.notify(ok ? (result.message || "通知发送成功") : (result.message || "通知发送失败"), ok ? "success" : "danger");
            } catch (e) {
                App.notify(e.message, "danger");
            }
        });
    });
}

function initNotifyTemplateModal() {
    const notifyTemplateList = document.getElementById("notifyTemplateList");
    const saveBtn = document.getElementById("saveNotifyTemplatesBtn");
    const modal = document.getElementById("notifyTemplateModal");
    
    if (!notifyTemplateList || !modal) return;
    
    modal.addEventListener("show.bs.modal", async () => {
        try {
            const templates = await App.request("/api/configs/notify-templates");
            notifyTemplateList.innerHTML = "";
            
            templates.forEach(t => {
                const div = document.createElement("div");
                div.className = "mb-3 p-3 border rounded";
                div.innerHTML = `
                    <label class="form-label fw-bold">${t.name}</label>
                    <small class="text-muted d-block mb-2">模板KEY: ${t.key}</small>
                    <textarea class="form-control template-content" data-id="${t.id}" rows="4">${t.content}</textarea>
                    <small class="text-muted mt-1 d-block">可用变量: {project_name}, {project_code}, {project_notes}, {file_name}, {task_type}, {due_date}, {author}, {pending_count}, {assignees}, {task_list}, {task_list_with_links}, {doc_link}, {business_side}, {product}, {country}, {file_version}, {document_display_date}, {reviewer}, {approver}</small>
                `;
                notifyTemplateList.appendChild(div);
            });
        } catch (e) {
            App.notify(e.message, "danger");
        }
    });
    
    saveBtn?.addEventListener("click", async () => {
        const textareas = notifyTemplateList.querySelectorAll(".template-content");
        for (const textarea of textareas) {
            try {
                await App.request(`/api/configs/notify-templates/${textarea.dataset.id}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ content: textarea.value }),
                });
            } catch (e) {
                App.notify(`保存失败: ${e.message}`, "danger");
                return;
            }
        }
        App.notify("通知文案保存成功");
        bootstrap.Modal.getInstance(modal)?.hide();
    });
}

/** 根据表头可见列宽，更新项目名称/文件名称 sticky 的 left 偏移 */
function syncStickyNameColumns(table) {
    if (!table || !table.classList.contains("table-sticky-name-cols")) return;
    const thProject = table.querySelector('thead th[data-col="projectName"]');
    const thFile = table.querySelector('thead th[data-col="fileName"]');
    const row = (thProject || thFile)?.parentElement;
    if (!row) return;

    const prefixWidth = (beforeTh) => {
        let left = 0;
        for (const cell of row.children) {
            if (cell === beforeTh) break;
            if (cell.style.display === "none") continue;
            left += cell.offsetWidth;
        }
        return left;
    };

    if (thProject && thProject.style.display !== "none") {
        const left = prefixWidth(thProject);
        const pw = thProject.offsetWidth || 150;
        table.style.setProperty("--sticky-project-left", `${left}px`);
        if (thFile && thFile.style.display !== "none") {
            table.style.setProperty("--sticky-file-left", `${left + pw}px`);
        } else {
            table.style.removeProperty("--sticky-file-left");
        }
    } else if (thFile && thFile.style.display !== "none") {
        table.style.removeProperty("--sticky-project-left");
        table.style.setProperty("--sticky-file-left", `${prefixWidth(thFile)}px`);
    } else {
        table.style.removeProperty("--sticky-project-left");
        table.style.removeProperty("--sticky-file-left");
    }
}

function scheduleSyncStickyNameColumns(table) {
    if (!table) return;
    requestAnimationFrame(() => syncStickyNameColumns(table));
}

function initColumnToggle(btnId, menuId, tableId) {
    const btn = document.getElementById(btnId);
    const menu = document.getElementById(menuId);
    const table = document.getElementById(tableId);
    if (!btn || !menu || !table) return;
    const storeKey = table.dataset.colStoreKey || ("colVis_" + tableId + "_v2");
    const ths = table.querySelectorAll("thead tr th[data-col]");
    if (!ths.length) return;

    const colNames = {
        seq: "序号", projectName: "项目名称", projectCode: "项目编号",
        fileName: "文件名称", taskType: "任务类型", belongingModule: "所属模块",
        source: "来源", fileVersion: "文件版本号", author: "编写人员",
        dueDate: "截止日期", docDisplayDate: "文档体现日期", businessSide: "影响业务方",
        product: "影响产品", country: "国家", taskStatus: "状态", auditStatus: "审核状态",
        reviewer: "审核人员", approver: "批准人员", displayedAuthor: "体现编写人员",
        projectNotes: "项目备注", notes: "下发任务备注", executionNotes: "执行任务备注",
        registeredProductName: "注册产品名称", model: "型号", registrationVersion: "注册版本号",
        op: "操作", docLink: "文档链接/地址", completionStatus: "完成状态",
    };
    const defaultHiddenCols = ["projectCode", "fileVersion", "docDisplayDate", "reviewer", "approver", "displayedAuthor", "projectNotes", "registeredProductName", "model", "registrationVersion"];
    const defaultHidden = new Set(defaultHiddenCols);

    function getDefaultVisible(col) {
        return !defaultHidden.has(col);
    }

    let saved;
    try { saved = JSON.parse(localStorage.getItem(storeKey)); } catch (e) { saved = null; }

    const colList = [];
    ths.forEach((th) => {
        const col = th.dataset.col;
        if (!col) return;
        const colIndex = Array.from(th.parentNode.children).indexOf(th);
        let visible;
        if (saved && typeof saved[col] === "boolean") {
            visible = saved[col];
        } else {
            visible = getDefaultVisible(col);
        }
        colList.push({ col, colIndex, visible });
    });

    function applyVisibility() {
        const allRows = table.querySelectorAll("tr");
        colList.forEach(({ col, colIndex, visible }) => {
            allRows.forEach((tr) => {
                const cell = tr.children[colIndex];
                if (cell) cell.style.display = visible ? "" : "none";
            });
        });
        const state = {};
        colList.forEach(c => { state[c.col] = c.visible; });
        try { localStorage.setItem(storeKey, JSON.stringify(state)); } catch (e) {}
        if (table.classList.contains("table-sticky-name-cols")) {
            scheduleSyncStickyNameColumns(table);
        }
    }

    function syncCheckboxes() {
        const items = colList.filter(c => c.col !== "op");
        const cbs = menu.querySelectorAll("input[type=checkbox]");
        items.forEach((item, idx) => {
            if (cbs[idx]) cbs[idx].checked = item.visible;
        });
    }

    menu.innerHTML = "";
    const btnRow = document.createElement("div");
    btnRow.className = "d-flex gap-1 px-2 py-2 border-bottom";
    const btnAll = document.createElement("button");
    btnAll.type = "button";
    btnAll.className = "btn btn-sm btn-outline-secondary";
    btnAll.textContent = "全选";
    btnAll.addEventListener("click", () => {
        colList.forEach(c => { c.visible = true; });
        syncCheckboxes();
        applyVisibility();
    });
    const btnReset = document.createElement("button");
    btnReset.type = "button";
    btnReset.className = "btn btn-sm btn-outline-secondary";
    btnReset.textContent = "恢复默认";
    btnReset.addEventListener("click", () => {
        try { localStorage.removeItem(storeKey); } catch (e) {}
        colList.forEach(c => { c.visible = getDefaultVisible(c.col); });
        syncCheckboxes();
        applyVisibility();
    });
    btnRow.appendChild(btnAll);
    btnRow.appendChild(btnReset);
    menu.appendChild(btnRow);

    colList.forEach((item) => {
        if (item.col === "op") return;
        const label = document.createElement("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = item.visible;
        cb.addEventListener("change", () => {
            item.visible = cb.checked;
            applyVisibility();
        });
        const span = document.createElement("span");
        span.textContent = colNames[item.col] || item.col;
        label.appendChild(cb);
        label.appendChild(span);
        menu.appendChild(label);
    });

    applyVisibility();

    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        menu.classList.toggle("show");
    });
    document.addEventListener("click", (e) => {
        if (!menu.contains(e.target) && e.target !== btn) {
            menu.classList.remove("show");
        }
    });

    const observer = new MutationObserver(() => {
        applyVisibility();
    });
    const tbody = table.querySelector("tbody");
    if (tbody) observer.observe(tbody, { childList: true });

    if (table.classList.contains("table-sticky-name-cols")) {
        scheduleSyncStickyNameColumns(table);
        if (!window._stickyNameColsResizeBound) {
            window._stickyNameColsResizeBound = true;
            window.addEventListener("resize", () => {
                scheduleSyncStickyNameColumns(document.getElementById("recordsTable"));
                scheduleSyncStickyNameColumns(document.getElementById("myTasksTable"));
            });
        }
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    await loadCompletionStatuses().catch((e) => {
        console.warn("loadCompletionStatuses:", e);
    });
    Promise.resolve(initUploadPage()).catch((e) => {
        console.error("initUploadPage:", e);
        if (document.getElementById("recordsTableBody")) loadRecordsList();
    });
    initLoginPage();
    initGeneratePage();
    initDashboardPage();

    initColumnToggle("colToggleBtn1", "colToggleMenu1", "recordsTable");
    initColumnToggle("colToggleBtn2", "colToggleMenu2", "myTasksTable");
    initColumnToggle("colToggleBtn3", "colToggleMenu3", "detailTable");
});
