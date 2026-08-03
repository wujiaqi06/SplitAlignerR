#!/bin/sh
set -eu

: "${ENGINE001_SPECIES_TREE:?ENGINE001_SPECIES_TREE is required}"
: "${ENGINE001_FIXED_TREES:?ENGINE001_FIXED_TREES is required}"
: "${ENGINE001_FREE_TREES:?ENGINE001_FREE_TREES is required}"
: "${ENGINE001_RESULT_DIR:?ENGINE001_RESULT_DIR is required}"
: "${ENGINE001_WORK_DIR:?ENGINE001_WORK_DIR is required}"

mkdir -p "$ENGINE001_RESULT_DIR" "$ENGINE001_WORK_DIR" \
  "$ENGINE001_RESULT_DIR/rss" "$ENGINE001_RESULT_DIR/logs" \
  "$ENGINE001_RESULT_DIR/final"

run_monitored() {
  label=$1
  shift
  "$@" >"$ENGINE001_RESULT_DIR/logs/$label.log" 2>&1 &
  task_pid=$!
  Rscript dev/ENGINE001/benchmark/rss_monitor.R "$task_pid" \
    "$ENGINE001_RESULT_DIR/rss/$label.rss.txt" &
  monitor_pid=$!
  set +e
  wait "$task_pid"
  task_status=$?
  wait "$monitor_pid"
  monitor_status=$?
  set -e
  if [ "$task_status" -ne 0 ] || [ "$monitor_status" -ne 0 ]; then
    echo "ENGINE001 monitored case failed: $label" >&2
    exit 1
  fi
}

run_monitored packed_schema Rscript \
  dev/ENGINE001/benchmark/run_engine001_benchmarks.R packed \
  "$ENGINE001_SPECIES_TREE" "$ENGINE001_FIXED_TREES" "$ENGINE001_FREE_TREES" \
  "$ENGINE001_RESULT_DIR/packed_schema.csv" \
  "$ENGINE001_RESULT_DIR/PACKED_ROUNDTRIP_RESULTS.txt"

for layout in row_major column_major tiled_256x256; do
  label="matrix_authority_${layout}"
  run_monitored "$label" Rscript \
    dev/ENGINE001/benchmark/run_engine001_benchmarks.R matrix \
    "$layout" 2275 1086 "$ENGINE001_RESULT_DIR/$label.csv" \
    "$ENGINE001_WORK_DIR"
done

for layout in row_major column_major tiled_256x256; do
  label="matrix_large_${layout}"
  run_monitored "$label" Rscript \
    dev/ENGINE001/benchmark/run_engine001_benchmarks.R matrix \
    "$layout" 100000 4913 "$ENGINE001_RESULT_DIR/$label.csv" \
    "$ENGINE001_WORK_DIR"
done

Rscript dev/ENGINE001/benchmark/run_engine001_benchmarks.R manifest \
  "$ENGINE001_RESULT_DIR/MANIFEST_VALIDATION_RESULTS.txt" \
  >"$ENGINE001_RESULT_DIR/logs/manifest.log" 2>&1

Rscript dev/ENGINE001/benchmark/run_engine001_benchmarks.R ownership \
  "$ENGINE001_RESULT_DIR/OWNERSHIP_LIFECYCLE_RESULTS.txt" \
  >"$ENGINE001_RESULT_DIR/logs/ownership.log" 2>&1

Rscript dev/ENGINE001/benchmark/run_engine001_benchmarks.R aggregate \
  "$ENGINE001_RESULT_DIR" "$ENGINE001_RESULT_DIR/rss" \
  "$ENGINE001_RESULT_DIR/final"
