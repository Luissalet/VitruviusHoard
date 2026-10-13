import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../App.jsx";
import { useCopilotForm } from "../copilot-hooks.js";

export default function PatternPicker({ onApply }) {
  const { lang, notify } = useApp();
  const es = lang === "es";
  const [patterns, setPatterns] = useState([]);
  const [id, setId] = useState("editorial");
  const [text, setText] = useState("FORM / FIELD");
  const [accent, setAccent] = useState("#e36a39");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(null);
  useCopilotForm("pattern-draft", {
    initial: { id: "editorial", text: "FORM / FIELD", accent: "#e36a39" },
    current: { id, text, accent },
  });
  useEffect(() => {
    let active = true;
    api.designPatterns().then((data) => { if (active) setPatterns(data.patterns); }).catch((error) => { if (active) notify(error.message); });
    return () => { active = false; };
  }, []);
  const generate = async (event) => {
    event.preventDefault();
    setBusy(true);
    try { setReady(await api.designPattern({ id, text, accent })); }
    catch (error) { notify(error.message); }
    finally { setBusy(false); }
  };
  return (
    <details className="panel mb-4">
      <summary className="cursor-pointer font-semibold text-[14px]">{es ? "Patrones HTML propios" : "Original HTML patterns"}</summary>
      <p className="help mt-2">{es ? "Ocho estudios de composición e interacción. Genera una fuente, llévala al editor y comprueba el resultado con Render y el ensayo funcional." : "Eight composition and interaction studies. Generate source, bring it into the editor and check it with Render and the functional assay."}</p>
      <form onSubmit={generate} className="flex flex-col gap-3 mt-3">
        <label className="label" htmlFor="pattern-id">{es ? "Patrón" : "Pattern"}</label>
        <select id="pattern-id" className="field" value={id} onChange={(event) => setId(event.target.value)}>
          {patterns.map((pattern) => <option key={pattern.id} value={pattern.id}>{es ? pattern.name_es : pattern.name}</option>)}
        </select>
        <label className="label" htmlFor="pattern-text">{es ? "Texto" : "Text"}</label>
        <input id="pattern-text" className="field" value={text} onChange={(event) => setText(event.target.value)} />
        <div className="flex items-end gap-3 flex-wrap">
          <label className="flex items-center gap-2" htmlFor="pattern-accent">{es ? "Color" : "Colour"}<input id="pattern-accent" type="color" value={accent} onChange={(event) => setAccent(event.target.value)} /></label>
          <button className="btn" type="submit" disabled={busy || !patterns.length}>{busy ? (es ? "Generando…" : "Generating…") : (es ? "Generar fuente" : "Generate source")}</button>
        </div>
      </form>
      {ready && <div className="mt-3 flex items-center gap-3 flex-wrap" role="status">
        <span className="help break-words min-w-0">{es ? ready.pattern.name_es : ready.pattern.name} · {ready.parameters.text}</span>
        <button className="btn btn-primary" type="button" onClick={() => onApply(ready.html)}>{es ? "Usar esta fuente en el editor" : "Use this source in the editor"}</button>
        <a className="btn" href={`data:text/html;charset=utf-8,${encodeURIComponent(ready.html)}`} download={`${ready.pattern.id}.html`}>{es ? "Descargar HTML" : "Download HTML"}</a>
      </div>}
    </details>
  );
}
