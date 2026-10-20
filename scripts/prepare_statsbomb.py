"""Gera web/data/hypados.json: 30 gols "hypados" reconstruidos a partir do StatsBomb Open Data.

Uso (a partir da raiz do projeto):
    python3 -I scripts/prepare_statsbomb.py

Baixa so de raw.githubusercontent.com/statsbomb/open-data (matches, events, lineups e
three-sixty) para data/raw/statsbomb/ e reaproveita o cache quando ele ja existe.
Biblioteca padrao apenas. Os JSONs baixados sao dados nao confiaveis: sao lidos com
json.load e nunca executados.

Formato de saida: o mesmo de web/data/lances.json (ver docstring de prepare_lastrow.py),
mais: ordem (1..30), grupo ("hypados"), subtitulo, finalizadorId (id do jogador que marcou),
frameChute (indice do quadro do chute), partida e qualidade. Por jogador: estimado.

Coordenadas: metros, origem no centro do campo, 105 x 68, o time que marcou ataca para +x,
+y a esquerda de quem ataca para +x, z para cima. O StatsBomb usa jardas (120 x 80), com
eventos orientados pelo time que executa a acao; eventos do outro time sao espelhados
(x -> 120 - x, y -> 80 - y) antes da conversao.

Reconstrucao (resumo): janela de ate 16 s antes do chute (limitada ao inicio da posse) mais
2,5 s depois; bola por keyframes de passe/conducao/chute; jogadores por keyframes reais
(eventos, freeze frame e 360 associado por vizinho mais proximo); interpolacao de Hermite a
20 fps; limite de 10,5 m/s; jogadores com um ponto real alem do chute recebem movimento
sintetizado (estimado: true) que acompanha a bola.
"""

import bisect
import json
import math
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "raw" / "statsbomb"
SAIDA = RAIZ / "web" / "data" / "hypados.json"
LANCES_LASTROW = RAIZ / "web" / "data" / "lances.json"
BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data/"

FPS = 20
JANELA_DEPOIS = 2.5  # s depois do chute
JANELA_PADRAO = 16.0  # s antes do chute (limitada ao inicio da posse)
JANELA_MINIMA = 4.0  # s antes do chute quando a posse comeca em cima da hora (bola parada)
YARD = 0.9144
LINHA_GOL = 52.5  # metros, meia largura do campo em x
VMAX_JOG = 10.5  # m/s
VMAX_BOLA_SEG = 35.0  # m/s: teto usado para dimensionar segmentos da bola (verificacao: 45)
K_OFF = (0.35, 0.2)  # fracao do movimento da bola copiada por jogador estimado
MOV_SINTETICO_ANTES = 4.0  # s antes do primeiro ponto real em que o movimento estimado comeca
TAU = 0.5  # s, desaceleracao depois do ultimo ponto real
VMAX_CHAVE = 9.0  # m/s: pontos reais consecutivos mais rapidos que isso sao descartados (dados inconsistentes)
VMAX_LIMITE = 10.3  # m/s: alvo do limitador (margem para o arredondamento a 3 casas)
CAMPO_LIM_X = 55.5  # m: jogadores ficam ate 3 m fora das linhas de fundo
CAMPO_LIM_Y = 37.0  # m: e 3 m fora das laterais
GOLEIRO_LIM_X = 54.5  # m: goleiro pode ir ate a rede (dentro do gol)
PRIO = {"chute": -1, "ev": 0, "ff": 1, "360": 2}  # menor = mais prioritario na juncao de pontos proximos


# ---------------------------------------------------------------------------
# Especificacao dos 30 itens (+ reservas). Filtros de gol: autor (substring sem acento),
# minuto (minuto do relogio), n (n-esimo gol do autor na partida), time, tecnica.
# ---------------------------------------------------------------------------

