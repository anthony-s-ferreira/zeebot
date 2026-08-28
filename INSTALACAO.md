# Instalação do Zee Assistant

Guia completo para deixar um Raspberry Pi novo pronto para uso.

---

## 1. Pré-requisitos

**Hardware**

* Raspberry Pi 4B (4 GB)
* Cartão microSD de 16 GB ou mais (o modelo Vosk ocupa ~40 MB; o sistema, o resto)
* Tela LCD touchscreen (800×480, 1024×600, 1280×800 ou 1920×1080)
* Microfone USB **ou** I2S
* Alto-falante ou saída de áudio (P2/HDMI/USB)
* Fonte oficial de 5 V / 3 A (subtensão causa falhas aleatórias de Wi-Fi e áudio)

**Software**

* Raspberry Pi OS **64 bits** (Bookworm ou mais recente), versão **com desktop**
  — o kiosk precisa de sessão gráfica
* Acesso ao terminal (teclado ou SSH)

Confirme a arquitetura:

```bash
uname -m        # deve responder: aarch64
cat /etc/os-release
```

---

## 2. Preparar o sistema

```bash
sudo apt update && sudo apt full-upgrade -y
sudo raspi-config    # System Options → Boot / Auto Login → Desktop Autologin
```

Se o microfone for **I2S**, adicione o overlay do seu módulo em
`/boot/firmware/config.txt` **antes** de continuar, por exemplo:

```
dtoverlay=googlevoicehat-soundcard      # ajuste conforme o seu hardware
```

e reinicie.

---

## 3. Copiar o projeto

```bash
# via git
git clone <seu-repositorio> ~/zee-assistant

# ou via pendrive/scp
scp -r zee-assistant pi@<ip-do-pi>:~/
```

O diretório pode ficar em qualquer lugar (`~/zee-assistant`, `/opt/zee-assistant`, …);
o instalador usa o caminho onde o projeto estiver.

---

## 4. Executar o instalador

```bash
cd ~/zee-assistant
./scripts/install.sh
```

O que ele faz, em 12 etapas:

| # | Etapa | Detalhe |
|---|---|---|
| 1 | Verificação | arquitetura, Raspberry Pi OS, Python 3 |
| 2 | Pacotes do sistema | `python3-venv`, `python3-dev`, `libportaudio2`, `portaudio19-dev`, `libatlas-base-dev`, `alsa-utils`, `mpg123`, `unzip`, `wget`, `curl`, `network-manager` |
| 3 | Chromium | instala se ausente |
| 4 | iptables | fallback do captive portal |
| 5 | Virtualenv | `venv/` na raiz do projeto (`--copies`, para permitir `setcap`) |
| 6 | Dependências Python | `requirements.txt` |
| 7 | Modelo Vosk PT-BR | baixa `vosk-model-small-pt-0.3` para `models/vosk/pt-br` |
| 8 | Permissões | grupos `audio`/`netdev`/`video` + `/etc/sudoers.d/zee-assistant` |
| 9 | Rede | habilita NetworkManager e instala o DNS wildcard do captive portal |
| 10 | systemd | instala e habilita `zee-assistant.service` |
| 11 | Kiosk | autostart do Chromium (labwc / wayfire / LXDE) e desliga o blanking |
| 12 | Start | sobe o serviço e mostra o resumo |

Opções úteis:

```bash
./scripts/install.sh --no-model    # não baixar o modelo agora
./scripts/install.sh --no-kiosk    # não configurar o Chromium
./scripts/install.sh --no-apt      # pular a instalação de pacotes
```

O script é **idempotente**: pode ser executado novamente sem quebrar a instalação.

---

## 5. Colocar os arquivos que você fornece

```bash
cd ~/zee-assistant

# imagem oficial da abelha (PNG quadrado, fundo transparente, ~512 px)
cp /caminho/zee-circulo.mp4 static/assets/images/zee-circulo.mp4

sudo systemctl restart zee-assistant
```

Sem a imagem o sistema **não trava**: usa o desenho SVG da abelha.

Os quatro avisos sonoros já vêm no projeto:

| Arquivo | Quando toca |
|---|---|
| `static/assets/audio/saudacao.mp3` | o assistente ficou pronto |
| `static/assets/audio/pode-falar.mp3` | a wakeword foi reconhecida |
| `static/assets/audio/encontrei.mp3` | o pedido foi entendido |
| `static/assets/audio/erro.mp3` | o pedido não foi entendido |

