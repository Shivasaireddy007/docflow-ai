import time

from core import signing


def test_a_signed_body_verifies() -> None:
    headers = signing.sign("s3cret", b'{"a": 1}')

    assert signing.verify(
        "s3cret", b'{"a": 1}', headers["X-Docflow-Timestamp"], headers["X-Docflow-Signature"]
    )


def test_tampering_the_wrong_secret_and_replays_are_refused() -> None:
    headers = signing.sign("s3cret", b'{"total": 100}')
    ts, sig = headers["X-Docflow-Timestamp"], headers["X-Docflow-Signature"]

    assert not signing.verify("s3cret", b'{"total": 999}', ts, sig)
    assert not signing.verify("other", b'{"total": 100}', ts, sig)
    assert not signing.verify("", b'{"total": 100}', ts, sig), "no secret configured: refuse everything"
    assert not signing.verify("s3cret", b'{"total": 100}', ts, sig, now=time.time() + 600), "replayed later"
    assert not signing.verify("s3cret", b'{"total": 100}', "not-a-time", sig)
