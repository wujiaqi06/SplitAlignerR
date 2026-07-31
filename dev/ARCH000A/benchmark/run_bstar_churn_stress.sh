#!/bin/sh
set -eu

: "${ARCH000A_BSTAR_RESULT_DIR:?ARCH000A_BSTAR_RESULT_DIR is required}"
mkdir -p "${ARCH000A_BSTAR_RESULT_DIR}"

Rscript dev/ARCH000A/benchmark/run_bstar_churn_stress.R \
  >"${ARCH000A_BSTAR_RESULT_DIR}/BSTAR_CHURN_RUN.raw.log" 2>&1 &
case_pid=$!
Rscript dev/ARCH000A/benchmark/rss_monitor.R \
  "${case_pid}" "${ARCH000A_BSTAR_RESULT_DIR}/BSTAR_CHURN_RSS.raw.txt" &
monitor_pid=$!
case_status=0
wait "${case_pid}" || case_status=$?
wait "${monitor_pid}"
if [ "${case_status}" -eq 0 ]
then
  Rscript dev/ARCH000A/benchmark/finalize_bstar_churn_results.R \
    "${ARCH000A_BSTAR_RESULT_DIR}"
fi
exit "${case_status}"
