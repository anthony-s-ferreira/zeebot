# Imagens

* `zee.png` — **imagem oficial da abelha Zee** (substitua este arquivo quando tiver a arte
  final). Formato recomendado: PNG quadrado com fundo transparente, 512x512 px.
* `zee.svg` — placeholder usado automaticamente pelo frontend enquanto `zee.png` não existir.

O frontend tenta carregar `zee.png` e, se a imagem não for encontrada, cai para `zee.svg`
(ver `static/js/app.js`, listener de `error` na tag `<img id="zee-face">`).
