#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: run_rc_job.sh SOURCE_ROOT AUTHORITY_ROOT EXPECTED_COMMIT" >&2
  exit 64
fi

source_root="$(cd "$1" && pwd)"
authority_root="$(cd "$2" && pwd)"
expected_commit="$3"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runner_temp="${RUNNER_TEMP:?RUNNER_TEMP is required}"
runner_os="${RUNNER_OS:-unknown-os}"
runner_arch="${RUNNER_ARCH:-unknown-arch}"
perl_commit="1aea990946e08d13349bc6a164dc7334d61cae08"
authority_chunk_size="${SPLITALIGNERR_AUTHORITY_CHUNK_SIZE:-50}"

preflight_dir="$(mktemp -d "${runner_temp}/splitalignerr-rc-preflight.XXXXXX")"
evidence_dir=""
artifact_dir="${runner_temp}/splitalignerr-rc-artifacts"
artifact_zip=""
artifact_sidecar=""

emit_outputs() {
  if [[ -n "${GITHUB_OUTPUT:-}" && -n "$artifact_zip" ]]; then
    {
      printf 'artifact_zip=%s\n' "$artifact_zip"
      printf 'artifact_sidecar=%s\n' "$artifact_sidecar"
    } >> "$GITHUB_OUTPUT"
  fi
}

finalize() {
  local status=$?
  local packaging_status=0
  trap - EXIT
  set +e
  if [[ $status -ne 0 && -z "$evidence_dir" ]]; then
    evidence_dir="${preflight_dir}/PRECHECK_FAILURE_EVIDENCE"
    mkdir -p "$evidence_dir"
    find "$preflight_dir" -maxdepth 1 -type f -exec cp {} "$evidence_dir/" \;
    {
      printf 'overall_status: FAILED_PRECHECK\n'
      printf 'exit_status: %s\n' "$status"
      printf 'accepted_run_directory_created: FALSE\n'
    } > "${evidence_dir}/RUN_SUMMARY.txt"
  elif [[ $status -ne 0 && -n "$evidence_dir" ]]; then
    {
      printf 'overall_status: FAILED\n'
      printf 'exit_status: %s\n' "$status"
    } > "${evidence_dir}/RUN_SUMMARY.txt"
  fi
  if [[ -n "$evidence_dir" && -d "$evidence_dir" ]]; then
    mkdir -p "$artifact_dir"
    artifact_zip="${artifact_dir}/SplitAlignerR_rc_evidence_${runner_os}_${runner_arch}.zip"
    artifact_sidecar="${artifact_zip}.sha256"
    python3 "${script_dir}/package_evidence.py" \
      --input-dir "$evidence_dir" --output-zip "$artifact_zip"
    packaging_status=$?
    if [[ $packaging_status -eq 0 ]]; then
      emit_outputs
    elif [[ $status -eq 0 ]]; then
      status=$packaging_status
    fi
  fi
  exit "$status"
}
trap finalize EXIT

preflight_log="${preflight_dir}/PRECHECK.log"
{
  printf 'preflight_started_utc: '
  date -u '+%Y-%m-%dT%H:%M:%SZ'
  printf 'source_root: %s\n' "$source_root"
  printf 'authority_root: %s\n' "$authority_root"
  printf 'expected_source_commit: %s\n' "$expected_commit"
  printf 'expected_perl_commit: %s\n' "$perl_commit"
} > "$preflight_log"

required_commands=(R Rscript python3 git locale tar gzip)
if [[ "$runner_os" == "Windows" ]]; then
  required_commands+=(cygpath)
fi
for command_name in "${required_commands[@]}"; do
  command -v "$command_name" >> "$preflight_log" 2>&1 || {
    printf 'missing_command: %s\n' "$command_name" >> "$preflight_log"
    exit 69
  }
done

