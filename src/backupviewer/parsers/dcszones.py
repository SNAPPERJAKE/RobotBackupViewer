"""DCS zone geometry for the 3D view: DCSPOS.VA + DCSVRFY.DG.

DCSPOS.VA (a sysvar dump of the DCS SHADOW tables) is the authoritative
geometry source: full vertex arrays, Z extents and the DCS user frames
(which can be rotated - a zone's numbers only make sense through its
frame). DCSVRFY.DG rides along for what the .VA does not carry: the
pendant's verify STATUS per zone, the method text ("Diagonal(OUT)") and
the TCP position captured when the report was written. Backups without
DCSPOS.VA fall back to the verify report's Point 1/Point 2 boxes
(diagonal-only - lossy but drawable, flagged "approx").

Ground truth established against a live fence zone: $MODE=1 <->
"Diagonal(OUT)", $STOP_TYP=0 <-> "Power-Off stop", and the .VA
vertices/Z match the pendant's table digit for digit. $MODE values
beyond 0/1 are NOT assumed - without the verify text to say, method
reads "?" and the shape falls back to a vertex-count heuristic.
$NUM_VTX stays at its factory 8 on Diagonal zones, so it is only
trusted in Lines mode. $DCSS_TUIRO/$DCSS_TUIZN are not handled
(unknown semantics; none seen configured with geometry).
"""
from __future__ import annotations

import re

# tables kept from DCSPOS.VA; everything else in the dump is skipped
_WANTED = {"DCSS_CPC", "DCSS_CSC", "DCSS_JPC", "DCSS_JSC", "DCSS_UFRM"}

_TABLE = re.compile(r"^\[\*SYSTEM\*\]\$(\w+)\b")
_FIELD = re.compile(r"^\s+Field:\s+\$(\w+)\[([\d,]+)\]\.\$(\w+)\b(.*)$")
_ELEM = re.compile(r"^\s+\[(\d+)\]\s*=\s*(.*?)\s*$")
_METHOD = re.compile(r"^(\w+)\s*\(\s*(IN|OUT)\s*\)", re.I)

_STOP_TYPES = {0: "Power-Off stop", 1: "Controlled stop"}


def _value(tok: str):
    tok = tok.strip()
    if tok.startswith("'"):
        return tok.strip("'").strip()
    try:
        if re.fullmatch(r"-?\d+", tok):
            return int(tok)
        return float(tok)
    except ValueError:
        return tok


def _parse_tables(text: str) -> dict:
    """DCSPOS.VA -> {table: {idx_str: {FIELD: value | {elem_i: value}}}}."""
    tables: dict[str, dict] = {}
    cur_table: str | None = None
    cur_arr: dict | None = None  # element target for ARRAY fields
    for raw in text.splitlines():
        m = _TABLE.match(raw)
        if m:
            cur_table = m.group(1) if m.group(1) in _WANTED else None
            cur_arr = None
            continue
        if cur_table is None:
            continue
        m = _FIELD.match(raw)
        if m:
            var, idx, field, rest = m.group(1), m.group(2), m.group(3), m.group(4)
            if var != cur_table:
                continue
            rec = tables.setdefault(var, {}).setdefault(idx, {})
            if " = " in rest:
                rec[field] = _value(rest.split(" = ", 1)[1])
                cur_arr = None
            elif "=" in rest:  # tight "STRING[25] ='x'" never seen, but be lenient
                rec[field] = _value(rest.split("=", 1)[1])
                cur_arr = None
            else:  # "ARRAY[8] OF REAL" header - elements follow
                cur_arr = rec[field] = {}
            continue
        if cur_arr is not None:
            m = _ELEM.match(raw)
            if m:
                cur_arr[int(m.group(1))] = _value(m.group(2))
    return tables


def _arr(rec: dict, field: str, n: int) -> list:
    a = rec.get(field) or {}
    return [a.get(i, 0.0) for i in range(1, n + 1)]


def _frames(tables: dict) -> dict:
    """$DCSS_UFRM[group,slot] -> {(group, frame_number): frame dict}.

    Zones reference the user-chosen frame NUMBER ($UFRM_NUM, e.g. 21),
    not the slot, so the lookup is keyed on that."""
    out = {}
    for idx, rec in (tables.get("DCSS_UFRM") or {}).items():
        parts = idx.split(",")
        grp = int(parts[0]) if len(parts) == 2 else 1
        num = rec.get("UFRM_NUM") or 0
        if not num:
            continue
        out[(grp, int(num))] = {
            "x": rec.get("X", 0.0), "y": rec.get("Y", 0.0), "z": rec.get("Z", 0.0),
            "w": rec.get("W", 0.0), "p": rec.get("P", 0.0), "r": rec.get("R", 0.0),
            "num": int(num), "comment": rec.get("COMMENT", "") or "",
        }
    return out