ITENS = [
    dict(titulo="Maradona — Gol do Século", comp=(43, 54), times=("Argentina", "England"), autor="Maradona", minuto=54, janela=22, time="Argentina",
         contexto="Maradona recebe perto do meio-campo, dribla quatro ingleses e marca de esquerda aos 54', o segundo gol da Argentina."),
    dict(titulo="Maradona — Mão de Deus", comp=(43, 54), times=("Argentina", "England"), autor="Maradona", minuto=50, time="Argentina",
         contexto="Gol de mão de Maradona aos 50', o primeiro da Argentina nas quartas da Copa de 1986."),
    dict(titulo="Carlos Alberto — o 4º gol", comp=(43, 272), times=("Brazil", "Italy"), autor="Carlos Alberto", minuto=86, time="Brazil",
         contexto="Carlos Alberto fecha o 4 × 1 do Brasil sobre a Itália na final da Copa de 1970, aos 86'."),
    dict(titulo="Pelé — o gol do chapéu", comp=(43, 269), times=("Brazil", "Sweden"), autor="Edson Arantes", minuto=54, n=1, time="Brazil",
         contexto="Pelé marca o primeiro gol dele na final da Copa de 1958, aos 54' (Brasil 5 × 2 Suécia)."),
    dict(titulo="Sergio Ramos — 92:48", comp=(16, 25), times=("Real Madrid", "Atlético Madrid"), autor="Ramos", minuto=92, time="Real Madrid",
         contexto="Cabeçada de Ramos aos 92' empata a final em 1 × 1; o Real vence por 4 × 1 na prorrogação."),
    dict(titulo="Bale — bicicleta", comp=(16, 1), times=("Real Madrid", "Liverpool"), autor="Bale", minuto=63, n=1, time="Real Madrid",
         contexto="Bale marca de bicicleta aos 63' e coloca o Real na frente por 2 × 1; o Real vence a final de 2018 por 3 × 1."),
    dict(titulo="Drogba — cabeçada aos 88'", comp=(16, 23), times=("Bayern Munich", "Chelsea"), autor="Drogba", minuto=87, time="Chelsea",
         contexto="Drogba empata a final de 2012 com uma cabeçada aos 88' (1 × 1); o Chelsea vence nos pênaltis."),
    dict(titulo="Mandžukić — voleio de costas", comp=(16, 2), times=("Juventus", "Real Madrid"), autor="Mandžukić", minuto=26, time="Juventus",
         contexto="Mandžukić empata a final de 2017 com voleio de costas aos 26' (1 × 1); o Real vence por 4 × 1."),
    dict(titulo="Messi — de fora da área", comp=(16, 22), times=("Barcelona", "Manchester United"), autor="Messi", minuto=53, time="Barcelona",
         contexto="Messi chuta de fora da área aos 53' e faz o 2 × 1 na final de 2011, que o Barcelona vence por 3 × 1."),
    dict(titulo="Gerrard — cabeçada", comp=(16, 37), times=("AC Milan", "Liverpool"), autor="Gerrard", minuto=53, time="Liverpool",
         contexto="Cabeçada de Gerrard aos 53' reduz para 1 × 3; o Liverpool chega a 3 × 3 em seguida e vence nos pênaltis."),
    dict(titulo="Ronaldinho — no Bernabéu", comp=(11, 38), times=("Real Madrid", "Barcelona"), autor="Ronaldo de Assis", n=2, time="Barcelona",
         contexto="Segundo gol de Ronaldinho no Bernabéu, aos 77', fecha o 3 × 0 do Barcelona sobre o Real Madrid em novembro de 2005."),
    dict(titulo="Messi — 92' no Bernabéu", comp=(11, 2), times=("Real Madrid", "Barcelona"), autor="Messi", minuto=91, time="Barcelona", data="2017-04",
         contexto="Messi marca aos 92' e fecha a virada do Barcelona no Bernabéu: Real Madrid 2 × 3 Barcelona, em abril de 2017."),
    dict(titulo="Suárez — rebote do pênalti de Messi", comp=(11, 27), times=("Barcelona", "Celta Vigo"), autor="Suárez", minuto=81, time="Barcelona", data="2016-02",
         contexto="Messi perde um pênalti aos 80'; Suárez completa aos 81' e amplia para 4 × 1 do Barcelona sobre o Celta, em fevereiro de 2016."),
    dict(titulo="Henry — contra o Liverpool", comp=(2, 44), times=("Arsenal", "Liverpool"), autor="Henry", n=2, time="Arsenal", data="2004-04",
         contexto="Segundo gol de Henry na vitória do Arsenal por 4 × 2 sobre o Liverpool, em abril de 2004; aos 49' ele faz o 3 × 2."),
    dict(titulo="Vardy — voleio", comp=(2, 27), times=("Leicester City", "Liverpool"), autor="Vardy", minuto=59, n=1, time="Leicester City", data="2016-02",
         contexto="Vardy abre o placar com voleio aos 59' (Leicester 2 × 0 Liverpool, em fevereiro de 2016)."),
    # 16: Bayern x Wolfsburg nao existe no Open Data (Bundesliga 2015/16 traz 34 partidas); cai na reserva 1.
    dict(titulo="Lewandowski — 5 gols em 9 minutos", comp=(9, 27), times=("Bayern Munich", "Wolfsburg"), autor="Lewandowski", n=5, time="Bayern Munich",
         contexto="Lewandowski, de voleio, marca o quinto gol da sequência de 9 minutos contra o Wolfsburg."),
    dict(titulo="Pavard — voleio", comp=(43, 3), times=("France", "Argentina"), autor="Pavard", minuto=56, time="France",
         contexto="Pavard, de voleio aos 56', empata em 2 × 2 com a Argentina nas oitavas da Copa de 2018 (França 4 × 3)."),
    dict(titulo="Cristiano Ronaldo — falta no fim", comp=(43, 3), times=("Portugal", "Spain"), autor="Cristiano Ronaldo", minuto=87, time="Portugal",
         contexto="Falta de Cristiano Ronaldo aos 87' empata em 3 × 3 contra a Espanha na fase de grupos da Copa de 2018."),
    dict(titulo="Kroos — gol aos 94'", comp=(43, 3), times=("Germany", "Sweden"), autor="Kroos", minuto=94, time="Germany",
         contexto="Kroos marca aos 94' e a Alemanha vence a Suécia por 2 × 1 na fase de grupos da Copa de 2018."),
    dict(titulo="Chadli — contra-ataque", comp=(43, 3), times=("Belgium", "Japan"), autor="Chadli", minuto=93, time="Belgium",
         contexto="Chadli marca aos 93' e a Bélgica vira para 3 × 2 sobre o Japão nas oitavas da Copa de 2018."),
    dict(titulo="Richarlison — voleio de bicicleta", comp=(43, 106), times=("Brazil", "Serbia"), autor="Richarlison", n=2, time="Brazil",
         contexto="Segundo gol de Richarlison, aos 73', na vitória do Brasil por 2 × 0 sobre a Sérvia na Copa de 2022."),
    dict(titulo="Messi — contra o México", comp=(43, 106), times=("Argentina", "Mexico"), autor="Messi", minuto=63, time="Argentina",
         contexto="Messi abre o placar aos 63' na vitória da Argentina por 2 × 0 sobre o México na fase de grupos da Copa de 2022."),
    dict(titulo="Molina — passe de Messi", comp=(43, 106), times=("Netherlands", "Argentina"), autor="Molina", n=1, time="Argentina",
         contexto="Molina abre o placar aos 34' com passe de Messi nas quartas contra a Holanda (2 × 2 no fim)."),
    dict(titulo="Neymar — prorrogação", comp=(43, 106), times=("Croatia", "Brazil"), autor="Neymar", minuto=105, time="Brazil",
         contexto="Neymar abre o placar aos 105' da prorrogação contra a Croácia, nas quartas da Copa de 2022 (1 × 1 no fim)."),
    dict(titulo="Di María — final", comp=(43, 106), times=("Argentina", "France"), autor="Di María", minuto=35, time="Argentina",
         contexto="Di María marca aos 35' e faz o 2 × 0 na final da Copa de 2022, que terminou 3 × 3."),
    dict(titulo="Mbappé — voleio (2×2)", comp=(43, 106), times=("Argentina", "France"), autor="Mbappé", tecnica="Volley", time="France",
         contexto="Mbappé empata a final de 2022 com voleio aos 80' (2 × 2 contra a Argentina)."),
    dict(titulo="Schick — do meio-campo", comp=(55, 43), times=("Scotland", "Czech Republic"), autor="Schick", n=2, time="Czech Republic",
         contexto="Schick marca do meio-campo aos 51' e faz o 2 × 0 contra a Escócia na Eurocopa de 2020."),
    dict(titulo="Lamine Yamal — Euro 2024", comp=(55, 282), times=("Spain", "France"), autor="Lamine Yamal", minuto=20, time="Spain",
         contexto="Lamine Yamal empata aos 20' (1 × 1) na semifinal contra a França; a Espanha vence por 2 × 1."),
    dict(titulo="Bellingham — bicicleta", comp=(55, 282), times=("England", "Slovakia"), autor="Bellingham", minuto=94, time="England",
         contexto="Bellingham, de bicicleta aos 94', faz o 2 × 1 da Inglaterra sobre a Eslováquia nas oitavas da Eurocopa de 2024."),
]

# Origi (30) nao e StatsBomb: copiado de web/data/lances.json.

