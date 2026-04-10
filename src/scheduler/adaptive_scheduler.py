"""
static_priority_scheduler.py

Insight: service time variance dominates tail latency, not queue depth.
The BG worker steals CPU during LC service windows (13ms compute tasks).
Fix: permanently suppress BG, permanently boost LC.
No feedback loop needed — the signal doesn't change fast enough to matter.
"""

import os
import time
import csv
from datetime import datetime

BASE_DIR     = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
DATA_DIR     = os.path.join(BASE_DIR, "data")
LAT_FILE     = os.path.join(DATA_DIR, "latency_pids.txt")
BG_FILE      = os.path.join(DATA_DIR, "background_pids.txt")
DECISION_LOG = os.path.join(DATA_DIR, "decisions.csv")

NICE_LC = -5    # boost LC workers
NICE_BG = +15   # maximally suppress BG — still scheduled, never starved


def read_pids(filepath):
    try:
        with open(filepath) as f:
            return [int(x.strip()) for x in f if x.strip().isdigit()]
    except Exception:
        return []


def set_nice(pid, value):
    try:
        os.setpriority(os.PRIO_PROCESS, pid, value)
        return True
    except Exception:
        return False


def init_log():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DECISION_LOG, "w", newline="") as f:
        csv.writer(f).writerow(["time", "pid", "type", "nice", "success"])


def log(pid, ptype, nice, success):
    with open(DECISION_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().strftime("%H:%M:%S.%f"),
            pid, ptype, nice, int(success)
        ])


def apply_priorities():
    """Set priorities once and verify they stuck."""
    lc_pids = read_pids(LAT_FILE)
    bg_pids = read_pids(BG_FILE)

    if not lc_pids and not bg_pids:
        return False

    print(f"[Scheduler] LC pids: {lc_pids}")
    print(f"[Scheduler] BG pids: {bg_pids}")

    for pid in lc_pids:
        ok = set_nice(pid, NICE_LC)
        log(pid, "LC", NICE_LC, ok)
        print(f"  LC pid {pid} → nice {NICE_LC}  {'OK' if ok else 'FAILED'}")

    for pid in bg_pids:
        ok = set_nice(pid, NICE_BG)
        log(pid, "BG", NICE_BG, ok)
        print(f"  BG pid {pid} → nice {NICE_BG}  {'OK' if ok else 'FAILED'}")

    return True


def verify_priorities():
    """Read back nice values from /proc to confirm they stuck."""
    for filepath, label in [(LAT_FILE, "LC"), (BG_FILE, "BG")]:
        for pid in read_pids(filepath):
            try:
                actual = os.getpriority(os.PRIO_PROCESS, pid)
                print(f"  [Verify] {label} pid {pid} actual nice = {actual}")
            except Exception:
                print(f"  [Verify] {label} pid {pid} — could not read")


def run_scheduler():
    init_log()
    print("[Scheduler] Static priority mode")
    print(f"[Scheduler] Target: LC=nice{NICE_LC}, BG=nice+{NICE_BG}")
    print("[Scheduler] Waiting for PIDs...")

    # Wait until workload has registered its PIDs
    for _ in range(30):
        lc_pids = read_pids(LAT_FILE)
        bg_pids = read_pids(BG_FILE)
        if lc_pids and bg_pids:
            break
        time.sleep(1)
    else:
        print("[Scheduler] ERROR: PIDs never appeared. Check workload.")
        return

    # Apply once
    applied = apply_priorities()
    if not applied:
        print("[Scheduler] ERROR: No PIDs found after waiting.")
        return

    # Verify they stuck
    time.sleep(0.5)
    verify_priorities()

    print("\n[Scheduler] Priorities set. Monitoring for new PIDs every 10s...")

    # Light maintenance loop — only re-apply if PIDs change (e.g. worker crash/restart)
    known_lc = set(read_pids(LAT_FILE))
    known_bg = set(read_pids(BG_FILE))

    while True:
        time.sleep(10)   # 10s poll — negligible overhead
        current_lc = set(read_pids(LAT_FILE))
        current_bg = set(read_pids(BG_FILE))

        new_lc = current_lc - known_lc
        new_bg = current_bg - known_bg

        if new_lc or new_bg:
            print(f"[Scheduler] New PIDs detected — LC:{new_lc} BG:{new_bg}")
            for pid in new_lc:
                ok = set_nice(pid, NICE_LC)
                log(pid, "LC", NICE_LC, ok)
            for pid in new_bg:
                ok = set_nice(pid, NICE_BG)
                log(pid, "BG", NICE_BG, ok)
            known_lc = current_lc
            known_bg = current_bg


if __name__ == "__main__":
    run_scheduler()