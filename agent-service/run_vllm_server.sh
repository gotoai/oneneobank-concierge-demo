#!/usr/bin/env bash
# run_vllm_server.sh — start the vLLM OpenAI-compatible server for the concierge.
#
# This process IS the continuous-batching engine and the ONLY place the model is
# loaded. vLLM batches every concurrent request into one running decode loop
# automatically (on by default; there is no flag to "enable" it). Start this once;
# the gateway (agent.api_vllm) and any number of web clients then share it.
#
# Layout (see agent/api_vllm.py):
#   * this server:  vllm serve  ->  port 8001  (the model)
#   * the gateway:  python -m agent.api_vllm  ->  API_PORT, default 8000  (the /v1 API)
# The gateway reaches this server via VLLM_BASE_URL (default http://127.0.0.1:8001/v1).
#
# Usage:
#   ./run_vllm_server.sh
# Override via env, e.g. a small-GPU w4a16 checkpoint on a different port:
#   VLLM_MODEL_ID=google/gemma-4-E4B-it-qat-w4a16-ct PORT=8001 ./run_vllm_server.sh
set -euo pipefail

cd "$(dirname "$0")"

# Prefer this backend's OWN venv (.venv-vllm, per requirements-vllm.txt) without needing
# it pre-activated, so `vllm`/`python` below resolve there rather than a system install.
if [[ -x ".venv-vllm/bin/vllm" ]]; then
  export PATH="$PWD/.venv-vllm/bin:$PATH"
fi

# Load agent-service/.env if present (e.g. HF_TOKEN for un-throttled downloads,
# VLLM_MODEL_ID). Keep .env untracked — it may hold credentials.
if [[ -f ".env" ]]; then
  set -a; source ./.env; set +a
fi

# FlashInfer (vLLM's default sampler/attention kernels) JIT-compiles CUDA at runtime;
# point CUDA_HOME at the system toolkit so that compile can find nvcc + headers.
if [[ -z "${CUDA_HOME:-}" ]] && command -v nvcc >/dev/null 2>&1; then
  export CUDA_HOME="$(dirname "$(dirname "$(command -v nvcc)")")"
  echo "[run_vllm_server] CUDA_HOME=$CUDA_HOME (nvcc: $(command -v nvcc))" >&2
fi

# We decode with light sampling; if FlashInfer's JIT sampler fails to build against an
# older system nvcc, fall back to vLLM's native sampler (no runtime compile needed).
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"

# Reduce CUDA fragmentation OOMs — vLLM suggests this when the card is near full.
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

# Model to serve. MUST match the gateway's VLLM_MODEL_ID (agent/config.py) — the gateway
# asks vLLM for this exact name. Defaults to the transformers backend's model; for a 16GB
# GPU point it at a w4a16 QAT checkpoint (e.g. google/gemma-4-E4B-it-qat-w4a16-ct).
MODEL_ID="${VLLM_MODEL_ID:-google/gemma-4-12B-it}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
# Fraction of VRAM for weights + KV cache. Keep headroom on a 16GB card: CUDA-graph pools
# and the sampler warmup buffer allocate ON TOP of this, so 0.90 can OOM at startup. 0.80
# leaves ~1.5GB slack; raise it only if you have VRAM to spare.
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.80}"
# Optional VRAM knobs (unset = vLLM defaults):
#   MAX_NUM_SEQS  — cap the batch; shrinks the per-step sampler/activation buffer (e.g. 16).
#   ENFORCE_EAGER — set to 1 to skip torch.compile + CUDA-graph capture: frees ~0.8GB and
#                   boots much faster (small inference-speed cost). Good for a demo / debug.
MAX_NUM_SEQS="${MAX_NUM_SEQS:-}"
ENFORCE_EAGER="${ENFORCE_EAGER:-}"

# Keep the model cache project-local (mirrors the transformers backend's HF_HOME handling).
export HF_HOME="${HF_HOME:-$PWD/.hf_cache}"

ARGS=(
  "$MODEL_ID"
  --host "$HOST"
  --port "$PORT"
  --served-model-name "$MODEL_ID"    # serve under exactly this name (gateway matches it)
  --max-model-len "$MAX_MODEL_LEN"
  --gpu-memory-utilization "$GPU_MEM_UTIL"
  # text-only concierge: skip the vision/audio towers to save VRAM (Gemma 4 is multimodal).
  --limit-mm-per-prompt '{"image": 0, "audio": 0}'
)
[[ -n "$MAX_NUM_SEQS" ]] && ARGS+=(--max-num-seqs "$MAX_NUM_SEQS")
[[ "$ENFORCE_EAGER" == "1" ]] && ARGS+=(--enforce-eager)

echo "[run_vllm_server] serving $MODEL_ID on $HOST:$PORT (HF_HOME=$HF_HOME, gpu-mem-util=$GPU_MEM_UTIL)" >&2
echo "[run_vllm_server] the gateway expects VLLM_BASE_URL=http://127.0.0.1:$PORT/v1" >&2
exec vllm serve "${ARGS[@]}"
