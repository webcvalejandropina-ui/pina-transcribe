// Piña Transcribe · lógica de la interfaz (sin dependencias).
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const DICT = window.PINA_I18N;
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* modo privado */ } },
  };

  const DEFAULT_MODELS = ['tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en', 'medium', 'medium.en', 'large-v1', 'large-v2', 'large-v3', 'large'];
  const PHASES = ['init', 'download', 'transcribe', 'save', 'done'];

  const state = {
    lang: root.lang === 'en' ? 'en' : 'es',
    platform: 'youtube',
    device: 'auto',
    model: store.get('pina.model') || '',
    models: [],
    recommended: '',
    about: null,
    system: null,
    pollTimer: null,
    elapsedTimer: null,
    startedAt: 0,
    transcript: '',
    lastResult: null,
    lastError: null,
    lastProgress: null,
    history: [],
    online: true,
  };

  const show = (id, on) => $(id).classList.toggle('active', on);

  // ---------------------------------------------------------------- i18n
  const t = (key, vars) => {
    let s = (DICT[state.lang] && DICT[state.lang][key]) ?? DICT.es[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace('{' + k + '}', v);
    return s;
  };

  const applyI18n = () => {
    root.lang = state.lang;
    document.title = t('meta.title');
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-html]').forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    document.querySelectorAll('[data-i18n-title]').forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    document.querySelectorAll('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
    document.querySelectorAll('[data-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === state.lang)));
    setOnline(state.online);
    renderModels();
    renderAbout();
    renderSystem();
    renderHistory();
    if (state.lastResult) renderResult(state.lastResult.id, state.lastResult.job, false);
    if (state.lastProgress) setProgress(...state.lastProgress);
    if (state.lastError) showError(state.lastError);
  };

  document.querySelectorAll('[data-lang]').forEach((btn) => btn.addEventListener('click', () => {
    state.lang = btn.dataset.lang;
    store.set('pina.lang', state.lang);
    applyI18n();
  }));

  // ---------------------------------------------------------------- tema
  const media = matchMedia('(prefers-color-scheme: dark)');
  const applyTheme = (pref) => {
    root.dataset.themePref = pref;
    root.dataset.theme = pref === 'dark' || (pref === 'auto' && media.matches) ? 'dark' : 'light';
    document.querySelectorAll('[data-theme-choice]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.themeChoice === pref)));
  };
  document.querySelectorAll('[data-theme-choice]').forEach((b) => b.addEventListener('click', () => {
    store.set('pina.theme', b.dataset.themeChoice);
    applyTheme(b.dataset.themeChoice);
  }));
  media.addEventListener('change', () => { if (root.dataset.themePref === 'auto') applyTheme('auto'); });
  applyTheme(root.dataset.themePref || 'auto');

  // ---------------------------------------------------------------- utilidades
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const fmtClock = (sec) => {
    const s = Math.max(0, Math.round(sec));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    const pad = (n) => String(n).padStart(2, '0');
    return h ? `${h}:${pad(m)}:${pad(r)}` : `${m}:${pad(r)}`;
  };
  const fmtAgo = (ts) => {
    if (!ts) return '';
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 60) return t('ago.s', { n: s });
    if (s < 3600) return t('ago.m', { n: Math.floor(s / 60) });
    if (s < 86400) return t('ago.h', { n: Math.floor(s / 3600) });
    return t('ago.d', { n: Math.floor(s / 86400) });
  };
  const api = async (url, opts) => {
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch { /* sin cuerpo */ }
    return { ok: res.ok, status: res.status, data };
  };

  // ---------------------------------------------------------------- reloj
  const tickClock = () => {
    const d = new Date();
    $('clock').textContent = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  };
  tickClock();
  setInterval(tickClock, 30000);

  // ---------------------------------------------------------------- segmentados
  const setSegmented = (id, value) => {
    $(id).querySelectorAll('.chip').forEach((b) => {
      const on = b.dataset.value === value;
      b.setAttribute('aria-checked', String(on));
      b.classList.toggle('active', on);
    });
  };
  const bindSegmented = (id, onChange) => {
    $(id).querySelectorAll('.chip').forEach((b) => b.addEventListener('click', () => {
      setSegmented(id, b.dataset.value);
      onChange(b.dataset.value);
    }));
  };
  bindSegmented('platform', (v) => { state.platform = v; });
  bindSegmented('device', (v) => { state.device = v; renderHints(); });
  setSegmented('platform', 'youtube');
  setSegmented('device', 'auto');

  // ---------------------------------------------------------------- modelos
  // Sin preferencia guardada, se usa el modelo recomendado para este equipo.
  const currentModel = () => state.model || state.recommended || 'tiny';
  // Avisos según el equipo: qué procesador se usará y si el modelo encaja.
  const baseModel = (m) => m.replace(/\.en$/, '');
  const setHint = (id, text, kind) => {
    const el = $(id);
    el.textContent = text || '';
    el.classList.toggle('warn', kind === 'warn');
    el.classList.toggle('good', kind === 'good');
  };
  const renderHints = () => {
    const s = state.system;
    if (!s) { setHint('device-hint', t('side.checking')); setHint('model-hint', ''); return; }
    const gpuBtn = $('device').querySelector('[data-value="gpu"]');
    gpuBtn.disabled = s.gpu_count === 0;
    if (s.gpu_count === 0 && state.device === 'gpu') { state.device = 'auto'; setSegmented('device', 'auto'); }
    if (s.gpu_count > 0 && state.device !== 'cpu') setHint('device-hint', t('hint.device.gpu', { n: s.gpu_count }), 'good');
    else setHint('device-hint', t('hint.device.cpu', { n: s.cpu_threads }));

    const m = currentModel();
    const r = t('model.' + state.recommended);
    const gpuTxt = s.gpu_count > 0 ? s.gpu_count + ' GPU NVIDIA' : t('hint.nogpu');
    const st = modelStatus(m);
    let text, kind;
    if (st === 'nofit') {
      text = t('hint.model.heavy', { g: (s.model_memory_gb || {})[m], have: s.memory_gb }); kind = 'warn';
    } else if (st === 'ideal') {
      text = t('hint.model.ideal', { cpu: s.cpu_threads, mem: s.memory_gb ?? '?', gpu: gpuTxt }); kind = 'good';
    } else if (st === 'slower') {
      text = t('hint.model.slow', { r }); kind = 'warn';
    } else {
      text = t('hint.model.fast', { r });
    }
    setHint('model-hint', text, kind);
  };

  // Botones de calidad: nombre claro + estado calculado para este equipo.
  const UI_MODELS = ['tiny', 'base', 'small', 'medium', 'large-v3'];
  const modelStatus = (m) => {
    const s = state.system;
    if (!s) return '';
    const need = (s.model_memory_gb || {})[m];
    if (need && s.memory_gb && need > s.memory_gb) return 'nofit';
    if (m === state.recommended) return 'ideal';
    const order = s.model_order || [];
    return order.indexOf(m) < order.indexOf(state.recommended) ? 'faster' : 'slower';
  };
  const renderModels = () => {
    const available = state.models.length ? state.models : DEFAULT_MODELS;
    const list = UI_MODELS.filter((m) => available.includes(m));
    const selected = currentModel();
    $('models').innerHTML = list.map((m) => {
      const st = modelStatus(m);
      const tag = st ? t('model.status.' + st) : '';
      return `<button type="button" class="chip chip-model${m === selected ? ' active' : ''}${st ? ' st-' + st : ''}" role="radio" data-value="${m}" aria-checked="${m === selected}"${st === 'nofit' ? ' disabled' : ''}>
        <span class="m-name">${escapeHtml(t('model.' + m))}</span>
        <span class="m-meta">${escapeHtml(m)}${tag ? ' · ' + escapeHtml(tag) : ''}</span>
      </button>`;
    }).join('');
    $('models').querySelectorAll('.chip').forEach((c) => c.addEventListener('click', () => {
      state.model = c.dataset.value;
      store.set('pina.model', state.model);
      renderModels();
    }));
    renderHints();
  };

  // ---------------------------------------------------------------- detección de enlaces
  const YT_URL = /(?:youtube\.com\/watch\?(?:.*&)?v=|youtu\.be\/|youtube\.com\/shorts\/|youtube\.com\/live\/|youtube\.com\/embed\/)([A-Za-z0-9_-]{11})/;
  const YT_ID = /^[A-Za-z0-9_-]{11}$/;
  const TW_URL = /twitch\.tv\/(?:[^/]+\/)?videos?\/(\d+)/;
  const TW_ID = /^\d+$/;
  const detect = (raw) => {
    const v = raw.trim();
    let m;
    if ((m = v.match(YT_URL))) return { platform: 'youtube', id: m[1] };
    if ((m = v.match(TW_URL))) return { platform: 'twitch', id: m[1] };
    if (YT_ID.test(v)) return { platform: 'youtube', id: v };
    if (TW_ID.test(v)) return { platform: 'twitch', id: v };
    return null;
  };
  const onSourceInput = () => {
    const d = detect($('source').value);
    $('detected').textContent = d ? d.platform.toUpperCase() + ' / ' + d.id : '';
    if (d) { state.platform = d.platform; setSegmented('platform', d.platform); }
  };
  $('source').addEventListener('input', onSourceInput);
  $('source').addEventListener('paste', () => setTimeout(onSourceInput, 0));
  $('source').addEventListener('focus', () => $('url-pill').classList.add('focused'));
  $('source').addEventListener('blur', () => $('url-pill').classList.remove('focused'));

  // ---------------------------------------------------------------- tiempos
  const parseTime = (raw) => {
    const v = raw.trim().replace(',', '.');
    if (!v) return null;
    const parts = v.split(':');
    if (parts.length > 3 || parts.some((p) => p === '' || isNaN(Number(p)))) return NaN;
    const nums = parts.map(Number);
    if (nums.some((n) => n < 0) || nums.slice(1).some((n) => n >= 60)) return NaN;
    return nums.reduce((acc, n) => acc * 60 + n, 0);
  };
  ['start', 'end'].forEach((id) => $(id).addEventListener('input', () => {
    $(id + '-pill').classList.toggle('invalid', Number.isNaN(parseTime($(id).value)));
  }));

  // ---------------------------------------------------------------- progreso
  const startElapsed = (fromTs) => {
    state.startedAt = fromTs ? fromTs * 1000 : Date.now();
    clearInterval(state.elapsedTimer);
    const tick = () => {
      const s = Math.floor((Date.now() - state.startedAt) / 1000);
      $('elapsed').textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
    };
    tick();
    state.elapsedTimer = setInterval(tick, 500);
  };
  const stopElapsed = () => clearInterval(state.elapsedTimer);

  const setProgress = (phase, pct, msgKey) => {
    state.lastProgress = [phase, pct, msgKey];
    show('progress', true);
    const idx = Math.max(0, PHASES.indexOf(phase));
    const p = Math.round(pct || 0);
    document.querySelectorAll('#steps .phase').forEach((el, i) => {
      const done = i < idx || phase === 'done';
      el.classList.toggle('done', done);
      el.classList.toggle('active', i === idx && phase !== 'done');
      el.querySelector('.pct').textContent = done ? '100' : i === idx ? String(p) : '--';
    });
    $('bar-fill').style.width = p + '%';
    $('bar').setAttribute('aria-valuenow', String(p));
    $('bar-pct').textContent = p + '%';
    $('bar-msg').textContent = msgKey ? t('msg.' + msgKey) : t('progress.waiting');
  };
  const resetProgress = () => {
    state.lastProgress = null;
    show('progress', false);
    $('bar-fill').style.width = '0';
    $('bar-pct').textContent = '0%';
    $('elapsed').textContent = '00:00';
    $('bar-msg').textContent = t('progress.waiting');
    document.querySelectorAll('#steps .phase').forEach((el) => {
      el.classList.remove('done', 'active');
      el.querySelector('.pct').textContent = '--';
    });
  };

  const showError = (err) => {
    state.lastError = err;
    const code = err && err.code;
    const known = code && DICT.es['err.' + code];
    $('error-msg').textContent = known ? t('err.' + code) : (err && err.message) || t('err.unexpected');
    show('error', true);
  };
  const clearError = () => { state.lastError = null; show('error', false); };
  const detailToErr = (data, fallback) => {
    const d = data && data.detail;
    if (d && typeof d === 'object' && d.code) return d;
    if (typeof d === 'string') return { message: d };
    if (Array.isArray(d)) return { code: 'invalid_source' };
    return { code: fallback };
  };

  // ---------------------------------------------------------------- envío
  const busy = (on) => { $('submit').disabled = on; };

  const submit = async () => {
    const raw = $('source').value.trim();
    if (!raw) { $('source').focus(); return; }
    const start = $('start').value.trim();
    const end = $('end').value.trim();
    if (Number.isNaN(parseTime(start)) || Number.isNaN(parseTime(end))) {
      showError({ code: 'invalid_time' });
      return;
    }
    const d = detect(raw);
    if (d) { state.platform = d.platform; setSegmented('platform', d.platform); }

    clearError();
    show('result', false);
    state.lastResult = null;
    busy(true);
    resetProgress();
    setProgress('init', 0, 'init.queued');
    startElapsed();

    let r;
    try {
      r = await api('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform: state.platform,
          video_id: raw,
          model: currentModel(),
          lang: $('lang').value,
          device: state.device,
          start: start || null,
          end: end || null,
        }),
      });
    } catch {
      r = null;
    }
    if (!r || !r.ok) {
      busy(false); stopElapsed(); resetProgress();
      showError(r ? detailToErr(r.data, 'unexpected') : { code: 'network' });
      return;
    }
    history.replaceState(null, '', '#' + r.data.job_id);
    poll(r.data.job_id);
  };

  const poll = (jobId) => {
    clearInterval(state.pollTimer);
    const once = async () => {
      let r;
      try { r = await api('/api/jobs/' + jobId); } catch { return; }
      if (!r.ok) {
        clearInterval(state.pollTimer);
        busy(false); stopElapsed();
        showError(detailToErr(r.data, 'job_not_found'));
        return;
      }
      const j = r.data;
      setProgress(j.phase || 'init', j.progress || 0, j.status === 'error' ? null : j.message);
      if (j.status === 'done') {
        clearInterval(state.pollTimer);
        busy(false); stopElapsed();
        renderResult(jobId, j, true);
        refreshHistory();
      } else if (j.status === 'error') {
        clearInterval(state.pollTimer);
        busy(false); stopElapsed();
        showError({ code: j.error_code, message: j.error || j.message });
        refreshHistory();
      }
    };
    once();
    state.pollTimer = setInterval(once, 500);
  };

  $('form').addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  $('reset').addEventListener('click', () => {
    ['source', 'start', 'end', 'search'].forEach((id) => { $(id).value = ''; });
    ['start-pill', 'end-pill'].forEach((id) => $(id).classList.remove('invalid'));
    $('lang').value = '';
    onSourceInput();
    clearError();
    resetProgress();
    show('result', false);
    state.lastResult = null;
    history.replaceState(null, '', location.pathname + location.search);
  });

  // ---------------------------------------------------------------- resultado
  const renderResult = (jobId, job, scroll) => {
    state.lastResult = { id: jobId, job };
    const r = job.result || {};
    $('r-title').textContent = r.title || t('result.title');
    const words = (r.text || '').split(/\s+/).filter(Boolean).length;
    const parts = [];
    if (r.platform) parts.push('<b>' + escapeHtml(r.platform.toUpperCase()) + '</b>');
    if (r.language) parts.push(escapeHtml(t('result.lang')) + ' <b>' + escapeHtml(r.language) + '</b>');
    if (r.model) parts.push(escapeHtml(t('result.model')) + ' <b>' + escapeHtml(r.model) + '</b>');
    if (r.device) parts.push(escapeHtml(t('result.device')) + ' <b>' + escapeHtml(r.device.toUpperCase()) + '</b>');
    if (r.start_seconds != null || r.end_seconds != null) {
      const b = r.end_seconds != null ? fmtClock(r.end_seconds) : '…';
      parts.push(escapeHtml(t('result.range')) + ' <b>' + fmtClock(r.start_seconds || 0) + ' – ' + b + '</b>');
    }
    parts.push(escapeHtml(t('result.words', { n: words.toLocaleString(state.lang) })));
    if (r.url && /^https:\/\/(www\.)?(youtube\.com|twitch\.tv)\//.test(r.url)) {
      parts.push('<a href="' + escapeHtml(r.url) + '" target="_blank" rel="noopener noreferrer" class="source-link">' + escapeHtml(t('result.source')) + '</a>');
    }
    $('r-tags').innerHTML = parts.join(' · ');
    state.transcript = r.text || '';
    highlight($('search').value);
    $('dl-txt').href = '/api/jobs/' + jobId + '/download?format=txt';
    $('dl-srt').href = '/api/jobs/' + jobId + '/download?format=srt';
    show('result', true);
    setProgress('done', 100, 'done');
    if (scroll) $('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const highlight = (q) => {
    const text = state.transcript;
    const box = $('transcript');
    const query = q.trim();
    if (!query) { box.textContent = text; $('match-count').textContent = ''; return; }
    let n = 0;
    box.innerHTML = escapeHtml(text).replace(new RegExp(escapeRe(escapeHtml(query)), 'gi'), (m) => { n++; return '<mark>' + m + '</mark>'; });
    $('match-count').textContent = t('result.matches', { n });
  };
  $('search').addEventListener('input', (e) => highlight(e.target.value));
  $('clear-search').addEventListener('click', () => { $('search').value = ''; highlight(''); });

  $('copy').addEventListener('click', async () => {
    if (!state.transcript) return;
    try {
      await navigator.clipboard.writeText(state.transcript);
      $('copy').textContent = t('result.copied');
      setTimeout(() => { $('copy').textContent = t('result.copy'); }, 1400);
    } catch {
      showError({ code: 'copy' });
    }
  });

  // ---------------------------------------------------------------- historial
  const renderHistory = () => {
    const box = $('history');
    if (!state.history.length) {
      box.innerHTML = `<div class="history-empty">${escapeHtml(t('side.history.empty'))}</div>`;
      return;
    }
    box.innerHTML = state.history.map((j) => {
      const cls = j.status === 'done' ? 'done' : j.status === 'error' ? 'error' : 'running';
      const right = j.status === 'done' ? (j.language || 'OK') : j.status === 'error' ? 'ERROR' : Math.round(j.progress || 0) + '%';
      return `<div class="history-item" data-id="${escapeHtml(j.job_id)}" tabindex="0">
        <div class="h-title">${escapeHtml(j.title || j.video_id || t('untitled'))}</div>
        <div class="h-meta">
          <span class="h-status ${cls}"></span>
          <span>${escapeHtml((j.platform || '').toUpperCase())}</span><span>·</span>
          <span>${escapeHtml((j.model || '').toUpperCase())}</span><span>·</span>
          <span>${escapeHtml(String(right).toUpperCase())}</span><span>·</span>
          <span>${escapeHtml(fmtAgo(j.finished_at || j.created_at))}</span>
        </div>
      </div>`;
    }).join('');
    box.querySelectorAll('.history-item').forEach((el) => {
      const open = () => openJob(el.dataset.id, true);
      el.addEventListener('click', open);
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    });
  };
  const refreshHistory = async () => {
    try {
      const r = await api('/api/jobs');
      setOnline(true);
      if (r.ok) { state.history = r.data.jobs || []; renderHistory(); }
    } catch {
      setOnline(false);
    }
  };
  const setOnline = (on) => {
    state.online = on;
    $('status').classList.toggle('off', !on);
    const label = $('status').querySelector('[data-i18n]');
    label.dataset.i18n = on ? 'nav.online' : 'nav.offline';
    label.textContent = t(label.dataset.i18n);
  };

  const openJob = async (id, scroll) => {
    let r;
    try { r = await api('/api/jobs/' + id); } catch { return; }
    if (!r.ok) return;
    const j = r.data;
    history.replaceState(null, '', '#' + id);
    clearError();
    if (j.status === 'done') {
      renderResult(id, j, scroll);
    } else if (j.status === 'running' || j.status === 'queued') {
      busy(true);
      startElapsed(j.created_at);
      poll(id);
    } else if (j.status === 'error') {
      showError({ code: j.error_code, message: j.error || j.message });
    }
  };

  // ---------------------------------------------------------------- info
  const renderAbout = () => {
    const a = state.about;
    if (!a) return;
    const vars = { v: a.version, d: a.updated_at };
    $('utility-meta').textContent = t('util.meta', vars);
    $('footer-meta').textContent = t('footer.meta', vars);
    $('release-meta').textContent = t('side.release.meta', vars);
    const changes = (a.changes && (a.changes[state.lang] || a.changes.es)) || [];
    $('changes').innerHTML = changes.map((c) => `<li>${escapeHtml(c)}</li>`).join('');
  };
  const renderSystem = () => {
    const s = state.system;
    if (!s) return;
    $('sys-cpu').textContent = s.cpu_threads;
    $('sys-mem').textContent = s.memory_gb != null ? s.memory_gb + ' GB' : '--';
    $('sys-gpu').textContent = s.gpu_count > 0 ? '× ' + s.gpu_count : t('side.gpu.none');
    $('sys-model').textContent = t('model.' + s.recommended_model);
    renderHints();
  };

  const init = async () => {
    applyI18n();
    const [about, models, system] = await Promise.allSettled([
      api('/api/about'), api('/api/models'), api('/api/system'),
    ]);
    if (about.status === 'fulfilled' && about.value.ok) state.about = about.value.data;
    if (models.status === 'fulfilled' && models.value.ok) state.models = models.value.data.models || [];
    if (system.status === 'fulfilled' && system.value.ok) {
      state.system = system.value.data;
      state.recommended = state.system.recommended_model;
    }
    if (state.model && !UI_MODELS.includes(state.model)) state.model = '';
    renderModels();
    renderAbout();
    renderSystem();
    await refreshHistory();
    setInterval(refreshHistory, 5000);
    const id = location.hash.slice(1);
    if (id) openJob(id, false);
  };

  // ---------------------------------------------------------------- teclado
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      if (!$('submit').disabled) $('form').requestSubmit();
    }
    if (e.key === 'Escape' && document.activeElement === $('search')) {
      $('search').value = '';
      highlight('');
    }
  });

  init();
})();
