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


def janela_analisada(pasta):
    """(de, ate) em segundos da fonte original que o audio16k.wav cobre (None = começo/fim)."""
    j = ler_json(pasta / "janela.json", {})
    return j.get("de"), j.get("ate")


def audio_16k(pasta, ate=None, de=None):
    """WAV mono 16 kHz da fonte. `de`/`ate` (segundos) analisam só um trecho — útil em lives de muitas horas.
    Os tempos de tudo que sai daqui (transcrição, picos, blocos) continuam sendo os da fonte original."""
    wav = pasta / "audio16k.wav"
    pedido = {"de": float(de) if de else None, "ate": float(ate) if ate else None}
    if wav.exists() and (de is not None or ate is not None):
        atual = dict(zip(("de", "ate"), janela_analisada(pasta)))
        if atual != pedido:  # mudou o trecho analisado: refaz o áudio e o que depende dele
            wav.unlink()
            for velho in ("transcricao.json", "transcricao.parcial.json", "volume.json"):
                (pasta / velho).unlink(missing_ok=True)
            for velho in list((pasta / "blocos").glob("*.txt")) if (pasta / "blocos").exists() else []:
                velho.unlink()
    if not wav.exists():
        corte = (["-ss", f"{pedido['de']:.0f}"] if pedido["de"] else []) + (
            ["-t", f"{pedido['ate'] - (pedido['de'] or 0):.0f}"] if pedido["ate"] else [])
        rodar(["ffmpeg", "-v", "error", "-y", *corte[:2], "-i", baixar_audio(pasta), *corte[2:], "-ac", "1",
               "-ar", str(SR), wav])
        gravar_json(pasta / "janela.json", pedido)
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
    # em pedaços: lives de 10 h não cabem na memória de uma vez (o espectrograma passa de 7 GB)
    pedaco = 30 * 60 * SR
    out, t0, lingua = [], time.time(), idioma or c["idioma"]
    parcial = pasta / "transcricao.parcial.json"
    feito = ler_json(parcial, {"ate": 0, "segmentos": []})
    out = feito["segmentos"]
    inicio = janela_analisada(pasta)[0] or 0.0
    for ini in range(feito["ate"], len(x), pedaco):
        desloc = inicio + ini / SR
        segs, info = m.transcribe(x[ini:ini + pedaco], language=lingua, word_timestamps=True, vad_filter=True,
                                  beam_size=5, condition_on_previous_text=False)
        lingua = lingua or info.language
        for s in segs:
            out.append({"ini": round(s.start + desloc, 2), "fim": round(s.end + desloc, 2), "texto": s.text.strip(),
                        "palavras": [[w.word.strip(), round(w.start + desloc, 2), round(w.end + desloc, 2)]
                                     for w in (s.words or [])]})
        gravar_json(parcial, {"ate": ini + pedaco, "segmentos": out})  # retomável se cair no meio
        print(f"  {hms(inicio + min(len(x), ini + pedaco) / SR)} de {hms(inicio + len(x) / SR)} transcrito "
              f"({time.time() - t0:.0f}s)", flush=True)
    dados = {"idioma": lingua, "duracao": inicio + len(x) / SR, "segmentos": out}
    gravar_json(saida, dados)
    parcial.unlink(missing_ok=True)
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
    inicio = int(janela_analisada(pasta)[0] or 0)
    picos = [[inicio + int(i), round(float(excesso[i]), 1)] for i in np.flatnonzero(excesso >= limite)]
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


def preparar(pasta, modelo=None, idioma=None, ate=None, de=None):
    trecho = f" (de {hms(de or 0)} até {hms(ate) if ate else 'o fim'})" if (de or ate) else ""
    print("[1/3] separando o áudio…" + trecho)
    audio_16k(pasta, ate, de)
    folhas_de_quadros(pasta)
    print("[2/3] transcrevendo…")
    trans = transcrever(pasta, modelo, idioma)
    print("[3/3] marcando picos de volume e de chat…")
    volume, chat = picos_de_volume(pasta), picos_do_chat(pasta)
    n = escrever_blocos(pasta, trans, volume, chat)
    print(f"pronto: {n} blocos em {pasta / 'blocos'} · {len(volume)} s de pico de volume · {len(chat)} picos de chat")
    return n
