from pokerbot.opponents.aliases import canonical


def test_nickname_maps_to_canonical():
    assert canonical("Hungry horse") == "bizz"
    assert canonical("hungry horse") == "bizz"      # case-insensitive
    assert canonical("  Hungry horse  ") == "bizz"  # trimmed


def test_capitalization_variants_collapse():
    assert canonical("Shivas") == "shivas"
    assert canonical("shivas") == "shivas"
    assert canonical("SHIVAS") == "shivas"


def test_unknown_names_pass_through_trimmed():
    assert canonical("vik") == "vik"
    assert canonical(" Arnav Shah ") == "Arnav Shah"
    assert canonical("") == ""
    assert canonical(None) == ""
