# Procedimentos de teste — Zee Assistant

Cada funcionalidade abaixo tem: **como testar**, **resultado esperado** e **o que
olhar quando falhar**. Os testes T1–T21 cobrem os critérios de aceite do projeto.

> Para testar no seu computador, sem o Raspberry Pi, use
> **[TESTES-LOCAIS.md](TESTES-LOCAIS.md)**.

Prepare dois terminais:

```bash
# terminal 1 — log da aplicação
tail -f ~/zee-assistant/logs/zee.log

# terminal 2 — comandos
cd ~/zee-assistant
```

---

## Testes automatizados (antes de tudo)

```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest -v
```

**Esperado:** 275 testes passando. Eles cobrem JSON, normalização, intenção,
busca fuzzy, wakeword, estados, API e segurança de log — sem precisar de
microfone, rede ou tela.

---

## T1 — Serviço sobe no boot

```bash
sudo reboot
# após reiniciar:
systemctl is-enabled zee-assistant     # enabled
systemctl is-active  zee-assistant     # active
journalctl -u zee-assistant -b | head -20
```

**Esperado:** serviço ativo, log com `Zee Assistant 1.0.0 iniciando`.
**Se falhar:** `journalctl -u zee-assistant -n 50` mostra a exceção.

---

## T2 — Reinício automático em caso de falha

```bash
pgrep -f "main.py" | head -1 | xargs sudo kill -9
sleep 8
systemctl is-active zee-assistant      # active novamente
```

**Esperado:** o systemd reinicia em ~5 s (`Restart=always`, `RestartSec=5`).

---

## T3 — Chromium abre em kiosk

Observe a tela após o boot.

**Esperado:** tela cheia, sem barra de endereço, abas, menus ou balão de
"sessão restaurada"; a tela não apaga sozinha.
**Se falhar:** `TROUBLESHOOTING.md` → "Chromium não inicia".

---

## T4 — Backend responde

```bash
curl -s localhost:5000/healthz
curl -s localhost:5000/api/status | python3 -m json.tool | head -20
```

**Esperado:** `{"ok": true, "state": "HOME_LISTENING"}` e o status completo com
microfone, modelo e contagem de recursos.

---

## T5 — Home

**Esperado:** abelha centralizada, texto `Diga "Oi, Zee"`, botão **MENU** grande
na parte inferior. Sem microfone, aparece discretamente `Microfone indisponível`
e a dica muda para `Toque em MENU para explorar` — a aplicação **não trava**.

---

## T6 — Menu e listagens (toque)

1. Toque em **MENU** → quatro cards: VÍDEOS, ÁUDIOS, LIVROS, JOGOS (com a
   contagem de itens de cada tipo).
2. Toque em **VÍDEOS** → apenas recursos `tipo: video`.
3. Repita para os outros três.
4. **VOLTAR** em cada tela.

```bash
curl -s "localhost:5000/api/resources?tipo=livro" | python3 -m json.tool
```

**Esperado:** o que está na tela é exatamente o que a API devolve.

---

