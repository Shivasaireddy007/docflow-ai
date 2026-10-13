#!/usr/bin/env bash
# Serves the OCR model with vLLM on one GPU (tested settings for a 24 GB NVIDIA L4).
#   bench/serve-vllm.sh [model]
# Then: uv run bench/vision_bench.py --url http://localhost:8000 --model <model> --images data/cord-eval
set -euo pipefail
MODEL="${1:-Qwen/Qwen2.5-VL-3B-Instruct}"

# --max-num-seqs: requests batched together; more raises throughput until the GPU saturates.
# --gpu-memory-utilization: share of VRAM for weights + KV cache (PagedAttention blocks).
# --max-model-len: a receipt page is ~1-2k image tokens plus the transcript; 8k leaves headroom
#   and keeps more sequences' KV cache resident.
# --limit-mm-per-prompt: one page per request, as the pipeline sends them.
# --enable-prefix-caching: the prompt text is identical for every page.
docker run --rm --gpus all -p 8000:8000 --ipc=host \
  -v "${HF_HOME:-$HOME/.cache/huggingface}:/root/.cache/huggingface" \
  vllm/vllm-openai:latest \
  --model "$MODEL" \
  --max-num-seqs 32 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --limit-mm-per-prompt '{"image": 1}' \
  --enable-prefix-caching
