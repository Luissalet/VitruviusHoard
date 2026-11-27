"""Content drafts and library-backed art direction for a new design."""
from __future__ import annotations

import re
import unicodedata

from . import design_patterns, i18n
from .showcase import library as showcase


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


# Each row pairs ready-to-edit copy with the role of a shipped showcase recipe.
# Supplied facts remain authoritative. The example names and figures are draft copy.
_DOMAINS = {
    "lighting": (r"\blampar|\blamp|\bluminaria|\blighting", ("editorial", "diorama", "halftone"), (
        ("workshop", "rock", "Del torno al vidrio", "From lathe to glass",
         "En el taller de Brétema torneamos el pie de latón, soplamos cada tulipa y comprobamos el halo sobre la mesa antes de embalarla.",
         "At the Brétema workshop we turn the brass base, blow each shade and check its pool of light on the table before packing."),
        ("reservation", "rock", "Ficha y primera tirada", "First-run specification",
         "La lámpara Vela mide 38 cm y lleva vidrio soplado ámbar y casquillo E14. Reserva una pieza y elige la temperatura de luz al confirmar.",
         "The Vela table lamp stands 38 cm tall and uses amber blown glass and an E14 socket. Reserve a piece and choose its light temperature at confirmation."),
    )),
    "weather": (r"\bmeteorolog|\bweather|\bestaciones\b|\blluvia", ("pulse", "constellation", "editorial"), (
        ("readings", "city", "Lecturas en la sierra", "Readings on the ridge",
         "A las 08:15, Alto del Tejo marca 8,4 °C y Collado del Pino marca 11,2 °C. Elige una hora para comparar todas las estaciones.",
         "At 08:15, Alto del Tejo reads 8.4 °C and Collado del Pino reads 11.2 °C. Choose a time to compare all stations."),
        ("outages", "city", "Estaciones sin señal", "Stations without a signal",
         "Barranco Hondo lleva 47 min sin enviar lecturas. Puedes consultar su último registro. La lluvia de hoy queda sin lectura.",
         "Barranco Hondo last sent a reading 47 min ago. Its last record is available. Today's rainfall has no reading."),
    )),
    "ceramics": (r"\bceramic|\bpottery|\bcuencos?\b|\bbarro\b", ("holographic", "editorial", "halftone"), (
        ("process", "rock", "Torno, esmalte y horno", "Wheel, glaze and kiln",
         "En Taller Garúa, Lía modela las piezas al torno. El esmalte Ceniza queda mate tras la cocción a 1.240 °C y cambia ligeramente en cada borde.",
         "At Garúa Studio, Lía throws each piece on the wheel. The Ash glaze comes out matte after firing at 1,240 °C and varies around every rim."),
        ("pieces", "gallery", "Piezas de la hornada", "Pieces from the kiln",
         "La taza Bruma tiene 290 ml de capacidad y un asa para dos dedos. El cuenco Duna mide 16 cm y conserva el pie sin esmaltar. La ficha enseña la pieza exacta que se añade a la cesta.",
         "The Bruma cup holds 290 ml and has a two-finger handle. The Duna bowl measures 16 cm and has an unglazed foot. Each listing shows the exact piece that goes in the basket."),
    )),
    "physiotherapy": (r"\bfisio|\bphysio|\bphysical therap|\brehabilitacion\b", ("editorial", "constellation", "diorama"), (
        ("people", "gallery", "Quién te atiende", "Who will see you",
         "En Centro Urdimbre, Mara Belda lleva ejercicio terapéutico, Gabi Rial rehabilitación deportiva, Noa Ferrer suelo pélvico e Inés Mallo terapia manual.",
         "At Urdimbre Clinic, Mara Belda handles therapeutic exercise, Gabi Rial sports rehabilitation, Noa Ferrer pelvic health and Inés Mallo manual therapy."),
        ("appointment", "book", "Tu primera cita", "Your first appointment",
         "Primera valoración de rodilla, 45 min. Elige a Gabi Rial y una hora libre. El centro confirma la sala y cómo llegar desde la entrada accesible.",
         "First knee assessment, 45 min. Choose Gabi Rial and an open time. The clinic confirms the room and the route from the accessible entrance."),
    )),
    "photography": (r"\bfotograf|\bphotograph|\bdocumental\b|\bdocumentary\b", ("holographic", "editorial", "diorama"), (
        ("tides", "book", "Cuaderno de bajamar", "Low-tide notebook",
         "Antes de las seis, los mariscadores cruzan a pie el carrizo de A Laxe. La serie sigue la distancia que deja el agua durante tres mareas.",
         "Before six, shellfish gatherers cross the reeds at A Laxe on foot. The series follows the distance the water leaves across three tides."),
        ("night", "book", "Turno de noche", "Night shift",
         "Vera Souto vuelve durante ocho noches al último quiosco abierto. Los pies de foto cuentan qué cambia en cada turno y dejan sitio al silencio.",
         "Vera Souto returns to the last open kiosk on eight nights. The captions trace what changes from shift to shift and leave room for silence."),
    )),
    "registration": (r"\bgestoria|\bautonom|\bself.employ|\bsole trader|\btax registration", ("editorial", "constellation", "halftone"), (
        ("identity", "book", "Identidad y actividad", "Identity and work",
         "Nerea Cid solicita el alta como encuadernadora con inicio el 15 de abril. Comprueba el NIF y la actividad antes de pasar al domicilio fiscal.",
         "Nerea Cid is registering as a bookbinder with a 15 April start date. Check the tax ID and activity before moving to the tax address."),
        ("review", "book", "Domicilio, cuenta y revisión", "Address, account and review",
         "Revisa el domicilio fiscal y la cuenta donde se cargarán las cuotas. Si pulsas «Editar cuenta», guardamos el domicilio y el resto de los datos.",
         "Review your tax address and the account for direct debits. If you choose Edit account, we keep your address and other entries."),
    )),
    "invoicing": (r"\bfactur|\binvoi[cc]|\bbilling\b|\bpricing\b", ("editorial", "halftone", "constellation"), (
        ("invoice", "book", "Una factura, de principio a fin", "One invoice, start to finish",
         "Factura AB-014. Dos reparaciones de 45 € suman 90 €. Con 18,90 € de IVA, el total es 108,90 €. Pendiente de cobro. Descargar factura en PDF.",
         "Invoice AB-014. Two €45 repairs total €90. With €18.90 VAT, the total is €108.90. Awaiting payment. Download invoice as a PDF."),
        ("plans", "gallery", "Qué cambia en cada plan", "What changes with each plan",
         "Oficio incluye una persona. Equipo añade permisos por rol. Estudio permite varias series de facturación. Elige pago anual para ver el total y el ahorro.",
         "Oficio includes one user. Equipo adds role-based permissions. Estudio supports several invoice series. Choose annual billing to see your total and savings."),
    )),
    "plants": (r"\bplantas?\b|\bplants?\b|\briego\b|\bwatering\b|\babono\b", ("holographic", "diorama", "constellation"), (
        ("water", "book", "1 · Revisar el riego", "1 · Check watering",
         "A la calatea de la ventana este le toca revisión el jueves. Si la capa superior sigue húmeda, retrasa el recordatorio dos días.",
         "The calathea in the east window is due for a check on Thursday. If the top layer is still damp, move the reminder back two days."),
        ("light", "book", "2 · Encontrar su sitio", "2 · Find the right spot",
         "El poto de la estantería recibe luz indirecta. La ficha guarda su ubicación y permite cambiarla al mover la maceta.",
         "The pothos on the bookshelf gets indirect light. Its record remembers the location and can be updated when you move the pot."),
        ("feed", "book", "3 · Anotar el abono", "3 · Record feeding",
         "En la ficha del ficus, registra el abono del 7 de abril y consulta cuándo se hizo la última aportación antes de repetirla.",
         "In the ficus record, log the 7 April feed and check when you last added fertiliser before feeding again."),
    )),
    "restaurant": (r"\brestaurante?\b|\bmarket cook|\bcocina de mercado\b|\bmenu del dia\b", ("editorial", "diorama", "holographic"), (
        ("menu", "book", "Pizarra de mediodía", "Lunch board",
         "En La Veta abrimos con alcachofas de Benicarló y seguimos con arroz de coliflor y bacalao. El menú se sirve de martes a viernes, de 13:30 a 15:30.",
         "At La Veta we start with Benicarló artichokes, then serve cauliflower and cod rice. The set lunch runs Tuesday to Friday, 13:30 to 15:30."),
        ("table", "gallery", "Carta de temporada y mesas", "Seasonal menu and tables",
         "La carta de primavera incorpora caballa escabechada y fresas con yogur. Al reservar, elige entre el comedor y las mesas del patio.",
         "The spring menu adds pickled mackerel and strawberries with yoghurt. When booking, choose the dining room or a table in the courtyard."),
    )),
    "banking": (r"\bbanc[oa]\b|\bbank|\btransferenc|\btransfer\b|\bsaldos?\b", ("pulse", "constellation", "editorial"), (
        ("accounts", "gallery", "Cuentas y movimientos", "Accounts and transactions",
         "La cuenta Día tiene 1.284,60 € disponibles y Reserva tiene 2.950,00 €. En Día aparece «Abono nómina» y un recibo de luz de 41,80 €.",
         "The Día account has €1,284.60 available and Reserva has €2,950.00. Día shows a salary credit and a €41.80 electricity bill."),
        ("transfer", "book", "Transferencia hablada", "Spoken transfer",
         "«Envía 36,50 € a Ada Llorente desde Día por la reparación de la bici». Si empiezas por «a Ada», te preguntaré el importe y leeré el resumen antes de confirmar.",
         "“Send €36.50 to Ada Llorente from Día for the bike repair.” If you start with “to Ada”, I'll ask for the amount and read back the summary before confirmation."),
    )),
}


