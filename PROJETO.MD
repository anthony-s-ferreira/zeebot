# Prompt para desenvolvimento do Zee Assistant no Raspberry Pi 4B

Atue como um **Arquiteto de Software Sênior especializado em Raspberry Pi, Linux embarcado, Python, interfaces touchscreen, reconhecimento de voz offline, PWAs e sistemas multimídia**.

Quero que você desenvolva um aplicativo completo chamado **Zee Assistant**, destinado a executar localmente em um:

* Raspberry Pi 4B
* 4 GB de RAM
* Raspberry Pi OS 64 bits
* Tela LCD touchscreen
* Microfone conectado ao Raspberry Pi, podendo ser USB ou I2S
* Alto-falante/saída de áudio
* Wi-Fi
* Chromium em modo kiosk

O sistema deve ser otimizado para funcionar de maneira fluida nesse hardware.

Não quero apenas exemplos ou pseudocódigo.

Quero que você:

1. Defina a arquitetura.
2. Crie toda a estrutura de diretórios.
3. Gere todos os arquivos necessários.
4. Gere o backend.
5. Gere o frontend.
6. Implemente o reconhecimento de voz.
7. Implemente a configuração de Wi-Fi.
8. Implemente os serviços Linux necessários.
9. Crie scripts de instalação.
10. Crie arquivos de configuração.
11. Crie instruções de instalação.
12. Crie um README detalhado.
13. Garanta inicialização automática ao ligar o Raspberry Pi.
14. Implemente tratamento de erros.
15. Explique como testar cada funcionalidade.

O objetivo é que, depois de clonar/copiar o projeto para um Raspberry Pi novo e executar o script de instalação, o sistema fique praticamente pronto para uso.

---

# 1. VISÃO GERAL DO PRODUTO

O Zee Assistant será um dispositivo educacional interativo.

Ele terá duas formas principais de interação:

### Interação por voz

Na tela inicial o dispositivo ficará permanentemente aguardando a wakeword:

**"Oi, Zee"**

Quando detectar essa frase, o dispositivo deve começar uma interação por voz.

### Interação touchscreen

O usuário poderá clicar em:

**MENU**

e navegar por uma biblioteca multimídia contendo:

* Vídeos
* Áudios
* Livros
* Jogos

Os conteúdos estarão cadastrados em um arquivo JSON armazenado localmente no Raspberry Pi.

---

# 2. ARQUITETURA SUGERIDA

Prefira uma arquitetura simples, robusta e adequada ao Raspberry Pi.

Sugestão:

## Backend

Python 3.

Pode utilizar:

* Flask
* pathlib
* threading
* subprocess
* logging
* requests
* RapidFuzz
* Vosk

Evite frameworks excessivamente pesados.

## Frontend

Utilize:

* HTML5
* CSS3
* JavaScript ES6
* sem React
* sem Vue
* sem Angular

O frontend deve rodar no Chromium em:

**modo kiosk / fullscreen**

A aplicação web deve ser servida localmente pelo próprio Raspberry Pi.

Exemplo:

http://127.0.0.1:5000

---

# 3. RECONHECIMENTO DE VOZ OFFLINE

Uma exigência importante é:

**não depender de serviços de reconhecimento de voz externos.**

Prefira reconhecimento offline.

Minha preferência é utilizar:

**Vosk**

com modelo de português brasileiro compatível com Raspberry Pi.

O reconhecimento deve funcionar em dois estágios.

## Estágio 1 — Wakeword

Enquanto estiver na Home, o sistema ficará escutando continuamente apenas algo equivalente a:

**"Oi Zee"**

O reconhecimento dessa etapa deve ser o mais leve possível.

Utilize gramática/restrição de vocabulário quando possível para evitar que o modelo fique processando frases completas permanentemente.

Considere variações naturais de reconhecimento como:

* oi zee
* oi zi
* oi zii
* oizee

Internamente normalize essas variações.

Não quero que qualquer fala aleatória ative o assistente.

## Estágio 2 — Comando

Depois de detectar:

**"Oi Zee"**

o sistema muda temporariamente para reconhecimento completo da fala.

---

# 4. FLUXO DE INTERAÇÃO POR VOZ

Na tela inicial haverá a imagem/rosto de uma abelha chamada **Zee**.

