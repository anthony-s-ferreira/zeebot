# 🐝 Zee Assistant

Assistente educacional interativo para **Raspberry Pi 4B (4 GB, Raspberry Pi OS 64 bits)**
com tela touchscreen, reconhecimento de voz **100% offline** (Vosk PT-BR) e biblioteca
multimídia (vídeos, áudios, livros e jogos) carregada de um JSON local.

```
                    🐝
              Diga "Oi, Zee"

                 [ MENU ]
```

* **Voz** — na Home o dispositivo escuta continuamente a wakeword *"Oi, Zee"*.
  Ao detectar, toca um MP3 local ("Oi, estou ouvindo."), grava o comando,
  transcreve localmente, interpreta e abre o conteúdo sozinho.
* **Toque** — o botão **MENU** dá acesso a Vídeos, Áudios, Livros e Jogos.
* **Wi-Fi** — no primeiro boot o Pi cria a rede `Zee-Setup-XXXX`, mostra um QR Code
  na tela e serve um captive portal para o celular escolher a rede da escola.
* **Sem nuvem** — nenhum serviço externo de reconhecimento de voz é usado.

Documentos complementares:

| Documento | Conteúdo |
|---|---|
| [INSTALACAO.md](INSTALACAO.md) | Passo a passo da instalação em um Pi novo |
| [TESTES.md](TESTES.md) | Como testar **cada** funcionalidade no Raspberry Pi |
| [TESTES-LOCAIS.md](TESTES-LOCAIS.md) | Como testar no seu Mac, **sem** o Raspberry Pi |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Soluções para os problemas mais comuns |

---

## 1. Arquitetura

### Decisões e por quê

| Decisão | Motivo |
|---|---|
| **Um único processo Python** com 3 threads (HTTP, voz, rede) | O Pi 4B tem 4 GB; um processo evita duplicar o modelo Vosk na memória e elimina IPC entre voz e interface. O estado vive em memória, protegido por locks. |
| **Flask + Werkzeug (threaded)** | Servidor local mínimo. Nada de Gunicorn/uWSGI: um cliente (o Chromium do kiosk) não justifica o overhead. |
| **Server-Sent Events** para backend → frontend | Precisamos apenas de um canal unidirecional ("abra o recurso X"). SSE é HTTP puro, reconecta sozinho no navegador e não traz dependências extras — mais simples que WebSocket e mais robusto que polling (que segue como *fallback* automático no JS). |
| **Vosk com gramática restrita no estágio 1** | Ouvir o tempo todo com o modelo completo consome CPU e gera falsos positivos. A gramática limita o reconhecedor a um punhado de frases. |
| **Wakeword em 3 camadas** (gramática → lista → estrutura) | O modelo PT-BR não tem "zee" no vocabulário: ele escreve "oi zé", "oi zi", "oi zí", "oi z"… A análise estrutural (saudação + nome) reconhece todas essas formas sem listar cada uma. |
| **RapidFuzz + normalização** | Busca tolerante a acentos, pontuação e frases naturais, sem nenhum modelo de linguagem pesado. |
| **NetworkManager (`nmcli`)** | É o gerenciador padrão do Raspberry Pi OS atual; dispensa hostapd/dnsmasq manuais — o modo `shared` já sobe DHCP e DNS. |
| **HTML/CSS/JS puro** | Sem React/Vue/Angular e sem Electron: o Chromium em kiosk carrega ~100 KB de assets. |
| **Máquina de estados explícita** | A regra "wakeword só na Home" é uma consequência do estado, não de `if`s espalhados. |

### Diagrama de blocos

