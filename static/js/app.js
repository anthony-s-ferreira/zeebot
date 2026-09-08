/* =========================================================================
   Zee Assistant — frontend (JavaScript ES6, sem frameworks)

   O backend é a fonte da verdade do estado.  A tela reage a eventos SSE
   (/api/events) e, quando o usuário toca em algo, informa o backend via
   POST /api/navigation — é isso que liga/desliga a wakeword.
   ========================================================================= */
(() => {
  'use strict';

  const CFG = window.ZEE_CONFIG || { texts: {} };
  const TEXTS = CFG.texts || {};

  const $ = (sel) => document.querySelector(sel);
  const el = {
    body: document.body,
    splash: $('#splash'),
    views: {
      wifi: $('#view-wifi'),
      home: $('#view-home'),
      menu: $('#view-menu'),
      list: $('#view-list'),
      resource: $('#view-resource'),
    },
    hint: $('#home-hint'),
    transcript: $('#home-transcript'),
    answer: $('#home-answer'),
    zeeStatic: $('#zee-static'),
    zeeMotion: $('#zee-motion'),
    principalButton: $('#btn-principal'),
    listBackButton: $('#btn-list-back'),
    micIndicator: $('#mic-indicator'),
    micIndicatorLabel: $('#mic-indicator-label'),
    badgeMic: $('#badge-mic'),
    badgeMicText: $('#badge-mic-text'),
    badgeRecognizer: $('#badge-recognizer'),
    badgeRecognizerText: $('#badge-recognizer-text'),
    badgeNet: $('#badge-net'),
    listTitle: $('#list-title'),
    listSubtitle: $('#list-subtitle'),
    listCards: $('#list-cards'),
    listEmpty: $('#list-empty'),
    resourceTitle: $('#resource-title'),
    resourceStage: $('#resource-stage'),
    resourceHelp: $('#resource-help'),
    resourceHelpText: $('#resource-help-text'),
    overlay: $('#overlay'),
    overlayText: $('#overlay-text'),
    overlayEmoji: $('#overlay-emoji'),
    wifiSsid: $('#wifi-ssid'),
    wifiSsidAlt: $('#wifi-ssid-alt'),
    wifiUrl: $('#wifi-url'),
    wifiStatus: $('#wifi-status'),
    wifiQr: $('#wifi-qr'),
    qrFallback: $('#qr-fallback'),
  };

  const TYPE_LABELS = { video: 'Vídeos', audio: 'Áudios', livro: 'Livros', jogo: 'Jogos' };
  const LOAD_HELP_DELAY = 8000;

  const store = {
    view: null,
    backend: null,
    thresholds: {},
    resourcesByType: new Map(),
    currentResource: null,
    currentKey: null,
    pendingKey: null,
    lastOptions: [],
    lastList: { tipo: null, mode: 'list', returnTo: 'menu' },
    overlayTimer: null,
    helpTimer: null,
    audio: null,
    sse: null,
    sseRetry: 0,
    pollTimer: null,
    wifiPollTimer: null,
    micActivityTimer: null,
  };

  /* ------------------------------------------------------------------ API */
  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) {
      const message = (payload && (payload.error || payload.message)) || `HTTP ${response.status}`;
      throw new Error(message);
    }
    return payload;
  }

  /* ---------------------------------------------------------------- views */
  function showView(name) {
    Object.entries(el.views).forEach(([key, node]) => {
      if (!node) return;
      node.hidden = key !== name;
    });
    if (store.view !== name) {
      store.view = name;
      el.body.dataset.view = name;
    }
    hideSplash();
  }

  function hideSplash() {
    if (el.splash && !el.splash.hidden) {
      el.splash.style.opacity = '0';
      setTimeout(() => { el.splash.hidden = true; }, 300);
    }
  }

  /** Navegação iniciada por toque: o backend decide e devolve o novo estado. */
  async function navigate(view, extra = {}) {
    try {
      await api('/api/navigation', { method: 'POST', body: { view, ...extra } });
    } catch (error) {
      console.error('[zee] navegação falhou:', error);
      showOverlay('Não consegui mudar de tela. Tentando de novo...', '⚠️', 3000);
    }
  }

  async function startWifiSetup() {
    try {
      await api('/api/wifi/setup', { method: 'POST', body: { action: 'start' } });
    } catch (error) {
      showOverlay(
        error.message || 'Não consegui iniciar a configuração do Wi-Fi. Verifique o adaptador e o NetworkManager.',
        '⚠️',
        7000
      );
    }
  }

  /* ------------------------------------------------------------- roteador */
  function applyBackendState(snapshot) {
    if (!snapshot) return;
    store.backend = snapshot;
    el.body.dataset.state = snapshot.state;
    syncZeeMedia(snapshot.state);
    if (snapshot.state !== 'WAITING_USER') setMicrophoneActivity(false);
    updateBadges(snapshot);
    updateHint(snapshot);

    const ctx = snapshot.context || {};
    if (el.principalButton) el.principalButton.hidden = snapshot.state !== 'ANSWERING';
    switch (snapshot.state) {
      case 'WIFI_SETUP':
        teardownResource();
        showView('wifi');
        startWifiStatusPolling();
        break;
      case 'MENU':
        teardownResource();
        showView('menu');
        refreshCounts();
        break;
      case 'RESOURCE_LIST':
        openList(ctx);
        break;
      case 'RESOURCE_VIEW':
        openResource(ctx.resource_id);
        break;
      case 'BOOTING':
        break;
      default: // HOME_LISTENING, WAKEWORD_DETECTED, WAITING_USER, PROCESSING_COMMAND, ERROR
        stopWifiStatusPolling();
        teardownResource();
        showView('home');
        break;
    }
  }

  const ZEE_MOTION_STATES = new Set([
    'WAKEWORD_DETECTED',
    'WAITING_USER',
    'PROCESSING_COMMAND',
    'ANSWERING',
  ]);

  /** Decodifica o MP4 apenas durante uma interação de voz visível. */
  function syncZeeMedia(state) {
    if (!el.zeeStatic || !el.zeeMotion) return;
    const animate = document.visibilityState !== 'hidden' && ZEE_MOTION_STATES.has(state);
    const wasAnimating = !el.zeeMotion.hidden;
    if (animate) {
      if (wasAnimating) return;
      el.zeeStatic.hidden = true;
      el.zeeMotion.hidden = false;
      el.zeeMotion.play().catch(() => {
        el.zeeMotion.hidden = true;
        el.zeeStatic.hidden = false;
      });
      return;
    }
    if (wasAnimating) {
      el.zeeMotion.pause();
      try { el.zeeMotion.currentTime = 0; } catch (_) { /* metadados ainda não carregados */ }
    }
    el.zeeMotion.hidden = true;
    el.zeeStatic.hidden = false;
  }

  function setMicrophoneActivity(active, level = 0) {
    if (!el.micIndicator) return;
    const isListening = el.body.dataset.state === 'WAITING_USER';
    const isSpeaking = Boolean(active) && isListening;
    el.micIndicator.classList.toggle('is-speaking', isSpeaking);
    el.micIndicator.style.setProperty('--mic-level', String(Math.max(0, Math.min(1, Number(level) || 0))));
    if (el.micIndicatorLabel) {
      el.micIndicatorLabel.textContent = isSpeaking ? 'Estou ouvindo você' : 'Microfone ligado';
    }
    if (store.micActivityTimer) {
      clearTimeout(store.micActivityTimer);
      store.micActivityTimer = null;
    }
    // Evita deixar o indicador aceso se um evento SSE se perder.
    if (isSpeaking) {
      store.micActivityTimer = window.setTimeout(() => setMicrophoneActivity(false), 700);
    }
  }

  function updateHint(snapshot) {
    if (!el.hint) return;
    const map = {
      HOME_LISTENING: TEXTS.idle || 'Diga "Oi, Zee"',
      WAKEWORD_DETECTED: TEXTS.listening || 'Oi! Estou ouvindo...',
      WAITING_USER: TEXTS.waiting || 'Aguardando usuário...',
      PROCESSING_COMMAND: TEXTS.processing || 'Procurando conteúdo...',
      ANSWERING: 'Resposta:',
      ERROR: (snapshot.context && snapshot.context.message) || TEXTS.notFound,
    };
    if (map[snapshot.state]) el.hint.textContent = map[snapshot.state];

    const mic = snapshot.microphone || {};
    const model = snapshot.voice_model || {};
    if (snapshot.state === 'HOME_LISTENING' && (!mic.available || !model.loaded)) {
      el.hint.textContent = 'Toque em MENU para explorar';
    }
    if (el.answer && snapshot.state === 'HOME_LISTENING') el.answer.hidden = true;
    if (snapshot.state !== 'PROCESSING_COMMAND' && snapshot.state !== 'ERROR' && el.transcript) {
      if (snapshot.state === 'HOME_LISTENING') el.transcript.textContent = '';
    }
  }

  function updateBadges(snapshot) {
    const mic = snapshot.microphone || {};
    const model = snapshot.voice_model || {};
    const micOk = mic.available && model.loaded;
    if (el.badgeMic) {
      el.badgeMic.hidden = micOk;
      if (!micOk && el.badgeMicText) {
        el.badgeMicText.textContent = !mic.available
          ? (TEXTS.noMic || 'Microfone indisponível')
          : 'Voz indisponível (modelo)';
      }
    }
    const recognizer = snapshot.speech_recognizer || {};
    if (el.badgeRecognizerText) {
      const label = recognizer.label || 'Inicializando...';
      const fallback = recognizer.fallback ? ' (fallback)' : '';
      el.badgeRecognizerText.textContent = `Modelo de voz: ${label}${fallback}`;
    }
    if (el.badgeRecognizer) {
      el.badgeRecognizer.classList.toggle('badge--warn', recognizer.available === false);
      el.badgeRecognizer.classList.toggle('badge--info', recognizer.available !== false);
    }
    const net = snapshot.network || {};
    if (el.badgeNet) el.badgeNet.hidden = Boolean(net.connected) || snapshot.state === 'WIFI_SETUP';
  }

  /* ------------------------------------------------------------- listagem */
  async function fetchResources(tipo) {
    const key = tipo || '__all__';
    if (store.resourcesByType.has(key)) return store.resourcesByType.get(key);
    const query = tipo ? `?tipo=${encodeURIComponent(tipo)}` : '';
    const payload = await api(`/api/resources${query}`);
    const items = (payload && payload.recursos) || [];
    store.resourcesByType.set(key, items);
    return items;
  }

  function invalidateResources() { store.resourcesByType.clear(); }

  async function openList(ctx = {}) {
    const mode = ctx.mode || 'list';
    const tipo = ctx.tipo || null;
    const returnTo = ctx.return_to === 'home' || ctx.source === 'voz' ? 'home' : 'menu';
    store.lastList = { tipo, mode, returnTo };
    teardownResource();
    showView('list');

    if (mode === 'options') {
      renderCards(store.lastOptions, {
        title: TEXTS.multiple || 'Encontrei mais de uma opção.',
        subtitle: 'Toque no conteúdo que você quer abrir.',
        showScore: true,
        emptyText: store.lastOptions.length ? null : 'Só um instante...',
      });
      return;
    }

    el.listTitle.textContent = TYPE_LABELS[tipo] || 'Conteúdos';
    el.listSubtitle.hidden = true;
    try {
      const items = await fetchResources(tipo);
      renderCards(items, { title: TYPE_LABELS[tipo] || 'Conteúdos' });
    } catch (error) {
      console.error('[zee] falha ao listar recursos:', error);
      renderCards([], { title: TYPE_LABELS[tipo] || 'Conteúdos' });
      el.listEmpty.textContent = 'Não consegui ler a lista de conteúdos.';
      el.listEmpty.hidden = false;
    }
  }

  function renderCards(items, { title, subtitle, showScore, emptyText } = {}) {
    if (title) el.listTitle.textContent = title;
    if (subtitle) {
      el.listSubtitle.textContent = subtitle;
      el.listSubtitle.hidden = false;
    } else {
      el.listSubtitle.hidden = true;
    }

    el.listCards.textContent = '';
    const list = items || [];
    el.listEmpty.hidden = list.length > 0;
    if (!list.length) {
      el.listEmpty.textContent = emptyText || 'Nenhum conteúdo cadastrado nesta categoria.';
      return;
    }

    const fragment = document.createDocumentFragment();
    list.forEach((item) => fragment.appendChild(buildCard(item, showScore)));
    el.listCards.appendChild(fragment);
  }

  function buildCard(item, showScore) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = `card card--${item.tipo}`;
    card.dataset.resourceId = item.id;

    const thumb = document.createElement('span');
    thumb.className = 'card__thumb';
    if (item.thumbnail) {
      const img = document.createElement('img');
      img.src = item.thumbnail;
      img.alt = '';
      img.loading = 'lazy';
      img.addEventListener('error', () => { thumb.textContent = ''; thumb.appendChild(buildIcon(item.tipo)); });
      thumb.appendChild(img);
    } else {
      thumb.appendChild(buildIcon(item.tipo));
    }

    const body = document.createElement('span');
    const title = document.createElement('h2');
    title.className = 'card__title';
    title.textContent = item.titulo;
    const desc = document.createElement('p');
    desc.className = 'card__desc';
    desc.textContent = item.descricao || '';
    body.appendChild(title);
    body.appendChild(desc);

    if (showScore && typeof item.score === 'number') {
      const score = document.createElement('span');
      score.className = 'card__score';
      score.textContent = `${Math.round(item.score)}%`;
      body.appendChild(score);
    }

    card.appendChild(thumb);
    card.appendChild(body);
    card.addEventListener('click', () => navigate('resource', {
      resource_id: item.id,
      return_to: store.lastList.returnTo,
    }));
    return card;
  }

  function buildIcon(tipo) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'card__icon');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#icon-${tipo}`);
    svg.appendChild(use);
    return svg;
  }

  async function refreshCounts() {
    try {
      const payload = await api('/api/resources');
      const counts = (payload && payload.counts) || {};
      document.querySelectorAll('[data-count]').forEach((node) => {
        const tipo = node.dataset.count;
        const total = counts[tipo] || 0;
        node.textContent = total === 1 ? '1 item' : `${total} itens`;
      });
      store.resourcesByType.set('__all__', (payload && payload.recursos) || []);
    } catch (error) {
      console.warn('[zee] não foi possível contar recursos:', error);
    }
  }

  /* -------------------------------------------------------------- conteúdo */
  async function openResource(resourceId) {
    if (!resourceId) return;
    if (store.currentKey === resourceId && store.view === 'resource') return;
    if (store.pendingKey === resourceId) return;   // state + action chegam juntos
    store.pendingKey = resourceId;

    let resource = null;
    try {
      resource = await api(`/api/resources/${encodeURIComponent(resourceId)}`);
    } catch (error) {
      console.error('[zee] recurso não encontrado:', error);
      store.pendingKey = null;
      showOverlay('Não encontrei esse conteúdo.', '🤔', 4000);
      navigate('home');
      return;
    } finally {
      store.pendingKey = null;
    }

    teardownResource();
    store.currentResource = resource;
    store.currentKey = resource.id;
    el.resourceTitle.textContent = resource.titulo;
    showView('resource');

    const renderer = RENDERERS[resource.tipo] || RENDERERS.default;
    renderer(resource);
  }

  /** Renderizadores por tipo — adicionar um tipo novo é adicionar uma chave. */
  const RENDERERS = {
    video: (resource) => renderFrame(resource, resource.embed_url || resource.url, {
      allow: 'autoplay; encrypted-media; picture-in-picture; fullscreen',
    }),
    livro: (resource) => renderFrame(resource, resource.url, {
      allow: 'fullscreen',
      helpText: 'O PDF não abriu?',
    }),
    jogo: (resource) => renderFrame(resource, resource.url, {
      allow: 'autoplay; fullscreen; gamepad',
      sandbox: 'allow-scripts allow-same-origin allow-forms allow-popups',
      helpText: 'O jogo não abriu? Alguns sites bloqueiam a exibição aqui dentro.',
    }),
    audio: (resource) => renderAudio(resource),
    default: (resource) => renderError(
      'Tipo de conteúdo não suportado',
      `Ainda não sei abrir conteúdos do tipo "${resource.tipo}".`
    ),
  };

  function isRemote(url) { return /^https?:\/\//i.test(url || ''); }

  function renderFrame(resource, url, options = {}) {
    if (!url) {
      renderError('Conteúdo indisponível', 'Este item está sem endereço cadastrado.');
      return;
    }
    if (isRemote(url) && navigator.onLine === false) {
      renderError(
        'Sem internet',
        'Não foi possível carregar este conteúdo. Verifique sua conexão com a internet.'
      );
      return;
    }

    const iframe = document.createElement('iframe');
    iframe.src = url;
    iframe.title = resource.titulo;
    iframe.referrerPolicy = 'no-referrer-when-downgrade';
    iframe.setAttribute('allow', options.allow || 'fullscreen');
    iframe.setAttribute('allowfullscreen', '');
    if (options.sandbox) iframe.setAttribute('sandbox', options.sandbox);
    iframe.addEventListener('load', () => { /* carregou algo — a ajuda continua disponível */ });
    el.resourceStage.appendChild(iframe);

    // X-Frame-Options / CSP não geram evento de erro: oferecemos ajuda após um tempo.
    el.resourceHelpText.textContent = options.helpText || 'Está demorando para carregar?';
    store.helpTimer = window.setTimeout(() => { el.resourceHelp.hidden = false; }, LOAD_HELP_DELAY);
  }

  function renderAudio(resource) {
    if (isRemote(resource.url) && navigator.onLine === false) {
      renderError(
        'Sem internet',
        'Não foi possível carregar este áudio. Verifique sua conexão com a internet.'
      );
      return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'audio-player';
    wrapper.innerHTML = `
      <div class="audio-player__art"><svg><use href="#icon-audio"></use></svg></div>
      <h2 class="audio-player__title"></h2>
      <p class="audio-player__desc"></p>
      <div class="audio-controls">
        <button type="button" class="audio-btn" data-role="play" aria-label="Reproduzir">▶</button>
        <span class="audio-time" data-role="current">0:00</span>
        <input type="range" data-role="seek" min="0" max="1000" value="0" step="1" aria-label="Progresso">
        <span class="audio-time" data-role="duration">--:--</span>
      </div>
      <div class="audio-volume">
        <span>🔈</span>
        <input type="range" data-role="volume" min="0" max="100" value="85" aria-label="Volume">
        <span>🔊</span>
      </div>
    `;
    wrapper.querySelector('.audio-player__title').textContent = resource.titulo;
    wrapper.querySelector('.audio-player__desc').textContent = resource.descricao || '';
    el.resourceStage.appendChild(wrapper);

    const audio = new Audio();
    audio.preload = 'metadata';
    audio.src = resource.url;
    audio.volume = 0.85;
    store.audio = audio;

    const playBtn = wrapper.querySelector('[data-role="play"]');
    const seek = wrapper.querySelector('[data-role="seek"]');
    const current = wrapper.querySelector('[data-role="current"]');
    const duration = wrapper.querySelector('[data-role="duration"]');
    const volume = wrapper.querySelector('[data-role="volume"]');
    let seeking = false;

    const fmt = (seconds) => {
      if (!isFinite(seconds) || seconds < 0) return '--:--';
      const m = Math.floor(seconds / 60);
      const s = Math.floor(seconds % 60);
      return `${m}:${String(s).padStart(2, '0')}`;
    };

    playBtn.addEventListener('click', () => {
      if (audio.paused) {
        audio.play().catch((error) => {
          console.error('[zee] falha ao reproduzir áudio:', error);
          renderError('Não consegui tocar este áudio',
            'Verifique sua conexão com a internet ou o endereço do arquivo.');
        });
      } else {
        audio.pause();
      }
    });
    audio.addEventListener('play', () => { playBtn.textContent = '❚❚'; wrapper.classList.add('is-playing'); });
    audio.addEventListener('pause', () => { playBtn.textContent = '▶'; wrapper.classList.remove('is-playing'); });
    audio.addEventListener('ended', () => { playBtn.textContent = '▶'; wrapper.classList.remove('is-playing'); });
    audio.addEventListener('loadedmetadata', () => { duration.textContent = fmt(audio.duration); });
    audio.addEventListener('timeupdate', () => {
      current.textContent = fmt(audio.currentTime);
      if (!seeking && audio.duration) seek.value = String((audio.currentTime / audio.duration) * 1000);
    });
    audio.addEventListener('error', () => {
      renderError('Não foi possível carregar este áudio',
        'Verifique sua conexão com a internet e tente novamente.');
    });
    seek.addEventListener('input', () => { seeking = true; });
    seek.addEventListener('change', () => {
      if (audio.duration) audio.currentTime = (Number(seek.value) / 1000) * audio.duration;
      seeking = false;
    });
    volume.addEventListener('input', () => { audio.volume = Number(volume.value) / 100; });

    audio.play().catch(() => { /* autoplay pode ser bloqueado: o botão resolve */ });
  }

  function renderError(title, message) {
    teardownStage();
    const box = document.createElement('div');
    box.className = 'resource-error';
    const heading = document.createElement('h2');
    heading.textContent = title;
    const text = document.createElement('p');
    text.textContent = message;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn--small';
    button.textContent = 'VOLTAR';
    button.addEventListener('click', goBackFromResource);
    box.appendChild(heading);
    box.appendChild(text);
    box.appendChild(button);
    el.resourceStage.appendChild(box);
  }

  function teardownStage() {
    if (store.audio) {
      try { store.audio.pause(); store.audio.src = ''; store.audio.load(); } catch (_) { /* noop */ }
      store.audio = null;
    }
    // Destruir o iframe libera memória e para o vídeo/jogo imediatamente.
    el.resourceStage.textContent = '';
  }

  function teardownResource() {
    if (store.helpTimer) { clearTimeout(store.helpTimer); store.helpTimer = null; }
    el.resourceHelp.hidden = true;
    teardownStage();
    store.currentResource = null;
    store.currentKey = null;
  }

  function goBackFromResource() {
    if (store.lastList && (store.lastList.tipo || store.lastList.mode === 'options')) {
      navigate('list', {
        tipo: store.lastList.tipo,
        mode: store.lastList.mode,
        return_to: store.lastList.returnTo,
      });
    } else {
      navigate('menu');
    }
  }

  /* -------------------------------------------------------------- overlay */
  function showOverlay(message, emoji = '🐝', autoHideMs = 0) {
    if (store.overlayTimer) { clearTimeout(store.overlayTimer); store.overlayTimer = null; }
    el.overlayText.textContent = message;
    el.overlayEmoji.textContent = emoji;
    el.overlay.hidden = false;
    if (autoHideMs > 0) {
      store.overlayTimer = window.setTimeout(hideOverlay, autoHideMs);
    }
  }
  function hideOverlay() {
    el.overlay.hidden = true;
    if (store.overlayTimer) { clearTimeout(store.overlayTimer); store.overlayTimer = null; }
  }

  /* ----------------------------------------------------------------- wifi */
  function applyWifiInfo(info) {
    if (!info) return;
    if (info.ap_ssid) {
      el.wifiSsid.textContent = info.ap_ssid;
      el.wifiSsidAlt.textContent = info.ap_ssid;
    }
    if (info.portal_url) el.wifiUrl.textContent = info.portal_url;
    if (info.qr_payload) {
      const src = `/api/wifi/qrcode.svg?payload=${encodeURIComponent(info.qr_payload)}`;
      if (el.wifiQr.getAttribute('src') !== src) el.wifiQr.setAttribute('src', src);
    }

    const status = info.status || 'idle';
    const classes = { starting: 'is-busy', connecting: 'is-busy', connected: 'is-ok', failed: 'is-error', ap_failed: 'is-error' };
    el.wifiStatus.className = `wifi-status ${classes[status] || ''}`.trim();
    if (status === 'starting') {
      el.wifiStatus.textContent = 'Iniciando a rede de configuração...';
    } else if (status === 'connecting') {
      el.wifiStatus.textContent = `Conectando a ${info.ssid || 'rede'}...`;
    } else if (status === 'connected') {
      el.wifiStatus.textContent = 'Conectado!';
    } else if (status === 'failed') {
      el.wifiStatus.textContent = info.message || 'Não foi possível conectar. Tente novamente.';
    } else if (status === 'ap_failed') {
      el.wifiStatus.textContent = 'Não consegui criar a rede de configuração. Verifique o Wi-Fi do Raspberry Pi.';
    } else {
      el.wifiStatus.textContent = '';
    }
  }

  function startWifiStatusPolling() {
    if (store.wifiPollTimer) return;
    const poll = async () => {
      try {
        const result = await api('/api/wifi/status');
        applyWifiInfo(result.setup);
      } catch (_) { /* a troca de rede pode interromper uma consulta */ }
    };
    poll();
    store.wifiPollTimer = window.setInterval(poll, 2000);
  }

  function stopWifiStatusPolling() {
    if (store.wifiPollTimer) {
      clearInterval(store.wifiPollTimer);
      store.wifiPollTimer = null;
    }
  }

  /* ---------------------------------------------------------------- ações */
  function handleAction(data) {
    if (!data || !data.action) return;
    switch (data.action) {
      case 'open_resource':
        hideOverlay();
        openResource(data.resource_id);
        break;
      case 'show_options':
        store.lastOptions = (data.match && data.match.candidates) || [];
        openList({ mode: 'options', source: 'voz', return_to: 'home' });
        break;
      case 'open_list':
        invalidateResources();
        openList({ tipo: data.tipo, mode: 'list', source: 'voz', return_to: 'home' });
        break;
      case 'open_menu':
        hideOverlay();
        teardownResource();
        showView('menu');
        refreshCounts();
        break;
      case 'not_found': {
        const seconds = Number(store.thresholds.error_auto_return_seconds || 5);
        showOverlay(data.message || TEXTS.notFound, '🤔', seconds * 1000);
        break;
      }
      case 'show_answer':
        hideOverlay();
        showView('home');
        if (el.answer) {
          el.answer.textContent = data.answer || 'Não consegui responder agora.';
          el.answer.hidden = false;
        }
        break;
      case 'go_home':
        hideOverlay();
        break;
      default:
        console.debug('[zee] ação desconhecida:', data.action);
    }
  }

  /* ------------------------------------------------------------------ SSE */
  function connectEvents() {
    if (store.sse) { store.sse.close(); store.sse = null; }
    const source = new EventSource('/api/events');
    store.sse = source;

    source.addEventListener('open', () => {
      store.sseRetry = 0;
      stopPolling();
      console.info('[zee] conectado ao fluxo de eventos');
    });
    source.addEventListener('state', (event) => {
      const payload = safeParse(event.data);
      if (payload) applyBackendState(payload.data || payload);
    });
    source.addEventListener('capabilities', (event) => {
      const payload = safeParse(event.data);
      if (payload) applyBackendState(payload.data || payload);
    });
    source.addEventListener('network', (event) => {
      const payload = safeParse(event.data);
      const net = payload && payload.data && payload.data.network;
      if (net && el.badgeNet) el.badgeNet.hidden = Boolean(net.connected);
    });
    source.addEventListener('action', (event) => {
      const payload = safeParse(event.data);
      if (payload) handleAction(payload.data || payload);
    });
    source.addEventListener('wifi', (event) => {
      const payload = safeParse(event.data);
      if (payload) applyWifiInfo(payload.data || payload);
    });
    source.addEventListener('transcript', (event) => {
      const payload = safeParse(event.data);
      const text = payload && payload.data && payload.data.text;
      if (el.transcript) el.transcript.textContent = text ? `"${text}"` : '';
    });
    source.addEventListener('microphone_activity', (event) => {
      const payload = safeParse(event.data);
      const activity = payload && (payload.data || payload);
      if (activity) setMicrophoneActivity(activity.active, activity.level);
    });
    source.addEventListener('resources', () => invalidateResources());
    source.addEventListener('error', () => {
      // O EventSource reconecta sozinho; o polling cobre falhas longas.
      store.sseRetry += 1;
      if (store.sseRetry >= 2) startPolling();
    });
  }

  function safeParse(raw) {
    try { return JSON.parse(raw); } catch (error) { return null; }
  }

  function startPolling() {
    if (store.pollTimer) return;
    console.warn('[zee] SSE instável — usando polling de estado');
    store.pollTimer = window.setInterval(async () => {
      try {
        const status = await api('/api/status');
        store.thresholds = status.thresholds || store.thresholds;
        applyBackendState({
          state: status.state,
          context: status.context,
          microphone: status.microphone,
          voice_model: status.voice_model,
          speech_recognizer: status.speech_recognizer,
          network: status.network,
        });
      } catch (error) { /* segue tentando */ }
    }, 3000);
  }
  function stopPolling() {
    if (store.pollTimer) { clearInterval(store.pollTimer); store.pollTimer = null; }
  }

  /* ------------------------------------------------------------- eventos UI */
  function bindUI() {
    $('#btn-menu').addEventListener('click', () => navigate('menu'));
    $('#btn-principal').addEventListener('click', () => navigate('home'));
    $('#btn-list-back').addEventListener('click', () => navigate(store.lastList.returnTo));

    document.querySelectorAll('.menu-card').forEach((card) => {
      card.addEventListener('click', () => {
        if (card.id === 'btn-wifi-setup') {
          startWifiSetup();
          return;
        }
        invalidateResources();
        navigate('list', { tipo: card.dataset.tipo });
      });
    });

    document.querySelectorAll('[data-back]').forEach((button) => {
      button.addEventListener('click', () => {
        const target = button.dataset.back;
        if (target === 'list') goBackFromResource();
        else navigate(target);
      });
    });

    $('#btn-resource-back').addEventListener('click', goBackFromResource);
    $('#btn-resource-retry').addEventListener('click', () => {
      const resource = store.currentResource;
      if (!resource) return;
      store.currentKey = null;
      teardownResource();
      openResource(resource.id);
    });
    $('#overlay-close').addEventListener('click', hideOverlay);

    window.addEventListener('online', () => { if (el.badgeNet) el.badgeNet.hidden = true; });
    window.addEventListener('offline', () => { if (el.badgeNet) el.badgeNet.hidden = false; });
    document.addEventListener('visibilitychange', () => {
      syncZeeMedia(store.backend && store.backend.state);
    });

    // Teclas de apoio durante o desenvolvimento/teste.
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') navigate('home');
    });

    // O QR Code depende da lib qrcode; se falhar, mostramos as instruções.
    el.wifiQr.addEventListener('error', () => {
      el.wifiQr.hidden = true;
      el.qrFallback.hidden = false;
    });
    el.wifiQr.addEventListener('load', () => {
      el.wifiQr.hidden = false;
      el.qrFallback.hidden = true;
    });
  }

  async function bootstrap() {
    bindUI();
    try {
      const status = await api('/api/status');
      store.thresholds = status.thresholds || {};
      applyBackendState({
        state: status.state,
        context: status.context,
        microphone: status.microphone,
        voice_model: status.voice_model,
        speech_recognizer: status.speech_recognizer,
        network: status.network,
      });
      refreshCounts();
    } catch (error) {
      console.error('[zee] backend indisponível na inicialização:', error);
      hideSplash();
      showView('home');
    }
    try {
      const wifi = await api('/api/wifi/status');
      applyWifiInfo(wifi.setup);
    } catch (error) { /* opcional */ }
    connectEvents();
  }

  document.addEventListener('DOMContentLoaded', bootstrap);
})();
