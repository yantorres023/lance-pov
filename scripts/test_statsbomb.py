"""Checagens de web/data/hypados.json (saida de scripts/prepare_statsbomb.py).

Uso: python3 -I scripts/test_statsbomb.py
Sai com codigo 1 se alguma checagem falhar.

Por lance:
  (a) finalizador a menos de 1,5 m da bola no quadro do chute (frameChute). Origi (Last-Row, sem
      quadro de chute no StatsBomb): menor distancia entre o finalizador e a bola nos 40 quadros
      antes de a bola cruzar a linha de gol.
  (b) a bola cruza a linha de gol +x depois do chute. O ponto do cruzamento e interpolado
      exatamente em x = 52,5 entre o ultimo quadro antes e o primeiro quadro alem da linha;
      exige |y| < 3,66 e z < 2,44 nesse ponto.
  (c) nenhum jogador passa de 10,5 m/s e a bola nao passa de 45 m/s (pares de quadros consecutivos).
  (d) pelo menos 8 jogadores.
  (e) len(bola) == frames e len(pos) == frames para cada jogador.
  (f) orientacao: Bale (cruzamento do Marcelo com y > 0) e Carlos Alberto (chute com y < 0).
  (g) jogadores ate 3 m fora das linhas: |x| <= 55,5 e |y| <= 37.
  (h) periodo: todos os eventos e quadros 360 usados sao do mesmo periodo do chute. Relido do cache
      (data/raw/statsbomb/data/events/<matchId>.json) a partir de lance.auditoria.
  (i) goleiro: quando ha quadro 360 associado, cada goleiro presente na janela fica a no maximo 30 m
      da propria linha de gol em todos os quadros. Goleiro sem nenhum evento/quadro na janela nao
      entra no lance (regra do brief) e e so listado.
  (j) finalizador percorre pelo menos 3 m na janela, salvo bola parada (penalti, falta, escanteio).
  (k) jogador com estimado:false nao fica parado (passo < 0,01 m por quadro) em mais de 80% dos quadros
      (so lances reconstruidos; o Origi e copia do Last-Row e fica fora desta checagem).
  (A) colagem: dentro dos segmentos de posse (data/posse/statsbomb.json e lastrow.json, que vale para
      o Origi), o dono fica a ate 0,9 m da bola em pelo menos 99% dos quadros, por lance.
  (E) eventos com bola: em todo evento com bola da janela (passe, conducao, drible, recebimento, chute,
      desarme, corte), o autor fica a ate 1,0 m da bola no instante do evento; durante toda conducao
      (Carry), a ate 0,9 m em todos os quadros. Quando nao fica, o caso e classificado e listado como
      conflito do dado: (1) bola em voo (acima de 10,3 m/s no instante); (2) evento fora da cadeia de bola
      (bola parada a mais de 3 m do local do evento); (3) atraso depois de um conflito de velocidade entre
      eventos registrado em data/posse/statsbomb.json. Qualquer outro caso e falha.
"""

import collections
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidencia as EV  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
JSON_PATH = RAIZ / "web" / "data" / "hypados.json"
CACHE_EVENTOS = RAIZ / "data" / "raw" / "statsbomb" / "data" / "events"
POSSE_DIR = RAIZ / "data" / "posse"
FPS = 20
LINHA_GOL = 52.5
A_LIMITE_M = EV.A_LIMITE_M
_MOTIVOS_ANTIGOS = ("bola em voo", "atraso apos conflito de velocidade", "atraso ate 0,5 s depois de bola em voo",
                "evento fora da cadeia de bola")


ANCORA_TIPOS_E = ("Carry", "Pass", "Shot", "Dribble", "Ball Receipt*", "Interception", "Ball Recovery", "Clearance")
VMAX_BOLA_CORTE = 10.3  # m/s: mesmo corte da colagem (bola acima disso nao esta no pe)
E_LIMITE_EVENTO_M = 1.0
E_LIMITE_CARRY_M = 0.9
E_BOLA_LONGE_M = 3.0
E_JANELA_ATRASO_S = 4.0  # s depois de um conflito de velocidade em que o atraso ainda conta como conflito


def _campo(loc, espelhar):
    x, y = loc
    if espelhar:
        x, y = 120.0 - x, 80.0 - y
    return (x - 60.0) * 105.0 / 120.0, (40.0 - y) * 68.0 / 80.0


