# agent-service — vLLM Backend Install (concurrent serving)

This installs the **optional vLLM backend** for the concierge web API. It serves the exact
same `/v1/*` contract as the default transformers backend (`agent.api`, see
[`INSTALL.md`](INSTALL.md)), so it is a **drop-in on the same port** — the web-app does not
change. The difference is throughput: vLLM continuously batches concurrent requests into
one decode loop, so **multiple users generate in parallel** instead of queueing on a lock.

**When to use this instead of `INSTALL.md`:**
- You expect **several simultaneous users** (e.g. PC + mobile at once) and want their
  replies generated concurrently rather than serialized.
- You want vLLM's faster single-GPU serving.

Stick with `INSTALL.md` (transformers) if you just need the interactive CLI (`agent.cli`)
or a single-user demo — that path is simpler (one process, one venv).

Target box: Ubuntu 24.04, NVIDIA GPU. A **16GB** GPU is fine with a w4a16 checkpoint
(step 4); the 12B model in full precision needs ~24GB+.

> **Isolation:** this backend has its **own venv** (`.venv-vllm`) and **own requirements**
> (`requirements-vllm.txt`), separate from the transformers `.venv`. `vllm` hard-pins its
> own torch build, which conflicts with the transformers stack — **do not** install both
> requirement files into one venv. See `requirements-vllm.txt` for the rationale.

Follow the steps in order. After each **✅ Check**, confirm the expected output before
continuing. Report back at any step that fails.

---

## Architecture — two processes

Unlike the transformers backend (one process that loads the model in-VRAM), vLLM runs as
**two** processes:

```
web-app (:8090) ──▶ gateway  agent.api_vllm  (:8000)   ← this is the /v1/* API (drop-in)
                         │ OpenAI API over HTTP
                         ▼
                    vllm serve  (:8001)                 ← the model + continuous batching
```

- **Process B — `./run_vllm_server.sh`** loads the model and serves it on **:8001** (the
  only place the model lives).
- **Process A — `python -m agent.api_vllm`** is a thin async gateway on **:8000** (`API_PORT`)
  that adds the grounding and calls process B. No GPU lock here — concurrency comes from vLLM.

You run **one** `/v1` API on `:8000` — either `agent.api` (transformers) **or**
`agent.api_vllm` (vLLM), never both at once.

---

## 0. Verify the GPU driver

```bash
nvidia-smi
```

**✅ Check:** you see your GPU, its memory, and a "CUDA Version: XX.X" (top-right). vLLM
needs a reasonably recent driver/CUDA — if `nvidia-smi` reports an old CUDA version, update
the driver (`sudo ubuntu-drivers autoinstall`, reboot) before continuing.

---

## 1. Build the knowledge base (prerequisite)

Same as the transformers backend: the gateway grounds each reply on the compiled artifacts
in the **repo root** `DATA/`. If you already did this for `INSTALL.md`, skip ahead.

```bash
cd ..                     # repo root: oneneobank-concierge-demo/
make all                  # -> DATA/products.yaml, campaigns.yaml, transactions.yaml (+ personas)
make kb                   # -> DATA/kb-cmp-*.yaml  (the per-campaign customer Q&A knowledge)
cd agent-service
```

**✅ Check:** these exist and are non-empty:

```bash
ls -l ../DATA/kb-cmp-dep-2026q3-01.yaml ../DATA/campaigns.yaml ../DATA/products.yaml ../DATA/transactions.yaml
```

---

## 2. Create the vLLM venv (separate from the transformers `.venv`)

```bash
cd agent-service
python3.12 -m venv .venv-vllm
source .venv-vllm/bin/activate
python -m pip install --upgrade pip
```

**✅ Check:** your prompt is prefixed with `(.venv-vllm)`. This directory is git-ignored.
Re-activate later with `source .venv-vllm/bin/activate` in each new shell.

---

## 3. Install vLLM + the gateway deps

`vllm` pulls its **own matching torch build** — do not install torch yourself, and do not
pin it:

