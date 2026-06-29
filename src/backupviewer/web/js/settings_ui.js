/* settings_ui.js - font size + ui scale, persisted via the settings api.
   "too little information ... in too small of font" -> both knobs live here. */
(function () {
  "use strict";

  var FONT_SIZES = [12, 13, 14, 15, 16, 18];
  var SCALES = [0.85, 1.0, 1.1, 1.25, 1.4];
  /* shop-floor friendly defaults - old eyes and young eyes both read this */
  var DEFAULT_FONT = 15;
  var DEFAULT_SCALE = 1.1;
  /* switchable UI font. "mono" keeps the classic look; "rog" uses the bundled
     Orbitron display face (web/fonts) - applied only to UI chrome, never to data
     or code (those are pinned to --font-mono in css), so columns stay aligned. */
  var FONT_OPTIONS = [
    { id: "mono", label: "mono", css: "var(--font-mono)" },
    { id: "rog", label: "ROG", css: '"Orbitron", var(--font-mono)' },
  ];
  var DEFAULT_FONT_FAMILY = "mono";

  BV.uiPrefs = {
    apply: function (settings) {
      var fs = settings.font_size || DEFAULT_FONT;
      var sc = settings.ui_scale || DEFAULT_SCALE;
      var ff = settings.font_family || DEFAULT_FONT_FAMILY;
      var fopt = FONT_OPTIONS.find(function (o) { return o.id === ff; }) || FONT_OPTIONS[0];
      document.documentElement.style.setProperty("--font", fopt.css);
      document.documentElement.style.fontSize = fs + "px";
      document.body.style.fontSize = fs + "px";
      document.body.style.zoom = sc;
      /* #app divides its 100vh by this so the layout still fits the window
         exactly under zoom (vh units don't compensate for zoom) */
      document.documentElement.style.setProperty("--app-zoom", sc);
      /* accent panel borders on by default; "off" flattens the UI (see base.css .no-edges) */
      document.documentElement.classList.toggle("no-edges", settings.edges === false);
      BV.state.emit("uiprefs", settings);
    },

    modal: function () {
      var s = BV.state.settings || {};
      var body = BV.el("div");

      function segRow(label, values, current, fmt, onPick) {
        var rowEl = BV.el("div", { class: "set-row" });
        rowEl.appendChild(BV.el("span", { class: "name" }, BV.esc(label)));
        var seg = BV.el("div", { class: "seg" });
        values.forEach(function (v) {
          var b = BV.el("button", { class: v === current ? "active" : "" }, fmt(v));
          b.addEventListener("click", function () {
            seg.querySelectorAll("button").forEach(function (x) { x.classList.remove("active"); });
            b.classList.add("active");
            onPick(v);
          });
          seg.appendChild(b);
        });
        rowEl.appendChild(seg);
        body.appendChild(rowEl);
      }

      segRow("font size", FONT_SIZES, s.font_size || DEFAULT_FONT,
        function (v) { return v + "px"; },
        function (v) {
          s.font_size = v;
          BV.uiPrefs.apply(s);
          BV.api.call("set_setting", "font_size", v).catch(function () {});
        });

      segRow("ui scale", SCALES, s.ui_scale || DEFAULT_SCALE,
        function (v) { return Math.round(v * 100) + "%"; },
        function (v) {
          s.ui_scale = v;
          BV.uiPrefs.apply(s);
          BV.api.call("set_setting", "ui_scale", v).catch(function () {});
        });

      segRow("font", FONT_OPTIONS.map(function (o) { return o.id; }),
        s.font_family || DEFAULT_FONT_FAMILY,
        function (id) {
          var o = FONT_OPTIONS.find(function (x) { return x.id === id; });
          return o ? o.label : id;
        },
        function (id) {
          s.font_family = id;
          BV.uiPrefs.apply(s);
          BV.api.call("set_setting", "font_family", id).catch(function () {});
        });

      segRow("borders", [true, false], s.edges !== false,
        function (v) { return v ? "on" : "off"; },
        function (v) {
          s.edges = v;
          BV.uiPrefs.apply(s);
          BV.api.call("set_setting", "edges", v).catch(function () {});
        });

      /* library folder: the single root that is both the FTP backup destination
         and the tree the app scans to build the library. Changing it rescans. */
      var pathRow = BV.el("div", { class: "set-row" });
      pathRow.appendChild(BV.el("span", { class: "name" }, "library folder"));
      var pathWrap = BV.el("div", { class: "set-path" });
      var pathVal = BV.el("span", { class: "set-path-val dim" }, "…");
      var changeBtn = BV.el("button", { class: "btn" }, "change…");
      pathWrap.appendChild(pathVal);
      pathWrap.appendChild(changeBtn);
      pathRow.appendChild(pathWrap);
      body.appendChild(pathRow);

      function showPath(p) { pathVal.textContent = p || "(default)"; pathVal.title = p || ""; }
      BV.api.call("get_library_root").then(function (r) { showPath(r && r.path); }).catch(function () {});
      changeBtn.addEventListener("click", function () {
        BV.api.call("pick_library_root").then(function (p) {
          if (!p) return null;
          return BV.api.call("set_library_root", p).then(function (r) {
            showPath(r && r.path);
            BV.toast("library folder set — rescanning…");
            return BV.api.call("lib_rescan").then(function () { BV.toast("library updated"); });
          });
        }).catch(function (e) { BV.toast(e.message); });
      });

      BV.state.settings = s;
      BV.modal("display", body);
    },
  };
})();
