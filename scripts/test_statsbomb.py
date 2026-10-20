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

import json
import math
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JSON_PATH = RAIZ / "web" / "data" / "hypados.json"
CACHE_EVENTOS = RAIZ / "data" / "raw" / "statsbomb" / "data" / "events"
POSSE_DIR = RAIZ / "data" / "posse"
FPS = 20
LINHA_GOL = 52.5
A_LIMITE_M = 0.9
A_META_PCT = 99.0


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


def checar_eventos(lances, posse_meta):
    """(E): ver o cabecalho. Devolve (falhas, conflitos, total de eventos/quadros checados)."""
    falhas, conflitos = [], []
    checados = ok = 0
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
            s = min(max(f - i, 0.0), 1.0)
            return (pts[i][0] * (1 - s) + pts[i + 1][0] * s, pts[i][1] * (1 - s) + pts[i + 1][1] * s)

        def classificar(pid, f, t_rel, ev_xy, d):
            return motivo_conflito(bola, n, pid, f, t_rel, ev_xy, janelas)

        for eid in l["auditoria"]["eventos"]:
            e = evs.get(eid)
            if not e or e["type"]["name"] not in ANCORA_TIPOS_E or not e.get("player") or not e.get("location"):
                continue
            t = e["timestamp"]
            h, m_, s_ = t.split(":")
            te = int(h) * 3600.0 + int(m_) * 60.0 + float(s_)
            f = (te - t0) * FPS
            if f < 0 or f > n - 1:
                continue
            pid = str(e["player"]["id"])
            checados += 1
            if pid not in jog:
                falhas.append(f"{l['ordem']:>2} {l['titulo']}: {e['type']['name']} sem trajetoria do autor {pid}")
                continue
            d = math.dist(em(jog[pid], f), em(bola, f))
            if d <= E_LIMITE_EVENTO_M:
                ok += 1
                continue
            ev_xy = _campo(e["location"], e["team"]["id"] != gol_team) if gol_team is not None else None
            motivo = classificar(pid, f, te - t0, ev_xy, d)
            item = f"{l['ordem']:>2} {e['type']['name']} t={te - t0:.2f}s autor={d:.2f} m"
            if motivo:
                conflitos.append(f"{item}: {motivo}")
            else:
                falhas.append(f"{l['ordem']:>2} {l['titulo']}: {e['type']['name']} em {te - t0:.2f}s, autor a {d:.2f} m da bola (max {E_LIMITE_EVENTO_M})")
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
                checados += 1
                d = math.dist(jog[pid][fr], bola[fr][:2])
                if d <= E_LIMITE_CARRY_M:
                    ok += 1
                    continue
                motivo = classificar(pid, fr, fr / FPS, None, d)
                item = f"{l['ordem']:>2} Carry {pid} quadro {fr} (t={fr / FPS:.2f}s) autor={d:.2f} m"
                if motivo:
                    conflitos.append(f"{item}: {motivo}")
                else:
                    falhas.append(f"{l['ordem']:>2} {l['titulo']}: conducao {pid} no quadro {fr}, autor a {d:.2f} m da bola (max {E_LIMITE_CARRY_M})")
                    break
    return falhas, conflitos, checados, ok


def carregar_posse():
    """id do lance -> [(id do jogador, ini, fim)] em quadros, juntando statsbomb.json e lastrow.json."""
    segs = {}
    for nome in ("statsbomb.json", "lastrow.json"):
        arq = POSSE_DIR / nome
        if not arq.exists():
            continue
        for lid, lista in json.loads(arq.read_text(encoding="utf-8"))["lances"].items():
            segs.setdefault(lid, []).extend((str(p), int(a), int(b)) for p, a, b in lista)
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
        # (c)
        vmax_j = 0.0
        # (c): 10,5 m/s. Entre dois eventos com bola, um trecho que o dado pede mais rapido (registrado em
        # data/posse/statsbomb.json, ate 11,5 m/s, com janela de atraso depois) e a unica excecao.
        janelas_c = janelas_de(posse_meta_full, l["id"])
        for j in jogs:
            p = j["pos"]
            for i in range(1, len(p)):
                if p[i] is None or p[i - 1] is None:
                    continue
                v_i = math.dist(p[i], p[i - 1]) * FPS
                vmax_j = max(vmax_j, v_i)
                if v_i > 10.5 + 1e-6:
                    registrado = any(pid_ == j["id"] and a_ <= i / FPS <= b_ for pid_, a_, b_, _ in janelas_c)
                    if not registrado or v_i > 11.5 + 1e-6:
                        falha(l, f"jogador {j['nome']} a {v_i:.2f} m/s no quadro {i} (max 10,5; excecao registrada ate 11,5)")
                        break
        if vmax_j > 11.5 + 1e-6:
            falha(l, f"jogador a {vmax_j:.2f} m/s (max 11,5 mesmo em trecho registrado)")
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

        # (A) colagem da posse: dono a ate 0,9 m da bola nos quadros de posse. Quadros com motivo de
        # conflito do dado (ver motivo_conflito) saem do calculo e sao listados.
        if l["id"] in posse:
            pos_jog = {j["id"]: j["pos"] for j in jogs}
            tot_l = bons_l = 0
            janelas_l = janelas_de(posse_meta_full, l["id"])
            for pid, a, b in posse[l["id"]]:
                for f in range(max(0, a), min(n - 1, b) + 1):
                    p_ = pos_jog.get(pid, [None] * n)[f]
                    if p_ is None or bola[f] is None:
                        continue
                    d_ = math.hypot(p_[0] - bola[f][0], p_[1] - bola[f][1])
                    if d_ <= A_LIMITE_M:
                        tot_l += 1
                        bons_l += 1
                        continue
                    motivo_a = motivo_conflito(bola, n, pid, f, f / FPS, None, janelas_l)
                    if motivo_a:
                        conflitos_a.append(f"{l['ordem']:>2} (A) {pid} quadro {f} autor={d_:.2f} m: {motivo_a}")
                    else:
                        tot_l += 1
            a_total += tot_l
            a_bons += bons_l
            conflitos_gerais.extend(conflitos_a)
            if tot_l and 100 * bons_l / tot_l < A_META_PCT:
                falha(l, f"colagem (A): {100 * bons_l / tot_l:.1f}% dos quadros de posse a ate {A_LIMITE_M} m (meta {A_META_PCT}%)")
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
    print(f"    (A) colagem: {a_bons} de {a_total} quadros de posse a ate {A_LIMITE_M} m do dono "
          f"({100 * a_bons / max(1, a_total):.2f}%)")
    ef, ec, e_tot, e_ok = checar_eventos(lances, posse_meta_full)
    falhas.extend(ef)
    print(f"    (A) quadros de posse fora do calculo por conflito do dado: {len(conflitos_gerais)}")
    print(f"    (E) eventos com bola e conducoes: {e_ok} de {e_tot} quadros/eventos ate o limite; "
          f"conflitos do dado listados: {len(ec)}; falhas: {len(ef)}")
    for linha in conflitos_gerais + ec:
        print("      conflito:", linha)
    if falhas:
        print(f"\nFALHAS ({len(falhas)}):")
        print("\n".join(falhas))
        return 1
    print(f"\nOK: {len(lances)} lances, todas as checagens passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
