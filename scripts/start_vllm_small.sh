#!/usr/bin/env bash
# Smallest practical Qwen instruct; low KV and VRAM use. No sudo.
# Requires: conda env with vllm (see AGENTS.md) or adjust VLLM_BIN.
set -euo pipefail
PORT="${1:-8000}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
VLLM_BIN="${VLLM_BIN:-/home/kudrevskaia/miniconda/bin/vllm}"
exec "$VLLM_BIN" serve Qwen/Qwen2.5-0.5B-Instruct \
  --port "$PORT" \
  --max-model-len 2048 \
  --gpu-memory-utilization 0.75 \
  --max-num-seqs 8 \
  --disable-log-requests
