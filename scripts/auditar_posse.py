"""Audita a distancia entre bola e jogador nos tres conjuntos de lances.

Uso: python3 -I scripts/auditar_posse.py [--limite 1.8] [--detalhe] [--dados DIR]

Duas medidas, por lance:

(A) Dentro dos segmentos de posse (data/posse/*.json, gerados pelos geradores): distancia
    dono-bola em cada quadro do segmento. Meta: <= 0,9 m em >= 99% dos quadros.
    Lances sem segmentos registrados (roteiros brasileiros, por enquanto) ficam como "sem posse".

(B) Metrica generica: quadros com a bola no chao (z < 0,5 m), dentro do campo e andando entre
    0,5 e 9 m/s. Conta os que tem jogador a mais de --limite m da bola. Meta: <= 5% por lance e
    nenhum trecho continuo maior que 0,5 s. Lances fora da meta sao listados com o instante.

Roteiros (brasil.json) sao expandidos a 20 fps com a mesma interpolacao do visualizador.
--dados DIR le os JSONs de outra pasta (mesmos nomes); os segmentos sempre vem de data/posse/.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_statsbomb as TS  # noqa: E402  (mesma classificacao de conflito do dado usada pelo teste)

RAIZ = Path(__file__).resolve().parent.parent
RAIZ_DADOS = RAIZ / "web" / "data"
RAIZ_POSSE = RAIZ / "data" / "posse"
FPS_ROTEIRO = 20
ARQUIVOS = ["hypados.json", "brasil.json", "lances.json"]
META_A = 0.9       # m: distancia dono-bola dentro da posse
META_A_PCT = 99.0  # % dos quadros de posse
META_B_PCT = 5.0   # % dos quadros da metrica (B) longe da bola
META_B_TRECHO = 0.5  # s: maior trecho continuo longe da bola
VEL_B_MIN, VEL_B_MAX = 0.5, 9.0  # m/s: faixa de bola da metrica (B)
Z_CHAO = 0.5
LIM_X = 52.5


def expandir(chaves, n, fps, suave):
    ks = sorted(chaves, key=lambda k: k[0])
    dims = len(ks[0]) - 1
    out, i = [], 0
    for f in range(n):
        t = f / fps
        if t <= ks[0][0]:
            out.append(ks[0][1:]); continue
        if t >= ks[-1][0]:
            out.append(ks[-1][1:]); continue
        while i < len(ks) - 2 and t > ks[i + 1][0]:
            i += 1
        k1, k2 = ks[i], ks[i + 1]
        u = (t - k1[0]) / max(1e-6, k2[0] - k1[0])
        v = []
        for d in range(1, dims + 1):
            if not suave:
                v.append(k1[d] + (k2[d] - k1[d]) * u); continue
            k0 = ks[i - 1] if i > 0 else k1
            k3 = ks[i + 2] if i + 2 < len(ks) else k2
            p0, p1, p2, p3 = k0[d], k1[d], k2[d], k3[d]
            v.append(0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3))
        out.append(v)
    return out


def arrays(l):
    if l.get("roteiro"):
        n = round(l["duracao"] * FPS_ROTEIRO) + 1
        bola = expandir(l["chavesBola"], n, FPS_ROTEIRO, False)
        jog = [(j["id"], expandir(j["chaves"], n, FPS_ROTEIRO, True)) for j in l["jogadores"]]
        return FPS_ROTEIRO, n, bola, jog
    ult = next(b for b in l["bola"] if b)
    bola = []
    for b in l["bola"]:
        ult = b or ult
        bola.append(ult if len(ult) == 3 else [ult[0], ult[1], 0])
    return l["fps"], l["frames"], bola, [(j["id"], j["pos"]) for j in l["jogadores"]]


def carregar_posse(pasta):
    """id do lance -> lista de (id do jogador, ini, fim) em quadros de 20 fps. Junta todos os arquivos."""
    segs = {}
    for arq in sorted(pasta.glob("*.json")):
        dados = json.loads(arq.read_text(encoding="utf-8"))
        for lid, lista in dados.get("lances", {}).items():
            segs.setdefault(lid, []).extend((str(p), int(a), int(b)) for p, a, b in lista)
    return segs


def medir_a(l, segs, janelas=()):
    """(A): (quadros, quadros dentro de META_A, pior distancia, instante da pior, quadros de conflito excluidos).
    Quadro longe do dono com motivo de conflito do dado (test_statsbomb.motivo_conflito) sai do calculo."""
    fps, n, bola, jog = arrays(l)
    pos = dict(jog)
    tot = bons = excl = 0
    pior, t_pior = 0.0, None
    for pid, a, b in segs:
        p = pos.get(pid)
        if p is None:
            continue
        for f in range(max(0, a), min(n - 1, b) + 1):
            if p[f] is None:
                continue
            d = math.hypot(p[f][0] - bola[f][0], p[f][1] - bola[f][1])
            if d <= META_A:
                tot += 1
                bons += 1
                continue
            if TS.motivo_conflito(bola, n, pid, f, f / fps, None, janelas):
                excl += 1
                continue
            tot += 1
            if d > pior:
                pior, t_pior = d, f / fps
    return tot, bons, pior, t_pior, excl


def medir_b(l, limite):
    """(B): dict com quadros dominados, longe, pior distancia, maior trecho continuo (s) e instante."""
    fps, n, bola, jog = arrays(l)
    ruins = dominada = 0
    pior, t_pior = 0.0, None
    seq, maior_seq, inicio_maior = 0, 0, None
    for f in range(n):
        b = bola[f]
        a, c = bola[max(0, f - 1)], bola[min(n - 1, f + 1)]
        dt = (min(n - 1, f + 1) - max(0, f - 1)) / fps
        vel = math.hypot(c[0] - a[0], c[1] - a[1]) / dt if dt else 0
        if abs(b[0]) > LIM_X or b[2] >= Z_CHAO or not (VEL_B_MIN <= vel <= VEL_B_MAX):
            seq = 0
            continue
        dominada += 1
        d = min((math.hypot(p[f][0] - b[0], p[f][1] - b[1]) for _, p in jog if p[f]), default=99)
        if d > limite:
            ruins += 1
            seq += 1
            if d > pior:
                pior, t_pior = d, f / fps
            if seq > maior_seq:
                maior_seq, inicio_maior = seq, (f - seq + 1) / fps
        else:
            seq = 0
    return {"dominada": dominada, "ruins": ruins, "pior": pior, "t_pior": t_pior,
            "maior_seq_s": maior_seq / fps, "t_maior": inicio_maior}


def carregar_janelas(pasta):
    """id do lance -> janelas de atraso registradas (data/posse/statsbomb.json; o Last-Row nao tem)."""
    arq = pasta / "statsbomb.json"
    if not arq.exists():
        return {}
    anc = json.loads(arq.read_text(encoding="utf-8")).get("ancoras", {})
    return {lid: TS.janelas_de({"ancoras": {lid: v}}, lid) for lid, v in anc.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=float, default=1.8)
    ap.add_argument("--detalhe", action="store_true")
    ap.add_argument("--dados", type=Path, default=RAIZ_DADOS)
    a = ap.parse_args()
    segs = carregar_posse(RAIZ_POSSE)
    janelas = carregar_janelas(RAIZ_POSSE)
    tot_a = bons_a = excl_a = 0
    tot_b_ruins = tot_b_dom = 0
    falhas_a, falhas_b = [], []
    for nome in ARQUIVOS:
        lances = json.loads((a.dados / nome).read_text(encoding="utf-8"))["lances"]
        print(f"\n== {nome}")
        for l in lances:
            ra = medir_a(l, segs.get(l["id"], []), janelas.get(l["id"], ())) if l["id"] in segs else None
            rb = medir_b(l, a.limite)
            tot_b_ruins += rb["ruins"]
            tot_b_dom += rb["dominada"]
            pct_b = 100 * rb["ruins"] / rb["dominada"] if rb["dominada"] else 0
            marca_b = pct_b > META_B_PCT or rb["maior_seq_s"] > META_B_TRECHO
            if ra is not None:
                tot_a += ra[0]
                bons_a += ra[1]
                excl_a += ra[4]
                pct_a = 100 * ra[1] / ra[0] if ra[0] else 100
                marca_a = pct_a < META_A_PCT
                txt_a = f"A {ra[1]:4d}/{ra[0]:4d} ok ({pct_a:6.2f}%) pior={ra[2]:5.2f} m"
                if marca_a:
                    falhas_a.append(f"{l.get('ordem', '')} {l['titulo']}: {pct_a:.2f}% ok, pior {ra[2]:.2f} m em {ra[3]:.2f}s")
            else:
                marca_a = False
                txt_a = "A sem posse registrada"
            if marca_b:
                falhas_b.append(f"{l.get('ordem', '')} {l['titulo']}: {pct_b:.1f}% longe, trecho {rb['maior_seq_s']:.2f}s em {rb['t_maior'] or 0:.2f}s")
            if a.detalhe or marca_a or marca_b:
                tp = f"{rb['t_pior']:.2f}s" if rb["t_pior"] is not None else "-"
                print(f"  {str(l.get('ordem', '')):>3} {l['titulo'][:40]:40} {txt_a} | B dom={rb['dominada']:4d} "
                      f"longe={rb['ruins']:4d} ({pct_b:4.1f}%) pior={rb['pior']:5.1f} m em {tp:>7} "
                      f"trecho={rb['maior_seq_s']:.2f}s{'  <<' if (marca_a or marca_b) else ''}")
    print(f"\nTOTAL (A): {bons_a} de {tot_a} quadros de posse a até {META_A} m do dono ({100 * bons_a / max(1, tot_a):.2f}%)")
    print(f"TOTAL (B): {tot_b_ruins} de {tot_b_dom} quadros com bola andando 0,5-9 m/s estao a mais de {a.limite} m "
          f"de qualquer jogador ({100 * tot_b_ruins / max(1, tot_b_dom):.1f}%)")
    print(f"quadros de posse fora do calculo (A) por conflito do dado: {excl_a}")
    print(f"fora da meta (A): {len(falhas_a)}" + ("".join(f"\n  {x}" for x in falhas_a)))
    print(f"fora da meta (B): {len(falhas_b)}" + ("".join(f"\n  {x}" for x in falhas_b)))


if __name__ == "__main__":
    main()
