"""
run_experiment.py
Runs multiple trials of:
Run1 (CFS) + Run2 (PTLS)
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

# 🔥 UPDATED
DURATION  = 300   # seconds (was 180)
TRIALS    = 4

SUMMARY_FILE = os.path.join(ROOT, "experiment_summary.txt")


# ─────────────────────────────────────────────────────────────
def nuclear_cleanup():
    scripts = ["workload_gen.py", "profiler.py", 
               "adaptive_scheduler.py", "queue_aware_scheduler.py"]
    for script in scripts:
        subprocess.run(["pkill", "-f", script], capture_output=True)

    time.sleep(2)

    result = subprocess.run(
        ["pgrep", "-f", "workload_gen.py"],
        capture_output=True, text=True
    )

    if result.stdout.strip():
        print(f"[WARN] Still alive: {result.stdout.strip()}")
        subprocess.run(["pkill", "-9", "-f", "workload_gen.py"])
        time.sleep(1)

    print("[Setup] Clean slate confirmed.")


# ─────────────────────────────────────────────────────────────
def clear_data():
    os.makedirs(DATA, exist_ok=True)

    for f in ["latency_pids.txt", "background_pids.txt", "decisions.csv"]:
        open(os.path.join(DATA, f), "w").close()

    open(os.path.join(DATA, "latency_log.csv"), "w").close()
    print("[Setup] data files cleared")


# ─────────────────────────────────────────────────────────────
def save_run(label, trial):
    for src_name, dst_name in [
        ("latency_log.csv", f"trial{trial}_{label}_latency.csv"),
        ("metrics.csv",     f"trial{trial}_{label}_metrics.csv"),
        ("decisions.csv",   f"trial{trial}_{label}_decisions.csv"),
    ]:
        src = os.path.join(DATA, src_name)
        dst = os.path.join(DATA, dst_name)

        if os.path.exists(src) and os.path.getsize(src) > 10:
            shutil.copy(src, dst)
            print(f"[Save] {dst_name} ({os.path.getsize(dst):,} bytes)")
        else:
            print(f"[WARN] {src_name} empty or missing")


# ─────────────────────────────────────────────────────────────
def wait_with_progress(seconds, label):
    start = time.time()
    last_print = -1

    while True:
        elapsed = int(time.time() - start)
        if elapsed >= seconds:
            break

        if elapsed % 15 == 0 and elapsed != last_print:
            print(f"[{label}] {elapsed}s / {seconds}s")
            last_print = elapsed

        time.sleep(1)


# ─────────────────────────────────────────────────────────────
def kill_all(procs):
    for p in procs:
        try: p.terminate()
        except: pass

    time.sleep(1)

    for p in procs:
        try: p.kill()
        except: pass


# ─────────────────────────────────────────────────────────────
def check_scripts():
    missing = [s for s in [WORKLOAD, PROFILER, SCHEDULER] if not os.path.exists(s)]
    if missing:
        print("[ERROR] Missing files:")
        for m in missing:
            print(m)
        sys.exit(1)


# ─────────────────────────────────────────────────────────────
def run1_cfs(trial):
    print(f"\n--- RUN 1 (CFS) | Trial {trial} ---")

    clear_data()

    procs = []
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(3)

    procs.append(subprocess.Popen([PYTHON, PROFILER]))

    wait_with_progress(DURATION, f"CFS-T{trial}")
    kill_all(procs)

    save_run("run1", trial)


# ─────────────────────────────────────────────────────────────
def run2_ptls(trial):
    print(f"\n--- RUN 2 (PTLS) | Trial {trial} ---")

    clear_data()

    procs = []
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(4)

    procs.append(subprocess.Popen([PYTHON, PROFILER]))
    time.sleep(1)

    procs.append(subprocess.Popen([PYTHON, SCHEDULER]))

    wait_with_progress(DURATION, f"PTLS-T{trial}")
    kill_all(procs)

    save_run("run2", trial)


# ─────────────────────────────────────────────────────────────
def append_summary(trial):
    with open(SUMMARY_FILE, "a") as f:
        f.write(f"\n=== Trial {trial} ===\n")
        f.write(f"CFS file: trial{trial}_run1_latency.csv\n")
        f.write(f"PTLS file: trial{trial}_run2_latency.csv\n")


# ─────────────────────────────────────────────────────────────
def analyse(trial):
    if not os.path.exists(METRICS):
        return

    print(f"\n--- ANALYSIS | Trial {trial} ---")

    for label, fname in [
        ("CFS", f"trial{trial}_run1_latency.csv"),
        ("PTLS", f"trial{trial}_run2_latency.csv")
    ]:
        csv_path = os.path.join(DATA, fname)

        if not os.path.exists(csv_path):
            continue

        shutil.copy(csv_path, os.path.join(DATA, "latency_log.csv"))
        print(f"\n[{label}]")
        subprocess.run([PYTHON, METRICS])


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    nuclear_cleanup()

    print("\n==============================")
    print(" MULTI-TRIAL EXPERIMENT RUN ")
    print("==============================")

    check_scripts()

    open(SUMMARY_FILE, "w").close()

    try:
        for trial in range(1, TRIALS + 1):

            print("\n" + "#"*60)
            print(f"STARTING TRIAL {trial}/{TRIALS}")
            print("#"*60)

            run1_cfs(trial)

            print("\nCooling down 10s...\n")
            time.sleep(10)

            run2_ptls(trial)

            analyse(trial)
            append_summary(trial)

        print(f"\nALL DONE. Summary saved at:\n{SUMMARY_FILE}")

    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(1)