available_locales="$(locale -a 2>&1)" || {
  printf 'locale_probe: FAILED\n' >> "$preflight_log"
  exit 69
}
selected_locale=""
r_locale_report=""
if [[ "$runner_os" == "Windows" ]]; then
  unset LANG LC_ALL LC_CTYPE LC_COLLATE LC_TIME LC_MONETARY
  if Rscript -e 'stopifnot(isTRUE(l10n_info()[["UTF-8"]]))' \
      >> "$preflight_log" 2>&1; then
    selected_locale="R-native-UTF-8"
    r_locale_report="R_UTF8_CAPABLE: TRUE"
  fi
else
  for candidate in C.UTF-8 C.utf8 en_US.UTF-8; do
    if grep -Fxiq "$candidate" <<< "$available_locales" && \
        r_locale_report="$(env LANG="$candidate" LC_ALL="$candidate" \
        Rscript -e '
          info <- l10n_info()
          stopifnot(isTRUE(info[["UTF-8"]]))
          cat("R_LC_CTYPE: ", Sys.getlocale("LC_CTYPE"), "\n", sep = "")
          cat("R_UTF8_CAPABLE: TRUE\n")
        ' 2>&1)"; then
      selected_locale="$candidate"
      break
    fi
  done
  if [[ -n "$selected_locale" ]]; then
    export LANG="$selected_locale"
    export LC_ALL="$selected_locale"
  fi
fi
if [[ -z "$selected_locale" ]]; then
  {
    printf 'utf8_locale: MISSING_OR_REJECTED_BY_R\n'
    printf '%s\n' "$r_locale_report"
    printf '%s\n' "$available_locales"
  } >> "$preflight_log"
  exit 69
fi
printf 'selected_utf8_locale: %s\n' "$selected_locale" >> "$preflight_log"
printf '%s\n' "$r_locale_report" >> "$preflight_log"

Rscript -e 'stopifnot(getRversion() >= "3.5.0")' >> "$preflight_log" 2>&1
cxx17="$(R CMD config CXX17)"
if [[ -z "$cxx17" ]]; then
  printf 'cxx17_compiler: MISSING\n' >> "$preflight_log"
  exit 69
fi
printf 'cxx17_compiler: %s\n' "$cxx17" >> "$preflight_log"

Rscript "${script_dir}/dependency_report.R" \
  "${preflight_dir}/DEPENDENCIES.tsv" >> "$preflight_log" 2>&1

python3 -B "${script_dir}/test_payload_manifest_normalization.py" \
  >> "$preflight_log" 2>&1

residual_dir="${preflight_dir}/residual-authority"
python3 "${script_dir}/materialize_residual_authority.py" \
  --output-dir "$residual_dir" \
  --report "${preflight_dir}/RESIDUAL_AUTHORITY.txt" \
  >> "$preflight_log" 2>&1

actual_source_commit="$(git -C "$source_root" rev-parse HEAD)"
actual_perl_commit="$(git -C "$authority_root" rev-parse HEAD)"
source_status="$(git -C "$source_root" status --porcelain)"
if [[ "$actual_source_commit" != "$expected_commit" ||
      "$actual_perl_commit" != "$perl_commit" ||
      -n "$source_status" ]]; then
  {
    printf 'actual_source_commit: %s\n' "$actual_source_commit"
    printf 'actual_perl_commit: %s\n' "$actual_perl_commit"
    printf 'source_status: %s\n' "${source_status:-<empty>}"
  } >> "$preflight_log"
  exit 65
fi

python3 "${script_dir}/verify_authority.py" \
  --perl-root "$authority_root" \
  --residual-dir "$residual_dir" \
  --report "${preflight_dir}/AUTHORITY_SHA256.tsv" \
  >> "$preflight_log" 2>&1
printf 'preflight_status: PASS\n' >> "$preflight_log"

evidence_dir="${runner_temp}/splitalignerr-rc-evidence-${runner_os}-${runner_arch}"
if [[ -e "$evidence_dir" ]]; then
  echo "refusing to overwrite evidence directory: $evidence_dir" >&2
  exit 73
