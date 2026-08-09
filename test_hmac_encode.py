import hmac
try:
    hmac.compare_digest("hello".encode('utf-8'), "안녕".encode('utf-8'))
    print("Bytes work")
except Exception as e:
    print(f"Exception: {repr(e)}")
