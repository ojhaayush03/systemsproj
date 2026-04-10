"""
run_experiment.py  —  place at ~/systemsproj/run_experiment.py
Runs Run1 (CFS, no scheduler) then Run2 (PTLS) for 3 min each.
"""

import os, sys, time, shutil, subprocess

ROOT      = os.path.dirname(os.path.abspath(__file__))
DATA      = os.path.join(ROOT, "data")
SRC       = os.path.join(ROOT, "src")
WORKLOAD  = os.path.join(SRC, "workload",  "workload_gen.py")
PROFILER  = os.path.join(SRC, "profiler",  "profiler.py")
SCHEDULER = os.path.join(SRC, "scheduler", "adaptive_scheduler.py")
METRICS   = os.path.join(SRC, "analysis",  "latency_metrics.py")
PYTHON    = sys.executable
DURATION  = 180   # seconds per run


def nuclear_cleanup():
    """Kill ALL leftover processes from previous runs before starting."""
    scripts = ["workload_gen.py", "profiler.py", 
               "adaptive_scheduler.py", "queue_aware_scheduler.py"]
    for script in scripts:
        subprocess.run(["pkill", "-f", script], 
                      capture_output=True)  # suppress output if nothing found
    time.sleep(2)
    # Verify
    result = subprocess.run(
        ["pgrep", "-f", "workload_gen.py"], 
        capture_output=True, text=True
    )
    if result.stdout.strip():
        print(f"[WARN] Still alive: {result.stdout.strip()}")
        subprocess.run(["pkill", "-9", "-f", "workload_gen.py"])
        time.sleep(1)
    print("[Setup] Clean slate confirmed.")

def clear_data():
    os.makedirs(DATA, exist_ok=True)
    # Only clear PID files and decisions — workload_gen writes its own header
    for f in ["latency_pids.txt", "background_pids.txt", "decisions.csv"]:
        open(os.path.join(DATA, f), "w").close()
    # Wipe latency_log so workload_gen starts fresh with its header
    open(os.path.join(DATA, "latency_log.csv"), "w").close()
    print("[Setup] data files cleared")


def save_run(label):
    for src_name, dst_name in [
        ("latency_log.csv", f"{label}_latency.csv"),
        ("metrics.csv",     f"{label}_metrics.csv"),
        ("decisions.csv",   f"{label}_decisions.csv"),
    ]:
        src = os.path.join(DATA, src_name)
        dst = os.path.join(DATA, dst_name)
        if os.path.exists(src) and os.path.getsize(src) > 10:
            shutil.copy(src, dst)
            print(f"[Save] {dst_name}  ({os.path.getsize(dst):,} bytes)")
        else:
            print(f"[WARN] {src_name} is empty or missing — check workload")


def wait_with_progress(seconds, label):
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed >= seconds:
            break
        if int(elapsed) % 15 == 0 and elapsed > 0:
            print(f"  [{label}] {int(elapsed):3d}s elapsed, "
                  f"{int(seconds-elapsed):3d}s remaining...")
        time.sleep(1)


def kill_all(procs):
    for p in procs:
        try: p.terminate()
        except: pass
    time.sleep(1)
    for p in procs:
        try: p.kill()
        except: pass


def check_scripts():
    missing = [s for s in [WORKLOAD, PROFILER, SCHEDULER] if not os.path.exists(s)]
    if missing:
        print("[ERROR] Missing files:")
        for m in missing: print(f"  {m}")
        sys.exit(1)


# ── Run 1: CFS baseline ───────────────────────────────────────────────────
def run1_cfs():
    print("\n" + "─"*52)
    print(f"  RUN 1 — CFS baseline (no scheduler)  [{DURATION}s]")
    print("─"*52)
    clear_data()

    procs = []
    # Start workload — it will write header + spawn LC/BG processes
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(3)    # wait for PIDs to register and header to be written

    # Verify latency_log.csv has data started
    lat_log = os.path.join(DATA, "latency_log.csv")
    size = os.path.getsize(lat_log) if os.path.exists(lat_log) else 0
    print(f"[Check] latency_log.csv size after 3s: {size} bytes")
    if size == 0:
        print("[WARN] latency_log.csv still empty after 3s — path problem?")
        print(f"       Expected: {lat_log}")

    procs.append(subprocess.Popen([PYTHON, PROFILER]))
    print(f"  workload PID={procs[0].pid}  profiler PID={procs[1].pid}\n")

    wait_with_progress(DURATION, "Run1-CFS")
    kill_all(procs)
    time.sleep(1)

    # Final check
    size = os.path.getsize(lat_log) if os.path.exists(lat_log) else 0
    print(f"[Check] latency_log.csv final size: {size} bytes")
    save_run("run1")
    print("[Run 1] Complete.")


# ── Run 2: PTLS adaptive scheduler ────────────────────────────────────────
def run2_ptls():
    print("\n" + "─"*52)
    print(f"  RUN 2 — PTLS scheduler  [{DURATION}s]")
    print("─"*52)
    clear_data()

    procs = []
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(4)    # longer wait — PIDs must be in latency_pids.txt before scheduler reads

    lat_log = os.path.join(DATA, "latency_log.csv")
    size = os.path.getsize(lat_log) if os.path.exists(lat_log) else 0
    print(f"[Check] latency_log.csv size after 4s: {size} bytes")

    procs.append(subprocess.Popen([PYTHON, PROFILER]))
    time.sleep(1)
    procs.append(subprocess.Popen([PYTHON, SCHEDULER]))
    print(f"  workload={procs[0].pid}  profiler={procs[1].pid}"
          f"  scheduler={procs[2].pid}\n")

    wait_with_progress(DURATION, "Run2-PTLS")
    kill_all(procs)
    time.sleep(1)

    size = os.path.getsize(lat_log) if os.path.exists(lat_log) else 0
    print(f"[Check] latency_log.csv final size: {size} bytes")
    save_run("run2")
    print("[Run 2] Complete.")


# ── Analysis ──────────────────────────────────────────────────────────────
def analyse():
    if not os.path.exists(METRICS):
        return
    print("\n" + "="*52 + "\n  RESULTS\n" + "="*52)
    for label, fname in [("Run 1 — CFS", "run1_latency.csv"),
                          ("Run 2 — PTLS", "run2_latency.csv")]:
        csv_path = os.path.join(DATA, fname)
        if not os.path.exists(csv_path) or os.path.getsize(csv_path) < 10:
            print(f"\n  [{label}] no data")
            continue
        shutil.copy(csv_path, os.path.join(DATA, "latency_log.csv"))
        print(f"\n  ── {label} ──")
        subprocess.run([PYTHON, METRICS])


# ── Entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    nuclear_cleanup()
    print("\n" + "="*52)
    print("  PTLS Experiment Runner  (2 × 3 min ≈ 7 min)")
    print("="*52)
    check_scripts()
    try:
        run1_cfs()
        print("\n  Cooling down 10s...\n")
        time.sleep(10)
        run2_ptls()
        analyse()
    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(1)
    print(f"\n[Done] Results in {DATA}/")