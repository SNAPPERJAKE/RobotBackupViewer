/* phoneview.js - hand a phone a live picture over a QR handoff.

   BV.openViewfinder() shares a user-picked rectangle of THIS PC's screen:
   the bridge freezes the screen into a snip-style picker (drag a box over
   the area - the DA operator page's live image, Design Assistant, anything),
   then the phone streams that rect live. "pick area" moves the box any time.

   BV.openPhoneView(ip, label) is the camera-direct variant (relays the MTX
   HMI frame without touching the screen); the UI leads with the viewfinder
   since it works regardless of what the camera publishes.

   Both open the same modal: a scannable QR of http://<this pc>:<port>/v/
   <token>, chips to pick WHICH of this PC's addresses the QR dials
   (mobile-hotspot net first - the usual answer when the laptop is wired to
   the robot network), and a live status line that flips the moment a phone
   actually pulls a frame. The share keeps serving when the modal closes;
   "stop sharing" ends it. The phone only ever needs a route to the PC. */
(function () {
  "use strict";

  /* matrix -> inline SVG. Always dark-on-white with a quiet zone, whatever
     the theme - scanners want the contrast, not our palette. */
  function qrSvg(m) {
    var n = m.size, q = 4, s = n + 2 * q, d = "";
    for (var r = 0; r < n; r++) {
      var row = m.rows[r];
      for (var c = 0; c < n; c++) {
        if (row.charCodeAt(c) === 49) d += "M" + (c + q) + " " + (r + q) + "h1v1h-1z";
      }
    }
    return '<svg viewBox="0 0 ' + s + " " + s + '" shape-rendering="crispEdges" role="img"' +
      ' aria-label="QR code for the phone view URL" style="display:block;width:100%;height:auto">' +
      '<rect width="100%" height="100%" fill="#fff"/><path d="' + d + '" fill="#000"/></svg>';
  }

  BV.openPhoneView = function (ip, label) {
    BV.api.call("phone_view_start", { ip: ip, label: label || "" }).then(function (d) {
      show(label || ip, d, false);
    }).catch(function (e) { BV.toast("phone view: " + e.message); });
  };

  /* the screen share, one thing on screen at a time: 📱 dims the screen into
     the picker; the QR modal appears only after the area is confirmed. While
     the picker is up we just wait on status - picking done + area = show the
     QR; session gone = the user cancelled a first pick. */
  var waiting = false;

  function awaitPick(d) {
    if (waiting) return;
    waiting = true;
    (function poll() {
      BV.api.call("phone_view_status").then(function (st) {
        var s = (st.sessions || []).filter(function (x) { return x.token === d.token; })[0];
        if (!s) { waiting = false; BV.toast("phone view cancelled"); return; }
        if (s.picking || !s.area) { setTimeout(poll, 600); return; }
        waiting = false;
        show("screen area", d, true);
      }).catch(function (e) { waiting = false; BV.toast("phone view: " + e.message); });
    })();
  }

  BV.openViewfinder = function () {
    if (waiting) return;
    BV.api.call("viewfinder_start").then(function (d) {
      awaitPick(d);
    }).catch(function (e) { BV.toast("phone view: " + e.message); });
  };

  function show(label, d, screen) {
    var urls = d.urls;

    var wrap = BV.el("div", { style:
      "display:flex;flex-direction:column;gap:0.7rem;max-width:26rem" });

    var qrBox = BV.el("div", { style:
      "background:#fff;border-radius:10px;padding:0.75rem;align-self:center;" +
      "width:min(60vw,16rem)" });
    var urlLine = BV.el("div", { class: "dim", title: "click to copy", style:
      "font-family:Consolas,monospace;font-size:0.8rem;text-align:center;" +
      "cursor:pointer;user-select:text;word-break:break-all" });
    urlLine.addEventListener("click", function () {
      BV.copyText(urlLine.textContent, "address copied");
    });

    function pick(i) {
      var u = urls[i];
      urlLine.textContent = u.url;
      qrBox.innerHTML = '<div class="dim" style="text-align:center">…</div>';
      BV.api.call("phone_view_qr", { text: u.url }).then(function (m) {
        qrBox.innerHTML = qrSvg(m);
      }).catch(function (e) {
        qrBox.innerHTML = '<div class="dim" style="text-align:center;color:#000;padding:0.5rem">' +
          "no QR (" + BV.esc(e.message) + ") — type the address instead</div>";
      });
    }

    wrap.appendChild(qrBox);
    wrap.appendChild(urlLine);

    if (urls.length > 1) {
      var seg = BV.segmented(urls.map(function (u, i) {
        return { id: String(i), label: u.ip, title: "reach this pc via its " + u.kind + " address" };
      }), { value: "0", onChange: function (id) { pick(+id); } });
      seg.el.style.justifyContent = "center";
      seg.el.style.flexWrap = "wrap";
      wrap.appendChild(seg.el);
    }

    var status = BV.el("div", { class: "dim", style: "text-align:center" }, "starting…");
    wrap.appendChild(status);

    wrap.appendChild(BV.el("div", { class: "dim", style: "font-size:0.78rem" },
      "scan with the phone camera. the phone must reach <b>this pc</b>: same wifi, " +
      "or turn on windows <b>mobile hotspot</b>, join it from the phone, and pick the " +
      "hotspot address above. " +
      (screen
        ? "the pc streams the picked screen area, so whatever shows there — the " +
          "camera page included — reaches the phone. "
        : "the pc relays the camera, so the phone never needs the robot network. ") +
      "the first share may pop a windows firewall prompt — allow it."));

    var row = BV.el("div", { style: "display:flex;gap:0.5rem;justify-content:flex-end" });
    if (screen) {
      var pickBtn = BV.el("button", { class: "btn",
        title: "move the screen area the phone sees" }, "▣ pick area");
      pickBtn.addEventListener("click", function () {
        BV.api.call("viewfinder_pick", { token: d.token }).then(function () {
          modal.close();          /* the picker owns the screen; QR comes back after */
          awaitPick(d);
        }).catch(function (e) { BV.toast("could not open the picker: " + e.message); });
      });
      row.appendChild(pickBtn);
      row.appendChild(BV.el("span", { style: "margin-left:auto" }));
    }
    var stopBtn = BV.el("button", { class: "btn" }, "stop sharing");
    var closeBtn = BV.el("button", { class: "btn" }, "close (keeps sharing)");
    row.appendChild(stopBtn);
    row.appendChild(closeBtn);
    wrap.appendChild(row);

    var poll = null;
    var modal = BV.modal("phone view · " + label, wrap, {
      onClose: function () { clearInterval(poll); },
    });
    closeBtn.addEventListener("click", function () { modal.close(); });
    stopBtn.addEventListener("click", function () {
      BV.api.call("phone_view_stop", { token: d.token }).then(function () {
        BV.toast("stopped sharing");
        modal.close();
      }).catch(function (e) { BV.toast("could not stop: " + e.message); });
    });

    function refresh() {
      BV.api.call("phone_view_status").then(function (st) {
        var s = (st.sessions || []).filter(function (x) { return x.token === d.token; })[0];
        if (!s) { status.textContent = "share ended"; return; }
        var watching = s.phones && s.last_pull_ms !== null && s.last_pull_ms <= 15000;
        var who = watching
          ? '<span style="color:var(--ok)">' + s.phones +
            (s.phones === 1 ? " phone" : " phones") + " watching</span>"
          : "no phone watching yet — scan the code";
        if (s.picking) {
          status.innerHTML = who + ' <span class="dim">· drag the box on the pc screen</span>';
        } else if (s.kind === "screen" && !s.area) {
          status.innerHTML = who + ' <span class="dim">· no area picked yet — ▣ pick area</span>';
        } else if (s.fetch_err) {
          status.innerHTML = '<span style="color:var(--error)">' +
            (s.kind === "screen" ? "screen capture failing" : "camera not answering") +
            '</span> <span class="dim">· ' + BV.esc(s.fetch_err) + "</span>";
        } else {
          status.innerHTML = who +
            (watching && s.frame_age_ms !== null
              ? ' <span class="dim">· frame ' + (s.frame_age_ms / 1000).toFixed(1) + "s old</span>"
              : "") +
            (s.area
              ? ' <span class="dim">· ' + s.area[2] + "×" + s.area[3] + " px</span>"
              : "");
        }
      }).catch(function () { /* keep the last status through a hiccup */ });
    }
    poll = setInterval(refresh, 2000);
    refresh();

    pick(0);
  }
})();