Enquanto estiver esperando a wakeword, o estado da interface pode mostrar discretamente algo como:

**"Diga: Oi, Zee"**

Quando o usuário disser:

**"Oi, Zee"**

executar imediatamente:

### Passo 1

Interromper temporariamente a detecção da wakeword.

### Passo 2

Reproduzir um MP3 LOCAL.

Por exemplo:

```text
/assets/audio/oi_estou_ouvindo.mp3
```

O conteúdo desse MP3 será:

**"Oi, estou ouvindo."**

Não utilizar Text-to-Speech para essa frase.

É obrigatório reproduzir o arquivo MP3 armazenado localmente.

### Passo 3

Na tela, mudar o estado para:

**Aguardando usuário...**

Criar também uma animação visual indicando que o microfone está ativo.

Pode ser:

* ondas
* barras
* círculo pulsando
* microfone animado

### Passo 4

Capturar o que o usuário disser.

Por exemplo:

**"Quero assistir ao vídeo de introdução à inteligência artificial."**

ou:

**"Quero ouvir o podcast de inteligência artificial."**

ou:

**"Abra o livro fundamentos de inteligência artificial."**

ou:

**"Quero jogar o jogo do ABC."**

### Passo 5

Converter a fala para texto localmente.

### Passo 6

Interpretar o comando.

### Passo 7

Pesquisar o conteúdo no JSON.

### Passo 8

Caso encontre o recurso, abrir automaticamente sua tela.

---

# 5. BUSCA INTELIGENTE DOS RECURSOS

Não quero comparação apenas por igualdade exata de strings.

Implemente uma busca tolerante.

Utilize, por exemplo:

**RapidFuzz**

Faça normalização antes da comparação:

* converter para minúsculas
* remover acentos
* remover pontuação
* remover palavras irrelevantes
* normalizar espaços

Considere informações como:

* tipo
* título
* descrição

Também interprete palavras que representem os tipos.

Por exemplo:

### Vídeos

Palavras como:

* vídeo
* assistir
* veja
* mostrar
* reproduzir vídeo

devem sugerir:

```text
tipo = video
```

### Áudios

Palavras como:

* áudio
* podcast
* ouvir
* escutar

devem sugerir:

```text
tipo = audio
```

### Livros

Palavras como:

* livro
* ler
* leitura
* PDF

devem sugerir:

```text
tipo = livro
```

### Jogos

Palavras como:

* jogo
* jogar
* brincar

devem sugerir:

```text
tipo = jogo
```

Depois disso, combinar o tipo detectado com similaridade do título.

Exemplo:

JSON:

```text
Introdução à Inteligência Artificial
```

Usuário:

```text
quero assistir o vídeo de introdução a inteligência artificial
```

deve encontrar esse conteúdo com alta confiança.

---

# 6. NÍVEL DE CONFIANÇA

Implemente um score para os resultados.

Exemplo:

```text
0 - 100
```

Caso exista um resultado claramente superior aos demais e acima do threshold configurado, abrir automaticamente.

Exemplo:

```text
confidence >= 70
```

Esse valor deve ficar em configuração.

Caso dois conteúdos tenham scores muito semelhantes, mostrar na tela:

**"Encontrei mais de uma opção."**

e apresentar os cards correspondentes para o usuário selecionar.

Caso nenhum conteúdo seja encontrado, mostrar:

**"Não encontrei esse conteúdo."**

Depois de alguns segundos voltar automaticamente à Home e reativar:

**"Oi, Zee"**

---

# 7. TIMEOUT DO COMANDO DE VOZ

Depois de falar:

**"Oi Zee"**

o dispositivo não deve ficar escutando indefinidamente.

Implemente:

* detecção de silêncio
* timeout configurável
* por exemplo, máximo de 8 a 10 segundos de gravação

Quando perceber que o usuário terminou de falar, processar imediatamente.

---

# 8. HOME

A Home deve ter aparência amigável, moderna e infantil/educacional.

No centro haverá:

**o rosto de uma abelha Zee.**

Crie no projeto a estrutura:

```text
static/assets/images/zee.png
```

Caso essa imagem não exista, utilize temporariamente um SVG/placeholder simples de uma abelha.

Eu posteriormente substituirei esse arquivo pela imagem oficial.

Na região inferior deverá existir um botão grande:

