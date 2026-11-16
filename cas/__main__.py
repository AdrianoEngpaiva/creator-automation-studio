"""Linha de comando do Creator Automation Studio.

  python -m cas instalar                         confere ffmpeg/pacotes, baixa o detector de rosto, cria as pastas
  python -m cas buscar [--quantas 7]             vídeos longos de hoje para os termos (padrão: lives de GTA 6)
  python -m cas preparar LINK [LINK…]            baixa só o áudio, transcreve, marca picos e escreve os blocos
  python -m cas escolher FONTE [--manter 3]      junta os momentos anotados e fica com os melhores
  python -m cas cortar FONTE [--so 01,02]        baixa só os trechos, acha a câmera, narra e renderiza
  python -m cas cortar-arquivo cortes.json       mesma montagem, para vídeos que já estão no disco
  python -m cas contas | autorizar --conta X | quem --conta X
  python -m cas postar --conta X VIDEO.mp4 | --pasta PASTA
  python -m cas status
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import config
from .util import gravar_json, ler_json

SIGLAS = {"GTA", "RP", "PC", "PS5", "PS4", "NPC", "FPS", "VI", "V", "IV", "XBOX", "4K", "HD", "IA", "AI"}


def frase(titulo):
    """'PAULINHO JOGOU GTA 5' → 'Paulinho jogou GTA 5' (mantém siglas)."""
    p = [w.upper() if w.upper().strip("?!.,:") in SIGLAS else w for w in titulo.lower().split()]
    return (p[0][:1].upper() + p[0][1:] + "".join(" " + w for w in p[1:])) if p else ""


def gta6(titulo):
    t = titulo.lower()
    return re.search(r"gta\s*-?\s*(6|vi)(?![0-9a-z])", t) and not re.search(r"gta\s*-?\s*(5|v|iv|rp)(?![0-9a-z])", t)


# ---------------------------------------------------------------- comandos
def instalar(_):
    ok = True
    for exe in ("ffmpeg", "ffprobe"):
        achou = shutil.which(exe)
        print(f"  {'✓' if achou else '✗'} {exe}")
        ok &= bool(achou)
    for mod in ("faster_whisper", "cv2", "numpy", "soundfile", "yt_dlp", "googleapiclient", "google_auth_oauthlib"):
        try:
            __import__(mod)
            print(f"  ✓ {mod}")
        except ImportError:
            print(f"  ✗ {mod}  → pip install -r requirements.txt")
            ok = False
    from .camera import YUNET, YUNET_URL
    if not YUNET.exists():
        YUNET.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["curl", "-fsSL", "-o", str(YUNET), YUNET_URL], check=False)
    print(f"  {'✓' if YUNET.exists() else '✗'} detector de rosto (YuNet)")
    for p in (config.TRABALHO, config.SAIDA, config.SEGREDOS):
        p.mkdir(parents=True, exist_ok=True)
    raiz = Path(__file__).resolve().parent.parent / "config"
    for exemplo, destino in (("config.example.json", config.CONFIG), ("contas.example.json", config.CONTAS)):
        if not destino.exists() and (raiz / exemplo).exists():
            shutil.copy(raiz / exemplo, destino)
            print(f"  … criei {destino} a partir do exemplo — edite com os seus dados")
    print(f"\n{'TUDO PRONTO' if ok else 'FALTA ALGO (veja acima)'} · dados em {config.HOME}")


def buscar(a):
    from .fonte import buscar_lives
    lista = buscar_lives(a.termos, a.quantas, filtro=gta6 if a.so_gta6 else None)
    if not lista:
        print("nada longo publicado hoje para esses termos")
    for i, v in enumerate(lista, 1):
        print(f"{i}. {v.get('title')}\n   {v.get('channel') or v.get('uploader')} · {(v.get('duration') or 0) // 60} min · "
              f"{v.get('view_count') or 0} views\n   https://www.youtube.com/watch?v={v['id']}")


def preparar(a):
    from .fonte import preparar_pasta
    from .ouvir import preparar as prep
    for link in a.links:
        pasta = preparar_pasta(link)
        print(f"\n== {pasta.name}")
        prep(pasta, a.modelo, a.idioma)


def _pasta(nome):
    from .fonte import pasta_da_fonte
    p = pasta_da_fonte(nome)
    if not p:
        sys.exit(f"não achei '{nome}' em {config.TRABALHO}; rode antes: python -m cas preparar LINK")
    return p


def escolher(a):
    from .escolher import escolher as esc
    esc(_pasta(a.fonte), a.manter)


def cortar(a):
    from .camera import achar_camera
    from .fonte import baixar_trecho
    from .render import render_corte
    from .voz import Voz
    pasta = _pasta(a.fonte)
    info = ler_json(pasta / "info.json", {})
    escolhidos = ler_json(pasta / "escolhidos.json", {}).get("cortes")
    if not escolhidos:
        sys.exit("nenhum corte escolhido; rode antes: python -m cas escolher " + pasta.name)
    autor = info.get("uploader") or info.get("channel") or ""
    voz = Voz(a.rascunho)
    so = {x.strip() for x in a.so.split(",") if x.strip()}
    for i, m in enumerate(escolhidos, 1):
        cid = f"{i:02d}"
        if so and cid not in so:
            continue
        tdir = pasta / f"corte_{cid}"
        tdir.mkdir(exist_ok=True)
        trecho = baixar_trecho(pasta, m["ini"], m["fim"], tdir / "trecho.mp4")
        cam = achar_camera(trecho)
        print(f"[{cid}] {m.get('titulo', '')} · {'câmera achada' if cam else 'sem câmera: tela cheia'}")
        corte = {"id": cid, "titulo": m.get("titulo", ""), "fonte": str(trecho), "trechos": [[0, m["fim"] - m["ini"]]],
                 "camera": cam, "credito": f"@{autor}" if autor else "", "narracao": m.get("narracao", []),
                 "post": {"titulo": m.get("titulo_post") or frase(m.get("titulo", "")),
                          "descricao": (m.get("post") or "").strip() + (
                              "" if info.get("local") else
                              f"\n\nCorte de {autor}: {info.get('webpage_url') or info.get('url')}"),
                          "hashtags": m.get("hashtags", "#shorts")}}
        render_corte(corte, config.SAIDA / pasta.name, pasta / "render", voz)
    print(f"\npronto: {config.SAIDA / pasta.name}")


def cortar_arquivo(a):
    from .render import render_corte
    from .voz import Voz
    arq = Path(a.cortes).resolve()
    cfg = json.loads(arq.read_text(encoding="utf-8"))
    voz = Voz(a.rascunho)
    saida = Path(cfg.get("saida") or (config.SAIDA / arq.parent.name))
    for c in cfg["cortes"]:
        c = {"fonte": cfg.get("fonte"), "camera": cfg.get("camera"), "credito": cfg.get("credito", ""), **c}
        render_corte(c, saida, arq.parent / "render", voz, cfg.get("legendar_original", True), cfg.get("zoom", 1.25))


def contas(_):
    from . import postar as p
    for k, v in json.loads(Path(p.CONTAS).read_text(encoding="utf-8")).items():
        tok = (Path(p.SEGREDOS) / v.get("token", f"token_youtube_{k}.json")).exists()
        print(f"{k:12s} YouTube '{v['canal_youtube']}' · {v.get('formato')} · {'autorizada' if tok else 'NÃO autorizada'}")


def autorizar(a):
    from . import postar as p
    conta = p.conta_cfg(a.conta)
    yt = p.youtube(conta, interativo=True)
    p.garantir_canal(yt, conta)


def quem(a):
    from . import postar as p
    print("Canal:", p.canal(p.youtube(p.conta_cfg(a.conta)))[0])


def postar(a):
    from . import postar as p
    conta = p.conta_cfg(a.conta)
    yt = p.youtube(conta)
    p.garantir_canal(yt, conta)
    videos = a.videos or sorted(str(v) for v in Path(a.pasta).glob("*.mp4") if not v.name.startswith("_"))
    for v in videos:
        p.enviar(yt, conta, v, a.titulo, a.descricao, a.thumb)


def status(_):
    if not config.TRABALHO.exists():
        print("nada ainda")
        return
    for p in sorted(x for x in config.TRABALHO.iterdir() if x.is_dir()):
        nb = len(list((p / "blocos").glob("*.txt")))
        nm = len(list((p / "momentos").glob("*.json")))
        esc = len(ler_json(p / "escolhidos.json", {}).get("cortes") or [])
        prontos = len(list((config.SAIDA / p.name).glob("*.mp4")))
        print(f"{p.name}\n  blocos lidos {nm}/{nb} · escolhidos {esc} · prontos {prontos}")


def main():
    ap = argparse.ArgumentParser(prog="cas", description="Creator Automation Studio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("instalar").set_defaults(f=instalar)
    b = sub.add_parser("buscar")
    b.add_argument("--termos", nargs="+", default=["GTA 6 live", "GTA 6 ao vivo", "GTA VI stream"])
    b.add_argument("--quantas", type=int, default=7)
    b.add_argument("--todos", dest="so_gta6", action="store_false", help="não filtrar por GTA 6 no título")
    b.set_defaults(f=buscar)
    p = sub.add_parser("preparar")
    p.add_argument("links", nargs="+")
    p.add_argument("--modelo")
    p.add_argument("--idioma")
    p.set_defaults(f=preparar)
    e = sub.add_parser("escolher")
    e.add_argument("fonte")
    e.add_argument("--manter", type=int, default=3)
    e.set_defaults(f=escolher)
    c = sub.add_parser("cortar")
    c.add_argument("fonte")
    c.add_argument("--so", default="")
    c.add_argument("--rascunho", action="store_true")
    c.set_defaults(f=cortar)
    ca = sub.add_parser("cortar-arquivo")
    ca.add_argument("cortes")
    ca.add_argument("--rascunho", action="store_true")
    ca.set_defaults(f=cortar_arquivo)
    sub.add_parser("contas").set_defaults(f=contas)
    for nome, fn in (("autorizar", autorizar), ("quem", quem)):
        s = sub.add_parser(nome)
        s.add_argument("--conta", required=True)
        s.set_defaults(f=fn)
    po = sub.add_parser("postar")
    po.add_argument("--conta", required=True)
    po.add_argument("videos", nargs="*")
    po.add_argument("--pasta")
    po.add_argument("--titulo")
    po.add_argument("--descricao")
    po.add_argument("--thumb")
    po.set_defaults(f=postar)
    sub.add_parser("status").set_defaults(f=status)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
