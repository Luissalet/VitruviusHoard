from conftest import default_probe

from vitruvius_hoard.lint import CHECKS, CHECK_IDS, run_lint


def ids_of(result):
    return {f["check_id"] for f in result["findings"]}


def test_all_checks_registered_and_ids_match():
    assert len(CHECKS) == len(CHECK_IDS) == 29
    assert len(set(CHECK_IDS)) == 29


def test_clean_probe_triggers_few_or_no_findings():
    result = run_lint(default_probe(), "<html lang='en'><body><h1>Hi</h1></body></html>")
    assert result["score"] >= 8.0


def test_font_generic_only():
    probe = default_probe(generic_defaults={"fonts_only_generic": True})
    result = run_lint(probe, "<html></html>")
    assert "font.generic-only" in ids_of(result)


def test_font_generic_only_negative():
    result = run_lint(default_probe(), "<html></html>")
    assert "font.generic-only" not in ids_of(result)


def test_font_too_many_families():
    probe = default_probe(fonts={"loaded": ["A", "B", "C", "D", "E"]})
    result = run_lint(probe, "<html></html>")
    assert "font.too-many-families" in ids_of(result)


def test_font_too_many_families_negative():
    probe = default_probe(fonts={"loaded": ["A", "B"]})
    result = run_lint(probe, "<html></html>")
    assert "font.too-many-families" not in ids_of(result)


def test_color_low_contrast():
    probe = default_probe(contrast_pairs=[{"color": "rgb(180,180,180)", "background": "rgb(200,200,200)", "text": "x"}])
    result = run_lint(probe, "<html></html>")
    assert "color.low-contrast" in ids_of(result)


def test_color_low_contrast_negative():
    probe = default_probe(contrast_pairs=[{"color": "rgb(0,0,0)", "background": "rgb(255,255,255)", "text": "x"}])
    result = run_lint(probe, "<html></html>")
    assert "color.low-contrast" not in ids_of(result)


def test_color_generic_ai_palette_1():
    probe = default_probe(colors=[{"color": "rgb(5,5,5)", "background": "rgb(255,255,255)"},
                                  {"color": "rgb(50,255,50)", "background": "rgb(0,0,0)"}])
    result = run_lint(probe, "<html></html>")
    assert "color.generic-ai-palette-1" in ids_of(result)


def test_color_generic_ai_palette_1_negative():
    result = run_lint(default_probe(), "<html></html>")
    assert "color.generic-ai-palette-1" not in ids_of(result)


def test_color_generic_ai_palette_2():
    probe = default_probe(colors=[{"color": "rgb(180,80,60)", "background": "rgb(250,240,222)"}],
                          fonts={"loaded": [], "h1": "Playfair Display, serif", "p": "Inter"})
    result = run_lint(probe, "<html></html>")
    assert "color.generic-ai-palette-2" in ids_of(result)
    # the same colours with a sans heading are not the stock triad
    probe = default_probe(colors=[{"color": "rgb(180,80,60)", "background": "rgb(250,240,222)"}],
                          fonts={"loaded": [], "h1": "Inter, sans-serif", "p": "Inter"})
    assert "color.generic-ai-palette-2" not in ids_of(run_lint(probe, "<html></html>"))


def test_color_generic_ai_palette_2_negative():
    result = run_lint(default_probe(), "<html></html>")
    assert "color.generic-ai-palette-2" not in ids_of(result)


def test_color_generic_ai_palette_3():
    probe = default_probe(colors=[
        {"color": "rgb(20,20,20)", "background": "rgb(255,255,255)"},
        {"color": "rgb(230,230,230)", "background": "rgb(240,240,240)"},
        {"color": "rgb(100,100,100)", "background": "rgb(90,90,90)"},
        {"color": "rgb(60,80,220)", "background": "rgb(255,255,255)"},
    ])
    result = run_lint(probe, "<html></html>")
    assert "color.generic-ai-palette-3" in ids_of(result)


def test_color_generic_ai_palette_3_negative():
    result = run_lint(default_probe(), "<html></html>")
    assert "color.generic-ai-palette-3" not in ids_of(result)


def test_color_purple_blue_gradient():
    probe = default_probe(generic_defaults={"purple_blue_gradient_buttons": True})
    result = run_lint(probe, "<html></html>")
    assert "color.purple-blue-gradient" in ids_of(result)


def test_color_purple_blue_gradient_negative():
    result = run_lint(default_probe(), "<html></html>")
    assert "color.purple-blue-gradient" not in ids_of(result)


