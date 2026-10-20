"""Colagem da posse: quem tem a bola fica DIST_M metros atras dela, no sentido do movimento.

Biblioteca padrao, sem dependencias. Usada por prepare_statsbomb.py e prepare_lastrow.py (e pode
ser usada por roteiros_brasil.py). Nao sabe de fontes: recebe a bola por quadro, a trajetoria de
cada jogador e uma lista de segmentos de posse.

colar(fps, bola, jogadores, segmentos, vmax=VMAX_MS, lim=None, vmax_bola=None) -> (novas, relatorio)

  bola        [[x, y, z], ...] por quadro, sem None (metros)
  jogadores   {id: [[x, y] | None, ...]} por quadro, mesmo comprimento de bola
  segmentos   [(id, ini, fim), ...] em quadros, extremos inclusivos: o jogador tem a bola
  vmax        velocidade maxima do jogador (m/s); o padrao e 10,5
  lim         opcional {id: (lim_x, lim_y)}: prende o jogador a esses limites (metros)
  vmax_bola   opcional: bola acima disso (m/s) nao esta no pe; esses quadros saem da posse (padrao: vmax)

  novas       {id: [[x, y], ...]}: posicoes depois da colagem (so muda na posse e nas rampas)
  relatorio   {"runs": [(id, ini, fim), ...]  posse efetiva (a que foi colada),
               "quadros_colados": int,
               "cortados_bola_rapida": int   quadros de segmento com bola acima de vmax_bola (fora da posse),
               "conflitos": int              quadros com dois donos (fica o que comecou primeiro),
               "fora_do_alcance": int        quadros tirados das pontas: jogador ainda longe da posicao colada,
               "vel_jogador": [(id, quadro, m/s)] jogador acima de vmax depois da colagem (deve ser vazio)}

Regras:
- Dentro da posse o jogador fica em B - DIST_M * u, onde u e o sentido do movimento da bola. Com a bola
  quase parada, u e o sentido do movimento do proprio jogador (fica atras da bola, do lado de onde vinha).
- A posse so comeca quando o jogador esta a ate DIST_ENTRADA da posicao colada, e so termina enquanto ele
  ainda esta a ate DIST_PONTA; quadros fora disso saem da posse (e contam em fora_do_alcance).
- Rampa antes e depois da posse: mistura suave entre a posicao original e a colada, mais longa quando o
  salto e grande (RAMPA_FATOR). Nada e movido fora da posse, salvo a rampa.
- Limite de velocidade do caminho inteiro do jogador: se a mistura ou a bola forem rapidas demais, ele
  segue com atraso (erro de colagem), nunca com salto.
- Mesmo jogador com duas posses separadas por folga curta e so bola lenta: vira uma posse so.
"""
import math

DIST_M = 0.45          # m: distancia do jogador atras da bola
ANCORADOS = ("carry", "dribble", "passe", "chute")  # tipos de posse que comecam em evento com bola (ancora)
SEM_CORTE_PONTA = ANCORADOS + ("receb",)  # estas posses nao saem das pontas (entrada/saida) por distancia
VMAX_MS = 10.5         # m/s: limite do jogador
RAMPA_S = 0.2          # s: rampa de entrada e de saida
VEL_BOLA_LENTA = 1.0   # m/s: abaixo disso, o sentido vem do jogador
VEL_BOLA_RAPIDA = 2.0  # m/s: acima disso, o sentido vem da bola (mistura linear entre os dois)
VEL_JOG_MIN = 0.3      # m/s: velocidade minima do jogador para definir o proprio sentido
DIST_ENTRADA = 2.0     # m: a posse so comeca quando o jogador esta a esta distancia da posicao colada
DIST_PONTA = 0.85      # m: as pontas da posse saem enquanto o jogador ainda nao esta colado (ao menos isto)
RAMPA_FATOR = 3.0      # rampa de (FATOR * salto * fps / vmax) quadros: a mistura nao soma velocidade demais


def _suave(s):
    s = min(1.0, max(0.0, s))
    return s * s * (3.0 - 2.0 * s)


def _vel(pts, i, fps):
    """Velocidade (vx, vy) por diferenca central no quadro i, ou None se faltar ponto."""
    n = len(pts)
    a, b = max(0, i - 1), min(n - 1, i + 1)
    if a == b or pts[a] is None or pts[b] is None:
        return None
    dt = (b - a) / fps
    return ((pts[b][0] - pts[a][0]) / dt, (pts[b][1] - pts[a][1]) / dt)


