"""Narração: VoiceStudio local (TTS com voz clonada, servidor MCP por HTTP) com reserva no edge-tts.

O edge-tts é só para rascunho (não é licenciado para uso comercial): quando ele é usado, o vídeo sai marcado
"(RASCUNHO)" no nome do arquivo.
"""
import base64
import json
import os
import subprocess
import sys
import urllib.request

import numpy as np

from .config import cfg, whisper
from .util import rodar


class ClienteMCP:
    """Cliente mínimo de MCP por HTTP (JSON-RPC; respostas em SSE ou JSON)."""

    def __init__(self, url, cliente="creator-automation-studio"):
        self.url, self.sessao, self.n = url, None, 0
        self.cab = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                    "X-OmniVoice-Client-Id": os.environ.get("VOICESTUDIO_CLIENT_ID", "claude-code")}
        self._post({"jsonrpc": "2.0", "id": self._id(), "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                               "clientInfo": {"name": cliente, "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _id(self):
        self.n += 1
        return self.n

    def _post(self, corpo, timeout=900):
        cab = dict(self.cab)
        if self.sessao:
            cab["mcp-session-id"] = self.sessao
        resp = urllib.request.urlopen(urllib.request.Request(self.url, json.dumps(corpo).encode(), cab), timeout=timeout)
        self.sessao = resp.headers.get("mcp-session-id") or self.sessao
        texto = resp.read().decode("utf-8")
        msgs = [json.loads(l[6:]) for l in texto.splitlines() if l.startswith("data: ")]
        if not msgs and texto.strip().startswith("{"):
            msgs = [json.loads(texto)]
        return msgs[-1] if msgs else None

    def chamar(self, ferramenta, args):
        r = self._post({"jsonrpc": "2.0", "id": self._id(), "method": "tools/call",
                        "params": {"name": ferramenta, "arguments": args}})["result"]
        if r.get("isError"):
            raise RuntimeError(r["content"][0]["text"])
        txt = r["content"][0]["text"]
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            return txt


class Voz:
    def __init__(self, rascunho=False):
        self.c = cfg()["voz"]
        self.mcp, self.rascunho, self.perfil = None, rascunho, None
        if rascunho or self.c["motor"] != "voicestudio":
            self.rascunho = True
            return
        try:
            self.mcp = ClienteMCP(self.c["url"])
            vozes = self.mcp.chamar("list_voices", {})
            nome = self.c["nome"].lower()
            self.perfil = next(v for v in vozes if not nome or v["name"].lower() == nome)
            print(f"voz: VoiceStudio · {self.perfil['name']}")
        except Exception as e:  # noqa: BLE001
            print(f"!! VoiceStudio indisponível ({type(e).__name__}) → voz de rascunho (edge-tts)")
            self.mcp, self.rascunho = None, True

    def gerar(self, texto, destino):
        """Gera a fala em WAV mono 48 kHz, sem silêncio no começo."""
        if os.path.exists(destino):
            return destino
        bruto = str(destino) + ".src"
        if self.mcp:
            r = self.mcp.chamar("generate_speech", {"text": texto, "profile_id": self.perfil["id"],
                                                    "steps": self.c["steps"], "speed": self.c["velocidade"]})
            open(bruto, "wb").write(base64.b64decode(r["wav_base64"]))
        else:
            subprocess.run([sys.executable, "-m", "edge_tts", "--voice", self.c["reserva"], "--rate", "+8%",
                            "--text", texto, "--write-media", bruto], check=True, capture_output=True)
        rodar(["ffmpeg", "-v", "error", "-y", "-i", bruto, "-af",
               "silenceremove=start_periods=1:start_threshold=-45dB", "-ac", "1", "-ar", "48000", destino])
        os.remove(bruto)
        return destino


_modelo_fala = None


def tempos_das_palavras(wav, texto):
    """Tempo de cada palavra do TEXTO dentro do wav (whisper dá início/fim; o texto do roteiro manda na grafia)."""
    global _modelo_fala
    import soundfile as sf
    if _modelo_fala is None:
        _modelo_fala = whisper("small")
    x, sr = sf.read(str(wav), dtype="float32")
    x16 = np.interp(np.arange(0, len(x), sr / 16000), np.arange(len(x)), x).astype("float32")
    ditas = [w for s in _modelo_fala.transcribe(x16, language=cfg()["idioma"], word_timestamps=True)[0]
             for w in (s.words or [])]
    toks = texto.split()
    if len(ditas) == len(toks):
        return [(t, w.start, w.end) for t, w in zip(toks, ditas)]
    ini = ditas[0].start if ditas else 0.0
    fim = ditas[-1].end if ditas else len(x) / sr
    total = sum(len(t) + 1 for t in toks)
    out, c = [], ini
    for t in toks:  # distribui pelo tamanho de cada palavra
        d = (fim - ini) * (len(t) + 1) / total
        out.append((t, c, c + d))
        c += d
    return out
