#!/bin/sh
set -eu

: "${ARCH000A_302_DIR:?ARCH000A_302_DIR is required}"
: "${ARCH000A_2275_DIR:?ARCH000A_2275_DIR is required}"
: "${ARCH000A_RESIDUAL_LEDGER:?ARCH000A_RESIDUAL_LEDGER is required}"
: "${ARCH000A_EVIDENCE_DIR:?ARCH000A_EVIDENCE_DIR is required}"
: "${ARCH000A_WORK_DIR:?ARCH000A_WORK_DIR is required}"
: "${ARCH000A_SELECTED_CACHE_BYTES:=67108864}"

ARCH000A_RUN_FULL=1
export ARCH000A_RUN_FULL ARCH000A_SELECTED_CACHE_BYTES

mkdir -p "${ARCH000A_EVIDENCE_DIR}" "${ARCH000A_WORK_DIR}"

Rscript dev/ARCH000A/prototype/run_conformance.R \
  >"${ARCH000A_EVIDENCE_DIR}/CONFORMANCE_RUN.raw.log" 2>&1 &
case_pid=$!

Rscript dev/ARCH000A/benchmark/rss_monitor.R \
  "${case_pid}" "${ARCH000A_EVIDENCE_DIR}/FULL_CONFORMANCE_RSS.raw.txt" &
monitor_pid=$!

case_status=0
wait "${case_pid}" || case_status=$?
wait "${monitor_pid}"

exit "${case_status}"