## T7 — Conteúdo dinâmico do JSON

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('data/recursos.json')
d = json.loads(p.read_text(encoding='utf-8'))
d['recursos'].append({
  "id": "rec_teste", "tipo": "jogo",
  "titulo": "Jogo de Teste", "descricao": "Item adicionado durante o teste.",
  "url": "https://example.com/jogo.html"
})
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
PY
```

Volte à Home, entre em MENU → JOGOS.

**Esperado:** "Jogo de Teste" aparece **sem reiniciar o serviço**.
Remova o item depois do teste.

---

## T8 — Vídeo (YouTube)

Abra um recurso `tipo: video`.

**Esperado:** iframe ocupando quase toda a tela, URL `watch?v=` convertida
automaticamente para `/embed/`; botão **VOLTAR** sempre visível.

```bash
curl -s localhost:5000/api/resources/rec_001 | grep -o '"embed_url":"[^"]*"'
```

---

## T9 — Áudio (MP3)

Abra um recurso `tipo: audio`.

**Esperado:** player próprio (sem iframe) com play/pause, barra de progresso,
tempo atual, duração e volume; título e descrição visíveis.
Ao tocar em **VOLTAR** o áudio **para imediatamente**.

---

## T10 — Livro (PDF)

Abra um recurso `tipo: livro`.

**Esperado:** PDF renderizado pelo Chromium dentro do iframe, com rolagem e
zoom; **VOLTAR** disponível. Se o servidor do PDF bloquear iframes, aparece a
barra "O PDF não abriu?" com **TENTAR DE NOVO** e **VOLTAR** — a tela nunca fica
branca sem saída.

---

## T11 — Jogo (HTML)

Abra um recurso `tipo: jogo`.

**Esperado:** jogo em tela quase cheia. Se o site enviar `X-Frame-Options` ou
`Content-Security-Policy: frame-ancestors`, a barra de ajuda aparece após 8 s —
a aplicação continua navegável.

---

## T12 — Microfone detectado

```bash
sudo systemctl stop zee-assistant
venv/bin/python scripts/voice_test.py devices
./scripts/check_audio.sh
sudo systemctl start zee-assistant
grep -i "microfone" logs/zee.log | tail -3
```

**Esperado:** dispositivo listado e log `microfone detectado: <nome> (índice N)`.

---

## T13 — Modelo Vosk carregado

```bash
grep -i "modelo Vosk" logs/zee.log | tail -2
curl -s localhost:5000/api/voice/status | python3 -m json.tool
```

**Esperado:** `modelo Vosk carregado de .../models/vosk/pt-br (X.Xs)` e
`"model_loaded": true`.
**Teste do caminho de erro:** renomeie a pasta do modelo e reinicie —
o log deve trazer um erro claro, a voz fica desativada e **o touchscreen
continua funcionando**.

---

## T14 — Wakeword offline

1. Desconecte o cabo de rede / desligue o Wi-Fi do roteador (o reconhecimento é local).
2. Na Home, diga **"Oi, Zee"**.

**Esperado, em sequência:**

| Momento | Tela | Áudio |
|---|---|---|
| Inicialização | Home aparece | toca `saudacao.mp3` |
| Detecção | `Oi! Estou ouvindo...` | toca `pode-falar.mp3` |
| Captura | `Aguardando usuário...` + barras animadas | — (mudo) |
| Busca | `Procurando conteúdo...` | — |
| Entendeu | conteúdo/listagem abre | toca `encontrei.mp3` |
| Não entendeu | `Não encontrei esse conteúdo.` | toca `erro.mp3` |

```bash
grep -E "wakeword detectada|áudio reproduzido|transcrição" logs/zee.log | tail -5
```

Teste também as variações — todas devem acionar o assistente:
**"oi zee"**, **"oi zi"**, **"oi zí"**, **"oi zé"**, **"ei zi"**, **"olá zee"**.
E estas **não** podem acionar: "oi", "oi tudo bem", "oi zebra", "oi professora".

A mesma matriz roda sem microfone (útil para regressão):

```bash
venv/bin/python scripts/voice_test.py wake
```

**Se não reconhecer com o microfone:** rode
`venv/bin/python scripts/voice_test.py wakeword` (com o serviço parado) e veja
[TROUBLESHOOTING.md §5](TROUBLESHOOTING.md).

---

## T14b — Avisos sonoros

```bash
# cada som isolado, pelo alto-falante do dispositivo
for som in startup wakeword found error; do
  echo "== $som"
  curl -s -X POST localhost:5000/api/voice/sound -H 'Content-Type: application/json' \
       -d "{\"name\":\"$som\"}"
  sleep 3
done

# o que a aplicação encontrou
curl -s localhost:5000/api/voice/status | python3 -c "
import json,sys
for k,v in json.load(sys.stdin)['sounds'].items(): print(k, v['exists'], v['path'])"
```

**Esperado:** os quatro tocam e aparecem como `exists: true`.

Verificações de comportamento:

1. **A saudação toca uma vez** por inicialização
   (`grep "assistente pronto" logs/zee.log`).
2. **O Zee não escuta a si mesmo**: durante qualquer aviso,
   `curl -s localhost:5000/api/status` mostra `"audio_playing": true` e
   `"wakeword_enabled": false`.
3. **O aviso de erro é aguardado**: diga algo sem sentido e confira no log que
   `erro.mp3` termina **antes** da transição `ERROR -> HOME_LISTENING`.
4. **Um aviso novo corta o anterior**: dispare `startup` e, 1 s depois, `found`.
5. **Arquivo ausente não trava**: renomeie `encontrei.mp3`, faça um pedido
   válido — o conteúdo abre e o log registra `Found not found`.

Para executar o ciclo completo (som + gravação) sem falar a wakeword:

```bash
curl -X POST localhost:5000/api/voice/simulate -H 'Content-Type: application/json' \
     -d '{"wakeword":true}'