**MENU**

A Home deve mostrar também o estado do assistente.

Exemplo:

```text
Diga "Oi, Zee"
```

Quando ativado:

```text
Oi! Estou ouvindo...
```

Depois:

```text
Aguardando usuário...
```

E durante processamento:

```text
Procurando conteúdo...
```

---

# 9. BOTÃO MENU

Ao clicar em:

**MENU**

a detecção do wakeword deve ser IMEDIATAMENTE DESATIVADA.

Enquanto o usuário estiver navegando pelo MENU ou consumindo um conteúdo:

**"Oi Zee" NÃO deve funcionar.**

Isso é uma regra obrigatória.

O wakeword só será reativado quando o usuário voltar para a HOME.

---

# 10. TELA MENU

Exibir quatro cards grandes:

### VÍDEOS

Ícone de vídeo.

### ÁUDIOS

Ícone de fone, música ou áudio.

### LIVROS

Ícone de livro.

### JOGOS

Ícone de joystick.

Layout otimizado para touchscreen.

Os cards devem ser grandes e fáceis de clicar.

---

# 11. JSON DE RECURSOS

Os recursos estarão armazenados localmente.

Exemplo:

```text
data/recursos.json
```

Utilize inicialmente este JSON corrigido:

```json
{
  "recursos": [
    {
      "id": "rec_001",
      "tipo": "video",
      "titulo": "Introdução à Inteligência Artificial",
      "descricao": "Vídeo apresentando os principais conceitos de IA.",
      "url": "https://www.youtube.com/watch?v=XXXXXXXXXXX"
    },
    {
      "id": "rec_002",
      "tipo": "audio",
      "titulo": "Podcast de Inteligência Artificial",
      "descricao": "Discussão sobre aplicações práticas de IA.",
      "url": "https://conteudos.exemplo.com/audio/inteligencia-artificial.mp3"
    },
    {
      "id": "rec_003",
      "tipo": "livro",
      "titulo": "Fundamentos de Inteligência Artificial",
      "descricao": "Livro digital para aprofundamento do conteúdo.",
      "url": "https://conteudos.exemplo.com/livros/fundamentos-ia.pdf"
    },
    {
      "id": "rec_004",
      "tipo": "jogo",
      "titulo": "Jogo do ABC",
      "descricao": "Jogo educacional para aprendizagem do alfabeto.",
      "url": "https://conteudos.exemplo.com/jogos/abc.html"
    }
  ]
}
```

O sistema deve ler esse arquivo dinamicamente.

Não quero conteúdos hardcoded na interface.

Se eu adicionar um novo recurso ao JSON e reiniciar/recarregar a aplicação, ele deve aparecer automaticamente.

---

# 12. LISTAGEM DE CONTEÚDOS

Ao clicar em:

**VÍDEOS**

filtrar:

```text
tipo = video
```

Ao clicar em:

**ÁUDIOS**

filtrar:

```text
tipo = audio
```

Ao clicar em:

**LIVROS**

filtrar:

```text
tipo = livro
```

Ao clicar em:

**JOGOS**

filtrar:

```text
tipo = jogo
```

Apresentar os resultados em formato de cards.

Cada card deve possuir:

* título
* descrição
* ícone correspondente ao tipo

Pode opcionalmente aceitar uma propriedade futura:

```json
"thumbnail": "..."
```

Não deve ser obrigatória.

---

# 13. EXIBIÇÃO DE VÍDEOS

Quando o conteúdo for:

```text
tipo = video
```

abrir uma tela de conteúdo.

Para URLs do YouTube converter automaticamente:

```text
https://www.youtube.com/watch?v=ID
```

para:

```text
https://www.youtube.com/embed/ID
```

Exibir o vídeo ocupando a maior parte da tela.

Usar iframe.

Exemplo conceitual:

```html
<iframe
    src="..."
    allow="autoplay; encrypted-media; fullscreen"
    allowfullscreen>
</iframe>
```

Criar botão:

**VOLTAR**

---

# 14. EXIBIÇÃO DE ÁUDIOS

Quando:

```text
tipo = audio
```

não utilizar iframe.

Criar uma interface amigável de player.

Utilizar:

```html
<audio>
```

O player deve possuir:

* play
* pause
* barra de progresso
* duração
* volume

Mostrar também:

* título
* descrição

Criar botão:

**VOLTAR**

---

# 15. EXIBIÇÃO DE LIVROS

Quando:

```text
tipo = livro
```

normalmente será uma URL de PDF.

Abrir o PDF dentro da própria aplicação.

Utilizar inicialmente iframe no Chromium.

A tela deve permitir:

* leitura
* scroll
* zoom quando suportado
* voltar

Preferencialmente ocupar praticamente toda a tela.

Criar botão:

**VOLTAR**

Caso posteriormente seja necessário, deixe a arquitetura preparada para trocar o iframe por PDF.js.

---

# 16. EXIBIÇÃO DOS JOGOS

Quando:

```text
tipo = jogo
```

abrir a URL HTML dentro de iframe.

O jogo deve ocupar praticamente toda a tela.

Criar botão:

**VOLTAR**

Considere que alguns servidores podem impedir iframe através de:

* X-Frame-Options
* Content-Security-Policy

Caso isso aconteça, tratar o erro de maneira amigável.

Não travar a aplicação.

---

# 17. NAVEGAÇÃO

Fluxo esperado:

```text
HOME
   |
   +-- MENU
        |
        +-- VÍDEOS
        |     |
        |     +-- CONTEÚDO
        |
        +-- ÁUDIOS
        |     |
        |     +-- CONTEÚDO
        |
        +-- LIVROS
        |     |
        |     +-- CONTEÚDO
        |
        +-- JOGOS
              |
              +-- CONTEÚDO
```

Sempre fornecer:

**VOLTAR**

Quando voltar de um conteúdo para a listagem:

wakeword continua desativado.

Quando voltar da listagem/menu para HOME:

wakeword é reativado.

---

# 18. PRIMEIRA INICIALIZAÇÃO — CONFIGURAÇÃO DO WI-FI

Essa é uma das partes mais importantes.

Quando o Raspberry Pi for ligado pela primeira vez e ainda NÃO possuir uma rede Wi-Fi configurada, o sistema deverá entrar automaticamente em:

**Modo de Configuração.**

O Raspberry Pi deverá criar temporariamente seu próprio Wi-Fi Access Point.

Por exemplo:

```text
SSID: Zee-Setup-XXXX
```

onde XXXX pode ser baseado em alguns caracteres do serial/device ID.

Utilize preferencialmente os recursos do:

**NetworkManager**

e comandos `nmcli`, pois o Raspberry Pi OS atual utiliza NetworkManager.

---

# 19. QRCODE DE CONFIGURAÇÃO

Na tela LCD mostrar:

**Configure o Wi-Fi do Zee**

e abaixo um grande QR Code.

O QR Code deve facilitar a conexão do smartphone à rede criada pelo Raspberry Pi.

Utilize o padrão de QR Code para redes Wi-Fi quando possível.

Depois que o smartphone conectar ao Access Point do Zee, deve ser disponibilizado um:

**Captive Portal**

O smartphone deve, sempre que suportado pelo sistema operacional, abrir automaticamente a página de configuração.

Caso o captive portal não seja aberto automaticamente, mostrar na tela também algo como:

```text
Após conectar ao Zee-Setup, acesse:

http://10.42.0.1
```

Não dependa exclusivamente da abertura automática do captive portal.

---

# 20. PÁGINA DE CONFIGURAÇÃO DO WI-FI

A página aberta pelo smartphone deve possuir uma interface responsiva.

Título:

**Configurar Zee**

Texto:

**Escolha a rede Wi-Fi que o Zee deverá utilizar.**

O Raspberry Pi deve procurar as redes Wi-Fi disponíveis utilizando NetworkManager/nmcli.

Mostrar algo como:

```text
MinhaCasa
Escola-WiFi
Rede-Visitantes
Outra rede...
```

Para cada rede, se possível, mostrar:

* SSID
* intensidade do sinal
* se possui senha

O usuário seleciona a rede.

Se necessário, informar:

**Senha**

Botão:

**CONECTAR**

---

# 21. PROCESSO DE CONEXÃO

Ao clicar em conectar:

1. Receber SSID.
2. Receber senha.
3. Tentar conectar utilizando NetworkManager.
4. Esperar confirmação real da conexão.
5. Verificar se recebeu IP.
6. Preferencialmente verificar conectividade.

