"""Tests for Helix News clip cache, incremental renderer, and brief assembler."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
#  ClipCache
# ═══════════════════════════════════════════════════════════════


class TestClipCache:
    """Test the ClipCache manifest manager."""

    @pytest.fixture(autouse=True)
    def _setup_cache(self, tmp_path, monkeypatch):
        """Redirect cache dir to tmp_path for isolation."""
        self.cache_dir = tmp_path / "helix_clip_cache"
        self.cache_dir.mkdir()
        monkeypatch.setattr("ncl_agency_runtime.fpc.helix_news.clip_cache._CACHE_DIR", self.cache_dir)
        monkeypatch.setattr(
            "ncl_agency_runtime.fpc.helix_news.clip_cache._MANIFEST_PATH",
            self.cache_dir / "manifest.json",
        )
        from ncl_agency_runtime.fpc.helix_news.clip_cache import ClipCache

        self.cache = ClipCache()

    def test_empty_cache(self):
        assert self.cache.manifest == {}
        assert self.cache.get_fresh_clips() == []

    def test_status_empty(self):
        s = self.cache.status()
        assert s["total_entries"] == 0
        assert s["fresh_clips"] == 0

    def test_add_clip(self):
        # Create a fake video file
        clip_dir = self.cache_dir / "clips" / "test"
        clip_dir.mkdir(parents=True)
        video = clip_dir / "test.mp4"
        video.write_bytes(b"fake")

        self.cache.add_clip(
            "abc123",
            {
                "topic": "Test Topic",
                "video": str(video),
                "impact_score": 0.95,
            },
        )
        assert "abc123" in self.cache.manifest
        assert self.cache.has_fresh_clip("abc123")

    def test_fresh_clip_no_file(self):
        """Clip in manifest but file deleted → not fresh."""
        self.cache.add_clip(
            "gone",
            {
                "topic": "Gone",
                "video": "/nonexistent/path.mp4",
                "impact_score": 0.5,
            },
        )
        assert not self.cache.has_fresh_clip("gone")

    def test_stale_clip(self):
        """Clip older than 24h → stale."""
        clip_dir = self.cache_dir / "clips" / "old"
        clip_dir.mkdir(parents=True)
        video = clip_dir / "old.mp4"
        video.write_bytes(b"fake")

        self.cache.manifest["old_hash"] = {
            "topic": "Old",
            "video": str(video),
            "impact_score": 0.3,
            "rendered_at": (datetime.now() - timedelta(hours=25)).isoformat(),
            "pred_hash": "old_hash",
        }
        self.cache.save()
        assert not self.cache.has_fresh_clip("old_hash")

    def test_prune_stale(self):
        """Prune removes stale entries."""
        self.cache.manifest["stale"] = {
            "topic": "Stale",
            "video": "/gone.mp4",
            "impact_score": 0.1,
            "rendered_at": (datetime.now() - timedelta(hours=48)).isoformat(),
            "pred_hash": "stale",
        }
        self.cache.save()
        removed = self.cache.prune_stale()
        assert removed == 1
        assert "stale" not in self.cache.manifest

    def test_get_fresh_sorted(self):
        """Fresh clips returned sorted by impact_score descending."""
        clips_dir = self.cache_dir / "clips"
        clips_dir.mkdir(parents=True)
        for name, score in [("a", 0.5), ("b", 0.9), ("c", 0.1)]:
            video = clips_dir / f"{name}.mp4"
            video.write_bytes(b"fake")
            self.cache.add_clip(
                name,
                {
                    "topic": f"Topic {name}",
                    "video": str(video),
                    "impact_score": score,
                },
            )
        fresh = self.cache.get_fresh_clips()
        assert len(fresh) == 3
        assert fresh[0]["impact_score"] == 0.9
        assert fresh[2]["impact_score"] == 0.1

    def test_persist_and_reload(self):
        """Manifest survives save + reload."""
        clips_dir = self.cache_dir / "clips"
        clips_dir.mkdir(parents=True)
        video = clips_dir / "persist.mp4"
        video.write_bytes(b"fake")
        self.cache.add_clip(
            "persist",
            {
                "topic": "Persist",
                "video": str(video),
                "impact_score": 0.7,
            },
        )

        from ncl_agency_runtime.fpc.helix_news.clip_cache import ClipCache

        cache2 = ClipCache()
        assert "persist" in cache2.manifest


# ═══════════════════════════════════════════════════════════════
#  Prediction Hash
# ═══════════════════════════════════════════════════════════════


class TestPredictionHash:
    def test_stable_hash(self):
        from ncl_agency_runtime.fpc.helix_news.clip_cache import _prediction_hash

        p = {"topic": "Bitcoin crash", "predicted_outcome": "Drop to 50k"}
        h1 = _prediction_hash(p)
        h2 = _prediction_hash(p)
        assert h1 == h2
        assert len(h1) == 16

    def test_different_predictions_different_hash(self):
        from ncl_agency_runtime.fpc.helix_news.clip_cache import _prediction_hash

        h1 = _prediction_hash({"topic": "A", "predicted_outcome": "X"})
        h2 = _prediction_hash({"topic": "B", "predicted_outcome": "Y"})
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════
#  IncrementalRenderer
# ═══════════════════════════════════════════════════════════════


class TestIncrementalRenderer:
    """Test the incremental renderer with mocked dependencies."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.cache_dir = tmp_path / "helix_clip_cache"
        self.cache_dir.mkdir()
        monkeypatch.setattr("ncl_agency_runtime.fpc.helix_news.clip_cache._CACHE_DIR", self.cache_dir)
        monkeypatch.setattr(
            "ncl_agency_runtime.fpc.helix_news.clip_cache._MANIFEST_PATH",
            self.cache_dir / "manifest.json",
        )

    @patch("ncl_agency_runtime.fpc.helix_news.avatar_engine.AvatarEngine")
    @patch("ncl_agency_runtime.fpc.helix_news.tts_engine.TTSEngine")
    @patch("ncl_agency_runtime.fpc.signal_scorer.SignalScorer.rank_predictions")
    def test_render_new_clips(self, mock_rank, mock_tts_cls, mock_avatar_cls, tmp_path):
        from ncl_agency_runtime.fpc.helix_news.clip_cache import IncrementalRenderer

        mock_rank.return_value = [
            {
                "topic": "Bitcoin surge",
                "predicted_outcome": "Up 20%",
                "confidence": 0.8,
                "grade": "A",
                "impact_score": 0.9,
                "domain": "finance",
                "risk_level": "LOW",
                "recommendation": "BUY",
            },
        ]

        # Mock TTS
        mock_tts = MagicMock()
        audio_path = str(tmp_path / "test.mp3")
        Path(audio_path).write_bytes(b"audio")
        mock_tts.synthesize.return_value = {"audio": audio_path, "subtitles": None}
        mock_tts_cls.return_value = mock_tts

        # Mock Avatar
        mock_avatar = MagicMock()
        video_path = str(self.cache_dir / "clips" / "test" / "test.mp4")
        Path(video_path).parent.mkdir(parents=True, exist_ok=True)
        Path(video_path).write_bytes(b"video")
        mock_avatar.render.return_value = {"video": video_path, "engine": "mock"}
        mock_avatar_cls.return_value = mock_avatar

        renderer = IncrementalRenderer()
        result = renderer.render_new_clips()

        assert result["rendered"] == 1
        assert result["errors"] == 0
        assert result["cache_status"]["fresh_clips"] == 1

    @patch("ncl_agency_runtime.fpc.signal_scorer.SignalScorer.rank_predictions")
    def test_skip_cached(self, mock_rank, tmp_path):
        """Already-cached predictions are skipped."""
        from ncl_agency_runtime.fpc.helix_news.clip_cache import ClipCache, IncrementalRenderer, _prediction_hash

        pred = {"topic": "Already cached", "predicted_outcome": "stable"}
        mock_rank.return_value = [
            {
                **pred,
                "confidence": 0.5,
                "grade": "C",
                "impact_score": 0.3,
                "domain": "general",
                "risk_level": "LOW",
                "recommendation": "HOLD",
            },
        ]

        # Pre-populate cache
        h = _prediction_hash(pred)
        video = self.cache_dir / "clips" / "cached" / "cached.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"cached")

        cache = ClipCache()
        cache.add_clip(h, {"topic": "Already cached", "video": str(video), "impact_score": 0.3})

        renderer = IncrementalRenderer()
        result = renderer.render_new_clips()

        assert result["rendered"] == 0
        assert result["skipped"] == 1


