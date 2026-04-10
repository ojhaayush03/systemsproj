import time
import csv
import os
from datetime import datetime
from utils.cpu_utils import read_cpu_times, get_cpu_util


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
DATA_PATH = os.path.join(BASE_DIR, "data")
OUTPUT_FILE = os.path.join(DATA_PATH, "metrics.csv")


def get_runqueue():
    with open("/proc/loadavg", "r") as f:
        return float(f.read().split()[0])


def run_profiler():
    prev_idle, prev_total = read_cpu_times()

    os.makedirs(DATA_PATH, exist_ok=True)

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "cpu_util", "runqueue"])

        print("Profiler started...")

        while True:
            cpu_util, prev_idle, prev_total = get_cpu_util(prev_idle, prev_total)
            runqueue = get_runqueue()

            writer.writerow([
                datetime.now().strftime("%H:%M:%S.%f"),
                cpu_util,
                runqueue
            ])

            f.flush()
            time.sleep(0.1)


if __name__ == "__main__":
    run_profiler()