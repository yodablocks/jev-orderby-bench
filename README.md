# jev-orderby-bench

Does `ORDER BY` over a Jev probability put rows in a defensible order?
An independent measurement of TypeSafe AI's Jev (`jev-1.13.0`) on the
properties a semantic sort actually depends on: pairwise inversion rate,
Score ordinality against a graded target, and whether the probabilities
move with evidence or with wording. Calibration (ECE, Brier) is reported
too, but it is not the gate on its own: a model can be well calibrated in
aggregate and still invert the pairs a sorted page shows.

**Headline (2026-09-18): `jev-1.13.0` passes all six pre-registered gate
conditions on 360 human-labeled rows.** Boolean inversion rate 0.036;
Score ordinal inversion 0.143 against a 0.15 threshold, the weak link and
the sort key; negation asymmetry 0.016 but indistinguishable from plain
paraphrase sensitivity; underconfident in 8 of 10 bins. And the sort
key itself is coarse: probabilities come back at two decimals, 360 rows
produced 45 distinct values, and 53 rows tie at 0.99, so
`ORDER BY prob DESC LIMIT 20` returns 20 of those 53 in whatever order
the engine left them. See [Results](#results).

Run: 360 rows, 350 fresh requests, 359,013 tokens (~999/row), about $0.013.

## Where this sits

Three DuckDB integrations for Jev shipped in the week of its release:
[colliber/duckdb-jev](https://github.com/colliber/duckdb-jev),
[recodelabs/duckdb-jev](https://github.com/recodelabs/duckdb-jev) and
[Query-farm/vgi-typesafe](https://github.com/Query-farm/vgi-typesafe),
plus [pg-jev](https://github.com/realZachi/pg-jev) for Postgres. All
expose `ORDER BY` over a Jev probability; none ships a measurement of
whether that order is defensible. The vendor's
[evals](https://evals.typesafe.ai/) publish accuracy, cost and time
against labels averaged from two frontier models, and no calibration
figure. This repo is the measurement, not a fourth extension.
`harness/udf.py` is a reference for consuming the numbers at the SQL
boundary, gated on the results; use one of the extensions above for real
work.

Jev's SDK had its first public release on 2026-09-14 and the only figure
its vendor publishes is 67.8% agreement against averaged frontier
judgments, self-run and unreproduced.
Agreement with other models is not calibration, so these are independent
numbers rather than a reproduction of that one. Every method choice is in
the repo and the run is reproducible, so disagree with the numbers by
re-running rather than by taking anyone's word for it, including mine.

**Reproduce:** `python3 harness/run_calibration.py` with a key. At the
published price of $0.042 per million input tokens (output is free), the
full run costs about **$0.013**. Responses are cached locally, so once
you have run it, `--analyze-only` recomputes everything for nothing.

## License

Code: MIT (see `LICENSE`). This covers the harness only, **not** the
corpus (see [Corpus licensing](#corpus-licensing)) and not Jev's outputs,
which are governed by TypeSafe AI's terms.

## Results

`model: jev-1.13.0`, question set `60658e143af92016`.

| Primitive | Metric | Value | Gate |
|---|---|---|---|
| `jev_bool` | Brier | **0.0524** | |
| | ECE (adaptive, 10 bins) | **0.0453** | ≤ 0.10 ✓ |
| | ECE (fixed-width, 10 bins) | 0.0454 | |
| | resolution | 0.1820 | > 0 ✓ |
| | AUC | 0.9637 | |
| | inversion rate | **0.0363** | ≤ 0.15 ✓ |
| | distinct values / tied pairs | 45 / **21.6%** | |
| | rows tied at the top (0.99) | **53** | |
| `jev_choice` | accuracy | 0.8754 | |
| | confidence ECE | 0.0769 | ≤ 0.10 ✓ |
| `jev_score` | ordinal inversion | **0.1433** | ≤ 0.15 ✓ |
| | binary inversion | 0.0370 | |
| | distinct values / tied pairs | 88 / 15.0% | |
| | rows tied at the top (3.0) | 54 | |
| Invariant | negation \|P(q)+P(¬q)−1\| | 0.0161 | ≤ 0.15 ✓ |
| | rubric mirror error | 0.0223 (0.74% of scale) | |

Per probe (`jev_bool` ECE): medical 0.030, forsale 0.042, space 0.062.

### Four things the headline number hides

**1. The negation result is not about negation.** The jaggedness page
disclaims `P(q) = 1 - P(not q)`, and the identity in fact holds well:
median violation 0.010, only 2.8% of rows above 0.10. But the paraphrase
control measures 0.0159 against negation's 0.0161, a ratio of **1.01x**.
A semantically equivalent rewording disagrees just as much as a negation
does. So this is general wording stability, not a negation-specific
property, and the negation figure carries no information beyond the
control. Publishing it alone would have overclaimed. This is precisely
what the control was added to catch, and it fired.

**2. The model is systematically underconfident.** 8 of 10 reliability
bins sit above the diagonal, mean signed gap **+0.042**. That one-
directional consistency rules out noise. It is the benign direction for
ranking (ordering is preserved), but it means a `WHERE prob > 0.9`
threshold is stricter than it reads: the true rate at a predicted 0.855
is 0.914. Calibrate thresholds against this table, not against intuition.
MCE 0.126 is ~3x ECE, and the two mid-range bins (predicted 0.029 and
0.188) contribute over half the total error, so the miscalibration is
concentrated where the model is genuinely uncertain.

**3. `jev_score` is the weak link, and it is the sort key.** Ordinal
inversion 0.1433 against a 0.15 threshold is the only condition that
nearly failed, and it passes on a coarse proxy (the 3-level sampling
stratum, not human relevance grades). `jev_score_val` is what semantic
`ORDER BY` sorts on, so this is the number to re-measure on real data
before trusting production sorting. The binary figure of 0.0370 looks
far healthier and should not be quoted in its place: it cannot see
mis-ordering within the positives, which is the graded ordering that
`ORDER BY` actually exploits.

**4. The sort key is quantized to two decimals, and the top of the
ranking is one big tie.** Jev returns probabilities at two decimal
places. Over 360 rows `jev_bool` produced 45 distinct values; 21.6% of
all row pairs tie exactly, 154 rows sit at 0.01 and 53 at 0.99. Score
has the same shape: 88 distinct values, 54 rows tied at the maximum of
3.0. SQL does not define the order of rows that tie on the sort key, so
`ORDER BY prob DESC LIMIT 10`, `LIMIT 20` and `LIMIT 50` all cut inside
the 53-way tie at 0.99 and return an engine-dependent sample of it, not
a ranking. The inversion rate above cannot see this: it scores a tie as
half-discordant, and the rows tied at 0.99 mostly share a label, so
they are not comparable pairs. This is a property of the API's output,
so it applies to every extension identically, including the
`ORDER BY jev_prob(...) DESC LIMIT 20` pattern their READMEs show.
Mitigations, in order of how much they help: treat `LIMIT k` as a
filter (`WHERE prob >= 0.99`) and accept the whole group; break ties
with a second, more specific question or a Score's confidence; at
minimum add a deterministic secondary key (`ORDER BY prob DESC, id`) so
the result is at least reproducible. `sort_key_resolution` in
`results.json` reports the tie group at each cut.

The corpus, client, metrics, gate and notebook all run without a key;
only the scoring pass needs one. See [Running it](#running-it).

---

## Why the measurement comes before the SQL

The product is `ORDER BY` over a semantic score. If the probabilities are
not calibrated, the sort key is a meaningless number and every query fails
*silently*: rows come back in an order, just not a defensible one. Nothing
errors, nothing looks wrong, and the result is wrong. So the calibration
harness is the first deliverable and the gate on everything after it.

`udf.register()` enforces this in code: it refuses to register the SQL
functions unless `results/results.json` records a passing gate.

## What is measured

Two families, because a gate on calibration alone is the wrong gate.

**Calibration** (Brier + Murphy decomposition, ECE, MCE) asks: is a stated
0.7 really 70%?

**Ranking** (Spearman, Kendall, AUC, pairwise inversion rate) asks: does
sorting by this put rows in the right order?

They come apart in both directions. Probabilities squashed into
[0.48, 0.52] but perfectly ordered give an ECE of 0.485 with zero
inversions: terrible calibration, flawless sort. (That exact case is a
test in `test_metrics.py`.) Conversely a model calibrated in aggregate can
still invert many individual pairs and produce a visibly wrong page of
results. `ORDER BY` depends on the second family; the original spec's gate
named only the first.

**Invariants** are the third thing measured, and the most defensible,
because they need **no ground-truth labels at all**:

| Invariant | What it catches |
|---|---|
| Negation symmetry: `P(q)` vs `1 - P(not q)` | Probabilities that move with phrasing rather than evidence. The `jev-1.13` jaggedness page explicitly disclaims this identity, which is what makes it worth measuring. |
| Paraphrase control: `P(q)` vs `P(reworded q)` | The confound in the line above. A semantically equivalent rewording *should* agree, so this is the floor for general wording sensitivity. If it is as large as the negation violation, the asymmetry is not about negation at all, and the headline invariant has to be reported that way. Paraphrases preserve the **predicate**, not just the topic ("is this an offer to sell" not "does this concern selling"), because a drifted paraphrase inflates the control and would push the headline toward "not negation-specific" for the wrong reason. Reported per probe as well as aggregate, so one bad string cannot move the conclusion. |
| Score rubric ordinality: reversed rubric should mirror | Levels are scored independently and the model never sees level numbers, so ordinality is imposed entirely by *our* array order. If `score_reversed != scale_max - score`, the rubric is not ordinal to the model and every sort key built from it is noise. |

The negation question is derived **mechanically** from the positive one
rather than hand-written, so that a large measured asymmetry cannot be
explained away by the two strings not having been true complements.

All three ride along in a request already being paid for: one row costs
one request carrying six questions, not six requests.

Because these compare the model against itself, they are immune to the
label-provenance problem below. They are necessary, not sufficient:
passing negation symmetry does not imply calibration, but failing it means
the probabilities cannot be thresholded reliably, which kills
`WHERE prob > x` independently of calibration.

## Label provenance

This decides whether any of the numbers mean anything.

The corpus is **20 Newsgroups**, and each document's label is the
newsgroup its author chose to post it to: a human judgment, recorded by a
human, independent of this project. Hand-labeling the corpus ourselves
would have measured Jev's agreement with Claude and published it as
calibration, producing an authoritative-looking number worth nothing.

Selection constraints, in the order they bound the result:

1. Human-labeled by provenance, and freely redistributed for research
   (see [Corpus licensing](#corpus-licensing) for what that does and does
   not mean).
2. Single-factor labels, matching the spec's rule for questions.
3. Clear of Jev's documented weak spots. The jaggedness page for
   `jev-1.13` names math/counting, date comparison, and hex/RGB numeric
   representations. Topic membership touches none of them, so a
   miscalibration we measure is not secretly a counting failure.
4. **Labels span the probability range.** Sampling only obvious cases pins
   every prediction at 0 or 1, ECE comes out tiny, the gate passes
   vacuously, and nothing is learned.

Constraint 4 drives the stratified sampler: each probe draws clear
positives, topically adjacent **near misses**, and plainly unrelated
negatives, weighted toward the near misses. Default corpus is 360 rows
across 3 probes, inside the spec's 300-500 band.

### The near-miss labels are not all sound, and that is handled explicitly

The positive labels are safe: the author chose `sci.med`, so "is this
about medicine" is yes. **The negative labels are weaker.** A
`talk.politics.misc` post about healthcare reform genuinely *is* about
health; a `rec.autos` post selling a part genuinely *is* offering an item
for sale. The author picking a different newsgroup does not entail "not
about X."

This is sharper than generic label noise, because the sampler
deliberately concentrates the least reliable labels in the largest
stratum *and* in the mid-probability region where ECE is decided. A
correct 0.6 scored against a wrong `False` reads as miscalibration and
could fail a 0.10 gate on label error alone.

So doubtful rows are detected **per row, not per group**
(`is_ambiguous_negative`) and flagged `label_confident=False`: 7 of 360
rows. They are **excluded from every gated calibration metric** and
**kept for ranking**, because ranking only needs the pairs the labels do
order, and those hard rows are exactly where sort order matters.
`results.json` reports the all-rows figure alongside each gated one, so
it is visible how much work the exclusion is doing.

Banning whole groups was the first attempt and was wrong twice over.
Measured contamination is only 2-5% per group, so a ban discards ~95% of
usable rows; worse, it removed *both* of `forsale`'s near-miss groups,
collapsing that probe to clear positives plus clear negatives. That is
precisely the vacuous-gate failure constraint 4 exists to prevent,
reintroduced by the fix. Per-row filtering keeps all three strata on all
three probes (47 near-misses each).

Document headers are stripped before scoring. A leftover `Newsgroups:` or
`Subject:` line hands the model the answer, and an `Organization: Memorial
Sloan-Kettering Cancer Center` line makes an unrelated post look medical:
either way the run would be measuring header parsing, not judgment.

The vendor's self-reported 67.8% agreement against averaged frontier
judgments is not used as a baseline anywhere here. Agreement with other
models is not calibration.

### Corpus licensing

**20 Newsgroups carries no explicit license.** Neither the original
distribution page nor scikit-learn's documentation states one. It has
been redistributed for research since the 1990s and ships inside
scikit-learn, so research use is well established by convention, but
"conventionally redistributed" is not the same as "licensed", and this
README previously said "licensed for research use", which overstated
what can be verified. Corrected here rather than quietly.

Practical consequences:

- **No corpus text is committed to this repo.** Only aggregate metrics
  are (`results/results.json`). The corpus and the raw response cache are
  gitignored build artifacts you regenerate locally.
- The documents are public Usenet posts from the 1990s written by
  identifiable people. If you republish any of it, that is your call to
  make, not one this repo makes for you.
- **Content warning:** the corpus includes `talk.politics.*` and
  `talk.religion.*` posts, and scikit-learn explicitly warns that it
  "contains data which may be inappropriate for certain NLP
  applications" and that inflammatory or culturally biased text will
  propagate biases. The probe questions here are about topic membership,
  which does not surface that content in the metrics, but you will see it
  if you read the raw rows.

## Gate

Thresholds were fixed **before** any results were seen.

The spec asks for the three primitives to be *reported* separately because
they may calibrate differently. They are therefore *gated* separately too:
gating only `jev_bool` would let a Score that inverts a third of its pairs
through, and `jev_score_val` is the accessor `ORDER BY` actually sorts on.

| Condition | Threshold | Rationale |
|---|---|---|
| `jev_bool` ECE | ≤ 0.10 | A stated 0.8 that is really 0.7 is tolerable for ranking; wider and the probability is decorative. |
| `jev_bool` inversion rate | ≤ 0.15 | Past roughly one bad pair in six, a sorted page looks visibly wrong. |
| `jev_bool` resolution | > 0 | At or below zero, the model is not separating classes at all. A model predicting the base rate every time scores a respectable Brier and is useless for `ORDER BY`. |
| **`jev_score` inversion rate** | ≤ 0.15 | Graded ranking, scored against the 3-level ordinal stratum rather than the binary label, so it can detect mis-ordering *within* the positives. A necessary condition for semantic `ORDER BY`, gated on its own merits. |
| `jev_choice` confidence ECE | ≤ 0.10 | Does stated confidence predict whether the pick was right? |
| Negation asymmetry | ≤ 0.15 | Beyond this, phrasing moves the answer as much as evidence does. |

## Running it

The harness needs **no new packages**: numpy, scipy, sklearn, matplotlib
and requests are already present. `duckdb` is needed only by
`harness/udf.py`.

### The API key

Put it in a `.env` file rather than pasting it anywhere it could be
logged. `.env` is gitignored (and `test_pipeline.py` asserts that, so the
protection cannot rot silently):

```sh
cp .env.example .env
$EDITOR .env          # TYPESAFE_AI_API_KEY=your-key-here
```

The harness looks for `.env` at the repo root and accepts either
`TYPESAFE_AI_API_KEY` or `TYPESAFE_API_KEY` (the build spec names the
first, the published SDK page the second). An already exported shell
variable always wins, so a stale `.env` cannot silently override a key
you set deliberately.

`export TYPESAFE_AI_API_KEY=...` also works if you prefer not to have the
key on disk.

```sh
# one-time corpus download (~14MB, human-labeled; see Corpus licensing)
mkdir -p ~/scikit_learn_data/20news_home
curl -L -A "Mozilla/5.0" -o /tmp/20news.tar.gz \
  http://qwone.com/~jason/20Newsgroups/20news-bydate.tar.gz
tar xzf /tmp/20news.tar.gz -C ~/scikit_learn_data/20news_home

# build the corpus
python3 harness/corpus.py .data/jev-calibration/corpus.jsonl

# verify the harness with no API key and no spend
python3 harness/test_metrics.py     # 29 known-answer metric tests
python3 harness/test_pipeline.py    # end-to-end against a mock Jev server

# then, with a key in .env (or exported):
python3 harness/run_calibration.py --pilot   # 10 rows + cost extrapolation
python3 harness/run_calibration.py           # full run
python3 harness/run_calibration.py --analyze-only   # recompute, no spend
```

`harness/udf.py` additionally needs `pip install duckdb` (run it yourself; this
repo does not install packages autonomously).

## Execution layer

Built into the harness rather than retrofitted later, because all four
are cheaper to build now and the calibration run needs them anyway.

- **Batching.** Every question for a row goes in one request. Jev answers
  independent questions against one state in a single parallel pass, so
  the calibration run issues 1 request per row instead of 4, and pays for
  the state tokens once instead of six times. Verified by test: 60 rows →
  60 requests, 6 questions each.
- **Cache.** Content hash of `(model, state, questions)` → SQLite (WAL,
  thread-local connections). Verified: a replay run makes 0 requests and
  spends 0 tokens.
- **Cost ceiling.** Hard token budget that raises `BudgetExceeded` rather
  than degrading. `ORDER BY` over a large table is an easy way to spend
  real money by accident, so the failure mode is a loud stop.
- **Concurrency.** Bounded pool, exponential backoff with jitter,
  honouring `retry-after`. Retries 429/529/5xx; does not retry 401/422,
  which will not improve. Partial failures are collected and surfaced, not
  silently nulled.

Token usage is recorded per call from the first request. TypeSafe
publishes pricing ($0.042 per million input tokens, output free) and rate
limits (250k tokens/s, 1,200 requests/min, 64k context with 32k for state
plus the longest question) at docs.typesafe.ai/models, but the limits are
stated to adjust with demand, so a production cost ceiling is calibrated
from usage we measure ourselves rather than from the published figures.

## Consuming the numbers in SQL (reference only)

`harness/udf.py` registers these as DuckDB Python scalar functions. It
exists to show the shape the numbers should take at the SQL boundary,
not to compete with the native extensions above; the design points
below apply to any of them.

```
jev_bool(text, question)      -> STRUCT(value BOOLEAN, prob DOUBLE)
jev_choice(text, options[])   -> STRUCT(value VARCHAR, prob DOUBLE, confidence DOUBLE)
jev_score(text, rubric[])     -> STRUCT(score DOUBLE, confidence DOUBLE)
jev_score_val(text, rubric[]) -> DOUBLE
```

Structs, not bare values: returning NULL on low confidence poisons
`ORDER BY` unpredictably (DuckDB sorts NULLs last regardless of direction,
so low-confidence rows silently clump at one end), and a bare score hides
the uncertainty the caller needs. `jev_score_val` covers the case where
the caller has already decided to trust the score.

`jev_bool` exposes `prob` with no separate confidence because Noul returns
a probability and has no confidence field: `value` is `prob >= 0.5`.

### Score scale: the sharp edge

Score returns a probability-weighted mean over level **indices**, so an
`n`-level rubric spans `0..n-1`, **not** `0..1`. Therefore:

- `jev_score_val` output is **not comparable across different rubrics**.
- `ORDER BY` mixing rubrics is meaningless, and nothing in SQL will warn.

## Limitations

- **One corpus, one domain.** English newsgroup posts. Calibration is a
  property of model *and* domain; these numbers will not transfer to
  contracts, tickets or governance proposals without re-running.
- **Topic membership is an easy judgment**, so treat the results as an
  upper bound on harder ORDER BY workloads.
- **~120 rows per probe.** Ten-bin ECE is noisy at that size. Bins carry
  Wilson intervals and adaptive (equal-mass) binning is the default; read
  the intervals, not the third decimal.
- **Adaptive ECE is sensitive to tie handling at the ±0.003 level.** Jev
  returns two-decimal probabilities and 154 of 360 rows sit at exactly
  0.01, so five of the ten equal-mass bins contain that one tied value
  (three consist of nothing else) and which tied rows fall on which
  side of a bin edge is arbitrary. An
  earlier draft of this table reported 0.0427 from the same responses in
  a different row order; the code now sorts rows canonically so the
  number is reproducible, but the fixed-width ECE (0.0454), which has no
  tie problem, is the one to quote if the third decimal matters.
- **20 Newsgroups labels are themselves noisy** (cross-posting, imperfect
  group choice), which inflates apparent miscalibration. The worst cases
  are held out of ECE (see above), but the remaining negatives are still
  "the author posted elsewhere", not "a human judged this not-about-X".
- **The tie statistics are corpus-dependent; the quantization is not.**
  Topic membership is easy, which crowds rows at 0.01 and 0.99. A harder
  corpus would spread values across the range and shrink the top tie
  group. Two-decimal output is a property of the API and caps the sort
  key at 101 distinct values whatever the corpus.
- **Invariants bound wording sensitivity, not correctness.** A model can
  be perfectly self-consistent and consistently wrong.
- **Graded ranking is proxied, not measured directly.** The ordinal target
  is the 3-level sampling stratum, not a human-assigned relevance grade.
  It detects gross mis-ordering within the positives; it cannot certify
  fine-grained rank quality.
- **`jev-latest` is a moving target.** The `model` field from each
  response is recorded; these numbers attach to one version.

## Layout

```
harness/corpus.py           stratified corpus builder, provenance notes
harness/client.py           batching, cache, budget, retries, metering
harness/metrics.py          calibration + ranking + invariants + gate
harness/run_calibration.py  scoring run, analysis, reliability diagram
harness/udf.py              reference DuckDB functions (gated on results.json)
harness/test_metrics.py     known-answer tests for every metric
harness/test_pipeline.py    end-to-end test against a mock Jev server,
                            plus secret-hygiene assertions
.env.example                copy to .env and add your key (.env is ignored)
notebook/calibration.ipynb  the publishable artifact
results/                    results.json + reliability.png (after a run)
```

Corpus and cached responses live in `.data/jev-calibration/` (gitignored):
raw response bodies can contain corpus text, and the cache is a build
artifact.
