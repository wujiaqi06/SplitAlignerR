#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
arch_root=$(CDPATH= cd -- "${script_dir}/.." && pwd)
result_dir="${ARCH000_BENCH_RESULT_DIR:-/tmp/arch000-benchmark-raw}"
work_dir="${ARCH000_BENCH_WORK_DIR:-/tmp/arch000-benchmark-work}"
threshold_bytes="${ARCH000_BSTAR_THRESHOLD_BYTES:-33554432}"
storage_type="${ARCH000_STORAGE_TYPE:-local_APFS_SSD}"
species="${work_dir}/catnip10_species.nwk"
plain="${work_dir}/catnip10_rep_10000.nwk"
gzip="${plain}.gz"

run_case() {
  label=$1
  input=$2
  variant=$3
  stem="${result_dir}/${label}__${variant}"
  /usr/bin/time -l -o "${stem}.time.txt" \
    Rscript "${script_dir}/run_arch000_benchmarks.R" case \
      "label=${label}" "species=${species}" "input=${input}" \
      "variant=${variant}" "result=${stem}.rds" \
      "threshold_bytes=${threshold_bytes}" "storage_type=${storage_type}"
}

run_case catnip10_rep_10000 "${plain}" production_in_memory
run_case catnip10_rep_10000_io "${plain}" read_only
run_case catnip10_rep_10000_io "${plain}" taxa_scan_only
run_case catnip10_rep_10000_io "${plain}" full_parse_only
run_case catnip10_rep_10000_gzip_io "${gzip}" read_only
run_case catnip10_rep_10000_gzip_io "${gzip}" taxa_scan_only
run_case catnip10_rep_10000_gzip_io "${gzip}" full_parse_only

Rscript "${script_dir}/run_arch000_benchmarks.R" aggregate \
  "result_dir=${result_dir}" \
  "output=${arch_root}/benchmark/BENCHMARK_RESULTS.csv"
