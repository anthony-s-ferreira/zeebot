# Prompts aceitos pelo Zee

O Zee escuta o comando depois de dizer **"Oi, Zee"**. O roteamento é simples:

1. Se o pedido corresponde a um recurso ou categoria do catálogo, o Zee abre o conteúdo.
2. Se não corresponde a um recurso, o texto inteiro é enviado ao SLM local.
3. O SLM responde de forma curta na tela, em português, sem inventar itens do catálogo.

## Recursos do catálogo

Os títulos, descrições e `aliases` cadastrados em `data/recursos.json` definem o que pode ser aberto.

### Abrir conteúdo

```text
Quero assistir ao vídeo de introdução à inteligência artificial
Quero ouvir o podcast de inteligência artificial
Abra o livro de fundamentos de inteligência artificial
Quero jogar o jogo do alfabeto
Mostre o vídeo sobre inteligência artificial
```

### Abrir categorias

```text
Mostra os vídeos
Quais áudios existem?
Abra a lista de livros
Quero ver os jogos
Mostre todos os conteúdos
Abra o menu
```

Para novos conteúdos, prefira adicionar `aliases` com palavras inteiras, por exemplo:

```json
"aliases": ["jogo do alfabeto", "jogo das letras"]
```

## Perguntas respondidas pelo SLM

O SLM é indicado para perguntas curtas, explicações simples e conversas educativas:

### Matemática básica

```text
Quanto é 10 + 10?
Quanto é 5 vezes 3?
Qual é a metade de 20?
O que é um número par?
```

### Conhecimentos gerais

```text
O que é inteligência artificial?
Por que o céu é azul?
O que é um animal mamífero?
Como funciona a chuva?
Qual é a capital do Brasil?
```

### Educação

```text
Explique fotossíntese de forma simples
Explique o que é um planeta
Me ajude a estudar matemática
Faça uma pergunta sobre ciências
Resuma o que é o sistema solar
```

### Conversa curta

```text
Olá, tudo bem?
Conte uma piada curta
Dê uma curiosidade sobre abelhas
Obrigado
```

## Limites do SLM no Raspberry Pi 4B

O modelo padrão é o **Qwen2.5 0.5B Instruct Q4_K_M**, executado localmente com
`llama-cpp-python`. Ele foi escolhido para caber no Raspberry Pi 4B com 4 GB:

- respostas curtas funcionam melhor;
- perguntas factuais muito específicas podem conter erros;
- não acessa a internet nem consulta fontes externas;
- não abre recursos: quem abre recursos é o catálogo;
- operações matemáticas complexas devem ser conferidas;
- o modelo é carregado somente na primeira pergunta geral.

Para testar sem microfone:

```bash
curl -s -X POST http://localhost:5000/api/voice/simulate \
  -H 'Content-Type: application/json' \
  -d '{"text":"qual o valor de 10 + 10?"}' | python3 -m json.tool
```

No fluxo real, diga **"Oi, Zee"** e comece a falar assim que o som **"pode falar"** começar: o Zee captura o pedido em paralelo com esse áudio.
