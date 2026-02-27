const App = {
    async request(url, options = {}) {
        let response;
        try {
            response = await fetch(url, options);
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
                window.location.href = "/login";
                throw new Error("需要登录");
            }
            
            if (response.status === 409 && data && data.needsConfirmation) {
                const confirmReplace = window.confirm(data.message);
                if (!confirmReplace) {
                    throw new Error("用户取消了替换操作");
                }
                const nextBody = (() => {
                    if (options.body instanceof FormData) {
                        options.body.set("replace", "true");
                        return options.body;
                    }
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

function createTaskRow() {
    rowCounter++;
    const tr = document.createElement("tr");
    tr.dataset.rowId = rowCounter;
    tr.innerHTML = `
        <td><input type="text" class="form-control form-control-sm task-project" placeholder="项目名称"></td>
        <td><input type="text" class="form-control form-control-sm task-filename" placeholder="文件名称"></td>
        <td class="task-type-cell"></td>
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
        <td><input type="text" class="form-control form-control-sm task-business-side" placeholder="影响业务方"></td>
        <td><input type="text" class="form-control form-control-sm task-product" placeholder="产品"></td>
        <td><input type="text" class="form-control form-control-sm task-country" placeholder="国家"></td>
        <td><input type="text" class="form-control form-control-sm task-notes" placeholder="下发任务备注"></td>
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
            if (!filenameInput.value) {
                filenameInput.value = fileInput.files[0].name;
            }
        }
    });

    linkInput.addEventListener("input", () => {
        if (linkInput.value.trim()) {
            fileInput.value = "";
            fileNameDisplay.classList.add("d-none");
        }
    });

    tr.querySelector(".btn-remove-row").addEventListener("click", () => tr.remove());

    tr.querySelector(".btn-create-user").addEventListener("click", () => {
        const authorInput = tr.querySelector(".task-author");
        const username = authorInput.value.trim();
        if (username) {
            document.getElementById("quickUsername").value = username;
        }
        const modal = new bootstrap.Modal(document.getElementById("quickUserModal"));
        modal.show();
    });

    return tr;
}

function initDragSort(tbody, onReorder) {
    let draggedRow = null;
    
    tbody.addEventListener("dragstart", (e) => {
        if (e.target.tagName === "TR" && !e.target.classList.contains("group-header-row")) {
            draggedRow = e.target;
            e.target.style.opacity = "0.4";
        }
    });
    
    tbody.addEventListener("dragend", (e) => {
        if (e.target.tagName === "TR") {
            e.target.style.opacity = "1";
            draggedRow = null;
        }
    });
    
    tbody.addEventListener("dragover", (e) => {
        e.preventDefault();
        const targetRow = e.target.closest("tr");
        if (targetRow && targetRow.classList.contains("group-header-row")) return;
        if (targetRow && draggedRow && targetRow !== draggedRow) {
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
        if (onReorder) {
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
    const taskInputBody = document.getElementById("taskInputBody");
    const addRowBtn = document.getElementById("addRowBtn");
    const saveAllBtn = document.getElementById("saveAllBtn");
    const placeholderResult = document.getElementById("placeholderResult");

    if (!taskInputBody) return;

    await loadTaskTypes();
    taskInputBody.appendChild(createTaskRow());

    addRowBtn?.addEventListener("click", () => {
        const newRow = createTaskRow();
        const existingRows = taskInputBody.querySelectorAll("tr");
        if (existingRows.length > 0) {
            const lastRow = existingRows[existingRows.length - 1];
            const from = {
                project: lastRow.querySelector(".task-project")?.value ?? "",
                filename: lastRow.querySelector(".task-filename")?.value ?? "",
                taskType: lastRow.querySelector(".task-type-cell select")?.value ?? "",
                link: lastRow.querySelector(".task-link")?.value ?? "",
                author: lastRow.querySelector(".task-author")?.value ?? "",
                duedate: lastRow.querySelector(".task-duedate")?.value ?? "",
                businessSide: lastRow.querySelector(".task-business-side")?.value ?? "",
                product: lastRow.querySelector(".task-product")?.value ?? "",
                country: lastRow.querySelector(".task-country")?.value ?? "",
                notes: lastRow.querySelector(".task-notes")?.value ?? "",
            };
            newRow.querySelector(".task-project").value = from.project;
            newRow.querySelector(".task-filename").value = from.filename;
            const typeSelect = newRow.querySelector(".task-type-cell select");
            if (typeSelect) typeSelect.value = from.taskType;
            newRow.querySelector(".task-link").value = from.link;
            newRow.querySelector(".task-author").value = from.author;
            newRow.querySelector(".task-duedate").value = from.duedate;
            newRow.querySelector(".task-business-side").value = from.businessSide;
            newRow.querySelector(".task-product").value = from.product;
            newRow.querySelector(".task-country").value = from.country;
            newRow.querySelector(".task-notes").value = from.notes || "";
        }
        taskInputBody.appendChild(newRow);
    });

    saveAllBtn?.addEventListener("click", async () => {
        const rows = taskInputBody.querySelectorAll("tr");
        let successCount = 0;
        let lastPlaceholders = [];

        for (const row of rows) {
            const projectName = row.querySelector(".task-project").value.trim();
            const fileName = row.querySelector(".task-filename").value.trim();
            const taskType = row.querySelector(".task-type").value.trim();
            const link = row.querySelector(".task-link").value.trim();
            const fileInput = row.querySelector(".task-file");
            const author = row.querySelector(".task-author").value.trim();
            const dueDate = row.querySelector(".task-duedate").value.trim();
            const businessSide = row.querySelector(".task-business-side")?.value.trim() || "";
            const product = row.querySelector(".task-product")?.value.trim() || "";
            const country = row.querySelector(".task-country")?.value.trim() || "";

            if (!projectName || !fileName || !author) continue;
            const notes = row.querySelector(".task-notes")?.value?.trim() || "";

            const formData = new FormData();
            formData.append("projectName", projectName);
            formData.append("fileName", fileName);
            formData.append("taskType", taskType);
            formData.append("author", author);
            formData.append("assigneeName", author);
            if (notes) formData.append("notes", notes);
            if (dueDate) formData.append("dueDate", dueDate);
            if (businessSide) formData.append("businessSide", businessSide);
            if (product) formData.append("product", product);
            if (country) formData.append("country", country);
            if (link) {
                formData.append("templateLinks", normalizeDocLink(link));
            } else if (fileInput.files.length > 0) {
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
                App.notify(`保存失败 (${projectName}-${fileName}): ${error.message}`, "danger");
            }
        }

        if (successCount > 0) {
            App.notify(`成功保存 ${successCount} 条记录`);
            taskInputBody.innerHTML = "";
            taskInputBody.appendChild(createTaskRow());
            loadRecordsList();
            if (lastPlaceholders.length > 0) {
                renderPlaceholderChips(placeholderResult, lastPlaceholders);
            }
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
    document.getElementById("editRecordFile").value = r.fileName || "";
    document.getElementById("editRecordTaskType").value = r.taskType || "";
    document.getElementById("editRecordAuthor").value = r.author || "";
    document.getElementById("editRecordDueDate").value = r.dueDate || "";
    document.getElementById("editRecordAssignee").value = r.assigneeName || r.author || "";
    document.getElementById("editRecordBusinessSide").value = r.businessSide || "";
    document.getElementById("editRecordProduct").value = r.product || "";
    document.getElementById("editRecordCountry").value = r.country || "";
    document.getElementById("editRecordTemplateLinks").value = r.templateLinks || "";
    document.getElementById("editRecordNotes").value = r.notes || "";
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
            templateLinks: document.getElementById("editRecordTemplateLinks").value.trim() || null,
            notes: document.getElementById("editRecordNotes").value.trim() || null,
        };
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
        const taskTypeVal = first ? (first.taskType || "").trim() : "";
        const authorVal = first ? (first.author || "").trim() : "";
        const assigneeVal = first ? (first.assigneeName || first.author || "").trim() : "";
        const dueDateVal = first ? (first.dueDate || "").trim() : "";
        const businessSideVal = first ? (first.businessSide || "").trim() : "";
        const productVal = first ? (first.product || "").trim() : "";
        const countryVal = first ? (first.country || "").trim() : "";
        const auditVal = first ? (first.auditStatus || "").trim() : "";
        const sameTaskType = taskTypeVal !== "" && records.every((r) => ((r.taskType || "").trim()) === taskTypeVal);
        const sameAuthor = authorVal !== "" && records.every((r) => ((r.author || "").trim()) === authorVal);
        const sameAssignee = assigneeVal !== "" && records.every((r) => ((r.assigneeName || r.author || "").trim()) === assigneeVal);
        const sameDueDate = dueDateVal !== "" && records.every((r) => ((r.dueDate || "").trim()) === dueDateVal);
        const sameBusinessSide = businessSideVal !== "" && records.every((r) => ((r.businessSide || "").trim()) === businessSideVal);
        const sameProduct = productVal !== "" && records.every((r) => ((r.product || "").trim()) === productVal);
        const sameCountry = countryVal !== "" && records.every((r) => ((r.country || "").trim()) === countryVal);
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
        document.getElementById("batchEditTaskType").value = sameTaskType ? taskTypeVal : "";
        document.getElementById("batchEditAuthor").value = sameAuthor ? authorVal : "";
        document.getElementById("batchEditAssignee").value = sameAssignee ? assigneeVal : "";
        document.getElementById("batchEditDueDate").value = sameDueDate ? dueDateVal : "";
        document.getElementById("batchEditBusinessSide").value = sameBusinessSide ? businessSideVal : "";
        document.getElementById("batchEditProduct").value = sameProduct ? productVal : "";
        document.getElementById("batchEditCountry").value = sameCountry ? countryVal : "";
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
        const taskType = (document.getElementById("batchEditTaskType")?.value || "").trim();
        const author = (document.getElementById("batchEditAuthor")?.value || "").trim();
        const assignee = (document.getElementById("batchEditAssignee")?.value || "").trim();
        const dueDate = (document.getElementById("batchEditDueDate")?.value || "").trim();
        const businessSide = (document.getElementById("batchEditBusinessSide")?.value || "").trim();
        const product = (document.getElementById("batchEditProduct")?.value || "").trim();
        const country = (document.getElementById("batchEditCountry")?.value || "").trim();
        const auditEl = document.getElementById("batchEditAuditStatus");
        const auditStatus = auditEl?.value?.trim() ?? "";
        const payload = {};
        if (taskType !== "") payload.taskType = taskType;
        if (author !== "") payload.author = author;
        if (assignee !== "") payload.assigneeName = assignee;
        if (dueDate !== "") payload.dueDate = dueDate;
        if (businessSide !== "") payload.businessSide = businessSide;
        if (product !== "") payload.product = product;
        if (country !== "") payload.country = country;
        if (auditStatus !== "") payload.auditStatus = auditStatus;
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
            if (projectVal && !r.projectName.toLowerCase().includes(projectVal)) return false;
            if (fileVal && !r.fileName.toLowerCase().includes(fileVal)) return false;
            if (authorVal && !r.author.toLowerCase().includes(authorVal)) return false;
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
        tr.draggable = true;
        tr.dataset.id = r.id;
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
        tr.innerHTML = `
            <td><input type="checkbox" class="form-check-input record-checkbox" data-id="${r.id}"></td>
            <td class="seq-cell">${idx + 1}</td>
            <td>${r.projectName}</td>
            <td>${r.fileName}</td>
            <td>${r.taskType || "-"}</td>
            <td>${sourceHtml}</td>
            <td>${r.author}</td>
            <td>${dueDateHtml}</td>
            <td>${(r.businessSide != null && r.businessSide !== "") ? r.businessSide : "-"}</td>
            <td>${(r.product != null && r.product !== "") ? r.product : "-"}</td>
            <td>${(r.country != null && r.country !== "") ? r.country : "-"}</td>
            <td>${statusBadge}</td>
            <td>${auditStatusText}</td>
            <td class="text-truncate" style="max-width:100px" title="${(r.notes != null && r.notes !== "") ? r.notes : ""}">${(r.notes != null && r.notes !== "") ? r.notes : "-"}</td>
            <td class="text-truncate" style="max-width:100px" title="${(r.executionNotes != null && r.executionNotes !== "") ? r.executionNotes : ""}">${(r.executionNotes != null && r.executionNotes !== "") ? r.executionNotes : "-"}</td>
            <td>
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
            header1.innerHTML = `<td colspan="16" class="cursor-pointer"><span class="group-toggle">${collapsed1 ? "▶" : "▼"}</span> 项目：${projectName || "（空）"} (${totalProject}条)</td>`;
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
                header2.innerHTML = `<td colspan="16" class="cursor-pointer ps-4"><span class="group-toggle">${collapsed2 ? "▶" : "▼"}</span> 编写人：${authorName || "（空）"} (${arr.length}条)</td>`;
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
            headerTr.innerHTML = `<td colspan="16" class="cursor-pointer"><span class="group-toggle">${collapsed ? "▶" : "▼"}</span> ${label}：${key || "（空）"} (${arr.length}条)</td>`;
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

    App.request("/api/uploads")
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
let myTasksSortKey = "";
let myTasksSortDir = "asc";
let myTasksCollapsedGroups = new Set();

async function initGeneratePage() {
    const myTasksBody = document.getElementById("myTasksBody");
    const noTasksAlert = document.getElementById("noTasksAlert");
    const userInfo = document.getElementById("userInfo");
    const logoutBtn = document.getElementById("logoutBtn");
    const placeholderModal = document.getElementById("placeholderModal");

    if (!myTasksBody) return;

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
            const res = await App.request("/api/my-tasks");
            myTasksCache = res.records || [];
            
            if (myTasksCache.length === 0) {
                noTasksAlert?.classList.remove("d-none");
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
            if (projectVal && !r.projectName.toLowerCase().includes(projectVal)) return false;
            if (fileVal && !r.fileName.toLowerCase().includes(fileVal)) return false;
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
        tr.draggable = true;
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
        const notesDisplay = (r.notes != null && r.notes !== "") ? r.notes : "-";
        const dueDateStyle = getDueDateStyle(r.dueDate);
        const dueDateHtml = dueDateStyle.class
            ? `<span class="badge ${dueDateStyle.class}" title="${dueDateStyle.title || ''}">${dueDateStyle.text}</span>`
            : (r.dueDate || "-");
        tr.innerHTML = `
            <td class="seq-cell">${idx + 1}</td>
            <td>${r.projectName}</td>
            <td>${r.fileName}</td>
            <td>${r.taskType || "-"}</td>
            <td>${sourceTd}</td>
            <td class="task-link-cell">${linkCellHtml}</td>
            <td>${dueDateHtml}</td>
            <td>${(r.businessSide != null && r.businessSide !== "") ? r.businessSide : "-"}</td>
            <td>${(r.product != null && r.product !== "") ? r.product : "-"}</td>
            <td>${(r.country != null && r.country !== "") ? r.country : "-"}</td>
            <td class="text-truncate" style="max-width:80px" title="${notesDisplay !== "-" ? r.notes : ""}">${notesDisplay}</td>
            <td><input type="text" class="form-control form-control-sm execution-notes-input" placeholder="执行备注" data-id="${r.id}" value="${(r.executionNotes != null && r.executionNotes !== "") ? String(r.executionNotes).replace(/"/g, "&quot;") : ""}"></td>
            <td class="completion-status-cell"></td>
            <td>
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
        lastRenderedMyTasks.forEach((r, idx) => addOneRow(r, idx));
    } else {
        const keyFn = groupBy === "project" ? (r) => r.projectName : (r) => r.author;
        const label = groupBy === "project" ? "项目" : "编写人";
        const groupMap = new Map();
        lastRenderedMyTasks.forEach((r) => {
            const k = keyFn(r) || "";
            if (!groupMap.has(k)) groupMap.set(k, []);
            groupMap.get(k).push(r);
        });
        let globalIdx = 0;
        let gidx = 0;
        groupMap.forEach((arr, key) => {
            const collapsed = myTasksCollapsedGroups.has(key);
            const headerTr = document.createElement("tr");
            headerTr.className = "group-header-row bg-light" + (collapsed ? " group-collapsed" : "");
            headerTr.dataset.groupKey = key;
            headerTr.dataset.groupIndex = String(gidx);
            headerTr.innerHTML = `<td colspan="14" style="cursor:pointer"><span class="group-toggle">${collapsed ? "▶" : "▼"}</span> ${label}：${key || "（空）"} (${arr.length}条)</td>`;
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
                if (w) w.value = configResult.weekly || "";
                if (o) o.value = configResult.overdue || "";
                if (p) p.value = configResult.project || "";
            }
            if (scheduleInfo) {
                scheduleInfo.innerHTML = "";
                
                const configured = result.dingtalkConfigured;
                const statusDiv = document.createElement("div");
                statusDiv.className = `p-2 border rounded ${configured ? 'bg-success-subtle border-success' : 'bg-warning-subtle border-warning'}`;
                statusDiv.innerHTML = `
                    <div class="fw-bold small">${configured ? '✓ 钉钉已配置' : '⚠ 钉钉未配置'}</div>
                    <div class="text-muted small">${configured ? '可正常发送通知' : '请设置环境变量 DINGTALK_WEBHOOK'}</div>
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

    document.getElementById("saveScheduleConfigBtn")?.addEventListener("click", async () => {
        const weekly = (document.getElementById("scheduleWeekly")?.value || "").trim() || "thu 16:00";
        const overdue = (document.getElementById("scheduleOverdue")?.value || "").trim() || "15:00";
        const project = (document.getElementById("scheduleProject")?.value || "").trim() || "mon,wed,fri 9:30";
        try {
            await App.request("/api/notify/schedule-config", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ weekly, overdue, project }),
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
                <td class="text-danger">${row.pending}</td>
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
                <td class="text-danger">${row.pending}</td>
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
            tr.innerHTML = `
                <td>${idx + 1}</td>
                <td>${row.label}</td>
                <td class="text-success">${row.completed}</td>
                <td class="text-danger">${row.pending}</td>
                <td>${formatRate(row.rate)}</td>
                <td>${formatStatusBadges(row.byStatus)}</td>
            `;
            projectAuthorBody.appendChild(tr);
        });
    };
    
    const renderDetailTable = (rows) => {
        lastRenderedDetailRows = rows || [];
        tableBody.innerHTML = "";
        const groupBy = (document.querySelector('input[name="detailGroupBy"]:checked') || {}).value || "none";
        
        const addDetailRow = (row, groupKey, groupIndex, collapsed, twoLevelKeys) => {
            const tr = document.createElement("tr");
            tr.draggable = true;
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
            tr.innerHTML = `
                <td class="seq-cell">${row.seq}</td>
                <td>${row.projectName}</td>
                <td>${row.fileName}</td>
                <td>${row.taskType || "-"}</td>
                <td>${row.author}</td>
                <td>${statusHtml}</td>
                <td>${dueDateHtml}</td>
                <td>${(row.businessSide != null && row.businessSide !== "") ? row.businessSide : "-"}</td>
                <td>${(row.product != null && row.product !== "") ? row.product : "-"}</td>
                <td>${(row.country != null && row.country !== "") ? row.country : "-"}</td>
                <td class="text-truncate" style="max-width:100px" title="${(row.notes != null && row.notes !== "") ? row.notes : ""}">${(row.notes != null && row.notes !== "") ? row.notes : "-"}</td>
                <td class="text-truncate" style="max-width:100px" title="${(row.executionNotes != null && row.executionNotes !== "") ? row.executionNotes : ""}">${(row.executionNotes != null && row.executionNotes !== "") ? row.executionNotes : "-"}</td>
                <td>${row.docLink ? `<a href="${row.docLink}" target="_blank" rel="noopener">打开</a>` : "-"}</td>
                <td>
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
                header1.innerHTML = "<td colspan=\"14\" style=\"cursor:pointer\"><span class=\"group-toggle\">" + (collapsed1 ? "▶" : "▼") + "</span> 项目：" + (projectName || "（空）") + " (" + totalProject + "条)</td>";
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
                    header2.innerHTML = "<td colspan=\"14\" style=\"cursor:pointer\" class=\"ps-4\"><span class=\"group-toggle\">" + (collapsed2 ? "▶" : "▼") + "</span> 编写人：" + (authorName || "（空）") + " (" + arr.length + "条)</td>";
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
                headerTr.innerHTML = `<td colspan="14" style="cursor:pointer"><span class="group-toggle">${collapsed ? "▶" : "▼"}</span> ${label}：${key || "（空）"} (${arr.length}条)</td>`;
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
        }
        
        tr.innerHTML = `
            <td>${idx + 1}</td>
            <td>${row.label}</td>
            <td class="text-success">${row.completed}</td>
            <td class="text-danger">${row.pending}</td>
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
        tr.draggable = true;
        tr.dataset.id = row.uploadId;
        
        const statusHtml = row.completionStatus 
            ? `<span class="badge bg-success">${row.completionStatus}</span>`
            : '<span class="badge bg-secondary">未完成</span>';
        const dueDateStyle = getDueDateStyle(row.dueDate);
        const dueDateHtml = dueDateStyle.class 
            ? `<span class="badge ${dueDateStyle.class}" title="${dueDateStyle.title || ''}">${dueDateStyle.text}</span>`
            : (dueDateStyle.text || "-");
        
        tr.innerHTML = `
            <td class="seq-cell">${idx + 1}</td>
            <td>${row.projectName}</td>
            <td>${row.fileName}</td>
            <td>${row.taskType || "-"}</td>
            <td>${row.author}</td>
            <td>${statusHtml}</td>
            <td>${dueDateHtml}</td>
            <td>${(row.businessSide != null && row.businessSide !== "") ? row.businessSide : "-"}</td>
            <td>${(row.product != null && row.product !== "") ? row.product : "-"}</td>
            <td>${(row.country != null && row.country !== "") ? row.country : "-"}</td>
            <td class="text-truncate" style="max-width:100px" title="${(row.notes != null && row.notes !== "") ? row.notes : ""}">${(row.notes != null && row.notes !== "") ? row.notes : "-"}</td>
            <td class="text-truncate" style="max-width:100px" title="${(row.executionNotes != null && row.executionNotes !== "") ? row.executionNotes : ""}">${(row.executionNotes != null && row.executionNotes !== "") ? row.executionNotes : "-"}</td>
            <td>${row.docLink ? `<a href="${row.docLink}" target="_blank" rel="noopener">打开</a>` : "-"}</td>
            <td>
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
                    <small class="text-muted mt-1 d-block">可用变量: {project_name}, {file_name}, {task_type}, {due_date}, {author}, {pending_count}, {assignees}, {task_list}, {task_list_with_links}, {doc_link}, {business_side}, {product}, {country}</small>
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

document.addEventListener("DOMContentLoaded", async () => {
    await loadCompletionStatuses();
    initUploadPage();
    initLoginPage();
    initGeneratePage();
    initDashboardPage();
});
