// Small formatting helpers shared by the pages.
export const STATUS_COLORS = {
  idle: "var(--muted)",
  cloning: "var(--accent)",
  ingesting: "var(--accent)",
  ready: "var(--ok)",
  error: "var(--danger)",
};

export const SEVERITY_COLORS = {
  info: "var(--accent)",
  warn: "var(--warn)",
  error: "var(--danger)",
};

export function clock(ts, lang) {
  if (!ts) return "—";
  const date = new Date(ts * 1000);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  const locale = lang === "en" ? "en-GB" : "es-ES";
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  return sameDay ? time : `${date.toLocaleDateString(locale, { day: "2-digit", month: "short" })} ${time}`;
}

// WCAG relative luminance / contrast ratio, used for the token ramp swatches.
export function hexToRgb(hex) {
  const clean = (hex || "").replace("#", "");
  const full = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
  const num = parseInt(full, 16);
  if (Number.isNaN(num) || full.length < 6) return { r: 0, g: 0, b: 0 };
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
}

function relativeLuminance({ r, g, b }) {
  const lin = (c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  const [rl, gl, bl] = [lin(r), lin(g), lin(b)];
  return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl;
}

export function contrastRatio(hexA, hexB) {
  const la = relativeLuminance(hexToRgb(hexA));
  const lb = relativeLuminance(hexToRgb(hexB));
  const [lighter, darker] = la > lb ? [la, lb] : [lb, la];
  return (lighter + 0.05) / (darker + 0.05);
}

export function bestTextColor(hex) {
  return contrastRatio(hex, "#ffffff") >= contrastRatio(hex, "#000000") ? "#ffffff" : "#000000";
}

// Render/reference file paths are absolute server paths; the API serves them by the
// portion relative to that render/reference's own folder (e.g. "desktop/1440.png").
export function fileRelPath(fullPath, id) {
  if (!fullPath) return "";
  const marker = `/${id}/`;
  const idx = fullPath.indexOf(marker);
  if (idx === -1) return fullPath.split("/").pop();
  return fullPath.slice(idx + marker.length);
}

export function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