def test_layout_hero_three_cards():
    html = '<div class="hero"></div><div class="card"></div><div class="card"></div><div class="card"></div>'
    result = run_lint(default_probe(), html)
    assert "layout.hero-three-cards" in ids_of(result)


def test_layout_hero_three_cards_negative_four_cards():
    html = '<div class="hero"></div>' + '<div class="card"></div>' * 4
    result = run_lint(default_probe(), html)
    assert "layout.hero-three-cards" not in ids_of(result)


def test_layout_no_max_width():
    result = run_lint(default_probe(), "<html><body>no constraint here</body></html>")
    assert "layout.no-max-width" in ids_of(result)


def test_layout_no_max_width_negative():
    result = run_lint(default_probe(), "<style>.wrap{max-width:72ch}</style>")
    assert "layout.no-max-width" not in ids_of(result)


def test_layout_horizontal_overflow():
    result = run_lint(default_probe(), "<style>.x{width: 2000px;}</style>")
    assert "layout.horizontal-overflow" in ids_of(result)


def test_layout_horizontal_overflow_negative_with_handling():
    result = run_lint(default_probe(), "<style>.x{width: 2000px; overflow-x: hidden;}</style>")
    assert "layout.horizontal-overflow" not in ids_of(result)


def test_type_scale_flat():
    probe = default_probe(font_sizes=["16px"])
    result = run_lint(probe, "<html></html>")
    assert "type.scale-flat" in ids_of(result)


def test_type_scale_flat_negative():
    probe = default_probe(font_sizes=["16px", "24px", "40px", "12px"])
    result = run_lint(probe, "<html></html>")
    assert "type.scale-flat" not in ids_of(result)


def test_type_line_length():
    probe = default_probe(long_paragraphs=3)
    result = run_lint(probe, "<html></html>")
    assert "type.line-length" in ids_of(result)


def test_type_line_length_negative():
    result = run_lint(default_probe(long_paragraphs=0), "<html></html>")
    assert "type.line-length" not in ids_of(result)


def test_motion_no_reduced_motion():
    probe = default_probe(reduced_motion_css_present=False)
    result = run_lint(probe, "<html></html>")
    assert "motion.no-reduced-motion" in ids_of(result)


def test_motion_no_reduced_motion_negative():
    probe = default_probe(reduced_motion_css_present=True)
    result = run_lint(probe, "<html></html>")
    assert "motion.no-reduced-motion" not in ids_of(result)


def test_motion_everything_animates():
    probe = default_probe(animations_count=20)
    result = run_lint(probe, "<html></html>")
    assert "motion.everything-animates" in ids_of(result)


def test_motion_everything_animates_negative():
    probe = default_probe(animations_count=3)
    result = run_lint(probe, "<html></html>")
    assert "motion.everything-animates" not in ids_of(result)


def test_motion_long_durations():
    probe = default_probe(long_transition_count=2)
    result = run_lint(probe, "<html></html>")
    assert "motion.long-durations" in ids_of(result)


def test_motion_long_durations_negative():
    probe = default_probe(long_transition_count=0)
    result = run_lint(probe, "<html></html>")
    assert "motion.long-durations" not in ids_of(result)


def test_motion_linear_easing():
    probe = default_probe(linear_easing_count=1)
    result = run_lint(probe, "<html></html>")
    assert "motion.linear-easing" in ids_of(result)


def test_motion_linear_easing_negative():
    probe = default_probe(linear_easing_count=0)
    result = run_lint(probe, "<html></html>")
    assert "motion.linear-easing" not in ids_of(result)


def test_a11y_missing_alt():
    probe = default_probe(images_without_alt=2)
    result = run_lint(probe, "<html></html>")
    assert "a11y.missing-alt" in ids_of(result)


def test_a11y_missing_alt_negative():
    probe = default_probe(images_without_alt=0)
    result = run_lint(probe, "<html></html>")
    assert "a11y.missing-alt" not in ids_of(result)


def test_a11y_small_targets():
    probe = default_probe(small_tap_targets=3)
    result = run_lint(probe, "<html></html>")
    assert "a11y.small-targets" in ids_of(result)


def test_a11y_small_targets_negative():
    probe = default_probe(small_tap_targets=0)
    result = run_lint(probe, "<html></html>")
    assert "a11y.small-targets" not in ids_of(result)


def test_a11y_heading_order_skip():
    probe = default_probe(heading_order=[1, 3])
    result = run_lint(probe, "<html></html>")
    assert "a11y.heading-order" in ids_of(result)


