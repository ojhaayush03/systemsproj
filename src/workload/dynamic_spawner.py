"""
dynamic_spawner.py

Spawns one additional BG worker after a configurable delay (default 150s).
The new worker registers its PID in data/background_pids.txt and emits
burst signals to classify_signal.csv exactly like the original BG worker.

This tests the classifier's cold-start convergence:
  - New PID has 0 observations at spawn time
  - Classifier must accumulate MIN_OBS_PER_PID before labeling
  - We measure seconds from first observation to correct BG label

Called by run_experiment_dynamic.py as a subprocess.
Can also be run standalone for debugging.

Usage:
    python3 dynamic_spawner.py [--delay 150] [--data-dir ~/systemsproj/data]
"""

import os
import sys
import time
import csv
import argparse
from multiprocessing import Process, Queue

DATA_DIR = os.path.expanduser("~/systemsproj/data")


def _write_pid(filepath, pid):
    with open(filepath, "a") as f:
        f.write(str(pid) + "\n")


def late_background_task(data_dir, classify_queue):
    """
    Identical compute pattern to the original background_task().
    Registers PID in background_pids.txt so static scheduler also
    picks it up if running alongside.
    """
    pid     = os.getpid()
    bg_file = os.path.join(data_dir, "background_pids.txt")
    _write_pid(bg_file, pid)
    print(f"[DynSpawner] Late BG worker PID {pid} registered at "
          f"t={time.monotonic():.1f}s", flush=True)

    while True:
        t0 = time.monotonic()
        for _ in range(2_000_000):
            pass
        cpu_burst_ms = (time.monotonic() - t0) * 1000.0

        try:
            classify_queue.put_nowait((pid, cpu_burst_ms, "BG"))
        except Exception:
            pass

        time.sleep(0.05)


def burst_writer(classify_queue, data_dir):
    """
    Reads (pid, cpu_burst_ms, ground_truth) from classify_queue
    and appends directly to classify_signal.csv.
    Runs as a daemon thread in the spawner process.
    """
    import threading

    sig_log = os.path.join(data_dir, "classify_signal.csv")

    def _loop():
        while True:
            try:
                item = classify_queue.get(timeout=2.0)
            except Exception:
                continue
            pid, cpu_burst_ms, ground_truth = item
            with open(sig_log, "a", newline="") as f:
                csv.writer(f).writerow([
                    round(time.monotonic() * 1000, 2),
                    pid,
                    round(cpu_burst_ms, 4),
                    ground_truth,
                ])

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t


def run(delay: float, data_dir: str):
    """
    Sleep for `delay` seconds, then spawn one late BG worker.
    The spawner process itself stays alive (keeping the writer thread
    running) until killed by the orchestrator.
    """
    print(f"[DynSpawner] Will spawn late BG worker in {delay}s ...",
          flush=True)
    time.sleep(delay)
    print(f"[DynSpawner] Spawning late BG worker now (t+{delay}s)",
          flush=True)

    classify_queue = Queue(maxsize=2000)

    # Start the burst writer thread in THIS process
    burst_writer(classify_queue, data_dir)

    # Spawn the actual worker
    p = Process(
        target=late_background_task,
        args=(data_dir, classify_queue)
    )
    p.start()

    print(f"[DynSpawner] Late BG worker running as PID {p.pid}", flush=True)

    # Keep this process alive so the writer thread keeps running
    try:
        p.join()
    except KeyboardInterrupt:
        p.terminate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay",    type=float, default=150.0,
                        help="Seconds to wait before spawning (default 150)")
    parser.add_argument("--data-dir", type=str,
                        default=DATA_DIR,
                        help="Path to data directory")
    args = parser.parse_args()
    run(args.delay, args.data_dir)