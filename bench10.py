import timeit

streams = [
    {"index": 0, "codec_name": "hevc", "codec_type": "video", "width": 1920, "height": 1080},
    {"index": 1, "codec_name": "aac", "codec_type": "audio", "channels": 2},
    {"index": 2, "codec_name": "subrip", "codec_type": "subtitle"}
]

def test_original():
    has_video = any(s.get("codec_type") == "video" for s in streams)
    audio_stream = next(
        (s for s in streams if s.get("codec_type") == "audio"), None
    )
    return has_video, audio_stream

def test_optimized():
    has_video = False
    audio_stream = None
    for stream in streams:
        t = stream.get("codec_type")
        if t == "video":
            has_video = True
        elif t == "audio" and audio_stream is None:
            audio_stream = stream
    return has_video, audio_stream

print("Original:", timeit.timeit(test_original, number=1000000))
print("Optimized:", timeit.timeit(test_optimized, number=1000000))
