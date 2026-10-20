"""Checagens de web/data/lances.json (saida de scripts/prepare_lastrow.py).

Uso: python3 -I scripts/test_lastrow.py
Sai com codigo 1 se alguma checagem falhar.

Por lance:
  (a) estrutura: 20 fps, len(bola) == frames e len(pos) == frames para cada jogador.
  (b) colagem (A): dentro dos segmentos de posse detectados (data/posse/lastrow.json), o dono fica a
      ate 0,9 m da bola em pelo menos 99% dos quadros, por lance. Lance sem segmento e listado.
  (c) orientacao e cadastro: ids de lance unicos; o campo 'fonte' do Last-Row presente.
"""

import json
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JSON_PATH = RAIZ / "web" / "data" / "lances.json"
POSSE_PATH = RAIZ / "data" / "posse" / "lastrow.json"
FPS = 20
A_LIMITE_M = 0.9
A_META_PCT = 99.0


def main():
    erros = []
    lances = json.loads(JSON_PATH.read_text(encoding="utf-8"))["lances"]
    posse = json.loads(POSSE_PATH.read_text(encoding="utf-8"))["lances"] if POSSE_PATH.exists() else None
    if posse is None:
        erros.append("sem data/posse/lastrow.json (rode prepare_lastrow.py)")
    ids = [l["id"] for l in lances]
    if len(set(ids)) != len(ids):
        erros.append("ids de lance repetidos")

    a_total = a_bons = 0
    linhas = []
    for l in lances:
        n = l["frames"]
        if l["fps"] != FPS:
            erros.append(f"[{l['id']}] fps {l['fps']} (esperado {FPS})")
        if len(l["bola"]) != n:
            erros.append(f"[{l['id']}] bola com {len(l['bola'])} quadros (frames={n})")
        for j in l["jogadores"]:
            if len(j["pos"]) != n:
                erros.append(f"[{l['id']}] jogador {j['id']} com {len(j['pos'])} quadros (frames={n})")
        if not l.get("fonte", "").startswith("Last-Row"):
            erros.append(f"[{l['id']}] fonte inesperada: {l.get('fonte')!r}")

        segs = (posse or {}).get(l["id"], [])
        pos = {j["id"]: j["pos"] for j in l["jogadores"]}
        tot = bons = 0
        pior = 0.0
        for pid, a, b in segs:
            for f in range(max(0, a), min(n - 1, b) + 1):
                p = pos.get(pid, [None] * n)[f]
                bf = l["bola"][f]
                if p is None or bf is None:
                    continue
                d = math.hypot(p[0] - bf[0], p[1] - bf[1])
                tot += 1
                bons += d <= A_LIMITE_M
                pior = max(pior, d if d > A_LIMITE_M else 0.0)
        a_total += tot
        a_bons += bons
        pct = 100 * bons / tot if tot else None
        if tot and pct < A_META_PCT:
            erros.append(f"[{l['id']}] colagem (A): {pct:.1f}% dos quadros de posse a ate {A_LIMITE_M} m "
                         f"(meta {A_META_PCT}%), pior {pior:.2f} m")
        linhas.append(f"{l.get('titulo', l['id'])[:40]:40} posse={len(segs):2d} segs  quadros={tot:4d}  "
                      f"(A)={'-' if pct is None else f'{pct:6.2f}%'}")

    print("\n".join(linhas))
    print(f"(A) colagem: {a_bons} de {a_total} quadros de posse a ate {A_LIMITE_M} m do dono "
          f"({100 * a_bons / max(1, a_total):.2f}%)")
    if erros:
        print(f"\nFALHAS ({len(erros)}):")
        print("\n".join(erros))
        return 1
    print(f"\nOK: {len(lances)} lances, todas as checagens passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