```
┌──────────────────────────── Raspberry Pi 4B ────────────────────────────┐
│                                                                         │
│  Chromium (kiosk, 127.0.0.1:5000)                                       │
│        │  HTTP + SSE                                                    │
│  ┌─────▼──────────────────────────────────────────────────────────┐     │
│  │ main.py — processo único                                       │     │
│  │                                                                │     │
│  │  ┌────────────┐   ┌───────────────┐   ┌──────────────────────┐ │     │
│  │  │ server.py  │   │ voice/engine  │   │ network/manager      │ │     │
│  │  │ Flask+SSE  │   │ (thread)      │   │ (thread)             │ │     │
│  │  └─────┬──────┘   └───────┬───────┘   └──────────┬───────────┘ │     │
│  │        │                  │                      │             │     │
│  │        └────────► state.py (StateMachine) ◄──────┘             │     │
│  │                      │  events.py (EventBus → SSE)             │     │
│  │        ┌─────────────┴───────────────┐                         │     │
│  │  resources.py                 voice/matcher.py                 │     │
│  │  (data/recursos.json)         (RapidFuzz + intenção)           │     │
│  └────────────────────────────────────────────────────────────────┘     │
│         │                    │                         │                │
│    microfone            alto-falante              wlan0 / nmcli         │
│    (Vosk PT-BR)         (mpg123)                  AP + captive portal   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Máquina de estados

```
                    ┌───────────┐
                    │  BOOTING  │
                    └─────┬─────┘
              sem Wi-Fi   │   Wi-Fi ok
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌───────────────┐  conectou        ┌─────────────────┐
│  WIFI_SETUP   ├─────────────────►│ HOME_LISTENING  │◄────────┐
│ (AP + QR + 80)│                  │  wakeword = ON  │         │
└───────────────┘                  └────────┬────────┘         │
                                     "Oi,Zee"│                 │
                                            ▼                  │
                                  ┌────────────────────┐       │
                                  │ WAKEWORD_DETECTED  │ MP3   │
                                  └─────────┬──────────┘       │
                                            ▼                  │
                                  ┌────────────────────┐       │
                                  │   WAITING_USER     │ grava │
                                  └─────────┬──────────┘       │
                                            ▼                  │
                                  ┌────────────────────┐       │
                                  │ PROCESSING_COMMAND │ busca │
                                  └─────────┬──────────┘       │
                    ┌───────────────────────┼───────────────┐  │
                    ▼                       ▼               ▼  │
            ┌───────────────┐      ┌────────────────┐  ┌───────┴──────┐
   toque ──►│     MENU      │─────►│ RESOURCE_LIST  │─►│RESOURCE_VIEW │
            └───────┬───────┘      └───────┬────────┘  └──────┬───────┘
                    │  wakeword = OFF em TODOS estes estados  │
                    └────────────── VOLTAR ───────────────────┘
                                 (Home reativa o wakeword)
