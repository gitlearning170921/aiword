/**
 * 全站作用域条 + 空数据原因提示（依赖 App.request / window.__SCRIPT_ROOT__）
 */
(function (global) {
    "use strict";

    var _ctx = null;
    var _loading = false;

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function pageKeyFromPath() {
        var p = global.location.pathname || "";
        if (p.indexOf("/company") >= 0) return "page0";
        if (p.indexOf("/upload") >= 0) return "page1";
        if (p.indexOf("/generate") >= 0) return "page2";
        if (p.indexOf("/dashboard") >= 0) return "page3";
        if (p.indexOf("/admin") >= 0) return "page4";
        if (p.indexOf("/exam") >= 0) return "exam";
        if (p.indexOf("/audit") >= 0 || p.indexOf("/draft") >= 0 || p.indexOf("/translate") >= 0) {
            return "integration";
        }
        return "unknown";
    }

    function shouldShowBar() {
        var p = global.location.pathname || "";
        if (p.indexOf("/login") >= 0) return false;
        if (global.__SCOPE_BAR_SUPPRESS__) return false;
        if (!global.__PAGE13_SUPER_ADMIN__) return false;
        return true;
    }

    function mountEl() {
        return document.getElementById("globalScopeBarMount");
    }

    function renderBar(ctx) {
        var el = mountEl();
        if (!el || !ctx) return;
        el.classList.remove("d-none");
        var warns = (ctx.warnings || []).concat(ctx.emptyReasons || []);
        var warnHtml = "";
        if (warns.length) {
            warnHtml =
                '<ul class="scope-bar-warn-list mb-0 ps-3">' +
                warns.map(function (w) {
                    return "<li>" + esc(w) + "</li>";
                }).join("") +
                "</ul>";
        }
        var diagBtn = ctx.diagnosticsAvailable
            ? '<button type="button" class="btn btn-sm btn-outline-secondary" id="scopeBarDiagnosticsBtn">作用域诊断</button>'
            : "";
        el.innerHTML =
            '<div class="scope-bar card border-0 shadow-sm">' +
            '<div class="card-body py-2 px-3">' +
            '<div class="d-flex flex-wrap justify-content-between align-items-start gap-2">' +
            '<div class="flex-grow-1 min-w-0">' +
            '<div class="d-flex flex-wrap align-items-center gap-2 mb-1">' +
            '<span class="badge bg-primary-subtle text-primary-emphasis border border-primary-subtle">' +
            esc(ctx.pageLabel || ctx.pageKey || "当前页面") +
            "</span>" +
            '<span class="small fw-semibold text-dark">' +
            esc(ctx.scopeSummary || "") +
            "</span>" +
            (ctx.activeKnowledgeCollection
                ? '<span class="small text-muted">collection: <code>' +
                  esc(ctx.activeKnowledgeCollection) +
                  "</code></span>"
                : "") +
            "</div>" +
            '<div class="small text-muted">' +
            esc(ctx.scopeHint || "") +
            "</div>" +
            warnHtml +
            "</div>" +
            '<div class="d-flex gap-2 align-items-center flex-shrink-0">' +
            diagBtn +
            '<button type="button" class="btn btn-sm btn-link text-muted p-0" id="scopeBarRefreshBtn" title="刷新作用域">↻</button>' +
            "</div>" +
            "</div>" +
            "</div>" +
            "</div>";
        el.querySelector("#scopeBarRefreshBtn")?.addEventListener("click", function () {
            refresh(true);
        });
        el.querySelector("#scopeBarDiagnosticsBtn")?.addEventListener("click", showDiagnosticsModal);
    }

    function emptyMessages(contextKey) {
        var ctx = _ctx || {};
        var reasons = (ctx.emptyReasons || []).slice();
        var base = {
            page0_projects:
                "当前筛选条件下暂无公司总览项目。可点击「登记新项目」，或在页面1 使用「同步页面0项目」建立关联。",
            page1_projects:
                "暂无页面1 项目。可点击「新增项目」，或使用「同步页面0项目」从公司总览导入。",
            page1_records: "暂无任务记录。请在下方任务录入区新建任务，或检查项目组/公司筛选是否过窄。",
            page2_records: "暂无生成记录。请先在页面1 创建任务并完成上传/生成流程。",
            page3_stats: "当前统计范围内暂无数据。",
            exam_student_history: "暂无练习/考试记录。提交成功后会在此显示。",
            exam_teacher_assignments: "暂无考试任务。项目管理员/老师可在老师端下发任务。",
            exam_analytics: "暂无学生活动数据。请确认考试中心顶部公司与项目组筛选是否正确。",
            generic: "暂无数据。",
        };
        var msg = base[contextKey] || base.generic;
        return { message: msg, reasons: reasons };
    }

    function emptyHtml(contextKey, extraLines) {
        var pack = emptyMessages(contextKey);
        var lines = [pack.message].concat(pack.reasons || []).concat(extraLines || []);
        var uniq = [];
        lines.forEach(function (x) {
            var s = String(x || "").trim();
            if (s && uniq.indexOf(s) < 0) uniq.push(s);
        });
        return (
            '<div class="scope-empty-hint text-muted small p-3">' +
            '<p class="mb-1 fw-semibold">' +
            esc(uniq[0] || pack.message) +
            "</p>" +
            (uniq.length > 1
                ? '<ul class="mb-0 ps-3">' +
                  uniq
                      .slice(1)
                      .map(function (r) {
                          return "<li>" + esc(r) + "</li>";
                      })
                      .join("") +
                  "</ul>"
                : "") +
            "</div>"
        );
    }

    function emptyTableRow(colspan, contextKey, extraLines) {
        return (
            '<tr><td colspan="' +
            Number(colspan || 1) +
            '">' +
            emptyHtml(contextKey, extraLines) +
            "</td></tr>"
        );
    }

    function showDiagnosticsModal() {
        var App = global.App;
        if (!App || !App.request) return;
        App.request("/api/scope/diagnostics")
            .then(function (data) {
                var eff = data.effective || {};
                var sess = data.session || {};
                var bind = data.bindings || {};
                var body =
                    '<dl class="row small mb-0">' +
                    '<dt class="col-sm-3">账号</dt><dd class="col-sm-9">' +
                    esc((data.user && data.user.username) || "—") +
                    "（" +
                    esc((data.user && data.user.adminRoleLabel) || "") +
                    "）</dd>" +
                    '<dt class="col-sm-3">绑定公司</dt><dd class="col-sm-9">' +
                    esc((bind.organizationNames || []).join("、") || "—") +
                    "</dd>" +
                    '<dt class="col-sm-3">绑定项目组</dt><dd class="col-sm-9">' +
                    esc((bind.teamNames || []).join("、") || "—") +
                    "</dd>" +
                    '<dt class="col-sm-3">Session 公司</dt><dd class="col-sm-9"><code>' +
                    esc(sess.activeOrganizationId || "—") +
                    "</code></dd>" +
                    '<dt class="col-sm-3">Session 项目组</dt><dd class="col-sm-9"><code>' +
                    esc(sess.activeExamTeamId || (sess.examTeamScopeAll ? "全部" : "—")) +
                    "</code></dd>" +
                    '<dt class="col-sm-3">有效范围</dt><dd class="col-sm-9">' +
                    esc(eff.scopeSummary || "") +
                    '<br><span class="text-muted">' +
                    esc(eff.scopeHint || "") +
                    "</span></dd>" +
                    "</dl>";
                if (data.apiFilters) {
                    body +=
                        '<hr><p class="small fw-semibold mb-1">各页 API 过滤</p><ul class="small mb-0">';
                    Object.keys(data.apiFilters).forEach(function (k) {
                        body += "<li><code>" + esc(k) + "</code>：" + esc(data.apiFilters[k]) + "</li>";
                    });
                    body += "</ul>";
                }
                var modalId = "scopeDiagnosticsModal";
                var existing = document.getElementById(modalId);
                if (existing) existing.remove();
                var wrap = document.createElement("div");
                wrap.innerHTML =
                    '<div class="modal fade" id="' +
                    modalId +
                    '" tabindex="-1">' +
                    '<div class="modal-dialog modal-lg modal-dialog-scrollable">' +
                    '<div class="modal-content">' +
                    '<div class="modal-header"><h6 class="modal-title">作用域诊断</h6>' +
                    '<button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>' +
                    '<div class="modal-body">' +
                    body +
                    "</div>" +
                    '<div class="modal-footer">' +
                    '<a class="btn btn-sm btn-outline-primary" href="' +
                    esc((global.__SCRIPT_ROOT__ || "") + "/admin") +
                    '">打开页面4</a>' +
                    '<button type="button" class="btn btn-sm btn-secondary" data-bs-dismiss="modal">关闭</button>' +
                    "</div></div></div></div>";
                document.body.appendChild(wrap.firstElementChild);
                var modalEl = document.getElementById(modalId);
                if (global.bootstrap && modalEl) {
                    new global.bootstrap.Modal(modalEl).show();
                }
            })
            .catch(function (e) {
                if (App.notify) App.notify(e.message || "加载诊断失败", "danger");
            });
    }

    function refresh(force) {
        if (_loading && !force) return Promise.resolve(_ctx);
        var App = global.App;
        if (!App || !App.request || !shouldShowBar()) return Promise.resolve(null);
        _loading = true;
        var page = pageKeyFromPath();
        return App.request("/api/scope/context?page=" + encodeURIComponent(page))
            .then(function (data) {
                _ctx = data;
                renderBar(data);
                global.dispatchEvent(new CustomEvent("scopecontext:ready", { detail: data }));
                return data;
            })
            .catch(function () {
                var el = mountEl();
                if (el) el.classList.add("d-none");
                return null;
            })
            .finally(function () {
                _loading = false;
            });
    }

    function init() {
        if (!shouldShowBar()) return;
        refresh(false);
    }

    global.ScopeBar = {
        refresh: refresh,
        getContext: function () {
            return _ctx;
        },
        emptyHtml: emptyHtml,
        emptyTableRow: emptyTableRow,
        emptyMessages: emptyMessages,
        pageKeyFromPath: pageKeyFromPath,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})(window);
