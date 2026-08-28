/* Captive portal do Zee — seleção de rede e envio da senha.
   A senha só existe em memória e no corpo da requisição: nada de log. */
(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const ui = {
    networks: $('#networks'),
    refresh: $('#btn-refresh'),
    other: $('#btn-other'),
    panelNetworks: $('#panel-networks'),
    panelConnect: $('#panel-connect'),
    panelStatus: $('#panel-status'),
    selectedTitle: $('#selected-title'),
    fieldSsid: $('#field-ssid'),
    fieldPassword: $('#field-password'),
    inputSsid: $('#input-ssid'),
    inputPassword: $('#input-password'),
    togglePassword: $('#btn-toggle-password'),
    form: $('#form-connect'),
    connect: $('#btn-connect'),
    cancel: $('#btn-cancel'),
    spinner: $('#spinner'),
    statusTitle: $('#status-title'),
    statusText: $('#status-text'),
    statusNote: $('#status-note'),
    retry: $('#btn-retry'),
  };

  let selected = null;      // { ssid, secured }
  let pollTimer = null;
  let pollMisses = 0;

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      ...options,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    return { ok: response.ok, status: response.status, payload };
  }

  function signalBars(signal) {
    const level = signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1;
    const bars = document.createElement('span');
    bars.className = 'bars';
    for (let i = 1; i <= 4; i += 1) {
      const bar = document.createElement('i');
      if (i <= level) bar.classList.add('on');
      bars.appendChild(bar);
    }
    return bars;
  }

  async function loadNetworks() {
    ui.networks.innerHTML = '<li class="loading">Procurando redes...</li>';
    const { ok, payload } = await api('/api/networks');
    const list = (ok && payload && payload.networks) || [];
    ui.networks.innerHTML = '';

    if (!list.length) {
      const item = document.createElement('li');
      item.className = 'empty';
      item.textContent = 'Nenhuma rede encontrada. Toque em "Atualizar".';
      ui.networks.appendChild(item);
      return;
    }

    list.forEach((network) => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'network';

      const name = document.createElement('span');
      name.className = 'network__name';
      name.textContent = network.ssid;

      const meta = document.createElement('span');
      meta.className = 'network__meta';
      meta.appendChild(document.createTextNode(network.secured ? '🔒' : '🔓'));
      meta.appendChild(signalBars(Number(network.signal) || 0));

      button.appendChild(name);
      button.appendChild(meta);
      button.addEventListener('click', () => selectNetwork(network.ssid, network.secured));
      item.appendChild(button);
      ui.networks.appendChild(item);
    });
  }

  function selectNetwork(ssid, secured, manual = false) {
    selected = { ssid: ssid || '', secured: secured !== false };
    ui.panelNetworks.hidden = true;
    ui.panelConnect.hidden = false;
    ui.panelStatus.hidden = true;
    ui.selectedTitle.textContent = manual || !ssid ? 'Outra rede' : ssid;
    ui.fieldSsid.hidden = !(manual || !ssid);
    ui.inputSsid.value = manual ? '' : ssid;
    ui.fieldPassword.hidden = false;
    ui.inputPassword.value = '';
    ui.connect.disabled = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
    setTimeout(() => {
      if (ui.fieldSsid.hidden) ui.inputPassword.focus();
      else ui.inputSsid.focus();
    }, 120);
  }

  function backToList() {
    ui.inputPassword.value = '';
    ui.panelConnect.hidden = true;
    ui.panelStatus.hidden = true;
    ui.panelNetworks.hidden = false;
  }

  function showStatus(title, text, kind = '', showRetry = false, spinner = true) {
    ui.panelConnect.hidden = true;
    ui.panelNetworks.hidden = true;
    ui.panelStatus.hidden = false;
    ui.statusTitle.textContent = title;
    ui.statusText.textContent = text;
    ui.statusText.className = kind;
    ui.spinner.hidden = !spinner;
    ui.retry.hidden = !showRetry;
    ui.statusNote.hidden = !spinner;
  }

  async function submit(event) {
    event.preventDefault();
    const ssid = (ui.fieldSsid.hidden ? selected && selected.ssid : ui.inputSsid.value.trim()) || '';
    const password = ui.inputPassword.value;

    if (!ssid) {
      showStatus('Ops', 'Informe o nome da rede.', 'err', true, false);
      return;
    }
    if (password && (password.length < 8 || password.length > 63)) {
      showStatus('Senha inválida', 'A senha do Wi-Fi deve ter entre 8 e 63 caracteres.', 'err', true, false);
      return;
    }

    ui.connect.disabled = true;
    showStatus('Conectando...', `Enviando a rede ${ssid} para o Zee.`, '', false, true);

    const { ok, payload } = await api('/api/connect', { method: 'POST', body: { ssid, password } });
    ui.inputPassword.value = '';

    if (!ok) {
      showStatus('Não deu certo',
        (payload && payload.message) || 'Não consegui enviar os dados. Tente novamente.',
        'err', true, false);
      ui.connect.disabled = false;
      return;
    }

    showStatus('Conectando...', `O Zee está tentando entrar na rede ${ssid}.`, '', false, true);
    startPolling();
  }

  function startPolling() {
    stopPolling();
    pollMisses = 0;
    pollTimer = window.setInterval(checkStatus, 2500);
  }
  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  async function checkStatus() {
    let result;
    try {
      result = await api('/api/status');
    } catch (_) {
      result = { ok: false };
    }

    if (!result.ok) {
      pollMisses += 1;
      // O AP cai enquanto o Zee testa a rede: perder contato é esperado.
      if (pollMisses >= 4) {
        stopPolling();
        showStatus(
          'Quase lá!',
          'Perdi o contato com o Zee — isso costuma significar que ele entrou na sua rede. '
          + 'Confira a tela do dispositivo: se aparecer a abelha, deu certo. '
          + 'Se voltar o QR Code, reconecte-se à rede do Zee e tente de novo.',
          '', true, false
        );
      }
      return;
    }

    pollMisses = 0;
    const status = (result.payload && result.payload.status) || 'idle';
    const message = (result.payload && result.payload.message) || '';

    if (status === 'connected') {
      stopPolling();
      showStatus('Tudo certo!', 'Wi-Fi configurado com sucesso!', 'ok', false, false);
    } else if (status === 'failed') {
      stopPolling();
      showStatus('Não foi possível conectar',
        message || 'Verifique a senha e tente novamente.', 'err', true, false);
    }
  }

  function bind() {
    ui.refresh.addEventListener('click', loadNetworks);
    ui.other.addEventListener('click', () => selectNetwork('', true, true));
    ui.cancel.addEventListener('click', backToList);
    ui.form.addEventListener('submit', submit);
    ui.retry.addEventListener('click', () => { stopPolling(); backToList(); loadNetworks(); });
    ui.togglePassword.addEventListener('click', () => {
      const isPassword = ui.inputPassword.type === 'password';
      ui.inputPassword.type = isPassword ? 'text' : 'password';
      ui.togglePassword.textContent = isPassword ? '🙈' : '👁';
    });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && pollTimer) checkStatus();
    });
  }

  bind();
  loadNetworks();
})();
