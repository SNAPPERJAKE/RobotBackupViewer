"""Label cross-reference: LBL definitions + the JMPs that target them.

Fully synthetic and identifier-clean - no sample backup needed.
"""
from backupviewer.parsers.ls_program import label_xref, parse_ls_program

LBL_LS = """/PROG  TESTNAV
/ATTR
COMMENT\t\t= "LBL XREF";
/MN
   1:  !setup ;
   2:  LBL[1:TOP] ;
   3:  IF DI[7]=ON,JMP LBL[2] ;
   4:  R[1]=R[1]+1 ;
   5:  JMP LBL[1] ;
   6:  LBL[2:DONE] ;
   7:  ! JMP LBL[1] ;
   8:  JMP LBL[99] ;
   9:  LBL[3] ;
/POS
/END
"""


def test_label_xref():
    p = parse_ls_program(LBL_LS)
    order = [e["id"] for e in p["labels"]]
    assert order == [1, 2, 3, 99]  # program order, broken jumps trailing
    L = {e["id"]: e for e in p["labels"]}
    assert L[1] == {"id": 1, "name": "TOP", "line": 2, "jumps": [5]}
    assert L[2]["line"] == 6 and L[2]["jumps"] == [3]  # forward jump resolves
    assert L[3]["line"] == 9 and L[3]["jumps"] == []   # unreferenced, still listed
    assert L[99]["line"] is None and L[99]["jumps"] == [8]  # JMP to nowhere
    assert 7 not in L[1]["jumps"]  # commented-out JMP is not a jump


def test_label_xref_not_fooled_by_lookalikes():
    body = [
        {"n": 1, "text": "!LBL[4]"},          # commented definition defines nothing
        {"n": 2, "text": "LBL[6],DO[1]=ON"},  # label id in a compound line - not a definition
    ]
    out = label_xref(body)
    ids = {e["id"] for e in out}
    assert 4 not in ids and 6 not in ids
