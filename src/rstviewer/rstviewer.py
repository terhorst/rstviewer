#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import os.path
import shutil
import subprocess
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import watchdog.events
import watchdog.observers
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).parent

ERROR_TEMPLATE = """
<html>
<head><title>Error</title></head>
<body style="font-family: monospace; padding: 2rem;">
<h4>Error during conversion</h4>
<code>{traceback}</code>
</body>
</html>
"""


# ── Conversion RST → HTML ────────────────────────────────────────────────────

def convert_rst(rstfile: str, dest: str, stylesheet: str | None = None):
    """Conversion synchrone — appelée depuis le thread watchdog ou le main."""
    logger.debug("Converting %s -> %s", rstfile, dest)
    cmd = ["rst2html5", "--traceback"]
    if stylesheet:
        cmd += [f"--stylesheet={stylesheet}"]
    cmd += [rstfile, dest]

    result = subprocess.run(cmd, capture_output=True)
    logger.debug("rst2html5 exited with code %d", result.returncode)

    if result.returncode != 0:
        with open(dest, "wt", encoding="utf-8") as f:
            f.write(
                ERROR_TEMPLATE.format(
                    traceback=result.stderr.decode().replace("\n", "<br/>")
                )
            )

# ── Watchdog ─────────────────────────────────────────────────────────────────
 
class FileWatcher(watchdog.events.FileSystemEventHandler):
    """Surveille un fichier .rst.
 
    A chaque changement : reconvertit le fichier (synchrone, dans le thread
    watchdog) puis lève un threading.Event pour signaler la boucle asyncio.
 
    Un debounce de DEBOUNCE_DELAY secondes évite les doubles événements
    émis par certains éditeurs ou par l'OS (contenu + métadonnées).
    """
 
    DEBOUNCE_DELAY = 0.15  # secondes
 
    def __init__(self, trigger: threading.Event,
                 filename: str, dest: str, stylesheet: str | None):
        super().__init__()
        self._trigger    = trigger
        self._filename   = os.path.abspath(filename)
        self._dest       = dest
        self._stylesheet = stylesheet
        self._timer: threading.Timer | None = None
        self._lock  = threading.Lock()
 
    def _matches(self, event) -> bool:
        return (
            not event.is_directory
            and os.path.abspath(event.src_path) == self._filename
        )
 
    def _handle(self, event):
        if not self._matches(event):
            return
        # Annule le timer précédent s'il n'a pas encore tiré
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.DEBOUNCE_DELAY, self._convert)
            self._timer.start()
 
    def _convert(self):
        convert_rst(self._filename, self._dest, self._stylesheet)
        self._trigger.set()
 
    def on_modified(self, event): self._handle(event)
    def on_created(self, event):  self._handle(event)

# ── WebSocket broadcast ───────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._clients.append(ws)
        logger.debug("WS client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self._clients:
                self._clients.remove(ws)
        logger.debug("WS client disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, message: str):
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                pass


# ── FastAPI app ───────────────────────────────────────────────────────────────

def build_app(static_dir: str, templates_dir: str,
              trigger: threading.Event) -> FastAPI:
    manager  = ConnectionManager()
    templates = Jinja2Templates(directory=templates_dir)

    stop = threading.Event()  # signale l'arrêt au thread executor
 
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def broadcaster():
            """Attend le threading.Event (sans bloquer la boucle asyncio)
            puis broadcast 'update' à tous les clients connectés."""
            loop = asyncio.get_running_loop()
            while True:
                # Attend avec timeout pour pouvoir détecter l'arrêt
                await loop.run_in_executor(None, lambda: trigger.wait(timeout=0.2))
                if stop.is_set():
                    break
                if trigger.is_set():
                    trigger.clear()
                    logger.debug("Broadcasting update")
                    await manager.broadcast("update")
 
        task = asyncio.create_task(broadcaster())
        yield
        stop.set()
        trigger.set()   # débloque immédiatement le wait en cours
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await manager.broadcast("close")

    app = FastAPI(lifespan=lifespan)
    app.state.manager = manager

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="viewer.html",
            context={"port": app.state.port},
        )

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            await manager.disconnect(websocket)

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    return app


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pick_free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _resolve_dirs(args) -> tuple[Path, Path]:
    templates_dir  = Path(args.templates_dir) if args.templates_dir \
                     else PACKAGE_DIR / "templates"
    package_static = PACKAGE_DIR / "static"
    return templates_dir, package_static


# ── Entry point ───────────────────────────────────────────────────────────────

def main(test_mode: bool = False):
    parser = argparse.ArgumentParser("rstviewer")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Augmente la verbosité (répéter pour plus)")
    parser.add_argument("-p", "--port", type=int, default=0,
                        help="Port d'écoute (défaut : aléatoire)")
    parser.add_argument("--no-style", action="store_true",
                        help="Désactive la feuille de style par défaut")
    parser.add_argument("--stylesheet",
                        help="Chemin ou URL vers une feuille de style CSS personnalisée")
    parser.add_argument("--templates-dir",
                        help="Répertoire contenant un viewer.html personnalisé")
    parser.add_argument("file", metavar="file.rst", help="Fichier à prévisualiser")
    args = parser.parse_args()

    lvl = logging.ERROR
    if args.verbose == 1:   lvl = logging.INFO
    elif args.verbose >= 2: lvl = logging.DEBUG
    logging.basicConfig(level=lvl)


    abspath     = os.path.abspath(args.file)
    rst_dir     = os.path.dirname(abspath)
    iframe_path = os.path.join(rst_dir, "_iframe.html")
    templates_dir, package_static = _resolve_dirs(args)

    to_remove = [iframe_path]


    if args.no_style:
        stylesheet = None
    elif args.stylesheet:
        stylesheet = args.stylesheet
    else:
        dest_css = os.path.join(rst_dir, "rstviewer.css")
        shutil.copy(str(package_static / "rstviewer.css"), dest_css)
        to_remove.append(dest_css)
        stylesheet = "/static/rstviewer.css"

    # Conversion initiale (synchrone, avant le démarrage du serveur)
    convert_rst(abspath, iframe_path, stylesheet)

    # threading.Event : pont thread-safe entre watchdog et asyncio
    trigger = threading.Event()

    watcher  = FileWatcher(trigger, abspath, iframe_path, stylesheet)
    observer = watchdog.observers.Observer()
    observer.schedule(watcher, path=rst_dir, recursive=False)
    observer.start()
    logger.debug("Watchdog started on %s", rst_dir)

    port = args.port if args.port != 0 else _pick_free_port()
    app  = build_app(rst_dir, str(templates_dir), trigger)
    app.state.port = port

    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    if not test_mode:
        url = f"http://127.0.0.1:{port}/"
        threading.Timer(0.5, lambda: webbrowser.open(url, new=0)).start()

    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        try:
            for f in to_remove:
                os.unlink(f)
                logger.debug("Removed %s", f)
        except OSError:
            pass


if __name__ == "__main__":
    main()