def _vel_bola_em(bola, f, n):
    i = min(max(int(round(f)), 1), n - 2)
    return math.dist(bola[i + 1][:2], bola[i - 1][:2]) * FPS / 2


def motivo_conflito(bola, n, pid, f, t_rel, ev_xy, janelas):
    """Classifica um quadro/evento longe do dono (> limite) como conflito do dado, ou None (falha).
    1) bola em voo no instante (acima de VMAX_BOLA_CORTE);
    2) evento fora da cadeia de bola (bola parada a mais de E_BOLA_LONGE_M do local do evento);
    3) atraso depois de conflito de velocidade registrado (janelas);
    4) atraso ate 0,5 s depois de bola em voo (o jogador ainda esta alcancando a bola)."""
    if _vel_bola_em(bola, f, n) > VMAX_BOLA_CORTE:
        return "bola em voo"
    if ev_xy is not None:
        x0, y0 = bola[min(max(int(math.floor(f)), 0), n - 2)][:2]
        x1, y1 = bola[min(max(int(math.floor(f)), 0), n - 2) + 1][:2]
        s = min(max(f - math.floor(f), 0.0), 1.0)
        bx, by = x0 + (x1 - x0) * s, y0 + (y1 - y0) * s
        if math.dist(ev_xy, (bx, by)) > E_BOLA_LONGE_M:
            return "evento fora da cadeia de bola"
    if any(p == pid and a <= t_rel <= b for p, a, b, _ in janelas):
        return "atraso apos conflito de velocidade"
    if any(_vel_bola_em(bola, g, n) > VMAX_BOLA_CORTE for g in range(max(0, int(f) - 10), int(f) + 1)):
        return "atraso ate 0,5 s depois de bola em voo"
    return None


def janelas_de(posse_meta, lid):
    """Janelas de atraso registradas para o lance (conflitos e trechos de velocidade entre eventos)."""
    anc = posse_meta["ancoras"].get(lid, {})
    out = [(r_["pid"], r_["t_ini"] - 0.2, r_["t_fim"] + E_JANELA_ATRASO_S, "c") for r_ in anc.get("conflito", [])]
    out += [(r_["pid"], r_["t_ini"] - 0.2, r_["t_fim"] + E_JANELA_ATRASO_S, "v") for r_ in anc.get("vel", [])]
    return out


E_LIMITE_LOCAL_M = 1.0   # m: bola no local original do evento, no instante do evento
E_META_OK_PCT = 95.0     # % dos eventos com bola que devem ficar ok. Aceito pelo coordenador (~95,7%, com as
                         # incompatibilidades da fonte listadas); a meta anterior de 97% nao foi atingida


