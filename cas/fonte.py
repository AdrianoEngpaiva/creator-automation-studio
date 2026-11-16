"""Fontes: lê metadados, baixa só o áudio, baixa só o trecho de vídeo e busca lives do dia (via yt-dlp)."""
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import TRABALHO
from .util import gravar_json, ler_json, rodar, slug

FORMATO_VIDEO = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b"


def ytdlp():
    exe = Path(sys.executable).parent / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
    cmd = [str(exe)] if exe.exists() else [sys.executable, "-m", "yt_dlp"]
    js = shutil.which("deno") and "deno" or shutil.which("node") and "node"
    return cmd + (["--js-runtimes", js] if js else []) + ["--no-warnings", "--no-playlist"]


def metadados(url):
    j = json.loads(rodar(ytdlp() + ["-J", url]))
    return {k: j.get(k) for k in ("id", "title", "uploader", "channel", "duration", "view_count", "webpage_url",
                                  "extractor_key", "live_status")} | {"url": url}


def pasta_da_fonte(url_ou_nome):
    """Aceita o link original, o nome da pasta ou um pedaço dele."""
    if (TRABALHO / url_ou_nome).is_dir():
        return TRABALHO / url_ou_nome
    for p in sorted(TRABALHO.glob("*")):
        info = ler_json(p / "info.json", {})
        if url_ou_nome in (info.get("url"), info.get("webpage_url")) or url_ou_nome.lower() in p.name:
            return p
    return None


def preparar_pasta(url):
    existente = pasta_da_fonte(url)
    if existente:
        return existente
    info = metadados(url)
    pasta = TRABALHO / slug(f"{info.get('uploader') or 'fonte'}-{info.get('title') or info['id']}")
    pasta.mkdir(parents=True, exist_ok=True)
    gravar_json(pasta / "info.json", info)
    return pasta


def baixar_audio(pasta):
    if not list(pasta.glob("audio.*")):
        info = ler_json(pasta / "info.json", {})
        rodar(ytdlp() + ["-f", "ba/b", "-x", "-o", str(pasta / "audio.%(ext)s"), info["url"]])
    return next(pasta.glob("audio.*"))


def baixar_chat(pasta):
    """Replay do chat (só existe em live que passou no YouTube). Sem chat não é erro."""
    info = ler_json(pasta / "info.json", {})
    marca = pasta / "chat.ok"
    if marca.exists() or not str(info.get("extractor_key", "")).lower().startswith("youtube"):
        return next(iter(pasta.glob("chat*.live_chat.json")), None)
    try:
        subprocess.run(ytdlp() + ["--skip-download", "--write-subs", "--sub-langs", "live_chat",
                                  "-o", str(pasta / "chat"), info["url"]], capture_output=True, timeout=1800)
    except subprocess.TimeoutExpired:
        pass
    marca.write_text("ok")
    return next(iter(pasta.glob("chat*.live_chat.json")), None)


def tem_imagem(arq):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-count_packets", "-show_entries",
                        "stream=nb_read_packets", "-of", "csv=p=0", str(arq)], capture_output=True, text=True)
    return r.stdout.strip().isdigit() and int(r.stdout.strip()) > 10


def baixar_trecho(pasta, ini, fim, destino):
    """Tenta baixar só os segundos do corte; se o site não deixar, baixa o vídeo uma vez e recorta localmente."""
    destino = Path(destino)
    if destino.exists() and tem_imagem(destino):
        return destino
    info = ler_json(pasta / "info.json", {})
    subprocess.run(ytdlp() + ["-q", "-f", FORMATO_VIDEO, "--download-sections", f"*{ini:.2f}-{fim:.2f}",
                              "--force-keyframes-at-cuts", "--merge-output-format", "mp4", "-o", str(destino),
                              info["url"]], capture_output=True)
    if destino.exists() and tem_imagem(destino):
        return destino
    destino.unlink(missing_ok=True)
    inteiro = next((p for p in pasta.glob("video_inteiro.*") if tem_imagem(p)), None)
    if not inteiro:
        rodar(ytdlp() + ["-f", FORMATO_VIDEO, "--merge-output-format", "mp4", "-o",
                         str(pasta / "video_inteiro.%(ext)s"), info["url"]])
        inteiro = next(pasta.glob("video_inteiro.*"))
    rodar(["ffmpeg", "-v", "error", "-y", "-ss", f"{ini:.2f}", "-i", inteiro, "-t", f"{fim - ini:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", destino])
    return destino


def buscar_lives(termos, quantas=7, min_minutos=30, filtro=None):
    """Vídeos longos publicados hoje para os termos, ordenados por visualizações."""
    hoje = dt.date.today().strftime("%Y%m%d")
    achados = {}
    for termo in termos:
        r = subprocess.run(ytdlp() + ["-J", "--flat-playlist", f"ytsearchdate30:{termo}"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        try:
            itens = json.loads(r.stdout).get("entries", [])
        except json.JSONDecodeError:
            itens = []
        for v in itens:
            if not v or (v.get("duration") or 0) < min_minutos * 60:
                continue
            if v.get("upload_date") and v["upload_date"] != hoje:
                continue
            if filtro and not filtro(v.get("title") or ""):
                continue
            achados[v["id"]] = v
    return sorted(achados.values(), key=lambda v: -(v.get("view_count") or 0))[:quantas]
