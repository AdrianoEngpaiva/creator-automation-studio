"""Monta o corte vertical 1080x1920: câmera em cima + jogo até o fim da tela (ou o vídeo em tela cheia),
título na emenda, legenda palavra por palavra, narração com o áudio original abaixando por baixo, −14 LUFS.

Um corte é um dict:
  {"id": "01", "titulo": "ELE NÃO ACREDITOU", "fonte": "trecho.mp4", "trechos": [[0, 42.5]],
   "camera": [x, y, w, h] | None, "credito": "@streamer", "narracao": [{"t": 0.2, "texto": "..."}],
   "post": {"titulo": "...", "descricao": "...", "hashtags": "#gta6 #shorts"}}
"""
import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np

from .config import cfg, whisper
from .util import nome_arquivo, rodar, segundos, sondar
from .voz import Voz, tempos_das_palavras

W, H = 1080, 1920


# ---------------------------------------------------------------- legenda (ASS)
def _t(s):
    cs = int(round(max(0.0, s) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _limpo(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


def _cor_ass(hexa):
    h = hexa.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def agrupar(palavras, max_palavras=3, max_dur=1.4):
    grupos, atual = [], []
    for p in palavras:
        if atual and (len(atual) >= max_palavras or p[2] - atual[0][1] > max_dur or p[1] - atual[-1][2] > 0.5):
            grupos.append(atual)
            atual = []
        atual.append(p)
        if re.search(r"[.!?…]$", p[0]):
            grupos.append(atual)
            atual = []
    return grupos + ([atual] if atual else [])


MAX_LETRAS_TITULO = 24  # cabe em 1080 px com a fonte do título (62 px, Arial Black)


def quebrar_titulo(titulo, maximo=MAX_LETRAS_TITULO):
    """Título longo vira duas linhas equilibradas (nunca corta nas laterais)."""
    if len(titulo) <= maximo:
        return [titulo]
    palavras = titulo.split()
    melhor = None
    for i in range(1, len(palavras)):
        a, b = " ".join(palavras[:i]), " ".join(palavras[i:])
        custo = max(len(a), len(b))
        if melhor is None or custo < melhor[0]:
            melhor = (custo, a, b)
    return [melhor[1], melhor[2]] if melhor else [titulo]


def corrigir_volume(arquivo, alvo=-14.0, tolerancia=0.5):
    """2ª passada: mede o loudness integrado e ajusta só o áudio (o vídeo é copiado)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(arquivo), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", r.stderr)
    if not m:
        return None
    medido = float(m[-1])
    if abs(medido - alvo) <= tolerancia:
        return medido
    ajustado = Path(arquivo).with_name(Path(arquivo).stem + "_vol.mp4")
    rodar(["ffmpeg", "-v", "error", "-y", "-i", arquivo, "-map", "0", "-c:v", "copy", "-af",
           f"volume={alvo - medido:.2f}dB,alimiter=limit=0.89:level=disabled", "-c:a", "aac", "-b:a", "192k",
           "-ar", "48000", "-movflags", "+faststart", ajustado])
    os.replace(ajustado, arquivo)
    return medido


def escrever_legenda(caminho, dur, titulo, credito, palavras, y_leg, y_tit=None):
    c = cfg()["legenda"]
    destaque = _cor_ass(c["cor_destaque"])
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Leg,{c['fonte']},{c['tamanho']},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,7,4,5,60,60,0,1
Style: Tit,{c['fonte']},62,&H00FFFFFF,&H00FFFFFF,&H00180A1C,&H00180A1C,1,0,0,0,100,100,0,0,3,18,0,8,70,70,250,1
Style: Cred,Arial,34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,2,8,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    pos_t = f"\\an5\\pos({W // 2},{y_tit})" if y_tit else ""
    linhas_tit = quebrar_titulo(titulo.upper()) if titulo else []
    if titulo:
        ev.append(f"Dialogue: 2,{_t(0)},{_t(dur)},Tit,,0,0,0,,{{{pos_t}\\fad(150,0)}}"
                  + "\\N".join(_limpo(l) for l in linhas_tit))
    if credito:
        extra = 38 * (len(linhas_tit) - 1)  # o título em 2 linhas cresce para cima e para baixo da emenda
        y_c = (y_tit + 75 + extra) if y_tit else 400 + 2 * extra
        ev.append(f"Dialogue: 2,{_t(0)},{_t(dur)},Cred,,0,0,0,,{{\\an8\\pos({W // 2},{y_c})}}{_limpo(credito)}")
    grupos = agrupar(palavras)
    for k, g in enumerate(grupos):
        prox = grupos[k + 1][0][1] if k + 1 < len(grupos) else dur
        for i, (_, s, e) in enumerate(g):
            fim = g[i + 1][1] if i + 1 < len(g) else min(prox, max(e, s + 0.25) + 0.7)
            if round(fim, 2) <= round(s, 2):
                continue  # evento de duração zero: o libass some com o título inteiro quando encontra um desses
            txt = " ".join(f"{{\\c{destaque}\\fscx108\\fscy108}}{_limpo(w.upper())}{{\\c&HFFFFFF&\\fscx100\\fscy100}}"
                           if j == i else _limpo(w.upper()) for j, (w, _, _) in enumerate(g))
            pop = "\\t(0,80,\\fscx110\\fscy110)\\t(80,160,\\fscx100\\fscy100)" if i == 0 else ""
            ev.append(f"Dialogue: 1,{_t(s)},{_t(fim)},Leg,,0,0,0,,{{\\pos({W // 2},{y_leg}){pop}}}{txt}")
    Path(caminho).write_text(cab + "\n".join(ev) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- palavras do áudio original
_modelo_orig = None


def palavras_originais(fonte, trechos, tmp):
    global _modelo_orig
    cache = tmp / "palavras_orig.json"
    if cache.exists():
        return [tuple(p) for p in json.loads(cache.read_text(encoding="utf-8"))]
    import soundfile as sf
    if _modelo_orig is None:
        _modelo_orig = whisper(cfg()["modelo_legenda"])
    out, desloc = [], 0.0
    for i, (a, b) in enumerate(trechos):
        wav = tmp / f"orig_{i:02d}.wav"
        rodar(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", fonte, "-vn", "-ac", "1",
               "-ar", "16000", wav])
        x, _ = sf.read(str(wav), dtype="float32")
        segs, _ = _modelo_orig.transcribe(x, language=cfg()["idioma"], word_timestamps=True, vad_filter=True,
                                          condition_on_previous_text=False)
        out += [(w.word.strip(), w.start + desloc, w.end + desloc) for s in segs for w in (s.words or []) if w.word.strip()]
        desloc += b - a
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# ---------------------------------------------------------------- encoder
def _encoder():
    r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    if "h264_nvenc" in r.stdout:
        teste = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1", "-c:v", "h264_nvenc",
                                "-f", "null", "-"], capture_output=True)
        if teste.returncode == 0:
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-maxrate", "16M",
                    "-bufsize", "32M", "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high"]


# ---------------------------------------------------------------- render
def render_corte(c, pasta_saida, tmp_raiz, voz=None, legendar_original=True, zoom=1.25):
    c_ = cfg()
    fonte = c["fonte"]
    info = sondar(fonte)
    trechos = [(segundos(a), segundos(b)) for a, b in c["trechos"]]
    dur = sum(b - a for a, b in trechos)
    if dur > c_["limite_segundos"]:
        raise SystemExit(f"corte {c['id']}: {dur:.0f}s passa do limite de {c_['limite_segundos']}s")
    tmp = Path(tmp_raiz) / c["id"]
    tmp.mkdir(parents=True, exist_ok=True)
    voz = voz or Voz()

    # palavras do áudio original e da narração (a narração tem prioridade)
    palavras = palavras_originais(fonte, trechos, tmp) if legendar_original and info["audio"] else []
    narr = np.zeros(int((dur + 1) * 48000), dtype="float32")
    janelas, pal_narr = [], []
    import soundfile as sf
    for k, n in enumerate(c.get("narracao", [])):
        wav = voz.gerar(n["texto"], str(tmp / f"narr_{k:02d}.wav"))
        x, _ = sf.read(wav, dtype="float32")
        i0 = int(n["t"] * 48000)
        x = x[: max(0, len(narr) - i0)]
        narr[i0:i0 + len(x)] += x
        janelas.append((n["t"], n["t"] + len(x) / 48000))
        pal_narr += [(w, s + n["t"], e + n["t"]) for w, s, e in tempos_das_palavras(wav, n["texto"])]
    palavras = [p for p in palavras if not any(p[2] > a - 0.4 and p[1] < b + 0.05 for a, b in janelas)]
    palavras = sorted(palavras + pal_narr, key=lambda p: p[1])
    narr_wav = tmp / "narracao.wav"
    sf.write(str(narr_wav), narr, 48000)

    # layout: sempre tela cheia (sem fundo borrado)
    fps = 60 if info["fps"] >= 50 else 30
    gw = int(W * zoom) // 2 * 2
    gh = int(gw * info["h"] / info["w"]) // 2 * 2
    cam = c.get("camera")
    if cam:
        cx, cy, cw, ch = [int(v) // 2 * 2 for v in cam]
        cam_h = min(int(W * ch / cw) // 2 * 2, 720)
        topo, faixa = cam_h, H - cam_h
        y_tit, y_leg = cam_h, min(cam_h + int((H - cam_h) * 0.55), H - 520)
    else:
        topo, faixa, y_tit, y_leg = 0, H, None, H - 620
    if gh < faixa:
        gh = faixa // 2 * 2
        gw = max(W, int(gh * info["w"] / info["h"]) // 2 * 2)
    legenda = tmp / "legenda.ass"
    escrever_legenda(legenda, dur, c.get("titulo", ""), c.get("credito", ""), palavras, y_leg, y_tit)

    cmd = ["ffmpeg", "-v", "error", "-y"]
    for a, b in trechos:
        cmd += ["-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", fonte]
    cmd += ["-i", narr_wav]
    n, f = len(trechos), []
    for i in range(n):
        f.append(f"[{i}:v]fps={fps},scale={info['w']}:{info['h']},setsar=1,format=yuv420p[v{i}]")
        f.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]" if info["audio"] else
                 f"anullsrc=r=48000:cl=stereo,atrim=0:{trechos[i][1] - trechos[i][0]:.3f}[a{i}]")
    f.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    f.append("[vc]split=2[s1][s2]")
    f.append(f"[s1]scale={gw}:{gh},crop={W}:{faixa}[jogo]")
    if cam:
        f.append(f"[s2]crop={cw}:{ch}:{cx}:{cy},scale={W}:{cam_h}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{cam_h}[cam]")
        f.append(f"color=c=black:s={W}x{H}:r={fps}[base];[base][cam]overlay=0:0:shortest=1[b1];"
                 f"[b1][jogo]overlay=0:{topo}[comp]")
    else:
        f.append("[s2]nullsink")
        f.append(f"color=c=black:s={W}x{H}:r={fps}[base];[base][jogo]overlay=0:0:shortest=1[comp]")
    caminho_leg = str(legenda).replace("\\", "/").replace(":", "\\:")
    fontes = "C\\:/Windows/Fonts" if os.name == "nt" else "/usr/share/fonts"
    f.append(f"[comp]subtitles=filename='{caminho_leg}':fontsdir='{fontes}'[vout]")
    f.append(f"[{n}:a]aformat=channel_layouts=stereo,asplit=2[n1][n2]")
    f.append("[ac]volume=0.9[ao];[ao][n1]sidechaincompress=threshold=0.015:ratio=10:attack=15:release=350[duck]")
    f.append("[duck][n2]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    nome = f"{c['id']} - {nome_arquivo(c.get('titulo', 'corte'))}"
    if voz.rascunho and c.get("narracao"):
        nome += " (RASCUNHO)"
    temporario = pasta_saida / f"_{c['id']}_render.mp4"
    cmd += ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]", *_encoder(),
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{dur:.3f}", temporario]
    rodar(cmd)
    corrigir_volume(temporario)
    rodar(["ffmpeg", "-v", "error", "-i", temporario, "-f", "null", "-"])  # decodifica inteiro antes de liberar
    final = pasta_saida / f"{nome}.mp4"
    final.unlink(missing_ok=True)
    os.replace(temporario, final)
    p = c.get("post", {})
    texto = f"TÍTULO:\n{p.get('titulo', c.get('titulo', ''))}\n\nDESCRIÇÃO:\n{p.get('descricao', '')}\n"
    if c.get("credito"):
        texto += f"\nCréditos: {c['credito']}\n"
    texto += f"\n{p.get('hashtags', '#shorts')}\n"
    final.with_suffix(".txt").write_text(texto, encoding="utf-8")
    print(f"ok  {final.name}  ({int(dur // 60)}:{dur % 60:04.1f})")
    return final
