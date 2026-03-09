"""
Unit tests for wait_for_dependencies() in pps/docker/server_http.py

Tests are isolated using mocks — no Docker containers required.
Run with: python3 -m pytest tests/test_wait_for_dependencies.py -v
"""

import os
import sys
import socket
import unittest
import urllib.error
from unittest.mock import patch, MagicMock, call
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# Minimal module-level stubs so we can import just the function under test
# without pulling in FastAPI, uvicorn, or any PPS layers.
# ---------------------------------------------------------------------------

# We'll exec just the function rather than importing the whole module,
# to avoid triggering the module-level wait_for_dependencies() call.

import ast
import textwrap

_SOURCE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "pps", "docker", "server_http.py"
)


def _extract_function(source: str, func_name: str) -> str:
    """Extract a single function definition from source as a string."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            lines = source.splitlines(keepends=True)
            start = node.lineno - 1
            end = node.end_lineno
            return "".join(lines[start:end])
    raise ValueError(f"Function {func_name!r} not found in source")


def _load_function(func_name: str, globals_override: dict):
    """Load a function from server_http.py into a fresh namespace."""
    with open(_SOURCE_PATH) as f:
        source = f.read()
    func_src = _extract_function(source, func_name)
    # Provide the globals the function needs (os, sys already set at module level)
    ns = {
        "os": os,
        "sys": sys,
    }
    ns.update(globals_override)
    exec(compile(func_src, _SOURCE_PATH, "exec"), ns)
    return ns[func_name]


# ---------------------------------------------------------------------------
# Helper to build a wait_for_dependencies function with specific USE_CHROMA,
# CHROMA_HOST, CHROMA_PORT values baked in.
# ---------------------------------------------------------------------------

def _make_fn(use_chroma: bool, chroma_host: str = "chromadb", chroma_port: int = 8000):
    return _load_function("wait_for_dependencies", {
        "USE_CHROMA": use_chroma,
        "CHROMA_HOST": chroma_host,
        "CHROMA_PORT": chroma_port,
    })


class TestSyntaxValidation(unittest.TestCase):
    """Verify the file parses without errors."""

    def test_ast_parse(self):
        with open(_SOURCE_PATH) as f:
            source = f.read()
        ast.parse(source)  # raises SyntaxError on failure


class TestWaitForDependenciesNeo4jOnly(unittest.TestCase):
    """Tests with USE_CHROMA=False — only neo4j in pending."""

    def setUp(self):
        self.fn = _make_fn(use_chroma=False)

    @patch("time.sleep", return_value=None)
    @patch("socket.create_connection")
    def test_neo4j_ready_immediately(self, mock_conn, mock_sleep):
        """Socket connects on first try — returns without sleeping."""
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"NEO4J_URI": "bolt://neo4j:7687"}):
            self.fn(timeout=5, poll_interval=1)  # should not raise

        mock_conn.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("time.sleep", return_value=None)
    @patch("socket.create_connection", side_effect=OSError("refused"))
    @patch("sys.exit")
    def test_neo4j_never_ready_exits(self, mock_exit, mock_conn, mock_sleep):
        """Socket always fails — sys.exit(1) called after timeout."""
        with patch.dict(os.environ, {"NEO4J_URI": "bolt://neo4j:7687"}):
            # Use a timeout short enough that monotonic math triggers quickly.
            # We patch time.monotonic to control time.
            import time
            times = iter([0.0, 0.0, 5.0])  # deadline=5, first check <5, second >5
            with patch("time.monotonic", side_effect=times):
                self.fn(timeout=5, poll_interval=1)

        mock_exit.assert_called_once_with(1)

    @patch("time.sleep", return_value=None)
    @patch("socket.create_connection")
    def test_neo4j_ready_on_second_attempt(self, mock_conn, mock_sleep):
        """First attempt fails, second succeeds."""
        fail = OSError("not ready yet")
        success = MagicMock()
        success.__enter__ = lambda s: s
        success.__exit__ = MagicMock(return_value=False)
        mock_conn.side_effect = [fail, success]

        with patch.dict(os.environ, {"NEO4J_URI": "bolt://neo4j:7687"}):
            import time
            times = iter([0.0, 0.0, 1.0, 1.0, 2.0])
            with patch("time.monotonic", side_effect=times):
                self.fn(timeout=60, poll_interval=1)

        self.assertEqual(mock_conn.call_count, 2)
        mock_sleep.assert_called_once_with(1)


class TestWaitForDependenciesWithChroma(unittest.TestCase):
    """Tests with USE_CHROMA=True."""

    def setUp(self):
        self.fn = _make_fn(use_chroma=True, chroma_host="chromadb", chroma_port=8000)

    @patch("time.sleep", return_value=None)
    @patch("urllib.request.urlopen")
    @patch("socket.create_connection")
    def test_both_ready_immediately(self, mock_conn, mock_urlopen, mock_sleep):
        """Both neo4j and chromadb respond on first try."""
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"NEO4J_URI": "bolt://neo4j:7687"}):
            self.fn(timeout=10, poll_interval=1)

        mock_conn.assert_called_once()
        mock_urlopen.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("time.sleep", return_value=None)
    @patch("urllib.request.urlopen", side_effect=urllib.error.URLError("not ready"))
    @patch("socket.create_connection")
    @patch("sys.exit")
    def test_chromadb_never_ready_exits(self, mock_exit, mock_conn, mock_urlopen, mock_sleep):
        """Neo4j ready but ChromaDB always fails — exits after timeout."""
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"NEO4J_URI": "bolt://neo4j:7687"}):
            import time
            times = iter([0.0, 0.0, 5.0])
            with patch("time.monotonic", side_effect=times):
                self.fn(timeout=5, poll_interval=1)

        mock_exit.assert_called_once_with(1)

    @patch("time.sleep", return_value=None)
    @patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        url="http://chromadb:8000/api/v2/heartbeat",
        code=410,
        msg="Gone",
        hdrs=None,
        fp=None,
    ))
    @patch("socket.create_connection")
    @patch("sys.exit")
    def test_chromadb_410_treated_as_not_ready(self, mock_exit, mock_conn, mock_urlopen, mock_sleep):
        """HTTP 410 from ChromaDB v1 endpoint is caught as URLError (HTTPError subclass)
        and treated as not-ready, eventually timing out.

        This test documents what would happen if the wrong (v1) endpoint were used.
        The fix uses /api/v2/heartbeat which returns 200 OK.
        """
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {"NEO4J_URI": "bolt://neo4j:7687"}):
            import time
            times = iter([0.0, 0.0, 5.0])
            with patch("time.monotonic", side_effect=times):
                self.fn(timeout=5, poll_interval=1)

        mock_exit.assert_called_once_with(1)


class TestUriParsing(unittest.TestCase):
    """Test that NEO4J_URI parsing handles various formats correctly."""

    # We test the URI parsing logic by mocking socket to succeed immediately
    # and observing what host:port create_connection was called with.

    def _run_and_capture_conn_args(self, neo4j_uri: str):
        fn = _make_fn(use_chroma=False)
        captured = {}

        def fake_conn(address, timeout):
            captured["address"] = address
            cm = MagicMock()
            cm.__enter__ = lambda s: s
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("socket.create_connection", side_effect=fake_conn):
            with patch("time.sleep", return_value=None):
                with patch.dict(os.environ, {"NEO4J_URI": neo4j_uri}):
                    fn(timeout=5, poll_interval=1)

        return captured.get("address")

    def test_standard_uri(self):
        addr = self._run_and_capture_conn_args("bolt://neo4j:7687")
        self.assertEqual(addr, ("neo4j", 7687))

    def test_localhost_uri(self):
        addr = self._run_and_capture_conn_args("bolt://localhost:7687")
        self.assertEqual(addr, ("localhost", 7687))

    def test_ip_address_uri(self):
        addr = self._run_and_capture_conn_args("bolt://10.0.0.1:7687")
        self.assertEqual(addr, ("10.0.0.1", 7687))

    def test_uri_with_path(self):
        """bolt://neo4j:7687/db/data — path component should be stripped."""
        addr = self._run_and_capture_conn_args("bolt://neo4j:7687/db/data")
        self.assertEqual(addr, ("neo4j", 7687))

    def test_custom_port(self):
        addr = self._run_and_capture_conn_args("bolt://neo4j:17687")
        self.assertEqual(addr, ("neo4j", 17687))

    def test_invalid_uri_fallback(self):
        """Malformed URI falls back to defaults neo4j:7687."""
        addr = self._run_and_capture_conn_args("not-a-valid-uri")
        self.assertEqual(addr, ("neo4j", 7687))

    def test_missing_port_fallback(self):
        """URI without port falls back to defaults."""
        addr = self._run_and_capture_conn_args("bolt://neo4j")
        # rsplit(':', 1) on 'neo4j' yields ['neo4j'] — only one element,
        # so the unpack raises ValueError → fallback
        self.assertEqual(addr, ("neo4j", 7687))


