"""Checagens de web/data/hypados.json (saida de scripts/prepare_statsbomb.py).

Uso: python3 -I scripts/test_statsbomb.py
Sai com codigo 1 se alguma checagem falhar.

Por lance:
  (a) finalizador a menos de 1,5 m da bola no quadro do chute (frameChute). Origi (Last-Row, sem
      quadro de chute no StatsBomb): menor distancia entre o finalizador e a bola nos 2 s antes de a
      bola cruzar a linha de gol.
  (b) a bola cruza a linha de gol +x depois do chute com |y| < 3,66 e z < 2,44.
  (c) nenhum jogador passa de 10,5 m/s e a bola nao passa de 45 m/s (pares de quadros consecutivos).
  (d) pelo menos 8 jogadores.
  (e) len(bola) == frames e len(pos) == frames para cada jogador.
  (g) jogadores ate 3 m fora das linhas: |x| <= 55,5 e |y| <= 37 (goleiro: x <= 54,5, nao verificado aqui).
Orientacao (f): Bale (cruzamento do Marcelo com y > 0) e Carlos Alberto (chute com y < 0).
"""

import json
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JSON_PATH = RAIZ / "web" / "data" / "hypados.json"
FPS = 20
LINHA_GOL = 52.5


def achar(lances, prefixo):
    for l in lances:
        if l["titulo"].startswith(prefixo):
            return l
    raise KeyError(prefixo)


def main():
    dados = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    lances = dados["lances"]
    falhas = []

    def falha(lance, msg):
        falhas.append(f"{lance['ordem']:>2} {lance['titulo']}: {msg}")

    if len(lances) != 30:
        falha({"ordem": 0, "titulo": "arquivo"}, f"{len(lances)} lances (esperado 30)")
    ordens = sorted(l["ordem"] for l in lances)
    if ordens != list(range(1, 31)):
        falha({"ordem": 0, "titulo": "arquivo"}, f"ordem fora de 1..30: {ordens}")

    resumo = []
    for l in sorted(lances, key=lambda z: z["ordem"]):
        n = l["frames"]
        bola = l["bola"]
        jogs = l["jogadores"]
        # (e)
        if len(bola) != n:
            falha(l, f"bola com {len(bola)} quadros (frames={n})")
        for j in jogs:
            if len(j["pos"]) != n:
                falha(l, f"jogador {j['nome']} com {len(j['pos'])} quadros (frames={n})")
        # (d)
        if len(jogs) < 8:
            falha(l, f"so {len(jogs)} jogadores (minimo 8)")
        # (c)
        vmax_j = 0.0
        for j in jogs:
            p = j["pos"]
            for i in range(1, len(p)):
                if p[i] is None or p[i - 1] is None:
                    continue
                v = math.dist(p[i], p[i - 1]) * FPS
                vmax_j = max(vmax_j, v)
        if vmax_j > 10.5 + 1e-6:
            falha(l, f"jogador a {vmax_j:.2f} m/s (max 10,5)")
        vmax_b = 0.0
        for i in range(1, n):
            if bola[i] is None or bola[i - 1] is None:
                continue
            vmax_b = max(vmax_b, math.dist(bola[i], bola[i - 1]) * FPS)
        if vmax_b > 45.0:
            falha(l, f"bola a {vmax_b:.2f} m/s (max 45)")

        # (g) limite do campo: jogadores ate 3 m fora das linhas (|x| <= 55,5, |y| <= 37)
        for j in jogs:
            if any(p is not None and (abs(p[0]) > 55.5 + 1e-6 or abs(p[1]) > 37.0 + 1e-6) for p in j["pos"]):
                falha(l, f"jogador {j['nome']} fora do campo +3 m")
                break

        fin_id = str(l["finalizadorId"])
        fin = next((j for j in jogs if j["id"] == fin_id), None)
        if fin is None:
            falha(l, "finalizador ausente em jogadores")
            continue

        # (a) e (b)
        if "frameChute" in l:
            c = l["frameChute"]
            b = bola[c]
            p = fin["pos"][c]
            if b is None or p is None:
                falha(l, "sem bola/jogador no quadro do chute")
                dist_a = None
            else:
                dist_a = math.dist((b[0], b[1]), tuple(p))
                if dist_a >= 1.5:
                    falha(l, f"finalizador a {dist_a:.2f} m da bola no chute (max 1,5)")
            inicio = c
        else:
            # Origi: primeiro quadro em que a bola cruza a linha de gol +x
            inicio = next(i for i in range(1, n) if bola[i] and bola[i - 1] and bola[i][0] > LINHA_GOL >= bola[i - 1][0])
            dists = [math.dist((bola[i][0], bola[i][1]), tuple(fin["pos"][i])) for i in range(max(0, inicio - 40), inicio + 1)
                     if bola[i] and fin["pos"][i]]
            dist_a = min(dists) if dists else None
            if dist_a is None or dist_a >= 1.5:
                falha(l, f"finalizador a {dist_a} m da bola antes do gol (max 1,5)")
            c = None
        cruz = next((i for i in range(inicio + 1, n) if bola[i] and bola[i][0] > LINHA_GOL), None)
        if cruz is None:
            falha(l, "bola nao cruza a linha de gol apos o chute")
        else:
            y, z = bola[cruz][1], bola[cruz][2]
            if not (abs(y) < 3.66 and z < 2.44):
                falha(l, f"cruzamento com y={y:.2f} z={z:.2f} (exige |y|<3,66 e z<2,44)")

        resumo.append(f"{l['ordem']:>2} {l['titulo']:<36} frames={n:<4} jog={len(jogs):<3} "
                      f"v_jog={vmax_j:5.2f} v_bola={vmax_b:5.1f} dist_fin={'-' if dist_a is None else f'{dist_a:.2f}'} "
                      f"cruz_y={'-' if cruz is None else f'{bola[cruz][1]:+.2f}'}")

    # (f) orientacao
    bale = achar(lances, "Bale")
    if "frameChute" in bale:
        c = bale["frameChute"]
        # cruzamento: no ultimo segundo antes do chute, a bola esta no terco final (x >= 25 m)
        pts = [bola_xy for bola_xy in (bale["bola"][i] for i in range(max(0, c - 20), c)) if bola_xy and bola_xy[0] >= 25.0]
        if not pts:
            falha(bale, "orientacao: bola nao chega ao terco final antes do chute")
        else:
            media_y = sum(p[1] for p in pts) / len(pts)
            if media_y <= 0:
                falha(bale, f"orientacao: cruzamento com y medio {media_y:.2f} (esperado > 0, lado esquerdo do ataque)")
            resumo.append(f"    orientacao Bale: y medio do cruzamento = {media_y:+.2f}")
    carlos = achar(lances, "Carlos Alberto")
    c = carlos["frameChute"]
    yc = carlos["bola"][c][1]
    if not yc < 0:
        falha(carlos, f"orientacao: chute com y={yc:.2f} (esperado < 0, lado direito do ataque)")
    resumo.append(f"    orientacao Carlos Alberto: y do chute = {yc:+.2f}")

    print("\n".join(resumo))
    if falhas:
        print(f"\nFALHAS ({len(falhas)}):")
        print("\n".join(falhas))
        return 1
    print(f"\nOK: {len(lances)} lances, todas as checagens passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
