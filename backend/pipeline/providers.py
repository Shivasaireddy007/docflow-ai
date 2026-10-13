"""OCR and field extraction with self-hosted models.

Two ways to reach a model server, chosen with MODEL_API: Ollama's own API (local development)
or the OpenAI-compatible API that vLLM serves (GPU deployments; Ollama speaks it too). Both use
temperature 0 and a fixed seed, so a document processed twice by the same pipeline version gives
the same result, and extraction is constrained to the receipt JSON schema.
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
- Amounts are plain numbers without currency symbols or thousands separators. A separator followed
  by exactly three digits groups thousands (12.500 or 12,500 -> 12500); followed by one or two
  digits it is the decimal point (38.90 -> 38.9, 6,35 -> 6.35). Keep the decimals.
- total is the final amount payable, printed as TOTAL, GRAND TOTAL, AMOUNT DUE, DUE, TOTAL BAYAR or
  JUMLAH. It is never the CASH amount handed over, the CHANGE returned, or the SUBTOTAL.
- cash_paid is the CASH (TUNAI) amount handed over; change is the CHANGE (KEMBALI) returned.
- OCR sometimes lists the labels (SUBTOTAL, TAX, TOTAL, CASH, CHANGE) and then a column of amounts:
  pair them in the same order.
- receipt_date is YYYY-MM-DD. currency is the 3-letter ISO code, only if a currency code or symbol is printed.
- line_items are the purchased items in order; amount is the printed line total.

Receipt text:
"""


class ModelError(Exception):
    """The model server failed or returned something unusable. Worth retrying."""


class ModelRepetition(ModelError):
    """The model fell into a loop ("0000...") and was cut off. Deterministic: the same input loops
    again, so the page is retried once with anti-repetition sampling instead of as-is."""


# Used only after a repetition loop: penalise repeats and sample a little (still seeded).
ANTI_REPETITION = {"repeat_penalty": 1.25, "temperature": 0.3}


class OcrProvider(Protocol):
    model: str

    def __call__(self, pages: list[bytes]) -> str: ...


class ExtractionProvider(Protocol):
    model: str

    def __call__(self, text: str) -> dict[str, Any]: ...


class ChatClient(Protocol):
    def chat(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int,
        images: list[bytes] | None = None,
        schema: dict[str, Any] | None = None,
        sampling: dict[str, float] | None = None,
    ) -> str: ...


class OllamaClient:
    """Ollama's native /api/chat."""

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
        sampling: dict[str, float] | None = None,
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
            "options": {"temperature": 0, "seed": 7, "num_predict": max_tokens, **(sampling or {})},
            "keep_alive": "30m",
        }
        if schema is not None:
            body["format"] = schema
        if self._before_call is not None:
            self._before_call(model)
        try:
            response = self._http.post("/api/chat", json=body)
            if response.status_code == 500 and "repeat limit" in response.text:
                raise ModelRepetition(f"{model} repeated itself until it was stopped")
            response.raise_for_status()
            reply = response.json()
            content = reply["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ModelError(f"{model} failed: {exc}") from exc
        if reply.get("done_reason") == "length":
            raise ModelRepetition(f"{model} ran past {max_tokens} tokens")
        return str(content)


class OpenAIClient:
    """The OpenAI-compatible /v1/chat/completions served by vLLM (and Ollama, and others)."""

    def __init__(
        self,
        base_url: str,
        timeout: float,
        api_key: str = "",
        transport: httpx.BaseTransport | None = None,
        before_call: Callable[[str], None] | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport, headers=headers)
        self._before_call = before_call

    def chat(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int,
        images: list[bytes] | None = None,
        schema: dict[str, Any] | None = None,
        sampling: dict[str, float] | None = None,
    ) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images or []:
            url = "data:image/png;base64," + base64.b64encode(image).decode()
            content.append({"type": "image_url", "image_url": {"url": url}})
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "seed": 7,
            "max_tokens": max_tokens,
        }
        if sampling:  # vLLM calls the repeat penalty repetition_penalty
            body["temperature"] = sampling.get("temperature", 0)
            body["repetition_penalty"] = sampling.get("repeat_penalty", 1.0)
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "receipt", "schema": schema, "strict": True},
            }
        if self._before_call is not None:
            self._before_call(model)
        try:
            response = self._http.post("/v1/chat/completions", json=body)
            response.raise_for_status()
            choice = response.json()["choices"][0]
            text = choice["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ModelError(f"{model} failed: {exc}") from exc
        if choice.get("finish_reason") == "length":
            raise ModelRepetition(f"{model} ran past {max_tokens} tokens")
        return str(text)


class Ocr:
    def __init__(self, client: ChatClient, model: str) -> None:
        self.client = client
        self.model = model

    def __call__(self, pages: list[bytes]) -> str:
        # One page per request keeps each image within the model's context.
        return "\n\n".join(self._read(page) for page in pages)

    def _read(self, page: bytes) -> str:
        try:
            return self.client.chat(self.model, OCR_PROMPT, images=[page], max_tokens=2048).strip()
        except ModelRepetition:
            log.warning("%s looped on a page; reading it again with anti-repetition sampling", self.model)
            return self.client.chat(
                self.model, OCR_PROMPT, images=[page], max_tokens=2048, sampling=ANTI_REPETITION
            ).strip()


class Extractor:
    def __init__(self, client: ChatClient, model: str) -> None:
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


def make_client(before_call: Callable[[str], None] | None = _rate_limited) -> ChatClient:
    if settings.MODEL_API == "openai":
        return OpenAIClient(
            settings.MODEL_URL,
            settings.MODEL_TIMEOUT_SECONDS,
            settings.MODEL_API_KEY,
            before_call=before_call,
        )
    return OllamaClient(settings.MODEL_URL, settings.MODEL_TIMEOUT_SECONDS, before_call=before_call)


def default_providers() -> tuple[OcrProvider, ExtractionProvider]:
    client = make_client()
    return Ocr(client, settings.OCR_MODEL), Extractor(client, settings.EXTRACTION_MODEL)
