#!/bin/sh
set -eu

: "${ARCH000A_302_DIR:?ARCH000A_302_DIR is required}"
: "${ARCH000A_2275_DIR:?ARCH000A_2275_DIR is required}"
: "${ARCH000A_BENCH_RESULT_DIR:?ARCH000A_BENCH_RESULT_DIR is required}"
: "${ARCH000A_BENCH_WORK_DIR:?ARCH000A_BENCH_WORK_DIR is required}"

mkdir -p "${ARCH000A_BENCH_RESULT_DIR}" "${ARCH000A_BENCH_WORK_DIR}"
runner="dev/ARCH000A/benchmark/run_arch000a_benchmarks.R"

run_case() {
  case_label="$1"
  shift
  case_mode="$1"
  shift
  Rscript "${runner}" "${case_mode}" "${case_label}" "$@" &
  case_pid=$!
  Rscript dev/ARCH000A/benchmark/rss_monitor.R \
    "${case_pid}" "${ARCH000A_BENCH_RESULT_DIR}/${case_label}.rss.txt" &
  monitor_pid=$!
  case_status=0
  wait "${case_pid}" || case_status=$?
  wait "${monitor_pid}"
  if [ "${case_status}" -ne 0 ]
  then
    return "${case_status}"
  fi
}

if [ "${ARCH000A_REUSE_PREPARED:-0}" != "1" ]
then
  run_case prepare_authority prepare_authority
  run_case phase_authority phase_decomposition
fi

run_case walk_retain_original strategy_walk retain_all original 0
run_case walk_recompute_original strategy_walk recompute original 0
run_case walk_lru_recompute_32m strategy_walk lru_recompute original 33554432
run_case walk_lru_recompute_256m strategy_walk lru_recompute original 268435456
run_case walk_disk_original strategy_walk disk original 0

for budget in 33554432 67108864 134217728 268435456
do
  run_case "walk_lru_disk_${budget}_original" \
    strategy_walk lru_disk_decoded original "${budget}"
  run_case "walk_packed_lru_${budget}_original" \
    strategy_walk packed_disk_lru original "${budget}"
done

for ordering in grouped interleaved reversed random
do
  run_case "walk_lru_disk_33554432_${ordering}" \
    strategy_walk lru_disk_decoded "${ordering}" 33554432
  run_case "walk_packed_lru_33554432_${ordering}" \
    strategy_walk packed_disk_lru "${ordering}" 33554432
done

run_case authority_end_to_end_64m end_to_end 67108864

run_case stress_2275_u10 stress_actual 2275 0.10
run_case stress_2275_u50 stress_actual 2275 0.50
run_case stress_2275_u90 stress_actual 2275 0.90
run_case stress_2275_u100 stress_actual 2275 1.00
run_case stress_10000_u100 stress_actual 10000 1.00

run_case stress_100000_u100_interleaved_64m \
  stress_substrate 100000 1.00 67108864 interleaved

Rscript dev/ARCH000A/benchmark/aggregate_arch000a_benchmarks.R \
  "${ARCH000A_BENCH_RESULT_DIR}"
