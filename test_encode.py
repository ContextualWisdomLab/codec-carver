import hmac

provided_key = "\xff"
configured_keys = ["secret-key"]

try:
    any(hmac.compare_digest(provided_key.encode("utf-8"), key.encode("utf-8")) for key in configured_keys)
    print("UTF-8 works")
except Exception as e:
    print(repr(e))
