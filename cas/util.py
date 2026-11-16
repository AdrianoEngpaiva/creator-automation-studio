"""Funções pequenas usadas em todo o pipeline."""
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path


def hms(s):
    s = max(0, int(round(s)))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def segundos(v):
    """3723 | '3723' | '1:02:03' | '62:03' -> float"""
    if isinstance(v, (int, float)):
        return float(v)
    total = 0.0
    for parte in str(v).strip().split(":"):
        total = total * 60 + float(parte)
    return total


def slug(texto, limite=60):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()[:limite].strip("-") or "fonte"


def nome_arquivo(texto, limite=60):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^\w\- ]", "", t).strip()[:limite]


def rodar(cmd, silencioso=True, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode:
        sys.exit(f"ERRO ao rodar {Path(str(cmd[0])).name}:\n{r.stderr[-3000:]}")
    if not silencioso and r.stdout:
        print(r.stdout)
    return r.stdout


def sondar(video):
    j = json.loads(rodar(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", video]))
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    num, den = map(float, v["r_frame_rate"].split("/"))
    return {"w": int(v["width"]), "h": int(v["height"]), "fps": num / den if den else 30.0,
            "dur": float(j["format"]["duration"]), "audio": any(s["codec_type"] == "audio" for s in j["streams"])}


def ler_json(caminho, padrao=None):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho, dados):
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Path(caminho).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
