#!/bin/bash
export PYTHONPATH=$(pwd)/src

echo "Starting workload..."
python src/workload/workload_gen.py &

echo "Starting profiler..."
python src/profiler/profiler.py &

echo "Starting predictor..."
python src/scheduler/live_predictor.py

wait