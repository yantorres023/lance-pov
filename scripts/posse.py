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
- Mesmo jogador com duas posses separadas por folga de ate 0,3 s, ou com o jogador junto da bola durante
  toda a folga (dados originais): vira uma posse so. Bola lenta sozinha nao junta posses.
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
        # So junta quando ha continuidade real: folga de ate 0,3 s, ou o jogador ja estava junto da bola
        # durante toda a folga nos dados originais (<= 1,5 m). Bola lenta sozinha nao basta (passe solto).
        if folga <= round(0.3 * fps):
            junta = True
        else:
            junta = all(jogadores[x["pid"]][f] is not None and bola[f] is not None
                        and math.dist(jogadores[x["pid"]][f], bola[f][:2]) <= 1.5
                        for f in range(x["b"] + 1, y["a"]))
        if x["pid"] == y["pid"] and junta and x["r_out"] + y["r_in"] > folga:
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


# ---------------------------------------------------------------- posse original e correcao da bola
CONTATO_M = 1.5           # m: jogador a esta distancia da bola (dados originais) conta como toque
SAIDA_VEL = 10.3          # m/s: bola acima disso saiu do pe (fora da posse)
PARADA_VEL = 0.3          # m/s: bola com velocidade original abaixo disso esta parada (preparacao de cobranca):
                          # nao abre posse e nunca e movida
LAG_M = 0.9               # m: dono a mais disso da bola, dentro da posse, esta atrasado (a bola vai ao pe)
PE_M = 0.45               # m: pe do dono, a frente, na direcao do movimento
ENTRADA_S = 0.5           # s: chegada do dono ao inicio da posse (quadros sem correcao, evidencia no dado original)
VMAX_BOLA = 10.3          # m/s: a correcao nao cria velocidade da bola acima disso onde a original estava abaixo
LINHA_GOL_X = 52.5        # m: bola alem da linha de gol: a partir dali nada abre posse e a bola nao muda


def _vel_bola(bola, i, fps):
    n = len(bola)
    a, b = max(0, i - 1), min(n - 1, i + 1)
    if a == b:
        return 0.0
    return math.dist(bola[b][:2], bola[a][:2]) * fps / (b - a)


def _vel_quadros(bola, f, fps):
    """Velocidade consecutiva (quadro f-1 para f), a mesma que o visualizador interpola."""
    if f <= 0 or f >= len(bola):
        return 0.0
    return math.dist(bola[f][:2], bola[f - 1][:2]) * fps


def congelamento(bola):
    """Quadro a partir do qual nada e tocado: dois quadros antes do primeiro quadro com a bola alem da linha de gol
    (assim o par de quadros que define o cruzamento fica igual ao original). Sem cruzamento: len(bola)."""
    for f in range(len(bola)):
        if abs(bola[f][0]) > LINHA_GOL_X:
            return max(0, f - 2)
    return len(bola)