```

**Regra obrigatória implementada em [`app/state.py`](app/state.py):**
`wakeword_enabled == True` **somente** quando `state == HOME_LISTENING`
(e com microfone + modelo disponíveis). Qualquer navegação — inclusive o toque
em MENU — desliga a escuta na mesma transição, e o motor de voz **fecha o
dispositivo de áudio**, não apenas ignora o que chega.

---

## 2. Estrutura do projeto

```
zee-assistant/
├── main.py                       # ponto de entrada (servidor + threads)
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
│
├── app/
│   ├── config.py                 # configuração central (merge com padrões)
│   ├── logging_setup.py          # logging rotativo + redação de senhas
│   ├── events.py                 # EventBus (SSE)
│   ├── state.py                  # máquina de estados + regra do wakeword
│   ├── resources.py              # catálogo (data/recursos.json)
│   ├── audio.py                  # microfone + reprodução de MP3
│   ├── services.py               # composição das dependências
│   ├── server.py                 # Flask: páginas, API e /api/events
│   │
│   ├── voice/
│   │   ├── engine.py             # thread de voz (ciclo wakeword → comando)
│   │   ├── wakeword.py           # gramática + variações "oi zee"
│   │   ├── recognizer.py         # Vosk + captura com silêncio/timeout
│   │   ├── matcher.py            # busca fuzzy + intenção + confiança
│   │   └── mic.py                # stream PortAudio (abre/fecha explicitamente)
│   │
│   ├── network/
│   │   ├── wifi.py               # wrapper nmcli (scan, connect, AP)
│   │   ├── manager.py            # supervisor: setup / recuperação
│   │   └── captive_portal.py     # servidor HTTP do portal (porta 80)
│   │
│   └── utils/
│       ├── text.py               # normalização, stopwords, tipos
│       ├── fuzzy.py              # RapidFuzz (com fallback stdlib)
│       └── proc.py               # subprocess seguro (sem shell=True)
│
├── templates/
│   ├── index.html                # aplicação (Home, Menu, Listas, Conteúdo)
│   └── portal.html               # captive portal (celular)
│
├── static/
│   ├── css/app.css               # interface do dispositivo
│   ├── css/portal.css            # interface do captive portal
│   ├── js/app.js                 # roteador, SSE, players
│   ├── js/portal.js              # seleção de rede e senha
│   └── assets/
│       ├── images/zee.svg        # placeholder (troque por zee.png)
│       └── audio/                # oi_estou_ouvindo.mp3 (você fornece)
│
├── data/recursos.json            # conteúdos (editável em produção)
├── config/
│   ├── config.json               # TODAS as constantes ajustáveis
│   └── system/
│       ├── zee-assistant.sudoers      # permissões mínimas (nmcli/iptables)
│       └── zee-captive.dnsmasq.conf   # DNS wildcard do captive portal
│
├── models/vosk/                  # modelo PT-BR (baixado na instalação)
├── scripts/
│   ├── install.sh                # instalação completa
│   ├── configure_kiosk.sh        # autostart do Chromium
│   ├── kiosk.sh                  # lança o Chromium em kiosk
│   ├── download_vosk_model.sh    # baixa o modelo PT-BR
│   ├── voice_test.py             # calibração da voz (essencial!)
│   ├── check_audio.sh            # diagnóstico de áudio
│   └── uninstall.sh
│
├── systemd/
│   ├── zee-assistant.service     # serviço principal (Restart=always)
│   └── zee-kiosk.service         # opcional (kiosk via systemd --user)
│
├── tests/                        # 203 testes (pytest)
└── logs/zee.log                  # log rotativo
```

---

## 3. Instalação rápida

```bash
git clone <seu-repo> zee-assistant     # ou copie a pasta para o Pi
cd zee-assistant
./scripts/install.sh
sudo reboot
```

O instalador cuida de: pacotes do sistema, virtualenv, dependências Python,
modelo Vosk PT-BR, grupos e sudoers, serviço systemd, DNS do captive portal e
autostart do Chromium em kiosk. Detalhes em **[INSTALACAO.md](INSTALACAO.md)**.

Depois da instalação, coloque os dois arquivos que você fornece:

```bash
cp minha-abelha.png   static/assets/images/zee.png
cp minha-saudacao.mp3 static/assets/audio/oi_estou_ouvindo.mp3
sudo systemctl restart zee-assistant
```

---

## 4. Configuração central (`config/config.json`)

Nenhuma constante fica espalhada pelo código. Chaves principais:

```jsonc
{
  "app": {
    "port": 5000,                       // porta da interface
    "resources_file": "data/recursos.json",
    "auto_reload_resources": true,      // relê o JSON quando o arquivo muda
    "error_auto_return_seconds": 5      // volta à Home após "não encontrei"
  },
  "voice": {
    "enabled": true,
    "model_path": "models/vosk/pt-br",
    "welcome_audio": "static/assets/audio/oi_estou_ouvindo.mp3",
    "input_device": null,               // índice ou parte do nome do microfone
    "wakeword": {
      "phrases": ["oi zee", "oi zi", "oi zí", "oi zé", "oizee", "..."],
      "use_grammar": true,              // estágio 1 com vocabulário restrito
      "grammar_phrases": ["oi", "oi zé", "oi zi", "oi z"],
      "fuzzy_threshold": 82,            // ↑ mais rígido, ↓ mais sensível
      "phrase_threshold": 90,           // exigência da lista de variações
      "max_words": 4,                   // frases longas nunca são wakeword
      "cooldown_seconds": 2.0,
      "structural": {                   // reconhece "saudação + nome" (ver §6.1)
        "enabled": true,
        "greetings": ["oi", "ei", "olá", "alô", "opa"],
        "names": ["ze", "zi", "z", "zey", "zin"],
        "name_threshold": 74,
        "max_name_length": 3            // barra "zebra", "zero", "senhor"...
      }
    },
    "command": {
      "max_record_seconds": 10,         // teto da gravação
      "no_speech_timeout_seconds": 5.0, // desiste se ninguém falar
      "silence_rms_threshold": 350,     // sensibilidade do fim de fala
      "silence_duration_seconds": 1.2   // silêncio que encerra a captura
    }
  },
  "matching": {
    "confidence_threshold": 70,         // abre automaticamente a partir daqui
    "ambiguity_margin": 8,              // scores mais próximos que isso => opções
    "max_suggestions": 4,
    "synonyms": { "ia": "inteligencia artificial" }
  },
  "network": {
    "manage_wifi": true,
    "ap_ssid_prefix": "Zee-Setup",
    "ap_password": "",                  // vazio = rede aberta (QR mais simples)
    "ap_address": "10.42.0.1",
    "wifi_recovery_timeout_seconds": 60 // sem rede por 60s => volta ao setup
  },
  "logging": { "level": "INFO", "file": "logs/zee.log", "max_bytes": 1048576 }
}
```

Após editar: `sudo systemctl restart zee-assistant`.

---

## 5. Conteúdos (`data/recursos.json`)

```json
{
  "recursos": [
    {
      "id": "rec_001",
      "tipo": "video",
      "titulo": "Introdução à Inteligência Artificial",
      "descricao": "Vídeo apresentando os principais conceitos de IA.",
      "url": "https://www.youtube.com/watch?v=XXXXXXXXXXX",
      "thumbnail": "https://.../capa.jpg",
      "aliases": ["introdução à ia", "aula de inteligência artificial"]
    }
  ]
}
```

* `tipo`: `video` | `audio` | `livro` | `jogo` (aceita variações como `vídeo`, `áudios`, `pdf`).
* `thumbnail`: **opcional**; sem ela o card usa o ícone do tipo.
* `aliases` (ou `sinonimos`): **opcional**; outras formas de pedir o conteúdo por
  voz. Pontuam como o título. Úteis porque o modelo de voz **não transcreve
  siglas soletradas** — "ABC" vira `se` e "IA" vira `dia`. Prefira títulos e
  apelidos com palavras inteiras ("alfabeto", "inteligência artificial").
* Links do YouTube (`watch?v=`, `youtu.be`, `shorts`) viram `embed` automaticamente.
* Itens inválidos são **ignorados com log**, sem derrubar o restante do catálogo.
* Adicionou um item? O arquivo é relido sozinho (ou force com
  `curl -X POST localhost:5000/api/resources/reload`).

---

## 6. Fluxo de voz

```
HOME_LISTENING ── "Oi, Zee" ──► WAKEWORD_DETECTED
                                     │ 1. para de escutar a wakeword
                                     │ 2. toca oi_estou_ouvindo.mp3 (arquivo local)
                                     ▼
                               WAITING_USER   "Aguardando usuário..." + animação
                                     │ grava até: silêncio de 1,2 s
                                     │              ou 10 s de teto
                                     │              ou 5 s sem ninguém falar
                                     ▼
                            PROCESSING_COMMAND  "Procurando conteúdo..."
                                     │
              ┌──────────────────────┼───────────────────────┐
     score ≥ 70 e folga         empate (< 8)            nada ≥ 70
              ▼                      ▼                       ▼
        abre o conteúdo      "Encontrei mais de       "Não encontrei esse
        automaticamente       uma opção." + cards      conteúdo." → Home em 5 s
