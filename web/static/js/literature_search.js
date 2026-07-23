(function () {
  const state = {
    batches: [],
    captchaSessionId: "",
    pendingBatchId: "",
    lastSearchPayload: null,
    batchPage: 0,
    reimportBatchId: "",
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

  // 剥掉 Scholar 残留 HTML（含损坏闭合如 </SPAN中>、及 &lt;span&gt; 实体转义形态）
  function stripHtmlTags(v) {
    let s = String(v || "");
    for (let i = 0; i < 2; i++) {
      s = s
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/&lt;/gi, "<")
        .replace(/&gt;/gi, ">")
        .replace(/&quot;/gi, '"')
        .replace(/&#39;/gi, "'")
        .replace(/&#x27;/gi, "'")
        .replace(/&#(\d+);/g, (_, n) => {
          const code = Number(n);
          return Number.isFinite(code) ? String.fromCharCode(code) : "";
        })
        .replace(/&#x([0-9a-f]+);/gi, (_, h) => {
          const code = parseInt(h, 16);
          return Number.isFinite(code) ? String.fromCharCode(code) : "";
        })
        .replace(/<[^>]*>/gi, " ");
      if (!/[<>]/.test(s)) break;
    }
    return s.replace(/\s+/g, " ").trim();
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

  // 批次摘要里去掉「检索式：…」段，检索式单独用库内原文展示（不由服务端译成中文；浏览器整页翻译仍可生效）
  function summaryWithoutQuery(b) {
    let s = String((b && b.summary) || "").trim();
    if (!s) return "";
    // 去掉前缀「检索式：xxx ｜」或「检索式：xxx」
    s = s.replace(/^检索式：\s*/u, "");
    const q = String((b && b.query) || "").trim();
    if (q && s.startsWith(q)) {
      s = s.slice(q.length).replace(/^\s*｜\s*/, "").trim();
    } else {
      // summary 中检索式可能被浏览器/历史数据改写，按「｜」劈掉首段更稳
      const parts = s.split(/\s*｜\s*/);
      if (parts.length > 1 && /来源|每源|已取|文件/.test(parts.slice(1).join("｜"))) {
        s = parts.slice(1).join(" ｜ ").trim();
      }
    }
    return s;
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
      params: b.params && typeof b.params === "object" ? b.params : {},
      query: b.query || "",
      sources: Array.isArray(b.sources) ? b.sources : [],
      persisted: true,
    };
  }

  // 批次的「每源目标条数」：优先用该批次存下的检索参数，其次用当前表单值。
  // Scholar 的「约 N 条」估计不可靠，续抓目标以用户填写的每源条数为准。
  function batchTarget(b) {
    const rp = (b && b.params) || {};
    const t = Number(rp.max_results_per_source || 0);
    if (t > 0) return t;
    return Number((el.maxPerSource && el.maxPerSource.value) || 200) || 200;
  }

  // 判断某检索批次是否还能「续抓」：含 scholar、已有记录，且「已抓 < 目标(每源条数)」。
  // 不再依赖不靠谱的 totalFound 估计来隐藏按钮——只要没到用户设定的每源条数就允许续抓。
  function scholarResumeInfo(b) {
    if (!b || b.type === "import") return null;
    const sources = Array.isArray(b.sources) ? b.sources : [];
    const hasScholar =
      sources.includes("scholar") ||
      (b.records || []).some((r) => (r.source || "") === "scholar");
    if (!hasScholar) return null;
    const scholarCount = (b.records || []).filter((r) => (r.source || "") === "scholar").length;
    if (scholarCount <= 0) return null;
    const detail = (b.details || []).find((d) => d && d.source === "scholar") || {};
    const totalFoundRaw = Number(detail.totalFound || 0);
    const hadError = !!detail.error;
    const target = batchTarget(b);
    // 已达到用户设定的每源条数 → 视为完成，不再显示续抓
    if (scholarCount >= target) return null;
    // 展示分母：估计值明显大于已抓时才用估计，否则用用户填写的每源条数
    const displayTotal = totalFoundRaw > scholarCount ? totalFoundRaw : target;
    return { offset: scholarCount, totalFound: displayTotal, hadError };
  }

  function upsertBatch(batch) {
    const idx = state.batches.findIndex((b) => b.id === batch.id);
    if (idx >= 0) {
      state.batches[idx] = batch;
    } else {
      state.batches.unshift(batch);
      // 新批次插到最前（第 1 页），跳回首页让用户看到
      state.batchPage = 0;
    }
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
    if (rec.citation) return stripHtmlTags(rec.citation);
    const bits = [rec.authors, rec.title, rec.source_info].map(stripHtmlTags).filter(Boolean);
    return bits.join(". ");
  }

  // 卷/期/页缺失（仅对学术文献 scholar/pubmed 提示；导入类不判）
  function vipMissing(rec) {
    const src = String((rec && rec.source) || "").toLowerCase();
    if (src !== "scholar" && src !== "pubmed") return false;
    return !String((rec && rec.volume_issue_pages) || "").trim();
  }

  // 无链接地址
  function linkMissing(rec) {
    return !String((rec && rec.source_url) || "").trim();
  }

  // 批次内记录分页：每页 100 条
  const LIT_PAGE_SIZE = 100;
  // 批次列表分页：每页 10 个批次
  const LIT_BATCH_PER_PAGE = 10;

  function batchTotalPages(b) {
    const total = (b && b.records ? b.records.length : 0) || 0;
    return Math.max(1, Math.ceil(total / LIT_PAGE_SIZE));
  }

  function clampBatchPage(b) {
    const totalPages = batchTotalPages(b);
    let p = Number(b._page || 0);
    if (!(p >= 0)) p = 0;
    if (p > totalPages - 1) p = totalPages - 1;
    b._page = p;
    return p;
  }

  // 当前页的记录行（每页 LIT_PAGE_SIZE 条；Item 编号跨页连续）
  function batchRowsHtml(b) {
    const recs = b.records || [];
    const page = clampBatchPage(b);
    const start = page * LIT_PAGE_SIZE;
    const slice = recs.slice(start, start + LIT_PAGE_SIZE);
    // 预计算每条按 Database 的连续序号（跨页一致）
    const counters = {};
    const itemNo = recs.map((r) => {
      const db = dbLabel(r);
      counters[db] = (counters[db] || 0) + 1;
      return counters[db];
    });
    return slice
      .map((r, j) => {
        const ri = start + j;
        const db = dbLabel(r);
        const cite = citationOf(r);
        const title = stripHtmlTags(r.title) || "—";
        const abstractText = stripHtmlTags(r.abstract || r.snippet) || "—";
        const vipTag = vipMissing(r)
          ? ' <span class="badge text-bg-warning" title="卷/期/页缺失，建议核对原文后手动补充">卷期页缺失</span>'
          : "";
        const noLinkTag = linkMissing(r)
          ? ' <span class="badge text-bg-danger" title="该文献没有链接地址">无链接</span>'
          : "";
        const link = linkMissing(r)
          ? '<span class="badge text-bg-danger" title="该文献没有链接地址">无链接</span>'
          : `<a href="${escapeHtml(r.source_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">打开</a>`;
        const selected = !!r.selected;
        const duplicate = !!r.duplicate;
        const noFulltext = !!r.no_fulltext;
        const rowClass = [
          "lit-row",
          selected ? "table-success" : "",
          duplicate ? "table-secondary" : "",
          noFulltext ? "table-warning" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return `<tr class="${rowClass}" data-batch-id="${escapeHtml(b.id)}" data-index="${ri}" style="cursor:pointer;" title="点击查看完整详情">
              <td class="text-nowrap text-center" onclick="event.stopPropagation()">
                <input type="checkbox" class="form-check-input lit-mark-selected" data-batch-id="${escapeHtml(b.id)}" data-index="${ri}" ${selected ? "checked" : ""} title="选用">
              </td>
              <td class="text-nowrap text-center" onclick="event.stopPropagation()">
                <input type="checkbox" class="form-check-input lit-mark-duplicate" data-batch-id="${escapeHtml(b.id)}" data-index="${ri}" ${duplicate ? "checked" : ""} title="重复">
              </td>
              <td class="text-nowrap text-center" onclick="event.stopPropagation()">
                <input type="checkbox" class="form-check-input lit-mark-nofulltext" data-batch-id="${escapeHtml(b.id)}" data-index="${ri}" ${noFulltext ? "checked" : ""} title="无法获取全文">
              </td>
              <td class="text-nowrap">${escapeHtml(db)}</td>
              <td class="text-nowrap">[${itemNo[ri]}]</td>
              <td style="white-space:pre-wrap; min-width:260px; max-width:420px;">${escapeHtml(title)}</td>
              <td style="white-space:pre-wrap; min-width:320px; max-width:560px;">${escapeHtml(abstractText)}</td>
              <td style="white-space:pre-wrap; min-width:420px; max-width:720px;">${escapeHtml(cite)}${vipTag}${noLinkTag}</td>
              <td class="text-nowrap">${link}</td>
              <td class="text-nowrap"><button type="button" class="btn btn-sm btn-link p-0 lit-detail-btn" data-batch-id="${escapeHtml(b.id)}" data-index="${ri}">详情</button></td>
            </tr>`;
      })
      .join("");
  }

  // 分页控件（记录超过每页条数才显示）
  function batchPagerHtml(b) {
    const total = (b.records || []).length;
    const totalPages = batchTotalPages(b);
    const page = clampBatchPage(b);
    if (total <= LIT_PAGE_SIZE) {
      return `<div id="litPager_${escapeHtml(b.id)}"></div>`;
    }
    const from = page * LIT_PAGE_SIZE + 1;
    const to = Math.min(total, (page + 1) * LIT_PAGE_SIZE);
    return `<div id="litPager_${escapeHtml(b.id)}" class="d-flex justify-content-between align-items-center px-3 py-2 border-top small text-muted">
      <span>第 ${from}–${to} 条 / 共 ${total} 条 · 第 ${page + 1}/${totalPages} 页</span>
      <span class="btn-group">
        <button type="button" class="btn btn-sm btn-outline-secondary lit-page-prev" data-batch-id="${escapeHtml(b.id)}" ${page <= 0 ? "disabled" : ""}>上一页</button>
        <button type="button" class="btn btn-sm btn-outline-secondary lit-page-next" data-batch-id="${escapeHtml(b.id)}" ${page >= totalPages - 1 ? "disabled" : ""}>下一页</button>
      </span>
    </div>`;
  }

  // 就地翻页：只更新该批次的 tbody 与分页控件，避免整体重渲染导致折叠态被重置
  function changeBatchPage(batchId, delta) {
    const b = findBatch(batchId);
    if (!b) return;
    b._page = clampBatchPage(b) + delta;
    clampBatchPage(b);
    const tbody = document.getElementById(`litRows_${b.id}`);
    if (tbody) tbody.innerHTML = batchRowsHtml(b);
    const pager = document.getElementById(`litPager_${b.id}`);
    if (pager) pager.outerHTML = batchPagerHtml(b);
  }

  // 更新选用/重复/无法获取全文标记（字段相互独立），已落库批次同步到服务端
  async function setRecordMark(batchId, index, field, value) {
    const b = findBatch(batchId);
    if (!b || !Array.isArray(b.records) || !b.records[index]) return;
    if (field !== "selected" && field !== "duplicate" && field !== "no_fulltext") return;
    b.records[index][field] = !!value;
    // 就地刷新当前页行样式，避免整表闪烁
    const tbody = document.getElementById(`litRows_${b.id}`);
    if (tbody) tbody.innerHTML = batchRowsHtml(b);
    if (!b.persisted || String(b.id || "").startsWith("tmp_")) {
      setStatus("标记已更新（批次尚未落库，检索完成后会一并保存）。", "warn");
      return;
    }
    try {
      const payload = { index: Number(index) };
      payload[field] = !!value;
      const res = await fetch(`/literature/api/batches/${encodeURIComponent(b.id)}/record-marks`, {
        method: "POST",
        headers: { "Content-Type": "application/json; charset=utf-8" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        throw new Error(data.message || "保存标记失败");
      }
      if (data.batch && data.batch.id) {
        const idx = state.batches.findIndex((x) => x.id === data.batch.id);
        if (idx >= 0) {
          const page = b._page;
          state.batches[idx] = fromServerBatch(data.batch);
          state.batches[idx]._page = page;
        }
      }
      const tip =
        field === "selected"
          ? "选用标记已保存。"
          : field === "duplicate"
            ? "重复标记已保存。"
            : "无法获取全文标记已保存。";
      setStatus(tip, "ok");
    } catch (err) {
      setStatus(String(err && err.message ? err.message : err), "error");
    }
  }

  function showDetail(batchId, index) {
    const batch = findBatch(batchId);
    const rec = batch && Array.isArray(batch.records) ? batch.records[index] : null;
    if (!rec || !el.detailBody) return;
    const rows = [
      ["Database", dbLabel(rec)],
      ["Item", `[${index + 1}]`],
      ["选用", rec.selected ? "是" : ""],
      ["重复", rec.duplicate ? "是" : ""],
      ["无法获取全文", rec.no_fulltext ? "是" : ""],
      ["Literature", citationOf(rec)],
      ["Title", stripHtmlTags(rec.title)],
      ["Abstract", stripHtmlTags(rec.abstract || rec.snippet)],
      ["Authors", stripHtmlTags(rec.authors)],
      ["Journal", stripHtmlTags(rec.journal)],
      ["Year / Date", rec.pub_date || rec.year],
      ["Volume/Issue/Pages", rec.volume_issue_pages],
      ["DOI", rec.doi],
      ["PMID", rec.pmid],
      ["Source", rec.source],
      ["Link", rec.source_url || ""],
    ];
    const vipWarn = vipMissing(rec)
      ? '<div class="alert alert-warning py-2 px-3 mb-3 small">⚠ 卷/期/页缺失：Crossref 未能按该文献补全，建议核对原文后手动补充（工具不会虚构编号）。</div>'
      : "";
    const linkWarn = linkMissing(rec)
      ? '<div class="alert alert-danger py-2 px-3 mb-3 small">⚠ 无链接地址：该文献没有 Link / source_url。</div>'
      : "";
    el.detailBody.innerHTML =
      vipWarn +
      linkWarn +
      rows
      .map(([k, v]) => {
        const val = String(v || "").trim();
        const isMark = k === "选用" || k === "重复" || k === "无法获取全文" || k === "Link";
        // 标记未勾选时显示空（不写「否」）；Link 无地址时也展示并标「无链接」
        if (!val && !isMark) return "";
        if (k === "Link") {
          if (!val) {
            return `<div class="mb-2"><div class="text-muted small">${escapeHtml(k)}</div><div><span class="badge text-bg-danger">无链接</span></div></div>`;
          }
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
    // 批次列表分页：每页 LIT_BATCH_PER_PAGE 个批次
    const batchTotalPages = Math.max(1, Math.ceil(batchCount / LIT_BATCH_PER_PAGE));
    if (!(state.batchPage >= 0)) state.batchPage = 0;
    if (state.batchPage > batchTotalPages - 1) state.batchPage = batchTotalPages - 1;
    const pageStart = state.batchPage * LIT_BATCH_PER_PAGE;
    const pageBatches = state.batches.slice(pageStart, pageStart + LIT_BATCH_PER_PAGE);
    const listPager =
      batchCount > LIT_BATCH_PER_PAGE
        ? `<div class="d-flex justify-content-between align-items-center mb-3 small text-muted">
            <span>批次 ${pageStart + 1}–${pageStart + pageBatches.length} / 共 ${batchCount} 批 · 第 ${state.batchPage + 1}/${batchTotalPages} 页</span>
            <span class="btn-group">
              <button type="button" class="btn btn-sm btn-outline-secondary lit-batchlist-prev" ${state.batchPage <= 0 ? "disabled" : ""}>上一页</button>
              <button type="button" class="btn btn-sm btn-outline-secondary lit-batchlist-next" ${state.batchPage >= batchTotalPages - 1 ? "disabled" : ""}>下一页</button>
            </span>
          </div>`
        : "";
    el.batchList.innerHTML =
      listPager +
      pageBatches
      .map((b, j) => {
        const i = pageStart + j;
        const no = batchCount - i;
        // 最近一批（全局第 0 项）默认展开，其余默认收起
        const expanded = i === 0;
        const collapseId = `litBatchBody_${escapeHtml(b.id)}`;
        const rows = batchRowsHtml(b);
        const body =
          (b.records || []).length > 0
            ? `<div class="table-responsive" style="max-height:55vh;">
                <table class="table table-sm table-hover mb-0 align-middle">
                  <thead class="table-light sticky-top">
                    <tr>
                      <th class="text-nowrap">选用</th>
                      <th class="text-nowrap">重复</th>
                      <th class="text-nowrap" title="无法获取文献全文">无全文</th>
                      <th>Database</th>
                      <th>Item</th>
                      <th>Title</th>
                      <th>Abstract</th>
                      <th>Literature</th>
                      <th>Link</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody id="litRows_${escapeHtml(b.id)}">${rows}</tbody>
                </table>
              </div>${batchPagerHtml(b)}`
            : `<div class="p-3 text-muted small">${escapeHtml(b.statusNote || "本批次暂无记录")}</div>`;
        return `<div class="card mb-3" data-batch-id="${escapeHtml(b.id)}">
          <div class="card-header d-flex justify-content-between align-items-start flex-wrap gap-2">
            <div class="flex-grow-1" style="min-width:200px;">
              <button type="button" class="btn btn-link text-decoration-none text-dark p-0 text-start lit-batch-toggle"
                data-bs-toggle="collapse" data-bs-target="#${collapseId}" aria-expanded="${expanded ? "true" : "false"}" aria-controls="${collapseId}">
                <span class="fw-semibold">${expanded ? "▼" : "▶"} 批次 #${no} · ${escapeHtml(b.typeLabel)} · ${escapeHtml(b.createdAt)}${b.persisted ? "" : " · 未落库"}</span>
              </button>
              ${
                b.query
                  ? `<div class="small mt-1"><span class="text-muted">检索式：</span><span style="white-space:pre-wrap;">${escapeHtml(b.query)}</span></div>`
                  : ""
              }
              <div class="small text-muted mt-1">${escapeHtml(summaryWithoutQuery(b))}</div>
              ${b.statusNote ? `<div class="small text-warning mt-1">${escapeHtml(b.statusNote)}</div>` : ""}
            </div>
            <div class="d-flex gap-2 align-items-center flex-wrap">
              <span class="badge text-bg-secondary">${(b.records || []).length} 条</span>
              ${
                (() => {
                  const ri = scholarResumeInfo(b);
                  if (!ri) return "";
                  const tip = ri.totalFound
                    ? `从第 ${ri.offset + 1} 条续抓（scholar ${ri.offset}/${ri.totalFound}）`
                    : `从第 ${ri.offset + 1} 条继续抓取`;
                  return `<button type="button" class="btn btn-sm btn-primary lit-continue-batch" data-batch-id="${escapeHtml(b.id)}" title="${escapeHtml(tip)}">继续抓取</button>`;
                })()
              }
              ${
                b.type === "import"
                  ? `<button type="button" class="btn btn-sm btn-outline-primary lit-reimport-batch" data-batch-id="${escapeHtml(b.id)}" title="选择文件后导入，将更新本批次：匹配条目复用序号并保留标记，新条目追加">重新导入更新</button>`
                  : `<button type="button" class="btn btn-sm btn-outline-primary lit-research-batch" data-batch-id="${escapeHtml(b.id)}" title="用相同检索式从头重新检索，结果覆盖本批次">重新检索</button>`
              }
              <button type="button" class="btn btn-sm btn-outline-success lit-export-batch" data-batch-id="${escapeHtml(b.id)}" data-format="docx" ${(b.records || []).length ? "" : "disabled"}>导出 Word</button>
              <button type="button" class="btn btn-sm btn-outline-success lit-export-batch" data-batch-id="${escapeHtml(b.id)}" data-format="xlsx" ${(b.records || []).length ? "" : "disabled"}>导出 Excel</button>
              <button type="button" class="btn btn-sm btn-outline-danger lit-remove-batch" data-batch-id="${escapeHtml(b.id)}">删除</button>
            </div>
          </div>
          <div id="${collapseId}" class="collapse${expanded ? " show" : ""} card-body p-0">${body}</div>
        </div>`;
      })
      .join("") +
      listPager;

    // 批次列表翻页
    el.batchList.querySelectorAll(".lit-batchlist-prev").forEach((btn) => {
      btn.addEventListener("click", function () {
        if (state.batchPage > 0) {
          state.batchPage -= 1;
          renderBatches();
        }
      });
    });
    el.batchList.querySelectorAll(".lit-batchlist-next").forEach((btn) => {
      btn.addEventListener("click", function () {
        state.batchPage += 1;
        renderBatches();
      });
    });

    // 折叠态切换时更新箭头
    el.batchList.querySelectorAll(".lit-batch-toggle").forEach((btn) => {
      const targetSel = btn.getAttribute("data-bs-target");
      const panel = targetSel ? document.querySelector(targetSel) : null;
      if (!panel) return;
      const syncArrow = () => {
        const open = panel.classList.contains("show");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        const label = btn.querySelector(".fw-semibold");
        if (label) {
          label.textContent = label.textContent.replace(/^[▼▶]\s*/, open ? "▼ " : "▶ ");
        }
      };
      panel.addEventListener("shown.bs.collapse", syncArrow);
      panel.addEventListener("hidden.bs.collapse", syncArrow);
    });
  }

  function openCaptchaModal(sessionId, progress) {
    state.captchaSessionId = sessionId || "";
    if (!state.captchaSessionId || !el.captchaModal) {
      setStatus("需要人机验证，但未获得验证会话，请稍后重试或改用导入。", "error");
      return;
    }
    const url = `/literature/api/scholar-captcha/${encodeURIComponent(state.captchaSessionId)}`;
    if (el.captchaFrame) el.captchaFrame.src = url;
    // 「新标签打开」优先指向真实 Google 验证页：浏览器与后端同一代理出口 IP，
    // 在真实浏览器里原生解 reCAPTCHA 更可靠，解完同一 IP 会被放行，再点继续检索。
    const p = progress || {};
    const directUrl = (p.searchUrl || "").trim();
    if (el.captchaOpenTab) el.captchaOpenTab.href = directUrl || url;

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

    if (el.captchaProgress) {
      const tip =
        "提示：若弹窗内验证码无法点选，请点上方「新标签打开验证页」，在浏览器里完成验证（与后端同一代理出口，解完同一 IP 会放行），再回此处点「继续检索」。";
      el.captchaProgress.textContent = progressText ? `${progressText} ${tip}` : tip;
    }

    const modal =
      window.bootstrap && bootstrap.Modal ? bootstrap.Modal.getOrCreateInstance(el.captchaModal) : null;
    if (modal) modal.show();
    else window.open(directUrl || url, "_blank", "noopener");
    setStatus(
      `请完成 Google 人机验证后点击「继续检索」。若弹窗内无法验证，用「新标签打开验证页」在浏览器里解。${progressText ? " " + progressText : ""}`,
      "warn"
    );
  }

  function applySearchResult(data, payload, batchId) {
    // 续抓前的 scholar 已抓数（用于判断本次是否真的取到了新记录）
    const priorScholarCount = (() => {
      const b = findBatch(batchId);
      return b ? (b.records || []).filter((r) => (r.source || "") === "scholar").length : 0;
    })();
    const isContinue = Array.isArray(payload.prior_records) && payload.prior_records.length > 0;
    const targetPerSource = Number(payload.max_results_per_source || 0) || 0;
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
        // Scholar 估计不可靠：估计值不明显大于已抓时用「每源条数」作分母
        let total = Number(d.totalFound || 0);
        if ((d.source || "") === "scholar" && targetPerSource && total <= fetched) {
          total = targetPerSource;
        }
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

    // 续抓后本次 scholar 已抓数：判断是否真的取到新记录
    const newScholarCount = (batch.records || []).filter(
      (r) => (r.source || "") === "scholar"
    ).length;
    const continueNoGain =
      isContinue && !data.needsCaptcha && !rateLimited && newScholarCount <= priorScholarCount;

    let level = "ok";
    if (data.needsCaptcha || rateLimited) level = "warn";
    else if (hasErr && !(data.count > 0)) level = "error";
    else if (hasErr) level = "warn";
    else if (continueNoGain) level = "warn";
    const short = state.lastDetails.some((d) => {
      const fetched =
        typeof d.fetched === "number" ? d.fetched : Array.isArray(d.records) ? d.records.length : 0;
      return targetPerSource && fetched < targetPerSource;
    });
    setStatus(
      `批次已更新：${data.count || 0} 条。${detailMsg ? " " + detailMsg : ""}${
        continueNoGain
          ? " 本次续抓未获取到新记录：Scholar 对当前出口 IP 已停止提供更多结果（翻页被折叠/软封锁），续抓偏移不会再空转推进。建议①换 Clash 节点后再点「继续抓取」；②或在弹出的验证页里完成人机验证（同一出口 IP 通过后可恢复完整翻页）。若浏览器同一节点也翻不到更多，则该 IP 下确实没有更多结果。"
          : short
            ? " 未取满「每源条数」：可点「继续抓取」续抓，或完成 Scholar 验证后继续。"
            : ""
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
      openCaptchaModal(data.captchaSessionId, {
        fetched,
        target,
        totalFound,
        searchUrl: data.captchaSearchUrl || "",
      });
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
    // 续抓某历史批次：用该批次存下的检索式与参数（保证 offset 落在同一结果集）
    const resumeBatch = options.continueBatchId ? findBatch(options.continueBatchId) : null;
    // 重新检索：用该批次的检索式从头重跑，结果覆盖原批次（不带 prior_records / offset）
    const rerunBatch = options.rerunBatchId ? findBatch(options.rerunBatchId) : null;
    // 读取检索式与参数的来源批次（续抓或重新检索都从历史批次取）
    const srcBatch = resumeBatch || rerunBatch;
    const query = srcBatch ? srcBatch.query || "" : (el.query.value || "").trim();
    const sources = srcBatch
      ? Array.isArray(srcBatch.sources) && srcBatch.sources.length
        ? srcBatch.sources
        : ["scholar"]
      : selectedSources();
    if (!query) {
      setStatus("请先输入检索式。", "error");
      return;
    }
    if (sources.length < 1) {
      setStatus("至少选择 1 个来源。", "error");
      return;
    }
    const rp = (srcBatch && srcBatch.params) || {};
    const payload = {
      query,
      sources,
      start_year: srcBatch ? String(rp.start_year || "") : (el.startYear.value || "").trim(),
      end_year: srcBatch ? String(rp.end_year || "") : (el.endYear.value || "").trim(),
      max_results_per_source: srcBatch
        ? Number(rp.max_results_per_source || el.maxPerSource.value || 200)
        : Number(el.maxPerSource.value || 200),
      scholar_sort_by: srcBatch
        ? rp.scholar_sort_by || "relevance"
        : (el.scholarSort && el.scholarSort.value) || "relevance",
    };
    if (options.withCaptcha && state.captchaSessionId) {
      payload.scholar_captcha_session_id = state.captchaSessionId;
    }
    state.lastSearchPayload = payload;

    let batchId = "";
    if (resumeBatch) batchId = resumeBatch.id;
    else if (rerunBatch) batchId = rerunBatch.id;
    else if (options.withCaptcha && state.pendingBatchId) batchId = state.pendingBatchId;
    if (rerunBatch) {
      // 重新检索：从头覆盖，保留同一 batch_id，清空展示中的旧记录（保留 createdAt/params 等原字段）
      payload.batch_id = batchId;
      upsertBatch(
        Object.assign({}, rerunBatch, {
          _page: 0,
          records: [],
          summary: `重新检索中… ${query}`,
          statusNote: "正在从头重新检索并覆盖本批次，按真人节奏放慢翻页，请勿刷新…",
        })
      );
    } else if (!batchId) {
      batchId = `tmp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      upsertBatch({
        id: batchId,
        type: "search",
        typeLabel: "检索",
        createdAt: nowLabel(),
        records: [],
        summary: `检索中… ${query}`,
        statusNote: "正在按真人节奏放慢翻页抓取（抗验证码），全量约需 5–12 分钟，请勿刷新…",
        query,
        sources,
        persisted: false,
      });
    } else {
      // 续抓：带上已有记录，scholar 从「已抓 scholar 条数」处继续翻页
      const existing = findBatch(batchId);
      if (existing && (existing.records || []).length) {
        const scholarOffset = (existing.records || []).filter(
          (r) => (r.source || "") === "scholar"
        ).length;
        const sd = (existing.details || []).find((d) => d && d.source === "scholar");
        // 关键：续抓偏移必须用「原始翻页位置」nextOffset，而非去重后的条数；
        // 否则去重会让 offset 落回已抓过的页 → 全被去重 → 误判「没有更多」。
        const rawNext = sd && Number(sd.nextOffset) > 0 ? Number(sd.nextOffset) : scholarOffset;
        payload.batch_id = batchId;
        payload.prior_records = existing.records;
        payload.scholar_start_offset = rawNext;
        // 带上历史见过的最大总数，避免续抓时被本次缩水的估计覆盖成「47/11」
        if (sd && Number(sd.totalFound) > 0) payload.prior_total_found = Number(sd.totalFound);
      } else if (batchId && !String(batchId).startsWith("tmp_")) {
        payload.batch_id = batchId;
      }
    }

    setBusy(el.searchBtn, true, "检索中...");
    if (el.captchaContinueBtn) setBusy(el.captchaContinueBtn, true, "继续检索中...");
    setStatus(
      resumeBatch
        ? `正在从上次结束处续抓（scholar 第 ${payload.scholar_start_offset + 1} 条起），按真人节奏放慢翻页，请耐心等待、不要刷新页面…`
        : rerunBatch
        ? "正在从头重新检索并覆盖本批次，按真人节奏放慢翻页，请耐心等待、不要刷新页面…"
        : "正在按真人节奏放慢翻页抓取（每页间隔十几~二十几秒，抗验证码），全量约需 5–12 分钟，请耐心等待、不要刷新页面…",
      "warn"
    );
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

  function syncImportButtonLabel() {
    if (!el.importBtn) return;
    if (state.reimportBatchId) {
      const bt = findBatch(state.reimportBatchId);
      const tip = bt ? `更新到批次` : "更新已选批次";
      el.importBtn.textContent = tip;
      el.importBtn.classList.remove("btn-outline-primary");
      el.importBtn.classList.add("btn-primary");
    } else {
      el.importBtn.textContent = "导入为新批次";
      el.importBtn.classList.add("btn-outline-primary");
      el.importBtn.classList.remove("btn-primary");
    }
  }

  async function doImport() {
    const file = el.importFile.files && el.importFile.files[0];
    if (!file) {
      setStatus("请选择需要导入的 RIS/CSV 文件。", "error");
      return;
    }
    const reimportId = (state.reimportBatchId || "").trim();
    const target = reimportId ? findBatch(reimportId) : null;
    if (reimportId && !target) {
      setStatus("要更新的批次已不存在，请重新点「重新导入更新」。", "error");
      state.reimportBatchId = "";
      syncImportButtonLabel();
      return;
    }
    const fd = new FormData();
    fd.append("source", el.importSource.value);
    fd.append("file", file);
    if (reimportId) fd.append("batch_id", reimportId);

    let batchId = reimportId;
    if (!batchId) {
      batchId = `tmp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
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
    } else {
      upsertBatch(
        Object.assign({}, target, {
          summary: `重新导入更新中… ${file.name}`,
          statusNote: "正在合并更新（匹配条目复用序号、保留标记）…",
        })
      );
    }
    setBusy(el.importBtn, true, reimportId ? "更新中..." : "导入中...");
    setStatus(
      reimportId
        ? "正在重新导入并更新该批次（文件内判重；匹配条目复用序号）..."
        : "正在导入为新批次（文件内按 DOI/PMID/URL/标题判重）...",
      "warn"
    );
    try {
      const res = await fetch("/literature/api/import", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.message || `导入失败（HTTP ${res.status}）`);
      }
      if (!reimportId) removeBatchLocal(batchId);
      if (data.batch && data.batch.id) {
        upsertBatch(fromServerBatch(data.batch));
      } else {
        upsertBatch({
          id: batchId,
          type: "import",
          typeLabel: "导入",
          createdAt: (target && target.createdAt) || nowLabel(),
          records: Array.isArray(data.records) ? data.records : [],
          summary: `文件：${file.name} ｜ 来源：${el.importSource.value} ｜ 命中 ${data.count || 0}`,
          statusNote: data.persistWarning || "",
          sources: [el.importSource.value],
          persisted: false,
        });
      }
      const ms = data.mergeStats || {};
      const extra = reimportId
        ? ` 更新 ${ms.updated || 0}，保留 ${ms.kept || 0}，新增 ${ms.added || 0}。`
        : "";
      setStatus(
        `导入完成：${data.count || 0} 条。${extra}${data.persistWarning ? " " + data.persistWarning : ""}`,
        data.persistWarning ? "warn" : "ok"
      );
      state.reimportBatchId = "";
      syncImportButtonLabel();
      if (el.importFile) el.importFile.value = "";
    } catch (err) {
      const batch = findBatch(batchId);
      if (batch) {
        batch.statusNote = String(err && err.message ? err.message : err);
        upsertBatch(batch);
      }
      setStatus(String(err && err.message ? err.message : err), "error");
    } finally {
      setBusy(el.importBtn, false, reimportId ? "更新中..." : "导入中...");
      syncImportButtonLabel();
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
  el.batchList.addEventListener("change", function (ev) {
    const t = ev.target;
    if (!(t instanceof HTMLInputElement) || t.type !== "checkbox") return;
    const bid = t.getAttribute("data-batch-id") || "";
    const idx = Number(t.getAttribute("data-index") || -1);
    if (!bid || !(idx >= 0)) return;
    if (t.classList.contains("lit-mark-selected")) {
      setRecordMark(bid, idx, "selected", t.checked);
      return;
    }
    if (t.classList.contains("lit-mark-duplicate")) {
      setRecordMark(bid, idx, "duplicate", t.checked);
      return;
    }
    if (t.classList.contains("lit-mark-nofulltext")) {
      setRecordMark(bid, idx, "no_fulltext", t.checked);
    }
  });

  el.batchList.addEventListener("click", function (ev) {
    const t = ev.target;
    if (!(t instanceof HTMLElement)) return;
    // 勾选标记时不打开详情
    if (t.closest(".lit-mark-selected, .lit-mark-duplicate, .lit-mark-nofulltext")) return;
    const exportBtn = t.closest(".lit-export-batch");
    if (exportBtn) {
      exportBatch(
        exportBtn.getAttribute("data-batch-id") || "",
        exportBtn.getAttribute("data-format") || "docx"
      );
      return;
    }
    const continueBtn = t.closest(".lit-continue-batch");
    if (continueBtn) {
      doSearch({ continueBatchId: continueBtn.getAttribute("data-batch-id") || "" });
      return;
    }
    const researchBtn = t.closest(".lit-research-batch");
    if (researchBtn) {
      const bid = researchBtn.getAttribute("data-batch-id") || "";
      const bt = findBatch(bid);
      const q = bt && bt.query ? `「${bt.query}」` : "该批次";
      if (window.confirm(`将用相同检索式从头重新检索，结果会覆盖${q}的现有记录。确定继续？`)) {
        doSearch({ rerunBatchId: bid });
      }
      return;
    }
    const reimportBtn = t.closest(".lit-reimport-batch");
    if (reimportBtn) {
      const bid = reimportBtn.getAttribute("data-batch-id") || "";
      state.reimportBatchId = bid;
      syncImportButtonLabel();
      setStatus(
        "已选择该导入批次：请选好 RIS/CSV 后点「更新到批次」。匹配条目会复用原序号并保留选用/重复/无全文标记，新条目追加到末尾。",
        "warn"
      );
      if (el.importCard) el.importCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
      if (el.importFile) el.importFile.focus();
      return;
    }
    const pagePrev = t.closest(".lit-page-prev");
    if (pagePrev) {
      changeBatchPage(pagePrev.getAttribute("data-batch-id") || "", -1);
      return;
    }
    const pageNext = t.closest(".lit-page-next");
    if (pageNext) {
      changeBatchPage(pageNext.getAttribute("data-batch-id") || "", 1);
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
  syncImportButtonLabel();
  loadBatches();
})();
