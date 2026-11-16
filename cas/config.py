"""Onde ficam os dados, a configuração e os segredos. Nada pessoal fica no código.

Tudo sai de variáveis de ambiente ou de `<CAS_HOME>/config.json` (veja config/config.example.json):
  CAS_HOME      pasta de trabalho (padrão: ~/creator-automation-studio)
  CAS_TRABALHO  CAS_SAIDA  CAS_SEGREDOS  CAS_CONTAS   para separar cada pasta, se quiser
"""
import glob
import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("CAS_HOME", Path.home() / "creator-automation-studio"))
TRABALHO = Path(os.environ.get("CAS_TRABALHO", HOME / "trabalho"))  # áudio, transcrição, blocos e trechos
SAIDA = Path(os.environ.get("CAS_SAIDA", HOME / "saida"))            # vídeos prontos + .txt de postagem
MODELOS = HOME / "modelos"       # detector de rosto
SEGREDOS = Path(os.environ.get("CAS_SEGREDOS", HOME / "segredos"))  # credencial OAuth e tokens
CONFIG = HOME / "config.json"
CONTAS = Path(os.environ.get("CAS_CONTAS", HOME / "contas.json"))

PADRAO = {
    "idioma": "pt",
    "limite_segundos": 170,            # 2:50 — margem para o limite de 3 min do Shorts
    "duracao_min": 15,
    "bloco_minutos": 12,               # a IA lê a transcrição em blocos deste tamanho
    "modelo_escuta": "large-v3",       # transcrição da fonte inteira (GPU); "base" na CPU
    "modelo_legenda": "medium",
    "voz": {"motor": "voicestudio", "nome": "", "url": "http://127.0.0.1:3900/mcp/", "steps": 32, "velocidade": 1.05,
            "reserva": "pt-BR-AntonioNeural"},
    "legenda": {"fonte": "Arial Black", "tamanho": 78, "cor_destaque": "#FFD23F"},
    "dll_cuda_extra": [],              # pastas extras com cublas/cudnn (Windows), se precisar
}


def cfg():
    dados = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    out = {**PADRAO, **dados}
    out["voz"] = {**PADRAO["voz"], **dados.get("voz", {})}
    out["legenda"] = {**PADRAO["legenda"], **dados.get("legenda", {})}
    return out


def preparar_cuda():
    """No Windows, o faster-whisper precisa achar as DLLs do CUDA (pacotes nvidia-* ou pastas extras)."""
    if os.name != "nt":
        return
    site = Path(sys.executable).parent / "Lib" / "site-packages"
    pastas = glob.glob(str(site / "nvidia" / "*" / "bin")) + glob.glob(str(site / "torch" / "lib"))
    pastas += cfg().get("dll_cuda_extra", [])
    for d in pastas:
        if os.path.isdir(d):
            os.add_dll_directory(os.path.abspath(d))
            os.environ["PATH"] = os.path.abspath(d) + os.pathsep + os.environ.get("PATH", "")


def whisper(modelo):
    """Carrega o faster-whisper na GPU; sem GPU, cai para a CPU (int8)."""
    preparar_cuda()
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(modelo, device="cuda", compute_type="float16")
    except Exception:  # noqa: BLE001
        return WhisperModel(modelo if modelo not in ("large-v3", "medium") else "small", device="cpu", compute_type="int8")
