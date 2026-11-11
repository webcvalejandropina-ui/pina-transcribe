// Se carga en <head> antes de pintar: aplica tema e idioma guardados sin parpadeo.
(() => {
  const root = document.documentElement;
  const params = new URLSearchParams(location.search);
  const read = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const themePref = params.get('theme') || read('pina.theme') || 'auto';
  const dark = themePref === 'dark' ||
    (themePref === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  root.dataset.themePref = themePref;
  root.dataset.theme = dark ? 'dark' : 'light';
  const browserLang = (navigator.language || 'es').slice(0, 2).toLowerCase();
  const lang = params.get('lang') || read('pina.lang') || (browserLang === 'es' ? 'es' : 'en');
  root.lang = lang === 'en' ? 'en' : 'es';
})();
