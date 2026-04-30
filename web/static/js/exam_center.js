(function () {
    function scriptRoot() {
        return (window.__SCRIPT_ROOT__ != null ? String(window.__SCRIPT_ROOT__) : "").replace(/\/+$/, "");
    }

    function escExam(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    /** 截止完成时间展示：与页面3截止日期列配色一致（#FDE2E2 / #C03639）。 */
    function examDueCompletionPillHtml(dueAtIso) {
        if (!dueAtIso) return '<span class="text-muted">—</span>';
        var dueEnd = new Date(String(dueAtIso).trim().replace(" ", "T"));
        if (Number.isNaN(dueEnd.getTime())) return '<span class="text-muted">—</span>';
        var y = dueEnd.getFullYear();
        var m = String(dueEnd.getMonth() + 1).padStart(2, "0");
        var day = String(dueEnd.getDate()).padStart(2, "0");
        var text = y + "-" + m + "-" + day;
        var now = new Date();
        if (now.getTime() > dueEnd.getTime()) {
            return (
                '<span class="exam-due-pill exam-due-pill-overdue" title="已超过截止完成时间">' +
                escExam(text) +
                "</span>"
            );
        }
        var today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        var dueDay0 = new Date(dueEnd.getFullYear(), dueEnd.getMonth(), dueEnd.getDate());
        var diffDays = Math.round((dueDay0.getTime() - today0.getTime()) / 86400000);
        if (diffDays === 0 || diffDays === 1) {
            var ttl = diffDays === 0 ? "今日截止" : "截止日前一天（临期）";
            return (
                '<span class="exam-due-pill exam-due-pill-warn" title="' +
                escExam(ttl) +
                '">' +
                escExam(text) +
                "</span>"
            );
        }
        return '<span class="text-muted small">' + escExam(text) + "</span>";
    }

    function normalizeTrackKey(raw) {
        var s = String(raw || "").trim().toLowerCase();
        if (s === "iso" || s === "13485" || s === "iso_13485") return "iso13485";
        if (s === "china") return "cn";
        if (s === "m_dsap") return "mdsap";
        if (s === "cn" || s === "iso13485" || s === "mdsap") return s;
        return "cn";
    }

    function trackRecommendedPreset(trackRaw) {
        var track = normalizeTrackKey(trackRaw);
        if (track === "iso13485") {
            return { teacherCount: 25, teacherDifficulty: "medium", studentCount: 25, studentDifficulty: "medium" };
        }
        if (track === "mdsap") {
            return { teacherCount: 30, teacherDifficulty: "hard", studentCount: 30, studentDifficulty: "hard" };
        }
        return { teacherCount: 20, teacherDifficulty: "easy", studentCount: 20, studentDifficulty: "easy" };
    }

    function withRoot(path) {
        var root = scriptRoot();
        if (!root || !path || !path.startsWith("/")) return path;
        if (path.startsWith(root + "/")) return path;
        return root + path;
    }

    function roleLabel(role) {
        if (role === "teacher") return "老师端";
        if (role === "analytics") return "统计端";
        return "学生端";
    }

    function currentPathQueryHash() {
        var p = window.location.pathname || "/";
        var q = window.location.search || "";
        var h = window.location.hash || "";
        return p + q + h;
    }

    async function apiRequest(url, method, payload) {
        var fetchOpts = {
            method: method || "GET",
            credentials: "include",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest"
            },
            body: payload ? JSON.stringify(payload) : undefined
        };
        if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
            fetchOpts.signal = AbortSignal.timeout(120000);
        }
        var response = await fetch(withRoot(url), fetchOpts);
        var text = await response.text();
        var data = {};
        try {
            data = text ? JSON.parse(text) : {};
        } catch (e) {
            data = {
                code: "BAD_RESPONSE",
                message: text || "响应解析失败",
                data: null,
                request: { url: withRoot(url), method: method || "GET", upstreamPath: "" }
            };
        }
        // 对齐 aiword 现有交互：当需要登录/访问密码时，自动跳转到对应页面
        // 注意：这里仍返回整包 JSON 供界面展示（含 request.url/trace_id）
        if (response.status === 401 && data && typeof data === "object") {
            var root = scriptRoot();
            if (data.needsLogin) {
                var loginPath = (root || "") + "/login";
                if (window.location.pathname !== loginPath) {
                    window.location.href = loginPath;
                }
            }
            if (data.needsPage13Auth) {
                // 触发后端 gate：整页重载须保留 ?role= / bank_set_id= 等查询串，否则 exam-center 会落回默认 student，老师列表永远不会 fetch
                if (!window._page13Redirecting) {
                    window._page13Redirecting = true;
                    setTimeout(function () {
                        var target = currentPathQueryHash();
                        if (!target || target === "/") {
                            target = (root || "") + "/upload";
                        }
                        window.location.href = target;
                    }, 50);
                }
            }
        }
        // 关键：即使 HTTP 非 2xx，也把后端返回整包展示出来（含 request.url / trace_id）
        // 前端不再丢弃 payload，避免只看到 message 无法排查。
        if (!response.ok) {
            if (data && typeof data === "object") {
                data.__http_status = response.status;
                data.__ok = false;
            }
            return data;
        }
        return data;
    }

    function getExamRole() {
        var cx = window.__EXAM_CENTER_CONTEXT__;
        return cx && cx.role ? String(cx.role).toLowerCase().trim() : "student";
    }

    /** 与老师/学生/统计端切换联动：顶部「返回页面1/2/3」按钮、接口响应卡片显隐（学生端不写 JSON）。 */
    function updateExamChromeForRole(role) {
        role = String(role || "student").toLowerCase().trim();
        document.querySelectorAll("[data-exam-nav-for]").forEach(function (a) {
            var want = String(a.getAttribute("data-exam-nav-for") || "").toLowerCase().trim();
            a.classList.toggle("d-none", want !== role);
        });
        var apiCard = document.getElementById("examApiResultCard");
        if (apiCard) apiCard.classList.toggle("d-none", role === "student");
        var btnH = document.getElementById("btnExamHealth");
        if (btnH) btnH.classList.toggle("d-none", role === "student");
        var px = document.getElementById("examChromeProxyHint");
        if (px) px.classList.toggle("d-none", role === "student");
        var heroSub = document.getElementById("examHeroSubtitle");
        if (heroSub) heroSub.classList.toggle("d-none", role === "student");
    }

    function studentShowFeedback(message, variant) {
        var box = document.getElementById("studentOperationFeedback");
        if (!box) return;
        var msg = String(message == null ? "" : message).trim();
        if (!msg) {
            box.classList.add("d-none");
            box.textContent = "";
            return;
        }
        box.classList.remove(
            "d-none",
            "alert-success",
            "alert-danger",
            "alert-info",
            "alert-warning",
            "alert-light"
        );
        box.classList.add("alert", "border", "mb-0");
        if (variant === "success") box.classList.add("alert-success");
        else if (variant === "danger") box.classList.add("alert-danger");
        else if (variant === "warning") box.classList.add("alert-warning");
        else box.classList.add("alert-info");
        box.textContent = msg;
    }

    /** 学生端：不向「接口响应」面板写入底层 JSON（后续可删掉该面板数据源）；仅在失败时给用户可读提示。 */
    function createStudentAwareRender(baseRender) {
        return function (payload) {
            if (getExamRole() !== "student") {
                baseRender(payload);
                return;
            }
            if (!payload || typeof payload !== "object") return;
            if (payload.code === "UI_ERROR") {
                studentShowFeedback(String(payload.message || "操作失败"), "danger");
                return;
            }
            if (payload.__ok === false) {
                studentShowFeedback(String(payload.message || "请求失败"), "danger");
                return;
            }
        };
    }

    function difficultyLabelZh(code) {
        var c = String(code || "").trim().toLowerCase();
        if (c === "easy") return "简单";
        if (c === "medium") return "中等";
        if (c === "hard") return "困难";
        return "—";
    }

    /** 与页面2（/generate）同源：会话用户展示名取自 /api/me。 */
    async function refreshExamCenterUserDisplay() {
        var el = document.getElementById("examCurrentUserLabel");
        if (!el) return;
        try {
            var me = await apiRequest("/api/me", "GET");
            if (!me || !me.loggedIn || !me.user) return;
            var u = me.user;
            var t = String(u.displayName || "").trim();
            if (!t) t = String(u.username || "").trim();
            if (!t && u.id != null) t = String(u.id);
            if (t) el.textContent = t;
        } catch (e0) {}
    }

    function bindRoleSwitch(ctx, onRoleChange) {
        var rawAllowed = Array.isArray(ctx.allowedRoles) ? ctx.allowedRoles : [];
        var initial = String((ctx && ctx.role) || "student").trim().toLowerCase();
        if (rawAllowed.indexOf(initial) === -1) {
            initial = rawAllowed.length ? String(rawAllowed[0]).trim().toLowerCase() : "student";
        }
        var role = initial;
        var label = document.getElementById("examCurrentRoleLabel");
        var allowed = rawAllowed.length ? rawAllowed : [role];

        function activate(nextRole) {
            role = String(nextRole || "student").trim().toLowerCase();
            if (window.__EXAM_CENTER_CONTEXT__) {
                window.__EXAM_CENTER_CONTEXT__.role = role;
            }
            if (label) label.textContent = roleLabel(role);
            updateExamChromeForRole(role);
            ["teacher", "student", "analytics"].forEach(function (r) {
                var panel = document.getElementById("examRole" + r.charAt(0).toUpperCase() + r.slice(1));
                if (!panel) return;
                panel.classList.toggle("d-none", r !== role);
            });
            document.querySelectorAll(".exam-role-btn").forEach(function (btn) {
                var active = btn.dataset.role === role;
                btn.classList.toggle("btn-primary", active);
                btn.classList.toggle("btn-outline-primary", !active);
            });
            if (typeof onRoleChange === "function") {
                try {
                    onRoleChange(role);
                } catch (e) {}
            }
        }

        document.querySelectorAll(".exam-role-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var targetRole = String(btn.dataset.role || "").trim().toLowerCase();
                if (allowed.indexOf(targetRole) === -1) return;
                activate(targetRole);
            });
        });
        activate(role);
    }

    function bindOutput() {
        var resultBox = document.getElementById("examApiResult");
        return function (payload) {
            if (!resultBox) return;
            resultBox.textContent = JSON.stringify(payload, null, 2);
        };
    }

    function readValue(id) {
        var el = document.getElementById(id);
        return el ? String(el.value || "").trim() : "";
    }

    function readInt(id, fallback) {
        var raw = readValue(id);
        var n = parseInt(raw, 10);
        if (!Number.isFinite(n) || n <= 0) return fallback;
        return n;
    }

    function setButtonLoading(btn, loading, loadingText) {
        if (!btn) return;
        if (loading) {
            if (!btn.dataset.origText) btn.dataset.origText = btn.textContent || "";
            btn.disabled = true;
            btn.textContent = loadingText || "处理中…";
            btn.classList.add("disabled");
        } else {
            btn.disabled = false;
            btn.classList.remove("disabled");
            if (btn.dataset.origText) btn.textContent = btn.dataset.origText;
        }
    }

    function setIngestProgress(visible, text) {
        var box = document.getElementById("teacherIngestProgress");
        var el = document.getElementById("teacherIngestProgressText");
        var stopBtn = document.getElementById("btnTeacherIngestStop");
        if (box) box.classList.toggle("d-none", !visible);
        if (el && text != null) el.textContent = String(text);
        if (stopBtn) stopBtn.classList.toggle("d-none", !visible);
    }

    function setReviewProgress(visible, text) {
        var box = document.getElementById("teacherReviewProgress");
        var el = document.getElementById("teacherReviewProgressText");
        var stopBtn = document.getElementById("btnTeacherReviewStop");
        if (box) box.classList.toggle("d-none", !visible);
        if (el && text != null) el.textContent = String(text);
        if (stopBtn) stopBtn.classList.toggle("d-none", !visible);
    }

    function pickJobId(resp) {
        // 兼容多种返回形状：data.job_id / data.jobId / data.data.job_id ...
        if (!resp || typeof resp !== "object") return "";
        var d = resp.data;
        if (d && typeof d === "object") {
            if (d.job_id) return String(d.job_id);
            if (d.jobId) return String(d.jobId);
            if (d.job_record && typeof d.job_record === "object") {
                if (d.job_record.upstream_job_id) return String(d.job_record.upstream_job_id);
                if (d.job_record.job_id) return String(d.job_record.job_id);
            }
            if (d.jobRecord && typeof d.jobRecord === "object") {
                if (d.jobRecord.upstream_job_id) return String(d.jobRecord.upstream_job_id);
                if (d.jobRecord.job_id) return String(d.jobRecord.job_id);
            }
            if (d.data && typeof d.data === "object") {
                if (d.data.job_id) return String(d.data.job_id);
                if (d.data.jobId) return String(d.data.jobId);
                if (d.data.job && typeof d.data.job === "object") {
                    if (d.data.job.id) return String(d.data.job.id);
                    if (d.data.job.job_id) return String(d.data.job.job_id);
                }
            }
        }
        if (resp.job_id) return String(resp.job_id);
        if (resp.jobId) return String(resp.jobId);
        return "";
    }

    function pickJobStatus(jobResp) {
        // 约定：done/failed；如果上游是 status 字段，也兼容
        if (!jobResp || typeof jobResp !== "object") return "";
        var d = jobResp.data;
        if (d && typeof d === "object") {
            if (d.job_record && typeof d.job_record === "object" && d.job_record.status) {
                return String(d.job_record.status).toLowerCase();
            }
            if (d.jobRecord && typeof d.jobRecord === "object" && d.jobRecord.status) {
                return String(d.jobRecord.status).toLowerCase();
            }
            if (d.status) return String(d.status).toLowerCase();
            if (d.state) return String(d.state).toLowerCase();
            if (d.job_status) return String(d.job_status).toLowerCase();
            if (d.jobStatus) return String(d.jobStatus).toLowerCase();
            if (d.data && typeof d.data === "object") {
                var inner = d.data;
                if (inner.status) return String(inner.status).toLowerCase();
                if (inner.state) return String(inner.state).toLowerCase();
                if (inner.job_status) return String(inner.job_status).toLowerCase();
                if (inner.jobStatus) return String(inner.jobStatus).toLowerCase();
                if (inner.job && typeof inner.job === "object") {
                    var j = inner.job;
                    if (j.status) return String(j.status).toLowerCase();
                    if (j.state) return String(j.state).toLowerCase();
                }
            }
        }
        return "";
    }

    function pickSetIdFromResp(resp) {
        if (!resp || typeof resp !== "object") return "";
        var jr = resp.data && resp.data.job_record ? resp.data.job_record : null;
        if (jr && typeof jr === "object") {
            if (jr.upstream_set_id) return String(jr.upstream_set_id);
            if (jr.upstreamSetId) return String(jr.upstreamSetId);
            if (jr.set_id) return String(jr.set_id);
            if (jr.setId) return String(jr.setId);
        }
        var d = resp.data;
        if (d && typeof d === "object") {
            if (d.set_id) return String(d.set_id);
            if (d.setId) return String(d.setId);
            if (d.data && typeof d.data === "object") {
                if (d.data.set_id) return String(d.data.set_id);
                if (d.data.setId) return String(d.data.setId);
            }
        }
        return "";
    }

    function autofillTeacherSetIdIfEmpty(setId) {
        var input = document.getElementById("teacherSetId");
        if (!input || !setId) return;
        var cur = String(input.value || "").trim();
        if (!cur) input.value = String(setId);
    }

    function maybeAutofillSetIdFromAnyResp(resp) {
        var sid = pickSetIdFromResp(resp);
        if (sid) autofillTeacherSetIdIfEmpty(sid);
    }

    function sleep(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    function bindTeacherActions(render) {
        var btnGenerate = document.getElementById("btnTeacherGenerateSet");
        var btnIngest = document.getElementById("btnTeacherIngestBank");
        var btnIngestStop = document.getElementById("btnTeacherIngestStop");
        var btnReview = document.getElementById("btnTeacherReviewSet");
        var btnPublish = document.getElementById("btnTeacherPublishSet");
        var btnJobsRefresh = document.getElementById("btnTeacherIngestJobsRefresh");
        var selJobsLimit = document.getElementById("teacherIngestJobsLimit");
        var tbodyJobs = document.getElementById("teacherIngestJobsBody");
        var btnReviewStop = document.getElementById("btnTeacherReviewStop");
        var btnReviewJobsRefresh = document.getElementById("btnTeacherReviewJobsRefresh");
        var selReviewJobsLimit = document.getElementById("teacherReviewJobsLimit");
        var tbodyReviewJobs = document.getElementById("teacherReviewJobsBody");
        var ingestState = { running: false, stop: false, jobId: "", lastJobStatus: "" };
        var reviewState = { running: false, stop: false, jobId: "", lastJobStatus: "" };

        var bankState = { offset: 0, total: 0, limit: 50 };
        var currentSetIdForDetail = "";
        var btnSetsRefresh = document.getElementById("btnTeacherSetsRefresh");
        var inputSetSearch = document.getElementById("teacherSetSearch");
        var tbodySets = document.getElementById("teacherSetsBody");
        var chkSetsAll = document.getElementById("teacherSetsCheckAll");
        var btnBatchReview = document.getElementById("btnTeacherBatchReview");
        var btnBatchAssign = document.getElementById("btnTeacherBatchAssign");
        var btnBatchPublish = document.getElementById("btnTeacherBatchPublish");
        var btnBatchDelete = document.getElementById("btnTeacherBatchDelete");
        var selBankCollection = document.getElementById("teacherBankCollection");
        var selBankIsActive = document.getElementById("teacherBankIsActive");
        var inputBankSetId = document.getElementById("teacherBankFilterSetId");
        var btnBankClearSet = document.getElementById("btnTeacherBankClearSetFilter");
        var bankSectionEl = document.getElementById("examTeacherBankSection");
        var inputBankQ = document.getElementById("teacherBankQ");
        var btnBankRefresh = document.getElementById("btnTeacherBankRefresh");
        var btnBankBatchDeactivate = document.getElementById("btnTeacherBankBatchDeactivate");
        var selBankLimit = document.getElementById("teacherBankLimit");
        var btnBankPrev = document.getElementById("btnTeacherBankPrev");
        var btnBankNext = document.getElementById("btnTeacherBankNext");
        var bankMeta = document.getElementById("teacherBankMeta");
        var bankBody = document.getElementById("teacherBankBody");
        var bankCheckAll = document.getElementById("teacherBankCheckAll");
        var modalBankEl = document.getElementById("teacherBankEditModal");
        var btnBankSave = document.getElementById("btnTeacherBankSave");
        var setDetailModalEl = document.getElementById("teacherSetDetailModal");
        var setDetailMetaEl = document.getElementById("teacherSetDetailMeta");
        var setDetailItemsBody = document.getElementById("teacherSetDetailItemsBody");
        var btnSetDetailBankFilter = document.getElementById("btnTeacherSetDetailBankFilter");
        var btnSetDetailReview = document.getElementById("btnTeacherSetDetailReview");
        var btnSetDetailPublish = document.getElementById("btnTeacherSetDetailPublish");
        var btnSetDetailDelete = document.getElementById("btnTeacherSetDetailDelete");
        var btnIssuedRefresh = document.getElementById("btnTeacherIssuedAssignmentsRefresh");
        var tbodyIssued = document.getElementById("teacherIssuedAssignmentsBody");
        // 下发任务改为弹窗表单（截止/目的/对象）
        var assignModalEl = document.getElementById("teacherAssignIssueModal");
        var assignModalDue = document.getElementById("teacherAssignModalDueDate");
        var assignModalPurpose = document.getElementById("teacherAssignModalPurpose");
        var assignModalUsers = document.getElementById("teacherAssignModalUsers");
        var assignModalSets = document.getElementById("teacherAssignModalSets");
        var assignModalSearch = document.getElementById("teacherAssignModalUserSearch");
        var btnAssignModalSelectAll = document.getElementById("btnTeacherAssignModalSelectAll");
        var btnAssignModalClearAll = document.getElementById("btnTeacherAssignModalClearAll");
        var btnAssignModalSubmit = document.getElementById("btnTeacherAssignModalSubmit");
        var assignModal = null;
        var teacherSetTitleMap = {};
        var assignModalState = { setIds: [], items: [] };
        var btnCheckReq = document.getElementById("btnTeacherCheckRequirements");
        var btnMarkReqBase = document.getElementById("btnTeacherMarkRequirementBaseline");
        var requirementBox = document.getElementById("teacherRequirementStatus");
        var selTrack = document.getElementById("teacherExamTrack");
        var inputTeacherCount = document.getElementById("teacherQuestionCount");
        var selTeacherDifficulty = document.getElementById("teacherDifficulty");
        var inputPolicyVersion = document.getElementById("teacherRegPolicyVersion");
        var btnSavePolicyVersion = document.getElementById("btnTeacherSavePolicyVersion");
        if (btnSetDetailReview) {
            btnSetDetailReview.title =
                "套题级 AI 复审：调用上游按 set_id 批量处理本套全部题目。逐题编辑推荐下方题库「修改」。";
        }
        if (btnSetDetailPublish) {
            btnSetDetailPublish.title =
                "同步：将套题同步到上游可用状态（显示为“已同步”），供学生端练习或挂载考试任务（以上游为准）；不是自动创建一场独立「正式考试」记录。";
        }

        function isNonTerminalIngestStatus(st) {
            var s = String(st || "").toLowerCase();
            if (!s) return false;
            if (s === "done" || s === "success" || s === "completed" || s === "finished") return false;
            if (s === "failed" || s === "error") return false;
            if (s === "unknown") return false;
            return true;
        }

        async function refreshIngestJobGateState(setId) {
            // 复审/发布前：尽量用最新上游状态判断 ingest 是否仍在 running（避免仅依赖页面轮询时的缓存状态）
            var sid = String(setId || "").trim();
            var jid = String(ingestState.jobId || "").trim();
            if (jid) {
                var jr = await apiRequest("/api/exam-center/teacher/bank/ingest-jobs/" + encodeURIComponent(jid) + "?refresh=1", "GET");
                ingestState.lastJobStatus = pickJobStatus(jr) || ingestState.lastJobStatus;
                maybeAutofillSetIdFromAnyResp(jr);
                return ingestState.lastJobStatus;
            }
            if (!sid) return ingestState.lastJobStatus;
            var list = await apiRequest("/api/exam-center/teacher/bank/ingest-jobs?limit=50", "GET");
            var jobs = list && list.data && list.data.jobs ? list.data.jobs : null;
            if (!jobs || !jobs.length) return ingestState.lastJobStatus;
            var hit = null;
            for (var i = 0; i < jobs.length; i++) {
                var j = jobs[i];
                if (!j || typeof j !== "object") continue;
                var jsid = String(j.upstream_set_id || j.set_id || j.setId || "").trim();
                if (jsid && jsid === sid) {
                    hit = j;
                    break;
                }
            }
            if (!hit || !hit.upstream_job_id) return ingestState.lastJobStatus;
            var jr2 = await apiRequest("/api/exam-center/teacher/bank/ingest-jobs/" + encodeURIComponent(String(hit.upstream_job_id)) + "?refresh=1", "GET");
            ingestState.lastJobStatus = pickJobStatus(jr2) || String(hit.status || "").toLowerCase() || ingestState.lastJobStatus;
            maybeAutofillSetIdFromAnyResp(jr2);
            return ingestState.lastJobStatus;
        }

        function escHtml(s) {
            return String(s == null ? "" : s)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;");
        }

        function applyTeacherTrackDefaults() {
            // 体考类型联动题量/难度（仅影响「来一套」的输入框默认值；录题不读取这些下拉/输入）
            var preset = trackRecommendedPreset(readValue("teacherExamTrack") || "cn");
            if (inputTeacherCount) inputTeacherCount.value = String(preset.teacherCount);
            if (selTeacherDifficulty) selTeacherDifficulty.value = String(preset.teacherDifficulty);
        }

        function requirementTopicText(rows) {
            if (!Array.isArray(rows) || !rows.length) return "—";
            var bad = [];
            rows.forEach(function (r) {
                if (!r || r.is_met === true) return;
                var topic = String(r.topic || "未知主题");
                bad.push(topic);
            });
            return bad.length ? ("缺失：" + bad.join("、")) : "已覆盖";
        }

        async function loadTeacherPolicyVersion() {
            if (!inputPolicyVersion) return;
            var track = normalizeTrackKey(readValue("teacherExamTrack") || "cn");
            try {
                var d = await apiRequest(
                    "/api/exam-center/teacher/bank/policy-version?exam_track=" + encodeURIComponent(track),
                    "GET"
                );
                if (d && d.__ok === false) return;
                var pv = d && d.data ? String(d.data.policy_version || "") : "";
                var autoPv = d && d.data ? String(d.data.auto_policy_version || "") : "";
                var src = d && d.data ? String(d.data.policy_version_source || "none") : "none";
                inputPolicyVersion.value = pv;
                if (autoPv) {
                    inputPolicyVersion.title = "当前自动识别版本：" + autoPv + "（来源：" + src + "）";
                } else {
                    inputPolicyVersion.title = "当前未识别到自动版本，可填写兜底版本。";
                }
            } catch (e) {}
        }

        async function saveTeacherPolicyVersion() {
            var track = normalizeTrackKey(readValue("teacherExamTrack") || "cn");
            var pv = inputPolicyVersion ? String(inputPolicyVersion.value || "").trim() : "";
            var d = await apiRequest("/api/exam-center/teacher/bank/policy-version", "PUT", {
                exam_track: track,
                policy_version: pv
            });
            render(d);
            return d;
        }

        async function loadTeacherRequirementStatus() {
            if (!requirementBox) return;
            var track = normalizeTrackKey(readValue("teacherExamTrack") || "cn");
            requirementBox.innerHTML = '<span class="text-muted">检查中…</span>';
            try {
                var d = await apiRequest(
                    "/api/exam-center/teacher/bank/requirements-check?exam_track=" + encodeURIComponent(track),
                    "GET"
                );
                render(d);
                if (d && d.__ok === false) {
                    requirementBox.innerHTML = '<span class="text-danger">检查失败：' + escHtml(d.message || "请求失败") + "</span>";
                    return;
                }
                var x = d && d.data && typeof d.data === "object" ? d.data : {};
                var met = x.is_satisfied === true;
                var title = escHtml(String(x.track_label || track));
                var total = Number(x.bank_total || 0);
                var target = Number(x.required_min_total || 0);
                var topicTxt = requirementTopicText(x.topic_checks || []);
                var km = x.knowledge_markers && typeof x.knowledge_markers === "object" ? x.knowledge_markers : {};
                var effectivePv = km.current_policy_version ? escHtml(String(km.current_policy_version)) : "未设置";
                var autoPv = km.auto_policy_version ? escHtml(String(km.auto_policy_version)) : "未识别";
                var fallbackPv = km.fallback_policy_version ? escHtml(String(km.fallback_policy_version)) : "未配置";
                var policySource = km.policy_version_source ? String(km.policy_version_source) : "none";
                var policyConf = km.policy_version_confidence ? escHtml(String(km.policy_version_confidence)) : "none";
                var ev = km.policy_version_evidence && typeof km.policy_version_evidence === "object" ? km.policy_version_evidence : null;
                var sourceZh = policySource === "auto" ? "自动识别" : (policySource === "fallback" ? "兜底配置" : "未命中");
                var evTxt = "无";
                if (ev) {
                    var evFile = String(ev.file_name || "").trim();
                    var evBy = String(ev.matched_by || "").trim();
                    var evToken = String(ev.matched_token || "").trim();
                    evTxt = (evFile || "未知文件") + (evBy ? (" / " + evBy) : "") + (evToken ? (" / " + evToken) : "");
                }
                var reasons = Array.isArray(x.reasons) ? x.reasons : [];
                var reasonHtml = reasons.length
                    ? '<div class="mt-1 text-danger">未达标原因：' + escHtml(reasons.join("；")) + "</div>"
                    : '<div class="mt-1 text-success">达标：可继续录题增强覆盖，或停止录题。</div>';
                var style = met ? "text-success" : "text-danger";
                requirementBox.innerHTML =
                    '<div><strong>' + title + "</strong>：" +
                    '<span class="' + style + '">' + (met ? "已满足体考要求" : "尚未满足体考要求") + "</span>" +
                    "；题量 " + escHtml(String(total)) + "/" + escHtml(String(target)) +
                    "；主题覆盖：" + escHtml(topicTxt) +
                    "；法规版本（生效）：" + effectivePv + "（来源：" + escHtml(sourceZh) + "）" +
                    "；自动识别：" + autoPv + "；兜底配置：" + fallbackPv +
                    "；识别置信度：" + policyConf +
                    "；识别证据：" + escHtml(evTxt) +
                    "；建议批次：每次 " + escHtml(String(x.next_batch_target_count || 50)) + " 题。</div>" +
                    reasonHtml;
            } catch (e) {
                requirementBox.innerHTML = '<span class="text-danger">检查异常：' + escHtml(e.message || String(e)) + "</span>";
            }
        }

        async function markTeacherRequirementBaseline() {
            var track = normalizeTrackKey(readValue("teacherExamTrack") || "cn");
            var d = await apiRequest("/api/exam-center/teacher/bank/requirements-baseline", "POST", { exam_track: track });
            render(d);
            if (d && d.__ok === false) {
                if (requirementBox) requirementBox.innerHTML = '<span class="text-danger">设置基线失败：' + escHtml(d.message || "请求失败") + "</span>";
                return;
            }
            await loadTeacherRequirementStatus();
        }

        function safeJson(v) {
            try {
                return JSON.stringify(v, null, 2);
            } catch (e) {
                return String(v);
            }
        }

        function jsonTryParseOrString(raw) {
            var t = String(raw == null ? "" : raw).trim();
            if (!t) return null;
            try {
                return JSON.parse(t);
            } catch (e) {
                return t;
            }
        }

        function pickSetStatusFromUpstream(s) {
            if (!s || typeof s !== "object") return "";
            var cands = [
                s.status,
                s.state,
                s.publish_status,
                s.publishStatus,
                s.set_status,
                s.setStatus,
                s.review_status,
                s.reviewStatus,
                s.lifecycle,
                s.exam_status,
                s.examStatus
            ];
            var i;
            for (i = 0; i < cands.length; i++) {
                if (cands[i] != null && String(cands[i]).trim() !== "") return String(cands[i]).trim();
            }
            var meta = s.meta || s.metadata;
            if (meta && typeof meta === "object") {
                var m = meta.status || meta.state || meta.publish_status || meta.publishStatus;
                if (m != null && String(m).trim() !== "") return String(m).trim();
            }
            return "";
        }

        function normalizeSetRow(s) {
            if (!s || typeof s !== "object") return { id: "", title: "", status: "", createdAt: "" };
            var id = String(s.set_id || s.setId || s.id || "").trim();
            var title = String(s.title || s.name || "").trim();
            var status = pickSetStatusFromUpstream(s);
            var createdAt = String(s.created_at || s.createdAt || s.created || "").trim();
            return { id: id, title: title, status: status, createdAt: createdAt };
        }

        function pickSetsArray(resp) {
            var d = resp && resp.data;
            if (!d || typeof d !== "object") return [];
            var inner = d.data && typeof d.data === "object" ? d.data : null;
            var cands = [
                d.items,
                d.sets,
                d.list,
                inner && (inner.items || inner.sets || inner.list),
                Array.isArray(d.data) ? d.data : null
            ];
            var i;
            for (i = 0; i < cands.length; i++) {
                if (Array.isArray(cands[i])) return cands[i];
            }
            return [];
        }

        function pickTeacherSetLoadSet(up) {
            if (!up || typeof up !== "object") return null;
            var inner = up.data;
            if (inner && typeof inner === "object") {
                if (inner.load_set && typeof inner.load_set === "object") return inner.load_set;
                if (inner.set && typeof inner.set === "object") return inner.set;
                if (Array.isArray(inner.items) || Array.isArray(inner.questions)) return inner;
                if (inner.data && typeof inner.data === "object") return pickTeacherSetLoadSet(inner);
            }
            if (up.load_set && typeof up.load_set === "object") return up.load_set;
            if (up.set && typeof up.set === "object") return up.set;
            if (Array.isArray(up.items) || Array.isArray(up.questions)) return up;
            return inner && typeof inner === "object" ? inner : up;
        }

        function pickSetDetailItemsArray(loadSet) {
            if (!loadSet || typeof loadSet !== "object") return [];
            var arr =
                loadSet.items ||
                loadSet.questions ||
                loadSet.question_items ||
                loadSet.questionItems ||
                loadSet.entries;
            return Array.isArray(arr) ? arr : [];
        }

        function setDetailRowHtml(item, idx) {
            var orderNo = item.order_no != null ? item.order_no : item.orderNo != null ? item.orderNo : idx + 1;
            var stem = String(item.stem || item.title || "").trim();
            if (!stem && typeof item.question === "string") stem = String(item.question).trim();
            if (!stem && item.question && typeof item.question === "object") {
                var qq = item.question;
                stem = String(qq.stem || qq.title || qq.content || "").trim();
            }
            var score = item.score != null ? item.score : "";
            var ans = item.answer != null ? item.answer : "";
            var ansText = typeof ans === "object" ? safeJson(ans) : String(ans);
            var details = {
                question_id: item.question_id || item.questionId,
                options: item.options,
                explanation: item.explanation,
                evidence: item.evidence
            };
            var detailsText = safeJson(details);
            return (
                "<tr>" +
                '<td class="small">' +
                escHtml(orderNo) +
                "</td>" +
                '<td class="small">' +
                '<div class="fw-semibold">' +
                escHtml(stem || "—") +
                '</div><details class="mt-1"><summary class="small text-muted">展开</summary>' +
                '<pre class="exam-api-result mt-2" style="max-height:180px;">' +
                escHtml(detailsText) +
                "</pre></details></td>" +
                '<td class="small">' +
                escHtml(score) +
                "</td>" +
                '<td class="small"><pre class="mb-0" style="white-space:pre-wrap;max-height:160px;overflow:auto;">' +
                escHtml(ansText) +
                "</pre></td></tr>"
            );
        }

        function isLikelySetPublished(statusRaw) {
            var s = String(statusRaw || "").toLowerCase();
            if (!s) return false;
            // 严格判定“终态已同步”，避免 unpublished / publish_pending 被误判
            return (
                s === "published" ||
                s === "synced" ||
                s === "sync_success" ||
                s === "已发布" ||
                s === "已同步" ||
                s === "同步成功"
            );
        }

        function syncTeacherPublishButtonUi(btn, statusRaw) {
            if (!btn) return;
            var pub = isLikelySetPublished(statusRaw);
            btn.disabled = pub;
            btn.textContent = pub ? "已同步" : "同步";
            btn.className = pub ? "btn btn-sm btn-outline-secondary" : "btn btn-sm btn-success";
        }

        function syncSetDetailPublishButton(statusRaw) {
            syncTeacherPublishButtonUi(btnSetDetailPublish, statusRaw);
        }

        function ensureAssignModal() {
            try {
                if (assignModalEl && window.bootstrap && window.bootstrap.Modal) {
                    if (!assignModal) assignModal = window.bootstrap.Modal.getOrCreateInstance(assignModalEl);
                }
            } catch (e0) {}
            return assignModal;
        }

        async function loadAssignableUsersIntoModal() {
            if (!assignModalUsers) return;
            assignModalUsers.innerHTML = '<div class="text-muted small">加载中…</div>';
            try {
                var resp = await apiRequest("/api/users", "GET");
                if (resp && resp.__ok === false) {
                    assignModalUsers.innerHTML = '<div class="text-danger small">' + escHtml(resp.message || "加载失败") + "</div>";
                    return;
                }
                // 兼容：/api/users 返回 {users:[...]}（页面1使用） vs {data:{users:[...]}}（部分接口风格）
                var rows = [];
                if (resp && resp.data && Array.isArray(resp.data.users)) rows = resp.data.users;
                else if (resp && Array.isArray(resp.users)) rows = resp.users;
                if (!rows.length) {
                    assignModalUsers.innerHTML = '<div class="text-muted small">暂无人员（请先在页面1录入/管理用户）。</div>';
                    return;
                }
                var html = [];
                rows.forEach(function (u) {
                    if (!u || typeof u !== "object") return;
                    var uid = String(u.id || "").trim();
                    if (!uid) return;
                    var dn = String(u.display_name || u.displayName || "").trim();
                    var un = String(u.username || "").trim();
                    var label = (dn || un || uid).trim();
                    html.push(
                        '<label class="d-flex align-items-center gap-2 user-row" data-key="' +
                            escHtml((label + " " + un).toLowerCase()) +
                            '"><input type="checkbox" class="form-check-input assign-user" value="' +
                            escHtml(uid) +
                            '"><span>' +
                            escHtml(label) +
                            (un && dn ? ' <span class="text-muted">(' + escHtml(un) + ")</span>" : "") +
                            "</span></label>"
                    );
                });
                assignModalUsers.innerHTML = html.join("") || '<div class="text-muted small">暂无可选人员。</div>';
            } catch (e) {
                assignModalUsers.innerHTML = '<div class="text-danger small">' + escHtml(e.message || "加载失败") + "</div>";
            }
        }

        function filterAssignModalUsers() {
            if (!assignModalUsers) return;
            var kw = assignModalSearch ? String(assignModalSearch.value || "").trim().toLowerCase() : "";
            var rows = assignModalUsers.querySelectorAll(".user-row");
            rows.forEach(function (r) {
                var k = String(r.getAttribute("data-key") || "");
                r.style.display = !kw || k.indexOf(kw) >= 0 ? "" : "none";
            });
        }

        function collectAssignModalUserIds() {
            if (!assignModalUsers) return [];
            var ids = [];
            assignModalUsers.querySelectorAll('input.assign-user[type="checkbox"]:checked').forEach(function (c) {
                var v = String(c.value || "").trim();
                if (v) ids.push(v);
            });
            return ids;
        }

        async function openIssueAssignmentsModal(setIds) {
            var ids = Array.isArray(setIds) ? setIds : [];
            ids = ids.map(function (x) { return String(x || "").trim(); }).filter(function (x) { return x; });
            if (!ids.length) throw new Error("请选择至少一个套题再下发");
            assignModalState.setIds = ids.slice();
            assignModalState.items = ids.map(function (sid) {
                return { set_id: sid, title: teacherSetTitleMap[sid] || "" };
            });
            if (assignModalSets) {
                assignModalSets.textContent = ids.join("，");
            }
            if (assignModalDue) assignModalDue.value = "";
            if (assignModalPurpose) assignModalPurpose.value = "";
            if (assignModalSearch) assignModalSearch.value = "";
            await loadAssignableUsersIntoModal();
            filterAssignModalUsers();
            var m = ensureAssignModal();
            if (m) m.show();
        }

        function syncBankSetIdToUrl(raw) {
            try {
                var u = new URL(window.location.href);
                var v = String(raw == null ? "" : raw).trim();
                if (v) u.searchParams.set("bank_set_id", v);
                else u.searchParams.delete("bank_set_id");
                if (history && history.replaceState) history.replaceState(null, "", u.pathname + u.search + u.hash);
            } catch (e0) {}
        }

        function applyBankSetFilterFromUrl() {
            if (!inputBankSetId) return;
            try {
                var u = new URL(window.location.href);
                var v = (u.searchParams.get("bank_set_id") || u.searchParams.get("set_id") || "").trim();
                if (v) inputBankSetId.value = v;
            } catch (e1) {}
        }

        function bankQuery() {
            var q = {};
            var collection = selBankCollection ? String(selBankCollection.value || "").trim() : "";
            if (collection) q.collection = collection;
            var isActive = selBankIsActive ? String(selBankIsActive.value || "").trim() : "";
            if (isActive !== "") q.is_active = isActive;
            var kw = inputBankQ ? String(inputBankQ.value || "").trim() : "";
            if (kw) q.q = kw;
            var limit = selBankLimit ? parseInt(selBankLimit.value || "50", 10) : 50;
            if (!Number.isFinite(limit) || limit < 1) limit = 50;
            if (limit > 200) limit = 200;
            bankState.limit = limit;
            q.limit = String(limit);
            q.offset = String(bankState.offset || 0);
            var setF = inputBankSetId ? String(inputBankSetId.value || "").trim() : "";
            if (setF) {
                q.set_id = setF;
                q.bank_set_id = setF;
            }
            return q;
        }

        function bankMutationQueryString() {
            var coll = selBankCollection ? String(selBankCollection.value || "").trim() : "";
            var parts = ["collection=" + encodeURIComponent(coll || "regulations")];
            var sid = inputBankSetId ? String(inputBankSetId.value || "").trim() : "";
            if (sid) parts.push("set_id=" + encodeURIComponent(sid));
            return parts.join("&");
        }

        function bankSelectedIds() {
            var ids = [];
            if (!bankBody) return ids;
            bankBody.querySelectorAll('input[type="checkbox"][data-qid]:checked').forEach(function (c) {
                var id = String(c.dataset.qid || "").trim();
                if (id) ids.push(id);
            });
            return ids;
        }

        function jumpToBankBySetId(sid, closeSetDetail) {
            sid = String(sid || "").trim();
            if (!sid || !inputBankSetId) return;
            inputBankSetId.value = sid;
            syncBankSetIdToUrl(sid);
            bankState.offset = 0;
            loadTeacherBankQuestions();
            if (closeSetDetail && setDetailModalEl && window.__setDetailModal && typeof window.__setDetailModal.hide === "function") {
                window.__setDetailModal.hide();
            }
            if (bankSectionEl && bankSectionEl.scrollIntoView) {
                try {
                    bankSectionEl.scrollIntoView({ behavior: "smooth", block: "start" });
                } catch (e4) {}
            }
        }

        async function openSetDetail(setId) {
            currentSetIdForDetail = String(setId || "").trim();
            if (!currentSetIdForDetail) return;
            syncSetDetailPublishButton("");
            if (setDetailMetaEl) setDetailMetaEl.textContent = "加载中… set_id=" + currentSetIdForDetail;
            if (setDetailItemsBody) {
                setDetailItemsBody.innerHTML = '<tr><td colspan="4" class="text-muted small">加载中…</td></tr>';
            }
            if (setDetailModalEl && window.bootstrap && window.bootstrap.Modal) {
                window.__setDetailModal = window.__setDetailModal || new window.bootstrap.Modal(setDetailModalEl);
                window.__setDetailModal.show();
            }
            var resp = await apiRequest("/api/exam-center/teacher/sets/" + encodeURIComponent(currentSetIdForDetail), "GET");
            render(resp);
            var up = resp && resp.data ? resp.data : null;
            var loadSet = pickTeacherSetLoadSet(up || {});
            var title = loadSet ? loadSet.title || loadSet.name || "" : "";
            var status = loadSet ? pickSetStatusFromUpstream(loadSet) : "";
            var track = loadSet ? loadSet.exam_track || loadSet.examTrack || "" : "";
            var itemsPreview = pickSetDetailItemsArray(loadSet || {});
            var cnt = itemsPreview.length;
            if (setDetailMetaEl) {
                setDetailMetaEl.textContent =
                    "set_id=" +
                    currentSetIdForDetail +
                    (title ? "，title=" + title : "") +
                    (track ? "，exam_track=" + track : "") +
                    (status ? "，status=" + status : "") +
                    "，题数=" +
                    cnt;
            }
            syncSetDetailPublishButton(status);
            var items = pickSetDetailItemsArray(loadSet || {});
            if (!setDetailItemsBody) return;
            if (!items.length) {
                setDetailItemsBody.innerHTML =
                    '<tr><td colspan="4" class="text-muted small">暂无题目明细（录题 running 请等 done；或上游返回结构不含 items）。</td></tr>';
                return;
            }
            setDetailItemsBody.innerHTML = items.map(function (it, idx) {
                return setDetailRowHtml(it, idx);
            }).join("");
        }

        function selectedSetIds() {
            var ids = [];
            if (!tbodySets) return ids;
            tbodySets.querySelectorAll('input[type="checkbox"][data-set-id]:checked').forEach(function (c) {
                var sid = String(c.dataset.setId || "").trim();
                if (sid) ids.push(sid);
            });
            return ids;
        }

        async function loadTeacherSets() {
            if (!tbodySets) return;
            tbodySets.innerHTML = '<tr><td colspan="6" class="text-muted small">加载中…</td></tr>';
            try {
                var kw = inputSetSearch ? String(inputSetSearch.value || "").trim() : "";
                var url = "/api/exam-center/teacher/sets";
                if (kw) url += "?q=" + encodeURIComponent(kw);
                var resp = await apiRequest(url, "GET");
                render(resp);
                if (resp && resp.__ok === false) {
                    tbodySets.innerHTML =
                        '<tr><td colspan="6" class="text-danger small">' +
                        escHtml(resp.message || "套题列表请求失败") +
                        "（HTTP " +
                        escHtml(String(resp.__http_status || "?")) +
                        "）</td></tr>";
                    return;
                }
                var ingestBySet =
                    resp && resp.data && resp.data.aiword && resp.data.aiword.ingest_jobs_by_set_id
                        ? resp.data.aiword.ingest_jobs_by_set_id
                        : {};
                var sets = pickSetsArray(resp);
                if ((!sets || !sets.length) && ingestBySet && typeof ingestBySet === "object") {
                    sets = Object.keys(ingestBySet).map(function (sid) {
                        return { set_id: sid, title: "", status: "", created_at: ingestBySet[sid].created_at || "" };
                    });
                }
                if (!Array.isArray(sets) || sets.length === 0) {
                    tbodySets.innerHTML =
                        '<tr><td colspan="6" class="text-muted small">暂无套题数据（上游未实现或返回空）。</td></tr>';
                    return;
                }
                tbodySets.innerHTML = "";
                teacherSetTitleMap = {};
                sets.forEach(function (s) {
                    var row = normalizeSetRow(s);
                    if (!row.id) return;
                    teacherSetTitleMap[row.id] = row.title || "";
                    var jr = ingestBySet && ingestBySet[row.id] ? ingestBySet[row.id] : null;
                    var ingestText = jr ? "job_id=" + (jr.upstream_job_id || "") + " / " + (jr.status || "") : "—";
                    var tr = document.createElement("tr");
                    tr.innerHTML =
                        '<td><input type="checkbox" data-set-id="1"></td>' +
                        '<td class="small">' +
                        escHtml(row.createdAt || (jr && jr.created_at) || "") +
                        "</td>" +
                        '<td class="small"><code>' +
                        escHtml(row.id) +
                        "</code>" +
                        (row.title ? '<div class="text-muted small">' + escHtml(row.title) + "</div>" : "") +
                        "</td>" +
                        '<td class="small"><span class="badge bg-light text-dark">' +
                        escHtml(row.status || "") +
                        "</span></td>" +
                        '<td class="small"><code>' +
                        escHtml(ingestText) +
                        '</code></td><td class="small"><div class="d-flex gap-1 flex-wrap" data-op="1"></div></td>';
                    var chk = tr.querySelector('input[type="checkbox"][data-set-id]');
                    chk.dataset.setId = row.id;
                    tbodySets.appendChild(tr);
                    var op = tr.querySelector("[data-op]");
                    if (!op) return;
                    var b0 = document.createElement("button");
                    b0.type = "button";
                    b0.className = "btn btn-sm btn-outline-primary";
                    b0.textContent = "查看";
                    b0.addEventListener("click", function () {
                        openSetDetail(row.id);
                    });
                    var bBank = document.createElement("button");
                    bBank.type = "button";
                    bBank.className = "btn btn-sm btn-outline-info";
                    bBank.textContent = "题库筛选";
                    bBank.title = "在下方题库中按本套 set_id 筛选";
                    bBank.addEventListener("click", function () {
                        jumpToBankBySetId(row.id, false);
                    });
                    var b1 = document.createElement("button");
                    b1.type = "button";
                    b1.className = "btn btn-sm btn-outline-secondary";
                    b1.textContent = "复审";
                    b1.title =
                        "按「套题」调用上游 AI 复审：对本套内全部题目批量处理（说明/证据等由上游定义）。单题逐条修改请用下方题库「修改」。";
                    b1.addEventListener("click", async function () {
                        var d = await apiRequest("/api/exam-center/teacher/sets/review-by-ai", "POST", { set_id: row.id });
                        render(d);
                        await loadTeacherReviewJobs();
                    });
                    var bAssign = document.createElement("button");
                    bAssign.type = "button";
                    bAssign.className = "btn btn-sm btn-outline-primary";
                    bAssign.textContent = "下发考试任务";
                    bAssign.title = "基于当前套题 set_id 下发考试任务（学生端任务列表可见）";
                    bAssign.addEventListener("click", async function () {
                        try {
                            await openIssueAssignmentsModal([row.id]);
                        } catch (e0) {
                            render({ code: "UI_ERROR", message: e0.message || String(e0), data: null });
                        }
                    });
                    var b2 = document.createElement("button");
                    b2.type = "button";
                    b2.className = "btn btn-sm btn-success";
                    b2.textContent = "同步";
                    b2.title =
                        "将套题同步到上游可用状态（状态显示“已同步”）：学生端可被选为考试任务/练习来源（具体规则以上游 aicheckword 为准）。";
                    syncTeacherPublishButtonUi(b2, row.status);
                    b2.addEventListener("click", async function () {
                        if (b2.disabled) return;
                        var d = await apiRequest("/api/exam-center/teacher/sets/publish", "POST", { set_id: row.id });
                        render(d);
                        await loadTeacherSets();
                    });
                    var b3 = document.createElement("button");
                    b3.type = "button";
                    b3.className = "btn btn-sm btn-outline-danger";
                    b3.textContent = "删除";
                    b3.addEventListener("click", async function () {
                        var d = await apiRequest("/api/exam-center/teacher/sets/" + encodeURIComponent(row.id), "DELETE");
                        render(d);
                        await loadTeacherSets();
                    });
                    op.appendChild(b0);
                    op.appendChild(bBank);
                    op.appendChild(b1);
                    op.appendChild(bAssign);
                    op.appendChild(b2);
                    op.appendChild(b3);
                });
            } catch (e) {
                tbodySets.innerHTML =
                    '<tr><td colspan="6" class="text-danger small">加载失败：' + escHtml(e.message) + "</td></tr>";
            }
        }

        async function loadTeacherBankQuestions() {
            if (!bankBody) return;
            syncBankSetIdToUrl(inputBankSetId ? inputBankSetId.value : "");
            var q = bankQuery();
            var qs = Object.keys(q)
                .map(function (k) {
                    return encodeURIComponent(k) + "=" + encodeURIComponent(String(q[k]));
                })
                .join("&");
            bankBody.innerHTML = '<tr><td colspan="8" class="text-muted small">加载中…</td></tr>';
            try {
                var resp = await apiRequest("/api/exam-center/teacher/bank/questions" + (qs ? "?" + qs : ""), "GET");
                render(resp);
                if (resp && resp.__ok === false) {
                    bankBody.innerHTML =
                        '<tr><td colspan="8" class="text-danger small">' +
                        escHtml(resp.message || "题库列表请求失败") +
                        "（HTTP " +
                        escHtml(String(resp.__http_status || "?")) +
                        "）</td></tr>";
                    return;
                }
                var d = resp && resp.data;
                var items =
                    d && d.items ? d.items : d && d.data && d.data.items ? d.data.items : [];
                var total =
                    d && d.total != null ? d.total : d && d.data && d.data.total != null ? d.data.total : null;
                bankState.total = total != null ? parseInt(total, 10) : 0;
                if (bankMeta) {
                    var bs = inputBankSetId ? String(inputBankSetId.value || "").trim() : "";
                    var metaLine =
                        "total=" +
                        (bankState.total || 0) +
                        "，limit=" +
                        bankState.limit +
                        "，offset=" +
                        (bankState.offset || 0);
                    if (bs) metaLine += "，套题筛选 set_id=" + bs;
                    var dm = d && typeof d === "object" ? d.meta : null;
                    if (dm && dm.aiword_note) metaLine += "；" + String(dm.aiword_note).slice(0, 120);
                    if (bs && (!dm || !dm.aiword_bank_set_filter) && resp && resp.__ok !== false) {
                        metaLine += "（未带 aiword 套题合并标记时，若条数不变请确认后端版本）";
                    }
                    bankMeta.textContent = metaLine;
                }
                if (!Array.isArray(items) || items.length === 0) {
                    bankBody.innerHTML = '<tr><td colspan="8" class="text-muted small">无数据</td></tr>';
                    return;
                }
                bankBody.innerHTML = "";
                items.forEach(function (it) {
                    var qid = String(it.question_id || it.questionId || it.id || "").trim();
                    if (!qid) return;
                    var stem = String(it.stem || it.title || it.content || "").trim();
                    var examTrack = String(it.exam_track || it.examTrack || "").trim();
                    var qt = String(it.question_type || it.questionType || "").trim();
                    var diff = String(it.difficulty || "").trim();
                    var active = it.is_active;
                    var activeText =
                        active === false || active === 0 || String(active).toLowerCase() === "false" ? "否" : "是";
                    var tr = document.createElement("tr");
                    tr.innerHTML =
                        '<td><input type="checkbox" data-qid="1"></td>' +
                        '<td class="small"><code>' +
                        escHtml(qid) +
                        "</code></td>" +
                        '<td class="small" title="' +
                        escHtml(stem) +
                        '">' +
                        escHtml(stem.slice(0, 120)) +
                        (stem.length > 120 ? "…" : "") +
                        "</td>" +
                        '<td class="small">' +
                        escHtml(examTrack) +
                        "</td>" +
                        '<td class="small">' +
                        escHtml(qt) +
                        "</td>" +
                        '<td class="small">' +
                        escHtml(diff) +
                        "</td>" +
                        '<td class="small">' +
                        escHtml(activeText) +
                        '</td><td class="small"><div class="d-flex gap-1 flex-wrap" data-op="1"></div></td>';
                    var c = tr.querySelector('input[type="checkbox"][data-qid]');
                    c.dataset.qid = qid;
                    bankBody.appendChild(tr);
                    var op = tr.querySelector("[data-op]");
                    if (!op) return;
                    var bEdit = document.createElement("button");
                    bEdit.type = "button";
                    bEdit.className = "btn btn-sm btn-outline-primary";
                    bEdit.textContent = "修改";
                    bEdit.addEventListener("click", function () {
                        function setVal(id, v) {
                            var el = document.getElementById(id);
                            if (el) el.value = v == null ? "" : String(v);
                        }
                        setVal("teacherBankEditId", qid);
                        setVal("teacherBankEditExamTrack", it.exam_track || it.examTrack || "");
                        var elAct = document.getElementById("teacherBankEditIsActive");
                        if (elAct) elAct.value = "";
                        setVal("teacherBankEditStem", it.stem || "");
                        setVal("teacherBankEditOptions", it.options != null ? JSON.stringify(it.options, null, 2) : "");
                        setVal("teacherBankEditExplanation", it.explanation || "");
                        setVal("teacherBankEditEvidence", it.evidence != null ? JSON.stringify(it.evidence, null, 2) : "");
                        setVal("teacherBankEditStatus", it.status || "");
                        setVal("teacherBankEditCategory", it.category || "");
                        setVal("teacherBankEditQuestionType", it.question_type || it.questionType || "");
                        setVal("teacherBankEditDifficulty", it.difficulty || "");
                        setVal("teacherBankEditAnswer", it.answer != null ? JSON.stringify(it.answer, null, 2) : "");
                        var ap = document.getElementById("teacherBankEditAnswerPresent");
                        if (ap) ap.checked = false;
                        if (modalBankEl && window.bootstrap && window.bootstrap.Modal) {
                            window.__bankModal = window.__bankModal || new window.bootstrap.Modal(modalBankEl);
                            window.__bankModal.show();
                        }
                    });
                    var bUnlist = document.createElement("button");
                    bUnlist.type = "button";
                    bUnlist.className = "btn btn-sm btn-outline-warning";
                    bUnlist.textContent = "下架";
                    bUnlist.title = "PATCH：将题目 is_active=false（仍保留记录；是否生效以上游为准）";
                    bUnlist.addEventListener("click", async function () {
                        var d = await apiRequest(
                            "/api/exam-center/teacher/bank/questions/" + encodeURIComponent(qid) + "?" + bankMutationQueryString(),
                            "PATCH",
                            { is_active: false }
                        );
                        render(d);
                        await loadTeacherBankQuestions();
                    });
                    var bDel = document.createElement("button");
                    bDel.type = "button";
                    bDel.className = "btn btn-sm btn-outline-danger";
                    bDel.textContent = "删除";
                    bDel.title = "DELETE：从题库删除该题（不可恢复以上游为准）";
                    bDel.addEventListener("click", async function () {
                        if (
                            !window.confirm(
                                "确定删除题目 " + qid + "？\n此操作调用上游 DELETE，通常不可恢复（以上游实现为准）。"
                            )
                        ) {
                            return;
                        }
                        var d = await apiRequest(
                            "/api/exam-center/teacher/bank/questions/" + encodeURIComponent(qid) + "?" + bankMutationQueryString(),
                            "DELETE"
                        );
                        render(d);
                        await loadTeacherBankQuestions();
                    });
                    op.appendChild(bEdit);
                    op.appendChild(bUnlist);
                    op.appendChild(bDel);
                });
            } catch (e) {
                bankBody.innerHTML =
                    '<tr><td colspan="8" class="text-danger small">加载失败：' + escHtml(e.message) + "</td></tr>";
            }
        }

        async function loadTeacherIngestJobs() {
            if (!tbodyJobs) return;
            var limit = 20;
            if (selJobsLimit && selJobsLimit.value) {
                var n = parseInt(selJobsLimit.value, 10);
                if (Number.isFinite(n) && n > 0) limit = n;
            }
            tbodyJobs.innerHTML = '<tr><td colspan="7" class="text-muted small">加载中…</td></tr>';
            try {
                var res = await apiRequest("/api/exam-center/teacher/bank/ingest-jobs?limit=" + encodeURIComponent(String(limit)), "GET");
                if (res && res.__ok === false) {
                    tbodyJobs.innerHTML =
                        '<tr><td colspan="7" class="text-danger small">' +
                        escHtml(res.message || "请求失败") +
                        "（HTTP " +
                        escHtml(String(res.__http_status || "?")) +
                        "；本列表仅查 aiword 库，不访问 aicheckword。）</td></tr>";
                    return;
                }
                var jobs = (res && res.data && res.data.jobs) ? res.data.jobs : [];
                if (!Array.isArray(jobs) || jobs.length === 0) {
                    tbodyJobs.innerHTML = '<tr><td colspan="7" class="text-muted small">暂无任务记录（发起一次“AI批量录入题库”后会出现）。</td></tr>';
                    return;
                }
                tbodyJobs.innerHTML = "";
                jobs.forEach(function (j) {
                    var tr = document.createElement("tr");
                    var created = escHtml(j.createdAt || j.created_at || "");
                    var st = escHtml(j.status || "");
                    var track = escHtml(j.exam_track || j.examTrack || "");
                    var tgt = escHtml(j.target_count != null ? j.target_count : (j.targetCount != null ? j.targetCount : ""));
                    var jidRaw = String(j.upstream_job_id || j.upstreamJobId || "");
                    var jid = escHtml(jidRaw);
                    var setRaw = String(j.upstream_set_id || j.upstreamSetId || j.set_id || j.setId || "");
                    var setDisp = escHtml(setRaw);
                    tr.innerHTML =
                        "<td class=\"small\">" + created + "</td>" +
                        "<td><span class=\"badge bg-light text-dark\">" + st + "</span></td>" +
                        "<td class=\"small\">" + track + "</td>" +
                        "<td class=\"small\">" + tgt + "</td>" +
                        "<td class=\"small\"><code>" + jid + "</code></td>" +
                        "<td class=\"small\"><code>" + (setDisp || "—") + "</code></td>" +
                        "<td class=\"small ingest-job-op\"></td>";
                    tbodyJobs.appendChild(tr);

                    var opTd = tr.querySelector(".ingest-job-op");
                    if (opTd && jidRaw) {
                        var wrap = document.createElement("div");
                        wrap.className = "d-flex flex-column gap-1";

                        var btnFill = document.createElement("button");
                        btnFill.type = "button";
                        btnFill.className = "btn btn-sm btn-outline-primary";
                        btnFill.textContent = "填入套题ID";
                        btnFill.disabled = !setRaw;
                        btnFill.addEventListener("click", function () {
                            if (!setRaw) return;
                            autofillTeacherSetIdIfEmpty(setRaw);
                            if (jidRaw) {
                                ingestState.jobId = jidRaw;
                                ingestState.lastJobStatus = String(j.status || "").toLowerCase() || ingestState.lastJobStatus;
                            }
                        });

                        var btn = document.createElement("button");
                        btn.type = "button";
                        btn.className = "btn btn-sm btn-outline-secondary";
                        btn.textContent = "刷新任务";
                        btn.dataset.jobId = jidRaw;
                        btn.addEventListener("click", async function () {
                            var id = btn.dataset.jobId || "";
                            if (!id) return;
                            ingestState.jobId = id;
                            var jr = await apiRequest("/api/exam-center/teacher/bank/ingest-jobs/" + encodeURIComponent(id) + "?refresh=1", "GET");
                            render(jr);
                            maybeAutofillSetIdFromAnyResp(jr);
                            var jst = pickJobStatus(jr);
                            if (jst) ingestState.lastJobStatus = jst;
                            await loadTeacherIngestJobs();
                        });
                        wrap.appendChild(btnFill);
                        wrap.appendChild(btn);
                        opTd.appendChild(wrap);
                    }
                });
            } catch (e) {
                var aborted = e && (e.name === "AbortError" || e.name === "TimeoutError");
                tbodyJobs.innerHTML =
                    '<tr><td colspan="7" class="text-danger small">' +
                    escHtml(aborted ? "请求超时（120s），请检查 aiword 是否卡住或网络。" : "加载失败：" + e.message) +
                    "</td></tr>";
            }
        }

        async function loadTeacherReviewJobs() {
            if (!tbodyReviewJobs) return;
            var limit = 20;
            if (selReviewJobsLimit && selReviewJobsLimit.value) {
                var n2 = parseInt(selReviewJobsLimit.value, 10);
                if (Number.isFinite(n2) && n2 > 0) limit = n2;
            }
            tbodyReviewJobs.innerHTML = '<tr><td colspan="5" class="text-muted small">加载中…</td></tr>';
            try {
                var res2 = await apiRequest("/api/exam-center/teacher/sets/review-jobs?limit=" + encodeURIComponent(String(limit)), "GET");
                if (res2 && res2.__ok === false) {
                    tbodyReviewJobs.innerHTML =
                        '<tr><td colspan="5" class="text-danger small">' +
                        escHtml(res2.message || "请求失败") +
                        "（HTTP " +
                        escHtml(String(res2.__http_status || "?")) +
                        "；本列表仅查 aiword 库，不访问 aicheckword。）</td></tr>";
                    return;
                }
                var jobs2 = (res2 && res2.data && res2.data.jobs) ? res2.data.jobs : [];
                if (!Array.isArray(jobs2) || jobs2.length === 0) {
                    tbodyReviewJobs.innerHTML = '<tr><td colspan="5" class="text-muted small">暂无复审任务（发起一次「AI复审套题」后会出现）。</td></tr>';
                    return;
                }
                tbodyReviewJobs.innerHTML = "";
                jobs2.forEach(function (j) {
                    var tr2 = document.createElement("tr");
                    var created2 = escHtml(j.created_at || j.createdAt || "");
                    var st2 = escHtml(j.status || "");
                    var setRaw2 = String(j.set_id || j.setId || "");
                    var setDisp2 = escHtml(setRaw2);
                    var jidRaw2 = String(j.upstream_job_id || j.upstreamJobId || "");
                    var jid2 = escHtml(jidRaw2);
                    tr2.innerHTML =
                        "<td class=\"small\">" + created2 + "</td>" +
                        "<td><span class=\"badge bg-light text-dark\">" + st2 + "</span></td>" +
                        "<td class=\"small\"><code>" + (setDisp2 || "—") + "</code></td>" +
                        "<td class=\"small\"><code>" + jid2 + "</code></td>" +
                        "<td class=\"small review-job-op\"></td>";
                    tbodyReviewJobs.appendChild(tr2);
                    var opTd2 = tr2.querySelector(".review-job-op");
                    if (opTd2 && jidRaw2) {
                        var btnRf = document.createElement("button");
                        btnRf.type = "button";
                        btnRf.className = "btn btn-sm btn-outline-secondary";
                        btnRf.textContent = "刷新状态";
                        btnRf.addEventListener("click", async function () {
                            reviewState.jobId = jidRaw2;
                            var jr3 = await apiRequest(
                                "/api/exam-center/teacher/sets/review-jobs/" + encodeURIComponent(jidRaw2) + "?refresh=1",
                                "GET"
                            );
                            render(jr3);
                            var jst3 = pickJobStatus(jr3);
                            if (jst3) reviewState.lastJobStatus = jst3;
                            await loadTeacherReviewJobs();
                        });
                        opTd2.appendChild(btnRf);
                    }
                });
            } catch (e2) {
                var ab2 = e2 && (e2.name === "AbortError" || e2.name === "TimeoutError");
                tbodyReviewJobs.innerHTML =
                    '<tr><td colspan="5" class="text-danger small">' +
                    escHtml(ab2 ? "请求超时（120s），请检查 aiword 是否卡住或网络。" : "加载失败：" + e2.message) +
                    "</td></tr>";
            }
        }

        /** 提交 AI 复审并轮询 job，直至终态或超时（与批量录题交互一致） */
        async function runTeacherReviewJobPolling(setId) {
            setId = String(setId || "").trim();
            if (!setId) throw new Error("缺少 set_id");
            if (reviewState.running) {
                setReviewProgress(true, "已有 AI 复审任务轮询中，请勿重复点击（可点「停止轮询」）。job_id=" + (reviewState.jobId || "—"));
                return;
            }
            var ingestSt = String(await refreshIngestJobGateState(setId) || "").toLowerCase();
            if (isNonTerminalIngestStatus(ingestSt)) {
                throw new Error("录题任务仍在进行中（status=" + (ingestSt || "unknown") + "）。请等 status=done 后再复审。");
            }
            reviewState.running = true;
            reviewState.stop = false;
            reviewState.jobId = "";
            reviewState.lastJobStatus = "";
            setReviewProgress(true, "正在提交 AI 复审… set_id=" + setId);
            try {
                var startResp2 = await apiRequest("/api/exam-center/teacher/sets/review-by-ai", "POST", { set_id: setId });
                render(startResp2);
                maybeAutofillSetIdFromAnyResp(startResp2);
                await loadTeacherReviewJobs();

                if (startResp2 && startResp2.__ok === false) {
                    setReviewProgress(true, "创建复审任务失败（HTTP " + (startResp2.__http_status || "?") + "），请查看接口响应。");
                    return;
                }
                var jobId2 = pickJobId(startResp2);
                if (!jobId2) {
                    setReviewProgress(true, "未获取到 job_id（请查看接口响应 data）。");
                    return;
                }
                reviewState.jobId = jobId2;
                setReviewProgress(true, "复审任务已创建，job_id=" + jobId2 + "，开始轮询…");

                var maxMs2 = 10 * 60 * 1000;
                var startTs2 = Date.now();
                var pollMs2 = 1200;
                while (true) {
                    if (reviewState.stop) {
                        setReviewProgress(true, "已停止轮询（job_id=" + jobId2 + "）。");
                        break;
                    }
                    if (Date.now() - startTs2 > maxMs2) {
                        setReviewProgress(true, "轮询超时（超过 10 分钟）。job_id=" + jobId2);
                        break;
                    }
                    await sleep(pollMs2);
                    var jobResp2 = await apiRequest(
                        "/api/exam-center/teacher/sets/review-jobs/" + encodeURIComponent(jobId2) + "?refresh=1",
                        "GET"
                    );
                    render(jobResp2);
                    maybeAutofillSetIdFromAnyResp(jobResp2);
                    reviewState.lastJobStatus = pickJobStatus(jobResp2) || reviewState.lastJobStatus;
                    await loadTeacherReviewJobs();

                    if (jobResp2 && jobResp2.__ok === false) {
                        pollMs2 = Math.min(3000, Math.round(pollMs2 * 1.4));
                        setReviewProgress(true, "轮询失败（HTTP " + (jobResp2.__http_status || "?") + "），" + pollMs2 + "ms 后重试… job_id=" + jobId2);
                        continue;
                    }
                    var stx = pickJobStatus(jobResp2);
                    if (stx) setReviewProgress(true, "当前状态：" + stx + "（job_id=" + jobId2 + "）");
                    if (stx === "done" || stx === "success" || stx === "completed") {
                        setReviewProgress(true, "复审已完成（job_id=" + jobId2 + "）");
                        break;
                    }
                    if (stx === "failed" || stx === "error") {
                        setReviewProgress(true, "复审失败（job_id=" + jobId2 + "），请查看返回 data/trace_id");
                        break;
                    }
                    pollMs2 = Math.max(1200, Math.min(1800, pollMs2 - 200));
                }
            } finally {
                reviewState.running = false;
                await loadTeacherReviewJobs();
            }
        }

        async function batchSetsAction(action) {
            var ids = selectedSetIds();
            if (!ids.length) {
                render({ code: "UI_ERROR", message: "请先勾选至少 1 个套题。", data: null });
                return;
            }
            var results = [];
            var i;
            for (i = 0; i < ids.length; i++) {
                var sid = ids[i];
                try {
                    if (action === "review") {
                        results.push(
                            await apiRequest("/api/exam-center/teacher/sets/review-by-ai", "POST", { set_id: sid })
                        );
                    } else if (action === "assign") {
                        // 批量下发改为弹窗统一提交，不在循环里逐个提交
                        results.push({ code: 0, message: "请使用“批量下发考试任务”弹窗提交", data: { set_id: sid } });
                    } else if (action === "publish") {
                        results.push(await apiRequest("/api/exam-center/teacher/sets/publish", "POST", { set_id: sid }));
                    } else if (action === "delete") {
                        results.push(await apiRequest("/api/exam-center/teacher/sets/" + encodeURIComponent(sid), "DELETE"));
                    }
                } catch (e) {
                    results.push({ code: "UI_ERROR", message: "set_id=" + sid + "：" + e.message, data: null });
                }
            }
            render({ code: 0, message: "批量操作完成：" + action, data: { results: results } });
            await loadTeacherSets();
        }

        btnSetsRefresh &&
            btnSetsRefresh.addEventListener("click", function () {
                loadTeacherSets();
            });
        btnBankRefresh &&
            btnBankRefresh.addEventListener("click", function () {
                bankState.offset = 0;
                loadTeacherBankQuestions();
            });
        inputBankQ &&
            inputBankQ.addEventListener("change", function () {
                bankState.offset = 0;
                loadTeacherBankQuestions();
            });
        selBankCollection &&
            selBankCollection.addEventListener("change", function () {
                bankState.offset = 0;
                loadTeacherBankQuestions();
            });
        selBankIsActive &&
            selBankIsActive.addEventListener("change", function () {
                bankState.offset = 0;
                loadTeacherBankQuestions();
            });
        selBankLimit &&
            selBankLimit.addEventListener("change", function () {
                bankState.offset = 0;
                loadTeacherBankQuestions();
            });
        inputBankSetId &&
            inputBankSetId.addEventListener("change", function () {
                bankState.offset = 0;
                loadTeacherBankQuestions();
            });
        btnBankClearSet &&
            btnBankClearSet.addEventListener("click", function () {
                if (inputBankSetId) inputBankSetId.value = "";
                syncBankSetIdToUrl("");
                bankState.offset = 0;
                loadTeacherBankQuestions();
            });
        btnBankPrev &&
            btnBankPrev.addEventListener("click", function () {
                bankState.offset = Math.max(0, (bankState.offset || 0) - bankState.limit);
                loadTeacherBankQuestions();
            });
        btnBankNext &&
            btnBankNext.addEventListener("click", function () {
                var next = (bankState.offset || 0) + bankState.limit;
                if (bankState.total && next >= bankState.total) return;
                bankState.offset = next;
                loadTeacherBankQuestions();
            });
        bankCheckAll &&
            bankCheckAll.addEventListener("change", function () {
                var on = !!bankCheckAll.checked;
                bankBody &&
                    bankBody.querySelectorAll('input[type="checkbox"][data-qid]').forEach(function (c) {
                        c.checked = on;
                    });
            });
        btnBankBatchDeactivate &&
            btnBankBatchDeactivate.addEventListener("click", async function () {
                var ids = bankSelectedIds();
                if (!ids.length) {
                    render({ code: "UI_ERROR", message: "请先勾选至少 1 个题目。", data: null });
                    return;
                }
                var qs = bankMutationQueryString();
                var out = [];
                var j;
                for (j = 0; j < ids.length; j++) {
                    out.push(
                        await apiRequest(
                            "/api/exam-center/teacher/bank/questions/" + encodeURIComponent(ids[j]) + "?" + qs,
                            "DELETE"
                        )
                    );
                }
                render({ code: 0, message: "批量下架完成", data: { results: out } });
                await loadTeacherBankQuestions();
            });
        btnBankSave &&
            btnBankSave.addEventListener("click", async function () {
                var qid = readValue("teacherBankEditId");
                if (!qid) return;
                var qs = bankMutationQueryString();
                var payload = {};
                var stem = readValue("teacherBankEditStem");
                if (stem) payload.stem = stem;
                var examTrack = readValue("teacherBankEditExamTrack");
                if (examTrack) payload.exam_track = examTrack;
                var status = readValue("teacherBankEditStatus");
                if (status) payload.status = status;
                var category = readValue("teacherBankEditCategory");
                if (category) payload.category = category;
                var qt = readValue("teacherBankEditQuestionType");
                if (qt) payload.question_type = qt;
                var diff = readValue("teacherBankEditDifficulty");
                if (diff) payload.difficulty = diff;
                var expl = readValue("teacherBankEditExplanation");
                if (expl) payload.explanation = expl;
                var optsRaw = readValue("teacherBankEditOptions");
                if (optsRaw) payload.options = jsonTryParseOrString(optsRaw);
                var evRaw = readValue("teacherBankEditEvidence");
                if (evRaw) payload.evidence = jsonTryParseOrString(evRaw);
                var isAct = readValue("teacherBankEditIsActive");
                if (isAct === "true") payload.is_active = true;
                if (isAct === "false") payload.is_active = false;
                var ap = document.getElementById("teacherBankEditAnswerPresent");
                if (ap && ap.checked) {
                    payload.answer_present = true;
                    var ansRaw = readValue("teacherBankEditAnswer");
                    payload.answer = ansRaw ? jsonTryParseOrString(ansRaw) : null;
                }
                var resp = await apiRequest(
                    "/api/exam-center/teacher/bank/questions/" + encodeURIComponent(qid) + "?" + qs,
                    "PATCH",
                    payload
                );
                render(resp);
                if (modalBankEl && window.__bankModal && typeof window.__bankModal.hide === "function") {
                    window.__bankModal.hide();
                }
                await loadTeacherBankQuestions();
            });
        chkSetsAll &&
            chkSetsAll.addEventListener("change", function () {
                var on = !!chkSetsAll.checked;
                tbodySets &&
                    tbodySets.querySelectorAll('input[type="checkbox"][data-set-id]').forEach(function (c) {
                        c.checked = on;
                    });
            });
        btnBatchReview && btnBatchReview.addEventListener("click", function () { batchSetsAction("review"); });
        btnBatchAssign &&
            btnBatchAssign.addEventListener("click", async function () {
                try {
                    var ids = selectedSetIds();
                    await openIssueAssignmentsModal(ids);
                } catch (e0) {
                    render({ code: "UI_ERROR", message: e0.message || String(e0), data: null });
                }
            });

        if (assignModalSearch) {
            assignModalSearch.addEventListener("input", function () {
                filterAssignModalUsers();
            });
        }
        btnAssignModalSelectAll &&
            btnAssignModalSelectAll.addEventListener("click", function () {
                if (!assignModalUsers) return;
                assignModalUsers.querySelectorAll('input.assign-user[type="checkbox"]').forEach(function (c) {
                    if (c.closest(".user-row") && c.closest(".user-row").style.display === "none") return;
                    c.checked = true;
                });
            });
        btnAssignModalClearAll &&
            btnAssignModalClearAll.addEventListener("click", function () {
                if (!assignModalUsers) return;
                assignModalUsers.querySelectorAll('input.assign-user[type="checkbox"]').forEach(function (c) {
                    c.checked = false;
                });
            });
        btnAssignModalSubmit &&
            btnAssignModalSubmit.addEventListener("click", async function () {
                var ids = collectAssignModalUserIds();
                if (!ids.length) {
                    render({ code: "BAD_REQUEST", message: "请选择考试对象（至少1人）", data: null });
                    return;
                }
                var dd = assignModalDue ? String(assignModalDue.value || "").trim() : "";
                var purpose = assignModalPurpose ? String(assignModalPurpose.value || "").trim() : "";
                var payload = {
                    exam_track: readValue("teacherExamTrack") || "cn",
                    items: assignModalState.items || [],
                    audience_user_ids: ids,
                };
                if (dd) payload.due_date = dd;
                if (purpose) payload.purpose = purpose;
                setButtonLoading(btnAssignModalSubmit, true, "下发中…");
                try {
                    var resp = await apiRequest("/api/exam-center/teacher/assignments/issue", "POST", payload);
                    render(resp);
                    if (!(resp && resp.__ok === false)) {
                        try {
                            var m = ensureAssignModal();
                            if (m) m.hide();
                        } catch (e1) {}
                        await loadTeacherIssuedAssignments();
                    }
                } finally {
                    setButtonLoading(btnAssignModalSubmit, false);
                }
            });
        btnBatchPublish && btnBatchPublish.addEventListener("click", function () { batchSetsAction("publish"); });
        btnBatchDelete && btnBatchDelete.addEventListener("click", function () { batchSetsAction("delete"); });
        btnSetDetailBankFilter &&
            btnSetDetailBankFilter.addEventListener("click", function () {
                if (!currentSetIdForDetail) return;
                jumpToBankBySetId(currentSetIdForDetail, true);
            });
        btnSetDetailReview &&
            btnSetDetailReview.addEventListener("click", async function () {
                if (!currentSetIdForDetail) return;
                var d = await apiRequest("/api/exam-center/teacher/sets/review-by-ai", "POST", { set_id: currentSetIdForDetail });
                render(d);
                await loadTeacherReviewJobs();
                await openSetDetail(currentSetIdForDetail);
            });
        btnSetDetailPublish &&
            btnSetDetailPublish.addEventListener("click", async function () {
                if (!currentSetIdForDetail || (btnSetDetailPublish && btnSetDetailPublish.disabled)) return;
                var d = await apiRequest("/api/exam-center/teacher/sets/publish", "POST", { set_id: currentSetIdForDetail });
                render(d);
                await loadTeacherSets();
                await openSetDetail(currentSetIdForDetail);
            });
        btnSetDetailDelete &&
            btnSetDetailDelete.addEventListener("click", async function () {
                if (!currentSetIdForDetail) return;
                var d = await apiRequest("/api/exam-center/teacher/sets/" + encodeURIComponent(currentSetIdForDetail), "DELETE");
                render(d);
                await loadTeacherSets();
                if (setDetailModalEl && window.__setDetailModal && typeof window.__setDetailModal.hide === "function") {
                    window.__setDetailModal.hide();
                }
            });

        if (btnIngestStop) {
            btnIngestStop.addEventListener("click", function () {
                ingestState.stop = true;
                setIngestProgress(true, "已请求停止轮询（不会再发请求）。");
                setButtonLoading(btnIngest, false);
                ingestState.running = false;
            });
        }

        if (btnReviewStop) {
            btnReviewStop.addEventListener("click", function () {
                reviewState.stop = true;
                setReviewProgress(true, "已请求停止轮询（不会再发复审轮询请求）。");
                reviewState.running = false;
            });
        }

        btnJobsRefresh && btnJobsRefresh.addEventListener("click", function () {
            loadTeacherIngestJobs();
        });
        selJobsLimit && selJobsLimit.addEventListener("change", function () {
            loadTeacherIngestJobs();
        });
        btnReviewJobsRefresh && btnReviewJobsRefresh.addEventListener("click", function () {
            loadTeacherReviewJobs();
        });
        selReviewJobsLimit && selReviewJobsLimit.addEventListener("change", function () {
            loadTeacherReviewJobs();
        });

        btnGenerate && btnGenerate.addEventListener("click", async function () {
            if (btnGenerate && btnGenerate.disabled) return;
            setButtonLoading(btnGenerate, true, "生成中…");
            try {
                var track = readValue("teacherExamTrack") || "cn";
                var payload = {
                    exam_track: track,
                    examTrack: track,
                    track: track,
                    exam_type: track,
                    question_count: readInt("teacherQuestionCount", 20),
                };
                // aicheckword：difficulty 须为 string；「默认」为空则不传难度字段（避免 422）
                var diff = readValue("teacherDifficulty");
                if (diff) {
                    payload.difficulty = diff;
                    payload.difficulty_level = diff;
                    payload.difficultyLevel = diff;
                    payload.level = diff;
                }

                var data = await apiRequest("/api/exam-center/teacher/sets/generate", "POST", payload);
                render(data);
                // 与录题一致：上游 data.data 内含 set_id / id（aicheckword load_set），自动填入套题 ID 便于复审/发布
                maybeAutofillSetIdFromAnyResp(data);
            } catch (e) {
                render({ code: "UI_ERROR", message: e.message, data: null });
            } finally {
                setButtonLoading(btnGenerate, false);
            }
        });

        btnIngest && btnIngest.addEventListener("click", async function () {
            if (reviewState.running) {
                setIngestProgress(true, "已有 AI 复审任务轮询中，请先停止复审轮询或等待结束。");
                return;
            }
            if (ingestState.running) {
                setIngestProgress(true, "已有批量录题任务轮询中，请勿重复点击（可点“停止轮询”）。job_id=" + (ingestState.jobId || "—"));
                return;
            }
            if (btnIngest && btnIngest.disabled) return;
            ingestState.running = true;
            ingestState.stop = false;
            ingestState.jobId = "";
            ingestState.lastJobStatus = "";
            setButtonLoading(btnIngest, true, "已提交…");
            setIngestProgress(true, "正在发起批量录题任务…");
            try {
                // 录题：题量/难度/题型占比由上游提示词/策略统一控制（每批 50 题等），
                // 老师端下拉框仅影响「来一套」。
                var ingestBody = {
                    exam_track: readValue("teacherExamTrack") || "cn",
                    target_count: 50,
                    review_mode: "draft"
                };
                var startResp = await apiRequest("/api/exam-center/teacher/bank/ingest-by-ai", "POST", ingestBody);
                render(startResp);
                maybeAutofillSetIdFromAnyResp(startResp);
                await loadTeacherIngestJobs();

                if (startResp && startResp.__ok === false) {
                    setIngestProgress(true, "创建任务失败（HTTP " + (startResp.__http_status || "?") + "），请查看接口响应里的 message/request.url/trace_id。");
                    return;
                }

                var jobId = pickJobId(startResp);
                if (!jobId) {
                    setIngestProgress(true, "未获取到 job_id（请查看接口响应 data；上游应在 POST 后立刻返回 job_id）");
                    return;
                }
                ingestState.jobId = jobId;
                setIngestProgress(true, "任务已创建，job_id=" + jobId + "，开始轮询进度…");
                setButtonLoading(btnIngest, true, "录题进行中…");

                var maxMs = 10 * 60 * 1000; // 10 分钟上限，避免无限轮询
                var startTs = Date.now();
                var pollMs = 1200;
                while (true) {
                    if (ingestState.stop) {
                        setIngestProgress(true, "已停止轮询（job_id=" + jobId + "）。");
                        break;
                    }
                    if (Date.now() - startTs > maxMs) {
                        setIngestProgress(true, "轮询超时（超过 10 分钟），请稍后重试或查看 aicheckword 日志。job_id=" + jobId);
                        break;
                    }
                    await sleep(pollMs);
                    // 轮询从“任务记录接口”取（默认 refresh=1 会刷新上游并回写快照）
                    var jobResp = await apiRequest("/api/exam-center/teacher/bank/ingest-jobs/" + encodeURIComponent(jobId) + "?refresh=1", "GET");
                    render(jobResp);
                    maybeAutofillSetIdFromAnyResp(jobResp);
                    ingestState.lastJobStatus = pickJobStatus(jobResp) || ingestState.lastJobStatus;
                    await loadTeacherIngestJobs();

                    if (jobResp && jobResp.__ok === false) {
                        pollMs = Math.min(3000, Math.round(pollMs * 1.4));
                        setIngestProgress(true, "轮询失败（HTTP " + (jobResp.__http_status || "?") + "），将在 " + pollMs + "ms 后重试… job_id=" + jobId);
                        continue;
                    }

                    var st = pickJobStatus(jobResp);
                    if (st) setIngestProgress(true, "当前状态：" + st + "（job_id=" + jobId + "）");
                    if (st === "done" || st === "success" || st === "completed") {
                        setIngestProgress(true, "已完成（job_id=" + jobId + "）");
                        await loadTeacherRequirementStatus();
                        break;
                    }
                    if (st === "failed" || st === "error") {
                        setIngestProgress(true, "已失败（job_id=" + jobId + "），请查看返回 data/trace_id");
                        break;
                    }
                    pollMs = Math.max(1200, Math.min(1800, pollMs - 200));
                }
            } catch (e) {
                render({ code: "UI_ERROR", message: e.message, data: null });
                setIngestProgress(true, "前端请求异常：" + e.message);
            } finally {
                setButtonLoading(btnIngest, false);
                ingestState.running = false;
                loadTeacherIngestJobs();
            }
        });

        btnReview && btnReview.addEventListener("click", async function () {
            if (btnReview && btnReview.disabled) return;
            if (ingestState.running) {
                setReviewProgress(true, "批量录题轮询进行中，请先停止录题轮询或等待结束后再复审。");
                return;
            }
            setButtonLoading(btnReview, true, "处理中…");
            try {
                var setIdRv = readValue("teacherSetId");
                if (!setIdRv) throw new Error("请先输入 set_id（可从任务记录列表点“填入套题ID”）");
                await runTeacherReviewJobPolling(setIdRv);
            } catch (e) {
                render({ code: "UI_ERROR", message: e.message, data: null });
                setReviewProgress(true, "复审流程异常：" + e.message);
            } finally {
                setButtonLoading(btnReview, false);
            }
        });

        btnPublish && btnPublish.addEventListener("click", async function () {
            if (btnPublish && btnPublish.disabled) return;
            if (reviewState.running) {
                render({ code: "UI_ERROR", message: "AI 复审轮询进行中，请等待结束后再同步。", data: null });
                return;
            }
            setButtonLoading(btnPublish, true, "同步中…");
            try {
                var setId = readValue("teacherSetId");
                if (!setId) throw new Error("请先输入 set_id（可从任务记录列表点“填入套题ID”）");
                var st = String(await refreshIngestJobGateState(setId) || "").toLowerCase();
                if (isNonTerminalIngestStatus(st)) {
                    throw new Error("录题任务仍在进行中（status=" + (st || "unknown") + "）。套题可能尚未就绪，请等 status=done 后再同步。");
                }
                var data = await apiRequest("/api/exam-center/teacher/sets/publish", "POST", {
                    set_id: setId
                });
                render(data);
            } catch (e) {
                render({ code: "UI_ERROR", message: e.message, data: null });
            } finally {
                setButtonLoading(btnPublish, false);
            }
        });

        async function loadTeacherIssuedAssignments() {
            if (!tbodyIssued) return;
            tbodyIssued.innerHTML = '<tr><td colspan="7" class="text-muted small">加载中…</td></tr>';
            try {
                var resp = await apiRequest("/api/exam-center/teacher/assignments-local", "GET");
                render(resp);
                if (resp && resp.__ok === false) {
                    tbodyIssued.innerHTML =
                        '<tr><td colspan="7" class="text-danger small">' +
                        escHtml(resp.message || "请求失败") +
                        "（HTTP " +
                        escHtml(String(resp.__http_status || "?")) +
                        "）</td></tr>";
                    return;
                }
                var c = resp != null ? resp.code : undefined;
                if (c != null && String(c) !== "0" && Number(c) !== 0) {
                    tbodyIssued.innerHTML =
                        '<tr><td colspan="7" class="text-danger small">' + escHtml(resp.message || "加载失败") + "</td></tr>";
                    return;
                }
                var rows = resp && resp.data && resp.data.rows ? resp.data.rows : [];
                if (!rows.length) {
                    tbodyIssued.innerHTML =
                        '<tr><td colspan="7" class="text-muted small">暂无已下发记录（或未在 aiword 落库镜像）。</td></tr>';
                    return;
                }
                tbodyIssued.innerHTML = "";
                rows.forEach(function (r) {
                    var aid = String(r && r.assignment_id != null ? r.assignment_id : "").trim();
                    if (!aid) return;
                    var dueCell = r.due_at ? examDueCompletionPillHtml(r.due_at) : '<span class="text-muted">—</span>';
                    var tr = document.createElement("tr");
                    tr.innerHTML =
                        '<td class="small">' +
                        escHtml(r.title || aid) +
                        "</td>" +
                        '<td class="small"><code>' +
                        escHtml(aid) +
                        "</code></td>" +
                        '<td class="small"><code>' +
                        escHtml(r.set_id || "") +
                        "</code></td>" +
                        '<td class="small">' +
                        escHtml(difficultyLabelZh(r.difficulty)) +
                        "</td>" +
                        '<td class="small"><span class="badge bg-light text-dark">' +
                        escHtml(r.status || "—") +
                        "</span></td>" +
                        '<td class="small text-center">' +
                        dueCell +
                        "</td>" +
                        '<td class="small"><div class="d-flex gap-1 flex-wrap exam-issued-ops" data-aid="' +
                        escHtml(aid) +
                        '"></div></td>';
                    var opWrap = tr.querySelector(".exam-issued-ops");
                    tbodyIssued.appendChild(tr);
                    if (!opWrap) return;
                    var bUn = document.createElement("button");
                    bUn.type = "button";
                    bUn.className = "btn btn-sm btn-outline-warning";
                    bUn.textContent = "下架";
                    bUn.title = "本地标记 inactive；并尝试上游取消/停用";
                    bUn.addEventListener("click", async function () {
                        if (!window.confirm("确定下架该考试任务？学生端本地兜底列表将不再显示。")) return;
                        setButtonLoading(bUn, true, "下架中…");
                        try {
                            var d = await apiRequest(
                                "/api/exam-center/teacher/assignments/" + encodeURIComponent(aid) + "/unpublish",
                                "POST",
                                {}
                            );
                            render(d);
                            await loadTeacherIssuedAssignments();
                        } catch (e) {
                            render({ code: "UI_ERROR", message: e.message, data: null });
                        } finally {
                            setButtonLoading(bUn, false);
                        }
                    });
                    var bDel = document.createElement("button");
                    bDel.type = "button";
                    bDel.className = "btn btn-sm btn-outline-danger";
                    bDel.textContent = "删除";
                    bDel.title = "删除本地记录并尝试上游删除";
                    bDel.addEventListener("click", async function () {
                        if (!window.confirm("确定删除该任务记录？此操作通常不可恢复。")) return;
                        setButtonLoading(bDel, true, "删除中…");
                        try {
                            var d2 = await apiRequest(
                                "/api/exam-center/teacher/assignments/" + encodeURIComponent(aid),
                                "DELETE"
                            );
                            render(d2);
                            await loadTeacherIssuedAssignments();
                        } catch (e) {
                            render({ code: "UI_ERROR", message: e.message, data: null });
                        } finally {
                            setButtonLoading(bDel, false);
                        }
                    });
                    opWrap.appendChild(bUn);
                    opWrap.appendChild(bDel);
                });
            } catch (e) {
                tbodyIssued.innerHTML =
                    '<tr><td colspan="7" class="text-danger small">' + escHtml(e.message || String(e)) + "</td></tr>";
            }
        }

        btnIssuedRefresh &&
            btnIssuedRefresh.addEventListener("click", function () {
                loadTeacherIssuedAssignments();
            });
        btnCheckReq &&
            btnCheckReq.addEventListener("click", function () {
                loadTeacherRequirementStatus();
            });
        btnMarkReqBase &&
            btnMarkReqBase.addEventListener("click", async function () {
                if (!window.confirm("确认将当前题库状态设为该体考类型的“达标基线”？后续检测将以此判断新增/升级要求。")) return;
                setButtonLoading(btnMarkReqBase, true, "保存中…");
                try {
                    await markTeacherRequirementBaseline();
                } finally {
                    setButtonLoading(btnMarkReqBase, false);
                }
            });
        selTrack &&
            selTrack.addEventListener("change", function () {
                applyTeacherTrackDefaults();
                loadTeacherPolicyVersion();
                loadTeacherRequirementStatus();
            });
        btnSavePolicyVersion &&
            btnSavePolicyVersion.addEventListener("click", async function () {
                setButtonLoading(btnSavePolicyVersion, true, "保存中…");
                try {
                    var r = await saveTeacherPolicyVersion();
                    if (!(r && r.__ok === false)) {
                        await loadTeacherRequirementStatus();
                    }
                } finally {
                    setButtonLoading(btnSavePolicyVersion, false);
                }
            });
        applyTeacherTrackDefaults();
        // 学生端进入页面时不要触发老师端初始化请求，否则会 401 needsPage13Auth → 重载 → 死循环刷新
        if (getExamRole() === "teacher") {
            loadTeacherPolicyVersion();
            loadTeacherRequirementStatus();
        }

        // 供角色切换/页面初始化调用：加载任务记录列表
        window.__examLoadTeacherIngestJobs = loadTeacherIngestJobs;
        window.__examLoadTeacherReviewJobs = loadTeacherReviewJobs;
        window.__examLoadTeacherSets = loadTeacherSets;
        window.__examLoadTeacherBankQuestions = loadTeacherBankQuestions;
        window.__examLoadTeacherIssuedAssignments = loadTeacherIssuedAssignments;
        window.__examLoadTeacherRequirementStatus = loadTeacherRequirementStatus;

        applyBankSetFilterFromUrl();
        if (inputBankSetId && String(inputBankSetId.value || "").trim() && bankSectionEl) {
            setTimeout(function () {
                try {
                    bankSectionEl.scrollIntoView({ behavior: "smooth", block: "start" });
                } catch (e5) {}
            }, 450);
        }
    }

    function bindStudentActions(render) {
        var btnSet = document.getElementById("btnStudentGenerateSet");
        var btnWrongbook = document.getElementById("btnStudentWrongbook");
        var btnTracks = document.getElementById("btnStudentTracks");
        var btnSubmitIx = document.getElementById("btnStudentSubmitInteraction");
        var btnCancelIx = document.getElementById("btnStudentCancelInteraction");
        var cardIx = document.getElementById("studentInteractionCard");
        var titleIx = document.getElementById("studentInteractionTitle");
        var metaIx = document.getElementById("studentInteractionMeta");
        var qListIx = document.getElementById("studentQuestionList");
        var tbodyAssign = document.getElementById("studentAssignmentsBody");
        var btnAssignRefresh = document.getElementById("btnStudentAssignmentsRefresh");
        var btnHist = document.getElementById("btnStudentRefreshHistory");
        var btnHistMore = document.getElementById("btnStudentHistoryLoadMore");
        var elHistMeta = document.getElementById("studentHistoryMeta");
        var tbodyHist = document.getElementById("studentHistoryBody");
        var studentHistoryCache = [];
        var HISTORY_PAGE = 80;
        var resultPre = document.getElementById("examApiResult");
        var selStudentTrack = document.getElementById("studentExamTrack");
        var inputStudentCount = document.getElementById("studentSetSize");
        var selStudentDiff = document.getElementById("studentDifficulty");

        var sessionState = {
            mode: "",
            setId: "",
            sessionId: "",
            attemptId: "",
            assignmentId: "",
            assignmentLabel: "",
            questions: [],
            upstreamSnapshot: null
        };

        function escSt(s) {
            return String(s == null ? "" : s)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;");
        }

        function applyStudentTrackDefaults() {
            var preset = trackRecommendedPreset(readValue("studentExamTrack") || "cn");
            if (inputStudentCount) inputStudentCount.value = String(preset.studentCount);
            if (selStudentDiff) selStudentDiff.value = String(preset.studentDifficulty);
        }

        /** 与 teacher 端 safeJson 同源；必须在本闭包内定义，不可引用 bindTeacherActions 内的函数（否则详情渲染报 ReferenceError）。 */
        function safeJson(v) {
            try {
                return JSON.stringify(v, null, 2);
            } catch (e) {
                return String(v);
            }
        }

        function safeInputNamePart(s) {
            return String(s || "").replace(/[^a-zA-Z0-9_-]/g, "_");
        }

        function pickSetIdFromAny(obj) {
            if (!obj || typeof obj !== "object") return "";
            var direct = String(obj.set_id || obj.setId || obj.quiz_set_id || obj.quizSetId || "").trim();
            if (direct) return direct;
            var setObj = obj.set;
            if (setObj && typeof setObj === "object") {
                var fromSet = String(setObj.id || setObj.set_id || setObj.setId || "").trim();
                if (fromSet) return fromSet;
            }
            var loadSet = obj.load_set;
            if (loadSet && typeof loadSet === "object") {
                var fromLoad = String(loadSet.id || loadSet.set_id || loadSet.setId || "").trim();
                if (fromLoad) return fromLoad;
            }
            var dataObj = obj.data;
            if (dataObj && typeof dataObj === "object") return pickSetIdFromAny(dataObj);
            return "";
        }

        function pickAttemptIdFromAny(obj) {
            if (!obj || typeof obj !== "object") return "";
            var direct = String(
                obj.attempt_id ||
                    obj.attemptId ||
                    obj.practice_attempt_id ||
                    obj.practiceAttemptId ||
                    obj.practice_id ||
                    obj.practiceId ||
                    obj.id ||
                    ""
            ).trim();
            if (direct) return direct;
            var attemptObj = obj.attempt;
            if (attemptObj && typeof attemptObj === "object") {
                var fromAttempt = String(attemptObj.id || attemptObj.attempt_id || attemptObj.attemptId || "").trim();
                if (fromAttempt) return fromAttempt;
            }
            var dataObj = obj.data;
            if (dataObj && typeof dataObj === "object") return pickAttemptIdFromAny(dataObj);
            return "";
        }

        function unwrapStudentUpstream(resp) {
            if (!resp || typeof resp !== "object") return {};
            var d = resp.data;
            if (!d || typeof d !== "object") return {};
            var inner;
            if (Object.prototype.hasOwnProperty.call(d, "code") && d.data && typeof d.data === "object") {
                inner = d.data;
            } else {
                inner = d;
            }
            inner = Object.assign({}, inner);
            var liftKeys = [
                "practice_session_id",
                "session_id",
                "practiceSessionId",
                "sessionId",
                "set_id",
                "setId",
                "attempt_id",
                "attemptId",
                "assignment_id",
                "assignmentId"
            ];
            var i;
            for (i = 0; i < liftKeys.length; i++) {
                var lk = liftKeys[i];
                var cur = inner[lk];
                var empty = cur == null || String(cur).trim() === "";
                if (empty && d[lk] != null && String(d[lk]).trim() !== "") {
                    inner[lk] = d[lk];
                }
            }
            return inner;
        }

        function quizPayloadBusinessOk(resp) {
            if (!resp || typeof resp !== "object") return false;
            if (resp.__ok === false) return false;
            if (resp.code !== undefined && resp.code !== 0 && resp.code !== "0") return false;
            var d = resp.data;
            if (d && typeof d === "object") {
                if (d.code !== undefined && d.code !== 0 && d.code !== "0") return false;
                var inn = d.data;
                if (inn && typeof inn === "object" && inn.code !== undefined && inn.code !== 0 && inn.code !== "0") {
                    return false;
                }
            }
            return true;
        }

        function unwrapQuizOkData(pkg) {
            if (!pkg || typeof pkg !== "object") return null;
            if (pkg.ok === true && pkg.data && typeof pkg.data === "object") return pkg.data;
            return pkg;
        }

        function unwrapQuizOkPackage(resp) {
            if (!resp || resp.data == null || typeof resp.data !== "object") return null;
            return unwrapQuizOkData(resp.data);
        }

        /** 练习/考试提交后，从网关包中取出 quiz 上游 data（含 grading_status）。 */
        function pickQuizSubmitResult(resp) {
            var d = resp && resp.data;
            if (!d || typeof d !== "object") return null;
            return unwrapQuizOkData(d);
        }

        /** 主观题异步阅卷后轮询 READY，就绪后触发本地 activity 汇总同步。 */
        function pollGradingUntilReady(attemptId, opts) {
            opts = opts || {};
            var maxMs = opts.maxMs != null ? opts.maxMs : 180000;
            var intervalMs = opts.intervalMs != null ? opts.intervalMs : 2500;
            var deadline = Date.now() + maxMs;
            var aid = String(attemptId || "").trim();
            if (!aid) return Promise.resolve({ ready: false, timeout: false });
            return new Promise(function (resolve) {
                function tick() {
                    if (Date.now() >= deadline) {
                        resolve({ ready: false, timeout: true });
                        return;
                    }
                    apiRequest("/api/exam-center/student/quiz/grading-status/" + encodeURIComponent(aid), "GET")
                        .then(function (resp) {
                            if (!resp || resp.__ok === false) {
                                setTimeout(tick, intervalMs);
                                return;
                            }
                            var ud = unwrapQuizOkData(resp.data);
                            var g = ud && typeof ud === "object" ? ud : null;
                            if (!g || typeof g.ready === "undefined") {
                                setTimeout(tick, intervalMs);
                                return;
                            }
                            if (g.ready === true) {
                                apiRequest("/api/exam-center/student/quiz/sync-attempt-result", "POST", {
                                    attempt_id: aid,
                                    attemptId: aid
                                }).finally(function () {
                                    resolve({ ready: true, grading: g, timeout: false });
                                });
                                return;
                            }
                            setTimeout(tick, intervalMs);
                        })
                        .catch(function () {
                            setTimeout(tick, intervalMs);
                        });
                }
                tick();
            });
        }

        /** 本地考试：轮询主观题整卷判分完成（aiword 本地 attempt）。 */
        function pollLocalGradingUntilReady(attemptId, opts) {
            opts = opts || {};
            var maxMs = opts.maxMs != null ? opts.maxMs : 180000;
            var intervalMs = opts.intervalMs != null ? opts.intervalMs : 2500;
            var deadline = Date.now() + maxMs;
            var aid = String(attemptId || "").trim();
            if (!aid) return Promise.resolve({ ready: false, timeout: false });
            return new Promise(function (resolve) {
                function tick() {
                    if (Date.now() >= deadline) {
                        resolve({ ready: false, timeout: true });
                        return;
                    }
                    apiRequest("/api/exam-center/student/attempts/" + encodeURIComponent(aid) + "/sync-grading", "POST", {})
                        .then(function () {
                            return apiRequest(
                                "/api/exam-center/student/attempts/" + encodeURIComponent(aid) + "/grading-status",
                                "GET"
                            );
                        })
                        .then(function (resp) {
                            if (!resp || resp.__ok === false) {
                                setTimeout(tick, intervalMs);
                                return;
                            }
                            var d = resp.data || {};
                            if (String(d.state || "") === "graded") {
                                resolve({ ready: true, grading: d, timeout: false });
                                return;
                            }
                            setTimeout(tick, intervalMs);
                        })
                        .catch(function () {
                            setTimeout(tick, intervalMs);
                        });
                }
                tick();
            });
        }

        function ensureActivityModal() {
            var el = document.getElementById("examActivityDetailModal");
            if (!el || !window.bootstrap || !window.bootstrap.Modal) return null;
            if (!window.__examActivityDetailModal) {
                window.__examActivityDetailModal = new window.bootstrap.Modal(el);
            }
            return window.__examActivityDetailModal;
        }

        function ensureStudentBankListModal() {
            var el = document.getElementById("examStudentBankListModal");
            if (!el || !window.bootstrap || !window.bootstrap.Modal) return null;
            if (!window.__examStudentBankListModal) {
                window.__examStudentBankListModal = new window.bootstrap.Modal(el);
            }
            return window.__examStudentBankListModal;
        }

        function showStudentBankListModal(title, metaLine, rows, listKind) {
            listKind = listKind || "inventory";
            captureDefaultStudentBankTheadOnce();
            var trh = document.querySelector("#examStudentBankListModal table thead tr");
            if (trh) {
                if (listKind === "wrongbook") {
                    trh.innerHTML =
                        '<th style="width:48px">序号</th>' +
                        "<th>题干</th>" +
                        '<th style="width:200px">选项</th>' +
                        '<th style="width:110px">学生答案</th>' +
                        '<th style="width:110px">标准答案</th>' +
                        '<th style="width:72px">判定</th>';
                } else if (window.__examBankListTheadDefault) {
                    trh.innerHTML = window.__examBankListTheadDefault;
                }
            }
            var t = document.getElementById("examStudentBankListTitle");
            var m = document.getElementById("examStudentBankListMeta");
            var tb = document.getElementById("examStudentBankListBody");
            if (t) t.textContent = title || "列表";
            if (m) m.textContent = metaLine || "—";
            if (!tb) return;
            var colspan = listKind === "wrongbook" ? "6" : "4";
            if (!rows || !rows.length) {
                tb.innerHTML =
                    '<tr><td colspan="' +
                    colspan +
                    '" class="text-muted small">暂无数据。</td></tr>';
            } else if (listKind === "wrongbook") {
                tb.innerHTML = "";
                rows.forEach(function (r, idx) {
                    if (!r || typeof r !== "object") return;
                    var tr = document.createElement("tr");
                    var stem = String(r.stem || r.title || "").trim();
                    var fakeIt = {
                        user_answer: r.user_answer,
                        answer: r.answer,
                        options: r.options,
                        options_json: r.options_json,
                        question_type: r.question_type,
                        type: r.type,
                        teacher_comment: "",
                    };
                    var ua = pickItemUserAnswer(fakeIt);
                    var ca = pickItemCorrectAnswer(fakeIt);
                    var uaStr =
                        ua == null ? "" : typeof ua === "object" ? safeJson(ua) : formatAnswerDetailDisplay(fakeIt, ua);
                    var caStr =
                        ca == null ? "" : typeof ca === "object" ? safeJson(ca) : formatAnswerDetailDisplay(fakeIt, ca);
                    tr.innerHTML =
                        '<td class="small">' +
                        String(idx + 1) +
                        "</td>" +
                        '<td class="small">' +
                        escSt(stem || "题目#" + String(r.question_id || r.id || "")) +
                        "</td>" +
                        '<td class="small">' +
                        formatOptionsCellHtml(r) +
                        "</td>" +
                        '<td class="small"><code class="text-danger fw-semibold">' +
                        escSt(uaStr) +
                        "</code></td>" +
                        '<td class="small"><code class="text-body">' +
                        escSt(caStr) +
                        "</code></td>" +
                        '<td class="small">错</td>';
                    tb.appendChild(tr);
                });
            } else {
                tb.innerHTML = "";
                rows.forEach(function (r) {
                    if (!r || typeof r !== "object") return;
                    var tr = document.createElement("tr");
                    tr.innerHTML =
                        '<td class="small"><code>' +
                        escSt(r.question_id || r.id || "") +
                        "</code></td>" +
                        '<td class="small">' +
                        escSt(r.stem || r.title || "") +
                        "</td>" +
                        '<td class="small">' +
                        escSt(r.question_type || r.type || "") +
                        "</td>" +
                        '<td class="small">' +
                        escSt(r.exam_track || "") +
                        "</td>";
                    tb.appendChild(tr);
                });
            }
            var modal = ensureStudentBankListModal();
            if (modal) modal.show();
        }

        function badgeHtml(ok) {
            if (ok === true) return '<span class="badge bg-success">通过</span>';
            if (ok === false) return '<span class="badge bg-danger">不通过</span>';
            return '<span class="badge bg-light text-dark">未知</span>';
        }

        function judgeLabel(ok) {
            return ok === true ? "对" : ok === false ? "错" : "未知";
        }

        function roundScoreInt(x) {
            var n = Number(x);
            if (!Number.isFinite(n)) return "";
            return String(Math.round(n));
        }

        function formatScoreSlashDisplay(score, total) {
            var a = score == null || score === "" ? "" : roundScoreInt(score);
            var b = total == null || total === "" ? "" : roundScoreInt(total);
            if (a && b) return a + "/" + b;
            return a || b || "";
        }

        function normAnswerPlainForCompare(v) {
            if (v === null || v === undefined) return "";
            if (typeof v === "boolean") return v ? "true" : "false";
            if (typeof v === "object") {
                try {
                    return JSON.stringify(v);
                } catch (e) {
                    return String(v);
                }
            }
            return String(v).trim();
        }

        function letterChoiceIndex(v) {
            if (v === null || v === undefined) return null;
            var s = String(v).trim().toUpperCase();
            if (s.length !== 1 || s < "A" || s > "Z") return null;
            return s.charCodeAt(0) - "A".charCodeAt(0);
        }

        function resolveLetterToOptionValue(value, it) {
            var opts = pickItemOptions(it);
            if (!opts.length) return value;
            var ix = letterChoiceIndex(value);
            if (ix === null || ix >= opts.length) return value;
            return opts[ix];
        }

        function trueFalseToBool(v) {
            if (v === true || v === false) return v;
            if (typeof v === "number" && isFinite(v)) return v !== 0;
            if (typeof v === "string") {
                var t = v.trim().toLowerCase();
                if (
                    t === "false" ||
                    t === "0" ||
                    t === "no" ||
                    t === "n" ||
                    t === "f" ||
                    t === "wrong" ||
                    t === "错误" ||
                    t === "错" ||
                    t === "否" ||
                    t === "不正确" ||
                    t === "不对"
                ) {
                    return false;
                }
                if (
                    t === "true" ||
                    t === "1" ||
                    t === "yes" ||
                    t === "y" ||
                    t === "t" ||
                    t === "正确" ||
                    t === "对" ||
                    t === "是" ||
                    t === "√"
                ) {
                    return true;
                }
                return false;
            }
            return false;
        }

        function tfMaybeLiteralJs(v) {
            if (v === true || v === false) return true;
            if (typeof v !== "string") return false;
            var s = v.trim();
            var sl = s.toLowerCase();
            if (sl === "true" || sl === "false" || sl === "1" || sl === "0") return true;
            return ["正确", "错误", "对", "错", "是", "否"].indexOf(s) >= 0;
        }

        function normSingleChoiceKeyJs(value, it) {
            var v = resolveLetterToOptionValue(value, it);
            if (v === null || v === undefined) return "";
            return String(v).trim().toLowerCase();
        }

        function normMcKeysSorted(raw, it) {
            var items = Array.isArray(raw) ? raw : raw == null ? [] : [raw];
            var out = [];
            var j;
            for (j = 0; j < items.length; j++) {
                var v = resolveLetterToOptionValue(items[j], it);
                var k = v == null ? "" : String(v).trim().toLowerCase();
                if (k) out.push(k);
            }
            out.sort();
            return out;
        }

        function multipleChoiceAnswersEqual(ca, ua, it) {
            var a = normMcKeysSorted(ca, it);
            var b = normMcKeysSorted(ua, it);
            if (!a.length) return false;
            if (a.length !== b.length) return false;
            var i;
            for (i = 0; i < a.length; i++) {
                if (a[i] !== b[i]) return false;
            }
            return true;
        }

        /** 客观题比对：与 aicheckword `_score_objective_answer` / aiword `_objective_answers_equivalent_aiword` 维度一致 */
        function objectiveAnswersEqualJs(it, ua, ca) {
            if (!it || typeof it !== "object") {
                return normAnswerPlainForCompare(ua) === normAnswerPlainForCompare(ca);
            }
            var opts = pickItemOptions(it);
            var qt = String(it.question_type || it.type || "").toLowerCase();
            if (qt === "true_false") {
                var aa = resolveLetterToOptionValue(ca, it);
                var uu = resolveLetterToOptionValue(ua, it);
                return trueFalseToBool(aa) === trueFalseToBool(uu);
            }
            if (qt === "single_choice") {
                return normSingleChoiceKeyJs(ua, it) === normSingleChoiceKeyJs(ca, it);
            }
            if (qt === "multiple_choice") {
                return multipleChoiceAnswersEqual(ca, ua, it);
            }
            if (opts.length) {
                if (normSingleChoiceKeyJs(ua, it) === normSingleChoiceKeyJs(ca, it)) return true;
                var ur = resolveLetterToOptionValue(ua, it);
                var cr = resolveLetterToOptionValue(ca, it);
                if (typeof cr === "boolean" || tfMaybeLiteralJs(cr) || tfMaybeLiteralJs(ur)) {
                    return trueFalseToBool(cr) === trueFalseToBool(ur);
                }
            }
            return normAnswerPlainForCompare(ua) === normAnswerPlainForCompare(ca);
        }

        /** 详情弹窗：学生/标准答案与判分维度一致展示（判断题不显裸字母 A）。 */
        function formatAnswerDetailDisplay(it, raw) {
            if (raw === null || raw === undefined) return "";
            if (typeof raw === "object") {
                try {
                    return JSON.stringify(raw);
                } catch (e) {
                    return String(raw);
                }
            }
            var qt = String(it && it.question_type ? it.question_type : it && it.type ? it.type : "").toLowerCase();
            var opts = it && typeof it === "object" ? pickItemOptions(it) : [];
            var ix = letterChoiceIndex(raw);
            if (opts.length && ix !== null && ix >= 0 && ix < opts.length) {
                var lbl = String(opts[ix]);
                if (qt === "true_false") {
                    return trueFalseToBool(lbl) ? "正确" : "错误";
                }
                return String.fromCharCode(65 + ix) + "（" + lbl + "）";
            }
            if (qt === "true_false" || (opts.length === 2 && (typeof raw === "boolean" || tfMaybeLiteralJs(String(raw))))) {
                return trueFalseToBool(raw) ? "正确" : "错误";
            }
            return String(raw);
        }

        /** 与后端/快照字段对齐：取学生作答（含 camelCase、本地快照列名）。 */
        function pickItemUserAnswer(it) {
            if (!it || typeof it !== "object") return undefined;
            var keys = [
                "user_answer",
                "selected_answer",
                "userAnswer",
                "selectedAnswer",
                "student_answer",
                "studentAnswer",
                "response"
            ];
            var k;
            for (k = 0; k < keys.length; k++) {
                var v = it[keys[k]];
                if (v !== undefined && v !== null) return v;
            }
            return undefined;
        }

        /** 与后端/快照字段对齐：取标准答案。 */
        function pickItemCorrectAnswer(it) {
            if (!it || typeof it !== "object") return undefined;
            var keys = [
                "answer",
                "correct_answer",
                "correctAnswer",
                "standard_answer",
                "standardAnswer",
                "answer_key",
                "answerKey"
            ];
            var k2;
            for (k2 = 0; k2 < keys.length; k2++) {
                var v2 = it[keys[k2]];
                if (v2 !== undefined && v2 !== null) return v2;
            }
            return undefined;
        }

        function pickItemOptions(it) {
            if (!it || typeof it !== "object") return [];
            var o = it.options;
            if (Array.isArray(o) && o.length) return o;
            if (Array.isArray(it.options_json) && it.options_json.length) return it.options_json;
            var oj = it.options_json;
            if (typeof oj === "string" && oj.trim()) {
                try {
                    var parsed = JSON.parse(oj);
                    if (Array.isArray(parsed) && parsed.length) return parsed;
                } catch (eOpt) {}
            }
            return [];
        }

        /** 详情/错题本：选项列 HTML（多行 A./B./…）。 */
        function formatOptionsCellHtml(it) {
            var opts = pickItemOptions(it);
            if (!opts.length) return '<span class="text-muted">—</span>';
            var parts = [];
            var i;
            for (i = 0; i < opts.length; i++) {
                parts.push(
                    "<div>" + escSt(String.fromCharCode(65 + i) + ". " + String(opts[i])) + "</div>"
                );
            }
            return '<div class="small text-break">' + parts.join("") + "</div>";
        }

        function captureDefaultStudentBankTheadOnce() {
            var tr = document.querySelector("#examStudentBankListModal table thead tr");
            if (tr && !window.__examBankListTheadDefault) {
                window.__examBankListTheadDefault = tr.innerHTML;
            }
        }

        /** 当 is_correct 未回填时，用学生答案与标准答案字符串比对补全判定（客观题）。 */
        function deriveItemCorrectness(it) {
            if (!it || typeof it !== "object") return null;
            var ic = it.is_correct;
            if (ic === true || ic === 1 || ic === "1") return true;
            if (ic === false || ic === 0 || ic === "0") return false;
            var tc = String(it.teacher_comment || it.teacherComment || "").trim();
            if (tc.indexOf("pending_subjective") >= 0) return null;
            var ua = pickItemUserAnswer(it);
            var ca = pickItemCorrectAnswer(it);
            if (ua === undefined || ua === null || ca === undefined || ca === null) return null;
            return objectiveAnswersEqualJs(it, ua, ca);
        }

        function judgeLabelFromItem(it) {
            if (!it || typeof it !== "object") return judgeLabel(null);
            if (it.subjective_needed === true || it.subjectiveNeeded === true) {
                var sc = it.subjective_score != null ? Number(it.subjective_score) : null;
                if (sc != null && isFinite(sc)) {
                    var pct = Math.round(Math.max(0, Math.min(1, sc)) * 100);
                    return '<span class="badge bg-info text-dark">主观</span> <span class="small">得分 ' + String(pct) + "/100</span>";
                }
                return '<span class="badge bg-warning text-dark">阅卷中</span>';
            }
            var tc = String(it.teacher_comment || it.teacherComment || "").trim();
            if (tc.indexOf("pending_subjective") >= 0 || tc.indexOf("阅卷中") >= 0) {
                return '<span class="badge bg-warning text-dark">阅卷中</span>';
            }
            var pen = deriveItemCorrectness(it);
            if (pen === true) return "对";
            if (pen === false) return "错";
            return judgeLabel(null);
        }

        function renderActivityDetailModal(payload) {
            var metaEl = document.getElementById("examActivityDetailMeta");
            var bodyEl = document.getElementById("examActivityDetailBody");
            if (!metaEl || !bodyEl) return;
            var d = payload && payload.data ? payload.data : {};
            var act = d.activity || {};
            var det = d.detail || {};
            var items = Array.isArray(d.attempt_items) ? d.attempt_items : [];
            var total = items.length;
            var correct = 0;
            var wrong = 0;
            items.forEach(function (it) {
                if (!it || typeof it !== "object") return;
                var pen = deriveItemCorrectness(it);
                if (pen === true) correct += 1;
                else if (pen === false) wrong += 1;
            });
            var scoreTxt = "";
            if (det && det.score != null) {
                scoreTxt = formatScoreSlashDisplay(det.score, det.total_score);
            }
            if (!scoreTxt && act.result_summary && String(act.result_summary).indexOf("阅卷中") >= 0) {
                scoreTxt = "阅卷中";
            }
            var passedDer = det && det.passed;
            try {
                if (
                    passedDer !== true &&
                    passedDer !== false &&
                    det &&
                    det.score != null &&
                    det.pass_score != null
                ) {
                    var sN = Number(det.score);
                    var pN = Number(det.pass_score);
                    if (Number.isFinite(sN) && Number.isFinite(pN)) {
                        passedDer = Math.round(sN) >= Math.round(pN) ? true : false;
                    }
                }
            } catch (ePd) {}
            var passTxt = passedDer === true ? badgeHtml(true) : passedDer === false ? badgeHtml(false) : "";
            metaEl.innerHTML =
                '<span class="me-2">时间：' +
                escSt(act.created_at || "-") +
                "</span>" +
                '<span class="me-2">类型：' +
                escSt(act.mode || "-") +
                "</span>" +
                (scoreTxt ? '<span class="me-2">分数：' + escSt(scoreTxt) + "</span>" : "") +
                (passTxt ? '<span class="me-2">' + passTxt + "</span>" : "") +
                '<span class="me-2">题数：' +
                String(total) +
                "</span>" +
                '<span class="me-2">对：' +
                String(correct) +
                "</span>" +
                '<span class="me-2">错：' +
                String(wrong) +
                "</span>";
            if (!items.length) {
                bodyEl.innerHTML =
                    '<tr><td colspan="6" class="text-muted small">暂无题目明细（无答题记录 attempt、上游暂无答案或可参考下方接口响应）。</td></tr>';
                return;
            }
            bodyEl.innerHTML = "";
            items.forEach(function (it, idx) {
                var tr = document.createElement("tr");
                var stem = String(it.stem || "").trim();
                var ua = pickItemUserAnswer(it);
                var ca = pickItemCorrectAnswer(it);
                var uaStr =
                    ua == null ? "" : typeof ua === "object" ? safeJson(ua) : formatAnswerDetailDisplay(it, ua);
                var caStr =
                    ca == null ? "" : typeof ca === "object" ? safeJson(ca) : formatAnswerDetailDisplay(it, ca);
                var pen = deriveItemCorrectness(it);
                var uaCls = pen === false ? "text-danger fw-semibold" : "text-body";
                var caCls = "text-body";
                tr.innerHTML =
                    '<td class="small">' +
                    String(idx + 1) +
                    "</td>" +
                    '<td class="small">' +
                    escSt(stem || ("题目#" + String(it.question_id || ""))) +
                    "</td>" +
                    '<td class="small">' +
                    formatOptionsCellHtml(it) +
                    "</td>" +
                    '<td class="small"><code class="' +
                    uaCls +
                    '">' +
                    escSt(uaStr) +
                    "</code></td>" +
                    '<td class="small"><code class="' +
                    caCls +
                    '">' +
                    escSt(caStr) +
                    (it.subjective_reason
                        ? '<div class="text-muted small mt-1">' + escSt(String(it.subjective_reason)) + "</div>"
                        : "") +
                    (Array.isArray(it.evidence_used) && it.evidence_used.length
                        ? '<div class="text-muted small mt-1">证据：' +
                          escSt(
                              it.evidence_used
                                  .map(function (e) { return (e && e.source_file) ? String(e.source_file) : ""; })
                                  .filter(function (s) { return s; })
                                  .join("，")
                          ) +
                          "</div>"
                        : "") +
                    "</code></td>" +
                    '<td class="small">' +
                    judgeLabelFromItem(it) +
                    "</td>";
                bodyEl.appendChild(tr);
            });
        }

        /** 详情 + attempt-items 并行拉取，缩短首屏阻塞时间。 */
        async function openExamActivityDetail(activityId, renderBridge) {
            var pid = encodeURIComponent(String(activityId));
            var metaEl = document.getElementById("examActivityDetailMeta");
            var bodyEl = document.getElementById("examActivityDetailBody");
            if (!activityId) return;
            if (bodyEl) {
                bodyEl.innerHTML =
                    '<tr><td colspan="6" class="text-muted small">并行加载明细…</td></tr>';
            }
            if (metaEl) {
                metaEl.innerHTML =
                    '<span class="text-muted small">正在加载时间与分数摘要…</span>';
            }
            try {
                var out = await Promise.all([
                    apiRequest("/api/exam-center/activity/" + pid, "GET"),
                    apiRequest("/api/exam-center/activity/" + pid + "/attempt-items", "GET"),
                ]);
                var d = out[0];
                var up = out[1];
                if (typeof renderBridge === "function") {
                    renderBridge(d);
                }
                var items = [];
                if (up && up.data && Array.isArray(up.data.items)) {
                    items = up.data.items;
                }
                var base = d && d.data && typeof d.data === "object" ? d.data : {};
                renderActivityDetailModal({
                    data: Object.assign({}, base, { attempt_items: items }),
                });
            } catch (e) {
                if (typeof renderBridge === "function") {
                    renderBridge({
                        code: "UI_ERROR",
                        message: e.message,
                        data: null,
                    });
                }
                if (bodyEl) {
                    bodyEl.innerHTML =
                        '<tr><td colspan="6" class="text-danger small">加载失败：' +
                        escSt(e.message) +
                        "</td></tr>";
                }
                if (metaEl) {
                    metaEl.textContent = "加载中断";
                }
            }
        }

        function scrollExamApiResultIntoView() {
            if (!resultPre) return;
            try {
                resultPre.scrollIntoView({ behavior: "smooth", block: "nearest" });
            } catch (eScroll2) {}
        }

        function normalizeAttemptIdAsIntString(raw) {
            var s = String(raw == null ? "" : raw).trim();
            if (!s) return "";
            var m = s.match(/\d+/);
            if (m && m[0]) return m[0];
            // UUID/纯字符串等无数字时，转稳定正整数，避免上游 int_parsing
            var hash = 0;
            for (var i = 0; i < s.length; i++) {
                hash = ((hash << 5) - hash + s.charCodeAt(i)) | 0;
            }
            var n = Math.abs(hash) || 1;
            return String(n);
        }

        function pickQuestionItemsFromRoot(root) {
            if (!root || typeof root !== "object") return [];
            var keys = ["questions", "items", "question_items", "questionItems", "entries"];
            var k;
            var arr;
            for (k = 0; k < keys.length; k++) {
                arr = root[keys[k]];
                if (Array.isArray(arr) && arr.length && typeof arr[0] === "object") {
                    return arr;
                }
            }
            var nested = root.set || root.load_set || root.paper || root.quiz;
            if (nested && typeof nested === "object") {
                for (k = 0; k < keys.length; k++) {
                    arr = nested[keys[k]];
                    if (Array.isArray(arr) && arr.length && typeof arr[0] === "object") {
                        return arr;
                    }
                }
            }
            if (root.data && typeof root.data === "object") {
                return pickQuestionItemsFromRoot(root.data);
            }
            return [];
        }

        function qidFromItem(it, idx) {
            if (!it || typeof it !== "object") return "idx-" + idx;
            var q = String(it.question_id || it.questionId || it.id || "").trim();
            return q || "idx-" + idx;
        }

        function stemFromItem(it, idx) {
            if (!it || typeof it !== "object") return "";
            var stem = String(it.stem || it.title || it.question || "").trim();
            if (typeof it.question === "object" && it.question) {
                stem = String(it.question.stem || it.question.title || stem).trim();
            }
            return stem || "题目#" + String(idx + 1);
        }

        function submissionQuestionsSnapshotPayload() {
            if (!sessionState.questions || !sessionState.questions.length) return [];
            return sessionState.questions.map(function (it, idx) {
                return { question_id: qidFromItem(it, idx), stem: stemFromItem(it, idx) };
            });
        }

        function optionsFromItem(it) {
            var o = it.options;
            if (o && typeof o === "object" && !Array.isArray(o)) {
                o = Object.keys(o).map(function (k) {
                    return { value: k, label: String(o[k] == null ? "" : o[k]) };
                });
            }
            if (!Array.isArray(o)) return [];
            return o.map(function (x, i) {
                if (x && typeof x === "object") {
                    var v = x.value != null ? x.value : x.key != null ? x.key : x.id != null ? x.id : i;
                    var lab = x.label != null ? x.label : x.text != null ? x.text : x.title != null ? x.title : v;
                    return { value: String(v), label: String(lab) };
                }
                return { value: String(i), label: String(x) };
            });
        }

        function questionTypeFromItem(it) {
            if (!it || typeof it !== "object") return "single_choice";
            var qt = String(it.question_type || it.questionType || it.type || "").trim().toLowerCase();
            if (!qt && it.question && typeof it.question === "object") {
                qt = String(it.question.question_type || it.question.type || "").trim().toLowerCase();
            }
            if (qt === "single" || qt === "sc" || qt === "singlechoice") return "single_choice";
            if (qt === "multiple" || qt === "mc" || qt === "multiplechoice") return "multiple_choice";
            if (qt === "tf" || qt === "judge" || qt === "truefalse") return "true_false";
            if (qt === "case" || qt === "analysis" || qt === "caseanalysis") return "case_analysis";
            if (qt === "single_choice" || qt === "multiple_choice" || qt === "true_false" || qt === "case_analysis") return qt;
            return qt || "single_choice";
        }

        function questionTypeLabelZh(qt) {
            var t = String(qt || "").trim().toLowerCase();
            if (t === "single_choice") return "单选题";
            if (t === "multiple_choice") return "多选题";
            if (t === "true_false") return "判断题";
            if (t === "case_analysis") return "案例分析题";
            return "其它题型";
        }

        function indexToLetterAZ(i) {
            var n = Number(i);
            if (!Number.isFinite(n) || n < 0) return "";
            return "ABCDEFGHIJKLMNOPQRSTUVWXYZ".charAt(n) || "";
        }

        function draftStorageKey() {
            var base = sessionState.mode || "x";
            var a = sessionState.assignmentId || "";
            var s = sessionState.setId || "";
            var t = sessionState.attemptId || sessionState.sessionId || "";
            return "aiword_exam_draft__" + base + "__" + String(a || s || "unknown") + "__" + String(t || "noattempt");
        }

        function loadDraftAnswers() {
            var k = draftStorageKey();
            sessionState.draftKey = k;
            sessionState.draftAnswers = {};
            try {
                var raw = localStorage.getItem(k);
                if (!raw) return;
                var obj = JSON.parse(raw);
                if (obj && typeof obj === "object") sessionState.draftAnswers = obj;
            } catch (e) {
                sessionState.draftAnswers = {};
            }
        }

        function saveDraftAnswers() {
            try {
                if (!sessionState.draftKey) sessionState.draftKey = draftStorageKey();
                localStorage.setItem(sessionState.draftKey, JSON.stringify(sessionState.draftAnswers || {}));
            } catch (e) {}
        }

        function clearDraftAnswers() {
            try {
                if (!sessionState.draftKey) sessionState.draftKey = draftStorageKey();
                localStorage.removeItem(sessionState.draftKey);
            } catch (e) {}
            sessionState.draftAnswers = {};
        }

        function updateDraftAnswer(qid, v) {
            if (!qid) return;
            if (!sessionState.draftAnswers || typeof sessionState.draftAnswers !== "object") sessionState.draftAnswers = {};
            if (v == null || (Array.isArray(v) && !v.length) || (typeof v === "string" && !String(v).trim())) {
                delete sessionState.draftAnswers[qid];
            } else {
                sessionState.draftAnswers[qid] = v;
            }
            saveDraftAnswers();
            try {
                if (metaIx) {
                    var n = Object.keys(sessionState.draftAnswers || {}).length;
                    var base = metaIx.textContent || "";
                    base = base.replace(/\s*（已暂存.*?）\s*$/, "");
                    metaIx.textContent = base + "（已暂存 " + String(n) + " 题）";
                }
            } catch (e) {}
        }

        function hideStudentInteraction() {
            if (cardIx) cardIx.classList.add("d-none");
            if (qListIx) qListIx.innerHTML = "";
            sessionState = {
                mode: "",
                setId: "",
                sessionId: "",
                attemptId: "",
                assignmentId: "",
                assignmentLabel: "",
                questions: [],
                upstreamSnapshot: null,
                draftKey: "",
                draftAnswers: {}
            };
        }

        /** 学生端：开始练习/开考前先展示独立交互区（加载态），避免空白等待。 */
        function openInteractionPending(titleLine, metaLine) {
            if (!cardIx || !titleIx || !metaIx || !qListIx) return false;
            titleIx.textContent = titleLine || "请稍候…";
            metaIx.textContent = metaLine || "";
            qListIx.innerHTML =
                '<div class="card border-primary border-opacity-50"><div class="card-body py-5 text-center">' +
                '<div class="spinner-border text-primary mb-3" role="status" aria-hidden="true"></div>' +
                '<div class="fw-semibold">' +
                escSt(titleLine || "加载中…") +
                "</div>" +
                '<div class="small text-muted mt-2">加载完成后将在此区域显示题干与选项。</div>' +
                "</div></div>";
            cardIx.classList.remove("d-none");
            try {
                cardIx.scrollIntoView({ behavior: "smooth", block: "nearest" });
            } catch (eScr) {}
            return true;
        }

        function showInteractionError(titleLine, errMsg) {
            if (!cardIx || !titleIx || !qListIx) return;
            titleIx.textContent = titleLine || "无法继续";
            if (metaIx) metaIx.textContent = "";
            qListIx.innerHTML =
                '<div class="alert alert-danger mb-0" role="alert">' +
                escSt(errMsg || "发生错误") +
                "</div>";
            cardIx.classList.remove("d-none");
            try {
                cardIx.scrollIntoView({ behavior: "smooth", block: "nearest" });
            } catch (eScr2) {}
        }

        function renderQuestionCard(it, idx) {
            var qid = qidFromItem(it, idx);
            var qt = questionTypeFromItem(it);
            var stem = String(it.stem || it.title || it.question || "题目").trim();
            if (typeof it.question === "object" && it.question) {
                stem = String(it.question.stem || it.question.title || stem).trim();
            }
            var opts = qt === "case_analysis" ? [] : optionsFromItem(it);
            var nm = "stq-" + safeInputNamePart(qid);
            var body;
            var draftV = sessionState.draftAnswers ? sessionState.draftAnswers[qid] : null;
            if (qt === "multiple_choice" && opts.length) {
                var picked = Array.isArray(draftV) ? draftV.map(String) : typeof draftV === "string" ? [draftV] : [];
                body = opts
                    .map(function (o, j) {
                        var letter = indexToLetterAZ(j) || String(j);
                        var oid = nm + "-" + j;
                        var checked = picked.indexOf(letter) >= 0 ? ' checked' : '';
                        return (
                            '<div class="form-check">' +
                            '<input class="form-check-input" type="checkbox" name="' +
                            escSt(nm) +
                            '" data-qid="' +
                            escSt(qid) +
                            '" data-qtype="' +
                            escSt(qt) +
                            '" id="' +
                            escSt(oid) +
                            '" value="' +
                            escSt(letter) +
                            '"' +
                            checked +
                            '>' +
                            '<label class="form-check-label small" for="' +
                            escSt(oid) +
                            '">' +
                            escSt(letter + ". " + String(o.label || "")) +
                            "</label></div>"
                        );
                    })
                    .join("");
            } else if (opts.length && qt !== "case_analysis") {
                var pickedOne = draftV != null ? String(draftV) : "";
                body = opts
                    .map(function (o, j) {
                        var letter = indexToLetterAZ(j) || String(j);
                        var oid = nm + "-" + j;
                        var checked = pickedOne && pickedOne === letter ? ' checked' : '';
                        return (
                            '<div class="form-check">' +
                            '<input class="form-check-input" type="radio" name="' +
                            escSt(nm) +
                            '" data-qid="' +
                            escSt(qid) +
                            '" data-qtype="' +
                            escSt(qt) +
                            '" id="' +
                            escSt(oid) +
                            '" value="' +
                            escSt(letter) +
                            '"' +
                            checked +
                            '>' +
                            '<label class="form-check-label small" for="' +
                            escSt(oid) +
                            '">' +
                            escSt(letter + ". " + String(o.label || "")) +
                            "</label></div>"
                        );
                    })
                    .join("");
            } else {
                var tv = draftV != null ? String(draftV) : "";
                body =
                    '<textarea class="form-control form-control-sm" rows="3" data-student-answer="' +
                    escSt(qid) +
                    '" data-qid="' +
                    escSt(qid) +
                    '" data-qtype="' +
                    escSt(qt) +
                    '" placeholder="' +
                    escSt(qt === "case_analysis" ? "请在此输入案例分析作答（文本）" : "作答") +
                    '">' +
                    escSt(tv) +
                    "</textarea>";
            }
            return (
                '<div class="card mb-2"><div class="card-body py-2"><div class="fw-semibold small mb-2">' +
                (idx + 1) +
                ". " +
                escSt(stem) +
                "</div>" +
                body +
                "</div></div>"
            );
        }

        function showStudentInteraction(mode, inner, questions) {
            if (!cardIx || !qListIx) return;
            sessionState.mode = mode;
            sessionState.setId = pickSetIdFromAny(inner);
            sessionState.sessionId = String(
                inner.practice_session_id ||
                    inner.session_id ||
                    inner.practiceSessionId ||
                    inner.sessionId ||
                    ""
            ).trim();
            sessionState.attemptId = pickAttemptIdFromAny(inner);
            if (mode === "exam") {
                sessionState.assignmentId = String(inner.assignment_id || inner.assignmentId || sessionState.assignmentId || "").trim();
            }
            sessionState.questions = questions || [];
            if (titleIx) {
                titleIx.textContent = mode === "exam" ? "考试作答中" : "练习作答中";
            }
            if (metaIx) {
                metaIx.textContent =
                    "题目数=" +
                    sessionState.questions.length +
                    (sessionState.setId ? "，set=" + sessionState.setId : "") +
                    (sessionState.sessionId ? "，session=" + sessionState.sessionId : "") +
                    (sessionState.attemptId ? "，attempt=" + sessionState.attemptId : "");
            }
            loadDraftAnswers();
            var groups = {
                single_choice: [],
                multiple_choice: [],
                true_false: [],
                case_analysis: [],
                other: []
            };
            sessionState.questions.forEach(function (it) {
                var qt = questionTypeFromItem(it);
                if (qt === "single_choice") groups.single_choice.push(it);
                else if (qt === "multiple_choice") groups.multiple_choice.push(it);
                else if (qt === "true_false") groups.true_false.push(it);
                else if (qt === "case_analysis") groups.case_analysis.push(it);
                else groups.other.push(it);
            });
            function secHtml(qtKey, arr) {
                if (!arr || !arr.length) return "";
                var label = questionTypeLabelZh(qtKey);
                var head =
                    '<div class="mt-3 mb-2 d-flex align-items-center justify-content-between">' +
                    '<div class="fw-semibold">' +
                    escSt(label) +
                    "（" +
                    String(arr.length) +
                    "）</div>" +
                    (qtKey === "multiple_choice"
                        ? '<div class="small text-muted">可多选</div>'
                        : qtKey === "case_analysis"
                        ? '<div class="small text-muted">文本作答</div>'
                        : '<div class="small text-muted">单选</div>') +
                    "</div>";
                var body = arr
                    .map(function (it, i) {
                        return renderQuestionCard(it, i);
                    })
                    .join("");
                return head + body;
            }
            qListIx.innerHTML =
                secHtml("single_choice", groups.single_choice) +
                secHtml("multiple_choice", groups.multiple_choice) +
                secHtml("true_false", groups.true_false) +
                secHtml("case_analysis", groups.case_analysis) +
                secHtml("other", groups.other);
            sessionState.upstreamSnapshot = Object.assign({}, inner);
            cardIx.classList.remove("d-none");
            try {
                if (metaIx) {
                    var n2 = Object.keys(sessionState.draftAnswers || {}).length;
                    if (n2 > 0) {
                        metaIx.textContent = metaIx.textContent + "（已暂存 " + String(n2) + " 题）";
                    } else {
                        metaIx.textContent = metaIx.textContent + "（自动暂存已开启）";
                    }
                }
            } catch (eMetaDraft) {}

            // 绑定暂存事件（radio/checkbox/textarea）
            try {
                if (qListIx) {
                    qListIx.querySelectorAll('input[type="radio"][data-qid]').forEach(function (el) {
                        el.addEventListener("change", function () {
                            updateDraftAnswer(String(el.getAttribute("data-qid") || ""), String(el.value || ""));
                        });
                    });
                    qListIx.querySelectorAll('input[type="checkbox"][data-qid]').forEach(function (el) {
                        el.addEventListener("change", function () {
                            var qid = String(el.getAttribute("data-qid") || "");
                            var nm = el.getAttribute("name") || "";
                            var checked = [];
                            qListIx.querySelectorAll('input[type="checkbox"][name="' + nm + '"]:checked').forEach(function (c) {
                                checked.push(String(c.value || "").trim());
                            });
                            updateDraftAnswer(qid, checked);
                        });
                    });
                    qListIx.querySelectorAll('textarea[data-qid]').forEach(function (el) {
                        el.addEventListener("input", function () {
                            updateDraftAnswer(String(el.getAttribute("data-qid") || ""), String(el.value || ""));
                        });
                    });
                }
            } catch (eBindDraft) {}
            try {
                cardIx.scrollIntoView({ behavior: "smooth", block: "nearest" });
            } catch (eScroll) {}
        }

        function collectStudentResponses() {
            var out = [];
            function guessLetterFromLabelText(t) {
                var s = String(t || "").trim();
                if (!s) return "";
                var m = s.match(/^\s*([A-H])(?:[\.\、\:\：\)\）\s]|$)/i);
                if (m && m[1]) return String(m[1]).toUpperCase();
                return "";
            }

            function indexToLetter(v) {
                var n = parseInt(String(v || "").trim(), 10);
                if (!Number.isFinite(n) || n < 0) return "";
                var code = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".charAt(n) || "";
                return code;
            }

            function normalizePickedAnswer(pickedEl) {
                if (!pickedEl) return "";
                var v = String(pickedEl.value == null ? "" : pickedEl.value).trim();
                // 若 value 为数字（常见为数组选项下标），尽量转为 A/B/C/D…（与标准答案常见维度一致）
                if (/^\d+$/.test(v)) {
                    try {
                        var id = pickedEl.getAttribute("id") || "";
                        if (id) {
                            var lab = document.querySelector('label[for="' + id.replace(/"/g, '\\"') + '"]');
                            if (lab) {
                                var lt = guessLetterFromLabelText(lab.textContent || "");
                                if (lt) return lt;
                            }
                        }
                    } catch (eLab) {}
                    var byIdx = indexToLetter(v);
                    if (byIdx) return byIdx;
                }
                return v;
            }

            sessionState.questions.forEach(function (it, idx) {
                var qid = qidFromItem(it, idx);
                var qt = questionTypeFromItem(it);
                var nm = "stq-" + safeInputNamePart(qid);
                if (qt === "multiple_choice") {
                    var cands = qListIx
                        ? qListIx.querySelectorAll('input[type="checkbox"][name="' + nm + '"]:checked')
                        : document.querySelectorAll('input[type="checkbox"][name="' + nm + '"]:checked');
                    var arr = [];
                    cands &&
                        cands.forEach &&
                        cands.forEach(function (el) {
                            arr.push(normalizePickedAnswer(el));
                        });
                    if (arr.length) {
                        out.push({ question_id: qid, answer: arr });
                        return;
                    }
                } else {
                    var picked = qListIx
                        ? qListIx.querySelector('input[type="radio"][name="' + nm + '"]:checked')
                        : document.querySelector('input[type="radio"][name="' + nm + '"]:checked');
                    if (picked) {
                        out.push({ question_id: qid, answer: normalizePickedAnswer(picked) });
                        return;
                    }
                }
                var ta = null;
                if (qListIx) {
                    qListIx.querySelectorAll("textarea[data-student-answer]").forEach(function (el) {
                        if (el.getAttribute("data-student-answer") === qid) {
                            ta = el;
                        }
                    });
                }
                if (ta) {
                    var v = String(ta.value || "").trim();
                    if (v) out.push({ question_id: qid, answer: v });
                }
            });
            return out;
        }

        function responsesToAnswerMap(rows) {
            var o = {};
            rows.forEach(function (r) {
                if (r && r.question_id) o[r.question_id] = r.answer;
            });
            return o;
        }

        async function loadStudentAssignments() {
            if (!tbodyAssign) return;
            tbodyAssign.innerHTML = '<tr><td colspan="6" class="text-muted small">加载中…</td></tr>';
            try {
                var data = await apiRequest("/api/exam-center/student/assignments", "GET");
                render(data);
                if (data && data.__ok === false) {
                    tbodyAssign.innerHTML =
                        '<tr><td colspan="6" class="text-danger small">' + escSt(data.message || "加载失败") + "</td></tr>";
                    return;
                }
                var list = data && data.data && data.data.assignments ? data.data.assignments : [];
                if (!Array.isArray(list) || !list.length) {
                    tbodyAssign.innerHTML = '<tr><td colspan="6" class="text-muted small">暂无考试任务（等待老师下发）。</td></tr>';
                    return;
                }
                tbodyAssign.innerHTML = "";
                list.forEach(function (a) {
                    if (!a || typeof a !== "object") return;
                    var aid = String(a.id || a.assignment_id || a.assignmentId || "").trim();
                    if (!aid) return;
                    var name = String(a.name || a.title || a.label || aid).trim() || aid;
                    var setId = String(a.set_id || a.setId || "").trim();
                    var diff = String(a.difficulty || "").trim().toLowerCase();
                    var dueIso = String(a.due_at || a.dueAt || "").trim();
                    var dueCell = dueIso ? examDueCompletionPillHtml(dueIso) : '<span class="text-muted">—</span>';
                    var tr = document.createElement("tr");
                    tr.innerHTML =
                        '<td class="small">' + escSt(name) + "</td>" +
                        '<td class="small"><code>' + escSt(aid) + "</code></td>" +
                        '<td class="small"><code>' + escSt(setId || "—") + "</code></td>" +
                        '<td class="small">' + escSt(difficultyLabelZh(diff)) + "</td>" +
                        '<td class="small text-center">' + dueCell + "</td>" +
                        '<td class="small assign-op"></td>';
                    tbodyAssign.appendChild(tr);
                    var op = tr.querySelector(".assign-op");
                    if (op) {
                        var b = document.createElement("button");
                        b.type = "button";
                        b.className = "btn btn-sm btn-outline-primary";
                        b.textContent = "开始考试";
                        b.addEventListener("click", async function () {
                            openInteractionPending("正在加载考试试卷…", "任务：" + escSt(name) + "（" + escSt(aid) + "）");
                            setButtonLoading(b, true, "开考中…");
                            try {
                                var data2 = await apiRequest("/api/exam-center/student/exams/start-local", "POST", {
                                    assignment_id: aid
                                });
                                if (data2 && data2.__ok === false) {
                                    showInteractionError("无法开始考试", data2.message || "请求失败");
                                    if (getExamRole() !== "student") render(data2);
                                    return;
                                }
                                render(data2);
                                var inner = data2 && data2.data ? data2.data : {};
                                var qarr = Array.isArray(inner.items) ? inner.items : [];
                                inner.assignment_id = aid;
                                inner.assignmentId = aid;
                                inner.assignment_label = name;
                                inner.assignmentLabel = name;
                                showStudentInteraction("exam", inner, qarr);
                                if (sessionState.mode === "exam" && !sessionState.questions.length) {
                                    showInteractionError(
                                        "未加载到题目",
                                        "考试已开始，但未解析到题目列表。请稍后重试或联系管理员。"
                                    );
                                    if (getExamRole() !== "student") {
                                        render({
                                            code: "UI",
                                            message:
                                                "考试已开始，但未解析到题目列表，请核对 data 是否含 questions/items。",
                                            data: null
                                        });
                                    }
                                } else if (sessionState.mode === "exam") {
                                    studentShowFeedback("试卷已加载，请作答后提交。", "success");
                                }
                            } catch (e) {
                                showInteractionError("开考失败", e.message || "网络或服务异常");
                                if (getExamRole() !== "student") {
                                    render({ code: "UI_ERROR", message: e.message, data: null });
                                }
                            } finally {
                                setButtonLoading(b, false);
                            }
                        });
                        op.appendChild(b);
                    }
                });
            } catch (e) {
                tbodyAssign.innerHTML = '<tr><td colspan="6" class="text-danger small">加载失败：' + escSt(e.message) + "</td></tr>";
            }
        }

        function historyResultCellHtml(r) {
            var scoreText =
                r && r.score != null
                    ? formatScoreSlashDisplay(r.score, r.total_score)
                    : "";
            var parts = [];
            if (scoreText) {
                parts.push('<div class="text-muted small">分数：' + escSt(scoreText) + "</div>");
            }
            if (r.passed === true) {
                parts.push('<div><span class="text-success fw-semibold">通过</span></div>');
            } else if (r.passed === false) {
                parts.push('<div><span class="text-danger fw-semibold">不通过</span></div>');
            } else {
                var hint = String(r.result || "").trim();
                if (hint && hint !== "-") {
                    parts.push('<div class="small text-muted">' + escSt(hint.slice(0, 240)) + "</div>");
                } else {
                    parts.push('<div class="small text-muted">—</div>');
                }
            }
            return parts.join("");
        }

        function renderStudentHistoryTable() {
            if (!tbodyHist) return;
            var selM = document.getElementById("studentHistoryFilterMode");
            var selR = document.getElementById("studentHistoryFilterResult");
            var modeF = selM && selM.value ? String(selM.value).trim().toLowerCase() : "";
            var resF = selR && selR.value ? String(selR.value).trim().toLowerCase() : "";
            var list = studentHistoryCache.filter(function (r) {
                if (!r) return false;
                if (modeF && String(r.mode || "").trim().toLowerCase() !== modeF) return false;
                if (resF === "pass") return r.passed === true;
                if (resF === "fail") return r.passed === false;
                if (resF === "pending") return r.passed !== true && r.passed !== false;
                return true;
            });
            if (!list.length) {
                var hint = "";
                if (studentHistoryCache.length) {
                    hint =
                        '<div class="small text-muted mb-1">已加载 ' +
                        String(studentHistoryCache.length) +
                        " 条；当前筛选下列表为空，请将「类型 / 结果」选为「全部」或调整筛选。</div>";
                }
                tbodyHist.innerHTML =
                    hint +
                    '<tr><td colspan="4" class="text-muted small">无匹配记录（请调整筛选或刷新）。</td></tr>';
                return;
            }
            tbodyHist.innerHTML = "";
            list.forEach(function (r) {
                var tr = document.createElement("tr");
                tr.innerHTML =
                    '<td class="small">' +
                    escSt(r.created_at || "-") +
                    "</td>" +
                    '<td class="small">' +
                    escSt(r.mode_label || r.mode || "") +
                    "</td>" +
                    '<td class="small">' +
                    escSt(r.target_label || "-") +
                    "</td>" +
                    '<td class="small">' +
                    historyResultCellHtml(r) +
                    "</td>";
                if (r && r.id) {
                    var td = tr.querySelectorAll("td")[3];
                    if (td) {
                        var btn = document.createElement("button");
                        btn.type = "button";
                        btn.className = "btn btn-sm btn-outline-secondary mt-1";
                        btn.textContent = "详情";
                        btn.addEventListener("click", async function () {
                            var m = ensureActivityModal();
                            if (m) m.show();
                            await openExamActivityDetail(r.id, render);
                            scrollExamApiResultIntoView();
                        });
                        td.appendChild(document.createElement("br"));
                        td.appendChild(btn);
                    }
                }
                tbodyHist.appendChild(tr);
            });
        }

        function syncStudentHistoryChrome(total, loaded, hasMore) {
            if (elHistMeta) {
                var t = Number(total);
                var l = Number(loaded);
                if (Number.isFinite(t) && t >= 0 && Number.isFinite(l) && l >= 0) {
                    elHistMeta.textContent =
                        "共 " +
                        t +
                        " 条记录（当前已加载 " +
                        l +
                        " 条）。列表按当前登录账号筛选；若换过账号或 user_id 变更，旧记录不会出现在此列表。";
                } else {
                    elHistMeta.textContent = "";
                }
            }
            if (btnHistMore) {
                btnHistMore.classList.toggle("d-none", !hasMore);
            }
        }

        async function loadStudentHistory(append) {
            if (!tbodyHist) return;
            var doAppend = append === true;
            if (!doAppend) {
                tbodyHist.innerHTML = '<tr><td colspan="4" class="text-muted small">加载中…</td></tr>';
            } else if (btnHistMore) {
                setButtonLoading(btnHistMore, true, "加载中…");
            }
            try {
                var offset = doAppend ? studentHistoryCache.length : 0;
                var data = await apiRequest(
                    "/api/exam-center/student/history?limit=" +
                        String(HISTORY_PAGE) +
                        "&offset=" +
                        String(offset),
                    "GET"
                );
                if (data && data.__ok === false) {
                    tbodyHist.innerHTML =
                        '<tr><td colspan="4" class="text-danger small">' +
                        escSt(data.message || "加载失败") +
                        "</td></tr>";
                    studentHistoryCache = [];
                    syncStudentHistoryChrome(0, 0, false);
                    return;
                }
                var recs = data && data.data && data.data.records ? data.data.records : [];
                var total =
                    data && data.data && data.data.total != null ? Number(data.data.total) : NaN;
                var hasMore = !!(data && data.data && data.data.has_more);
                if (doAppend) {
                    studentHistoryCache = studentHistoryCache.concat(recs);
                } else {
                    studentHistoryCache = recs;
                }
                if (!Number.isFinite(total)) {
                    total = studentHistoryCache.length;
                    hasMore = recs.length >= HISTORY_PAGE;
                }
                syncStudentHistoryChrome(total, studentHistoryCache.length, hasMore);
                if (!studentHistoryCache.length) {
                    tbodyHist.innerHTML =
                        '<tr><td colspan="4" class="text-muted small">暂无记录（提交练习/考试成功后会在此落库）。</td></tr>';
                    return;
                }
                renderStudentHistoryTable();
            } catch (e) {
                studentHistoryCache = [];
                syncStudentHistoryChrome(0, 0, false);
                tbodyHist.innerHTML =
                    '<tr><td colspan="4" class="text-danger small">' + escSt(e.message) + "</td></tr>";
            } finally {
                if (btnHistMore) {
                    setButtonLoading(btnHistMore, false);
                }
            }
        }

        function maybeOpenPracticeFromResponse(data) {
            var inner = unwrapStudentUpstream(data);
            var qs = pickQuestionItemsFromRoot(inner);
            if (!qs.length) {
                return;
            }
            showStudentInteraction("practice", inner, qs);
        }

        function maybeOpenExamFromResponse(data, assignmentId, assignmentLabel) {
            var inner = unwrapStudentUpstream(data);
            var qs = pickQuestionItemsFromRoot(inner);
            if (!assignmentId) return;
            sessionState.assignmentId = assignmentId;
            sessionState.assignmentLabel = assignmentLabel || "";
            if (!qs.length) {
                return;
            }
            showStudentInteraction("exam", inner, qs);
        }

        btnSet &&
            btnSet.addEventListener("click", async function () {
                if (btnSet && btnSet.disabled) return;
                setButtonLoading(btnSet, true, "生成中…");
                openInteractionPending("正在生成练习卷…", "体考类型：" + escSt(readValue("studentExamTrack") || "cn"));
                try {
                    var data = await apiRequest("/api/exam-center/student/practice/generate-set", "POST", {
                        exam_track: readValue("studentExamTrack") || "cn",
                        question_count: readInt("studentSetSize", 10),
                        difficulty: readValue("studentDifficulty") || "medium"
                    });
                    if (data && data.__ok === false) {
                        showInteractionError("无法开始练习", data.message || "请求失败");
                        if (getExamRole() !== "student") render(data);
                        return;
                    }
                    render(data);
                    maybeOpenPracticeFromResponse(data);
                    if (sessionState.mode === "practice" && !sessionState.questions.length) {
                        showInteractionError(
                            "未加载到题目",
                            "服务端已响应，但未解析到题目列表（questions/items）。请稍后重试或联系管理员。"
                        );
                        if (getExamRole() !== "student") {
                            render({
                                code: "UI",
                                message:
                                    "练习卷接口已返回，但未解析到题目列表，请核对 data 结构。",
                                data: null
                            });
                        }
                    } else if (sessionState.mode === "practice") {
                        studentShowFeedback("练习题卷已就绪，请在下方作答后提交。", "success");
                    }
                } catch (e) {
                    showInteractionError("练习卷生成中断", e.message || "网络或服务异常");
                    if (getExamRole() !== "student") {
                        render({ code: "UI_ERROR", message: e.message, data: null });
                    }
                } finally {
                    setButtonLoading(btnSet, false);
                }
            });

        btnAssignRefresh && btnAssignRefresh.addEventListener("click", function () { loadStudentAssignments(); });
        selStudentTrack &&
            selStudentTrack.addEventListener("change", function () {
                applyStudentTrackDefaults();
            });
        applyStudentTrackDefaults();

        btnSubmitIx &&
            btnSubmitIx.addEventListener("click", async function () {
                if (btnSubmitIx && btnSubmitIx.disabled) return;
                var rows = collectStudentResponses();
                if (!rows.length) {
                    render({ code: "UI_ERROR", message: "请先作答至少一题。", data: null });
                    return;
                }
                setButtonLoading(btnSubmitIx, true, "提交中…");
                try {
                    var snap =
                        sessionState.upstreamSnapshot && typeof sessionState.upstreamSnapshot === "object"
                            ? sessionState.upstreamSnapshot
                            : {};
                    if (sessionState.mode === "practice") {
                        var practiceAttemptIdRaw = String(
                            sessionState.attemptId ||
                                pickAttemptIdFromAny(snap) ||
                                sessionState.sessionId ||
                                snap.session_id ||
                                snap.sessionId ||
                                snap.practice_session_id ||
                                snap.practiceSessionId ||
                                ""
                        ).trim();
                        var practiceAttemptId = normalizeAttemptIdAsIntString(practiceAttemptIdRaw);
                        var payP = Object.assign({}, snap, {
                            set_id: sessionState.setId || pickSetIdFromAny(snap) || "",
                            practice_session_id:
                                sessionState.sessionId ||
                                snap.practice_session_id ||
                                snap.session_id ||
                                snap.sessionId ||
                                "",
                            session_id:
                                sessionState.sessionId ||
                                snap.session_id ||
                                snap.practice_session_id ||
                                snap.sessionId ||
                                "",
                            exam_track: readValue("studentExamTrack") || "cn",
                            answers: rows,
                            responses: rows,
                            submission_questions_snapshot: submissionQuestionsSnapshotPayload()
                        });
                        if (practiceAttemptId) {
                            payP.attempt_id = practiceAttemptId;
                            payP.attemptId = practiceAttemptId;
                        } else {
                            delete payP.attempt_id;
                            delete payP.attemptId;
                        }
                        var r1 = await apiRequest("/api/exam-center/student/practice/submit", "POST", payP);
                        render(r1);
                        scrollExamApiResultIntoView();
                        if (quizPayloadBusinessOk(r1)) {
                            var rs1 = pickQuizSubmitResult(r1);
                            if (rs1 && rs1.grading_status === "pending") {
                                studentShowFeedback("答卷已提交，主观题阅卷中，总分与是否通过将于阅卷完成后更新。", "info");
                            clearDraftAnswers();
                                hideStudentInteraction();
                                loadStudentHistory();
                                var aidPg = String(
                                    (rs1 && (rs1.attempt_id || rs1.attemptId)) ||
                                        practiceAttemptId ||
                                        ""
                                ).trim();
                                if (aidPg) {
                                    pollGradingUntilReady(aidPg).then(function (pg1) {
                                        loadStudentHistory();
                                        if (pg1 && pg1.ready) {
                                            studentShowFeedback("阅卷已完成，成绩已更新。", "success");
                                        }
                                    });
                                }
                            } else {
                                studentShowFeedback("练习答案已提交。", "success");
                            clearDraftAnswers();
                                hideStudentInteraction();
                                loadStudentHistory();
                            }
                        } else if (metaIx) {
                            metaIx.textContent = "提交未成功，请检查提示或稍后重试。";
                            if (!(r1 && r1.__ok === false)) {
                                studentShowFeedback(
                                    "练习提交未成功：" + (r1 && r1.message ? String(r1.message) : "请重试"),
                                    "danger"
                                );
                            }
                        }
                    } else if (sessionState.mode === "exam") {
                        var payE = Object.assign({}, snap, {
                            attempt_id: String(sessionState.attemptId || "").trim(),
                            attemptId: String(sessionState.attemptId || "").trim(),
                            answers: rows
                        });
                        var r2 = await apiRequest("/api/exam-center/student/exams/submit-local", "POST", payE);
                        render(r2);
                        scrollExamApiResultIntoView();
                        if (r2 && r2.__ok === false) {
                            studentShowFeedback("考试提交未成功：" + (r2.message ? String(r2.message) : "请重试"), "danger");
                            return;
                        }
                        var st2 = r2 && r2.data ? String(r2.data.state || "") : "";
                        if (st2 === "grading") {
                            studentShowFeedback("答卷已提交，主观题阅卷中。阅卷完成后可查看详情。", "info");
                            clearDraftAnswers();
                            hideStudentInteraction();
                            loadStudentHistory();
                            var aidPg2 = String(sessionState.attemptId || "").trim();
                            if (aidPg2) {
                                pollLocalGradingUntilReady(aidPg2).then(function (pg2) {
                                    loadStudentHistory();
                                    if (pg2 && pg2.ready) {
                                        studentShowFeedback("阅卷已完成，成绩已更新。", "success");
                                        apiRequest("/api/exam-center/student/attempts/" + encodeURIComponent(aidPg2), "GET")
                                            .then(function (det) {
                                                if (!det || det.__ok === false) return;
                                                render(det);
                                                renderActivityDetailModal({
                                                    data: {
                                                        activity: {
                                                            created_at: (det.data.attempt && det.data.attempt.submitted_at) || "",
                                                            mode: "exam",
                                                            result_summary: "阅卷完成"
                                                        },
                                                        detail: {
                                                            score: (det.data.attempt && det.data.attempt.score) || null,
                                                            total_score: (det.data.attempt && det.data.attempt.total_score) || null,
                                                            pass_score: 80
                                                        },
                                                        attempt_items: det.data.items || []
                                                    }
                                                });
                                                try {
                                                    var m = ensureActivityModal();
                                                    if (m) m.show();
                                                } catch (eM) {}
                                            })
                                            .catch(function () {});
                                    }
                                });
                            }
                        } else if (metaIx) {
                            studentShowFeedback("考试答卷已提交。", "success");
                            clearDraftAnswers();
                            hideStudentInteraction();
                            loadStudentHistory();
                        }
                    } else {
                        render({ code: "UI_ERROR", message: "当前无进行中的作答会话。", data: null });
                        scrollExamApiResultIntoView();
                    }
                } catch (e) {
                    render({ code: "UI_ERROR", message: e.message, data: null });
                    scrollExamApiResultIntoView();
                } finally {
                    setButtonLoading(btnSubmitIx, false);
                }
            });

        btnCancelIx &&
            btnCancelIx.addEventListener("click", function () {
                hideStudentInteraction();
                studentShowFeedback("已取消本次作答（未提交）。", "info");
                render({ code: "UI", message: "已取消本次作答（未提交）。", data: null });
            });

        btnWrongbook &&
            btnWrongbook.addEventListener("click", async function () {
                if (btnWrongbook && btnWrongbook.disabled) return;
                setButtonLoading(btnWrongbook, true, "加载中…");
                try {
                    var qs =
                        "?collection=regulations&limit=120&exam_track=" +
                        encodeURIComponent(readValue("studentExamTrack") || "cn");
                    var data = await apiRequest("/api/exam-center/student/wrongbook" + qs, "GET");
                    if (getExamRole() !== "student") render(data);
                    if (!quizPayloadBusinessOk(data)) {
                        studentShowFeedback((data && data.message) || "错题本加载失败", "danger");
                        return;
                    }
                    var inner = unwrapQuizOkPackage(data);
                    var items = inner && Array.isArray(inner.items) ? inner.items : [];
                    var cnt = inner && inner.count != null ? inner.count : items.length;
                    showStudentBankListModal(
                        "错题本",
                        "体考：" + escSt(readValue("studentExamTrack") || "cn") + "，共 " + String(cnt) + " 题（曾判错）",
                        items,
                        "wrongbook"
                    );
                    studentShowFeedback("已打开错题本列表。", "info");
                } catch (e) {
                    studentShowFeedback(e.message || "错题本加载失败", "danger");
                    if (getExamRole() !== "student") render({ code: "UI_ERROR", message: e.message, data: null });
                } finally {
                    setButtonLoading(btnWrongbook, false);
                }
            });

        btnTracks &&
            btnTracks.addEventListener("click", async function () {
                if (btnTracks && btnTracks.disabled) return;
                setButtonLoading(btnTracks, true, "统计中…");
                try {
                    var track = readValue("studentExamTrack") || "cn";
                    var qs2 =
                        "?collection=regulations&limit=0&exam_track=" + encodeURIComponent(track);
                    var data2 = await apiRequest("/api/exam-center/student/unpracticed-bank" + qs2, "GET");
                    if (getExamRole() !== "student") render(data2);
                    if (!quizPayloadBusinessOk(data2)) {
                        studentShowFeedback((data2 && data2.message) || "未练题量查询失败", "danger");
                        return;
                    }
                    var inner2 = unwrapQuizOkPackage(data2);
                    var total =
                        inner2 && inner2.total_count != null
                            ? inner2.total_count
                            : inner2 && inner2.count != null
                              ? inner2.count
                              : 0;
                    studentShowFeedback(
                        "体考「" + escSt(track) + "」下，题库中还有 " + String(total) + " 道题你尚未做过（不计入具体题号）。",
                        "info"
                    );
                } catch (e) {
                    studentShowFeedback(e.message || "未练题量查询失败", "danger");
                    if (getExamRole() !== "student") render({ code: "UI_ERROR", message: e.message, data: null });
                } finally {
                    setButtonLoading(btnTracks, false);
                }
            });

        btnHist &&
            btnHist.addEventListener("click", function () {
                loadStudentHistory(false);
            });
        btnHistMore &&
            btnHistMore.addEventListener("click", function () {
                loadStudentHistory(true);
            });
        var selHistMode = document.getElementById("studentHistoryFilterMode");
        var selHistRes = document.getElementById("studentHistoryFilterResult");
        selHistMode &&
            selHistMode.addEventListener("change", function () {
                renderStudentHistoryTable();
            });
        selHistRes &&
            selHistRes.addEventListener("change", function () {
                renderStudentHistoryTable();
            });

        window.__examLoadStudentAssignments = loadStudentAssignments;
        window.__examLoadStudentHistory = loadStudentHistory;
        window.__examOpenActivityDetail = openExamActivityDetail;
        window.__examRenderActivityDetailModal = renderActivityDetailModal;
    }

    function fillSelectByOptions(selectEl, options, placeholder) {
        if (!selectEl) return;
        var list = Array.isArray(options) ? options : [];
        var old = String(selectEl.value || "");
        selectEl.innerHTML = "";
        var p = document.createElement("option");
        p.value = "";
        p.textContent = placeholder || "请选择";
        selectEl.appendChild(p);
        list.forEach(function (it) {
            if (!it || typeof it !== "object") return;
            var id = String(it.id || it.assignment_id || it.assignmentId || "").trim();
            if (!id) return;
            var name = String(it.name || it.label || id);
            var opt = document.createElement("option");
            opt.value = id;
            opt.textContent = name;
            selectEl.appendChild(opt);
        });
        if (old) {
            for (var i = 0; i < selectEl.options.length; i++) {
                if (selectEl.options[i].value === old) {
                    selectEl.selectedIndex = i;
                    return;
                }
            }
        }
    }

    function bindAnalyticsActions(render) {
        var btnOverview = document.getElementById("btnStatsOverview");
        var selStudent = document.getElementById("statsStudentId");
        var selAssignment = document.getElementById("statsAssignmentId");
        var tbodyRecent = document.getElementById("statsRecentActivityBody");
        var btnRecentRefresh = document.getElementById("btnStatsRecentActivityRefresh");
        var btnRecentClear = document.getElementById("btnStatsRecentActivityClear");
        var selRecentMode = document.getElementById("statsRecentFilterMode");
        var selRecentResult = document.getElementById("statsRecentFilterResult");
        var statsRecentActivityCache = [];
        var elPassScore = document.getElementById("statsPassScore");
        var elExamCount = document.getElementById("statsExamCount");
        var elGradedCount = document.getElementById("statsGradedCount");
        var elPassCount = document.getElementById("statsPassCount");
        var elFailCount = document.getElementById("statsFailCount");
        var elPassRate = document.getElementById("statsPassRate");
        var elPassBar = document.getElementById("statsPassRateBar");
        var elPracticeCount = document.getElementById("statsPracticeCount");
        var elDashTitle = document.getElementById("statsDashboardTitle");
        var elFocusHint = document.getElementById("statsFocusHint");
        // 看板：按学生（全表，GET /stats/students）
        var tbodyStudentBoard = document.getElementById("statsStudentBoardBody");
        // 看板：学生 × 考试/练习（GET /stats/students-by-mode）
        var tbodyStudentMode = document.getElementById("statsStudentModeBody");
        // 看板：考试 / 练习对照（无需下拉，两行表格并行拉取）
        var tbodyModeCompare = document.getElementById("statsModeCompareBody");

        function analyticsPortalAllowed() {
            var cx = window.__EXAM_CENTER_CONTEXT__;
            return cx && Array.isArray(cx.allowedRoles) && cx.allowedRoles.indexOf("analytics") !== -1;
        }

        function escStats(s) {
            return String(s == null ? "" : s)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;");
        }

        function formatDt(iso) {
            if (!iso) return "-";
            try {
                var d = new Date(iso);
                if (Number.isNaN(d.getTime())) return escStats(iso);
                return escStats(d.toLocaleString());
            } catch (e) {
                return escStats(iso);
            }
        }

        function numOrDash(v) {
            if (v == null || v === "") return "-";
            var n = Number(v);
            return Number.isFinite(n) ? String(n) : "-";
        }

        function pctOrDash(v) {
            if (v == null || v === "") return "-";
            var n = Number(v);
            if (!Number.isFinite(n)) return "-";
            return String(n) + "%";
        }

        function clampPct(v) {
            var n = Number(v);
            if (!Number.isFinite(n)) return 0;
            if (n < 0) return 0;
            if (n > 100) return 100;
            return n;
        }

        async function loadExamAssignmentDeadlineStats() {
            var panel = document.getElementById("statsExamDeadlinePanel");
            if (!panel) return;
            var aid = selAssignment ? String(selAssignment.value || "").trim() : "";
            if (!aid) {
                panel.innerHTML =
                    '<span class="text-muted small">请选择「考试任务」并点「应用筛选」，可查看该任务的<strong>截止时间</strong>与<strong>按时完成人数</strong>（基于本地落库）。</span>';
                return;
            }
            panel.innerHTML = '<span class="text-muted small">加载任务统计…</span>';
            try {
                var data = await apiRequest("/api/exam-center/stats/exam/" + encodeURIComponent(aid), "GET");
                render(data);
                if (data && data.__ok === false) {
                    panel.innerHTML =
                        '<span class="text-danger small">' + escStats(data.message || "请求失败") + "</span>";
                    return;
                }
                var d = unwrapStatsData(data);
                var dc =
                    (d && d.deadline_completion) ||
                    (data &&
                        data.aiword &&
                        typeof data.aiword === "object" &&
                        data.aiword.deadline_completion) ||
                    {};
                var dueTxt =
                    dc.due_at != null && String(dc.due_at).trim()
                        ? escStats(String(dc.due_at).trim())
                        : '<span class="text-muted">未配置</span>';
                var subm = dc.exam_students_submitted != null ? escStats(String(dc.exam_students_submitted)) : "—";
                var parts = [];
                parts.push("<strong>任务 " + escStats(aid) + "</strong>：截止 " + dueTxt);
                parts.push("；已考人数（首次提交计）<strong>" + subm + "</strong>");
                if (dc.on_time_count != null && dc.late_count != null) {
                    parts.push(
                        '；<span class="text-success fw-semibold">按时 ' +
                            escStats(String(dc.on_time_count)) +
                            '</span> / <span class="text-danger fw-semibold">逾期 ' +
                            escStats(String(dc.late_count)) +
                            "</span>"
                    );
                } else if (dc.note) {
                    parts.push(' <span class="text-muted small">(' + escStats(dc.note) + ")</span>");
                }
                panel.innerHTML = "<div>" + parts.join("") + "</div>";
            } catch (e) {
                panel.innerHTML =
                    '<span class="text-danger small">' + escStats(e.message || String(e)) + "</span>";
            }
        }

        function unwrapStatsData(resp) {
            if (!resp || typeof resp !== "object") return {};
            if (resp.__ok === false) return {};
            // 兼容：有些接口 payload 顶层 data 就是对象
            var d = resp.data && typeof resp.data === "object" ? resp.data : {};
            return d;
        }

        /** 仅刷新「整体统计」卡片（不重复拉取下方三张表）；进入统计端时与其它接口并行触发。 */
        async function loadStatsOverviewCards() {
            if (!analyticsPortalAllowed()) return;
            try {
                var data = await apiRequest("/api/exam-center/stats/overview", "GET");
                render(data);
                var s0 = unwrapStatsData(data);
                var local = data && data.aiword && data.aiword.local_overview ? data.aiword.local_overview : null;
                renderDashboard("全局", local && typeof local === "object" ? local : s0);
            } catch (e) {
                render({ code: "UI_ERROR", message: "整体统计加载失败：" + e.message, data: null });
            }
        }

        window.__examLoadStatsOverview = loadStatsOverviewCards;

        function renderDashboard(kind, statsObj) {
            var d = statsObj && typeof statsObj === "object" ? statsObj : {};
            var passScore = d.pass_score != null ? d.pass_score : 80;
            if (elPassScore) elPassScore.textContent = String(passScore);
            if (elDashTitle) elDashTitle.textContent = kind || "全局";
            if (elPracticeCount) elPracticeCount.textContent = numOrDash(d.practice_count);
            if (elExamCount) elExamCount.textContent = numOrDash(d.exam_count || d.exam_submitted_count || d.submitted_count);
            if (elGradedCount) elGradedCount.textContent = numOrDash(d.graded_exam_count || d.graded_count);
            if (elPassCount) elPassCount.textContent = numOrDash(d.pass_count);
            if (elFailCount) elFailCount.textContent = numOrDash(d.fail_count);
            if (elPassRate) elPassRate.textContent = pctOrDash(d.pass_rate_percent);
            var pct = clampPct(d.pass_rate_percent);
            if (elPassBar) {
                elPassBar.style.width = String(pct) + "%";
                elPassBar.textContent = pct > 12 ? String(pct) + "%" : "";
            }
            if (elFocusHint) {
                var hints = [];
                if (Array.isArray(d.focus_flags) && d.focus_flags.length) {
                    hints.push("关注点：" + d.focus_flags.join("、"));
                }
                if (Array.isArray(d.focus_students) && d.focus_students.length) {
                    hints.push("需重点关注学生数：" + String(d.focus_students.length));
                }
                elFocusHint.textContent = hints.join("；");
            }
        }

        function renderStatsRecentActivityTable() {
            if (!tbodyRecent) return;
            if (!statsRecentActivityCache || !statsRecentActivityCache.length) {
                return;
            }
            var selM = document.getElementById("statsRecentFilterMode");
            var selR = document.getElementById("statsRecentFilterResult");
            var modeF = selM && selM.value ? String(selM.value).trim().toLowerCase() : "";
            var resF = selR && selR.value ? String(selR.value).trim().toLowerCase() : "";
            var list = statsRecentActivityCache.filter(function (r) {
                if (!r) return false;
                if (modeF && String(r.mode || "").trim().toLowerCase() !== modeF) return false;
                if (resF === "pass") return r.passed === true;
                if (resF === "fail") return r.passed === false;
                if (resF === "pending") return r.passed !== true && r.passed !== false;
                return true;
            });
            if (!list.length) {
                tbodyRecent.innerHTML =
                    '<tr><td colspan="5" class="text-muted small">无匹配记录（请调整类型/结果筛选，或重新应用「学生/任务」筛选）。</td></tr>';
                return;
            }
            tbodyRecent.innerHTML = "";
            list.forEach(function (r) {
                var tr = document.createElement("tr");
                var who = escStats(r.student_name || r.user_id || "-");
                var scoreTxt =
                    r && r.score != null
                        ? String(r.score) + (r.total_score != null ? "/" + String(r.total_score) : "")
                        : "";
                var resultParts = [];
                if (scoreTxt) {
                    resultParts.push(
                        '<div class="text-muted small">分数：' + escStats(scoreTxt) + "</div>"
                    );
                }
                if (r.passed === true) {
                    resultParts.push('<div><span class="text-success fw-semibold">通过</span></div>');
                } else if (r.passed === false) {
                    resultParts.push('<div><span class="text-danger fw-semibold">不通过</span></div>');
                } else {
                    var hint = String(r.result || "").trim();
                    if (hint && hint !== "-") {
                        resultParts.push(
                            '<div class="small text-muted">' + escStats(hint.slice(0, 240)) + "</div>"
                        );
                    } else {
                        resultParts.push('<div class="small text-muted">—</div>');
                    }
                }
                var resultCell = resultParts.join("");
                tr.innerHTML =
                    '<td class="small">' +
                    formatDt(r.created_at) +
                    "</td>" +
                    '<td class="small">' +
                    who +
                    "</td>" +
                    '<td class="small">' +
                    escStats(r.mode_label || r.mode || "") +
                    "</td>" +
                    '<td class="small">' +
                    escStats(r.target_label || "-") +
                    "</td>" +
                    '<td class="small">' +
                    resultCell +
                    "</td>";
                if (r && r.id) {
                    var td5 = tr.querySelectorAll("td")[4];
                    if (td5) {
                        var bDetail = document.createElement("button");
                        bDetail.type = "button";
                        bDetail.className = "btn btn-sm btn-outline-secondary mt-1";
                        bDetail.textContent = "详情";
                        bDetail.addEventListener("click", async function () {
                            if (typeof window.__examOpenActivityDetail !== "function") {
                                render({
                                    code: "UI_ERROR",
                                    message: "练习/考试详情未初始化（请刷新页面重试，或确认 exam_center.js 已更新）。",
                                    data: null,
                                });
                                return;
                            }
                            if (typeof window.__examEnsureActivityModal === "function") {
                                var m2 = window.__examEnsureActivityModal();
                                if (m2) m2.show();
                            }
                            await window.__examOpenActivityDetail(r.id, render);
                            try {
                                var box = document.getElementById("examApiResult");
                                if (box) box.scrollIntoView({ behavior: "smooth", block: "nearest" });
                            } catch (e0) {}
                        });
                        td5.appendChild(document.createElement("br"));
                        td5.appendChild(bDetail);

                        var bDel = document.createElement("button");
                        bDel.type = "button";
                        bDel.className = "btn btn-sm btn-outline-danger mt-1 ms-1";
                        bDel.textContent = "删除";
                        bDel.addEventListener("click", async function () {
                            var ok = window.confirm("确定删除该条练习/考试记录吗？删除后不可恢复。");
                            if (!ok) return;
                            var d2 = await apiRequest("/api/exam-center/activity/" + encodeURIComponent(String(r.id)), "DELETE");
                            render(d2);
                            loadStatsRecentActivity();
                            if (typeof window.__examLoadStatsOverview === "function") {
                                window.__examLoadStatsOverview();
                            }
                            if (typeof window.__examLoadStudentBoardTable === "function") {
                                window.__examLoadStudentBoardTable();
                            }
                            if (typeof window.__examLoadStudentModeTable === "function") {
                                window.__examLoadStudentModeTable();
                            }
                            if (typeof window.__examLoadModeCompare === "function") {
                                window.__examLoadModeCompare();
                            }
                        });
                        td5.appendChild(bDel);
                    }
                }
                tbodyRecent.appendChild(tr);
            });
        }

        async function loadStatsRecentActivity() {
            if (!analyticsPortalAllowed()) return;
            if (!tbodyRecent) return;
            tbodyRecent.innerHTML = '<tr><td colspan="5" class="text-muted small">加载中…</td></tr>';
            try {
                var q = [];
                q.push("limit=80");
                var sid = selStudent ? String(selStudent.value || "").trim() : "";
                var aid = selAssignment ? String(selAssignment.value || "").trim() : "";
                if (sid) q.push("student_id=" + encodeURIComponent(sid));
                if (aid) q.push("assignment_id=" + encodeURIComponent(aid));
                var data = await apiRequest("/api/exam-center/stats/recent-activity?" + q.join("&"), "GET");
                if (data && data.__ok === false) {
                    statsRecentActivityCache = [];
                    tbodyRecent.innerHTML =
                        '<tr><td colspan="5" class="text-danger small">' +
                        escStats(data.message || "请求失败") +
                        "（HTTP " +
                        escStats(String(data.__http_status || "?")) +
                        "）</td></tr>";
                    return;
                }
                var recs = data && data.data && data.data.records ? data.data.records : [];
                statsRecentActivityCache = recs;
                if (!recs.length) {
                    tbodyRecent.innerHTML = '<tr><td colspan="5" class="text-muted small">暂无记录。</td></tr>';
                    return;
                }
                renderStatsRecentActivityTable();
                var box = document.getElementById("examApiResult");
                var highlighted = 0;
                if (box && data && data.data && Array.isArray(data.data.focus_students) && data.data.focus_students.length) {
                    highlighted = data.data.focus_students.length;
                }
                if (highlighted > 0 && box) {
                    box.textContent =
                        (box.textContent || "") +
                        "\\n\\n[本地关注提醒] 需重点关注学生数：" +
                        highlighted +
                        "（练习次数少/错题多/未完成考试）";
                }
            } catch (e) {
                statsRecentActivityCache = [];
                tbodyRecent.innerHTML =
                    '<tr><td colspan="5" class="text-danger small">加载失败：' + escStats(e.message) + "</td></tr>";
            }
        }

        async function loadStatsOptions() {
            if (!analyticsPortalAllowed()) return;
            try {
                var data = await apiRequest("/api/exam-center/stats/options", "GET");
                render(data);
                if (data && data.__ok === false) {
                    return;
                }
                var students = data && data.data && data.data.students ? data.data.students : [];
                var assignments = data && data.data && data.data.assignments ? data.data.assignments : [];
                fillSelectByOptions(selStudent, students, "请选择学生");
                fillSelectByOptions(selAssignment, assignments, "请选择考试任务");
            } catch (e) {
                render({ code: "UI_ERROR", message: "加载统计下拉失败：" + e.message, data: null });
            }
        }

        async function loadStudentBoardTable() {
            if (!analyticsPortalAllowed()) return;
            if (!tbodyStudentBoard) return;
            tbodyStudentBoard.innerHTML =
                '<tr><td colspan="9" class="text-muted small">加载中…</td></tr>';
            try {
                var data = await apiRequest("/api/exam-center/stats/students", "GET");
                render(data);
                if (data && data.__ok === false) {
                    tbodyStudentBoard.innerHTML =
                        '<tr><td colspan="9" class="text-danger small">' +
                        escStats(data.message || "请求失败") +
                        "</td></tr>";
                    return;
                }
                var d = unwrapStatsData(data);
                var rows = d.rows && Array.isArray(d.rows) ? d.rows : [];
                if (!rows.length) {
                    tbodyStudentBoard.innerHTML =
                        '<tr><td colspan="9" class="text-muted small">暂无学生活动数据（或尚未同步到本地）。</td></tr>';
                    return;
                }
                tbodyStudentBoard.innerHTML = "";
                rows.forEach(function (r) {
                    var focus =
                        Array.isArray(r.focus_flags) && r.focus_flags.length
                            ? r.focus_flags.join("、")
                            : "-";
                    var pc = Number(r.practice_count || 0);
                    var ec = Number(r.exam_submitted_count || 0);
                    var totalLearn =
                        r.total_learning_count != null && r.total_learning_count !== ""
                            ? Number(r.total_learning_count)
                            : pc + ec;
                    var tr = document.createElement("tr");
                    tr.innerHTML =
                        '<td class="small">' +
                        escStats(r.student_name || r.student_id || "-") +
                        "</td>" +
                        '<td class="small">' +
                        (Number.isFinite(totalLearn) ? String(totalLearn) : "-") +
                        ' <span class="text-muted small">（练习 ' +
                        numOrDash(r.practice_count) +
                        " · 考试 " +
                        numOrDash(r.exam_submitted_count) +
                        "）</span></td>" +
                        "<td>" +
                        numOrDash(r.practice_count) +
                        "</td>" +
                        "<td>" +
                        numOrDash(r.exam_submitted_count) +
                        "</td>" +
                        "<td>" +
                        numOrDash(r.graded_exam_count != null ? r.graded_exam_count : (Number(r.pass_count || 0) + Number(r.fail_count || 0))) +
                        "</td>" +
                        '<td class="text-success">' +
                        numOrDash(r.pass_count) +
                        "</td>" +
                        '<td class="text-danger">' +
                        numOrDash(r.fail_count) +
                        "</td>" +
                        "<td>" +
                        pctOrDash(r.pass_rate_percent) +
                        "</td>" +
                        '<td class="small text-muted">' +
                        escStats(focus) +
                        "</td>";
                    tbodyStudentBoard.appendChild(tr);
                });
            } catch (e) {
                tbodyStudentBoard.innerHTML =
                    '<tr><td colspan="9" class="text-danger small">加载失败：' +
                    escStats(e.message) +
                    "</td></tr>";
            }
        }

        /** 兼容：underscore 路由 / 新版双注册；命中旧代理或未完成部署时降级连字符路径。 */
        async function fetchStatsStudentsByModeRows() {
            var data = await apiRequest("/api/exam-center/stats/students_by_mode", "GET");
            var badHtml =
                data &&
                data.code === "BAD_RESPONSE" &&
                typeof data.message === "string" &&
                /<!DOCTYPE|<html\s/i.test(data.message);
            if ((data && data.__http_status === 404 && data.__ok === false) || badHtml) {
                data = await apiRequest("/api/exam-center/stats/students-by-mode", "GET");
            }
            return data;
        }

        async function loadStudentModeTable() {
            if (!analyticsPortalAllowed()) return;
            if (!tbodyStudentMode) return;
            tbodyStudentMode.innerHTML =
                '<tr><td colspan="7" class="text-muted small">加载中…</td></tr>';
            try {
                var data = await fetchStatsStudentsByModeRows();
                render(data);
                if (data && data.__ok === false) {
                    tbodyStudentMode.innerHTML =
                        '<tr><td colspan="7" class="text-danger small">' +
                        escStats(data.message || "请求失败") +
                        "</td></tr>";
                    return;
                }
                var d = unwrapStatsData(data);
                var rows = d.rows && Array.isArray(d.rows) ? d.rows : [];
                if (!rows.length) {
                    tbodyStudentMode.innerHTML =
                        '<tr><td colspan="7" class="text-muted small">暂无数据（无学生活动或尚未同步到本地）。</td></tr>';
                    return;
                }
                tbodyStudentMode.innerHTML = "";
                rows.forEach(function (r) {
                    var modeKey = String(r.mode || "").toLowerCase();
                    var tr = document.createElement("tr");
                    tr.innerHTML =
                        '<td class="small">' +
                        escStats(r.student_name || r.student_id || "-") +
                        "</td>" +
                        '<td class="small"><span class="badge bg-light text-dark border">' +
                        escStats(r.mode_label || (modeKey === "exam" ? "考试" : "练习")) +
                        "</span></td>" +
                        "<td>" +
                        numOrDash(r.total_count) +
                        "</td>" +
                        "<td>" +
                        numOrDash(r.graded_count) +
                        "</td>" +
                        '<td class="text-success">' +
                        numOrDash(r.pass_count) +
                        "</td>" +
                        '<td class="text-danger">' +
                        numOrDash(r.fail_count) +
                        "</td>" +
                        "<td>" +
                        pctOrDash(r.pass_rate_percent) +
                        "</td>";
                    tbodyStudentMode.appendChild(tr);
                });
            } catch (e) {
                tbodyStudentMode.innerHTML =
                    '<tr><td colspan="7" class="text-danger small">加载失败：' +
                    escStats(e.message) +
                    "</td></tr>";
            }
        }

        /** 单行：分类展示 mode 聚合（/stats/mode?mode=...） */
        function modeRowCells(labelBold, modeKey, d) {
            if (d && d.err) {
                return (
                    "<tr>" +
                    "<td><strong>" +
                    escStats(labelBold) +
                    "</strong></td>" +
                    '<td colspan="5" class="text-danger small">' +
                    escStats(d.err) +
                    "</td>" +
                    "</tr>"
                );
            }
            var x = d && typeof d === "object" ? d : {};
            return (
                "<tr>" +
                "<td><strong>" +
                escStats(labelBold) +
                "</strong></td>" +
                "<td>" +
                numOrDash(x.total_count) +
                "</td>" +
                "<td>" +
                numOrDash(x.graded_count) +
                "</td>" +
                "<td class=\"text-success\">" +
                numOrDash(x.pass_count) +
                "</td>" +
                "<td class=\"text-danger\">" +
                numOrDash(x.fail_count) +
                "</td>" +
                "<td>" + pctOrDash(x.pass_rate_percent) + "</td>" +
                "</tr>"
            );
        }

        async function loadModeCompare() {
            if (!analyticsPortalAllowed()) return;
            if (!tbodyModeCompare) return;
            tbodyModeCompare.innerHTML =
                '<tr><td colspan="6" class="text-muted small">加载中…</td></tr>';

            async function fetchMode(mode) {
                try {
                    var data = await apiRequest("/api/exam-center/stats/mode?mode=" + encodeURIComponent(mode), "GET");
                    if (data && data.__ok === false) {
                        render(data);
                        return { err: data.message || "请求失败" };
                    }
                    return unwrapStatsData(data);
                } catch (e) {
                    return { err: e.message || "加载失败" };
                }
            }

            try {
                var results = await Promise.all([fetchMode("exam"), fetchMode("practice")]);
                var exam = results[0];
                var prac = results[1];
                tbodyModeCompare.innerHTML =
                    modeRowCells("考试", "exam", exam) + modeRowCells("练习", "practice", prac);
            } catch (e) {
                tbodyModeCompare.innerHTML =
                    '<tr><td colspan="6" class="text-danger small">加载失败：' +
                    escStats(e.message) +
                    "</td></tr>";
            }
        }

        btnRecentRefresh &&
            btnRecentRefresh.addEventListener("click", function () {
                loadStatsRecentActivity();
                loadExamAssignmentDeadlineStats();
            });
        btnRecentClear &&
            btnRecentClear.addEventListener("click", function () {
                if (selStudent) selStudent.value = "";
                if (selAssignment) selAssignment.value = "";
                if (selRecentMode) selRecentMode.value = "";
                if (selRecentResult) selRecentResult.value = "";
                loadStatsRecentActivity();
                loadExamAssignmentDeadlineStats();
            });
        selRecentMode &&
            selRecentMode.addEventListener("change", function () {
                renderStatsRecentActivityTable();
            });
        selRecentResult &&
            selRecentResult.addEventListener("change", function () {
                renderStatsRecentActivityTable();
            });

        btnOverview && btnOverview.addEventListener("click", async function () {
            if (btnOverview && btnOverview.disabled) return;
            setButtonLoading(btnOverview, true, "加载中…");
            try {
                await loadStatsOverviewCards();
                loadStudentBoardTable();
                loadStudentModeTable();
                loadModeCompare();
            } catch (e) {
                render({ code: "UI_ERROR", message: e.message, data: null });
            } finally {
                setButtonLoading(btnOverview, false);
            }
        });

        window.__examLoadStatsOptions = loadStatsOptions;
        window.__examLoadStatsRecentActivity = loadStatsRecentActivity;
        window.__examLoadExamAssignmentDeadlineStats = loadExamAssignmentDeadlineStats;
        window.__examLoadStudentBoardTable = loadStudentBoardTable;
        window.__examLoadStudentModeTable = loadStudentModeTable;
        window.__examLoadModeCompare = loadModeCompare;
    }

    document.addEventListener("DOMContentLoaded", function () {
        var ctx = window.__EXAM_CENTER_CONTEXT__;
        if (!ctx || !document.getElementById("examApiResult")) return;

        var renderRaw = bindOutput();
        var render = createStudentAwareRender(renderRaw);
        var btnHealth = document.getElementById("btnExamHealth");
        btnHealth && btnHealth.addEventListener("click", async function () {
            if (btnHealth && btnHealth.disabled) return;
            setButtonLoading(btnHealth, true, "检查中…");
            renderRaw({ code: "UI", message: "正在健康检查（上游超时=3秒）…", data: null });
            try {
                var data = await apiRequest("/api/exam-center/health", "GET");
                renderRaw(data);
            } catch (e) {
                renderRaw({ code: "UI_ERROR", message: e.message, data: null });
            } finally {
                setButtonLoading(btnHealth, false);
            }
        });
        // 必须先注册各列表加载函数（挂到 window），再 bindRoleSwitch → activate，
        // 否则会首次进入时空跑 onRoleChange、列表永远停在「加载中」直到手动刷新。
        bindTeacherActions(render);
        bindStudentActions(render);
        bindAnalyticsActions(render);

        if (typeof window.__examEnsureActivityModal !== "function") {
            window.__examEnsureActivityModal = function () {
                var el = document.getElementById("examActivityDetailModal");
                if (!el || !window.bootstrap || !window.bootstrap.Modal) return null;
                if (!window.__examActivityDetailModal) {
                    window.__examActivityDetailModal = new window.bootstrap.Modal(el);
                }
                return window.__examActivityDetailModal;
            };
        }

        refreshExamCenterUserDisplay();
        bindRoleSwitch(ctx, function (role) {
            if (role === "teacher") {
                if (typeof window.__examLoadTeacherIngestJobs === "function") {
                    window.__examLoadTeacherIngestJobs();
                }
                if (typeof window.__examLoadTeacherReviewJobs === "function") {
                    window.__examLoadTeacherReviewJobs();
                }
                if (typeof window.__examLoadTeacherSets === "function") {
                    window.__examLoadTeacherSets();
                }
                if (typeof window.__examLoadTeacherBankQuestions === "function") {
                    window.__examLoadTeacherBankQuestions();
                }
                if (typeof window.__examLoadTeacherIssuedAssignments === "function") {
                    window.__examLoadTeacherIssuedAssignments();
                }
                if (typeof window.__examLoadTeacherRequirementStatus === "function") {
                    window.__examLoadTeacherRequirementStatus();
                }
            }
            if (role === "analytics") {
                if (typeof window.__examLoadStatsOptions === "function") {
                    window.__examLoadStatsOptions();
                }
                if (typeof window.__examLoadStatsRecentActivity === "function") {
                    window.__examLoadStatsRecentActivity();
                }
                if (typeof window.__examLoadStatsOverview === "function") {
                    window.__examLoadStatsOverview();
                }
                if (typeof window.__examLoadStudentBoardTable === "function") {
                    window.__examLoadStudentBoardTable();
                }
                if (typeof window.__examLoadStudentModeTable === "function") {
                    window.__examLoadStudentModeTable();
                }
                if (typeof window.__examLoadModeCompare === "function") {
                    window.__examLoadModeCompare();
                }
                if (typeof window.__examLoadExamAssignmentDeadlineStats === "function") {
                    window.__examLoadExamAssignmentDeadlineStats();
                }
            }
            if (role === "student") {
                if (typeof window.__examLoadStudentAssignments === "function") {
                    window.__examLoadStudentAssignments();
                }
                if (typeof window.__examLoadStudentHistory === "function") {
                    window.__examLoadStudentHistory();
                }
            }
        });
    });
})();
