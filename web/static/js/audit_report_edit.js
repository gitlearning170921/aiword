(function () {

  "use strict";

  var root = window.__SCRIPT_ROOT__ || "";

  var $ = function (id) { return document.getElementById(id); };

  var _rawReport = null;

  var _points = [];



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

    box.className = "alert " + (isErr ? "alert-danger" : "alert-info");

    box.classList.remove("d-none");

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



  function updateImmediateHint() {

    var el = $("are_immediate_hint");

    if (!el) return;

    var n = countImmediatePoints();

    el.textContent = n ? ("可生成待办：" + n + " 个「立即修改」点") : "当前无「立即修改」审核点，无法生成待办";

    var btn = $("are_btn_todo");

    if (btn) btn.disabled = n <= 0;

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

      return;

    }

    var subIdx = currentSubIdx();

    fetch(root + "/audit/api/reports/" + encodeURIComponent(String(rid)), { credentials: "same-origin" })

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

    if (q.report_id) $("are_report_id").value = String(q.report_id);

    if (q.upload_id) $("are_upload_id").value = String(q.upload_id);

    if (q.sub_report_index) $("are_sub_idx").value = String(q.sub_report_index);



    $("are_btn_load").addEventListener("click", loadReport);

    $("are_btn_save").addEventListener("click", saveCurrentPoint);

    $("are_btn_todo").addEventListener("click", gotoTodo);

    $("are_point_sel").addEventListener("change", function () {

      var idx = parseInt(($("are_point_sel").value || ""), 10);

      if (!isNaN(idx)) renderPointForm(idx);

    });

    if (($("are_report_id").value || "").trim()) loadReport();

    else updateImmediateHint();

  }



  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);

  else init();

})();