def segmentos_originais(fps, bola, jogadores, z_max=None, candidatos=None, inicio=0, tomadas=None, times=None):
    """Posse ORIGINAL, antes de qualquer correcao: lista de (pid, ini, fim, tipo), extremos inclusivos.

    Sem candidatos (Last-Row, roteiros): a posse abre no primeiro quadro, a partir de `inicio`, em que um jogador
    esta a ate CONTATO_M da bola, a bola se move (velocidade original >= PARADA_VEL) e nao esta no ar.
    Termina quando a bola sai do pe: (a) bola acima de SAIDA_VEL (ou no ar, z > z_max); o ultimo quadro e o
    anterior a saida; (b) outro jogador toca a bola: o fim e o ultimo quadro do dono a ate CONTATO_M antes do toque.
    Com candidatos (StatsBomb): o inicio e o do candidato (evento: conducao, passe, drible, chute, recebimento);
    o fim e a saida da bola ou um EVENTO EFETIVO de adversario em `tomadas` ([(quadro, time)], com `times` pid->time).
    Proximidade de jogador nunca encerra posse de evento (posicao estimada nao comprova toque).
    Quadros a partir de congelamento(bola) nao abrem nem continuam posse. Chute nao sofre corte de velocidade."""
    n = len(bola)
    sb = [_vel_bola(bola, i, fps) for i in range(n)]
    cong = congelamento(bola)

    def no_pe(f):
        return sb[f] <= SAIDA_VEL and (z_max is None or bola[f][2] <= z_max)

    def parada(f):
        return sb[f] < PARADA_VEL

    def contato(pid, f):
        p = jogadores[pid][f]
        return p is not None and math.dist(p, bola[f][:2]) <= CONTATO_M

    def mais_perto(cands, f):
        return min(cands, key=lambda p: math.dist(jogadores[p][f], bola[f][:2]))

    out = []
    if candidatos is None:
        dono, a, ult = None, None, None

        def fecha(fim):
            nonlocal dono
            if dono is not None and fim is not None and fim >= a:
                out.append((dono, a, fim, "toque"))
            dono = None

        for f in range(n):
            if f >= cong:
                break
            if dono is None:
                if f >= inicio and no_pe(f) and not parada(f):
                    cs = [p for p in jogadores if contato(p, f)]
                    if cs:
                        dono, a, ult = mais_perto(cs, f), f, f
                continue
            if not no_pe(f):
                fecha(f - 1)
                continue
            if contato(dono, f):
                ult = f
                continue
            outros = [p for p in jogadores if p != dono and contato(p, f) and f >= inicio]
            if outros and not parada(f):
                fecha(ult)
                dono, a, ult = mais_perto(outros, f), f, f
        fecha(min(n - 1, cong - 1))
        return out

    for pid, a, b, tipo in sorted(candidatos, key=lambda s: (s[1], s[2])):
        b = min(b, cong - 1)
        ini = max(a, inicio)
        while ini <= b and not no_pe(ini):
            ini += 1
        if ini > b:
            continue
        fim = b
        for f in range(ini, b + 1):
            if not no_pe(f):
                fim = f - 1
                break
            if tomadas and times and any(fr == f and tm != times.get(pid) for fr, tm in tomadas):
                fim = f - 1
                break
        if fim >= ini:
            out.append((pid, ini, fim, tipo))
    return out


def _direcao_pe(pts, bola, fps, f):
    """Sentido para onde fica o pe do dono no quadro f: o movimento dele; se ele esta quase parado, o movimento
    da bola (que ele conduz). Se esse sentido aponta para longe da bola (dono andando de costas para ela), usa
    a direcao do dono para a bola: o pe nunca fica do outro lado da bola. Sem nada disso, (1, 0)."""
    to_bola = None
    if pts[f] is not None:
        dx, dy = bola[f][0] - pts[f][0], bola[f][1] - pts[f][1]
        if math.hypot(dx, dy) > 0.2:
            m = math.hypot(dx, dy)
            to_bola = (dx / m, dy / m)
    u = None
    v = _vel(pts, f, fps)
    if v is not None and math.hypot(*v) >= VEL_JOG_MIN:
        m = math.hypot(*v)
        u = (v[0] / m, v[1] / m)
    if u is None:
        n = len(bola)
        a, b = max(0, f - 1), min(n - 1, f + 1)
        if b > a:
            vx = (bola[b][0] - bola[a][0]) * fps / (b - a)
            vy = (bola[b][1] - bola[a][1]) * fps / (b - a)
            if math.hypot(vx, vy) >= 1.0:
                m = math.hypot(vx, vy)
                u = (vx / m, vy / m)
    if u is None:
        u = to_bola or (1.0, 0.0)
    if to_bola is not None and u[0] * to_bola[0] + u[1] * to_bola[1] < 0.7:
        u = to_bola
    return u


