# Research Plan — Aug 23, 2026 → Apr 30, 2027

18 two-week sprints; one GitHub milestone each; bi-weekly portfolio submission every sprint.

| Sprint | Dates | Goal |
|---|---|---|
| S01 · Literature Review & Pivot | 2026-08-23 → 2026-09-05 | Literature review, SOTA matrix, Java→Python pivot, Edwards 2019/2021 acquired. |
| S02 · Proposal Writing | 2026-09-06 → 2026-09-19 | Research proposal v2 written against the 8-part defence blueprint. |
| S03 · Proposal Defence & Foundations | 2026-09-20 → 2026-10-03 | Defend the proposal; repo scaffold; datasets validated. |
| S04 · Proposal Submission & Data Replay | 2026-10-04 → 2026-10-17 | Submit revised proposal document; ProgSnap2 replay engine; frozen splits (now five-fold CV, #74). |
| S05 · EDA & Behaviour States | 2026-10-18 → 2026-10-31 | Exploratory analysis of both cohorts; Algorithm 1 behaviour states. |
| S06 · AST Detectors I | 2026-11-01 → 2026-11-14 | AST detectors 1–4 fully tested. |
| S07 · AST Detectors II & Features | 2026-11-15 → 2026-11-28 | AST detectors 5–7; Algorithm 2 ~40-feature extractor. |
| S08 · RQ1 Mining & Synthetic Data | 2026-11-29 → 2026-12-12 | RQ1 counts per misconception; synthetic supplement. |
| S09 · Annotation & Ingest API | 2026-12-13 → 2026-12-26 | Human-verified test labels; second annotator briefed; FastAPI ingest. |
| S10 · Label Reliability & Sandbox | 2026-12-27 → 2027-01-09 | Cohen's kappa; rule-only baseline; GPU secured; Docker sandbox. |
| S11 · ML Baseline, Fusion Data & Editor | 2027-01-10 → 2027-01-23 | XGBoost baseline; fusion JSONL dataset; Monaco capture front end. |
| S12 · Fine-tuning & Interim Presentation | 2027-01-24 → 2027-02-06 | LoRA fine-tuned Qwen2.5-Coder-7B fusion model; interim presentation. |
| S13 · Model Validation & Replay Harness | 2027-02-07 → 2027-02-20 | Ablation adapters, threshold, base-model check; replay harness. |
| S14 · Serving & Live Pipeline | 2027-02-21 → 2027-03-06 | vLLM serving with latency benchmark; live pipeline; raters booked. |
| S15 · Interventions, Dashboard & Hardening | 2027-03-07 → 2027-03-20 | Five-level intervention engine; dashboard; end-to-end testing. |
| S16 · Evaluation Stages A–C | 2027-03-21 → 2027-04-03 | Stage A replay, Stage B ablation, Stage C cross-cohort, grade check. |
| S17 · Expert Study, Results & Paper Draft | 2027-04-04 → 2027-04-17 | Stage D expert rating; results chapter; research paper draft. |
| S18 · Final Submissions & Presentation | 2027-04-18 → 2027-04-30 | Final research paper, final thesis, v1.0 release, final presentation. |

## Campus milestones

| Milestone | Sprint |
|---|---|
| Proposal defence | S03 |
| Proposal document submission | S04 |
| Bi-weekly portfolio submission | every sprint |
| Interim presentation | S12 |
| Final research paper submission | S18 |
| Final thesis submission | S18 |
| Final presentation | S18 |

## Final proposal and panel comments (Nov 2026)

The finalised proposal (signed 26 Nov 2026) replaces proposal v2. Section numbers in issues
written before it refer to v2. The main mapping: v2 §6.2–6.4 is now §3.1.3 (Tables 3.1–3.3),
v2 §6.6 is now §3.2.1, and v2 §7 is now §3.2.3–3.2.4.

### Panel comments (proposal defence, 12 Nov 2026)

| Comment | How the plan addresses it |
|---|---|
| Existing dataset to be checked against AI-generated data | Every synthetic batch is validated against real data before use (#75). The four checks are (a) a KS test and JS divergence per feature, (b) a real-vs-synthetic discriminator, where a batch with AUROC > 0.70 is rejected, (c) blind annotation of 10%, which must reach κ ≥ 0.80, and (d) a with-and-without ablation on real test folds only. Synthetic data is never used in validation or test, and is seeded from training folds only (#9). |
| If real data is collected, statistical biases among the cohort to be addressed | Cohort-bias controls for any new cohort (#77, conditional): a background survey, balanced recruitment, a cohort comparison with covariate-shift tests, separate evaluation first, and per-cohort and per-experience-band reporting, where a gap > 0.10 macro-F1 is reported as a limitation. The ethics application is prepared early (#76). |
| RQs clear | No change. |
| Research type OK | No change: quantitative, comparative experimental design with ablation. |

### Other changes from v2 that affect the work

| Change | Issues |
|---|---|
| Student-grouped **five-fold cross-validation** replaces the fixed 70/10/20 split. Within each training portion, one fold's worth of students is held back for threshold tuning. Results are reported as mean ± sd across folds. | #74 (supersedes #4), #12, #13, #15, #16, #17 |
| Occurrence gate across both cohorts: fewer than 50 **verified** real cases means the misconception is exploratory and excluded from the main claims. | #8 |
| The NONE class is built from flagged slips plus random unflagged windows. A random unflagged sample estimates the detectors' missed cases. | #10 |
| κ is reported before and after resolution, with a shared subset of at least 20%. | #11 |
| Detection phases: earliness is measured for the pre-run misconceptions (aliasing, identity, indentation, int/float division). For the post-run ones (mutable default, global/local, `self`), p95 time-to-flag must be ≤ 11 s. | #27 |
| Statistical testing: a bootstrap CI over students for fusion − B3, and McNemar's test against each baseline. | #28 |
| Run events confirmed in both cohorts (#2), so RUNNING and execution features are used in training. | #5, #7 |
| The single-university public data is stated as a limitation. | #29, #32 |

### Specific-objective deadlines (final proposal §1.4)

| Objective | Due | Status on 26 Nov 2026 |
|---|---|---|
| SO1 Schema audit, code-state replay, occurrence count | 31 Oct 2026 | Audit (#2) and replay (#3) done; detectors 1–4 in review (#6); detectors 5–7 (#40) and the count (#8) outstanding, so **overdue** |
| SO2 Human-verified corpus, κ ≥ 0.80 | 15 Dec 2026 | Not started (#10, #11, #41) |
| SO3 LoRA fusion model and ablation under five-fold CV | 31 Jan 2027 | Not started |
| SO4 Web MVP, p95 latency < 1 s | 28 Feb 2027 | Scaffold only (#1) |
| SO5 Replay, cross-cohort and expert evaluation | 31 Mar 2027 | Not started |
