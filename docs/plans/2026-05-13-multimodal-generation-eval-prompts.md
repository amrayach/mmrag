# Multimodal Generation — Eval Prompt Design

**Date:** 2026-05-13
**Status:** Draft — sibling to `2026-05-13-multimodal-generation-design.md`
**Goal:** Pre-design the discriminating prompt set for Phase 3 of the Track 0 multimodal generation hybrid. Four discriminating prompts + one retrieval-bounded control (BMW p04 anchor) + one regression-sanity check. Each carries a predicted swing direction and a scoring rubric.

Phase 3 of the parent spec is the long pole. The implementation in Phase 2 is small; the eval is where the credibility of the A/B comes from. Front-loading the prompt design now means Phase 3 starts from a defensible position instead of "let's come up with some prompts."

---

## Framework: what captions cannot preserve

The discrimination case rests on what a 1-2 sentence German caption *cannot carry* but a vision encoder *can read directly*:

| Information class | Caption preserves? | Pixels preserve? | Discriminator? |
|---|---|---|---|
| Topic, dominant element ("ein Balkendiagramm") | Reliably | Yes | No — both work |
| Specific numeric values on bars/axes | Almost never | Yes (within visual budget) | **Yes — strong** |
| Legend entries verbatim | Paraphrased at best | Yes | **Yes — strong** |
| Counts of distinct elements | Approximate ("mehrere") | Exact | **Yes — strong** |
| Embedded text (titles, source attribution) | Almost never | Yes | **Yes — moderate** |
| Spatial / color-coded relationships | Rarely | Yes | Marginal — captioners sometimes mention colors |