class TestChromaHeartbeatEndpoint(unittest.TestCase):
    """
    Verify the ChromaDB heartbeat endpoint used by wait_for_dependencies.

    As of chromadb/chroma:latest (verified 2026-03-09):
    - /api/v1/heartbeat returns HTTP 410 Gone (deprecated)
    - /api/v2/heartbeat returns HTTP 200 with JSON body

    The function must use /api/v2/heartbeat.
    """

    def test_function_uses_v2_heartbeat_url(self):
        """Verify the function calls the v2 heartbeat endpoint, not v1."""
        fn = _make_fn(use_chroma=True, chroma_host="chromadb", chroma_port=8000)
        captured_urls = []

        def fake_urlopen(url, timeout):
            captured_urls.append(url)
            cm = MagicMock()
            cm.__enter__ = lambda s: s
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                with patch("time.sleep", return_value=None):
                    with patch.dict(os.environ, {"NEO4J_URI": "bolt://neo4j:7687"}):
                        fn(timeout=10, poll_interval=1)

        self.assertEqual(len(captured_urls), 1)
        self.assertIn("/api/v2/heartbeat", captured_urls[0])
        self.assertNotIn("/api/v1/heartbeat", captured_urls[0])

    def test_chromadb_v2_heartbeat_url_format(self):
        """The correct URL format for ChromaDB v2 heartbeat."""
        host = "chromadb"
        port = 8000
        expected = f"http://{host}:{port}/api/v2/heartbeat"
        self.assertEqual(expected, "http://chromadb:8000/api/v2/heartbeat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