RESERVAS = [
    dict(titulo="Maradona — contra o River (1981)", comp=(81, 275), times=("Boca Juniors", "River Plate"), autor="Maradona", minuto=67, time="Boca Juniors",
         contexto="Maradona marca aos 67' pelo Boca Juniors na vitória por 3 × 0 sobre o River Plate, em abril de 1981."),
    dict(titulo="Messi — cavadinha no Betis", comp=(11, 4), times=("Real Betis", "Barcelona"), autor="Messi", minuto=84, time="Barcelona", data="2019-03",
         contexto="Messi marca de cavadinha aos 84' na vitória do Barcelona por 4 × 1 sobre o Betis, em março de 2019."),
    dict(titulo="Al-Dawsari — contra a Argentina", comp=(43, 106), times=("Argentina", "Saudi Arabia"), autor="Dawsari", minuto=52, time="Saudi Arabia",
         contexto="Al-Dawsari marca aos 52' e a Arábia Saudita vira sobre a Argentina por 2 × 1 na fase de grupos da Copa de 2022."),
    dict(titulo="Oyarzabal — final da Euro 2024", comp=(55, 282), times=("Spain", "England"), autor="Oyarzabal", minuto=85, time="Spain",
         contexto="Oyarzabal marca aos 85' na final da Eurocopa de 2024; a Espanha vence a Inglaterra por 2 × 1."),
    dict(titulo="Arda Güler — contra a Geórgia", comp=(55, 282), times=("Turkey", "Georgia"), autor="Arda Güler", minuto=64, time="Turkey",
         contexto="Arda Güler marca aos 64' e a Turquia vence a Geórgia por 3 × 1 na fase de grupos da Eurocopa de 2024."),
    dict(titulo="Messi — cabeçada na final de 2009", comp=(16, 41), times=("Barcelona", "Manchester United"), autor="Messi", minuto=69, time="Barcelona",
         contexto="Messi cabeceia aos 69' e faz o 2 × 0 do Barcelona sobre o Manchester United na final da Liga dos Campeões de 2009."),
    dict(titulo="Pogba — contra a Suíça", comp=(55, 43), times=("France", "Switzerland"), autor="Pogba", minuto=74, time="France",
         contexto="Pogba marca aos 74' contra a Suíça nas oitavas da Eurocopa de 2020 (3 × 3 no tempo normal)."),
    dict(titulo="Mbappé — 2º gol contra a Argentina", comp=(43, 3), times=("France", "Argentina"), autor="Mbappé", n=2, time="France",
         contexto="Segundo gol de Mbappé, aos 67', na vitória da França por 4 × 3 sobre a Argentina nas oitavas da Copa de 2018."),
    dict(titulo="Enzo Fernández — contra o México", comp=(43, 106), times=("Argentina", "Mexico"), autor="Enzo", minuto=86, time="Argentina",
         contexto="Enzo Fernández marca aos 86' e fecha o 2 × 0 da Argentina sobre o México na Copa de 2022."),
]

CORES = {  # nome StatsBomb: (cor principal, borda, cor alternativa usada quando o adversario fica parecido)
    "Argentina": ("#75AADB", "#FFFFFF", "#1B1B1B"),
    "England": ("#FFFFFF", "#C8102E", "#1D428A"),
    "Brazil": ("#FFDF00", "#009C3B", "#1E40AF"),
    "Italy": ("#1E4FA0", "#FFFFFF", "#FFFFFF"),
    "Sweden": ("#FECB00", "#005293", "#005293"),
    "Real Madrid": ("#FFFFFF", "#1D4E89", "#1B2E6B"),
    "Atlético Madrid": ("#CB3524", "#FFFFFF", "#1D3E8C"),
    "Liverpool": ("#C8102E", "#FFFFFF", "#FFFFFF"),
    "Bayern Munich": ("#DC052D", "#FFFFFF", "#FFFFFF"),
    "Chelsea": ("#034694", "#FFFFFF", "#FFFFFF"),
    "Juventus": ("#111111", "#FFFFFF", "#FFFFFF"),
    "Barcelona": ("#004D98", "#A50044", "#FFFFFF"),
    "Manchester United": ("#DA291C", "#FBE122", "#FFFFFF"),
    "AC Milan": ("#FB090B", "#111111", "#FFFFFF"),
    "Arsenal": ("#EF0107", "#FFFFFF", "#000000"),
    "Leicester City": ("#003090", "#FDBE11", "#FDBE11"),
    "Portugal": ("#D7141A", "#006600", "#006600"),
    "Spain": ("#C60B1E", "#FFC400", "#1F3A8A"),
    "Germany": ("#FFFFFF", "#000000", "#000000"),
    "Belgium": ("#ED2939", "#FFD200", "#000000"),
    "Japan": ("#002E6D", "#FFFFFF", "#FFFFFF"),
    "France": ("#002395", "#FFFFFF", "#FFFFFF"),
    "Croatia": ("#D52B1E", "#FFFFFF", "#FFFFFF"),
    "Netherlands": ("#FF6600", "#FFFFFF", "#1F3A8A"),
    "Mexico": ("#006847", "#CE1126", "#FFFFFF"),
    "Serbia": ("#C6363C", "#FFFFFF", "#0C4076"),
    "Scotland": ("#003078", "#FFFFFF", "#FFFFFF"),
    "Czech Republic": ("#D7141A", "#FFFFFF", "#FFFFFF"),
    "Slovakia": ("#0B4EA2", "#FFFFFF", "#FFFFFF"),
    "Switzerland": ("#D52B1E", "#FFFFFF", "#FFFFFF"),
    "Turkey": ("#E30A17", "#FFFFFF", "#FFFFFF"),
    "Georgia": ("#FFFFFF", "#E30A17", "#E30A17"),
    "Saudi Arabia": ("#006C35", "#FFFFFF", "#FFFFFF"),
    "Boca Juniors": ("#1F3F8B", "#FFD200", "#FFD200"),
    "River Plate": ("#FFFFFF", "#E00020", "#E00020"),
    "Celta Vigo": ("#7FB6E6", "#FFFFFF", "#FFFFFF"),
    "Real Betis": ("#00A859", "#FFFFFF", "#FFFFFF"),
}

