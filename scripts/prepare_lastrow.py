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
Sistema de coordenadas: campo 105 x 68 m, origem no centro, x para a direita
(da câmera de TV), y para o lado oposto à câmera; z para cima.
"""
import csv
import re
import json
import sys
from collections import OrderedDict
from pathlib import Path

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
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w") as f:
        json.dump({"lances": saida}, f, separators=(",", ":"), ensure_ascii=False)
    for l in saida:
        print(f"{l['titulo']}: {l['frames']} frames, {len(l['jogadores'])} jogadores")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
