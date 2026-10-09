from __future__ import annotations

import pandas as pd
import pytest

from pipeline import targets as T


@pytest.mark.parametrize(
    "desc, name, depth, side",
    [
        ("(5:43) (Shotgun) D.Prescott pass incomplete deep left to C.Lamb.", "C.Lamb", "deep", "left"),
        ("(:39) (Shotgun) D.Prescott pass deep right to A.Cooper for 21 yards, TOUCHDOWN.", "A.Cooper", "deep", "right"),
        ("(9:09) D.Prescott pass incomplete short left to A.Cooper. PENALTY on TB-C.Davis", "A.Cooper", "short", "left"),
        ("J.Brissett pass deep right intended for M.Gesicki INTERCEPTED by L.Wallace at BUF 15.", "M.Gesicki", "deep", "right"),
        ("J.Goff pass incomplete deep left to A.St. Brown.", "A.St. Brown", "deep", "left"),
        ("T.Brady pass short middle to T.Johnson to NO 44 for 8 yards (B.Roby).", "T.Johnson", "short", "middle"),
        ("Aa.Rodgers pass short right to A.Lazard pushed ob at GB 39 for 11 yards", "A.Lazard", "short", "right"),
        ("J.Allen pass incomplete short left.", None, "short", "left"),
        ("D.Jones pass deep right INTERCEPTED by M.Williams at NO 2.", None, "deep", "right"),
    ],
)
def test_parse_description(desc, name, depth, side):
    p = T.parse_description(desc)
    assert (p["targetName"], p["depth"], p["side"]) == (name, depth, side)


@pytest.mark.parametrize(
    "abbrev, expected",
    [("C.Lamb", ("c", "lamb")), ("A.St. Brown", ("a", "stbrown")), ("A.J. Brown", ("aj", "brown")),
     ("Dj.Moore", ("dj", "moore")), ("O.Beckham Jr.", ("o", "beckham"))],
)
def test_split_abbrev(abbrev, expected):
    assert T.split_abbrev(abbrev) == expected


CANDIDATES = pd.DataFrame(
    {
        "nflId": [1, 2, 3, 4, 5, 6, 48415],
        "displayName": ["CeeDee Lamb", "Amari Cooper", "Amon-Ra St. Brown", "D.J. Moore", "Mike Williams", "Mike Williams", "Deonte Harty"],
    }
)


@pytest.mark.parametrize(
    "abbrev, nfl_id, how",
    [
        ("C.Lamb", 1, "unique"),
        ("A.Cooper", 2, "unique"),
        ("A.St. Brown", 3, "unique"),
        ("Dj.Moore", 4, "unique"),
        ("M.Williams", None, "multi"),
        ("D.Harris", 48415, "unique"),  # listed under his later name
        ("X.Nobody", None, "none"),
        ("", None, "no_name"),
    ],
)
def test_match_target(abbrev, nfl_id, how):
    assert T.match_target(abbrev, CANDIDATES) == (nfl_id, how)


def test_sector_distance():
    assert T.sector_distance(45.0, "left") == 0.0
    assert T.sector_distance(-45.0, "left") == pytest.approx(55.0)
    assert T.sector_distance(0.0, "middle") == 0.0
    assert T.sector_distance(80.0, "middle") == pytest.approx(50.0)


@pytest.mark.data
def test_targets_on_real_data():
    t = T.build_targets(with_ball=False, verbose=False)
    tab = T.match_table(t)
    print("\n" + tab.to_string())
    named = t[t["passResult"].isin(["C", "I", "IN"]) & t["targetName"].notna()]
    share = (named["targetMatch"] == "unique").mean()
    assert share >= 0.99, f"measured {share:.2%} unique matches among named targets"
    assert tab.loc["I", "no_name"] == 253
    demo = t[(t["gameId"] == 2021090900) & (t["playId"] == 1687)].iloc[0]
    assert demo["targetNflId"] == 52425  # CeeDee Lamb
    assert (demo["depth"], demo["side"]) == ("deep", "left")