def _sentidos_jogador(orig, fps):
    """Sentido unitario do movimento do jogador em cada quadro (o ultimo valido, para tras ate o primeiro)."""
    out, ultimo = [], None
    for i in range(len(orig)):
        v = _vel(orig, i, fps)
        if v is not None and math.hypot(*v) >= VEL_JOG_MIN:
            m = math.hypot(*v)
            ultimo = (v[0] / m, v[1] / m)
        out.append(ultimo)
    primeiro = next((u for u in out if u is not None), None)
    return [u if u is not None else primeiro for u in out]


def _mistura(orig_xy, alvo_xy, s_g):
    """s_g = 1 e so a colada; s_g = 0 e so a original (sem original, fica a colada)."""
    if orig_xy is None:
        return alvo_xy
    return (s_g * alvo_xy[0] + (1 - s_g) * orig_xy[0], s_g * alvo_xy[1] + (1 - s_g) * orig_xy[1])


def _alvo(bola, velb, sent, i, dist):
    """Posicao colada ideal no quadro i: bola menos dist no sentido do movimento."""
    bx, by = bola[i][0], bola[i][1]
    vb = velb[i]
    sb = math.hypot(*vb)
    u_b = (vb[0] / sb, vb[1] / sb) if sb > 1e-9 else None
    u_j = sent[i]
    if u_b is None and u_j is None:
        return bx - dist, by
    if u_j is None:
        ux, uy = u_b
    elif u_b is None:
        ux, uy = u_j
    else:
        w = min(1.0, max(0.0, (sb - VEL_BOLA_LENTA) / (VEL_BOLA_RAPIDA - VEL_BOLA_LENTA)))
        mx = w * u_b[0] + (1 - w) * u_j[0]
        my = w * u_b[1] + (1 - w) * u_j[1]
        m = math.hypot(mx, my)
        ux, uy = (mx / m, my / m) if m > 1e-6 else u_b
    return bx - dist * ux, by - dist * uy


def _passo(anterior, alvo, passo_max):
    """Proximo ponto do seguidor: vai ate o alvo sem dar passo maior que passo_max."""
    dx, dy = alvo[0] - anterior[0], alvo[1] - anterior[1]
    d = math.hypot(dx, dy)
    if d > passo_max:
        dx, dy = dx * passo_max / d, dy * passo_max / d
    return (anterior[0] + dx, anterior[1] + dy)