# toca "pode falar" e grava do microfone: fale o comando após o aviso
```

---

## T15 — Comandos de voz completos

Com o serviço rodando, diga:

| Comando | Esperado |
|---|---|
| "Oi Zee" → "Quero assistir ao vídeo de introdução à inteligência artificial" | abre `rec_001` |
| "Oi Zee" → "Quero ouvir o podcast de inteligência artificial" | abre `rec_002` |
| "Oi Zee" → "Abra o livro fundamentos de inteligência artificial" | abre `rec_003` |
| "Oi Zee" → "Quero jogar o jogo do ABC" | abre `rec_004` |
| "Oi Zee" → "Quero uma receita de bolo" | `Não encontrei esse conteúdo.` e volta à Home em 5 s |
| "Oi Zee" → "Lista de vídeos" | abre a listagem de Vídeos |
| "Oi Zee" → "Mostra a lista de podcasts" | abre a listagem de Áudios |
| "Oi Zee" → "Quais jogos existem" | abre a listagem de Jogos |
| "Oi Zee" → "Abre o menu" | abre o MENU |
| "Oi Zee" → "Toca o podcast de inteligência artificial" | abre `rec_002` |
| "Oi Zee" → "Bora brincar com o alfabeto" | abre `rec_004` |

Sem falar nada após a wakeword: em ~5 s o sistema desiste e volta à Home.

**Sem microfone?** O mesmo caminho de decisão pode ser testado por HTTP:

```bash
curl -s -X POST localhost:5000/api/voice/simulate -H 'Content-Type: application/json' \
     -d '{"text":"quero ouvir o podcast de inteligência artificial"}' | python3 -m json.tool
```

A tela deve navegar sozinha, sem nenhum clique.

---

## T16 — Busca tolerante e níveis de confiança

```bash
for t in "abra introdução inteligência artificial" \
         "quero o podcast de IA" \
         "QUERO ASSISTIR, INTRODUCAO A INTELIGENCIA ARTIFICIAL!" \
         "quero jogar abc" \
         "quero ver vídeos"; do
  echo "== $t"
  curl -s -X POST localhost:5000/api/voice/match -H 'Content-Type: application/json' \
       -d "{\"text\": \"$t\"}" \
       | python3 -c "import json,sys; d=json.load(sys.stdin); print(' ', d['status'], d['confidence'], (d['resource'] or {}).get('id'), '| tipo:', d['detected_type'])"
done
```

**Esperado:** os quatro primeiros com `status: open`, confiança ≥ 70 e o `id`
correto; o último com `status: open_list` e `detected_type: video`
(pedido genérico abre a listagem em vez de adivinhar).

Pedidos de listagem e de menu:

```bash
for t in "lista de vídeos" "mostra a lista de podcasts" "quais jogos existem" "abre o menu"; do
  curl -s -X POST localhost:5000/api/voice/match -H 'Content-Type: application/json' \
       -d "{\"text\": \"$t\"}" \
       | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status'], d['detected_type'])"
done
# open_list video / open_list audio / open_list jogo / open_menu None
```

Para inspecionar o ranking completo:

```bash
venv/bin/python scripts/voice_test.py match "quero ver o vídeo de ia"
```

---

## T17 — Wakeword desativada fora da Home (regra obrigatória)

1. Toque em **MENU** e diga "Oi, Zee" várias vezes → **nada acontece**.
2. Entre em **VÍDEOS** e repita → nada acontece.
3. Abra um vídeo e repita → nada acontece.
4. **VOLTAR** até a Home e diga "Oi, Zee" → funciona normalmente.

Verificação objetiva:

```bash
curl -s -X POST localhost:5000/api/navigation -H 'Content-Type: application/json' -d '{"view":"menu"}'
# {"ok":true,"state":"MENU","wakeword_enabled":false}
curl -s -X POST localhost:5000/api/navigation/home
# {"ok":true,"state":"HOME_LISTENING","wakeword_enabled":true}
```

No log deve aparecer `wakeword desativada (MENU) — liberando microfone`
(nível DEBUG) e as transições com `(wakeword=off)` / `(wakeword=on)`.

---

## T18 — Configuração de Wi-Fi por QR Code

**Simulação em um Pi já configurado:**

```bash
curl -s -X POST localhost:5000/api/wifi/setup -H 'Content-Type: application/json' \
     -d '{"action":"start"}' | python3 -m json.tool
```

**Esperado:**

1. a tela mostra `Configure o Wi-Fi do Zee` + QR Code grande + o SSID
   `Zee-Setup-XXXX` + `http://10.42.0.1`;
2. `nmcli device wifi list` em outro aparelho mostra a rede `Zee-Setup-XXXX`;
3. ao conectar o celular, o captive portal abre sozinho (Android/iOS);
4. o portal lista as redes com nome, cadeado e intensidade de sinal;
5. escolher a rede + senha + **CONECTAR**;
6. a tela do Pi mostra `Conectando a <rede>...` e depois `Conectado!`;
7. o AP cai, o portal encerra e a Home aparece com a wakeword ativa.

