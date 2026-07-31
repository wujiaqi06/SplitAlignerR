#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
arch_root=$(CDPATH= cd -- "${script_dir}/.." && pwd)
result_dir="${ARCH000_BENCH_RESULT_DIR:-${arch_root}/benchmark/raw}"
work_dir="${ARCH000_BENCH_WORK_DIR:-/tmp/SplitAlignerR_ARCH000_workloads}"
threshold_bytes="${ARCH000_BSTAR_THRESHOLD_BYTES:-33554432}"
storage_type="${ARCH000_STORAGE_TYPE:-local_APFS_SSD}"

if [ -z "${ARCH000_302_DIR:-}" ] || [ -z "${ARCH000_2275_DIR:-}" ]; then
  echo "Set ARCH000_302_DIR and ARCH000_2275_DIR." >&2
  exit 2
fi

mkdir -p "${result_dir}" "${work_dir}"
Rscript "${script_dir}/run_arch000_benchmarks.R" generate "work=${work_dir}"
Rscript "${script_dir}/run_arch000_benchmarks.R" environment \
  "output=${arch_root}/benchmark/BENCHMARK_ENVIRONMENT.txt"

run_case() {
  label=$1
  species=$2
  input=$3
  variant=$4
  stem="${result_dir}/${label}__${variant}"
  /usr/bin/time -l -o "${stem}.time.txt" \
    Rscript "${script_dir}/run_arch000_benchmarks.R" case \
      "label=${label}" "species=${species}" "input=${input}" \
      "variant=${variant}" "result=${stem}.rds" \
      "threshold_bytes=${threshold_bytes}" "storage_type=${storage_type}"
}

authority_species="${ARCH000_302_DIR}/input/speciesTree302.nwk"
authority_input="${ARCH000_2275_DIR}/fix.2275genes.nwk"
catnip_species="${work_dir}/catnip10_species.nwk"

run_case authority_2275 "${authority_species}" "${authority_input}" taxa_full
run_case authority_2275 "${authority_species}" "${authority_input}" full_full
run_case authority_2275 "${authority_species}" "${authority_input}" in_memory_text
run_case catnip10_rep_10000 "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk" taxa_full
run_case catnip10_rep_10000 "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk" full_full
run_case catnip10_rep_10000 "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk" in_memory_text
run_case catnip10_rep_10000_gzip "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk.gz" taxa_full
run_case catnip10_rep_100000 "${catnip_species}" \
  "${work_dir}/catnip10_rep_100000.nwk" taxa_full

run_case catnip10_rep_10000 "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk" production_in_memory
run_case catnip10_rep_10000_io "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk" read_only
run_case catnip10_rep_10000_io "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk" taxa_scan_only
run_case catnip10_rep_10000_io "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk" full_parse_only
run_case catnip10_rep_10000_gzip_io "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk.gz" read_only
run_case catnip10_rep_10000_gzip_io "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk.gz" taxa_scan_only
run_case catnip10_rep_10000_gzip_io "${catnip_species}" \
  "${work_dir}/catnip10_rep_10000.nwk.gz" full_parse_only

Rscript "${script_dir}/run_arch000_benchmarks.R" aggregate \
  "result_dir=${result_dir}" \
  "output=${arch_root}/benchmark/BENCHMARK_RESULTS.csv"
