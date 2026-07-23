/* cvxremote.js - live CV-X remote-desktop overlay (screen mirror + mouse).

   BV.openCvxRemote(ip, label) opens a fullscreen-capable panel that mirrors a
   Keyence CV-X controller's live 1024x768 screen and forwards mouse input -
   all three buttons plus the wheel, so the controller's own zoom (scroll),
   pan (middle-drag) and context-menu (right-click) gestures work.

   The Python side (cvx_remote.py, via api.cvx_remote_*) speaks the controller's
   own TCP protocol and re-streams frames as MJPEG over a localhost HTTP server,
   so the live screen is just an <img> - no JS decoding. Mouse events map from the
   rendered image rect back to 1024x768 controller pixels. Wholly separate from
   the CV-X anon-FTP backup path. */
(function () {
  "use strict";

  var SCREEN_W = 1024, SCREEN_H = 768;
  /* Keyence's own VapiMouseEventId values (Vapi.Net.dll): 5/6 are the wheel
     BUTTON (middle), 10/11 wheel rotation (zoom). Moving with a button held
     must be sent as the dedicated DRAG id, not MOVE - the controller ignores
     plain MOVEs while pressed and the viewport would only snap at release. */
  var EV_MOVE = 0, EV_LDOWN = 1, EV_LUP = 2, EV_RDOWN = 3, EV_RUP = 4,
      EV_MDOWN = 5, EV_MUP = 6, EV_WHEEL_UP = 10, EV_WHEEL_DOWN = 11,
      EV_DRAGGED = 14, EV_WHEEL_DRAGGED = 15;
  var DOWN_EV = { 0: EV_LDOWN, 1: EV_MDOWN, 2: EV_RDOWN };
  var UP_EV = { 0: EV_LUP, 1: EV_MUP, 2: EV_RUP };
  var DRAG_EV = { 0: EV_DRAGGED, 1: EV_WHEEL_DRAGGED, 2: EV_DRAGGED };
  /* VapiConsoleKeyCode: the CV-X console has no PC keyboard - KEY_0..KEY_8 are
     button INDICES, not ascii digits. Forwarding is EXPERIMENTAL and OFF until
     the remoteControl wire method id is recovered from a live capture; the
     Python endpoint no-ops until then, so this can be flipped on for testing
     without risk of half-working shipped UX. */
  var KBD_ENABLED = false;
  var KEY_CODE = { "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
                   "5": 5, "6": 6, "7": 7, "8": 8 };
  var open = false;   /* one session at a time */

  BV.openCvxRemote = function (ip, label) {
    if (open) { BV.toast("a remote session is already open"); return; }
    ip = (ip || "").trim();
    if (!ip) { BV.toast("this camera has no IP on record"); return; }
    open = true;

    var sid = null, statusTimer = null, lastMove = 0, downBtn = null;
    var pressPt = null, dragging = false, wheelAcc = 0;
    var closed = false;   /* so a connect that resolves AFTER teardown stops the session it made */

    /* --- overlay chrome ------------------------------------------------- */
    var overlay = BV.el("div", { class: "cvx-remote" });
    var bar = BV.el("div", { class: "cvx-bar" });
    var title = BV.el("span", { class: "cvx-title" },
      "CV-X remote · " + BV.esc(label || ip));
    var status = BV.el("span", { class: "cvx-status" }, "connecting…");
    var spacer = BV.el("span", { style: "margin-left:auto" });
    var fsBtn = BV.el("button", { class: "btn", title: "fullscreen (f)" }, "fullscreen");
    var closeBtn = BV.el("button", { class: "btn", title: "close (esc)" }, "✕ close");
    bar.appendChild(title); bar.appendChild(status); bar.appendChild(spacer);
    bar.appendChild(fsBtn); bar.appendChild(closeBtn);

    var stage = BV.el("div", { class: "cvx-stage" });
    var screen = BV.el("div", { class: "cvx-screen" });
    var img = BV.el("img", { alt: "CV-X live screen", draggable: "false" });
    var hint = BV.el("div", { class: "cvx-hint" }, "waiting for the first frame…");
    screen.appendChild(img); screen.appendChild(hint);
    stage.appendChild(screen);
    overlay.appendChild(bar); overlay.appendChild(stage);
    document.body.appendChild(overlay);

    /* keep the 4:3 screen box as large as fits, so mouse coords map linearly */
    function fit() {
      var sw = stage.clientWidth, sh = stage.clientHeight, ar = SCREEN_W / SCREEN_H;
      var w = sw, h = sw / ar;
      if (h > sh) { h = sh; w = sh * ar; }
      screen.style.width = Math.round(w) + "px";
      screen.style.height = Math.round(h) + "px";
    }
    window.addEventListener("resize", fit);
    fit();

    /* --- teardown ------------------------------------------------------- */
    function close() {
      if (closed) return;
      closed = true;
      open = false;
      clearInterval(statusTimer);
      window.removeEventListener("resize", fit);
      window.removeEventListener("mouseup", onMouseUp);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("keydown", onKeyCapture, true);
      img.src = "";                       /* drop the MJPEG connection */
      if (document.fullscreenElement) { try { document.exitFullscreen(); } catch (e) {} }
      overlay.remove();
      if (sid) BV.api.call("cvx_remote_stop", sid).catch(function () {});
    }
    closeBtn.addEventListener("click", close);

    function toggleFs() {
      if (document.fullscreenElement) { try { document.exitFullscreen(); } catch (e) {} }
      else { try { overlay.requestFullscreen(); } catch (e) {} }
    }
    fsBtn.addEventListener("click", toggleFs);

    function onKey(e) {
      if (e.key === "Escape") {
        if (document.fullscreenElement) return;   /* let the browser exit fs first */
        e.preventDefault(); close();
      } else if (e.key === "f" || e.key === "F") {
        toggleFs();
      }
    }
    document.addEventListener("keydown", onKey);

    /* console-key forwarding (experimental). Capture phase so a digit never
       leaks to keys.js and switches a tab behind the fullscreen remote -
       correct even while KBD_ENABLED is off. Forwards only once the wire
       method is known (the endpoint no-ops until then). */
    function onKeyCapture(e) {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (!(e.key in KEY_CODE)) return;
      e.preventDefault(); e.stopPropagation();
      if (!KBD_ENABLED || !sid) return;
      BV.api.call("cvx_remote_key", sid, KEY_CODE[e.key]).catch(function () {});
    }
    document.addEventListener("keydown", onKeyCapture, true);

    /* --- mouse forwarding ----------------------------------------------- */
    function toScreen(e) {
      var r = screen.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width * SCREEN_W;
      var y = (e.clientY - r.top) / r.height * SCREEN_H;
      return { x: Math.round(x), y: Math.round(y) };
    }
    /* fire-and-forget with a client sequence number. pywebview runs each api
       call on its own Python thread (util.js_bridge_call), so calls can
       ARRIVE out of order (a press before its positioning move) - Python
       reorders by seq before touching the socket. Don't chain input on the
       bridge promises instead: one lost call would stall every later event. */
    var seq = 0;
    function sendMouse(ev, p) {
      if (!sid) return;
      BV.api.call("cvx_remote_mouse", sid, ev, p.x, p.y, seq++).catch(function () {});
    }
    screen.addEventListener("mousemove", function (e) {
      if (!sid) return;
      var p = toScreen(e);
      if (downBtn !== null && !dragging) {
        /* click-vs-drag dead-zone: hand jitter while a button is held must
           not read as a drag - a jittered right-click would drag-cancel the
           controller's context menu instead of opening it. */
        if (Math.abs(p.x - pressPt.x) < 4 && Math.abs(p.y - pressPt.y) < 4) return;
        dragging = true;
      }
      var now = Date.now();
      if (now - lastMove < 45) return;    /* throttle: ~22 moves/s */
      lastMove = now;
      /* held button -> the button's DRAG id; the controller pans on those
         and ignores plain MOVEs while pressed (hover stays MOVE) */
      sendMouse(dragging && downBtn !== null ? DRAG_EV[downBtn] : EV_MOVE, p);
    });
    screen.addEventListener("mousedown", function (e) {
      if (!sid || !(e.button in DOWN_EV)) return;
      e.preventDefault();
      var p = toScreen(e);
      downBtn = e.button; pressPt = p; dragging = false;
      sendMouse(EV_MOVE, p);              /* position the cursor, then press */
      sendMouse(DOWN_EV[e.button], p);
    });
    function onMouseUp(e) {
      if (!sid || downBtn === null) return;
      var p = dragging ? toScreen(e) : pressPt;   /* a click releases where it pressed */
      sendMouse(UP_EV[downBtn], p);
      downBtn = null; dragging = false;
    }
    window.addEventListener("mouseup", onMouseUp);
    screen.addEventListener("wheel", function (e) {
      if (!sid) return;
      e.preventDefault();
      var d = e.deltaY;
      if (e.deltaMode === 1) d *= 33;     /* lines -> px */
      else if (e.deltaMode === 2) d *= 300;
      if (wheelAcc !== 0 && (d > 0) !== (wheelAcc > 0)) wheelAcc = 0;
      wheelAcc += d;
      var p = toScreen(e), sent = 0;
      while (Math.abs(wheelAcc) >= 100 && sent < 3) {   /* 100 px = one notch */
        if (!sent) sendMouse(EV_MOVE, p);               /* zoom centers on the cursor */
        sendMouse(wheelAcc > 0 ? EV_WHEEL_DOWN : EV_WHEEL_UP, p);
        wheelAcc -= (wheelAcc > 0 ? 100 : -100);
        sent++;
      }
      if (sent === 3) wheelAcc = 0;       /* a trackpad fling must not zoom forever */
    }, { passive: false });
    screen.addEventListener("contextmenu", function (e) { e.preventDefault(); });

    /* --- connect + stream ----------------------------------------------- */
    img.addEventListener("load", function () { hint.style.display = "none"; });

    BV.api.call("cvx_remote_start", { ip: ip }).then(function (r) {
      if (closed) {
        /* the overlay was torn down while connecting - stop the session it just
           opened so we never strand the camera's one remote slot */
        if (r && r.session_id) BV.api.call("cvx_remote_stop", r.session_id).catch(function () {});
        return;
      }
      sid = r.session_id;
      if (r.screen) { SCREEN_W = r.screen.w; SCREEN_H = r.screen.h; fit(); }
      img.src = r.stream_url;
      statusTimer = setInterval(pollStatus, 1000);
    }).catch(function (e) {
      if (closed) return;
      hint.textContent = "";
      status.textContent = "connection failed";
      status.classList.add("err");
      screen.appendChild(BV.el("div", { class: "cvx-error" },
        '<div class="big">could not connect</div><div class="hint">' + BV.esc(e.message) +
        "</div><div class=\"hint\">the camera may be off, or the Terminal / an operator is already on it.</div>"));
    });

    function pollStatus() {
      if (!sid) return;
      BV.api.call("cvx_remote_status", sid).then(function (s) {
        if (!open) return;
        if (s.error) {
          status.textContent = "error"; status.classList.add("err");
          hint.style.display = ""; hint.textContent = s.error;
        } else if (!s.alive) {
          status.textContent = "disconnected"; status.classList.add("err");
        } else if (s.frames > 0) {
          status.textContent = "live · " + s.frames + " frames"; status.classList.remove("err");
        } else {
          status.textContent = s.handshake_done ? "connected — awaiting screen…" : "connecting…";
        }
      }).catch(function () {});
    }
  };
})();
