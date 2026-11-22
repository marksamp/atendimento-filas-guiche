"""Ponto de entrada do app Guichê."""
import logging
import sys
from logging.handlers import RotatingFileHandler

import customtkinter as ctk

from config import APP_NAME, VERSAO
from services.config_store import pasta_config


def _configurar_log() -> None:
    pasta = pasta_config() / "logs"
    pasta.mkdir(exist_ok=True)
    arquivo = RotatingFileHandler(pasta / "guiche.log", maxBytes=2_000_000,
                                  backupCount=5, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    arquivo.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[arquivo, console])
    logging.getLogger("mysql.connector").setLevel(logging.WARNING)


def _hook(log: logging.Logger):
    def tratar(tipo, valor, tb):
        if issubclass(tipo, KeyboardInterrupt):
            log.info("Interrompido pelo usuário.")
        else:
            log.critical("Erro fatal.", exc_info=(tipo, valor, tb))
    return tratar


def main() -> None:
    _configurar_log()
    log = logging.getLogger("main")
    sys.excepthook = _hook(log)
    log.info("Iniciando %s v%s.", APP_NAME, VERSAO)

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    from app import App
    app = App()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        log.info("Interrompido pelo usuário; encerrando sessão.")
        try:
            if app.winfo_exists():
                app._fechar()       # encerra a sessão e libera o guichê
        except Exception:  # noqa: BLE001
            log.exception("Falha ao encerrar após interrupção.")


if __name__ == "__main__":
    main()
