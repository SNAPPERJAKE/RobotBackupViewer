"""dcszones: DCSPOS.VA geometry + DCSVRFY.DG merge for the 3D view.

Fixtures mirror the real controller output shapes (fabricated values,
no plant identifiers): the sysvar-dump Field/element lines of DCSPOS.VA
and the pendant-text verify report parsed by parsers.dcs.
"""
from backupviewer.parsers import dcs, dcszones


def _cpc_zone(n, comment, enable, mode, grp, ufrm, num_vtx, xs, ys, z1, z2, stop=0):
    lines = [
        f"     Field: $DCSS_CPC[{n}].$COMMENT Access: RW: STRING[25] = '{comment}'",
        f"     Field: $DCSS_CPC[{n}].$ENABLE Access: RW: INTEGER = {enable}",
        f"     Field: $DCSS_CPC[{n}].$MODE Access: RW: INTEGER = {mode}",
        f"     Field: $DCSS_CPC[{n}].$GRP_NUM Access: RW: INTEGER = {grp}",
        f"     Field: $DCSS_CPC[{n}].$MODEL_NUM  ARRAY[3] OF INTEGER",
        "      [1] = -1",
        "      [2] = 0",
        "      [3] = 0",
        f"     Field: $DCSS_CPC[{n}].$UFRM_NUM Access: RW: INTEGER = {ufrm}",
        f"     Field: $DCSS_CPC[{n}].$NUM_VTX Access: RW: INTEGER = {num_vtx}",
        f"     Field: $DCSS_CPC[{n}].$X  ARRAY[8] OF REAL",
    ]
    lines += [f"      [{i + 1}] = {v:e}" for i, v in enumerate(xs + [0.0] * (8 - len(xs)))]
    lines += [f"     Field: $DCSS_CPC[{n}].$Y  ARRAY[8] OF REAL"]
    lines += [f"      [{i + 1}] = {v:e}" for i, v in enumerate(ys + [0.0] * (8 - len(ys)))]
    lines += [
        f"     Field: $DCSS_CPC[{n}].$Z1 Access: RW: REAL = {z1:e}",
        f"     Field: $DCSS_CPC[{n}].$Z2 Access: RW: REAL = {z2:e}",
        f"     Field: $DCSS_CPC[{n}].$STOP_TYP Access: RW: INTEGER = {stop}",
        f"     Field: $DCSS_CPC[{n}].$USE_PREDICT Access: RW: INTEGER = 1",
    ]
    return "\n".join(lines)


