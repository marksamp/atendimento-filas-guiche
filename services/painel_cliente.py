"""
Cliente HTTP do servidor de mídias dos painéis (servidor_midias.py).

- Sem proxy (rede local). Todas as rotas usam o cabeçalho de token.
- Erros viram ErroPainel(codigo, mensagem): 0 = sem conexão; demais = HTTP.
- enviar(): progresso(enviados, total) a cada bloco lido pelo http.client.
"""
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from config_slideshow import SLIDESHOW

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ErroPainel(Exception):
    def __init__(self, codigo: int, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


class _Leitor:
    """Arquivo que avisa os bytes lidos (http.client envia em blocos via read())."""

    def __init__(self, f, total: int, progresso: Optional[Callable[[int, int], None]]):
        self._f, self._total, self._cb, self._n = f, total, progresso, 0

    def read(self, n: int = -1) -> bytes:
        bloco = self._f.read(n)
        if bloco and self._cb:
            self._n += len(bloco)
            self._cb(self._n, self._total)
        return bloco


def _url(ip: str, porta: int, rota: str) -> str:
    host = f"[{ip}]" if ":" in ip else ip
    return f"http://{host}:{int(porta)}{rota}"


def _mensagem(exc: urllib.error.HTTPError) -> str:
    try:
        return json.loads(exc.read().decode() or "{}").get("erro") or str(exc.reason)
    except Exception:  # noqa: BLE001
        return str(exc.reason)


def _abrir(req: urllib.request.Request, timeout: float):
    try:
        return _OPENER.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise ErroPainel(exc.code, f"HTTP {exc.code}: {_mensagem(exc)}") from exc
    except urllib.error.URLError as exc:
        raise ErroPainel(0, f"Sem conexão ({exc.reason}).") from exc
    except OSError as exc:
        raise ErroPainel(0, f"Sem conexão ({exc}).") from exc


def testar_tcp(ip: str, porta: int) -> None:
    try:
        with socket.create_connection((ip, int(porta)), timeout=SLIDESHOW.timeout_status_s):
            pass
    except OSError as exc:
        raise ErroPainel(0, f"Porta {porta} inacessível em {ip} ({exc}).") from exc


def status(ip: str, porta: int, token: str) -> dict:
    req = urllib.request.Request(_url(ip, porta, "/status"),
                                 headers={SLIDESHOW.cabecalho_token: token})
    try:
        with _abrir(req, SLIDESHOW.timeout_status_s) as r:
            dados = json.loads(r.read().decode() or "{}")
    except (OSError, ValueError) as exc:
        if isinstance(exc, ErroPainel):
            raise
        raise ErroPainel(0, f"Resposta inválida do painel ({exc}).") from exc
    return dados if isinstance(dados, dict) else {}


def enviar(ip: str, porta: int, token: str, caminho: Path, nome: str,
           progresso: Optional[Callable[[int, int], None]] = None) -> bool:
    """True = gravado agora; False = o painel já tinha o arquivo."""
    tamanho = caminho.stat().st_size
    with open(caminho, "rb") as f:
        req = urllib.request.Request(
            _url(ip, porta, f"/midias/{nome}"), data=_Leitor(f, tamanho, progresso),
            method="PUT",
            headers={SLIDESHOW.cabecalho_token: token, "Content-Length": str(tamanho),
                     "Content-Type": "application/octet-stream"})
        try:
            with _abrir(req, SLIDESHOW.timeout_envio_s) as r:
                return r.status == 201
        except ErroPainel:
            raise
        except OSError as exc:
            raise ErroPainel(0, f"Envio interrompido ({exc}).") from exc


def baixar(ip: str, porta: int, token: str, nome: str, destino: Path, max_bytes: int) -> None:
    req = urllib.request.Request(_url(ip, porta, f"/midias/{nome}"),
                                 headers={SLIDESHOW.cabecalho_token: token})
    try:
        with _abrir(req, SLIDESHOW.timeout_envio_s) as r:
            tamanho = int(r.headers.get("Content-Length") or 0)
            if tamanho <= 0 or tamanho > max_bytes:
                raise ErroPainel(413, "Tamanho do arquivo inválido.")
            restante = tamanho
            with open(destino, "wb") as f:
                while restante > 0:
                    bloco = r.read(min(SLIDESHOW.bloco_bytes, restante))
                    if not bloco:
                        raise ErroPainel(0, "Download incompleto.")
                    f.write(bloco)
                    restante -= len(bloco)
    except ErroPainel:
        raise
    except (OSError, ValueError) as exc:
        raise ErroPainel(0, f"Download interrompido ({exc}).") from exc
