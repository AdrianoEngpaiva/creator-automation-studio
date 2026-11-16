"""Escuta a fonte inteira: transcrição com tempo por palavra, picos de volume, picos do chat e blocos para leitura.

Cada bloco vira um .txt com linhas "[hh:mm:ss] fala" e duas marcas que ajudam a achar momentos:
  [ALTO +11dB]  a fala ficou bem acima do volume normal daquele trecho (grito, susto, surto)
  [CHAT 3.4x]   o chat do replay andou 3,4x mais rápido que o normal ali
"""
import json
import time

import numpy as np

from .config import cfg, whisper
from .fonte import baixar_audio, baixar_chat
from .util import gravar_json, hms, ler_json, rodar

SR = 16000


def audio_16k(pasta):
    wav = pasta / "audio16k.wav"
    if not wav.exists():
        rodar(["ffmpeg", "-v", "error", "-y", "-i", baixar_audio(pasta), "-ac", "1", "-ar", str(SR), wav])
    return wav


def carregar(wav):
    import soundfile as sf
    x, sr = sf.read(str(wav), dtype="float32")
    assert sr == SR, "esperado WAV mono 16 kHz"
    return x


def transcrever(pasta, modelo=None, idioma=None):
    saida = pasta / "transcricao.json"
    if saida.exists():
        return ler_json(saida)
    c = cfg()
    x = carregar(audio_16k(pasta))
    m = whisper(modelo or c["modelo_escuta"])
    segs, info = m.transcribe(x, language=idioma or c["idioma"], word_timestamps=True, vad_filter=True,
                              beam_size=5, condition_on_previous_text=False)
    out, t0, ultimo = [], time.time(), 0.0
    for s in segs:
        out.append({"ini": round(s.start, 2), "fim": round(s.end, 2), "texto": s.text.strip(),
                    "palavras": [[w.word.strip(), round(w.start, 2), round(w.end, 2)] for w in (s.words or [])]})
        if s.end - ultimo > 300:
            ultimo = s.end
            print(f"  {hms(s.end)} transcrito ({time.time() - t0:.0f}s)", flush=True)
    dados = {"idioma": info.language, "duracao": info.duration, "segmentos": out}
    gravar_json(saida, dados)
    return dados


def picos_de_volume(pasta, janela=150):
    """Segundos em que o volume passa muito do 'normal' local (mediana móvel dos trechos com fala)."""
    saida = pasta / "volume.json"
    if saida.exists():
        return ler_json(saida)
    x = carregar(audio_16k(pasta))
    n = len(x) // SR
    db = 20 * np.log10(np.sqrt((x[: n * SR].reshape(n, SR) ** 2).mean(1)) + 1e-9)
    com_fala = db > np.percentile(db, 20)
    base = np.empty(n)
    for i in range(0, n, 30):  # a base muda devagar: recalcula a cada 30 s
        a, b = max(0, i - janela), min(n, i + janela)
        trecho = db[a:b][com_fala[a:b]]
        base[i:i + 30] = np.median(trecho) if trecho.size else np.median(db)
    excesso = db - base
    limite = max(8.0, float(np.percentile(excesso, 98)))
    picos = [[int(i), round(float(excesso[i]), 1)] for i in np.flatnonzero(excesso >= limite)]
    gravar_json(saida, picos)
    return picos


def picos_do_chat(pasta, caixa=10, janela=30):
    arq = baixar_chat(pasta)
    if not arq:
        return []
    tempos = []
    for linha in arq.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            tempos.append(int(json.loads(linha)["replayChatItemAction"]["videoOffsetTimeMsec"]) / 1000)
        except (KeyError, ValueError, json.JSONDecodeError):
            pass
    if len(tempos) < 50:
        return []
    contagem = np.bincount((np.asarray(tempos) // caixa).astype(int))
    picos = []
    for i, c in enumerate(contagem):
        normal = max(1.0, float(np.median(contagem[max(0, i - janela): i + janela])))
        if c >= 8 and c / normal >= 2.5:
            picos.append([i * caixa, round(c / normal, 1)])
    return picos


def escrever_blocos(pasta, trans, volume, chat, minutos=None):
    passo = (minutos or cfg()["bloco_minutos"]) * 60
    (pasta / "blocos").mkdir(exist_ok=True)
    (pasta / "momentos").mkdir(exist_ok=True)
    alto = dict((s, e) for s, e in volume)
    segs = trans["segmentos"]
    fim = segs[-1]["fim"] if segs else 0
    feitos = 0
    for k, ini in enumerate(range(0, int(fim) + 1, passo), start=1):
        linhas = []
        for s in segs:
            if not ini <= s["ini"] < ini + passo:
                continue
            marca = ""
            pico = max((alto.get(t, 0) for t in range(int(s["ini"]), int(s["fim"]) + 1)), default=0)
            if pico:
                marca += f"  [ALTO +{pico:.0f}dB]"
            ch = max((r for t, r in chat if s["ini"] - 10 <= t <= s["fim"]), default=0)
            if ch:
                marca += f"  [CHAT {ch}x]"
            linhas.append(f"[{hms(s['ini'])}] {s['texto']}{marca}")
        if linhas:
            feitos += 1
            cab = (f"# BLOCO {k:02d} — de {hms(ini)} a {hms(ini + passo)}\n"
                   f"# Momentos deste bloco vão em: momentos/bloco_{k:02d}.json\n\n")
            (pasta / "blocos" / f"bloco_{k:02d}.txt").write_text(cab + "\n".join(linhas) + "\n", encoding="utf-8")
    return feitos


def folhas_de_quadros(pasta, passo=15):
    """Para vídeo do disco (ex.: gameplay sem fala): folhas 6x5 com um quadro a cada `passo` s e o tempo escrito."""
    info = ler_json(pasta / "info.json", {})
    destino = pasta / "quadros"
    if not info.get("local") or list(destino.glob("folha_*.jpg")):
        return
    destino.mkdir(exist_ok=True)
    rodar(["ffmpeg", "-v", "error", "-y", "-i", info["url"], "-vf",
           f"fps=1/{passo},scale=320:-2,drawtext=font=Arial:text='%{{pts\\:hms}}':x=6:y=6:fontsize=22:"
           "fontcolor=yellow:box=1:boxcolor=black@0.6,tile=6x5", "-q:v", "4", destino / "folha_%02d.jpg"])


def preparar(pasta, modelo=None, idioma=None):
    print("[1/3] separando o áudio…")
    audio_16k(pasta)
    folhas_de_quadros(pasta)
    print("[2/3] transcrevendo…")
    trans = transcrever(pasta, modelo, idioma)
    print("[3/3] marcando picos de volume e de chat…")
    volume, chat = picos_de_volume(pasta), picos_do_chat(pasta)
    n = escrever_blocos(pasta, trans, volume, chat)
    print(f"pronto: {n} blocos em {pasta / 'blocos'} · {len(volume)} s de pico de volume · {len(chat)} picos de chat")
    return n
