from vitruvius_hoard.lint import run_lint


def node(tag, text="", *, parent=-1, rect=(0, 0, 600, 120), style=None, **fields):
    return {"tag": tag, "t": text, "tl": len(text), "p": parent, "r": rect, "s": style or {}, **fields}


def probe(*elements, **fields):
    return {"dom": {"1440": {"width": 1440, "height": 900, "page_height": 1200,
                             "els": [dict(e, i=i) for i, e in enumerate(elements)]}}, **fields}


def check(rule, snapshot=None, html="", tokens=None):
    report = run_lint(snapshot or {}, html, only=[rule], tokens=tokens)
    assert all(f["title"] != "Check failed" for f in report["findings"])
    return report["findings"]


def test_brand_label_uses_text_lines_even_with_a_decorative_child():
    header = node("header")
    brand = node("a", "Solumbre", parent=0, c="brand", rect=(8, 0, 144, 44), ln=1)
    dot = node("span", "·", parent=1, rect=(136, 14, 6, 12))
    assert not check("craft/button-wrap", probe(header, brand, dot))
    wrapped = dict(brand, t="", tl=0, ln=2)
    assert check("craft/button-wrap", probe(header, wrapped, node("span", "Ver disponibilidad", parent=1)))


def test_reservation_email_is_functional_content_and_subscription_stays_detectable():
    sections = [node("section", rect=(0, y, 1440, 360), id=f"band{i}") for i, y in enumerate((0, 360, 720))]
    hero = node("h1", "Una lámpara hecha a mano", parent=0)
    short_band = node("p", "Materiales", parent=1)
    form = [
        node("form", parent=2),
        node("label", "Correo electrónico", parent=5, **{"for": "email"}),
        node("input", parent=5, ctl="email", id="email"),
        node("button", "Confirmar reserva", parent=5, bt="submit"),
    ]
    snapshot = probe(*sections, hero, short_band, *form)
    assert not check("slop/stock-close", snapshot)
    thin = check("craft/thin-section", snapshot)
    assert len(thin) == 1 and "section#band1" in str(thin[0]["evidence"])
    assert "section#band2" not in str(thin[0]["evidence"])
    form[-1] = dict(form[-1], t="Suscríbete al boletín")
    assert check("slop/stock-close", probe(*sections, hero, short_band, *form))


def test_preset_cream_and_body_face_are_intentional_only_when_selected():
    html = "<style>body{background:#f7f3eb}</style>"
    tokens = {"tokens": {"color": {"surfaces": {"light": {"bg": "#f7f3eb"}}},
                         "typography": {"body": "'IBM Plex Sans', sans-serif"}}}
    snapshot = probe(node("p", "Formulario de alta para quienes trabajen por cuenta propia.",
                          style={"ff": "IBM Plex Sans"}))
    assert check("slop/cream-palette", html=html)
    assert not check("slop/cream-palette", html=html, tokens=tokens)
    assert check("slop/overused-font", snapshot)
    assert not check("slop/overused-font", snapshot, tokens=tokens)
    fallback = [{"role": "body", "declared": "IBM Plex Sans", "used": ["Arial"], "element": "p", "text": "Formulario"}]
    fallback_snapshot = dict(snapshot, rendered_fonts=fallback)
    assert not check("slop/overused-font", fallback_snapshot)
    assert run_lint(fallback_snapshot, html)["rendered_fonts"] == fallback


def test_decorative_arrow_and_single_divider_do_not_turn_into_findings():
    icon = '<button>Continuar <span aria-hidden="true">→</span></button>'
    assert not check("slop/template-punctuation", html=icon)
    assert check("slop/template-punctuation", html="<button><span>Continuar →</span></button>")
    outer = node("div", rect=(0, 0, 720, 600), style={"bw": [1] * 4}, c="registration")
    divider = node("div", "Continuar", parent=0, c="actions", rect=(16, 400, 600, 90), style={"bw": [1, 0, 0, 0]})
    assert not check("slop/nested-cards", probe(outer, divider))
    assert check("slop/nested-cards", probe(outer, dict(divider, s={"bw": [1] * 4})))


