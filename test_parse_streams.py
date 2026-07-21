import json

def parse_original(streams):
    audio_stream = None
    has_video = False
    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type == "audio" and audio_stream is None:
            audio_stream = stream
        elif codec_type == "video":
            has_video = True
    return audio_stream, has_video

def parse_optimized(streams):
    audio_stream = None
    has_video = False
    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type == "audio" and audio_stream is None:
            audio_stream = stream
            if has_video:
                break
        elif codec_type == "video":
            has_video = True
            if audio_stream is not None:
                break
    return audio_stream, has_video

import timeit

s1 = [{"codec_type": "subtitle"}] * 100 + [{"codec_type": "audio"}, {"codec_type": "video"}] + [{"codec_type": "subtitle"}] * 100

print("Original:", timeit.timeit(lambda: parse_original(s1), number=1000000))
print("Optimized:", timeit.timeit(lambda: parse_optimized(s1), number=1000000))
