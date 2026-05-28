"""
classifier.py  — runtime task classifier with ADAPTIVE threshold (v2)

Key improvements over v1:
  1. Histogram is Gaussian-smoothed before valley search → eliminates
     the argmin jumping to a noise bin (17ms → 56ms oscillation seen in v1).
  2. Per-PID hysteresis: a PID must cross the threshold for HYSTERESIS_N
     consecutive polls before its label changes → kills BG flickering.
  3. Valley candidate is validated: it must sit between two local maxima
     (genuine peaks), not just be the global minimum of a flat histogram.

Algorithm:
  1. Accumulate all burst observations into a global ring buffer (maxlen 5000).
  2. Every POLL_S seconds, build a histogram over [HIST_LO, HIST_HI] ms.
  3. Apply Gaussian smoothing (sigma=1.5 bins).
  4. Find the smoothed-minimum bin inside [VALLEY_LO, VALLEY_HI] ms.
  5. Validate: there must be a local max on each side of the valley.
  6. If valid, use valley midpoint as threshold; else fall back to T_FALLBACK.
  7. Apply per-PID hysteresis before writing classified_pids.csv.
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

# ── Fixed parameters ─────────────────────────────────────────
T_FALLBACK      = 30.0   # ms — used before MIN_SAMPLES or if valley invalid
WINDOW          = 10     # rolling mean window per PID
POLL_S          = 1.0    # poll interval
MIN_OBS_PER_PID = 3      # minimum obs before classifying a PID
MIN_SAMPLES     = 80     # minimum global obs before adaptive mode

# ── Histogram parameters ─────────────────────────────────────
HIST_LO         = 3.0
HIST_HI         = 220.0
N_BINS          = 50
SMOOTH_SIGMA    = 1.5    # Gaussian smoothing in bin units

# Valley must sit in this band (ms)
VALLEY_LO       = 12.0
VALLEY_HI       = 75.0

# ── Hysteresis ───────────────────────────────────────────────
HYSTERESIS_N    = 3      # polls a PID must consistently read new label
                         # before the label is actually changed


# ── Valley finder (smoothed) ──────────────────────────────────
def find_valley(all_bursts: list) -> float:
    """
    Returns the adaptive threshold (valley midpoint) or T_FALLBACK.
    """
    if len(all_bursts) < MIN_SAMPLES:
        return T_FALLBACK

    arr = np.array(all_bursts, dtype=float)
    hist, edges = np.histogram(arr, bins=N_BINS, range=(HIST_LO, HIST_HI))
    bin_mids    = (edges[:-1] + edges[1:]) / 2.0

    # Smooth to kill single-bin noise
    smoothed = gaussian_filter1d(hist.astype(float), sigma=SMOOTH_SIGMA)

    # Restrict valley search to band
    mask = (bin_mids >= VALLEY_LO) & (bin_mids <= VALLEY_HI)
    if not mask.any():
        return T_FALLBACK

    search_smoothed = smoothed[mask]
    search_mids     = bin_mids[mask]
    valley_idx_local = int(np.argmin(search_smoothed))
    valley_ms        = float(search_mids[valley_idx_local])

    # Map back to global index for peak validation
    global_idx = int(np.where(mask)[0][valley_idx_local])

    # Validate: there must be a local max to the LEFT (LC peak)
    # and to the RIGHT (BG peak) of the valley in the full smoothed array.
    left_region  = smoothed[:global_idx]
    right_region = smoothed[global_idx + 1:]

    if len(left_region) == 0 or len(right_region) == 0:
        return T_FALLBACK

    left_max  = float(left_region.max())
    right_max = float(right_region.max())
    valley_val = float(smoothed[global_idx])

    # The valley must be meaningfully lower than both surrounding peaks.
    # Require valley < 60% of both peak heights.
    if valley_val >= 0.60 * left_max or valley_val >= 0.60 * right_max:
        return T_FALLBACK

    # Final sanity: threshold must be in a reasonable range
    if not (12.0 <= valley_ms <= 70.0):
        return T_FALLBACK

    return valley_ms


# ── Main loop ─────────────────────────────────────────────────
def run_classifier():
    os.makedirs(DATA_DIR, exist_ok=True)

    # pid → deque of recent cpu_burst_ms
    history: dict = collections.defaultdict(
        lambda: collections.deque(maxlen=WINDOW)
    )

    # pid → current confirmed label
    confirmed_labels: dict = {}

    # pid → (candidate_label, consecutive_count)
    pending: dict = {}

    # Global ring buffer for histogram
    global_bursts: collections.deque = collections.deque(maxlen=5000)

    seen_rows = 0
    threshold = T_FALLBACK

    print(f"[Classifier] ADAPTIVE v2  fallback={T_FALLBACK}ms  "
          f"smooth_sigma={SMOOTH_SIGMA}  hysteresis={HYSTERESIS_N} polls")
    print(f"[Classifier] Valley band: [{VALLEY_LO}, {VALLEY_HI}] ms  "
          f"adaptive after {MIN_SAMPLES} obs")
    print(f"[Classifier] Reading : {SIGNAL_FILE}")
    print(f"[Classifier] Writing : {CLASSIFIED_FILE}")

    while True:
        # ── 1. Read new rows ───────────────────────────────────
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

        # ── 2. Update threshold ────────────────────────────────
        new_threshold = find_valley(list(global_bursts))
        if abs(new_threshold - threshold) > 0.5:
            print(f"[Classifier] Threshold: {threshold:.1f}ms "
                  f"→ {new_threshold:.1f}ms  (n={len(global_bursts)})",
                  flush=True)
        threshold = new_threshold

        # ── 3. Classify with hysteresis ────────────────────────
        for pid, bursts in history.items():
            if len(bursts) < MIN_OBS_PER_PID:
                continue

            mean_burst    = sum(bursts) / len(bursts)
            raw_label     = "LC" if mean_burst < threshold else "BG"
            current_label = confirmed_labels.get(pid)

            if raw_label == current_label:
                # Stable — reset any pending counter
                pending.pop(pid, None)
            else:
                # Potential label change — count consecutive polls
                cand_label, count = pending.get(pid, (raw_label, 0))
                if cand_label != raw_label:
                    # Candidate itself changed — restart counter
                    pending[pid] = (raw_label, 1)
                else:
                    count += 1
                    if count >= HYSTERESIS_N:
                        # Commit the label change
                        old = confirmed_labels.get(pid, "UNSET")
                        confirmed_labels[pid] = raw_label
                        pending.pop(pid, None)
                        print(f"[Classifier] PID {pid} label: "
                              f"{old} → {raw_label} "
                              f"(mean={mean_burst:.1f}ms, "
                              f"thresh={threshold:.1f}ms)", flush=True)
                    else:
                        pending[pid] = (raw_label, count)

            # First-time assignment (no hysteresis needed for initial label)
            if pid not in confirmed_labels and len(bursts) >= MIN_OBS_PER_PID:
                confirmed_labels[pid] = raw_label

        # ── 4. Write classified_pids.csv ───────────────────────
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