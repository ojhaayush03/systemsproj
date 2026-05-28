"""
run_experiment_dynamic.py

Runs the dynamic spawn robustness experiment:

  - Standard classified run (3 LC + 1 BG from t=0)
  - At t=SPAWN_DELAY (default 150s), one additional BG worker is spawned
  - Classifier must discover and correctly label the new PID
  - We measure convergence latency and LC p99 impact

Files saved to data/:
  dynamic_classified_latency.csv   — LC latency log
  dynamic_classified_signals.csv   — all burst signals (incl. late PID)
  dynamic_label_log.csv            — timestamped label decisions
  dynamic_classified_pids.csv      — final classified_pids snapshot

Analysis:
  validate_dynamic.py is called automatically after the run.

Usage:
    python3 run_experiment_dynamic.py
"""

import os
import sys
import time
import shutil
import subprocess

ROOT         = os.path.dirname(os.path.abspath(__file__))
DATA         = os.path.join(ROOT, "data")
SRC          = os.path.join(ROOT, "src")
OUTPUTS      = os.path.join(ROOT, "outputs")

WORKLOAD     = os.path.join(SRC, "workload",  "workload_gen.py")
SPAWNER      = os.path.join(SRC, "workload",  "dynamic_spawner.py")
PROFILER     = os.path.join(SRC, "profiler",  "profiler.py")
CLASSIFIER   = os.path.join(SRC, "scheduler", "dynamic_classifier.py")   # label-log version
CLASS_SCHED  = os.path.join(SRC, "scheduler", "classified_scheduler.py")
METRICS      = os.path.join(SRC, "analysis",  "latency_metrics.py")
VALIDATOR    = os.path.join(SRC, "analysis",  "validate_dynamic.py")

PYTHON       = sys.executable
DURATION     = 300     # total experiment seconds
SPAWN_DELAY  = 150     # seconds before late BG worker appears
TRIALS       = 2


def nuclear_cleanup():
    for script in ["workload_gen.py", "profiler.py", "dynamic_classifier.py",
                   "classified_scheduler.py", "dynamic_spawner.py"]:
        subprocess.run(["pkill", "-f", script], capture_output=True)
    time.sleep(2)
    subprocess.run(["pkill", "-9", "-f", "workload_gen.py"],
                   capture_output=True)
    time.sleep(1)
    print("[Setup] Clean slate.")


def clear_data():
    os.makedirs(DATA, exist_ok=True)
    for fname in ["latency_pids.txt", "background_pids.txt",
                  "decisions.csv", "classified_pids.csv",
                  "classify_signal.csv", "dynamic_label_log.csv"]:
        open(os.path.join(DATA, fname), "w").close()
    open(os.path.join(DATA, "latency_log.csv"), "w").close()
    print("[Setup] Data files cleared.")


def save_run(trial):
    for src_name, dst_name in [
        ("latency_log.csv",     f"trial{trial}_dynamic_latency.csv"),
        ("classify_signal.csv", f"trial{trial}_dynamic_signals.csv"),
        ("dynamic_label_log.csv", f"trial{trial}_dynamic_label_log.csv"),
        ("classified_pids.csv", f"trial{trial}_dynamic_classified_pids.csv"),
    ]:
        src = os.path.join(DATA, src_name)
        dst = os.path.join(DATA, dst_name)
        if os.path.exists(src) and os.path.getsize(src) > 10:
            shutil.copy(src, dst)
            print(f"[Save] {dst_name}  ({os.path.getsize(dst):,} bytes)")
        else:
            print(f"[WARN] {src_name} missing or empty")


def wait_with_progress(seconds, label):
    start = time.time()
    last  = -1
    while True:
        elapsed = int(time.time() - start)
        if elapsed >= seconds:
            break
        if elapsed % 15 == 0 and elapsed != last:
            print(f"[{label}] {elapsed}s / {seconds}s")
            last = elapsed
        time.sleep(1)


def kill_all(procs):
    for p in procs:
        try: p.terminate()
        except: pass
    time.sleep(1)
    for p in procs:
        try: p.kill()
        except: pass


def run_dynamic_trial(trial):
    print(f"\n--- RUN: Dynamic spawn | Trial {trial} ---")
    print(f"    Late BG worker spawns at t+{SPAWN_DELAY}s")
    clear_data()
    procs = []

    # Core workload (3 LC + 1 BG from t=0)
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(4)

    procs.append(subprocess.Popen([PYTHON, PROFILER]))
    time.sleep(1)

    # Adaptive classifier with label logging
    procs.append(subprocess.Popen([PYTHON, CLASSIFIER]))
    time.sleep(3)

    # Scheduler
    procs.append(subprocess.Popen([PYTHON, CLASS_SCHED]))
    time.sleep(1)

    # Dynamic spawner — waits SPAWN_DELAY seconds then adds one BG worker
    procs.append(subprocess.Popen(
        [PYTHON, SPAWNER, "--delay", str(SPAWN_DELAY),
         "--data-dir", DATA]
    ))
    print(f"[Dynamic] Spawner started — late BG worker in {SPAWN_DELAY}s")

    wait_with_progress(DURATION, f"Dynamic-T{trial}")
    kill_all(procs)
    save_run(trial)


def analyse(trial):
    if not os.path.exists(METRICS):
        return
    print(f"\n--- LATENCY ANALYSIS | Trial {trial} ---")
    latency_csv = os.path.join(DATA, f"trial{trial}_dynamic_latency.csv")
    if os.path.exists(latency_csv):
        shutil.copy(latency_csv, os.path.join(DATA, "latency_log.csv"))
        subprocess.run([PYTHON, METRICS])


def validate(trial):
    if not os.path.exists(VALIDATOR):
        print(f"[WARN] {VALIDATOR} not found — skipping convergence analysis")
        return

    signals_path = os.path.join(DATA, f"trial{trial}_dynamic_signals.csv")
    labels_path  = os.path.join(DATA, f"trial{trial}_dynamic_label_log.csv")
    latency_path = os.path.join(DATA, f"trial{trial}_dynamic_latency.csv")
    out_path     = os.path.join(OUTPUTS,
                                f"fig_convergence_timeline_t{trial}.png")

    for p in [signals_path, labels_path, latency_path]:
        if not os.path.exists(p):
            print(f"[WARN] Missing for validation: {p}")
            return

    print(f"\n--- CONVERGENCE VALIDATION | Trial {trial} ---")
    subprocess.run([
        PYTHON, VALIDATOR,
        "--signals",  signals_path,
        "--labels",   labels_path,
        "--latency",  latency_path,
        "--out",      out_path,
    ])


if __name__ == "__main__":
    nuclear_cleanup()
    os.makedirs(OUTPUTS, exist_ok=True)

    print("\n" + "="*60)
    print("  DYNAMIC SPAWN ROBUSTNESS EXPERIMENT")
    print("="*60)
    print(f"  Trials       : {TRIALS}")
    print(f"  Duration     : {DURATION}s per trial")
    print(f"  Spawn delay  : {SPAWN_DELAY}s (late BG worker)")
    print(f"  Est. total   : ~{TRIALS * DURATION // 60} min")
    print("="*60 + "\n")

    try:
        for trial in range(1, TRIALS + 1):
            print("\n" + "#"*60)
            print(f"  TRIAL {trial}/{TRIALS}")
            print("#"*60)

            run_dynamic_trial(trial)
            analyse(trial)
            validate(trial)

            if trial < TRIALS:
                print("\nCooling 15s...\n")
                time.sleep(15)

        print(f"\nDONE. Convergence plots in: {OUTPUTS}/")

    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(1)