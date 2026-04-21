const App = {
    async request(url, options = {}) {
        const root = (window.__SCRIPT_ROOT__ != null ? String(window.__SCRIPT_ROOT__) : "").replace(/\/+$/, "");
        if (root && typeof url === "string") {
            // 仅对站内绝对路径（/api/xxx）自动加前缀；避免影响 http(s):// 外链与相对路径
            if (url.startsWith("/") && !url.startsWith(root + "/")) {
                url = root + url;
            }
        }
        let response;
        try {
            response = await fetch(url, { credentials: "include", ...options });
        } catch (networkError) {
            throw new Error("网络错误，请检查网络连接");
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

async function loadTaskTypes() {
    try {
        const res = await App.request("/api/configs/task-types");
        taskTypesCache = res.taskTypes || [];
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

function createTaskTypeSelect() {
    const select = document.createElement("select");
    select.className = "form-select form-select-sm task-type";
    select.innerHTML = '<option value="">选择类型</option>';
    taskTypesCache.forEach(t => {
        const opt = document.createElement("option");
        opt.value = t.name;
        opt.textContent = t.name;
        select.appendChild(opt);
    });
    return select;
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
        const label = p.priorityLabel ? `【${p.priorityLabel}】${p.projectKey || p.name}` : (p.projectKey || p.name);
        opt.textContent = label;
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

function createProjectBlock() {
    const block = document.createElement("div");
    block.className = "project-block card border mb-3";
    block.innerHTML = `
        <div class="card-body">
            <h6 class="card-subtitle text-muted mb-2">第一层 · 项目信息</h6>
            <div class="row g-2 mb-2">
                <div class="col-md-3"><label class="form-label small">项目名称 *</label><select class="form-select form-select-sm project-name" required></select></div>
                <div class="col-md-3"><label class="form-label small">影响业务方</label><input type="text" class="form-control form-control-sm project-business-side" placeholder="影响业务方"></div>
                <div class="col-md-3"><label class="form-label small">影响产品</label><input type="text" class="form-control form-control-sm project-product" placeholder="影响产品"></div>
                <div class="col-md-3"><label class="form-label small">国家</label><input type="text" class="form-control form-control-sm project-country" placeholder="国家"></div>
            </div>
            <div class="mb-2">
                <button type="button" class="btn btn-outline-secondary btn-sm add-task-row-btn">+ 添加任务行</button>
                <button type="button" class="btn btn-outline-danger btn-sm float-end remove-project-btn">删除项目</button>
            </div>
            <p class="text-muted small fw-bold mb-2 mt-2">以下为文档通用及签审批信息</p>
            <div class="row g-2 mb-2">
                <div class="col-md-2"><label class="form-label small">项目编号</label><input type="text" class="form-control form-control-sm project-code" placeholder="项目编号"></div>
                <div class="col-md-2"><label class="form-label small">项目备注</label><input type="text" class="form-control form-control-sm project-notes" placeholder="项目备注"></div>
                <div class="col-md-2"><label class="form-label small">注册产品名称</label><input type="text" class="form-control form-control-sm project-registered-product-name" placeholder="注册产品名称"></div>
                <div class="col-md-2"><label class="form-label small">型号</label><input type="text" class="form-control form-control-sm project-model" placeholder="型号"></div>
                <div class="col-md-2"><label class="form-label small">注册版本号</label><input type="text" class="form-control form-control-sm project-registration-version" placeholder="注册版本号"></div>
            </div>
            <h6 class="card-subtitle text-muted mb-2 mt-3">第二层 · 文件/事项任务</h6>
            <div class="table-responsive">
                <table class="table table-bordered table-sm align-middle">
                    <thead class="table-light">
                        <tr>
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
                        <tr>
                            <th></th>
                            <th></th>
                            <th></th>
                            <th></th>
                            <th></th>
                            <th></th>
                            <th></th>
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

    // 根据下拉选择自动填充“国家”，避免任务记录中的国家与项目元数据不一致
    const projectSelectEl = block.querySelector(".project-name");
    const countryInputEl = block.querySelector(".project-country");
    projectSelectEl?.addEventListener("change", () => {
        const opt = projectSelectEl.options[projectSelectEl.selectedIndex];
        const v = opt?.dataset?.registeredCountry || "";
        if (countryInputEl) countryInputEl.value = v;
    });

    _populateProjectNameSelect(block.querySelector(".project-name"));
    block.querySelector(".add-task-row-btn").addEventListener("click", () => {
        const newRow = createTaskRowUnderProject(block);
        tbody.appendChild(newRow);
        const rows = tbody.querySelectorAll("tr");
        if (rows.length >= 2) {
            const prevRow = rows[rows.length - 2];
            const newRowEl = rows[rows.length - 1];
            newRowEl.querySelector(".task-filename").value = prevRow.querySelector(".task-filename")?.value ?? "";
            const prevTypeSelect = prevRow.querySelector(".task-type-cell select");
            const newTypeSelect = newRowEl.querySelector(".task-type-cell select");
            if (prevTypeSelect && newTypeSelect) {
                const pv = (prevTypeSelect.value || "").trim();
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
    });
    block.querySelector(".remove-project-btn").addEventListener("click", () => block.remove());
    tbody.appendChild(createTaskRowUnderProject(block));
    return block;
}

function createTaskRowUnderProject(projectBlock) {
    rowCounter++;
    const tr = document.createElement("tr");
    tr.dataset.rowId = rowCounter;
    tr.innerHTML = `
        <td><input type="text" class="form-control form-control-sm task-filename" placeholder="文件名称"></td>
        <td class="task-type-cell"></td>
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
                    <input type="file" class="d-none task-file" accept=".docx,.doc">
                    文件
                </label>
            </div>
            <small class="task-file-name text-muted d-none"></small>
        </td>
        <td>
            <div class="input-group input-group-sm">
                <input type="text" class="form-control task-author" placeholder="编写人员">
                <button type="button" class="btn btn-outline-success btn-create-user" title="快速创建账号">+</button>
            </div>
        </td>
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
    tr.querySelector(".task-type-cell").appendChild(createTaskTypeSelect());
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
    tr.querySelector(".btn-remove-row").addEventListener("click", () => tr.remove());
    tr.querySelector(".btn-create-user").addEventListener("click", () => {
        const authorInput = tr.querySelector(".task-author");
        const username = authorInput.value.trim();
        if (username) document.getElementById("quickUsername").value = username;
        const modal = new bootstrap.Modal(document.getElementById("quickUserModal"));
        modal.show();
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

    // 进入页面时默认不显示历史项目；防止浏览器回退/表单恢复导致再次进入时仍保持勾选
    if (showHistoryEl) showHistoryEl.checked = false;

    showHistoryEl?.addEventListener("change", () => {
        loadRecordsList();
    });

    // bfcache 场景：回退/前进时也复位并重新加载（确保默认仍隐藏历史）
    if (!window._page1HistoryToggleBound) {
        window._page1HistoryToggleBound = true;
        window.addEventListener("pageshow", () => {
            const el = document.getElementById("showHistoryProjectsPage1");
            if (el) el.checked = false;
            if (typeof loadRecordsList === "function") loadRecordsList();
        });
    }

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

    await loadTaskTypes();
    projectBlocksContainer.appendChild(createProjectBlock());
    _populateProjectNameSelect(projectBlocksContainer.querySelector(".project-block .project-name"));

    addProjectBtn?.addEventListener("click", () => {
        projectBlocksContainer.appendChild(createProjectBlock());
        const blocks = projectBlocksContainer.querySelectorAll(".project-block");
        if (blocks.length >= 2) {
            const prev = blocks[blocks.length - 2];
            const curr = blocks[blocks.length - 1];
            _populateProjectNameSelect(curr.querySelector(".project-name"), prev.querySelector(".project-name")?.value ?? "");
            curr.querySelector(".project-code").value = prev.querySelector(".project-code")?.value ?? "";
            curr.querySelector(".project-business-side").value = prev.querySelector(".project-business-side")?.value ?? "";
            curr.querySelector(".project-product").value = prev.querySelector(".project-product")?.value ?? "";
            curr.querySelector(".project-country").value = prev.querySelector(".project-country")?.value ?? "";
            curr.querySelector(".project-notes").value = prev.querySelector(".project-notes")?.value ?? "";
        }
    });

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

    saveAllBtn?.addEventListener("click", async () => {
        const blocks = projectBlocksContainer.querySelectorAll(".project-block");
        let successCount = 0;
        let skippedIncomplete = 0;
        let plannedSaveCount = 0;
        let lastPlaceholders = [];
        const btn = saveAllBtn;
        const origText = btn?.textContent || "保存全部";
        try {
            if (btn) { btn.disabled = true; btn.textContent = "保存中…"; }
            App.notify("正在保存…", "info");

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
                    const taskTypeSelect = row.querySelector(".task-type-cell select");
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
                        if (btn) {
                            btn.disabled = false;
                            btn.textContent = origText;
                        }
                        return;
                    }
                    dupSeen.add(dupKey);
                    plannedSaveCount++;

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
                        });
                        successCount++;
                        if (result.record && result.record.placeholders) {
                            lastPlaceholders = result.record.placeholders;
                        }
                    } catch (error) {
                        const msg = error && error.message ? error.message : "";
                        const is409Replace = error && error.is409Replace === true;
                        if (is409Replace) {
                            const replaceOk = window.confirm(
                                (msg || "存在重复记录，是否替换？") +
                                    "\n\n提示：选「确定」将用本行内容覆盖库里已有同一条（同项目+文件名称+任务类型+编写人员）；选「取消」则跳过本行，可继续保存其余行。"
                            );
                            if (replaceOk) {
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
                                if (link) {
                                    formDataReplace.append("templateLinks", normalizeDocLink(link));
                                } else if (fileInput && fileInput.files.length > 0) {
                                    formDataReplace.append("file", fileInput.files[0]);
                                }
                                try {
                                    const resultReplace = await App.request("/api/upload", { method: "POST", body: formDataReplace });
                                    successCount++;
                                    if (resultReplace.record && resultReplace.record.placeholders) {
                                        lastPlaceholders = resultReplace.record.placeholders;
                                    }
                                } catch (e2) {
                                    App.notify(`保存失败 (${projectKey}-${fileName}): ${e2 && e2.message ? e2.message : "请重试"}`, "danger");
                                }
                            } else {
                                App.notify(`已跳过：${fileName}（与已有记录重复，您选择了不替换）`, "info");
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
            if (btn) { btn.disabled = false; btn.textContent = origText; }
        }
    });

    initUserForm();
    initQuickUserForm();
    initConfigManagement();
    loadRecordsList();
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
        try {
            await App.request(`/api/users/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mobile: mobile || null }),
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
    document.getElementById("editRecordId").value = r.id;
    document.getElementById("editRecordProject").value = r.projectName || "";
    const projectCodeEl = document.getElementById("editRecordProjectCode");
    if (projectCodeEl) projectCodeEl.value = r.projectCode || "";
    document.getElementById("editRecordFile").value = r.fileName || "";
    const taskTypeEl = document.getElementById("editRecordTaskType");
    if (taskTypeEl) {
        await loadTaskTypes();
        taskTypeEl.innerHTML = '<option value="">选择类型</option>';
        (taskTypesCache || []).forEach(t => {
            const opt = document.createElement("option");
            opt.value = t.name;
            opt.textContent = t.name;
            taskTypeEl.appendChild(opt);
        });
        ensureSelectHasOption(
            taskTypeEl,
            r.taskType || "",
            "（当前记录中的类型；若已不在「任务类型」配置中，请补回配置以免保存丢失）"
        );
        taskTypeEl.value = r.taskType || "";
    }
    const editRecordBelongingModuleEl = document.getElementById("editRecordBelongingModule");
    if (editRecordBelongingModuleEl) editRecordBelongingModuleEl.value = r.belongingModule || "";
    document.getElementById("editRecordAuthor").value = r.author || "";
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
            const user = users.find(u => (u.username && u.username.trim() === name) || (u.displayName && u.displayName.trim() === name));
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
    const authorInput = document.getElementById("editRecordAuthor");
    if (authorInput && assigneeInput) {
        authorInput.addEventListener("blur", () => {
            if (modalEl.classList.contains("show")) {
                const authorVal = authorInput.value.trim();
                if (authorVal) assigneeInput.value = authorVal;
                updateEditRecordAssigneeMobileHint(assigneeInput.value || "");
            }
        });
        authorInput.addEventListener("change", () => {
            if (modalEl.classList.contains("show")) {
                const authorVal = authorInput.value.trim();
                if (authorVal) assigneeInput.value = authorVal;
            }
        });
    }
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
            author: document.getElementById("editRecordAuthor").value.trim(),
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
        try {
            await App.request(`/api/uploads/${id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            App.notify("任务已更新");
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
        const batchTaskTypeSel = document.getElementById("batchEditTaskType");
        if (batchTaskTypeSel) {
            await loadTaskTypes();
            batchTaskTypeSel.innerHTML = '<option value="">— 不修改 —</option>';
            (taskTypesCache || []).forEach((t) => {
                const opt = document.createElement("option");
                opt.value = t.name;
                opt.textContent = t.name;
                batchTaskTypeSel.appendChild(opt);
            });
            batchTaskTypeSel.value = sameTaskType ? taskTypeVal : "";
        }
        const batchEditProjectCodeEl = document.getElementById("batchEditProjectCode");
        if (batchEditProjectCodeEl) batchEditProjectCodeEl.value = sameProjectCode ? projectCodeVal : "";
        document.getElementById("batchEditAuthor").value = sameAuthor ? authorVal : "";
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

    batchEditSaveBtn?.addEventListener("click", async () => {
        const idsStr = batchEditModal?.dataset.batchEditIds;
        if (!idsStr) return;
        const ids = idsStr.split(",").filter(Boolean);
        const projectCode = (document.getElementById("batchEditProjectCode")?.value || "").trim();
        const taskType = (document.getElementById("batchEditTaskType")?.value || "").trim();
        const author = (document.getElementById("batchEditAuthor")?.value || "").trim();
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
    if (!tbody || !btn) return;
    const checked = tbody.querySelectorAll(".record-checkbox:checked").length;
    btn.disabled = checked === 0;
}

function renderRecordsTable(records) {
    const tbody = document.getElementById("recordsTableBody");
    if (!tbody) return;
    lastRenderedRecords = records || [];
    const groupBy = (document.querySelector('input[name="recordsGroupBy"]:checked') || {}).value || "none";
    
    const makeRow = (r, idx) => {
        const tr = document.createElement("tr");
        tr.dataset.id = r.id;
        tr.dataset.projectName = (r.projectName != null && r.projectName !== "") ? String(r.projectName).trim() : "";
        let sourceHtml;
        if (r.hasFile) {
            sourceHtml = "文件";
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
        tr.innerHTML = `
            <td class="col-drag"><span class="drag-handle" draggable="true" title="拖动排序">⋮⋮</span><input type="checkbox" class="form-check-input record-checkbox" data-id="${r.id}"></td>
            <td class="seq-cell">${idx + 1}</td>
            <td title="${_escTitle(r.projectName)}">${r.projectName}</td>
            <td title="${_escTitle(r.fileName)}">${r.fileName}</td>
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
        })
        .catch((e) => App.notify(e.message || "加载记录失败", "danger"));
}

function loadUsersList() {
    const tbody = document.getElementById("usersTableBody");
    if (!tbody) return;

    App.request("/api/users")
        .then((res) => {
            tbody.innerHTML = "";
            (res.users || []).forEach((u) => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td>${u.username}</td>
                    <td class="user-mobile-cell">${u.mobile || "-"}</td>
                    <td>
                        <button type="button" class="btn btn-sm btn-outline-secondary btn-edit-mobile me-1" data-id="${u.id}" data-username="${u.username}" data-mobile="${u.mobile || ""}">编辑手机号</button>
                        <button type="button" class="btn btn-sm btn-outline-danger btn-delete-user" data-id="${u.id}">删除</button>
                    </td>
                `;
                tbody.appendChild(tr);
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
            tbody.querySelectorAll(".btn-edit-mobile").forEach((btn) => {
                btn.addEventListener("click", () => {
                    document.getElementById("editUserMobileId").value = btn.dataset.id;
                    document.getElementById("editUserMobileUsername").value = btn.dataset.username || "";
                    document.getElementById("editUserMobileValue").value = btn.dataset.mobile || "";
                    const modal = new bootstrap.Modal(document.getElementById("editUserMobileModal"));
                    modal.show();
                });
            });
        })
        .catch((e) => App.notify(e.message || "加载用户失败", "danger"));
}

function initUserForm() {
    const form = document.getElementById("userForm");
    if (!form) return;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const usernameInput = document.getElementById("newUsername");
        const passwordInput = document.getElementById("newPassword");
        const displayNameInput = document.getElementById("newDisplayName");
        const mobileInput = document.getElementById("newMobile");
        
        const payload = {
            username: usernameInput.value.trim(),
            password: passwordInput.value.trim(),
            displayName: displayNameInput ? displayNameInput.value.trim() || null : null,
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
            loadUsersList();
        } catch (error) {
            App.notify(error.message, "danger");
        }
    });
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
            loadUsersList();
            bootstrap.Modal.getInstance(document.getElementById("quickUserModal"))?.hide();
            const editId = document.getElementById("editRecordId")?.value;
            const editModal = document.getElementById("editRecordModal");
            if (editId && editModal?.classList.contains("show")) {
                const assigneeInput = document.getElementById("editRecordAssignee");
                if (assigneeInput) {
                    assigneeInput.value = result.user?.displayName || result.user?.username || payload.username || "";
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
            const res = await App.request("/api/configs/task-types");
            taskTypesCache = res.taskTypes || [];
            taskTypesList.innerHTML = "";
            taskTypesCache.forEach(t => {
                const badge = document.createElement("span");
                badge.className = "badge bg-secondary d-flex align-items-center";
                badge.innerHTML = `${t.name} <button class="btn-close btn-close-white ms-1" style="font-size:0.6rem;" data-id="${t.id}"></button>`;
                badge.querySelector("button").addEventListener("click", async () => {
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
        try {
            await App.request("/api/configs/task-types", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
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
            password: document.getElementById("loginPassword").value.trim(),
        };
        try {
            await App.request("/api/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            window.location.href = "/generate";
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
            userInfo.textContent = `欢迎，${res.user.displayName || res.user.username}`;
        }
    });

    logoutBtn?.addEventListener("click", async () => {
        await App.request("/api/logout", { method: "POST" });
        window.location.href = "/login";
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
        const source = r.hasFile ? "文件" : (r.hasLinks ? `链接` : "-");
        const firstLink = r.templateLinks ? (r.templateLinks.split("\n")[0] || "").trim() : "";
        const sourceTd = r.hasLinks && firstLink ? `<a href="${firstLink}" target="_blank" class="text-primary">${source}</a>` : source;
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
        tr.innerHTML = `
            <td class="col-drag seq-cell"><span class="drag-handle" draggable="true" title="拖动排序">⋮⋮</span>${idx + 1}</td>
            <td title="${_escTitle(r.projectName)}">${r.projectName}</td>
            <td title="${_escTitle(r.fileName)}">${r.fileName}</td>
            <td title="${_escTitle(r.taskType)}">${r.taskType || "-"}</td>
            <td title="${_escTitle(r.belongingModule)}">${(r.belongingModule != null && r.belongingModule !== "") ? r.belongingModule : "-"}</td>
            <td>${sourceTd}</td>
            <td class="task-link-cell">${linkCellHtml}</td>
            <td>${dueDateHtml}</td>
            <td title="${_escTitle(r.businessSide)}">${(r.businessSide != null && r.businessSide !== "") ? r.businessSide : "-"}</td>
            <td title="${_escTitle(r.product)}">${(r.product != null && r.product !== "") ? r.product : "-"}</td>
            <td title="${_escTitle(r.country)}">${(r.country != null && r.country !== "") ? r.country : "-"}</td>
            <td data-wrap style="max-width:180px" title="${_escTitle(r.notes)}">${_renderNotesHtml(r.notes)}</td>
            <td><input type="text" class="form-control form-control-sm execution-notes-input" placeholder="执行备注" data-id="${r.id}" value="${(r.executionNotes != null && r.executionNotes !== "") ? String(r.executionNotes).replace(/"/g, "&quot;") : ""}"></td>
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
                ${r.hasFile || (r.placeholders && r.placeholders.length > 0)
                    ? `<button class="btn btn-sm btn-outline-primary btn-fill-placeholders" data-id="${r.id}">填写</button>`
                    : ''}
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
            if (isCompleted && !hasTemplate) {
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
            try {
                await App.request(`/api/uploads/${r.id}/completion-status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
                App.notify("状态已更新");
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
                try {
                    await App.request(`/api/uploads/${r.id}/execution-notes`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ executionNotes: val || null }) });
                    r.executionNotes = val || null;
                    App.notify("执行任务备注已保存");
                } catch (err) { App.notify(err.message || "保存失败", "danger"); }
            });
        }
        tr.querySelector(".btn-fill-placeholders")?.addEventListener("click", () => openPlaceholderModal(r, placeholderModal));
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

function initDashboardPage() {
    const loadSystemSettings = async () => {
        const container = document.getElementById("systemSettingsForm");
        if (!container) return;
        try {
            const res = await App.request("/api/system-settings");
            const keys = res.keys || [];
            const settings = res.settings || {};
            if (!keys.length) {
                container.innerHTML =
                    '<div class="col-12"><div class="alert alert-warning mb-0 small">未获取到配置项列表，请刷新页面。</div></div>';
                return;
            }
            container.innerHTML = keys.map((k) => {
                const raw = settings[k.key] != null ? String(settings[k.key]) : "";
                const esc = (s) =>
                    String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
                const showVal = esc(raw);
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
                return `<div class="col-md-6"><label class="form-label small mb-0">${k.label.replace(/</g, "&lt;")}</label><input type="${typ}" class="form-control form-control-sm sys-cfg-input" data-key="${k.key}" data-sensitive="${k.sensitive ? "1" : "0"}" value="${showVal}" placeholder="${esc(ph)}" autocomplete="off"></div>`;
            }).join("");
        } catch (e) {
            console.error(e);
            const escE = (s) =>
                String(s)
                    .replace(/&/g, "&amp;")
                    .replace(/"/g, "&quot;")
                    .replace(/</g, "&lt;");
            container.innerHTML = `<div class="col-12"><div class="alert alert-danger mb-0 small">系统配置加载失败：${escE(
                (e && e.message) || String(e)
            )}。若提示需要访问密码，请先完成页面验证后再试。</div></div>`;
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
                        '<div class="col-12"><div class="alert alert-info mb-0 small">加载中…</div></div>';
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
            await App.request("/api/system-settings", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            App.notify("系统配置已保存", "success");
            await loadSystemSettings();
            if (typeof window.__dashboardReloadSchedule === "function") {
                window.__dashboardReloadSchedule();
            }
        } catch (e) {
            App.notify((e.data && e.data.message) || e.message || "保存失败", "danger");
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
            tr.innerHTML = `
                <td>${idx + 1}</td>
                <td>${row.label}</td>
                <td class="text-success">${row.completed}</td>
                <td class="${row.pending > 0 ? 'text-danger' : ''}">${row.pending}</td>
                <td>${formatRate(row.rate)}</td>
                <td>${formatStatusBadges(row.byStatus)}</td>
                <td>
                    <button class="btn btn-sm btn-outline-warning btn-module-cascade" data-project="${(projectName || "").replace(/"/g, "&quot;")}" title="该项目：产品全部完成→催办开发；开发全部完成→催办测试">
                        模块级联催办
                    </button>
                </td>
            `;
            projectAuthorBody.appendChild(tr);
        });
        projectAuthorBody.querySelectorAll(".btn-module-cascade").forEach(btn => {
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
                    loadModuleCascadeStatus && loadModuleCascadeStatus();
                } catch (e) {
                    const data = e.data || {};
                    App.notify(data.message || e.message || "请求失败", "danger");
                }
            });
        });
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
            actionHtml = `<td><button class="btn btn-sm btn-outline-warning btn-module-cascade" data-project="${pn}" title="该项目：产品全部完成→催办开发；开发全部完成→催办测试">模块级联催办</button></td>`;
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
        tbody.querySelectorAll(".btn-module-cascade").forEach(btn => {
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
                } catch (e) {
                    const data = e.data || {};
                    App.notify(data.message || e.message || "请求失败", "danger");
                }
            });
        });
    }
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

    const observer = new MutationObserver(() => applyVisibility());
    const tbody = table.querySelector("tbody");
    if (tbody) observer.observe(tbody, { childList: true });
}

document.addEventListener("DOMContentLoaded", async () => {
    try {
        await loadCompletionStatuses();
    } catch (e) {
        if (window.location.pathname !== "/login") throw e;
    }
    initUploadPage();
    initLoginPage();
    initGeneratePage();
    initDashboardPage();

    initColumnToggle("colToggleBtn1", "colToggleMenu1", "recordsTable");
    initColumnToggle("colToggleBtn2", "colToggleMenu2", "myTasksTable");
    initColumnToggle("colToggleBtn3", "colToggleMenu3", "detailTable");
});