# -- DCSVRFY.DG cross-reference ---------------------------------------------


def _vrfy_sections(report: dict | None, needle: str) -> list[dict]:
    if not report:
        return []
    return [s for s in report.get("sections", []) if needle in s.get("title", "").lower()]


def _vrfy_cpc(report: dict | None) -> dict[int, dict]:
    """verify-report Cartesian Position Check entries by zone number."""
    out: dict[int, dict] = {}
    for sec in _vrfy_sections(report, "cartesian position check"):
        for e in sec.get("entries", []):
            out[e["index"]] = e
    return out


def _detail_kv(entry: dict, key_start: str) -> str:
    for d in entry.get("detail", []):
        if d.get("key", "").lower().startswith(key_start):
            return str(d.get("value", ""))
    return ""


def _detail_pos(entry: dict) -> dict | None:
    for d in entry.get("detail", []):
        if "pos_table" in d:
            return d["pos_table"]
    return None


def _pos_col(pt: dict, col: int) -> dict:
    """pos_table column -> {axis: float} (masked/odd values skipped)."""
    out = {}
    for row in pt.get("rows", []):
        vals = row.get("values", [])
        if col < len(vals):
            try:
                out[row["axis"]] = float(vals[col])
            except ValueError:
                pass
    return out


# -- builders ----------------------------------------------------------------


def _box_poly(p1: tuple, p2: tuple) -> list:
    (x1, y1), (x2, y2) = p1, p2
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _method(rec: dict, ventry: dict | None):
    """(method, side, text, source). Verify text wins; $MODE only maps the
    two values we have ground truth for (0 factory default / 1 observed)."""
    txt = _detail_kv(ventry, "method") if ventry else ""
    m = _METHOD.match(txt)
    if m:
        return m.group(1).lower(), m.group(2).lower(), txt, "vrfy"
    mode = rec.get("MODE", 0)
    if mode == 0:
        return "diagonal", "in", "Diagonal(IN)", "va"
    if mode == 1:
        return "diagonal", "out", "Diagonal(OUT)", "va"
    return "?", "?", f"mode {mode}", "heuristic"


def _cpc_shape(rec: dict, method: str):
    """-> (poly, vtx_used). Diagonal = 2 corner points regardless of
    $NUM_VTX (the pendant leaves it at 8); Lines = the first $NUM_VTX
    vertices. Unknown method: trust the vertex data itself."""
    xs, ys = _arr(rec, "X", 8), _arr(rec, "Y", 8)
    n_vtx = int(rec.get("NUM_VTX") or 2)
    if method == "lines":
        n = max(3, min(n_vtx, 8))
        return [[xs[i], ys[i]] for i in range(n)], n
    if method == "diagonal":
        return _box_poly((xs[0], ys[0]), (xs[1], ys[1])), 2
    # unknown mode: any vertex beyond the first two set -> treat as polygon
    if any(xs[i] or ys[i] for i in range(2, 8)):
        n = max(3, min(n_vtx, 8))
        return [[xs[i], ys[i]] for i in range(n)], n
    return _box_poly((xs[0], ys[0]), (xs[1], ys[1])), 2


def _stop_text(rec: dict, ventry: dict | None) -> str:
    txt = _detail_kv(ventry, "stop type") if ventry else ""
    if txt:
        return txt
    v = rec.get("STOP_TYP")
    if v is None:
        return ""
    return _STOP_TYPES.get(v, f"stop type {v}")


def _synth_detail(rec: dict, poly: list, z1: float, z2: float, extra: list) -> list:
    """va-only zones still get a pendant-shaped detail block for the panel."""
    items = list(extra)
    pt = {
        "headers": [f"Point {i + 1}" for i in range(len(poly))],
        "rows": [
            {"axis": "X", "values": [f"{p[0]:.1f}" for p in poly]},
            {"axis": "Y", "values": [f"{p[1]:.1f}" for p in poly]},
            {"axis": "Z", "values": [f"{z1:.1f}", f"{z2:.1f}"] + [""] * (len(poly) - 2)},
        ],
    }
    items.append({"pos_table": pt})
    return items


