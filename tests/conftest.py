import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_FEED = Path(__file__).parent.parent / "examples" / "sample-feed.xml"


class FeedServer:
    """A local HTTP server whose responses are set per path by each test."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self.delay = 0.0
        # If set, every request waits until this many requests are being handled at once.
        self.barrier: threading.Barrier | None = None
        self.requests: list[dict[str, str]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server.requests.append(dict(self.headers.items()))
                time.sleep(server.delay)
                status, headers, body = server.routes.get(self.path, (404, {}, b"not found"))
                if server.barrier is not None:
                    try:
                        server.barrier.wait()
                    except threading.BrokenBarrierError:
                        status, headers, body = 503, {}, b"requests were not concurrent"
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                if "Content-Length" not in headers:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}{path}"


@pytest.fixture
def feed_server() -> Iterator[FeedServer]:
    server = FeedServer()
    thread = threading.Thread(
        target=server.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield server
    server.httpd.shutdown()
    server.httpd.server_close()
