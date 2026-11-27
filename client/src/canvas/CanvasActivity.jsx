import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { groupCanvasActivity } from "./canvasConversation.js";

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
    <button type="button" className="btn btn-sm" aria-controls="canvas-conversation"
      aria-expanded={open} onClick={show}>{open ? (es ? "Ir al chat" : "Go to chat")
        : (es ? "Abrir conversación" : "Open conversation")}</button>
    <div id="canvas-conversation" ref={slot} data-hoard-copilot-inline-slot />
  </section>;
}

const STEP_LABELS = {
  es: { edit: "Editando el código", click: "Clic", fill: "Entrada de texto", select: "Selección", navigate: "Navegación", scroll: "Desplazamiento", highlight: "Resaltado" },
  en: { edit: "Editing source", click: "Click", fill: "Text input", select: "Selection", navigate: "Navigation", scroll: "Scroll", highlight: "Highlight" },
};

function CanvasStep({ entry, es }) {
  const actor = entry.actor?.name || entry.actor?.id || (es ? "Agente" : "Agent");
  const locator = entry.target?.label ?? entry.target?.text;
  const target = entry.target?.vsrc || entry.target?.selector || entry.target?.sources?.[0] || entry.target?.files?.[0]
    || (typeof locator === "string" && locator)
    || (entry.target?.ref ? (es ? "Elemento " : "Element ") + entry.target.ref : null);
  return <li className="canvas-step">
    <strong>{STEP_LABELS[es ? "es" : "en"][entry.kind]} · {actor}</strong>
    <span className="chip">{entry.state === "active" ? (es ? "En curso" : "In progress")
      : entry.state === "failed" ? (es ? "Con error" : "Failed") : (es ? "Hecho" : "Done")}</span>
    {target && <code>{target}</code>}
    <CanvasMaterials examples={entry.target?.examples} tokensId={entry.target?.tokens_id} />
  </li>;
}

export function CanvasTimeline({ steps, es }) {
  const request = steps.findLast((entry) => entry.role === "user");
  const requestNode = useRef(null);
  useEffect(() => {
    if (requestNode.current?.getClientRects().length) requestNode.current.scrollIntoView({ block: "nearest" });
  }, [request?.id]);
  if (!steps.length) return null;
  return <div className="canvas-timeline" role="log" aria-label={es ? "Conversación y actividad" : "Conversation and activity"}
    aria-relevant="additions">
    <ol role="list">
      {groupCanvasActivity(steps).map((entry) => {
        if (entry.kind === "speech") {
          const user = entry.role === "user";
          const label = user ? (es ? "Encargo" : "Request") : entry.speaker || (es ? "Agente" : "Agent");
          return <li key={entry.id} className="canvas-speech" data-role={entry.role}
            ref={entry.id === request?.id ? requestNode : undefined}>
            <strong>{label}</strong>
            <p>{entry.text}</p>
          </li>;
        }
        if (entry.kind === "interactions") {
          const count = entry.steps.length;
          const unit = es ? (count === 1 ? "interacción" : "interacciones")
            : (count === 1 ? "interaction" : "interactions");
          return <li key={entry.id} className="canvas-interactions">
            <details>
              <summary>{count} {unit}</summary>
              <ul role="list">{entry.steps.map((step) => <CanvasStep key={step.id} entry={step} es={es} />)}</ul>
            </details>
          </li>;
        }
        return <CanvasStep key={entry.id} entry={entry} es={es} />;
      })}
    </ol>
  </div>;
}

export function CanvasMaterials({ examples, tokensId }) {
  if (!examples?.length && !tokensId) return null;
  return <div className="canvas-materials">
    {examples?.map((value) => <span key={value} className="chip chip-wrap">{value}</span>)}
    {tokensId && <span className="chip chip-wrap">Tokens · {tokensId}</span>}
  </div>;
}