```bash
pip install -r requirements-vllm.txt      # vllm, openai, fastapi, uvicorn[standard], python-dotenv, PyYAML
```

This is the largest download in the process (vLLM + CUDA wheels). It can take a while.

**✅ Check — vLLM imports and torch sees the GPU:**

```bash
python -c "import vllm, torch; print('vllm', vllm.__version__, '| torch', torch.__version__, '| cuda', torch.cuda.is_available())"
```

Expected: a vLLM version, a torch version, and `cuda True`. If `cuda False`, the torch build
vLLM pulled does not match your driver — see **Troubleshooting**.

---

## 4. Choose the model + configure `.env`

The gateway and the model server both read `agent-service/.env`. Create it from the example
if you don't have one, then set the vLLM model:

```bash
cp .env.example .env    # if .env doesn't exist yet
```

Add/edit these in `.env`:

```ini
# --- vLLM backend ---
# The checkpoint vllm serves. MUST be the same string for the server and the gateway;
# keeping it in .env guarantees that. For a 16GB GPU use a w4a16 QAT checkpoint:
VLLM_MODEL_ID=google/gemma-4-E4B-it-qat-w4a16-ct
# Where the gateway reaches the model server (default already points here):
VLLM_BASE_URL=http://127.0.0.1:8001/v1
# Shared HF cache so weights aren't re-downloaded (reuse the same one as the transformers .venv):
HF_HOME=/abs/path/to/your/.hf_cache
```

Notes:
- `VLLM_MODEL_ID` defaults to `google/gemma-4-12B-it` (full precision, needs ~24GB+). On a
  **16GB** GPU, set a **w4a16 QAT** checkpoint as above. Confirm the exact checkpoint name
  exists on Hugging Face / your cache before starting.
- `VLLM_API_KEY` defaults to `EMPTY` (vLLM doesn't require a key unless you start it with
  `--api-key`); leave it unless you secured the model server.
- `GOTOAI_AGENT_API_KEY` — the **web API** bearer key — works exactly as in the transformers
  backend (shared code). Set it here to require `Authorization: Bearer <key>` on `/v1/*`.

**✅ Check:** the settings resolve:

```bash
python -c "from agent import config; print(config.VLLM_MODEL_ID, config.VLLM_BASE_URL)"
```

---

## 5. Grounding check (no GPU / no model download)

The gateway's data + prompt layers are torch-free, so confirm they load before spending time
on the model — this runs instantly in `.venv-vllm`:

```bash
python -c "
from agent import data, concierge
print('customers :', ', '.join(data.customer_names()))
print('answerable:', data.campaigns_with_kb())
c  = data.find_customer('Aoi')
ck = data.load_campaign('CMP-DEP-2026Q3-01')
print('prompt len:', len(concierge.build_system_prompt(c, ck)), 'chars')
"
```

**✅ Check:** you see the 17 customers, a non-empty `answerable` list including
`CMP-DEP-2026Q3-01` (only campaigns with a compiled `kb-<id>.yaml` are answerable), and a
prompt of several thousand chars. A "Missing data artifact" error → go back to **step 1**.

---

## 6. Start the model server (terminal 1)

`run_vllm_server.sh` starts `vllm serve` on **:8001**, using `.venv-vllm` and reading `.env`
(so it picks up `VLLM_MODEL_ID` and `HF_HOME`). The **first** run downloads the weights.

```bash
./run_vllm_server.sh
# override without editing .env, e.g. a different port or context length:
#   PORT=8001 MAX_MODEL_LEN=8192 GPU_MEM_UTIL=0.90 ./run_vllm_server.sh
```

Leave it running. For vLLM's first-boot, it loads the quantized weights and then does torch.compile + CUDA-graph capture. It's ready when it logs a line like
`Uvicorn running on http://0.0.0.0:8001`.

**✅ Check (in another terminal):** the model server answers and lists your model:

```bash
curl -sS http://127.0.0.1:8001/v1/models
```

Expected: JSON with `"id": "<your VLLM_MODEL_ID>"`. Watch VRAM with `watch -n1 nvidia-smi`.

