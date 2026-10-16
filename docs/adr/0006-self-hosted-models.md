# 6. Self-hosted open models behind an OpenAI-compatible API

**Context.** Receipts and invoices carry personal and financial data, and per-page API pricing
grows with volume.

**Decision.** Open models (Qwen2.5-VL for OCR, Qwen2.5 for fields), served by Ollama on a laptop and
by vLLM on a GPU, both reached through the OpenAI-compatible API. Temperature 0, a fixed seed, a
JSON schema for extraction, capped output, and anti-repetition sampling only when a model loops.

**Consequences.** Documents never leave infrastructure we control, costs are a GPU's hourly rate,
and models can be swapped by configuration. We own the serving: throughput depends on batching
(the [benchmark](../../bench/README.md)), and quality on choosing models
([model comparison](../evaluation/README.md)).

**Alternatives.** A hosted LLM API (simpler; data leaves; cost per page); a cloud document-AI
service (good OCR, little control over extraction and no self-hosting).