Se funcionar, mostrar no smartphone:

**Wi-Fi configurado com sucesso!**

Na tela do Raspberry:

**Conectado!**

Esperar alguns segundos e:

1. parar o Access Point;
2. entrar na aplicação principal;
3. mostrar a Zee;
4. iniciar listening de "Oi Zee".

Não armazenar a senha em logs.

---

# 22. FALHA NA CONFIGURAÇÃO DE WI-FI

Caso a conexão falhe:

não sair do Access Point.

Mostrar:

**Não foi possível conectar. Verifique a senha e tente novamente.**

Permitir nova tentativa.

---

# 23. RECUPERAÇÃO DE WI-FI

Implemente também um mecanismo de recuperação.

Se futuramente o Raspberry Pi for ligado e não conseguir conectar a nenhuma rede previamente configurada depois de um tempo configurável, por exemplo:

```text
60 segundos
```

ele pode novamente entrar no:

**Zee Wi-Fi Setup Mode**

Isso evita que o dispositivo fique inutilizável caso seja levado para outra escola/local.

Esse tempo deve ficar em configuração.

---

# 24. ESTADOS DO SISTEMA

Crie explicitamente uma máquina de estados ou mecanismo equivalente.

Por exemplo:

```text
WIFI_SETUP
HOME_LISTENING
WAKEWORD_DETECTED
WAITING_USER
PROCESSING_COMMAND
MENU
RESOURCE_LIST
RESOURCE_VIEW
ERROR
```

O módulo de voz deve saber o estado atual.

Uma regra crítica:

```text
voice_enabled = true
```

somente quando:

```text
state == HOME_LISTENING
```

e durante o ciclo iniciado pelo wakeword.

Nunca deixar o reconhecedor disparando comandos enquanto o usuário estiver no MENU.

---

# 25. EXEMPLOS DE COMANDOS

O sistema deve entender frases como:

```text
Oi Zee
Quero assistir ao vídeo de introdução à inteligência artificial
```

Resultado:

Abrir:

```text
rec_001
```

---

Outro exemplo:

```text
Oi Zee
Quero ouvir o podcast de inteligência artificial
```

Resultado:

Abrir:

```text
rec_002
```

---

Outro exemplo:

```text
Oi Zee
Abra o livro fundamentos de inteligência artificial
```

Resultado:

Abrir:

```text
rec_003
```

---

Outro exemplo:

```text
Oi Zee
Quero jogar o jogo do ABC
```

Resultado:

Abrir:

```text
rec_004
```

Também deve funcionar com frases mais curtas:

```text
abra introdução inteligência artificial
```

```text
quero o podcast de IA
```

```text
abra fundamentos de inteligência artificial
```

---

# 26. COMUNICAÇÃO BACKEND ↔ FRONTEND

Defina uma solução simples e robusta para o backend avisar ao frontend que deve mudar de tela devido a um comando de voz.

Pode ser:

* Server-Sent Events
* WebSocket
* polling de estado local

Escolha a solução de menor complexidade que seja robusta no Raspberry Pi.

Por exemplo:

Quando o backend identificar:

```json
{
  "action": "open_resource",
  "resource_id": "rec_001"
}
```

o frontend deverá automaticamente navegar para o conteúdo correspondente.

Não exigir clique do usuário depois do comando de voz.

---

# 27. CONFIGURAÇÃO CENTRAL

Criar arquivo semelhante a:

```text
config/config.json
```

com configurações como:

```json
{
  "wakeword": "oi zee",
  "command_timeout_seconds": 10,
  "wifi_recovery_timeout_seconds": 60,
  "fuzzy_match_threshold": 70,
  "app_port": 5000,
  "resources_file": "data/recursos.json",
  "welcome_audio": "static/assets/audio/oi_estou_ouvindo.mp3"
}
```

Não espalhar constantes pelo código.

---

# 28. LOGS

Implementar logs usando módulo `logging`.

Criar, por exemplo:

```text
logs/zee.log
```

Registrar:

* inicialização
* estado da aplicação
* microfone detectado
* modelo Vosk carregado
* wakeword detectada
* transcrição
* recurso selecionado
* erros
* conexão de rede

NUNCA registrar:

* senha Wi-Fi

Criar rotação dos logs para impedir crescimento infinito.

---

