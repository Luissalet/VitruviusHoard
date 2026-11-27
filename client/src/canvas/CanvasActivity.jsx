import React, { useLayoutEffect, useRef, useState } from "react";

export function CanvasConversation({ es, projectId }) {
  const slot = useRef(null);
  const [open, setOpen] = useState(false);

  useLayoutEffect(() => {
    const container = slot.current;
    setOpen(false);
    const update = (event) => {
      if (event.detail?.container === container) setOpen(Boolean(event.detail.visible));
    };
    window.addEventListener("hoard:copilot-visibility", update);
    return () => {
      window.removeEventListener("hoard:copilot-visibility", update);
      window.dispatchEvent(new CustomEvent("hoard:copilot-release", { detail: { container } }));
    };
  }, [projectId]);

  const show = (event) => {
    if (!open) window.dispatchEvent(new CustomEvent("hoard:copilot-open", {
      detail: { container: slot.current, trigger: event.currentTarget },
    }));
    slot.current?.querySelector(".hoard-copilot")?.focus();
  };

  return <section className="canvas-inspector-section">
    <div className="canvas-conversation-heading">
      <h2 className="canvas-inspector-heading">{es ? "Conversación" : "Conversation"}</h2>
      <button type="button" className="btn btn-sm" aria-controls="canvas-conversation"
        aria-expanded={open} onClick={show}>{open ? (es ? "Ir al chat" : "Go to chat")
          : (es ? "Abrir conversación" : "Open conversation")}</button>
    </div>
    <div id="canvas-conversation" ref={slot} data-hoard-copilot-inline-slot />
  </section>;
}

export function CanvasLiveSteps({ steps, es }) {
  if (!steps.length) return null;
  const labels = es
    ? { edit: "Editando el código", click: "Clic", fill: "Entrada de texto", select: "Selección", navigate: "Navegación", scroll: "Desplazamiento", highlight: "Resaltado" }
    : { edit: "Editing source", click: "Click", fill: "Text input", select: "Selection", navigate: "Navigation", scroll: "Scroll", highlight: "Highlight" };
  return <ul className="canvas-live-steps" aria-label={es ? "Actividad en la vista previa" : "Preview activity"} aria-live="polite">
    {steps.map((entry) => {
      const actor = entry.actor?.name || entry.actor?.id || (es ? "Agente" : "Agent");
      const locator = entry.target?.label ?? entry.target?.text;
      const target = entry.target?.vsrc || entry.target?.selector || entry.target?.sources?.[0] || entry.target?.files?.[0]
        || (typeof locator === "string" && locator)
        || (entry.target?.ref ? (es ? "Elemento " : "Element ") + entry.target.ref : null);
      return <li key={entry.id}>
        <strong>{labels[entry.kind]} · {actor}</strong>
        <span className="chip">{entry.state === "active" ? (es ? "En curso" : "In progress")
          : entry.state === "failed" ? (es ? "Con error" : "Failed") : (es ? "Hecho" : "Done")}</span>
        {target && <code>{target}</code>}
        <CanvasMaterials examples={entry.target?.examples} tokensId={entry.target?.tokens_id} />
      </li>;
    })}
  </ul>;
}

export function CanvasMaterials({ examples, tokensId }) {
  if (!examples?.length && !tokensId) return null;
  return <div className="canvas-materials">
    {examples?.map((value) => <span key={value} className="chip chip-wrap">{value}</span>)}
    {tokensId && <span className="chip chip-wrap">Tokens · {tokensId}</span>}
  </div>;
}
