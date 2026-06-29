/* tabs/home.js - the ecosystem main menu (#home). The whole screen is the saved
   robot library, grouped PLANT -> LINE -> ROBOT, with collapsible folders.
   "+ add robot" opens a context menu (from backup / manually). Each robot row has
   a selection checkbox + edit; clicking the row opens the robot's backup. Per-LINE
   controls (select-all / backup / trash) act on that line's selected robots, and
   "backup" pulls fresh FTP backups for all selected at once, showing live per-row
   progress. Marked shell:true so the router lets it render with no manifest. */
(function () {
  "use strict";

  var _libWrap = null;          /* the mounted library container, for in-place refresh */
  var _collapsed = {};          /* folder keys explicitly collapsed (default = expanded) */
  var _selected = {};           /* selected robot ids (object used as a Set) */
  var _robots = [];             /* last loaded library list, for client-side collision checks */
  var _active = {};             /* jobId -> {robotId} for in-flight backups */
  var _poll = null;             /* the single shared progress-poll interval */
  var _showHidden = false;      /* reveal hidden robots in the list */
  var _showHiddenBtn = null;    /* the header toggle (shown only when some are hidden) */

  /* ---- folder collapse state (survives in-place refreshes) ---- */
  function isExpanded(key) { return !_collapsed[key]; }
  function setExpanded(key, open) { if (open) delete _collapsed[key]; else _collapsed[key] = true; }
  function makeCollapsible(node, head, body, key) {
    node.appendChild(head);
    node.appendChild(body);
    BV.collapsible(node, head, body, {
      open: isExpanded(key),
      onToggle: function (open) { setExpanded(key, open); },
    });
    return node;
  }

  /* ---- screen ---- */

  function render(view, toolbar, params) {
    _libWrap = BV.el("div", { class: "home-library" });
    view.appendChild(_libWrap);
    loadLibrary();
  }

  function loadLibrary() {
    if (!_libWrap) return;
    _libWrap.innerHTML = "";

    var head = BV.el("div", { class: "home-lib-head" });
    head.appendChild(BV.el("h2", null, "library"));
    var headActs = BV.el("div", { class: "home-lib-actions" });
    var cancelAll = BV.el("button", { class: "btn lib-cancel-all hidden", id: "lib-cancel-all" },
      "cancel backups");
    cancelAll.addEventListener("click", cancelAllBackups);
    _showHiddenBtn = BV.el("button", { class: "btn lib-show-hidden hidden",
      title: "show robots you've hidden" }, "show hidden");
    _showHiddenBtn.addEventListener("click", function () { _showHidden = !_showHidden; refresh(); });
    var rescanBtn = BV.el("button", { class: "btn lib-rescan",
      title: "re-read the library folder from disk (picks up copied-in backups)" }, "rescan");
    rescanBtn.addEventListener("click", function () {
      rescanBtn.disabled = true;
      BV.api.call("lib_rescan")
        .then(function () { BV.toast("library rescanned"); refresh(); })
        .catch(function (e) { BV.toast(e.message); rescanBtn.disabled = false; });
    });
    var addBtn = BV.el("button", { class: "btn lib-add-robot", id: "lib-add-robot",
      title: "add a robot to the library" }, "+ add robot");
    addBtn.addEventListener("click", function () {
      BV.menu(addBtn, [
        { label: "from backup", onClick: BV.addToLibraryFlow },
        { label: "bulk from folder", onClick: bulkAddFlow },
        { label: "discover on network", onClick: discoverFlow },
        { label: "manually", onClick: function () { editRobotModal(null, true); } },
      ]);
    });
    headActs.appendChild(cancelAll);
    headActs.appendChild(_showHiddenBtn);
    headActs.appendChild(rescanBtn);
    headActs.appendChild(addBtn);
    head.appendChild(headActs);
    _libWrap.appendChild(head);

    var body = BV.el("div", { class: "home-lib-body" }, '<div class="dim">loading…</div>');
    _libWrap.appendChild(body);

    BV.api.call("lib_list").then(function (data) {
      _robots = (data && data.robots) || [];
      renderTree(body, data);
      reattachProgress();   /* repaint any backups already running */
    }).catch(function (e) {
      body.innerHTML = '<div class="dim">library unavailable: ' + BV.esc(e.message) + "</div>";
    });
  }

  function refresh() {
    if (_libWrap && document.body.contains(_libWrap)) loadLibrary();
  }

  function updateHiddenToggle(hiddenCount) {
    if (!_showHiddenBtn) return;
    _showHiddenBtn.classList.toggle("hidden", hiddenCount === 0);
    _showHiddenBtn.textContent = (_showHidden ? "hide hidden" : "show hidden") +
      (hiddenCount ? " (" + hiddenCount + ")" : "");
  }

  function renderTree(body, data) {
    var robots = (data && data.robots) || [];
    if (!robots.length) {
      body.innerHTML = '<div class="empty-lib">no robots saved yet — add a backup, or take one.</div>';
      updateHiddenToggle(0);
      return;
    }
    var plants = {}, hiddenCount = 0, visible = 0;
    robots.forEach(function (r) {
      if (r.hidden) { hiddenCount++; if (!_showHidden) return; }
      visible++;
      var pl = r.plant || "—", ln = r.line || "—";
      plants[pl] = plants[pl] || {};
      plants[pl][ln] = plants[pl][ln] || [];
      plants[pl][ln].push(r);
    });
    updateHiddenToggle(hiddenCount);
    body.innerHTML = "";
    if (!visible) {
      body.innerHTML = '<div class="empty-lib">all robots are hidden — use “show hidden” above.</div>';
      return;
    }
    Object.keys(plants).sort().forEach(function (pl) {
      var plantNode = BV.el("div", { class: "lib-plant" });
      var plantHead = BV.el("div", { class: "lib-plant-h" }, BV.esc(pl));
      var plantBody = BV.el("div", { class: "lib-plant-body" });
      var lines = plants[pl];
      Object.keys(lines).sort().forEach(function (ln) {
        var lineRobots = lines[ln].sort(function (a, b) {
          return (a.robot || "").localeCompare(b.robot || "");
        });
        var lineNode = BV.el("div", { class: "lib-line" });
        var lineHead = buildLineHead(ln, lineRobots);
        var lineBody = BV.el("div", { class: "lib-line-body" });
        lineRobots.forEach(function (r) { lineBody.appendChild(robotRow(r)); });
        makeCollapsible(lineNode, lineHead, lineBody, pl + "|||" + ln);
        plantBody.appendChild(lineNode);
      });
      makeCollapsible(plantNode, plantHead, plantBody, pl);
      body.appendChild(plantNode);
    });
    syncSelectionUI();
  }

  function buildLineHead(ln, lineRobots) {
    var head = BV.el("div", { class: "lib-line-h" });
    head.appendChild(BV.el("span", { class: "lib-line-name" }, BV.esc(ln)));

    var controls = BV.el("div", { class: "lib-line-controls" });
    controls.addEventListener("click", function (e) { e.stopPropagation(); });

    var sa = BV.el("input", { type: "checkbox", class: "lf-check lib-line-selall",
      title: "select all in line" });
    sa.addEventListener("change", function () {
      var ids = lineRobots.map(function (r) { return r.id; });
      var allOn = ids.length && ids.every(function (id) { return _selected[id]; });
      ids.forEach(function (id) { if (allOn) delete _selected[id]; else _selected[id] = true; });
      syncSelectionUI();
    });

    var bk = BV.el("button", { class: "btn lib-line-backup", title: "back up selected robots" },
      "backup");
    bk.addEventListener("click", function () { startLineBackup(lineRobots); });

    var tr = BV.el("button", { class: "btn lib-line-hide", title: "hide selected from view" },
      "hide");
    tr.addEventListener("click", function () { hideSelectedInLine(lineRobots); });

    var fix = BV.el("button", { class: "btn lib-line-fix",
      title: "fix names from the backup contents (selected)" }, "fix names");
    fix.addEventListener("click", function () { fixNamesInLine(lineRobots); });

    var mrg = BV.el("button", { class: "btn lib-line-merge",
      title: "merge 2 selected duplicate robots into one" }, "merge");
    mrg.addEventListener("click", function () { mergeSelectedInLine(lineRobots); });

    controls.appendChild(sa);
    controls.appendChild(bk);
    controls.appendChild(tr);
    controls.appendChild(fix);
    controls.appendChild(mrg);
    head.appendChild(controls);
    return head;
  }

  function robotRow(r) {
    var row = BV.el("div", { class: "lib-robot" + (r.stale ? " stale" : "") +
      (r.hidden ? " hidden-robot" : "") });
    row.setAttribute("data-robot-id", r.id);

    var cb = BV.el("input", { type: "checkbox", class: "lf-check lib-check", title: "select" });
    cb.checked = !!_selected[r.id];
    cb.addEventListener("click", function (e) { e.stopPropagation(); });
    cb.addEventListener("change", function () {
      if (cb.checked) _selected[r.id] = true; else delete _selected[r.id];
      syncSelectionUI();
    });
    row.appendChild(cb);

    var main = BV.el("div", { class: "lib-robot-main" });
    var nameHtml = '<span class="lib-robot-name">' + BV.esc(r.robot || "(unnamed)") + "</span>";
    if (r.model) nameHtml += '<span class="lib-robot-model">' + BV.esc(r.model) + "</span>";
    main.appendChild(BV.el("div", null, nameHtml));
    var meta = [];
    if (r.ips && r.ips.length) meta.push(BV.esc(r.ips[0]));
    if (r.last_backup) meta.push("last " + BV.esc(r.last_backup));
    if (r.backups && r.backups.length) meta.push(r.backups.length + " saved");
    if (r.stale) meta.push('<span class="pill warn">missing</span>');
    if (!r.latest_path && !r.stale) meta.push('<span class="pill ghost">no backup</span>');
    main.appendChild(BV.el("div", { class: "lib-robot-meta" },
      meta.join(' <span class="sep">·</span> ')));
    appendNote(main, r);
    row.appendChild(main);

    var prog = BV.el("div", { class: "lib-robot-progress" });
    row.appendChild(prog);

    var acts = BV.el("div", { class: "lib-robot-acts" });
    var editBtn = BV.el("button", { class: "btn", title: "edit" }, "edit");
    editBtn.addEventListener("click", function (e) { e.stopPropagation(); editRobotModal(r, false); });
    var moreBtn = BV.el("button", { class: "btn lib-robot-more", title: "more actions" }, "⋯");
    moreBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var items = [
        { label: r.hidden ? "unhide" : "hide", onClick: function () { setHidden(r, !r.hidden); } },
      ];
      if (r.history_root) {
        items.push({ label: "open folder", onClick: function () { openLocation(r.history_root); } });
      }
      items.push({ label: "delete from disk…", danger: true, onClick: function () { deleteFromDiskFlow(r); } });
      BV.menu(moreBtn, items);
    });
    acts.appendChild(editBtn);
    acts.appendChild(moreBtn);
    row.appendChild(acts);

    /* whole row opens the robot, except the checkbox + the action buttons */
    row.addEventListener("click", function (e) {
      if (cb.contains(e.target) || acts.contains(e.target)) return;
      openRobot(r);
    });
    return row;
  }

  /* a robot's note in the listing: first line in grey, the rest behind an
     expand caret (reusing BV.collapsible). A single-line note shows plain. */
  function appendNote(main, r) {
    var text = (r.notes || "").replace(/\r\n?/g, "\n");
    if (!text.trim()) return;
    var lines = text.split("\n");
    var first = (lines[0] || "").trim() || "(note)";
    var rest = lines.slice(1).join("\n").replace(/\s+$/, "");
    if (!rest.trim()) {
      var solo = BV.el("div", { class: "lib-robot-note-head solo" },
        '<span class="note-line">' + BV.esc(first) + "</span>");
      solo.addEventListener("click", function (e) { e.stopPropagation(); });
      main.appendChild(solo);
      return;
    }
    var node = BV.el("div", { class: "lib-robot-note" });
    var head = BV.el("div", { class: "lib-robot-note-head" },
      '<span class="note-line">' + BV.esc(first) + "</span>");
    var body = BV.el("div", { class: "lib-robot-note-body" }, BV.esc(rest));
    node.appendChild(head);
    node.appendChild(body);
    BV.collapsible(node, head, body, { open: false });
    /* don't let toggling (or right-click expand-all) open the robot */
    head.addEventListener("click", function (e) { e.stopPropagation(); });
    head.addEventListener("contextmenu", function (e) { e.stopPropagation(); });
    main.appendChild(node);
  }

  function openRobot(r) {
    if (!r.latest_path) { BV.toast("no backup yet — take one"); return; }
    if (r.stale) { BV.toast("backup folder missing on disk"); return; }
    BV.api.call("lib_open", r.id, "latest").then(function (manifest) {
      BV.state.setManifest(manifest);
      BV.toast(manifest.robot_name
        ? manifest.robot_name + " · " + manifest.file_count + " files" : "opened");
      location.hash = "#overview";
    }).catch(function (e) { BV.toast(e.message); });
  }

  /* ---- selection ---- */

  function selectedInLine(lineRobots) {
    return lineRobots.filter(function (r) { return _selected[r.id]; });
  }

  /* reflect _selected onto every checkbox + each line's select-all tri-state */
  function syncSelectionUI() {
    if (!_libWrap) return;
    _libWrap.querySelectorAll(".lib-line").forEach(function (lineNode) {
      var rows = lineNode.querySelectorAll(".lib-robot[data-robot-id]");
      var total = rows.length, on = 0;
      rows.forEach(function (rowEl) {
        var id = rowEl.getAttribute("data-robot-id");
        var cb = rowEl.querySelector(".lib-check");
        var checked = !!_selected[id];
        if (cb) cb.checked = checked;
        if (checked) on++;
      });
      var sa = lineNode.querySelector(".lib-line-selall");
      if (sa) {
        sa.checked = total > 0 && on === total;
        sa.indeterminate = on > 0 && on < total;
      }
    });
  }

  /* ---- per-line actions ---- */

  function hideSelectedInLine(lineRobots) {
    var sel = selectedInLine(lineRobots);
    if (!sel.length) { BV.toast("select robots first"); return; }
    Promise.all(sel.map(function (r) {
      return BV.api.call("lib_set_hidden", r.id, true).then(function () { delete _selected[r.id]; });
    })).then(function () {
      BV.toast("hid " + sel.length + " — files kept on disk");
      refresh();
    }).catch(function (e) { BV.toast(e.message); });
  }

  function setHidden(r, hidden) {
    BV.api.call("lib_set_hidden", r.id, hidden).then(function () {
      BV.toast(hidden ? "hidden" : "unhidden");
      refresh();
    }).catch(function (e) { BV.toast(e.message); });
  }

  /* ---- rename / merge / tidy ---- */

  /* open a backup folder in the OS file manager (guarded to the library root) */
  function openLocation(path) {
    if (!path) { BV.toast("no folder on disk"); return; }
    BV.api.call("open_path", path).catch(function (e) { BV.toast(e.message); });
  }
  BV.openLocation = openLocation;   /* reused by the overview "open location" button */

  /* is there ANOTHER saved robot already at this name+line? (the merge target) */
  function collidesWithExisting(excludeId, name, line) {
    var nm = (name || "").toUpperCase(), ln = (line || "").toUpperCase();
    for (var i = 0; i < _robots.length; i++) {
      var e = _robots[i];
      if (e.id === excludeId) continue;
      if ((e.robot || "").toUpperCase() === nm && (e.line || "").toUpperCase() === ln) return e;
    }
    return null;
  }

  /* "fix names from backups": auto-rename the clean ones, then prompt to merge any
     duplicates. Acts on the line's selected robots. */
  function fixNamesInLine(lineRobots) {
    var sel = selectedInLine(lineRobots);
    if (!sel.length) { BV.toast("select robots first"); return; }
    var ids = sel.map(function (r) { return r.id; });

    function clearSel() { ids.forEach(function (id) { delete _selected[id]; }); }
    function done(nRenamed, nMerged) {
      var parts = [];
      if (nRenamed) parts.push("renamed " + nRenamed);
      if (nMerged) parts.push("merged " + nMerged);
      BV.toast(parts.length ? parts.join(" · ") : "no changes");
      clearSel();
      refresh();
    }

    BV.api.call("lib_resolve_names", ids).then(function (res) {
      var items = (res && res.items) || [];
      var renames = items.filter(function (it) { return it.action === "rename"; });
      var merges = items.filter(function (it) { return it.action === "merge"; });
      if (!renames.length && !merges.length) { BV.toast("names already match the backups"); return; }

      var step = renames.length
        ? BV.api.call("lib_apply_renames", renames.map(function (it) {
            return { id: it.id, plant: it.plant, line: it.line, robot: it.proposed };
          }))
        : Promise.resolve({ renamed: [], merged: [], failed: [] });

      step.then(function (rr) {
        var nRenamed = (rr.renamed || []).length;
        if ((rr.failed || []).length) BV.toast((rr.failed.length) + " rename(s) failed");
        if (!merges.length) { done(nRenamed, (rr.merged || []).length); return; }
        confirmMergeBatch(merges, function () {
          var byTarget = {};
          merges.forEach(function (it) {
            (byTarget[it.merge_into] = byTarget[it.merge_into] || []).push(it.id);
          });
          Promise.all(Object.keys(byTarget).map(function (primId) {
            return BV.api.call("lib_merge", primId, byTarget[primId]);
          })).then(function (results) {
            var nMerged = results.reduce(function (a, r) { return a + ((r.merged || []).length); }, 0);
            done(nRenamed, nMerged);
          }).catch(function (e) { BV.toast(e.message); refresh(); });
        }, function () { done(nRenamed, 0); });   /* user skipped the merges */
      }).catch(function (e) { BV.toast(e.message); refresh(); });
    }).catch(function (e) { BV.toast(e.message); });
  }

  /* explicit merge of exactly 2 selected robots (always previews) */
  function mergeSelectedInLine(lineRobots) {
    var sel = selectedInLine(lineRobots);
    if (sel.length !== 2) { BV.toast("select exactly 2 robots to merge"); return; }
    var a = sel[0], b = sel[1];
    if ((a.line || "").toUpperCase() !== (b.line || "").toUpperCase()) {
      BV.toast("can't merge across lines"); return;
    }
    /* keep the richer history's id as the primary */
    var primary = ((a.backups || []).length >= (b.backups || []).length) ? a : b;
    var secondary = (primary === a) ? b : a;
    confirmSingleMerge(secondary, primary, function () {
      BV.api.call("lib_merge", primary.id, [secondary.id]).then(function (res) {
        if ((res.refused || []).length) { BV.toast("refused — can't merge across lines"); refresh(); return; }
        delete _selected[a.id]; delete _selected[b.id];
        var m = (res.merged || [])[0] || {};
        var skipped = (m.skipped || []).length, conflicts = (m.conflicts || []).length;
        var msg = "merged " + (secondary.robot || "") + " into " + (primary.robot || "");
        if (skipped) msg += " · " + skipped + " duplicate" + (skipped === 1 ? "" : "s") + " skipped";
        if (conflicts) msg += " · " + conflicts + " conflict" + (conflicts === 1 ? "" : "s") + " kept";
        BV.toast(msg);
        refresh();
      }).catch(function (e) { BV.toast(e.message); });
    });
  }

  /* the batched "Duplicate robots detected. Merge?" confirm (fix-names path) */
  function confirmMergeBatch(merges, onConfirm, onSkip) {
    var body = BV.el("div", { class: "lib-form" });
    body.appendChild(BV.el("div", { class: "del-warn" },
      "Duplicate robots detected. Merge them into the matching robot? " +
      "Backups are combined; identical snapshots are skipped."));
    var list = BV.el("ul", { class: "merge-list" });
    var byId = {};
    _robots.forEach(function (e) { byId[e.id] = e; });
    merges.forEach(function (it) {
      var into = (byId[it.merge_into] || {}).robot || it.proposed;
      list.appendChild(BV.el("li", null,
        BV.esc(it.current || "(unnamed)") + " → " + BV.esc(into)));
    });
    body.appendChild(list);
    var acts = BV.el("div", { class: "lf-actions" });
    var skip = BV.el("button", { class: "btn" }, "skip merge");
    var go = BV.el("button", { class: "btn primary" }, "merge");
    acts.appendChild(skip); acts.appendChild(go); body.appendChild(acts);
    var m = BV.modal("merge duplicates", body);
    skip.addEventListener("click", function () { m.close(); if (onSkip) onSkip(); });
    go.addEventListener("click", function () { m.close(); onConfirm(); });
  }

  /* single "are you sure?" merge confirm (explicit merge + edit-modal collision) */
  function confirmSingleMerge(secondary, primary, onConfirm) {
    var body = BV.el("div", { class: "lib-form" });
    body.appendChild(BV.el("div", { class: "del-warn" },
      "Merge <b>" + BV.esc(secondary.robot || "(unnamed)") + "</b> into <b>" +
      BV.esc(primary.robot || "(unnamed)") + "</b>? Their backups are combined under " +
      BV.esc(primary.robot || "this robot") + "; identical snapshots are skipped and " +
      BV.esc(secondary.robot || "the other") + " is removed."));
    var acts = BV.el("div", { class: "lf-actions" });
    var cancel = BV.el("button", { class: "btn" }, "cancel");
    var go = BV.el("button", { class: "btn primary" }, "merge");
    acts.appendChild(cancel); acts.appendChild(go); body.appendChild(acts);
    var m = BV.modal("merge robots", body);
    cancel.addEventListener("click", m.close);
    go.addEventListener("click", function () { m.close(); onConfirm(); });
  }

  /* delete-from-disk: two confirmations — "are you sure" then "type the name" */
  function deleteFromDiskFlow(r) {
    var b1 = BV.el("div", { class: "lib-form" });
    b1.appendChild(BV.el("div", { class: "del-warn" },
      "Delete <b>" + BV.esc(r.robot || "(unnamed)") +
      "</b> and ALL of its backups from disk? This cannot be undone."));
    var a1 = BV.el("div", { class: "lf-actions" });
    var c1 = BV.el("button", { class: "btn" }, "cancel");
    var go1 = BV.el("button", { class: "btn danger" }, "continue");
    a1.appendChild(c1); a1.appendChild(go1); b1.appendChild(a1);
    var m1 = BV.modal("delete from disk", b1);
    c1.addEventListener("click", m1.close);
    go1.addEventListener("click", function () { m1.close(); confirmDeleteByName(r); });
  }

  function confirmDeleteByName(r) {
    var b2 = BV.el("div", { class: "lib-form" });
    b2.appendChild(BV.el("div", { class: "del-warn" },
      "Type the robot name <b>" + BV.esc(r.robot || "") + "</b> to permanently delete it:"));
    var name = inp("", { placeholder: r.robot || "" });
    b2.appendChild(field("robot name", name));
    var a2 = BV.el("div", { class: "lf-actions" });
    var c2 = BV.el("button", { class: "btn" }, "cancel");
    var del = BV.el("button", { class: "btn danger" }, "delete");
    del.disabled = true;
    a2.appendChild(c2); a2.appendChild(del); b2.appendChild(a2);
    var m2 = BV.modal("confirm deletion", b2);
    name.focus();
    function matches() { return name.value.trim() === (r.robot || "").trim(); }
    name.addEventListener("input", function () { del.disabled = !matches(); });
    c2.addEventListener("click", m2.close);
    del.addEventListener("click", function () {
      if (!matches()) return;
      del.disabled = true;
      BV.api.call("lib_delete_files", r.id).then(function (res) {
        m2.close();
        var n = (res.removed || []).length, ref = (res.refused || []).length;
        BV.toast(n ? "deleted " + n + " folder" + (n === 1 ? "" : "s") + " from disk"
          : (ref ? "removed from library · " + ref + " folder(s) outside the library root were left"
                 : "removed from library"));
        delete _selected[r.id];
        refresh();
      }).catch(function (e) { BV.toast(e.message); del.disabled = false; });
    });
  }

  /* ---- multi-backup ---- */

  function statusText(p) {
    return {
      connecting: "connecting…", listing: "listing files…", downloading: "downloading…",
      done: "done", error: "failed", cancelled: "cancelled", pending: "starting…",
    }[p.status] || p.status;
  }

  function startLineBackup(lineRobots) {
    var sel = selectedInLine(lineRobots);
    if (!sel.length) { BV.toast("select robots first"); return; }
    var runnable = sel.filter(function (r) { return r.ips && r.ips[0]; });
    var noip = sel.length - runnable.length;
    if (!runnable.length) { BV.toast("no IP on selected robot(s)"); return; }

    var needsPw = runnable.some(function (r) { return r.ftp && r.ftp.user; });
    promptSharedPassword(needsPw, function (pw) {
      runnable.forEach(function (r) {
        var spec = {
          host: r.ips[0], robot: r.robot, line: r.line, plant: r.plant,
          user: (r.ftp && r.ftp.user) || "",
          passive: !r.ftp || r.ftp.passive !== false,
          passwd: (r.ftp && r.ftp.user) ? pw : "",
          note: "",
        };
        renderRowProgress(r.id, { status: "pending", total: 0, done: 0 });
        BV.api.call("start_backup", spec).then(function (res) {
          _active[res.job_id] = { robotId: r.id };
          setCancelAllVisible(true);
          ensurePoller();
        }).catch(function (e) {
          var slot = rowProgressSlot(r.id);
          if (slot) slot.innerHTML = '<div class="lib-robot-result err">✗ ' + BV.esc(e.message) + "</div>";
        });
        delete _selected[r.id];
      });
      syncSelectionUI();
      if (noip) BV.toast(noip + " skipped · no IP");
    });
  }

  /* one shared password prompt for the whole batch (FANUC default is anonymous) */
  function promptSharedPassword(needed, cont) {
    if (!needed) { cont(""); return; }
    var body = BV.el("div", { class: "lib-form" });
    var pw = BV.el("input", { type: "password", class: "lf-input", spellcheck: "false" });
    var row = BV.el("div", { class: "lf-row" });
    row.appendChild(BV.el("label", null, "password"));
    row.appendChild(pw);
    body.appendChild(row);
    var acts = BV.el("div", { class: "lf-actions" });
    var cancel = BV.el("button", { class: "btn" }, "cancel");
    var ok = BV.el("button", { class: "btn primary" }, "connect");
    acts.appendChild(cancel);
    acts.appendChild(ok);
    body.appendChild(acts);
    var m = BV.modal("ftp password (shared)", body);
    pw.focus();
    cancel.addEventListener("click", m.close);
    function go() { var v = pw.value; m.close(); cont(v); }
    ok.addEventListener("click", go);
    body.addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
  }

  function rowProgressSlot(robotId) {
    if (!_libWrap) return null;
    var row = _libWrap.querySelector('.lib-robot[data-robot-id="' + robotId + '"]');
    return row ? row.querySelector(".lib-robot-progress") : null;
  }

  function renderRowProgress(robotId, p) {
    var slot = rowProgressSlot(robotId);
    if (!slot) return;
    if (p.status === "done" || p.status === "error" || p.status === "cancelled") {
      var cls, txt;
      if (p.status === "done") { cls = "ok"; txt = "✓ " + p.done + " files"; }
      else if (p.status === "cancelled") { cls = ""; txt = "cancelled"; }
      else { cls = "err"; txt = "✗ " + (p.error || "failed"); }
      slot.innerHTML = '<div class="lib-robot-result ' + cls + '">' + BV.esc(txt) + "</div>";
      return;
    }
    var pct = p.total ? Math.round(100 * p.done / p.total) : 8;
    var html = '<div class="membar"><div class="mb-label"><span>' + BV.esc(statusText(p)) +
      "</span><span>" + (p.total ? p.done + " / " + p.total : "") + "</span></div>" +
      '<div class="mb-track"><div class="mb-fill" style="width:' + pct + '%"></div></div></div>';
    if (p.current) html += '<div class="bf-current dim">' + BV.esc(p.current) + "</div>";
    slot.innerHTML = html;
  }

  function setCancelAllVisible(v) {
    var b = _libWrap && _libWrap.querySelector("#lib-cancel-all");
    if (b) b.classList.toggle("hidden", !v);
  }

  function cancelAllBackups() {
    Object.keys(_active).forEach(function (jobId) {
      BV.api.call("cancel_backup", jobId).catch(function () {});
    });
    BV.toast("cancelling backups…");
  }

  /* a single 500ms poll drives every in-flight job's row. It stops itself when
     nothing is active or the library view is detached (jobs keep running server-
     side; reattachProgress() repaints them when #home is shown again). */
  function ensurePoller() {
    if (_poll) return;
    _poll = setInterval(function () {
      if (!_libWrap || !document.body.contains(_libWrap)) { clearInterval(_poll); _poll = null; return; }
      var ids = Object.keys(_active);
      if (!ids.length) { clearInterval(_poll); _poll = null; setCancelAllVisible(false); return; }
      ids.forEach(function (jobId) {
        BV.api.call("get_backup_progress", jobId).then(function (p) {
          if (!_active[jobId]) return;
          renderRowProgress(_active[jobId].robotId, p);
          if (p.status === "done" || p.status === "error" || p.status === "cancelled") {
            delete _active[jobId];
            if (!Object.keys(_active).length) { setCancelAllVisible(false); BV.toast("backups finished"); }
          }
        }).catch(function () {
          delete _active[jobId];
          if (!Object.keys(_active).length) setCancelAllVisible(false);
        });
      });
    }, 500);
  }

  /* after any (re)render, repaint backups that are still running */
  function reattachProgress() {
    var ids = Object.keys(_active);
    if (!ids.length) return;
    setCancelAllVisible(true);
    ensurePoller();
    ids.forEach(function (jobId) {
      BV.api.call("get_backup_progress", jobId).then(function (p) {
        if (_active[jobId]) renderRowProgress(_active[jobId].robotId, p);
      }).catch(function () {});
    });
  }

  /* ---- add / edit modal ---- */

  function inp(value, attrs) {
    var a = { type: "text", value: value || "", spellcheck: "false", class: "lf-input" };
    if (attrs) Object.keys(attrs).forEach(function (k) { a[k] = attrs[k]; });
    return BV.el("input", a);
  }
  function field(label, el) {
    var row = BV.el("div", { class: "lf-row" });
    row.appendChild(BV.el("label", null, BV.esc(label)));
    row.appendChild(el);
    return row;
  }

  function editRobotModal(entry, isNew) {
    entry = entry || {};
    var form = BV.el("div", { class: "lib-form" });

    var fPlant = inp(entry.plant);
    var fLine = inp(entry.line);
    var fRobot = inp(entry.robot || entry.robot_name);
    var fModel = inp(entry.model);
    var fIps = inp((entry.ips || []).join(", "));
    var fPath = inp(entry.latest_path, entry.latest_path ? { readonly: "readonly" } : null);
    var fUser = inp((entry.ftp || {}).user);
    var fPassive = BV.el("input", { type: "checkbox", class: "lf-check" });
    if (!entry.ftp || entry.ftp.passive !== false) fPassive.checked = true;
    var fNotes = inp(entry.notes);
    var hasFolders = !isNew && !!entry.history_root;
    var fMove = BV.el("input", { type: "checkbox", class: "lf-check" });
    fMove.checked = true;   /* default ON: folders rename WITH the entry */

    form.appendChild(field("plant", fPlant));
    form.appendChild(field("line", fLine));
    form.appendChild(field("robot", fRobot));
    form.appendChild(field("model", fModel));
    form.appendChild(field("ip(s)", fIps));
    form.appendChild(field("folder", fPath));
    form.appendChild(field("ftp user", fUser));
    form.appendChild(field("passive ftp", fPassive));
    form.appendChild(field("notes", fNotes));
    if (hasFolders) form.appendChild(field("also move backup folders", fMove));

    var actions = BV.el("div", { class: "lf-actions" });
    var cancel = BV.el("button", { class: "btn" }, "cancel");
    var save = BV.el("button", { class: "btn primary" }, isNew ? "add" : "save");
    actions.appendChild(cancel);
    actions.appendChild(save);
    form.appendChild(actions);

    var m = BV.modal(isNew ? "add robot" : "edit robot", form);
    cancel.addEventListener("click", m.close);
    fRobot.focus();

    save.addEventListener("click", function () {
      var robot = fRobot.value.trim();
      if (!robot) { BV.toast("robot name required"); return; }
      var fields = {
        plant: fPlant.value.trim(), line: fLine.value.trim(),
        robot: robot, model: fModel.value.trim(),
        ips: fIps.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean),
        latest_path: fPath.value.trim(), notes: fNotes.value.trim(),
        ftp: { user: fUser.value.trim(), passive: fPassive.checked },
      };
      if (isNew) {
        var draft = {
          f_number: entry.f_number || "", backup_type: entry.backup_type || "",
          // preserve dated history + robot folder discovered while scanning
          backups: entry.backups || [], history_root: entry.history_root || "",
        };
        Object.keys(fields).forEach(function (k) { draft[k] = fields[k]; });
        BV.api.call("lib_add", draft)
          .then(function () { m.close(); BV.toast("added"); refresh(); })
          .catch(function (e) { BV.toast(e.message); });
        return;
      }

      var idChanged = fields.plant !== (entry.plant || "") ||
                      fields.line !== (entry.line || "") ||
                      fields.robot !== (entry.robot || "");
      var moveFolders = hasFolders && fMove.checked && idChanged;

      if (!moveFolders) {
        BV.api.call("lib_update", entry.id, fields)
          .then(function () { m.close(); BV.toast("saved"); refresh(); })
          .catch(function (e) { BV.toast(e.message); });
        return;
      }

      /* identity changed AND "move folders" on: relocate the tree, then write the
         non-identity fields onto the surviving entry. A name+line collision is a
         merge — confirm it first (merges always confirm). */
      function relocateThenSave() {
        BV.api.call("lib_relocate", entry.id, fields.plant, fields.line, fields.robot)
          .then(function (res) {
            var survivingId = (res && res.id) || entry.id;
            BV.api.call("lib_update", survivingId, fields)
              .then(function () {
                m.close();
                BV.toast(res.action === "merged" ? "merged & saved" : "moved & saved");
                refresh();
              })
              .catch(function (e) { m.close(); BV.toast(e.message); refresh(); });
          })
          .catch(function (e) { BV.toast(e.message); });
      }

      var collide = collidesWithExisting(entry.id, fields.robot, fields.line);
      if (collide) {
        confirmSingleMerge({ robot: fields.robot }, collide, relocateThenSave);
      } else {
        relocateThenSave();
      }
    });
  }

  /* picked-folder -> draft -> add modal. A folder holding several dated
     snapshots of one robot returns a single draft with its history; one holding
     several robots returns {multi, drafts} and routes to a bulk confirm. */
  BV.addToLibraryFlow = function () {
    BV.api.call("pick_backup_folder").then(function (path) {
      if (!path) return null;
      return BV.api.call("lib_scan_folder", path).then(function (res) {
        if (res && res.multi) multiAddModal(res.drafts || []);
        else editRobotModal(res, true);
      });
    }).catch(function (e) { BV.toast(e.message); });
  };

  /* several robots found under one picked folder -> add them all under a shared
     plant/line (each draft already carries its own dated history). */
  function multiAddModal(drafts) {
    if (!drafts.length) { BV.toast("no backups found in that folder"); return; }
    var body = BV.el("div", { class: "lib-form" });
    body.appendChild(BV.el("div", { class: "scan-info dim" },
      drafts.length + " robots found in that folder — add them all?"));
    var list = BV.el("div", { class: "scan-results" });
    drafts.forEach(function (d) {
      var meta = [];
      if (d.model) meta.push(BV.esc(d.model));
      if (d.backups && d.backups.length) meta.push(d.backups.length + " backup" + (d.backups.length === 1 ? "" : "s"));
      var row = BV.el("div", { class: "scan-row" });
      row.innerHTML = '<span class="lib-robot-name">' + BV.esc(d.robot || "(unnamed)") + "</span>" +
        (meta.length ? ' <span class="lib-robot-meta">' + meta.join(" · ") + "</span>" : "");
      list.appendChild(row);
    });
    body.appendChild(list);
    var fPlant = inp(""), fLine = inp("");
    body.appendChild(field("plant", fPlant));
    body.appendChild(field("line", fLine));
    var actions = BV.el("div", { class: "lf-actions" });
    var cancel = BV.el("button", { class: "btn" }, "cancel");
    var add = BV.el("button", { class: "btn primary" }, "add " + drafts.length);
    actions.appendChild(cancel); actions.appendChild(add);
    body.appendChild(actions);
    var m = BV.modal("add robots from folder", body);
    cancel.addEventListener("click", m.close);
    add.addEventListener("click", function () {
      add.disabled = true;
      BV.api.call("lib_bulk_add", drafts, fPlant.value.trim(), fLine.value.trim()).then(function (r) {
        m.close();
        var added = (r.added || []).length, skipped = (r.skipped || []).length;
        BV.toast("added " + added + (skipped ? " · skipped " + skipped + " already in library" : ""));
        refresh();
      }).catch(function (e) { BV.toast(e.message); add.disabled = false; });
    });
  }

  /* ---- shared scan progress (bulk folder + network discover) ---- */

  function scanStatusText(p) {
    return {
      pending: "starting…", scanning: "scanning…",
      done: "done", error: "failed", cancelled: "cancelled",
    }[p.status] || p.status;
  }

  function renderScanBar(el, p) {
    var running = p.status === "pending" || p.status === "scanning";
    var pct = p.total ? Math.round(100 * p.scanned / p.total) : (running ? 8 : 100);
    var html = '<div class="membar"><div class="mb-label"><span>' + BV.esc(scanStatusText(p)) +
      "</span><span>" + (p.total ? p.scanned + " / " + p.total : "") +
      (p.found ? " · " + p.found + " found" : "") + "</span></div>" +
      '<div class="mb-track"><div class="mb-fill" style="width:' + pct + '%"></div></div></div>';
    if (running && p.current) html += '<div class="bf-current dim">' + BV.esc(p.current) + "</div>";
    el.innerHTML = html;
  }

  /* poll one scan job every 500ms; onTick each poll, onDone at a terminal state.
     returns a stop() that halts polling (the modal calls it + cancel_scan on close) */
  function pollScan(jobId, onTick, onDone) {
    var iv = setInterval(function () {
      BV.api.call("scan_progress", jobId).then(function (p) {
        onTick(p);
        if (p.status === "done" || p.status === "error" || p.status === "cancelled") {
          clearInterval(iv);
          onDone(p);
        }
      }).catch(function () {
        clearInterval(iv);
        onDone({ status: "error", error: "scan lost", results: [] });
      });
    }, 500);
    return function stop() { clearInterval(iv); };
  }

  /* ---- bulk add from a parent folder ---- */

  function bulkAddFlow() {
    BV.api.call("pick_backup_folder").then(function (path) {
      if (path) bulkAddModal(path);
    }).catch(function (e) { BV.toast(e.message); });
  }

  function bulkAddModal(path) {
    var body = BV.el("div", { class: "lib-form" });
    var info = BV.el("div", { class: "scan-info dim" }, "scanning " + BV.esc(path) + " …");
    var bar = BV.el("div", { class: "scan-bar" });
    var found = BV.el("div", { class: "scan-results" });
    var fPlant = inp(""), fLine = inp("");
    var actions = BV.el("div", { class: "lf-actions" });
    var cancelBtn = BV.el("button", { class: "btn" }, "cancel");
    var addBtn = BV.el("button", { class: "btn primary" }, "add");
    addBtn.disabled = true;
    actions.appendChild(cancelBtn);
    actions.appendChild(addBtn);
    body.appendChild(info);
    body.appendChild(bar);
    body.appendChild(found);
    body.appendChild(field("plant", fPlant));
    body.appendChild(field("line", fLine));
    body.appendChild(actions);

    var results = [], jobId = null, stop = null;
    var m = BV.modal("bulk add from folder", body, {
      onClose: function () { if (stop) stop(); if (jobId) BV.api.call("cancel_scan", jobId).catch(function () {}); },
    });
    cancelBtn.addEventListener("click", m.close);

    BV.api.call("lib_bulk_scan_start", path).then(function (res) {
      jobId = res.job_id;
      stop = pollScan(jobId, function (p) { renderScanBar(bar, p); }, function (p) {
        renderScanBar(bar, p);
        results = p.results || [];
        if (p.status !== "done") { info.textContent = "scan " + scanStatusText(p) + (p.error ? ": " + p.error : ""); return; }
        info.textContent = results.length
          ? results.length + " backup" + (results.length === 1 ? "" : "s") + " found — enter a plant & line"
          : "no backups found in this folder";
        found.innerHTML = "";
        results.forEach(function (d) {
          var row = BV.el("div", { class: "scan-row" });
          var meta = [];
          if (d.model) meta.push(BV.esc(d.model));
          if (d.backup_type && d.backup_type !== "unknown") meta.push(BV.esc(d.backup_type));
          row.innerHTML = '<span class="lib-robot-name">' + BV.esc(d.robot || "(unnamed)") + "</span>" +
            (meta.length ? ' <span class="lib-robot-meta">' + meta.join(" · ") + "</span>" : "");
          found.appendChild(row);
        });
        addBtn.disabled = results.length === 0;
        addBtn.textContent = results.length ? "add " + results.length : "add";
      });
    }).catch(function (e) { info.textContent = e.message; });

    addBtn.addEventListener("click", function () {
      if (!results.length) return;
      addBtn.disabled = true;
      BV.api.call("lib_bulk_add", results, fPlant.value.trim(), fLine.value.trim()).then(function (r) {
        m.close();
        var added = (r.added || []).length, skipped = (r.skipped || []).length;
        BV.toast("added " + added + (skipped ? " · skipped " + skipped + " already in library" : ""));
        refresh();
      }).catch(function (e) { BV.toast(e.message); addBtn.disabled = false; });
    });
  }

  /* ---- discover robots on the network ---- */

  function discoverFlow() {
    var body = BV.el("div", { class: "lib-form" });

    /* network picker: an adapter dropdown (default = connected ethernet) with an
       "advanced" toggle that reveals the raw subnet/port dials for power users. */
    var adapters = [], chosenCidr = "";
    var adapterBtn = BV.el("button", { class: "btn disc-adapter", type: "button" }, "detecting…");
    var advToggle = BV.el("button", { class: "disc-advanced", type: "button" }, "advanced ▸");
    var advBox = BV.el("div", { class: "disc-adv-box hidden" });
    var fSubnet = inp("", { placeholder: "192.168.1.0/24" });
    var fPort = inp("21", { placeholder: "21" });
    advBox.appendChild(field("subnet", fSubnet));
    advBox.appendChild(field("port", fPort));

    var fPlant = inp(""), fLine = inp("");
    var bar = BV.el("div", { class: "scan-bar" });
    var selRow = BV.el("div", { class: "scan-selall hidden" });
    var selAll = BV.el("input", { type: "checkbox", class: "lf-check" });
    selRow.appendChild(selAll);
    selRow.appendChild(BV.el("span", null, "select all"));
    var list = BV.el("div", { class: "scan-results" });
    var actions = BV.el("div", { class: "lf-actions" });
    var scanBtn = BV.el("button", { class: "btn" }, "scan");
    var addBtn = BV.el("button", { class: "btn primary" }, "add");
    addBtn.disabled = true;
    actions.appendChild(scanBtn);
    actions.appendChild(addBtn);
    body.appendChild(field("network", adapterBtn));
    body.appendChild(advToggle);
    body.appendChild(advBox);
    body.appendChild(field("plant", fPlant));
    body.appendChild(field("line", fLine));
    body.appendChild(bar);
    body.appendChild(selRow);
    body.appendChild(list);
    body.appendChild(actions);

    var advOpen = false;
    function setAdvanced(open) {
      advOpen = open;
      advBox.classList.toggle("hidden", !open);
      advToggle.textContent = open ? "advanced ▾" : "advanced ▸";
    }
    advToggle.addEventListener("click", function () { setAdvanced(!advOpen); });

    function adapterLabel(a) {
      return a.name + " · " + a.kind + " · " + a.ip + "/" + ((a.cidr || "").split("/")[1] || "24");
    }
    function setChosen(cidr, label) {
      chosenCidr = cidr || "";
      adapterBtn.textContent = label || (cidr || "auto (local subnet)");
      if (chosenCidr) fSubnet.value = chosenCidr;   /* keep the advanced field in sync */
    }
    adapterBtn.addEventListener("click", function () {
      var items = [];
      adapters.forEach(function (a) {
        if (!a.cidr) return;
        items.push({ label: adapterLabel(a), onClick: function () { setChosen(a.cidr, adapterLabel(a)); } });
      });
      items.push({ label: "enter manually…", onClick: function () {
        setAdvanced(true); setChosen("", "manual"); fSubnet.focus();
      } });
      BV.menu(adapterBtn, items);
    });

    var found = [], sel = {}, jobId = null, stop = null, scanning = false;
    var m = BV.modal("discover on network", body, {
      onClose: function () { if (stop) stop(); if (jobId) BV.api.call("cancel_scan", jobId).catch(function () {}); },
    });

    /* populate adapters; default to the connected ethernet, else the local /24 */
    BV.api.call("list_adapters").then(function (res) {
      adapters = (res && res.adapters) || [];
      var def = null, i;
      for (i = 0; i < adapters.length; i++) { if (adapters[i].default && adapters[i].cidr) { def = adapters[i]; break; } }
      if (!def) { for (i = 0; i < adapters.length; i++) { if (adapters[i].cidr) { def = adapters[i]; break; } } }
      if (def) { setChosen(def.cidr, adapterLabel(def)); return; }
      var fb = (res && res.fallback) || {};
      setChosen(fb.cidr || "", fb.cidr ? "auto · " + fb.cidr : "auto (local subnet)");
      if (!adapters.length) setAdvanced(true);   /* no NICs enumerated: show manual dials */
    }).catch(function () {
      BV.api.call("local_subnet").then(function (s) {
        if (s && s.cidr) setChosen(s.cidr, "auto · " + s.cidr);
      }).catch(function () {});
    });

    function updateAddBtn() {
      var n = found.filter(function (h) { return sel[h.host]; }).length;
      addBtn.disabled = n === 0;
      addBtn.textContent = n ? "add " + n : "add";
      var on = found.length && found.every(function (h) { return sel[h.host]; });
      selAll.checked = !!on;
      selAll.indeterminate = !on && found.some(function (h) { return sel[h.host]; });
    }

    function renderList() {
      selRow.classList.toggle("hidden", found.length === 0);
      list.innerHTML = "";
      found.forEach(function (h) {
        var row = BV.el("div", { class: "scan-row" });
        var cb = BV.el("input", { type: "checkbox", class: "lf-check" });
        cb.checked = !!sel[h.host];
        cb.addEventListener("change", function () { if (cb.checked) sel[h.host] = true; else delete sel[h.host]; updateAddBtn(); });
        row.appendChild(cb);
        var label = '<span class="lib-robot-name">' + BV.esc(h.name || h.host) + "</span>";
        var meta = [BV.esc(h.host)];
        if (h.has_md) meta.push(BV.pill("MD", "acc"));
        if (h.has_fr) meta.push(BV.pill("FR", "acc"));
        label += ' <span class="lib-robot-meta">' + meta.join(" · ") + "</span>";
        row.appendChild(BV.el("div", { class: "lib-robot-main" }, label));
        list.appendChild(row);
      });
      updateAddBtn();
    }

    selAll.addEventListener("change", function () {
      var on = selAll.checked;
      found.forEach(function (h) { if (on) sel[h.host] = true; else delete sel[h.host]; });
      renderList();
    });

    scanBtn.addEventListener("click", function () {
      if (scanning) { if (jobId) BV.api.call("cancel_scan", jobId).catch(function () {}); return; }
      var cidr = advOpen ? fSubnet.value.trim() : (chosenCidr || fSubnet.value.trim());
      var port = parseInt(fPort.value, 10) || 21;
      found = []; sel = {}; renderList();
      scanning = true; scanBtn.textContent = "stop"; addBtn.disabled = true;
      BV.api.call("net_scan_start", { cidr: cidr, port: port }).then(function (res) {
        jobId = res.job_id;
        stop = pollScan(jobId, function (p) {
          renderScanBar(bar, p);
          if ((p.results || []).length !== found.length) { found = p.results || []; renderList(); }
        }, function (p) {
          renderScanBar(bar, p);
          found = p.results || []; renderList();
          scanning = false; scanBtn.textContent = "scan";
          if (p.status === "done" && !found.length) BV.toast("no FANUC robots found");
        });
      }).catch(function (e) { BV.toast(e.message); scanning = false; scanBtn.textContent = "scan"; });
    });

    addBtn.addEventListener("click", function () {
      var drafts = found.filter(function (h) { return sel[h.host]; }).map(function (h) {
        return { robot: h.name || h.host, model: h.model || "", f_number: h.f_number || "",
          ips: [h.host], ftp: { user: "", passive: true } };
      });
      if (!drafts.length) return;
      addBtn.disabled = true;
      BV.api.call("lib_bulk_add", drafts, fPlant.value.trim(), fLine.value.trim()).then(function (r) {
        m.close();
        var added = (r.added || []).length, skipped = (r.skipped || []).length;
        BV.toast("added " + added + (skipped ? " · skipped " + skipped + " already in library" : ""));
        refresh();
      }).catch(function (e) { BV.toast(e.message); addBtn.disabled = false; });
    });
  }

  BV.tabs = BV.tabs || [];
  BV.tabs.push({ id: "home", label: "home", render: render, hidden: true, always: true, shell: true });
})();
