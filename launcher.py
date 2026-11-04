"""Abre o Handcut em uma janela própria (pywebview), sem precisar do navegador.

Uso:  python launcher.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path

import webview
from werkzeug.serving import make_server

from app import LOG_FILE, app

WINDOW_TITLE = "Handcut"
# No Windows a janela usa o WebView2 (já vem no Windows 10/11 atualizados).
GUI = "edgechromium" if sys.platform == "win32" else None


class Api:
    """Funções que a página chama por window.pywebview.api (ver static/app.js)."""

    _window = None  # com "_" no começo, o pywebview não expõe este atributo à página

    def choose_video(self):
        """Abre o seletor de arquivos do sistema e devolve o caminho escolhido (ou None)."""
        result = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(Path.home() / "Videos"),
            allow_multiple=False,
            file_types=("Vídeos (*.mp4;*.webm)",),
        )
        return result[0] if result else None


def unblock_own_files() -> None:
    """Tira a marca "veio da internet" dos arquivos do programa (só no Windows, versão empacotada).

    Arquivos extraídos de um ZIP baixado recebem essa marca, e o .NET se recusa a carregar as
    DLLs marcadas, o que impede a janela de abrir. Sem a marca, o usuário não precisa
    desbloquear o ZIP à mão.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    for path in Path(sys.executable).parent.rglob("*"):
        if path.suffix.lower() in {".dll", ".exe", ".pyd"}:
            try:
                os.remove(f"{path}:Zone.Identifier")  # a marca fica em um fluxo alternativo do arquivo
            except OSError:
                pass  # arquivo sem marca (o normal) ou sem permissão


def start_server() -> int:
    """Sobe o servidor do app em uma porta livre (a porta 0 pede uma ao sistema) e devolve o número."""
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_port


def report_error(details: str) -> None:
    """Sem terminal, o erro vai para o handcut.log e, no Windows, para uma caixa de mensagem."""
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [launcher] {details}\n")
    except OSError:
        pass
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            "Não foi possível abrir o Handcut.\n\n"
            "Se o programa veio de um ZIP baixado, clique com o botão direito no ZIP, abra "
            "Propriedades, marque Desbloquear e extraia de novo.\n\n"
            f"Os detalhes estão em:\n{LOG_FILE}",
            WINDOW_TITLE,
            0x10,
        )


def main() -> None:
    unblock_own_files()
    # Sem isto, o link "Baixar" não faz nada dentro da janela. Com isto, o Windows abre
    # o "Salvar como", em que o usuário escolhe a pasta e o nome do arquivo.
    webview.settings["ALLOW_DOWNLOADS"] = True
    port = start_server()
    api = Api()
    api._window = webview.create_window(
        WINDOW_TITLE, f"http://127.0.0.1:{port}/", js_api=api,
        width=1100, height=900, min_size=(800, 600),
    )
    webview.start(gui=GUI)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        report_error(traceback.format_exc())
        raise