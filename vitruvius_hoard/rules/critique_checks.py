"""Rendered signs of default component chrome, scaffold copy and stock layouts."""

from __future__ import annotations

import re

from .base import F
from .dom_rules import Ctx, drule
from .domtree import Dom, El


SCAFFOLD = re.compile(
    r"\b(?:entorno de prueba|(?:datos|saldos|cuentas) fictici[oa]s|lecturas de ejemplo|"
    r"portfolio de muestra|restaurante ficticio|test environment|(?:fictional|dummy) data|"
    r"sample (?:portfolio|readings)|fictional restaurant|demo (?:data|accounts|balances))\b",
    re.IGNORECASE,
)
BACK_TO_TOP = re.compile(r"^(?:volver arriba|back to top|return to top|ir arriba)[.! ↑]*$", re.IGNORECASE)
PRICE = re.compile(r"(?:\d\s*[€£$]|[€£$]\s*\d|\d\s*(?:EUR|GBP|USD)\b)", re.IGNORECASE)
HEADINGS = {"h1", "h2", "h3", "h4"}
MEDIA = {"figure", "img", "svg", "canvas", "video", "picture"}
PATTERN_WEIGHTS = {
    "single-form-card": 3.4,
    "hero-only": 3.0,
    "uniform-card-grid": 2.2,
    "repeated-editorial-bands": 2.2,
    "featured-middle-price": 2.0,
    "split-hero": 0.9,
    "back-to-top-footer": 0.5,
}


def _visible(el: El) -> bool:
    return el.w > 0 and el.h > 0 and el.st("op", 1) >= 0.3 and el.st("vis") not in ("hidden", "collapse")


def _tree(el: El):
    yield el
    yield from el.descendants()


def _text(el: El) -> str:
    return " ".join(item.text for item in _tree(el) if item.text and _visible(item))


def _finding(rule: str, en: str, es: str, evidence: dict, title_es: str, fix_es: str) -> list[dict]:
    finding = F(rule, en, evidence)
    finding.update(title_es=title_es, detail_es=es, fix_es=fix_es)
    return [finding]


@drule("webcraft/native-control-chrome")
def native_control_chrome(cx: Ctx):
    data = cx.probe.get("native_controls") or {}
    controls = data.get("controls") or []
    if not controls:
        return []
    visible = [c["selector"] for c in controls if c["state"] == "rendered"]
    in_dialog = [c["selector"] for c in controls if c["state"] == "closed_dialog"]
    en, es = [], []
    if visible:
        refs = ", ".join(visible[:8])
        en.append(f"The browser still draws default indicators for {refs}.")
        es.append(f"El navegador sigue dibujando los indicadores predeterminados de {refs}.")
    if in_dialog:
        refs = ", ".join(in_dialog[:8])
        en.append(f"The styles of closed dialogs also retain the default indicators for {refs}.")
        es.append(f"Los estilos de los diálogos cerrados también conservan los indicadores predeterminados de {refs}.")
    if any(c["locale_mismatch"] for c in controls):
        locale = f'{data["browser_language"]} / {data["language"]}'
        en.append(f"The date picker can follow a different language from the page ({locale}).")
        es.append(f"El selector de fecha puede seguir un idioma distinto al de la página ({locale}).")
    return _finding("webcraft/native-control-chrome", " ".join(en), " ".join(es),
                    {**data, "controls": controls[:12]}, "Indicadores nativos sin estilo propio",
                    "Integra el indicador con el diseño y comprueba el formato de las fechas en el idioma de la página.")


@drule("webcraft/scaffold-copy")
def scaffold_copy(cx: Ctx):
    matches = {}
    for dom in cx.all:
        for el in dom.els:
            copy = el.d.get("rendered_text") or el.text
            if not copy or not _visible(el) or any(parent.st("op", 1) < 0.3 for parent in el.ancestors()):
                continue
            match = SCAFFOLD.search(copy)
            if match:
                key = match[0].casefold()
                if key not in matches or len(copy) < len(matches[key]["text"]):
                    matches[key] = {"text": copy, "element": el.label()}
    if not matches:
        return []
    items = list(matches.values())[:8]
    quotes = ", ".join(f'“{item["text"]}”' for item in items)
    return _finding("webcraft/scaffold-copy", f"The page shows prototype or sample copy such as {quotes}.",
                    f"La página muestra texto de prototipo o de muestra, como {quotes}.", {"items": items},
                    "Texto de andamio visible", "Retira el texto interno o explica al usuario qué implica la simulación.")


def _surface(el: El):
    return (el.st("bg"), el.st("bgi"), el.st("sh"))


def _pricing_row(dom: Dom):
    for parent in dom.els:
        cols = sorted((c for c in parent.children if _visible(c) and c.w >= 150 and c.h >= 110), key=lambda c: c.x)
        if len(cols) != 3:
            continue
        left, middle, right = cols
        if (max(c.y for c in cols) - min(c.y for c in cols) <= 12
                and left.right <= middle.x + 2 and middle.right <= right.x + 2
                and _surface(left) == _surface(right) != _surface(middle)
                and all(PRICE.search(_text(c)) and any(e.tag in HEADINGS for e in c.descendants()) for c in cols)):
            return parent
    return None


