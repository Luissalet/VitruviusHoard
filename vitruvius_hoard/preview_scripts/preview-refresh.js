(() => {
  if (window.parent === window || window.__vitruviusLivePreview) return;
  window.__vitruviusLivePreview = true;

  const provenance = (node) => (node.getAttribute("data-vsrc") || "").match(/^(.*):(\d+):(\d+)$/);
  const sourceFile = (node) => provenance(node)?.[1];
  const sourced = (root) => [...root.querySelectorAll("[data-vsrc]")];
  const revisionMeta = () => document.querySelector('meta[name="vitruvius-preview-revision"]');
  // In the preview response this script runs before deferred project code and dock overlays.
  let rendered = document.documentElement.cloneNode(true);
  let hostOrigin;
  let layer;

  function describe(elements) {
    return {
      sources: [...new Set(elements.map((node) => node.getAttribute("data-vsrc")).filter(Boolean))],
      selectors: elements.filter((node) => node.id).map((node) => "#" + CSS.escape(node.id)),
    };
  }

  function authoredRoots(root, files) {
    return sourced(root).filter((node) => {
      const file = sourceFile(node);
      return files.has(file) && !node.parentElement?.closest("[data-vsrc]")?.getAttribute("data-vsrc")?.startsWith(file + ":");
    });
  }

  function bySource(root) {
    const byKey = new Map();
    for (const node of sourced(root)) {
      const key = node.getAttribute("data-vsrc");
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key).push(node);
    }
    return byKey;
  }

  const unsafe = "script, style, link, template, [data-vgen]";
  const attributes = (node) => [...node.attributes]
    .filter(({ name }) => name !== "data-vsrc")
    .map(({ name, value }) => [name, value]).sort();
  const text = (node) => [...node.childNodes].filter(({ nodeType }) => nodeType === Node.TEXT_NODE)
    .map(({ nodeValue }) => nodeValue);

  function planHtml(next, files) {
    if (!rendered.querySelector("[data-vsrc]") || !next.querySelector("[data-vsrc]")) return null;
    const beforeRoots = authoredRoots(rendered, files);
    const afterRoots = authoredRoots(next, files);
    if (beforeRoots.length !== afterRoots.length) return null;

    const active = bySource(document);
    const originals = bySource(rendered);
    const liveNode = (before) => {
      const key = before.getAttribute("data-vsrc");
      const original = originals.get(key);
      const present = active.get(key);
      return original?.length === present?.length && original ? present[original.indexOf(before)] : null;
    };
    const replace = (before, after) => {
      const node = liveNode(before);
      if (!node || !files.has(sourceFile(before)) || !files.has(sourceFile(after)) ||
          before.matches(unsafe) || after.matches(unsafe) || before.querySelector(unsafe) || after.querySelector(unsafe)) return null;
      return [{ node, after, replace: true }];
    };
    const plan = (before, after) => {
      if (before.isEqualNode(after)) return [];
      const beforeKey = before.getAttribute("data-vsrc");
      const afterKey = after.getAttribute("data-vsrc");
      const node = beforeKey !== afterKey ? liveNode(before) : null;
      if (beforeKey !== afterKey && (!node || !afterKey)) return null;
      const reanchor = node ? [{ node, after }] : [];
      if (before.hasAttribute("data-vgen") && before.getAttribute("data-vgen") === after.getAttribute("data-vgen")) {
        return reanchor;
      }
      if (before.tagName !== after.tagName || before.children.length !== after.children.length ||
          JSON.stringify(attributes(before)) !== JSON.stringify(attributes(after)) ||
          JSON.stringify(text(before)) !== JSON.stringify(text(after))) return replace(before, after);
      if (before.matches(unsafe) || after.matches(unsafe)) return null;
      for (let i = 0; i < before.children.length; i++) {
        const child = plan(before.children[i], after.children[i]);
        if (!child) return replace(before, after);
        reanchor.push(...child);
      }
      return reanchor;
    };

    const actions = [];
    for (let i = 0; i < beforeRoots.length; i++) {
      const action = plan(beforeRoots[i], afterRoots[i]);
      if (!action) return null;
      actions.push(...action);
    }
    return actions;
  }

  async function refreshHtml(change) {
    const route = location.href;
    const response = await fetch(route, { cache: "no-store", signal: AbortSignal.timeout(3500) });
    const revision = response.headers.get("X-Vitruvius-Revision");
    if (!response.ok || !response.headers.get("content-type")?.includes("text/html") ||
        (revision && revision !== change.revision)) return { applied: false };
    const documentAfter = new DOMParser().parseFromString(await response.text(), "text/html");
    if (location.href !== route) return { applied: false };
    const actions = planHtml(documentAfter, new Set(change.files));
    if (!actions) return { applied: false };
    const touched = [];
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    for (const { node, after, replace } of actions) {
      if (replace) {
        const copy = document.importNode(after, true);
        node.replaceWith(copy);
        touched.push(copy);
        if (!reduced) {
          const opacity = Number(getComputedStyle(copy).opacity);
          copy.animate([{ opacity: opacity * 0.65 }, { opacity }], { duration: 180, easing: "ease-out" });
        }
      } else {
        node.setAttribute("data-vsrc", after.getAttribute("data-vsrc"));
      }
    }
    rendered = documentAfter.documentElement;
    return { applied: true, targets: { ...describe(touched), exact: true } };
  }

  function stylesheetRules(rules, result = new Map()) {
    for (const rule of rules) {
      if (rule.selectorText) {
        result.set(rule.selectorText, (result.get(rule.selectorText) || "") + rule.cssText);
      }
      if (rule.cssRules) stylesheetRules(rule.cssRules, result);
    }
    return result;
  }

  async function refreshCss(change) {
    const paths = new Set(change.files.map((file) => file.replace(/^public\//, "")));
    const styles = [];
    for (const node of document.querySelectorAll('link[rel~="stylesheet"][href]')) {
      const url = new URL(node.href);
      const path = decodeURIComponent(url.pathname).slice(1);
      if (url.origin === location.origin && paths.has(path)) styles.push({ node, url, path });
    }
    if (new Set(styles.map(({ path }) => path)).size !== paths.size) return { applied: false };
    const staged = styles.map(({ node, url }) => {
      const next = node.cloneNode();
      url.searchParams.set("__vitruvius_revision", change.revision);
      next.href = url.href;
      next.media = "not all";
      return { node, next };
    });
    try {
      const loaded = await Promise.all(staged.map(({ node, next }) => new Promise((resolve) => {
        const timer = setTimeout(() => resolve(false), 3500);
        next.onload = () => { clearTimeout(timer); resolve(true); };
        next.onerror = () => { clearTimeout(timer); resolve(false); };
        node.after(next);
      })));
      if (!loaded.every(Boolean)) return { applied: false };
      const selectors = new Set();
      for (const { node, next } of staged) {
        const oldRules = stylesheetRules(node.sheet?.cssRules || []);
        const newRules = stylesheetRules(next.sheet?.cssRules || []);
        for (const selector of new Set([...oldRules.keys(), ...newRules.keys()])) {
          if (oldRules.get(selector) !== newRules.get(selector)) selectors.add(selector);
        }
      }
      for (const { node, next } of staged) {
        next.onload = next.onerror = null;
        if (node.hasAttribute("media")) next.setAttribute("media", node.getAttribute("media"));
        else next.removeAttribute("media");
        node.remove();
      }
      return { applied: true, targets: { selectors: [...selectors] } };
    } finally {
      for (const { node, next } of staged) if (node.isConnected) next.remove();
    }
  }

  function highlight(change) {
    let targets = [];
    const sources = new Set(change.sources || []);
    if (sources.size) targets = sourced(document).filter((node) => sources.has(node.getAttribute("data-vsrc")));
    for (const selector of change.selectors || []) {
      try { targets.push(...document.querySelectorAll(selector)); } catch {}
    }
    if (!targets.length && !change.exact && change.ranges) {
      targets = sourced(document).filter((node) => {
        const position = provenance(node);
        const range = position && change.ranges[position[1]]?.after;
        return range && Number(position[2]) >= range[0] && Number(position[2]) <= range[1];
      });
    }
    if (!targets.length && !change.exact) targets = [document.querySelector("main") || document.body];
    if (!targets.length) return;

    layer?.remove();
    const overlay = document.createElement("div");
    overlay.dataset.vLiveLayer = "";
    overlay.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483646;";
    const shadow = overlay.attachShadow({ mode: "open" });
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    for (const target of [...new Set(targets)].slice(0, 12)) {
      const rect = target.getBoundingClientRect();
      if (!rect.width || !rect.height || rect.bottom <= 0 || rect.top >= innerHeight ||
          rect.right <= 0 || rect.left >= innerWidth) continue;
      const border = document.createElement("div");
      border.style.cssText = "position:absolute;box-sizing:border-box;border:2px solid #1883ff;" +
        "border-radius:3px;box-shadow:0 0 0 1px white;pointer-events:none;";
      Object.assign(border.style, {
        left: Math.max(1, rect.left) + "px", top: Math.max(1, rect.top) + "px",
        width: (Math.min(innerWidth - 1, rect.right) - Math.max(1, rect.left)) + "px",
        height: (Math.min(innerHeight - 1, rect.bottom) - Math.max(1, rect.top)) + "px",
      });
      shadow.append(border);
      if (!reduced) border.animate([{ opacity: 0.3 }, { opacity: 1 }], { duration: 180, easing: "ease-out" });
    }
    document.body.append(overlay);
    layer = overlay;
    const dismiss = new AbortController();
    const remove = () => { overlay.remove(); dismiss.abort(); };
    window.addEventListener("scroll", remove, { once: true, signal: dismiss.signal });
    setTimeout(remove, 1250);
  }

  window.addEventListener("message", async (event) => {
    const message = event.data;
    if (event.source !== window.parent || message?.hoardDock !== 1 ||
        (hostOrigin && event.origin !== hostOrigin)) return;
    const reply = (result) => event.source.postMessage({
      hoardDock: 1, type: message.type + "/result", request: message.request, result,
    }, event.origin);
    if (message.type === "canvas/state") {
      hostOrigin = event.origin;
      reply({ route: location.pathname + location.search + location.hash, scroll: [scrollX, scrollY] });
    } else if (message.type === "canvas/restore") {
      hostOrigin = event.origin;
      if (Array.isArray(message.scroll) && message.scroll.length === 2 && message.scroll.every(Number.isFinite)) {
        window.scrollTo({ left: message.scroll[0], top: message.scroll[1], behavior: "instant" });
      }
      reply({ revision: revisionMeta()?.content });
    } else if (hostOrigin && message.type === "canvas/refresh") {
      try {
        const { change, mode } = message;
        const meta = revisionMeta();
        if (meta?.content && meta.content !== change.previous_revision) return reply({ applied: false });
        const result = await (mode === "css" ? refreshCss(change) : refreshHtml(change));
        if (result.applied && meta) meta.content = change.revision;
        reply(result);
      } catch {
        reply({ applied: false });
      }
    } else if (hostOrigin && message.type === "canvas/changed") {
      highlight(message);
    }
  });
})();
