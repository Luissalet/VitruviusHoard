import React from "react";

export default function CaptureWarning({ captures, lang }) {
  if (!captures?.length) return null;
  return (
    <ul role="status" className="list-none space-y-1 text-[13px]">
      {captures.map(({ width, captured_height, page_height }) => (
        <li key={width}>
          <strong>{lang === "es" ? "Captura recortada" : "Cropped screenshot"}.</strong>{" "}
          {lang === "es"
            ? `${width} px de ancho, ${captured_height} de ${page_height} px de alto.`
            : `${width} px wide, ${captured_height} of ${page_height} px tall.`}
        </li>
      ))}
    </ul>
  );
}