def test_a11y_heading_order_multiple_h1():
    probe = default_probe(heading_order=[1, 1, 2])
    result = run_lint(probe, "<html></html>")
    assert "a11y.heading-order" in ids_of(result)


def test_a11y_heading_order_negative():
    probe = default_probe(heading_order=[1, 2, 3])
    result = run_lint(probe, "<html></html>")
    assert "a11y.heading-order" not in ids_of(result)


def test_a11y_no_lang():
    probe = default_probe(lang=None)
    result = run_lint(probe, "<html></html>")
    assert "a11y.no-lang" in ids_of(result)


def test_a11y_no_lang_negative():
    probe = default_probe(lang="en")
    result = run_lint(probe, "<html></html>")
    assert "a11y.no-lang" not in ids_of(result)


def test_a11y_no_focus_visible():
    html = "<style>a{outline:none}</style>"
    result = run_lint(default_probe(), html)
    assert "a11y.no-focus-visible" in ids_of(result)


def test_a11y_no_focus_visible_negative_with_replacement():
    html = "<style>a{outline:none} a:focus-visible{outline:2px solid blue}</style>"
    result = run_lint(default_probe(), html)
    assert "a11y.no-focus-visible" not in ids_of(result)


def test_content_lorem_ipsum():
    result = run_lint(default_probe(), "<p>Lorem ipsum dolor sit amet</p>")
    assert "content.lorem-ipsum" in ids_of(result)


def test_content_lorem_ipsum_negative():
    result = run_lint(default_probe(), "<p>Real copy about real things.</p>")
    assert "content.lorem-ipsum" not in ids_of(result)


def test_content_emoji_icons():
    probe = default_probe(generic_defaults={"emoji_icons": True})
    result = run_lint(probe, "<html></html>")
    assert "content.emoji-icons" in ids_of(result)


def test_content_emoji_icons_negative():
    result = run_lint(default_probe(), "<html></html>")
    assert "content.emoji-icons" not in ids_of(result)


def test_content_placeholder_copy():
    result = run_lint(default_probe(), "<p>Welcome to Your Company</p>")
    assert "content.placeholder-copy" in ids_of(result)


def test_content_placeholder_copy_negative():
    result = run_lint(default_probe(), "<p>Welcome to Acme Robotics</p>")
    assert "content.placeholder-copy" not in ids_of(result)


def test_perf_dom_size():
    probe = default_probe(dom_size=3000)
    result = run_lint(probe, "<html></html>")
    assert "perf.dom-size" in ids_of(result)


def test_perf_dom_size_negative():
    probe = default_probe(dom_size=200)
    result = run_lint(probe, "<html></html>")
    assert "perf.dom-size" not in ids_of(result)


def test_perf_images_unsized():
    result = run_lint(default_probe(), '<img src="a.png">')
    assert "perf.images-unsized" in ids_of(result)


def test_perf_images_unsized_negative():
    result = run_lint(default_probe(), '<img src="a.png" width="10" height="10">')
    assert "perf.images-unsized" not in ids_of(result)


def test_perf_large_transfer():
    probe = default_probe(total_transfer_bytes=6_000_000)
    result = run_lint(probe, "<html></html>")
    assert "perf.large-transfer" in ids_of(result)


def test_perf_large_transfer_negative_when_absent():
    result = run_lint(default_probe(), "<html></html>")
    assert "perf.large-transfer" not in ids_of(result)


def test_viewport_missing():
    probe = default_probe(viewport_meta=None)
    result = run_lint(probe, "<html></html>")
    assert "viewport.missing" in ids_of(result)


def test_viewport_missing_negative():
    probe = default_probe(viewport_meta="width=device-width")
    result = run_lint(probe, "<html></html>")
    assert "viewport.missing" not in ids_of(result)


def test_dark_no_scheme():
    probe = default_probe(color_scheme_present=False)
    result = run_lint(probe, "<html></html>")
    assert "dark.no-scheme" in ids_of(result)


def test_dark_no_scheme_negative():
    probe = default_probe(color_scheme_present=True)
    result = run_lint(probe, "<html></html>")
    assert "dark.no-scheme" not in ids_of(result)


def test_run_lint_counts_and_score_shape():
    result = run_lint(default_probe(images_without_alt=1), "<html></html>")
    assert set(result.keys()) == {"findings", "score", "counts"}
    assert isinstance(result["score"], float)
    assert set(result["counts"].keys()) >= {"info", "warn", "error"}


def test_run_lint_handles_empty_inputs_gracefully():
    result = run_lint({}, "")
    assert isinstance(result["findings"], list)
    assert 0.0 <= result["score"] <= 10.0