_DIRECTION = {
    "editorial": (
        ("Retícula asimétrica, texto principal y pieza al otro lado.", "Asymmetric grid with the main text facing the piece."),
        ("Titular en gran escala y texto de lectura en sans de sistema.", "Large-scale headline and system sans for reading."),
        ("Papel cálido, tinta oscura y un acento de arcilla.", "Warm paper, dark ink and a clay accent."),
        ("Cambio de escala por control, sin animación automática.", "Scale changes via a control, with no automatic animation."),
        "#ac4c2f",
    ),
    "diorama": (
        ("Escena ancha en capas, con controles y pies fuera de la imagen.", "Wide layered scene with controls and captions outside the image."),
        ("Cabecera sans y pies breves a cuerpo de lectura.", "Sans heading and short captions at reading size."),
        ("Verdes de pizarra y fondo de papel claro.", "Slate greens on pale paper."),
        ("Paralaje por gesto, con capas centradas en movimiento reducido.", "Gesture-driven parallax with centred layers under reduced motion."),
        "#466f68",
    ),
    "halftone": (
        ("Campo de textura ancho y bancada inferior de controles.", "Wide texture field with a row of controls below."),
        ("Titular Georgia sobre controles sans y cifras tabulares.", "Georgia heading above sans controls and tabular figures."),
        ("Tinta verde oscura y puntos de ocre sobre papel gris verdoso.", "Dark green ink and ochre dots on green-grey paper."),
        ("La trama se recalcula al ajustar la densidad, sin bucle continuo.", "The texture redraws when density changes, with no continuous loop."),
        "#b35c37",
    ),
    "pulse": (
        ("Lectura gráfica central con controles de amplitud abajo.", "Central plot with amplitude controls below."),
        ("Serif para el título, sans y cifras tabulares para lecturas.", "Serif title, sans labels and tabular readings."),
        ("Verde carbón con una línea de acento menta.", "Charcoal green with a mint trace."),
        ("Trazado pausado por control o con movimiento reducido.", "The trace pauses via a control or under reduced motion."),
        "#8ad4ac",
    ),
    "constellation": (
        ("Nodos con relaciones visibles y un área de detalle debajo.", "Nodes with visible relationships and a detail area below."),
        ("Cabecera sans y etiquetas cortas junto a los puntos.", "Sans heading and short labels beside the points."),
        ("Fondo azul tinta con nodos claros y enlaces en turquesa.", "Ink-blue background with pale nodes and turquoise links."),
        ("Las relaciones aparecen al activar dos puntos con ratón o teclado.", "Links appear when two nodes are activated by pointer or keyboard."),
        "#68cbc0",
    ),
    "holographic": (
        ("Una ficha aislada en un escenario centrado y controles debajo.", "A single card on a centred stage with controls below."),
        ("Título en Georgia y texto de apoyo en sans.", "Georgia heading and sans supporting text."),
        ("Fondo grafito con una ficha de tintas prismáticas.", "Graphite background with a prism-toned card."),
        ("Giro por control o gesto, sin desplazamiento automático.", "Tilt via control or gesture, with no automatic movement."),
        "#b0aec4",
    ),
}