def _colar_uma_vez(fps, bola, jogadores, segmentos, vmax=VMAX_MS, lim=None, vmax_bola=None):
    segmentos = [(s[0], s[1], s[2], s[3] if len(s) > 3 else None) for s in segmentos]
    n = len(bola)
    for pid, pts in jogadores.items():
        if len(pts) != n:
            raise ValueError(f"jogador {pid}: {len(pts)} quadros, bola tem {n}")
    lim = lim or {}
    corte = vmax if vmax_bola is None else vmax_bola
    velb = [_vel([(b[0], b[1]) for b in bola], i, fps) or (0.0, 0.0) for i in range(n)]
    velb_m = [math.hypot(*v) for v in velb]
    sentidos = {pid: _sentidos_jogador(pts, fps) for pid, pts in jogadores.items()}
    R = max(2, round(RAMPA_S * fps))
    passo_max = vmax / fps

    def alvo(pid, f):
        return _alvo(bola, velb, sentidos[pid], f, DIST_M)

    def seguir(pid, a, b):
        """Seguidor de a ate b: comeca no alvo de a e nao passa de vmax por quadro."""
        G = {a: alvo(pid, a)}
        for f in range(a + 1, b + 1):
            G[f] = _passo(G[f - 1], alvo(pid, f), passo_max)
        return G

    def rampa(salto):
        """Quadros de rampa: o padrao, ou mais se o salto para a posicao colada for grande demais."""
        if salto <= 0:
            return R
        return max(R, math.ceil(RAMPA_FATOR * salto * fps / vmax))

    # 1) dono por quadro. Bola mais rapida que vmax nao esta no pe: esses quadros saem da posse
    #    (bola em voo) e sao contados. O primeiro segmento que chega fica; o conflito e contado.
    dono = [None] * n
    dono_tipo = [None] * n
    conflitos = 0
    cortados = 0
    for pid, a, b, tipo in sorted(segmentos, key=lambda s: (s[1], s[2])):
        if pid not in jogadores:
            raise ValueError(f"segmento de jogador desconhecido: {pid}")
        for f in range(max(0, a), min(n - 1, b) + 1):
            if velb_m[f] > corte and tipo != "chute":  # chute: o jogador esta na bola no instante do chute
                cortados += 1
                continue
            if dono[f] is None:
                dono[f] = pid
                dono_tipo[f] = tipo
            elif dono[f] != pid:
                conflitos += 1
    runs = []
    for f in range(n):
        if dono[f] is None:
            continue
        if runs and runs[-1][0] == dono[f] and runs[-1][2] == f - 1:
            runs[-1][2] = f
        else:
            runs.append([dono[f], f, f, dono_tipo[f]])
    # Posse so comeca quando o jogador chega perto da posicao colada (senao a rampa nao alcanca).
    fora_do_alcance = 0
    corrigidas = []
    for pid, a, b, tipo in runs:
        if tipo in SEM_CORTE_PONTA:  # evento com bola: a rampa de entrada cuida da chegada, nao se corta
            corrigidas.append([pid, a, b, tipo])
            continue
        while a <= b and jogadores[pid][a] is not None and \
                math.dist(jogadores[pid][a], alvo(pid, a)) > DIST_ENTRADA:
            a += 1
            fora_do_alcance += 1
        if a <= b:
            corrigidas.append([pid, a, b, tipo])
    runs = [list(r) for r in corrigidas]

    # 2) rampas de cada posse. Mesmo jogador com duas posses cujas rampas nao cabem na folga entre
    #    elas: se a folga so tem bola lenta, a posse vira uma so (ele segue a bola por dentro da folga);
    #    se a folga tem bola em voo, as rampas dividem a folga e o atraso aparece como erro.
    def info(pid, a, b, tipo):
        G = seguir(pid, a, b)
        o_a = jogadores[pid][a] or alvo(pid, a)
        r_in = rampa(math.dist(o_a, alvo(pid, a)))  # so cresce se o jogador comeca longe da posicao colada
        o_b = jogadores[pid][b] or G[b]
        r_out = rampa(math.dist(o_b, G[b]))
        return {"pid": pid, "a": a, "b": b, "G": G, "r_in": r_in, "r_out": r_out, "tipo": tipo}

    seg_info = [info(pid, a, b, tipo) for pid, a, b, tipo in runs]
    k = 0
    while k < len(seg_info) - 1:
        x, y = seg_info[k], seg_info[k + 1]
        folga = y["a"] - x["b"] - 1
        lenta = all(velb_m[f] <= corte for f in range(x["b"] + 1, y["a"]))
        if x["pid"] == y["pid"] and lenta and x["r_out"] + y["r_in"] > folga:
            seg_info[k] = info(x["pid"], x["a"], y["b"], x["tipo"])
            del seg_info[k + 1]
            continue
        k += 1
    for k in range(len(seg_info) - 1):
        x, y = seg_info[k], seg_info[k + 1]
        if x["pid"] != y["pid"]:
            continue
        folga = y["a"] - x["b"] - 1
        if x["r_out"] + y["r_in"] > folga:
            total = max(1, x["r_out"] + y["r_in"])
            x["r_out"] = folga * x["r_out"] // total
            y["r_in"] = folga - x["r_out"]

    # 3) composicao: segmento (seguidor), rampa de entrada (original -> alvo) e de saida (seguidor -> original)
    novas = {pid: [list(p) if p is not None else None for p in pts] for pid, pts in jogadores.items()}
    segmento_xy, rampa_xy = {}, {}
    for s in seg_info:
        pid, a, b, G = s["pid"], s["a"], s["b"], s["G"]
        orig = jogadores[pid]
        r_in, r_out = s["r_in"], s["r_out"]
        lo, hi = max(0, a - r_in), min(n - 1, b + r_out)
        for f in range(b + 1, hi + 1):
            G[f] = _passo(G[f - 1], alvo(pid, f), passo_max)
        for f in range(a, b + 1):
            segmento_xy[(pid, f)] = G[f]
        for f in range(lo, a):
            s_g = _suave((f - (a - r_in - 1)) / (r_in + 1))
            rampa_xy.setdefault((pid, f), _mistura(orig[f], alvo(pid, f), s_g))
        for f in range(b + 1, hi + 1):
            s_g = 1.0 - _suave((f - b) / (r_out + 1))
            rampa_xy.setdefault((pid, f), _mistura(orig[f], G[f], s_g))

    for chave, xy in rampa_xy.items():
        if chave not in segmento_xy:
            novas[chave[0]][chave[1]] = _fixar(xy, lim.get(chave[0]))
    for chave, xy in segmento_xy.items():
        novas[chave[0]][chave[1]] = _fixar(xy, lim.get(chave[0]))

    # 4) limite de velocidade do caminho inteiro de cada jogador que mudou. A mistura das rampas
    #    pode somar velocidade; aqui cada passo e limitado (o jogador segue o caminho com atraso,
    #    que aparece como erro de colagem). Depois da ultima mudanca o atraso some sozinho.
    vel_jog = set()
    for pid in {s["pid"] for s in seg_info}:
        pts = novas[pid]
        mudados = sorted(f for (q, f) in list(segmento_xy) + list(rampa_xy) if q == pid)
        ultimo = mudados[-1]
        prev = pts[max(0, mudados[0] - 1)]
        fim = n - 1
        for f in range(mudados[0], n):
            if pts[f] is None or prev is None:
                prev = pts[f] if pts[f] is not None else prev
                continue
            if f > ultimo and prev == pts[f]:
                fim = f - 1
                break
            novo = _passo(prev, pts[f], passo_max)
            pts[f] = [round(novo[0], 4), round(novo[1], 4)]
            prev = novo
        for f in range(max(1, mudados[0]), fim + 1):  # so o caminho mexido; o resto e a coleta original
            if pts[f] is None or pts[f - 1] is None:
                continue
            v = math.dist(pts[f], pts[f - 1]) * fps
            if v > vmax + 0.05:  # folga para o arredondamento a 4 casas (~0,003 m/s)
                vel_jog.add((f, pid, round(v, 2)))

    runs_t = [(s["pid"], s["a"], s["b"]) for s in seg_info]
    ancorados = {(s["pid"], s["a"], s["b"]) for s in seg_info if s["tipo"] in ANCORADOS}
    return novas, {
        "runs": runs_t,
        "ancorados": ancorados,
        "tipos": {(s["pid"], s["a"], s["b"]): s["tipo"] for s in seg_info},
        "quadros_colados": sum(b - a + 1 for _, a, b in runs_t),
        "cortados_bola_rapida": cortados,
        "conflitos": conflitos,
        "fora_do_alcance": fora_do_alcance,
        "vel_jogador": sorted(((pid, f, v) for f, pid, v in vel_jog), key=lambda t: (t[1], str(t[0]))),
    }


