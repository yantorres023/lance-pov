#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testa web/data/brasil.json (13 roteiros de gol) contra as regras de plausibilidade.

Uso: python3 -I scripts/test_brasil.py

Interpolação igual à do visualizador (web/app.js, expandirChaves):
  bola: linear entre chaves; jogadores: Catmull-Rom com u normalizado pelo tempo
  do segmento; constante antes da primeira e depois da última chave.
Amostragem a 20 fps: t = f / 20, f = 0 .. round(duracao * 20).

Os toques (quem toca a bola e quando) não estão no JSON: vêm dos metadados que
scripts/roteiros_brasil.py devolve em gerar(). O teste confere que o JSON
gravado é exatamente o que o gerador produz.

Distância de toque e de chute é horizontal (plano do campo): jogador é um ponto
no chão. Altura da bola no toque é conferida à parte (<= 2,5 m).
Só biblioteca padrão.
"""
import json
import math
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import roteiros_brasil as R  # noqa: E402  (gerador, mesmo diretório)

SAIDA = RAIZ / "web" / "data" / "brasil.json"
FPS = 20
VEL_JOGADOR = 9.5
VEL_BOLA = 38.0
TOQUE_M = 1.2
ALTURA_TOQUE_M = 2.5
GOL_X = 52.5
TRAVE_Y = 3.66
TRAVESSAO_Z = 2.44

CAMPOS_LANCE = {"id", "titulo", "subtitulo", "grupo", "ordem", "contexto", "fonte", "roteiro",
                "aproximado", "duracao", "times", "finalizadorId", "chavesBola", "jogadores"}
CAMPOS_JOG = {"id", "time", "numero", "nome", "cor", "borda", "chaves", "estimado"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

erros = []
verificacoes = 0


def checar(cond, msg):
    global verificacoes
    verificacoes += 1
    if not cond:
        erros.append(msg)


# ---------------------------------------------------------- interpolação (= app.js)

def bola_em(chaves, t):
    ks = sorted(chaves, key=lambda k: k[0])
    if t <= ks[0][0]:
        return tuple(ks[0][1:])
    if t >= ks[-1][0]:
        return tuple(ks[-1][1:])
    for i in range(len(ks) - 1):
        t1, t2 = ks[i][0], ks[i + 1][0]
        if t1 <= t <= t2:
            u = (t - t1) / max(1e-6, t2 - t1)
            return tuple(ks[i][d] + (ks[i + 1][d] - ks[i][d]) * u for d in range(1, len(ks[i])))
    raise AssertionError("t fora da faixa")


def jogador_em(chaves, t):
    ks = sorted(chaves, key=lambda k: k[0])
    if t <= ks[0][0]:
        return tuple(ks[0][1:])
    if t >= ks[-1][0]:
        return tuple(ks[-1][1:])
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


def amostras(dur):
    n = round(dur * FPS) + 1
    return [f / FPS for f in range(n)]


def cor_rgb(hexa):
    return tuple(int(hexa[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------- testes por lance

def testar_lance(l, meta):
    lid = l.get("id", "?")
    stats = {"id": lid, "ordem": l.get("ordem"), "dur": l.get("duracao"), "jog": 0, "bola": 0,
               "chaves_jog": 0, "vmax_jog": 0.0, "vmax_bola": 0.0, "toques": 0}

    def f(cond, msg):
        checar(cond, f"[{lid}] {msg}")

    # --- formato
    f(set(l.keys()) == CAMPOS_LANCE, f"campos do lance diferentes: {sorted(set(l.keys()) ^ CAMPOS_LANCE)}")
    f(l.get("grupo") == "brasil", "grupo != brasil")
    f(l.get("roteiro") is True and l.get("aproximado") is True, "roteiro/aproximado devem ser true")
    f(isinstance(l.get("ordem"), int), "ordem não é inteiro")
    for c in ("titulo", "subtitulo", "contexto", "fonte"):
        f(isinstance(l.get(c), str) and l.get(c).strip() != "", f"{c} vazio")
    dur = l.get("duracao")
    f(isinstance(dur, (int, float)) and 5 <= dur <= 16, f"duracao fora de 5..16: {dur}")
    if not isinstance(dur, (int, float)):
        return stats
    times = l.get("times", {})
    f(isinstance(times, dict) and set(times) == {"attack", "defense"}, "times deve ter attack e defense")

    # --- bola
    bola = l["chavesBola"]
    stats["bola"] = len(bola)
    f(all(isinstance(k, list) and len(k) == 4 for k in bola), "chavesBola: cada chave é [t,x,y,z]")
    ts = [k[0] for k in bola]
    f(all(a < b for a, b in zip(ts, ts[1:])), "chavesBola fora de ordem ou com tempo repetido")
    f(0 <= ts[0] and ts[-1] <= dur, "chavesBola fora de [0, duracao]")
    f(all(k[3] >= 0 for k in bola), "bola abaixo do chão (z < 0)")
    ult = bola[-1]
    f(53.0 <= ult[1] <= 54.0 and ult[3] <= 0.05, f"última chave da bola deve estar em x~53,5 e no chão: {ult}")

    # --- jogadores
    jog = l["jogadores"]
    stats["jog"] = len(jog)
    f(12 <= len(jog) <= 22, f"{len(jog)} jogadores (esperado 12..22)")
    ids = [j.get("id") for j in jog]
    f(len(set(ids)) == len(ids), "ids de jogador repetidos")
    por_id = {j["id"]: j for j in jog}
    for j in jog:
        f(set(j.keys()) == CAMPOS_JOG, f"campos do jogador {j.get('id')} diferentes")
        f(j.get("time") in ("attack", "defense"), f"time inválido em {j.get('id')}")
        f(j.get("numero") is None or isinstance(j.get("numero"), int), f"numero inválido em {j.get('id')}")
        f(j.get("nome") is None or isinstance(j.get("nome"), str), f"nome inválido em {j.get('id')}")
        f(HEX.match(str(j.get("cor"))) is not None and HEX.match(str(j.get("borda"))) is not None,
          f"cor/borda inválida em {j.get('id')}")
        f(isinstance(j.get("estimado"), bool), f"estimado não é bool em {j.get('id')}")
        ch = j["chaves"]
        stats["chaves_jog"] += len(ch)
        f(all(isinstance(k, list) and len(k) == 3 for k in ch), f"chaves de {j.get('id')}: cada chave é [t,x,y]")
        jt = [k[0] for k in ch]
        f(all(a < b for a, b in zip(jt, jt[1:])), f"chaves de {j.get('id')} fora de ordem")
        f(0 <= jt[0] and jt[-1] <= dur, f"chaves de {j.get('id')} fora de [0, duracao]")
        if j.get("estimado") is False:
            f(3 <= len(ch) <= 10, f"{j.get('id')} (envolvido) tem {len(ch)} chaves; esperado 3..10")
        else:
            f(2 <= len(ch) <= 3, f"{j.get('id')} (estimado) tem {len(ch)} chaves; esperado 2..3")

    # --- finalizador e goleiro
    fin = l.get("finalizadorId")
    f(fin in por_id, f"finalizadorId {fin!r} não existe")
    if fin in por_id:
        f(por_id[fin]["time"] == "attack", "finalizador deve ser do time que ataca (attack)")
    gk = por_id.get(meta["goleiro"])
    f(gk is not None and gk["time"] == "defense", "goleiro do lance não existe ou não defende")

    # --- cores: camisas do ataque e da defesa não podem ficar parecidas
    def cor_principal(lado):
        cs = [j["cor"] for j in jog if j["time"] == lado and j["cor"] != R.GOLEIRO_COR]
        return max(set(cs), key=cs.count) if cs else None
    ca, cd = cor_principal("attack"), cor_principal("defense")
    if ca and cd:
        d = math.dist(cor_rgb(ca), cor_rgb(cd))
        f(d >= 120, f"camisas parecidas ({ca} x {cd}, distância {d:.0f}); usar a alternativa do time que defende")

    # --- amostragem: velocidades, limites
    ams = amostras(dur)
    for j in jog:
        ch = j["chaves"]
        for a, b in zip(ch, ch[1:]):
            v = math.dist(a[1:], b[1:]) / (b[0] - a[0])
            f(v <= VEL_JOGADOR + 1e-9, f"{j['id']}: {v:.2f} m/s entre chaves {a[0]} e {b[0]} (limite {VEL_JOGADOR})")
        prev = None
        for t in ams:
            p = jogador_em(ch, t)
            if prev is not None:
                v = math.dist(prev, p) * FPS
                stats["vmax_jog"] = max(stats["vmax_jog"], v)
                f(v <= VEL_JOGADOR + 1e-9, f"{j['id']}: {v:.2f} m/s amostrado em t={t:.2f} (limite {VEL_JOGADOR})")
            f(abs(p[0]) <= 56 and abs(p[1]) <= 40, f"{j['id']} fora do cenário em t={t:.2f}: {p}")
            prev = p
    prev = None
    for t in ams:
        b = bola_em(bola, t)
        if prev is not None:
            v = math.dist(prev, b) * FPS
            stats["vmax_bola"] = max(stats["vmax_bola"], v)
            f(v <= VEL_BOLA + 1e-9, f"bola: {v:.2f} m/s amostrado em t={t:.2f} (limite {VEL_BOLA})")
        f(b[2] >= -1e-9 and b[2] <= 4.5, f"altura da bola fora de 0..4,5 m em t={t:.2f}: {b[2]:.2f}")
        f(abs(b[1]) <= 40, f"bola fora do campo em t={t:.2f}: y={b[1]:.2f}")
        prev = b
    for a, b in zip(bola, bola[1:]):
        v = math.dist(a[1:], b[1:]) / (b[0] - a[0])
        f(v <= VEL_BOLA + 1e-9, f"bola: {v:.2f} m/s entre chaves {a[0]} e {b[0]}")

    # --- chute e toques
    t_chute = meta["t_chute"]
    f(t_chute <= dur - 1.5, f"chute em {t_chute}s; precisa de pelo menos 1,5 s até o fim ({dur}s)")
    f(t_chute >= 0, "chute negativo")
    chave_chute = [k for k in bola if abs(k[0] - t_chute) < 1e-9]
    f(len(chave_chute) == 1, "não há chave da bola no instante do chute")
    toques = meta["toques"]
    stats["toques"] = len(toques)
    f((t_chute, fin) in [(round(t, 2), p) for t, p in toques], "o finalizador não aparece como toque no instante do chute")
    for t, pid in toques:
        f(pid in por_id, f"toque de {pid!r} que não existe")
        if pid not in por_id:
            continue
        ks_t = [k for k in bola if abs(k[0] - t) < 1e-9]
        f(len(ks_t) == 1, f"toque de {pid} em t={t} sem chave da bola nesse instante")
        bx, by, bz = bola_em(bola, t)
        px, py = jogador_em(por_id[pid]["chaves"], t)
        d = math.hypot(px - bx, py - by)
        f(d <= TOQUE_M + 1e-9, f"toque de {pid} em t={t}: jogador a {d:.2f} m da bola (limite {TOQUE_M})")
        f(bz <= ALTURA_TOQUE_M + 1e-9, f"toque de {pid} em t={t}: bola a {bz:.2f} m de altura")

    # --- gol: nada antes do chute; cruzamento válido depois
    antes = [k for k in bola if k[0] < t_chute - 1e-9]
    f(all(abs(k[1]) <= GOL_X + 1e-9 for k in antes), "bola passou da linha de fundo antes do chute")
    for t in ams:
        if t < t_chute - 1e-9:
            f(abs(bola_em(bola, t)[0]) <= GOL_X + 1e-9, f"bola além da linha de fundo em t={t:.2f}, antes do chute")
    cruzamento = None
    for a, b in zip(bola, bola[1:]):
        if a[1] < GOL_X <= b[1]:
            cruzamento = (a, b)
            break
    f(cruzamento is not None, "a bola nunca cruza x = 52,5")
    if cruzamento is not None:
        a, b = cruzamento
        f(a[0] >= t_chute - 1e-9, "a bola cruza a linha do gol antes do chute")
        u = (GOL_X - a[1]) / (b[1] - a[1])
        y = a[2] + u * (b[2] - a[2])
        z = a[3] + u * (b[3] - a[3])
        f(abs(y) < TRAVE_Y, f"gol inválido: cruzamento em y={y:.2f} (|y| < {TRAVE_Y})")
        f(z < TRAVESSAO_Z, f"gol inválido: cruzamento em z={z:.2f} (z < {TRAVESSAO_Z})")
        idx = bola.index(b)
        f(all(k[1] >= GOL_X - 1e-9 for k in bola[idx:]), "a bola volta para fora do gol depois de entrar")

    # --- goleiro: começa perto do gol e reage
    if gk is not None:
        g0 = gk["chaves"][0]
        f(45 <= g0[1] <= GOL_X, f"goleiro começa em x={g0[1]} (esperado 45..52,5)")
        t_ini, t_fim = max(0.0, t_chute - 0.5), min(dur, t_chute + 1.0)
        pts = [jogador_em(gk["chaves"], t) for t in ams if t_ini - 1e-9 <= t <= t_fim + 1e-9]
        caminho = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
        f(caminho >= 1.0, f"goleiro quase parado perto do chute (percorreu {caminho:.2f} m; esperado >= 1,0)")

    # --- barreira (falta do Ceni): 4 a 5 jogadores a ~9,15 m da bola
    if lid.startswith("rogerio-ceni"):
        bx, by, _ = bola_em(bola, t_chute)
        barreira = []
        for j in jog:
            if j["time"] != "defense" or j["id"] == meta["goleiro"]:
                continue
            px, py = jogador_em(j["chaves"], t_chute)
            if 8.5 <= math.hypot(px - bx, py - by) <= 10.0 and px > bx:
                barreira.append(j["id"])
        f(4 <= len(barreira) <= 5, f"barreira com {len(barreira)} jogadores (esperado 4..5)")
        stats["barreira"] = len(barreira)

    return stats


def main():
    global verificacoes
    f_json = json.loads(SAIDA.read_text(encoding="utf-8"))
    lances = f_json.get("lances")
    checar(isinstance(lances, list) and len(lances) == 13, "brasil.json deve ter 13 lances")
    if not isinstance(lances, list):
        print("\n".join(erros))
        return 1
    gerados = R.gerar()
    checar(json.loads(json.dumps([d for d, _ in gerados])) == lances,
           "brasil.json não bate com o gerador: rode python3 -I scripts/roteiros_brasil.py")
    checar([l.get("ordem") for l in lances] == list(range(1, 14)), "ordem deve ser 1..13")
    checar(len({l.get("id") for l in lances}) == 13, "ids de lance repetidos")
    metas = {d["id"]: m for d, m in gerados}

    tabela = []
    for l in lances:
        meta = metas.get(l.get("id"))
        if meta is None:
            erros.append(f"[{l.get('id')}] lance não gerado pelo roteiros_brasil.py")
            continue
        tabela.append(testar_lance(l, meta))

    print(f"{'#':>2}  {'id':<48} {'dur':>5} {'jog':>3} {'bola':>4} {'toq':>3} {'v_jog':>6} {'v_bola':>6}")
    for s in tabela:
        extra = f"  barreira={s['barreira']}" if "barreira" in s else ""
        print(f"{s['ordem']:>2}  {s['id']:<48} {s['dur']:>5} {s['jog']:>3} {s['bola']:>4} {s['toques']:>3} "
              f"{s['vmax_jog']:>6.2f} {s['vmax_bola']:>6.2f}{extra}")
    print(f"verificações: {verificacoes}, falhas: {len(erros)}")
    for e in erros[:60]:
        print("FALHA", e)
    if len(erros) > 60:
        print(f"... mais {len(erros) - 60} falhas")
    if erros:
        print("RESULTADO: falhou")
        return 1
    print("RESULTADO: passou")
    return 0


if __name__ == "__main__":
    sys.exit(main())
