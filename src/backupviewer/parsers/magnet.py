"""Magnet end-effector detection + config surfacing.

A magnet gripper is NOT an MH valve - it isn't wired into MHGRIPDT at all. It is
driven by a family of KAREL programs (MAG*.PC on the pendant: MAGFUNCTIONS,
MAGSETREGS, MAGGETTOLVAL, ...) and a block of numeric registers in the ~800s whose
comments start with "Mag" (Mag Power, Mag Select, Mag1 Tolerance, Mag 1 North PPI,
Mag1 North Empty, ...).

Detection is by program: a robot is magnet-equipped when it carries a MAG*.PC KAREL
program. The R[800-899] "Mag ..." registers are surfaced as the magnet's config so
the magnet's info can be grouped on the overview and MH valves screens, even though
it lives outside the valve tables.

The registers split into a "general" block (settings for the currently-active magnet,
selected by "Mag Select" / R[807]) and per-magnet blocks 1-4 (comments carrying a
magnet number, e.g. "Mag1 Tolerance", "Mag 1 North PPI"). "Mag N Var" / "Mag S Var"
are North/South vars, NOT magnet numbers, so they stay in general.
"""
from __future__ import annotations

import re

_REG_LO, _REG_HI = 800, 899
# a magnet number 1-4 right after "Mag" (with or without a space); the negative
# lookahead stops "Mag12"-style false splits. "Mag N/S Var" never match (N/S != digit).
_MAG_NUM = re.compile(r"[Mm]ag\s*([1-4])(?!\d)")


def build_magnet(numreg: list[dict] | None, program_names) -> dict:
    """{"is_magnet", "programs", "registers", "groups", "mag_select", "counts"}.

    `numreg` is parsers.registers.parse_numreg output ({index, value, comment});
    `program_names` is any iterable of program names/stems (KAREL stems are enough).
    `registers` stays a flat list (the MH valves tab renders it as a table); `groups`
    adds the general / per-magnet split for the overview card.
    """
    programs = sorted({
        n for n in (program_names or [])
        if str(n).upper().startswith("MAG")
    })
    registers = [
        r for r in (numreg or [])
        if _REG_LO <= (r.get("index") or 0) <= _REG_HI
        and "mag" in (r.get("comment") or "").lower()
    ]

    general: list[dict] = []
    by_magnet: dict[int, list[dict]] = {}
    mag_select = None
    for r in registers:
        comment = r.get("comment") or ""
        if "mag select" in comment.lower():
            mag_select = r.get("value")
        m = _MAG_NUM.search(comment)
        if m:
            by_magnet.setdefault(int(m.group(1)), []).append(r)
        else:
            general.append(r)
    magnets = [{"n": n, "registers": by_magnet[n]} for n in sorted(by_magnet)]

    return {
        "is_magnet": bool(programs),
        "programs": programs,
        "registers": registers,
        "groups": {"general": general, "magnets": magnets},
        "mag_select": mag_select,
        "counts": {"programs": len(programs), "registers": len(registers)},
    }
