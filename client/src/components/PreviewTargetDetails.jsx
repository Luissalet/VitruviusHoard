import React from "react";

export default function PreviewTargetDetails({ es, selector, source, locator, files }) {
  if (!selector && !source && !locator && !files?.length) return null;
  return <details className="preview-selection-details">
    <summary>{es ? "Detalles técnicos" : "Technical details"}</summary>
    <dl>
      {selector && <><dt>Selector</dt><dd><code>{selector}</code></dd></>}
      {source && <><dt>{es ? "Origen" : "Source"}</dt><dd><code>{source}</code></dd></>}
      {locator && <><dt>{es ? "Localizador" : "Locator"}</dt><dd><code>{locator}</code></dd></>}
      {!!files?.length && <><dt>{es ? "Ficheros" : "Files"}</dt><dd>
        <ul>{files.map((file) => <li key={file}><code>{file}</code></li>)}</ul>
      </dd></>}
    </dl>
  </details>;
}
