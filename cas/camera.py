"""Acha a câmera do streamer (o rosto que fica parado no mesmo lugar) e devolve o recorte para a faixa de cima.

Modelo: OpenCV YuNet (face_detection_yunet_2023mar.onnx, licença MIT), baixado por `cas instalar`.
Ideia: amostra quadros ao longo do trecho, detecta rostos, agrupa os centros numa grade grossa e fica com o grupo
que aparece na maior parte dos quadros. Rosto que anda pela tela (personagem do jogo) não forma grupo estável.
"""
from .config import MODELOS

YUNET = MODELOS / "face_detection_yunet_2023mar.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
PROPORCAO_FAIXA = 1080 / 720  # largura/altura da faixa da câmera no vídeo vertical


def detectar(video, amostras=20, confianca=0.8):
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    escala = 640 / W
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (640, int(H * escala)), confianca)
    caixas = []  # (quadro, x, y, w, h) em pixels do vídeo original
    for k in range(amostras):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / amostras))
        ok, q = cap.read()
        if not ok:
            continue
        _, rostos = det.detect(cv2.resize(q, (640, int(H * escala))))
        for r in (rostos if rostos is not None else []):
            x, y, w, h = (float(v) / escala for v in r[:4])
            if h > H * 0.04:  # ignora rostos minúsculos
                caixas.append((k, x, y, w, h))
    cap.release()
    if not caixas:
        return W, H, None
    # agrupa por célula de uma grade 8x8 (centro do rosto)
    grupos = {}
    for k, x, y, w, h in caixas:
        cel = (int((x + w / 2) / W * 8), int((y + h / 2) / H * 8))
        grupos.setdefault(cel, []).append((k, x, y, w, h))
    cel, membros = max(grupos.items(), key=lambda kv: len({m[0] for m in kv[1]}))
    if len({m[0] for m in membros}) < amostras * 0.3:  # precisa aparecer em ≥ 30% dos quadros
        return W, H, None
    rosto = np.median(np.array([m[1:] for m in membros]), axis=0)
    return W, H, tuple(float(v) for v in rosto)


def recorte_da_faixa(W, H, rosto, folga=3.0):
    """Retângulo [x, y, w, h] em volta do rosto, na proporção da faixa de cima (rosto um pouco acima do centro)."""
    fx, fy, fw, fh = rosto
    w = min(W, max(fw * folga, 240.0))
    h = w / PROPORCAO_FAIXA
    if h > H:
        h, w = float(H), H * PROPORCAO_FAIXA
    x = min(max(fx + fw / 2 - w / 2, 0), W - w)
    y = min(max(fy + fh * 0.6 - h / 2, 0), H - h)
    return [int(x) // 2 * 2, int(y) // 2 * 2, int(w) // 2 * 2, int(h) // 2 * 2]


def achar_camera(video):
    W, H, rosto = detectar(video)
    return recorte_da_faixa(W, H, rosto) if rosto else None
