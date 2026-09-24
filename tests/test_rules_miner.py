from vitruvius_hoard.ingest.rules import mine_rules


def test_mines_never_bullet_as_error():
    text = "- Never disable focus outlines without a replacement."
    rules = mine_rules(text, "src1")
    assert len(rules) == 1
    assert rules[0]["severity"] == "error"
    assert rules[0]["area"] == "a11y"
    assert rules[0]["check_id"] == "a11y.no-focus-visible"


def test_mines_avoid_bullet_as_warn():
    text = "* Avoid the purple to blue gradient on buttons."
    rules = mine_rules(text, "src1")
    assert rules[0]["severity"] == "warn"
    assert rules[0]["area"] == "color"


def test_mines_always_bullet_as_info():
    text = "1. Always set a max-width on the main content column."
    rules = mine_rules(text, "src1")
    assert rules[0]["severity"] == "info"
    assert rules[0]["area"] == "layout"
    assert rules[0]["check_id"] == "layout.no-max-width"


def test_ignores_lines_without_bullet_marker():
    text = "Never do this (but not a bullet line)."
    assert mine_rules(text, "src1") == []


def test_ignores_bullets_without_keyword():
    text = "- Just a regular bullet point about spacing between sections."
    assert mine_rules(text, "src1") == []


def test_area_guessing_typography():
    text = "- Don't use more than two font families on a page."
    rules = mine_rules(text, "src1")
    assert rules[0]["area"] == "typography"


def test_area_guessing_motion():
    text = "- Always respect reduced motion preferences in animations."
    rules = mine_rules(text, "src1")
    assert rules[0]["area"] == "motion"


def test_title_is_first_sentence_truncated():
    text = "- Never use lorem ipsum placeholder text. It looks unfinished and unprofessional in a final deliverable."
    rules = mine_rules(text, "src1")
    assert rules[0]["title"] == "Never use lorem ipsum placeholder text"
    assert rules[0]["check_id"] == "content.lorem-ipsum"


def test_multiple_bullets_produce_multiple_rules():
    text = "- Never skip heading levels.\n- Always add alt text to meaningful images."
    rules = mine_rules(text, "src1")
    assert len(rules) == 2
