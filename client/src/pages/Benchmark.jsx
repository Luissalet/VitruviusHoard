import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

const percent = (value) =>
  value == null ? "—" : `${Number(value).toFixed(2)} %`;
const at = (url) => `/design${url}`;
const states = {
  pending: ["Pendiente", "Pending"],
  preparing: ["Descargando referencia", "Downloading reference"],
  remaking: ["Rehaciendo", "Remaking"],
  measured: ["Medida", "Measured"],
  failed: ["Error", "Error"],
  queued: ["En cola", "Queued"],
  running: ["En curso", "Running"],
  done: ["Terminado", "Finished"],
  stopped: ["Parado", "Stopped"],
  interrupted: ["Interrumpido", "Interrupted"],
};

export default function Benchmark({ es, notify, openRemake }) {
  const [catalog, setCatalog] = useState(null);
  const [history, setHistory] = useState([]);
  const [run, setRun] = useState(null);
  const [version, setVersion] = useState("");
  const [selection, setSelection] = useState("");
  const [mode, setMode] = useState("copy");
  const [rounds, setRounds] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [before, setBefore] = useState("");
  const [comparison, setComparison] = useState(null);
  const activeRun = history.find((item) => item.running);
  const state = (value) => (states[value] || [value, value])[es ? 0 : 1];
  const refresh = useCallback(async () => {
    try {
      const [manifest, list] = await Promise.all([
        api.benchmarkCatalog(),
        api.benchmarkList(),
      ]);
      setCatalog(manifest);
      setHistory(list.runs);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  useEffect(() => {
    if (!activeRun) return undefined;
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [activeRun?.id, refresh]);
  useEffect(() => {
    if (!run?.running) return undefined;
    let alive = true;
    const timer = setInterval(async () => {
      try {
        const next = await api.benchmarkGet(run.id);
        if (alive) {
          setRun(next);
          if (!next.running) refresh();
        }
      } catch (e) {
        if (alive) setError(e.message);
      }
    }, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [run?.id, run?.running, refresh]);
  const act = async (fn) => {
    setBusy(true);
    setError("");
    try {
      setRun(await fn());
      setComparison(null);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const label = (id) => {
    const index = catalog?.cases.findIndex((item) => item.id === id) ?? -1;
    return `${es ? "Referencia" : "Reference"} ${String(index + 1).padStart(2, "0")}`;
  };
  return (
    <section
      className="panel flex flex-col gap-3"
      aria-labelledby="benchmark-title"
      data-testid="benchmark"
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 id="benchmark-title" className="text-[14px] font-semibold">
          {es ? "Banco de pruebas" : "Reconstruction benchmark"}
        </h2>
        <button type="button" className="btn btn-sm" onClick={refresh}>
          {es ? "Actualizar" : "Refresh"}
        </button>
      </div>
      <p className="help m-0" style={{ maxWidth: "72ch" }}>
        {es
          ? "70 referencias congeladas. Guarda la paridad visual de sus páginas de entrada a 1440 y 390 px por versión. Cada evaluación conserva configuración, hashes, rondas y capturas. Los casos funcionales y la puntuación SSIM oficial quedan sin medir."
          : "70 frozen references. Retains entry-page visual parity at 1440 and 390 px by version, with settings, hashes, rounds and captures. Functional cases and the official SSIM reward remain unmeasured."}
      </p>
      {error && (
        <p
          role="alert"
          className="help"
          style={{ color: "var(--danger)", overflowWrap: "anywhere" }}
        >
          {error}
        </p>
      )}
      {activeRun && run?.id !== activeRun.id && (
        <div
          className="flex gap-3 items-center flex-wrap"
          role="status"
          data-testid="benchmark-active"
        >
          <span
            className="help"
            style={{ overflowWrap: "anywhere", minWidth: 0 }}
          >
            {es ? "Evaluación en curso" : "Evaluation in progress"} ·{" "}
            {activeRun.version}
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy}
            onClick={() => act(() => api.benchmarkGet(activeRun.id))}
          >
            {es ? "Ver evaluación en curso" : "View running evaluation"}
          </button>
        </div>
      )}
      <form
        className="flex gap-3 items-end flex-wrap"
        onSubmit={(event) => {
          event.preventDefault();
          act(() =>
            api.benchmarkStart({
              version,
              cases: selection ? [selection] : null,
              mode,
              max_rounds: Number(rounds),
            }),
          );
        }}
      >
        <label style={{ flex: "1 1 220px" }}>
          <span className="label">
            {es ? "Versión que se mide" : "Version to measure"}
          </span>
          <input
            className="field"
            required
            maxLength={200}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            data-testid="benchmark-version"
          />
        </label>
        <label style={{ flex: "1 1 190px" }}>
          <span className="label">{es ? "Referencias" : "References"}</span>
          <select
            className="field"
            value={selection}
            onChange={(e) => setSelection(e.target.value)}
            data-testid="benchmark-selection"
          >
            <option value="">
              {es ? "Corpus completo (70)" : "Complete corpus (70)"}
            </option>
            {catalog?.cases.map((item) => (
              <option key={item.id} value={item.id}>
                {label(item.id)}
              </option>
            ))}
          </select>
        </label>
        <label style={{ flex: "1 1 180px" }}>
          <span className="label">{es ? "Método" : "Method"}</span>
          <select
            className="field"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="copy">
              {es ? "Copia de la página" : "Page copy"}
            </option>
            <option value="rebuild">
              {es ? "Reconstrucción con modelo" : "Model rebuild"}
            </option>
          </select>
        </label>
        <label style={{ width: 90 }}>
          <span className="label">{es ? "Rondas" : "Rounds"}</span>
          <input
            className="field"
            type="number"
            required
            min={1}
            max={20}
            value={rounds}
            onChange={(e) => setRounds(e.target.value)}
          />
        </label>
        <button
          className="btn btn-primary"
          disabled={busy || !catalog || Boolean(activeRun)}
          data-testid="benchmark-start"
        >
          {busy
            ? es
              ? "Iniciando…"
              : "Starting…"
            : es
              ? "Evaluar versión"
              : "Evaluate version"}
        </button>
      </form>
      <p className="help m-0">
        {es
          ? "La primera ejecución descarga las referencias seleccionadas y las inicia con datos locales nuevos."
          : "The first run downloads the selected references and starts them with fresh local state."}
      </p>
      {history.length > 0 && (
        <div className="flex gap-3 flex-wrap items-end">
          <label style={{ flex: "1 1 240px" }}>
            <span className="label">
              {es ? "Historial por versión" : "Version history"}
            </span>
            <select
              className="field"
              value={run?.id || ""}
              onChange={(e) =>
                e.target.value && act(() => api.benchmarkGet(e.target.value))
              }
              data-testid="benchmark-history"
            >
              <option value="">
                {es ? "Elegir evaluación" : "Choose evaluation"}
              </option>
              {history.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.version} · {state(item.status)} ·{" "}
                  {item.summary.measured}/{item.summary.selected} ·{" "}
                  {new Date(item.created_ts * 1000).toLocaleString()}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {run && (
        <div className="flex flex-col gap-3" data-testid="benchmark-result">
          {run.error && (
            <p
              role="alert"
              className="help"
              style={{ color: "var(--danger)", overflowWrap: "anywhere" }}
            >
              {run.error}
            </p>
          )}
          <div className="flex flex-wrap gap-3 items-center" role="status">
            <strong style={{ overflowWrap: "anywhere" }}>{run.version}</strong>
            <span>{state(run.status)}</span>
            <span>
              {run.summary.measured}/{run.summary.selected}{" "}
              {es ? "medidas" : "measured"}
            </span>
            <span>
              {run.summary.failed} {es ? "errores" : "errors"}
            </span>
            <span>
              {es ? "Media medida" : "Measured mean"}{" "}
              {percent(run.summary.mean_score)}
            </span>
          </div>
          <p className="help m-0">
            {run.settings.mode} · {run.settings.max_rounds}{" "}
            {run.settings.max_rounds === 1
              ? es
                ? "ronda"
                : "round"
              : es
                ? "rondas"
                : "rounds"}{" "}
            · {run.settings.widths.join(" / ")} px ·{" "}
            {es ? "umbral" : "threshold"} {run.settings.pass_score} %
          </p>
          <details className="help">
            <summary>
              {es ? "Procedencia y código" : "Provenance and code"}
            </summary>
            <p style={{ overflowWrap: "anywhere" }}>
              {es ? "Corpus" : "Corpus"} {run.corpus.revision}
              <br />
              SHA-256 {run.implementation_sha256}
            </p>
            <a
              className="btn-link"
              href={run.corpus.source}
              target="_blank"
              rel="noreferrer"
            >
              {es
                ? "Fuente y licencia del corpus"
                : "Corpus source and license"}
            </a>
          </details>
          <div className="flex gap-2 flex-wrap">
            <a className="btn btn-sm" href={at(run.export_url)}>
              {es ? "Descargar resultados JSON" : "Download results JSON"}
            </a>
            {run.running && (
              <button
                className="btn btn-sm"
                type="button"
                disabled={busy}
                onClick={() => act(() => api.benchmarkStop(run.id))}
              >
                {es ? "Parar evaluación" : "Stop evaluation"}
              </button>
            )}
            {!run.running &&
              ["stopped", "interrupted"].includes(run.status) && (
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={busy}
                  onClick={() => act(() => api.benchmarkResume(run.id))}
                >
                  {es ? "Reanudar pendientes" : "Resume pending cases"}
                </button>
              )}
          </div>
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              <thead>
                <tr className="help">
                  <th align="left">{es ? "Referencia" : "Reference"}</th>
                  <th align="left">{es ? "Estado" : "Status"}</th>
                  <th align="right">{es ? "Paridad" : "Parity"}</th>
                  <th>
                    <span className="sr-only">
                      {es ? "Evidencia" : "Evidence"}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {run.cases.map((row) => (
                  <tr
                    key={row.id}
                    style={{ borderTop: "1px solid var(--line)" }}
                    data-testid="benchmark-case"
                  >
                    <td className="py-2 pr-3" style={{ whiteSpace: "nowrap" }}>
                      {label(row.id)}
                    </td>
                    <td className="py-2 pr-3">
                      <span>{state(row.status)}</span>
                      {row.error && (
                        <details className="help">
                          <summary>{es ? "Ver error" : "Read error"}</summary>
                          <pre
                            style={{
                              whiteSpace: "pre-wrap",
                              overflowWrap: "anywhere",
                              maxWidth: 380,
                            }}
                          >
                            {row.error}
                          </pre>
                        </details>
                      )}
                    </td>
                    <td
                      align="right"
                      className="py-2 pr-3"
                      style={{ whiteSpace: "nowrap" }}
                    >
                      {percent(row.score)}
                    </td>
                    <td className="py-2">
                      {row.remake_id && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => {
                            openRemake(row.remake_id);
                            notify(
                              es
                                ? "Proyecto abierto debajo del banco de pruebas."
                                : "Project opened below the benchmark.",
                            );
                          }}
                        >
                          {es ? "Ver proyecto" : "View project"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-3 flex-wrap items-end">
            <label style={{ flex: "1 1 240px" }}>
              <span className="label">
                {es
                  ? "Comparar con una versión anterior"
                  : "Compare with a previous version"}
              </span>
              <select
                className="field"
                value={before}
                onChange={(e) => {
                  setBefore(e.target.value);
                  setComparison(null);
                }}
              >
                <option value="">
                  {es ? "Elegir evaluación" : "Choose evaluation"}
                </option>
                {history
                  .filter((item) => item.id !== run.id)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.version} ·{" "}
                      {new Date(item.created_ts * 1000).toLocaleString()}
                    </option>
                  ))}
              </select>
            </label>
            <button
              className="btn btn-sm"
              type="button"
              disabled={!before || busy}
              onClick={async () => {
                try {
                  setComparison(await api.benchmarkCompare(before, run.id));
                } catch (e) {
                  setError(e.message);
                }
              }}
            >
              {es ? "Comparar versiones" : "Compare versions"}
            </button>
          </div>
          {comparison && (
            <p
              role="status"
              className="help m-0"
              data-testid="benchmark-comparison"
            >
              {comparison.comparable
                ? `${es ? "Variación media" : "Mean change"} ${comparison.mean_delta == null ? "—" : `${comparison.mean_delta > 0 ? "+" : ""}${comparison.mean_delta.toFixed(2)}`} · ${comparison.paired_measured}/${comparison.selected} ${es ? "pares medidos" : "measured pairs"}`
                : `${es ? "Configuraciones incompatibles" : "Incompatible configurations"} (${comparison.differences.join(", ")})`}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
