import hmac

provided_key = "invalid\xc3\xb1" # simulated latin-1 decode from ASGI
key = "validkey"

try:
    hmac.compare_digest(provided_key, key)
except Exception as e:
    print(e)
