import hmac
try:
    hmac.compare_digest("hello", "world")
    print("ASCII works")
    hmac.compare_digest("hello", "안녕")
except Exception as e:
    print(f"Exception: {repr(e)}")