```bash
grep -E "Access Point|conexão|Wi-Fi configurado" logs/zee.log | tail -10
grep -ci "password\|senha" logs/zee.log     # deve ser 0 ocorrências com valor real
```

**Teste do caminho de falha:** informe uma senha errada.
**Esperado:** `Não foi possível conectar. Verifique a senha e tente novamente.`,
o **AP volta imediatamente** e é possível tentar de novo.

**Teste do primeiro boot real:**

```bash
sudo nmcli connection show                      # anote os perfis Wi-Fi
sudo nmcli connection delete "<perfil>"         # remove a rede salva
sudo reboot
```

O Pi deve entrar sozinho no modo de configuração.

---

## T19 — Recuperação de Wi-Fi

Com o Pi ocioso na Home, desligue o roteador (ou tire o Pi do alcance) e aguarde
`wifi_recovery_timeout_seconds` (padrão 60 s).

**Esperado:** log `sem Wi-Fi há 60s — reentrando no modo de configuração` e a
tela volta ao QR Code. Se o usuário estiver assistindo a um conteúdo, a
recuperação é **adiada** (log em nível DEBUG) até ele voltar à Home.

---

## T20 — Resiliência

| Situação | Como testar | Esperado |
|---|---|---|
| Sem internet | desligue o roteador e abra um conteúdo remoto | mensagem "Não foi possível carregar este conteúdo. Verifique sua conexão com a internet." + **VOLTAR** |
| Sem microfone | desconecte o microfone USB e reinicie o serviço | badge `Microfone indisponível`, touchscreen 100% funcional |
| Sem modelo Vosk | `mv models/vosk/pt-br models/vosk/off` e reinicie | erro claro no log, voz desativada, touchscreen funcional |
| Sem MP3 de saudação | remova o arquivo e diga "Oi, Zee" | log `Welcome audio not found` e o ciclo continua para a captura |
| JSON inválido | escreva `{` em `data/recursos.json` | log de erro e o **catálogo anterior é preservado** |
| Recurso inexistente | `curl localhost:5000/api/resources/xyz` | HTTP 404 com JSON de erro |
| SSE cai | `sudo systemctl restart zee-assistant` com a tela aberta | a interface reconecta sozinha (e cai para polling se necessário) |

---

## T21 — Segurança

```bash
# 1. senha do Wi-Fi nunca aparece no log
sudo grep -riE "psk|password [^*]" logs/zee.log | grep -v '\*\*\*'   # sem resultados

# 2. sem path traversal
curl -s -o /dev/null -w "%{http_code}\n" "localhost:5000/api/resources/..%2F..%2Fetc%2Fpasswd"   # 404

# 3. parâmetros validados
curl -s -o /dev/null -w "%{http_code}\n" "localhost:5000/api/resources?tipo=;rm%20-rf%20/"       # 400
curl -s -X POST localhost:5000/api/wifi/connect -H 'Content-Type: application/json' \
     -d '{"ssid":"-rede$(reboot)","password":"12345678"}' -o /dev/null -w "%{http_code}\n"       # 400

# 4. sudo restrito ao mínimo
sudo cat /etc/sudoers.d/zee-assistant     # apenas nmcli, iptables e rfkill
```

**Esperado:** todos os itens conforme indicado. Nenhum comando do usuário é
executado via shell — todo `subprocess` recebe lista de argumentos.

---

## Resumo dos critérios de aceite

| Critério | Teste |
|---|---|
| Inicia automaticamente com o Pi | T1 |
| Chromium abre em kiosk | T3 |
| Primeira inicialização cria Access Point | T18 |
| LCD apresenta QR Code | T18 |
| Smartphone conecta ao AP | T18 |
| Página para selecionar Wi-Fi | T18 |
| Pi conecta ao Wi-Fi informado | T18 |
| Após configuração aparece a Home | T18 |
| Home mostra a Zee | T5 |
| Botão MENU funciona | T6 |
| MENU mostra os quatro tipos | T6 |
| Conteúdo carregado dinamicamente do JSON | T7 |
| Vídeos / MP3 / PDFs / jogos funcionam | T8, T9, T10, T11 |
| Wakeword funciona offline | T14 |
| "Oi Zee" reproduz o MP3 local | T14, T14b |
| Interface mostra "Aguardando usuário" | T14 |
| Comando do usuário é reconhecido | T15 |
| Busca fuzzy identifica o recurso | T16 |
| Recurso é aberto automaticamente | T15 |
| Wakeword desabilitada no MENU e em conteúdos | T17 |
| Wakeword volta ao retornar à Home | T17 |
| Não trava sem internet / sem microfone | T20 |
| Logs são gerados | T4, T12, T13 |
| Senha do Wi-Fi nunca nos logs | T21 |
| Serviço reinicia em caso de falha | T2 |