_NOTICE = re.compile(
    r"(?:^|[.!?;\n])\s*(?:por favor[,:]?\s+|please\s+)?"
    r"(?:(?:quiero|queremos|necesito|necesitamos)\s+que\s+(?:se\s+)?)?"
    r"(?:incluy[ea]s?|incluid|muestr[ea]s?|mostrad|pon|poned|pongas?|anad[ea]s?|anadid|include|show|add|display)"
    r"\s+(?:un|el|una|a|the)\s+(?:aviso|nota|etiqueta|notice|label|disclaimer)"
    r"[^.!?;\n]{0,70}\b(?:fictici[oa]s?|simulad[oa]s?|synthetic|fictional|simulated)\b"
)


def build(subject: str, *, product_type: str | None = None, lang: str | None = None,
          show_simulation_notice: bool | None = None, allow_typical_direction: bool = False) -> dict:
    subject = subject.strip()
    if not subject:
        raise ValueError("A brief needs a subject")
    lang = i18n.norm_lang(lang)
    spanish = lang == "es"
    pick = 0 if spanish else 1
    folded = _fold(subject)
    label = _fold(product_type or "")
    domain = next((key for key, (match, _, _) in _DOMAINS.items() if key == label or re.search(match, label)), None)
    domain = domain or next((key for key, (match, _, _) in _DOMAINS.items() if re.search(match, folded)), "general")
    if domain == "general":
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", subject) if s]
        patterns = ("editorial", "diorama", "constellation")
        rows = (
            ("offer", "book", "El encargo", "The brief", sentences[0], sentences[0]),
            ("use", "gallery", "En uso", "In use", sentences[-1], sentences[-1]),
        )
    else:
        _, patterns, rows = _DOMAINS[domain]
    recipes = {r["id"]: r for r in showcase.search()["recipes"]}
    sections = []
    for key, recipe_id, title_es, title_en, copy_es, copy_en in rows:
        recipe = recipes[recipe_id]
        sections.append({"id": key, "title": (title_es, title_en)[pick], "copy": (copy_es, copy_en)[pick],
                         "recipe": {"id": recipe_id, "title": recipe["title"], "url": recipe["recipe_url"],
                                    "tool": "showcase_recipe", "arguments": {"id": recipe_id},
                                    "cite": f"[vitruvius: showcase/{recipe_id}]"}})
    catalogue = {p["id"]: p for p in design_patterns.catalogue()}
    directions, variants = [], []
    for index, key in enumerate(patterns):
        pattern = catalogue[key]
        name = pattern["name_es" if spanish else "name"]
        composition, typography, color, motion, accent = _DIRECTION[key]
        reference = {"tool": "design_pattern", "arguments": {"id": key, "text": sections[0]["title"], "accent": accent},
                     "cite": f"[vitruvius: pattern/{key}]"}
        directions.append({"id": key, "title": name, "typical": index == 0, "composition": composition[pick],
                           "typography": typography[pick], "color": color[pick], "motion": motion[pick], "reference": reference})
        typical = (" · Típica de la categoría" if spanish else " · Typical for the category") if index == 0 else ""
        variants.append({"label": name + typical, "kind": "page", "pattern_id": key, "pattern_text": sections[0]["title"],
                         "pattern_accent": accent, "typical": index == 0, "intent": composition[pick]})
    show = bool(_NOTICE.search(folded)) if show_simulation_notice is None else show_simulation_notice
    notice = ("Datos simulados" if spanish else "Simulated data") if show else None
    return {
        "domain": domain, "content_sections": sections, "content_status": "draft",
        "content_cites": sorted({s["recipe"]["cite"] for s in sections} | {d["reference"]["cite"] for d in directions}),
        "copy_instruction": (
            "Conserva los hechos del encargo. Ajusta nombres y cifras de las propuestas a los datos aprobados."
            if spanish else "Keep the facts in the brief. Replace proposed names and figures with approved details."
        ),
        "simulation_notice": {"show": show, "placement": "footer" if show else None, "text": notice},
        "art_direction": {
            "required_before_build": True, "directions": directions,
            "recommended_id": patterns[0] if allow_typical_direction else patterns[1],
            "steps": ["design_alternatives_create", "design_alternatives_evaluate", "design_alternatives_decide"],
            "create": {"tool": "design_alternatives_create", "arguments": {
                "brief": (subject if len(subject) >= 8 else f"{subject} · {sections[0]['title']}")[:2000],
                "art_direction": True, "allow_typical": allow_typical_direction,
                "criteria": [{"name": "Adecuación al encargo" if spanish else "Fit to the brief",
                              "source": "manual", "why": (
                                  "Valora si la composición sirve al contenido y a la acción principal."
                                  if spanish else "Judge whether the composition serves the content and the primary action."
                              )}],
                "alternatives": variants,
            }},
        },
    }
