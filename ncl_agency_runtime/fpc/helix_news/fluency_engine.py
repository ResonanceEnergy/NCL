"""Helix News — Fluency Engine.

Pre-analyzes broadcast scripts to plan optimal clip placement,
duration, transitions, and data sidebar content for smooth video flow.

The fluency engine solves the "choppy multi-clip" problem by:
  1. Using longer clips (12-15s vs 8s) to halve the number of cuts
  2. Breaking at natural sentence boundaries
  3. Planning crossfade transitions between clips
  4. Extracting structured data points for sidebar overlay

Usage::

    engine = FluencyEngine()
    plans = engine.analyze(script_segments, audio_durations)
    # plans["headlines"] → SegmentPlan with sub-clip details
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SidebarItem:
    """A single data point to display in the sidebar."""

    label: str  # e.g. "AI Regulation"
    value: str  # e.g. "85%"
    category: str  # header | topic | metric | domain


@dataclass
class SubClipPlan:
    """Plan for a single sub-clip within a segment."""

    index: int
    start_sec: float  # Start time in the audio
    end_sec: float  # End time in the audio
    grok_duration: int  # Duration to request from Grok API (5-15)
    prompt_hint: str  # Text context for the video prompt
    sidebar_items: list[SidebarItem] = field(default_factory=list)
    transition: str = "fade"  # xfade transition type


@dataclass
class SegmentPlan:
    """Full clip plan for one segment."""

    segment_name: str
    audio_duration: float
    clips: list[SubClipPlan]
    crossfade_duration: float = 0.5


# Segment display labels for sidebar headers
_SEGMENT_LABELS: dict[str, str] = {
    "cold_open": "NCC DAILY BRIEF",
    "headlines": "TOP HEADLINES",
    "market_pulse": "MARKET PULSE",
    "predictions": "PREDICTIONS",
    "alerts": "ALERT BOARD",
    "closing": "HELIX NEWS",
}


class FluencyEngine:
    """Analyzes scripts and plans clip placement for smooth video flow."""

    MAX_CLIP_DURATION = 15  # Grok Video API max
    MIN_CLIP_DURATION = 5
    TARGET_CLIP_DURATION = 13  # Sweet spot — reduces cuts, still varied
    CROSSFADE_DURATION = 0.5

    def analyze(
        self,
        segments: list[dict[str, Any]],
        audio_durations: dict[str, float],
    ) -> dict[str, SegmentPlan]:
        """Analyze all segments and produce clip plans.

        Args:
            segments: List of segment dicts from ScriptGenerator
                      (each has 'name', 'text', 'metadata').
            audio_durations: Dict mapping segment name → audio duration in seconds.

        Returns:
            Dict mapping segment name → SegmentPlan.
        """
        plans: dict[str, SegmentPlan] = {}
        for seg in segments:
            name = seg["name"]
            dur = audio_durations.get(name, 30.0)
            text = seg.get("text", "")
            plans[name] = self._plan_segment(name, text, dur)
        return plans

    def _plan_segment(self, name: str, text: str, duration: float) -> SegmentPlan:
        """Build a clip plan for a single segment."""
        # Short segments (<=15s) → single clip, no splitting needed
        if duration <= self.MAX_CLIP_DURATION:
            clip = SubClipPlan(
                index=0,
                start_sec=0.0,
                end_sec=duration,
                grok_duration=max(self.MIN_CLIP_DURATION, min(self.MAX_CLIP_DURATION, int(duration) + 1)),
                prompt_hint=text[:120],
                sidebar_items=self._extract_sidebar_data(name, text),
            )
            return SegmentPlan(name, duration, [clip], crossfade_duration=0.0)

        # Longer segments → split at sentence boundaries with ~13s target
        sentences = self._split_sentences(text)
        clips = self._allocate_clips(sentences, duration, name)

        logger.info(
            "Fluency plan for '%s': %.1fs → %d clips (target %ds)",
            name,
            duration,
            len(clips),
            self.TARGET_CLIP_DURATION,
        )

        return SegmentPlan(
            segment_name=name,
            audio_duration=duration,
            clips=clips,
            crossfade_duration=self.CROSSFADE_DURATION if len(clips) > 1 else 0.0,
        )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences at . ! ? boundaries."""
        parts = re.split(r"(?<=[.!?])\s+", text)
        return [p.strip() for p in parts if p.strip()]

    def _allocate_clips(
        self,
        sentences: list[str],
        total_duration: float,
        segment_name: str,
    ) -> list[SubClipPlan]:
        """Allocate sentences into sub-clips with optimal durations."""
        total_words = sum(len(s.split()) for s in sentences)
        if total_words == 0:
            grok_dur = min(self.MAX_CLIP_DURATION, max(self.MIN_CLIP_DURATION, int(total_duration)))
            return [SubClipPlan(0, 0, total_duration, grok_dur, "", [])]

        wps = total_words / total_duration  # words per second

        clips: list[SubClipPlan] = []
        current_words: list[str] = []
        current_word_count = 0
        clip_start = 0.0
        clip_idx = 0

        for sentence in sentences:
            word_count = len(sentence.split())
            current_words.append(sentence)
            current_word_count += word_count
            estimated_duration = current_word_count / wps

            # Break at sentence boundary once we reach target duration
            if estimated_duration >= self.TARGET_CLIP_DURATION:
                clip_end = min(clip_start + estimated_duration, total_duration)
                grok_dur = min(
                    self.MAX_CLIP_DURATION,
                    max(self.MIN_CLIP_DURATION, int(estimated_duration) + 1),
                )
                clip_text = " ".join(current_words)

                clips.append(
                    SubClipPlan(
                        index=clip_idx,
                        start_sec=clip_start,
                        end_sec=clip_end,
                        grok_duration=grok_dur,
                        prompt_hint=clip_text[:120],
                        sidebar_items=self._extract_sidebar_data(segment_name, clip_text),
                    )
                )

                clip_start = clip_end
                current_words = []
                current_word_count = 0
                clip_idx += 1

        # Handle remaining words
        if current_words:
            remaining_dur = total_duration - clip_start
            if remaining_dur < self.MIN_CLIP_DURATION and clips:
                # Merge tiny remainder into last clip
                last = clips[-1]
                merged_text = last.prompt_hint + " " + " ".join(current_words)
                clips[-1] = SubClipPlan(
                    index=last.index,
                    start_sec=last.start_sec,
                    end_sec=total_duration,
                    grok_duration=min(self.MAX_CLIP_DURATION, last.grok_duration + 2),
                    prompt_hint=merged_text[:120],
                    sidebar_items=last.sidebar_items,
                )
            else:
                grok_dur = min(
                    self.MAX_CLIP_DURATION,
                    max(self.MIN_CLIP_DURATION, int(remaining_dur) + 1),
                )
                clip_text = " ".join(current_words)
                clips.append(
                    SubClipPlan(
                        index=clip_idx,
                        start_sec=clip_start,
                        end_sec=total_duration,
                        grok_duration=grok_dur,
                        prompt_hint=clip_text[:120],
                        sidebar_items=self._extract_sidebar_data(segment_name, clip_text),
                    )
                )

        if not clips:
            grok_dur = min(self.MAX_CLIP_DURATION, max(self.MIN_CLIP_DURATION, int(total_duration)))
            return [SubClipPlan(0, 0, total_duration, grok_dur, "", [])]

        return clips

    def _extract_sidebar_data(self, segment_name: str, text: str) -> list[SidebarItem]:
        """Extract structured data points from script text for sidebar display."""
        items: list[SidebarItem] = []

        # Segment header (always first)
        label = _SEGMENT_LABELS.get(segment_name, segment_name.upper().replace("_", " "))
        items.append(SidebarItem(label="SEGMENT", value=label, category="header"))

        # Extract "Number N: ... — Topic." items
        for m in re.finditer(r"Number\s+(\d+)[,:]\s*(?:In\s+\w+\s*[—-]\s*)?([^.]+)\.", text):
            topic = m.group(2).strip()[:35]
            items.append(SidebarItem(label=f"#{m.group(1)}", value=topic, category="topic"))

        # Extract domain tags
        for m in re.finditer(
            r"In (markets|tech|cybersecurity|science|health|geopolitics)",
            text,
            re.IGNORECASE,
        ):
            items.append(SidebarItem(label="Domain", value=m.group(1).title(), category="domain"))

        # Extract confidence percentages
        for m in re.finditer(r"Confidence:\s*(\d+)%", text):
            items.append(SidebarItem(label="Confidence", value=m.group(1) + "%", category="metric"))

        # Extract risk levels
        for m in re.finditer(r"Risk level:\s*(\w+)", text, re.IGNORECASE):
            items.append(SidebarItem(label="Risk", value=m.group(1).title(), category="metric"))

        # Cap at 6 items to fit sidebar
        return items[:6]

    def build_sidebar_drawtext_filters(
        self,
        plan: SegmentPlan,
        video_width: int = 1280,
    ) -> str:
        """Build ffmpeg drawtext filter chain for sidebar overlay.

        Returns a string of chained vf filters that draw a semi-transparent
        panel with data points that change per sub-clip time window.
        """
        panel_w = 260
        panel_x = video_width - panel_w
        text_x = panel_x + 15
        # Use fontconfig font name — avoids Windows path colon escaping issues
        font = "Arial"

        filters: list[str] = []

        # Semi-transparent dark panel (always visible)
        filters.append(
            f"drawbox=x={panel_x}:y=0:w={panel_w}:h=ih:color=black@0.55:t=fill"
        )

        # Thin accent line on left edge of panel
        filters.append(
            f"drawbox=x={panel_x}:y=0:w=3:h=ih:color=0x00ccff@0.8:t=fill"
        )

        for clip in plan.clips:
            t_start = clip.start_sec
            t_end = clip.end_sec
            # enable must be UNQUOTED so ffmpeg sees \, as escaped commas
            # (inside single quotes, \, would be literal backslash+comma)
            enable = f"between(t\\,{t_start:.2f}\\,{t_end:.2f})"

            y_pos = 25
            for si in clip.sidebar_items:
                if si.category == "header":
                    # Escape for drawtext: apostrophes, colons (option sep), % (format specifier)
                    escaped_val = si.value.replace("'", "'\\''").replace(":", "\\:").replace("%", "%%")
                    filters.append(
                        f"drawtext=text='{escaped_val}'"
                        f":font={font}:fontsize=20:fontcolor=white"
                        f":x={text_x}:y={y_pos}:enable={enable}"
                    )
                    y_pos += 30
                    # Separator line
                    filters.append(
                        f"drawbox=x={text_x}:y={y_pos}:w={panel_w - 30}:h=2"
                        f":color=0x00ccff@0.6:t=fill:enable={enable}"
                    )
                    y_pos += 12
                elif si.category == "topic":
                    escaped_label = si.label.replace("'", "'\\''").replace(":", "\\:").replace("%", "%%")
                    escaped_val = si.value.replace("'", "'\\''").replace(":", "\\:").replace("%", "%%")
                    # Topic number in cyan
                    filters.append(
                        f"drawtext=text='{escaped_label}'"
                        f":font={font}:fontsize=16:fontcolor=0x00ccff"
                        f":x={text_x}:y={y_pos}:enable={enable}"
                    )
                    # Topic text in white
                    filters.append(
                        f"drawtext=text='{escaped_val}'"
                        f":font={font}:fontsize=14:fontcolor=white"
                        f":x={text_x + 30}:y={y_pos + 2}:enable={enable}"
                    )
                    y_pos += 24
                elif si.category == "metric":
                    escaped_label = si.label.replace("'", "'\\''").replace(":", "\\:").replace("%", "%%")
                    escaped_val = si.value.replace("'", "'\\''").replace(":", "\\:").replace("%", "%%")
                    # Metric label in grey, value in green
                    color = "0x00ff88" if si.label == "Confidence" else "0xffaa00"
                    filters.append(
                        f"drawtext=text='{escaped_label}\\: {escaped_val}'"
                        f":font={font}:fontsize=14:fontcolor={color}"
                        f":x={text_x}:y={y_pos}:enable={enable}"
                    )
                    y_pos += 22
                elif si.category == "domain":
                    escaped_val = si.value.replace("'", "'\\''").replace(":", "\\:").replace("%", "%%")
                    filters.append(
                        f"drawtext=text='[{escaped_val}]'"
                        f":font={font}:fontsize=13:fontcolor=0xaaaaaa"
                        f":x={text_x}:y={y_pos}:enable={enable}"
                    )
                    y_pos += 20

        return ",".join(filters)
