"""Checagens de web/data/lances.json (saida de scripts/prepare_lastrow.py).

Uso: python3 -I scripts/test_lastrow.py
Sai com codigo 1 se alguma checagem falhar.

Por lance:
  (a) estrutura: 20 fps, len(bola) == frames e len(pos) == frames para cada jogador.
  (b) colagem (A): dentro dos segmentos ORIGINAIS (data/posse/lastrow.json, chave "originais": posse a partir
      do toque, ate a saida da bola), a bola corrigida fica a ate 0,9 m do dono. Fonte inteira >= 99%; por lance,
      abaixo de 95% so passa com motivo de dado listado. Denominador integral; excecoes ficam no denominador.
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
A_META_FONTE_PCT = 99.0   # % (A) da fonte inteira (denominador integral)
A_META_LANCE_PCT = 95.0   # % (A) de cada lance: abaixo disso, so passa com motivo de dado listado
MOTIVOS_DADO = ("bola em voo", "atraso apos conflito de velocidade", "atraso ate 0,5 s depois de bola em voo",
                "evento fora da cadeia de bola")
VMAX_BOLA_CORTE = 10.3  # m/s: bola acima disso nao esta no pe (mesmo corte da colagem)


def main():
    erros = []
    lances = json.loads(JSON_PATH.read_text(encoding="utf-8"))["lances"]
    posse = json.loads(POSSE_PATH.read_text(encoding="utf-8")) if POSSE_PATH.exists() else None
    if posse is None or "originais" not in posse:
        erros.append("sem data/posse/lastrow.json com 'originais' (rode prepare_lastrow.py)")
        posse = {"originais": {}}
    originais = posse["originais"]
    ids = [l["id"] for l in lances]
    if len(set(ids)) != len(ids):
        erros.append("ids de lance repetidos")

    a_total = a_bons = 0
    linhas = []
    abaixo99 = []
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

        segs = originais.get(l["id"], [])
        pos = {j["id"]: j["pos"] for j in l["jogadores"]}
        tot = bons = 0
        pior = 0.0
        excecoes = {}
        for pid, a, b, *_ in segs:
            for f in range(max(0, a), min(n - 1, b) + 1):
                p = pos.get(pid, [None] * n)[f]
                bf = l["bola"][f]
                tot += 1
                if p is None or bf is None:
                    excecoes["sem dado"] = excecoes.get("sem dado", 0) + 1
                    continue
                d = math.hypot(p[0] - bf[0], p[1] - bf[1])
                if d <= A_LIMITE_M:
                    bons += 1
                    continue
                pior = max(pior, d)
                g = f - 1 if f > 0 else f + 1
                v = math.hypot(l["bola"][g][0] - bf[0], l["bola"][g][1] - bf[1]) * FPS if l["bola"][g] else 0.0
                if v > VMAX_BOLA_CORTE:
                    motivo = "bola em voo"
                elif f - a < FPS:
                    motivo = "entrada: dono ainda chegando (1 s do inicio do segmento original)"
                elif b - f < FPS:
                    motivo = "saida: dono ja se afastou (1 s do fim do segmento original)"
                else:
                    motivo = "sem motivo"
                excecoes[motivo] = excecoes.get(motivo, 0) + 1
        a_total += tot
        a_bons += bons
        pct = 100 * bons / tot if tot else None
        if tot and pct < A_META_LANCE_PCT and not any(k in MOTIVOS_DADO for k in excecoes):
            erros.append(f"[{l['id']}] colagem (A) real {pct:.2f}% sem motivo de dado ({bons}/{tot} quadros originais "
                         f"a ate {A_LIMITE_M} m; pior {pior:.2f} m); excecoes: {excecoes}")
        elif tot and pct < 99.0:
            abaixo99.append(f"[{l['id']}] {pct:.2f}% (excecoes: {excecoes})")
        linhas.append(f"{l.get('titulo', l['id'])[:40]:40} originais={len(segs):2d} segs  quadros={tot:4d}  "
                      f"(A)={'-' if pct is None else f'{pct:6.2f}%'}  excecoes={excecoes or '-'}")

    print("\n".join(linhas))
    print(f"(A) colagem real (originais, denominador integral): {a_bons} de {a_total} quadros a ate "
          f"{A_LIMITE_M} m do dono ({100 * a_bons / max(1, a_total):.2f}%)")
    if a_total and 100 * a_bons / a_total < A_META_FONTE_PCT:
        erros.append(f"(A) fonte Last-Row {100 * a_bons / a_total:.2f}% (meta {A_META_FONTE_PCT}%)")
    if abaixo99:
        print("(A) abaixo de 99% (informativo; acima de 95% ou com motivo):")
        print("\n".join("  " + x for x in abaixo99))
    if erros:
        print(f"\nFALHAS ({len(erros)}):")
        print("\n".join(erros))
        return 1
    print(f"\nOK: {len(lances)} lances, todas as checagens passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
