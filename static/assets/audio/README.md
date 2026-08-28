# Áudios do sistema

O Zee fala por meio de quatro arquivos locais (nada de TTS). Cada um marca um
momento do fluxo e é tocado pelo alto-falante do dispositivo:

| Arquivo | Quando toca | Configuração |
|---|---|---|
| `saudacao.mp3` | o assistente ficou pronto (a Home apareceu) | `voice.sounds.startup` |
| `pode-falar.mp3` | a wakeword "Oi, Zee" foi reconhecida | `voice.sounds.wakeword` |
| `encontrei.mp3` | o pedido foi entendido (conteúdo, listagem ou menu) | `voice.sounds.found` |
| `erro.mp3` | o pedido não foi entendido | `voice.sounds.error` |

Trocar qualquer um deles é só substituir o arquivo (mesmo nome) ou apontar outro
caminho em `config/config.json` → `voice.sounds`.

## Regras de comportamento

* **Enquanto um som toca, a wakeword fica suspensa** — o Zee não pode escutar a
  si mesmo pelo microfone. Depois do fim ainda há um pequeno silêncio de guarda
  (`voice.sound_tail_silence_seconds`, padrão 0,4 s) para o eco não virar
  wakeword.
* **Um aviso novo interrompe o anterior**: se o usuário pedir algo enquanto a
  saudação ainda toca, a saudação é cortada.
* **O aviso de erro é aguardado até o fim** antes de a tela voltar para a Home,
  mesmo que o áudio dure mais que `app.error_auto_return_seconds`.
* **Arquivo ausente não trava nada**: o sistema registra `<Nome> not found` no
  log e segue o fluxo normalmente.

## Formato recomendado

MP3 mono, 44,1 kHz, 96–128 kbps. Mantenha os avisos curtos — `pode-falar.mp3`
entra no caminho crítico entre a wakeword e a gravação do comando (o ideal é
ficar abaixo de 2 segundos).

## Testar

```bash
# um som isolado, pelo alto-falante do dispositivo
curl -X POST localhost:5000/api/voice/sound -H 'Content-Type: application/json' \
     -d '{"name":"wakeword"}'      # startup | wakeword | found | error

# direto pelo player, sem passar pela aplicação
mpg123 static/assets/audio/pode-falar.mp3     # Raspberry Pi
afplay static/assets/audio/pode-falar.mp3     # macOS

# conferir o que a aplicação encontrou
curl -s localhost:5000/api/voice/status | python3 -m json.tool
```