---

## 7. Start the gateway (terminal 2)

In a **second** terminal, activate the same venv and start the `/v1` API on **:8000**:

```bash
cd agent-service
source .venv-vllm/bin/activate
python -m agent.api_vllm
```

On startup it prints whether the vLLM backend is reachable.

**✅ Check — probes:**

```bash
curl -sS http://127.0.0.1:8000/healthz     # {"status":"ok"}
curl -sS http://127.0.0.1:8000/readyz      # {"status":"ready","model_id":"..."}  (503 until the model server is up)
```

**✅ Check — a grounded reply** (add `-H "Authorization: Bearer $GOTOAI_AGENT_API_KEY"` if you set a key):

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"customer":"Aoi","campaign":"CMP-DEP-2026Q3-01","message":"今日申し込むと最大でいくらもらえますか？"}'
```

Expected: JSON with a polite Japanese `message`, the resolved `customer`/`campaign_id`, and
`model_id` = your `VLLM_MODEL_ID`. Add `"language":"en"` to the body to get English.

---

## 8. Point the web-app at it (nothing to change)

The gateway is a **drop-in** on `:8000` with the identical `/v1/*` contract, so the web-app
needs no changes — its `AGENT_API_URL` (default `http://127.0.0.1:8000`) already targets it.
Just make sure that if you set `GOTOAI_AGENT_API_KEY` on the gateway, the **same** value is
in `web-app/.env` (see the web-app README). Then use the concierge as usual — now two users
chatting at once are served in parallel.

**✅ Concurrency check (optional):** fire two streaming requests at once and watch them both
make progress immediately (rather than the second waiting for the first):

```bash
for i in 1 2; do
  curl -sN -X POST http://127.0.0.1:8000/v1/chat/stream \
    -H "Content-Type: application/json" \
    -d '{"customer":"Aoi","campaign":"CMP-DEP-2026Q3-01","message":"特典を教えて"}' &
done; wait
```

---

## Troubleshooting

- **`torch.cuda.is_available()` is `False`** after step 3 → the torch build vLLM pulled
  doesn't match your driver. Check `nvidia-smi`'s CUDA version and install a vLLM build that
  targets a CUDA at or below it (see vLLM's install matrix); do **not** hand-install a
  conflicting torch into this venv.
- **`/readyz` stays 503 / gateway logs "reachable: False"** → the model server (terminal 1)
  isn't up yet (weights still downloading) or is on a different port. Confirm
  `curl http://127.0.0.1:8001/v1/models` works and that `VLLM_BASE_URL` matches its port.
- **`generation failed` (503) from `/v1/chat`** → the model server crashed or the model name
  differs. Ensure `VLLM_MODEL_ID` in `.env` matches exactly what `run_vllm_server.sh` served
  (check terminal 1's startup log / `/v1/models`).
- **`CUDA out of memory` when the model server starts** → the checkpoint is too big for your
  VRAM. Use a **w4a16 QAT** checkpoint (step 4), lower `GPU_MEM_UTIL` (e.g. `0.85`) or
  `MAX_MODEL_LEN`, and close other GPU apps (`nvidia-smi`).
- **FlashInfer / nvcc JIT build errors on startup** → the run script already sets
  `VLLM_USE_FLASHINFER_SAMPLER=0` and points `CUDA_HOME` at the system toolkit if `nvcc` is
  present. If a kernel still fails to build, installing the matching CUDA toolkit (`nvcc`) or
  updating vLLM usually resolves it.
- **Model won't download / repeated downloads** → set `HF_HOME` in `.env` to a writable
  shared cache (and `HF_TOKEN` there for gated/faster downloads); the run script reads `.env`.
- **Port already in use on :8000** → a transformers `agent.api` (or another gateway) is
  already bound there. Run only one `/v1` API per port, or set `API_PORT` in `.env`.
- **401 on `/v1/*`** → `GOTOAI_AGENT_API_KEY` is set; send `Authorization: Bearer <key>` (and
  match it in `web-app/.env`).
```
