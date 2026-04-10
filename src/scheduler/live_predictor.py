import time
from utils.cpu_utils import read_cpu_times, get_cpu_util


ALPHA = 0.7

# initialize EWMA
ewma = None


def get_live_cpu(prev_idle, prev_total):
    cpu, idle, total = get_cpu_util(prev_idle, prev_total)
    return cpu, idle, total


def run_live_predictor():
    global ewma

    prev_idle, prev_total = read_cpu_times()

    print("Live predictor started...\n")

    while True:
        cpu, prev_idle, prev_total = get_live_cpu(prev_idle, prev_total)

        if ewma is None:
            ewma = cpu
        else:
            ewma = ALPHA * cpu + (1 - ALPHA) * ewma

        # burst detection (same logic as before)
        # we use simple threshold for now
        burst = 1 if ewma > 92 else 0

        print(f"CPU: {cpu:.2f} | EWMA: {ewma:.2f} | Burst: {burst}")

        time.sleep(0.1)


if __name__ == "__main__":
    run_live_predictor()