"""Retrieval evaluation — Recall@k + MRR per category + overall refusal rate.

Usage (inside the backend container):
    python -m evals.run_retrieval_eval

Writes a markdown summary to backend/evals/reports/retrieval_<repo>.md and
prints the same to stdout so it can be pasted into the README.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import yaml

from src.config import settings
from src.retrieve import search_code, should_answer

EVALS_DIR = Path(__file__).parent
GOLD_SET = EVALS_DIR / "gold_set.yaml"
REFUSAL_SET = EVALS_DIR / "refusal_set.yaml"
REPORTS_DIR = EVALS_DIR / "reports"


# ── Matching ─────────────────────────────────────────────────────────
def is_hit(retrieved_symbol_path: str, expected: list[str]) -> bool:
    """A chunk counts as a hit if its symbol_path suffix-matches OR contains
    any expected symbol (lenient — Flask's symbol_paths are deep)."""
    rp = (retrieved_symbol_path or "").lower()
    for exp in expected:
        e = exp.lower()
        if rp == e or rp.endswith("." + e) or e in rp:
            return True
    return False


# ── Per-query scoring ────────────────────────────────────────────────
def score_query(case: dict) -> dict:
    k = case.get("k", 5)
    expected = case["expected_symbols"]
    t0 = time.time()
    chunks = search_code(
        case["query"],
        tenant=settings.REPO_NAME,
        top_k=k,
        expand=False,           # eval the bare retrieval, not the expanded view
    )
    elapsed = time.time() - t0

    # Restrict to chunks the retriever actually returned (filter parent/file
    # expansions if any leaked in — expand=False should prevent this).
    search_chunks = [c for c in chunks if c.source == "search"]

    retrieved_paths = [c.symbol_path or c.file_path for c in search_chunks]
    hits = [p for p in retrieved_paths if is_hit(p, expected)]

    # Recall@k: at least one hit anywhere in top-k counts as full credit
    # since most queries have a small expected_symbols set. (We don't
    # require all expected to appear — that'd be too strict.)
    recall = 1.0 if hits else 0.0

    # MRR: reciprocal rank of first hit
    rr = 0.0
    for i, p in enumerate(retrieved_paths, 1):
        if is_hit(p, expected):
            rr = 1.0 / i
            break

    return {
        "query": case["query"],
        "category": case["category"],
        "k": k,
        "recall": recall,
        "mrr": rr,
        "elapsed_s": round(elapsed, 2),
        "retrieved": retrieved_paths,
        "expected": expected,
        "first_hit_rank": next(
            (i for i, p in enumerate(retrieved_paths, 1) if is_hit(p, expected)),
            None,
        ),
    }


# ── Refusal scoring ──────────────────────────────────────────────────
def score_refusal(case: dict, threshold: float = 0.3) -> dict:
    chunks = search_code(case["query"], tenant=settings.REPO_NAME, top_k=5, expand=False)
    refused = not should_answer(chunks, threshold=threshold)
    top_score = chunks[0].rerank_score if chunks else None
    return {
        "query": case["query"],
        "reason": case.get("reason", ""),
        "refused": refused,
        "top_rerank_score": round(top_score, 4) if top_score is not None else None,
    }


# ── Reporting ────────────────────────────────────────────────────────
def by_category(results: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cats: dict[str, list[dict]] = {}
    for r in results:
        cats.setdefault(r["category"], []).append(r)
    for cat, rows in cats.items():
        out[cat] = {
            "n": len(rows),
            "recall_at_k": round(statistics.mean(r["recall"] for r in rows), 3),
            "mrr": round(statistics.mean(r["mrr"] for r in rows), 3),
        }
    return out


def write_markdown(retrieval: list[dict], refusal: list[dict]) -> str:
    overall_recall = statistics.mean(r["recall"] for r in retrieval)
    overall_mrr = statistics.mean(r["mrr"] for r in retrieval)
    refusal_rate = statistics.mean(1.0 if r["refused"] else 0.0 for r in refusal)
    p50_latency = statistics.median(r["elapsed_s"] for r in retrieval)
    p95_latency = sorted(r["elapsed_s"] for r in retrieval)[int(len(retrieval) * 0.95)]
    cats = by_category(retrieval)

    lines: list[str] = []
    lines.append(f"# Retrieval Evaluation — {settings.REPO_NAME}\n")
    lines.append(f"Gold set: {len(retrieval)} queries · Refusal set: {len(refusal)} queries\n")
    lines.append("## Overall\n")
    lines.append(f"- Recall@k:  **{overall_recall:.3f}**")
    lines.append(f"- MRR:       **{overall_mrr:.3f}**")
    lines.append(f"- Refusal rate (off-topic queries correctly refused): **{refusal_rate * 100:.0f}%**")
    lines.append(f"- Latency (p50 / p95): **{p50_latency:.2f}s / {p95_latency:.2f}s**\n")
    lines.append("## By category\n")
    lines.append("| Category | N | Recall@k | MRR |")
    lines.append("|---|---|---|---|")
    for cat in sorted(cats):
        c = cats[cat]
        lines.append(f"| {cat:<20s} | {c['n']} | {c['recall_at_k']:.3f} | {c['mrr']:.3f} |")
    lines.append("")

    misses = [r for r in retrieval if r["recall"] == 0.0]
    if misses:
        lines.append(f"## Misses ({len(misses)} of {len(retrieval)})\n")
        for r in misses:
            lines.append(f"- **{r['query']}** _(cat: {r['category']})_")
            lines.append(f"  - expected: `{r['expected']}`")
            lines.append(f"  - retrieved top-{r['k']}: `{r['retrieved'][:3]}{'…' if len(r['retrieved']) > 3 else ''}`")
        lines.append("")

    lines.append("## Refusal set\n")
    lines.append("| Query | Refused | Top rerank |")
    lines.append("|---|---|---|")
    for r in refusal:
        marker = "✓" if r["refused"] else "✗"
        score = f"{r['top_rerank_score']:.3f}" if r["top_rerank_score"] is not None else "—"
        lines.append(f"| {r['query'][:60]} | {marker} | {score} |")
    lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────
def main() -> int:
    with open(GOLD_SET) as f:
        gold = yaml.safe_load(f)
    with open(REFUSAL_SET) as f:
        refusal = yaml.safe_load(f)

    print(f"== Running retrieval eval on {settings.REPO_NAME} ==")
    print(f"  Gold set:    {len(gold)} queries")
    print(f"  Refusal set: {len(refusal)} queries\n")

    retrieval_results: list[dict] = []
    for i, case in enumerate(gold, 1):
        r = score_query(case)
        marker = "✓" if r["recall"] > 0 else "✗"
        rank = f"rank={r['first_hit_rank']}" if r["first_hit_rank"] else "no hit"
        print(f"  [{i:>2d}/{len(gold)}] {marker} {r['category']:<20s} "
              f"recall={r['recall']:.0f} mrr={r['mrr']:.2f} {rank}  · {r['query'][:55]}")
        retrieval_results.append(r)

    print()
    refusal_results: list[dict] = []
    for i, case in enumerate(refusal, 1):
        r = score_refusal(case)
        marker = "✓ refused" if r["refused"] else "✗ ANSWERED"
        print(f"  [{i:>2d}/{len(refusal)}] {marker:<15s} top={r['top_rerank_score']}  · {r['query'][:55]}")
        refusal_results.append(r)

    md = write_markdown(retrieval_results, refusal_results)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"retrieval_{settings.REPO_NAME}.md"
    out_path.write_text(md)
    print(f"\n📝 Report written to {out_path}")
    print("\n" + "=" * 60)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
