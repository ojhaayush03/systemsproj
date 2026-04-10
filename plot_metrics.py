import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("data/metrics.csv")
df= df.dropna()  # Remove rows with missing values
# ✅ Convert timestamp string → datetime
df["timestamp"] = pd.to_datetime(df["timestamp"], format="%H:%M:%S.%f")

# ✅ Convert to seconds (relative time)
df["timestamp"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()

print(df.head())
print(df.shape)
print(df.dtypes)
print(df.isnull().sum())

# Create plots
plt.figure(figsize=(12, 8))

# CPU Utilization
plt.subplot(3, 1, 1)
plt.plot(df["timestamp"], df["cpu_util"])
plt.title("CPU Utilization Over Time")
plt.ylabel("CPU %")

# Runqueue
plt.subplot(3, 1, 2)
plt.plot(df["timestamp"], df["runqueue"])
plt.title("Runqueue Length Over Time")
plt.ylabel("Processes")

# Context Switches
plt.subplot(3, 1, 3)
plt.plot(df["timestamp"], df["ctx_switches"])
plt.title("Context Switches Over Time")
plt.xlabel("Time (s)")
plt.ylabel("Count")

plt.tight_layout()
plt.show()