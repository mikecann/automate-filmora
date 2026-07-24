"""Headless silence and repeated-take planning for a Filmora rough cut."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .archive import WfpError


Pathish = Union[str, Path]


@dataclass(frozen=True)
class SilenceInterval:
    start: float
    end: float


@dataclass(frozen=True)
class TranscriptWord:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: Tuple[TranscriptWord, ...] = ()


@dataclass(frozen=True)
class SpeechRegion:
    id: str
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TakeDecision:
    region_id: str
    decision: str
    confidence: float
    reason: str
    duplicate_of: Optional[str] = None


@dataclass(frozen=True)
class RepeatedWordSpan:
    start: float
    end: float
    repeated_at_start: float
    repeated_at_end: float
    matched_word_count: int


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")
_SRT_RANGE_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")


def _finite_non_negative(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise WfpError("{0} must be a non-negative number".format(label))
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WfpError("{0} must be a non-negative number".format(label)) from exc
    if number < 0 or number != number or number in (float("inf"), float("-inf")):
        raise WfpError("{0} must be a finite non-negative number".format(label))
    return number


def _validate_intervals(
    intervals: Iterable[SilenceInterval],
    *,
    duration_seconds: Optional[float] = None,
) -> List[SilenceInterval]:
    duration = None
    if duration_seconds is not None:
        duration = _finite_non_negative(duration_seconds, "duration_seconds")
    result: List[SilenceInterval] = []
    for interval in intervals:
        start = _finite_non_negative(interval.start, "silence start")
        end = _finite_non_negative(interval.end, "silence end")
        if end <= start:
            raise WfpError("Silence intervals must have positive duration")
        if duration is not None and end > duration + 0.001:
            raise WfpError("Silence interval extends beyond the media duration")
        result.append(SilenceInterval(start, min(end, duration) if duration is not None else end))
    result.sort(key=lambda item: (item.start, item.end))
    merged: List[SilenceInterval] = []
    for interval in result:
        if merged and interval.start <= merged[-1].end:
            merged[-1] = SilenceInterval(merged[-1].start, max(merged[-1].end, interval.end))
        else:
            merged.append(interval)
    return merged


def parse_ffmpeg_silence_output(output: str) -> Tuple[float, List[SilenceInterval]]:
    """Parse duration and paired intervals from ffmpeg's silencedetect log."""

    duration_match = _DURATION_RE.search(output)
    if duration_match is None:
        raise WfpError("ffmpeg output did not contain a media duration")
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    pending: List[float] = []
    intervals: List[SilenceInterval] = []
    for line in output.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match is not None:
            pending.append(float(start_match.group(1)))
        end_match = _SILENCE_END_RE.search(line)
        if end_match is not None and pending:
            intervals.append(SilenceInterval(pending.pop(0), float(end_match.group(1))))
    # ffmpeg may report a final silence_start without a matching silence_end.
    for start in pending:
        if start < duration:
            intervals.append(SilenceInterval(start, duration))
    return duration, _validate_intervals(intervals, duration_seconds=duration)


def detect_silence(
    media: Pathish,
    *,
    ffmpeg: str = "ffmpeg",
    threshold_db: float = -35.0,
    minimum_duration: float = 0.5,
) -> Tuple[float, List[SilenceInterval]]:
    """Run ffmpeg silencedetect without decoding or writing the video stream."""

    media_path = Path(media).expanduser().resolve()
    if not media_path.is_file():
        raise WfpError("Media file does not exist: {0}".format(media_path))
    ffmpeg_path = shutil.which(ffmpeg) if not Path(ffmpeg).is_file() else str(Path(ffmpeg).resolve())
    if not ffmpeg_path:
        raise WfpError("ffmpeg was not found: {0}".format(ffmpeg))
    threshold = float(threshold_db)
    minimum = _finite_non_negative(minimum_duration, "minimum_duration")
    if minimum <= 0:
        raise WfpError("minimum_duration must be greater than zero")
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-nostats",
        "-i",
        str(media_path),
        "-map",
        "0:a:0",
        "-af",
        "silencedetect=noise={0}dB:d={1}".format(threshold, minimum),
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        tail = "\n".join(completed.stderr.splitlines()[-10:])
        raise WfpError("ffmpeg silence detection failed:\n{0}".format(tail))
    return parse_ffmpeg_silence_output(completed.stderr)


def speech_regions_from_silences(
    duration_seconds: float,
    silences: Sequence[SilenceInterval],
    *,
    softening_buffer: float = 0.4,
) -> List[Tuple[float, float]]:
    """Return audible source ranges with a retained buffer inside each silence."""

    duration = _finite_non_negative(duration_seconds, "duration_seconds")
    if duration <= 0:
        raise WfpError("duration_seconds must be greater than zero")
    buffer_seconds = _finite_non_negative(softening_buffer, "softening_buffer")
    normalized = _validate_intervals(silences, duration_seconds=duration)
    audible: List[Tuple[float, float]] = []
    cursor = 0.0
    for silence in normalized:
        if silence.start > cursor:
            audible.append((cursor, silence.start))
        cursor = max(cursor, silence.end)
    if cursor < duration:
        audible.append((cursor, duration))

    softened = [
        (max(0.0, start - buffer_seconds), min(duration, end + buffer_seconds))
        for start, end in audible
        if end > start
    ]
    return _merge_ranges(softened)


