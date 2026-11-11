from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app_metadata import APP_VERSION, UPDATED_AT
from utils.downloader import DownloadError, _build_ydl_opts
from utils.system_info import recommend_model
from utils.timecode import format_timecode, parse_timecode
from web_server import _parse_source, app


class SourceParsingTests(unittest.TestCase):
    def test_youtube_id_and_url(self) -> None:
        self.assertEqual(_parse_source("youtube", "X59ABp1nQY8"), "X59ABp1nQY8")
        self.assertEqual(
            _parse_source("youtube", "https://youtu.be/X59ABp1nQY8?t=4"),
            "X59ABp1nQY8",
        )

    def test_twitch_url_with_channel(self) -> None:
        self.assertEqual(
            _parse_source("twitch", "https://www.twitch.tv/somechannel/video/123456789"),
            "123456789",
        )

    def test_youtube_url_with_extra_params(self) -> None:
        self.assertEqual(
            _parse_source("youtube", "https://www.youtube.com/watch?list=PL1&v=X59ABp1nQY8"),
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
        self.assertNotIn("download_ranges", opts)
        self.assertEqual(
            opts["postprocessor_args"]["extractaudio"], ["-ar", "16000", "-ac", "1"]
        )

    def test_range_only_downloads_requested_section(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            opts = _build_ydl_opts("/tmp/x.%(ext)s", [], True, start_seconds=60, end_seconds=90)
        ranges = list(opts["download_ranges"]({}, None))
        self.assertEqual((ranges[0]["start_time"], ranges[0]["end_time"]), (60.0, 90.0))

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


class TimecodeTests(unittest.TestCase):
    def test_parse_formats(self) -> None:
        self.assertIsNone(parse_timecode(""))
        self.assertEqual(parse_timecode("90"), 90.0)
        self.assertEqual(parse_timecode("1:30"), 90.0)
        self.assertEqual(parse_timecode("1:01:30"), 3690.0)
        self.assertEqual(parse_timecode(12.5), 12.5)
        for bad in ("abc", "1:75", "-3", "1::2"):
            with self.assertRaises(ValueError):
                parse_timecode(bad)

    def test_format(self) -> None:
        self.assertEqual(format_timecode(90), "1:30")
        self.assertEqual(format_timecode(3690), "1:01:30")


class RecommendationTests(unittest.TestCase):
    def test_scales_with_hardware(self) -> None:
        self.assertEqual(recommend_model(2, 2.0, 0), "tiny")
        self.assertEqual(recommend_model(4, 8.0, 0), "base")
        self.assertEqual(recommend_model(10, 16.0, 0), "small")
        self.assertEqual(recommend_model(8, 16.0, 1), "large-v3")


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
        self.assertEqual(page.status_code, 200)
        self.assertIn('href="/favicon.svg', page.text)
        about = self.client.get("/api/about").json()
        self.assertEqual(about["version"], APP_VERSION)
        self.assertEqual(about["updated_at"], UPDATED_AT)
        self.assertEqual(set(about["changes"]), {"es", "en"})

    def test_static_assets_and_system(self) -> None:
        for asset in ("app.js", "i18n.js", "boot.js", "styles.css"):
            self.assertEqual(self.client.get(f"/static/{asset}").status_code, 200)
        system = self.client.get("/api/system").json()
        self.assertIn("recommended_model", system)
        self.assertGreaterEqual(system["cpu_threads"], 1)

    def test_errors_carry_codes(self) -> None:
        bad = self.client.post(
            "/api/jobs", json={"platform": "youtube", "video_id": "https://example.com/x"}
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["detail"]["code"], "invalid_source")
        rng = self.client.post(
            "/api/jobs",
            json={"platform": "youtube", "video_id": "X59ABp1nQY8", "start": "2:00", "end": "1:00"},
        )
        self.assertEqual(rng.json()["detail"]["code"], "invalid_range")

    def test_security_headers_and_internal_docs_disabled(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        csp = response.headers["content-security-policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(self.client.get("/docs").status_code, 404)
        self.assertEqual(self.client.get("/openapi.json").status_code, 404)


if __name__ == "__main__":
    unittest.main()
