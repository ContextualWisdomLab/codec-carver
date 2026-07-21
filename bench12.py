import timeit

def parse_original(streams):
    # Fast path: O(N) loop to find audio stream and check for video in one pass
    # Avoids multiple generator expressions and any/next calls for measurable CPU savings on large files
    audio_stream = None
    has_video = False
    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type == "audio" and audio_stream is None:
            audio_stream = stream
        elif codec_type == "video":
            has_video = True
    return audio_stream, has_video

def parse_original_break(streams):
    audio_stream = None
    has_video = False
    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type == "audio" and audio_stream is None:
            audio_stream = stream
            if has_video: break
        elif codec_type == "video":
            has_video = True
            if audio_stream is not None: break
    return audio_stream, has_video


streams_many = [{"codec_type": "subtitle"}] * 100 + [{"codec_type": "audio"}, {"codec_type": "video"}] + [{"codec_type": "subtitle"}] * 100

print("Original:", timeit.timeit(lambda: parse_original(streams_many), number=1000000))
print("Optimized (break):", timeit.timeit(lambda: parse_original_break(streams_many), number=1000000))