fi
mkdir -p "$evidence_dir"
cp "${preflight_dir}/PRECHECK.log" "$evidence_dir/"
cp "${preflight_dir}/DEPENDENCIES.tsv" "$evidence_dir/"
cp "${preflight_dir}/RESIDUAL_AUTHORITY.txt" "$evidence_dir/"
cp "${preflight_dir}/AUTHORITY_SHA256.tsv" "$evidence_dir/"

run_logged() {
  local label="$1"
  local cwd="$2"
  shift 2
  local log="${evidence_dir}/${label}.log"
  {
    printf 'working_directory: %s\n' "$cwd"
    printf 'command:'
    printf ' %q' "$@"
    printf '\n'
  } > "$log"
  set +e
  (cd "$cwd" && "$@") >> "$log" 2>&1
  local status=$?
  set -e
  printf 'exit_status: %s\n' "$status" >> "$log"
  if [[ $status -ne 0 ]]; then
    echo "FAILED: $label" >&2
    return "$status"
  fi
}

{
  printf 'workflow: %s\n' "${GITHUB_WORKFLOW:-local}"
  printf 'workflow_ref: %s\n' "${GITHUB_WORKFLOW_REF:-local}"
  printf 'workflow_sha: %s\n' "${GITHUB_WORKFLOW_SHA:-$expected_commit}"
  printf 'run_id: %s\n' "${GITHUB_RUN_ID:-NOT_AVAILABLE}"
  printf 'run_attempt: %s\n' "${GITHUB_RUN_ATTEMPT:-NOT_AVAILABLE}"
  printf 'job_key: %s\n' "${GITHUB_JOB:-NOT_AVAILABLE}"
  printf 'runner_name: %s\n' "${RUNNER_NAME:-NOT_AVAILABLE}"
  printf 'runner_os: %s\n' "$runner_os"
  printf 'runner_arch: %s\n' "$runner_arch"
  printf 'kernel: '
  uname -a
  printf 'source_commit: %s\n' "$actual_source_commit"
  printf 'authority_commit: %s\n' "$actual_perl_commit"
  printf 'selected_utf8_locale: %s\n' "$selected_locale"
  printf 'R: '
  R --version 2>&1 | sed -n '1p'
  printf 'R_platform: '
  Rscript -e 'cat(R.version$platform, "\n", sep = "")'
  printf '%s\n' "$r_locale_report"
  printf 'CXX17: %s\n' "$cxx17"
  printf 'CXX17STD: %s\n' "$(R CMD config CXX17STD)"
} > "${evidence_dir}/ENVIRONMENT.txt"

source_commit_tar="${runner_temp}/SplitAlignerR-source-${expected_commit}.tar"
run_logged "00_archive_exact_source_commit" "$source_root" \
  git archive --format=tar --output="$source_commit_tar" "$expected_commit"
source_commit_tar_for_tar="$source_commit_tar"
if [[ "$runner_os" == "Windows" ]]; then
  source_commit_tar_for_tar="$(cygpath -u "$source_commit_tar")"
fi
python3 - "$source_commit_tar" \
  > "${evidence_dir}/SOURCE_COMMIT_ARCHIVE_SHA256.txt" <<'PY'
import hashlib
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"{digest}  {path.name}")
PY

materialize_source_snapshot() {
  local label="$1"
  local destination="$2"
  local destination_for_tar="$destination"
  mkdir -p "$destination"
  if [[ "$runner_os" == "Windows" ]]; then
    destination_for_tar="$(cygpath -u "$destination")"
  fi
  run_logged "$label" "$runner_temp" \
    tar -xf "$source_commit_tar_for_tar" -C "$destination_for_tar"
}

