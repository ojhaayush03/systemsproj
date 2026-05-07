"""
run_experiment.py
Sweeps multiple priority configs × multiple trials.
Each config runs: Run1 (CFS baseline) + Run2 (PTLS with given nice values)
"""

import os, sys, time, shutil, subprocess

ROOT      = os.path.dirname(os.path.abspath(__file__))
DATA      = os.path.join(ROOT, "data")
SRC       = os.path.join(ROOT, "src")
WORKLOAD  = os.path.join(SRC, "workload",  "workload_gen.py")
PROFILER  = os.path.join(SRC, "profiler",  "profiler.py")
SCHEDULER = os.path.join(SRC, "scheduler", "adaptive_scheduler.py")  # fixed filename
METRICS   = os.path.join(SRC, "analysis",  "latency_metrics.py")

PYTHON = sys.executable

DURATION = 300  # seconds per trial
TRIALS   = 2    # trials per config — 2 is enough for sensitivity sweep

# ── Priority configs to sweep ─────────────────────────────────
# Add/remove rows here. run_experiment.py handles everything else.
PRIORITY_CONFIGS = [
    # {"lc":  0,  "bg":  0},   # gap=0:  pure CFS equivalent (control)
    # {"lc": -2,  "bg": +5},   # gap=7:  weak separation
    {"lc": -5,  "bg": +15},  # gap=20: current working config
    {"lc": -10, "bg": +15},  # gap=25: more LC boost, same BG suppression
    {"lc": -10, "bg": +19},  # gap=29: maximum practical gap
]
# ─────────────────────────────────────────────────────────────

SUMMARY_FILE = os.path.join(ROOT, "experiment_summary.txt")


def nuclear_cleanup():
    scripts = ["workload_gen.py", "profiler.py", "adaptive_scheduler.py"]
    for script in scripts:
        subprocess.run(["pkill", "-f", script], capture_output=True)
    time.sleep(2)
    result = subprocess.run(["pgrep", "-f", "workload_gen.py"],
                            capture_output=True, text=True)
    if result.stdout.strip():
        print(f"[WARN] Still alive: {result.stdout.strip()}")
        subprocess.run(["pkill", "-9", "-f", "workload_gen.py"])
        time.sleep(1)
    print("[Setup] Clean slate confirmed.")


def clear_data():
    os.makedirs(DATA, exist_ok=True)
    for f in ["latency_pids.txt", "background_pids.txt", "decisions.csv"]:
        open(os.path.join(DATA, f), "w").close()
    open(os.path.join(DATA, "latency_log.csv"), "w").close()
    print("[Setup] data files cleared")


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
        for m in missing:
            print(f"  {m}")
        sys.exit(1)


def run1_cfs(trial, config_label):
    print(f"\n--- RUN 1 (CFS baseline) | Trial {trial} | Config {config_label} ---")
    clear_data()
    procs = []
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(3)
    procs.append(subprocess.Popen([PYTHON, PROFILER]))
    wait_with_progress(DURATION, f"CFS-T{trial}-{config_label}")
    kill_all(procs)
    save_run(f"cfs_{config_label}", trial)


def run2_ptls(trial, lc_nice, bg_nice, config_label):
    print(f"\n--- RUN 2 (PTLS) | Trial {trial} | LC={lc_nice} BG={bg_nice} ---")
    clear_data()
    procs = []
    procs.append(subprocess.Popen([PYTHON, WORKLOAD]))
    time.sleep(4)
    procs.append(subprocess.Popen([PYTHON, PROFILER]))
    time.sleep(1)

    # Pass nice values to scheduler via environment variables
    env = os.environ.copy()
    env["NICE_LC"] = str(lc_nice)
    env["NICE_BG"] = str(bg_nice)
    procs.append(subprocess.Popen([PYTHON, SCHEDULER], env=env))

    wait_with_progress(DURATION, f"PTLS-T{trial}-{config_label}")
    kill_all(procs)
    save_run(f"ptls_{config_label}", trial)


def append_summary(trial, config_label, lc_nice, bg_nice):
    with open(SUMMARY_FILE, "a") as f:
        f.write(f"\n=== Trial {trial} | LC={lc_nice} BG={bg_nice} (gap={bg_nice - lc_nice}) ===\n")
        f.write(f"CFS  file: trial{trial}_cfs_{config_label}_latency.csv\n")
        f.write(f"PTLS file: trial{trial}_ptls_{config_label}_latency.csv\n")


def analyse(trial, config_label):
    if not os.path.exists(METRICS):
        return
    print(f"\n--- ANALYSIS | Trial {trial} | Config {config_label} ---")
    for label, fname in [
        ("CFS",  f"trial{trial}_cfs_{config_label}_latency.csv"),
        ("PTLS", f"trial{trial}_ptls_{config_label}_latency.csv"),
    ]:
        csv_path = os.path.join(DATA, fname)
        if not os.path.exists(csv_path):
            continue
        shutil.copy(csv_path, os.path.join(DATA, "latency_log.csv"))
        print(f"\n[{label}]")
        subprocess.run([PYTHON, METRICS])


if __name__ == "__main__":
    nuclear_cleanup()

    print("\n==============================")
    print("  PRIORITY SENSITIVITY SWEEP  ")
    print("==============================")
    print(f"  Configs : {len(PRIORITY_CONFIGS)}")
    print(f"  Trials  : {TRIALS} per config")
    print(f"  Duration: {DURATION}s per trial")
    total_min = len(PRIORITY_CONFIGS) * TRIALS * 2 * DURATION // 60
    print(f"  Est. total runtime: ~{total_min} min")
    print("==============================\n")

    check_scripts()
    open(SUMMARY_FILE, "w").close()

    try:
        for cfg in PRIORITY_CONFIGS:
            lc_nice     = cfg["lc"]
            bg_nice     = cfg["bg"]
            gap         = bg_nice - lc_nice
            # e.g. "lc-5_bg15" — used in filenames
            config_label = f"lc{lc_nice}_bg{bg_nice}"

            print("\n" + "="*60)
            print(f"CONFIG: LC={lc_nice}  BG={bg_nice}  GAP={gap}")
            print("="*60)

            for trial in range(1, TRIALS + 1):
                print("\n" + "#"*60)
                print(f"  TRIAL {trial}/{TRIALS}  |  LC={lc_nice} BG={bg_nice}")
                print("#"*60)

                run1_cfs(trial, config_label)

                print("\nCooling down 10s...\n")
                time.sleep(10)

                run2_ptls(trial, lc_nice, bg_nice, config_label)

                analyse(trial, config_label)
                append_summary(trial, config_label, lc_nice, bg_nice)

            print(f"\n[Done] Config LC={lc_nice} BG={bg_nice} complete. Cooling 15s...")
            time.sleep(15)

        print(f"\nALL CONFIGS DONE. Summary saved at:\n{SUMMARY_FILE}")

    except KeyboardInterrupt:
        print("\n[Interrupted]")
        sys.exit(1)