# 29. TRATAMENTO DO MICROFONE

Na inicialização:

1. detectar microfone;
2. verificar se é possível capturar áudio;
3. registrar dispositivo encontrado;
4. se não houver microfone, continuar permitindo utilização touchscreen.

Nesse caso mostrar discretamente:

**Microfone indisponível**

Não travar a aplicação.

---

# 30. TRATAMENTO DE INTERNET

Mesmo com o sistema funcionando localmente, os recursos do JSON poderão estar na internet.

Antes/depois de tentar abrir um conteúdo remoto, tratar falhas de rede.

Por exemplo:

**Não foi possível carregar este conteúdo. Verifique sua conexão com a internet.**

Sempre permitir:

**VOLTAR**

Nunca deixar uma tela branca sem possibilidade de navegação.

---

# 31. SERVIÇOS DO LINUX

Crie arquivos `systemd` para os serviços necessários.

Por exemplo:

```text
zee-app.service
zee-voice.service
```

ou utilize um único serviço se considerar arquiteturalmente melhor.

Garanta:

```text
Restart=always
```

quando apropriado.

Os serviços devem subir automaticamente durante o boot.

---

# 32. MODO KIOSK

O Chromium deve iniciar automaticamente em fullscreen.

Exemplo conceitual:

```bash
chromium \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  http://127.0.0.1:5000
```

Utilize os parâmetros corretos para a versão instalada.

Não mostrar:

* barra de endereço
* abas
* menus do navegador
* mensagens de restauração de sessão

Desabilitar screensaver/blanking quando necessário.

A interface deverá ficar sempre visível.

---

# 33. INICIALIZAÇÃO

Fluxo completo do boot:

```text
Raspberry Pi liga
       ↓
Linux inicia
       ↓
Zee Services iniciam
       ↓
Verifica Wi-Fi
       ↓
┌──────────────────────────────┐
│ Wi-Fi configurado?           │
└──────────────────────────────┘
       ↓ SIM             ↓ NÃO
 Aplicação Zee       Setup Wi-Fi
       ↓                  ↓
 Chromium             Access Point
 Kiosk                    ↓
       ↓               QR Code
    HOME                  ↓
       ↓              Smartphone
 Diga "Oi Zee"            ↓
                    Configura Wi-Fi
                           ↓
                       Conecta
                           ↓
                         HOME
```

---

# 34. INTERFACE

A interface deve ser:

* bonita
* moderna
* amigável
* infantil sem ser excessivamente infantil
* adequada a ambiente educacional
* touch-first
* responsiva
* fullscreen
* com botões grandes

Utilizar animações CSS leves.

Não utilizar animações pesadas que prejudiquem o Raspberry Pi.

Preferencialmente utilizar CSS e SVG em vez de bibliotecas gráficas pesadas.

---

# 35. RESOLUÇÕES

A interface deve funcionar principalmente em telas como:

```text
800x480
1024x600
1280x800
1920x1080
```

Não assumir uma resolução fixa.

O layout deve se adaptar.

---

# 36. ESTRUTURA DE DIRETÓRIOS

Crie uma estrutura organizada semelhante a:

```text
zee-assistant/
│
├── app/
│   ├── __init__.py
│   ├── server.py
│   ├── state.py
│   ├── resources.py
│   ├── voice/
│   │   ├── listener.py
│   │   ├── wakeword.py
│   │   ├── recognizer.py
│   │   └── matcher.py
│   │
│   ├── network/
│   │   ├── wifi.py
│   │   └── captive_portal.py
│   │
│   └── utils/
│
├── templates/
│   └── index.html
│
├── static/
│   ├── css/
│   │   └── app.css
│   ├── js/
│   │   └── app.js
│   └── assets/
│       ├── images/
│       │   └── zee.png
│       └── audio/
│           └── oi_estou_ouvindo.mp3
│
├── data/
│   └── recursos.json
│
├── config/
│   └── config.json
│
├── models/
│   └── vosk/
│
├── scripts/
│   ├── install.sh
│   ├── configure_kiosk.sh
│   └── uninstall.sh
│
├── systemd/
│   └── zee-assistant.service
│
├── logs/
│
├── requirements.txt
├── README.md
└── main.py
```

Pode modificar essa organização se houver uma solução arquiteturalmente melhor, mas mantenha clara separação entre:

