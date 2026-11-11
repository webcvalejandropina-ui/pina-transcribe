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

  const MAIN_MODELS = ['tiny', 'base', 'small', 'medium', 'large-v3'];
  const MODEL_INFO = {
    tiny: { es: 'Ultrarrápido', en: 'Ultra fast' },
    base: { es: 'Rápido', en: 'Fast' },
    small: { es: 'Equilibrado', en: 'Balanced' },
    medium: { es: 'Preciso', en: 'Accurate' },
    'large-v3': { es: 'Máxima calidad', en: 'Best quality' },
  };
  const PHASES = ['init', 'download', 'transcribe', 'save', 'done'];

  const state = {
    lang: root.lang === 'en' ? 'en' : 'es',
    platform: 'youtube',
    device: 'auto',
    model: store.get('pina.model') || '',
    models: [],
    recommended: '',
    about: null,
    pollTimer: null,
    elapsedTimer: null,
    startedAt: 0,
    transcript: '',
    lastResult: null,
    lastError: null,
    lastProgress: null,
    history: [],
  };

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
    updateThemeLabel();
    renderModels();
    renderAbout();
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
    updateThemeLabel();
  };
  const updateThemeLabel = () => { $('theme-label').textContent = t('nav.theme.' + root.dataset.themePref); };
  $('theme-btn').addEventListener('click', () => {
    const order = ['auto', 'light', 'dark'];
    const next = order[(order.indexOf(root.dataset.themePref) + 1) % order.length];
    store.set('pina.theme', next);
    applyTheme(next);
  });
  media.addEventListener('change', () => { if (root.dataset.themePref === 'auto') applyTheme('auto'); });

  // ---------------------------------------------------------------- utilidades
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
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

  // ---------------------------------------------------------------- segmentados
  const bindSegmented = (id, onChange) => {
    const group = $(id);
    group.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      setSegmented(id, b.dataset.value);
      onChange(b.dataset.value);
    }));
  };
  const setSegmented = (id, value) => {
    $(id).querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.value === value)));
  };
  bindSegmented('platform', (v) => { state.platform = v; });
  bindSegmented('device', (v) => { state.device = v; });

  // ---------------------------------------------------------------- modelos
  // Sin preferencia guardada, se usa el modelo recomendado para este equipo.
  const currentModel = () => state.model || state.recommended || 'base';
  const renderModels = () => {
    const box = $('models');
    const list = state.models.length ? state.models.filter((m) => MAIN_MODELS.includes(m)) : MAIN_MODELS;
    const selected = currentModel();
    box.innerHTML = list.map((m) => `
      <button type="button" class="chip" role="radio" data-model="${m}" aria-checked="${m === selected}">
        ${m === state.recommended ? `<span class="rec">${escapeHtml(t('form.recommended'))}</span>` : ''}
        <b>${m}</b><small>${escapeHtml((MODEL_INFO[m] || {})[state.lang] || '')}</small>
      </button>`).join('');
    box.querySelectorAll('.chip').forEach((c) => c.addEventListener('click', () => {
      state.model = c.dataset.model;
      store.set('pina.model', state.model);
      renderModels();
    }));
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
    const badge = $('detected');
    if (d) {
      badge.hidden = false;
      badge.textContent = (d.platform === 'youtube' ? 'YouTube' : 'Twitch') + ' · ' + d.id;
      state.platform = d.platform;
      setSegmented('platform', d.platform);
    } else {
      badge.hidden = true;
    }
  };
  $('source').addEventListener('input', onSourceInput);

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
    $(id).classList.toggle('invalid', Number.isNaN(parseTime($(id).value)));
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
    $('progress').hidden = false;
    const idx = Math.max(0, PHASES.indexOf(phase));
    document.querySelectorAll('#steps li').forEach((li, i) => {
      li.classList.toggle('done', i < idx || phase === 'done');
      li.classList.toggle('active', i === idx && phase !== 'done');
    });
    const p = Math.round(pct || 0);
    $('bar-fill').style.width = p + '%';
    $('bar').setAttribute('aria-valuenow', String(p));
    $('bar-pct').textContent = p + '%';
    $('bar-msg').textContent = msgKey ? t('msg.' + msgKey) : t('progress.waiting');
  };
  const resetProgress = () => {
    state.lastProgress = null;
    $('progress').hidden = true;
    $('bar-fill').style.width = '0';
    $('elapsed').textContent = '00:00';
    document.querySelectorAll('#steps li').forEach((li) => li.classList.remove('done', 'active'));
  };

  const showError = (err) => {
    state.lastError = err;
    const code = err && err.code;
    const known = code && DICT.es['err.' + code];
    $('error-msg').textContent = known ? t('err.' + code) : (err && err.message) || t('err.unexpected');
    $('error').hidden = false;
  };
  const clearError = () => { state.lastError = null; $('error').hidden = true; };
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
      $('advanced').open = true;
      showError({ code: 'invalid_time' });
      return;
    }
    const d = detect(raw);
    if (d) { state.platform = d.platform; setSegmented('platform', d.platform); }

    clearError();
    $('result').hidden = true;
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
    state.pollTimer = setInterval(once, 700);
  };

  $('form').addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  $('reset').addEventListener('click', () => {
    ['source', 'start', 'end', 'search'].forEach((id) => { $(id).value = ''; $(id).classList.remove('invalid'); });
    $('lang').value = '';
    onSourceInput();
    clearError();
    resetProgress();
    $('result').hidden = true;
    state.lastResult = null;
    history.replaceState(null, '', location.pathname + location.search);
    $('source').focus();
  });

  // ---------------------------------------------------------------- resultado
  const renderResult = (jobId, job, scroll) => {
    state.lastResult = { id: jobId, job };
    const r = job.result || {};
    $('r-title').textContent = r.title || t('result.title');
    const words = (r.text || '').split(/\s+/).filter(Boolean).length;
    const tags = [];
    if (r.platform) tags.push(`<span class="tag"><b>${r.platform === 'youtube' ? 'YouTube' : 'Twitch'}</b></span>`);
    if (r.language) tags.push(`<span class="tag">${escapeHtml(t('result.lang'))} <b>${escapeHtml(r.language)}</b></span>`);
    if (r.model) tags.push(`<span class="tag">${escapeHtml(t('result.model'))} <b>${escapeHtml(r.model)}</b></span>`);
    if (r.device) tags.push(`<span class="tag">${escapeHtml(t('result.device'))} <b>${escapeHtml(r.device.toUpperCase())}</b></span>`);
    if (r.start_seconds != null || r.end_seconds != null) {
      const a = fmtClock(r.start_seconds || 0);
      const b = r.end_seconds != null ? fmtClock(r.end_seconds) : '…';
      tags.push(`<span class="tag">${escapeHtml(t('result.range'))} <b>${a} – ${b}</b></span>`);
    }
    tags.push(`<span class="tag">${escapeHtml(t('result.words', { n: words.toLocaleString(state.lang) }))}</span>`);
    if (r.url && /^https:\/\/(www\.)?(youtube\.com|twitch\.tv)\//.test(r.url)) {
      tags.push(`<a class="tag" href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t('result.source'))} ↗</a>`);
    }
    $('r-tags').innerHTML = tags.join('');
    state.transcript = r.text || '';
    highlight($('search').value);
    $('dl-txt').href = '/api/jobs/' + jobId + '/download?format=txt';
    $('dl-srt').href = '/api/jobs/' + jobId + '/download?format=srt';
    $('result').hidden = false;
    setProgress('done', 100, 'done');
    if (scroll) $('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const highlight = (q) => {
    const text = state.transcript;
    const box = $('transcript');
    const query = q.trim();
    if (!query) { box.textContent = text; $('match-count').textContent = ''; return; }
    const re = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    let n = 0;
    box.innerHTML = escapeHtml(text).replace(new RegExp(escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), (m) => { n++; return '<mark>' + m + '</mark>'; });
    void re;
    $('match-count').textContent = t('result.matches', { n });
    const first = box.querySelector('mark');
    if (first) first.scrollIntoView({ block: 'nearest' });
  };
  $('search').addEventListener('input', (e) => highlight(e.target.value));

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
      box.innerHTML = `<li class="empty">${escapeHtml(t('side.history.empty'))}</li>`;
      return;
    }
    box.innerHTML = state.history.map((j) => {
      const cls = j.status === 'done' ? 'done' : j.status === 'error' ? 'error' : 'running';
      const right = j.status === 'done' ? (j.language || 'ok') : j.status === 'error' ? 'error' : Math.round(j.progress || 0) + '%';
      return `<li data-id="${escapeHtml(j.job_id)}" tabindex="0">
        <div class="h-title">${escapeHtml(j.title || j.video_id || t('untitled'))}</div>
        <div class="h-meta"><span class="h-dot ${cls}"></span>
          <span>${escapeHtml(j.platform || '')}</span>·<span>${escapeHtml(j.model || '')}</span>·<span>${escapeHtml(right)}</span>·<span>${escapeHtml(fmtAgo(j.finished_at || j.created_at))}</span>
        </div></li>`;
    }).join('');
    box.querySelectorAll('li[data-id]').forEach((li) => {
      const open = () => openJob(li.dataset.id, true);
      li.addEventListener('click', open);
      li.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
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
    $('version').textContent = 'v' + a.version;
    $('footer-version').textContent = 'v' + a.version;
    $('release-meta').textContent = 'v' + a.version + ' · ' + a.updated_at;
    const changes = (a.changes && (a.changes[state.lang] || a.changes.es)) || [];
    $('changes').innerHTML = changes.map((c) => `<li>${escapeHtml(c)}</li>`).join('');
  };
  const renderSystem = (s) => {
    $('sys-cpu').textContent = s.cpu_threads;
    $('sys-mem').textContent = s.memory_gb != null ? s.memory_gb + ' GB' : '—';
    const gpuEl = $('sys-gpu');
    gpuEl.dataset.i18n = s.gpu_count > 0 ? '' : 'side.gpu.none';
    gpuEl.textContent = s.gpu_count > 0 ? '× ' + s.gpu_count : t('side.gpu.none');
    if (!gpuEl.dataset.i18n) delete gpuEl.dataset.i18n;
    $('sys-model').textContent = s.recommended_model;
  };

  const init = async () => {
    applyI18n();
    const [about, models, system] = await Promise.allSettled([
      api('/api/about'), api('/api/models'), api('/api/system'),
    ]);
    if (about.status === 'fulfilled' && about.value.ok) state.about = about.value.data;
    if (models.status === 'fulfilled' && models.value.ok) state.models = models.value.data.models || [];
    if (system.status === 'fulfilled' && system.value.ok) {
      state.recommended = system.value.data.recommended_model;
      renderSystem(system.value.data);
    }
    if (state.model && state.models.length && !MAIN_MODELS.includes(state.model)) state.model = '';
    renderModels();
    renderAbout();
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
