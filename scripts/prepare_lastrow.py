"""Converte os CSVs do Last-Row (Friends of Tracking) para o formato de lance do lance-pov.

Uso: python3 -I scripts/prepare_lastrow.py data/raw web/data/lances.json

Formato de saída (o mesmo que a fase 2 vai gerar a partir de vídeo):
{
  "lances": [{
    "id", "titulo", "fonte", "fps", "frames",
    "bola": [[x, y, z] | null, ...],                  # metros, por frame
    "jogadores": [{"id", "time", "numero", "nome", "cor", "borda",
                   "pos": [[x, y] | null, ...]}]      # metros, por frame
  }]
}
Também grava data/posse/lastrow.json: segmentos de posse colados (usados pela auditoria e pelo teste).
Sistema de coordenadas: campo 105 x 68 m, origem no centro, x para a direita
(da câmera de TV), y para o lado oposto à câmera; z para cima.
"""
import csv
import math
import re
import json
import sys
from collections import OrderedDict
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import posse  # noqa: E402  (colagem da posse, mesmo diretorio)

POSSE_SAIDA = SCRIPTS.parent / "data" / "posse" / "lastrow.json"  # segmentos colados (auditoria; fora de web/)

X_SIZE, Y_SIZE = 105.0, 68.0
FPS = 20
Z_MAX_M = 3.0  # o Last-Row grava a altura da bola de 0 a 1.5 sem unidade; aproximamos para até 3 m

# Camisas do Liverpool em 2019 (estáveis no ano, segundo o README do Last-Row).
NOMES_LIVERPOOL = {
    1: "Alisson", 3: "Fabinho", 4: "Van Dijk", 5: "Wijnaldum", 6: "Lovren",
    7: "Milner", 8: "Keïta", 9: "Firmino", 10: "Mané", 11: "Salah",
    12: "Joe Gomez", 13: "Adrián", 14: "Henderson", 15: "Oxlade-Chamberlain",
    20: "Lallana", 23: "Shaqiri", 26: "Robertson", 27: "Origi", 32: "Matip",
    66: "Alexander-Arnold",
}
NOMES_EXTRA = {("Real vs Barcelona — Calma", 7): "Cristiano Ronaldo"}
TIMES_EXTRA = {"Real vs Barcelona — Calma": {"attack": "Real Madrid", "defense": "Barcelona"}}
CONTEXTO = {
    "Liverpool [4] - 0 Barcelona": "Origi, após escanteio rápido de Alexander-Arnold (semifinal da Champions, mai/2019).",
    "Real vs Barcelona — Calma": "Cristiano Ronaldo no Camp Nou, o gol do \"calma, calma\" (abr/2012).",
}


def times(titulo):
    """Descobre o time atacante pelo placar entre colchetes ("Liverpool [4] - 0 Barcelona")."""
    if titulo in TIMES_EXTRA:
        return TIMES_EXTRA[titulo]
    esq, dir_ = titulo.split(" - ", 1)
    nome_esq = re.sub(r"\s*\[?\d+\]?$", "", esq).strip()
    nome_dir = re.sub(r"^\[?\d+\]?\s*", "", dir_).strip()
    if "[" in esq or ("[" not in dir_ and nome_esq == "Liverpool"):
        return {"attack": nome_esq, "defense": nome_dir}
    return {"attack": nome_dir, "defense": nome_esq}


# Autor do gol quando a heurística do visualizador (atacante mais perto da bola antes do gol) erra.
FINALIZADOR = {"Fulham 0 - [1] Liverpool": 10}  # Mané (relatório oficial do Liverpool FC)

TITULOS = {"Real vs Barcelona — Calma": "Barcelona 1 × 2 Real Madrid"}


def placar(titulo):
    if titulo in TITULOS:
        return TITULOS[titulo]
    return titulo.replace("[", "").replace("]", "").replace(" - ", " × ")

ARQUIVOS = [
    # (arquivo, coluna do lance ou título fixo)
    ("liverpool_2019.csv", None),
    # LIV_[2]-1_CHE.csv ficou de fora: é o mesmo gol do arquivo principal, espelhado no eixo x.
    ("Real_vs_Barcelona_Calma.csv", "Real vs Barcelona — Calma"),
]


