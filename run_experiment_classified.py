"""
run_experiment_classified.py

Runs a single comparison experiment:
  Run 1 (PTLS-labelled)   — original static_priority_scheduler.py
                            uses hardcoded latency_pids.txt / background_pids.txt
  Run 2 (PTLS-classified) — classifier.py + classified_scheduler.py
                            discovers LC/BG dynamically at runtime

Both runs use NICE_LC=-5, NICE_BG=+15 (the known-good config).
Goal: show classified run matches labelled run in p99 and TLR.
After both runs, validate_classifier.py is called to print accuracy.

Usage:
    python3 run_experiment_classified.py
"""

import os, sys, time, shutil, subprocess

ROOT        = os.path.dirname(os.path.abspath(__file__))
DATA        = os.path.join(ROOT, "data")
SRC         = os.path.join(ROOT, "src")

WORKLOAD    = os.path.join(SRC, "workload",   "workload_gen.py")
PROFILER    = os.path.join(SRC, "profiler",   "profiler.py")
STATIC_SCHED= os.path.join(SRC, "scheduler",  "adaptive_scheduler.py")
CLASSIFIER  = os.path.join(SRC, "scheduler",  "classifier.py")
CLASS_SCHED = os.path.join(SRC, "scheduler",  "classified_scheduler.py")
METRICS     = os.path.join(SRC, "analysis",   "latency_metrics.py")
VALIDATOR   = os.path.join(SRC, "analysis",   "validate_classifier.py")

PYTHON   = sys.executable
DURATION = 300    # seconds per run
TRIALS   = 2      # trials of each mode

SUMMARY_FILE = os.path.join(ROOT, "classifier_experiment_summary.txt")


def nuclear_cleanup():
    for script in ["workload_gen.py", "profiler.py", "classifier.py",
                   "classified_scheduler.py", "adaptive_scheduler.py"]:
        subprocess.run(["pkill", "-f", script], capture_output=True)
    time.sleep(2)
    subprocess.run(["pkill", "-9", "-f", "workload_gen.py"], capture_output=True)
    time.sleep(1)
    print("[Setup] Clean slate.")


def clear_data():
    os.makedirs(DATA, exist_ok=True)
    for fname in ["latency_pids.txt", "background_pids.txt",
                  "decisions.csv", "classified_pids.csv",
                  "classify_signal.csv"]:
        open(os.path.join(DATA, fname), "w").close()
    open(os.path.join(DATA, "latency_log.csv"), "w").close()
    print("[Setup] Data files cleared.")


def save_run(label, trial):
    for src_name, dst_name in [
        ("latency_log.csv",      f"trial{trial}_{label}_latency.csv"),
        ("classify_signal.csv",  f"trial{trial}_{label}_signals.csv"),
        ("classified_pids.csv",  f"trial{trial}_{label}_classified_pids.csv"),
        ("decisions.csv",        f"trial{trial}_{label}_decisions.csv"),
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


# ── Run 1: labelled (original static scheduler) ───────────────
def run_labelled(trial):
    print(f"\n--- RUN: PTLS-labelled | Trial {trial} ---")
    clear_data()
    procs = []
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(4)
    procs.append(subprocess.Popen([PYTHON, PROFILER]))
    time.sleep(1)
    procs.append(subprocess.Popen([PYTHON, STATIC_SCHED]))
    wait_with_progress(DURATION, f"Labelled-T{trial}")
    kill_all(procs)
    save_run("labelled", trial)


# ── Run 2: classified (classifier + classified_scheduler) ─────
def run_classified(trial):
    print(f"\n--- RUN: PTLS-classified | Trial {trial} ---")
    clear_data()
    procs = []
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(4)
    procs.append(subprocess.Popen([PYTHON, PROFILER]))
    time.sleep(1)
    # Start classifier first, then scheduler reads its output
    procs.append(subprocess.Popen([PYTHON, CLASSIFIER]))
    time.sleep(3)   # give classifier time to observe a few bursts
    procs.append(subprocess.Popen([PYTHON, CLASS_SCHED]))
    wait_with_progress(DURATION, f"Classified-T{trial}")
    kill_all(procs)
    save_run("classified", trial)


def analyse(trial):
    if not os.path.exists(METRICS):
        return
    print(f"\n--- ANALYSIS | Trial {trial} ---")
    for label, fname in [
        ("PTLS-labelled",    f"trial{trial}_labelled_latency.csv"),
        ("PTLS-classified",  f"trial{trial}_classified_latency.csv"),
    ]:
        csv_path = os.path.join(DATA, fname)
        if not os.path.exists(csv_path):
            continue
        shutil.copy(csv_path, os.path.join(DATA, "latency_log.csv"))
        print(f"\n[{label}]")
        subprocess.run([PYTHON, METRICS])


def validate(trial):
    """Run classifier accuracy check on the signals file."""
    if not os.path.exists(VALIDATOR):
        return
    sig_file = os.path.join(DATA, f"trial{trial}_classified_signals.csv")
    if not os.path.exists(sig_file):
        return
    print(f"\n--- CLASSIFIER VALIDATION | Trial {trial} ---")
    subprocess.run([PYTHON, VALIDATOR, "--signals", sig_file])


if __name__ == "__main__":
    nuclear_cleanup()

    print("\n==============================")
    print(" CLASSIFIER COMPARISON RUN    ")
    print("==============================")
    print(f"  Trials  : {TRIALS}")
    print(f"  Duration: {DURATION}s per run")
    print(f"  Est. total: ~{TRIALS * 2 * DURATION // 60} min")
    print("==============================\n")

    open(SUMMARY_FILE, "w").close()

    try:
        for trial in range(1, TRIALS + 1):
            print("\n" + "#"*60)
            print(f"  TRIAL {trial}/{TRIALS}")
            print("#"*60)

            run_labelled(trial)
            print("\nCooling 10s...\n")
            time.sleep(10)

            run_classified(trial)
            analyse(trial)
            validate(trial)

            with open(SUMMARY_FILE, "a") as f:
                f.write(f"\n=== Trial {trial} ===\n")
                f.write(f"Labelled:   trial{trial}_labelled_latency.csv\n")
                f.write(f"Classified: trial{trial}_classified_latency.csv\n")
                f.write(f"Signals:    trial{trial}_classified_signals.csv\n")

        print(f"\nDONE. Summary: {SUMMARY_FILE}")

    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(1)