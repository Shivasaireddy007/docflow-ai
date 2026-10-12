import base64
import json
from typing import Any

import httpx
import pytest

from pipeline.providers import ModelError, OllamaClient, OllamaExtractor, OllamaOcr
from pipeline.schema import JSON_SCHEMA


class FakeOllama:
    def __init__(self, replies: list[httpx.Response]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        return self.replies.pop(0)

    def client(self) -> OllamaClient:
        return OllamaClient("http://ollama", 5, transport=httpx.MockTransport(self.handle))


def reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


def test_ocr_sends_each_page_as_an_image_deterministically() -> None:
    server = FakeOllama([reply("page one"), reply("page two")])

    text = OllamaOcr(server.client(), "qwen2.5vl:3b")([b"png-1", b"png-2"])

    assert text == "page one\n\npage two"
    first = server.requests[0]
    assert first["model"] == "qwen2.5vl:3b"
    assert first["messages"][0]["images"] == [base64.b64encode(b"png-1").decode()]
    assert first["options"] == {"temperature": 0, "seed": 7, "num_predict": 2048}
    assert first["keep_alive"] == "30m"
    assert "format" not in first


def test_extraction_is_constrained_to_the_schema() -> None:
    server = FakeOllama([reply('{"total": 56100}')])

    result = OllamaExtractor(server.client(), "qwen2.5:7b")("TOTAL 56.100")

    assert result == {"total": 56100}
    assert server.requests[0]["format"] == JSON_SCHEMA
    assert server.requests[0]["messages"][0]["content"].endswith("TOTAL 56.100")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="model crashed"),
        reply("Sure! The total is 56100."),
        reply("[1, 2, 3]"),
        httpx.Response(200, json={"error": "unexpected"}),
    ],
)
def test_server_failures_and_bad_output_raise_a_retryable_error(response: httpx.Response) -> None:
    server = FakeOllama([response])

    with pytest.raises(ModelError):
        OllamaExtractor(server.client(), "qwen2.5:7b")("text")