Discriminating prompts target rows 2-5. The control prompt (P0) targets the BMW p04 *retrieval* failure (caption ≈ pixels because retrieval doesn't surface the relevant chunk — neither mode can answer). The regression-sanity prompt (P5) targets row 1 (both should win; multimodal must not regress).

---

## P0 — BMW p04 list-completeness (control / retrieval-bound anchor)

**Query (DE):** *"Welche Geschäftsbereiche und Aufgaben der BMW Group werden auf Seite 4 des Nachhaltigkeitsberichts genannt?"*

**Target asset class:** No image required. This is a *text retrieval* failure case from the Phase 0 retrieval diagnostics (see `project_phase0_diagnostics.md`). The prompt anchors the A/B against the known BMW p04 classification.

**Predicted swing:** **≈ (caption ≈ multimodal).** Retrieval is the bottleneck. If the relevant chunk is in `hits[]`, both modes recover the same list. If it isn't, both fail identically. Multimodal generation cannot rescue a chunk that vector search did not surface.

**Scoring rubric:**

- Let N = number of distinct list entries on BMW p04 (operator-defined against the actual chunk; canonical list lives in the existing diagnostic artifact).
- For each expected entry recovered in the answer: 1.0 verbatim, 0.7 paraphrase preserving meaning, 0 missing.
- For each fabricated entry not in the source: −0.5 (penalty against hallucination).
- Final score: max(0, sum) / N.

**Value of including this prompt:** If multimodal *unexpectedly* improves P0, that's a signal worth investigating — either (a) retrieval was actually surfacing the chunk all along and the LLM was failing on the read, which would re-open the BMW p04 classification, or (b) the chunk is being retrieved as an image (the table on p04 may be rasterized in the source PDF) and pixel-level reading finally recovers it. Either result reshapes Track 0's framing.

---

## P1 — Numeric values on a chart (high-value win)

**Query (DE):** *"Welche genauen Zahlenwerte zeigt die Grafik zu den CO₂-Emissionen pro Geschäftsbereich? Nenne die Werte für jedes Segment."*

**Target asset class:** PDF chart with numeric labels on bars or segments (BMWGroup or Nachhaltigkeit corpus). Operator selects one concrete asset before Phase 3.

**Predicted swing:** **Multimodal wins clearly.** Captioner output for charts is reliably topic-level ("eine Übersicht der CO₂-Emissionen pro Geschäftsbereich") but does not carry specific numbers. Gemma 4 reading chart pixels reads the numeric labels directly via its OCR-capable vision encoder.

**Scoring rubric:**

- Let K = number of distinct numeric values labeled on the chart (operator-defined; typically 4-8 for a comparison chart).
- For each expected value present in the answer:
  - Exact match: 1.0
  - Within ±5%: 0.5
  - Wrong number, wrong scale, or missing: 0
- Final score: sum / K.

**Risk to flag:** This case partly probes the visual-budget choice. If the chart has small or dense numeric labels and Phase 2 picked too low a visual budget (e.g., 70 or 140 tokens/image), even multimodal will underperform. The default Phase 2 placement uses Gemma's 280-token "OCR / document parsing" zone — if P1 fails, the first lever to pull is bumping to 560.

---

## P2 — Legend entries verbatim (cleanest win)

**Query (DE):** *"Wie ist die Legende des Diagramms beschriftet? Liste alle Legenden-Einträge wörtlich auf."*

**Target asset class:** PDF diagram with a multi-entry legend (Siemens or TechVision likely best).

**Predicted swing:** **Multimodal wins clearly.** Legends are dense, short multi-line text that captioners summarize as "ein Diagramm mit Legende" or paraphrase entries into prose. Gemma 4 reads legend text directly.

**Scoring rubric:**

- Let M = number of legend entries (operator-defined; typically 3-6).
- For each expected entry recovered:
  - Verbatim or trivial typo: 1.0
  - Clear paraphrase preserving the entry's identifier: 0.5
  - Missing or fabricated: 0
- Final score: sum / M.

**Why this is the cleanest win:** legend entries are short, finite, unambiguous. There's no rubric ambiguity. Either the model produces them or it doesn't. This prompt is the most defensible "yes pixels help" data point.

---

## P3 — Count plus names of distinct elements (highest-discriminator)

**Query (DE):** *"Wie viele verschiedene Geschäftsbereiche werden in der Grafik verglichen? Wie heißen die einzelnen Bereiche?"*

**Target asset class:** PDF comparison chart with multiple labeled segments (Nachhaltigkeit or BMW comparison views).

**Predicted swing:** **Multimodal wins clearly.** Captioner output for comparison charts is almost universally "vergleicht mehrere Geschäftsbereiche" — count is missing, names are missing. Gemma 4 counts and reads.

**Scoring rubric:**

- Let N = actual count of distinct segments (operator-defined).
- Count correctness: 1 if exact, 0 otherwise.
- Name correctness: 1 point per correctly recovered name (verbatim or trivial typo), max N.
- Final score: (count_score + name_score) / (1 + N).

**Why this prompt is the highest discriminator:** it probes two distinct vision-encoder capabilities at once — counting (a known weakness of older small VLMs) and OCR of label text. A pass here is the strongest single signal that Track 0 is working end-to-end. A failure isolates the bottleneck (count failure → vision encoder; name failure → OCR fidelity).

---

## P4 — Embedded text: chart title + source attribution (broad applicability)

**Query (DE):** *"Welcher Titel steht über der Grafik und welche Quellenangabe ist darunter aufgeführt?"*

**Target asset class:** Any PDF chart with a title at the top and a source attribution at the bottom. Most corporate charts in the corpus have both (BMW, Nachhaltigkeit, TechVision).

**Predicted swing:** **Multimodal wins moderately to clearly.** Captioners almost never preserve chart titles verbatim — they generate their own description ("die Grafik zeigt …") instead. Source attributions ("Quelle: …") are essentially never preserved. Gemma 4 reads both directly.

**Scoring rubric:**

- Title recovery: 1.0 verbatim, 0.5 paraphrase preserving the topic, 0 wrong/missing.
- Source recovery: 1.0 verbatim, 0.5 partial (e.g., publisher recovered but year missing), 0 wrong/missing.
- Final score: (title_score + source_score) / 2.

**Why this is broadly applicable:** almost every corporate chart in the corpus has both elements. This prompt generalizes well to whatever a reviewer might ask unprompted during the demo.

---

## P5 — Topic identification (regression-sanity)

**Query (DE):** *"Was ist das Hauptthema des Bildes auf Seite N? Beschreibe kurz, was darauf zu sehen ist."*

**Target asset class:** Any PDF image with a clear topic. Pick something different from P1-P4 to avoid cross-contamination.

**Predicted swing:** **Both ≈, multimodal must not regress.** Caption-only handles this question well (topic identification is exactly what 1-2 sentence captions deliver). Multimodal must not get distracted by visual noise and produce a less coherent or less topically-correct answer.

**Scoring rubric:**

- Topic correctness: 1.0 correct topic identified, 0.5 partial (topic family right, specifics wrong), 0 wrong topic.
- Answer coherence: 1.0 well-formed German prose, 0.5 awkward but readable, 0 nonsensical or disfluent.
- Final score: (topic + coherence) / 2.

**Why this prompt is essential:** without a regression-sanity prompt the A/B might just be measuring "harder prompts" and we would never see if pixels distract the model on easy ones. If P5 regresses for multimodal, that is a real problem with at least three possible causes:

1. Visual budget too high — model over-attends to images on text-natural prompts.
2. System prompt isn't framing the role of images correctly — model treats every image as obligatory grounding.
3. Image placement order pushes text context too far from the assistant's attention.

P5 is also the test that gates "we're not just slower for marginal quality gains."

---

## Predicted A/B summary

| Prompt | Caption-only predicted | Multimodal predicted | Hypothesis basis |
|---|---|---|---|
| P0 BMW p04 control | Low | Low | Retrieval-bound; neither mode rescues |
| P1 numeric values | Very low | High | Captions don't carry numbers; pixels do |
| P2 legend entries | Low | High | Captions paraphrase; pixels are verbatim |
| P3 count + names | Low | High | Probes counting + OCR simultaneously |
| P4 title + source | Very low | Medium-high | Embedded text almost always missed by caption |
| P5 topic sanity | High | High (no regression) | Both should pass; multimodal must not break |

**A defensible A/B requires:**

- P1, P2, P3 swing as predicted (caption low → multimodal high). If any of these comes back flat, investigate the visual-budget setting before declaring the experiment a failure.
- P4 swings at least moderately. A flat result here is recoverable (operator picks a different asset with more legible title/source).
- P5 does **not** regress. A regression here is a hard stop for Phase 4.
- P0 stays flat. A surprise multimodal win on P0 is interesting but does not change the headline finding.

---

## Asset selection (operator task, gated to start of Phase 3)

Before Phase 3 begins, the operator selects one concrete asset per discriminating prompt. The asset choice locks in the K/M/N values for the rubrics.

| Prompt | Required asset properties | Suggested source |
|---|---|---|
| P1 | Chart with ≥ 4 numeric labels on bars/segments | BMWGroup or Nachhaltigkeit |
| P2 | Diagram with ≥ 4 legend entries | Siemens or TechVision |
| P3 | Comparison chart with ≥ 4 labeled segments | Nachhaltigkeit or BMW |
| P4 | Chart with title + source attribution | Any corporate PDF |
| P5 | Any image with clear, simple topic | Any (RSS or PDF) |

Asset paths plus the operator-defined values (K, M, N, expected title/source strings) get bundled into the prompt JSON fixtures when Phase 3 begins. The fixtures should live under `data/eval/prompts/` per the parent spec's "Files Changed" table.

---

## What this design does **not** cover

- **Multilingual prompts.** Everything here is German; the demo is German-first. English prompts can come later if a reviewer requests them.
- **Adversarial / jailbreak prompts.** Out of scope. Reviewers in the existing demo cohort come prepared, not hostile.
- **Multi-turn deictic follow-ups.** Covered by the existing 12-prompt baseline. The discriminating prompts here are single-turn by design — multi-turn confounds the multimodal vs caption comparison.
- **Cross-source prompts that mix PDF and RSS.** Existing baseline already covers this. Adding such a prompt to the discriminating set would muddy the signal: RSS image quality varies wildly, and PDF charts are the demo's strength.
- **Visual budget A/B (70 / 140 / 280 / 560 / 1120).** The parent spec fixes the default visual budget implicitly via Ollama's defaults. If P1 underperforms, that's the next experiment — but it's outside Phase 3's headline A/B.

---

## Cross-references

- `docs/plans/2026-05-13-multimodal-generation-design.md` — parent spec; Phase 3 of that spec is where these prompts run.
- `data/eval/runs/20260505_190437__baseline_post_odl/` — existing 12-prompt baseline. Phase 3 re-runs against the same DB snapshot to keep numbers comparable.
- `project_phase0_diagnostics.md` (memory) — BMW p04 retrieval-side classification, which P0 anchors against.
- `project_post_odl_baseline_eval.md` (memory) — scorecard rubric pattern reused here; "headline target is p04 list-completeness" framing aligns with P0.
