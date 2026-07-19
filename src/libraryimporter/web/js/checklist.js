/* components/checklist.js - ONE multiselect for every checkbox list.
   Every checklist in the app (library robot rows, per-line select-alls, the
   fix-names / merge previews, discover results) shares this controller, so
   selection behaves identically everywhere:
     - click toggles one row
     - shift+click selects the visible range from the last-clicked row
       (file-manager convention: the whole range takes THIS click's new state;
       rows folded inside a collapsed group are never silently included)
     - a group box (select-all) is an honest tri-state: from empty it selects
       all, but ANY existing selection makes a click CLEAR — the "minus" state
       reads as "click to reset", never "click to select the rest"
   The controller owns selection STATE; callers own the DOM. Binding a key
   that is already bound replaces the old checkbox, so re-renders just re-bind
   and selection survives refreshes for free. */
(function () {
  "use strict";

  /* opts: {onChange()} — fired after every sync (selection repaint), so the
     caller can drive counters / button enablement from one place. */
  BV.checklist = function (opts) {
    opts = opts || {};
    var sel = {};        /* selected keys (object used as a Set) */
    var anchor = null;   /* shift+click range anchor: the last-clicked KEY */
    var items = {};      /* key -> {cb, seq}; seq preserves render order across re-binds */
    var groups = {};     /* gkey -> {cb, keys()} select-all boxes */
    var seq = 0;

    function setOne(key, on) { if (on) sel[key] = true; else delete sel[key]; }

    /* the rows as the user SEES them: render order, skipping anything hidden
       (collapsed group, filtered out, or detached by a re-render) */
    function visibleKeys() {
      return Object.keys(items)
        .filter(function (k) { return items[k].cb.offsetParent !== null; })
        .sort(function (a, b) { return items[a].seq - items[b].seq; });
    }

    function sync() {
      Object.keys(items).forEach(function (k) { items[k].cb.checked = !!sel[k]; });
      Object.keys(groups).forEach(function (gk) {
        var g = groups[gk];
        var keys = g.keys() || [];
        var on = keys.filter(function (k) { return sel[k]; }).length;
        g.cb.checked = keys.length > 0 && on === keys.length;
        g.cb.indeterminate = on > 0 && on < keys.length;
      });
      if (opts.onChange) opts.onChange();
    }

    var api = {
      /* wire a row checkbox to a key. Returns the checkbox for chaining. */
      bind: function (cb, key) {
        items[key] = { cb: cb, seq: seq++ };
        if (!cb.title) cb.title = "select (shift+click selects a range)";
        cb.checked = !!sel[key];
        cb.addEventListener("click", function (e) {
          e.stopPropagation();               /* row-click actions stay separate */
          var on = cb.checked;               /* the checkbox has already toggled */
          var keys = null, a = -1, b = -1;
          if (e.shiftKey && anchor && anchor !== key) {
            keys = visibleKeys();
            a = keys.indexOf(anchor);
            b = keys.indexOf(key);
          }
          if (keys && a >= 0 && b >= 0 && a !== b) {
            var lo = Math.min(a, b), hi = Math.max(a, b);
            for (var i = lo; i <= hi; i++) setOne(keys[i], on);
          } else {
            setOne(key, on);                 /* anchor folded away -> plain toggle */
          }
          anchor = key;
          sync();
        });
        return cb;
      },

      /* wire a select-all box over keysFn()'s CURRENT keys (call-time, so the
         group tracks whatever the caller renders). gkey dedupes across
         re-renders the same way bind does. */
      group: function (cb, keysFn, gkey) {
        groups[gkey || "all"] = { cb: cb, keys: keysFn };
        cb.addEventListener("change", function () {
          var keys = keysFn() || [];
          var any = keys.some(function (k) { return sel[k]; });
          keys.forEach(function (k) { setOne(k, !any); });   /* any -> clear; none -> all */
          sync();
        });
        return cb;
      },

      has: function (key) { return !!sel[key]; },
      set: function (key, on) { setOne(key, on); },   /* no repaint — sync() after a batch */
      clear: function () { sel = {}; anchor = null; },
      selected: function () { return Object.keys(sel); },
      size: function () { return Object.keys(sel).length; },
      sync: sync,
    };
    return api;
  };
})();
