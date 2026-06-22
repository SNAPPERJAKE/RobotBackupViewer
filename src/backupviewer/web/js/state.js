/* state.js - app state: manifest of the open backup, per-tab data cache, pub/sub. */
(function () {
  "use strict";

  var listeners = {};

  BV.state = {
    manifest: null,        /* {path, name, file_count, robot_name, f_number, tabs:{}} */
    tabData: {},           /* tabId -> parsed payload (frontend cache) */
    settings: {},

    on: function (evt, fn) {
      (listeners[evt] = listeners[evt] || []).push(fn);
    },
    emit: function (evt, payload) {
      (listeners[evt] || []).forEach(function (fn) { fn(payload); });
    },

    setManifest: function (m) {
      BV.state.manifest = m;
      BV.state.tabData = {};
      BV.state.emit("manifest", m);
    },
  };

  /* in-session per-tab UI state (scroll, expand/collapse, sort, filters). Stored
     under tabData so it is wiped when a different backup opens (setManifest) -
     exactly the lifetime we want; survives navigating in/out of the tab. */
  BV.tabState = function (id) {
    return BV.state.tabData[id] || (BV.state.tabData[id] = {});
  };

  /* restore + persist a scroll container's position by key. Works for BOTH a
     persistent element (#view, reused across routes) and a fresh element (a
     VTable host rebuilt each render): exactly one listener per element, always
     re-pointed to whichever key currently owns it, so a stale tab's listener
     never clobbers another tab's saved position. Call AFTER content is mounted
     (so scrollHeight is established and the restore sticks synchronously - the
     hidden probe window runs no rAF). */
  BV.persistScroll = function (key, el) {
    if (!el) return;
    var st = BV.tabState(key);
    if (st._scroll) el.scrollTop = st._scroll;
    el._bvScrollKey = key;
    if (!el._bvScrollWired) {
      el._bvScrollWired = true;
      /* save synchronously (it's just a number) so the position is never lost to
         debounce timing - e.g. when the router resets scrollTop on the next route */
      el.addEventListener("scroll", function () {
        if (el._bvScrollKey) BV.tabState(el._bvScrollKey)._scroll = el.scrollTop;
      });
    }
  };
})();
