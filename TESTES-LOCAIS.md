# Testando o Zee Assistant no macOS (sem o Raspberry Pi)

Dá para desenvolver e validar **quase tudo** no Mac: interface, navegação, API,
busca por voz e até o reconhecimento offline com o Vosk. Só a parte de rede
(Access Point, captive portal, kiosk) depende do Raspberry Pi — e mesmo essas
telas podem ser abertas para conferir o visual.

> Tudo neste guia foi executado e validado em um MacBook Pro (Apple Silicon,
> macOS + Python 3.9).

---

## 0. O que dá e o que não dá

| Funcionalidade | No Mac | Observação |
|---|:--:|---|
| Interface (Home, Menu, listas, conteúdo) | ✅ | no navegador, em qualquer resolução |
| API + eventos SSE | ✅ | |
| Catálogo dinâmico (`recursos.json`) | ✅ | |
| Vídeo / áudio / PDF / jogo | ✅ | depende dos links do JSON |
| Busca fuzzy e classificação de intenção | ✅ | |
| Reconhecimento de voz (Vosk PT-BR) | ✅ | wheels do `vosk` e `sounddevice` existem para macOS |
| Wakeword pelo microfone do Mac | ✅ | requer permissão de microfone |
| MP3 de saudação | ✅ | usa o `afplay` (já vem no macOS) |
| Testes automatizados (`pytest`) | ✅ | 203 testes |
| Tela de configuração de Wi-Fi + QR Code | 🟡 | a tela e o QR aparecem; o Access Point real, não |
| Captive portal (página do celular) | 🟡 | dá para abrir em `/setup` e testar o layout |
| Criar o Access Point `Zee-Setup` | ❌ | precisa de `nmcli` (Linux) |
| Chromium em modo kiosk / systemd | ❌ | específico do Raspberry Pi OS |

---

## 1. Preparação (uma vez)

Não precisa de Homebrew: o wheel do `sounddevice` já traz o PortAudio, e o
player de áudio (`afplay`) faz parte do macOS.

```bash
cd "caminho/para/projeto-raspberry-zeebot"

python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements-dev.txt      # inclui o pytest
```

Se o `vosk` não instalar no seu Python (ele exige 64 bits), você ainda pode
testar **tudo menos a voz real** — basta rodar com `--no-voice`.

Modelo de voz PT-BR (~50 MB em disco):

```bash
./scripts/download_vosk_model.sh
ls models/vosk/pt-br          # final.mdl, HCLr.fst, Gr.fst, ivector/, ...
```

---

## 2. Rodar a aplicação

O macOS não tem `nmcli`, então desligue o gerenciamento de Wi-Fi:

```bash
venv/bin/python main.py --no-wifi --port 5000
```

Sem microfone/modelo (ou para focar só na interface):

```bash
venv/bin/python main.py --no-wifi --no-voice --port 5000
```

Abra **http://127.0.0.1:5000**. O log aparece no terminal e em `logs/zee.log`.

Para simular o comportamento do dispositivo, abra o Chrome/Chromium assim:

```bash
open -a "Google Chrome" --args --app=http://127.0.0.1:5000 --window-size=1024,600
```

---

## 3. Testar a interface

1. **Home** — abelha (SVG placeholder até você colocar `zee.png`), texto
   `Diga "Oi, Zee"` e o botão **MENU**.
2. **MENU** → quatro cards com a contagem de itens de cada tipo.
3. **VÍDEOS / ÁUDIOS / LIVROS / JOGOS** → listagens vindas do JSON.
4. **Conteúdo** → vídeo em iframe, player de áudio próprio, PDF em iframe,
   jogo em iframe. O botão **VOLTAR** existe em todas as telas.
5. `Esc` volta para a Home (atalho de desenvolvimento).

### Conferir as resoluções do LCD

No Chrome: `Cmd+Option+I` → ícone de dispositivo (`Cmd+Shift+M`) → *Responsive*
e teste **800×480**, **1024×600**, **1280×800** e **1920×1080**.
Em telas baixas o layout compacta a abelha e o botão automaticamente.

### Conteúdo dinâmico

```bash
# em outro terminal, com o app rodando
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('data/recursos.json')
d = json.loads(p.read_text(encoding='utf-8'))
d['recursos'].append({"id":"rec_teste","tipo":"jogo","titulo":"Jogo de Teste",
                      "descricao":"Adicionado em tempo de execução.",
                      "url":"https://example.com/jogo.html"})
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
PY
```

Volte ao MENU → JOGOS: o item aparece **sem reiniciar** o serviço.
(Depois remova o item de teste.)

---

## 4. Testar o fluxo de voz **sem** falar

Estes endpoints executam exatamente o mesmo caminho de decisão da voz real —
a tela navega sozinha, sem clique:

```bash
# abre o vídeo automaticamente
curl -s -X POST localhost:5000/api/voice/simulate \
  -H 'Content-Type: application/json' \
  -d '{"text":"quero assistir ao vídeo de introdução à inteligência artificial"}' \
  | python3 -m json.tool

# "não encontrei" -> volta para a Home em 5 s
curl -s -X POST localhost:5000/api/voice/simulate \
  -H 'Content-Type: application/json' -d '{"text":"quero uma receita de bolo"}'

# só a busca, sem mexer no estado (ideal para calibrar o limiar)
curl -s -X POST localhost:5000/api/voice/match \
  -H 'Content-Type: application/json' -d '{"text":"quero o podcast de inteligência artificial"}' \
  | python3 -m json.tool
```

Ranking completo de qualquer frase, direto no terminal:

```bash
venv/bin/python scripts/voice_test.py match "quero jogar o jogo do alfabeto"
```

Acompanhar os eventos que o backend envia para a tela:

```bash
curl -N localhost:5000/api/events
```

### A regra do wakeword

```bash
curl -s -X POST localhost:5000/api/navigation -H 'Content-Type: application/json' \
     -d '{"view":"menu"}'          # {"state":"MENU","wakeword_enabled":false}
curl -s -X POST localhost:5000/api/navigation/home
                                   # {"state":"HOME_LISTENING","wakeword_enabled":true}
```

---

## 5. Testar a wakeword sem microfone

A decisão (aceitar/recusar) é testável isoladamente:

```bash
venv/bin/python scripts/voice_test.py wake                     # matriz padrão
venv/bin/python scripts/voice_test.py wake "oi zí" "oi zebra"  # frases específicas
```

Saída esperada: `oi zee`, `oi zi`, `oi zí`, `oi zé`, `oizee`, `ei zi`,
`olá zee` → **ACEITO**; `oi`, `oi zebra`, `oi zero`, `oi professora`,
`bom dia` → **recusado**.

Conferir se a gramática usa palavras que existem no modelo (a acentuação
importa: o modelo PT-BR tem `zé` e `zi`, mas **não** tem `ze` nem `zee`):

```bash
venv/bin/python scripts/voice_test.py vocab
```

---

## 6. Testar a voz de verdade, com o microfone do Mac

### Permissão de microfone

Na primeira execução o macOS pede acesso ao microfone para o **Terminal**
(ou iTerm/VS Code). Se você não vir o pedido:
**Ajustes do Sistema → Privacidade e Segurança → Microfone** → ative o app do
terminal e reinicie-o.

```bash
venv/bin/python scripts/voice_test.py devices
```

Deve listar `MacBook Pro Microphone` (ou o seu microfone externo).

### Ver o que o Vosk entende quando você fala

```bash
venv/bin/python scripts/voice_test.py wakeword
```

Fale "Oi, Zee" algumas vezes. Cada linha mostra o nível de áudio, o texto
reconhecido e as duas camadas de decisão:

```
  final   rms=  1820  texto='oi zé'  lista=100.0 estrut=100.0 score=100.0  <<< WAKEWORD
```

Gravar e interpretar um comando completo:

```bash
venv/bin/python scripts/voice_test.py command
```

### Ciclo completo (wakeword → MP3 → comando → tela)

```bash
venv/bin/python main.py --no-wifi --port 5000
```

Com o navegador aberto em `http://127.0.0.1:5000`, diga **"Oi, Zee"** e depois
o comando. A tela deve passar por `Oi! Estou ouvindo...` →
`Aguardando usuário...` → `Procurando conteúdo...` → conteúdo aberto.

Para ouvir a saudação, coloque o arquivo em
`static/assets/audio/oi_estou_ouvindo.mp3` (o macOS reproduz com `afplay`).
Sem ele, o log mostra `Welcome audio not found` e o ciclo continua.

---

## 7. Testar com fala sintética (sem falar nada)

O macOS tem vozes em português no `say`. O script abaixo gera o áudio,
alimenta o Vosk e mostra a decisão completa:

```bash
venv/bin/python scripts/dev_say_test.py
```

Saída validada neste projeto:

```
WAKEWORD — deve acionar
  OK   'Oi Zé'     -> 'oi zé'    score=100.0  ACIONA
  OK   'Oi Zê'     -> 'oi zi'    score=100.0  ACIONA
  OK   'Oi Zee'    -> 'oi zé'    score=100.0  ACIONA
  ...
WAKEWORD — não pode acionar
  OK   'Bom dia turma'   -> '[unk]'  score=0.0  ignora
  OK   'Oi professora'   -> 'oi'     score=0.0  ignora
  ...
COMANDOS — transcrição + busca
  falado    : 'quero ouvir o podcast de inteligência artificial'
  transcrito: 'quero ouvir o pode se de inteligência artificial'
  resultado : open conf=100.0 tipo=audio -> rec_002 (Podcast de Inteligência Artificial)
```

Frases específicas:

```bash
venv/bin/python scripts/dev_say_test.py "Oi Zi" "Oi Zeca"
venv/bin/python scripts/dev_say_test.py --comando "quero jogar o jogo do alfabeto"
venv/bin/python scripts/dev_say_test.py --voz Felipe        # outra voz pt-BR
```

Vozes em português instaladas:

```bash
say -v '?' | grep pt_BR      # se não houver, instale em Ajustes → Acessibilidade → Conteúdo Falado
```

> **Nota importante descoberta nos testes:** o modelo pequeno **não transcreve
> siglas soletradas** — "ABC" vira `se`, "IA" vira `dia`. Por isso os recursos
> aceitam **apelidos**; veja a seção 9.

---

## 8. Testar as telas de Wi-Fi (sem criar rede)

A tela do dispositivo e a página do celular podem ser inspecionadas no Mac:

```bash
# tela do dispositivo: QR Code + SSID + URL
curl -s -X POST localhost:5000/api/navigation -H 'Content-Type: application/json' \
     -d '{"view":"wifi"}'
# ...e olhe o navegador; para voltar:
curl -s -X POST localhost:5000/api/navigation/home
```

```bash
open http://127.0.0.1:5000/setup                 # página do captive portal
open http://127.0.0.1:5000/api/wifi/qrcode.svg   # QR Code isolado
```

No `/setup` a lista de redes fica vazia (não há `nmcli`), mas o layout,
o campo de senha, o estado "conectando" e as mensagens de erro são testáveis.
Simule o retorno da API com uma resposta falsa se quiser explorar a lista:

```bash
curl -s -X POST localhost:5000/api/wifi/connect -H 'Content-Type: application/json' \
     -d '{"ssid":"MinhaRede","password":"123"}'    # 400: senha muito curta
```

O Access Point de verdade só sobe no Raspberry Pi — veja
[TESTES.md T18](TESTES.md).

---

## 9. Apelidos dos conteúdos (`aliases`)

Como o reconhecimento não lida bem com siglas, cada recurso aceita apelidos:

```json
{
  "id": "rec_004",
  "tipo": "jogo",
  "titulo": "Jogo do ABC",
  "descricao": "Jogo educacional para aprendizagem do alfabeto.",
  "url": "https://conteudos.exemplo.com/jogos/abc.html",
  "aliases": ["jogo do alfabeto", "jogo das letras", "abecedário"]
}
```

Os apelidos pontuam como o título:

```bash
venv/bin/python scripts/voice_test.py match "quero jogar o jogo do alfabeto"
# -> 100.0  rec_004  [jogo] Jogo do ABC
```

**Regra prática:** escreva títulos e apelidos com palavras inteiras
("inteligência artificial", "alfabeto"), não com siglas ("IA", "ABC").

---

## 10. Testes automatizados

```bash
venv/bin/python -m pytest            # 203 testes
venv/bin/python -m pytest -v tests/test_matcher.py
venv/bin/python -m pytest -k wakeword
```

Não exigem microfone, rede nem modelo — rodam em ~1 segundo.

---

## 11. Diferenças macOS × Raspberry Pi

| Item | macOS | Raspberry Pi OS |
|---|---|---|
| Player de MP3 | `afplay` (nativo) | `mpg123` (instalado pelo `install.sh`) |
| Áudio de entrada | CoreAudio via PortAudio | ALSA via PortAudio |
| Gerenciamento de Wi-Fi | não disponível (`--no-wifi`) | `nmcli` (NetworkManager) |
| Inicialização | manual (`main.py`) | `systemd` + autostart do Chromium |
| Porta 80 (captive portal) | não usada | usada no modo de configuração |
| Desempenho do Vosk | carrega em ~0,1 s | carrega em ~1–3 s |

Os dois primeiros já estão contemplados: `config/config.json` lista
`afplay` **e** `mpg123` em `voice.audio_players`, e o primeiro encontrado é usado.

---

## 12. Checklist rápido antes de levar para o Raspberry Pi

```bash
venv/bin/python -m pytest                        # 1) testes verdes
venv/bin/python scripts/voice_test.py wake       # 2) wakeword decide certo
venv/bin/python scripts/voice_test.py vocab      # 3) gramática existe no modelo
venv/bin/python scripts/dev_say_test.py          # 4) voz ponta a ponta
python3 -m json.tool data/recursos.json > /dev/null   # 5) JSON válido
python3 -m json.tool config/config.json > /dev/null   # 6) config válido
```

Depois, no Pi: `./scripts/install.sh` ([INSTALACAO.md](INSTALACAO.md)) e o
roteiro completo de [TESTES.md](TESTES.md).

---

## 13. Limpeza

```bash
pkill -f "main.py"          # para a aplicação
rm -rf venv                 # remove o ambiente virtual
rm -rf models/vosk/pt-br    # remove o modelo (~50 MB)
: > logs/zee.log            # esvazia o log
```