def test_label_font_uses_winning_cascade_and_rendered_style():
    markup = ("<style>:root{--body:'Trebuchet MS',sans-serif}.mast-tag{font-family:Consolas,monospace}"
              "%s</style><p>Alta de actividad</p><span class='mast-tag'>Registro municipal</span>")
    rule = "slop/mono-costume"
    assert check(rule, html=markup % "")
    assert not check(rule, html=markup % ".mast-tag{font-family:var(--body)}")
    rendered = probe(node("span", "Registro municipal", c="mast-tag", style={"ff": "Trebuchet MS"}))
    assert not check(rule, rendered, markup % "")


def test_unpainted_steps_do_not_count_and_opening_them_does():
    long_text = " ".join(["documentación"] * 112)
    initial = [node("h1", "Identificación", rect=(0, 30, 500, 38)),
               node("label", "Correo electrónico", rect=(0, 80, 100, 22))]
    receipt = [node("div", long_text, rect=(0, 0, 0, 0), wc=112)]
    steps = [
        node("span", "Nueva solicitud", rect=(0, 180, 220, 20), style={"tt": "uppercase", "fs": 12}),
        node("h2", "Detalles de actividad", rect=(0, 210, 500, 38)),
        node("span", "Revisión y envío", rect=(0, 320, 220, 20), style={"tt": "uppercase", "fs": 12}),
        node("h2", "Confirma los detalles", rect=(0, 350, 500, 38)),
    ]
    hidden = [dict(e, painted=False) for e in steps]
    assert not check("slop/kicker-above-heading", probe(*initial, *receipt, *hidden))
    assert not check("craft/screen-budget", probe(*initial, *receipt, *hidden))
    assert check("slop/kicker-above-heading", probe(*initial, *steps, *receipt))
    shown_receipt = dict(receipt[0], r=(0, 410, 600, 360), t=long_text[:120])
    finding = check("craft/screen-budget", probe(*initial, shown_receipt))[0]
    assert "115 words" in finding["detail"]


def test_short_tap_target_reports_selector_and_dimensions():
    short = {"selector": "#help", "width": 38, "height": 20}
    finding = check("a11y.small-targets", probe(small_tap_targets=1, small_tap_target_details=[short]))[0]
    assert finding["evidence"] == [short]


def test_responsive_lamp_headings_are_distinct_from_off_scale_controls():
    tokens = {"color": {"surfaces": {}}, "typography": {"scale": {"body": "1rem", "title": "3rem"}}}
    headings = [("h1", "Nimbo", "lamp", 146.88, 60), ("h2", "Reserva tu lámpara", "reserve-title", 72, 42),
                ("h2", "Materiales de Nimbo", "spec-title", 72, 42)]
    wide = [node(tag, text, id=ident, style={"fs": size}) for tag, text, ident, size, _ in headings]
    narrow = [node(tag, text, id=ident, style={"fs": size}) for tag, text, ident, _, size in headings]
    controls = [node("button", "Confirmar reserva", style={"fs": size}) for size in (12, 22, 26)]
    mobile = dict(probe(*narrow)["dom"]["1440"], width=390)
    snapshot = probe(*wide)
    snapshot["dom"]["390"] = mobile
    assert not check("ds/scale", snapshot, tokens=tokens)
    snapshot = probe(*wide, *controls)
    snapshot["dom"]["390"] = mobile
    evidence = check("ds/scale", snapshot, tokens=tokens)[0]["evidence"]
    assert evidence["off_scale"] == {"12px": 1, "22px": 1, "26px": 1}
    assert evidence["responsive_headings"][0] == {"heading": "h1#lamp", "sizes": {"390px": 60, "1440px": 146.9}}
