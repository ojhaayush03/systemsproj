"""
classified_scheduler.py

Identical logic to static_priority_scheduler.py EXCEPT:
  - Reads PID labels from classified_pids.csv (written by classifier.py)
    instead of hardcoded latency_pids.txt / background_pids.txt.
  - This is the "classifier-driven" mode used to validate the classifier.

Run alongside classifier.py (not instead of it):
    Terminal 1: python3 workload_gen.py
    Terminal 2: python3 classifier.py
    Terminal 3: python3 classified_scheduler.py
Or let run_experiment_classified.py orchestrate everything.
"""

import os, time, csv
from datetime import datetime

DATA_DIR        = os.path.expanduser("~/systemsproj/data")
CLASSIFIED_FILE = os.path.join(DATA_DIR, "classified_pids.csv")
DECISION_LOG    = os.path.join(DATA_DIR, "decisions.csv")

NICE_LC = int(os.environ.get("NICE_LC", -5))
NICE_BG = int(os.environ.get("NICE_BG", +15))


def read_classified_pids():
    """Return (lc_pids, bg_pids) from classified_pids.csv."""
    lc_pids, bg_pids = [], []
    try:
        with open(CLASSIFIED_FILE) as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid   = int(row["pid"])
                label = row["label"].strip()
                if label == "LC":
                    lc_pids.append(pid)
                elif label == "BG":
                    bg_pids.append(pid)
    except Exception:
        pass
    return lc_pids, bg_pids


def set_nice(pid, value):
    try:
        os.setpriority(os.PRIO_PROCESS, pid, value)
        return True
    except Exception:
        return False


def log(pid, ptype, nice, success):
    with open(DECISION_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().strftime("%H:%M:%S.%f"),
            pid, ptype, nice, int(success)
        ])


def init_log():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DECISION_LOG, "w", newline="") as f:
        csv.writer(f).writerow(["time", "pid", "type", "nice", "success"])


def run_scheduler():
    init_log()
    print("[ClassifiedScheduler] Waiting for classifier to populate classified_pids.csv ...")
    print(f"[ClassifiedScheduler] NICE_LC={NICE_LC}  NICE_BG={NICE_BG}")

    # Wait until classifier has made at least one decision
    for _ in range(30):
        lc, bg = read_classified_pids()
        if lc or bg:
            break
        time.sleep(1)
    else:
        print("[ClassifiedScheduler] ERROR: classifier never wrote any PIDs.")
        return

    known_priorities = {}   # pid → last nice value applied

    while True:
        lc_pids, bg_pids = read_classified_pids()

        for pid in lc_pids:
            if known_priorities.get(pid) != NICE_LC:
                ok = set_nice(pid, NICE_LC)
                log(pid, "LC", NICE_LC, ok)
                known_priorities[pid] = NICE_LC
                print(f"  [Sched] LC pid {pid} → nice {NICE_LC}  {'OK' if ok else 'FAIL'}")

        for pid in bg_pids:
            if known_priorities.get(pid) != NICE_BG:
                ok = set_nice(pid, NICE_BG)
                log(pid, "BG", NICE_BG, ok)
                known_priorities[pid] = NICE_BG
                print(f"  [Sched] BG pid {pid} → nice {NICE_BG}  {'OK' if ok else 'FAIL'}")

        time.sleep(2)   # re-check every 2s — classifier updates every 1s


if __name__ == "__main__":
    run_scheduler()