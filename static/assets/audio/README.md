# Áudios do sistema

* `oi_estou_ouvindo.mp3` — **obrigatório em produção**. Gravação da frase
  "Oi, estou ouvindo.", reproduzida assim que a wakeword "Oi, Zee" é detectada.
  Não é gerada por TTS: o arquivo é reproduzido diretamente.

Se o arquivo não existir, o sistema registra `Welcome audio not found` no log e
segue direto para a captura do comando — sem travar.

Formato recomendado: MP3 mono, 44.1 kHz, 96-128 kbps, com no máximo ~2 segundos.

Para testar a reprodução isoladamente no Raspberry Pi:

```bash
mpg123 static/assets/audio/oi_estou_ouvindo.mp3
```
