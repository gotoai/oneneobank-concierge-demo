# agent-service — Local Install (CUDA + PyTorch)

The OneNeo Bank concierge CLI (`agent.cli`): an interactive agent that plays the bank's
AI concierge and answers a named customer's questions about one campaign, grounded in the
compiled knowledge under the repo's `DATA/`.

Target box: Ubuntu 24.04, NVIDIA GPU with ~16GB VRAM (Gemma 4 12B runs 4-bit, ~9-11GB).
This service has its **own venv and dependencies**, separate from the data pipeline.

Follow the steps in order. After each **✅ Check**, confirm the expected output before
continuing. Report back at any step that fails.

`requirements.txt` covers the pip-resolvable libraries; the steps below add the parts a
requirements file can't portably capture — the GPU driver and the **CUDA-matched
PyTorch wheel** (which depend on your box).

---

## 0. Verify the GPU driver

```bash
nvidia-smi
```

**✅ Check:** you see your GPU, its memory, and a "CUDA Version: XX.X" (top-right) — the
*driver-supported* CUDA. You do **not** need to install the CUDA toolkit (`nvcc`)
separately; PyTorch ships its own CUDA runtime. If `nvidia-smi` is missing, install the
driver first (`sudo ubuntu-drivers autoinstall`, reboot) and re-run.

---

## 1. Build the knowledge base (prerequisite)

The CLI reads compiled artifacts from the **repo root** `DATA/` — it does not generate
them. Build them once from the repo root, using the **pipeline's** environment (the
repo-root `.venv`, *not* this service's venv):

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

The concierge can only answer for a campaign that has a `kb-<id>.yaml`; today that is
`CMP-DEP-2026Q3-01`. Add more `docs/Q&A/CMP-*_QA_examples.md` and re-run `make kb` to
cover other campaigns.

---

## 2. Create the venv (in this directory)

```bash
cd agent-service
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

**✅ Check:** your prompt is prefixed with `(.venv)`. Re-activate later with
`source .venv/bin/activate` in each new shell.

---

## 3. Install PyTorch (CUDA build), then the rest

Install torch **first and separately** — the right wheel depends on your driver's CUDA,
so it is deliberately kept out of `requirements.txt`:

```bash
pip install torch torchvision            # default wheel bundles a recent CUDA runtime
pip install -r requirements.txt          # transformers>=5.10.1, accelerate, bitsandbytes, pillow, timm, python-dotenv, PyYAML
```

**✅ Check — PyTorch sees the GPU:**

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Expected: a version, `True`, and your GPU name (e.g. `2.x.x+cu124 True NVIDIA GeForce RTX ...`).
If it prints `False`, the driver/wheel CUDA versions don't match — reinstall torch from the
matching index, e.g.:

```bash
pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu121
# or .../whl/cu126 — pick the one at or below your nvidia-smi CUDA version
```

---

## 4. Configure `.env` (model + local cache)

```bash
cp .env.example .env
```

Then edit `.env`:
- `MODEL_ID=google/gemma-4-12B-it`
- `HF_HOME` — point at a **shared** Hugging Face cache so the model weights (~24GB) aren't
  re-downloaded per venv (e.g. reuse an existing shared `.hf_cache`, or a home-level cache).
  The app loads `.env` **before** importing transformers, so `HF_HOME` takes effect for the
  download.
- `MAX_NEW_TOKENS` / `GEN_TEMPERATURE` / `GEN_TOP_P` — generation defaults for the chat
  (1024 / 0.7 / 0.95 are fine to start).

**✅ Check:** `python -c "from agent.config import MODEL_ID, HF_HOME; print(MODEL_ID, HF_HOME)"`
prints your model id and cache path.

---

## 5. Grounding check (no GPU / no model download)

Confirm the data layer loads and a grounded prompt assembles — this exercises everything
*except* the model, so it runs instantly even before the weights download:

```bash
python -c "
from agent import data, concierge
print('customers :', ', '.join(data.customer_names()))
print('answerable:', data.campaigns_with_kb())
c  = data.find_customer('Aoi')
ck = data.load_campaign('CMP-DEP-2026Q3-01')
sp = concierge.build_system_prompt(c, ck)
print('customer  :', c.name, c.persona_id, '/ tx:', len(c.transactions))
print('campaign  :', ck.campaign_id, ck.campaign_name, '/ qa:', len(ck.kb['qa']))
print('prompt len:', len(sp), 'chars')
"
```

**✅ Check:** you see the 17 customers, `['CMP-DEP-2026Q3-01']` as answerable, Aoi resolved
to `S01`, 30 Q&A, and a prompt of several thousand chars. If instead you get a
"Missing data artifact" error, go back to **step 1**.

---

## 6. Run the concierge (first run downloads the model)

Interactive REPL — customer name and campaign id can be positional args, `--customer` /
`--campaign` flags, or omitted (you'll be asked to pick at startup):

```bash
python -m agent.cli Aoi CMP-DEP-2026Q3-01
# or: python -m agent.cli --customer Aoi --campaign CMP-DEP-2026Q3-01
# or: python -m agent.cli            # prompts for both
```

Then ask questions in Japanese (the concierge answers as OneNeo Bank to that customer,
grounded in the campaign's vetted Q&A). Commands: `/profile` (show the grounding),
`/reset`, `/exit`.

**✅ Non-interactive smoke** — pipe one question and let EOF end the session:

```bash
echo '今日申し込むと最大でいくらもらえますか？' | python -m agent.cli Aoi CMP-DEP-2026Q3-01
```

**✅ Check:** after the one-time model download you see a `Concierge>` reply in polite
Japanese. Watch VRAM live in another terminal with `watch -n1 nvidia-smi` (expect ~9–11GB).

---

## Troubleshooting

- `KeyError: 'gemma4'` / unknown model type → transformers too old; `pip install -U "transformers>=5.10.1"`.
- `torch.cuda.is_available()` is `False` → driver/wheel CUDA mismatch (see step 3's `--index-url`).
- `Missing data artifact: .../DATA/kb-....yaml` → the knowledge base isn't built; run
  `make kb` (and `make all`) from the repo root (**step 1**).
- `Unknown customer` / `Unknown campaign` → the CLI lists valid names/ids; note only
  campaigns with a `kb-<id>.yaml` are answerable (`data.campaigns_with_kb()`).
- `CUDA out of memory` during generation (model loaded, OOM at the forward pass) → lower
  `MAX_NEW_TOKENS` in `.env`, or trim the context (the grounding prompt bundles the full
  Q&A KB; reduce `_MAX_TX` in `agent/concierge.py` to include fewer transactions).
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` is set automatically to reduce
  fragmentation; the 4-bit `BitsAndBytesConfig` is active in `agent/llm.py`. Close other
  GPU apps (`nvidia-smi`), or fall back to a smaller Gemma variant (e.g.
  `google/gemma-4-E4B-it`) on lower-VRAM boxes.
- Slow / repeated downloads → make sure `HF_HOME` in `.env` points at your shared cache.
