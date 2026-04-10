def read_cpu_times():
    with open("/proc/stat", "r") as f:
        line = f.readline()
        values = list(map(int, line.strip().split()[1:]))

        idle = values[3] + values[4]   # idle + iowait
        total = sum(values)

        return idle, total


def get_cpu_util(prev_idle, prev_total):
    idle, total = read_cpu_times()

    delta_idle = idle - prev_idle
    delta_total = total - prev_total

    cpu_util = 0.0
    if delta_total > 0:
        cpu_util = 100.0 * (1 - (delta_idle / delta_total))

    return cpu_util, idle, total