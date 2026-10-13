# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28", "pillow>=11"]
# ///
"""Throughput and latency of a vision model doing OCR, at increasing concurrency.

Sends real receipt pages to an OpenAI-compatible server (vLLM, or Ollama's /v1) the way the
pipeline's OCR step does, and reports pages per second, p50 and p95 latency, and errors for
each concurrency level. Results go to results/<name>.json and a Markdown table on stdout.

    uv run bench/vision_bench.py --url http://localhost:8000 --model Qwen/Qwen2.5-VL-3B-Instruct \\
        --images data/cord-eval --concurrency 1 2 4 8 16 --requests 64 --name l4-vllm
"""

import argparse
import asyncio
import base64
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from PIL import Image

MAX_SIDE_PX = 1600  # what the pipeline scales pages to before OCR (backend/pipeline/files.py)

PROMPT = (
    "Transcribe all the text on this receipt exactly as printed, line by line, top to bottom. "
    "Keep numbers exactly as they appear, including separators. Output only the transcribed text."
)


def prepare(path: Path) -> bytes:
    """A page as the pipeline sends it: RGB, longest side at most 1600 px, as PNG."""
    import io

    with Image.open(path) as image:
        page = image.convert("RGB")
        page.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
        out = io.BytesIO()
        page.save(out, format="PNG")
        return out.getvalue()


def payload(model: str, image: bytes, max_tokens: int) -> dict[str, object]:
    url = "data:image/png;base64," + base64.b64encode(image).decode()
    return {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT}, {"type": "image_url", "image_url": {"url": url}},
        ]}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }  # fmt: skip


async def one(client: httpx.AsyncClient, body: dict[str, object]) -> tuple[float, int, str | None]:
    """(seconds, output tokens, error kind or None)."""
    started = time.perf_counter()
    try:
        response = await client.post("/v1/chat/completions", json=body)
        if response.status_code >= 400:
            kind = "repetition loop" if "repeat" in response.text else f"HTTP {response.status_code}: {response.text[:80]}"
            return time.perf_counter() - started, 0, kind
        tokens = int(response.json().get("usage", {}).get("completion_tokens", 0))
    except (httpx.HTTPError, ValueError) as exc:
        return time.perf_counter() - started, 0, type(exc).__name__
    return time.perf_counter() - started, tokens, None


async def level(args: argparse.Namespace, images: list[bytes], concurrency: int, offset: int) -> dict[str, object]:
    """One concurrency level, on images no earlier level has sent: a server that reuses work for
    content it has seen (prefix or image caching) would otherwise flatter the later levels."""
    limits = httpx.Limits(max_connections=concurrency)
    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    async with httpx.AsyncClient(base_url=args.url, timeout=600, limits=limits, headers=headers) as client:
        await one(client, payload(args.model, images[offset % len(images)], args.max_tokens))  # warm-up
        gate = asyncio.Semaphore(concurrency)

        async def run(i: int) -> tuple[float, int, str | None]:
            async with gate:
                image = images[(offset + 1 + i) % len(images)]
                return await one(client, payload(args.model, image, args.max_tokens))

        started = time.perf_counter()
        results = await asyncio.gather(*(run(i) for i in range(args.requests)))
        wall = time.perf_counter() - started

    latencies = [r[0] for r in results if r[2] is None]
    errors: dict[str, int] = {}
    for _, _, kind in results:
        if kind:
            errors[kind] = errors.get(kind, 0) + 1
    cuts = statistics.quantiles(latencies, n=100, method="inclusive") if len(latencies) > 1 else latencies * 99
    return {
        "concurrency": concurrency,
        "requests": args.requests,
        "errors": errors,
        "pages_per_second": round(len(latencies) / wall, 3),
        "output_tokens_per_second": round(sum(r[1] for r in results) / wall, 1),
        "p50_ms": round(cuts[49] * 1000) if latencies else None,
        "p95_ms": round(cuts[94] * 1000) if latencies else None,
    }


def table(rows: list[dict[str, object]]) -> str:
    lines = [
        "| Concurrency | Pages/s | Output tokens/s | p50 | p95 | Errors |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['concurrency']} | {r['pages_per_second']} | {r['output_tokens_per_second']} | "
            f"{(r['p50_ms'] or 0) / 1000:.1f} s | {(r['p95_ms'] or 0) / 1000:.1f} s | "
            f"{', '.join(f'{n} {k}' for k, n in r['errors'].items()) or 0} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="Server base URL, without /v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--images", type=Path, required=True, help="Folder of .jpg/.png pages")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--requests", type=int, default=32, help="Requests per concurrency level")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--name", default="run")
    parser.add_argument("--hardware", default=platform.machine(), help="Recorded with the results")
    args = parser.parse_args()

    paths = sorted(p for p in args.images.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    images = [prepare(p) for p in paths]
    if not images:
        raise SystemExit(f"No images in {args.images}")
    if len(images) < len(args.concurrency) * (args.requests + 1):
        print(f"Note: {len(images)} images for {len(args.concurrency) * (args.requests + 1)} requests; some repeat")
    rows = []
    for index, concurrency in enumerate(args.concurrency):
        row = asyncio.run(level(args, images, concurrency, offset=index * (args.requests + 1)))
        print(json.dumps(row), flush=True)
        rows.append(row)

    out = Path(__file__).parent / "results" / f"{args.name}.json"
    out.write_text(json.dumps({
        "date": datetime.now(UTC).isoformat(timespec="seconds"), "url": args.url, "model": args.model,
        "hardware": args.hardware, "images": len(images), "max_tokens": args.max_tokens, "levels": rows,
    }, indent=1))  # fmt: skip
    print(f"\n{args.model} on {args.hardware}\n\n{table(rows)}\n\nSaved {out}")


if __name__ == "__main__":
    main()