NOMES_PT = {
    "Argentina": "Argentina", "England": "Inglaterra", "Brazil": "Brasil", "Italy": "Itália",
    "Sweden": "Suécia", "Real Madrid": "Real Madrid", "Atlético Madrid": "Atlético de Madrid",
    "Liverpool": "Liverpool", "Bayern Munich": "Bayern de Munique", "Chelsea": "Chelsea",
    "Juventus": "Juventus", "Barcelona": "Barcelona", "Manchester United": "Manchester United",
    "AC Milan": "Milan", "Arsenal": "Arsenal", "Leicester City": "Leicester", "Portugal": "Portugal",
    "Spain": "Espanha", "Germany": "Alemanha", "Belgium": "Bélgica", "Japan": "Japão",
    "France": "França", "Croatia": "Croácia", "Netherlands": "Holanda", "Mexico": "México",
    "Serbia": "Sérvia", "Scotland": "Escócia", "Czech Republic": "Rep. Tcheca",
    "Slovakia": "Eslováquia", "Switzerland": "Suíça", "Turkey": "Turquia", "Georgia": "Geórgia",
    "Saudi Arabia": "Arábia Saudita", "Boca Juniors": "Boca Juniors", "River Plate": "River Plate",
    "Celta Vigo": "Celta", "Real Betis": "Real Betis",
}

COMP_PT = {
    (43, 54): "Copa do Mundo 1986", (43, 272): "Copa do Mundo 1970", (43, 269): "Copa do Mundo 1958",
    (16, 25): "Liga dos Campeões 2013/14", (16, 1): "Liga dos Campeões 2017/18",
    (16, 23): "Liga dos Campeões 2011/12", (16, 2): "Liga dos Campeões 2016/17",
    (16, 22): "Liga dos Campeões 2010/11", (16, 37): "Liga dos Campeões 2004/05",
    (16, 41): "Liga dos Campeões 2008/09", (11, 38): "La Liga 2005/06", (11, 2): "La Liga 2016/17",
    (11, 27): "La Liga 2015/16", (11, 4): "La Liga 2018/19", (2, 44): "Premier League 2003/04",
    (2, 27): "Premier League 2015/16", (9, 27): "Bundesliga 2015/16", (43, 3): "Copa do Mundo 2018",
    (43, 106): "Copa do Mundo 2022", (55, 43): "Eurocopa 2020", (55, 282): "Eurocopa 2024",
    (81, 275): "Liga Profesional 1981",
}

# Nomes curtos para jogadores sem player_nickname nos lineups (chave: trecho do nome sem acento, minusculo).
NOMES_CURTOS = {
    "edson arantes": "Pelé", "ronaldo de assis": "Ronaldinho", "sergio ramos": "Ramos",
    "cristiano ronaldo": "Cristiano Ronaldo", "didier yves drogba": "Drogba",
    "luis alberto suarez": "Suárez", "lionel andres messi": "Messi", "diego armando maradona": "Maradona",
    "carlos alberto torres": "Carlos Alberto", "gareth frank bale": "Bale", "kylian mbappe": "Mbappé",
    "angel fabian di maria": "Di María", "nahuel molina": "Molina", "neymar da silva": "Neymar",
    "richarlison de andrade": "Richarlison", "lamine yamal": "Lamine Yamal", "marco asensio": "Asensio",
    "salem mohammed al dawsari": "Al-Dawsari", "mario mandzukic": "Mandžukić", "thierry henry": "Henry",
    "steven gerrard": "Gerrard", "jamie vardy": "Vardy", "benjamin pavard": "Pavard",
    "patrik schick": "Schick", "jude bellingham": "Bellingham", "nacer chadli": "Chadli",
    "toni kroos": "Kroos", "enzo fernandez": "Enzo Fernández", "ronaldo de assis moreira": "Ronaldinho",
}


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def obter(rel):
    """JSON de BASE_URL + rel, com cache em data/raw/statsbomb/data/. None se o arquivo nao existe (404)."""
    alvo = CACHE / "data" / rel
    if alvo.exists() and alvo.stat().st_size > 0:
        return json.loads(alvo.read_text(encoding="utf-8"))
    marca = alvo.with_name(alvo.name + ".ausente")
    if marca.exists():
        return None
    alvo.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(BASE_URL + rel, timeout=180) as resp:
            dados = resp.read()
    except urllib.error.HTTPError as erro:
        if erro.code == 404:
            marca.write_text("404\n", encoding="utf-8")
            return None
        raise
    tmp = alvo.with_name(alvo.name + ".tmp")
    tmp.write_bytes(dados)
    tmp.replace(alvo)
    return json.loads(dados.decode("utf-8"))


def tempo(ev):
    """Segundos no relogio da partida (minuto x 60 + segundos com fracao do timestamp)."""
    return float(ev["minute"]) * 60.0 + float(ev["timestamp"].split(":")[2])


def cadeia_bola(eventos, gol, gol_team, desde):
    """Keyframes da bola ate o chute do gol. Devolve (keyframes, t_b, fim_gol).

    t_b e o inicio do chute da bola (pode ser um pouco depois do evento, se a cadeia anterior
    ainda estava em curso). fim_gol = (t, x, y, z) do ponto em que a bola chega ao gol.
    """
    bk = []
    cur_t = None
    cur_p = None
    t_b = None
    fim = None
    for e in sorted(eventos, key=lambda ev: ev["index"]):
        if e["index"] > gol["index"]:
            break
        if tempo(e) < desde:
            continue
        typ = e["type"]["name"]
        loc = e.get("location")
        if typ not in ("Pass", "Carry", "Shot") or not loc:
            continue
        alvo = e is gol
        esp = e["team"]["id"] != gol_team
        altura = None
        if typ == "Pass":
            fimloc = e["pass"].get("end_location") or loc
            altura = (e["pass"].get("height") or {}).get("name")
        elif typ == "Carry":
            fimloc = e["carry"].get("end_location") or loc
        else:
            fimloc = e["shot"].get("end_location") or loc
        p0 = campo_m(loc[0], loc[1], esp)
        p1 = campo_m(fimloc[0], fimloc[1], esp)
        if alvo:
            p1 = (max(p1[0], LINHA_GOL), p1[1])  # bola na linha de gol (gol confirmado pelo StatsBomb)
        d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        dur = float(e.get("duration") or 0.0)
        z1 = 0.0
        zpico = 0.0
        if typ == "Shot":
            if dur <= 0:
                dur = d / 25.0
            if len(fimloc) > 2:
                z1 = fimloc[2] * YARD
        elif typ == "Pass":
            zpico = {"Low Pass": 1.0, "High Pass": min(0.22 * d, 14.0)}.get(altura, 0.0)
        if cur_p is not None:
            dc = math.hypot(p0[0] - cur_p[0], p0[1] - cur_p[1])
            dtc = max(dc / VMAX_BOLA_SEG, 0.02)
            bk.append((cur_t + dtc, p0[0], p0[1], 0.0))
            ini = max(tempo(e), cur_t + dtc)
        else:
            ini = tempo(e)
        if alvo:
            t_b = ini
        bk.append((ini, p0[0], p0[1], 0.0))
        dt = max(dur, d / VMAX_BOLA_SEG, 0.02)
        for s in (0.25, 0.5, 0.75):
            bk.append((ini + dt * s, p0[0] + (p1[0] - p0[0]) * s, p0[1] + (p1[1] - p0[1]) * s,
                       z1 * s + zpico * 4 * s * (1 - s)))
        bk.append((ini + dt, p1[0], p1[1], z1))
        cur_t, cur_p = ini + dt, p1
        if alvo:
            fim = (ini + dt, p1[0], p1[1], z1)
            break
    if fim is None:
        raise RuntimeError("chute do gol sem segmento de bola")
    out = []
    for k in bk:
        if out and k[0] <= out[-1][0] + 1e-9:
            k = (out[-1][0] + 0.01,) + k[1:]  # tempos estritamente crescentes (ajuste de 10 ms)
        out.append(k)
    return out, t_b, fim