def _uniform_grid(dom: Dom):
    for parent in dom.els:
        if parent.st("disp") not in ("grid", "flex"):
            continue
        cards = [c for c in parent.children if _visible(c) and c.w >= 150 and c.h >= 110]
        if len(cards) < 3 or len({round(c.x / 10) for c in cards}) < 2:
            continue
        first = cards[0]
        shape = [c.tag for c in first.children if _visible(c)]
        if all(c.tag == first.tag and abs(c.w - first.w) <= first.w * 0.08
               and abs(c.h - first.h) <= first.h * 0.12
               and [child.tag for child in c.children if _visible(child)] == shape
               and any(e.tag in HEADINGS for e in c.descendants()) for c in cards):
            return parent, len(cards)
    return None


def _primary_form(main: El):
    forms = [
        el for el in main.descendants() if el.tag == "form" and _visible(el) and not el.in_tag("dialog")
        and sum(c.tag in ("input", "select", "textarea") and _visible(c) for c in el.descendants()) >= 3
    ]
    if len(forms) == 1:
        form = forms[0]
        if form.w * form.h >= main.w * main.h * 0.23 and form.y < main.y + main.h * 0.4:
            return form
    return None


def _split_hero(main: El):
    heading = next((el for el in main.descendants() if el.tag == "h1" and _visible(el)), None)
    if heading is None:
        return None
    for branch in _tree_ancestors(heading, main):
        parent = branch.parent
        if parent is None or parent.st("disp") not in ("grid", "flex"):
            continue
        for other in parent.children:
            if other is branch or not _visible(other) or other.w < parent.w * 0.23:
                continue
            if (other.right <= branch.x + 2 or branch.right <= other.x + 2) and (
                min(other.bottom, branch.bottom) - max(other.y, branch.y) >= 65
            ) and any(e.tag in MEDIA and e.w >= 120 and e.h >= 100 for e in _tree(other)):
                return parent
    return None


def _repeated_editorial_bands(main: El) -> bool:
    count = 0
    split = 0.0
    for band in main.children:
        if (band.tag not in ("section", "article") or not _visible(band) or band.w < main.w * 0.8
                or band.h < 120 or band.st("disp") not in ("grid", "flex")):
            count = 0
            continue
        columns = sorted((el for el in band.children if _visible(el) and el.w >= band.w * 0.23), key=lambda el: el.x)
        if len(columns) != 2:
            count = 0
            continue
        left, right = columns
        overlap = min(left.bottom, right.bottom) - max(left.y, right.y)
        if (left.right > right.x + 2 or overlap < min(left.h, right.h) * 0.45
                or not any(el.tag in HEADINGS and _visible(el) for el in _tree(left))
                or any(el.tag in HEADINGS and _visible(el) for el in _tree(right))):
            count = 0
            continue
        current = (right.x - band.x) / band.w
        if not count or abs(current - split) > 0.05:
            split = current
            count = 0
        count += 1
        if count == 3:
            return True
    return False


def _tree_ancestors(el: El, root: El):
    while el is not root and el.parent is not None:
        yield el
        el = el.parent


@drule("webcraft/category-composition")
def category_composition(cx: Ctx):
    dom = cx.wide
    main = next((el for el in dom.tags("main") if _visible(el)), None)
    patterns, en, es = [], [], []

    def add(kind, element, reason, reason_es):
        patterns.append({"kind": kind, "element": element.label()})
        en.append(reason)
        es.append(reason_es)

    if dom.width >= 800:
        prices = _pricing_row(dom)
        if prices:
            add("featured-middle-price", prices, "Three price columns highlight the middle plan.",
                "Tres columnas de precios con el plan central resaltado.")
        grid = _uniform_grid(dom)
        if grid and grid[0] is not prices:
            parent, count = grid
            add("uniform-card-grid", parent, f"{count} cards repeat the same dimensions and structure.",
                f"{count} tarjetas repiten las mismas dimensiones y estructura.")
        if main:
            form = _primary_form(main)
            if form:
                add("single-form-card", form, "One form with at least three controls dominates the main content.",
                    "Un único formulario con al menos tres controles domina el contenido principal.")
            hero = _split_hero(main)
            if hero and hero.h >= main.h * 0.8:
                add("hero-only", hero, "The split headline-and-image hero occupies nearly all of the main content.",
                    "La cabecera dividida entre titular e imagen ocupa casi todo el contenido principal.")
            elif hero:
                add("split-hero", hero, "The opening uses the common side-by-side headline-and-image layout.",
                    "La apertura usa la composición habitual de titular e imagen en paralelo.")
            if _repeated_editorial_bands(main):
                add("repeated-editorial-bands", main,
                    "Three consecutive sections repeat the same split, with the heading on the left and a content column on the right.",
                    "Tres secciones seguidas repiten la misma división entre titular a la izquierda y contenido a la derecha.")
    for footer in dom.tags("footer"):
        links = [el for el in footer.descendants() if el.tag == "a" and _visible(el)]
        if len(links) <= 2 and any(BACK_TO_TOP.fullmatch(_text(el)) for el in links) and len(_text(footer)) <= 160:
            add("back-to-top-footer", footer, "A short footer defaults to a Back to top link.",
                "Un pie breve se apoya en el enlace genérico «Volver arriba».")
            break
    if not patterns:
        return []
    return _finding("webcraft/category-composition", " ".join(en), " ".join(es),
                    {"patterns": patterns, "width": dom.width}, "Composición de plantilla de la categoría",
                    "Da protagonismo a lo que distingue al producto y varía el ritmo donde cambie el contenido.")
