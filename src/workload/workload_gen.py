import time
import random
import os
import csv
import threading
from multiprocessing import Process, Queue

# ── ABSOLUTE path to data/ — edit if your username differs ────────────────
DATA_DIR = os.path.expanduser("~/systemsproj/data")
# ──────────────────────────────────────────────────────────────────────────

LAT_FILE = os.path.join(DATA_DIR, "latency_pids.txt")
BG_FILE  = os.path.join(DATA_DIR, "background_pids.txt")
LAT_LOG  = os.path.join(DATA_DIR, "latency_log.csv")

N_LC    = 3     # latency-critical workers
N_BG    = 1     # background workers
LC_RATE = 20    # base requests/sec


def _write_pid(filepath, pid):
    with open(filepath, "a") as f:
        f.write(str(pid) + "\n")


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


def latency_task(task_queue, data_dir):
    """
    Latency-critical worker.
    Receives data_dir as argument — no __file__ path magic needed.
    """
    pid      = os.getpid()
    lat_file = os.path.join(data_dir, "latency_pids.txt")
    lat_log  = os.path.join(data_dir, "latency_log.csv")

    # Register PID so scheduler can find and prioritise this process
    _write_pid(lat_file, pid)
    print(f"[LC] PID {pid} registered", flush=True)

    while True:
        try:
            enqueue_time = task_queue.get(timeout=1.0)
        except Exception:
            continue

        dequeue_time     = time.monotonic()
        scheduling_delay = (dequeue_time - enqueue_time) * 1000.0

        t0           = time.monotonic()
        _            = sum(i * i for i in range(100_000))
        service_time = (time.monotonic() - t0) * 1000.0

        total_latency = scheduling_delay + service_time

        with open(lat_log, "a", newline="") as f:
            csv.writer(f).writerow([
                round(time.monotonic() * 1000, 2),
                pid,
                round(scheduling_delay, 3),
                round(service_time,     3),
                round(total_latency,    3),
            ])


def background_task(data_dir):
    """CPU-bound background worker."""
    pid     = os.getpid()
    bg_file = os.path.join(data_dir, "background_pids.txt")
    _write_pid(bg_file, pid)
    print(f"[BG] PID {pid} registered", flush=True)
    while True:
        for _ in range(2_000_000):
            pass
        time.sleep(0.05)


def start_workload(data_dir=None):
    if data_dir is None:
        data_dir = DATA_DIR

    os.makedirs(data_dir, exist_ok=True)

    lat_file = os.path.join(data_dir, "latency_pids.txt")
    bg_file  = os.path.join(data_dir, "background_pids.txt")
    lat_log  = os.path.join(data_dir, "latency_log.csv")

    # Clear PID files
    open(lat_file, "w").close()
    open(bg_file,  "w").close()

    # Write CSV header ONCE before any child process starts
    # Avoids race where multiple LC workers all try to write header
    with open(lat_log, "w", newline="") as f:
        csv.writer(f).writerow([
            "timestamp_ms", "pid",
            "scheduling_delay_ms", "service_time_ms", "total_latency_ms"
        ])

    print(f"[Workload] data_dir  = {data_dir}", flush=True)
    print(f"[Workload] latency_log = {lat_log}", flush=True)

    task_queue = Queue(maxsize=200)

    threading.Thread(
        target=request_generator,
        args=(task_queue, LC_RATE),
        daemon=True
    ).start()

    processes = []

    for _ in range(N_LC):
        p = Process(target=latency_task, args=(task_queue, data_dir))
        p.start()
        processes.append(p)

    for _ in range(N_BG):
        p = Process(target=background_task, args=(data_dir,))
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