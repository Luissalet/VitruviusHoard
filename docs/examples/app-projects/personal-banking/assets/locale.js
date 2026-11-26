const requested = new URLSearchParams(location.search).get('lang');
let preferred;
try {
  if (requested === 'en' || requested === 'es') localStorage.setItem('tesela-language', requested);
  preferred = localStorage.getItem('tesela-language');
} catch { /* Storage can be disabled. The URL still works. */ }
export const lang = (requested || preferred) === 'en' ? 'en' : 'es';
export const locale = lang === 'en' ? 'en-IE' : 'es-ES';
export const decimal = lang === 'en' ? '.' : ',';
export const t = (es, en) => lang === 'en' ? en : es;

document.documentElement.lang = lang;
if (lang === 'en') {
  for (const node of document.querySelectorAll('[data-en]')) node.textContent = node.dataset.en;
  for (const [suffix, attribute] of [['label', 'aria-label'], ['title', 'title'], ['placeholder', 'placeholder'], ['content', 'content']]) {
    for (const node of document.querySelectorAll(`[data-en-${suffix}]`)) {
      node.setAttribute(attribute, node.getAttribute(`data-en-${suffix}`));
    }
  }
}

const languageLink = document.getElementById('language-switch');
if (languageLink) {
  const next = t('en', 'es');
  const url = new URL(location.href);
  url.searchParams.set('lang', next);
  languageLink.href = url.pathname + url.search + url.hash;
  languageLink.lang = next;
  languageLink.hreflang = next;
  languageLink.textContent = next.toUpperCase();
  languageLink.setAttribute('aria-label', t('English', 'Español'));
}