_POS = "\n".join([
    "[*SYSTEM*]$DCSS_CPC  Storage: SHADOW  Access: RW  : ARRAY[32] OF DCSS_CPC_T",
    # diagonal keep-out fence in a rotated frame (mirrors the live zone shape)
    _cpc_zone(1, "FenceKO", 1, 1, 1, 21, 8,
              [-3839.63, -139.63], [2522.03, 2222.03], 3247.08, -1752.92),
    # untouched slot - factory defaults
    _cpc_zone(2, "", 0, 0, 1, 0, 8, [], [], 0.0, 0.0),
    # unknown $MODE with a real 4-vertex polygon -> heuristic shape
    _cpc_zone(3, "Conveyor", 1, 3, 2, 0, 4,
              [0.0, 1000.0, 1000.0, 0.0], [0.0, 0.0, 500.0, 500.0],
              100.0, 900.0, stop=1),
    "[*SYSTEM*]$DCSS_CSC  Storage: SHADOW  Access: RW  : ARRAY[16] OF DCSS_CSC_T",
    "     Field: $DCSS_CSC[1].$COMMENT Access: RW: STRING[25] = ''",
    "     Field: $DCSS_CSC[1].$ENABLE Access: RW: INTEGER = 1",
    "     Field: $DCSS_CSC[1].$MODE Access: RW: INTEGER = 0",
    "     Field: $DCSS_CSC[1].$GRP_NUM Access: RW: INTEGER = 1",
    "     Field: $DCSS_CSC[1].$TCP Access: RW: INTEGER = 0",
    "     Field: $DCSS_CSC[1].$UFRM_NUM Access: RW: INTEGER = 0",
    "     Field: $DCSS_CSC[1].$SPD_LIM Access: RW: REAL = 2.500000e+02",
    "     Field: $DCSS_CSC[1].$STOP_TYP Access: RW: INTEGER = 0",
    "     Field: $DCSS_CSC[1].$STOP_TOL Access: RW: REAL = 0.000000e+00",
    # a table the parser must skip untouched
    "[*SYSTEM*]$DCSS_TCP  Storage: SHADOW  Access: RW  : ARRAY[8,10] OF DCSS_TCP_T",
    "     Field: $DCSS_TCP[1,1].$X Access: RW: REAL = 9.990000e+02",
    "[*SYSTEM*]$DCSS_JPC  Storage: SHADOW  Access: RW  : ARRAY[40] OF DCSS_JPC_T",
    "     Field: $DCSS_JPC[1].$COMMENT Access: RW: STRING[25] = 'J2 window'",
    "     Field: $DCSS_JPC[1].$ENABLE Access: RW: INTEGER = 1",
    "     Field: $DCSS_JPC[1].$MODE Access: RW: INTEGER = 0",
    "     Field: $DCSS_JPC[1].$GRP_NUM Access: RW: INTEGER = 1",
    "     Field: $DCSS_JPC[1].$AXS_NUM Access: RW: INTEGER = 2",
    "     Field: $DCSS_JPC[1].$UPR_LIM Access: RW: REAL = 9.500000e+01",
    "     Field: $DCSS_JPC[1].$LWR_LIM Access: RW: REAL = -3.000000e+01",
    "     Field: $DCSS_JPC[1].$STOP_TYP Access: RW: INTEGER = 1",
    "[*SYSTEM*]$DCSS_JSC  Storage: SHADOW  Access: RW  : ARRAY[40] OF DCSS_JSC_T",
    "     Field: $DCSS_JSC[1].$COMMENT Access: RW: STRING[25] = ''",
    "     Field: $DCSS_JSC[1].$ENABLE Access: RW: INTEGER = 0",
    "     Field: $DCSS_JSC[1].$GRP_NUM Access: RW: INTEGER = 1",
    "     Field: $DCSS_JSC[1].$AXS_NUM Access: RW: INTEGER = 1",
    "     Field: $DCSS_JSC[1].$SPD_LIM Access: RW: REAL = 0.000000e+00",
    "[*SYSTEM*]$DCSS_UFRM  Storage: SHADOW  Access: RW  : ARRAY[8,9] OF DCSS_UFRM_T",
    "       Field: $DCSS_UFRM[1,1].$COMMENT Access: RW: STRING[25] = 'CPC SafeZones'",
    "       Field: $DCSS_UFRM[1,1].$UFRM_NUM Access: RW: INTEGER = 21",
    "       Field: $DCSS_UFRM[1,1].$X Access: RW: REAL = 1.000000e+02",
    "       Field: $DCSS_UFRM[1,1].$Y Access: RW: REAL = 0.000000e+00",
    "       Field: $DCSS_UFRM[1,1].$Z Access: RW: REAL = 0.000000e+00",
    "       Field: $DCSS_UFRM[1,1].$W Access: RW: REAL = 0.000000e+00",
    "       Field: $DCSS_UFRM[1,1].$P Access: RW: REAL = 0.000000e+00",
    "       Field: $DCSS_UFRM[1,1].$R Access: RW: REAL = -4.500000e+01",
    "       Field: $DCSS_UFRM[1,2].$COMMENT Access: RW: STRING[25] = ''",
    "       Field: $DCSS_UFRM[1,2].$UFRM_NUM Access: RW: INTEGER = 0",
    "       Field: $DCSS_UFRM[1,2].$X Access: RW: REAL = 0.000000e+00",
])

_VRFY = """F Number: F999999
VERSION : SpotTool+
$VERSION: V8.33258     10/28/2024
DATE:     12-JUN-26 13:29
DCS Version: V3.5.21

--- Cartesian Position Check -----------
  Process time factor (Max.1000):  450
 No.        G M Status     Comment
  1 ENABLE  1 DO SAFE [FenceKO         ]
  2 DISABLE 1 DI ---- [                ]

    No.  1              Status:SAFE
  1 Comment:   [FenceKO                ]
  2 Enable/Disable:            ENABLE
  3 Method(Safe side): Diagonal(OUT)
  4 Group:                            1
  8 User frame:                      21
    Position(mm):
        Current      Point 1    Point 2
  9 X     881.1    -3839.6     -139.6
 10 Y     731.5     2522.0     2222.0
 11 Z    1303.3     3247.1    -1752.9
 12 Stop type:         Power-Off stop
 14 Use Stop Position Prediction: Yes

--- User model -------------------------
 No.    Elements   Status   Comment
  1 2 OK [robot model]

No.  1 [robot model]
Element:  1  Status: OK
  1 Link No:                          1

--- Signature number (Dec) -------------
  1 DCS:   123  123
"""


