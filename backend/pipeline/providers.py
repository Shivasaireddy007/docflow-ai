"""OCR and field extraction with self-hosted models served by Ollama.

Both steps call the same chat endpoint with temperature 0 and a fixed seed, so a document
processed twice by the same pipeline version gives the same result. Extraction is constrained
to the receipt JSON schema, so the model can't return free text.
"""

import base64
import json
import logging
from collections.abc import Callable
from typing import Any, Protocol

import httpx
from django.conf import settings

from pipeline.schema import JSON_SCHEMA

log = logging.getLogger(__name__)

OCR_PROMPT = (
    "Transcribe all the text on this receipt exactly as printed, line by line, top to bottom. "
    "Keep numbers exactly as they appear, including separators. Output only the transcribed text."
)
EXTRACTION_PROMPT = """You extract fields from receipt text produced by OCR.
Return JSON matching the schema. Rules:
- Use null for anything not on the receipt. Never guess or calculate a value that isn't printed.
- Amounts are plain numbers without currency symbols or thousands separators (12.500 or 12,500 -> 12500).
- receipt_date is YYYY-MM-DD. currency is the 3-letter ISO code, only if a currency code or symbol is printed.
- line_items are the purchased items in order; amount is the printed line total.

Receipt text:
"""


class ModelError(Exception):
    """The model server failed or returned something unusable. Worth retrying."""


class OcrProvider(Protocol):
    model: str

    def __call__(self, pages: list[bytes]) -> str: ...


class ExtractionProvider(Protocol):
    model: str

    def __call__(self, text: str) -> dict[str, Any]: ...


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        before_call: Callable[[str], None] | None = None,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        self._before_call = before_call  # e.g. wait for a rate-limit token

    def chat(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int,
        images: list[bytes] | None = None,
        schema: dict[str, Any] | None = None,
    ) -> str:
        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            message["images"] = [base64.b64encode(image).decode() for image in images]
        body: dict[str, Any] = {
            "model": model,
            "messages": [message],
            "stream": False,
            # Capped output stops a model that starts repeating itself; keep_alive keeps the OCR
            # and extraction models both loaded instead of swapping them for every document.
            "options": {"temperature": 0, "seed": 7, "num_predict": max_tokens},
            "keep_alive": "30m",
        }
        if schema is not None:
            body["format"] = schema
        if self._before_call is not None:
            self._before_call(model)
        try:
            response = self._http.post("/api/chat", json=body)
            response.raise_for_status()
            content = response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ModelError(f"{model} failed: {exc}") from exc
        return str(content)


class OllamaOcr:
    def __init__(self, client: OllamaClient, model: str) -> None:
        self.client = client
        self.model = model

    def __call__(self, pages: list[bytes]) -> str:
        # One page per request keeps each image within the model's context.
        texts = [
            self.client.chat(self.model, OCR_PROMPT, images=[page], max_tokens=2048).strip() for page in pages
        ]
        return "\n\n".join(texts)


class OllamaExtractor:
    def __init__(self, client: OllamaClient, model: str) -> None:
        self.client = client
        self.model = model

    def __call__(self, text: str) -> dict[str, Any]:
        content = self.client.chat(self.model, EXTRACTION_PROMPT + text, schema=JSON_SCHEMA, max_tokens=1024)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelError(f"{self.model} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ModelError(f"{self.model} returned {type(data).__name__}, not an object")
        return data


def ocr_version() -> str:
    return f"{settings.OCR_MODEL};ocr-prompt={settings.OCR_PROMPT_VERSION}"


def extraction_version() -> str:
    return f"{settings.EXTRACTION_MODEL};prompt={settings.PROMPT_VERSION}"


def pipeline_version() -> str:
    """Identifies what produced a result; stored with it. Each step's part keys its cache entries."""
    return (
        f"ocr={settings.OCR_MODEL};llm={settings.EXTRACTION_MODEL};"
        f"prompt={settings.PROMPT_VERSION};ocr-prompt={settings.OCR_PROMPT_VERSION}"
    )


class ModelBusy(ModelError):
    """No rate-limit token within the wait: the job is retried later rather than piling on."""


def _rate_limited(model: str) -> None:
    from core.ratelimit import Bucket, get_limiter

    if not get_limiter().wait(f"model:{model}", Bucket.parse(settings.MODEL_RATE), timeout=30):
        raise ModelBusy(f"{model} is at its request limit")


def default_providers() -> tuple[OcrProvider, ExtractionProvider]:
    client = OllamaClient(settings.OLLAMA_URL, settings.MODEL_TIMEOUT_SECONDS, before_call=_rate_limited)
    return OllamaOcr(client, settings.OCR_MODEL), OllamaExtractor(client, settings.EXTRACTION_MODEL)
