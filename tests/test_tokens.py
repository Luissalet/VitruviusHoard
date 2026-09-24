import re

from vitruvius_hoard import tokens as T


def test_srgb_linear_roundtrip():
    for c in (0.0, 0.02, 0.2, 0.5, 0.99, 1.0):
        assert abs(T.linear_to_srgb(T.srgb_to_linear(c)) - c) < 1e-6


def test_hex_oklch_roundtrip():
    for hexv in ("#000000", "#ffffff", "#3355ff", "#ff0033", "#00aa88"):
        L, c, h = T.hex_to_oklch(hexv)
        assert T.oklch_to_hex(L, c, h) == hexv


def test_parse_hex_accepts_short_form():
    assert T.parse_hex("#fff") == (1.0, 1.0, 1.0)
    assert T.parse_hex("abc") == T.parse_hex("#aabbcc")


def test_parse_hex_rejects_garbage():
    import pytest
    with pytest.raises(ValueError):
        T.parse_hex("not-a-color")


def test_gamut_clamp_returns_in_range_rgb():
    r, g, b = T.oklch_to_rgb01(0.7, 5.0, 250.0)  # absurdly high chroma
    assert 0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0


def test_gamut_clamp_noop_for_small_chroma():
    r, g, b = T.oklch_to_rgb01(0.7, 0.05, 250.0)
    r2, g2, b2 = T.oklch_to_rgb01(0.7, 0.05, 250.0, clamp=False)
    assert abs(r - r2) < 1e-6 and abs(g - g2) < 1e-6 and abs(b - b2) < 1e-6


def test_contrast_ratio_black_white_is_21():
    assert abs(T.contrast_ratio("#000000", "#ffffff") - 21.0) < 0.01


def test_contrast_ratio_same_color_is_one():
    assert abs(T.contrast_ratio("#336699", "#336699") - 1.0) < 0.01


def test_contrast_ratio_symmetric():
    a = T.contrast_ratio("#111111", "#eeeeee")
    b = T.contrast_ratio("#eeeeee", "#111111")
    assert abs(a - b) < 1e-9


def test_wcag_level_thresholds():
    assert T.wcag_level(8.0) == "AAA"
    assert T.wcag_level(5.0) == "AA"
    assert T.wcag_level(2.0) == "fail"


def test_best_on_color_picks_higher_contrast():
    assert T.best_on_color("#0a0a0f") == "#ffffff"
    assert T.best_on_color("#fefefe") == "#0a0a0f"


def test_make_ramp_has_all_steps():
    ramp = T.make_ramp(250.0, 0.15)
    assert list(ramp.keys()) == [str(s) for s in T.RAMP_STEPS]
    assert all(re.match(r"^#[0-9a-f]{6}$", v) for v in ramp.values())


def test_make_ramp_lightness_decreases_with_step():
    ramp = T.make_ramp(250.0, 0.15)
    lum_50 = T.relative_luminance(ramp["50"])
    lum_950 = T.relative_luminance(ramp["950"])
    assert lum_50 > lum_950


def test_neutral_ramp_low_chroma():
    ramp = T.neutral_ramp(250.0)
    assert len(ramp) == len(T.RAMP_STEPS)


def test_type_scale_has_expected_keys_and_clamp_format():
    scale = T.type_scale()
    assert "base" in scale and "xl" in scale
    assert scale["base"].startswith("clamp(")


def test_generate_default_brief_has_all_sections():
    tokens = T.generate({"name": "demo"})
    for key in ("color", "typography", "spacing", "radius", "shadow", "motion", "z_index", "breakpoints"):
        assert key in tokens
    assert set(tokens["color"]["primary"].keys()) == {str(s) for s in T.RAMP_STEPS}
    assert "success" in tokens["color"]["semantic"]


def test_generate_with_base_color():
    tokens = T.generate({"name": "demo", "base_color": "#ff5500"})
    assert tokens["hue"] is not None


def test_generate_density_scales_spacing():
    compact = T.generate({"name": "d", "density": "compact"})
    spacious = T.generate({"name": "d", "density": "spacious"})
    v_compact = float(compact["spacing"]["4"].replace("px", ""))
    v_spacious = float(spacious["spacing"]["4"].replace("px", ""))
    assert v_spacious > v_compact


def test_generate_motion_intensity_scales_duration():
    low = T.generate({"name": "d", "motion_intensity": 1})
    high = T.generate({"name": "d", "motion_intensity": 10})
    assert high["motion"]["duration"]["base"] > low["motion"]["duration"]["base"]


def test_generate_style_controls_radius_and_shadow():
    sharp = T.generate({"name": "d", "style": "sharp"})
    pill = T.generate({"name": "d", "style": "pill"})
    assert sharp["radius"] != pill["radius"]


def test_to_flat_returns_dashed_keys():
    tokens = T.generate({"name": "d"})
    flat = T.to_flat(tokens)
    assert any(k.startswith("color-primary-500") for k in flat)


def test_to_w3c_has_value_and_type():
    tokens = T.generate({"name": "d"})
    w3c = T.to_w3c(tokens)
    node = w3c["color"]["primary"]["500"]
    assert node["$value"].startswith("#")
    assert node["$type"] == "color"


def test_to_css_contains_root_and_dark_theme():
    tokens = T.generate({"name": "d"})
    css = T.to_css(tokens)
    assert ":root {" in css
    assert '[data-theme="dark"]' in css
    assert "prefers-color-scheme: dark" in css
    assert "--color-primary-500" in css


def test_to_tailwind_contains_theme_block():
    tokens = T.generate({"name": "d"})
    tw = T.to_tailwind(tokens)
    assert tw.strip().startswith("@theme {")
    assert "--color-primary-500" in tw


def test_playground_html_contains_all_sections():
    tokens = T.generate({"name": "Demo System"})
    html = T.playground_html(tokens)
    for section_id in ("colors", "type", "space", "components", "motion"):
        assert f'id="{section_id}"' in html


def test_playground_html_respects_reduced_motion():
    tokens = T.generate({"name": "d"})
    html = T.playground_html(tokens)
    assert "prefers-reduced-motion: reduce" in html


def test_playground_html_dark_variant_sets_attribute():
    tokens = T.generate({"name": "d"})
    html = T.playground_html(tokens, dark=True)
    assert 'data-theme="dark"' in html


def test_playground_html_is_self_contained_no_external_requests():
    tokens = T.generate({"name": "d"})
    html = T.playground_html(tokens)
    assert "http://" not in html and "https://" not in html
