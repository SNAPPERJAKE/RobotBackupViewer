/* util.js - the BV namespace + the three helpers this tool actually uses,
   trimmed from BackupViewer's util.js. Loaded first. (Selection keys here are
   line + "/" + robot - a slash can never appear in a folder name, so no
   NUL-separator machinery is needed.) */
window.BV = {};

(function () {
  "use strict";

  BV.esc = function (s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  BV.el = function (tag, attrs, html) {
    var e = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") e.className = attrs[k];
        else if (k.indexOf("on") === 0) e.addEventListener(k.slice(2), attrs[k]);
        else e.setAttribute(k, attrs[k]);
      });
    }
    if (html !== undefined) e.innerHTML = html;
    return e;
  };

  var toastEl = null, toastTimer = null;
  BV.toast = function (msg, ms) {
    if (!toastEl) {
      toastEl = BV.el("div", { id: "toast" });
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, ms || 2200);
  };
})();
