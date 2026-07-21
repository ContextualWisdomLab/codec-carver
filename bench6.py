import timeit

def f1():
    streams = [{"codec_type": "audio", "codec_name": "aac"}, {"codec_type": "video", "codec_name": "h264"}]
    # Fast path: O(N) loop to find audio stream and check for video in one pass
    has_video = False
    audio_stream = None
    for stream in streams:
        if stream.get("codec_type") == "video":
            has_video = True
        elif audio_stream is None and stream.get("codec_type") == "audio":
            audio_stream = stream
    return has_video, audio_stream

print("f1:", timeit.timeit(f1, number=1000000))
