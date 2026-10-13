"""HMAC signatures for the pipeline's callback to the review app.

The AWS pipeline reports each result to Django over HTTPS. The body is signed with a shared
secret together with a timestamp, so a forged or replayed callback is refused:

    X-Docflow-Timestamp: <unix seconds>
    X-Docflow-Signature: hex(HMAC-SHA256(secret, "<timestamp>.<body>"))
"""

import hashlib
import hmac
import time

MAX_AGE_SECONDS = 300


def sign(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Docflow-Timestamp": ts, "X-Docflow-Signature": digest}


def verify(secret: str, body: bytes, timestamp: str, signature: str, now: float | None = None) -> bool:
    """Constant-time check of the signature, and that it is recent enough not to be a replay."""
    if not secret or not timestamp.isdigit():
        return False
    if abs((time.time() if now is None else now) - int(timestamp)) > MAX_AGE_SECONDS:
        return False
    expected = sign(secret, body, int(timestamp))["X-Docflow-Signature"]
    return hmac.compare_digest(expected, signature)
