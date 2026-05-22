/**
 * /translate/ 页面前端：提交 → 轮询 → 下载 ZIP。
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

  function showMsg(t, e) { AsyncJob.showMsg("tr_msg", t, e); }

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
      root + "/translate/api/upload-name?upload_id=" + encodeURIComponent(String(uploadId || "").trim()),
      { method: "GET" }
    ).then(function (x) {
      if (!x.ok || !x.json || !x.json.ok) return "";
      return String((x.json && x.json.fileName) || "");
    }).catch(function () { return ""; });
  }

  function renderUploadNames() {
    var box = $("tr_upload_names");
    if (!box) return;
    var ids = parseUploadIdsText($("tr_upload_ids") && $("tr_upload_ids").value);
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

  var trBootstrapOpts = null;

  function loadMeta() {
    if (!window.IntegrationPrefill) return;
    var IP = window.IntegrationPrefill;
    var pf = IP.parsePrefillFromLocation();
    trBootstrapOpts = {
      prefix: "tr",
      root: root,
      bootstrapUrl: root + "/translate/api/integration-bootstrap",
      uploadPrefillBase: root + "/translate",
      prefill: pf,
      withCases: false,
      onBootstrap: function (b) {
        var target = String(b.targetLangDefault || "").trim();
        if (target && $("tr_target_lang")) $("tr_target_lang").value = target;
        window.__trCompanyConfig = b.companyConfig || {};
        IP.applyCompanyConfig("tr", window.__trCompanyConfig, true);
      },
      onError: function (m) { showMsg(m, true); },
    };
    IP.loadBootstrap(trBootstrapOpts);
    IP.wireProjectSelect("tr", function () { return window.__integrationBootstrap_tr; }, function () {
      return IP.getPagePrefill("tr") || IP.parsePrefillFromLocation();
    });
  }

  function historyDownloadUrl(it) {
    if (!it || !it.id) return "";
    var src = String(it.source || "");
    if (src.indexOf("correct") >= 0) {
      return root + "/translate/api/correct/jobs/" + encodeURIComponent(it.id) + "/download";
    }
    return root + "/translate/api/jobs/" + encodeURIComponent(it.id) + "/download";
  }

  function historyCanDownload(it) {
    if (!it) return false;
    if (it.canDownload != null) return !!it.canDownload;
    return String(it.status || "").toLowerCase() === "succeeded";
  }

  function setHistoryRows(items) {
    var tbody = $("tr_history_rows");
    if (!tbody) return;
    tbody.innerHTML = "";
    (items || []).forEach(function (it) {
      var tr = document.createElement("tr");
      var statusBadge = '<span class="badge bg-' + (
        it.status === 'succeeded' ? 'success' : it.status === 'failed' ? 'danger' : 'secondary'
      ) + '">' + AsyncJob.statusZh(it.status || '') + '</span>';
      var outFiles = (it.outFiles || []).slice(0, 3).join(', ');
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
          if ($("tr_local_job_id")) $("tr_local_job_id").textContent = jid;
          var dlBtn = $("tr_btn_download");
          if (dlBtn) dlBtn.disabled = !historyCanDownload(it);
        });
        tdOp.appendChild(b);
      }
      tr.innerHTML =
        '<td class="small text-muted">' + esc(it.createdAt || '') + '</td>' +
        '<td>' + esc(it.targetLang || '') + '</td>' +
        '<td>' + statusBadge + '</td>' +
        '<td class="small text-monospace">' + esc(it.id || '') + '</td>' +
        '<td class="small">' + esc(outFiles || '—') + '</td>' +
        '<td class="small text-muted">' + esc(((it.message || it.error || '') + '').slice(0, 120)) + '</td>';
      tr.appendChild(tdOp);
      tbody.appendChild(tr);
    });
  }

  function updateHistoryPager(pg) {
    _historyPage = parseInt((pg && pg.page) || _historyPage || 1, 10) || 1;
    _historyTotalPages = parseInt((pg && pg.total_pages) || 1, 10) || 1;
    var info = $("tr_history_pager_info");
    if (info) info.textContent = "第 " + _historyPage + "/" + _historyTotalPages + " 页（共 " + ((pg && pg.total) || 0) + " 条）";
    var prev = $("tr_history_prev");
    var next = $("tr_history_next");
    if (prev) prev.disabled = _historyPage <= 1;
    if (next) next.disabled = _historyPage >= _historyTotalPages;
  }

  function loadHistory() {
    AsyncJob.api(
      root + "/translate/api/jobs?page=" + encodeURIComponent(String(_historyPage || 1)) + "&page_size=10",
      { method: "GET" }
    ).then(function (x) {
      if (x.ok && x.json && x.json.ok) {
        setHistoryRows(x.json.items || []);
        updateHistoryPager((x.json && x.json.pagination) || {});
      }
    });
  }

  function _buildKbQueryExtra(pid) {
    var n = parseInt(String(pid || "").trim(), 10);
    if (!n || isNaN(n)) return Promise.resolve("");
    var q = "project_id=" + encodeURIComponent(String(n));
    ["registration_country", "registration_type", "registration_component", "project_form"].forEach(function (k) {
      var el = $("tr_" + k);
      var v = el ? String(el.value || "").trim() : "";
      if (v) q += "&" + k + "=" + encodeURIComponent(v);
    });
    return AsyncJob.api(root + "/translate/api/kb-query-extra?" + q, { method: "GET" })
      .then(function (x) {
        if (x.ok && x.json && x.json.ok) return String(x.json.kbQueryExtra || "");
        return "";
      })
      .catch(function () { return ""; });
  }

  function buildPayload() {
    var pid = ($("tr_project_sel") && $("tr_project_sel").value || $("tr_project_id").value || "").trim();
    if ($("tr_project_id")) $("tr_project_id").value = pid;
    return _buildKbQueryExtra(pid).then(function (kb) {
      var payload = {
        target_lang: ($("tr_target_lang").value || "en").trim() || "en",
        collection: ($("tr_collection").value || "regulations").trim() || "regulations",
        provider: ($("tr_provider").value || "").trim() || null,
        use_kb: ($("tr_use_kb").value || "true") === "true",
      };
      var co = window.IntegrationPrefill
        ? window.IntegrationPrefill.readCompanyOverrides("tr")
        : null;
      if (co) payload.company_overrides = co;
      if (kb) payload.kb_query_extra = kb;
      return payload;
    });
  }

  function buildCorrectionPayload() {
    return buildPayload().then(function (payload) {
      payload.save_glossary = !!($("tr_save_glossary") && $("tr_save_glossary").checked);
      var IP = window.IntegrationPrefill;
      var rules = IP ? IP.parseManualRulesText($("tr_manual_rules") && $("tr_manual_rules").value) : [];
      if (rules.length) payload.manual_rules = rules;
      return payload;
    });
  }

  function submitJob() {
    var IP = window.IntegrationPrefill;
    if (IP && IP.requireAicheckwordProject) {
      var chk = IP.requireAicheckwordProject("tr");
      if (!chk.ok) {
        showMsg(chk.message, true);
        return;
      }
    }
    var prog = AsyncJob.progressUI({
      wrapId: "tr_progress_wrap",
      barId: "tr_progress_bar",
      textId: "tr_progress_caption",
      headlineId: "tr_progress_headline",
    });
    var btn = $("tr_btn_submit");
    var dlBtn = $("tr_btn_download");
    if (dlBtn) dlBtn.disabled = true;

    var uploadIdsTxt = ($("tr_upload_ids").value || "").trim();
    var pickedFiles = ($("tr_files_picker").files || []);
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
    var fileCount = hasTask
      ? uploadIdsTxt.split(/[\n,]+/).map(function (s) { return s.trim(); }).filter(Boolean).length
      : pickedFiles.length;
    if (fileCount > 5) {
      showMsg("单次最多 5 个文件，当前 " + fileCount + " 个", true);
      return;
    }

    buildPayload().then(function (payload) {
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

    return fetch(root + "/translate/api/jobs", { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, json: j }; }); })
      .then(function (x) {
        if (!x.ok || !x.json || !x.json.ok) {
          var em = (x.json && (x.json.message || x.json.detail)) || "提交失败";
          showMsg(em, true);
          prog.setRunning(false); prog.setTerminal(false); prog.update(0, em);
          if (btn) btn.disabled = false;
          return;
        }
        var localId = x.json.localJobId;
        $("tr_local_job_id").textContent = localId;
        var note = (x.json.providerNote || x.json.provider_note || "").trim();
        showMsg(
          "已提交，任务号 " + localId + "，轮询中…" + (note ? "（" + note + "）" : ""),
          false
        );
        prog.setHeadline("轮询中…");
        AsyncJob.pollJob(
          root + "/translate/api/jobs/" + encodeURIComponent(localId) + "/status",
          {
            onUpdate: function (u) { prog.update(u.progress || 0, u.message || ""); },
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
                prog.setHeadline("翻译已完成");
                prog.setTerminal(true);
                prog.update(1, "翻译完成，可下载 ZIP");
                var warns = (((finalJson || {}).result || {}).residual_cjk_warnings) || [];
                if (Array.isArray(warns) && warns.length) {
                  var total = 0;
                  for (var wi = 0; wi < warns.length; wi++) {
                    total += parseInt((warns[wi] && warns[wi].count) || 0, 10) || 0;
                  }
                  showMsg(
                    "翻译完成，但检测到残留中文片段（文件 " + warns.length + " 个，片段约 " + total + " 处），建议执行“翻译校正”复核。",
                    true
                  );
                } else {
                  showMsg("翻译完成", false);
                }
                if (dlBtn) dlBtn.disabled = false;
              } else {
                prog.setHeadline("翻译失败");
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
    }).catch(function (e) {
      showMsg(String((e && e.message) || e || "构建参数失败"), true);
    });
  }

  function submitCorrectionJob() {
    var IP0 = window.IntegrationPrefill;
    if (IP0 && IP0.requireAicheckwordProject) {
      var chk0 = IP0.requireAicheckwordProject("tr");
      if (!chk0.ok) {
        showMsg(chk0.message, true);
        return;
      }
    }
    var prog = AsyncJob.progressUI({
      wrapId: "tr_progress_wrap",
      barId: "tr_progress_bar",
      textId: "tr_progress_caption",
      headlineId: "tr_progress_headline",
    });
    var btn = $("tr_btn_correct");
    var dlBtn = $("tr_btn_download");
    if (dlBtn) dlBtn.disabled = true;

    var uploadIdsTxt = ($("tr_upload_ids").value || "").trim();
    var pickedFiles = ($("tr_files_picker").files || []);
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
    var fileCount = hasTask
      ? uploadIdsTxt.split(/[\n,]+/).map(function (s) { return s.trim(); }).filter(Boolean).length
      : pickedFiles.length;
    if (fileCount > 10) {
      showMsg("翻译校正单次最多 10 个文件，当前 " + fileCount + " 个", true);
      return;
    }

    buildCorrectionPayload().then(function (payload) {
    var fd = new FormData();
    fd.append("payload", JSON.stringify(payload));
    if (hasTask) fd.append("upload_ids", uploadIdsTxt);
    if (hasManual) {
      for (var i = 0; i < pickedFiles.length; i++) {
        fd.append("input_files", pickedFiles[i], pickedFiles[i].name);
      }
    }

    if (btn) btn.disabled = true;
    showMsg("正在提交翻译校正…", false);
    prog.show(); prog.setRunning(true); prog.setHeadline("提交中…");
    prog.update(0.03, "正在上传文件…");

    return fetch(root + "/translate/api/correct/jobs", { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, json: j }; }); })
      .then(function (x) {
        if (!x.ok || !x.json || !x.json.ok) {
          var em = (x.json && (x.json.message || x.json.detail)) || "提交失败";
          showMsg(em, true);
          prog.setRunning(false); prog.setTerminal(false); prog.update(0, em);
          if (btn) btn.disabled = false;
          return;
        }
        var localId = x.json.localJobId;
        $("tr_local_job_id").textContent = localId;
        showMsg("已提交翻译校正，任务号 " + localId + "，轮询中…", false);
        prog.setHeadline("轮询中…");
        AsyncJob.pollJob(
          root + "/translate/api/correct/jobs/" + encodeURIComponent(localId) + "/status",
          {
            onUpdate: function (u) { prog.update(u.progress || 0, u.message || ""); },
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
                prog.setHeadline("校正已完成");
                prog.setTerminal(true);
                prog.update(1, "翻译校正完成，可下载 ZIP");
                var warns = (((finalJson || {}).result || {}).residual_cjk_warnings) || [];
                if (Array.isArray(warns) && warns.length) {
                  var total = 0;
                  for (var wi = 0; wi < warns.length; wi++) {
                    total += parseInt((warns[wi] && warns[wi].count) || 0, 10) || 0;
                  }
                  showMsg(
                    "翻译校正完成，但仍检测到残留中文片段（文件 " + warns.length + " 个，片段约 " + total + " 处）。",
                    true
                  );
                } else {
                  showMsg("翻译校正完成", false);
                }
                if (dlBtn) dlBtn.disabled = false;
              } else {
                prog.setHeadline("校正失败");
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
    }).catch(function (e) {
      showMsg(String((e && e.message) || e || "构建参数失败"), true);
    });
  }

  function downloadJob() {
    var jid = ($("tr_local_job_id").textContent || "").trim();
    if (!jid || jid === "—") return;
    AsyncJob.api(
      root + "/translate/api/jobs?page=1&page_size=50",
      { method: "GET" }
    ).then(function (x) {
      var hit = null;
      if (x.ok && x.json && x.json.ok) {
        var rows = Array.isArray(x.json.items) ? x.json.items : [];
        for (var i = 0; i < rows.length; i++) {
          if (String(rows[i].id || "") === jid) { hit = rows[i]; break; }
        }
      }
      window.location.href = hit ? historyDownloadUrl(hit) : (
        root + "/translate/api/jobs/" + encodeURIComponent(jid) + "/download"
      );
    }).catch(function () {
      window.location.href = root + "/translate/api/jobs/" + encodeURIComponent(jid) + "/download";
    });
  }

  function init() {
    var q = parseQuery();
    if (q.upload_ids) {
      var lst = String(q.upload_ids).split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      $("tr_upload_ids").value = lst.join("\n");
      renderUploadNames();
    }
    if (q.upload_id) $("tr_upload_ids").value = String(q.upload_id);
    if (q.upload_id) renderUploadNames();
    if (q.target_lang && ["en", "de", "zh"].indexOf(q.target_lang) >= 0) $("tr_target_lang").value = q.target_lang;

    var picker = $("tr_files_picker");
    if (picker) {
      picker.addEventListener("change", function () {
        var n = (picker.files || []).length;
        $("tr_files_count").textContent = n ? "已选 " + n + " 个文件" : "未选择";
      });
    }

    var sBtn = $("tr_btn_submit");
    if (sBtn) sBtn.addEventListener("click", submitJob);
    var cBtn = $("tr_btn_correct");
    if (cBtn) cBtn.addEventListener("click", submitCorrectionJob);
    var upl = $("tr_upload_ids");
    if (upl) {
      upl.addEventListener("blur", function () {
        renderUploadNames();
        if (window.IntegrationPrefill && trBootstrapOpts) {
          window.IntegrationPrefill.rematchProjectFromTask("tr", trBootstrapOpts);
        }
      });
    }
    var coll = $("tr_collection");
    if (coll) {
      coll.addEventListener("change", function () {
        if (window.IntegrationPrefill && trBootstrapOpts) {
          trBootstrapOpts.prefill = window.IntegrationPrefill.getPagePrefill("tr")
            || window.IntegrationPrefill.parsePrefillFromLocation();
          loadMeta();
        } else {
          loadMeta();
        }
      });
    }
    var btnCo = $("tr_btn_load_company_default");
    if (btnCo) {
      btnCo.addEventListener("click", function () {
        if (window.IntegrationPrefill) {
          window.IntegrationPrefill.applyCompanyConfig("tr", window.__trCompanyConfig || {});
        }
      });
    }
    var dBtn = $("tr_btn_download");
    if (dBtn) dBtn.addEventListener("click", downloadJob);
    var hPrev = $("tr_history_prev");
    if (hPrev) hPrev.addEventListener("click", function () {
      if (_historyPage <= 1) return;
      _historyPage -= 1;
      loadHistory();
    });
    var hNext = $("tr_history_next");
    if (hNext) hNext.addEventListener("click", function () {
      if (_historyPage >= _historyTotalPages) return;
      _historyPage += 1;
      loadHistory();
    });

    loadMeta();
    loadHistory();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
