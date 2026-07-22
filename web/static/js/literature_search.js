(function () {
  const state = {
    batches: [],
    captchaSessionId: "",
    pendingBatchId: "",
    lastSearchPayload: null,
  };

  const el = {
    query: document.getElementById("litQuery"),
    sources: Array.from(document.querySelectorAll(".lit-source")),
    startYear: document.getElementById("litStartYear"),
    endYear: document.getElementById("litEndYear"),
    maxPerSource: document.getElementById("litMaxPerSource"),
    scholarSort: document.getElementById("litScholarSort"),
    searchBtn: document.getElementById("litSearchBtn"),
    clearBatchesBtn: document.getElementById("litClearBatchesBtn"),
    importSource: document.getElementById("litImportSource"),
    importFile: document.getElementById("litImportFile"),
    importBtn: document.getElementById("litImportBtn"),
    importCard: document.getElementById("litImportCard"),
    status: document.getElementById("litStatus"),
    batchList: document.getElementById("litBatchList"),
    countBadge: document.getElementById("litCountBadge"),
    captchaModal: document.getElementById("litCaptchaModal"),
    captchaFrame: document.getElementById("litCaptchaFrame"),
    captchaOpenTab: document.getElementById("litCaptchaOpenTab"),
    captchaContinueBtn: document.getElementById("litCaptchaContinueBtn"),
    captchaProgress: document.getElementById("litCaptchaProgress"),
    detailModal: document.getElementById("litDetailModal"),
    detailBody: document.getElementById("litDetailBody"),
  };

  if (!el.query || !el.searchBtn || !el.batchList) {
    return;
  }

  function selectedSources() {
    return el.sources.filter((x) => x.checked).map((x) => x.value);
  }

  function setStatus(text, level) {
    el.status.className = "small mt-2";
    if (level === "error") el.status.classList.add("text-danger");
    if (level === "ok") el.status.classList.add("text-success");
    if (level === "warn") el.status.classList.add("text-warning");
    el.status.textContent = text || "";
  }

  function setBusy(btn, busy, textBusy) {
    if (!btn) return;
    if (!btn.dataset.label) btn.dataset.label = btn.textContent || "";
    btn.disabled = !!busy;
    btn.setAttribute("aria-busy", busy ? "true" : "false");
    btn.textContent = busy ? textBusy : btn.dataset.label;
  }

  function escapeHtml(v) {
    return String(v || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function nowLabel() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  function totalRecordCount() {
    return state.batches.reduce((sum, b) => sum + (Array.isArray(b.records) ? b.records.length : 0), 0);
  }

  function findBatch(id) {
    return state.batches.find((b) => b.id === id) || null;
  }

  function fromServerBatch(b) {
    return {
      id: b.id,
      type: b.type || "search",
      typeLabel: b.typeLabel || (b.type === "import" ? "导入" : "检索"),
      createdAt: b.createdAt || nowLabel(),
      records: Array.isArray(b.records) ? b.records : [],
      details: Array.isArray(b.details) ? b.details : [],
      summary: b.summary || "",
      statusNote: b.statusNote || "",
      query: b.query || "",
      sources: Array.isArray(b.sources) ? b.sources : [],
      persisted: true,
    };
  }

  function upsertBatch(batch) {
    const idx = state.batches.findIndex((b) => b.id === batch.id);
    if (idx >= 0) state.batches[idx] = batch;
    else state.batches.unshift(batch);
    renderBatches();
  }

  function removeBatchLocal(id) {
    state.batches = state.batches.filter((b) => b.id !== id);
    if (state.pendingBatchId === id) state.pendingBatchId = "";
    renderBatches();
  }

  function dbLabel(rec) {
    return (
      rec.database ||
      ({ pubmed: "PUBMED", scholar: "Google", embase: "EMBASE", cochrane: "Cochrane" }[rec.source] ||
        rec.source ||
        "")
    );
  }

  function citationOf(rec) {
    if (rec.citation) return String(rec.citation);
    const bits = [rec.authors, rec.title, rec.source_info].filter(Boolean);
    return bits.join(". ");
  }

  function showDetail(batchId, index) {
    const batch = findBatch(batchId);
    const rec = batch && Array.isArray(batch.records) ? batch.records[index] : null;
    if (!rec || !el.detailBody) return;
    const rows = [
      ["Database", dbLabel(rec)],
      ["Item", `[${index + 1}]`],
      ["Literature", citationOf(rec)],
      ["Title", rec.title],
      ["Authors", rec.authors],
      ["Journal", rec.journal],
      ["Year / Date", rec.pub_date || rec.year],
      ["Volume/Issue/Pages", rec.volume_issue_pages],
      ["DOI", rec.doi],
      ["PMID", rec.pmid],
      ["Source", rec.source],
      ["Link", rec.source_url],
    ];
    el.detailBody.innerHTML = rows
      .map(([k, v]) => {
        const val = String(v || "").trim();
        if (!val) return "";
        if (k === "Link") {
          return `<div class="mb-2"><div class="text-muted small">${escapeHtml(k)}</div><a href="${escapeHtml(val)}" target="_blank" rel="noopener">${escapeHtml(val)}</a></div>`;
        }
        if (k === "Literature") {
          return `<div class="mb-2"><div class="text-muted small">${escapeHtml(k)}</div><div style="white-space:pre-wrap;">${escapeHtml(val)}</div></div>`;
        }
        return `<div class="mb-2"><div class="text-muted small">${escapeHtml(k)}</div><div>${escapeHtml(val)}</div></div>`;
      })
      .join("");
    const modal =
      window.bootstrap && bootstrap.Modal ? bootstrap.Modal.getOrCreateInstance(el.detailModal) : null;
    if (modal) modal.show();
  }

  function renderBatches() {
    const batchCount = state.batches.length;
    const recCount = totalRecordCount();
    el.countBadge.textContent = `${batchCount} 批 / ${recCount} 条`;
    if (!batchCount) {
      el.batchList.innerHTML =
        '<div class="text-muted text-center py-4 border rounded">暂无批次。请先检索或导入。</div>';
      return;
    }
    el.batchList.innerHTML = state.batches
      .map((b, i) => {
        const no = batchCount - i;
        const counters = {};
        const rows = (b.records || [])
          .map((r, ri) => {
            const db = dbLabel(r);
            counters[db] = (counters[db] || 0) + 1;
            const cite = citationOf(r);
            const link = r.source_url
              ? `<a href="${escapeHtml(r.source_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">打开</a>`
              : '<span class="text-muted">—</span>';
            return `<tr class="lit-row" data-batch-id="${escapeHtml(b.id)}" data-index="${ri}" style="cursor:pointer;" title="点击查看完整详情">
              <td class="text-nowrap">${escapeHtml(db)}</td>
              <td class="text-nowrap">[${counters[db]}]</td>
              <td style="white-space:pre-wrap; min-width:420px; max-width:720px;">${escapeHtml(cite)}</td>
              <td class="text-nowrap">${link}</td>
              <td class="text-nowrap"><button type="button" class="btn btn-sm btn-link p-0 lit-detail-btn" data-batch-id="${escapeHtml(b.id)}" data-index="${ri}">详情</button></td>
            </tr>`;
          })
          .join("");
        const body =
          (b.records || []).length > 0
            ? `<div class="table-responsive" style="max-height:55vh;">
                <table class="table table-sm table-hover mb-0 align-middle">
                  <thead class="table-light sticky-top">
                    <tr>
                      <th>Database</th>
                      <th>Item</th>
                      <th>Literature</th>
                      <th>Link</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>${rows}</tbody>
                </table>
              </div>`
            : `<div class="p-3 text-muted small">${escapeHtml(b.statusNote || "本批次暂无记录")}</div>`;
        return `<div class="card mb-3" data-batch-id="${escapeHtml(b.id)}">
          <div class="card-header d-flex justify-content-between align-items-start flex-wrap gap-2">
            <div>
              <div class="fw-semibold">批次 #${no} · ${escapeHtml(b.typeLabel)} · ${escapeHtml(b.createdAt)}${b.persisted ? "" : " · 未落库"}</div>
              <div class="small text-muted mt-1">${escapeHtml(b.summary || "")}</div>
              ${b.statusNote ? `<div class="small text-warning mt-1">${escapeHtml(b.statusNote)}</div>` : ""}
            </div>
            <div class="d-flex gap-2 align-items-center flex-wrap">
              <span class="badge text-bg-secondary">${(b.records || []).length} 条</span>
              <button type="button" class="btn btn-sm btn-outline-success lit-export-batch" data-batch-id="${escapeHtml(b.id)}" data-format="docx" ${(b.records || []).length ? "" : "disabled"}>导出 Word</button>
              <button type="button" class="btn btn-sm btn-outline-success lit-export-batch" data-batch-id="${escapeHtml(b.id)}" data-format="xlsx" ${(b.records || []).length ? "" : "disabled"}>导出 Excel</button>
              <button type="button" class="btn btn-sm btn-outline-danger lit-remove-batch" data-batch-id="${escapeHtml(b.id)}">删除</button>
            </div>
          </div>
          <div class="card-body p-0">${body}</div>
        </div>`;
      })
      .join("");
  }

  function openCaptchaModal(sessionId, progress) {
    state.captchaSessionId = sessionId || "";
    if (!state.captchaSessionId || !el.captchaModal) {
      setStatus("需要人机验证，但未获得验证会话，请稍后重试或改用导入。", "error");
      return;
    }
    const url = `/literature/api/scholar-captcha/${encodeURIComponent(state.captchaSessionId)}`;
    if (el.captchaFrame) el.captchaFrame.src = url;
    if (el.captchaOpenTab) el.captchaOpenTab.href = url;

    const p = progress || {};
    const fetched = Number(p.fetched || 0);
    const target = Number(p.target || 0);
    const totalFound = Number(p.totalFound || 0);
    let progressText = "";
    if (fetched || target || totalFound) {
      const parts = [`已抓 ${fetched} 条`];
      if (target) parts.push(`目标 ${target} 条`);
      if (totalFound) parts.push(`Scholar 估计约 ${totalFound} 条`);
      progressText = parts.join(" / ");
      if (fetched) progressText += `。验证完成后点「继续检索」将从第 ${fetched + 1} 条续抓。`;
    }
    if (el.captchaProgress) el.captchaProgress.textContent = progressText;
    if (el.captchaContinueBtn) {
      const label = fetched
        ? `验证完成，继续检索（续抓第 ${fetched + 1} 条起）`
        : "验证完成，继续检索";
      el.captchaContinueBtn.textContent = label;
      // 同步 setBusy 缓存，避免恢复时被旧文案覆盖
      el.captchaContinueBtn.dataset.label = label;
    }

    const modal =
      window.bootstrap && bootstrap.Modal ? bootstrap.Modal.getOrCreateInstance(el.captchaModal) : null;
    if (modal) modal.show();
    else window.open(url, "_blank", "noopener");
    setStatus(
      `请在弹窗中完成 Google 人机验证，然后点击「继续检索」。${progressText ? " " + progressText : ""}`,
      "warn"
    );
  }

  function applySearchResult(data, payload, batchId) {
    state.lastDetails = Array.isArray(data.details) ? data.details : [];
    const hasErr = state.lastDetails.some((d) => d && d.error);
    const rateLimited = state.lastDetails.some(
      (d) => d && d.error && /429|限流|人机验证|too many requests|\/sorry\//i.test(String(d.error))
    );
    const detailMsg = state.lastDetails
      .map((d) => {
        const fetched =
          typeof d.fetched === "number"
            ? d.fetched
            : Array.isArray(d.records)
              ? d.records.length
              : 0;
        const total = d.totalFound || 0;
        if (d.error) {
          return total ? `${d.source}: ${fetched}/${total}，${d.error}` : `${d.source}: ${d.error}`;
        }
        return total ? `${d.source}: ${fetched}/${total}` : `${d.source}: ${fetched} 条`;
      })
      .join(" | ");

    let batch;
    if (data.batch && data.batch.id) {
      batch = fromServerBatch(data.batch);
      // 保持前端 pending 用同一 id
      if (batchId && batch.id !== batchId) {
        removeBatchLocal(batchId);
      }
    } else {
      batch = findBatch(batchId) || {
        id: batchId,
        type: "search",
        typeLabel: "检索",
        createdAt: nowLabel(),
      };
      batch.records = Array.isArray(data.records) ? data.records : [];
      batch.details = state.lastDetails;
      batch.summary = data.batch && data.batch.summary ? data.batch.summary : batch.summary || "";
      batch.statusNote = detailMsg || "";
      batch.query = payload.query;
      batch.sources = payload.sources || [];
      batch.persisted = false;
      if (data.persistWarning) {
        batch.statusNote = `${batch.statusNote || ""} ${data.persistWarning}`.trim();
      }
    }
    upsertBatch(batch);

    let level = "ok";
    if (data.needsCaptcha || rateLimited) level = "warn";
    else if (hasErr && !(data.count > 0)) level = "error";
    else if (hasErr) level = "warn";
    const short = state.lastDetails.some((d) => {
      const fetched =
        typeof d.fetched === "number" ? d.fetched : Array.isArray(d.records) ? d.records.length : 0;
      return d.totalFound && fetched < d.totalFound && fetched < payload.max_results_per_source;
    });
    setStatus(
      `批次已更新：${data.count || 0} 条。${detailMsg ? " " + detailMsg : ""}${
        short ? " 若未取全：可提高「每源条数」，或完成 Scholar 验证后点「继续检索」。" : ""
      }${data.persistWarning ? " " + data.persistWarning : ""}`,
      level
    );
    if ((data.needsCaptcha || rateLimited) && el.importCard) {
      el.importCard.classList.add("border-warning");
    }
    if (data.needsCaptcha && data.captchaSessionId) {
      state.pendingBatchId = batch.id;
      const scholarDetail = state.lastDetails.find((d) => d && d.source === "scholar");
      const fetched = scholarDetail
        ? typeof scholarDetail.fetched === "number"
          ? scholarDetail.fetched
          : (batch.records || []).length
        : (batch.records || []).length;
      const totalFound = scholarDetail ? scholarDetail.totalFound || 0 : 0;
      const target = Number(payload.max_results_per_source || 0);
      openCaptchaModal(data.captchaSessionId, { fetched, target, totalFound });
    } else if (!data.needsCaptcha) {
      state.captchaSessionId = "";
      state.pendingBatchId = "";
    }
  }

  async function loadBatches() {
    try {
      const res = await fetch("/literature/api/batches?limit=50");
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        setStatus(
          `历史批次读取失败（${(data && data.message) || res.status}）。已保留本次结果，请稍后刷新重试。`,
          "warn"
        );
        return;
      }
      state.batches = (Array.isArray(data.batches) ? data.batches : []).map(fromServerBatch);
      renderBatches();
      if (state.batches.length) {
        setStatus(`已从数据库恢复 ${state.batches.length} 个批次。`, "ok");
      }
    } catch (e) {
      setStatus("历史批次读取异常，请检查网络或稍后刷新。", "warn");
    }
  }

  async function doSearch(opts) {
    const options = opts || {};
    const query = (el.query.value || "").trim();
    const sources = selectedSources();
    if (!query) {
      setStatus("请先输入检索式。", "error");
      return;
    }
    if (sources.length < 1) {
      setStatus("至少选择 1 个来源。", "error");
      return;
    }
    const payload = {
      query,
      sources,
      start_year: (el.startYear.value || "").trim(),
      end_year: (el.endYear.value || "").trim(),
      max_results_per_source: Number(el.maxPerSource.value || 200),
      scholar_sort_by: (el.scholarSort && el.scholarSort.value) || "relevance",
    };
    if (options.withCaptcha && state.captchaSessionId) {
      payload.scholar_captcha_session_id = state.captchaSessionId;
    }
    state.lastSearchPayload = payload;

    let batchId = options.withCaptcha && state.pendingBatchId ? state.pendingBatchId : "";
    if (!batchId) {
      batchId = `tmp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      upsertBatch({
        id: batchId,
        type: "search",
        typeLabel: "检索",
        createdAt: nowLabel(),
        records: [],
        summary: `检索中… ${query}`,
        statusNote: "正在检索并翻页，条数较多时可能需 1–3 分钟…",
        query,
        sources,
        persisted: false,
      });
    } else {
      // 续抓：带上已有记录与偏移
      const existing = findBatch(batchId);
      if (existing && (existing.records || []).length) {
        payload.batch_id = batchId;
        payload.prior_records = existing.records;
        payload.scholar_start_offset = existing.records.length;
      } else if (batchId && !String(batchId).startsWith("tmp_")) {
        payload.batch_id = batchId;
      }
    }

    setBusy(el.searchBtn, true, "检索中...");
    if (el.captchaContinueBtn) setBusy(el.captchaContinueBtn, true, "继续检索中...");
    setStatus("正在检索并翻页（Scholar 约每页 10 条），请稍候...", "warn");
    try {
      const res = await fetch("/literature/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.message || `请求失败（HTTP ${res.status}）`);
      }
      // 用服务端 batch.id 替换临时 id
      if (data.batch && data.batch.id && String(batchId).startsWith("tmp_")) {
        removeBatchLocal(batchId);
        batchId = data.batch.id;
      }
      applySearchResult(data, payload, batchId);
      if (options.withCaptcha && data.count > 0 && !data.needsCaptcha && el.captchaModal) {
        const modal =
          window.bootstrap && bootstrap.Modal
            ? bootstrap.Modal.getOrCreateInstance(el.captchaModal)
            : null;
        if (modal) modal.hide();
      }
    } catch (err) {
      const batch = findBatch(batchId);
      if (batch) {
        batch.statusNote = String(err && err.message ? err.message : err);
        upsertBatch(batch);
      }
      setStatus(String(err && err.message ? err.message : err), "error");
    } finally {
      setBusy(el.searchBtn, false, "检索中...");
      if (el.captchaContinueBtn) setBusy(el.captchaContinueBtn, false, "继续检索中...");
    }
  }

  async function doImport() {
    const file = el.importFile.files && el.importFile.files[0];
    if (!file) {
      setStatus("请选择需要导入的 RIS/CSV 文件。", "error");
      return;
    }
    const fd = new FormData();
    fd.append("source", el.importSource.value);
    fd.append("file", file);
    const batchId = `tmp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    upsertBatch({
      id: batchId,
      type: "import",
      typeLabel: "导入",
      createdAt: nowLabel(),
      records: [],
      summary: `导入中… ${file.name}（${el.importSource.value}）`,
      statusNote: "正在导入…",
      sources: [el.importSource.value],
      persisted: false,
    });
    setBusy(el.importBtn, true, "导入中...");
    setStatus("正在导入为新批次...", "warn");
    try {
      const res = await fetch("/literature/api/import", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.message || `导入失败（HTTP ${res.status}）`);
      }
      removeBatchLocal(batchId);
      if (data.batch && data.batch.id) {
        upsertBatch(fromServerBatch(data.batch));
      } else {
        upsertBatch({
          id: batchId,
          type: "import",
          typeLabel: "导入",
          createdAt: nowLabel(),
          records: Array.isArray(data.records) ? data.records : [],
          summary: `文件：${file.name} ｜ 来源：${el.importSource.value} ｜ 命中 ${data.count || 0}`,
          statusNote: data.persistWarning || "",
          sources: [el.importSource.value],
          persisted: false,
        });
      }
      setStatus(
        `导入完成：${data.count || 0} 条。${data.persistWarning ? " " + data.persistWarning : ""}`,
        data.persistWarning ? "warn" : "ok"
      );
    } catch (err) {
      const batch = findBatch(batchId);
      if (batch) {
        batch.statusNote = String(err && err.message ? err.message : err);
        upsertBatch(batch);
      }
      setStatus(String(err && err.message ? err.message : err), "error");
    } finally {
      setBusy(el.importBtn, false, "导入中...");
    }
  }

  async function exportBatch(batchId, format) {
    const batch = findBatch(batchId);
    if (!batch || !(batch.records || []).length) {
      setStatus("该批次暂无可导出的数据。", "error");
      return;
    }
    const fmt = format || "docx";
    setStatus(`正在导出本批次（${fmt === "xlsx" ? "Excel" : "Word"}）...`, "warn");
    try {
      const res = await fetch("/literature/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify({ records: batch.records, format: fmt }),
      });
      if (!res.ok) {
        let msg = `导出失败（HTTP ${res.status}）`;
        try {
          const data = await res.json();
          msg = data.message || msg;
        } catch (e) {
          // ignore
        }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      const m = /filename\*=UTF-8''([^;]+)|filename="?([^"]+)"?/i.exec(cd);
      const fileName = decodeURIComponent(
        (m && (m[1] || m[2])) ||
          (fmt === "xlsx"
            ? "Clinical_Literature_Search_Result.xlsx"
            : "Clinical_Literature_Search_Result.docx")
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus(`导出成功：${fileName}`, "ok");
    } catch (err) {
      setStatus(String(err && err.message ? err.message : err), "error");
    }
  }

  async function removeBatch(id) {
    if (!id) return;
    if (!String(id).startsWith("tmp_")) {
      try {
        const res = await fetch(`/literature/api/batches/${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          throw new Error(data.message || "删除失败");
        }
      } catch (err) {
        setStatus(String(err && err.message ? err.message : err), "error");
        return;
      }
    }
    removeBatchLocal(id);
    setStatus("已删除该批次。", "ok");
  }

  el.searchBtn.addEventListener("click", function () {
    doSearch({ withCaptcha: false });
  });
  el.importBtn.addEventListener("click", doImport);
  if (el.clearBatchesBtn) {
    el.clearBatchesBtn.addEventListener("click", async function () {
      try {
        const res = await fetch("/literature/api/batches", { method: "DELETE" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          throw new Error(data.message || "清空失败");
        }
      } catch (err) {
        setStatus(String(err && err.message ? err.message : err), "error");
        return;
      }
      state.batches = [];
      state.pendingBatchId = "";
      state.captchaSessionId = "";
      renderBatches();
      setStatus("已清空全部批次。", "ok");
    });
  }
  el.batchList.addEventListener("click", function (ev) {
    const t = ev.target;
    if (!(t instanceof HTMLElement)) return;
    const exportBtn = t.closest(".lit-export-batch");
    if (exportBtn) {
      exportBatch(
        exportBtn.getAttribute("data-batch-id") || "",
        exportBtn.getAttribute("data-format") || "docx"
      );
      return;
    }
    const removeBtn = t.closest(".lit-remove-batch");
    if (removeBtn) {
      removeBatch(removeBtn.getAttribute("data-batch-id") || "");
      return;
    }
    const detailBtn = t.closest(".lit-detail-btn");
    const row = t.closest(".lit-row");
    const target = detailBtn || row;
    if (target) {
      const bid = target.getAttribute("data-batch-id") || "";
      const idx = Number(target.getAttribute("data-index") || -1);
      if (bid && idx >= 0) showDetail(bid, idx);
    }
  });
  if (el.captchaContinueBtn) {
    el.captchaContinueBtn.addEventListener("click", function () {
      doSearch({ withCaptcha: true });
    });
  }

  renderBatches();
  loadBatches();
})();
