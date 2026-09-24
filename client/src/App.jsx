import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import { initialLang, makeT, saveLang } from "./i18n.js";
import { Icon } from "./components/ui.jsx";
import Library from "./pages/Library.jsx";
import Critique from "./pages/Critique.jsx";
import Tokens from "./pages/Tokens.jsx";
import Gallery from "./pages/Gallery.jsx";
import Settings from "./pages/Settings.jsx";

const PAGES = [
  { path: "library", key: "nav_library", icon: "M4 19.5A2.5 2.5 0 016.5 17H20M4 19.5A2.5 2.5 0 006.5 22H20V4H6.5A2.5 2.5 0 004 6.5v13z", component: Library },
  { path: "critique", key: "nav_critique", icon: "M9 3H5a2 2 0 00-2 2v4m18 0V5a2 2 0 00-2-2h-4m0 18h4a2 2 0 002-2v-4M3 15v4a2 2 0 002 2h4", component: Critique },
  { path: "tokens", key: "nav_tokens", icon: "M12 2l2.5 5 5.5.8-4 3.9.9 5.5L12 14.7 7.1 17.2l.9-5.5-4-3.9L9.5 7z", component: Tokens },
  { path: "gallery", key: "nav_gallery", icon: "M4 5h16v14H4zM4 15l4-4 3 3 5-5 4 4", component: Gallery },
  { path: "settings", key: "nav_settings", icon: "M12 15a3 3 0 100-6 3 3 0 000 6zM19 12l2-1-1-3-2 .3-1.4-1.4.3-2-3-1-1 2h-2l-1-2-3 1 .3 2L6.8 7.3 5 7 4 10l2 1v2l-2 1 1 3 2-.3 1.4 1.4-.3 2 3 1 1-2h2l1 2 3-1-.3-2 1.4-1.4 2 .3 1-3-2-1z", component: Settings },
];

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

function useHashRoute() {
  const read = () => {
    const [path] = window.location.hash.replace(/^#\/?/, "").split("?");
    const parts = path.split("/");
    return { page: parts[0] || "library", param: parts[1] || null };
  };
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function Toast({ message, onClose }) {
  useEffect(() => {
    if (!message) return undefined;
    const timer = setTimeout(onClose, 4500);
    return () => clearTimeout(timer);
  }, [message, onClose]);
  if (!message) return null;
  return (
    <div className="toast" role="status" onClick={onClose}>
      {message}
    </div>
  );
}

export default function App() {
  const route = useHashRoute();
  const [lang, setLang] = useState(initialLang);
  const t = useMemo(() => makeT(lang), [lang]);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const refresh = useCallback(async () => {
    try {
      setHealth(await api.health());
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => clearInterval(timer);
  }, [refresh]);

  const notify = useCallback((message) => setToast(message), []);
  const value = useMemo(() => ({ health, refresh, notify, t, lang }), [health, refresh, notify, t, lang]);

  const page = PAGES.find((p) => p.path === route.page) || PAGES[0];
  const Component = page.component;

  const switchLang = () => {
    const next = lang === "es" ? "en" : "es";
    saveLang(next);
    setLang(next);
  };

  return (
    <AppContext.Provider value={value}>
      <div className="min-h-dvh md:grid md:grid-cols-[216px_minmax(0,1fr)]">
        <aside className="sticky top-0 z-10 border-b md:self-start md:h-dvh md:border-b-0 md:border-r" style={{ background: "var(--sidebar)", borderColor: "var(--line)" }}>
          <div className="flex items-center gap-3 px-4 py-3 md:px-5 md:py-5">
            <img src="/icon-192.png" alt="" width="34" height="34" className="rounded-lg" />
            <div className="leading-tight">
              <div className="text-[15px] font-semibold">Vitruvius's Hoard</div>
              <div className="help text-[11px]">{t("tagline")}</div>
            </div>
          </div>
          <nav aria-label="Sections" className="flex gap-1 overflow-x-auto px-3 pb-2 md:flex-col">
            {PAGES.map((p) => (
              <a key={p.path} href={`#/${p.path}`} className="nav-link shrink-0 text-[13px]" aria-current={p.path === page.path ? "page" : undefined}>
                <Icon d={p.icon} />
                {t(p.key)}
              </a>
            ))}
          </nav>
          <div className="hidden px-5 pt-4 md:block">
            {health && (
              <div className="help text-[11px]">
                {health.counts?.sources ?? 0} {t("sources_title").toLowerCase()} · {health.counts?.chunks ?? 0} {t("chunks")}
              </div>
            )}
            <button type="button" className="btn btn-sm mt-4" onClick={switchLang}>{t("language")}</button>
          </div>
        </aside>
        <main className="min-w-0 px-4 py-4 md:px-8 md:py-7">
          {error && (
            <div className="mb-4 rounded-md border p-3 text-[13px]" style={{ background: "var(--danger-bg)", borderColor: "#e5534b66" }} role="alert">
              {t("unreachable")}: {error}. <button type="button" className="btn-link" onClick={refresh}>{t("retry")}</button>
            </div>
          )}
          <Component param={route.param} />
          <div className="mt-8 md:hidden">
            <button type="button" className="btn btn-sm" onClick={switchLang}>{t("language")}</button>
          </div>
        </main>
      </div>
      <Toast message={toast} onClose={() => setToast(null)} />
    </AppContext.Provider>
  );
}
