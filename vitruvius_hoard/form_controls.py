"""The reusable fields and a bilingual form showing their normal HTML contract."""
from __future__ import annotations

import html
from pathlib import Path

ID = "form-controls"
_ASSETS = Path(__file__).with_name("form_controls_assets")
_DEFAULT_TEXT = "FORM / FIELD"
_COPY = {
    "es": {
        "heading": "Reserva de sala", "lead": "Elige una sala, una fecha y la duración de tu reserva.",
        "room": "Sala", "room_empty": "Elige una sala", "library": "Biblioteca", "studio": "Taller",
        "date": "Fecha", "date_hint": "Puedes escribir la fecha o abrir el calendario.",
        "time": "Hora", "time_hint": "Horario de apertura de 09:00 a 21:00.",
        "duration": "Duración", "submit": "Comprobar reserva", "reset": "Restablecer",
    },
    "en": {
        "heading": "Room booking", "lead": "Choose the room, date and duration for your booking.",
        "room": "Room", "room_empty": "Choose a room", "library": "Library", "studio": "Studio",
        "date": "Date", "date_hint": "Type a date or open the calendar.",
        "time": "Time", "time_hint": "Opening hours are 09:00 to 21:00.",
        "duration": "Duration", "submit": "Check booking", "reset": "Reset",
    },
}

_DEMO_CSS = """
body {
  margin: 0;
  background: var(--color-bg, #edf2f1);
  color: var(--color-on-bg, #1d2c36);
  font: 1rem/1.5 var(--font-body, system-ui), sans-serif;
}
.form-example {
  box-sizing: border-box;
  display: grid;
  grid-template-columns: minmax(0, .8fr) minmax(0, 1fr);
  gap: clamp(1.5rem, 5vw, 5rem);
  max-inline-size: 64rem;
  margin: 0 auto;
  padding: clamp(1rem, 5vw, 4rem);
}
.form-example h1 {
  margin: 0;
  font-family: var(--font-heading, Georgia), serif;
  font-size: clamp(2.5rem, 6vw, 4.5rem);
  font-weight: 500;
  letter-spacing: -.035em;
  line-height: 1.05;
  overflow-wrap: anywhere;
}
.form-example header p { max-inline-size: 27ch; }
.form-example .design-form {
  padding: clamp(1rem, 3vw, 2rem);
  border: 1px solid var(--color-border, #a9b7bc);
  border-radius: var(--radius-lg, 12px);
  background: var(--color-surface, #fffefa);
}
.form-example .form-actions { display: flex; gap: .65rem; flex-wrap: wrap; }
.form-example .form-actions button {
  min-block-size: 44px;
  padding: .5rem .9rem;
  color: var(--control-text);
  background: var(--control-bg);
  border: 1px solid var(--control-line);
  border-radius: var(--control-radius);
  cursor: pointer;
  font: inherit;
}
.form-example .form-actions button[type=submit] {
  color: var(--color-primary-on-700, #fff);
  background: var(--control-accent);
  border-color: var(--control-accent);
  font-weight: 650;
}
.form-example output { overflow-wrap: anywhere; }
@media (max-width: 43rem) {
  .form-example { grid-template-columns: minmax(0, 1fr); }
}
"""

_DEMO_JS = """
(() => {
  const form = document.querySelector(".form-example .design-form");
  const result = form.querySelector("output");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const room = form.elements.room.selectedOptions[0].text;
    const locale = document.documentElement.lang === "en" ? "en-GB" : document.documentElement.lang;
    const date = new Intl.DateTimeFormat(locale, {
      day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC",
    }).format(new Date(data.get("date") + "T00:00:00Z"));
    result.textContent = [room, date, data.get("time"), data.get("duration") + " min"].join(" · ");
  });
  form.addEventListener("reset", () => { result.textContent = ""; });
})();
"""


def recipe(text: str, accent: str, lang: str) -> tuple[str, dict[str, str]]:
    """Return the live demonstration and the three pieces to reuse in an application."""
    copy = _COPY["es" if lang.split("-")[0].lower() == "es" else "en"]
    title = html.escape(copy["heading"] if text == _DEFAULT_TEXT else text)
    choices = "\n".join(
        f'      <label class="design-choice"><input type="radio" name="duration" value="{minutes}"'
        f'{state}> {minutes} min</label>'
        for minutes, state in ((30, ' checked required'), (45, ''), (60, ''))
    )
    markup = f"""<form class="design-form">
    <div class="design-field">
      <label for="room">{copy['room']}</label>
      <div class="design-control design-select">
        <select id="room" name="room" required>
          <option value="">{copy['room_empty']}</option>
          <option value="library">{copy['library']}</option>
          <option value="studio">{copy['studio']}</option>
        </select>
      </div>
    </div>
    <div class="design-field">
      <label for="date">{copy['date']}</label>
      <div class="design-control design-temporal">
        <input id="date" name="date" type="date" value="2026-11-30" aria-describedby="date-hint" required>
      </div>
      <p class="design-hint" id="date-hint">{copy['date_hint']}</p>
    </div>
    <div class="design-field">
      <label for="time">{copy['time']}</label>
      <div class="design-control design-temporal">
        <input id="time" name="time" type="time" min="09:00" max="21:00" value="18:30" aria-describedby="time-hint" required>
      </div>
      <p class="design-hint" id="time-hint">{copy['time_hint']}</p>
    </div>
    <fieldset class="design-choices">
      <legend>{copy['duration']}</legend>
{choices}
    </fieldset>
  </form>"""
    css = (_ASSETS / "controls.css").read_text(encoding="utf-8")
    script = (_ASSETS / "controls.js").read_text(encoding="utf-8")
    demo_markup = markup.removesuffix("</form>") + f"""  <div class="form-actions">
      <button type="submit">{copy['submit']}</button>
      <button type="reset">{copy['reset']}</button>
    </div>
    <output aria-live="polite"></output>
  </form>"""
    page = f"""<!doctype html>
<html lang="{html.escape(lang, quote=True)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>:root{{--accent:{accent}; color-scheme: light}}{_DEMO_CSS}{css}</style>
</head>
<body>
  <main class="form-example">
    <header><h1>{title}</h1><p>{copy['lead']}</p></header>
    {demo_markup}
  </main>
  <script>{script}</script>
  <script>{_DEMO_JS}</script>
</body>
</html>"""
    return page, {"markup": markup, "css": css, "script": script}
