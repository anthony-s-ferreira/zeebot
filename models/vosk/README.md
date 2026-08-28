# Modelo Vosk (PT-BR)

O sistema espera o modelo descompactado em:

```
models/vosk/pt-br/
```

O sistema aceita os **dois formatos** distribuídos pelo projeto Vosk:

```
# modelos "small" (recomendados) — estrutura plana
models/vosk/pt-br/final.mdl  HCLr.fst  Gr.fst  mfcc.conf  phones.txt  ivector/

# modelos grandes — com subpastas
models/vosk/pt-br/am/final.mdl  graph/  conf/  ivector/
```

Se você descompactar e sobrar um nível a mais
(`models/vosk/pt-br/vosk-model-small-pt-0.3/...`), a aplicação detecta e usa a
subpasta automaticamente, registrando um aviso no log.

## Instalação automática

```bash
./scripts/download_vosk_model.sh
```

## Instalação manual

```bash
cd models/vosk
wget https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip
unzip vosk-model-small-pt-0.3.zip
mv vosk-model-small-pt-0.3 pt-br
rm vosk-model-small-pt-0.3.zip
```

## Qual modelo usar?

| Modelo | Tamanho | Uso no Pi 4B |
|---|---|---|
| `vosk-model-small-pt-0.3` | ~31 MB | **Recomendado** — rápido, cabe folgado na RAM |
| `vosk-model-pt-fb-v0.1.1-20220516_2113` | ~1,6 GB | Não recomendado no Pi 4B de 4 GB |

O caminho é configurável em `config/config.json` → `voice.model_path`.

Se o modelo não existir, a aplicação registra o erro, desativa apenas a voz e
continua funcionando pelo touchscreen.
