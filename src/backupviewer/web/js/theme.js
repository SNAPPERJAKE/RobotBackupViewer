/* theme.js - MonkeyType-style theming: a theme is ~9 colors applied as CSS vars. */
(function () {
  "use strict";

  var VAR_MAP = {
    bg: "--bg", bg2: "--bg2", sub: "--sub", subAlt: "--sub-alt",
    text: "--text", accent: "--accent", error: "--error", ok: "--ok", warn: "--warn",
  };

  BV.theme = {
    themes: [],
    activeId: null,

    apply: function (theme) {
      var root = document.documentElement;
      Object.keys(VAR_MAP).forEach(function (k) {
        if (theme.colors[k]) root.style.setProperty(VAR_MAP[k], theme.colors[k]);
      });
      BV.theme.activeId = theme.id;
      BV.state.emit("theme", theme);
    },

    applyById: function (id, persist) {
      var t = BV.theme.themes.find(function (x) { return x.id === id; });
      if (!t) return;
      BV.theme.apply(t);
      if (persist) BV.api.call("set_setting", "theme", id).catch(function () {});
    },

    load: function () {
      return BV.api.call("get_themes").then(function (data) {
        BV.theme.themes = data.themes;
        var active = data.themes.find(function (t) { return t.id === data.active; });
        if (active) BV.theme.apply(active);
        return data;
      });
    },

    cycle: function () {
      if (!BV.theme.themes.length) return;
      var i = BV.theme.themes.findIndex(function (t) { return t.id === BV.theme.activeId; });
      var next = BV.theme.themes[(i + 1) % BV.theme.themes.length];
      BV.theme.applyById(next.id, true);
      BV.toast(next.name);
    },

    picker: function () {
      if (!BV.theme.themes.length) { BV.toast("no themes loaded"); return; }
      var all = BV.theme.themes;
      var startId = BV.theme.activeId;
      var chosen = false;

      /* a theme's pack; legacy themes with no category fall under MonkeyType */
      function catOf(t) { return t.category || "MonkeyType"; }
      /* pay respect to where each pack came from - shown under the filter */
      var CREDITS = {
        "MonkeyType": "themes adapted from monkeytype.com",
        "Sports": "team & university colors © their respective owners",
        "Cyberpunk 2077": "inspired by Cyberpunk 2077 — © CD Projekt Red",
        "Vibes": "inspired by retro-futuristic gradient art",
      };

      /* distinct categories in first-seen order, with "All" first */
      var cats = ["All"];
      all.forEach(function (t) { var c = catOf(t); if (cats.indexOf(c) < 0) cats.push(c); });
      var activeCat = "All";

      var body = BV.el("div");
      var catBtn = BV.el("button", { class: "cat-btn" });
      var head = BV.el("div", { class: "picker-head" });
      head.appendChild(catBtn);
      var credit = BV.el("div", { class: "credit-line" });
      var rowsWrap = BV.el("div");
      body.appendChild(head);
      body.appendChild(credit);
      body.appendChild(rowsWrap);

      catBtn.addEventListener("click", function () {
        BV.menu(catBtn, cats.map(function (c) {
          return { label: c, onClick: function () { activeCat = c; rebuild(); } };
        }));
      });

      var visible = [];   /* current filtered list */
      var rows = [];      /* row els parallel to `visible` */
      var focused = 0;

      function rebuild() {
        visible = all.filter(function (t) { return activeCat === "All" || catOf(t) === activeCat; });
        catBtn.textContent = "category: " + activeCat;
        credit.textContent = CREDITS[activeCat] || "";
        rowsWrap.innerHTML = "";
        rows = visible.map(function (t, i) {
          var sw = ["bg", "accent", "text", "sub"].map(function (k) {
            return '<span class="swatch" style="background:' + BV.esc(t.colors[k] || "#000") + '"></span>';
          }).join("");
          var row = BV.el("div", { class: "opt-row" + (t.id === startId ? " sel" : "") },
            '<span class="name">' + BV.esc(t.name || t.id) + (t.user ? ' <span class="dim">(user)</span>' : "") + "</span>" +
            '<span class="swatches">' + sw + "</span>");
          row.addEventListener("mouseenter", function () { setFocus(i, false); BV.theme.applyById(t.id, false); });
          row.addEventListener("click", function () {
            chosen = true;
            BV.theme.applyById(t.id, true);
            modal.close();
          });
          rowsWrap.appendChild(row);
          return row;
        });
        /* keep the active theme focused if it's in this category, else the first row */
        var fi = visible.findIndex(function (t) { return t.id === BV.theme.activeId; });
        setFocus(fi >= 0 ? fi : 0, false);
      }

      function setFocus(i, preview) {
        if (!rows.length) { focused = 0; return; }
        focused = (i + rows.length) % rows.length;
        rows.forEach(function (r, j) { r.classList.toggle("focused", j === focused); });
        rows[focused].scrollIntoView({ block: "nearest" });
        if (preview) BV.theme.applyById(visible[focused].id, false);
      }

      var modal = BV.modal("select theme", body, {
        onClose: function () {
          /* if user escaped without choosing, restore the persisted theme */
          if (!chosen) BV.theme.applyById(startId, false);
        },
        onKey: function (e, close) {
          if (e.key === "ArrowDown" || e.key === "j") { setFocus(focused + 1, true); return true; }
          if (e.key === "ArrowUp" || e.key === "k") { setFocus(focused - 1, true); return true; }
          if (e.key === "Enter") {
            if (!visible.length) return true;
            chosen = true;
            BV.theme.applyById(visible[focused].id, true);
            close();
            return true;
          }
          return false;
        },
      });

      rebuild();
    },
  };
})();
