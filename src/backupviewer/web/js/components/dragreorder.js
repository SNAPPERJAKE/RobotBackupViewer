/* components/dragreorder.js - generic drag-to-reorder for items inside one or
   more drop zones. Lifted out of the overview dashboard so the same behaviour
   can be dropped onto any list of cards/rows later: drag an item by its handle,
   see a before/after marker, drop to reposition (within or across zones), get
   a callback to persist the new order.

   Items keep their identity on the node itself (e.g. dataset.cardId); this
   module only moves DOM around. It also tracks the last drop so a click that
   immediately follows a sloppy drag can be ignored (isRecentDrag()).

   opts: { zones:[el], itemSelector, handleSelector, classes, onDrop, clickGuardMs,
           autoScroll, onDragState, axis }
           axis           - "y" (default, vertical lists) or "x" (horizontal
                            strips - the backup tab bar); picks which pointer
                            coordinate decides the insertion point
           zones          - the drop containers
           itemSelector   - selects a draggable item (".card[data-card-id]")
           handleSelector  - child selector for the grab handle, relative to an
                             item; wire(item) sets draggable on it
           classes        - { dragging, dropBefore, dropAfter, dropEnd } overrides
           onDrop(item, fromZone, toZone) - called after a successful move
           autoScroll     - [el] scroll containers to edge-scroll while dragging
           onDragState(active) - called true on dragstart, false on dragend (so a
                             host can reveal empty drop zones only mid-drag)
   returns: { wire(item), isRecentDrag(), destroy() } */
(function () {
  "use strict";

  BV.dragReorder = function (opts) {
    opts = opts || {};
    var zones = opts.zones || [];
    var itemSel = opts.itemSelector || ".card";
    var handleSel = opts.handleSelector || null;
    var cls = opts.classes || {};
    var DRAGGING = cls.dragging || "dragging";
    var BEFORE = cls.dropBefore || "drop-before";
    var AFTER = cls.dropAfter || "drop-after";
    var END = cls.dropEnd || "drop-end";
    var guardMs = opts.clickGuardMs || 250;
    var axis = opts.axis || "y";

    var dragged = null;
    var lastDragEnd = 0;
    var bound = [];
    var autoScroll = opts.autoScroll || [];   /* scroll containers for edge-scroll */
    var lastClientY = 0;
    var scrollRAF = null;

    function on(el, ev, fn) { el.addEventListener(ev, fn); bound.push([el, ev, fn]); }

    function clearMarks() {
      zones.forEach(function (z) {
        z.classList.remove(END);
        z.querySelectorAll("." + BEFORE + ", ." + AFTER).forEach(function (e) {
          e.classList.remove(BEFORE, AFTER);
        });
      });
    }

    /* the item we'd drop BEFORE for a pointer coordinate in this zone (null =
       append at the end). One model for "onto a card" and "into empty space"
       alike, so the marker always shows exactly where the card will land. */
    function insertionPoint(zone, coord) {
      var items = [].filter.call(zone.querySelectorAll(itemSel), function (it) {
        return it !== dragged && it.parentElement === zone;
      });
      for (var i = 0; i < items.length; i++) {
        var r = items[i].getBoundingClientRect();
        var mid = axis === "x" ? r.left + r.width / 2 : r.top + r.height / 2;
        if (coord < mid) return items[i];
      }
      return null;
    }

    /* edge auto-scroll: while dragging near a scroll container's top/bottom, nudge
       it. Driven synchronously from dragover (so the hidden probe window, which
       runs no rAF, still scrolls) AND from a rAF loop (so holding the pointer
       still at the edge keeps scrolling). */
    function edgeScrollStep() {
      if (!dragged) return;
      autoScroll.forEach(function (sc) {
        if (!sc) return;
        var r = sc.getBoundingClientRect();
        if (lastClientY < r.top || lastClientY > r.bottom) return;
        var band = Math.min(70, r.height * 0.2) || 40;
        var dy = 0;
        if (lastClientY < r.top + band) dy = -Math.max(6, Math.round((r.top + band - lastClientY) / 3));
        else if (lastClientY > r.bottom - band) dy = Math.max(6, Math.round((lastClientY - (r.bottom - band)) / 3));
        if (dy) sc.scrollTop += dy;
      });
    }
    function edgeLoop() {
      if (!dragged) { scrollRAF = null; return; }
      edgeScrollStep();
      scrollRAF = requestAnimationFrame(edgeLoop);
    }

    zones.forEach(function (zone) {
      on(zone, "dragstart", function (e) {
        var item = e.target.closest(itemSel);
        if (!item || !zone.contains(item)) return;
        dragged = item;
        item.classList.add(DRAGGING);
        if (opts.onDragState) opts.onDragState(true);
        if (autoScroll.length && !scrollRAF) scrollRAF = requestAnimationFrame(edgeLoop);
        try {
          e.dataTransfer.setData("text/plain", item.dataset.cardId || "");
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setDragImage(item, 20, 16);
        } catch (err) { /* synthetic probe events carry no dataTransfer */ }
      });

      on(zone, "dragend", function () {
        if (dragged) dragged.classList.remove(DRAGGING);
        clearMarks();
        dragged = null;
        lastDragEnd = Date.now();
        if (scrollRAF) { cancelAnimationFrame(scrollRAF); scrollRAF = null; }
        if (opts.onDragState) opts.onDragState(false);
      });

      on(zone, "dragover", function (e) {
        if (!dragged) return;
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
        lastClientY = e.clientY || 0;
        edgeScrollStep();
        clearMarks();
        /* mark exactly where it lands: a line ABOVE the insertion-point card, or
           the whole zone's END when it appends past the last card / into empty */
        var ref = insertionPoint(zone, axis === "x" ? (e.clientX || 0) : lastClientY);
        if (ref) ref.classList.add(BEFORE);
        else zone.classList.add(END);
      });

      on(zone, "drop", function (e) {
        if (!dragged) return;
        e.preventDefault();
        var from = dragged.parentElement;
        var ref = insertionPoint(zone, axis === "x" ? (e.clientX || 0) : (e.clientY || 0));
        if (ref) zone.insertBefore(dragged, ref);
        else zone.appendChild(dragged);
        clearMarks();
        if (opts.onDrop) opts.onDrop(dragged, from, zone);
      });
    });

    return {
      /* make an item draggable by marking its handle draggable */
      wire: function (item) {
        var handle = handleSel ? item.querySelector(handleSel) : item;
        if (handle) handle.draggable = true;
      },
      isRecentDrag: function () { return Date.now() - lastDragEnd < guardMs; },
      destroy: function () {
        if (scrollRAF) { cancelAnimationFrame(scrollRAF); scrollRAF = null; }
        bound.forEach(function (b) { b[0].removeEventListener(b[1], b[2]); });
        bound = [];
      },
    };
  };
})();
