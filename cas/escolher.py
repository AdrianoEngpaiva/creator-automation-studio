"""Junta os momentos que a IA anotou em cada bloco, ordena pela nota e fica com os melhores sem sobreposição."""
from .config import cfg
from .util import gravar_json, hms, ler_json, segundos


def carregar_momentos(pasta):
    momentos, problemas = [], []
    c = cfg()
    for arq in sorted((pasta / "momentos").glob("bloco_*.json")):
        dados = ler_json(arq)
        if dados is None:
            problemas.append(arq.name)
            continue
        for m in dados if isinstance(dados, list) else dados.get("momentos", []):
            try:
                ini, fim = segundos(m["inicio"]), segundos(m["fim"])
            except (KeyError, ValueError, TypeError):
                problemas.append(f"{arq.name}: {str(m)[:60]}")
                continue
            fim = min(max(fim, ini + c["duracao_min"]), ini + c["limite_segundos"])
            momentos.append({**m, "ini": ini, "fim": fim, "nota": float(m.get("nota", 0)), "bloco": arq.stem})
    return momentos, problemas


def escolher(pasta, manter=3):
    momentos, problemas = carregar_momentos(pasta)
    if problemas:
        print("não consegui ler:", *problemas, sep="\n  ")
    escolhidos = []
    for m in sorted(momentos, key=lambda m: -m["nota"]):
        if all(m["fim"] <= o["ini"] or o["fim"] <= m["ini"] for o in escolhidos):
            escolhidos.append(m)
        if len(escolhidos) >= manter:
            break
    escolhidos.sort(key=lambda m: m["ini"])
    gravar_json(pasta / "escolhidos.json", {"possiveis": len(momentos), "cortes": escolhidos})
    print(f"{len(momentos)} momentos possíveis → {len(escolhidos)} escolhidos:")
    for i, m in enumerate(escolhidos, 1):
        print(f"  {i}. [{hms(m['ini'])}–{hms(m['fim'])}] nota {m['nota']:.0f}  {m.get('titulo', '')}")
    return escolhidos