def colar(fps, bola, jogadores, segmentos, vmax=VMAX_MS, lim=None, vmax_bola=None):
    """Colagem completa. Depois de colar, a ponta de cada posse que ainda esta a mais de DIST_PONTA da
    bola sai da posse (o jogador ainda nao chegou ou ja saiu) e a colagem e refeita. Os quadros
    retirados entram em fora_do_alcance; o miolo da posse nao e mexido. Novas e relatorio sempre
    correspondem aos mesmos segmentos."""
    novas, rel = _colar_uma_vez(fps, bola, jogadores, segmentos, vmax=vmax, lim=lim, vmax_bola=vmax_bola)
    quadros_inicio = rel["quadros_colados"]
    fora_inicio = rel["fora_do_alcance"]
    for _ in range(8):
        ajustados, mudou = [], False
        for pid, a, b in rel["runs"]:
            tipo = rel["tipos"][(pid, a, b)]
            if tipo in SEM_CORTE_PONTA:  # ancorada/recebimento: o fim e o proprio evento; nao se corta
                ajustados.append((pid, a, b, tipo))
                continue
            pts = novas[pid]
            while a <= b and pts[a] is not None and math.dist(pts[a], bola[a][:2]) > DIST_PONTA:
                a += 1
                mudou = True
            while b >= a and pts[b] is not None and math.dist(pts[b], bola[b][:2]) > DIST_PONTA:
                b -= 1
                mudou = True
            if a <= b:
                ajustados.append((pid, a, b, tipo))
        if not mudou:
            break
        novas, rel = _colar_uma_vez(fps, bola, jogadores, ajustados, vmax=vmax, lim=lim, vmax_bola=vmax_bola)
    rel["fora_do_alcance"] = fora_inicio + (quadros_inicio - rel["quadros_colados"])
    return novas, rel


def _fixar(xy, limite):
    """Arredonda para 4 casas e prende aos limites do campo, se houver."""
    if limite is not None:
        lx, ly = limite
        xy = (min(max(xy[0], -lx), lx), min(max(xy[1], -ly), ly))
    return [round(xy[0], 4), round(xy[1], 4)]
