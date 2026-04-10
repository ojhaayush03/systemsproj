import pandas as pd
from sklearn.metrics import mean_absolute_error, f1_score


import matplotlib.pyplot as plt
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "metrics.csv")
DATA_SAVED_PATH = os.path.join(BASE_DIR, "data", "metrics_with_pred.csv")

def ewma_predict(series, alpha=0.7):
    predictions = []

    # initial prediction = first value
    prev_pred = series.iloc[0]

    for x in series:
        pred = alpha * x + (1 - alpha) * prev_pred
        predictions.append(pred)
        prev_pred = pred

    return predictions


if __name__ == "__main__":
    df = pd.read_csv(DATA_PATH)
    mean = df["cpu_util"].mean()
    std = df["cpu_util"].std()

    threshold = mean + 0.3 * std
    df["pred_cpu"] = ewma_predict(df["cpu_util"])
    df["actual_burst"] = (df["cpu_util"] > threshold).astype(int)
    df["pred_burst"] = (df["pred_cpu"] > threshold).astype(int)

    f1 = f1_score(df["actual_burst"], df["pred_burst"])
    print("F1 Score:", f1)

    mae = mean_absolute_error(df["cpu_util"], df["pred_cpu"])
    print("MAE:", mae)

    df.to_csv(DATA_SAVED_PATH, index=False)

    print("Predictions saved.")


plt.plot(df["cpu_util"], label="Actual")
plt.plot(df["pred_cpu"], label="Predicted")
plt.legend()
plt.title("EWMA Prediction vs Actual CPU")
plt.show()