* interface
* voz
* recursos
* Wi-Fi
* configuração
* infraestrutura

---

# 37. SCRIPT DE INSTALAÇÃO

Criar:

```text
scripts/install.sh
```

Ele deve automatizar o máximo possível.

Por exemplo:

1. verificar arquitetura;
2. atualizar dependências necessárias;
3. instalar Python/venv;
4. instalar dependências do sistema;
5. instalar Chromium;
6. instalar dependências de áudio;
7. criar virtualenv;
8. instalar requirements.txt;
9. instalar/configurar modelo Vosk;
10. configurar permissões;
11. instalar systemd service;
12. configurar Chromium kiosk;
13. configurar inicialização automática;
14. habilitar os serviços.

Não executar operações destrutivas desnecessárias.

---

# 38. MODELO VOSK

Documente exatamente:

* onde colocar o modelo PT-BR;
* como baixá-lo;
* como configurá-lo;
* qual diretório esperado.

Por exemplo:

```text
models/vosk/
```

Ao iniciar, verificar se o modelo existe.

Caso não exista:

registrar erro claro e permitir que a parte touchscreen continue funcionando.

---

# 39. ÁUDIO LOCAL DE RESPOSTA

O arquivo:

```text
static/assets/audio/oi_estou_ouvindo.mp3
```

será fornecido posteriormente.

Caso ele não exista durante desenvolvimento:

não travar.

Registrar:

```text
Welcome audio not found
```

e continuar para a captura do comando.

Crie uma implementação de reprodução adequada para Raspberry Pi.

---

# 40. SEGURANÇA

Mesmo sendo uma aplicação local:

* validar parâmetros recebidos;
* não executar texto fornecido pelo usuário como shell;
* evitar command injection;
* não permitir path traversal;
* não expor arquivos arbitrários;
* não registrar senhas;
* sanitizar SSIDs quando necessário;
* utilizar `subprocess` com lista de argumentos e nunca shell=True sempre que possível.

---

# 41. TESTES

Crie testes principalmente para:

### Parser do JSON

Validar tipos:

```text
video
audio
livro
jogo
```

### Busca fuzzy

Testar:

```text
"quero assistir introdução inteligência artificial"
```

deve encontrar `rec_001`.

### Classificação da intenção

Testar:

```text
quero ouvir podcast inteligência artificial
```

deve detectar:

```text
audio
```

### Normalização

Testar diferenças de:

* acentos
* maiúsculas
* pontuação

### Estados

Testar que o wakeword:

```text
HOME = habilitado
MENU = desabilitado
RESOURCE_LIST = desabilitado
RESOURCE_VIEW = desabilitado
```

---

# 42. API LOCAL

Crie endpoints claros.

Exemplos:

```text
GET /api/status
GET /api/resources
GET /api/resources?tipo=video
GET /api/resources/:id

GET /api/wifi/networks
POST /api/wifi/connect

GET /api/voice/status
POST /api/navigation/home
```

Não precisa seguir exatamente esses endpoints, mas mantenha uma API organizada.

---

# 43. FUTURA EXPANSÃO

A arquitetura deve ficar preparada para futuramente adicionar:

* novos tipos de recurso;
* recursos locais;
* vídeos locais;
* PDFs locais;
* MP3 locais;
* jogos HTML locais;
* respostas por IA;
* integração com APIs externas;
* câmera;
* reconhecimento de usuário;
* sincronização remota do JSON;
* atualização OTA da aplicação.

Não implemente essas funcionalidades agora.

Apenas não crie uma arquitetura que torne essas expansões difíceis.

---

# 44. PRIORIDADE: PERFORMANCE

Lembre-se:

o hardware é um:

**Raspberry Pi 4B com 4 GB.**

Portanto:

* evitar Electron;
* evitar frameworks frontend pesados;
* evitar modelos de IA grandes;
* evitar Whisper grande;
* evitar múltiplos processos desnecessários;
* evitar uso excessivo de memória;
* evitar animações complexas;
* liberar corretamente microfone e áudio;
* não manter múltiplos iframes abertos;
* destruir o iframe quando sair da tela de conteúdo.

Priorize estabilidade.

---

# 45. EXPERIÊNCIA ESPERADA

Quero conseguir colocar o Raspberry Pi sobre uma mesa.

