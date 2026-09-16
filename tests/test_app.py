from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app_metadata import APP_VERSION, UPDATED_AT
from utils.downloader import DownloadError, _build_ydl_opts
from web_server import _parse_source, app


class SourceParsingTests(unittest.TestCase):
    def test_youtube_id_and_url(self) -> None:
        self.assertEqual(_parse_source("youtube", "X59ABp1nQY8"), "X59ABp1nQY8")
        self.assertEqual(
            _parse_source("youtube", "https://youtu.be/X59ABp1nQY8?t=4"),
            "X59ABp1nQY8",
        )

    def test_rejects_arbitrary_url(self) -> None:
        with self.assertRaises(ValueError):
            _parse_source("youtube", "https://example.com/file.mp3")


class DownloaderOptionsTests(unittest.TestCase):
    def test_defaults_prioritize_hls_and_retry(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            opts = _build_ydl_opts("/tmp/%(id)s.%(ext)s", [], True)
        self.assertTrue(opts["format"].startswith("bestaudio[protocol*=m3u8]"))
        self.assertEqual(opts["retries"], 5)
        self.assertNotIn("proxy", opts)
        self.assertNotIn("cookiefile", opts)

    def test_proxy_and_cookie_file_are_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cookie_file = Path(directory) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            env = {
                "YTDLP_PROXY": "http://proxy.internal:8080",
                "YTDLP_COOKIES_FILE": str(cookie_file),
            }
            with patch.dict(os.environ, env, clear=True):
                opts = _build_ydl_opts("/tmp/%(id)s.%(ext)s", [], False)
        self.assertEqual(opts["proxy"], env["YTDLP_PROXY"])
        self.assertEqual(opts["cookiefile"], env["YTDLP_COOKIES_FILE"])

    def test_missing_cookie_file_fails_closed(self) -> None:
        with patch.dict(
            os.environ, {"YTDLP_COOKIES_FILE": "/missing/cookies.txt"}, clear=True
        ):
            with self.assertRaises(DownloadError):
                _build_ydl_opts("/tmp/%(id)s.%(ext)s", [], False)


class WebSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_exposes_release_metadata(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], APP_VERSION)
        self.assertEqual(response.json()["updated_at"], UPDATED_AT)

    def test_favicon_and_visible_release(self) -> None:
        favicon = self.client.get("/favicon.svg")
        self.assertEqual(favicon.status_code, 200)
        self.assertIn("image/svg+xml", favicon.headers["content-type"])

        page = self.client.get("/")
        self.assertIn(f"V{APP_VERSION}", page.text)
        self.assertIn(UPDATED_AT, page.text)
        self.assertIn('href="/favicon.svg"', page.text)

    def test_security_headers_and_internal_docs_disabled(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])
        self.assertEqual(self.client.get("/docs").status_code, 404)
        self.assertEqual(self.client.get("/openapi.json").status_code, 404)


if __name__ == "__main__":
    unittest.main()
