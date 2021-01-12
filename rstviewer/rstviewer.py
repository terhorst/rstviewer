#!/usr/bin/env python3
import argparse
import asyncio
import functools
import logging
import os
import os.path
import shlex
import webbrowser
from asyncio import run_coroutine_threadsafe
from socket import socket

import watchdog.events
from aiohttp import web
from hachiko.hachiko import AIOWatchdog


async def update_html(rstfile, dest, ev=None):
    """Convert rstfile to HTML file dest. Optionally fire ev upon completion."""
    logger.debug("Converting %s -> %s", rstfile, dest)
    p = await asyncio.create_subprocess_shell(
        " ".join(shlex.quote(arg) for arg in ["rst2html5", rstfile, dest])
    )  # this is shlex.join from 3.8 onwards
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
            patterns=["*/" + os.path.basename(filename)], ignore_directories=True
        )
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


async def run_server(sock, sock2, dir, ev):
    # create aiohttp application
    app = web.Application()
    app.router.add_static("/static", dir)
    # socket when it should push an update.
    ws_h = functools.partial(ws_handler, ev)
    app.router.add_route("GET", "/ws", ws_h)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.SockSite(runner, sock)
    site2 = web.SockSite(runner, sock2)
    await site.start()
    await site2.start()


async def ws_handler(ev, request):
    """Handle initial WebSocket request. Socket is kept open and change messages
    are pushed back to client when event ev fires."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    logger.debug(request)
    while True:
        await ev.wait()
        logger.debug("Sending update to ws")
        await ws.send_str("update")
        ev.clear()
    return ws


def main(test_mode=False):
    parser = argparse.ArgumentParser("rstviewer")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="verboseness, pass repeatedly to increase verbosity",
    )
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

    # Open ports used to serve
    sock = socket()
    # Port 0 => bind to a random port
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    # Add a second random port to service HTTP requests. This way,
    # we can serve images and stuff while holding open the websocket.
    sock2 = socket()
    # Port 0 => bind to a random port
    sock2.bind(("127.0.0.1", 0))
    port2 = sock2.getsockname()[1]

    # This _iframe holds the actual converted RST
    iframe_path = os.path.join(dir, "_iframe.html")

    html_name = "_" + fn + ".html"
    container_path = os.path.join(dir, html_name)
    iframe_url = "http://localhost:{port}/static/_iframe.html".format(port=port2)
    logger.debug("Creating container file at %s", container_path)
    open(container_path, "wt").write(
        HTML_TEMPLATE.format(iframe_src=iframe_url, port=port)
    )

    ev = asyncio.Event()
    # This starts the watchdog in another thread. It makes (thread-safe)
    # calls into the event loop to signal that a file has changed.
    watcher = FileWatcher(loop, ev, abspath, iframe_path)

    # Create tasks and run
    container_url = "http://localhost:{port}/static/{html_name}".format(
        port=port2, html_name=html_name
    )
    tasks = asyncio.gather(
        *[
            asyncio.ensure_future(x)
            for x in [
                update_html(abspath, iframe_path),
                watch(dir, watcher),
                run_server(sock, sock2, dir, ev),
            ]
        ]
    )
    loop.run_until_complete(tasks)
    if test_mode:
        # immediately exit. used for testing only.
        loop.call_soon_threadsafe(loop.stop)
    else:
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
