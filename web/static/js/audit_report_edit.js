(function () {

  "use strict";

  var root = window.__SCRIPT_ROOT__ || "";

  var $ = function (id) { return document.getElementById(id); };

  var _rawReport = null;

  var _points = [];

  var _orgCollection = "";



  var ACTION_OPTIONS = ["立即修改", "延期修改", "无需修改"];

  var SEV_LABEL = { high: "高", medium: "中", low: "低", info: "提示" };



  function defaultActionForSeverity(sev) {

    var s = String(sev || "info").toLowerCase();

    var map = { high: "立即修改", medium: "立即修改", low: "延期修改", info: "无需修改" };

    return map[s] || "无需修改";

  }



  function showMsg(msg, isErr) {

    var box = $("are_msg");

    if (!box) return;

    box.textContent = msg || "";

    box.className = "alert " + (isErr ? "alert-danger" : (msg ? "alert-success" : "alert-info"));

    box.classList.remove("d-none");

    try { box.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch (_) {}

  }



  function showCorrFeedback(msg, isErr) {

    var el = $("are_corr_feedback");

    if (!el) return;

    el.textContent = msg || "";

    el.className = "small " + (isErr ? "text-danger" : "text-success");

  }



  function bindClick(id, fn) {

    var el = $(id);

    if (!el || typeof fn !== "function") return;

    el.addEventListener("click", function (ev) {

      if (ev && ev.preventDefault) ev.preventDefault();

      fn(ev);

    });

  }



  function parseResponseJson(r) {

    return r.text().then(function (text) {

      var j = null;

      try { j = text ? JSON.parse(text) : null; } catch (_) {}

      if (!j) j = { message: (text || "").slice(0, 300) || ("HTTP " + r.status) };

      return { ok: r.ok, status: r.status, json: j };

    });

  }



  function loadOrgContext() {

    return fetch(root + "/audit/api/org-context", { credentials: "same-origin" })

      .then(function (r) { return parseResponseJson(r); })

      .then(function (x) {

        var j = x.json || {};

        if (!x.ok || !j.ok) return;

        _orgCollection = String(j.activeKnowledgeCollection || j.collection || "").trim();

        var el = $("are_kb_collection");

        if (el) el.textContent = _orgCollection || "—";

      })

      .catch(function () {});

  }



  function parseQuery() {

    var out = {};

    try {

      var p = new URLSearchParams(window.location.search || "");

      p.forEach(function (v, k) { out[k] = v; });

    } catch (_) {}

    return out;

  }



  function currentReportId() {

    var v = ($("are_report_id").value || "").trim();

    return v ? parseInt(v, 10) : NaN;

  }



  function currentSubIdx() {

    var v = ($("are_sub_idx").value || "").trim();

    var n = parseInt(v, 10);

    return isNaN(n) || n < 0 ? 0 : n;

  }



  function pickTargetReport(rootReport, subIdx) {

    var rp = rootReport || {};

    if (rp.batch && Array.isArray(rp.reports) && rp.reports.length) {

      var i = Math.min(Math.max(0, subIdx), rp.reports.length - 1);

      return rp.reports[i] || {};

    }

    return rp;

  }



  function effectiveAction(p) {

    var a = (p && p.action != null) ? String(p.action).trim() : "";

    if (a) return a;

    return defaultActionForSeverity(p && p.severity);

  }



  function countImmediatePoints() {

    var n = 0;

    (_points || []).forEach(function (p) {

      if (effectiveAction(p) === "立即修改") n += 1;

    });

    return n;

  }



  function auditTodoFeatureEnabled() {
    var f = window.__FEATURE_FLAGS__ || {};
    try {
      var q = new URLSearchParams(window.location.search || "");
      var scope = (q.get("scope") || "").trim().toLowerCase();
      if (scope === "page0") return !!f.FEATURE_PAGE0_AUDIT_TODO;
      var manual = (q.get("manual") || "").trim().toLowerCase();
      if (manual === "1" || manual === "true" || manual === "yes" || manual === "on") {
        return !!f.FEATURE_PAGE0_AUDIT_TODO;
      }
    } catch (e) { /* ignore */ }
    return !!f.FEATURE_PAGE1_AUDIT_TODO;
  }

  function updateImmediateHint() {

    var el = $("are_immediate_hint");

    if (!el) return;

    var n = countImmediatePoints();

    el.textContent = n ? ("可生成待办：" + n + " 个「立即修改」点") : "当前无「立即修改」审核点，无法生成待办";

    var btn = $("are_btn_todo");

    if (btn) {
      btn.disabled = n <= 0;
      if (!auditTodoFeatureEnabled()) {
        btn.classList.add("d-none");
      } else {
        btn.classList.remove("d-none");
      }
    }

  }



  function renderPointForm(idx) {

    var p = _points[idx] || {};

    var sev = String(p.severity || "info").toLowerCase();

    $("are_severity").value = SEV_LABEL[sev] || sev || "—";

    $("are_category").value = p.category != null ? String(p.category) : "";

    $("are_location").value = p.location != null ? String(p.location) : "";

    $("are_desc").value = p.description != null ? String(p.description) : "";

    if ($("are_regulation_ref")) {
      $("are_regulation_ref").value = p.regulation_ref != null ? String(p.regulation_ref) : "";
    }

    $("are_suggestion").value = p.suggestion != null ? String(p.suggestion) : "";

    var act = effectiveAction(p);

    if ($("are_action")) $("are_action").value = ACTION_OPTIONS.indexOf(act) >= 0 ? act : defaultActionForSeverity(sev);

    var md = p.modify_docs;

    $("are_modify_docs").value = Array.isArray(md) ? md.join("\n") : (md != null ? String(md) : "");

    if (p.correction_kind === "false_positive" || p.false_positive_reason) {

      if ($("are_corr_fp")) $("are_corr_fp").checked = true;

    } else if (p.deprecated) {

      if ($("are_corr_dep")) $("are_corr_dep").checked = true;

    } else if ($("are_corr_revision")) {

      $("are_corr_revision").checked = true;

    }

    syncCorrectionPanels(p);

  }



  function currentCorrectionKind() {

    var r = document.querySelector('input[name="are_corr_kind"]:checked');

    return (r && r.value) || "revision";

  }



  function syncCorrectionPanels(p) {

    var kind = currentCorrectionKind();

    var fpPanel = $("are_corr_fp_panel");

    var depPanel = $("are_corr_dep_panel");

    var revHint = $("are_corr_revision_hint");

    if (fpPanel) fpPanel.classList.toggle("d-none", kind !== "false_positive");

    if (depPanel) depPanel.classList.toggle("d-none", kind !== "deprecated");

    if (revHint) revHint.classList.toggle("d-none", kind !== "revision");

    if (kind === "false_positive" && $("are_fp_reason")) {

      if (!(($("are_fp_reason").value || "").trim()) && p && p.false_positive_reason) {

        $("are_fp_reason").value = String(p.false_positive_reason);

      }

    }

    if (kind === "deprecated" && $("are_dep_note") && p && p.deprecation_note) {

      $("are_dep_note").value = String(p.deprecation_note);

    }

    var repFields = $("are_replace_fields");

    if (repFields) {

      repFields.classList.toggle("d-none", !(kind === "deprecated" && $("are_add_replace") && $("are_add_replace").checked));

    }

  }



  function buildCorrectionBody() {

    var kind = currentCorrectionKind();

    var body = {

      correction_kind: kind,

      feed_to_kb: !($("are_feed_kb") && !$("are_feed_kb").checked),

    };

    if (kind === "false_positive") {

      body.false_positive_reason = ($("are_fp_reason") && $("are_fp_reason").value || "").trim();

      if (!body.false_positive_reason) {

        return { error: "请填写误报原因" };

      }

      return body;

    }

    if (kind === "deprecated") {

      body.deprecation_note = ($("are_dep_note") && $("are_dep_note").value || "").trim();

      if ($("are_add_replace") && $("are_add_replace").checked) {

        var desc = ($("are_rep_desc") && $("are_rep_desc").value || "").trim();

        if (!desc) return { error: "新增审核点请填写问题描述" };

        body.replacement_point = {

          category: ($("are_rep_category") && $("are_rep_category").value || "一致性").trim() || "一致性",

          location: ($("are_rep_location") && $("are_rep_location").value || "").trim(),

          description: desc,

          suggestion: ($("are_rep_suggestion") && $("are_rep_suggestion").value || "").trim(),

          severity: "low",

          action: "立即修改",

          modify_docs: [],

        };

      }

      return body;

    }

    body.description = $("are_desc").value || "";

    body.regulation_ref = ($("are_regulation_ref") && $("are_regulation_ref").value) || "";

    body.suggestion = $("are_suggestion").value || "";

    body.action = $("are_action").value || "";

    body.modify_docs = ($("are_modify_docs").value || "").split("\n").map(function (s) { return s.trim(); }).filter(Boolean);

    return body;

  }



  function saveCorrection() {

    showCorrFeedback("", false);

    var rid = currentReportId();

    if (!rid || isNaN(rid) || rid <= 0) {

      showMsg("请输入有效报告 ID", true);

      showCorrFeedback("请先填写报告 ID", true);

      return;

    }

    if (!_points || !_points.length) {

      showMsg("请先加载报告", true);

      showCorrFeedback("请先点击「加载报告」", true);

      return;

    }

    var sel = $("are_point_sel");

    var idx = parseInt((sel && sel.value) || "", 10);

    if (isNaN(idx) || idx < 0) {

      showMsg("请选择审核点", true);

      showCorrFeedback("请选择审核点", true);

      return;

    }

    var body = buildCorrectionBody();

    if (body.error) {

      showMsg(body.error, true);

      showCorrFeedback(body.error, true);

      return;

    }

    if (_orgCollection) body.collection = _orgCollection;

    var uid = ($("are_upload_id") && $("are_upload_id").value || "").trim();

    if (uid) body.upload_id = uid;

    body.save_correction = true;

    var url = root + "/audit/api/reports/" + encodeURIComponent(String(rid)) + "/points/" + encodeURIComponent(String(idx))

      + "?sub_report_index=" + encodeURIComponent(String(currentSubIdx()));

    var btn = $("are_btn_correct");

    var btnHtml = btn ? btn.innerHTML : "";

    if (btn) {

      btn.disabled = true;

      btn.setAttribute("aria-busy", "true");

      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>保存中…';

    }

    showCorrFeedback("正在保存纠正…", false);

    fetch(url, {

      method: "PATCH",

      credentials: "same-origin",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify(body),

    })

      .then(parseResponseJson)

      .then(function (x) {

        if (!x.ok || !x.json || !x.json.ok) {

          var em = (x.json && (x.json.message || x.json.detail)) || ("HTTP " + (x.status || ""));

          showMsg(em, true);

          showCorrFeedback(em, true);

          return;

        }

        var coll = (x.json.collection || (x.json.data && x.json.data.collection) || _orgCollection || "").trim();

        var fed = body.feed_to_kb

          ? ("，已写入公司知识库" + (coll ? ("（" + coll + "）") : ""))

          : "";

        showMsg("纠正已保存" + fed, false);

        showCorrFeedback("纠正已保存" + fed, false);

        return loadReport();

      })

      .catch(function (e) {

        var em = String((e && e.message) || e || "纠正保存失败");

        showMsg(em, true);

        showCorrFeedback(em, true);

      })

      .finally(function () {

        if (btn) {

          btn.innerHTML = btnHtml;

          btn.disabled = false;

          btn.removeAttribute("aria-busy");

        }

      });

  }



  function renderPointOptions() {

    var sel = $("are_point_sel");

    sel.innerHTML = "";

    _points.forEach(function (p, i) {

      var op = document.createElement("option");

      var sev = (p && p.severity) ? String(p.severity).toLowerCase() : "";

      var sevZh = SEV_LABEL[sev] || sev;

      var act = effectiveAction(p);

      op.value = String(i);

      op.textContent = "点 #" + i + " [" + (sevZh || "—") + "] · " + act;

      sel.appendChild(op);

    });

    if (_points.length) {

      sel.value = "0";

      renderPointForm(0);

    } else {

      $("are_desc").value = "";

      if ($("are_regulation_ref")) $("are_regulation_ref").value = "";

      $("are_suggestion").value = "";

      $("are_action").value = "无需修改";

      $("are_modify_docs").value = "";

      $("are_severity").value = "";

      $("are_category").value = "";

      $("are_location").value = "";

    }

    updateImmediateHint();

  }



  function loadReport() {

    var rid = currentReportId();

    if (!rid || isNaN(rid) || rid <= 0) {

      showMsg("请输入有效报告 ID", true);

      return Promise.resolve();

    }

    var subIdx = currentSubIdx();

    return fetch(root + "/audit/api/reports/" + encodeURIComponent(String(rid)), { credentials: "same-origin" })

      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, json: j }; }); })

      .then(function (x) {

        if (!x.ok || !x.json || !x.json.ok) {

          showMsg((x.json && (x.json.message || x.json.detail)) || "加载失败", true);

          return;

        }

        var row = x.json.data || {};

        _rawReport = row.report || {};

        var target = pickTargetReport(_rawReport, subIdx);

        _points = Array.isArray(target.audit_points) ? target.audit_points : [];

        renderPointOptions();

        $("are_summary").textContent =

          "总点数 " + (target.total_points || _points.length) +

          "（高 " + (target.high_count || 0) +

          " 中 " + (target.medium_count || 0) +

          " 低 " + (target.low_count || 0) +

          " 提示 " + (target.info_count || 0) + "）";

        showMsg("已加载报告，共 " + _points.length + " 个审核点", false);

      })

      .catch(function (e) {

        showMsg(String((e && e.message) || e || "加载失败"), true);

      });

  }



  function saveCurrentPoint() {

    var rid = currentReportId();

    if (!rid || isNaN(rid) || rid <= 0) {

      showMsg("请输入有效报告 ID", true);

      return;

    }

    var sel = $("are_point_sel");

    var idx = parseInt((sel && sel.value) || "", 10);

    if (isNaN(idx) || idx < 0) {

      showMsg("请选择审核点", true);

      return;

    }

    var body = {

      description: $("are_desc").value || "",

      regulation_ref: ($("are_regulation_ref") && $("are_regulation_ref").value) || "",

      suggestion: $("are_suggestion").value || "",

      action: $("are_action").value || "",

      modify_docs: ($("are_modify_docs").value || "").split("\n").map(function (s) { return s.trim(); }).filter(Boolean),

    };

    var url = root + "/audit/api/reports/" + encodeURIComponent(String(rid)) + "/points/" + encodeURIComponent(String(idx))

      + "?sub_report_index=" + encodeURIComponent(String(currentSubIdx()));

    fetch(url, {

      method: "PATCH",

      credentials: "same-origin",

      headers: { "Content-Type": "application/json" },

      body: JSON.stringify(body),

    })

      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, json: j }; }); })

      .then(function (x) {

        if (!x.ok || !x.json || !x.json.ok) {

          showMsg((x.json && (x.json.message || x.json.detail)) || "保存失败", true);

          return;

        }

        showMsg("已保存", false);

        loadReport();

      })

      .catch(function (e) {

        showMsg(String((e && e.message) || e || "保存失败"), true);

      });

  }



  function gotoTodo() {

    var rid = currentReportId();

    if (!rid || isNaN(rid) || rid <= 0) {

      showMsg("请先输入报告 ID", true);

      return;

    }

    if (countImmediatePoints() <= 0) {

      showMsg("当前报告没有「立即修改」的审核点，请先将需处理的点设为「立即修改」后再生成待办", true);

      return;

    }

    var uid = ($("are_upload_id").value || "").trim();

    var u = new URLSearchParams();

    u.set("report_id", String(rid));

    if (uid) {

      u.set("upload_id", uid);

      u.set("base_upload_id", uid);

    }

    window.open(root + "/audit-modify/?" + u.toString(), "_blank", "noopener");

  }



  function init() {

    var q = parseQuery();

    if (q.report_id && $("are_report_id")) $("are_report_id").value = String(q.report_id);

    if (q.upload_id && $("are_upload_id")) $("are_upload_id").value = String(q.upload_id);

    if (q.sub_report_index && $("are_sub_idx")) $("are_sub_idx").value = String(q.sub_report_index);

    var pendingPointIdx = q.point_index != null ? parseInt(String(q.point_index), 10) : NaN;

    var pendingCorrKind = (q.corr_kind || "").trim().toLowerCase();



    bindClick("are_btn_load", loadReport);

    bindClick("are_btn_save", saveCurrentPoint);

    bindClick("are_btn_todo", gotoTodo);

    bindClick("are_btn_correct", saveCorrection);



    document.querySelectorAll('input[name="are_corr_kind"]').forEach(function (el) {

      el.addEventListener("change", function () {

        var idx = parseInt(($("are_point_sel") && $("are_point_sel").value) || "", 10);

        syncCorrectionPanels(!isNaN(idx) ? (_points[idx] || {}) : {});

      });

    });



    if ($("are_add_replace")) {

      $("are_add_replace").addEventListener("change", function () {

        var idx = parseInt(($("are_point_sel") && $("are_point_sel").value) || "", 10);

        syncCorrectionPanels(!isNaN(idx) ? (_points[idx] || {}) : {});

      });

    }



    if ($("are_point_sel")) {

      $("are_point_sel").addEventListener("change", function () {

        var idx = parseInt(($("are_point_sel").value || ""), 10);

        if (!isNaN(idx)) renderPointForm(idx);

      });

    }



    function afterReportLoaded() {

      if (!isNaN(pendingPointIdx) && pendingPointIdx >= 0 && $("are_point_sel")) {

        $("are_point_sel").value = String(pendingPointIdx);

        renderPointForm(pendingPointIdx);

        if (pendingCorrKind === "false_positive" && $("are_corr_fp")) {

          $("are_corr_fp").checked = true;

          syncCorrectionPanels(_points[pendingPointIdx] || {});

        } else if (pendingCorrKind === "deprecated" && $("are_corr_dep")) {

          $("are_corr_dep").checked = true;

          syncCorrectionPanels(_points[pendingPointIdx] || {});

        }

      }

      if (window.location.hash === "#are_correction_panel") {

        var panel = $("are_correction_panel");

        if (panel && panel.scrollIntoView) panel.scrollIntoView({ behavior: "smooth", block: "start" });

      }

    }



    var boot = loadOrgContext();

    if (($("are_report_id").value || "").trim()) {

      return boot.then(function () { return loadReport(); }).then(afterReportLoaded);

    }

    updateImmediateHint();

    return boot;

  }



  function runInit() {

    if (!$("are_report_id")) return;

    var todoBtn = $("are_btn_todo");

    if (todoBtn && !auditTodoFeatureEnabled()) todoBtn.classList.add("d-none");

    try {

      return init();

    } catch (e) {

      showMsg("页面初始化失败：" + String((e && e.message) || e), true);

    }

  }



  if (typeof registerPageInit === "function") {

    registerPageInit(runInit);

  } else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", runInit);

  else runInit();

})();