def _rep():
    return dcs.parse_dcs_report(_VRFY)


def test_va_geometry_frames_and_heuristics():
    z = dcszones.build_zones(_POS, None)
    assert z["source"] == "va"
    assert z["groups"] == [1, 2]

    fence, empty, conv = z["cpc"]
    assert fence["label"] == "FenceKO" and fence["enabled"]
    # $MODE=1 is the one observed ground-truth mapping
    assert (fence["method"], fence["side"], fence["method_source"]) == ("diagonal", "out", "va")
    # diagonal -> a 4-corner box from the two diagonal points, Z normalized lo/hi
    assert fence["poly"] == [[-3839.63, 2522.03], [-139.63, 2522.03],
                             [-139.63, 2222.03], [-3839.63, 2222.03]]
    assert (fence["z1"], fence["z2"]) == (-1752.92, 3247.08)
    # rotated DCS user frame resolved by (group, frame NUMBER)
    assert fence["frame"]["num"] == 21 and fence["frame"]["r"] == -45.0
    assert fence["frame"]["x"] == 100.0 and fence["frame"]["comment"] == "CPC SafeZones"
    assert not fence["frame_missing"]
    # va-only zones still carry a pendant-shaped detail block
    assert any("pos_table" in d for d in fence["detail"])

    assert not empty["enabled"] and empty["label"] == "zone 2"

    # unknown $MODE + vertices beyond the first two -> polygon heuristic
    assert conv["method"] == "?" and conv["method_source"] == "heuristic"
    assert conv["poly"] == [[0.0, 0.0], [1000.0, 0.0], [1000.0, 500.0], [0.0, 500.0]]
    assert conv["group"] == 2 and conv["stop"] == "Controlled stop"

    jpc = z["jpc"][0]
    assert (jpc["axis"], jpc["low"], jpc["high"], jpc["side"]) == (2, -30.0, 95.0, "in")
    assert jpc["label"] == "J2 window" and jpc["stop"] == "Controlled stop"
    csc = z["csc"][0]
    assert csc["enabled"] and csc["limit"] == 250.0
    assert not z["jsc"][0]["enabled"]
    assert z["tcp"] is None and z["models"] == []


def test_vrfy_merge_wins_and_tcp():
    z = dcszones.build_zones(_POS, _rep())
    assert z["source"] == "va+dg" and z["date"] == "12-JUN-26 13:29"
    fence = z["cpc"][0]
    assert fence["method_source"] == "vrfy" and fence["method_text"] == "Diagonal(OUT)"
    assert fence["status"] == "SAFE" and fence["stop"] == "Power-Off stop"
    # the verify detail block (with the pendant's position table) rides along
    assert any("pos_table" in d for d in fence["detail"])
    # TCP at report time, frame-local + that zone's frame for the transform
    assert z["tcp"]["xyz"] == [881.1, 731.5, 1303.3]
    assert z["tcp"]["frame"]["num"] == 21 and not z["tcp"]["approx"]
    assert [m["label"] for m in z["models"]] == ["robot model"]


def test_dg_fallback_is_flagged_approx():
    z = dcszones.build_zones(None, _rep())
    assert z["source"] == "dg"
    assert len(z["cpc"]) == 1  # zone 2 has no detail table to rebuild from
    fence = z["cpc"][0]
    assert fence["approx"] and fence["enabled"]
    assert fence["poly"] == [[-3839.6, 2522.0], [-139.6, 2522.0],
                             [-139.6, 2222.0], [-3839.6, 2222.0]]
    assert (fence["z1"], fence["z2"]) == (-1752.9, 3247.1)
    # frame rotation isn't in the report: flagged missing, drawn frame-less
    assert fence["ufrm_num"] == 21 and fence["frame"] is None and fence["frame_missing"]
    assert z["tcp"]["approx"]


def test_empty_sources_stay_total():
    z = dcszones.build_zones(None, None)
    assert z["cpc"] == [] and z["jpc"] == [] and z["models"] == []
    assert z["groups"] == [1] and z["tcp"] is None
