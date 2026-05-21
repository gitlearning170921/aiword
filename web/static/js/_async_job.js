/**
 * aiword 公共"异步 job 轮询/进度/失败显式化"模块。
 *
 * 与 draft_gen.js 中的同名函数行为一致：
 * - 墙钟 ≤ 72h 终止；起始 1.2s，逐步 2.8s/4.5s 拉长间隔
 * - succeeded / failed 为终态
 * - 失败时把 message / error / errorSummary 拼成可读尾巴
 *
 * 由 audit.js / audit_modify.js / translate.js 直接引用。
 */
(function (global) {
  "use strict";

  var STATUS_ZH = {
    pending: "排队中",
    queued: "排队中",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
  };

  /** 与后端 normalize_upstream_job_status 对齐 */
  function normalizeJobStatus(st) {
    var s = (st || "").toString().toLowerCase();
    if (
      s === "succeeded" ||
      s === "success" ||
      s === "successful" ||
      s === "completed" ||
      s === "complete" ||
      s === "done" ||
      s === "finished"
    ) {
      return "succeeded";
    }
    if (s === "failed" || s === "error" || s === "errored" || s === "cancelled" || s === "canceled" || s === "aborted") {
      return "failed";
    }
    if (s === "queued" || s === "running" || s === "pending") {
      return s;
    }
    return s || "running";
  }

  function statusZh(st) {
    var s = normalizeJobStatus(st);
    return STATUS_ZH[s] || st || "";
  }

  function isTerminalStatus(st) {
    var s = normalizeJobStatus(st);
    return s === "succeeded" || s === "failed";
  }

  function $(id) {
    return document.getElementById(id);
  }

  /** 显示一段消息到 #<msgElId>（若存在）；isErr 为 true 用红色样式。 */
  function showMsg(msgElId, text, isErr) {
    var box = $(msgElId);
    if (!box) return;
    box.textContent = text || "";
    box.className = "alert " + (isErr ? "alert-danger" : "alert-info");
    box.classList.remove("d-none");
  }

  /** 把 fetch 响应包装成 {ok, status, json}。 */
  function api(url, opt) {
    opt = opt || {};
    opt.credentials = opt.credentials || "same-origin";
    return fetch(url, opt).then(function (r) {
      return r
        .json()
        .catch(function () {
          return {};
        })
        .then(function (j) {
          return { ok: r.ok, status: r.status, json: j };
        });
    });
  }

  /**
   * 通用轮询：传入 statusUrl 取上游同步后的本地状态；onUpdate 每个 tick 收到 { status, progress, message, errorTail }；
   * onDone(err, finalJson) 终态回调。
   */
  function pollJob(statusUrl, opt) {
    opt = opt || {};
    var onUpdate = typeof opt.onUpdate === "function" ? opt.onUpdate : function () {};
    var onDone = typeof opt.onDone === "function" ? opt.onDone : function () {};
    var deadlineMs = Date.now() + 72 * 3600 * 1000;
    var n = 0;
    function tick() {
      if (Date.now() > deadlineMs) {
        onDone(new Error("轮询超时（已超过 72 小时）"));
        return;
      }
      api(statusUrl, { method: "GET" })
        .then(function (x) {
          var j = (x && x.json && typeof x.json === "object") ? x.json : {};
          if (!x.ok) {
            var em = j.message || j.detail || "HTTP " + x.status;
            onDone(new Error(em));
            return;
          }
          var st = ((j.status || "") + "").toLowerCase();
          var pr = j.progress != null ? parseFloat(j.progress) : NaN;
          if (isNaN(pr)) pr = st === "succeeded" ? 1 : st === "failed" ? 1 : 0.12;
          var msg = ((j.message || "") + "").trim() || (st ? "状态：" + statusZh(st) : "处理中…");
          var errTail = ((j.error || j.errorSummary || "") + "").trim();
          onUpdate({
            status: st,
            statusZh: statusZh(st),
            progress: pr,
            message: msg,
            errorTail: errTail,
            raw: j,
          });
          if (st === "succeeded" || st === "failed") {
            onDone(null, j);
            return;
          }
          var delay = n < 45 ? 1200 : n < 150 ? 2800 : 4500;
          n += 1;
          setTimeout(tick, delay);
        })
        .catch(function (e) {
          onDone(e);
        });
    }
    tick();
  }

  /** 写"进度条 + 提示文案"到一组通用 DOM 元素（id 自定义）。 */
  function progressUI(opts) {
    opts = opts || {};
    var wrap = $(opts.wrapId);
    var bar = $(opts.barId);
    var text = $(opts.textId);
    var headline = $(opts.headlineId);
    return {
      show: function () {
        if (wrap) wrap.classList.remove("d-none");
      },
      hide: function () {
        if (wrap) wrap.classList.add("d-none");
      },
      setHeadline: function (s) {
        if (headline) headline.textContent = s == null ? "" : String(s);
      },
      update: function (frac, msg) {
        if (bar) {
          var p = Math.max(0, Math.min(1, parseFloat(frac) || 0));
          var pct = Math.round(p * 100);
          bar.style.width = pct + "%";
          bar.setAttribute("aria-valuenow", String(pct));
          bar.textContent = pct + "%";
        }
        if (text) text.textContent = msg == null ? "" : String(msg);
      },
      setRunning: function (running) {
        if (!bar) return;
        if (running) {
          bar.classList.add("progress-bar-animated", "progress-bar-striped");
          bar.classList.remove("bg-success", "bg-danger");
          bar.classList.add("bg-primary");
        } else {
          bar.classList.remove("progress-bar-animated", "progress-bar-striped");
        }
      },
      setTerminal: function (ok) {
        if (!bar) return;
        bar.classList.remove("bg-primary");
        bar.classList.add(ok ? "bg-success" : "bg-danger");
      },
    };
  }

  global.AsyncJob = {
    api: api,
    showMsg: showMsg,
    statusZh: statusZh,
    normalizeJobStatus: normalizeJobStatus,
    isTerminalStatus: isTerminalStatus,
    pollJob: pollJob,
    progressUI: progressUI,
  };
})(typeof window !== "undefined" ? window : this);
