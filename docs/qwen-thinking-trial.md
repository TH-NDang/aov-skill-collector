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

Valid JSON is not schema validation or an accuracy guarantee. Raw outputs are preserved in the workflow artifacts. 8B findings follow.

## 8B-Thinking result

All three requests completed with parseable JSON. Request times: overview 229.88 s; attributes 317.32 s; skill 376.88 s. Observed server peak RSS: 12538.9 MiB (~12.25 GiB). Total request time: 15.40 minutes; full job about 33 minutes. Model/projector download took approximately 14 minutes, accounting for a large part of the wait.

- Overview: Airi and Ninja rồng transcribed correctly; title again selected the epithet.
- Attributes: all 16 label/value pairs matched the crop, an improvement over 4B-Thinking.
- Skill: title became Phi tiê; tướng became tường in multiple clauses; Long ấn became Long ẩn; hất tung became hắt tung. The full cooldown-reset sentence was retained.
- Per-level table: all 12 speed/cooldown values matched, but the entire base-damage row (280, 336, 392, 448, 504, 560) was omitted. The ST gốc label was incorrectly attached to the level-header row.
- Structured effects remained incomplete and included an incorrect target for stack accumulation. Empty uncertain_parts did not reflect these errors.

Image SHA-256 comparisons confirmed byte-identical crops across all three models. 8B's lower request time than 4B in this single experiment does not establish a speed ranking: runners and output lengths differed.

## Conclusion

CPU execution is viable, but neither Thinking configuration consistently improved extraction quality on these samples. Keep raw outputs for review; do not promote either into an unattended full-dataset import. Prompt v2 changed task complexity as well as wording, so comparisons with the old Instruct run do not isolate model reasoning or prompt effects. A possible next experiment is separate transcription and structured extraction, with independent table-completeness checks and tighter crops. That experiment has not been run.
