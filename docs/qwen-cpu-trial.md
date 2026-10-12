# Qwen3-VL CPU extraction trial

This experiment reads existing screenshots from release `assets`; it never launches an emulator or signs into the game. Changes are isolated on `codex/qwen3-vl-ocr-test`.

## Reproducibility

- Model: official Qwen/Qwen3-VL-4B-Instruct-GGUF, Q4_K_M text weights and F16 vision projector.
- Model revision: `1cd86afb9a95c410a6038ab3b40d8b578c892266`.
- llama.cpp commit: `08ffba21e5c2f1728b6b405c05ff3913f65706d4`.
- Source: release asset `aov-1791785227605.zip`; SHA-256 is checked before extraction.
- CPU-only Ubuntu 24.04 runner, up to four inference threads, one server slot, 8192 context, at most 1536 image tokens.
- Three samples: overview, attributes, skill-1-detail. Prefer Airi if present, otherwise the first matching file in sorted archive order. Selected paths and crop boxes are recorded.
- Fixed crops assume the collector landscape layout. Review each crop before judging model accuracy.
- Each request is bounded to 15 minutes and 1800 output tokens. Entire job is limited to 65 minutes.

## Results

Download the workflow artifact, open `index.html`, and compare each image with the model text. `results.json` includes source names, crop coordinates, raw output, parsed JSON when possible, timing, and observed server peak resident memory. `server.log` preserves diagnostics. Results are written after each image, including failures.

JSON validity is only a format check, not an accuracy score. Values remain strings to avoid silently converting damaged decimal numbers. All extracted content is unreviewed. Do not auto-import it into production game data.

Manually check hero names and Vietnamese accents; every attribute value and label; decimals and percentages; the order of per-level damage and cooldown values; omitted clauses and hallucinated content. Benchmark results apply to these samples and this hardware only.

Pushes touching the trial script or workflow on this branch start the experiment. Main and existing emulator workflows are not modified. No API key or paid GPU is required. Artifacts expire after 14 days. Re-running currently repeats the three samples; cross-run checkpoint resume is not implemented in this bounded trial.