def campo_m(x, y, espelhar):
    """Jardas StatsBomb -> metros no referencial do time que marcou (ataca para +x)."""
    if espelhar:
        x, y = 120.0 - x, 80.0 - y
    return (x - 60.0) * 105.0 / 120.0, (40.0 - y) * 68.0 / 80.0



def interp_lin(ts, vs, t):
    if t <= ts[0]:
        return vs[0]
    if t >= ts[-1]:
        return vs[-1]
    i = bisect.bisect_right(ts, t) - 1
    s = (t - ts[i]) / (ts[i + 1] - ts[i])
    return tuple(a + (b - a) * s for a, b in zip(vs[i], vs[i + 1]))





def limpar_chaves(chaves):
    """chaves: [(t, x, y, src)]. Junta os pontos com menos de 0,04 s; fica o de maior prioridade (ev > ff > 360)."""
    out = []
    for k in sorted(chaves, key=lambda c: c[0]):
        if out and k[0] - out[-1][0] < 0.04:
            if PRIO[k[3]] <= PRIO[out[-1][3]]:
                out[-1] = k
        else:
            out.append(k)
    return out


def podar_chaves(ks, t_ref):
    """Mantem o ponto do chute (t_ref) e so os pontos reais que chegam a ele sem passar de VMAX_CHAVE."""
    ks = limpar_chaves(ks)
    if len(ks) <= 1:
        return ks
    ref = next((i for i, k in enumerate(ks) if abs(k[0] - t_ref) < 1e-3), None)
    if ref is None:
        ref = min(range(len(ks)), key=lambda i: abs(ks[i][0] - t_ref))
    antes, prox = [], ks[ref]
    for k in reversed(ks[:ref]):
        d = math.hypot(k[1] - prox[1], k[2] - prox[2])
        if d <= VMAX_CHAVE * (prox[0] - k[0]):
            antes.append(k)
            prox = k
    depois, prox = [], ks[ref]
    for k in ks[ref + 1:]:
        d = math.hypot(k[1] - prox[1], k[2] - prox[2])
        if d <= VMAX_CHAVE * (k[0] - prox[0]):
            depois.append(k)
            prox = k
    return list(reversed(antes)) + [ks[ref]] + depois


def limitar_campo(seq, lim_x, lim_y):
    """Prende cada ponto em |x| <= lim_x e |y| <= lim_y. Devolve (lista, pontos alterados)."""
    out = []
    n = 0
    for x, y in seq:
        nx = min(max(x, -lim_x), lim_x)
        ny = min(max(y, -lim_y), lim_y)
        if nx != x or ny != y:
            n += 1
        out.append((nx, ny))
    return out, n


def limitar_velocidade(seq, vmax):
    """Corrige, em ordem, cada passo maior que vmax/FPS. Devolve (lista, numero de correcoes)."""
    passo = vmax / FPS
    corr = 0
    out = [seq[0]]
    for i in range(1, len(seq)):
        px, py = out[-1]
        dx, dy = seq[i][0] - px, seq[i][1] - py
        d = math.hypot(dx, dy)
        if d > passo + 1e-9:
            f = passo / d
            out.append((px + dx * f, py + dy * f))
            corr += 1
        else:
            out.append(seq[i])
    return out, corr


# ---------------------------------------------------------------------------
# Selecao de partida e gol
# ---------------------------------------------------------------------------

def achar_partida(spec):
    comp, times = spec["comp"], spec["times"]
    matches = obter(f"matches/{comp[0]}/{comp[1]}.json")
    if matches is None:
        return None, f"matches/{comp[0]}/{comp[1]}.json inexistente no Open Data"
    alvo = set(times)
    for m in matches:
        nomes = {m["home_team"]["home_team_name"], m["away_team"]["away_team_name"]}
        if nomes != alvo:
            continue
        if spec.get("data") and not m["match_date"].startswith(spec["data"]):
            continue
        return m, None
    return None, "partida ausente no Open Data (" + " x ".join(times) + (f", {spec['data']}" if spec.get("data") else "") + ")"


def achar_gol(eventos, spec):
    cands = []
    for e in eventos:
        if e["type"]["name"] != "Shot" or e["shot"]["outcome"]["name"] != "Goal":
            continue
        if norm(spec["autor"]) not in norm(e["player"]["name"]):
            continue
        if spec.get("time") and e["team"]["name"] != spec["time"]:
            continue
        if "minuto" in spec and e["minute"] != spec["minuto"]:
            continue
        if spec.get("tecnica") and e["shot"]["technique"]["name"] != spec["tecnica"]:
            continue
        cands.append(e)
    cands.sort(key=tempo)
    if spec.get("n"):
        return (cands[spec["n"] - 1] if len(cands) >= spec["n"] else None), len(cands)
    if len(cands) == 1:
        return cands[0], 1
    return None, len(cands)


# ---------------------------------------------------------------------------
# Reconstrucao de um gol
# ---------------------------------------------------------------------------