def _build_cpc(tables: dict, frames: dict, vmap: dict[int, dict]) -> list:
    out = []
    for idx, rec in sorted((tables.get("DCSS_CPC") or {}).items(), key=lambda kv: int(kv[0])):
        n = int(idx)
        ventry = vmap.get(n)
        method, side, mtext, msource = _method(rec, ventry)
        poly, vtx_used = _cpc_shape(rec, method)
        za, zb = rec.get("Z1", 0.0) or 0.0, rec.get("Z2", 0.0) or 0.0
        grp = int(rec.get("GRP_NUM") or 1)
        ufrm_num = int(rec.get("UFRM_NUM") or 0)
        frame = frames.get((grp, ufrm_num)) if ufrm_num else None
        label = rec.get("COMMENT", "") or (ventry or {}).get("comment", "") or f"zone {n}"
        detail = (ventry or {}).get("detail") or _synth_detail(
            rec, poly, min(za, zb), max(za, zb),
            [{"key": "Method(Safe side)", "value": mtext},
             {"key": "Group", "value": str(grp)},
             {"key": "User frame", "value": str(ufrm_num)},
             {"key": "Stop type", "value": _stop_text(rec, None)}])
        out.append({
            "n": n, "label": label,
            "enabled": bool(rec.get("ENABLE")) or bool((ventry or {}).get("active")),
            "group": grp,
            "method": method, "side": side,
            "method_text": mtext, "method_source": msource,
            "ufrm_num": ufrm_num, "frame": frame,
            "frame_missing": bool(ufrm_num and frame is None),
            "poly": poly, "vtx_used": vtx_used,
            "z1": min(za, zb), "z2": max(za, zb),
            "stop": _stop_text(rec, ventry),
            "status": (ventry or {}).get("detail_status") or (ventry or {}).get("row_status", ""),
            "approx": False,
            "detail": detail,
        })
    return out


def _cpc_from_vrfy(vmap: dict[int, dict]) -> list:
    """No DCSPOS.VA: rebuild diagonal boxes from the verify report's
    Point 1/Point 2 table. The DCS user frame's rotation is not in the
    report, so geometry is drawn frame-less and flagged approx."""
    out = []
    for n, e in sorted(vmap.items()):
        pt = _detail_pos(e)
        if not pt:
            continue
        p1, p2 = _pos_col(pt, 1), _pos_col(pt, 2)
        if "X" not in p1 or "X" not in p2:
            continue
        txt = _detail_kv(e, "method")
        m = _METHOD.match(txt)
        try:
            ufrm_num = int(_detail_kv(e, "user frame") or 0)
        except ValueError:
            ufrm_num = 0
        out.append({
            "n": n, "label": e.get("comment") or f"zone {n}",
            "enabled": bool(e.get("active")),
            "group": int(e.get("group") or 1),
            "method": m.group(1).lower() if m else "diagonal",
            "side": m.group(2).lower() if m else "?",
            "method_text": txt or "", "method_source": "vrfy",
            "ufrm_num": ufrm_num, "frame": None,
            "frame_missing": bool(ufrm_num),
            "poly": _box_poly((p1["X"], p1.get("Y", 0.0)), (p2["X"], p2.get("Y", 0.0))),
            "vtx_used": 2,
            "z1": min(p1.get("Z", 0.0), p2.get("Z", 0.0)),
            "z2": max(p1.get("Z", 0.0), p2.get("Z", 0.0)),
            "stop": _detail_kv(e, "stop type"),
            "status": e.get("detail_status") or e.get("row_status", ""),
            "approx": True,
            "detail": e.get("detail", []),
        })
    return out


def _kv_items(pairs) -> list:
    return [{"key": k, "value": str(v)} for k, v in pairs if v not in (None, "")]


