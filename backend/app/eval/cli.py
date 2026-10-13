from __future__ import annotations

import asyncio
import sys

from app.eval.benchmark import load_benchmark
from app.eval.runner import run_benchmark


def print_report_table(report) -> None:
    sep = "=" * 90
    sub_sep = "-" * 90

    print("\n" + sep)
    print("           AGENT WORKBENCH - REAL RETRIEVAL & BENCHMARK REPORT")
    print(sep)
    header = (
        f"{'ID':<8} {'Category':<14} {'HitRate@3':<11} {'MRR@3':<9} {'Prec@3':<9} "
        f"{'Latency':<10} {'Status':<6}"
    )
    print(header)
    print(sub_sep)

    for case in report.case_results:
        status_str = "PASS" if case.passed else "FAIL"
        latency_str = f"{case.duration_ms} ms"
        line = (
            f"{case.case_id:<8} {case.category:<14} {case.hit_rate:<11.2f} {case.mrr:<9.2f} "
            f"{case.precision:<9.2f} {latency_str:<10} {status_str}"
        )
        print(line)

    print(sub_sep)
    print(" BENCHMARK SUMMARY:")
    print(f"  - Total Test Cases       : {report.total_cases}")
    pct = f"({report.pass_rate * 100:.1f}%)"
    print(f"  - Passed Cases           : {report.passed_cases} / {report.total_cases} {pct}")
    print(f"  - Avg Retrieval HitRate@3: {report.avg_hit_rate:.2%}")
    print(f"  - Avg Retrieval MRR@3    : {report.avg_mrr:.4f}")
    print(f"  - Avg Precision@3        : {report.avg_precision:.4f}")
    print(f"  - Avg Tool Accuracy      : {report.avg_tool_accuracy:.2%}")
    print(f"  - Avg Overall Score      : {report.avg_overall_score:.4f}")
    print(f"  - Total Benchmark Time   : {report.duration_ms} ms")
    print(sep + "\n")


async def main() -> int:
    cases = load_benchmark()
    print(f"Executing Evaluation Suite ({len(cases)} cases against sample corpus)...")
    report = await run_benchmark(cases)
    print_report_table(report)
    return 0 if report.pass_rate >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