```

### 6.1 Como "Oi, Zee" é reconhecido

O modelo PT-BR do Vosk **não conhece a grafia "zee"** — dependendo do microfone e
da pronúncia ele transcreve a mesma fala como `oi zé`, `oi zi`, `oi zii`, `oi z`,
`oizee`… Por isso a detecção ([`app/voice/wakeword.py`](app/voice/wakeword.py))
acontece em três camadas:

| Camada | O que faz | Exigência |
|---|---|---|
| 1. **Gramática** | O reconhecedor do estágio 1 só aceita um punhado de frases (`grammar_phrases` + `[unk]`) — não transcreve conversas | palavras que **existam no modelo** |
| 2. **Lista de variações** | Compara a fala inteira com `phrases` (sem acentos, com letras repetidas colapsadas) | similaridade ≥ `phrase_threshold` (90) |
| 3. **Análise estrutural** | Quebra a fala em **saudação + nome** e valida cada parte separadamente | saudação ≥ 80, nome ≥ 74 e nome com 2 a 4 letras |

> **Atenção à acentuação na gramática.** O Vosk só aceita palavras que existam
> no vocabulário do modelo — e o PT-BR conhece `zé` e `zi`, mas **não** conhece
> `ze` nem `zee`. Por isso `grammar_phrases` guarda a grafia acentuada, enquanto
> a comparação (camadas 2 e 3) trabalha sem acentos. Confira a sua gramática com
> `venv/bin/python scripts/voice_test.py vocab`.

A camada 3 é a que dá a tolerância de verdade:

```
"Oi, Zeee!"  → normaliza → "oi zeee" → colapsa repetições → "oi ze"
                                        │            │
                          saudação ─────┘            └───── nome
                     "oi" ≈ oi/ei/olá/alô/opa      "ze" ≈ ze/zi/z/zey/zin
