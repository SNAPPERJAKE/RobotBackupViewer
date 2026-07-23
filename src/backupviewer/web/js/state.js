/* state.js - app state: manifest of the open backup, per-tab data cache, pub/sub. */
(function () {
  "use strict";

  var listeners = {};
  /* per-backup UI-memory buckets, keyed by manifest.path. setManifest POINTS
     tabData at the open backup's bucket instead of wiping, so switching
     between session tabs restores each backup's scroll/sort/folds. A bucket
     dies when its tab CLOSES (dropBucket) - the old "cleared per backup"
     contract became "cleared per backup lifetime": re-open after close is
     fresh, switch away and back is restored. */
  var _buckets = {};

  BV.state = {
    manifest: null,        /* {path, name, file_count, robot_name, f_number, tabs:{}} */
    tabData: {},           /* tabId -> parsed payload (the open backup's bucket) */
    settings: {},

    on: function (evt, fn) {
      (listeners[evt] = listeners[evt] || []).push(fn);
    },
    emit: function (evt, payload) {
      (listeners[evt] || []).forEach(function (fn) { fn(payload); });
    },

    setManifest: function (m) {
      BV.state.manifest = m;
      BV.state.tabData = (m && m.path)
        ? (_buckets[m.path] || (_buckets[m.path] = {}))
        : {};
      BV.state.emit("manifest", m);
    },

    dropBucket: function (path) { delete _buckets[path]; },
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