# Posse por heuristica (o Last-Row nao tem eventos). Ver detectar_posse().
ALCANCE_M = 3.5        # m: candidato a dono = jogador a ate isso da bola
COS_MIN = 0.3          # cosseno minimo entre o movimento do jogador e o da bola (bola >= BOLA_LENTA)
BOLA_LENTA = 2.0       # m/s: abaixo disso, qualquer jogador perto serve
BOLA_MIN, BOLA_MAX = 0.3, 9.0  # m/s: faixa de bola em que ha dono (abaixo: bola parada; acima: passe/chute)
Z_POSSE_LR = 0.6       # m: bola acima disso nao esta no pe
HISTERESE_Q = 5        # quadros (0,25 s) que um candidato novo precisa para tirar a bola de quem a tem
FOLGA_Q = 2            # quadros sem candidato antes de a bola ser solta
SEG_MIN_Q = 5          # quadros (0,25 s): segmento menor que isso e descartado
VMAX_JOG = 10.3        # m/s: limite da colagem (margem para o arredondamento a 3 casas)


def _vel(pts, i, fps):
    n = len(pts)
    a, b = max(0, i - 1), min(n - 1, i + 1)
    if a == b or pts[a] is None or pts[b] is None:
        return None
    dt = (b - a) / fps
    return ((pts[b][0] - pts[a][0]) / dt, (pts[b][1] - pts[a][1]) / dt)


def detectar_posse(lance):
    """Segmentos de posse (id, ini, fim) em quadros, por heuristica sobre a bola e os jogadores.

    Candidato no quadro: bola no chao (z < Z_POSSE_LR) e andando entre BOLA_MIN e BOLA_MAX; jogador a
    ate ALCANCE_M da bola; se a bola anda >= BOLA_LENTA, o jogador tambem tem de andar para o mesmo lado
    da bola (cosseno >= COS_MIN). Vence o candidato mais perto. Quem tem a bola so perde para outro
    candidato depois de HISTERESE_Q quadros seguidos, ou quando nao ha candidato por mais de FOLGA_Q."""
    fps = lance["fps"]
    n = lance["frames"]
    bola = lance["bola"]
    b2 = [(b[0], b[1]) for b in bola]
    vb = [_vel(b2, i, fps) or (0.0, 0.0) for i in range(n)]
    sb = [math.hypot(*v) for v in vb]
    jog = {j["id"]: j["pos"] for j in lance["jogadores"]}
    velj = {pid: [_vel(pts, i, fps) for i in range(n)] for pid, pts in jog.items()}

    def candidato(pid, f):
        p = jog[pid][f]
        if p is None:
            return None
        d = math.dist(p, b2[f])
        if d > ALCANCE_M:
            return None
        if sb[f] >= BOLA_LENTA:
            v = velj[pid][f]
            if v is None or math.hypot(*v) < 0.3:
                return None
            cos = (v[0] * vb[f][0] + v[1] * vb[f][1]) / (math.hypot(*v) * sb[f])
            if cos < COS_MIN:
                return None
        return d

    cand = [None] * n
    for f in range(n):
        if not (bola[f][2] < Z_POSSE_LR and BOLA_MIN <= sb[f] <= BOLA_MAX):
            continue
        melhor = None
        for pid in jog:
            d = candidato(pid, f)
            if d is not None and (melhor is None or d < melhor[1]):
                melhor = (pid, d)
        cand[f] = melhor[0] if melhor else None

    dono = None
    miss = 0
    chal, chal_n = None, 0
    seq = [None] * n
    for f in range(n):
        c = cand[f]
        if dono is None:
            if c is not None:
                dono, miss, chal, chal_n = c, 0, None, 0
        elif c == dono:
            miss, chal, chal_n = 0, None, 0
        elif c is None:
            miss += 1
            if miss > FOLGA_Q:
                dono, chal, chal_n = None, None, 0
        elif candidato(dono, f) is not None:
            if chal == c:
                chal_n += 1
            else:
                chal, chal_n = c, 1
            if chal_n >= HISTERESE_Q:
                dono, miss, chal, chal_n = c, 0, None, 0
        else:
            dono, miss, chal, chal_n = c, 0, None, 0
        seq[f] = dono if (dono is not None and miss <= FOLGA_Q) else None

    segs = []
    f = 0
    while f < n:
        if seq[f] is None:
            f += 1
            continue
        g = f
        while g + 1 < n and seq[g + 1] == seq[f]:
            g += 1
        if g - f + 1 >= SEG_MIN_Q:
            segs.append((seq[f], f, g))
        f = g + 1
    return segs