Ligá-lo.

Na primeira utilização:

```text
[QR CODE]

Configure o Wi-Fi do Zee
```

Escaneio com meu smartphone.

Conecto.

Seleciono:

```text
Wi-Fi da Escola
```

informo a senha.

O Raspberry conecta.

Na tela aparece a Zee.

```text
🐝

Diga "Oi, Zee"


             [ MENU ]
```

Eu digo:

```text
Oi Zee
```

Zee reproduz:

```text
"Oi, estou ouvindo."
```

A tela mostra:

```text
Aguardando usuário...
```

Eu digo:

```text
Quero assistir ao vídeo de introdução à inteligência artificial
```

O sistema reconhece:

```text
tipo: video

consulta:
introducao inteligencia artificial
```

Encontra:

```text
rec_001
```

e automaticamente abre o vídeo.

---

Também quero poder simplesmente tocar:

```text
MENU
```

Depois:

```text
VÍDEOS
```

Selecionar:

```text
Introdução à Inteligência Artificial
```

e assistir.

Enquanto estiver no menu:

```text
"Oi Zee"
```

não deve ser reconhecido.

Quando eu voltar para Home:

```text
"Oi Zee"
```

deve voltar a funcionar.

---

# 46. CRITÉRIOS DE ACEITE

Considere o projeto concluído somente quando:

* [ ] inicia automaticamente com o Raspberry Pi;
* [ ] Chromium abre automaticamente em kiosk;
* [ ] primeira inicialização cria Access Point;
* [ ] LCD apresenta QR Code;
* [ ] smartphone consegue conectar ao Access Point;
* [ ] existe página para selecionar Wi-Fi;
* [ ] Raspberry consegue conectar ao Wi-Fi informado;
* [ ] após configuração aparece a Home;
* [ ] Home mostra a Zee;
* [ ] botão MENU funciona;
* [ ] MENU mostra Vídeos, Áudios, Livros e Jogos;
* [ ] conteúdo é carregado dinamicamente do JSON;
* [ ] vídeos funcionam;
* [ ] MP3 funciona;
* [ ] PDFs funcionam;
* [ ] jogos HTML funcionam;
* [ ] wakeword funciona offline;
* [ ] "Oi Zee" reproduz o MP3 local;
* [ ] interface mostra "Aguardando usuário";
* [ ] comando do usuário é reconhecido;
* [ ] busca fuzzy identifica recurso;
* [ ] recurso é aberto automaticamente;
* [ ] wakeword fica desabilitado no MENU;
* [ ] wakeword fica desabilitado durante conteúdos;
* [ ] wakeword volta ao retornar à HOME;
* [ ] aplicação não trava sem internet;
* [ ] aplicação não trava sem microfone;
* [ ] logs são gerados;
* [ ] senha Wi-Fi nunca aparece nos logs;
* [ ] serviço reinicia automaticamente em caso de falha.

---

# 47. FORMA DE ENTREGA

Agora desenvolva esse projeto.

Não responda somente com uma explicação arquitetural.

Comece apresentando:

## 1. Arquitetura

Explique resumidamente as decisões.

Depois:

## 2. Estrutura do projeto

Mostre a árvore completa de arquivos.

Depois:

## 3. Implementação

Gere o conteúdo COMPLETO dos arquivos necessários.

Para cada arquivo, informe claramente o caminho, por exemplo:

```text
app/voice/listener.py
```

e em seguida coloque seu código completo.

Não utilize trechos como:

```text
# restante do código aqui
```

ou:

```text
# implementar depois
```

Quero código executável.

Depois gere:

## 4. requirements.txt

## 5. scripts/install.sh

## 6. configurações systemd

## 7. configuração kiosk

## 8. configuração do captive portal

## 9. README.md

## 10. procedimentos de teste

## 11. troubleshooting

Inclua soluções para problemas comuns como:

* microfone não detectado;
* Raspberry sem áudio;
* Chromium não inicia;
* modelo Vosk não encontrado;
* wakeword não reconhecida;
* Wi-Fi não conecta;
* captive portal não abre;
* iframe não carrega;
* YouTube não carrega;
* PDF não aparece.

Sempre priorize uma solução funcional, simples, modular e apropriada para um Raspberry Pi 4B de 4 GB.
