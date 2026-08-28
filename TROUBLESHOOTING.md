# Troubleshooting — Zee Assistant

Comece sempre por aqui:

```bash
systemctl status zee-assistant
journalctl -u zee-assistant -n 60 --no-pager
tail -n 60 ~/zee-assistant/logs/zee.log
curl -s localhost:5000/api/status | python3 -m json.tool
```

---

## 1. Microfone não detectado

**Sintomas:** badge `Microfone indisponível`; log `nenhum microfone de entrada encontrado`.

```bash
arecord -l                                   # o ALSA enxerga o dispositivo?
./scripts/check_audio.sh                     # diagnóstico completo
sudo systemctl stop zee-assistant
venv/bin/python scripts/voice_test.py devices
```

| Causa | Solução |
|---|---|
| Microfone USB não enumerou | reconecte e verifique `dmesg \| tail -20`; troque de porta USB (evite hubs sem alimentação) |
| Falta o PortAudio | `sudo apt install -y libportaudio2 portaudio19-dev` e reinstale: `venv/bin/pip install --force-reinstall sounddevice` |
| Microfone I2S sem overlay | acrescente o `dtoverlay` correto em `/boot/firmware/config.txt` e reinicie |
| O serviço já está usando o microfone | `sudo systemctl stop zee-assistant` antes de testar manualmente |
| Dispositivo errado escolhido | fixe em `config.json` → `voice.input_device` (índice **ou** parte do nome) |
| Usuário sem permissão | `sudo usermod -aG audio $USER` e reinicie |

**Captura muda (grava, mas só silêncio):**

```bash
alsamixer            # F4 = captura; suba o volume; tecla M tira o mute
sudo alsactl store   # salva os níveis
```

Se o `rms` no `voice_test.py wakeword` fica abaixo de ~200 mesmo falando perto,
o ganho está baixo demais.

---

## 2. Raspberry sem áudio (o MP3 não toca)

**Sintomas:** log `nenhum player de áudio encontrado` ou `falha ao reproduzir`.

```bash
sudo apt install -y mpg123
mpg123 static/assets/audio/oi_estou_ouvindo.mp3     # teste direto
aplay /usr/share/sounds/alsa/Front_Center.wav      # teste do ALSA
```

| Causa | Solução |
|---|---|
| Saída errada (HDMI × P2) | `sudo raspi-config` → System Options → Audio; ou clique com o botão direito no ícone de volume do desktop |
| Volume no zero | `alsamixer` → F6 escolhe a placa → suba Master/PCM → `sudo alsactl store` |
| Arquivo ausente | log `Welcome audio not found` — copie o MP3 para `static/assets/audio/oi_estou_ouvindo.mp3` |
| MP3 corrompido | `mpg123 -t arquivo.mp3` reporta o erro |
| Serviço sem sessão de áudio | confirme `SupplementaryGroups=audio` em `/etc/systemd/system/zee-assistant.service` |

O sistema **não trava** sem áudio: ele registra o erro e segue para a captura do comando.

---

## 3. Chromium não inicia (ou abre fora do kiosk)

```bash
which chromium-browser chromium
DISPLAY=:0 ./scripts/kiosk.sh          # execute manualmente e leia a saída
```

| Causa | Solução |
|---|---|
| Sem login automático | `sudo raspi-config` → System Options → Boot / Auto Login → **Desktop Autologin** |
| Autostart não instalado | `./scripts/configure_kiosk.sh` e reinicie |
| Sessão gráfica diferente | confira `echo $XDG_SESSION_TYPE`; o script cobre labwc, wayfire e LXDE — para outra sessão, chame `scripts/kiosk.sh` no autostart dela |
| Backend ainda subindo | normal: o `kiosk.sh` aguarda `/healthz` por até 90 s |
| Balão "sessão restaurada" | já tratado pelo script; se persistir, apague `~/.config/zee-kiosk` |
| Tela apaga sozinha | `configure_kiosk.sh` desliga o blanking; em wayfire confirme `[idle] dpms_timeout = -1` em `~/.config/wayfire.ini` |
| Chromium ausente | `sudo apt install -y chromium-browser` (ou `chromium`) |

Para depurar a interface, abra o DevTools remoto com um teclado: `Ctrl+Shift+I`
(ou rode `chromium --kiosk http://127.0.0.1:5000` manualmente).

---

## 4. Modelo Vosk não encontrado

**Sintomas:** log `modelo Vosk não encontrado em ...` e badge de voz indisponível.

```bash
ls models/vosk/pt-br/            # deve conter am/ conf/ graph/ ivector/
./scripts/download_vosk_model.sh
```

| Causa | Solução |
|---|---|
| Download não executado | `./scripts/download_vosk_model.sh` |
| Pasta com nível extra (`pt-br/vosk-model-small-pt-0.3/am`) | mova o conteúdo um nível acima: `mv models/vosk/pt-br/*/* models/vosk/pt-br/` |
| Caminho diferente | ajuste `voice.model_path` no `config.json` |
| Sem espaço em disco | `df -h` — o modelo small precisa de ~40 MB |
| Pacote `vosk` não instalado | `venv/bin/pip install vosk` (exige Python 64 bits) |

