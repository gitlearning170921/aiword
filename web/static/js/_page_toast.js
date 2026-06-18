/**
 * 长页面提示：当顶部 alert 不在视口内时，右下角 Bootstrap Toast 补显。
 * 供 _async_job.js、draft_gen.js、audit_report_edit.js 等调用。
 */
(function (global) {
  "use strict";

  var STACK_ID = "aiword-page-toast-stack";
  var MAX_TOASTS = 4;
  var DEFAULT_DELAY_MS = 5500;
  var ERROR_DELAY_MS = 9000;

  function stackEl() {
    return document.getElementById(STACK_ID);
  }

  function ensureStack() {
    var el = stackEl();
    if (el) return el;
    el = document.createElement("div");
    el.id = STACK_ID;
    el.className = "toast-container position-fixed bottom-0 end-0 p-3 aiword-page-toast-stack";
    el.setAttribute("aria-live", "polite");
    el.setAttribute("aria-atomic", "true");
    document.body.appendChild(el);
    return el;
  }

  /** 消息锚点（如 #dg_msg）是否在可视区域内。 */
  function isMsgVisible(anchorEl) {
    if (!anchorEl || anchorEl.classList.contains("d-none")) return false;
    var rect = anchorEl.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight || 0;
    if (vh <= 0) return true;
    return rect.bottom > 16 && rect.top < vh - 16;
  }

  function trimStack(container) {
    var nodes = container.querySelectorAll(".toast");
    while (nodes.length > MAX_TOASTS) {
      var old = nodes[0];
      try {
        var inst = global.bootstrap && global.bootstrap.Toast.getInstance(old);
        if (inst) inst.hide();
      } catch (_) {}
      if (old.parentNode) old.parentNode.removeChild(old);
      nodes = container.querySelectorAll(".toast");
    }
  }

  function show(text, isErr) {
    var msg = String(text == null ? "" : text).trim();
    if (!msg || typeof global.bootstrap === "undefined" || !global.bootstrap.Toast) return false;

    var container = ensureStack();
    trimStack(container);

    var toast = document.createElement("div");
    toast.className = "toast aiword-page-toast" + (isErr ? " aiword-page-toast--error" : "");
    toast.setAttribute("role", "alert");
    toast.setAttribute("aria-live", "assertive");
    toast.setAttribute("aria-atomic", "true");

    var header = document.createElement("div");
    header.className =
      "toast-header" + (isErr ? " text-bg-danger border-0" : "");
    var title = document.createElement("strong");
    title.className = "me-auto";
    title.textContent = isErr ? "操作未成功" : "提示";
    var close = document.createElement("button");
    close.type = "button";
    close.className = "btn-close" + (isErr ? " btn-close-white" : "");
    close.setAttribute("data-bs-dismiss", "toast");
    close.setAttribute("aria-label", "关闭");
    header.appendChild(title);
    header.appendChild(close);

    var body = document.createElement("div");
    body.className = "toast-body";
    body.textContent = msg;

    toast.appendChild(header);
    toast.appendChild(body);
    container.appendChild(toast);

    var delay = isErr ? ERROR_DELAY_MS : DEFAULT_DELAY_MS;
    var inst = new global.bootstrap.Toast(toast, { autohide: true, delay: delay });
    toast.addEventListener("hidden.bs.toast", function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    });
    inst.show();
    return true;
  }

  /**
   * 更新页面内 alert；若锚点不可见则同时弹出 Toast。
   * @returns {boolean} 是否显示了 Toast
   */
  function maybeToastFor(anchorEl, text, isErr) {
    if (!text) return false;
    if (anchorEl && isMsgVisible(anchorEl)) return false;
    return show(text, isErr);
  }

  global.PageToast = {
    show: show,
    isMsgVisible: isMsgVisible,
    maybeToastFor: maybeToastFor,
  };
})(typeof window !== "undefined" ? window : this);