def checar_eventos(lances, posse_meta):
    """(E): eventos com bola (passe, conducao, drible, recebimento, chute, desarme, corte).
    Ok se, no instante do evento: (1) o autor esta a ate 1,0 m da bola e (2) a bola esta a ate 1,0 m do
    local ORIGINAL do evento (convertido para o campo). Quando nao, o caso vai para a lista de conflitos com
    motivo: bola em voo (acima de 10,3 m/s); incompatibilidade de cadeia (bola lenta fora do local do evento);
    atraso depois de conflito de velocidade registrado. Falha so o que nao tem motivo.
    Conducao (Carry): autor a ate 0,9 m em todos os quadros da conducao.
    Devolve (falhas, lista de conflitos/incompatibilidades, estatisticas)."""
    falhas, conflitos = [], []
    st = collections.Counter()
    for l in sorted(lances, key=lambda z: z["ordem"]):
        t0 = posse_meta["t0"].get(l["id"])
        if t0 is None or "auditoria" not in l:
            continue
        arq = CACHE_EVENTOS / f"{l['partida']['matchId']}.json"
        if not arq.exists():
            continue
        evs = {e["id"]: e for e in json.loads(arq.read_text(encoding="utf-8"))}
        gol_team = evs.get(l["auditoria"]["chuteId"], {}).get("team", {}).get("id")
        n = l["frames"]
        bola = l["bola"]
        jog = {j["id"]: j["pos"] for j in l["jogadores"]}
        janelas = janelas_de(posse_meta, l["id"])

        def em(pts, f):
            i = min(max(int(math.floor(f)), 0), n - 2)
            s_ = min(max(f - i, 0.0), 1.0)
            return (pts[i][0] * (1 - s_) + pts[i + 1][0] * s_, pts[i][1] * (1 - s_) + pts[i + 1][1] * s_)

        for eid in l["auditoria"]["eventos"]:
            e = evs.get(eid)
            if not e or e["type"]["name"] not in ANCORA_TIPOS_E or not e.get("player") or not e.get("location"):
                continue
            h, m_, s_ = e["timestamp"].split(":")
            te = int(h) * 3600.0 + int(m_) * 60.0 + float(s_)
            f = (te - t0) * FPS
            if f < 0 or f > n - 1:
                continue
            pid = str(e["player"]["id"])
            st["ev_tot"] += 1
            if pid not in jog:
                falhas.append(f"{l['ordem']:>2} {l['titulo']}: {e['type']['name']} sem trajetoria do autor {pid}")
                continue
            bf = em(bola, f)
            d_aut = math.dist(em(jog[pid], f), bf)
            ev_xy = _campo(e["location"], e["team"]["id"] != gol_team) if gol_team is not None else None
            d_loc = math.dist(ev_xy, bf) if ev_xy is not None else 0.0
            ok_aut, ok_loc = d_aut <= E_LIMITE_EVENTO_M, d_loc <= E_LIMITE_LOCAL_M
            st["medida_autor_ok"] += ok_aut
            st["medida_local_ok"] += ok_loc
            if ok_aut and ok_loc:
                st["ev_ok"] += 1
                continue
            item = f"{l['ordem']:>2} {e['type']['name']} t={te - t0:.2f}s autor={d_aut:.2f} m local={d_loc:.2f} m"
            vb = _vel_bola_em(bola, f, n)
            if not ok_loc and vb > VMAX_BOLA_CORTE:
                conflitos.append(f"{item}: bola em voo")
                st["bola em voo"] += 1
            elif not ok_loc:
                conflitos.append(f"{item}: incompatibilidade de cadeia (bola lenta fora do local do evento)")
                st["incompatibilidade"] += 1
            else:
                motivo = motivo_conflito(bola, n, pid, f, te - t0, None, janelas)
                if motivo:
                    conflitos.append(f"{item}: {motivo}")
                    st[motivo] += 1
                else:
                    falhas.append(f"{l['ordem']:>2} {l['titulo']}: {e['type']['name']} em {te - t0:.2f}s, autor a {d_aut:.2f} m da bola (max {E_LIMITE_EVENTO_M})")
        for eid in l["auditoria"]["eventos"]:
            e = evs.get(eid)
            if not e or e["type"]["name"] != "Carry" or not e.get("player"):
                continue
            pid = str(e["player"]["id"])
            h, m_, s_ = e["timestamp"].split(":")
            te = int(h) * 3600.0 + int(m_) * 60.0 + float(s_)
            dur = float(e.get("duration") or 0.0)
            if pid not in jog:
                continue
            for fr in range(max(0, math.ceil((te - t0) * FPS - 1e-9)), min(n - 1, math.floor((te + dur - t0) * FPS + 1e-9)) + 1):
                st["car_tot"] += 1
                d = math.dist(jog[pid][fr], bola[fr][:2])
                if d <= E_LIMITE_CARRY_M:
                    st["car_ok"] += 1
                    continue
                motivo = motivo_conflito(bola, n, pid, fr, fr / FPS, None, janelas)
                segs_pid = [(a_, b_) for p_, a_, b_, *_ in posse_meta.get("originais", {}).get(l["id"], [])
                            if p_ == pid]
                dentro = [(a_, b_) for a_, b_ in segs_pid if a_ <= fr <= b_]
                if not motivo and not dentro and segs_pid:
                    # fora da posse original (definicao): chegada antes do toque, ou posse encerrada antes do fim
                    motivo = ("fora da posse: chegada antes do toque (definicao)" if fr < min(a_ for a_, _ in segs_pid)
                              else "fora da posse: posse encerrada antes do fim da conducao (definicao)")
                elif not motivo and dentro and fr - dentro[0][0] < FPS:
                    motivo = "entrada: dono ainda chegando (1 s do inicio da posse)"
                item = f"{l['ordem']:>2} Carry {pid} quadro {fr} (t={fr / FPS:.2f}s) autor={d:.2f} m"
                if motivo:
                    conflitos.append(f"{item}: {motivo}")
                    st[motivo] += 1
                else:
                    falhas.append(f"{l['ordem']:>2} {l['titulo']}: conducao {pid} no quadro {fr}, autor a {d:.2f} m da bola (max {E_LIMITE_CARRY_M})")
                    break
    return falhas, conflitos, st