A aplicação **continua funcionando pelo touchscreen** com o modelo ausente.

---

## 5. Wakeword não reconhecida

Primeiro descubra **se o problema é o áudio ou a grafia**:

```bash
# 1) a decisão está correta para as grafias conhecidas? (não precisa de microfone)
venv/bin/python scripts/voice_test.py wake

# 2) o que o SEU microfone produz de verdade?
sudo systemctl stop zee-assistant
venv/bin/python scripts/voice_test.py wakeword
```

O passo 2 imprime, para cada fala, o texto reconhecido e as duas camadas de
decisão:

```
  final   rms=  1820  texto='oi zé'  lista=100.0 estrut=100.0 score=100.0  <<< WAKEWORD
```

| Situação no passo 2 | Diagnóstico | Solução |
|---|---|---|
| Nenhuma linha aparece | o áudio não chega | volte ao item 1 (microfone) |
| `rms` baixo (< 200) falando perto | ganho baixo | `alsamixer` → F4 → suba Capture |
| Texto sai, mas `estrut=0.0` com nome estranho (ex.: `oi si`) | forma do nome desconhecida | acrescente `si` em `voice.wakeword.structural.names` |
| Texto sai com 5+ palavras | o Vosk está transcrevendo conversa | confirme `use_grammar: true` e revise `grammar_phrases` |
| `score` fica logo abaixo do limiar | limiar apertado | `fuzzy_threshold` para 76–78 |

| Sintoma | Ajuste em `voice.wakeword` |
|---|---|
| Nunca reconhece | `fuzzy_threshold` para 76–78; adicione formas em `structural.names` |
| Dispara sozinho / com qualquer conversa | `fuzzy_threshold` para 86–90; `max_words` para 3; `structural.max_name_length` para 2 |
| Aceita nomes parecidos ("oi Zeca") | reduza `structural.max_name_length` |
| Só reconhece muito perto do microfone | suba o ganho no `alsamixer`; reduza `silence_rms_threshold` |
| Log cheio de "gramática rejeitada pelo modelo" | uma palavra da `grammar_phrases` não existe no modelo — remova-a, ou use `"use_grammar": false` (consome mais CPU) |

**Nada é reconhecido nem com o `voice_test`:** volte ao item 1 (áudio de entrada).

---

## 6. Comando reconhecido, mas o conteúdo não abre

```bash
venv/bin/python scripts/voice_test.py match "quero assistir o vídeo de ia"
```

O ranking mostra o score de cada recurso.

| Situação | Ajuste |
|---|---|
| O item certo ficou logo abaixo do limiar | baixe `matching.confidence_threshold` para 62–65 |
| Abre o item errado com confiança alta | melhore os títulos no `recursos.json` (títulos distintos ajudam mais que qualquer ajuste) |
| Sempre pede para escolher entre duas opções | reduza `matching.ambiguity_margin` (ex.: 5) |
| Siglas não são entendidas | **o modelo não transcreve siglas soletradas** ("ABC" vira `se`, "IA" vira `dia`): acrescente `aliases` ao recurso com palavras inteiras (`"jogo do alfabeto"`) |
| Sinônimos de texto | `matching.synonyms` (ex.: `"pln": "processamento de linguagem natural"`) |
| A transcrição sai truncada | aumente `voice.command.silence_duration_seconds` para 1.6 |

---

## 7. Wi-Fi não conecta

```bash
nmcli device status
nmcli device wifi list --rescan yes
sudo journalctl -u NetworkManager -n 40 --no-pager
```

| Causa | Solução |
|---|---|
| Senha incorreta | o portal informa e mantém o AP: tente de novo |
| Perfil antigo com senha errada | o Zee já apaga e recria; manualmente: `sudo nmcli connection delete "<SSID>"` |
| Wi-Fi bloqueado por rfkill | `sudo rfkill unblock wifi` |
| País de Wi-Fi não definido | `sudo raspi-config` → Localisation → WLAN Country (sem isso o rádio pode ficar mudo) |
| Rede 5 GHz distante | o Pi 4B suporta 5 GHz, mas o AP de configuração usa 2,4 GHz — aproxime o dispositivo |
| Rede corporativa (WPA2-Enterprise) | não suportada pelo portal; crie o perfil manualmente com `nmcli` |
| `sudo` pedindo senha | confira `/etc/sudoers.d/zee-assistant` (reinstale com `./scripts/install.sh`) |
| SSID oculto | o portal não lista redes ocultas; use "Outra rede..." e digite o nome |

---

## 8. Captive portal não abre no celular

Primeiro: **a tela do Zee sempre mostra a URL manual** (`http://10.42.0.1`).
Digite-a no navegador do celular — o fluxo funciona igual.

