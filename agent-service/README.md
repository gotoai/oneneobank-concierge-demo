# OneNeo Bank concierge — agent-service

The concierge agent: it plays the OneNeo Bank AI concierge and answers a named
customer's questions about one campaign, grounded in the compiled knowledge under the
repo's `DATA/`. It ships an interactive CLI and a web API, with **two interchangeable
backends** for the web API:

| | **transformers** | **vLLM** |
|---|---|---|
| Model runs | in-process (this process) | in a separate `vllm serve` process |
| Concurrency | one generation at a time (GPU lock) | parallel (vLLM continuous batching) |
| Processes | 1 | 2 (model server + gateway) |
| venv | `.venv` | `.venv-vllm` |
| Requirements | `requirements.txt` | `requirements-vllm.txt` |
| Install guide | [INSTALL.md](INSTALL.md) | [INSTALL-VLLM.md](INSTALL-VLLM.md) |

Both expose the **identical `/v1/*` API** on `API_PORT` (default `:8000`), so the web-app
talks to whichever one is running without any change. **Run only one on `:8000` at a time.**

`make help` lists every target.

---

## Prerequisite (both backends)

Build the knowledge base once from the **repo root** (uses the pipeline's env, not this
service's venv), then configure `.env`:

```bash
cd ..            # repo root
make all && make kb        # -> DATA/*.yaml (+ DATA/kb-cmp-*.yaml)
cd agent-service
cp .env.example .env       # then edit: MODEL_ID / HF_HOME / (vLLM) VLLM_MODEL_ID / GOTOAI_AGENT_API_KEY
```

Install is per-backend — see the two guides above, or use the Make targets below.

---

## Run — transformers version (in-process model)

```bash
make install         # create .venv + install requirements.txt (install the CUDA torch wheel first — INSTALL.md)
make serve-api       # -> agent.api on http://127.0.0.1:8000
# raw equivalent:  .venv/bin/python -m agent.api
```

One process. The model loads into VRAM on startup; requests queue (one generation at a
time). Use this for the CLI or a single-user demo.

### Interactive CLI (transformers only)

```bash
.venv/bin/python -m agent.cli Aoi CMP-DEP-2026Q3-01
# or: .venv/bin/python -m agent.cli            # prompts for customer + campaign
```

Ask in Japanese; commands: `/profile`, `/reset`, `/exit`.

---

## Run — vLLM version (concurrent serving)

Two processes, started in this order (two terminals):

```bash
make install-vllm    # create .venv-vllm + install requirements-vllm.txt

# terminal 1 — the model server on :8001 (first run downloads weights, then compiles)
make serve-vllm
# raw equivalent:  ./run_vllm_server.sh
#   VRAM-tuning knobs, e.g.:  GPU_MEM_UTIL=0.80 MAX_NUM_SEQS=16 ENFORCE_EAGER=1 make serve-vllm

# terminal 2 — the gateway (the /v1 API the web-app calls) on :8000
make serve-vllm-api
# raw equivalent:  .venv-vllm/bin/python -m agent.api_vllm
```

`serve-vllm` alone only starts the model on `:8001`; the **gateway** (`serve-vllm-api`)
is what serves `/v1` on `:8000`. Concurrent users are batched by vLLM and generate in
parallel. See [INSTALL-VLLM.md](INSTALL-VLLM.md) for model choice, VRAM tuning, and
troubleshooting.

---

## Verify (either backend)

```bash
curl -sS http://127.0.0.1:8000/healthz      # {"status":"ok"}
curl -sS http://127.0.0.1:8000/readyz       # {"status":"ready","model_id":"..."}

curl -sS -X POST http://127.0.0.1:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"customer":"Aoi","campaign":"CMP-DEP-2026Q3-01","message":"今日申し込むと最大でいくらもらえますか？"}'
# add "language":"en" for an English reply
# vLLM only — check the model server itself:  curl -sS http://127.0.0.1:8001/v1/models
```

If `GOTOAI_AGENT_API_KEY` is set in `.env`, add `-H "Authorization: Bearer <key>"` to the
`/v1/*` calls (and match it in `web-app/.env`).

---

## Layout

```
agent-service/
  agent/
    config.py        # env/config (both backends) — MODEL_ID, VLLM_*, API_PORT, keys
    data.py          # loads the DATA/ knowledge (customers, campaigns, KB)   [shared]
    concierge.py     # builds the grounded system prompt + messages           [shared]
    schemas.py       # the /v1/* request/response models, auth, grounding     [shared]
    llm.py           # transformers Gemma client (in-process)
    api.py           # transformers web API           -> make serve-api
    vllm_adapter.py  # async client to the vLLM server (OpenAI API)
    api_vllm.py      # vLLM gateway (same /v1 contract) -> make serve-vllm-api
    cli.py           # interactive REPL (transformers)
  run_vllm_server.sh          # launches `vllm serve` -> make serve-vllm
  requirements.txt  requirements-vllm.txt
  .env.example  Makefile  INSTALL.md  INSTALL-VLLM.md
```

The grounding (`data.py`, `concierge.py`, `schemas.py`) is shared by both backends, so
the two APIs stay byte-for-byte compatible — only the LLM layer differs.
