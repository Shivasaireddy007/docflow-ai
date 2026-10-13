# Serving benchmark

How fast the OCR model reads receipt pages, and how that changes with concurrency.
[`vision_bench.py`](vision_bench.py) sends real CORD pages, scaled the way the pipeline scales
them, to any OpenAI-compatible server (vLLM, or Ollama's `/v1`). Each concurrency level uses
pages no earlier level has sent, so a server that reuses work on content it has seen can't
flatter the later levels. Raw results are in [`results/`](results/).

```bash
uv run bench/vision_bench.py --url <server> --model <model> --images data/cord-eval \
    --concurrency 1 2 4 8 16 --requests 32 --name <run> --hardware "<what it ran on>"
```

## Apple M5 laptop, Ollama

`qwen2.5vl:3b`, 16 pages per level:

| Concurrency | Default settings: pages/s | p50 | p95 | `OLLAMA_NUM_PARALLEL=4`: pages/s | p50 | p95 |
|---|---|---|---|---|---|---|
| 1 | 0.14 | 6.7 s | 9.7 s | 0.14 | 6.5 s | 11.0 s |
| 2 | 0.14 | 13.8 s | 17.8 s | 0.13 | 15.7 s | 25.4 s |
| 4 | 0.12 | 32.8 s | 39.1 s | 0.14 | 29.3 s | 54.5 s |

Throughput stays at about 0.14 pages per second whatever the concurrency, and latency grows with
it: requests queue. Giving Ollama four parallel slots doesn't help either; one vision request
already keeps the laptop's GPU busy, so parallel requests just take turns. At this rate 1,000
pages take about two hours. On a laptop, more concurrency only adds waiting; throughput has to come
from a server that batches requests on a GPU with room for them.

## On a GPU: vLLM

[`serve-vllm.sh`](serve-vllm.sh) serves the model with vLLM, which batches concurrent requests
continuously and keeps their KV cache in pages (PagedAttention), so throughput should rise with
concurrency until the GPU saturates. The settings that matter, all flags in the script:

| Setting | Why |
|---|---|
| `--max-num-seqs 32` | How many requests share a batch; the main throughput lever |
| `--gpu-memory-utilization 0.90` | VRAM for weights plus KV cache; more cache means more concurrent pages |
| `--max-model-len 8192` | A page is roughly 1-2k image tokens plus the transcript; a shorter limit leaves room for more sequences |
| `--limit-mm-per-prompt '{"image": 1}'` | One page per request, as the pipeline sends them |
| `--enable-prefix-caching` | The instruction text is the same for every page |

To measure it on an NVIDIA L4 (24 GB), for example a `g6.xlarge` on AWS or an L4 from a GPU
cloud, at roughly ₹60-100 an hour:

```bash
bench/serve-vllm.sh Qwen/Qwen2.5-VL-3B-Instruct            # on the GPU machine
uv run bench/vision_bench.py --url http://<gpu-host>:8000 --model Qwen/Qwen2.5-VL-3B-Instruct \
    --images data/cord-eval --concurrency 1 2 4 8 16 32 --requests 32 --name l4-vllm --hardware "NVIDIA L4, vLLM"
```

Then point the pipeline at it: `MODEL_API=openai MODEL_URL=http://<gpu-host>:8000` (Terraform:
`model_api` and `model_url`). Cost per 1,000 pages is the GPU's hourly price × 1,000 / (pages per
second × 3,600), so the benchmark's best pages-per-second figure sets the cost.

Not yet run: it needs a rented GPU. The table above is the laptop baseline it will be compared
against.
