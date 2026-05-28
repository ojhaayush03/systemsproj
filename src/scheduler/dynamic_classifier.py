"""
classifier.py  — adaptive threshold v2 + label event log

Identical to the fixed classifier.py EXCEPT:
  - Writes data/dynamic_label_log.csv every time a PID's confirmed
    label is set or changed. This is consumed by validate_dynamic.py
    to compute convergence latency for dynamically spawned workers.

New output file columns:
    timestamp_ms, pid, label, mean_burst_ms, threshold_ms

Everything else (valley finder, hysteresis, classified_pids.csv) is
unchanged — drop this in as a direct replacement for classifier.py
when running run_experiment_dynamic.py.
"""

import os
import time
import csv
import collections
import numpy as np
from scipy.ndimage import gaussian_filter1d

# ── Paths ────────────────────────────────────────────────────
DATA_DIR        = os.path.expanduser("~/systemsproj/data")
SIGNAL_FILE     = os.path.join(DATA_DIR, "classify_signal.csv")
CLASSIFIED_FILE = os.path.join(DATA_DIR, "classified_pids.csv")
LABEL_LOG       = os.path.join(DATA_DIR, "dynamic_label_log.csv")  # NEW

# ── Parameters (identical to classifier.py v2) ────────────────
T_FALLBACK      = 30.0
WINDOW          = 10
POLL_S          = 1.0
MIN_OBS_PER_PID = 3
MIN_SAMPLES     = 80
HIST_LO         = 3.0
HIST_HI         = 220.0
N_BINS          = 50
SMOOTH_SIGMA    = 1.5
VALLEY_LO       = 12.0
VALLEY_HI       = 75.0
HYSTERESIS_N    = 3


def find_valley(all_bursts):
    if len(all_bursts) < MIN_SAMPLES:
        return T_FALLBACK
    arr      = np.array(all_bursts, dtype=float)
    hist, edges = np.histogram(arr, bins=N_BINS, range=(HIST_LO, HIST_HI))
    bin_mids = (edges[:-1] + edges[1:]) / 2.0
    smoothed = gaussian_filter1d(hist.astype(float), sigma=SMOOTH_SIGMA)
    mask     = (bin_mids >= VALLEY_LO) & (bin_mids <= VALLEY_HI)
    if not mask.any():
        return T_FALLBACK
    search_smoothed  = smoothed[mask]
    search_mids      = bin_mids[mask]
    valley_idx_local = int(np.argmin(search_smoothed))
    valley_ms        = float(search_mids[valley_idx_local])
    global_idx       = int(np.where(mask)[0][valley_idx_local])
    left_region      = smoothed[:global_idx]
    right_region     = smoothed[global_idx + 1:]
    if len(left_region) == 0 or len(right_region) == 0:
        return T_FALLBACK
    valley_val = float(smoothed[global_idx])
    if (valley_val >= 0.60 * float(left_region.max()) or
            valley_val >= 0.60 * float(right_region.max())):
        return T_FALLBACK
    if not (12.0 <= valley_ms <= 70.0):
        return T_FALLBACK
    return valley_ms


def run_classifier():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Initialise label log
    with open(LABEL_LOG, "w", newline="") as f:
        csv.writer(f).writerow(
            ["timestamp_ms", "pid", "label", "mean_burst_ms", "threshold_ms"]
        )

    history          = collections.defaultdict(
                           lambda: collections.deque(maxlen=WINDOW))
    confirmed_labels = {}
    pending          = {}
    global_bursts    = collections.deque(maxlen=5000)
    seen_rows        = 0
    threshold        = T_FALLBACK

    print(f"[Classifier] ADAPTIVE v2 + label log")
    print(f"[Classifier] Label log : {LABEL_LOG}")
    print(f"[Classifier] Reading   : {SIGNAL_FILE}")
    print(f"[Classifier] Writing   : {CLASSIFIED_FILE}")

    while True:
        # 1. Read new signal rows
        try:
            with open(SIGNAL_FILE) as f:
                rows = list(csv.DictReader(f))
        except Exception:
            time.sleep(POLL_S)
            continue

        for row in rows[seen_rows:]:
            try:
                pid      = int(row["pid"])
                burst_ms = float(row["cpu_burst_ms"])
                history[pid].append(burst_ms)
                global_bursts.append(burst_ms)
            except (KeyError, ValueError):
                pass
        seen_rows = len(rows)

        # 2. Update threshold
        new_threshold = find_valley(list(global_bursts))
        if abs(new_threshold - threshold) > 0.5:
            print(f"[Classifier] Threshold: {threshold:.1f}ms "
                  f"→ {new_threshold:.1f}ms  (n={len(global_bursts)})",
                  flush=True)
        threshold = new_threshold

        # 3. Classify with hysteresis + log label events
        for pid, bursts in history.items():
            if len(bursts) < MIN_OBS_PER_PID:
                continue

            mean_burst    = sum(bursts) / len(bursts)
            raw_label     = "LC" if mean_burst < threshold else "BG"
            current_label = confirmed_labels.get(pid)

            def _log_label(pid, label, mean_burst, threshold):
                with open(LABEL_LOG, "a", newline="") as f:
                    csv.writer(f).writerow([
                        round(time.monotonic() * 1000, 2),
                        pid,
                        label,
                        round(mean_burst, 3),
                        round(threshold, 3),
                    ])

            # First-time assignment
            if current_label is None:
                confirmed_labels[pid] = raw_label
                _log_label(pid, raw_label, mean_burst, threshold)
                print(f"[Classifier] PID {pid} initial label: {raw_label} "
                      f"(mean={mean_burst:.1f}ms)", flush=True)
                continue

            if raw_label == current_label:
                pending.pop(pid, None)
            else:
                cand_label, count = pending.get(pid, (raw_label, 0))
                if cand_label != raw_label:
                    pending[pid] = (raw_label, 1)
                else:
                    count += 1
                    if count >= HYSTERESIS_N:
                        old = confirmed_labels[pid]
                        confirmed_labels[pid] = raw_label
                        pending.pop(pid, None)
                        _log_label(pid, raw_label, mean_burst, threshold)
                        print(f"[Classifier] PID {pid} label: "
                              f"{old} → {raw_label} "
                              f"(mean={mean_burst:.1f}ms, "
                              f"thresh={threshold:.1f}ms)", flush=True)
                    else:
                        pending[pid] = (raw_label, count)

        # 4. Write classified_pids.csv
        lc_pids = [p for p, l in confirmed_labels.items() if l == "LC"]
        bg_pids = [p for p, l in confirmed_labels.items() if l == "BG"]

        with open(CLASSIFIED_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["pid", "label"])
            for pid in lc_pids:
                writer.writerow([pid, "LC"])
            for pid in bg_pids:
                writer.writerow([pid, "BG"])

        mode_str = (f"adaptive({threshold:.1f}ms)"
                    if len(global_bursts) >= MIN_SAMPLES
                    else f"fallback({threshold:.1f}ms)")
        print(f"[Classifier] [{mode_str}]  LC={lc_pids}  BG={bg_pids}",
              flush=True)

        time.sleep(POLL_S)


if __name__ == "__main__":
    run_classifier()