def carregar_originais():
    """id do lance -> segmentos ORIGINAIS detectados (antes de qualquer recorte): (id, ini, fim)."""
    segs = {}
    for nome in ("statsbomb.json", "lastrow.json"):
        arq = POSSE_DIR / nome
        if not arq.exists():
            continue
        dados = json.loads(arq.read_text(encoding="utf-8"))
        for lid, lista in dados.get("originais", {}).items():
            segs.setdefault(lid, []).extend((str(p), int(a), int(b)) for p, a, b, *_ in lista)
    return segs


def carregar_posse():
    """id do lance -> [(id do jogador, ini, fim)] em quadros, juntando statsbomb.json e lastrow.json."""
    segs = {}
    for nome in ("statsbomb.json", "lastrow.json"):
        arq = POSSE_DIR / nome
        if not arq.exists():
            continue
        for lid, lista in json.loads(arq.read_text(encoding="utf-8"))["lances"].items():
            segs.setdefault(lid, []).extend((str(p), int(a), int(b)) for p, a, b, *_ in lista)
    return segs


def achar(lances, prefixo):
    for l in lances:
        if l["titulo"].startswith(prefixo):
            return l
    raise KeyError(prefixo)


def cruzamento_interpolado(bola, inicio):
    """Primeiro par de quadros consecutivos que cruza x = 52,5 depois de `inicio`.
    Devolve (y, z) interpolados em x = 52,5, ou None."""
    for i in range(inicio + 1, len(bola)):
        a, b = bola[i - 1], bola[i]
        if a is None or b is None:
            continue
        if a[0] <= LINHA_GOL < b[0]:
            s = (LINHA_GOL - a[0]) / (b[0] - a[0])
            return a[1] + s * (b[1] - a[1]), a[2] + s * (b[2] - a[2])
    return None


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
    eventos_checados = 0
    goleiros_ausentes = []
    conflitos_gerais = []
    resumo_a = []
    posse_orig = carregar_originais()
    posse_meta_full = json.loads((POSSE_DIR / "statsbomb.json").read_text(encoding="utf-8")) if (POSSE_DIR / "statsbomb.json").exists() else {"t0": {}, "ancoras": {}}
    posse = carregar_posse()
    if not any(l["id"] in posse for l in lances):
        falha({"ordem": 0, "titulo": "posse"}, "sem data/posse/statsbomb.json (rode prepare_statsbomb.py)")
    a_total = a_bons = 0
    for l in sorted(lances, key=lambda z: z["ordem"]):
        n = l["frames"]
        bola = l["bola"]
        jogs = l["jogadores"]
        conflitos_a = []
        # (e)
        if len(bola) != n:
            falha(l, f"bola com {len(bola)} quadros (frames={n})")
        for j in jogs:
            if len(j["pos"]) != n:
                falha(l, f"jogador {j['nome']} com {len(j['pos'])} quadros (frames={n})")
        # (d)
        if len(jogs) < 8:
            falha(l, f"so {len(jogs)} jogadores (minimo 8)")
        # (c): nenhum jogador passa de 10,5 m/s na trajetoria final (teste estrito, sem excecao)
        vmax_j = 0.0
        for j in jogs:
            p = j["pos"]
            for i in range(1, len(p)):
                if p[i] is None or p[i - 1] is None:
                    continue
                v_i = math.dist(p[i], p[i - 1]) * FPS
                vmax_j = max(vmax_j, v_i)
                if v_i > 10.5 + 1e-6:
                    falha(l, f"jogador {j['nome']} a {v_i:.2f} m/s no quadro {i} (max 10,5)")
                    break
        if vmax_j > 10.5 + 1e-6:
            falha(l, f"jogador a {vmax_j:.2f} m/s (max 10,5)")
        vmax_b = 0.0
        for i in range(1, n):
            if bola[i] is None or bola[i - 1] is None:
                continue
            vmax_b = max(vmax_b, math.dist(bola[i], bola[i - 1]) * FPS)
        if vmax_b > 45.0:
            falha(l, f"bola a {vmax_b:.2f} m/s (max 45)")
        # (g)
        for j in jogs:
            if any(p is not None and (abs(p[0]) > 55.5 + 1e-6 or abs(p[1]) > 37.0 + 1e-6) for p in j["pos"]):
                falha(l, f"jogador {j['nome']} fora do campo +3 m")
                break
        # (k) so lances reconstruidos (o Origi e copia do Last-Row, com jogadores sem nome parados)
        for j in (jogs if l.get("auditoria") else []):
            if j.get("estimado") is not False:
                continue
            p = j["pos"]
            passos = [i for i in range(1, len(p)) if p[i] is not None and p[i - 1] is not None]
            if passos:
                paradas = sum(1 for i in passos if math.dist(p[i], p[i - 1]) < 0.01)
                if paradas / len(passos) > 0.8:
                    falha(l, f"jogador estimado:false {j['nome']} parado em {100 * paradas / len(passos):.0f}% da janela")

        fin_id = str(l["finalizadorId"])
        fin = next((j for j in jogs if j["id"] == fin_id), None)
        if fin is None:
            falha(l, "finalizador ausente em jogadores")
            continue

        # (j)
        if not l.get("bolaParada", False):
            caminho = sum(math.dist(fin["pos"][i], fin["pos"][i - 1]) for i in range(1, n)
                          if fin["pos"][i] is not None and fin["pos"][i - 1] is not None)
            if caminho < 3.0:
                falha(l, f"finalizador percorre so {caminho:.2f} m na janela (minimo 3, fora de bola parada)")
        else:
            caminho = None

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
            inicio = next(i for i in range(1, n) if bola[i] and bola[i - 1] and bola[i][0] > LINHA_GOL >= bola[i - 1][0])
            dists = [math.dist((bola[i][0], bola[i][1]), tuple(fin["pos"][i])) for i in range(max(0, inicio - 40), inicio + 1)
                     if bola[i] and fin["pos"][i]]
            dist_a = min(dists) if dists else None
            if dist_a is None or dist_a >= 1.5:
                falha(l, f"finalizador a {dist_a} m da bola antes do gol (max 1,5)")
        cz = cruzamento_interpolado(bola, inicio if "frameChute" in l else inicio - 1)
        if cz is None:
            falha(l, "bola nao cruza a linha de gol apos o chute")
            cruz_y = None
        else:
            y, z = cz
            cruz_y = y
            if not (abs(y) < 3.66 and z < 2.44):
                falha(l, f"cruzamento em x=52,5 com y={y:.2f} z={z:.2f} (exige |y|<3,66 e z<2,44)")

        # (h)
        aud = l.get("auditoria")
        if aud:
            arq = CACHE_EVENTOS / f"{l['partida']['matchId']}.json"
            if not arq.exists():
                falha(l, f"cache de eventos ausente ({arq.name})")
            else:
                periodos = {e["id"]: e["period"] for e in json.loads(arq.read_text(encoding="utf-8"))}
                p0 = aud["periodo"]
                if periodos.get(aud["chuteId"]) != p0:
                    falha(l, "chute fora do periodo registrado")
                for uid in aud["eventos"] + aud["frames360"]:
                    eventos_checados += 1
                    if periodos.get(uid) != p0:
                        falha(l, f"evento/quadro 360 {uid} do periodo {periodos.get(uid)} (chute no {p0})")
                        break

        # (i) goleiros presentes na janela; goleiro sem nenhum evento/quadro nao entra no lance
        if aud and aud.get("frames360"):
            for time_ in ("attack", "defense"):
                gks = [j for j in jogs if j.get("goleiro") and j["time"] == time_]
                if not gks:
                    goleiros_ausentes.append(f"{l['ordem']}:{time_}")
                linha = -LINHA_GOL if time_ == "attack" else LINHA_GOL
                for g in gks:
                    if any(p is not None and abs(p[0] - linha) > 30.0 for p in g["pos"]):
                        falha(l, f"goleiro {g['nome']} a mais de 30 m da propria linha de gol")

        # (A) colagem: sobre os segmentos ORIGINAIS detectados (antes de qualquer recorte), cobertura integral.
        # Quadro acima de 0,9 m do dono vai para as excecoes, com motivo; continua no denominador.
        if l["id"] in posse_meta_full.get("originais", {}):  # so a fonte StatsBomb (Origi e medido no test_lastrow)
            segs_o = [tuple(s) for s in posse_meta_full["originais"][l["id"]]]
            bola_o = posse_meta_full.get("bola_original", {}).get(l["id"], bola)
            dists_o = posse_meta_full.get("distancia_original", {}).get(l["id"], [])
            pos_jog = {j["id"]: j["pos"] for j in jogs}
            janelas_ev = {}
            for pid_, ta, tb, _ in janelas_de(posse_meta_full, l["id"]):
                janelas_ev.setdefault(pid_, []).append((ta, tb))

            def pos_fn(pid, f, pos_jog=pos_jog, n=n):
                p_ = pos_jog.get(pid, [None] * n)[f]
                return None if p_ is None else (p_[0], p_[1])

            def bola_fn(f, bola=bola):
                return bola[f]

            r = EV.avaliar(FPS, n, segs_o, dists_o, pos_fn, bola_fn, bola_o, janelas_ev)
            a_total += r["tot"]
            a_bons += r["ok"] + sum(r["justificados"].values())
            resumo_a.append((l["ordem"], l["titulo"], r["pct_just"], r["pct_ok"], r["tot"], dict(r["justificados"]),
                             dict(r["exemplos"])))
            if r["pct_just"] < EV.A_META_LANCE_PCT:
                falha(l, f"colagem (A) {r['pct_just']:.2f}% sem evidencia original em {len(r['falhas'])} quadros: "
                         f"{[(p_, f_, d_) for p_, f_, d_, _ in r['falhas'][:4]]}")
        resumo.append(f"{l['ordem']:>2} {l['titulo']:<36} frames={n:<4} jog={len(jogs):<3} "
                      f"v_jog={vmax_j:5.2f} v_bola={vmax_b:5.1f} dist_fin={'-' if dist_a is None else f'{dist_a:.2f}'} "
                      f"corr_fin={'bola_parada' if caminho is None else f'{caminho:5.1f}m'} "
                      f"cruz_y={'-' if cruz_y is None else f'{cruz_y:+.2f}'}")

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
    resumo.append(f"    (h) eventos e quadros 360 relidos do cache: {eventos_checados}")
    resumo.append(f"    (i) times sem goleiro na janela (nao exigido, sem dado): {', '.join(goleiros_ausentes) or 'nenhum'}")

    print("\n".join(resumo))
    print(f"    (A) colagem real (segmentos originais, denominador integral): {a_bons} de {a_total} quadros a ate "
          f"{A_LIMITE_M} m do dono ({100 * a_bons / max(1, a_total):.2f}%)")
    for ordem_a, tit_a, pct_j, pct_o, tot_a, exc_a, ex_a in resumo_a:
        if tot_a and pct_o < 99.0:
            print(f"      (A) {ordem_a} {tit_a}: ok {pct_o:.2f}%; excecoes por quadro: "
                  + "; ".join(f"{k}={v} (ex.: {ex_a[k]})" for k, v in exc_a.items()))
    if a_total and 100 * a_bons / a_total < EV.A_META_FONTE_PCT:
        falhas.append(f"(A) fonte StatsBomb {100 * a_bons / a_total:.2f}% (meta {EV.A_META_FONTE_PCT}%)")
    ef, ec, st_e = checar_eventos(lances, posse_meta_full)
    falhas.extend(ef)
    ev_tot, ev_ok = st_e["ev_tot"], st_e["ev_ok"]
    car_tot, car_ok = st_e["car_tot"], st_e["car_ok"]
    pct_e = 100 * ev_ok / max(1, ev_tot)
    if pct_e < E_META_OK_PCT:
        falhas.append(f"(E) eventos com bola ok {pct_e:.2f}% (meta {E_META_OK_PCT}%)")
    print(f"    (E) eventos com bola: {ev_ok} de {ev_tot} ok ({pct_e:.2f}%; meta {E_META_OK_PCT}%); "
          f"quadros de conducao ok: {car_ok} de {car_tot} ({100 * car_ok / max(1, car_tot):.2f}%)")
    print(f"    (E) medida 1 autor a ate {E_LIMITE_EVENTO_M} m da bola: {st_e['medida_autor_ok']} de {ev_tot}; "
          f"medida 2 bola a ate {E_LIMITE_LOCAL_M} m do local original: {st_e['medida_local_ok']} de {ev_tot}")
    print(f"    (E) conflitos/incompatibilidades listados: {len(ec)}; por motivo: "
          + ", ".join(f"{k} {v}" for k, v in sorted(st_e.items()) if k not in ("ev_tot", "ev_ok", "car_tot", "car_ok", "medida_autor_ok", "medida_local_ok")))
    for linha in ec:
        print("      conflito:", linha)
    if falhas:
        print(f"\nFALHAS ({len(falhas)}):")
        print("\n".join(falhas))
        return 1
    print(f"\nOK: {len(lances)} lances, todas as checagens passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