| Causa | Solução |
|---|---|
| DNS wildcard ausente | `ls /etc/NetworkManager/dnsmasq-shared.d/zee-captive.conf`; reinstale com `./scripts/install.sh` e `sudo systemctl restart NetworkManager` |
| Porta 80 indisponível | log `porta 80 indisponível`; o portal cai para 8080 + redirecionamento iptables. Acesse `http://10.42.0.1:8080` se necessário |
| Android com "Wi-Fi sem internet" | escolha "Manter conectado" quando perguntado |
| iPhone não abre a janelinha | abra o Safari e vá a `http://10.42.0.1` (o iOS não repete a detecção após dispensá-la) |
| Celular usando dados móveis | desative os dados móveis durante a configuração |
| AP não apareceu | `nmcli connection show`; verifique o log `Access Point ativo`; force com `curl -X POST localhost:5000/api/wifi/setup -d '{"action":"start"}' -H 'Content-Type: application/json'` |

---

## 9. Iframe não carrega (tela em branco no conteúdo)

Muitos sites enviam `X-Frame-Options: DENY` ou
`Content-Security-Policy: frame-ancestors 'none'` — o navegador se recusa a
exibi-los e **não** avisa a página. Por isso o Zee mostra a barra de ajuda após
8 segundos, com **TENTAR DE NOVO** e **VOLTAR**: a aplicação nunca fica presa.

| Causa | Solução |
|---|---|
| Site bloqueia iframes | hospede o conteúdo localmente, ou use outra fonte |
| URL só em `http://` | prefira `https://` (conteúdo misto é bloqueado) |
| Certificado inválido | corrija o certificado ou hospede o arquivo localmente |
| Sem internet | a mensagem "Verifique sua conexão com a internet" aparece antes de tentar |

Para conteúdo local, coloque os arquivos em `static/` e use no JSON uma URL
relativa como `/static/conteudos/aula.pdf`.

---

## 10. YouTube não carrega

| Causa | Solução |
|---|---|
| URL não convertida | confirme com `curl -s localhost:5000/api/resources/<id> \| grep embed_url` — deve conter `/embed/` |
| Vídeo com incorporação desativada | o autor bloqueou; use outro vídeo |
| Sem internet | veja o item 7 |
| Vídeo pesado travando | prefira 720p; o Pi 4B não decodifica VP9 4K por hardware |
| Aceleração de vídeo ausente | `sudo raspi-config` → Advanced → GL Driver → **GL (Fake KMS/Full KMS)** |
| Áudio do vídeo mudo | veja o item 2 |

---

## 11. PDF não aparece

| Causa | Solução |
|---|---|
| Visualizador desativado | no perfil do kiosk, confira `chrome://settings/content/pdfDocuments` — "Abrir PDFs no Chromium" |
| Servidor envia `Content-Disposition: attachment` | o Chromium baixa em vez de exibir; hospede o arquivo em outro lugar |
| Servidor bloqueia iframe | veja o item 9 |
| PDF muito grande | arquivos de dezenas de MB demoram no Pi; reduza/comprima |

Se precisar de um leitor próprio (anotações, paginação), troque apenas
`RENDERERS.livro` em `static/js/app.js` por uma implementação com PDF.js — a
arquitetura já prevê essa substituição.

---

## 12. A interface não atualiza sozinha após um comando de voz

**Sintoma:** o log mostra `recurso selecionado`, mas a tela não muda.

```bash
curl -N localhost:5000/api/events        # deve emitir eventos continuamente
```

| Causa | Solução |
|---|---|
| SSE bloqueado por proxy | não use proxy para `127.0.0.1` |
| Aba antiga sem reconectar | o JS reconecta sozinho e cai para polling; recarregue com F5 |
| Erro de JavaScript | abra o DevTools (`Ctrl+Shift+I`) e veja o console |

---

## 13. Serviço reiniciando em loop

```bash
journalctl -u zee-assistant -n 100 --no-pager | grep -iE "error|traceback|exception"
```

| Causa | Solução |
|---|---|
| Porta 5000 ocupada | `sudo ss -tlnp \| grep 5000`; mude `app.port` no `config.json` |
| `config.json` inválido | `python3 -m json.tool config/config.json`; o app cai para os padrões, mas o erro fica no log |
| Dependência faltando | `venv/bin/pip install -r requirements.txt` |
| Caminho errado no unit | `sudo systemctl cat zee-assistant`; reinstale com `./scripts/install.sh` |
| Sem permissão de escrita nos logs | `sudo chown -R $USER:$USER logs/` |

---

## 14. Desempenho ruim / travamentos

```bash
vcgencmd measure_temp        # acima de 80 °C há throttling
vcgencmd get_throttled       # 0x0 = tudo bem
free -h
top -o %CPU
```

| Causa | Solução |
|---|---|
| Subtensão | use a fonte oficial de 5 V/3 A (`get_throttled` diferente de `0x0`) |
| Superaquecimento | dissipador/ventoinha |
| Modelo Vosk grande | use o `small` (`vosk-model-small-pt-0.3`) |
| Muitos iframes | já tratado: o iframe é destruído ao sair da tela |
| Cartão SD lento | use um cartão A1/A2 de qualidade |

---

## 15. Reinstalar do zero

```bash
./scripts/uninstall.sh
rm -rf venv
./scripts/install.sh
```

Os conteúdos (`data/recursos.json`), o modelo e os logs são preservados.
