import hmac

provided_key = "invalid\xc3\xb1" # simulated latin-1 decode from ASGI
key = "validkey"

try:
    hmac.compare_digest(provided_key.encode('utf-8'), key.encode('utf-8'))
    print("Success")
except Exception as e:
    print(e)