def reconstruir(spec, partida, eventos, lineups, t360, gol):
    avisos = []
    mid = partida["match_id"]
    gol_team = gol["team"]["id"]
    times_ids = {}
    for m in lineups:
        times_ids[m["team_id"]] = m["team_name"]
    for e in eventos:
        if "team" in e:
            times_ids.setdefault(e["team"]["id"], e["team"]["name"])
    outro = {tid for tid in times_ids if tid != gol_team}
    if len(outro) != 1:
        raise RuntimeError(f"partida {mid}: times nao identificados")
    outro_id = outro.pop()
    nome_time = {gol_team: times_ids[gol_team], outro_id: times_ids[outro_id]}
    goleiros = {str(p["player_id"]) for m in lineups for p in m["lineup"]
                if any(q.get("position") == "Goalkeeper" for q in p.get("positions", []))}

    info = {}  # pid -> (nome, numero, team_id)
    for m in lineups:
        for p in m["lineup"]:
            pid = str(p["player_id"])
            nome_base = p.get("player_name") or ""
            nick = p.get("player_nickname")
            if nick:
                nome = nick
            else:
                nome = None
                nb = norm(nome_base)
                for chave, curto in NOMES_CURTOS.items():
                    if chave in nb:
                        nome = curto
                        break
                if nome is None:
                    nome = nome_base.split()[-1] if nome_base.split() else nome_base
            info[pid] = (nome, p.get("jersey_number"), m["team_id"])

    t_c = tempo(gol)
    inicio_posse = min(tempo(e) for e in eventos if e["possession"] == gol["possession"] and e["index"] <= gol["index"])
    W = spec.get("janela", JANELA_PADRAO)

    # ---------------- bola: cadeia de segmentos com tempo para frente ----------------
    # Cada passe/conducao/chute e um segmento. Se o segmento seguinte comeca antes do anterior
    # terminar, ele espera; se os pontos estao distantes, uma conexao anda no limite VMAX_BOLA_SEG.
    # Assim a bola nunca tem velocidade acima do limite. O chute pode atrasar um pouco (t_b).
    bk, t_b, fim_gol = cadeia_bola(eventos, gol, gol_team, t_c - W - 15.0)
    t_gol_fim, gx, gy, gz = fim_gol

    # ---------------- janela (quadros), alinhada ao inicio do chute da bola ----------------
    ini_bruto = max(inicio_posse, t_b - W)
    if t_b - ini_bruto < JANELA_MINIMA:
        ini_bruto = t_b - JANELA_MINIMA  # bola parada/cobranca: a posse comeca no proprio chute
    n_pre = round((t_b - ini_bruto) * FPS)
    t0 = t_b - n_pre / FPS
    t_fim = max(t_b + JANELA_DEPOIS, t_gol_fim + 0.5)  # chutes longos: a janela vai ate a bola entrar no gol
    n_pos = round((t_fim - t_b) * FPS)
    frames = n_pre + n_pos + 1
    t_fim = t_b + n_pos / FPS

    wev = [e for e in eventos if t0 - 3.0 <= tempo(e) <= t_fim + 1.0]
    eventos_janela = sum(1 for e in wev if t0 <= tempo(e) <= t_fim)

    # Bola entra no gol: ponto alem da linha e queda ate o chao, depois parada na rede.
    bk.append((t_gol_fim + 0.2, 53.8, gy, gz * 0.5))
    bk.append((t_gol_fim + 0.5, 54.0, gy, 0.0))
    b_ts = [k[0] for k in bk]
    b_vs = [(k[1], k[2], k[3]) for k in bk]
    if any(b_ts[i + 1] <= b_ts[i] for i in range(len(b_ts) - 1)):
        raise RuntimeError("tempos da bola nao crescentes")

    def bola_em(t):
        return interp_lin(b_ts, b_vs, t)

    # ---------------- jogadores: chaves reais ----------------
    chaves = {}  # pid -> [(t, x, y, src)]
    time_de = {}  # pid -> team id
    for pid, (_, _, tid) in info.items():
        time_de[pid] = tid

    def adicionar(pid, t, p, team, src):
        chaves.setdefault(pid, []).append((t, p[0], p[1], src))
        time_de.setdefault(pid, team)

    for e in wev:
        typ = e["type"]["name"]
        te = tempo(e)
        esp = e["team"]["id"] != gol_team
        tid = e["team"]["id"]
        loc = e.get("location")
        pl = e.get("player")
        pid = str(pl["id"]) if pl else None
        if pid and loc:
            src = "chute" if e is gol else "ev"
            adicionar(pid, te, campo_m(loc[0], loc[1], esp), tid, src)
        if typ == "Carry" and pid and e["carry"].get("end_location"):
            fim = e["carry"]["end_location"]
            adicionar(pid, te + float(e.get("duration") or 0.0), campo_m(fim[0], fim[1], esp), tid, "ev")
        if typ == "Pass" and e["pass"].get("recipient") and e["pass"].get("end_location"):
            rec = e["pass"]["recipient"]
            fim = e["pass"]["end_location"]
            adicionar(str(rec["id"]), te + float(e.get("duration") or 0.0), campo_m(fim[0], fim[1], esp), tid, "ev")
        if typ == "Shot" and e["shot"].get("freeze_frame"):
            for p in e["shot"]["freeze_frame"]:
                q = p.get("player")
                if not q or not p.get("location"):
                    continue
                qid = str(q["id"])
                if pid and qid == pid:
                    continue  # o chutador fica na posicao exata do chute
                team_q = tid if p.get("teammate") else (outro_id if tid == gol_team else gol_team)
                adicionar(qid, te, campo_m(p["location"][0], p["location"][1], esp), team_q, "ff")

    usou360 = False
    tem_360 = t360 is not None
    if tem_360:
        # 360 do proprio chute nao entra: o freeze frame do chute ja trouxe os nomes.
        quadros = {f["event_uuid"]: f for f in t360}
        seq = []
        for e in wev:
            if e["id"] not in quadros:
                continue
            te = tempo(e)
            if not (t0 - 0.001 <= te < t_c - 0.001):
                continue
            seq.append((te, e))
        seq.sort(key=lambda z: -z[0])
        for te, e in seq:
            quadro = quadros[e["id"]]
            ator_team = e["team"]["id"]
            ator_pid = str(e["player"]["id"]) if e.get("player") else None
            esp = ator_team != gol_team
            outro_ator = outro_id if ator_team == gol_team else gol_team
            pts = []
            for p in quadro.get("freeze_frame", []):
                if p.get("actor") or not p.get("location"):
                    continue
                team_p = ator_team if p.get("teammate") else outro_ator
                pts.append((campo_m(p["location"][0], p["location"][1], esp), team_p))
            for team in (ator_team, outro_ator):
                pts_t = [q for q, tm in pts if tm == team]
                if not pts_t:
                    continue
                estado = {}
                for pid, ks in chaves.items():
                    if time_de.get(pid) != team or pid == ator_pid or not ks:
                        continue
                    k = min(ks, key=lambda c: abs(c[0] - te))
                    estado[pid] = (abs(k[0] - te), k[1], k[2])
                pares = []
                for pid, (dt, x, y) in estado.items():
                    gate = max(3.0, 8.5 * dt)
                    for j, q in enumerate(pts_t):
                        d = math.hypot(q[0] - x, q[1] - y)
                        if d <= gate:
                            pares.append((d, pid, j))
                pares.sort()
                usados_p, usados_j = set(), set()
                for d, pid, j in pares:
                    if pid in usados_p or j in usados_j:
                        continue
                    usados_p.add(pid)
                    usados_j.add(j)
                    adicionar(pid, te, pts_t[j], team, "360")
                    usou360 = True

    # ---------------- jogadores: trajetorias ----------------
    pids = [pid for pid, ks in chaves.items() if any(t0 - 3.0 <= c[0] <= t_fim for c in ks)]
    if str(gol["player"]["id"]) not in pids:
        raise RuntimeError("finalizador sem chave")
    jogadores = []
    total_corr = 0
    total_campo = 0
    n_est = 0
    for pid in pids:
        ks = chaves[pid]
        extras = [c for c in ks if abs(c[0] - t_c) > 1e-3]
        estimado = len(extras) <= 1
        anc = podar_chaves(ks, t_c)
        if estimado and pid != str(gol["player"]["id"]):  # o chutador fica no ponto do chute
            ts = [c[0] for c in anc]
            ps = [(c[1], c[2]) for c in anc]
            bs = [tuple(bola_em(c[0])[:2]) for c in anc]
            lo, hi = ts[0] - MOV_SINTETICO_ANTES, ts[-1] + JANELA_DEPOIS

            def pos_fn(t, ts=ts, ps=ps, bs=bs, lo=lo, hi=hi):
                # o movimento copiado da bola so vale perto do ponto real (fora disso o jogador fica parado)
                P = interp_lin(ts, ps, t)
                Bb = interp_lin(ts, bs, t)
                Bt = bola_em(min(max(t, lo), hi))
                return (P[0] + K_OFF[0] * (Bt[0] - Bb[0]), P[1] + K_OFF[1] * (Bt[1] - Bb[1]))
            n_est += 1
        else:
            pts = [(c[0], c[1], c[2]) for c in anc]
            prep = ([c[0] for c in pts], [(c[1], c[2]) for c in pts])
            t_ult = pts[-1][0]
            x_ult, y_ult = pts[-1][1], pts[-1][2]
            if len(pts) >= 2 and pid != str(gol["player"]["id"]):
                dtv = pts[-1][0] - pts[-2][0]
                vx = (pts[-1][1] - pts[-2][1]) / dtv
                vy = (pts[-1][2] - pts[-2][2]) / dtv
                v = math.hypot(vx, vy)
                if v > VMAX_JOG:
                    vx, vy = vx * VMAX_JOG / v, vy * VMAX_JOG / v
            else:
                vx = vy = 0.0

            def pos_fn(t, prep=prep, t_ult=t_ult, x_ult=x_ult, y_ult=y_ult, vx=vx, vy=vy):
                if t <= t_ult:
                    return interp_lin(prep[0], prep[1], t)
                dt = t - t_ult
                f = TAU * (1 - math.exp(-dt / TAU))
                return (x_ult + vx * f, y_ult + vy * f)
        serie = [pos_fn(t0 + i / FPS) for i in range(frames)]
        lim_x = GOLEIRO_LIM_X if pid in goleiros else CAMPO_LIM_X
        serie, nc = limitar_campo(serie, lim_x, CAMPO_LIM_Y)  # antes do limitador de velocidade
        total_campo += nc
        serie, corr = limitar_velocidade(serie, VMAX_LIMITE)
        total_corr += corr
        time_lado = "attack" if time_de[pid] == gol_team else "defense"
        nome, numero, _ = info.get(pid, (None, None, None))
        if nome is None:
            nome = next((str(e["player"]["name"]).split()[-1] for e in wev if e.get("player") and str(e["player"]["id"]) == pid), pid)
        jogadores.append({
            "id": pid,
            "time": time_lado,
            "numero": int(numero) if numero is not None else None,
            "nome": nome,
            "pos": [[round(x, 3), round(y, 3)] for x, y in serie],
            "estimado": estimado,
        })
    if total_corr:
        avisos.append(f"{total_corr} pontos corrigidos pelo limite de 10,5 m/s")
    if total_campo:
        avisos.append(f"{total_campo} pontos presos ao campo (+3 m)")

    bola = []
    v_bola_max = 0.0
    prev = None
    for i in range(frames):
        b = bola_em(t0 + i / FPS)
        bola.append([round(b[0], 3), round(b[1], 3), round(b[2], 3)])
        if prev is not None:
            v = math.dist(b, prev) * FPS
            v_bola_max = max(v_bola_max, v)
        prev = b
    if v_bola_max > 45:
        avisos.append(f"velocidade da bola {v_bola_max:.1f} m/s")

    return {
        "frames": frames, "frameChute": n_pre, "bola": bola, "jogadores": jogadores,
        "finalizadorId": str(gol["player"]["id"]), "time_gol": nome_time[gol_team], "time_outro": nome_time[outro_id],
        "time_gol_id": gol_team, "avisos": avisos, "t_c": t_c, "t0": t0, "n_est": n_est,
        "limitados_campo": total_campo,
        "eventos": eventos_janela, "tem360": tem_360 and usou360, "ff": bool(gol["shot"].get("freeze_frame")),
        "v_bola_max": v_bola_max, "mid": mid, "bk": bk,
    }


