"""
validate_classifier.py

Reads classify_signal.csv (which has ground_truth labels written by workload_gen.py)
and simulates what classifier.py would have decided, then computes:
  - Accuracy, Precision, Recall per class
  - Confusion matrix
  - Plots: confusion matrix heatmap + per-trial p99 comparison

Usage:
    python3 validate_classifier.py
    python3 validate_classifier.py --signals data/trial1_classified_signals.csv
    python3 validate_classifier.py --compare \
        data/trial1_labelled_latency.csv \
        data/trial1_classified_latency.csv
"""

import os, sys, csv, argparse, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR  = os.path.join(ROOT, "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

T_BURST = 30.0   # must match classifier.py
WINDOW  = 10


# ── Classifier simulation ─────────────────────────────────────

def simulate_classifier(signals_path):
    """
    Re-run the classifier logic on the signal file.
    Returns list of (pid, ground_truth, predicted) tuples.
    """
    history     = collections.defaultdict(lambda: collections.deque(maxlen=WINDOW))
    results     = []

    with open(signals_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pid          = int(row["pid"])
                burst        = float(row["cpu_burst_ms"])
                ground_truth = row["ground_truth"].strip()
            except (KeyError, ValueError):
                continue

            history[pid].append(burst)

            if len(history[pid]) >= 3:
                mean_burst = sum(history[pid]) / len(history[pid])
                predicted  = "LC" if mean_burst < T_BURST else "BG"
                results.append((pid, ground_truth, predicted))

    return results


def compute_metrics(results):
    classes = ["LC", "BG"]
    # confusion[true][pred]
    confusion = {c: {c2: 0 for c2 in classes} for c in classes}
    for _, gt, pred in results:
        if gt in confusion and pred in classes:
            confusion[gt][pred] += 1

    total   = len(results)
    correct = sum(1 for _, gt, pred in results if gt == pred)
    accuracy = correct / total if total > 0 else 0.0

    metrics = {}
    for cls in classes:
        tp = confusion[cls][cls]
        fp = sum(confusion[c][cls] for c in classes if c != cls)
        fn = sum(confusion[cls][c] for c in classes if c != cls)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = (2 * precision * recall / (precision + recall)
                     if (precision + recall) > 0 else 0.0)
        metrics[cls] = dict(tp=tp, fp=fp, fn=fn,
                            precision=precision, recall=recall, f1=f1)
    return accuracy, confusion, metrics


def print_report(accuracy, confusion, metrics, signals_path):
    total = sum(sum(row.values()) for row in confusion.values())
    print(f"\n{'─'*52}")
    print(f"  Classifier Validation Report")
    print(f"  Signals file : {os.path.basename(signals_path)}")
    print(f"  Threshold    : T_BURST = {T_BURST} ms")
    print(f"  Total obs    : {total}")
    print(f"{'─'*52}")
    print(f"  Overall accuracy : {accuracy*100:.1f}%")
    print(f"\n  {'Class':<8} {'Precision':>10} {'Recall':>10} {'F1':>8}")
    print(f"  {'─'*38}")
    for cls, m in metrics.items():
        print(f"  {cls:<8} {m['precision']*100:>9.1f}% {m['recall']*100:>9.1f}% {m['f1']*100:>7.1f}%")
    print(f"\n  Confusion matrix (rows=actual, cols=predicted):")
    print(f"              {'LC':>8} {'BG':>8}")
    for cls in ["LC", "BG"]:
        print(f"  actual {cls:<2}:  {confusion[cls]['LC']:>8}  {confusion[cls]['BG']:>8}")
    print(f"{'─'*52}\n")


# ── Plot 1: Confusion matrix heatmap ─────────────────────────

def plot_confusion(confusion, accuracy, out_path):
    classes = ["LC", "BG"]
    matrix  = np.array([[confusion[r][c] for c in classes] for r in classes])
    total   = matrix.sum()

    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(matrix, cmap="Blues", aspect="auto")

    ax.set_xticks([0, 1]); ax.set_yticks([0, 1])
    ax.set_xticklabels(["Predicted LC", "Predicted BG"], fontsize=11)
    ax.set_yticklabels(["Actual LC", "Actual BG"], fontsize=11)

    for i in range(2):
        for j in range(2):
            count = matrix[i, j]
            pct   = count / total * 100
            color = "white" if matrix[i, j] > matrix.max() / 2 else "black"
            ax.text(j, i, f"{count}\n({pct:.1f}%)",
                    ha="center", va="center", fontsize=12,
                    fontweight="bold", color=color)

    ax.set_title(f"Classifier Confusion Matrix\nAccuracy = {accuracy*100:.1f}%",
                 fontsize=12, fontweight="bold", pad=12)
    plt.colorbar(im, ax=ax, shrink=0.8)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Saved] {out_path}")


# ── Plot 2: per-trial p99 comparison (labelled vs classified) ─

def percentile(values, p):
    if not values: return 0.0
    s   = sorted(values)
    idx = min(int(p / 100.0 * len(s)), len(s) - 1)
    return round(s[idx], 3)


def load_p99(filepath):
    vals = []
    try:
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    vals.append(float(row["total_latency_ms"]))
                except (KeyError, ValueError):
                    pass
    except Exception:
        pass
    return percentile(vals, 99) if vals else None


def plot_p99_comparison(labelled_files, classified_files, out_path):
    """
    labelled_files   : list of paths, one per trial
    classified_files : list of paths, one per trial
    """
    trials   = list(range(1, len(labelled_files) + 1))
    lab_p99  = [load_p99(f) for f in labelled_files]
    cls_p99  = [load_p99(f) for f in classified_files]

    # Filter out None (missing files)
    valid = [(t, l, c) for t, l, c in zip(trials, lab_p99, cls_p99)
             if l is not None and c is not None]
    if not valid:
        print("[WARN] No valid data for p99 comparison plot.")
        return
    trials, lab_p99, cls_p99 = zip(*valid)

    fig, ax = plt.subplots(figsize=(7, 4.5))

    ax.plot(trials, lab_p99,  "o-", color="#6B7280", linewidth=2,
            markersize=8, label="PTLS-labelled (ground truth)")
    ax.plot(trials, cls_p99,  "s-", color="#3730A3", linewidth=2,
            markersize=8, label="PTLS-classified (runtime)")

    # Shade the gap
    ax.fill_between(trials, lab_p99, cls_p99, alpha=0.10, color="#3730A3")

    # Annotate each classified point with delta
    for t, l, c in zip(trials, lab_p99, cls_p99):
        delta = round((c - l) / l * 100, 1)
        sign  = "+" if delta > 0 else ""
        color = "#DC2626" if delta > 5 else "#0D9488"
        ax.text(t, c + 0.3, f"{sign}{delta}%", ha="center",
                fontsize=9, color=color, fontweight="bold")

    ax.set_xlabel("Trial", fontsize=11)
    ax.set_ylabel("p99 latency (ms)", fontsize=11)
    ax.set_title("p99 latency — labelled vs classified scheduling\n"
                 "(parity = classifier works correctly)",
                 fontsize=12, fontweight="bold")
    ax.set_xticks(list(trials))
    ax.legend(fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[Saved] {out_path}")


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals",  default=os.path.join(DATA_DIR, "classify_signal.csv"),
                        help="classify_signal.csv to validate")
    parser.add_argument("--compare",  nargs=2, metavar=("LABELLED", "CLASSIFIED"),
                        help="Two latency CSVs to compare p99")
    parser.add_argument("--trials",   type=int, default=2,
                        help="Number of trials to scan for p99 comparison")
    args = parser.parse_args()

    # ── Classifier accuracy ───────────────────────────────────
    if os.path.exists(args.signals):
        results  = simulate_classifier(args.signals)
        accuracy, confusion, metrics = compute_metrics(results)
        print_report(accuracy, confusion, metrics, args.signals)
        plot_confusion(confusion, accuracy,
                       os.path.join(OUT_DIR, "fig_confusion_matrix.png"))
    else:
        print(f"[WARN] Signal file not found: {args.signals}")

    # ── p99 comparison ────────────────────────────────────────
    if args.compare:
        # Single pair provided explicitly
        plot_p99_comparison([args.compare[0]], [args.compare[1]],
                            os.path.join(OUT_DIR, "fig_p99_labelled_vs_classified.png"))
    else:
        # Auto-scan data/ for trial files
        lab_files = []
        cls_files = []
        for t in range(1, args.trials + 1):
            lf = os.path.join(DATA_DIR, f"trial{t}_labelled_latency.csv")
            cf = os.path.join(DATA_DIR, f"trial{t}_classified_latency.csv")
            lab_files.append(lf)
            cls_files.append(cf)

        plot_p99_comparison(lab_files, cls_files,
                            os.path.join(OUT_DIR, "fig_p99_labelled_vs_classified.png"))