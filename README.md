# Lance POV

Recria um lance de futebol em 3D e mostra pelos olhos de qualquer jogador em campo.

## Rodar
```bash
./servir.sh
```
Abra http://localhost:8765 (precisa de internet na primeira carga para baixar o three.js do jsDelivr).

## O que dá para fazer
- Escolher um dos 21 gols (19 do Liverpool em 2019, Liverpool × Chelsea, e o "calma" de Cristiano Ronaldo no Camp Nou).
- Escolher o jogador na lista, no minimapa ou clicando nele na cena. "Quem fez o gol" é detectado automaticamente.
- Vistas: **1ª pessoa**, **atrás dele**, **TV**, **livre** (arraste para girar) e **tática**. Atalhos: 1–5.
- Para onde ele olha: **Natural** (corpo segue a corrida, cabeça acompanha a bola até o limite do pescoço), **Bola** ou **Corrida**.
- Campo de visão ajustável, câmera lenta (0,25×) e **Gravar vídeo**, que baixa um `.webm` do lance inteiro na vista atual.
- Espaço: tocar ou pausar. ← →: avançar ou voltar um quadro.

## Limites
- Os dados (Last-Row / Friends of Tracking, @lastrowview) foram coletados à mão para animações: as posições são aproximadas e nem todos os 22 jogadores aparecem.
- Não há dado de para onde a cabeça do jogador estava virada; o olhar é estimado pela corrida e pela bola.
- Os bonecos são simples, sem animação de chute ou cabeceio.

## Estrutura
- `data/raw/` — CSVs originais do Last-Row.
- `scripts/prepare_lastrow.py` — converte para `web/data/lances.json` (o formato que a fase 2, vinda de vídeo, também vai gerar).
- `web/` — visualizador (three.js, sem build).
