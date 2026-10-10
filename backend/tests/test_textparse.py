from deadlang.textparse import item_type, stated_material


def test_vegetable_ivory_netsuke():
    assert stated_material("Vegetable ivory netsuke", "") == "tagua"
    assert item_type("Vegetable ivory netsuke", "") == "netsuke"


def test_ox_bone_figure():
    assert stated_material("Carved figure", "hand carved from ox bone") == "bone"
    assert item_type("Carved figure", "hand carved from ox bone") == "figurine"


def test_resin_beats_ivory_color():
    assert stated_material("Ivory-colored resin bangle", "") == "resin"
    assert item_type("Ivory-colored resin bangle", "") == "jewelry"


def test_ivory_tone_is_a_color():
    assert stated_material("Ivory tone bead necklace", "") == "ivory_color"
    assert item_type("Ivory tone bead necklace", "") == "jewelry"


def test_boxwood_netsuke():
    assert stated_material("Old netsuke", "boxwood") == "wood"
    assert item_type("Old netsuke", "boxwood") == "netsuke"


def test_unknown_material_carving():
    assert stated_material("Antique carving", "") == "unknown"
    assert item_type("Antique carving", "") == "figurine"


def test_ivory_mentioned():
    assert stated_material("Mammoth ivory?", "") == "ivory_mentioned"


def test_word_boundaries_and_plurals():
    assert stated_material("Trombone player statue", "") == "unknown"   # "bone" inside a word
    assert item_type("Lot of 3 bone carvings", "") == "figurine"
    assert item_type("Spring string", "") == "other"                    # "ring" inside a word
    assert item_type("Plain box", "") == "other"
