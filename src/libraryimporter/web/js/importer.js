/* importer.js - the page. Python owns the truth (parsed model + destination)
   and hands the WHOLE state back after every mutation; render(state) repaints
   from scratch (checklist re-binds keep selection alive). One BV.checklist
   owns selection; keys are line + "/" + robot - a slash can never appear in a
   folder name. window.LI is the Python->page push surface: LI.onDrop (native
   drops only surface real paths Python-side) and LI.onProgress. */
(function () {
  "use strict";

  var SEP = "/";
  var state = null;        /* last state payload from Python */
  var lineRefs = [];       /* [{line, robots, countEl}] rebuilt every render */
  var seeding = false;

  function $(id) { return document.getElementById(id); }
  function key(line, robot) { return line + SEP + robot; }

  var cl = BV.checklist({ onChange: syncGo });

  function allSelectableKeys() {
    var out = [];
    ((state && state.lines) || []).forEach(function (ln) {
      ln.robots.forEach(function (r) { if (!r.present) out.push(key(ln.line, r.robot)); });
    });
    return out;
  }

  function hintFor(why) {
    if (why === "ip") return "already in library (IP known)";
    if (why === "dup") return "duplicate IP in this list";
    return "already in library";
  }

  /* ---- rendering ---- */

  function render(s) {
    state = s;

    var dz = $("drop-zone");
    dz.classList.toggle("loaded", !!s.source);
    if (s.source) {
      $("src-name").textContent = s.source.name;
      $("src-meta").textContent = s.source.robots + " robots / " + s.source.lines +
        (s.source.lines === 1 ? " line" : " lines");
    }
    $("src-warnings").textContent = s.source ? (s.source.warnings || []).join(" · ") : "";

    $("dest-path").textContent = s.dest || "not chosen yet";
    $("dest-path").classList.toggle("chosen", !!s.dest);
    var dw = $("dest-warnings");
    dw.innerHTML = "";
    (s.warnings || []).forEach(function (w) {
      dw.appendChild(BV.el("div", { class: "warn-line" }, "⚠ " + BV.esc(w)));
    });

    /* keep whichever lines the user had expanded across re-renders */
    var box = $("lines");
    var wasOpen = {};
    box.querySelectorAll("details[data-line]").forEach(function (d) {
      if (d.open) wasOpen[d.getAttribute("data-line")] = true;
    });
    box.innerHTML = "";
    lineRefs = [];

    (s.lines || []).forEach(function (ln) {
      var det = BV.el("details", { class: "li-line", "data-line": ln.line });
      if (wasOpen[ln.line]) det.open = true;

      var sum = BV.el("summary");
      var sel = BV.el("input", { type: "checkbox", class: "lf-check" });
      /* the line box selects, it must never toggle the fold */
      sel.addEventListener("click", function (e) { e.stopPropagation(); });
      var selectable = ln.robots.filter(function (r) { return !r.present; });
      if (selectable.length) {
        cl.group(sel, function () {
          return selectable.map(function (r) { return key(ln.line, r.robot); });
        }, ln.line);
      } else {
        sel.disabled = true;        /* the whole line is already in the library */
        sel.checked = true;
      }
      sum.appendChild(sel);
      sum.appendChild(BV.el("span", { class: "li-name" }, BV.esc(ln.line)));
      var count = BV.el("span", { class: "li-count" });
      sum.appendChild(count);
      det.appendChild(sum);
      lineRefs.push({ line: ln.line, robots: ln.robots, countEl: count });

      ln.robots.forEach(function (r) {
        var row = BV.el("label", { class: "li-row" + (r.present ? " present" : "") });
        var cb = BV.el("input", { type: "checkbox", class: "lf-check" });
        if (r.present) {
          cb.disabled = true;       /* cosmetic: never bound, never counted */
          cb.checked = true;
        } else {
          cl.bind(cb, key(ln.line, r.robot));
        }
        row.appendChild(cb);
        row.appendChild(BV.el("span", { class: "li-robot" }, BV.esc(r.full)));
        row.appendChild(BV.el("span", { class: "li-ip" }, BV.esc(r.ip)));
        if (r.present) row.appendChild(BV.el("span", { class: "li-hint" }, BV.esc(hintFor(r.why))));
        det.appendChild(row);
      });
      box.appendChild(det);
    });

    $("robots-head").classList.toggle("hidden", !(s.lines || []).length);
    $("head-count").textContent = (s.lines || []).length
      ? s.selectable + " selectable" + (s.present ? " · " + s.present + " already in library" : "")
      : "";

    /* selections that stopped being selectable (new dest, rerun) fall away */
    var valid = {};
    allSelectableKeys().forEach(function (k) { valid[k] = true; });
    cl.selected().forEach(function (k) { if (!valid[k]) cl.set(k, false); });
    cl.sync();
  }

  /* ---- the go bar (checklist onChange) ---- */

  function syncGo() {
    lineRefs.forEach(function (ref) {
      var total = 0, on = 0;
      ref.robots.forEach(function (r) {
        if (r.present) return;
        total++;
        if (cl.has(key(ref.line, r.robot))) on++;
      });
      ref.countEl.textContent = total
        ? on + "/" + total
        : "all " + ref.robots.length + " in library";
    });
    var n = cl.size();
    var m = 0;
    lineRefs.forEach(function (ref) {
      if (ref.robots.some(function (r) { return !r.present && cl.has(key(ref.line, r.robot)); })) m++;
    });
    var go = $("btn-go");
    go.textContent = n ? "import " + n + " robot" + (n === 1 ? "" : "s") : "import";
    go.disabled = seeding || !n || !(state && state.dest);
    if (seeding) return;                    /* the progress push owns the bar */
    var sum = $("go-summary");
    if (!state || !state.source) sum.textContent = "";
    else if (!n) sum.textContent = "select lines or robots above";
    else if (!state.dest) sum.textContent = "pick a destination folder to enable import";
    else sum.textContent = n + " robot" + (n === 1 ? "" : "s") + " across " +
      m + " line" + (m === 1 ? "" : "s");
  }

  /* ---- actions ---- */

  function pickSource() {
    if (seeding) return;
    BV.api.call("pick_source").then(function (s) {
      if (!s) return;                       /* dialog cancelled */
      cl.clear();
      backToSteps();
      render(s);
    }).catch(function (e) { BV.toast(e.message); });
  }

  function pickDest() {
    if (seeding) return;
    BV.api.call("pick_dest").then(function (s) {
      if (!s) return;
      backToSteps();
      render(s);                            /* selection survives; render prunes */
    }).catch(function (e) { BV.toast(e.message); });
  }

  function go() {
    if (seeding || !cl.size() || !(state && state.dest)) return;
    var selection = {};
    cl.selected().forEach(function (k) {
      var i = k.indexOf(SEP);
      var line = k.slice(0, i), robot = k.slice(i + 1);
      (selection[line] = selection[line] || []).push(robot);
    });
    seeding = true;
    $("btn-go").disabled = true;
    $("go-summary").textContent = "importing…";
    BV.api.call("seed", selection).then(function (r) {
      seeding = false;
      showResult(r.result, r.state);
    }, function (e) {
      seeding = false;
      BV.toast(e.message);
      syncGo();
    });
  }

  function showResult(res, s) {
    cl.clear();
    render(s);                              /* the fresh plan re-grays what was created */
    var panel = $("result");
    panel.innerHTML = "";
    panel.appendChild(BV.el("div", {
      class: "res-big " + (res.errors.length ? "err" : "ok"),
    }, BV.esc(res.created + " robot" + (res.created === 1 ? "" : "s") + " created")));
    var bits = [];
    if (res.skipped) bits.push(res.skipped + " already there");
    if (res.errors.length) bits.push(res.errors.length + " failed");
    panel.appendChild(BV.el("div", { class: "res-sub" },
      BV.esc(bits.join(" · ") || "open BackupViewer and the fleet is there")));
    var bl = BV.el("div", { class: "res-lines" });
    res.by_line.forEach(function (b) {
      bl.appendChild(BV.el("div", { class: "res-line" },
        BV.esc(b.line) + ' <span class="dim">— ' + b.created + " created" +
        (b.skipped ? ", " + b.skipped + " skipped" : "") + "</span>"));
    });
    panel.appendChild(bl);
    res.errors.forEach(function (er) {
      panel.appendChild(BV.el("div", { class: "res-err" }, BV.esc(er.path + " — " + er.error)));
    });
    var acts = BV.el("div", { class: "res-actions" });
    acts.appendChild(BV.el("button", {
      class: "btn primary",
      onclick: function () { BV.api.call("open_dest").catch(function (e) { BV.toast(e.message); }); },
    }, "open the folder"));
    acts.appendChild(BV.el("button", { class: "btn", onclick: backToSteps }, "import more"));
    panel.appendChild(acts);
    $("steps").classList.add("hidden");
    $("gobar").classList.add("hidden");
    panel.classList.remove("hidden");
  }

  function backToSteps() {
    $("result").classList.add("hidden");
    $("steps").classList.remove("hidden");
    $("gobar").classList.remove("hidden");
  }

  /* ---- python -> page pushes ---- */

  window.LI = {
    onDrop: function (p) {
      if (!p || p.ok !== true) {
        BV.toast((p && p.error) || "drop failed");
        return;
      }
      cl.clear();
      backToSteps();
      render(p);
    },
    onProgress: function (done, total, line) {
      $("go-summary").textContent = line
        ? "importing " + line + "… " + done + "/" + total + " line" + (total === 1 ? "" : "s")
        : "importing…";
    },
  };

  /* ---- boot ---- */

  function init() {
    $("drop-zone").addEventListener("click", pickSource);
    $("btn-dest").addEventListener("click", pickDest);
    $("btn-go").addEventListener("click", go);
    cl.group($("sel-all"), allSelectableKeys, "ALL");

    /* dragover/drop highlight only - real drop paths arrive Python-side; the
       document-level preventDefault keeps a stray drop from navigating away */
    var dz = $("drop-zone");
    ["dragenter", "dragover"].forEach(function (t) {
      dz.addEventListener(t, function () { dz.classList.add("drag"); });
    });
    ["dragleave", "drop"].forEach(function (t) {
      dz.addEventListener(t, function () { dz.classList.remove("drag"); });
    });
    document.addEventListener("dragover", function (e) { e.preventDefault(); });
    document.addEventListener("drop", function (e) { e.preventDefault(); });

    BV.api.call("get_boot").then(function (b) {
      $("ver").textContent = "v" + b.version;
    }).catch(function () { /* plain browser: leave the header bare */ });

    syncGo();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