def colar_lance(lance):
    """Posse original (segmentos a partir do toque, antes de qualquer correcao) e correcao da bola: onde o dono
    esta atrasado dentro da posse, a BOLA vai ao pe dele (a bola deste lance e rastreada a mao). Os jogadores
    nao se movem. Devolve (segmentos originais, segmentos, relatorio)."""
    pos = {j["id"]: j["pos"] for j in lance["jogadores"]}
    bola_orig = [[round(x, 3), round(y, 3), round(z, 3)] for x, y, z in lance["bola"]]
    segs = posse.segmentos_originais(lance["fps"], lance["bola"], pos, z_max=Z_POSSE_LR)
    nova, rel = posse.bola_no_pe(lance["fps"], lance["bola"], pos, segs,
                                 lim=(X_SIZE / 2 - 0.1, Y_SIZE / 2 - 0.1))
    lance["bola"] = nova
    rel["recusados_lista"] = [[pid, f, k] for pid, f, k in rel.pop("recusados")]
    dist_orig = [[round(math.dist(pos[pid][f], bola_orig[f][:2]), 3) if pos[pid][f] is not None else None
                  for f in range(a, b + 1)] for pid, a, b, *_ in segs]
    return segs, segs, rel, bola_orig, dist_orig


def metros(x, y):
    return round(float(x) / 100 * X_SIZE - X_SIZE / 2, 3), round(float(y) / 100 * Y_SIZE - Y_SIZE / 2, 3)


def numero(valor):
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def ler(caminho, titulo_fixo):
    lances = OrderedDict()
    with open(caminho, newline="") as f:
        for r in csv.DictReader(f):
            titulo = titulo_fixo or r["play"]
            lance = lances.setdefault(titulo, {"linhas": []})
            lance["linhas"].append(r)
    return lances


def montar(titulo, linhas):
    n = max(int(r["frame"]) for r in linhas) + 1
    bola = [None] * n
    jogadores = OrderedDict()
    for r in linhas:
        fr = int(r["frame"])
        x, y = metros(r["x"], r["y"])
        if r["player"] == "0":
            z = round(min(float(r["z"] or 0), 1.5) / 1.5 * Z_MAX_M, 3)
            bola[fr] = [x, y, z]
            continue
        j = jogadores.get(r["player"])
        if j is None:
            num = numero(r.get("player_num")) or numero(r.get("num"))
            nome = None
            if num is not None:
                nome = NOMES_EXTRA.get((titulo, num))
                if nome is None and r["team"] == "attack" and "Liverpool" in titulo:
                    nome = NOMES_LIVERPOOL.get(num)
            j = jogadores[r["player"]] = {
                "id": r["player"], "time": r["team"], "numero": num, "nome": nome,
                "cor": r["bgcolor"], "borda": r["edgecolor"], "pos": [None] * n,
            }
        j["pos"][fr] = [x, y]
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", titulo.lower()).strip("-"), "titulo": placar(titulo),
        "times": times(titulo), "contexto": CONTEXTO.get(titulo), "finalizadorNumero": FINALIZADOR.get(titulo),
        "fonte": "Last-Row / Friends of Tracking (@lastrowview)", "fps": FPS, "frames": n,
        "bola": bola, "jogadores": list(jogadores.values()),
    }


def main(origem, destino):
    saida = []
    for nome, titulo in ARQUIVOS:
        for t, lance in ler(Path(origem) / nome, titulo).items():
            saida.append(montar(t, lance["linhas"]))
    posse_lances = {}
    posse_originais = {}
    bola_original = {}
    distancia_original = {}
    recusados = {}
    for l in saida:
        originais, runs, rel, bola_orig, dist_orig = colar_lance(l)
        recusados[l["id"]] = rel["recusados_lista"]
        posse_lances[l["id"]] = [list(s) for s in runs]
        posse_originais[l["id"]] = [list(s) for s in originais]
        bola_original[l["id"]] = bola_orig
        distancia_original[l["id"]] = dist_orig
        print(f"{l['titulo']}: {l['frames']} frames, {len(l['jogadores'])} jogadores; "
              f"posse original {len(originais)} segmentos; bola ao pe: {rel['quadros_movidos']} quadros, "
              f"deslocamento max {rel['deslocamento_max']} m, vel max {rel['vel_max']} m/s, "
              f"segmentos corrigidos {rel['segmentos_com_correcao']}, atrasos restantes {rel['atrasos_restantes']}, "
              f"velocidade acima do limite {rel['vel_excedida']}")
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w") as f:
        json.dump({"lances": saida}, f, separators=(",", ":"), ensure_ascii=False)
    POSSE_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(POSSE_SAIDA, "w", encoding="utf-8") as f:
        json.dump({"fps": FPS, "lances": posse_lances, "originais": posse_originais,
                   "bola_original": bola_original, "distancia_original": distancia_original,
                   "recusados": recusados},
                  f, ensure_ascii=False, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