build_dir="$(mktemp -d "${runner_temp}/splitalignerr-rc-build.XXXXXX")"
build_source="$(mktemp -d "${runner_temp}/splitalignerr-rc-source-build.XXXXXX")"
materialize_source_snapshot "00_extract_source_for_build" "$build_source"
run_logged "01_build_source" "$build_dir" R CMD build "$build_source"
shopt -s nullglob
built_tars=("${build_dir}"/SplitAlignerR_*.tar.gz)
shopt -u nullglob
if [[ ${#built_tars[@]} -ne 1 ]]; then
  echo "expected exactly one newly built source tar" >&2
  exit 65
fi
built_tar="${built_tars[0]}"
cp "$built_tar" "$evidence_dir/"
python3 "${script_dir}/payload_manifest.py" \
  --tar "$built_tar" --output "${evidence_dir}/SOURCE_PAYLOAD_MANIFEST.tsv"
python3 - "$built_tar" > "${evidence_dir}/BUILT_TAR_SHA256.txt" <<'PY'
import hashlib
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"{digest}  {path.name}")
PY

repeat_build_dir="$(mktemp -d "${runner_temp}/splitalignerr-rc-repeat-build.XXXXXX")"
repeat_build_source="$(mktemp -d "${runner_temp}/splitalignerr-rc-source-repeat-build.XXXXXX")"
materialize_source_snapshot \
  "00_extract_source_for_repeat_build" "$repeat_build_source"
run_logged "02_repeat_build_source" "$repeat_build_dir" \
  R CMD build "$repeat_build_source"
shopt -s nullglob
repeat_built_tars=("${repeat_build_dir}"/SplitAlignerR_*.tar.gz)
shopt -u nullglob
if [[ ${#repeat_built_tars[@]} -ne 1 ]]; then
  echo "expected exactly one repeat-built source tar" >&2
  exit 65
fi
repeat_built_tar="${repeat_built_tars[0]}"
cp "$repeat_built_tar" \
  "${evidence_dir}/SplitAlignerR_0.1.0.repeat-build.tar.gz"
python3 "${script_dir}/payload_manifest.py" \
  --tar "$repeat_built_tar" \
  --output "${evidence_dir}/SOURCE_PAYLOAD_MANIFEST_REPEAT.tsv"
python3 - "$repeat_built_tar" \
  > "${evidence_dir}/REPEAT_BUILT_TAR_SHA256.txt" <<'PY'
import hashlib
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
digest = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"{digest}  {path.name}")
PY
run_logged "03_compare_repeat_payloads" "$runner_temp" python3 \
  "${script_dir}/compare_payload_manifests.py" \
  --first "${evidence_dir}/SOURCE_PAYLOAD_MANIFEST.tsv" \
  --second "${evidence_dir}/SOURCE_PAYLOAD_MANIFEST_REPEAT.tsv" \
  --report "${evidence_dir}/REPEAT_BUILD_PAYLOAD_COMPARISON.txt"

check_dir="$(mktemp -d "${runner_temp}/splitalignerr-rc-check.XXXXXX")"
authority_302="${authority_root}/examples/302mammal"
authority_2275="${authority_root}/examples/preprint_302mammal/input"
run_logged "04_check_exact_tar_bundled_and_302" "$check_dir" \
  env \
  "SPLITALIGNERR_302MAMMAL_DIR=${authority_302}" \
  R CMD check --no-manual "$built_tar"
cp -R "${check_dir}/SplitAlignerR.Rcheck" "${evidence_dir}/R_CMD_CHECK"

install_lib_one="$(mktemp -d "${runner_temp}/splitalignerr-rc-lib-one.XXXXXX")"
run_logged "05_install_exact_tar_with_tests" "$runner_temp" \
  R CMD INSTALL --install-tests --library="$install_lib_one" "$built_tar"
run_logged "06_installed_package_tests_bundled_and_302" "$runner_temp" \
  env \
  "R_LIBS=${install_lib_one}" \
  "SPLITALIGNERR_302MAMMAL_DIR=${authority_302}" \
  Rscript -e \
  'library(testthat); test_package("SplitAlignerR", reporter = "summary")'

source_test_snapshot="$(mktemp -d "${runner_temp}/splitalignerr-rc-source-tests.XXXXXX")"
materialize_source_snapshot \
  "00_extract_source_for_source_root_tests" "$source_test_snapshot"
run_logged "07_source_root_tests_bundled_and_302" "$source_test_snapshot" \
  env \
  "SPLITALIGNERR_302MAMMAL_DIR=${authority_302}" \
  Rscript -e \
  'testthat::test_local(".", reporter = "summary")'

install_lib_two="$(mktemp -d "${runner_temp}/splitalignerr-rc-lib-two.XXXXXX")"
run_logged "08_repeat_clean_install" "$runner_temp" \
  R CMD INSTALL --library="$install_lib_two" "$built_tar"
run_logged "09_repeat_install_identity" "$runner_temp" \
  env "R_LIBS=${install_lib_two}" Rscript -e \
  'library(SplitAlignerR); stopifnot(as.character(packageVersion("SplitAlignerR")) == "0.1.0"); print(splitaligner_core_info())'

run_logged "10_release_metadata_consistency" "$runner_temp" \
  env "R_LIBS=${install_lib_one}" Rscript \
  "${script_dir}/release_metadata_gate.R" "$source_root" \
  "${evidence_dir}/RELEASE_METADATA_GATE.tsv"

run_logged "11_performance_benchmark" "$runner_temp" \
  env "R_LIBS=${install_lib_one}" Rscript \
  "${script_dir}/performance_benchmark.R" "$source_root" \
  "${evidence_dir}/PERFORMANCE_BENCHMARK"

run_logged "12_full_residual_authority_chunked" "$runner_temp" \
  env "R_LIBS=${install_lib_one}" Rscript \
  "${script_dir}/full_residual_authority.R" \
  "${authority_2275}/speciesTree302.nwk" \
  "${authority_2275}/fix.2275genes.nwk" \
  "${authority_2275}/free.2275genes.nwk" \
  "${residual_dir}/01_residual_NA_cell_ledger.tsv" \
  "${evidence_dir}/RESIDUAL_407_OBSERVED.tsv" \
  "${evidence_dir}/RESIDUAL_407_SUMMARY.txt" \
  "$authority_chunk_size"

run_logged "13_determinism_three_runs_and_input_order" "$runner_temp" \
  env "R_LIBS=${install_lib_one}" Rscript \
  "${script_dir}/determinism.R" "$authority_302" \
  "${evidence_dir}/DETERMINISM.txt"

run_logged "14_clean_source_after_all_gates" "$source_root" \
  git status --porcelain
if [[ -n "$(git -C "$source_root" status --porcelain)" ]]; then
  echo "source working tree is dirty after gates" >&2
  exit 65
fi

{
  printf 'source_materialized_from_expected_commit_archive: PASS\n'
  printf 'build_exact_source_tar: PASS\n'
  printf 'repeat_build_payload_identity: PASS\n'
  printf 'check_exact_source_tar_bundled_and_302: PASS\n'
  printf 'installed_package_tests_bundled_and_302: PASS\n'
  printf 'source_root_tests_bundled_and_302: PASS\n'
  printf 'documentation_examples_and_vignette: PASS via R CMD check\n'
  printf 'repeat_clean_install: PASS\n'
  printf 'release_metadata_consistency_gate: PASS\n'
  printf 'citation_metadata_gate: PASS via release metadata gate\n'
  printf 'gene_id_hardening_tests: PASS via bundled tests\n'
  printf 'catnip10_failure_classification_tests: PASS via bundled tests\n'
  printf 'oracle_locale_independence_tests: PASS via bundled tests\n'
  printf 'recursive_depth_probe: ISOLATED IN DEDICATED PLATFORM JOB\n'
  printf 'performance_benchmark: PASS; see PERFORMANCE_BENCHMARK\n'
  printf 'full_2275_residual_authority_chunked: PASS\n'
  printf 'determinism_three_runs: PASS\n'
  printf 'input_order_canonicalization: PASS\n'
  printf 'parallel_serial: NOT APPLICABLE\n'
  printf 'source_checkout_immutable_after_gates: PASS\n'
  printf 'overall_status: PASS\n'
  printf 'finished_utc: '
  date -u '+%Y-%m-%dT%H:%M:%SZ'
} > "${evidence_dir}/RUN_SUMMARY.txt"