Para trocar por outra voz, substitua os arquivos (mesmo nome) ou aponte outros
caminhos em `config/config.json` → `voice.sounds`. Arquivo ausente não trava
nada: o log registra `<Nome> not found` e o fluxo segue.

Teste o alto-falante logo após a instalação:

```bash
curl -X POST localhost:5000/api/voice/sound -H 'Content-Type: application/json' \
     -d '{"name":"startup"}'
```

### Piper TTS — leitura das respostas

O instalador completo já configura o Piper. Em uma instalação existente,
execute:

```bash
./scripts/install_piper.sh
sudo systemctl restart zee-assistant
```

A voz `pt_BR-faber-medium` funciona inteiramente offline depois do download.
Se o Piper ou o modelo estiver indisponível, a resposta permanece na tela e o
restante do assistente continua funcionando normalmente.

---

## 6. Cadastrar os conteúdos

```bash
nano data/recursos.json
```

Depois de salvar, o catálogo é recarregado automaticamente (o arquivo é
monitorado por `mtime`). Para forçar:

```bash
curl -X POST http://127.0.0.1:5000/api/resources/reload
```

---

## 7. Reiniciar e validar

```bash
sudo reboot
```

No boot esperado:

1. o serviço `zee-assistant` sobe antes da sessão gráfica;
2. o Chromium abre em tela cheia, sem barras nem abas;
3. se **não** houver Wi-Fi salvo, aparece o QR Code de configuração;
4. havendo rede, aparece a Zee com `Diga "Oi, Zee"`.

Checklist completo em [TESTES.md](TESTES.md).

---

## 8. Calibrar a wakeword (opcional)

O modelo PT-BR não conhece a grafia "zee" — ele escreve o que ouve como
"oi zé", "oi zi", "oi zí", "oi z"… **Todas essas formas já são aceitas de
fábrica** pela análise estrutural (saudação + nome, veja o [README §6.1](README.md#61-como-oi-zee-é-reconhecido)).
Confira sem sair do computador:

```bash
venv/bin/python scripts/voice_test.py wake
```

Se ainda assim o seu microfone produzir algo diferente, descubra o que **ele**
gera na prática:

```bash
sudo systemctl stop zee-assistant          # libera o microfone
venv/bin/python scripts/voice_test.py wakeword
```

Fale "Oi, Zee" algumas vezes e observe as linhas impressas:

```
  final   rms=  1820  texto='oi zé'  lista=100.0 estrut=100.0 score=100.0  <<< WAKEWORD
```

Se o texto reconhecido **não** for aceito, há duas saídas:

* a forma do nome é diferente (ex.: o modelo escreveu `oi si`) → acrescente-a em
  `voice.wakeword.structural.names`;
* a frase inteira é atípica (ex.: `alô zezinho`) → acrescente-a em
  `voice.wakeword.phrases`, e também em `grammar_phrases` se as palavras
  existirem no modelo.

Depois:

```bash
sudo systemctl start zee-assistant
```

Ajustes finos:

| Sintoma | Ajuste |
|---|---|
| Não reconhece | baixe `fuzzy_threshold` para 76–78; adicione formas em `structural.names` |
| Dispara sozinho | suba `fuzzy_threshold` para 86–90; reduza `max_words` para 3; reduza `structural.max_name_length` para 2 |
| Corta a fala do comando | aumente `silence_duration_seconds` para 1.6 |
| Demora a processar | reduza `silence_duration_seconds` para 0.9 |
| Não ouve fala baixa | reduza `silence_rms_threshold` para ~200 |

---

## 9. Instalação em modo desenvolvimento (PC, sem Raspberry)

Guia completo para macOS: **[TESTES-LOCAIS.md](TESTES-LOCAIS.md)**.
Em resumo:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt
venv/bin/python main.py --no-voice --no-wifi --port 5000 --debug
```

Abra `http://127.0.0.1:5000`. Simule comandos de voz por HTTP:

```bash
curl -X POST localhost:5000/api/voice/simulate \
     -H 'Content-Type: application/json' \
     -d '{"text":"quero assistir ao vídeo de introdução à inteligência artificial"}'
```

A tela navega sozinha, exatamente como aconteceria com a voz real.

---

## 10. Desinstalação

```bash
./scripts/uninstall.sh
```

Remove serviço, autostart, sudoers, DNS do portal e o perfil `zee-setup-ap`.
O código, os logs, o modelo e o `recursos.json` são preservados.
