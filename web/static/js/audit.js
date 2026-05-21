/**
 * /audit/ 页面前端：
 * - 解析 URL 参数（upload_ids、mode 等）回填表单
 * - 提交 → 轮询 → 显示报告摘要 / 下载 ZIP
 */
(function () {
  "use strict";
  if (!window.AsyncJob) return;
  var $ = function (id) { return document.getElementById(id); };
  var root = window.__SCRIPT_ROOT__ || "";
  var _historyPage = 1;
  var _historyTotalPages = 1;

  function parseQuery() {
    var out = {};
    try {
      var params = new URLSearchParams(window.location.search);
      params.forEach(function (v, k) { out[k] = v; });
    } catch (_) {}
    return out;
  }

  function showMsg(text, isErr) { AsyncJob.showMsg("aud_msg", text, isErr); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function parseUploadIdsText(txt) {
    return String(txt || "")
      .split(/[\n,]+/)
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function resolveUploadName(uploadId) {
    return AsyncJob.api(
      root + "/audit/api/upload-name?upload_id=" + encodeURIComponent(String(uploadId || "").trim()),
      { method: "GET" }
    ).then(function (x) {
      if (!x.ok || !x.json || !x.json.ok) return "";
      return String((x.json && x.json.fileName) || "");
    }).catch(function () { return ""; });
  }

  function renderUploadNames() {
    var box = $("aud_upload_names");
    if (!box) return;
    var ids = parseUploadIdsText($("aud_upload_ids") && $("aud_upload_ids").value);
    if (!ids.length) {
      box.textContent = "";
      return;
    }
    box.textContent = "正在解析文件名…";
    Promise.all(ids.map(function (id) {
      return resolveUploadName(id).then(function (nm) {
        return "ID " + id + " -> " + (nm || "（未找到名称）");
      });
    })).then(function (rows) {
      box.innerHTML = rows.map(function (r) { return esc(r); }).join("<br/>");
    });
  }

  function setHistoryRows(items) {
    var tbody = $("aud_history_rows");
    if (!tbody) return;
    tbody.innerHTML = "";
    (items || []).forEach(function (it) {
      var tr = document.createElement("tr");
      var statusBadge = '<span class="badge bg-' + (
        it.status === 'succeeded' ? 'success' : it.status === 'failed' ? 'danger' : 'secondary'
      ) + '">' + AsyncJob.statusZh(it.status || '') + '</span>';
      var reports = (it.reportIds || []).slice(0, 5).map(function (rid) { return String(rid); }).join(', ');
      var reportIds = Array.isArray(it.reportIds) ? it.reportIds.map(function (x) { return String(x); }) : [];
      var firstReportId = reportIds.length ? String(reportIds[0]) : "";
      var firstUploadId = (it.uploadIds && it.uploadIds.length) ? String(it.uploadIds[0]) : "";
      var tdOp = '<span class="text-muted small">—</span>';
      if (firstReportId) {
        var selectHtml = "";
        if (reportIds.length > 1) {
          selectHtml = '<select class="form-select form-select-sm d-inline-block me-1 aud-report-select" style="width:auto;">'
            + reportIds.map(function (rid) {
              return '<option value="' + rid + '">' + rid + '</option>';
            }).join("")
            + '</select>';
        }
        var editHref = root + "/audit/report-edit?report_id=" + encodeURIComponent(firstReportId)
          + (firstUploadId ? ("&upload_id=" + encodeURIComponent(firstUploadId)) : "");
        var todoHref = root + "/audit-modify/?report_id=" + encodeURIComponent(firstReportId)
          + (firstUploadId ? ("&upload_id=" + encodeURIComponent(firstUploadId) + "&base_upload_id=" + encodeURIComponent(firstUploadId)) : "");
        tdOp = selectHtml
          + '<button type="button" class="btn btn-sm btn-outline-success me-1 aud-btn-view-results" data-job-id="'
          + esc(it.id || '') + '" title="加载与 aicheckword 一致的完整审核点">查看结果</button>'
          + '<a class="btn btn-sm btn-outline-secondary me-1 aud-report-edit-link" target="_blank" rel="noopener"'
          + ' href="' + editHref + '" title="在 aiword 编辑报告">编辑报告</a>'
          + '<a class="btn btn-sm btn-outline-primary aud-report-todo-link" target="_blank" rel="noopener"'
          + ' href="' + todoHref + '" title="基于该报告生成审核后修改任务">生成待办</a>';
      } else if (it.status === "succeeded") {
        tdOp = '<button type="button" class="btn btn-sm btn-outline-success aud-btn-view-results" data-job-id="'
          + esc(it.id || '') + '">查看结果</button>';
      }
      tr.innerHTML =
        '<td class="small text-muted">' + (it.createdAt || '') + '</td>' +
        '<td>' + (it.mode || '') + '</td>' +
        '<td>' + statusBadge + '</td>' +
        '<td class="small">' + (reports || '—') + '</td>' +
        '<td class="small text-monospace">' + (it.id || '') + '</td>' +
        '<td class="small text-muted">' + ((it.message || it.error || '') + '').slice(0, 120) + '</td>' +
        '<td>' + tdOp + '</td>';
      tbody.appendChild(tr);
      tr.querySelector(".aud-btn-view-results")?.addEventListener("click", function () {
        var jid = (it.id || "").trim();
        if (!jid) return;
        $("aud_local_job_id").textContent = jid;
        loadJobFullReports(jid);
        var box = $("aud_reports_box");
        if (box && box.scrollIntoView) {
          try { box.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (_) { box.scrollIntoView(true); }
        }
        showMsg("已加载任务 " + jid + " 的完整审核结果", false);
      });
      var sel = tr.querySelector(".aud-report-select");
      if (sel) {
        sel.addEventListener("change", function () {
          var rid = String(sel.value || "").trim();
          if (!rid) return;
          var up = firstUploadId ? String(firstUploadId) : "";
          var edit = tr.querySelector(".aud-report-edit-link");
          var todo = tr.querySelector(".aud-report-todo-link");
          if (edit) {
            edit.href = root + "/audit/report-edit?report_id=" + encodeURIComponent(rid)
              + (up ? ("&upload_id=" + encodeURIComponent(up)) : "");
          }
          if (todo) {
            todo.href = root + "/audit-modify/?report_id=" + encodeURIComponent(rid)
              + (up ? ("&upload_id=" + encodeURIComponent(up) + "&base_upload_id=" + encodeURIComponent(up)) : "");
          }
        });
      }
    });
  }

  function updateHistoryPager(pg) {
    _historyPage = parseInt((pg && pg.page) || _historyPage || 1, 10) || 1;
    _historyTotalPages = parseInt((pg && pg.total_pages) || 1, 10) || 1;
    var info = $("aud_history_pager_info");
    if (info) info.textContent = "第 " + _historyPage + "/" + _historyTotalPages + " 页（共 " + ((pg && pg.total) || 0) + " 条）";
    var prev = $("aud_history_prev");
    var next = $("aud_history_next");
    if (prev) prev.disabled = _historyPage <= 1;
    if (next) next.disabled = _historyPage >= _historyTotalPages;
  }

  function loadHistory() {
    AsyncJob.api(
      root + "/audit/api/jobs?page=" + encodeURIComponent(String(_historyPage || 1)) + "&page_size=10",
      { method: "GET" }
    ).then(function (x) {
      if (x.ok && x.json && x.json.ok) {
        setHistoryRows(x.json.items || []);
        updateHistoryPager((x.json && x.json.pagination) || {});
      }
    });
  }

  var SEV_ICON = { high: "🔴", medium: "🟡", low: "🔵", info: "ℹ️" };
  var SEV_ZH = { high: "高", medium: "中", low: "低", info: "提示" };
  var _lastViewJobId = "";

  function renderReportsSummary(summary) {
    var box = $("aud_reports_box");
    if (!box) return;
    if (!summary || !summary.length) {
      box.textContent = "暂无报告摘要。";
      return;
    }
    var html = ['<ul class="list-group small mb-3">'];
    summary.forEach(function (it) {
      if (it.error) {
        html.push('<li class="list-group-item list-group-item-danger">'
          + esc(it.file || '') + ' · 错误：' + esc(it.error || '') + '</li>');
      } else {
        var rid = (it.report_id != null ? String(it.report_id) : "");
        var uploadId = (it.aiword_upload_id != null ? String(it.aiword_upload_id) : "");
        var editBtn = rid
          ? ('<a class="btn btn-sm btn-outline-secondary ms-2" target="_blank" rel="noopener"'
              + ' href="' + root + '/audit/report-edit?report_id=' + encodeURIComponent(rid)
              + (uploadId ? ('&upload_id=' + encodeURIComponent(uploadId)) : '')
              + '">编辑报告</a>')
          : "";
        var todoHref = root + "/audit-modify/?report_id=" + encodeURIComponent(rid || "");
        if (uploadId) {
          todoHref += "&upload_id=" + encodeURIComponent(uploadId);
          todoHref += "&base_upload_id=" + encodeURIComponent(uploadId);
        }
        var todoBtn = rid
          ? ('<a class="btn btn-sm btn-outline-primary ms-1" target="_blank" rel="noopener"'
              + ' href="' + todoHref + '">生成审核后修改待办</a>')
          : "";
        html.push('<li class="list-group-item">'
          + esc(it.file || '') + ' · 报告 ' + esc(it.report_id != null ? it.report_id : '—')
          + ' · 总点数 ' + esc(it.total || 0)
          + ' · <span class="badge bg-danger">高 ' + esc(it.high || 0) + '</span>'
          + ' <span class="badge bg-warning text-dark">中 ' + esc(it.medium || 0) + '</span>'
          + ' <span class="badge bg-info text-dark">低 ' + esc(it.low || 0) + '</span>'
          + ' <span class="badge bg-secondary">提示 ' + esc(it.info || 0) + '</span>'
          + editBtn + todoBtn
          + '</li>');
      }
    });
    html.push('</ul>');
    html.push('<div id="aud_full_reports_detail"></div>');
    box.innerHTML = html.join('');
  }

  function expandReportSections(row) {
    var root = (row && row.report) || {};
    if (root.batch && Array.isArray(root.reports) && root.reports.length) {
      return root.reports.map(function (sub, idx) {
        return {
          title: sub.original_filename || sub.file_name || ("子报告 " + (idx + 1)),
          report: sub,
          reportId: row.id,
          subIdx: idx,
        };
      });
    }
    return [{
      title: root.original_filename || root.file_name || row.file_name || ("报告 " + (row.id || "")),
      report: root,
      reportId: row.id,
      subIdx: 0,
    }];
  }

  function renderAuditPointCard(p, index) {
    var sev = String((p && p.severity) || "info").toLowerCase();
    var icon = SEV_ICON[sev] || "ℹ️";
    var dep = p && p.deprecated;
    var fp = p && (p.correction_kind === "false_positive" || p.false_positive_reason);
    var prefix = dep ? "〔弃〕 " : (fp ? "〔误〕 " : "");
    var action = (p && p.action) ? String(p.action) : "";
    var md = Array.isArray(p && p.modify_docs) ? p.modify_docs.filter(Boolean).join("；") : "";
    var parts = [
      '<div class="border-start border-3 ps-2 mb-3' + (dep ? " opacity-75" : "") + '">',
      '<div class="fw-semibold">' + prefix + icon + ' 审核点 ' + index + '：' + esc((p && p.category) || "未分类") + '</div>',
      '<div class="small text-muted">严重程度：' + esc(SEV_ZH[sev] || sev) + ' · 位置：' + esc((p && p.location) || "未知") + '</div>',
    ];
    if (action) {
      parts.push('<div class="small">处理状态：<span class="badge bg-light text-dark border">' + esc(action) + '</span></div>');
    }
    parts.push('<div class="small mt-1"><strong>问题描述：</strong>' + esc((p && p.description) || "") + '</div>');
    parts.push('<div class="small"><strong>法规依据：</strong>' + esc((p && p.regulation_ref) || "") + '</div>');
    parts.push('<div class="small"><strong>修改建议：</strong>' + esc((p && p.suggestion) || "") + '</div>');
    if (md) {
      parts.push('<div class="small"><strong>需修改文档：</strong>' + esc(md) + '</div>');
    }
    parts.push("</div>");
    return parts.join("");
  }

  function renderFullReports(items, errors) {
    var detail = $("aud_full_reports_detail");
    if (!detail) {
      var box = $("aud_reports_box");
      if (!box) return;
      detail = document.createElement("div");
      detail.id = "aud_full_reports_detail";
      box.appendChild(detail);
    }
    var html = [];
    if (errors && errors.length) {
      html.push('<div class="alert alert-warning small py-2">部分报告加载失败：'
        + esc(errors.map(function (e) {
          return (e.report_id != null ? ("#" + e.report_id) : "") + (e.error || "");
        }).join("；"))
        + '</div>');
    }
    if (!items || !items.length) {
      html.push('<p class="text-muted small">未加载到完整报告内容。</p>');
      detail.innerHTML = html.join("");
      return;
    }
    items.forEach(function (row) {
      expandReportSections(row).forEach(function (sec) {
        var rep = sec.report || {};
        html.push('<div class="border rounded p-3 mb-3 bg-white">');
        html.push('<h6 class="mb-2">📄 ' + esc(sec.title)
          + ' <span class="text-muted small">报告 ID ' + esc(sec.reportId || "—")
          + (sec.subIdx > 0 || (row.report && row.report.batch) ? (" · 子报告 " + sec.subIdx) : "")
          + '</span></h6>');
        html.push('<div class="d-flex flex-wrap gap-2 mb-2 small">'
          + '<span class="badge bg-danger">高 ' + esc(rep.high_count || 0) + '</span>'
          + '<span class="badge bg-warning text-dark">中 ' + esc(rep.medium_count || 0) + '</span>'
          + '<span class="badge bg-info text-dark">低 ' + esc(rep.low_count || 0) + '</span>'
          + '<span class="badge bg-secondary">提示 ' + esc(rep.info_count || 0) + '</span>'
          + '<span class="text-muted">共 ' + esc(rep.total_points || (rep.audit_points || []).length) + ' 点</span>'
          + '</div>');
        if (rep.summary) {
          html.push('<p class="small border-bottom pb-2"><strong>总结：</strong>' + esc(rep.summary) + '</p>');
        }
        var points = rep.audit_points || [];
        if (!points.length) {
          html.push('<p class="text-muted small">（无审核点）</p>');
        } else {
          points.forEach(function (p, i) {
            html.push(renderAuditPointCard(p, i + 1));
          });
        }
        var rid = sec.reportId != null ? String(sec.reportId) : "";
        if (rid) {
          html.push('<div class="mt-2">'
            + '<a class="btn btn-sm btn-outline-secondary" target="_blank" rel="noopener" href="'
            + root + '/audit/report-edit?report_id=' + encodeURIComponent(rid)
            + '&sub_report_index=' + encodeURIComponent(String(sec.subIdx || 0))
            + '">编辑本报告</a></div>');
        }
        html.push("</div>");
      });
    });
    detail.innerHTML = html.join("");
  }

  function loadJobFullReports(localJobId) {
    var box = $("aud_reports_box");
    if (!box || !localJobId) return Promise.resolve();
    _lastViewJobId = localJobId;
    var reloadBtn = $("aud_btn_reload_reports");
    if (reloadBtn) reloadBtn.classList.remove("d-none");
    box.innerHTML = '<p class="text-muted small">正在从 aicheckword 加载完整审核结果…</p>';
    return AsyncJob.api(
      root + "/audit/api/jobs/" + encodeURIComponent(localJobId) + "/reports",
      { method: "GET" }
    ).then(function (x) {
      if (!x.ok || !x.json || !x.json.ok) {
        var em = (x.json && (x.json.message || x.json.detail)) || ("HTTP " + x.status);
        box.innerHTML = '<p class="text-danger small">加载完整报告失败：' + esc(em) + '</p>';
        return;
      }
      var items = x.json.items || [];
      var pseudoSummary = items.map(function (row) {
        var rep = row.report || {};
        return {
          file: rep.original_filename || rep.file_name || row.file_name,
          report_id: row.id,
          total: rep.total_points,
          high: rep.high_count,
          medium: rep.medium_count,
          low: rep.low_count,
          info: rep.info_count,
        };
      });
      renderReportsSummary(pseudoSummary);
      renderFullReports(items, x.json.errors || []);
    }).catch(function (e) {
      box.innerHTML = '<p class="text-danger small">加载完整报告异常：' + esc(String((e && e.message) || e)) + '</p>';
    });
  }

  function buildPayload() {
    var IP = window.IntegrationPrefill;
    var mode = ($("aud_mode") && $("aud_mode").value || "single").trim();
    var pf0 = IP && IP.parsePrefillFromLocation ? IP.parsePrefillFromLocation() : null;
    var pid = ($("aud_project_sel") && $("aud_project_sel").value || $("aud_project_id").value || "").trim();
    if ((!pid || isNaN(parseInt(pid, 10))) && pf0 && pf0.aicheckword_project_id) {
      pid = String(pf0.aicheckword_project_id);
    }
    if ($("aud_project_id")) $("aud_project_id").value = pid;
    var rc = ($("aud_registration_country") && $("aud_registration_country").value || "").trim();
    var rt = ($("aud_registration_type") && $("aud_registration_type").value || "").trim();
    var rcomp = ($("aud_registration_component") && $("aud_registration_component").value || "").trim();
    var pf = ($("aud_project_form") && $("aud_project_form").value || "").trim();
    var payload = {
      mode: mode,
      collection: ($("aud_collection") && $("aud_collection").value || "regulations").trim() || "regulations",
      provider: ($("aud_provider") && $("aud_provider").value || "").trim() || null,
      auto_match_case: true,
      document_language: ($("aud_document_language") && $("aud_document_language").value || "").trim(),
      registration_country: rc,
      registration_type: rt,
      registration_component: rcomp,
      project_form: pf,
    };
    if (pid) payload.project_id = parseInt(pid, 10);
    var b = window.__integrationBootstrap_aud;
    var proj = IP && b ? IP.findProjectRow(b.projects, pid) : null;
    if (proj) {
      payload.project_name = proj.name || "";
      payload.project_name_en = proj.productNameEn || "";
      payload.product_name = proj.productName || "";
      payload.product_name_en = proj.productNameEn || "";
      payload.model = proj.model || "";
      payload.model_en = proj.modelEn || "";
      if (proj.registrationCountryEn) payload.registration_country_en = proj.registrationCountryEn;
    }
    payload.review_context = {
      registration_country: rc ? [rc] : [],
      registration_type: rt ? [rt] : [],
      registration_component: rcomp ? [rcomp] : [],
      project_form: pf ? [pf] : [],
      document_language: payload.document_language,
      _project_name: (proj && proj.name) || "",
      _product_name: (proj && proj.productName) || "",
    };
    return payload;
  }

  function submitJob() {
    var IP = window.IntegrationPrefill;
    if (IP && IP.requireAicheckwordProject) {
      var chk = IP.requireAicheckwordProject("aud");
      if (!chk.ok) {
        showMsg(chk.message, true);
        return;
      }
    }
    var prog = AsyncJob.progressUI({
      wrapId: "aud_progress_wrap",
      barId: "aud_progress_bar",
      textId: "aud_progress_caption",
      headlineId: "aud_progress_headline",
    });
    var btn = $("aud_btn_submit");
    var dlBtn = $("aud_btn_download");
    if (dlBtn) dlBtn.disabled = true;

    var payload = buildPayload();
    var uploadIdsTxt = ($("aud_upload_ids").value || "").trim();
    var pickedFiles = ($("aud_files_picker").files || []);
    var hasTask = !!uploadIdsTxt;
    var hasManual = pickedFiles && pickedFiles.length > 0;
    if (hasTask && hasManual) {
      showMsg("来源唯一性：upload_ids 与手动上传不可同时使用", true);
      return;
    }
    if (!hasTask && !hasManual) {
      showMsg("请提供 upload_ids 或选择文件", true);
      return;
    }
    if (payload.mode !== "single") {
      var fileCount = hasTask
        ? uploadIdsTxt.split(/[\n,]+/).map(function (s) { return s.trim(); }).filter(Boolean).length
        : pickedFiles.length;
      if (fileCount < 2) {
        showMsg(payload.mode + " 模式至少需要 2 个文件", true);
        return;
      }
    } else if (hasManual && pickedFiles.length > 50) {
      showMsg("single 模式单次最多 50 个文件，当前 " + pickedFiles.length + " 个", true);
      return;
    }

    var fd = new FormData();
    fd.append("payload", JSON.stringify(payload));
    if (hasTask) fd.append("upload_ids", uploadIdsTxt);
    if (hasManual) {
      for (var i = 0; i < pickedFiles.length; i++) {
        fd.append("input_files", pickedFiles[i], pickedFiles[i].name);
      }
    }

    if (btn) btn.disabled = true;
    showMsg("正在提交…", false);
    prog.show(); prog.setRunning(true); prog.setHeadline("提交中…");
    prog.update(0.03, "正在上传文件…");

    fetch(root + "/audit/api/jobs", { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, json: j }; }); })
      .then(function (x) {
        if (!x.ok || !x.json || !x.json.ok) {
          var em = (x.json && (x.json.message || x.json.detail)) || "提交失败";
          showMsg(em, true);
          prog.setRunning(false); prog.setTerminal(false);
          prog.update(0, em);
          if (btn) btn.disabled = false;
          return;
        }
        var localId = x.json.localJobId;
        $("aud_local_job_id").textContent = localId;
        showMsg("已提交，任务号 " + localId + "，轮询中…", false);
        prog.setHeadline("轮询中…");
        AsyncJob.pollJob(
          root + "/audit/api/jobs/" + encodeURIComponent(localId) + "/status",
          {
            onUpdate: function (u) {
              prog.update(u.progress || 0, u.message || "");
            },
            onDone: function (err, finalJson) {
              if (btn) btn.disabled = false;
              prog.setRunning(false);
              if (err) {
                prog.setHeadline("轮询异常");
                showMsg(String(err.message || err), true);
                prog.setTerminal(false);
                loadHistory();
                return;
              }
              var st = AsyncJob.normalizeJobStatus(finalJson && finalJson.status);
              if (st === "succeeded") {
                prog.setHeadline("审核已完成");
                prog.setTerminal(true);
                prog.update(1, "审核完成");
                showMsg("审核完成", false);
                if (dlBtn) dlBtn.disabled = false;
                var summ = (finalJson && finalJson.reportsSummary) || (finalJson && finalJson.result && finalJson.result.reports_summary) || [];
                renderReportsSummary(summ);
                loadJobFullReports(localId);
              } else {
                prog.setHeadline("审核失败");
                prog.setTerminal(false);
                var tail = (finalJson && (finalJson.error || finalJson.errorSummary || finalJson.message)) || "失败";
                showMsg("任务结束: " + AsyncJob.statusZh(st) + " · " + String(tail).slice(0, 300), true);
              }
              loadHistory();
            },
          }
        );
      })
      .catch(function (e) {
        if (btn) btn.disabled = false;
        prog.setRunning(false); prog.setTerminal(false);
        showMsg(String((e && e.message) || e || "提交异常"), true);
      });
  }

  function downloadJob() {
    var jid = ($("aud_local_job_id").textContent || "").trim();
    if (!jid || jid === "—") return;
    window.location.href = root + "/audit/api/jobs/" + encodeURIComponent(jid) + "/download";
  }

  function init() {
    if (!window.IntegrationPrefill) return;
    var IP = window.IntegrationPrefill;
    var q = parseQuery();
    var pf = IP.parsePrefillFromLocation();
    if (q.upload_ids) {
      var lst = String(q.upload_ids).split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      $("aud_upload_ids").value = lst.join("\n");
      renderUploadNames();
    }
    if (q.mode && ["single", "multi", "traceability"].indexOf(q.mode) >= 0) {
      $("aud_mode").value = q.mode;
    }
    if (!pf && q.project_id) {
      pf = { aicheckword_project_id: parseInt(String(q.project_id), 10) || null };
    }
    if (!pf && q.aicheckword_project_id) {
      pf = { aicheckword_project_id: parseInt(String(q.aicheckword_project_id), 10) || null };
    }

    var bootstrapOpts = {
      prefix: "aud",
      root: root,
      bootstrapUrl: root + "/audit/api/integration-bootstrap",
      uploadPrefillBase: root + "/audit",
      prefill: pf,
      withCases: false,
      onError: function (m) { showMsg(m, true); },
    };
    IP.loadBootstrap(bootstrapOpts);
    IP.wireProjectSelect("aud", function () { return window.__integrationBootstrap_aud; }, function () {
      return IP.getPagePrefill("aud") || IP.parsePrefillFromLocation();
    });

    var picker = $("aud_files_picker");
    if (picker) {
      picker.addEventListener("change", function () {
        var n = (picker.files || []).length;
        $("aud_files_count").textContent = n ? "已选 " + n + " 个文件" : "未选择";
      });
    }

    var subBtn = $("aud_btn_submit");
    if (subBtn) subBtn.addEventListener("click", submitJob);
    var upl = $("aud_upload_ids");
    if (upl) {
      upl.addEventListener("blur", function () {
        renderUploadNames();
        IP.rematchProjectFromTask("aud", bootstrapOpts);
      });
    }
    var coll = $("aud_collection");
    if (coll) {
      coll.addEventListener("change", function () {
        IP.loadBootstrap(Object.assign({}, bootstrapOpts, {
          prefill: IP.getPagePrefill("aud") || IP.parsePrefillFromLocation(),
        }));
      });
    }
    var dlBtn = $("aud_btn_download");
    if (dlBtn) dlBtn.addEventListener("click", downloadJob);
    var reloadRep = $("aud_btn_reload_reports");
    if (reloadRep) {
      reloadRep.addEventListener("click", function () {
        var jid = (_lastViewJobId || ($("aud_local_job_id").textContent || "")).trim();
        if (!jid || jid === "—") {
          showMsg("请先完成一次审核或从历史记录选择任务", true);
          return;
        }
        loadJobFullReports(jid);
      });
    }
    var hPrev = $("aud_history_prev");
    if (hPrev) hPrev.addEventListener("click", function () {
      if (_historyPage <= 1) return;
      _historyPage -= 1;
      loadHistory();
    });
    var hNext = $("aud_history_next");
    if (hNext) hNext.addEventListener("click", function () {
      if (_historyPage >= _historyTotalPages) return;
      _historyPage += 1;
      loadHistory();
    });

    loadHistory();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
