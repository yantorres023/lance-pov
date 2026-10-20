#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera web/data/brasil.json: 13 gols do futebol brasileiro como roteiros aproximados.

Uso: python3 -I scripts/roteiros_brasil.py

Não há dado de posição destes gols. Cada lance é um desenho plausível a partir
das descrições (ver .claude/familia/tarefa-operario-brasil.md no projeto).
Convenção: campo 105 x 68 m, origem no centro, o time que marca ataca para +x,
+y é a esquerda de quem ataca, z é a altura da bola em metros.
Bola: quadros-chave [t, x, y, z], interpolação linear.
Jogadores: quadros-chave [t, x, y], Catmull-Rom (como em web/app.js).

gerar() devolve, para cada lance, (dicionário do JSON, metadados). Os metadados
(toques, instante do chute, goleiro) são internos: só o teste os usa e não vão
para o arquivo.

Elenco: cada time fica com 11 jogadores em cada lance. Os nomeados ficam nos
quadros indicados; o resto ocupa posições de um 4-4-2 (estimado, sem nome).
"""
import json
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
SAIDA = RAIZ / "web" / "data" / "brasil.json"
POSSE_SAIDA = RAIZ / "data" / "posse" / "brasil.json"  # segmentos de posse colados (auditoria; fora de web/)
sys.path.insert(0, str(SCRIPTS))
import posse  # noqa: E402  (biblioteca de colagem, mesmo diretorio)

FONTE = "Reconstrução aproximada a partir de relatos (sem dados de posição)"
GOLEIRO_COR = "#7fb800"      # genérica: camisa de goleiro não verificada
GOLEIRO_BORDA = "#111111"

FPS = 20
VEL_MAX_ROTEIRO = 9.3   # m/s: colagem; test_brasil.VEL_JOGADOR e 9,5 (margem para o arredondamento das chaves)
VEL_CHAVES = 9.4        # m/s: limite verificado nas chaves e na trajetoria amostrada (Catmull-Rom)
# Excecoes justificadas: intervalo (t_ini, t_fim) em que a bola nao esta no pe. Drible da vaca de Neymar:
# bola e jogador passam por lados opostos do marcador (test_brasil exige separacao de 2 m no cruzamento).
EXCECAO_SEM_POSSE = {"neymar-santos-flamengo-2011": [(2.6, 4.7)]}
MAX_CHAVES = 30         # test_brasil: jogador envolvido tem de 3 a 30 chaves (adaptativas)
TOL_COLA = 0.4          # m: erro maximo entre as chaves e a trajetoria colada
MARGEM_JANELA = 20      # quadros de folga em cada janela de reducao (candidatos a chave)
Z_POSSE = 0.6           # m: bola acima disso nao esta no pe, nao ha posse
JANELA_TOQUE = 0.1      # s antes e depois de cada toque


class Time:
    """linhas = (x_def, x_meio, x_ata) em metros, coordenadas reais do campo."""

    def __init__(self, nome, cor, borda, linhas, gk_x):
        self.nome, self.cor, self.borda = nome, cor, borda
        self.linhas, self.gk_x = linhas, gk_x


def jog(pid, time, nome, numero, chaves, estimado=False, gk=False):
    """Jogador nomeado ou com papel no lance. time = 'attack' ou 'defense'."""
    return {"pid": pid, "time": time, "nome": nome, "numero": numero,
            "chaves": [tuple(k) for k in chaves], "estimado": estimado, "gk": gk}


def _slots(time):
    """Formação 4-4-2 com goleiro: lista de (x, y, é_goleiro)."""
    xd, xm, xa = time.linhas
    s = [(time.gk_x, 0.0, True)]
    s += [(xd, y, False) for y in (-20.0, -7.0, 7.0, 20.0)]
    s += [(xm, y, False) for y in (-22.0, -7.5, 7.5, 22.0)]
    s += [(xa, y, False) for y in (-5.0, 5.0)]
    return s


def _barreira(bola_xy, alvo_xy, dist=9.15, n=5):
    """Posições de uma barreira a 9,15 m da bola, perpendicular à linha bola-gol."""
    bx, by = bola_xy
    gx, gy = alvo_xy
    dx, dy = gx - bx, gy - by
    norma = math.hypot(dx, dy)
    ux, uy = dx / norma, dy / norma
    cx, cy = bx + ux * dist, by + uy * dist
    px, py = -uy, ux
    return [(cx + px * (i - (n - 1) / 2) * 0.7, cy + py * (i - (n - 1) / 2) * 0.7) for i in range(n)]


def _cr(ks, t):
    """Trajetoria do jogador como em web/app.js: Catmull-Rom sobre chaves [t, x, y]; constante nas pontas."""
    if t <= ks[0][0]:
        return (ks[0][1], ks[0][2])
    if t >= ks[-1][0]:
        return (ks[-1][1], ks[-1][2])
    i = 0
    while i < len(ks) - 2 and t > ks[i + 1][0]:
        i += 1
    k1, k2 = ks[i], ks[i + 1]
    u = (t - k1[0]) / max(1e-6, k2[0] - k1[0])
    k0 = ks[i - 1] if i - 1 >= 0 else k1
    k3 = ks[i + 2] if i + 2 < len(ks) else k2
    out = []
    for d in (1, 2):
        p0, p1, p2, p3 = k0[d], k1[d], k2[d], k3[d]
        out.append(0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u))
    return tuple(out)


def _bola_em(bola, t):
    """Bola linear entre chaves [t, x, y, z]; devolve (x, y, z)."""
    if t <= bola[0][0]:
        return tuple(bola[0][1:])
    if t >= bola[-1][0]:
        return tuple(bola[-1][1:])
    for i in range(len(bola) - 1):
        t1, t2 = bola[i][0], bola[i + 1][0]
        if t1 <= t <= t2:
            u = (t - t1) / max(1e-6, t2 - t1)
            return tuple(bola[i][d] + (bola[i + 1][d] - bola[i][d]) * u for d in (1, 2, 3))
    raise ValueError("t fora da faixa da bola")


def _segmentos_toques(toques, zs, n):
    """Posse em quadros (id, ini, fim). Cada toque vale +-JANELA_TOQUE; toques seguidos do mesmo
    jogador formam uma conducao. Trechos com a bola no ar (z > Z_POSSE) nao sao posse."""
    grupos = []
    for t, pid in sorted(toques):
        if grupos and grupos[-1][0] == pid:
            grupos[-1][2] = t
        else:
            grupos.append([pid, t, t])
    segs = []
    for pid, t1, t2 in grupos:
        a = max(0, round((t1 - JANELA_TOQUE) * FPS))
        b = min(n - 1, round((t2 + JANELA_TOQUE) * FPS))
        f = a
        while f <= b:
            if zs[f] > Z_POSSE:
                f += 1
                continue
            g = f
            while g < b and zs[g + 1] <= Z_POSSE:
                g += 1
            segs.append((pid, f, g))
            f = g + 1
    return segs




def _chaves_coladas(chaves, colada, t_toques, bola, n):
    """Chaves novas [t, x, y] de um jogador cuja trajetoria colada e `colada` (um ponto por quadro a FPS).

    Os quadros alterados formam grupos (separados por mais de 1 s ficam em grupos distintos). Cada grupo
    e reduzido em sua janela; fora dela as chaves ficam como estao. Devolve (chaves, erro_max_m, chaves_nas_janelas)."""
    orig = [_cr(chaves, f / FPS) for f in range(n)]
    mud = [f for f in range(n) if math.dist(orig[f], colada[f]) > 1e-6]
    if not mud:
        return chaves, 0.0, 0
    grupos = []
    for f in mud:
        if grupos and f - grupos[-1][1] <= FPS:
            grupos[-1][1] = f
        else:
            grupos.append([f, f])
    ks, e_max, n_tot = list(chaves), 0.0, 0
    for fa_, fb_ in grupos:  # candidatos numa janela com folga; erro medido na zona alterada +-10 quadros
        ks, e_, nk = _reduzir_janela(ks, colada, t_toques, bola, n, max(0, fa_ - MARGEM_JANELA),
                                     min(n - 1, fb_ + MARGEM_JANELA), max(0, fa_ - 10), min(n - 1, fb_ + 10))
        e_max = max(e_max, e_)
        n_tot += nk
    return ks, e_max, n_tot


def _reduzir_janela(chaves, colada, t_toques, bola, n, fa, fb, ea, eb):
    """Reduz as chaves de uma janela [fa, fb] (quadros) para o erro maximo TOL_COLA medido em [ea, eb]."""
    ta, tb = round(fa / FPS, 2), round(fb / FPS, 2)
    fora = [tuple(k) for k in chaves if k[0] < ta - 1e-9 or k[0] > tb + 1e-9]
    cand = {ta, tb}
    cand |= {round(k[0], 2) for k in chaves if ta - 1e-9 <= k[0] <= tb + 1e-9}
    cand |= {round(t, 2) for t in t_toques if ta - 1e-9 <= t <= tb + 1e-9}
    def valor(t):
        x = t * FPS
        i = min(int(math.floor(x + 1e-9)), n - 1)
        if i >= n - 1:
            return tuple(colada[-1])
        s = x - i
        return (colada[i][0] * (1 - s) + colada[i + 1][0] * s, colada[i][1] * (1 - s) + colada[i + 1][1] * s)

    def montar_chaves(c):
        return sorted(fora + [(t,) + valor(t) for t in c], key=lambda k: k[0])

    def erro(c):
        ks = montar_chaves(c)
        for a_, b_ in zip(ks, ks[1:]):  # velocidade entre chaves (teste: <= VEL_CHAVES)
            if math.dist(a_[1:], b_[1:]) > VEL_CHAVES * (b_[0] - a_[0]) + 1e-9:
                return float("inf"), max(0, min(n - 1, int(round(b_[0] * FPS))))
        pior, quadro = 0.0, None
        ant = None
        for f in range(ea, eb + 1):
            p_ = _cr(ks, f / FPS)
            if ant is not None and math.dist(p_, ant) * FPS > VEL_CHAVES:  # velocidade amostrada
                return float("inf"), f
            ant = p_
            d = math.dist(p_, colada[f])
            if d > pior:
                pior, quadro = d, f
        return pior, quadro

    e, quadro = erro(cand)
    tentativas = 0
    while e > TOL_COLA and quadro is not None and tentativas < 200:
        tentativas += 1
        # insere um quadro perto do pior ponto (o proprio, ou vizinho, ou meio-caminho entre chaves)
        ordenadas = sorted(cand)
        cands_novos = []
        for dq in (0, -1, 1, -2, 2):
            tq = round((quadro + dq) / FPS, 2)
            if ta < tq < tb and tq not in cand:
                cands_novos.append(tq)
        if not cands_novos:
            prox = [t for t in ordenadas if t >= quadro / FPS]
            ante = [t for t in ordenadas if t <= quadro / FPS]
            if prox and ante and prox[0] - ante[-1] > 0.051:
                cands_novos.append(round((ante[-1] + prox[0]) / 2 / 0.05) * 0.05)
        if not cands_novos:  # ultimo recurso: quadros vizinhos ainda nao usados
            cands_novos = [round(q / FPS, 2) for q in range(quadro - 6, quadro + 7)
                           if fa <= q <= fb and round(q / FPS, 2) not in cand and ta < round(q / FPS, 2) < tb]
        if not cands_novos:
            break
        cand.add(round(cands_novos[0], 2))
        e, quadro = erro(cand)
    mudou = True
    while mudou:  # tira chaves ate nao haver mais remocao possivel (repete, pois uma remocao libera outras)
        mudou = False
        for t in sorted(cand):
            if t in (ta, tb):
                continue
            teste = cand - {t}
            if erro(teste)[0] <= TOL_COLA:
                cand = teste
                mudou = True
    e, _ = erro(cand)
    novas = montar_chaves(cand)
    return novas, e, len(cand)


def _colar_jogadores(dur, bola, nomes, toques, lance_id=""):
    """Aplica a colagem da posse aos jogadores nomeados (muda `chaves` in place).
    Devolve (segmentos colados em quadros, relatorio) para a auditoria."""
    n = round(dur * FPS) + 1
    bola_q = [list(_bola_em(bola, f / FPS)) for f in range(n)]
    zs = [b[2] for b in bola_q]
    segs = [s for s in _segmentos_toques(toques, zs, n)]
    for t1_, t2_ in EXCECAO_SEM_POSSE.get(lance_id, []):  # excecoes justificadas (ver EXCECAO_SEM_POSSE)
        e1, e2 = round((t1_ + 0.05) * FPS), round((t2_ - 0.05) * FPS)
        recortados = []
        for pid, a, b in segs:
            if b < e1 or a > e2:
                recortados.append((pid, a, b))
                continue
            if a < e1:
                recortados.append((pid, a, e1 - 1))
            if b > e2:
                recortados.append((pid, e2 + 1, b))
        segs = recortados
    donos = {s[0] for s in segs}
    nomes_por_id = {j["pid"]: j for j in nomes}
    if not donos:
        return [], {"runs": [], "quadros_colados": 0, "conflitos": 0, "vel_jogador": [], "vel_bola": [],
                    "chaves": {}}
    orig = {pid: [list(_cr(nomes_por_id[pid]["chaves"], f / FPS)) for f in range(n)] for pid in donos}
    novas, rel = posse.colar(FPS, bola_q, orig, segs, vmax=VEL_MAX_ROTEIRO)

    info = {}
    for pid in donos:
        t_pid = [t for t, p in toques if p == pid]
        ks, erro, n_ch = _chaves_coladas(nomes_por_id[pid]["chaves"], novas[pid], t_pid, bola, n)
        nomes_por_id[pid]["chaves"] = [tuple(k) for k in ks]
        info[pid] = {"erro_m": round(erro, 3), "chaves_janela": n_ch, "chaves_total": len(ks)}
    rel["chaves"] = info
    return rel["runs"], rel


def montar(ordem, lance_id, titulo, subtitulo, contexto, duracao, ataque, defesa,
           bola, nomeados, toques, t_chute, finalizador, goleiro):
    """Monta o dicionário do JSON e os metadados internos de um lance."""
    dur = float(duracao)
    bola = [tuple(b) for b in bola]
    deriva = max(-2.0, min(2.0, 0.1 * (bola[-1][1] - bola[0][1])))  # o elenco acompanha a bola de leve
    segmentos, rel_posse = _colar_jogadores(dur, bola, nomeados, toques, lance_id)
    jogadores = []
    for lado, time in (("attack", ataque), ("defense", defesa)):
        nomes = [j for j in nomeados if j["time"] == lado]
        if len(nomes) > 11:
            raise ValueError(f"{lance_id}: mais de 11 jogadores em {lado}")
        slots = _slots(time)
        for j in nomes:  # cada nomeado ocupa o slot de formação mais próximo do ponto de partida
            cand = [i for i, s in enumerate(slots) if s[2] == j["gk"]]
            p = j["chaves"][0][1:]
            i = min(cand, key=lambda k: math.dist(slots[k][:2], p))
            slots.pop(i)
        for j in nomes:
            jogadores.append({
                "id": j["pid"], "time": lado, "numero": j["numero"], "nome": j["nome"],
                "cor": GOLEIRO_COR if j["gk"] else time.cor,
                "borda": GOLEIRO_BORDA if j["gk"] else time.borda,
                "chaves": [[round(t, 2), round(x, 2), round(y, 2)] for t, x, y in j["chaves"]],
                "estimado": j["estimado"],
            })
        for k, (x, y, gk) in enumerate(slots, 1):
            jogadores.append({
                "id": f"{lado}-f{k}", "time": lado, "numero": None, "nome": None,
                "cor": GOLEIRO_COR if gk else time.cor,
                "borda": GOLEIRO_BORDA if gk else time.borda,
                "chaves": [[0.0, round(x, 2), round(y, 2)],
                           [round(dur / 2, 2), round(x + deriva / 2, 2), round(y, 2)],
                           [round(dur, 2), round(x + deriva, 2), round(y, 2)]],
                "estimado": True,
            })
    lance = {
        "id": lance_id, "titulo": titulo, "subtitulo": subtitulo, "grupo": "brasil",
        "ordem": ordem, "contexto": contexto, "fonte": FONTE,
        "roteiro": True, "aproximado": True, "duracao": dur,
        "times": {"attack": ataque.nome, "defense": defesa.nome},
        "finalizadorId": finalizador,
        "chavesBola": [[round(t, 2), round(x, 2), round(y, 2), round(z, 2)] for t, x, y, z in bola],
        "jogadores": jogadores,
    }
    meta = {"toques": [(round(t, 2), pid) for t, pid in toques], "t_chute": round(t_chute, 2),
            "goleiro": goleiro, "finalizador": finalizador, "posse": segmentos, "posse_rel": rel_posse}
    return lance, meta


# ---------------------------------------------------------------- os 13 gols

def gol_01_neymar():
    santos = Time("Santos", "#f5f5f5", "#111111", (-8.0, 8.0, 20.0), -50.0)
    flamengo = Time("Flamengo", "#c8102e", "#111111", (36.0, 24.0, 10.0), 50.0)
    nomes = [
        jog("neymar", "attack", "Neymar", 11, [(0.0, 21.0, 21.0), (1.4, 27.0, 19.0), (2.2, 31.5, 17.0),
                                             (3.0, 35.9, 12.1), (3.6, 38.0, 10.2), (4.2, 41.0, 11.0),
                                             (4.8, 43.5, 13.2), (5.5, 44.6, 9.6), (6.3, 45.8, 6.4), (8.0, 49.5, 2.5)]),
        jog("borges", "attack", "Borges", None, [(0.0, 24.0, 14.5), (0.7, 25.0, 16.0), (1.6, 25.5, 17.5)]),
        jog("angelim", "defense", "Ronaldo Angelim", None, [(0.0, 37.0, 10.0), (2.6, 37.6, 12.0),
                                                           (3.6, 38.0, 12.4), (5.0, 40.0, 9.5)]),
        jog("marcador-a", "defense", None, None, [(0.0, 28.5, 20.5), (1.4, 29.8, 18.8), (2.6, 31.0, 18.5)]),
        jog("marcador-b", "defense", None, None, [(0.0, 33.5, 16.0), (2.2, 33.0, 16.0), (4.0, 34.5, 14.0)]),
        jog("felipe", "defense", "Felipe", None, [(0.0, 50.5, 0.0), (4.5, 49.5, 2.0), (6.0, 48.2, 5.2),
                                                 (7.2, 50.0, 3.5)], gk=True),
    ]
    # Drible da vaca: a bola passa pelo lado de dentro de Angelim (y > 12,4) e Neymar pelo de fora (y < 12,4).
    bola = [(0.0, 21.5, 20.5, 0.11), (0.7, 25.0, 16.0, 0.11), (1.4, 27.0, 19.0, 0.11),
            (2.2, 31.5, 17.0, 0.11), (3.0, 36.4, 13.0, 0.11), (3.5, 38.6, 14.8, 0.11),
            (4.2, 41.4, 14.6, 0.11), (4.8, 43.4, 14.2, 0.11), (5.5, 44.9, 9.9, 0.11),
            (6.3, 45.8, 6.4, 0.11), (6.9, 52.6, -1.6, 0.11), (7.7, 53.5, -1.8, 0.0)]
    toques = [(0.0, "neymar"), (0.7, "borges"), (1.4, "neymar"), (2.2, "neymar"),
              (3.0, "neymar"), (4.8, "neymar"), (5.5, "neymar"), (6.3, "neymar")]
    return montar(1, "neymar-santos-flamengo-2011", "Neymar — o gol do Puskás",
                  "Santos 4 × 5 Flamengo · Brasileirão 2011 · 27/07/2011",
                  "Vila Belmiro, 25'. O placar vai de 2 × 0 para 3 × 0. Prêmio Puskás 2011.",
                  8.5, santos, flamengo, bola, nomes, toques, 6.3, "neymar", "felipe")


def gol_02_arrascaeta_final_2018():
    cruzeiro = Time("Cruzeiro", "#1f4fa3", "#f5f5f5", (-12.0, 6.0, 24.0), -50.0)
    corinthians = Time("Corinthians", "#f5f5f5", "#111111", (36.0, 26.0, 14.0), 50.0)
    nomes = [
        jog("raniel", "attack", "Raniel", None, [(0.0, 3.0, 6.0), (2.6, 12.0, 4.5), (4.5, 17.0, 4.0)]),
        jog("arrascaeta", "attack", "Arrascaeta", None, [(0.0, 18.0, 4.0), (2.6, 27.0, 2.5), (3.6, 33.0, 2.8),
                                                       (4.4, 38.8, 2.2), (5.2, 44.5, 1.6), (6.5, 45.2, 0.6)]),
        jog("cassio", "defense", "Cássio", None, [(0.0, 49.5, 0.0), (4.5, 48.5, 0.2), (5.2, 47.2, 0.2),
                                                 (6.0, 48.8, 1.6)], gk=True),
    ]
    bola = [(0.0, 3.6, 6.0, 0.11), (2.6, 12.0, 4.5, 0.11), (3.6, 33.0, 2.8, 0.11), (5.2, 44.5, 1.6, 0.11),
            (5.6, 47.5, 0.8, 2.5), (6.1, 52.6, -0.2, 1.7), (6.5, 53.5, -0.3, 0.0)]
    toques = [(2.6, "raniel"), (3.6, "arrascaeta"), (5.2, "arrascaeta")]
    return montar(2, "arrascaeta-corinthians-cruzeiro-2018", "Arrascaeta — o gol da final da Copa do Brasil",
                  "Corinthians 1 × 2 Cruzeiro · Copa do Brasil 2018 (volta) · 17/10/2018",
                  "Arena Corinthians, 82'. O placar vai de 1 × 1 para 1 × 2. Cruzeiro campeão.",
                  7.5, cruzeiro, corinthians, bola, nomes, toques, 5.2, "arrascaeta", "cassio")


def gol_03_everton_2013():
    cruzeiro = Time("Cruzeiro", "#1f4fa3", "#f5f5f5", (-8.0, 12.0, 26.0), -50.0)
    flamengo = Time("Flamengo", "#c8102e", "#111111", (38.0, 26.0, 14.0), 50.0)
    nomes = [
        jog("everton", "attack", "Éverton Ribeiro", None, [(0.0, 30.0, -21.0), (1.2, 33.0, -20.5), (2.0, 35.0, -16.5),
                                                          (3.0, 37.2, -12.8), (3.45, 39.4, -13.6), (4.0, 41.4, -9.8),
                                                          (5.0, 44.5, -6.5)]),
        jog("parceiro", "attack", None, None, [(0.0, 31.0, -15.0), (1.6, 34.0, -18.0), (2.4, 36.0, -19.5)]),
        jog("zagueiro", "defense", None, None, [(0.0, 38.6, -11.6), (3.0, 39.0, -11.2), (4.2, 39.3, -10.9)]),
        jog("goleiro", "defense", None, None, [(0.0, 49.5, 0.0), (3.5, 49.0, -0.8), (4.0, 49.8, -1.0),
                                              (4.6, 50.6, -2.2)], gk=True),
    ]
    # Chapéu: a bola passa por cima do zagueiro (pico em ~(39,2; -11,0), z = 2,6) e Éverton contorna por fora.
    bola = [(0.0, 29.5, -21.5, 0.11), (1.2, 33.0, -20.5, 0.11), (1.6, 34.0, -18.0, 0.11),
            (2.0, 35.0, -16.5, 0.11), (3.0, 37.2, -12.8, 0.11), (3.45, 39.2, -11.0, 2.6),
            (4.0, 41.4, -9.3, 0.95), (4.5, 52.6, -2.8, 2.1), (5.2, 53.6, -2.9, 0.0)]
    toques = [(1.2, "everton"), (1.6, "parceiro"), (2.0, "everton"), (3.0, "everton"), (4.0, "everton")]
    return montar(3, "everton-ribeiro-cruzeiro-flamengo-2013", "Éverton Ribeiro — chapéu e voleio",
                  "Cruzeiro 2 × 1 Flamengo · Copa do Brasil 2013 (oitavas, ida) · 21/08/2013",
                  "Mineirão, segundo tempo. Oitavas de final, jogo de ida. Chapéu num defensor e voleio no ângulo.",
                  6.5, cruzeiro, flamengo, bola, nomes, toques, 4.0, "everton", "goleiro")


def gol_04_fred_2012():
    fluminense = Time("Fluminense", "#f5f5f5", "#0a6b3c", (-4.0, 16.0, 32.0), -50.0)
    flamengo = Time("Flamengo", "#c8102e", "#111111", (34.0, 24.0, 12.0), 50.0)
    nomes = [
        jog("deco", "attack", "Deco", None, [(0.0, 25.5, -22.0), (0.8, 28.0, -24.0), (1.6, 31.0, -22.5)]),
        jog("fred", "attack", "Fred", 9, [(0.0, 40.5, -1.0), (1.4, 42.0, -3.5), (2.2, 43.4, -4.8),
                                         (2.6, 43.6, -5.0), (3.6, 45.0, -3.2)]),
        jog("goleiro", "defense", None, None, [(0.0, 50.0, 0.5), (1.8, 50.0, 0.6), (2.6, 49.8, 1.0),
                                              (3.4, 50.8, -0.6)], gk=True),
    ]
    bola = [(0.0, 25.0, -22.5, 0.11), (0.8, 28.0, -24.0, 0.11), (1.8, 38.0, -14.0, 4.0),
            (2.6, 43.8, -5.2, 1.3), (2.95, 52.6, -1.0, 1.2), (3.8, 53.5, -1.1, 0.0)]
    toques = [(0.8, "deco"), (2.6, "fred")]
    return montar(4, "fred-fluminense-flamengo-2012", "Fred — o voleio do Engenhão",
                  "Fluminense 1 × 0 Flamengo · Brasileirão 2012 · 30/09/2012",
                  "Engenhão, 18'. Voleio após cruzamento de Deco. Eleito o mais bonito na enquete do GE de 2020.",
                  6.0, fluminense, flamengo, bola, nomes, toques, 2.6, "fred", "goleiro")


def gol_05_arrascaeta_ceara_2019():
    flamengo = Time("Flamengo", "#c8102e", "#111111", (-6.0, 12.0, 26.0), -50.0)
    ceara = Time("Ceará", "#f5f5f5", "#111111", (36.0, 26.0, 14.0), 50.0)
    nomes = [
        jog("rafinha", "attack", "Rafinha", None, [(0.0, 30.0, 22.0), (0.6, 31.0, 22.5), (2.0, 33.5, 23.0)]),
        jog("arrascaeta", "attack", "Arrascaeta", None, [(0.0, 34.0, 6.0), (1.0, 37.5, 4.0), (1.7, 40.2, 2.0),
                                                       (2.5, 42.5, 1.0), (3.4, 44.0, 0.5)]),
        jog("goleiro", "defense", None, None, [(0.0, 50.5, 0.0), (1.2, 50.0, 0.0), (1.7, 50.0, 0.3),
                                              (2.5, 51.0, -1.5), (3.4, 51.3, -1.8)], gk=True),
    ]
    bola = [(0.0, 30.0, 22.0, 0.11), (0.9, 36.0, 14.0, 4.0), (1.7, 40.2, 2.0, 2.2), (2.1, 47.0, 0.8, 1.9),
            (2.4, 52.6, 0.4, 1.6), (3.2, 53.5, 0.3, 0.0)]
    toques = [(0.0, "rafinha"), (1.7, "arrascaeta")]
    return montar(5, "arrascaeta-ceara-flamengo-2019", "Arrascaeta — a bicicleta do Castelão",
                  "Ceará 0 × 3 Flamengo · Brasileirão 2019 · 25/08/2019",
                  "Castelão, 51' do 2º tempo. Bicicleta após cruzamento de Rafinha. 2º na enquete do GE.",
                  6.0, flamengo, ceara, bola, nomes, toques, 1.7, "arrascaeta", "goleiro")


def gol_06_dinamite_1976():
    vasco = Time("Vasco", "#f5f5f5", "#111111", (-6.0, 12.0, 28.0), -50.0)
    botafogo = Time("Botafogo", "#1a1a1a", "#f5f5f5", (38.0, 28.0, 16.0), 50.0)
    nomes = [
        jog("zanata", "attack", "Zanata", None, [(0.0, 27.5, -24.0), (0.5, 28.2, -25.0), (1.8, 31.0, -22.0)]),
        jog("dinamite", "attack", "Roberto Dinamite", None, [(0.0, 37.0, -10.0), (1.8, 39.5, -8.0), (2.3, 41.0, -7.0),
                                                            (2.8, 42.2, -6.0), (3.4, 45.2, -3.8)]),
        jog("osmar", "defense", "Osmar", None, [(0.0, 42.0, -6.0), (2.0, 43.2, -6.8), (3.4, 43.6, -6.6)]),
        jog("wendell", "defense", "Wendell", None, [(0.0, 50.5, 0.0), (2.6, 50.5, 0.0), (3.4, 51.0, 1.4),
                                                   (4.0, 51.2, 1.8)], gk=True),
    ]
    bola = [(0.0, 27.5, -24.0, 0.11), (0.5, 28.2, -25.0, 0.11), (1.4, 36.0, -16.0, 3.2), (2.3, 41.0, -7.5, 1.4),
            (2.8, 42.4, -5.9, 1.9), (3.0, 43.6, -5.0, 2.0), (3.4, 45.4, -3.6, 1.0), (3.8, 52.6, -1.2, 0.5),
            (4.6, 53.5, -1.3, 0.0)]
    toques = [(0.5, "zanata"), (2.3, "dinamite"), (2.8, "dinamite"), (3.4, "dinamite")]
    return montar(6, "roberto-dinamite-vasco-botafogo-1976", "Roberto Dinamite — o gol do lençol",
                  "Vasco 2 × 1 Botafogo · Carioca 1976 · 09/05/1976",
                  "Maracanã, 1976. Lençol no zagueiro Osmar e finalização de primeira, antes de a bola tocar o chão.",
                  6.0, vasco, botafogo, bola, nomes, toques, 3.4, "dinamite", "wendell")


def gol_07_alex_2002():
    palmeiras = Time("Palmeiras", "#00703c", "#f5f5f5", (-4.0, 14.0, 30.0), -50.0)
    sao_paulo = Time("São Paulo", "#f5f5f5", "#c8102e", (38.0, 28.0, 16.0), 50.0)
    nomes = [
        jog("christian", "attack", "Christian", None, [(0.0, -5.0, 5.5), (0.4, -4.0, 6.0), (1.2, -1.0, 6.5),
                                                      (2.5, 3.0, 7.0)]),
        jog("alex", "attack", "Alex", None, [(0.0, 30.0, 3.5), (1.0, 33.5, 2.8), (2.0, 36.8, 2.0),
                                            (2.6, 38.6, 1.2), (3.2, 41.4, 0.4)]),
        jog("emerson", "defense", "Émerson", None, [(0.0, 39.5, 3.0), (2.0, 39.4, 2.6), (3.2, 40.3, 1.9)]),
        jog("ceni", "defense", "Rogério Ceni", 1, [(0.0, 49.5, 0.0), (2.0, 48.0, 0.2), (2.8, 46.6, 0.4),
                                                  (3.2, 45.2, 0.5), (3.8, 46.5, 1.0)], gk=True),
    ]
    bola = [(0.0, -5.0, 5.5, 0.11), (0.4, -4.0, 6.0, 0.11), (1.2, 18.0, 3.5, 1.2), (2.0, 36.8, 2.0, 0.11),
            (2.6, 38.8, 1.3, 0.11), (3.2, 41.6, 0.4, 0.11), (3.7, 46.5, 0.2, 2.4), (4.2, 52.6, 0.0, 1.5),
            (4.8, 53.5, -0.1, 0.0)]
    toques = [(0.4, "christian"), (2.0, "alex"), (2.6, "alex"), (3.2, "alex")]
    return montar(7, "alex-sao-paulo-palmeiras-2002", "Alex — o gol por cima de Rogério Ceni",
                  "São Paulo 2 × 4 Palmeiras · Torneio Rio-São Paulo 2002 · 20/03/2002",
                  "Morumbi. Lançamento de Christian, toque sutil em Émerson e encobrida no goleiro Rogério Ceni, na saída.",
                  6.0, palmeiras, sao_paulo, bola, nomes, toques, 3.2, "alex", "ceni")


def gol_08_ceni_2011():
    sao_paulo = Time("São Paulo", "#f5f5f5", "#c8102e", (-4.0, 16.0, 30.0), -50.0)
    corinthians = Time("Corinthians", "#111111", "#f5f5f5", (40.0, 31.0, 18.0), 50.0)
    t0 = 2.5
    curva = []  # falta curva: x linear, y com curl tardio, z em arco de 2,6 m na barreira
    for s in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        x = 35.5 + 17.1 * s
        y = 8.5 - 11.0 * s ** 1.8
        z = 0.11 + 1.8 * s + 6.4 * s * (1 - s)
        curva.append((round(t0 + 0.9 * s, 2), round(x, 2), round(y, 2), round(z, 2)))
    bola = [(0.0, 35.5, 8.5, 0.11)] + curva + [(3.8, 53.5, -2.7, 0.0)]
    barreira = _barreira((35.5, 8.5), (52.5, 0.0))
    nomes = [
        jog("ceni", "attack", "Rogério Ceni", 1, [(0.0, 31.5, 10.5), (1.6, 33.6, 9.6), (2.5, 34.9, 8.8),
                                                 (3.5, 36.0, 8.0)]),
        jog("julio-cesar", "defense", "Júlio César", None, [(0.0, 50.5, 0.0), (2.5, 50.4, -0.5),
                                                           (3.2, 51.0, -1.6), (3.9, 50.8, -1.9)], gk=True),
    ]
    for i, (x, y) in enumerate(barreira):
        nomes.append(jog(f"muro-{i + 1}", "defense", None, None,
                         [(0.5, x - 2.0, y), (2.5, x, y), (3.5, x + 0.1, y)], estimado=True))
    toques = [(2.5, "ceni")]
    return montar(8, "rogerio-ceni-sao-paulo-corinthians-2011", "Rogério Ceni — o 100º gol",
                  "São Paulo 2 × 1 Corinthians · Paulistão 2011 · 27/03/2011",
                  "Arena Barueri, 8' do 2º tempo. O 100º gol de Rogério Ceni: falta no ângulo de Júlio César.",
                  6.0, sao_paulo, corinthians, bola, nomes, toques, t0, "ceni", "julio-cesar")


def gol_09_ronaldinho_2012():
    atletico = Time("Atlético-MG", "#f5f5f5", "#111111", (-20.0, -2.0, 8.0), -50.0)
    cruzeiro = Time("Cruzeiro", "#1f4fa3", "#f5f5f5", (34.0, 24.0, 12.0), 50.0)
    nomes = [
        jog("passador", "attack", None, None, [(0.0, -5.5, 4.0), (0.2, -5.0, 3.6), (1.5, -3.0, 3.0)]),
        jog("ronaldinho", "attack", "Ronaldinho", None, [(1.0, 0.0, 0.5), (2.15, 6.5, 3.0), (3.3, 13.0, -2.5),
                                                        (4.83, 20.0, 2.5), (6.33, 27.0, -1.0), (7.82, 34.0, 2.0),
                                                        (9.43, 42.0, -1.5), (10.35, 47.0, 0.5), (10.81, 48.6, 0.4)]),
        jog("defensor-1", "defense", None, None, [(0.0, 7.5, 0.0), (2.15, 7.8, 0.5), (3.3, 8.4, -0.3)]),
        jog("defensor-2", "defense", None, None, [(0.0, 12.0, 0.2), (3.3, 12.0, 0.0), (5.2, 12.5, -0.5)]),
        jog("defensor-3", "defense", None, None, [(0.0, 18.5, -1.2), (4.83, 18.5, -1.0), (6.33, 19.0, -0.6)]),
        jog("goleiro", "defense", None, None, [(0.0, 50.0, 0.0), (8.1, 49.8, 0.0), (10.81, 50.0, -1.2),
                                              (11.5, 51.2, -1.8)], gk=True),
    ]
    bola = [(0.2, -5.0, 3.6, 0.11), (1.0, 0.0, 0.5, 0.11), (2.15, 7.2, 3.0, 0.11), (3.3, 13.7, -2.5, 0.11),
            (4.83, 20.7, 2.5, 0.11), (6.33, 27.7, -1.0, 0.11), (7.82, 34.7, 2.0, 0.11), (9.43, 42.7, -1.5, 0.11),
            (10.35, 47.7, 0.5, 0.11), (10.81, 48.9, 0.4, 0.11), (11.1, 52.6, 1.5, 0.3), (11.9, 53.5, 1.6, 0.0)]
    toques = [(0.2, "passador"), (1.0, "ronaldinho"), (2.15, "ronaldinho"), (3.3, "ronaldinho"),
              (4.83, "ronaldinho"), (6.33, "ronaldinho"), (7.82, "ronaldinho"), (9.43, "ronaldinho"),
              (10.35, "ronaldinho"), (10.81, "ronaldinho")]
    return montar(9, "ronaldinho-atletico-mg-cruzeiro-2012", "Ronaldinho — o slalom de 50 metros",
                  "Atlético-MG 2 × 2 Cruzeiro · Brasileirão 2012 · 26/08/2012",
                  "Círculo central, 89'. Slalom de cerca de 50 m driblando três. Relato de fonte única: a parte menos confiável da lista.",
                  12.5, atletico, cruzeiro, bola, nomes, toques, 10.81, "ronaldinho", "goleiro")


def gol_10_wendell_lira_2015():
    goianesia = Time("Goianésia", "#1f7a3a", "#f5f5f5", (-6.0, 14.0, 30.0), -50.0)
    atletico_go = Time("Atlético-GO", "#d7261e", "#111111", (40.0, 30.0, 18.0), 50.0)
    nomes = [
        jog("da-matta", "attack", "Da Matta", None, [(0.0, 32.0, 21.5), (0.6, 33.0, 21.0), (2.0, 35.0, 19.0)]),
        jog("wendell-lira", "attack", "Wendell Lira", None, [(0.0, 39.5, 0.0), (1.0, 40.8, 0.6), (1.6, 41.6, 1.1),
                                                            (2.0, 42.0, 1.4), (2.6, 43.5, 1.2)]),
        jog("marcio", "defense", "Márcio", None, [(0.0, 50.0, 0.0), (1.5, 49.8, 0.0), (2.0, 49.8, 0.9),
                                                 (2.6, 50.4, 1.8)], gk=True),
    ]
    bola = [(0.0, 32.0, 21.5, 0.11), (1.1, 37.5, 12.0, 4.0), (2.0, 42.0, 1.4, 2.2), (2.3, 47.0, -0.6, 2.1),
            (2.6, 52.6, -2.9, 2.0), (3.4, 53.5, -3.0, 0.0)]
    toques = [(0.0, "da-matta"), (2.0, "wendell-lira")]
    return montar(10, "wendell-lira-goianesia-atletico-go-2015", "Wendell Lira — a meia-bicicleta",
                  "Goianésia 2 × 1 Atlético-GO · Goiano 2015 · 11/03/2015",
                  "Serra Dourada. Bola alta de Da Matta e meia-bicicleta no canto do goleiro Márcio. Prêmio Puskás 2015.",
                  6.0, goianesia, atletico_go, bola, nomes, toques, 2.0, "wendell-lira", "marcio")


def gol_11_madruga_2023():
    botafogo_sp = Time("Botafogo-SP", "#111111", "#f5f5f5", (-8.0, 12.0, 26.0), -50.0)
    novorizontino = Time("Novorizontino", "#f2c200", "#111111", (36.0, 24.0, 12.0), 50.0)
    nomes = [
        jog("lateral", "attack", None, None, [(0.0, 29.5, 34.2), (0.8, 30.0, 33.6), (1.8, 31.0, 32.5)]),
        jog("madruga", "attack", "Guilherme Madruga", None, [(0.0, 30.0, 1.0), (1.8, 31.8, 2.0), (2.4, 32.6, 2.4),
                                                            (3.0, 32.8, 2.6), (3.8, 33.5, 3.0)]),
        jog("zagueiro", "defense", None, None, [(0.0, 38.0, 8.0), (1.8, 37.2, 9.4), (2.4, 36.0, 7.0)]),
        jog("marcador-1", "defense", None, None, [(0.0, 33.0, 5.0), (2.6, 33.5, 4.2), (3.6, 34.5, 3.5)],
            estimado=True),
        jog("marcador-2", "defense", None, None, [(0.0, 33.0, -0.5), (2.6, 33.4, 0.2), (3.6, 34.4, 0.6)],
            estimado=True),
        jog("jordi", "defense", "Jordi", None, [(0.0, 50.5, 0.0), (2.8, 50.2, 0.2), (3.4, 50.4, 1.0),
                                               (4.0, 50.9, 1.8)], gk=True),
    ]
    bola = [(0.0, 30.0, 33.8, 0.11), (0.9, 34.0, 19.0, 2.4), (1.8, 37.0, 9.6, 2.0), (2.4, 33.0, 3.1, 0.11),
            (3.0, 32.6, 2.6, 1.8), (3.5, 42.0, -0.8, 3.2), (3.9, 52.6, -2.7, 1.9), (4.4, 53.5, -2.9, 0.0)]
    toques = [(0.0, "lateral"), (1.8, "zagueiro"), (2.4, "madruga"), (3.0, "madruga")]
    return montar(11, "guilherme-madruga-botafogo-sp-novorizontino-2023", "Guilherme Madruga — a bicicleta de fora da área",
                  "Botafogo-SP 1 × 0 Novorizontino · Série B 2023 · 27/06/2023",
                  "Novo Horizonte, 36'. Lateral para a área, a defesa afasta mal; bicicleta de fora da área no canto do goleiro Jordi. Prêmio Puskás 2023.",
                  6.0, botafogo_sp, novorizontino, bola, nomes, toques, 3.0, "madruga", "jordi")


def gol_12_alerrandro_2024():
    vitoria = Time("Vitória", "#c8102e", "#111111", (-8.0, 8.0, 26.0), -50.0)
    cruzeiro = Time("Cruzeiro", "#1f4fa3", "#f5f5f5", (32.0, 22.0, 12.0), 50.0)
    nomes = [
        jog("passador", "attack", None, None, [(0.0, 8.0, -6.5), (0.2, 9.0, -6.0), (1.5, 12.0, -5.0)]),
        jog("joao-marcelo", "defense", "João Marcelo", None, [(0.0, 21.0, -4.5), (1.2, 23.6, -3.0),
                                                             (2.2, 26.0, -2.5), (3.2, 31.0, -1.8)]),
        jog("alerrandro", "attack", "Alerrandro", None, [(0.0, 35.0, -3.5), (1.8, 38.0, -2.2), (2.7, 40.0, -1.4),
                                                        (3.0, 40.6, -1.2), (3.8, 42.5, -0.6)]),
        jog("cassio", "defense", "Cássio", None, [(0.0, 49.5, 0.0), (2.5, 49.2, 0.0), (3.0, 48.2, 0.4),
                                                 (3.6, 48.4, 1.6), (4.2, 49.0, 2.0)], gk=True),
    ]
    bola = [(0.0, 8.5, -6.2, 0.11), (0.2, 9.0, -6.0, 0.11), (1.2, 23.8, -3.0, 0.9), (1.7, 27.0, -2.4, 3.0),
            (2.5, 34.5, -1.5, 2.0), (3.0, 41.0, -1.0, 1.7), (3.5, 47.0, -1.6, 2.5), (3.9, 52.6, -2.0, 2.1),
            (4.5, 53.5, -2.1, 0.0)]
    toques = [(0.2, "passador"), (1.2, "joao-marcelo"), (3.0, "alerrandro")]
    return montar(12, "alerrandro-vitoria-cruzeiro-2024", "Alerrandro — a bicicleta de primeira",
                  "Vitória 2 × 2 Cruzeiro · Brasileirão 2024 · 19/08/2024",
                  "Barradão, 28'. Bola cortada para o alto por João Marcelo; bicicleta de primeira por cima de Cássio. Finalista do Puskás 2024.",
                  6.0, vitoria, cruzeiro, bola, nomes, toques, 3.0, "alerrandro", "cassio")


def gol_13_pedro_2025():
    flamengo = Time("Flamengo", "#c8102e", "#111111", (-6.0, 14.0, 28.0), -50.0)
    vitoria = Time("Vitória", "#f5f5f5", "#111111", (40.0, 28.0, 16.0), 50.0)
    nomes = [
        jog("samuel-lino", "attack", "Samuel Lino", None, [(0.0, 26.5, 25.5), (0.8, 28.0, 24.0), (1.6, 30.0, 21.0)]),
        jog("pedro", "attack", "Pedro", 9, [(0.0, 33.5, 10.0), (0.9, 35.8, 6.6), (1.3, 37.0, 4.0),
                                           (1.9, 39.5, 1.6), (2.5, 42.2, 0.8)]),
        jog("halter", "defense", "Lucas Halter", None, [(0.0, 38.5, 6.5), (1.3, 38.4, 4.8), (2.4, 39.6, 3.8)]),
        jog("marcador-a", "defense", None, None, [(0.0, 38.0, 9.0), (1.8, 38.2, 8.8), (3.0, 39.0, 8.0)]),
        jog("marcador-b", "defense", None, None, [(0.0, 40.0, 6.0), (1.8, 40.3, 5.6), (3.0, 40.8, 5.0)]),
        jog("marcador-c", "defense", None, None, [(0.0, 41.0, -2.0), (1.8, 41.2, -2.2), (3.0, 41.8, -2.4)]),
        jog("marcador-d", "defense", None, None, [(0.0, 44.0, 2.5), (1.8, 44.2, 2.4), (3.0, 44.8, 2.0)]),
        jog("arcanjo", "defense", "Lucas Arcanjo", None, [(0.0, 50.0, 0.0), (1.5, 48.6, 0.2), (2.5, 46.0, 0.4),
                                                        (3.0, 45.6, 0.6), (3.8, 46.2, 0.9)], gk=True),
    ]
    bola = [(0.0, 27.0, 25.0, 0.11), (0.45, 32.0, 14.5, 0.11), (0.9, 36.0, 6.5, 0.11), (1.3, 37.6, 3.4, 0.11),
            (1.9, 40.2, 1.4, 0.11), (2.5, 42.4, 0.6, 0.11), (3.0, 46.5, 0.4, 2.3), (3.5, 52.6, 0.0, 1.5),
            (4.1, 53.5, -0.1, 0.0)]
    toques = [(0.0, "samuel-lino"), (0.9, "pedro"), (1.3, "pedro"), (2.5, "pedro")]
    return montar(13, "pedro-flamengo-vitoria-2025", "Pedro — o elástico e a encobrida",
                  "Flamengo 8 × 0 Vitória · Brasileirão 2025 · 25/08/2025",
                  "Maracanã. Trivela de Samuel Lino, elástico em Lucas Halter e encobrida no goleiro Lucas Arcanjo, que saía. Pedro deixa quatro marcadores para trás.",
                  6.0, flamengo, vitoria, bola, nomes, toques, 2.5, "pedro", "arcanjo")


def gerar():
    """Lista de (dicionário do JSON, metadados internos), em ordem."""
    return [f() for f in (gol_01_neymar, gol_02_arrascaeta_final_2018, gol_03_everton_2013,
                          gol_04_fred_2012, gol_05_arrascaeta_ceara_2019, gol_06_dinamite_1976,
                          gol_07_alex_2002, gol_08_ceni_2011, gol_09_ronaldinho_2012,
                          gol_10_wendell_lira_2015, gol_11_madruga_2023, gol_12_alerrandro_2024,
                          gol_13_pedro_2025)]


def main():
    gerados = gerar()
    lances = [d for d, _ in gerados]
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump({"lances": lances}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    POSSE_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    posse_lances = {d["id"]: [list(s) for s in m["posse_rel"]["runs"]] for d, m in gerados}
    with open(POSSE_SAIDA, "w", encoding="utf-8") as f:
        json.dump({"fps": FPS, "lances": posse_lances}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    for d, m in gerados:
        rel = m["posse_rel"]
        for pid, info in rel["chaves"].items():
            print(f"{d['ordem']:>2} {d['id']} {pid}: erro {info['erro_m']:.3f} m, chaves {info['chaves_total']}")
        if rel["vel_jogador"] or rel["conflitos"]:
            print(f"   aviso posse: vel_jogador={len(rel['vel_jogador'])} conflitos={rel['conflitos']}")
    print(f"{len(lances)} lances -> {SAIDA}")
    print(f"posse -> {POSSE_SAIDA}")


if __name__ == "__main__":
    main()
