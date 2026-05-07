"""
classifier.py  — runtime task classifier  (~50 lines of logic)

Reads classify_signal.csv (written by workload_gen.py).
For each PID, maintains a rolling mean of cpu_burst_ms.
Applies threshold T_BURST to label each PID as LC or BG.
Writes classified_pids.csv so the scheduler can read it.

Threshold justification:
  LC tasks run sum(i*i for i in range(100_000)) → ~3–15 ms
  BG tasks run 2_000_000 iterations             → ~50–200 ms
  T_BURST = 30 ms sits cleanly in the valley between the two modes.
  (Confirmed from service_time_ms histogram of baseline runs.)
"""

import os, time, csv, collections

DATA_DIR        = os.path.expanduser("~/systemsproj/data")
SIGNAL_FILE     = os.path.join(DATA_DIR, "classify_signal.csv")
CLASSIFIED_FILE = os.path.join(DATA_DIR, "classified_pids.csv")

T_BURST   = 30.0   # ms  — threshold between LC and BG burst durations
WINDOW    = 10     # rolling mean over last N observations per PID
POLL_S    = 1.0    # re-evaluate every second


def classify(mean_burst_ms):
    return "LC" if mean_burst_ms < T_BURST else "BG"


def run_classifier():
    os.makedirs(DATA_DIR, exist_ok=True)

    # pid → deque of recent cpu_burst_ms values
    history = collections.defaultdict(lambda: collections.deque(maxlen=WINDOW))
    seen_rows = 0

    print(f"[Classifier] T_BURST={T_BURST}ms  window={WINDOW}  poll={POLL_S}s")
    print(f"[Classifier] Reading: {SIGNAL_FILE}")
    print(f"[Classifier] Writing: {CLASSIFIED_FILE}")

    while True:
        # ── Read new rows from signal file ────────────────────
        try:
            with open(SIGNAL_FILE) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception:
            time.sleep(POLL_S)
            continue

        for row in rows[seen_rows:]:
            try:
                pid           = int(row["pid"])
                cpu_burst_ms  = float(row["cpu_burst_ms"])
                history[pid].append(cpu_burst_ms)
            except (KeyError, ValueError):
                pass
        seen_rows = len(rows)

        # ── Classify each known PID ───────────────────────────
        lc_pids, bg_pids = [], []
        for pid, bursts in history.items():
            if len(bursts) < 3:          # wait for at least 3 observations
                continue
            label = classify(sum(bursts) / len(bursts))
            (lc_pids if label == "LC" else bg_pids).append(pid)

        # ── Write classified_pids.csv ─────────────────────────
        with open(CLASSIFIED_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["pid", "label"])
            for pid in lc_pids:
                writer.writerow([pid, "LC"])
            for pid in bg_pids:
                writer.writerow([pid, "BG"])

        print(f"[Classifier] LC={lc_pids}  BG={bg_pids}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    run_classifier()