"""Checagens de web/data/lances.json (saida de scripts/prepare_lastrow.py).

Uso: python3 -I scripts/test_lastrow.py
Sai com codigo 0 so se todas as checagens passarem.

Por lance:
  (a) estrutura: 20 fps, len(bola) == frames e len(pos) == frames para cada jogador.
  (b) colagem (A): nos segmentos ORIGINAIS da posse (data/posse/lastrow.json), a bola corrigida fica a ate 0,9 m
      do dono. Excecao so por quadro, com evidencia nos dados originais (scripts/evidencia.py). Meta: 99% por lance
      e 99% por fonte, com excecoes contando como ok.
  (c) cadastro: ids de lance unicos; o campo 'fonte' do Last-Row presente.
  (d) bola parada: quadro com velocidade ORIGINAL abaixo de 0,3 m/s nao e movido.
  (e) antes do primeiro toque (inicio da primeira posse) a bola fica como no original.
  (f) gol: o cruzamento da linha x = +-52,5 (instante e ponto) e igual ao original, e a bola nao volta ao campo
      depois de entrar (quadros a partir do cruzamento iguais ao original).
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidencia as EV  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
JSON_PATH = RAIZ / "web" / "data" / "lances.json"
POSSE_PATH = RAIZ / "data" / "posse" / "lastrow.json"
FPS = 20
LINHA_X = 52.5
PARADA_VEL = 0.3
TOL_M = 1e-3


def cruzamento(bola, linha=LINHA_X):
    """Primeiro cruzamento de |x| > linha: (instante em quadros, y, z) interpolados na linha, ou None."""
    for f in range(1, len(bola)):
        x0, x1 = bola[f - 1][0], bola[f][0]
        if abs(x1) > linha >= abs(x0):
            s = (linha * math.copysign(1, x1) - x0) / (x1 - x0)
            return (f - 1 + s, bola[f - 1][1] + s * (bola[f][1] - bola[f - 1][1]),
                    bola[f - 1][2] + s * (bola[f][2] - bola[f - 1][2]))
    return None


# Exceções decididas pelo coordenador, nominais e limitadas por distância (não são regra geral).
EXCECOES_ACEITAS = {
    "liverpool-3-0-bournemouth": {
        "max_dist": 1.4,
        "quadros": {("14", f) for f in range(91, 101)},   # pares jogador–quadro autorizados; qualquer outro reprova
        "motivo": "decisão de 20/10/2026: dono a 1,0–1,4 m da bola em 10 quadros; a correção que fecharia a distância exigiria salto de bola; visualmente a bola segue no pé",
    },
}


def main():
    erros = []
    lances = json.loads(JSON_PATH.read_text(encoding="utf-8"))["lances"]
    posse = json.loads(POSSE_PATH.read_text(encoding="utf-8")) if POSSE_PATH.exists() else None
    if posse is None or "originais" not in posse or "bola_original" not in posse:
        erros.append("sem data/posse/lastrow.json com 'originais', 'bola_original' e 'distancia_original' "
                     "(rode prepare_lastrow.py)")
        posse = {"originais": {}, "bola_original": {}, "distancia_original": {}, "recusados": {}}
    ids = [l["id"] for l in lances]
    if len(set(ids)) != len(ids):
        erros.append("ids de lance repetidos")

    tot_fonte = ok_fonte = 0
    linhas, abaixo99 = [], []
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

        segs = posse["originais"].get(l["id"], [])
        if not segs:
            linhas.append(f"{l.get('titulo', l['id'])[:40]:40} sem posse original")
            continue
        bola_orig = posse["bola_original"][l["id"]]
        dists = posse["distancia_original"][l["id"]]
        pos = {j["id"]: j["pos"] for j in l["jogadores"]}
        bola = l["bola"]

        def pos_fn(pid, f, pos=pos):
            p = pos.get(pid, [None] * n)[f]
            return None if p is None else (p[0], p[1])

        def bola_fn(f, bola=bola):
            return bola[f]

        rec = {(pid, f): k for pid, f, k in posse.get("recusados", {}).get(l["id"], [])}
        r = EV.avaliar(FPS, n, segs, dists, pos_fn, bola_fn, bola_orig, {}, rec)
        tot_fonte += r["tot"]
        ok_fonte += r["ok"] + sum(r["justificados"].values())
        exc = ", ".join(f"{k} {v}" for k, v in sorted(r["justificados"].items())) or "-"
        linhas.append(f"{l.get('titulo', l['id'])[:40]:40} quadros={r['tot']:4d}  ok={r['pct_ok']:6.2f}%  "
                      f"com excecao={r['pct_just']:6.2f}%  excecoes: {exc}")
        aceita = EXCECOES_ACEITAS.get(l["id"])
        if r["pct_just"] < EV.A_META_LANCE_PCT and aceita and r["falhas"] and all((str(p_), f_) in aceita["quadros"] for p_, f_, _, _ in r["falhas"]) and all(d <= aceita["max_dist"] for _, _, d, _ in r["falhas"]):
            linhas.append(f"    exceção aceita [{l['id']}]: {len(r['falhas'])} quadros a <= {aceita['max_dist']} m — {aceita['motivo']}")
        elif r["pct_just"] < EV.A_META_LANCE_PCT:
            erros.append(f"[{l['id']}] colagem (A) {r['pct_just']:.2f}% < {EV.A_META_LANCE_PCT}% (dists={[d for _, _, d, _ in r['falhas']]}) "
                         f"(sem evidencia original em {len(r['falhas'])} quadros: "
                         f"{[(p, f, d) for p, f, d, _ in r['falhas'][:4]]})")
        if r["pct_ok"] < 99.0:
            abaixo99.append(f"  [{l['id']}] ok {r['pct_ok']:.2f}%; excecoes por quadro: "
                            + "; ".join(f"{k}={v} (ex.: {r['exemplos'][k]})" for k, v in r["justificados"].items()))

        # (d) bola parada: nunca movida
        movidas = [f for f in range(n) if EV.vel_original(bola_orig, f, FPS) < PARADA_VEL
                   and max(abs(bola[f][0] - bola_orig[f][0]), abs(bola[f][1] - bola_orig[f][1])) > TOL_M]
        if movidas:
            erros.append(f"[{l['id']}] bola parada (original < 0,3 m/s) movida nos quadros {movidas[:5]}")
        # (e) antes da primeira posse: bola como no original
        a0 = min(s[1] for s in segs)
        antes = [f for f in range(0, a0) if max(abs(bola[f][0] - bola_orig[f][0]),
                                               abs(bola[f][1] - bola_orig[f][1])) > TOL_M]
        if antes:
            erros.append(f"[{l['id']}] bola mudou antes do primeiro toque (quadro {a0}): {antes[:5]}")
        # (f) gol: cruzamento igual ao original e bola nao volta ao campo depois de entrar
        cz_o, cz_c = cruzamento(bola_orig), cruzamento(bola)
        if cz_o is not None:
            fc = int(cz_o[0])
            if cz_c is None or abs(cz_c[0] - cz_o[0]) > 1e-6 or math.dist(cz_c[1:], cz_o[1:]) > TOL_M:
                erros.append(f"[{l['id']}] cruzamento da linha mudou: original {cz_o}, corrigido {cz_c}")
            dif = [f for f in range(max(0, fc - 2), n) if max(abs(bola[f][0] - bola_orig[f][0]),
                                                             abs(bola[f][1] - bola_orig[f][1])) > TOL_M]
            if dif:
                erros.append(f"[{l['id']}] bola mudou a partir da linha de gol (quadros {dif[:5]})")

    print("\n".join(linhas))
    if tot_fonte:
        pct = 100.0 * ok_fonte / tot_fonte
        print(f"(A) fonte Last-Row (ok + excecoes com evidencia): {ok_fonte} de {tot_fonte} = {pct:.2f}%")
        if pct < EV.A_META_FONTE_PCT:
            erros.append(f"(A) fonte Last-Row {pct:.2f}% < {EV.A_META_FONTE_PCT}%")
    if abaixo99:
        print("(A) lances abaixo de 99% (ok puro), com as excecoes por quadro e a evidencia original:")
        print("\n".join(abaixo99))
    if erros:
        print(f"\nFALHAS ({len(erros)}):")
        print("\n".join(erros))
        return 1
    print(f"\nOK: {len(lances)} lances, todas as checagens passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
