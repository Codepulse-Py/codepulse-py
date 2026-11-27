# Synthetic data validated against real data (#75)

The proposal defence panel (12 Nov 2026) asked that the existing dataset be checked against
AI-generated data. The final proposal (§3.2.1) turned that into four checks that every synthetic
batch must pass before it is used. This document reports them for the synthetic windows from #9.

> **Result: all four synthetic batches fail check (b) and are rejected.** A classifier tells
> synthetic from real windows almost perfectly (AUROC 0.99 or more, against a limit of 0.70),
> including on behavioural features alone. This held across three rounds of revising the
> generator. Under §3.2.1 the synthetic data is **not used for training**. Mutable default,
> aliasing, identity vs equality and `self` confusion are reported as **exploratory**.

## Method

**Reproduce** (about 1 minute):

```bash
python scripts/validate_synthetic.py run
```

The code is `synthetic/validate.py`, and the outputs go to `data/interim/synthetic_validation/`.

**What is compared.** The rare classes have almost no real cases (aliasing has none), so
"synthetic vs real windows of the same misconception" can't always be measured directly. Two real
reference sets are used:

| Real reference set | Windows |
|---|---|
| **pooled**: real 2021 windows ending within 60 s after a persistent candidate episode starts (#8), any class. These are the real "misconception moments". | 1,424 |
| **same class**: the same, restricted to the synthetic batch's own misconception, where real cases exist | `self` 160, identity 23, mutable default and aliasing none |

Synthetic windows are those ending within 60 s after the injection. They come in two variants:

- **all**: these may include the student's real lead-in;
- **post**: windows starting after the injection, so the behaviour in them is entirely
  simulated.

Only 2021 is used, because the synthetic data is built from 2021 and the 2019 editor differs.

**Features.** The 50 window features from `docs/features.md`, without `n_flags` and
`flags_changed`. Those two are set by construction in synthetic windows, and on real data alone
they separate candidate moments from other moments. The discriminator is also run on the **43
behavioural features only**, without the code-structure group. Code size differs legitimately
by class: mutable defaults and `self` need functions and classes, while the pooled real
candidates are mostly indentation and division in small early programs. Behaviour is what the
panel's concern is about.

**The checks:**

- **(a)** Two-sample Kolmogorov–Smirnov test per feature, with Benjamini–Hochberg correction,
  plus the Jensen–Shannon divergence. A feature *differs* if its adjusted p < 0.05 and JS > 0.10.
- **(b)** A gradient-boosted classifier (scikit-learn `HistGradientBoostingClassifier`)
  separates real from synthetic. Folds are 5-fold `StratifiedGroupKFold`, grouped by student:
  real windows by their student, synthetic windows by their seed student, so a student's real
  and synthetic windows are never split across folds. Real windows are capped at 3× the
  synthetic ones. The out-of-fold AUROC is reported. **A batch with AUROC > 0.70 is rejected.**

## Baselines: how separable real data is from itself

To read the AUROCs, the same discriminator was run on real data only:

| Comparison | All features | Behaviour only |
|---|---:|---:|
| Random real windows vs random real windows | 0.508 | 0.515 |
| Real candidate moments vs other real moments | 0.779 | 0.669 |

Real windows from genuinely different situations are only moderately separable. A realistic
synthetic batch should therefore score near the 0.5–0.7 range, not near 1.

## Results (generator v4, the final revision)

**Primary test:** pooled reference, all windows.

| Misconception | Synthetic / real windows | AUROC | AUROC behaviour only | Features differing (a) | Verdict |
|---|---:|---:|---:|---:|---|
| Aliasing | 732 / 1,424 | **0.998** | 0.998 | 23 of 50 | ✗ rejected |
| Identity vs equality | 643 / 1,424 | **0.993** | 0.994 | 9 of 50 | ✗ rejected |
| Mutable default | 626 / 1,424 | **0.995** | 0.993 | 24 of 50 | ✗ rejected |
| `self` confusion | 657 / 1,424 | **0.995** | 0.990 | 10 of 50 | ✗ rejected |

**Other variants:** all of these fail as well.

| Variant | AUROC |
|---|---|
| Same-class reference | identity 0.911, `self` 0.940 |
| Purely simulated "post" windows | 0.986–1.000 |
| Each injection method separately | 0.87 (grounded `moved_local`, 33 windows) to 1.00 (`accumulator_param`) |

`report.json` has every combination.

**What gives the synthetic windows away:** median values on the pooled reference, by largest
Jensen–Shannon divergence:

| Feature | Synthetic | Real | Why |
|---|---:|---:|---|
| `jump_max` | 154 | 19 | Cues add lines (prints) away from the injection; real students edit in one place |
| `secs_since_last_run` | 15.9 | 57.1 | Cue runs follow the injection within seconds |
| `unparseable_share` | 0.60 | 0.25 | Injected text is typed character by character through broken states |
| `n_functions`, `ast_nodes` | 7.5, 426 | 2, 199 | These misconceptions need functions and classes, so seeds are larger programs |
| `iei_mean_s` | 0.58 | 0.74 | Simulated typing is steadier than real typing |

## Revision history

§3.2.1 says to revise the generator when features differ, then re-test.

| Generator | Change | Primary AUROC (alias / identity / mutable / `self`) |
|---|---|---|
| v2 | As merged in #9 and #83 (seeds at runs; run outcomes) | 0.999 / 0.995 / 0.999 / 0.996 |
| v3 | Seeds sampled from any moment of a session; PyCharm-style auto-closed brackets; typos at the student's rate | 0.998 / 0.996 / 0.998 / 0.996 |
| v4 | Typo rate scaled to real typo fixes; pause before cue runs; 1–2 cues | 0.998 / 0.993 / 0.995 / 0.995 |

v2 and v3 were measured with the flag-derived features still included; v4 excludes them.
Excluding them changed little.

**Why revision stopped.** Three rounds moved the AUROC by less than 0.01, while real-vs-real
comparisons sit at 0.67–0.78. The separation comes from the post-injection behaviour being
*scripted*: which cues happen, in what order, at what distance. Nudging individual feature values
does not change that. Revising further until the batch slips under this classifier would tune
the data to the test and empty the check of meaning. v3 and v4 are kept in the generator because
they are improvements (auto-closed brackets and real typo rates match the 2021 editor), not
because they pass.

## Checks (c) and (d)

- **(c) Blind annotation.** `scripts/validate_synthetic.py run` also writes a blinded packet:
  60 synthetic and 60 real windows with the code at the window end and a behaviour summary, plus
  a separate answer key. `scripts/validate_synthetic.py score --annotations labels.csv` reports κ
  against the intended labels (it must be ≥ 0.80). The packet is **not needed now**: a batch that
  fails (b) is rejected whatever the annotation shows. It is ready for any future revised batch.
- **(d) With-and-without ablation.** Not applicable. No synthetic batch is admitted, so the
  fusion model (#15) is trained on real data only, and that result is the primary one, as
  §3.2.1 requires.

## Consequences for the plan (for supervisor discussion)

1. **Training data.** The fusion model and the baselines are trained on real windows only. The
   four rare classes keep only their few real candidates:
   - mutable default 4, aliasing 0 and identity 5 (from `docs/rq1.md`);
   - `self` confusion 29, all in 2021.
2. **Claims.** As in `docs/rq1.md`, option (a): the main results cover the classes that pass the
   50-case gate after verification (indentation scope, int vs float division, global vs local).
   The other four are exploratory. This now holds *without* synthetic support for them.
3. **Options if those classes are needed:**
   - **Contingency collection** (#76 ethics, #77 cohort-bias controls), with tasks that elicit
     them. This gives real data and needs no synthetic validation, at the cost of time.
   - **The proposal's original LLM-prompted generator.** It would most likely fail the same way,
     because its edit traces would also be simulated; it is the trace, not the code, that the
     discriminator detects.
4. **For the thesis:** this is a reportable finding. Rule-based injection into real code passes
   structural checks but not behavioural ones. Simulated keystroke behaviour around a
   misconception is easy to tell from real behaviour (AUROC ≥ 0.99 against a real-vs-real
   baseline of 0.67–0.78). This supports the panel's caution.
