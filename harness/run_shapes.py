"""Does the request shape change the numbers?

The same row and the same question reach the API in different shapes
depending on which DuckDB integration sends them:

  A  this harness     state = the text; question = instructions + criteria;
                      one row per request.
  B  colliber shape   state = the text; question = criteria ONLY, no
                      instructions (its client never writes that key);
                      one row per request. Replayed through our client
                      because its binary is built for DuckDB 1.5.4.
  C  recodelabs       state = {"condition": ..., "rows": [up to 40 rows]};
                      one generic noul per row pointing at `rows[i]`. Run
                      through the extension itself, default batch of 40.
  C1 recodelabs       the same, with jev_batch_size = 1, to separate
                      "40 rows share one state" from "the condition lives
                      in the state instead of the question".

Baseline A comes from the cached calibration run. B, C and C1 cost real
money (about a cent each); everything is cached so a re-run is free.

Run: python3 harness/run_shapes.py [--limit N] [--skip-extension]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

import metrics as M
from client import JevClient, api_key, noul, score
from corpus import PROBES
from run_calibration import (
    CACHE, DATA, RELEVANCE_RUBRIC, RESULTS, load_corpus, questions_for,
)

EXT = DATA.parent / "extensions" / "recodelabs" / "jev.duckdb_extension"

TOPIC = {
    "space": "spaceflight, astronomy, or space exploration",
    "medical": "medicine, health, or medical treatment",
    "forsale": "offering an item for sale",
}


# ---------------------------------------------------------------- shapes --

def shape_b_questions(probe: str) -> dict:
    """colliber: criteria carry the whole meaning, no instructions."""
    t = TOPIC[probe]
    verb = "is" if probe != "forsale" else "is"
    return {
        "bool": {"type": "noul", "criteria": {
            "true": f"The message {verb} about {t}." if probe != "forsale"
                    else "The message is offering an item for sale.",
            "false": f"The message is not about {t}." if probe != "forsale"
                     else "The message is not offering an item for sale.",
        }},
        "score": {"type": "score",
                  "criteria": [lvl.replace("the topic", t) for lvl in RELEVANCE_RUBRIC]},
    }


def run_shape_b(rows, client) -> dict:
    out = {}
    for i, r in enumerate(rows):
        resp = client.ask(r["text"], shape_b_questions(r["probe"]))
        a = resp["answers"]
        out[r["row_id"]] = {"noul": a["bool"]["noul"], "score": a["score"]["score"]}
        if (i + 1) % 60 == 0:
            print(f"  B {i + 1}/{len(rows)}", file=sys.stderr)
    return out


def run_shape_c(rows, batch_size: int) -> tuple[dict, dict]:
    """Run the recodelabs extension for real, returning per-row answers
    and its own jev_stats() so its batching and cache claims are checked."""
    import duckdb
    con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
    con.execute(f"LOAD '{EXT}'")
    con.execute("SET jev_api_key = ?", [api_key()])
    con.execute("SET jev_notices = false")
    con.execute(f"SET jev_batch_size = {int(batch_size)}")
    con.execute("CREATE TABLE corpus (row_id VARCHAR, probe VARCHAR, text VARCHAR)")
    con.executemany("INSERT INTO corpus VALUES (?, ?, ?)",
                    [(r["row_id"], r["probe"], r["text"]) for r in rows])
    out = {}
    for probe, p in PROBES.items():
        # struct_pack(text := ...) so the model sees the text and nothing
        # else: no row_id, no probe name, and certainly no label.
        q = ("SELECT row_id, "
             "jev_prob(struct_pack(text := text), ?) AS p, "
             "jev_score(struct_pack(text := text), ?, ?) AS s "
             "FROM corpus WHERE probe = ?")
        for rid, pr, sc in con.execute(
            q, [p["question"], f"How directly is this message about {TOPIC[probe]}?",
                RELEVANCE_RUBRIC, probe]).fetchall():
            out[rid] = {"noul": pr, "score": sc}
        print(f"  C(batch={batch_size}) {probe} done", file=sys.stderr)
    stats_first = json.loads(con.execute("SELECT jev_stats()").fetchone()[0])
    # Second pass: the extension says answers are cached per row content.
    for probe, p in PROBES.items():
        con.execute("SELECT count(*) FROM (SELECT jev_prob(struct_pack(text := text), ?) "
                    "FROM corpus WHERE probe = ?)", [p["question"], probe]).fetchall()
    stats_second = json.loads(con.execute("SELECT jev_stats()").fetchone()[0])
    con.close()
    return out, {"after_first_pass": stats_first, "after_replay": stats_second}


# ------------------------------------------------------------- compare --

def compare(name, base, other, rows) -> dict:
    ids = [r["row_id"] for r in rows if r["row_id"] in base and r["row_id"] in other]
    by_id = {r["row_id"]: r for r in rows}
    y = np.array([by_id[i]["label"] for i in ids], float)
    conf = np.array([by_id[i].get("label_confident", True) for i in ids])
    rep = {"n": len(ids)}
    for key in ("noul", "score"):
        a = np.array([base[i][key] for i in ids], float)
        b = np.array([other[i][key] for i in ids], float)
        d = np.abs(a - b)
        scale = 1.0 if key == "noul" else float(len(RELEVANCE_RUBRIC) - 1)
        block = {
            "mean_abs_diff": float(d.mean()),
            "median_abs_diff": float(np.median(d)),
            "p95_abs_diff": float(np.percentile(d, 95)),
            "max_abs_diff": float(d.max()),
            "frac_changed_over_0.05": float((d > 0.05 * scale).mean()),
            "frac_changed_over_0.20": float((d > 0.20 * scale).mean()),
            "signed_mean_diff_other_minus_base": float((b - a).mean()),
            "spearman_between_shapes": M.rank_metrics(a, b)["spearman"]
                if len(np.unique(b)) > 1 else float("nan"),
            "ranking_vs_label": M.rank_metrics(b, y),
            "sort_key_resolution": M.sort_key_resolution(b),
        }
        if key == "noul":
            block["decision_flips_at_0.5"] = int(((a >= 0.5) != (b >= 0.5)).sum())
            block["ece"] = M.ece(b[conf], y[conf], n_bins=10, adaptive=True)["ece"]
            block["brier"] = M.brier(b[conf], y[conf])
            # Who is in the top group? ORDER BY p DESC LIMIT k draws from it.
            top_a = {i for i, v in zip(ids, a) if v == a.max()}
            top_b = {i for i, v in zip(ids, b) if v == b.max()}
            block["top_group"] = {
                "base_size": len(top_a), "other_size": len(top_b),
                "jaccard": len(top_a & top_b) / len(top_a | top_b),
            }
        rep[key] = block
    return rep


def baseline_from_cache(rows, client) -> dict:
    from client import Cache
    out = {}
    for r in rows:
        hit = client.cache.get(Cache.key(client.model, r["text"], questions_for(r["probe"])))
        if hit:
            a = hit["answers"]
            out[r["row_id"]] = {"noul": a["bool"]["noul"], "score": a["score"]["score"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip-extension", action="store_true")
    ap.add_argument("--token-budget", type=int, default=2_000_000)
    args = ap.parse_args()

    rows = load_corpus()
    if args.limit:
        rows = rows[: args.limit]
    client = JevClient(CACHE, token_budget=args.token_budget)

    base = baseline_from_cache(rows, client)
    print(f"A baseline: {len(base)}/{len(rows)} rows from cache")
    if len(base) < len(rows):
        sys.exit("baseline incomplete: run run_calibration.py first")

    print("B colliber shape (criteria only, no instructions)...")
    b = run_shape_b(rows, client)
    u = client.usage
    print(f"  B usage: {u.requests} requests, {u.total_tokens:,} tokens")

    report = {
        "n_rows": len(rows),
        "shapes": {
            "A": "state=text; instructions+criteria; 1 row/request (this harness)",
            "B": "state=text; criteria only, no instructions; 1 row/request (colliber)",
            "C": "state={condition, rows[<=40]}; generic noul per rows[i] (recodelabs, batch 40)",
            "C1": "as C with jev_batch_size=1 (recodelabs, batch 1)",
        },
        "B_vs_A": compare("B", base, b, rows),
        "usage_B": {"requests": u.requests, "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens},
    }

    if not args.skip_extension:
        if not EXT.exists():
            sys.exit(f"recodelabs extension not found at {EXT}")
        print("C recodelabs extension, batch 40...")
        c, stats_c = run_shape_c(rows, 40)
        report["C_vs_A"] = compare("C", base, c, rows)
        report["extension_stats_C"] = stats_c
        print("C1 recodelabs extension, batch 1...")
        c1, stats_c1 = run_shape_c(rows, 1)
        report["C1_vs_A"] = compare("C1", base, c1, rows)
        report["C1_vs_C"] = compare("C1vsC", c, c1, rows)
        report["extension_stats_C1"] = stats_c1
        # Keep the raw per-row numbers out of the repo: they are derived
        # from corpus text. Aggregates only.
        (DATA / "shapes_raw.json").write_text(json.dumps(
            {"B": b, "C": c, "C1": c1}, indent=1))

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "shapes.json").write_text(json.dumps(report, indent=2))
    print(f"\nWrote {RESULTS / 'shapes.json'}")
    for k in ("B_vs_A", "C_vs_A", "C1_vs_A", "C1_vs_C"):
        if k not in report:
            continue
        r = report[k]
        n = r["noul"]; s = r["score"]
        print(f"\n{k}: n={r['n']}")
        print(f"  noul : mean|d| {n['mean_abs_diff']:.3f}  p95 {n['p95_abs_diff']:.2f}  max {n['max_abs_diff']:.2f}"
              f"  >0.05: {n['frac_changed_over_0.05']:.1%}  >0.20: {n['frac_changed_over_0.20']:.1%}"
              f"  flips@0.5: {n['decision_flips_at_0.5']}  spearman {n['spearman_between_shapes']:.3f}")
        print(f"         ECE {n['ece']:.4f}  Brier {n['brier']:.4f}  inversion {n['ranking_vs_label']['inversion_rate']:.4f}"
              f"  distinct {n['sort_key_resolution']['distinct_values']}  rows@max {n['sort_key_resolution']['rows_at_max']}"
              f"  top-group jaccard {n['top_group']['jaccard']:.2f}")
        print(f"  score: mean|d| {s['mean_abs_diff']:.3f}  p95 {s['p95_abs_diff']:.2f}  >5%: {s['frac_changed_over_0.05']:.1%}"
              f"  spearman {s['spearman_between_shapes']:.3f}  inversion {s['ranking_vs_label']['inversion_rate']:.4f}")
    for k in ("extension_stats_C", "extension_stats_C1"):
        if k in report:
            f, s2 = report[k]["after_first_pass"], report[k]["after_replay"]
            print(f"\n{k}: first pass requests={f['requests']} batches={f['batches']} rows={f['rows_evaluated']} "
                  f"tokens={f['input_tokens']}+{f['output_tokens']} cost=${f['estimated_cost_usd']:.4f} cache_hits={f['cache_hits']}"
                  f"\n   replay: requests={s2['requests']} (delta {s2['requests'] - f['requests']}), cache_hits={s2['cache_hits']}")


if __name__ == "__main__":
    main()
