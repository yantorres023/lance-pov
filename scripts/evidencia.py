"""Medida (A) com excecoes por quadro e evidencia nos dados ORIGINAIS (antes da correcao).

Cada quadro de posse com o dono a mais de A_LIMITE_M da bola (depois da correcao) e um de tres casos:
- justificado: um motivo abaixo tem evidencia nos dados originais (bola_original, distancia_original, janelas
  de conflito registradas a partir dos eventos). O motivo vale so para aquele quadro;
- falha: nenhum motivo se sustenta com o dado original (inclusive quando a correcao piorou um quadro que
  o dado original ja deixava dentro de A_LIMITE_M).

Motivos e evidencia exigida:
- "bola em voo": velocidade ORIGINAL da bola acima de VMAX_BOLA_CORTE ou z original acima de Z_VOO;
- "atraso apos conflito de velocidade": quadro dentro de janela de conflito registrada (eventos originais);
- "atraso ate 0,5 s depois de bola em voo": bola original em voo nos 0,5 s anteriores;
- "chegada": dono a mais de A_LIMITE_M no dado original, nos primeiros JANELA_S do segmento;
- "saida": dono a mais de A_LIMITE_M no dado original, nos ultimos JANELA_S do segmento;
- "bola parada (preparacao)": bola original parada (abaixo de PARADA_VEL) e dono a mais de A_LIMITE_M: a correcao
  nunca move bola parada (registro do gerador conferido com o dado original).
"Correcao recusada pelo limite de velocidade" NAO e motivo: e limitacao da correcao, nao fato do dado; o quadro
e falha, com a razao registrada pelo gerador no detalhe.
A meta e por fonte e por lance: quadros justificados contam como ok, e o lance precisa de A_META_LANCE_PCT.
"""
import math

A_LIMITE_M = 0.9
A_META_LANCE_PCT = 99.0
A_META_FONTE_PCT = 99.0
VMAX_BOLA_CORTE = 10.3   # m/s: bola acima disso nao esta no pe
Z_VOO = 0.6              # m: bola acima disso nao esta no pe
JANELA_S = 0.5           # s: chegada e saida da posse


def vel_original(bola_orig, f, fps):
    n = len(bola_orig)
    a, b = max(0, f - 1), min(n - 1, f + 1)
    if a == b:
        return 0.0
    return math.dist(bola_orig[b][:2], bola_orig[a][:2]) * fps / (b - a)


PARADA_VEL = 0.3         # m/s: bola original abaixo disso esta parada


def motivo(bola_orig, f, fps, a_seg, b_seg, d0, janelas, recusado=None):
    """Motivo com evidencia original para o quadro f fora de A_LIMITE_M, ou None (falha).
    janelas: [(t_ini, t_fim)] em segundos relativos ao t0 do lance (conflitos registrados do jogador)."""
    v0 = vel_original(bola_orig, f, fps)
    z0 = bola_orig[f][2]
    if v0 > VMAX_BOLA_CORTE or z0 > Z_VOO:
        return "bola em voo", f"original {v0:.2f} m/s, z {z0:.2f} m"
    t = f / fps
    for ti, tf in janelas:
        if ti <= t <= tf:
            return "atraso apos conflito de velocidade", f"evento original, janela {ti:.2f}-{tf:.2f} s"
    if recusado == "parada" and d0 is not None and d0 > A_LIMITE_M and v0 < PARADA_VEL:
        return "bola parada (preparacao)", f"original {v0:.2f} m/s, dono a {d0:.2f} m"
    if any(vel_original(bola_orig, g, fps) > VMAX_BOLA_CORTE for g in range(max(0, f - int(round(JANELA_S * fps))), f + 1)):
        return "atraso ate 0,5 s depois de bola em voo", "bola original em voo nos 0,5 s anteriores"
    if d0 is not None and d0 > A_LIMITE_M:
        if f - a_seg <= JANELA_S * fps:
            return "chegada", f"dono a {d0:.2f} m no dado original, inicio da posse"
        if b_seg - f <= JANELA_S * fps:
            return "saida", f"dono a {d0:.2f} m no dado original, fim da posse"
    return None


def avaliar(fps, n, segs, dist_orig, pos_fn, bola_fn, bola_orig, janelas, recusados=None):
    """segs: [(pid, a, b, ...)] originais; dist_orig: lista paralela (distancias originais por quadro do segmento);
    pos_fn(pid, f) -> (x, y) corrigido ou None; bola_fn(f) -> (x, y, z) corrigido; janelas: pid -> [(t_ini, t_fim)].
    Devolve dict: tot, ok, justificados {motivo: n}, falhas [(pid, f, d, detalhe)], exemplos {motivo: detalhe}."""
    out = {"tot": 0, "ok": 0, "justificados": {}, "falhas": [], "exemplos": {}}
    for k, seg in enumerate(segs):
        pid, a, b = seg[0], seg[1], seg[2]
        dists = dist_orig[k] if k < len(dist_orig) else []
        for f in range(max(0, a), min(n - 1, b) + 1):
            out["tot"] += 1
            p = pos_fn(pid, f)
            bf = bola_fn(f)
            if p is None or bf is None:
                out["falhas"].append((pid, f, None, "sem dado"))
                continue
            d = math.dist(p, bf[:2])
            if d <= A_LIMITE_M:
                out["ok"] += 1
                continue
            d0 = dists[f - a] if 0 <= f - a < len(dists) else None
            rec = (recusados or {}).get((pid, f))
            m = motivo(bola_orig, f, fps, a, b, d0, janelas.get(pid, []), rec)
            if m is None:
                razao = "sem motivo de dado"
                if rec == "limite_velocidade":
                    razao = (f"correcao recusada pelo limite de velocidade (original {vel_original(bola_orig, f, fps):.2f} "
                             f"m/s; sem salto acima de max(10,3; original))")
                out["falhas"].append((pid, f, round(d, 2), razao))
            else:
                nome, det = m
                out["justificados"][nome] = out["justificados"].get(nome, 0) + 1
                out["exemplos"].setdefault(nome, det)
    out["pct_ok"] = 100.0 * out["ok"] / out["tot"] if out["tot"] else 100.0
    out["pct_just"] = 100.0 * (out["ok"] + sum(out["justificados"].values())) / out["tot"] if out["tot"] else 100.0
    return out
