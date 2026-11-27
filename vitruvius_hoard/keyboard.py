"""The keyboard measurement a capture takes: a Tab walk through the page, the focus indicator of every stop, controls only a pointer can use.

``walk(page)`` runs in the capture thread on a live Playwright page and returns a plain dict that ``rules/interaction.py`` reads from
``probe["keyboard"]``. It never raises: a page that breaks the measurement gets ``{"error": ...}`` and the rules that need it stay silent.
Transitions and animations are switched off while it runs so a computed style read right after a focus change is the final one.
"""
from __future__ import annotations

from typing import Any

MAX_STOPS = 60

_SIGNATURE_JS = r"""
  const sig = (el) => {
    const out = [];
    for (let n = el; n && n.nodeType === 1; n = (n.parentNode && n.parentNode.host) || null) {
      const cs = getComputedStyle(n);
      out.push([cs.outlineStyle, cs.outlineWidth, cs.outlineColor, cs.boxShadow, cs.borderTopColor, cs.borderTopStyle, cs.borderTopWidth, cs.backgroundColor, cs.color,
                cs.textDecorationLine, cs.filter, cs.transform].join('|'));
    }
    return out.join('||');
  };
"""

_PREPARE_JS = r"""
() => {
  const st = document.createElement('style');
  st.id = '__vh_kb_style';
  st.textContent = '*,*::before,*::after{transition:none!important;animation:none!important;scroll-behavior:auto!important}';
  document.head.appendChild(st);
  if (document.activeElement) document.activeElement.blur();
  window.scrollTo(0, 0);
""" + _SIGNATURE_JS + r"""
  const NATIVE = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[contenteditable=""],[contenteditable="true"],audio[controls],video[controls],[tabindex]';
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility === 'hidden' || n.hasAttribute('inert') || n.getAttribute('aria-hidden') === 'true') return false;
    }
    return true;
  };
  const label = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const c = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (c.length) s += '.' + c.join('.');
    return s;
  };
  const list = [];
  const segmented = {};
  document.querySelectorAll(NATIVE).forEach((el) => {
    const ti = el.getAttribute('tabindex');
    if (el.disabled || (ti !== null && parseInt(ti, 10) < 0) || !visible(el)) return;
    list.push(label(el) + '|' + (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40));
    el.setAttribute('data-vh-kb', String(list.length));
    if (el.tagName === 'INPUT' && /^(date|datetime-local|month|time|week)$/.test(el.type)) {
      segmented[list.length] = sig(el);
    }
  });
  // pointer-only: the outermost visible element with a pointer cursor that nothing focusable contains or is inside
  const INTERACTIVE = 'a[href],button,input,select,textarea,summary,label,[tabindex],[role=button],[role=link],[role=tab],[role=checkbox],[role=switch],[role=menuitem],[role=option],[contenteditable]';
  const pointer = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  for (let n = walker.nextNode(); n && pointer.length < 12; n = walker.nextNode()) {
    if (n.closest('#__vh_kb_style') || n.tagName === 'SCRIPT' || n.tagName === 'STYLE') continue;
    const cs = getComputedStyle(n);
    if (cs.cursor !== 'pointer') continue;
    if (n.parentElement && getComputedStyle(n.parentElement).cursor === 'pointer') continue;
    if (n.matches(INTERACTIVE) || n.closest(INTERACTIVE) || n.querySelector(INTERACTIVE) || n.shadowRoot) continue;
    if (!visible(n)) continue;
    pointer.push({ label: label(n), text: (n.textContent || '').trim().slice(0, 40) });
  }
  return { count: list.length, expected: list, pointer_only: pointer, segmented };
}
"""

_STOP_JS = r"""
(segmented) => {
  const deep = () => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; return a; };
""" + _SIGNATURE_JS + r"""
  const a = deep();
  if (!a || a === document.body || a === document.documentElement) return { body: true };
  const host = document.activeElement;
  const label = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const c = (el.getAttribute && el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (c.length) s += '.' + c.join('.');
    return s;
  };
  const r = host.getBoundingClientRect();
  const focused = sig(a);
  const mark = host.getAttribute('data-vh-kb');
  let plain = a === host ? segmented[mark] : undefined;
  // Blurring a native date or time input discards which segment Tab is on.
  if (plain === undefined) {
    a.blur();
    plain = sig(a);
    a.focus({ preventScroll: true });
  }
  return { label: label(host), inner: a === host ? '' : label(a), mark: mark, ring: focused !== plain,
           name: (host.getAttribute('aria-label') || host.textContent || '').trim().slice(0, 40),
           offscreen: r.width < 2 || r.height < 2 };
}
"""


def walk(page: Any, limit: int = MAX_STOPS) -> dict[str, Any]:
    try:
        prep = page.evaluate(_PREPARE_JS)
        segmented = prep.get("segmented") or {}
        stops: list[dict[str, Any]] = []
        seen: set[str] = set()
        previous = None
        complete = False
        for _ in range(limit):
            page.keyboard.press("Tab")
            stop = page.evaluate(_STOP_JS, segmented)
            if stop.get("body"):
                complete = True  # focus left the document: one full cycle
                break
            key = f"{stop['label']}|{stop.get('mark')}|{stop.get('inner')}"
            if key == previous:
                continue
            if key in seen:
                complete = True
                break
            seen.add(key)
            previous = key
            stops.append(stop)
        reached = {s.get("mark") for s in stops if s.get("mark")}
        expected = prep.get("expected") or []
        unreached = [{"label": row.split("|", 1)[0], "text": row.split("|", 1)[1]} for i, row in enumerate(expected, 1) if str(i) not in reached]
        # an element inside a shadow root or one the page moved focus past counts as reached by its host's stop
        return {"stops": stops, "complete": complete, "tab_stops": len(stops), "focusable": prep.get("count", 0), "unreached": unreached,
                "pointer_only": prep.get("pointer_only") or []}
    except Exception as error:  # noqa: BLE001 - the measurement is optional
        return {"error": str(error)[:200]}
    finally:
        try:
            page.evaluate("() => { const s = document.getElementById('__vh_kb_style'); if (s) s.remove(); document.querySelectorAll('[data-vh-kb]').forEach(e => e.removeAttribute('data-vh-kb')); }")
        except Exception:  # noqa: BLE001
            pass
