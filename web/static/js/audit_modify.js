/**
 * /audit-modify/ 页面前端：拉报告 → 预览 → 上传 Base → 提交 → 轮询。
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
      var p = new URLSearchParams(window.location.search);
      p.forEach(function (v, k) { out[k] = v; });
    } catch (_) {}
    return out;
  }

  function showMsg(t, e) { AsyncJob.showMsg("amod_msg", t, e); }

  function resolveUploadName(uploadId, boxId) {
    var box = $(boxId);
    if (!box) return;
    var id = String(uploadId || "").trim();
    if (!id) {
      box.textContent = "";
      return;
    }
    box.textContent = "正在加载文件名…";
    AsyncJob.api(
      root + "/audit-modify/api/upload-name?upload_id=" + encodeURIComponent(id),
      { method: "GET" }
    ).then(function (x) {
      if (!x.ok || !x.json || !x.json.ok) {
        box.textContent = "ID " + id + "（未找到名称）";
        return;
      }
      box.textContent = "ID " + id + " -> " + String(x.json.fileName || "");
    }).catch(function () {
      box.textContent = "ID " + id + "（名称查询失败）";
    });
  }


  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function statusBadgeZh(st) {
    var m = { modified: "已修改", partial: "部分修改", not_addressed: "未修改" };
    return m[String(st || "")] || String(st || "");
  }

  function renderAuditCoverage(covByTarget) {
    var wrap = $("amod_coverage_wrap");
    var sumEl = $("amod_coverage_summary");
    var listEl = $("amod_coverage_list");
    if (!wrap || !listEl) return;
    if (!covByTarget || typeof covByTarget !== "object") {
      wrap.classList.add("d-none");
      return;
    }
    var keys = Object.keys(covByTarget);
    if (!keys.length) {
      wrap.classList.add("d-none");
      return;
    }
    wrap.classList.remove("d-none");
    var html = "";
    var totalAll = 0, modAll = 0, missAll = 0;
    keys.forEach(function (fn) {
      var cov = covByTarget[fn] || {};
      var sm = cov.summary || {};
      totalAll += sm.total_immediate_points || 0;
      modAll += sm.modified || 0;
      missAll += (sm.not_addressed || 0) + (sm.partial || 0);
      html += '<div class="mb-3"><div class="fw-semibold">' + esc(fn) + "</div>";
      html += '<div class="text-muted mb-1">共 ' + (sm.total_immediate_points || 0) +
        " 点 · 已改 " + (sm.modified || 0) + " · 部分 " + (sm.partial || 0) +
        " · 未改 " + (sm.not_addressed || 0) + "（ZIP 内 *.audit_modify.log.md 含改前/改后详情）</div>";
      (cov.points || []).forEach(function (pt, idx) {
        var st = pt.status || "not_addressed";
        var badgeCls = st === "modified" ? "success" : st === "partial" ? "warning" : "secondary";
        html += '<div class="border-top pt-2 mt-2"><span class="badge bg-' + badgeCls + ' me-1">' +
          esc(statusBadgeZh(st)) + '</span><code>' + esc(pt.audit_point_ref || "") + "</code>";
        if (pt.location) html += '<div class="text-muted">位置：' + esc(pt.location) + "</div>";
        if (pt.description) html += "<div>问题：" + esc(String(pt.description).slice(0, 240)) + "</div>";
        (pt.changes || []).slice(0, 2).forEach(function (ch) {
          html += '<div class="mt-1"><span class="text-muted">' + esc(ch.type || "change") + "</span>";
          if (ch.before) html += '<pre class="small mb-0 bg-white border p-1">' + esc(String(ch.before).slice(0, 400)) + "</pre>";
          if (ch.after) html += '<pre class="small mb-0 bg-white border p-1">' + esc(String(ch.after).slice(0, 400)) + "</pre>";
          html += "</div>";
        });
        if (st !== "modified" && pt.not_addressed_reason) {
          html += '<div class="text-danger small mt-1">原因：' + esc(pt.not_addressed_reason) + "</div>";
        }
        html += "</div>";
      });
      html += "</div>";
    });
    if (sumEl) {
      sumEl.textContent = "汇总：共 " + totalAll + " 个立即修改点 · 已落实 " + modAll + " · 未完全落实 " + missAll;
    }
    listEl.innerHTML = html || "（无覆盖数据）";
  }

  function historyDownloadUrl(it) {
    if (!it || !it.id) return "";
    return root + "/audit-modify/api/jobs/" + encodeURIComponent(it.id) + "/download";
  }

  function historyCanDownload(it) {
    if (!it) return false;
    if (it.canDownload != null) return !!it.canDownload;
    return String(it.status || "").toLowerCase() === "succeeded";
  }

  function setHistoryRows(items) {
    var tbody = $("amod_history_rows");
    if (!tbody) return;
    tbody.innerHTML = "";
    (items || []).forEach(function (it) {
      var tr = document.createElement("tr");
      var statusBadge = '<span class="badge bg-' + (
        it.status === 'succeeded' ? 'success' : it.status === 'failed' ? 'danger' : 'secondary'
      ) + '">' + AsyncJob.statusZh(it.status || '') + '</span>';
      var targets = (it.templateNames || []).slice(0, 3).join(", ");
      var tdOp = document.createElement("td");
      var st = String(it.status || "").toLowerCase();
      if (historyCanDownload(it)) {
        var a = document.createElement("a");
        a.className = "btn btn-sm btn-outline-primary";
        a.href = historyDownloadUrl(it);
        a.setAttribute("download", "");
        a.textContent = "下载ZIP";
        tdOp.appendChild(a);
      } else if (st === "succeeded") {
        tdOp.appendChild(document.createTextNode("成功（暂不可下载）"));
      } else {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "btn btn-sm btn-outline-secondary";
        b.textContent = "填入当前任务";
        b.addEventListener("click", function () {
          var jid = String(it.id || "").trim();
          if ($("amod_local_job_id")) $("amod_local_job_id").textContent = jid;
          var dlBtn = $("amod_btn_download");
          if (dlBtn) dlBtn.disabled = !historyCanDownload(it);
        });
        tdOp.appendChild(b);
      }
      tr.innerHTML =
        '<td class="small text-muted">' + esc(it.createdAt || '') + '</td>' +
        '<td>' + statusBadge + '</td>' +
        '<td class="small">' + esc(targets || '—') + '</td>' +
        '<td class="small text-monospace">' + esc(it.id || '') + '</td>' +
        '<td class="small text-muted">' + esc(((it.message || it.error || '') + '').slice(0, 120)) + '</td>';
      tr.appendChild(tdOp);
      tbody.appendChild(tr);
    });
  }

  function updateHistoryPager(pg) {
    _historyPage = parseInt((pg && pg.page) || _historyPage || 1, 10) || 1;
    _historyTotalPages = parseInt((pg && pg.total_pages) || 1, 10) || 1;
    var info = $("amod_history_pager_info");
    if (info) info.textContent = "第 " + _historyPage + "/" + _historyTotalPages + " 页（共 " + ((pg && pg.total) || 0) + " 条）";
    var prev = $("amod_history_prev");
    var next = $("amod_history_next");
    if (prev) prev.disabled = _historyPage <= 1;
    if (next) next.disabled = _historyPage >= _historyTotalPages;
  }

  function loadHistory() {
    var scopeQ = (window.IntegrationPrefill && window.IntegrationPrefill.integrationScopeQuery)
      ? window.IntegrationPrefill.integrationScopeQuery()
      : "scope=workflow";
    return AsyncJob.api(
      root + "/audit-modify/api/jobs?page=" + encodeURIComponent(String(_historyPage || 1)) + "&page_size=10&" + scopeQ,
      { method: "GET" }
    ).then(function (x) {
      if (x.ok && x.json && x.json.ok) {
        setHistoryRows(x.json.items || []);
        updateHistoryPager((x.json && x.json.pagination) || {});
      }
    });
  }

  function preview() {
    var rid = ($("amod_report_id").value || "").trim();
    var uid = ($("amod_upload_id") && $("amod_upload_id").value || "").trim();
    if (!rid && !uid) {
      showMsg("预览需要 report_id 或 upload_id 任一", true);
      return;
    }
    var url = root + "/audit-modify/api/preview-remediation?"
      + (rid ? "report_id=" + encodeURIComponent(rid) : "upload_id=" + encodeURIComponent(uid));
    AsyncJob.api(url, { method: "GET" }).then(function (x) {
      if (!x.ok || !x.json || !x.json.ok) {
        showMsg(((x.json && x.json.message) || "预览失败"), true);
        return;
      }
      var rem = (x.json && x.json.remediation) || {};
      var targets = (x.json && x.json.targets) || [];
      var sum = x.json.reportSummary || {};
      var imm = (x.json && x.json.immediateCount != null) ? x.json.immediateCount : targets.length;
      $("amod_preview_summary").textContent = (
        "报告 " + (sum.id || '?') + " · 文件 " + (sum.file_name || '') +
        " · 共 " + (sum.total_points || 0) + " 点（高 " + (sum.high_count || 0) +
        " 中 " + (sum.medium_count || 0) + "）· 立即修改 " + imm + " 条 · 目标文件 " + targets.length + " 个"
      );
      var box = $("amod_preview_box");
      box.classList.remove("d-none");
      var text = "";
      targets.forEach(function (t) {
        text += "═══ " + t + " ═══\n" + (rem[t] || "") + "\n\n";
      });
      box.textContent = text || "（无可注入内容）";
      var baseNm = ($("amod_base_upload_name") && $("amod_base_upload_name").textContent) || "";
      var m = baseNm.match(/->\s*(.+)$/);
      var baseFn = m ? String(m[1]).trim() : "";
      if (baseFn && !$("amod_template_file_name").value) {
        $("amod_template_file_name").value = baseFn;
      } else if (targets.length && !$("amod_template_file_name").value) {
        $("amod_template_file_name").value = targets[0];
      }
      showMsg("预览完成", false);
      fetchPostAuditDefaults();
    });
  }

  function submitJob() {
    var IP0 = window.IntegrationPrefill;
    if (IP0 && IP0.requireAicheckwordProject) {
      var chk0 = IP0.requireAicheckwordProject("amod");
      if (!chk0.ok) {
        showMsg(chk0.message, true);
        return;
      }
    }
    var payload = {
      collection: ($("amod_collection").value || "regulations").trim() || "regulations",
      organizationId: (window.IntegrationPrefill && window.IntegrationPrefill.readOrganizationId
        ? window.IntegrationPrefill.readOrganizationId("amod")
        : "") || null,
      provider: ($("amod_provider").value || "").trim() || null,
      document_language: ($("amod_document_language").value || "").trim(),
      inplace_patch: true,
      save_as_case: false,
      draft_strategy: "change",
      skip_case_template_text: !!($("amod_skip_case_template") && $("amod_skip_case_template").checked),
      docx_track_changes: !$("amod_docx_track") || $("amod_docx_track").checked,
    };
    var pid = ($("amod_project_sel") && $("amod_project_sel").value || $("amod_project_id").value || "").trim();
    if ($("amod_project_id")) $("amod_project_id").value = pid;
    if (pid) payload.project_id = parseInt(pid, 10);
    /* 审核后修改固定不读案例模板；维度由 aicheckword project_id 提供 */
    var tplName = ($("amod_template_file_name").value || "").trim();
    if (tplName) payload.template_file_names = [tplName];

    var prog = AsyncJob.progressUI({
      wrapId: "amod_progress_wrap",
      barId: "amod_progress_bar",
      textId: "amod_progress_caption",
      headlineId: "amod_progress_headline",
    });
    var btn = $("amod_btn_submit");
    var dlBtn = $("amod_btn_download");
    if (dlBtn) dlBtn.disabled = true;

    var fd = new FormData();
    fd.append("payload", JSON.stringify(payload));
    var rid = ($("amod_report_id").value || "").trim();
    var uid = ($("amod_upload_id") && $("amod_upload_id").value || "").trim();
    var rfile = ($("amod_report_file").files && $("amod_report_file").files[0]) || null;
    var bUid = ($("amod_base_upload_id") && $("amod_base_upload_id").value || "").trim();
    var bFile = ($("amod_base_files").files && $("amod_base_files").files[0]) || null;
    if (!rid && !uid && !rfile) {
      showMsg("请提供 report_id、upload_id 或 上传 report.json", true);
      return;
    }
    if (bUid && bFile) {
      showMsg("Base 来源唯一性：base_upload_id 与上传 Base 不可同时提供", true);
      return;
    }
    if (!bUid && !bFile) {
      showMsg("请提供 base_upload_id 或上传 1 个 Base 文件", true);
      return;
    }
    if (rid) fd.append("report_id", rid);
    if (uid) fd.append("upload_id", uid);
    if (rfile) fd.append("report_json_file", rfile, rfile.name);
    if (bUid) fd.append("base_upload_id", bUid);
    if (bFile) fd.append("base_files", bFile, bFile.name);
    if (window.IntegrationPrefill && window.IntegrationPrefill.appendIntegrationScope) {
      window.IntegrationPrefill.appendIntegrationScope(fd);
    }

    if (btn) btn.disabled = true;
    showMsg("正在提交…", false);
    prog.show(); prog.setRunning(true); prog.setHeadline("提交中…");
    prog.update(0.03, "正在上传文件…");

    var submitController = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var submitTimer = null;
    if (submitController) {
      submitTimer = setTimeout(function () {
        try { submitController.abort(); } catch (_) {}
      }, 95000);
    }
    fetch(root + "/audit-modify/api/jobs", {
      method: "POST",
      body: fd,
      credentials: "same-origin",
      signal: submitController ? submitController.signal : undefined,
    })
      .then(function (r) {
        return r.text().then(function (txt) {
          var j = null;
          try { j = txt ? JSON.parse(txt) : null; } catch (_) {}
          return { ok: r.ok, status: r.status, json: j, raw: txt };
        });
      })
      .then(function (x) {
        if (submitTimer) {
          clearTimeout(submitTimer);
          submitTimer = null;
        }
        if (!x.ok || !x.json || !x.json.ok) {
          var em = (x.json && (x.json.message || x.json.detail)) || ("提交失败（HTTP " + (x.status || "?") + "）");
          showMsg(em, true);
          prog.setRunning(false); prog.setTerminal(false); prog.update(0, em);
          if (btn) btn.disabled = false;
          return;
        }
        var localId = x.json.localJobId;
        $("amod_local_job_id").textContent = localId;
        showMsg("已提交，任务号 " + localId + "，轮询中…", false);
        prog.setHeadline("轮询中（共用初稿 job）…");
        AsyncJob.pollJob(
          root + "/audit-modify/api/jobs/" + encodeURIComponent(localId) + "/status",
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
                return;
              }
              var st = AsyncJob.normalizeJobStatus(finalJson && finalJson.status);
              if (st === "succeeded") {
                prog.setHeadline("修改已完成");
                prog.setTerminal(true);
                prog.update(1, "修改完成，可下载 ZIP");
                showMsg("修改完成", false);
                if (dlBtn) dlBtn.disabled = false;
                var res = finalJson && finalJson.result;
                if (res && res.audit_point_coverage_by_target) {
                  renderAuditCoverage(res.audit_point_coverage_by_target);
                }
              } else {
                prog.setHeadline("修改失败");
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
        if (submitTimer) {
          clearTimeout(submitTimer);
          submitTimer = null;
        }
        if (btn) btn.disabled = false;
        prog.setRunning(false); prog.setTerminal(false);
        var isAbort = !!(e && (e.name === "AbortError" || /aborted|abort/i.test(String(e.message || ""))));
        var msg = isAbort
          ? "提交超时（95秒）：上游未及时返回，可在历史记录里刷新查看是否已创建任务。"
          : String((e && e.message) || e || "提交异常");
        showMsg(msg, true);
      });
  }

  function downloadJob() {
    var jid = ($("amod_local_job_id").textContent || "").trim();
    if (!jid || jid === "—") return;
    window.location.href = root + "/audit-modify/api/jobs/" + encodeURIComponent(jid) + "/download";
  }

  function init() {
    if (!window.IntegrationPrefill || !$("amod_report_id")) return Promise.resolve();
    var IP = window.IntegrationPrefill;
    var q = parseQuery();
    var pf = IP.parsePrefillFromLocation();
    if (q.upload_id && $("amod_upload_id")) $("amod_upload_id").value = String(q.upload_id);
    if (q.report_id) $("amod_report_id").value = String(q.report_id);
    if (q.base_upload_id && $("amod_base_upload_id")) $("amod_base_upload_id").value = String(q.base_upload_id);
    if (q.template_file_name) $("amod_template_file_name").value = String(q.template_file_name);
    if (!pf && (q.upload_id || q.from === "page2")) {
      pf = {
        fromPage2: true,
        upload_id: String(q.upload_id || ""),
        file_name: String(q.file_name || q.template_file_name || ""),
        project_name: String(q.project_name || ""),
        product: String(q.product || ""),
        country: String(q.country || ""),
        collection: String(q.collection || ""),
        aicheckword_project_id: q.aicheckword_project_id ? parseInt(q.aicheckword_project_id, 10) : null,
      };
    }
    resolveUploadName(($("amod_upload_id") && $("amod_upload_id").value) || "", "amod_upload_name");
    resolveUploadName(($("amod_base_upload_id") && $("amod_base_upload_id").value) || "", "amod_base_upload_name");

    function applyPostAuditMeta(meta) {
      if (!meta) return;
      var map = {
        document_language: "amod_document_language",
        registration_country: "amod_registration_country",
        registration_type: "amod_registration_type",
        registration_component: "amod_registration_component",
        project_form: "amod_project_form",
      };
      Object.keys(map).forEach(function (mk) {
        var v = String(meta[mk] || "").trim();
        if (!v) return;
        IP.setSelectValue(map[mk], v);
      });
      if (meta.project_id && $("amod_project_sel")) {
        IP.setSelectValue("amod_project_sel", String(meta.project_id));
        if ($("amod_project_id")) $("amod_project_id").value = String(meta.project_id);
      }
    }

    function fetchPostAuditDefaults() {
      var rid = ($("amod_report_id").value || "").trim();
      var uid = ($("amod_upload_id") && $("amod_upload_id").value || "").trim();
      var pid = ($("amod_project_id").value || $("amod_project_sel").value || "").trim();
      if (!rid && !uid) return Promise.resolve();
      var url = root + "/audit-modify/api/post-audit-defaults?";
      if (rid) url += "report_id=" + encodeURIComponent(rid);
      else if (uid) url += "upload_id=" + encodeURIComponent(uid);
      else return Promise.resolve();
      if (pid) url += "&project_id=" + encodeURIComponent(pid);
      return AsyncJob.api(url, { method: "GET" }).then(function (x) {
        if (x.ok && x.json && x.json.ok) applyPostAuditMeta(x.json.meta);
      });
    }

    function loadPage0LatestReportIfNeeded() {
      if (IP.integrationScopeFromLocation() !== "page0") return Promise.resolve();
      if (($("amod_report_id").value || "").trim()) return Promise.resolve();
      var scopeQ = IP.integrationScopeQuery ? IP.integrationScopeQuery() : "scope=page0";
      return AsyncJob.api(root + "/audit-modify/api/latest-audit-report?" + scopeQ, { method: "GET" })
        .then(function (x) {
          if (!x.ok || !x.json || !x.json.ok || !x.json.reportId) return;
          $("amod_report_id").value = String(x.json.reportId);
        });
    }

    var amodBootstrapOpts = {
      prefix: "amod",
      root: root,
      bootstrapUrl: root + "/audit-modify/api/integration-bootstrap",
      uploadPrefillBase: root + "/audit-modify",
      prefill: pf,
      withCases: false,
      onError: function (m) { showMsg(m, true); },
      onReady: function () {
        if (q.template_file_name && !$("amod_template_file_name").value) {
          $("amod_template_file_name").value = String(q.template_file_name);
        } else if (pf && pf.file_name && !$("amod_template_file_name").value) {
          $("amod_template_file_name").value = pf.file_name;
        }
        var rid = ($("amod_report_id").value || "").trim();
        var uid = ($("amod_upload_id") && $("amod_upload_id").value || "").trim();
        if (rid || uid) fetchPostAuditDefaults();
      },
    };
    var bootstrapPromise = loadPage0LatestReportIfNeeded().then(function () {
      return IP.loadBootstrap(amodBootstrapOpts);
    });

    IP.wireProjectSelect("amod", function () { return window.__integrationBootstrap_amod; }, function () {
      return IP.getPagePrefill("amod") || IP.parsePrefillFromLocation();
    });
    IP.wireCaseSelect("amod", function () { return window.__integrationBootstrap_amod; }, function () {
      return IP.getPagePrefill("amod") || IP.parsePrefillFromLocation();
    });

    var pBtn = $("amod_btn_preview");
    if (pBtn) pBtn.addEventListener("click", preview);
    var sBtn = $("amod_btn_submit");
    if (sBtn) sBtn.addEventListener("click", submitJob);
    var dBtn = $("amod_btn_download");
    if (dBtn) dBtn.addEventListener("click", downloadJob);
    var uid = $("amod_upload_id");
    if (uid) {
      uid.addEventListener("blur", function () {
        resolveUploadName(uid.value, "amod_upload_name");
        IP.rematchProjectFromTask("amod", amodBootstrapOpts);
      });
    }
    var buid = $("amod_base_upload_id");
    if (buid) {
      buid.addEventListener("blur", function () {
        resolveUploadName(buid.value, "amod_base_upload_name");
        IP.rematchProjectFromTask("amod", amodBootstrapOpts);
      });
    }
    var orgSel = $("amod_organization");
    if (orgSel) {
      orgSel.addEventListener("change", function () {
        IP.loadBootstrap(Object.assign({}, amodBootstrapOpts, {
          prefill: IP.getPagePrefill("amod") || IP.parsePrefillFromLocation(),
        }));
      });
    }
    var hPrev = $("amod_history_prev");
    if (hPrev) hPrev.addEventListener("click", function () {
      if (_historyPage <= 1) return;
      _historyPage -= 1;
      loadHistory();
    });
    var hNext = $("amod_history_next");
    if (hNext) hNext.addEventListener("click", function () {
      if (_historyPage >= _historyTotalPages) return;
      _historyPage += 1;
      loadHistory();
    });

    // 自动预览：若 URL 带 upload_id，默认预览一次
    if (q.upload_id || q.report_id) {
      setTimeout(preview, 200);
    }
    return Promise.all([bootstrapPromise, loadHistory()]);
  }

  function runInit() {
    return init();
  }

  if (typeof registerPageInit === "function") {
    registerPageInit(runInit);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", runInit);
  } else {
    runInit();
  }
})();