# ═══════════════════════════════════════════════════════════════
#  BriefAssembler
# ═══════════════════════════════════════════════════════════════


class TestBriefAssembler:
    """Test the brief assembler with mocked AV components."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.cache_dir = tmp_path / "helix_clip_cache"
        self.cache_dir.mkdir()
        self.output_dir = tmp_path / "reports" / "helix_news"
        self.output_dir.mkdir(parents=True)

        monkeypatch.setattr("ncl_agency_runtime.fpc.helix_news.clip_cache._CACHE_DIR", self.cache_dir)
        monkeypatch.setattr(
            "ncl_agency_runtime.fpc.helix_news.clip_cache._MANIFEST_PATH",
            self.cache_dir / "manifest.json",
        )

    def test_assemble_no_clips_falls_back(self):
        """With empty cache, assembler falls back to full pipeline."""
        from ncl_agency_runtime.fpc.helix_news.clip_cache import BriefAssembler

        with patch.object(BriefAssembler, "_fallback_full_pipeline") as mock_fb:
            mock_fb.return_value = {"mode": "full_pipeline", "final_video": None}
            assembler = BriefAssembler()
            result = assembler.assemble()
            mock_fb.assert_called_once()
            assert result["mode"] == "full_pipeline"

    @patch("ncl_agency_runtime.fpc.helix_news.compositor.Compositor")
    @patch("ncl_agency_runtime.fpc.helix_news.avatar_engine.AvatarEngine")
    @patch("ncl_agency_runtime.fpc.helix_news.tts_engine.TTSEngine")
    def test_assemble_with_cached_clips(self, mock_tts_cls, mock_avatar_cls, mock_comp_cls, tmp_path):
        from ncl_agency_runtime.fpc.helix_news.clip_cache import BriefAssembler, ClipCache

        # Seed 3 cached clips
        cache = ClipCache()
        for i in range(3):
            video = self.cache_dir / f"clip_{i}.mp4"
            video.write_bytes(b"clip")
            cache.add_clip(
                f"hash_{i}",
                {
                    "topic": f"Topic {i}",
                    "video": str(video),
                    "impact_score": 0.9 - i * 0.1,
                    "domain": "finance",
                    "grade": "A",
                },
            )

        # Mock TTS → audio
        mock_tts = MagicMock()
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"audio")
        mock_tts.synthesize.return_value = {"audio": str(audio_file), "subtitles": None}
        mock_tts_cls.return_value = mock_tts

        # Mock Avatar → video
        mock_avatar = MagicMock()
        vid_file = tmp_path / "vid.mp4"
        vid_file.write_bytes(b"vid")
        mock_avatar.render.return_value = {"video": str(vid_file), "engine": "mock"}
        mock_avatar_cls.return_value = mock_avatar

        # Mock Compositor → episode
        mock_comp = MagicMock()
        episode_file = tmp_path / "episode.mp4"
        episode_file.write_bytes(b"episode")
        mock_comp.compose.return_value = {"video": str(episode_file)}
        mock_comp_cls.return_value = mock_comp

        assembler = BriefAssembler()
        result = assembler.assemble()

        assert result["mode"] == "cached_assembly"
        assert result["clips_used"] == 3
        assert result["intro"] is True
        assert result["outro"] is True
        mock_comp.compose.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  Daemon Schedule Integration
# ═══════════════════════════════════════════════════════════════


class TestDaemonHelixSchedule:
    """Verify daemon generates HELIX tasks at the right hours."""

    def test_prerender_at_08(self):
        from ncl_agency_runtime.runtime.autonomous_daemon import TaskGenerator

        gen = TaskGenerator()
        with patch("ncl_agency_runtime.runtime.autonomous_daemon.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 8
            mock_now.weekday.return_value = 1  # Tuesday
            mock_dt.now.return_value = mock_now
            tasks = gen.generate_scheduled_tasks()
        categories = [t.category for t in tasks]
        assert "helix_prerender" in categories

    def test_prerender_at_12(self):
        from ncl_agency_runtime.runtime.autonomous_daemon import TaskGenerator

        gen = TaskGenerator()
        with patch("ncl_agency_runtime.runtime.autonomous_daemon.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 12
            mock_now.weekday.return_value = 3  # Thursday
            mock_dt.now.return_value = mock_now
            tasks = gen.generate_scheduled_tasks()
        categories = [t.category for t in tasks]
        assert "helix_prerender" in categories

    def test_prerender_at_16(self):
        from ncl_agency_runtime.runtime.autonomous_daemon import TaskGenerator

        gen = TaskGenerator()
        with patch("ncl_agency_runtime.runtime.autonomous_daemon.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 16
            mock_now.weekday.return_value = 0  # Monday
            mock_dt.now.return_value = mock_now
            tasks = gen.generate_scheduled_tasks()
        categories = [t.category for t in tasks]
        assert "helix_prerender" in categories

    def test_assemble_at_18(self):
        from ncl_agency_runtime.runtime.autonomous_daemon import TaskGenerator

        gen = TaskGenerator()
        with patch("ncl_agency_runtime.runtime.autonomous_daemon.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 18
            mock_now.weekday.return_value = 2  # Wednesday
            mock_dt.now.return_value = mock_now
            tasks = gen.generate_scheduled_tasks()
        categories = [t.category for t in tasks]
        assert "helix_assemble" in categories

    def test_no_helix_at_10(self):
        from ncl_agency_runtime.runtime.autonomous_daemon import TaskGenerator

        gen = TaskGenerator()
        with patch("ncl_agency_runtime.runtime.autonomous_daemon.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 10
            mock_now.weekday.return_value = 2
            mock_dt.now.return_value = mock_now
            tasks = gen.generate_scheduled_tasks()
        categories = [t.category for t in tasks]
        assert "helix_prerender" not in categories
        assert "helix_assemble" not in categories


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════


class TestCLI:
    """Test clip_cache CLI entry point."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.cache_dir = tmp_path / "helix_clip_cache"
        self.cache_dir.mkdir()
        monkeypatch.setattr("ncl_agency_runtime.fpc.helix_news.clip_cache._CACHE_DIR", self.cache_dir)
        monkeypatch.setattr(
            "ncl_agency_runtime.fpc.helix_news.clip_cache._MANIFEST_PATH",
            self.cache_dir / "manifest.json",
        )

    def test_status_cli(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["clip_cache", "status"])
        from ncl_agency_runtime.fpc.helix_news.clip_cache import main

        main()
        captured = capsys.readouterr()
        assert "Clip Cache:" in captured.out
        assert "0 fresh" in captured.out
