---
name: creator-automation-studio
description: Corta lives e vídeos longos em Shorts/TikToks verticais prontos para postar (câmera em cima, jogo embaixo, título-gancho, legenda palavra por palavra, narração com voz clonada) e publica no canal certo. Use quando pedirem "corta essa live", "faz cortes desse vídeo", "acha as maiores lives de hoje e corta" ou "posta esses cortes".
---

# Creator Automation Studio

O agente faz a parte editorial: **ler a transcrição e escolher os momentos**. O resto é o pacote `cas`
(`python -m cas …`, rodado na pasta do repositório). Rode `preparar` e `cortar` em segundo plano: demoram.

## Fluxo
1. `python -m cas buscar` (opcional) → mostre a lista e pergunte quais cortar.
2. `python -m cas preparar LINK` → blocos em `CAS_HOME/trabalho/<fonte>/blocos/`.
3. Leia **um bloco por vez** e escreva `momentos/bloco_NN.json` (mesmo número), mesmo vazio (`[]`).
4. `python -m cas escolher <fonte> --manter 3`.
5. `python -m cas cortar <fonte>` → `CAS_HOME/saida/<fonte>/NN - TITULO.mp4` + `.txt`.
6. Confira 2–3 quadros de cada corte (ffmpeg) antes de dizer que está pronto.
7. **Só com o "pode postar" do dono do canal:** `python -m cas postar --conta X --pasta <saida>`; o vídeo entra
   privado e é tornado público no YouTube Studio.

## O que vale um corte
Primeira reação a algo do jogo; descoberta absurda; surto, grito, susto; falha engraçada ou bug; opinião forte;
história ou piada que fecha sozinha. As marcas `[ALTO +NdB]` e `[CHAT Nx]` são pistas, não provas: confirme pela fala.

**Jogue fora:** o que precisa de contexto anterior; começo com enrolação ("é…", "então…", "tipo assim");
leitura de doação, propaganda, conversa sobre a própria live, tela de carregamento; fala que a transcrição não deixa entender.

**Nota de 0 a 100:** 90+ para qualquer pessoa parar de rolar o feed; 70–89 bom; abaixo de 60 nem escreva.
Normalmente 0 a 3 momentos bons por bloco. **Duração:** 20–90 s em geral, até 2:50 quando a história pede.
Comece 1–2 s antes da frase que prende e termine logo depois da reação.

## Campos
```json
{"inicio": "01:12:03", "fim": "01:12:41", "nota": 88, "tipo": "primeira reação",
 "titulo": "GANCHO EM MAIÚSCULAS, ATÉ ~45 LETRAS, SEM SPOILER",
 "porque": "por que fecha sozinho",
 "post": "1–2 frases + 4 a 6 hashtags",
 "narracao": [{"t": 0.2, "texto": "uma frase curta de gancho, 2–4 s"}]}
```
A narração entra por cima do áudio original (que abaixa sozinho). Não narre por cima do grito ou da frase principal.

## Respeito
Corte só de quem libera cortes e mantenha o crédito com o link da fonte.