def subtitulo(partida, spec):
    casa = NOMES_PT.get(partida["home_team"]["home_team_name"], partida["home_team"]["home_team_name"])
    fora = NOMES_PT.get(partida["away_team"]["away_team_name"], partida["away_team"]["away_team_name"])
    comp = COMP_PT.get(tuple(spec["comp"]), "")
    d = partida["match_date"].split("-")
    return (f"{casa} {partida['home_score']} × {partida['away_score']} {fora} · {comp} · "
            f"{d[2]}/{d[1]}/{d[0]}")


def montar_item(ordem, spec, partida, eventos, lineups, t360, gol):
    r = reconstruir(spec, partida, eventos, lineups, t360, gol)
    att, dfn = r["time_gol"], r["time_outro"]
    cor_a, borda_a, _ = CORES.get(att, ("#888888", "#FFFFFF", "#FFFFFF"))
    cor_d, borda_d, alt_d = CORES.get(dfn, ("#666666", "#FFFFFF", "#FFFFFF"))
    if math.dist(_hex_rgb(cor_a), _hex_rgb(cor_d)) < 110:
        cor_d = alt_d
        r["avisos"].append(f"cor do {dfn} trocada para a alternativa (parecida com {att})")
    cores = {"attack": (cor_a, borda_a), "defense": (cor_d, borda_d)}
    for j in r["jogadores"]:
        j["cor"], j["borda"] = cores[j["time"]]
    r["jogadores"].sort(key=lambda j: (j["time"] != "attack", j["numero"] is None, j["numero"] or 0))
    if CORES.get(att) is None or CORES.get(dfn) is None:
        r["avisos"].append(f"cor sem tabela: {att} x {dfn}")
    lance = {
        "id": slug(spec["titulo"]),
        "ordem": ordem,
        "grupo": "hypados",
        "titulo": spec["titulo"],
        "subtitulo": subtitulo(partida, spec),
        "contexto": spec["contexto"],
        "fonte": "StatsBomb Open Data",
        "fps": FPS,
        "frames": r["frames"],
        "bola": r["bola"],
        "jogadores": r["jogadores"],
        "times": {"attack": NOMES_PT.get(att, att), "defense": NOMES_PT.get(dfn, dfn)},
        "finalizadorId": r["finalizadorId"],
        "frameChute": r["frameChute"],
        "partida": {"matchId": r["mid"], "minuto": f"{gol['minute']}:{gol['second']:02d}"},
        "qualidade": {
            "freeze_frame": r["ff"],
            "tem360": r["tem360"],
            "eventos": r["eventos"],
            "jogadores_reais": sum(1 for j in r["jogadores"] if not j["estimado"]),
            "jogadores_estimados": sum(1 for j in r["jogadores"] if j["estimado"]),
        },
    }
    return lance, r


