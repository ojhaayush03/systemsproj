"""
workload_gen.py  (classifier-aware version)

Changes from original:
  1. latency_task() wraps its compute block with a timer and emits
     (pid, cpu_burst_ms, ground_truth="LC") to classify_queue.
  2. background_task() does the same with ground_truth="BG".
  3. A new classify_logger thread reads classify_queue and writes
     classify_signal.csv — used by classifier.py and for validation.

Everything else (request_generator, start_workload) is unchanged.
"""

import time
import random
import os
import csv
import threading
from multiprocessing import Process, Queue, Manager

DATA_DIR = os.path.expanduser("~/systemsproj/data")

LAT_FILE  = os.path.join(DATA_DIR, "latency_pids.txt")
BG_FILE   = os.path.join(DATA_DIR, "background_pids.txt")
LAT_LOG   = os.path.join(DATA_DIR, "latency_log.csv")
SIG_LOG   = os.path.join(DATA_DIR, "classify_signal.csv")   # NEW

N_LC    = 3
N_BG    = 1
LC_RATE = 20


def _write_pid(filepath, pid):
    with open(filepath, "a") as f:
        f.write(str(pid) + "\n")


# ── NEW: background logger thread ─────────────────────────────
def classify_logger(classify_queue, data_dir):
    """
    Daemon thread (in main process).
    Reads (pid, cpu_burst_ms, ground_truth) from classify_queue
    and appends to classify_signal.csv.
    classifier.py reads this file to make decisions.
    """
    sig_log = os.path.join(data_dir, "classify_signal.csv")
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
                ground_truth,           # "LC" or "BG" — ground truth for validation
            ])


# ─────────────────────────────────────────────────────────────
def request_generator(task_queue, rate_per_sec):
    """Daemon thread: Poisson arrivals with random 3x burst phases."""
    burst_active = False
    burst_end    = 0.0
    while True:
        now = time.monotonic()
        if not burst_active and random.random() < 0.02:
            burst_active = True
            burst_end    = now + random.uniform(1.0, 2.5)
        if burst_active and now > burst_end:
            burst_active = False
        effective_rate = rate_per_sec * 3 if burst_active else rate_per_sec
        time.sleep(random.expovariate(effective_rate))
        try:
            task_queue.put_nowait(time.monotonic())
        except Exception:
            pass


def latency_task(task_queue, data_dir, classify_queue):
    """
    Latency-critical worker.
    Added: timer around compute block → emit to classify_queue.
    """
    pid      = os.getpid()
    lat_file = os.path.join(data_dir, "latency_pids.txt")
    lat_log  = os.path.join(data_dir, "latency_log.csv")

    _write_pid(lat_file, pid)
    print(f"[LC] PID {pid} registered", flush=True)

    while True:
        try:
            enqueue_time = task_queue.get(timeout=1.0)
        except Exception:
            continue

        dequeue_time     = time.monotonic()
        scheduling_delay = (dequeue_time - enqueue_time) * 1000.0

        # ── CHANGED: wrap compute with timer ──────────────────
        t0           = time.monotonic()
        _            = sum(i * i for i in range(100_000))
        cpu_burst_ms = (time.monotonic() - t0) * 1000.0
        service_time = cpu_burst_ms
        # ─────────────────────────────────────────────────────

        total_latency = scheduling_delay + service_time

        # Emit signal for classifier (ground truth = "LC")
        try:
            classify_queue.put_nowait((pid, cpu_burst_ms, "LC"))
        except Exception:
            pass

        with open(lat_log, "a", newline="") as f:
            csv.writer(f).writerow([
                round(time.monotonic() * 1000, 2),
                pid,
                round(scheduling_delay, 3),
                round(service_time,     3),
                round(total_latency,    3),
            ])


def background_task(data_dir, classify_queue):
    """
    CPU-bound background worker.
    Added: timer around compute block → emit to classify_queue.
    """
    pid     = os.getpid()
    bg_file = os.path.join(data_dir, "background_pids.txt")
    _write_pid(bg_file, pid)
    print(f"[BG] PID {pid} registered", flush=True)

    while True:
        # ── CHANGED: wrap compute with timer ──────────────────
        t0 = time.monotonic()
        for _ in range(2_000_000):
            pass
        cpu_burst_ms = (time.monotonic() - t0) * 1000.0
        # ─────────────────────────────────────────────────────

        # Emit signal for classifier (ground truth = "BG")
        try:
            classify_queue.put_nowait((pid, cpu_burst_ms, "BG"))
        except Exception:
            pass

        time.sleep(0.05)


def start_workload(data_dir=None):
    if data_dir is None:
        data_dir = DATA_DIR

    os.makedirs(data_dir, exist_ok=True)

    lat_file = os.path.join(data_dir, "latency_pids.txt")
    bg_file  = os.path.join(data_dir, "background_pids.txt")
    lat_log  = os.path.join(data_dir, "latency_log.csv")
    sig_log  = os.path.join(data_dir, "classify_signal.csv")

    open(lat_file, "w").close()
    open(bg_file,  "w").close()

    with open(lat_log, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp_ms", "pid",
            "scheduling_delay_ms", "service_time_ms", "total_latency_ms"
        ])

    # Write classify_signal.csv header
    with open(sig_log, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp_ms", "pid", "cpu_burst_ms", "ground_truth"
        ])

    print(f"[Workload] data_dir    = {data_dir}", flush=True)
    print(f"[Workload] latency_log = {lat_log}", flush=True)
    print(f"[Workload] signal_log  = {sig_log}", flush=True)

    task_queue     = Queue(maxsize=200)
    classify_queue = Queue(maxsize=2000)   # NEW shared queue for classifier signals

    # Request generator thread
    threading.Thread(
        target=request_generator,
        args=(task_queue, LC_RATE),
        daemon=True
    ).start()

    # Classify logger thread (in main process — reads classify_queue)
    threading.Thread(
        target=classify_logger,
        args=(classify_queue, data_dir),
        daemon=True
    ).start()

    processes = []

    for _ in range(N_LC):
        p = Process(target=latency_task, args=(task_queue, data_dir, classify_queue))
        p.start()
        processes.append(p)

    for _ in range(N_BG):
        p = Process(target=background_task, args=(data_dir, classify_queue))
        p.start()
        processes.append(p)

    print(f"[Workload] {N_LC} LC + {N_BG} BG started @ {LC_RATE} req/s", flush=True)
    return processes


if __name__ == "__main__":
    procs = start_workload()
    try:
        for p in procs:
            p.join()
    except KeyboardInterrupt:
        print("\n[Workload] stopping...")
        for p in procs:
            p.terminate()