def _pe_xy(jogadores, sent, pid, f, b, lim=None):
    """Ponto do pe do dono no quadro f (f > b: mantem o ultimo quadro da posse); None se faltar dado.
    sent: {pid: funcao(f) -> sentido}. lim (lx, ly): o ponto fica dentro do retangulo."""
    g = min(f, b)
    p = jogadores[pid][g]
    if p is None:
        return None
    u = sent[pid](g)
    x, y = p[0] + PE_M * u[0], p[1] + PE_M * u[1]
    if lim is not None:
        x, y = min(max(x, -lim[0]), lim[0]), min(max(y, -lim[1]), lim[1])
    return (x, y)


def bola_no_pe(fps, bola, jogadores, segmentos, lim=None, inicio=0):
    """Correcao da bola (Last-Row e roteiros). Dentro de cada posse, nos quadros em que o dono esta atrasado
    (a mais de LAG_M da bola), a bola vai ao pe dele: PE_M a frente, no sentido do movimento. Regras:
    - so se move bola em movimento (velocidade original entre PARADA_VEL e SAIDA_VEL), a partir de `inicio`
      e antes de congelamento(bola) (depois da linha de gol). Bola parada (preparacao de cobranca) nunca e movida;
    - a rampa entra e sai da posse por quadros em movimento, no maximo ENTRADA_S antes do contato e ENTRADA_S
      depois; a rampa cresce ate a velocidade caber: a correcao nao cria velocidade acima de
      max(VMAX_BOLA, velocidade original). Onde nao cabe, o trecho encolhe;
    - o que sobra acima de LAG_M fica como excecao por quadro (evidencia: distancia do dado original);
    - os jogadores nao mudam.
    lim (lx, ly): o pe-alvo fica dentro desse retangulo. Devolve (bola_nova [[x, y, z], ...], relatorio)."""
    n = len(bola)
    original = [[float(b[0]), float(b[1]), float(b[2])] for b in bola]
    nova = [list(b) for b in original]
    sent = {pid: (lambda g, pts=pts: _direcao_pe(pts, bola, fps, g)) for pid, pts in jogadores.items()}
    cong = congelamento(bola)
    a_min = min((a for _, a, _, _ in segmentos), default=n)
    inicio_ok = max(inicio, 0)
    rampa_max = max(2, round(ENTRADA_S * fps))

    def movendo(f):
        return inicio_ok <= f < cong and PARADA_VEL <= _vel_bola(bola, f, fps) <= SAIDA_VEL

    rel = {"segmentos_com_correcao": 0, "vel_excedida": 0, "atrasos_restantes": 0, "congelado_a_partir": cong,
           "entrada_nao_corrigida": 0, "saida_nao_corrigida": 0, "recusados": []}

    # Peso da correcao e alvo do pe por quadro. Cada quadro e calculado UMA vez, a partir do original:
    # a bola = original + W * (alvo - original), com W o maior peso entre os trechos que o afetam.
    W = [0.0] * n
    T = [None] * n

    def posicao(f, w, t):
        ox, oy = original[f][0], original[f][1]
        return (ox + w * (t[0] - ox), oy + w * (t[1] - oy))

    def viola(tmp, lo, hi):
        for g in range(max(1, lo), min(n - 1, hi + 1) + 1):
            if _vel_quadros(tmp, g, fps) > max(VMAX_BOLA, _vel_quadros(original, g, fps)) + 1e-6:
                return g
        return None

    ordem = sorted(segmentos, key=lambda s: (s[1], s[2]))
    for k, (pid, a, b, tipo) in enumerate(ordem):
        pts = jogadores[pid]
        # rampa so em quadros livres: entre o fim da posse anterior e o inicio da seguinte (nao cruza outro dono)
        livre_ini = ordem[k - 1][2] + 1 if k > 0 else 0
        livre_fim = ordem[k + 1][1] - 1 if k + 1 < len(ordem) else n - 1
        lag = [f for f in range(a, b + 1)
               if movendo(f) and pts[f] is not None and math.dist(pts[f], nova[f][:2]) > LAG_M]
        grupos = []
        for f in lag:
            if grupos and f == grupos[-1][1] + 1:
                grupos[-1][1] = f
            else:
                grupos.append([f, f])
        if grupos:
            rel["segmentos_com_correcao"] += 1
        for s, e in grupos:
            feito = False
            while s <= e and not feito:
                alvo_s = _pe_xy(jogadores, sent, pid, s, b, lim)
                alvo_e = _pe_xy(jogadores, sent, pid, e, b, lim)
                if alvo_s is None or alvo_e is None:
                    break
                J = math.dist(nova[s][:2], alvo_s)
                J2 = math.dist(alvo_e, nova[e + 1][:2]) if e + 1 < n else 0.0
                disp_pre = 0  # quadros em movimento, livres, antes e depois do trecho
                while disp_pre < rampa_max and s - disp_pre - 1 >= livre_ini and movendo(s - disp_pre - 1):
                    disp_pre += 1
                disp_pos = 0
                while disp_pos < rampa_max and e + disp_pos + 1 <= livre_fim and movendo(e + disp_pos + 1):
                    disp_pos += 1
                fator = 1.0
                ok = False
                for _ in range(6):
                    kp = min(math.ceil(J * fps / VMAX_BOLA * fator) if J > 1e-9 else 0, disp_pre)
                    kq = min(math.ceil(J2 * fps / VMAX_BOLA * fator) if J2 > 1e-9 else 0, disp_pos)
                    lo, hi = s - kp, e + kq
                    W2, T2 = list(W), list(T)
                    for f in range(lo, hi + 1):
                        if not (movendo(f) or s <= f <= e):
                            continue
                        if s <= f <= e:
                            w = 1.0
                        elif f < s:
                            w = (f - lo + 1) / (kp + 1)
                        else:
                            w = 1.0 - (f - e) / (kq + 1)
                        alvo = _pe_xy(jogadores, sent, pid, f, b, lim)
                        if alvo is None:
                            continue
                        if w > W2[f]:
                            W2[f], T2[f] = w, alvo
                    tmp = [list(x) for x in nova]
                    for f in range(lo, hi + 1):
                        if T2[f] is not None and W2[f] > 0:
                            tmp[f][0], tmp[f][1] = posicao(f, W2[f], T2[f])
                    if viola(tmp, lo, hi) is None:
                        ok = True
                        break
                    fator *= 1.5
                if ok:
                    W, T, nova = W2, T2, tmp
                    feito = True
                elif s < e:
                    e -= 1  # encolhe o trecho corrigido pela saida: o resto vira excecao por quadro
                else:
                    s += 1
            if not feito:
                rel["vel_excedida"] += 1
        for f in range(a, b + 1):
            if pts[f] is not None and math.dist(pts[f], nova[f][:2]) > LAG_M:
                rel["atrasos_restantes"] += 1
                if f < a + max(1, round(ENTRADA_S * fps)):
                    rel["entrada_nao_corrigida"] += 1
                elif f > b - max(1, round(ENTRADA_S * fps)):
                    rel["saida_nao_corrigida"] += 1
                # motivo registrado pelo gerador (conferido pelo teste contra o dado original)
                if _vel_bola(bola, f, fps) < PARADA_VEL:
                    rel["recusados"].append((pid, f, "parada"))
                elif movendo(f):
                    rel["recusados"].append((pid, f, "limite_velocidade"))
                else:
                    rel["recusados"].append((pid, f, "outra"))

    movidos = [f for f in range(n) if math.dist(nova[f][:2], original[f][:2]) > 1e-9]
    rel["quadros_movidos"] = len(movidos)
    rel["deslocamento_max"] = round(max((math.dist(nova[f][:2], original[f][:2]) for f in movidos), default=0.0), 3)
    rel["vel_max"] = round(max((_vel_quadros(nova, g, fps) for g in range(1, n)), default=0.0), 2)
    return [[round(x, 3), round(y, 3), round(z, 3)] for x, y, z in nova], rel