def _merge_ranges(ranges: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
    merged: List[Tuple[float, float]] = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _srt_seconds(value: str) -> float:
    normalized = value.replace(",", ".")
    hours, minutes, seconds = normalized.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_srt(text: str) -> List[TranscriptSegment]:
    """Parse ordinary SRT blocks into timestamped transcript segments."""

    blocks = re.split(r"\r?\n\s*\r?\n", text.strip()) if text.strip() else []
    segments: List[TranscriptSegment] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        range_index = next(
            (index for index, line in enumerate(lines) if _SRT_RANGE_RE.fullmatch(line)),
            None,
        )
        if range_index is None:
            continue
        match = _SRT_RANGE_RE.fullmatch(lines[range_index])
        assert match is not None
        content = " ".join(lines[range_index + 1 :]).strip()
        if not content:
            continue
        segments.append(
            TranscriptSegment(
                _srt_seconds(match.group("start")),
                _srt_seconds(match.group("end")),
                content,
            )
        )
    segments.sort(key=lambda item: (item.start, item.end))
    return segments


def load_transcript(path: Pathish) -> List[TranscriptSegment]:
    transcript_path = Path(path).expanduser().resolve()
    if not transcript_path.is_file():
        raise WfpError("Transcript file does not exist: {0}".format(transcript_path))
    if transcript_path.suffix.lower() == ".srt":
        return parse_srt(transcript_path.read_text(encoding="utf-8", errors="replace"))
    if transcript_path.suffix.lower() != ".json":
        raise WfpError("Transcript must be SRT or rough-cut transcript JSON")
    try:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WfpError("Could not read transcript JSON: {0}".format(exc)) from exc
    raw_segments = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(raw_segments, list):
        raise WfpError("Transcript JSON must contain a segments array")
    result: List[TranscriptSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise WfpError("Transcript JSON contains an invalid segment")
        raw_words = item.get("words") or []
        words: List[TranscriptWord] = []
        for word in raw_words:
            if not isinstance(word, dict) or not isinstance(word.get("text"), str):
                raise WfpError("Transcript JSON contains an invalid word")
            words.append(
                TranscriptWord(
                    _finite_non_negative(word.get("start"), "word start"),
                    _finite_non_negative(word.get("end"), "word end"),
                    word["text"].strip(),
                )
            )
        result.append(
            TranscriptSegment(
                _finite_non_negative(item.get("start"), "segment start"),
                _finite_non_negative(item.get("end"), "segment end"),
                item["text"].strip(),
                tuple(words),
            )
        )
    result.sort(key=lambda item: (item.start, item.end))
    return result


def _load_whisper_model(model_name: str, device: str, compute_type: str) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise WfpError(
            "Transcription requires faster-whisper, or pass an existing SRT/JSON transcript"
        ) from exc
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def _transcript_segments_from_generated(
    generated: Iterable[Any],
    *,
    maximum_no_speech_probability: Optional[float] = None,
) -> List[TranscriptSegment]:
    result: List[TranscriptSegment] = []
    for segment in generated:
        no_speech_probability = float(getattr(segment, "no_speech_prob", 0.0))
        if (
            maximum_no_speech_probability is not None
            and no_speech_probability >= maximum_no_speech_probability
        ):
            # Short mouse and handling sounds commonly hallucinate phrases such
            # as "Thanks for watching" with a very high no-speech probability.
            continue
        text = (segment.text or "").strip()
        if not text:
            continue
        words: List[TranscriptWord] = []
        for word in segment.words or []:
            word_text = (word.word or "").strip()
            if word.start is None or word.end is None or not word_text:
                continue
            words.append(TranscriptWord(float(word.start), float(word.end), word_text))
        result.append(
            TranscriptSegment(
                float(segment.start),
                float(segment.end),
                text,
                tuple(words),
            )
        )
    return result


def transcribe_media(
    media: Pathish,
    *,
    model_name: str = "small.en",
    device: str = "cpu",
    compute_type: str = "int8",
) -> List[TranscriptSegment]:
    """Transcribe media with faster-whisper and retain word timestamps."""

    media_path = Path(media).expanduser().resolve()
    if not media_path.is_file():
        raise WfpError("Media file does not exist: {0}".format(media_path))
    model = _load_whisper_model(model_name, device, compute_type)
    generated, _info = model.transcribe(
        str(media_path),
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
    )
    return _transcript_segments_from_generated(
        generated,
        maximum_no_speech_probability=0.60,
    )


def transcribe_media_ranges(
    media: Pathish,
    ranges: Sequence[Tuple[float, float]],
    *,
    model_name: str = "small.en",
    device: str = "cpu",
    compute_type: str = "int8",
) -> List[TranscriptSegment]:
    """Transcribe each silence-cut range independently in one model pass.

    Whole-recording Whisper can join a short false start to a later completed
    take across several seconds of silence. `clip_timestamps` keeps absolute
    source times while `condition_on_previous_text=False` resets the language
    context at every range, exposing the repeated opening to take detection.
    """

    media_path = Path(media).expanduser().resolve()
    if not media_path.is_file():
        raise WfpError("Media file does not exist: {0}".format(media_path))
    clip_timestamps: List[float] = []
    for start_value, end_value in ranges:
        start = _finite_non_negative(start_value, "transcription range start")
        end = _finite_non_negative(end_value, "transcription range end")
        if end <= start:
            raise WfpError("Transcription ranges must have positive duration")
        clip_timestamps.extend((start, end))
    if not clip_timestamps:
        return []

    model = _load_whisper_model(model_name, device, compute_type)
    generated, _info = model.transcribe(
        str(media_path),
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=False,
        clip_timestamps=clip_timestamps,
    )
    return _transcript_segments_from_generated(
        generated,
        maximum_no_speech_probability=0.60,
    )


def transcript_to_json(segments: Sequence[TranscriptSegment]) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "segments": [asdict(segment) for segment in segments],
    }


def _normalize_tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def _looks_incomplete(text: str) -> bool:
    """Return whether punctuation and the final word suggest an abandoned thought."""

    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith(("...", "…")):
        return True
    if stripped.endswith((".", "?", "!")):
        return False
    tokens = _normalize_tokens(stripped)
    return bool(tokens) and tokens[-1] in {
        "a",
        "an",
        "and",
        "basically",
        "because",
        "but",
        "can",
        "could",
        "for",
        "have",
        "might",
        "of",
        "or",
        "should",
        "that",
        "the",
        "to",
        "with",
        "would",
    }


def _looks_like_recording_direction(text: str) -> bool:
    """Recognize a narrow self-direction phrase rather than tutorial content."""

    tokens = " ".join(_normalize_tokens(text))
    return "before we do that" in tokens and any(
        phrase in tokens
        for phrase in (
            "add this to the intro",
            "add that to the intro",
            "put this in the intro",
            "put that in the intro",
        )
    )


def _duplicate_score(earlier: SpeechRegion, later: SpeechRegion) -> Tuple[float, str]:
    first = _normalize_tokens(earlier.text)
    second = _normalize_tokens(later.text)
    if len(first) < 4 or len(second) < 4:
        return 0.0, "too_short"
    matcher = SequenceMatcher(a=first, b=second, autojunk=False)
    longest = matcher.find_longest_match(0, len(first), 0, len(second))
    shorter = min(len(first), len(second))
    coverage = longest.size / shorter
    ratio = matcher.ratio()
    matching_blocks = matcher.get_matching_blocks()
    ordered_match_words = sum(block.size for block in matching_blocks)
    ordered_coverage = ordered_match_words / len(first)
    starts_together = longest.a <= 1 and longest.b <= 1
    exact = first == second
    if exact:
        return 1.0, "same_transcript"
    # False starts usually repeat from the beginning and then continue further.
    if starts_together and longest.size >= 4 and coverage >= 0.80:
        confidence = min(0.99, 0.65 + 0.35 * coverage)
        return confidence, "repeated_opening_or_false_start"
    if starts_together and longest.size >= 5 and ratio >= 0.82:
        return min(0.97, ratio), "near_duplicate_take"

    # Short restarts often contain small insertions or reordered filler words,
    # so their longest exact block is too small for the conservative opening
    # rule above. Ordered coverage across all matching blocks catches these
    # reworded attempts while still requiring most of the short clip to recur.
    if (
        earlier.end - earlier.start < 5.0
        and ordered_match_words >= 3
        and ordered_coverage >= 0.70
    ):
        return min(0.97, 0.90 + 0.08 * ordered_coverage), "short_clip_repeated_in_later_take"

    # Normal-length takes can be reworded without preserving one long exact
    # phrase. High ordered coverage across several blocks catches those earlier
    # versions while requiring enough total evidence to avoid generic overlap.
    if (
        ordered_match_words >= 12
        and ordered_coverage >= 0.70
        and longest.size >= 4
    ):
        return min(0.97, 0.90 + 0.08 * ordered_coverage), "reworded_take_repeated_later"

    # Do not put a hard semantic cliff at five seconds. A brief 5.x-second take
    # with a substantial matching phrase can be the same kind of restart as a
    # 4.9-second clip.
    if (
        earlier.end - earlier.start < 6.0
        and ordered_match_words >= 8
        and ordered_coverage >= 0.55
        and longest.size >= 5
    ):
        return min(0.95, 0.90 + 0.08 * ordered_coverage), "brief_take_repeated_later"

    # A longer attempt ending mid-thought can be reworded substantially before
    # the final take. Strong ordered overlap plus an incomplete ending is useful
    # evidence, but unlike the short rule this requires at least eight matching
    # words and a substantial contiguous phrase.
    if (
        _looks_incomplete(earlier.text)
        and ordered_match_words >= 8
        and longest.size >= 4
        and (ordered_coverage >= 0.50 or longest.size >= 6)
    ):
        return min(0.96, 0.91 + 0.05 * ordered_coverage), "incomplete_take_repeated_later"
    return 0.0, "not_duplicate"


def detect_duplicate_takes(
    regions: Sequence[SpeechRegion],
    *,
    lookahead_seconds: float = 90.0,
    auto_drop_confidence: float = 0.90,
) -> List[TakeDecision]:
    """Mark a high-confidence earlier take when a nearby later take repeats it."""

    window = _finite_non_negative(lookahead_seconds, "lookahead_seconds")
    threshold = float(auto_drop_confidence)
    if not 0.5 <= threshold <= 1.0:
        raise WfpError("auto_drop_confidence must be between 0.5 and 1.0")
    decisions = [
        TakeDecision(region.id, "keep", 0.0, "no_high_confidence_duplicate")
        for region in regions
    ]
    for earlier_index, earlier in enumerate(regions):
        best: Optional[Tuple[float, str, SpeechRegion]] = None
        for later in regions[earlier_index + 1 :]:
            if later.start - earlier.end > window:
                break
            score, reason = _duplicate_score(earlier, later)
            if (
                reason == "short_clip_repeated_in_later_take"
                and later.start - earlier.end > 30.0
            ):
                score = 0.0
                reason = "short_repeat_too_distant"
            if best is None or score > best[0]:
                best = (score, reason, later)
        if best is not None and best[0] >= threshold:
            decisions[earlier_index] = TakeDecision(
                earlier.id,
                "drop",
                round(best[0], 4),
                best[1],
                best[2].id,
            )
    return decisions


def detect_repeated_word_spans(
    transcript: Sequence[TranscriptSegment],
    *,
    minimum_words: int = 5,
    lookahead_seconds: float = 90.0,
) -> List[RepeatedWordSpan]:
    """Find exact nearby word sequences and nominate the earlier occurrence.

    A five-word repeat is a useful high-precision signal for spoken retakes. The
    later occurrence is preserved because presenters normally restart and then
    continue with the preferred take. Every result remains visible in the
    review report before a Filmora writer can consume it.
    """

    if isinstance(minimum_words, bool) or not isinstance(minimum_words, int) or minimum_words < 4:
        raise WfpError("minimum_words must be an integer of at least four")
    window = _finite_non_negative(lookahead_seconds, "lookahead_seconds")
    words: List[Tuple[str, float, float]] = []
    for segment in transcript:
        for word in segment.words:
            tokens = _normalize_tokens(word.text)
            for token in tokens:
                words.append((token, word.start, word.end))
    words.sort(key=lambda item: (item[1], item[2]))
    if len(words) < minimum_words * 2:
        return []

    occurrences: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
    spans: List[RepeatedWordSpan] = []
    for later_index in range(0, len(words) - minimum_words + 1):
        key = tuple(
            words[index][0]
            for index in range(later_index, later_index + minimum_words)
        )
        earlier_candidates = [
            index
            for index in occurrences[key]
            if 0 < words[later_index][1] - words[index + minimum_words - 1][2] <= window
        ]
        if earlier_candidates:
            earlier_index = earlier_candidates[-1]
            matched_words = minimum_words
            while (
                earlier_index + matched_words < len(words)
                and later_index + matched_words < len(words)
                and words[earlier_index + matched_words][0]
                == words[later_index + matched_words][0]
            ):
                matched_words += 1
            spans.append(
                RepeatedWordSpan(
                    words[earlier_index][1],
                    words[earlier_index + matched_words - 1][2],
                    words[later_index][1],
                    words[later_index + matched_words - 1][2],
                    matched_words,
                )
            )
        occurrences[key].append(later_index)

    # Overlapping n-grams from the same retake produce many equivalent spans.
    # Merge only their earlier source ranges; retain the widest later evidence.
    merged: List[RepeatedWordSpan] = []
    for span in sorted(spans, key=lambda item: (item.start, item.end)):
        if merged and span.start <= merged[-1].end:
            previous = merged[-1]
            merged[-1] = RepeatedWordSpan(
                previous.start,
                max(previous.end, span.end),
                min(previous.repeated_at_start, span.repeated_at_start),
                max(previous.repeated_at_end, span.repeated_at_end),
                max(previous.matched_word_count, span.matched_word_count),
            )
        else:
            merged.append(span)
    return merged


def _split_ranges_at_leading_internal_restarts(
    ranges: Sequence[Tuple[float, float]],
    repeated_word_spans: Sequence[RepeatedWordSpan],
) -> Tuple[List[Tuple[float, float]], List[Dict[str, Any]]]:
    """Expose a repeated restart that silence detection left inside one range.

    The repeated phrase must begin within one second of the audible range. This
    guard distinguishes a restart at the beginning of a take from intentional
    repetition later in a continuous explanation.
    """

    boundaries: Dict[int, List[float]] = defaultdict(list)
    diagnostics: List[Dict[str, Any]] = []
    for span in repeated_word_spans:
        for index, (range_start, range_end) in enumerate(ranges):
            if not (
                range_start <= span.start <= range_end
                and range_start <= span.repeated_at_start <= range_end
            ):
                continue
            if span.start - range_start > 1.0:
                continue
            boundary = span.repeated_at_start
            if boundary - range_start < 0.5 or range_end - boundary < 0.5:
                continue
            boundaries[index].append(boundary)
            diagnostics.append(
                {
                    "range_start": range_start,
                    "range_end": range_end,
                    "restart_at": boundary,
                    "matched_word_count": span.matched_word_count,
                }
            )

    result: List[Tuple[float, float]] = []
    for index, (range_start, range_end) in enumerate(ranges):
        cursor = range_start
        for boundary in sorted(set(boundaries.get(index, []))):
            result.append((cursor, boundary))
            cursor = boundary
        result.append((cursor, range_end))
    return result, diagnostics


def _texts_for_ranges(
    ranges: Sequence[Tuple[float, float]],
    transcript: Sequence[TranscriptSegment],
) -> List[str]:
    """Assign each transcript word or segment to only one source range.

    Silence detection can split through a Whisper segment. Repeating the whole
    segment on every overlap makes adjacent ranges look like duplicate takes, so
    word-timestamped transcripts are distributed word by word. Legacy SRT
    segments without word timestamps go to their single best-overlap range.
    """

    parts: List[List[str]] = [[] for _range in ranges]

    def best_range(start: float, end: float) -> Optional[int]:
        best_index: Optional[int] = None
        best_overlap = 0.0
        for index, (range_start, range_end) in enumerate(ranges):
            overlap = max(0.0, min(end, range_end) - max(start, range_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_index = index
        return best_index

    for segment in transcript:
        if segment.words:
            for word in segment.words:
                index = best_range(word.start, word.end)
                if index is not None and word.text.strip():
                    parts[index].append(word.text.strip())
            continue
        index = best_range(segment.start, segment.end)
        if index is not None and segment.text.strip():
            parts[index].append(segment.text.strip())
    return [" ".join(items) for items in parts]


def _transcript_evidence_for_ranges(
    ranges: Sequence[Tuple[float, float]],
    transcript: Sequence[TranscriptSegment],
) -> List[bool]:
    """Return whether each audible range overlaps an actual transcript unit.

    Word timestamps are the useful signal when available. A Whisper segment can
    span handling noise between spoken words, so using the whole segment envelope
    would incorrectly classify those noises as speech. SRT input has no word
    timestamps, in which case segment overlap is the best evidence available.
    """

    evidence = [False for _range in ranges]
    for segment in transcript:
        units: Sequence[Union[TranscriptWord, TranscriptSegment]] = (
            segment.words if segment.words else (segment,)
        )
        for unit in units:
            if not unit.text.strip():
                continue
            for index, (range_start, range_end) in enumerate(ranges):
                if min(unit.end, range_end) > max(unit.start, range_start):
                    evidence[index] = True
    return evidence


def _group_fragmented_false_starts(
    regions: Sequence[SpeechRegion],
    repeated_word_spans: Sequence[RepeatedWordSpan],
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Join fragments of an earlier false start while preserving the last take.

    Separate repeated phrases can identify the first and last islands of one
    abandoned attempt while a non-matching stumble between them survives the
    ordinary per-region checks. Two repeat spans must progress through both
    attempts within a narrow window before the intervening earlier islands are
    nominated together. The later attempt is never replaced by this rule.
    """

    clusters: List[Dict[str, Any]] = []
    for span in repeated_word_spans:
        earlier_indices = {
            index
            for index, region in enumerate(regions)
            if min(span.end, region.end) > max(span.start, region.start)
        }
        later_indices = {
            index
            for index, region in enumerate(regions)
            if min(span.repeated_at_end, region.end)
            > max(span.repeated_at_start, region.start)
        }
        if not earlier_indices or not later_indices:
            continue

        cluster = next(
            (
                item
                for item in clusters
                if span.start >= item["earlier_start"]
                and span.start <= item["earlier_end"] + 20.0
                and span.repeated_at_start >= item["later_start"]
                and span.repeated_at_start <= item["later_end"] + 20.0
            ),
            None,
        )
        if cluster is None:
            clusters.append(
                {
                    "earlier_indices": set(earlier_indices),
                    "later_indices": set(later_indices),
                    "earlier_start": span.start,
                    "earlier_end": span.end,
                    "later_start": span.repeated_at_start,
                    "later_end": span.repeated_at_end,
                    "matched_word_count": span.matched_word_count,
                    "span_count": 1,
                    "spans": [span],
                }
            )
            continue
        cluster["earlier_indices"].update(earlier_indices)
        cluster["later_indices"].update(later_indices)
        cluster["earlier_end"] = max(cluster["earlier_end"], span.end)
        cluster["later_start"] = min(cluster["later_start"], span.repeated_at_start)
        cluster["later_end"] = max(cluster["later_end"], span.repeated_at_end)
        cluster["matched_word_count"] += span.matched_word_count
        cluster["span_count"] += 1
        cluster["spans"].append(span)

    forced_drops: Dict[str, str] = {}
    groups: List[Dict[str, Any]] = []
    for cluster in clusters:
        earlier_indices = sorted(cluster["earlier_indices"])
        if cluster["span_count"] < 2 or earlier_indices[-1] - earlier_indices[0] < 2:
            continue
        if (
            cluster["earlier_end"] - cluster["earlier_start"] > 30.0
            or cluster["later_end"] - cluster["later_start"] > 30.0
            or cluster["later_start"] <= cluster["earlier_end"]
        ):
            continue

        expanded_indices = list(range(earlier_indices[0], earlier_indices[-1] + 1))
        selected = [regions[index] for index in expanded_indices]
        endpoint_midpoints = (
            (selected[0].start + selected[0].end) / 2,
            (selected[-1].start + selected[-1].end) / 2,
        )
        if not all(
            any(span.start <= midpoint <= span.end for span in cluster["spans"])
            for midpoint in endpoint_midpoints
        ):
            continue

        # The endpoint regions are already removed by the ordinary repeated-span
        # rule. Only nominate the islands trapped between that proven evidence.
        trapped = selected[1:-1]
        duplicate_of = "source-{0:.3f}".format(cluster["later_start"])
        for region in trapped:
            forced_drops[region.id] = duplicate_of
        groups.append(
            {
                "reason": "fragmented_earlier_attempt",
                "matched_word_count": cluster["matched_word_count"],
                "span_count": cluster["span_count"],
                "earlier_start": selected[0].start,
                "earlier_end": selected[-1].end,
                "earlier_region_ids": [region.id for region in selected],
                "trapped_region_ids": [region.id for region in trapped],
                "repeated_at_start": cluster["later_start"],
                "repeated_at_end": cluster["later_end"],
            }
        )

    # A presenter can abandon a take, make several tiny restart noises, then
    # deliver another substantial attempt which is itself abandoned in favour
    # of a final take. In that shape the exact matcher proves A -> B -> C, but
    # the small islands between A and B do not contain enough matching words to
    # be rejected on their own. Only bridge two or more short islands when B is
    # independently proven to be an earlier version of C.
    def best_region_index(start: float, end: float) -> Optional[int]:
        overlaps = [
            (min(end, region.end) - max(start, region.start), index)
            for index, region in enumerate(regions)
            if min(end, region.end) > max(start, region.start)
        ]
        if not overlaps:
            return None
        return max(overlaps)[1]

    repeated_edges: Dict[Tuple[int, int], List[RepeatedWordSpan]] = defaultdict(list)
    for span in repeated_word_spans:
        earlier_index = best_region_index(span.start, span.end)
        later_index = best_region_index(span.repeated_at_start, span.repeated_at_end)
        if (
            earlier_index is not None
            and later_index is not None
            and later_index > earlier_index
        ):
            repeated_edges[(earlier_index, later_index)].append(span)

    for (earlier_index, later_index), edge_spans in sorted(repeated_edges.items()):
        trapped = list(regions[earlier_index + 1 : later_index])
        if len(trapped) < 2 or any(region.end - region.start > 3.0 for region in trapped):
            continue
        if regions[later_index].start - regions[earlier_index].end > 15.0:
            continue

        continuation_edges = [
            (target_index, spans)
            for (source_index, target_index), spans in repeated_edges.items()
            if source_index == later_index
            and target_index > later_index
            and regions[target_index].start - regions[later_index].end <= 15.0
        ]
        if not continuation_edges:
            continue
        continuation_index, continuation_spans = min(
            continuation_edges,
            key=lambda item: item[0],
        )

        duplicate_of = "source-{0:.3f}".format(regions[later_index].start)
        for region in trapped:
            forced_drops.setdefault(region.id, duplicate_of)
        groups.append(
            {
                "reason": "chained_false_start_attempts",
                "matched_word_count": sum(
                    span.matched_word_count for span in edge_spans + continuation_spans
                ),
                "span_count": len(edge_spans) + len(continuation_spans),
                "earlier_start": regions[earlier_index].start,
                "earlier_end": regions[later_index].end,
                "earlier_region_ids": [
                    region.id for region in regions[earlier_index : later_index + 1]
                ],
                "trapped_region_ids": [region.id for region in trapped],
                "repeated_at_start": regions[later_index].start,
                "repeated_at_end": regions[continuation_index].end,
                "final_region_id": regions[continuation_index].id,
            }
        )
    return forced_drops, groups


def _group_contextual_restart_fragments(
    regions: Sequence[SpeechRegion],
    decisions: Sequence[TakeDecision],
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Drop tiny restart fragments trapped inside a proven contextual retake."""

    region_index = {region.id: index for index, region in enumerate(regions)}
    decision_by_id = {decision.region_id: decision for decision in decisions}
    forced_drops: Dict[str, str] = {}
    groups: List[Dict[str, Any]] = []
    contextual_reasons = {
        "brief_take_repeated_later",
        "reworded_take_repeated_later",
        "short_clip_repeated_in_later_take",
        "incomplete_take_repeated_later",
    }
    for decision in decisions:
        if decision.decision != "drop" or decision.reason not in contextual_reasons:
            continue
        if decision.duplicate_of not in region_index:
            continue
        earlier_index = region_index[decision.region_id]
        later_index = region_index[decision.duplicate_of]
        if later_index <= earlier_index + 1:
            continue
        trapped = list(regions[earlier_index + 1 : later_index])
        if not trapped or any(
            region.end - region.start >= 5.0
            and decision_by_id[region.id].decision != "drop"
            for region in trapped
        ):
            continue

        newly_forced = [
            region
            for region in trapped
            if decision_by_id[region.id].decision != "drop"
            and region.end - region.start < 5.0
            and region.text.strip()
            and region.id not in forced_drops
        ]
        if not newly_forced:
            continue
        for region in newly_forced:
            forced_drops[region.id] = decision.duplicate_of
        groups.append(
            {
                "reason": "contextual_restart_fragments",
                "earlier_region_id": decision.region_id,
                "trapped_region_ids": [region.id for region in newly_forced],
                "final_region_id": decision.duplicate_of,
            }
        )
    return forced_drops, groups


def build_rough_cut_plan(
    *,
    source_name: str,
    duration_seconds: float,
    silences: Sequence[SilenceInterval],
    transcript: Sequence[TranscriptSegment],
    softening_buffer: float = 0.4,
    threshold_db: float = -35.0,
    minimum_silence: float = 0.5,
    duplicate_window: float = 90.0,
    auto_drop_confidence: float = 0.90,
    minimum_duplicate_words: int = 5,
    short_clip_suspicion_seconds: float = 5.0,
    drop_untranscribed_audio: bool = True,
) -> Dict[str, Any]:
    """Combine silence and transcript evidence into a reviewable cut plan."""

    duration = _finite_non_negative(duration_seconds, "duration_seconds")
    short_clip_threshold = _finite_non_negative(
        short_clip_suspicion_seconds,
        "short_clip_suspicion_seconds",
    )
    repeated_word_spans = detect_repeated_word_spans(
        transcript,
        minimum_words=minimum_duplicate_words,
        lookahead_seconds=duplicate_window,
    )
    speech_ranges = speech_regions_from_silences(
        duration,
        silences,
        softening_buffer=softening_buffer,
    )
    speech_ranges, internal_restart_splits = _split_ranges_at_leading_internal_restarts(
        speech_ranges,
        repeated_word_spans,
    )
    region_texts = _texts_for_ranges(speech_ranges, transcript)
    transcript_evidence = _transcript_evidence_for_ranges(speech_ranges, transcript)
    regions = [
        SpeechRegion(
            "speech-{0:04d}".format(index),
            start,
            end,
            region_texts[index - 1],
        )
        for index, (start, end) in enumerate(speech_ranges, start=1)
    ]
    decisions = detect_duplicate_takes(
        regions,
        lookahead_seconds=duplicate_window,
        auto_drop_confidence=auto_drop_confidence,
    )
    decision_by_id = {item.region_id: item for item in decisions}
    grouped_false_start_drops, fragmented_false_start_groups = (
        _group_fragmented_false_starts(regions, repeated_word_spans)
    )
    contextual_drops, contextual_groups = _group_contextual_restart_fragments(
        regions,
        decisions,
    )
    for group in contextual_groups:
        fresh_region_ids = [
            region_id
            for region_id in group["trapped_region_ids"]
            if region_id not in grouped_false_start_drops
        ]
        if not fresh_region_ids:
            continue
        for region_id in fresh_region_ids:
            grouped_false_start_drops[region_id] = contextual_drops[region_id]
        fragmented_false_start_groups.append(
            {**group, "trapped_region_ids": fresh_region_ids}
        )
    region_rows: List[Dict[str, Any]] = []
    keep_ranges: List[Tuple[float, float]] = []
    duplicate_ranges: List[Tuple[float, float]] = []
    non_speech_ranges: List[Tuple[float, float]] = []
    for region_index, region in enumerate(regions):
        decision = decision_by_id[region.id]
        midpoint = (region.start + region.end) / 2
        repeated_span = next(
            (
                span
                for span in repeated_word_spans
                if span.start <= midpoint <= span.end
                or (
                    span.start - region.start <= 1.0
                    and abs(span.repeated_at_start - region.end) <= 0.001
                )
            ),
            None,
        )
        if region.id in grouped_false_start_drops:
            decision = TakeDecision(
                region.id,
                "drop",
                0.95,
                "fragmented_false_start_group",
                grouped_false_start_drops[region.id],
            )
        elif repeated_span is not None:
            decision = TakeDecision(
                region.id,
                "drop",
                0.95,
                "repeated_word_sequence",
                "source-{0:.3f}".format(repeated_span.repeated_at_start),
            )
        elif not transcript_evidence[region_index]:
            decision = TakeDecision(
                region.id,
                "drop" if drop_untranscribed_audio else "review",
                0.90 if drop_untranscribed_audio else 0.0,
                (
                    "no_transcript_word_overlap"
                    if drop_untranscribed_audio
                    else "audible_region_has_no_transcript"
                ),
            )
        elif decision.decision == "keep" and _looks_like_recording_direction(region.text):
            decision = TakeDecision(
                region.id,
                "drop",
                0.95,
                "recording_direction",
            )
        elif (
            decision.decision == "keep"
            and region_index == len(regions) - 1
            and region.end - region.start < 2.0
            and set(_normalize_tokens(region.text)) <= {"ok", "okay"}
        ):
            decision = TakeDecision(
                region.id,
                "drop",
                0.95,
                "trailing_recording_marker",
            )
        elif (
            decision.decision == "keep"
            and _normalize_tokens(region.text)
            and set(_normalize_tokens(region.text)) <= {"ahem", "erm", "hmm", "uh", "um"}
        ):
            decision = TakeDecision(
                region.id,
                "drop",
                0.95,
                "filler_only",
            )
        elif (
            decision.decision == "keep"
            and short_clip_threshold > 0
            and region.end - region.start < short_clip_threshold
        ):
            decision = TakeDecision(
                region.id,
                "review",
                0.50,
                "short_clip_suspicious",
            )
        row = asdict(region)
        row.update(asdict(decision))
        row.pop("region_id", None)
        row["has_transcript_evidence"] = transcript_evidence[region_index]
        region_rows.append(row)
        if decision.decision == "drop":
            if decision.reason == "no_transcript_word_overlap":
                non_speech_ranges.append((region.start, region.end))
            else:
                duplicate_ranges.append((region.start, region.end))
        else:
            # The opt-out keeps untranscribed audio visible for manual review.
            keep_ranges.append((region.start, region.end))

    normalized_silences = _validate_intervals(silences, duration_seconds=duration)
    return {
        "schema_version": 1,
        "source": {
            "filename": source_name,
            "duration_seconds": duration,
        },
        "settings": {
            "threshold_db": float(threshold_db),
            "minimum_silence_seconds": float(minimum_silence),
            "softening_buffer_seconds": float(softening_buffer),
            "duplicate_window_seconds": float(duplicate_window),
            "auto_drop_confidence": float(auto_drop_confidence),
            "minimum_duplicate_words": minimum_duplicate_words,
            "short_clip_suspicion_seconds": short_clip_threshold,
            "drop_untranscribed_audio": bool(drop_untranscribed_audio),
        },
        "silences": [asdict(item) for item in normalized_silences],
        "regions": region_rows,
        "keep_ranges": [
            {"start": start, "end": end} for start, end in _merge_ranges(keep_ranges)
        ],
        "duplicate_drop_ranges": [
            {"start": start, "end": end} for start, end in duplicate_ranges
        ],
        "non_speech_drop_ranges": [
            {"start": start, "end": end} for start, end in non_speech_ranges
        ],
        "repeated_word_spans": [asdict(item) for item in repeated_word_spans],
        "internal_restart_splits": internal_restart_splits,
        "fragmented_false_start_groups": fragmented_false_start_groups,
        "review_required": any(
            row["decision"] in ("drop", "review") for row in region_rows
        ),
        "filmora_handoff": {
            "status": "writer_available_after_seed_check",
            "required_input": "A seed WFP with one untouched linked A/V source pair",
            "command": "rough-cut-project",
        },
    }


def build_rough_cut_inputs(
    *,
    source_name: str,
    duration_seconds: float,
    silences: Sequence[SilenceInterval],
    transcript: Sequence[TranscriptSegment],
    softening_buffer: float = 0.4,
    threshold_db: float = -35.0,
    minimum_silence: float = 0.5,
) -> Dict[str, Any]:
    """Build time-aligned sections without making editorial decisions.

    Video HQ sends this complete ordered transcript to Codex. Python owns the
    media-specific work only: silence boundaries, timestamps, and transcript
    text. It deliberately does not try to identify false starts or good takes.
    """

    duration = _finite_non_negative(duration_seconds, "duration_seconds")
    speech_ranges = speech_regions_from_silences(
        duration,
        silences,
        softening_buffer=softening_buffer,
    )
    region_texts = _texts_for_ranges(speech_ranges, transcript)
    transcript_evidence = _transcript_evidence_for_ranges(speech_ranges, transcript)
    regions = []
    for index, ((start, end), text, has_evidence) in enumerate(
        zip(speech_ranges, region_texts, transcript_evidence),
        start=1,
    ):
        regions.append(
            {
                "id": "speech-{0:04d}".format(index),
                "start": start,
                "end": end,
                "text": text,
                "decision": "review",
                "confidence": 0.0,
                "reason": "awaiting_codex_analysis",
                "duplicate_of": None,
                "has_transcript_evidence": has_evidence,
            }
        )

    return {
        "schema_version": 1,
        "source": {
            "filename": source_name,
            "duration_seconds": duration,
        },
        "settings": {
            "threshold_db": float(threshold_db),
            "minimum_silence_seconds": float(minimum_silence),
            "softening_buffer_seconds": float(softening_buffer),
            "classification": "codex",
        },
        "silences": [
            asdict(item)
            for item in _validate_intervals(silences, duration_seconds=duration)
        ],
        "regions": regions,
    }


def write_rough_cut_inputs(
    output_directory: Pathish,
    *,
    inputs: Dict[str, Any],
    transcript: Sequence[TranscriptSegment],
) -> Dict[str, str]:
    """Write the media evidence consumed by Video HQ's Codex analysis."""

    destination = Path(output_directory).expanduser().resolve()
    if destination.exists():
        raise WfpError("Refusing to overwrite rough-cut output: {0}".format(destination))
    destination.mkdir(parents=True)
    inputs_path = destination / "rough-cut-input.json"
    transcript_path = destination / "transcript.json"
    inputs_path.write_text(
        json.dumps(inputs, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    transcript_path.write_text(
        json.dumps(transcript_to_json(transcript), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "inputs": str(inputs_path),
        "transcript": str(transcript_path),
    }


def write_rough_cut_outputs(
    output_directory: Pathish,
    *,
    plan: Dict[str, Any],
    transcript: Sequence[TranscriptSegment],
) -> Dict[str, str]:
    """Write a new ignored/private result directory without overwriting files."""

    destination = Path(output_directory).expanduser().resolve()
    if destination.exists():
        raise WfpError("Refusing to overwrite rough-cut output: {0}".format(destination))
    destination.mkdir(parents=True)
    plan_path = destination / "rough-cut-plan.json"
    transcript_path = destination / "transcript.json"
    review_path = destination / "review.txt"
    plan_path.write_text(
        json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    transcript_path.write_text(
        json.dumps(transcript_to_json(transcript), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "Rough-cut review",
        "Source: {0}".format(plan["source"]["filename"]),
        "",
    ]
    for row in plan.get("regions") or []:
        if row.get("decision") not in ("drop", "review"):
            continue
        lines.append(
            "{0} {1:.3f}-{2:.3f} {3}: {4}".format(
                str(row.get("decision")).upper(),
                float(row.get("start")),
                float(row.get("end")),
                row.get("reason"),
                row.get("text") or "(no transcript)",
            )
        )
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "directory": str(destination),
        "plan": str(plan_path),
        "transcript": str(transcript_path),
        "review": str(review_path),
    }


def _ranges_from_rows(rows: Any, label: str) -> List[Tuple[float, float]]:
    if not isinstance(rows, list):
        raise WfpError("{0} must be an array".format(label))
    result: List[Tuple[float, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise WfpError("{0} contains an invalid range".format(label))
        start = _finite_non_negative(row.get("start"), "{0} start".format(label))
        end = _finite_non_negative(row.get("end"), "{0} end".format(label))
        if end <= start:
            raise WfpError("{0} ranges must have positive duration".format(label))
        result.append((start, end))
    return _merge_ranges(result)


def _range_duration(ranges: Sequence[Tuple[float, float]]) -> float:
    return sum(end - start for start, end in _merge_ranges(ranges))


def _range_intersection(
    first: Sequence[Tuple[float, float]],
    second: Sequence[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    left = _merge_ranges(first)
    right = _merge_ranges(second)
    result: List[Tuple[float, float]] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        start = max(left[left_index][0], right[right_index][0])
        end = min(left[left_index][1], right[right_index][1])
        if end > start:
            result.append((start, end))
        if left[left_index][1] < right[right_index][1]:
            left_index += 1
        else:
            right_index += 1
    return result


def compare_keep_ranges(
    predicted: Sequence[Tuple[float, float]],
    actual: Sequence[Tuple[float, float]],
) -> Dict[str, float]:
    """Return time-weighted keep precision, recall, and intersection-over-union."""

    predicted_seconds = _range_duration(predicted)
    actual_seconds = _range_duration(actual)
    intersection_seconds = _range_duration(_range_intersection(predicted, actual))
    union_seconds = predicted_seconds + actual_seconds - intersection_seconds
    return {
        "predicted_keep_seconds": predicted_seconds,
        "actual_keep_seconds": actual_seconds,
        "intersection_seconds": intersection_seconds,
        "keep_precision": intersection_seconds / predicted_seconds if predicted_seconds else 0.0,
        "keep_recall": intersection_seconds / actual_seconds if actual_seconds else 0.0,
        "keep_iou": intersection_seconds / union_seconds if union_seconds else 0.0,
    }


def evaluate_rough_cut_plan(
    plan: Union[Pathish, Dict[str, Any]],
    reference_project: Pathish,
    *,
    source_uuid: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare a proposed source-time keep list with a manually edited WFP."""

    if isinstance(plan, dict):
        payload = plan
    else:
        plan_path = Path(plan).expanduser().resolve()
        if not plan_path.is_file():
            raise WfpError("Rough-cut plan does not exist: {0}".format(plan_path))
        try:
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WfpError("Could not read rough-cut plan: {0}".format(exc)) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise WfpError("Rough-cut evaluation requires plan schema version 1")
    predicted = _ranges_from_rows(payload.get("keep_ranges"), "keep_ranges")

    # The established target discovery already resolves canonical linked pairs
    # and their absolute source bounds without exposing private media paths.
    from .edit_plan import list_edit_targets

    targets = list_edit_targets(reference_project).get("linked_av_targets") or []
    sources = sorted(
        {
            target.get("source_uuid")
            for target in targets
            if isinstance(target.get("source_uuid"), str)
        }
    )
    selected_source = source_uuid
    if selected_source is None:
        if len(sources) != 1:
            raise WfpError(
                "Reference project has {0} linked A/V sources; pass --source-uuid".format(
                    len(sources)
                )
            )
        selected_source = sources[0]
    selected = [target for target in targets if target.get("source_uuid") == selected_source]
    if not selected:
        raise WfpError("No linked A/V targets matched the requested source UUID")
    actual = [
        (float(target["in_point"]) / 10_000_000, float(target["out_point"]) / 10_000_000)
        for target in selected
    ]
    metrics = compare_keep_ranges(predicted, actual)
    duplicate_ranges = _ranges_from_rows(
        payload.get("duplicate_drop_ranges") or [],
        "duplicate_drop_ranges",
    )
    duplicate_seconds = _range_duration(duplicate_ranges)
    duplicate_false_seconds = _range_duration(_range_intersection(duplicate_ranges, actual))
    return {
        "plan_schema_version": 1,
        "reference_source_uuid": selected_source,
        "reference_linked_pair_count": len(selected),
        **metrics,
        "duplicate_drop_seconds": duplicate_seconds,
        "duplicate_correct_drop_seconds": duplicate_seconds - duplicate_false_seconds,
        "duplicate_false_drop_seconds": duplicate_false_seconds,
    }


def inspect_rough_cut_seed(project: Pathish) -> Dict[str, Any]:
    """Read-only check for the single-pair WFP accepted by the rough-cut writer."""

    # The import stays local so planning and transcription do not need to load
    # any of the archive writer machinery.
    from .rough_cut_wfp import inspect_rough_cut_seed_shape

    return inspect_rough_cut_seed_shape(project)
