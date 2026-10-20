# Lance POV

Recria lances de futebol em 3D e mostra pelos olhos de qualquer jogador em campo.

**No ar:** https://yantorres023.github.io/lance-pov/

## O que tem
- **Os 30 gols mais hypados**: Maradona em 1986, Carlos Alberto em 1970, Pelé em 1958, finais da Champions (Ramos, Bale, Drogba, Mandžukić, Messi, Gerrard), Ronaldinho e Messi no Bernabéu, Copas de 2018 e 2022 (Pavard, Cristiano Ronaldo, Kroos, Chadli, Richarlison, Messi, Molina, Neymar, Di María, Mbappé), Euros (Schick, Lamine Yamal, Bellingham) e o escanteio rápido do Origi.
- **Futebol brasileiro**: Neymar × Flamengo (2011), Arrascaeta na final da Copa do Brasil 2018, Éverton Ribeiro × Flamengo (2013) e um top 10 baseado na enquete do GE de 2020 e nos Puskás brasileiros. **São reconstruções aproximadas** (não existe dado público de posição desses jogos) e dá para corrigi-las no editor.
- **Mais lances**: os outros 20 gols do Liverpool em 2019 do Last-Row, com tracking completo.

## Como usar
- Escolha o lance e o jogador (na lista, no minimapa ou clicando nele). "Quem fez o gol" já vem selecionado.
- Vistas: **1ª pessoa**, **atrás dele**, **TV**, **livre** (arraste para girar) e **tática**. Atalhos: 1–5.
- **Visual**: Realista, Palitos (claro e escuro, no estilo minimalista do [stickman-video-director](https://github.com/kaomei/stickman-video-director)), Blocos (inspirado no Minecraft) e Bloquinho (inspirado no Roblox).
- Para onde ele olha: **Natural** (corpo na corrida, cabeça na bola até o limite do pescoço), **Bola** ou **Corrida**.
- **Gravar vídeo** baixa um `.webm` do lance inteiro na vista e no visual atuais.
- **✎ Editar**: na vista de cima, arraste jogadores e bola; cada arraste grava um quadro-chave no instante atual e o resto é interpolado. Roda do mouse aproxima. O rascunho fica salvo no navegador; **Exportar JSON** gera um arquivo que pode virar lance permanente. **Novo lance do zero** começa com 22 jogadores em formação.
- Espaço: tocar ou pausar. ← →: um quadro. Delete (no editor): apaga o quadro-chave do instante.
- Links diretos: `?lance=<id>&estilo=palitos-claro`.

## De onde vêm os dados
- **StatsBomb Open Data** (uso não comercial, com atribuição): eventos de cada lance (passes, conduções, dribles, chute) e posição de todos os jogadores no instante do chute. Nas Copas de 2022 e nas Euros há também posições de quase todo mundo a cada evento (360). O movimento entre eventos é interpolado; jogadores que só aparecem no chute têm movimento **estimado** (marcados na lista e tracejados no minimapa).
- **Last-Row / Friends of Tracking** (@lastrowview): tracking à mão, 20 quadros por segundo.
- Gols brasileiros: desenho aproximado a partir de relatos; ver o aviso em cada lance.
- **Bola no pé**: `scripts/posse.py` garante que, enquanto alguém conduz a bola, ela fique no pé dele (≤ 0,9 m em 99,9% dos quadros de posse). No StatsBomb o jogador vai até a bola (a bola é âncora dos eventos); no Last-Row e nos roteiros a bola vai até o pé do jogador (lá ela é aproximada). Auditoria: `python3 -I scripts/auditar_posse.py`.

## Estrutura
- `scripts/prepare_statsbomb.py` → `web/data/hypados.json` (baixa e guarda cache em `data/raw/statsbomb/`, fora do git). Teste: `scripts/test_statsbomb.py`.
- `scripts/roteiros_brasil.py` → `web/data/brasil.json` (quadros-chave). Teste: `scripts/test_brasil.py`.
- `scripts/prepare_lastrow.py` → `web/data/lances.json`.
- `web/` — visualizador (three.js, sem build). Rodar localmente: `./servir.sh` e abrir http://localhost:8765.

Projeto pessoal, sem fins comerciais.
