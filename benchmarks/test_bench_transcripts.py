"""Benchmarks for transcript post-processing: subtitles, search, diarization,
chapters and summarization.

All inputs are synthetic and generated in memory so the measured work is the
pure-Python processing, not file I/O.
"""

import random

import pytest

import chapters
import diarize
import subtitles
import summarize
import transcript_search
from media_shrinker import SilenceInterval

_VOCABULARY = (
    "audio recording meeting budget roadmap release codec opus flac silence "
    "segment transcript speaker model latency throughput archive metadata "
    "quarter planning review decision action customer feedback research "
    "experiment result analysis deadline migration pipeline storage"
).split()


def _sentence(rng: random.Random) -> str:
    """Return a pseudo-random sentence drawn from a fixed vocabulary."""
    words = [rng.choice(_VOCABULARY) for _ in range(rng.randint(6, 18))]
    words[0] = words[0].capitalize()
    return " ".join(words) + rng.choice((".", "!", "?", "."))


def _transcript(count: int, seed: int = 1234) -> list[tuple[float, float, str]]:
    """Return ``count`` contiguous (start, end, text) transcript segments."""
    rng = random.Random(seed)
    segments = []
    cursor = 0.0
    for _ in range(count):
        length = rng.uniform(1.5, 8.0)
        segments.append((cursor, cursor + length, _sentence(rng)))
        cursor += length + rng.uniform(0.0, 0.6)
    return segments


_RAW_SEGMENTS = _transcript(2_000)
_TOTAL_DURATION = _RAW_SEGMENTS[-1][1] + 1.0


@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_subtitles_render(benchmark, fmt):
    """Render a 2,000-cue transcript to SRT/WebVTT."""
    cues = [subtitles.Segment(start, end, text) for start, end, text in _RAW_SEGMENTS]
    render = subtitles.to_srt if fmt == "srt" else subtitles.to_vtt
    output = benchmark(render, cues)
    assert output


def test_transcript_index_build(benchmark):
    """Build an inverted index over several recordings' transcripts."""
    recordings = {
        f"recording-{index:02d}.flac": [
            transcript_search.Segment(start, end, text)
            for start, end, text in _transcript(500, seed=index)
        ]
        for index in range(8)
    }

    def build():
        index = transcript_search.TranscriptIndex()
        for recording_id, segments in recordings.items():
            index.add(recording_id, segments)
        return index

    assert len(benchmark(build)) == 4_000


@pytest.mark.parametrize(
    "query",
    [
        pytest.param("budget", id="single_term"),
        pytest.param("release roadmap decision", id="multi_term"),
    ],
)
def test_transcript_index_search(benchmark, query):
    """Run AND-semantics queries against a populated transcript index."""
    index = transcript_search.TranscriptIndex()
    for recording in range(8):
        index.add(
            f"recording-{recording:02d}.flac",
            (
                transcript_search.Segment(start, end, text)
                for start, end, text in _transcript(500, seed=recording)
            ),
        )
    matches = benchmark(index.search, query)
    assert matches


def test_tokenize(benchmark):
    """Tokenize transcript text for indexing."""
    texts = [text for _, _, text in _RAW_SEGMENTS]

    def tokenize_all():
        return sum(len(transcript_search.tokenize(text)) for text in texts)

    assert benchmark(tokenize_all) > 0


def test_diarize_merge_with_transcript(benchmark):
    """Attribute transcript segments to speakers by maximum time overlap."""
    rng = random.Random(99)
    turns = []
    cursor = 0.0
    while cursor < _TOTAL_DURATION:
        length = rng.uniform(3.0, 40.0)
        turns.append(
            diarize.SpeakerTurn(
                start=cursor,
                end=cursor + length,
                speaker=f"SPEAKER_{rng.randint(0, 3):02d}",
            )
        )
        cursor += length
    segments = [
        subtitles.Segment(start, end, text) for start, end, text in _RAW_SEGMENTS[:1_000]
    ]
    merged = benchmark(diarize.merge_with_transcript, turns, segments)
    assert len(merged) == len(segments)


def test_detect_chapters(benchmark):
    """Propose chapters for a 12h recording from ~1,000 silence intervals."""
    rng = random.Random(7)
    total = 12 * 60 * 60.0
    silences = []
    cursor = 0.0
    while cursor < total:
        cursor += rng.uniform(10.0, 80.0)
        silences.append(
            SilenceInterval(start_seconds=cursor, end_seconds=cursor + rng.uniform(0.5, 9.0))
        )
    rng.shuffle(silences)
    result = benchmark(chapters.detect_chapters, silences, total)
    assert result


def test_chapters_serialize(benchmark):
    """Serialize detected chapters to FFMETADATA and JSON."""
    silences = [
        SilenceInterval(start_seconds=start, end_seconds=start + 5.0)
        for start in range(90, 43_200, 90)
    ]
    detected = chapters.detect_chapters(silences, 43_200.0)

    def serialize():
        return chapters.to_ffmetadata(detected), chapters.to_json(detected)

    ffmetadata, as_json = benchmark(serialize)
    assert ffmetadata and as_json


def test_summarize_segments(benchmark):
    """Produce an extractive summary of a long transcript."""
    segments = [
        subtitles.Segment(start, end, text) for start, end, text in _RAW_SEGMENTS[:600]
    ]
    summary = benchmark(summarize.summarize_segments, segments, 8)
    assert summary
