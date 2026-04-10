"""
latency_metrics_v2.py  —  Full analysis with all paper metrics
================================================================
Reads latency_log.csv (produced by workload_gen_v2.py) and
decisions.csv (produced by scheduler_v2.py) and computes:

  - p50, p95, p99, TLR (Tail-Latency Ratio)
  - scheduling_delay stats (what the scheduler actually controls)
  - service_time stats (compute baseline, should be stable)
  - context switch rate
  - throughput (requests/second)
  - burst-phase vs normal-phase breakdown

Usage:
    python3 src/analysis/latency_metrics_v2.py
    python3 src/analysis/latency_metrics_v2.py --compare run1.csv run2.csv
"""

import os
import sys
import csv
import argparse
from collections import defaultdict

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
DATA_DIR = os.path.join(BASE_DIR, "data")
LAT_LOG  = os.path.join(DATA_DIR, "latency_log.csv")
DEC_LOG  = os.path.join(DATA_DIR, "decisions.csv")


def load_latencies(filepath=LAT_LOG):
    """
    Load latency log.
    Supports both old format (single float per line) and
    new format (CSV with header).
    Returns list of dicts with keys:
      scheduling_delay_ms, service_time_ms, total_latency_ms
    """
    rows = []
    if not os.path.exists(filepath):
        print(f"[ERROR] File not found: {filepath}")
        return rows

    with open(filepath) as f:
        first = f.read(100)
    
    # Detect format
    if "scheduling_delay" in first or "timestamp" in first:
        # New CSV format
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rows.append({
                        "scheduling_delay_ms": float(row["scheduling_delay_ms"]),
                        "service_time_ms":     float(row["service_time_ms"]),
                        "total_latency_ms":    float(row["total_latency_ms"]),
                        "pid":                 int(row.get("pid", 0)),
                    })
                except (ValueError, KeyError):
                    pass
    else:
        # Old format: one float per line
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        v = float(line)
                        # Old format only has total latency
                        rows.append({
                            "scheduling_delay_ms": 0.0,
                            "service_time_ms":     v,
                            "total_latency_ms":    v,
                            "pid":                 0,
                        })
                    except ValueError:
                        pass
    return rows


def percentile(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(int(p / 100.0 * len(s)), len(s) - 1)
    return round(s[idx], 3)


def mean(values):
    return round(sum(values) / len(values), 3) if values else 0.0


def compute_stats(rows, label=""):
    total_lats = [r["total_latency_ms"] for r in rows]
    sched_lats = [r["scheduling_delay_ms"] for r in rows]
    svc_lats   = [r["service_time_ms"] for r in rows]

    if not total_lats:
        print(f"[{label}] No data.")
        return {}

    p50  = percentile(total_lats, 50)
    p95  = percentile(total_lats, 95)
    p99  = percentile(total_lats, 99)
    tlr  = round(p99 / p50, 3) if p50 > 0 else 0.0

    stats = {
        "count":               len(total_lats),
        "p50_ms":              p50,
        "p95_ms":              p95,
        "p99_ms":              p99,
        "tlr":                 tlr,
        "mean_total_ms":       mean(total_lats),
        "mean_sched_delay_ms": mean(sched_lats),
        "mean_service_ms":     mean(svc_lats),
        "p99_sched_delay_ms":  percentile(sched_lats, 99),
    }
    return stats


def load_decisions(filepath=DEC_LOG):
    """Load scheduler decision log."""
    decisions = []
    if not os.path.exists(filepath):
        return decisions
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                decisions.append({
                    "burst":       int(row["burst"]),
                    "action":      row["action"],
                    "cpu_util":    float(row["cpu_util"]),
                    "ewma":        float(row["ewma"]),
                    "total_ctx":   int(row.get("total_ctx_switches", 0)),
                })
            except (ValueError, KeyError):
                pass
    return decisions


def print_report(stats, label, decisions=None):
    sep = "─" * 50
    print(f"\n{sep}")
    print(f"  {label}")
    print(sep)
    print(f"  Requests:              {stats['count']}")
    print(f"  p50 latency:           {stats['p50_ms']} ms")
    print(f"  p95 latency:           {stats['p95_ms']} ms")
    print(f"  p99 latency:           {stats['p99_ms']} ms")
    print(f"  TLR (p99/p50):         {stats['tlr']}   ← key metric")
    print(f"  Mean total latency:    {stats['mean_total_ms']} ms")
    print(f"  Mean scheduling delay: {stats['mean_sched_delay_ms']} ms")
    print(f"  p99 scheduling delay:  {stats['p99_sched_delay_ms']} ms")

    if decisions:
        burst_count = sum(1 for d in decisions if d["burst"] == 1)
        isolations  = sum(1 for d in decisions if d["action"] == "burst_isolate")
        total_ctx   = sum(d["total_ctx"] for d in decisions)
        avg_cpu     = mean([d["cpu_util"] for d in decisions])
        print(f"  Scheduler decisions:   {len(decisions)}")
        print(f"  Burst phases:          {burst_count} / {len(decisions)} intervals")
        print(f"  Isolation events:      {isolations}")
        print(f"  Total ctx switches:    {total_ctx}")
        print(f"  Avg CPU util:          {avg_cpu}%")
    print(sep)


def compare_two(file_a, label_a, file_b, label_b):
    rows_a = load_latencies(file_a)
    rows_b = load_latencies(file_b)
    stats_a = compute_stats(rows_a, label_a)
    stats_b = compute_stats(rows_b, label_b)

    print_report(stats_a, label_a)
    print_report(stats_b, label_b)

    # Delta table
    print(f"\n{'Metric':<28} {label_a:>12} {label_b:>12} {'Delta':>10}")
    print("─" * 65)
    for key in ["p50_ms", "p95_ms", "p99_ms", "tlr"]:
        a = stats_a.get(key, 0)
        b = stats_b.get(key, 0)
        delta = round(b - a, 3)
        pct   = round((b - a) / a * 100, 1) if a != 0 else 0
        sign  = "+" if delta > 0 else ""
        arrow = "↑ worse" if delta > 0 else "↓ better"
        print(f"  {key:<26} {a:>12} {b:>12}   {sign}{delta} ({pct}%) {arrow}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", nargs=2, metavar=("FILE_A", "FILE_B"),
                        help="Compare two latency log files")
    parser.add_argument("--labels", nargs=2, default=["Run 1", "Run 2"])
    args = parser.parse_args()

    if args.compare:
        compare_two(args.compare[0], args.labels[0],
                    args.compare[1], args.labels[1])
    else:
        rows = load_latencies(LAT_LOG)
        stats = compute_stats(rows, "Current run")
        decisions = load_decisions(DEC_LOG)
        print_report(stats, "Current run", decisions)