def _hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def slug(texto):
    s = norm(texto)
    s = "".join(c if c.isalnum() else "-" for c in s)
    return "-".join(p for p in s.split("-") if p)


def tentar(spec):
    """Resolve um item (ou reserva). Devolve (lance, relatorio) ou (None, motivo)."""
    partida, motivo = achar_partida(spec)
    if partida is None:
        return None, motivo
    eventos = obter(f"events/{partida['match_id']}.json")
    if eventos is None:
        return None, "events ausente"
    gol, n = achar_gol(eventos, spec)
    if gol is None:
        return None, f"gol nao encontrado ({n} candidatos)"
    lineups = obter(f"lineups/{partida['match_id']}.json") or []
    t360 = obter(f"three-sixty/{partida['match_id']}.json")
    return (partida, eventos, lineups, t360, gol), None


def copiar_origi():
    """Devolve (lance, pontos presos ao campo). Posicoes do Last-Row: sem informacao de goleiro."""
    lances = json.loads(LANCES_LASTROW.read_text(encoding="utf-8"))["lances"]
    origi = next(l for l in lances if l["id"] == "liverpool-4-0-barcelona")
    lance = dict(origi)
    nc_total = 0
    jogs = []
    for j in origi["jogadores"]:
        novo = []
        for p in j["pos"]:
            if p is None:
                novo.append(None)
                continue
            (q,), nc = limitar_campo([tuple(p)], CAMPO_LIM_X, CAMPO_LIM_Y)
            nc_total += nc
            novo.append(p if nc == 0 else [round(q[0], 3), round(q[1], 3)])
        jogs.append({**j, "pos": novo})
    lance["jogadores"] = jogs
    lance["ordem"] = 30
    lance["grupo"] = "hypados"
    lance["titulo"] = "Origi — escanteio rápido"
    lance["subtitulo"] = "Liverpool 4 × 0 Barcelona · Liga dos Campeões 2018/19 · semifinal, mai/2019"
    lance["finalizadorId"] = "13"
    lance["qualidade"] = {"freeze_frame": False, "tem360": False, "eventos": None,
                          "jogadores_reais": sum(1 for j in origi["jogadores"]), "jogadores_estimados": 0}
    lance["partida"] = {"matchId": None, "minuto": ""}
    return lance, nc_total


def tentar_completo(spec, ordem):
    """Reconstroi o item. Devolve ((lance, relatorio, spec), None) ou (None, motivo)."""
    res, motivo = tentar(spec)
    if res is None:
        return None, motivo
    partida, eventos, lineups, t360, gol = res
    try:
        lance, r = montar_item(ordem, spec, partida, eventos, lineups, t360, gol)
    except RuntimeError as erro:
        return None, f"reconstrucao falhou: {erro}"
    if len(r["jogadores"]) < 8:
        return None, f"so {len(r['jogadores'])} jogadores (minimo 8)"
    return (lance, r), None


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    proxima_reserva = 0
    saida = []
    relatorio = []
    limitados_total = 0
    for ordem, spec in enumerate(ITENS, start=1):
        ok, motivo = tentar_completo(spec, ordem)
        usado = spec
        if ok is None:
            relatorio.append(f"{ordem:>2} {spec['titulo']}: {motivo}")
            while proxima_reserva < len(RESERVAS):
                cand = RESERVAS[proxima_reserva]
                proxima_reserva += 1
                ok, motivo2 = tentar_completo(cand, ordem)
                if ok is not None:
                    usado = cand
                    relatorio.append(f"{ordem:>2} {spec['titulo']}: SUBSTITUIDO por '{cand['titulo']}'")
                    break
                relatorio.append(f"{ordem:>2} reserva '{cand['titulo']}' descartada: {motivo2}")
            if ok is None:
                relatorio.append(f"{ordem:>2} {spec['titulo']}: SEM SUBSTITUTO")
                continue
        lance, r = ok
        saida.append(lance)
        limitados_total += r["limitados_campo"]
        gol_min = lance["partida"]["minuto"]
        print(f"{ordem:>2} {usado['titulo']}: match {lance['partida']['matchId']}, {gol_min}, "
              f"frames {r['frames']}, chute@{r['frameChute']}, jogadores {len(r['jogadores'])} "
              f"(estimados {r['n_est']}), 360={'sim' if r['tem360'] else 'nao'}, "
              f"freeze={'sim' if r['ff'] else 'nao'}"
              + (" [reserva]" if usado is not spec else ""))
        for a in r["avisos"]:
            print("    aviso:", a)

    origi, nc_origi = copiar_origi()
    saida.append(origi)
    limitados_total += nc_origi
    print(f"30 {origi['titulo']}: copiado de web/data/lances.json (Last-Row)")
    saida.sort(key=lambda l: l["ordem"])

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    tmp = SAIDA.with_name(SAIDA.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"lances": saida}, f, separators=(",", ":"), ensure_ascii=False)
    tmp.replace(SAIDA)
    print(f"gravado {SAIDA} com {len(saida)} lances")
    print(f"pontos de jogadores presos ao campo (+3 m): {limitados_total}")
    for linha in relatorio:
        print("  relatorio:", linha)


if __name__ == "__main__":
    sys.exit(main())
