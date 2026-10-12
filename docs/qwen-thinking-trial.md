# Qwen3-VL Thinking trial

Run: https://github.com/TH-NDang/aov-skill-collector/actions/runs/38216073980

4B-Thinking and 8B-Thinking use the same Vietnamese prompt in `prompts/aov-extract-v2.txt`, same three Airi crop regions, Q4_K_M weights, F16 projector, CPU-only inference and pinned llama.cpp. Reasoning budget: 1536 tokens; total generation cap: 6000; context: 12288. Sampling: temperature 0.6, top_p 0.95, top_k 20, seed 42. Per-request timeout is 20 minutes. Each model runs on a separate standard Ubuntu runner, sequentially. No emulator or game login is used.

The prompt asks for faithful transcription first, preservation of diacritics and all numbers, then structured effects with source evidence. It contains no hero-specific answers. The previous 4B-Instruct baseline used a shorter prompt and deterministic sampling; comparisons with it are observational, not a controlled isolation of reasoning or prompt changes.

## 4B-Thinking result

All three requests returned valid JSON. Request times: overview 205.13 s; attributes 406.38 s; skill 434.79 s. Observed model-server peak RSS: 8163.2 MiB (~7.97 GiB). The full job took about 26 minutes; downloading the language model alone took nearly five minutes.

Visual comparison with the original crops:

- Overview: Airi and Ninja rồng are correct in text_lines, but title selects the epithet instead of the hero name.
- Attributes: omitted Giáp phép 80 | 0%; changed Máu to Màu, Tầm đánh to Tâm đánh, and 0% magic lifesteal to 0 | 0%; duplicated cooldown reduction. This is worse than the earlier Instruct output on this crop.
- Skill: Phi tiêu is correct; the cooldown-reset sentence is retained but diacritics remain wrong. Long ấn becomes Long ẩn; hất tung becomes hát tung; chiêu becomes chiếu. All 18 numerical entries of the three per-level table rows match the image.
- Structured effects are incomplete: damage, knock-up and the +100% non-hero damage effect are not represented in effects. Some unknown fields are empty strings instead of null, and attributes/table_rows do not consistently follow the prompt.

Valid JSON is not schema validation or an accuracy guarantee. Raw outputs are preserved in the workflow artifacts. 8B findings pending.
