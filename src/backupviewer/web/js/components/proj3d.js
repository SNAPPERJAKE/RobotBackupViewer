/* components/proj3d.js - fixed-view 3D->2D projection for the 3D View tab.

   Pure math, no DOM: FANUC world coordinates (mm, Z up) onto SVG screen
   space (y grows DOWN). Each view is an orthonormal screen basis
   (right / up / toViewer); project() returns [sx, sy, depth] where depth
   ASCENDS toward the viewer - painter's order is "sort ascending, draw
   in order". No perspective: plant zones read best orthographic, and
   distances stay measurable. */
(function () {
  "use strict";

  var D2R = Math.PI / 180;

  function cross(a, b) {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function norm(a) {
    var l = Math.sqrt(dot(a, a)) || 1;
    return [a[0] / l, a[1] / l, a[2] / l];
  }
  function neg(a) { return [-a[0], -a[1], -a[2]]; }

  /* screen basis from an eye direction (viewer sits at +eye looking at the
     origin), world +Z as up. right = forward x up, screenUp = right x forward */
  function basis(eye) {
    var f = norm(neg(eye));
    var r = norm(cross(f, [0, 0, 1]));
    var u = cross(r, f);
    return { right: r, up: u, toViewer: norm(eye) };
  }

  /* the four side views + top are axis-aligned; iso looks in from the
     front-right-top octant. Its azimuth is deliberately OFF the 45° grid:
     plant fences love 0/45/90° orientations, and a wall parallel to the
     eye azimuth degenerates to a sliver (seen on a real -45° fence). */
  var VIEWS = {
    front: basis([1, 0, 0]),
    back: basis([-1, 0, 0]),
    right: basis([0, -1, 0]),
    left: basis([0, 1, 0]),
    iso: basis([0.91, -0.42, 0.75]),
  };
  /* top/bottom: cross(f,[0,0,1]) degenerates at the poles - hand-built,
     PLAN-oriented for the FANUC world frame (X forward, Y left, Z up -
     right-handed): X points up-screen; top shows Y to screen-left, and
     bottom (seen from underneath) mirrors it to screen-right. */
  VIEWS.top = { right: [0, -1, 0], up: [1, 0, 0], toViewer: [0, 0, 1] };
  VIEWS.bottom = { right: [0, 1, 0], up: [1, 0, 0], toViewer: [0, 0, -1] };

  function fromBasis(b, persp) {
    function ortho(p) { return [dot(b.right, p), -dot(b.up, p), dot(b.toViewer, p)]; }
    var project = ortho;
    if (persp) {
      /* mild depth foreshortening about the scene center: points AT the
         center's depth are unchanged, so fit/pan/pivot math done there is
         exact in both modes. Clamped so geometry never crosses the eye. */
      var c = ortho(persp.center), D = persp.dist;
      project = function (p) {
        var o = ortho(p);
        var k = D / Math.max(D - (o[2] - c[2]), D * 0.05);
        return [c[0] + (o[0] - c[0]) * k, c[1] + (o[1] - c[1]) * k, o[2]];
      };
    }
    return {
      basis: b,
      project: project,
      /* ortho inverse at an explicit depth (exact at the persp center depth) */
      unproject: function (sx, sy, d) {
        return [
          b.right[0] * sx - b.up[0] * sy + b.toViewer[0] * d,
          b.right[1] * sx - b.up[1] * sy + b.toViewer[1] * d,
          b.right[2] * sx - b.up[2] * sy + b.toViewer[2] * d,
        ];
      },
      depthOf: function (p) { return dot(b.toViewer, p); },
    };
  }

  function projector(viewId, persp) { return fromBasis(VIEWS[viewId] || VIEWS.iso, persp); }

  /* free orbit: eye from azimuth (deg about Z from +X) + elevation (deg
     above the floor). Clamped short of the poles - basis() degenerates
     against the Z up-vector there. */
  function orbitProjector(azDeg, elDeg, persp) {
    var el = Math.max(-89.5, Math.min(89.5, elDeg)) * D2R;
    var az = azDeg * D2R;
    return fromBasis(basis([
      Math.cos(el) * Math.cos(az),
      Math.cos(el) * Math.sin(az),
      Math.sin(el),
    ]), persp);
  }

  /* orbit-space angles of each named view, so a drag STARTS from where the
     preset was looking (top/bottom azimuths are chosen so their near-pole
     limits match the hand-built plan bases) */
  var PRESET_ANGLES = {
    iso: [-24.8, 36.8],
    top: [180, 89.5],
    bottom: [0, -89.5],
    front: [0, 0],
    back: [180, 0],
    left: [90, 0],
    right: [-90, 0],
  };

  /* FANUC xyzwpr frame: R = Rz(r) * Ry(p) * Rx(w), world = R*local + t.
     null/undefined frame -> identity (zone numbers are already world). */
  function frameTransform(f) {
    if (!f) return function (p) { return [p[0], p[1], p[2]]; };
    var w = (f.w || 0) * D2R, p = (f.p || 0) * D2R, r = (f.r || 0) * D2R;
    var cw = Math.cos(w), sw = Math.sin(w);
    var cp = Math.cos(p), sp = Math.sin(p);
    var cr = Math.cos(r), sr = Math.sin(r);
    /* rows of Rz(r)*Ry(p)*Rx(w), composed on paper once */
    var m = [
      [cr * cp, cr * sp * sw - sr * cw, cr * sp * cw + sr * sw],
      [sr * cp, sr * sp * sw + cr * cw, sr * sp * cw - cr * sw],
      [-sp, cp * sw, cp * cw],
    ];
    var t = [f.x || 0, f.y || 0, f.z || 0];
    return function (pt) {
      return [
        m[0][0] * pt[0] + m[0][1] * pt[1] + m[0][2] * pt[2] + t[0],
        m[1][0] * pt[0] + m[1][1] * pt[1] + m[1][2] * pt[2] + t[1],
        m[2][0] * pt[0] + m[2][1] * pt[1] + m[2][2] * pt[2] + t[2],
      ];
    };
  }

  /* an XY polygon extruded z1..z2 -> vertices (bottom ring then top ring),
     quad/n-gon faces and the wireframe edge list, all index-based */
  function prism(poly, z1, z2) {
    var n = poly.length;
    var pts = [];
    var i;
    for (i = 0; i < n; i++) pts.push([poly[i][0], poly[i][1], z1]);
    for (i = 0; i < n; i++) pts.push([poly[i][0], poly[i][1], z2]);
    var faces = [];
    var bottom = [], top = [];
    for (i = 0; i < n; i++) { bottom.push(i); top.push(n + i); }
    faces.push(bottom);
    faces.push(top);
    for (i = 0; i < n; i++) faces.push([i, (i + 1) % n, n + (i + 1) % n, n + i]);
    var edges = [];
    for (i = 0; i < n; i++) {
      edges.push([i, (i + 1) % n]);
      edges.push([n + i, n + (i + 1) % n]);
      edges.push([i, n + i]);
    }
    return { pts: pts, faces: faces, edges: edges };
  }

  BV.proj3d = {
    VIEW_IDS: ["iso", "top", "bottom", "front", "back", "left", "right"],
    PRESET_ANGLES: PRESET_ANGLES,
    projector: projector,
    orbitProjector: orbitProjector,
    frameTransform: frameTransform,
    prism: prism,
  };
})();