def _build_jpc(tables: dict) -> list:
    out = []
    for idx, rec in sorted((tables.get("DCSS_JPC") or {}).items(), key=lambda kv: int(kv[0])):
        n = int(idx)
        low, high = rec.get("LWR_LIM", 0.0) or 0.0, rec.get("UPR_LIM", 0.0) or 0.0
        mode = rec.get("MODE", 0)
        side = {0: "in", 1: "out"}.get(mode, "?")
        item = {
            "n": n, "label": rec.get("COMMENT", "") or f"joint check {n}",
            "enabled": bool(rec.get("ENABLE")),
            "group": int(rec.get("GRP_NUM") or 1),
            "axis": int(rec.get("AXS_NUM") or 1),
            "low": low, "high": high, "side": side,
            "stop": _stop_text(rec, None),
        }
        item["detail"] = _kv_items([
            ("Axis", f"J{item['axis']}"), ("Group", item["group"]),
            ("Lower limit", f"{low:.3f}"), ("Upper limit", f"{high:.3f}"),
            ("Safe side", side), ("Stop type", item["stop"]),
        ])
        out.append(item)
    return out


def _build_csc(tables: dict) -> list:
    out = []
    for idx, rec in sorted((tables.get("DCSS_CSC") or {}).items(), key=lambda kv: int(kv[0])):
        n = int(idx)
        item = {
            "n": n, "label": rec.get("COMMENT", "") or f"speed check {n}",
            "enabled": bool(rec.get("ENABLE")),
            "group": int(rec.get("GRP_NUM") or 1),
            "limit": rec.get("SPD_LIM", 0.0) or 0.0,
            "tcp_num": rec.get("TCP"), "ufrm_num": rec.get("UFRM_NUM"),
            "stop": _stop_text(rec, None),
        }
        item["detail"] = _kv_items([
            ("Speed limit (mm/s)", item["limit"]), ("Group", item["group"]),
            ("TCP", item["tcp_num"]), ("User frame", item["ufrm_num"]),
            ("Stop tolerance", rec.get("STOP_TOL")), ("Stop type", item["stop"]),
        ])
        out.append(item)
    return out


def _build_jsc(tables: dict) -> list:
    out = []
    for idx, rec in sorted((tables.get("DCSS_JSC") or {}).items(), key=lambda kv: int(kv[0])):
        n = int(idx)
        item = {
            "n": n, "label": rec.get("COMMENT", "") or f"joint speed {n}",
            "enabled": bool(rec.get("ENABLE")),
            "group": int(rec.get("GRP_NUM") or 1),
            "axis": int(rec.get("AXS_NUM") or 1),
            "limit": rec.get("SPD_LIM", 0.0) or 0.0,
            "stop": _stop_text(rec, None),
        }
        item["detail"] = _kv_items([
            ("Axis", f"J{item['axis']}"), ("Group", item["group"]),
            ("Speed limit", item["limit"]), ("Stop type", item["stop"]),
        ])
        out.append(item)
    return out


def _tcp(cpc: list, vmap: dict[int, dict]) -> dict | None:
    """TCP position when the verify report was written, from the first
    enabled zone's 'Current' column. The pendant prints it in the same
    (frame-local) columns as the points, so the zone's frame rides along
    for the world transform."""
    for z in cpc:
        if not z["enabled"]:
            continue
        e = vmap.get(z["n"])
        pt = _detail_pos(e) if e else None
        if not pt:
            continue
        cur = _pos_col(pt, 0)
        if "X" not in cur:
            continue
        return {
            "xyz": [cur.get("X", 0.0), cur.get("Y", 0.0), cur.get("Z", 0.0)],
            "frame": z["frame"],
            "approx": z["frame_missing"],
        }
    return None


def build_zones(pos_text: str | None, vrfy_report: dict | None) -> dict:
    """The 3D-view payload. Either source may be missing (not both)."""
    tables = _parse_tables(pos_text) if pos_text else {}
    vmap = _vrfy_cpc(vrfy_report)
    frames = _frames(tables)

    if tables.get("DCSS_CPC"):
        cpc = _build_cpc(tables, frames, vmap)
        source = "va+dg" if vrfy_report else "va"
    else:
        cpc = _cpc_from_vrfy(vmap)
        source = "dg"

    models = []
    for sec in (vrfy_report.get("sections", []) if vrfy_report else []):
        if sec.get("kind") == "user_model":
            models = sec.get("entries", [])
            break

    jpc, csc, jsc = _build_jpc(tables), _build_csc(tables), _build_jsc(tables)
    groups = sorted({z["group"] for coll in (cpc, jpc, csc, jsc) for z in coll} or {1})

    return {
        "source": source,
        "date": (vrfy_report or {}).get("header", {}).get("date", ""),
        "groups": groups,
        "tcp": _tcp(cpc, vmap),
        "cpc": cpc, "jpc": jpc, "csc": csc, "jsc": jsc,
        "models": models,
    }
