#!/usr/bin/env python3
import asyncio
import shutil
import signal
import watchdog.events
from hachiko.hachiko import AIOWatchdog, AIOEventHandler
from aiohttp import web
import os
import os.path
import argparse
import functools
import webbrowser
import tempfile
import logging
from socket import socket
import urllib

# This was added in 3.5.1.
try:
    from asyncio import run_coroutine_threadsafe
except ImportError:
    def run_coroutine_threadsafe(coro, loop):
        def f():
            loop.create_task(coro)
        loop.call_soon_threadsafe(f)


async def update_html(rstfile, dest, ev=None):
    """Convert rstfile to HTML file dest. Optionally fire ev upon completion."""
    logger.debug("Converting %s -> %s", rstfile, dest)
    p = await asyncio.create_subprocess_shell(
            "rst2html5 {} {}".format(rstfile, dest))
    await p.wait()
    logger.debug("Done updating")
    if ev is not None:
        logger.debug("Firing update event")
        ev.set()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<style>
body {{
    margin: 0;            /* Reset default margin */
}}
iframe {{
    display: block;       /* iframes are inline by default */
    background: #fff;
    border: none;         /* Reset default border */
    height: 100vh;        /* Viewport-relative units */
    width: 100vw;
}}
</style>
<meta charset="UTF-8">
</head>
<body>
  <iframe id="rst" src="{iframe_src}"></iframe>
   
  <script type="text/javascript">
    var ws = new WebSocket("ws://localhost:{port}/ws")
        
    ws.onmessage = function(event) {{
        console.log('updating');
        document.getElementById("rst").contentWindow.location.reload();
    }};
     
    ws.onerror = function(event){{
        console.log("Error ", event)
    }}
</script>
</body>
</html>
"""


# Coroutine which opens browser to URL
async def open_browser(url):
    """Open a browser window to URL."""
    logger.debug("Opening browser url {}".format(url))
    webbrowser.open(url, new=0)


# Watch for changes to file
class FileWatcher(watchdog.events.PatternMatchingEventHandler):
    def __init__(self, loop, ev, filename, dest):
        """Monitor filename for changes. Upon a change, convert filename
        to HTML and save to dest by injecting a routine into event loop,
        and fire event ev.
        """
        super().__init__(
            patterns=['*/' + os.path.basename(filename)],
            ignore_directories=True)
        self._loop = loop
        self._ev = ev
        self._fn = filename
        self._dest = dest

    def on_modified(self, event):
        self._update(event)

    def on_created(self, event):
        self._update(event)

    def _update(self, event):
        update_coro = update_html(self._fn, self._dest, self._ev)
        run_coroutine_threadsafe(update_coro, self._loop)


async def watch(dir, watcher):
    """Start watchdog thread monitoring changes to dir."""
    watcher = AIOWatchdog(dir, False, watcher)
    watcher.start()


async def ws_handler(ev, request):
    """Handle initial WebSocket request. Socket is kept open and change messages
    are pushed back to client when event ev fires."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    logger.debug(request)
    while True:
        await ev.wait()
        logger.debug("Sending update to ws")
        ws.send_str("update")
        ev.clear()
    return ws


def main():
    parser = argparse.ArgumentParser("rstviewer")
    parser.add_argument('-v', '--verbose', action='count', default=0, help='verbosity level')
    parser.add_argument("file", metavar="file.rst", help="File to preview")
    args = parser.parse_args()
    lvl = logging.ERROR
    if args.verbose == 1:
        lvl = logging.INFO
    elif args.verbose >= 2:
        lvl = logging.DEBUG
    logging.getLogger().setLevel(lvl)

    # Extract directory from filename. watchdog monitors a whole
    # directory.
    abspath = os.path.abspath(args.file)
    fn = os.path.basename(abspath)
    dir = os.path.dirname(abspath)

    loop = asyncio.get_event_loop()
    # This event is used to communicate to the coroutine holding the web
    # socket this it should push an update.
    ev = asyncio.Event()

    app = web.Application(loop=loop)
    # This _iframe holds the actual converted RST
    iframe_path = os.path.join(dir, "_iframe.html")
    # Static routes to serve the initial .html files.
    app.router.add_static("/static", dir)
    # Set up the web socket handler.
    ws_h = functools.partial(ws_handler, ev)
    app.router.add_route("GET", "/ws", ws_h)
    handler = app.make_handler()
    sock = socket()
    # Port 0 => bind to a random port
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    # Add a second random port to service HTTP requests. This way,
    # we can serve images and stuff while holding open the websocket.
    sock2 = socket()
    # Port 0 => bind to a random port
    sock2.bind(('127.0.0.1', 0))
    port2 = sock2.getsockname()[1]

    html_name = "_" + fn + ".html"
    container_path = os.path.join(dir, html_name)
    iframe_url = "http://localhost:{port}/static/_iframe.html".format(
        port=port2)
    logger.debug("Creating container file at %s", container_path)
    open(container_path, "wt").write(HTML_TEMPLATE.format(
             iframe_src=iframe_url, port=port))

    # This starts the watchdog in another thread. It makes (thread-safe)
    # calls into the event loop to signal that a file has changed.
    watcher = FileWatcher(loop, ev, abspath, iframe_path)

    # Create tasks and run
    container_url = "http://localhost:{port}/static/{html_name}".format(port=port2, html_name=html_name)
    tasks = asyncio.gather(*[
        asyncio.ensure_future(x) for x in [
            update_html(abspath, iframe_path),
            watch(dir, watcher),
            loop.create_server(handler, sock=sock),
            loop.create_server(handler, sock=sock2)]
            ])
    loop.run_until_complete(tasks)
    asyncio.ensure_future(open_browser(container_url))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        for fn in [container_path, iframe_path]:
            try:
                os.unlink(fn)
            except OSError:
                pass


if __name__ == "__main__":
    main()