```

Como acentos são removidos e letras repetidas colapsadas, **"oi zee", "oi zi",
"oi zí", "oi zé", "oi ze", "oi zii", "oi z", "oizee", "ei zi", "olá zee" e
"opa zi" caem todas no mesmo lugar** — sem precisar listar cada grafia.

Os limites de tamanho do nome (2 a 4 letras) são o que impede falsos positivos:
`oi zebra`, `oi zero`, `oi senhor`, `oi maria`, `oi professora`, `oi z` e até
`oi` sozinho são recusados. Um nome **sozinho** (`zé`, sem o `oi`) também não
dispara — com a gramática ativa, qualquer conversa próxima acabaria encaixada na
palavra mais parecida da lista. Se o seu microfone cortar o início da fala, ligue
`voice.wakeword.structural.allow_name_only`.

Limitação conhecida: com a gramática ativa, uma frase foneticamente muito
próxima ("oi, Zebra") pode ser transcrita como `oi zé` e acionar o assistente.
O cooldown e o timeout da captura seguinte limitam o incômodo.

Teste qualquer frase sem microfone:

```bash
venv/bin/python scripts/voice_test.py wake              # matriz padrão
venv/bin/python scripts/voice_test.py wake "oi zí"      # uma frase específica
venv/bin/python scripts/voice_test.py vocab             # gramática × vocabulário
```

No macOS dá para validar com fala sintética, sem falar no microfone:
`venv/bin/python scripts/dev_say_test.py` (ver [TESTES-LOCAIS.md](TESTES-LOCAIS.md)).

**Como o comando vira uma busca** (`app/voice/matcher.py`):

1. normaliza (minúsculas, sem acentos, sem pontuação, espaços colapsados);
2. expande sinônimos (`ia` → `inteligencia artificial`);
3. detecta o tipo por palavras-chave (`assistir/vídeo` → `video`, `ouvir/podcast` → `audio`,
   `ler/livro/pdf` → `livro`, `jogar/jogo/brincar` → `jogo`);
4. remove stopwords e as próprias palavras de tipo, sobrando o **assunto**;
5. pontua cada recurso: `0,5 × RapidFuzz WRatio + 0,5 × cobertura de palavras`
   contra o título **e os apelidos** (a descrição só pode *elevar* a nota,
   nunca derrubá-la);
6. aplica bônus/penalidade de tipo (`+12` / `−25`);
7. decide: abrir, oferecer opções ou avisar que não encontrou.

> A cobertura de palavras evita um erro clássico: para *"abra fundamentos de
> inteligência artificial"*, o `token_set_ratio` puro daria 100 tanto para
> *"Fundamentos de IA"* quanto para *"Podcast de IA"*. Contando quantas palavras
> do comando o título realmente cobre, o item certo vence com folga.

---

## 7. Configuração de Wi-Fi (primeiro boot)

```
Pi liga ──► NetworkManager tenta os perfis salvos (até 45 s)
                    │                        │
             conectou│                        │não conectou
                    ▼                        ▼
             HOME_LISTENING          WIFI_SETUP
                                     ├─ nmcli cria o AP  Zee-Setup-XXXX (10.42.0.1)
                                     ├─ captive portal na porta 80
                                     ├─ dnsmasq responde qualquer domínio → 10.42.0.1
                                     └─ LCD mostra o QR Code (padrão WIFI:)
                                            │
                            celular escaneia, entra na rede,
                            o portal abre sozinho (ou http://10.42.0.1)
                                            │
                            escolhe a rede + senha → CONECTAR
                                            │
                     AP cai → nmcli conecta → verifica IP + internet
                          │                              │
                    falhou│                              │ok
                          ▼                              ▼
              AP volta imediatamente             "Conectado!" → Home
              "Verifique a senha e                (AP e portal desligados)
               tente novamente."
```

* **Recuperação**: se o dispositivo for levado para outra escola e ficar
  `wifi_recovery_timeout_seconds` (padrão 60 s) sem rede **estando ocioso na Home**,
  ele volta sozinho ao modo de configuração. Nunca interrompe um conteúdo em uso.
* **A senha nunca é registrada**: não vai para o log, é apagada da memória logo
  após o uso e, mesmo assim, um filtro de redação atua como rede de segurança.

---

## 8. API local

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/` | Aplicação (Home/Menu/Listas/Conteúdo) |
| `GET` | `/setup` | Prévia do captive portal (útil para testar no desktop) |
| `GET` | `/healthz` | Liveness do serviço |
| `GET` | `/api/status` | Estado, microfone, modelo, rede, contagens, limiares |
| `GET` | `/api/resources` · `?tipo=video` | Catálogo completo ou filtrado |
| `GET` | `/api/resources/<id>` | Um recurso (com `embed_url`) |
| `POST` | `/api/resources/reload` | Relê o JSON imediatamente |
| `GET` | `/api/events` | **SSE**: `state`, `action`, `wifi`, `transcript`, … |
| `POST` | `/api/navigation` | `{"view":"home\|menu\|list\|resource\|error\|wifi"}` |
| `POST` | `/api/navigation/home` | Volta à Home e **reativa a wakeword** |
| `GET` | `/api/voice/status` | Modelo, microfone, gramática, última transcrição |
| `POST` | `/api/voice/simulate` | `{"text":"..."}` — executa o ciclo **sem microfone** |
| `POST` | `/api/voice/match` | `{"text":"..."}` — só a busca, sem mexer no estado |
| `GET` | `/api/wifi/status` · `/networks` | Estado da rede · redes visíveis |
| `POST` | `/api/wifi/connect` | `{"ssid":"...","password":"..."}` |
| `POST` | `/api/wifi/setup` | `{"action":"start"\|"stop"}` |
| `GET` | `/api/wifi/qrcode.svg` | QR Code da rede de configuração |

Exemplo de evento SSE que faz a tela navegar sozinha:

```json
{ "type": "action", "data": { "action": "open_resource", "resource_id": "rec_001" } }
```

---

## 9. Operação

```bash
sudo systemctl status zee-assistant       # estado do serviço
sudo systemctl restart zee-assistant      # reiniciar
journalctl -u zee-assistant -f            # log do systemd
tail -f logs/zee.log                      # log da aplicação (rotativo, 5×1 MB)

venv/bin/python scripts/voice_test.py devices    # microfones detectados
venv/bin/python scripts/voice_test.py wake       # decisão da wakeword (sem microfone)
venv/bin/python scripts/voice_test.py wakeword   # o que o Vosk ouve (calibração)
venv/bin/python scripts/voice_test.py vocab      # gramática × vocabulário do modelo
./scripts/check_audio.sh                          # diagnóstico de áudio
```

O log registra inicialização, transições de estado, microfone detectado, modelo
carregado, wakeword detectada, transcrição, recurso escolhido, erros e eventos de
rede — **nunca** a senha do Wi-Fi.

---

## 10. Testes

```bash
venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest          # 203 testes
```

Cobertura: parser do JSON (incluindo apelidos), conversão de URLs do YouTube,
normalização de texto, classificação de intenção, busca fuzzy (todos os comandos
do enunciado), níveis de confiança/ambiguidade, wakeword (26 variações aceitas e
33 recusas, gramática e camada estrutural), regra de estados do wakeword,
API HTTP, validação de SSID/senha e redação de segredos no log.

Os procedimentos manuais no Raspberry Pi (voz real, Wi-Fi, kiosk, boot) estão em
**[TESTES.md](TESTES.md)**; para validar no seu Mac, veja
**[TESTES-LOCAIS.md](TESTES-LOCAIS.md)**.

---

## 11. Desempenho no Pi 4B

Escolhas para manter o dispositivo fluido:

* modelo Vosk **small** (~31 MB em disco, ~80 MB residentes) — nada de Whisper;
* estágio 1 com gramática restrita: o reconhecedor não processa frases completas;
* microfone **fechado** (não apenas ignorado) fora da Home e durante a reprodução do MP3;
* iframes destruídos ao sair da tela de conteúdo — nunca há dois abertos;
* animações CSS só de `transform`/`opacity`, sem blur nem sombras animadas;
* SVG inline no lugar de bibliotecas de ícones;
* um processo, três threads — sem Electron, sem framework frontend, sem broker.

Consumo típico em repouso: ~150–200 MB de RAM e CPU baixa entre comandos.

---

## 12. Expansão futura

A arquitetura já está preparada (nada disso está implementado):

* **Novos tipos de recurso**: acrescente em `VALID_TYPES` (`app/resources.py`),
  um ícone no `templates/index.html` e uma entrada no mapa `RENDERERS`
  (`static/js/app.js`). O matcher aprende o tipo adicionando palavras em
  `TYPE_KEYWORDS` (`app/utils/text.py`).
* **Conteúdo local** (vídeos/PDFs/MP3/jogos no cartão SD): sirva a pasta como
  rota estática e use URLs relativas no JSON — os renderizadores não distinguem.
* **PDF.js** no lugar do iframe: troque apenas `RENDERERS.livro`.
* **Respostas por IA / APIs externas**: o `VoiceEngine.handle_transcript` é o
  ponto único onde a transcrição vira ação.
* **Sincronização remota do JSON / OTA**: `ResourceLibrary` já recarrega por
  `mtime`; basta um job que atualize o arquivo.

---

## 13. Licença e créditos

Projeto desenvolvido para uso educacional.
Modelo de voz: [Vosk](https://alphacephei.com/vosk/) (Apache 2.0).
