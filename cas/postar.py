"""Publica no YouTube pela API oficial (sem limite de tamanho), conta por conta, conferindo o canal.

- Contas em <CAS_HOME>/contas.json (veja config/contas.example.json); segredos em <CAS_HOME>/segredos/.
- O vídeo entra PRIVADO (projeto Google não verificado); depois muda-se para público no YouTube Studio.
- Só envia se o canal do token for o canal esperado da conta: nunca posta no canal errado.
- Registro em <pasta do vídeo>/postados.json: o mesmo arquivo não sobe duas vezes para a mesma conta.
"""
import json
import os
import re
import subprocess
import sys
import time

from .config import CONTAS as _CONTAS, SEGREDOS as _SEGREDOS

SEGREDOS = str(_SEGREDOS)
CLIENT = os.path.join(SEGREDOS, "client_secret.json")
CONTAS = str(_CONTAS)
ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]


def conta_cfg(nome):
    contas = json.load(open(CONTAS, encoding="utf8"))
    if nome not in contas:
        sys.exit(f"Conta '{nome}' não existe em {CONTAS}. Contas: {', '.join(contas)}")
    c = dict(contas[nome]); c["id"] = nome
    c["token"] = os.path.join(SEGREDOS, c.get("token", f"token_youtube_{nome}.json"))
    return c


def credenciais(conta, interativo=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    tok = conta["token"]
    cred = Credentials.from_authorized_user_file(tok, ESCOPOS) if os.path.exists(tok) else None
    if cred and cred.expired and cred.refresh_token:
        try:
            cred.refresh(Request())
        except Exception:  # noqa: BLE001 — token vencido (modo Testando: 7 dias) ou revogado
            cred = None
    if not cred or not cred.valid:
        if not interativo:
            sys.exit(f"Sem autorização válida para '{conta['id']}'. Rode: postar.py autorizar --conta {conta['id']}")
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT, ESCOPOS)
        # não abre o navegador padrão: o link precisa ser aberto no perfil do Chrome desta conta
        cred = flow.run_local_server(
            port=8765, prompt="consent", open_browser=False, timeout_seconds=900,
            authorization_prompt_message=f"ABRA NO PERFIL DO CHROME '{conta.get('perfil_chrome', conta['id'])}': {{url}}")
    open(tok, "w", encoding="utf8").write(cred.to_json())
    return cred


def youtube(conta, interativo=False):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credenciais(conta, interativo), cache_discovery=False)


def canal(yt):
    itens = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    return (itens[0]["snippet"]["title"], itens[0]["id"]) if itens else (None, None)


def garantir_canal(yt, conta):
    titulo, cid = canal(yt)
    if titulo != conta["canal_youtube"]:
        sys.exit(f"O token de '{conta['id']}' é do canal '{titulo}', não do '{conta['canal_youtube']}'. Nada enviado. "
                 f"Apague {conta['token']} e autorize de novo com a conta certa.")
    print(f"Canal: {titulo} ({cid})")


def ler_txt(mp4):
    txt = os.path.splitext(mp4)[0] + ".txt"
    if not os.path.exists(txt):
        return None, None
    t = open(txt, encoding="utf8").read()
    m = re.search(r"T[ÍI]TULO:\s*\n(.+?)\n\s*\n", t, re.S)
    d = re.search(r"DESCRI[ÇC][ÃA]O:\s*\n(.*)", t, re.S)
    return (m.group(1).strip() if m else None), (d.group(1).strip() if d else None)


def metadados(mp4, conta, titulo=None, descricao=None):
    t2, d2 = ler_txt(mp4)
    titulo = titulo or t2 or re.sub(r"^\d+\s*-\s*", "", os.path.splitext(os.path.basename(mp4))[0])
    descricao = descricao if descricao is not None else (d2 or "")
    if conta.get("formato") == "shorts" and "#shorts" not in (titulo + descricao).lower():
        descricao += "\n#shorts"
    for h in conta.get("hashtags_fixas", []):
        if h.lower() not in descricao.lower():
            descricao += f" {h}"
    titulo = re.sub(r"[<>]", "", titulo)[:100]
    descricao = re.sub(r"[<>]", "", descricao)[:4900]
    tags = sorted(set(h[1:] for h in re.findall(r"#\w+", descricao)))[:15]
    return titulo, descricao, tags


def checar_video(mp4, conta):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", mp4], capture_output=True, text=True)
    j = json.loads(r.stdout)
    w, h = j["streams"][0]["width"], j["streams"][0]["height"]
    dur = float(j["format"]["duration"])
    if conta.get("formato") == "shorts":
        if dur > 180:
            sys.exit(f"{os.path.basename(mp4)}: {dur:.0f}s — passa de 3 min, não é Short. Não enviei.")
        if h <= w:
            sys.exit(f"{os.path.basename(mp4)}: {w}x{h} não é vertical — não é Short. Não enviei.")
    return dur


def enviar(yt, conta, mp4, titulo=None, descricao=None, thumb=None):
    from googleapiclient.errors import HttpError, ResumableUploadError
    from googleapiclient.http import MediaFileUpload
    pasta = os.path.dirname(os.path.abspath(mp4))
    reg_p = os.path.join(pasta, "postados.json")
    reg = json.load(open(reg_p, encoding="utf8")) if os.path.exists(reg_p) else {}
    nome = os.path.basename(mp4)
    chave = f"youtube:{conta['id']}"
    antigo = reg.get(nome, {})
    if antigo.get(chave):
        vid = antigo[chave]
        print(f"  já enviado: {nome} → https://youtu.be/{vid}")
        return vid
    dur = checar_video(mp4, conta)
    titulo, descricao, tags = metadados(mp4, conta, titulo, descricao)
    corpo = {
        "snippet": {"title": titulo, "description": descricao, "tags": tags,
                    "categoryId": str(conta.get("categoria", "22")),
                    "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR"},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "embeddable": True},
    }
    print(f"  enviando {nome} ({int(dur // 60)}:{dur % 60:04.1f}, {os.path.getsize(mp4) / 1e6:.0f} MB)\n    título: {titulo}")
    media = MediaFileUpload(mp4, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=corpo, media_body=media)
    resp, tentativas = None, 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                print(f"    {int(status.progress() * 100)}%", flush=True)
        except (HttpError, ResumableUploadError, ConnectionError, TimeoutError) as e:
            if "quotaExceeded" in str(e) or "uploadLimitExceeded" in str(e):
                sys.exit("  Cota diária do YouTube esgotada (~6 envios/dia no projeto). Tente amanhã.")
            code = getattr(getattr(e, "resp", None), "status", 0)
            tentativas += 1
            if tentativas > 5 or (code and code < 500):
                raise
            time.sleep(2 ** tentativas)
    vid = resp["id"]
    if thumb:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb)).execute()
            print("    capa enviada")
        except Exception as e:  # noqa: BLE001 — conta sem verificação por telefone não pode pôr capa
            print(f"    capa não enviada ({str(e)[:120]}) — coloque pelo YouTube Studio")
    reg.setdefault(nome, {})[chave] = vid
    reg[nome][f"{chave}:quando"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(reg, open(reg_p, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"  OK → https://youtu.be/{vid}  (privado — mude para público no Studio)")
    return vid
