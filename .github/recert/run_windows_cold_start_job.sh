#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: run_windows_cold_start_job.sh SOURCE_ROOT EXPECTED_COMMIT" >&2
  exit 64
fi

source_root="$(cd "$1" && pwd)"
expected_commit="$2"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runner_temp="${RUNNER_TEMP:?RUNNER_TEMP is required}"
runner_os="${RUNNER_OS:-unknown-os}"
runner_arch="${RUNNER_ARCH:-unknown-arch}"
timeout_seconds="${SPLITALIGNERR_COLD_START_TIMEOUT_SECONDS:-900}"
evidence_dir="${runner_temp}/splitalignerr-windows-cold-start-${runner_os}-${runner_arch}"
artifact_dir="${runner_temp}/splitalignerr-windows-cold-start-artifacts"
artifact_zip=""
artifact_sidecar=""

if [[ -e "$evidence_dir" ]]; then
  echo "refusing to overwrite evidence directory: $evidence_dir" >&2
  exit 73
fi
mkdir -p "$evidence_dir"

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
  if [[ $status -ne 0 && ! -f "${evidence_dir}/RUN_SUMMARY.txt" ]]; then
    {
      printf 'source_commit: %s\n' "$expected_commit"
      printf 'diagnostic_evidence_capture: FAILED\n'
      printf 'exit_status: %s\n' "$status"
      printf 'overall_status: FAILED\n'
    } > "${evidence_dir}/RUN_SUMMARY.txt"
  fi
  mkdir -p "$artifact_dir"
  artifact_zip="${artifact_dir}/SplitAlignerR_windows_cold_start_${runner_os}_${runner_arch}.zip"
  artifact_sidecar="${artifact_zip}.sha256"
  python3 -B "${script_dir}/package_evidence.py" \
    --input-dir "$evidence_dir" --output-zip "$artifact_zip"
  packaging_status=$?
  if [[ $packaging_status -eq 0 ]]; then
    emit_outputs
  elif [[ $status -eq 0 ]]; then
    status=$packaging_status
  fi
  exit "$status"
}
trap finalize EXIT

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

required_commands=(R Rscript python3 git tar)
if [[ "$runner_os" == "Windows" ]]; then
  required_commands+=(cygpath taskkill)
fi
for command_name in "${required_commands[@]}"; do
  command -v "$command_name" >> "${evidence_dir}/PRECHECK.log" 2>&1 || {
    printf 'missing_command: %s\n' "$command_name" \
      >> "${evidence_dir}/PRECHECK.log"
    exit 69
  }
done

actual_commit="$(git -C "$source_root" rev-parse HEAD)"
source_status="$(git -C "$source_root" status --porcelain)"
if [[ "$actual_commit" != "$expected_commit" || -n "$source_status" ]]; then
  {
    printf 'expected_commit: %s\n' "$expected_commit"
    printf 'actual_commit: %s\n' "$actual_commit"
    printf 'source_status: %s\n' "${source_status:-<empty>}"
  } >> "${evidence_dir}/PRECHECK.log"
  exit 65
fi
printf 'precheck_status: PASS\n' >> "${evidence_dir}/PRECHECK.log"

cxx17="$(R CMD config CXX17)"
cxx17std="$(R CMD config CXX17STD)"
{
  printf 'workflow: %s\n' "${GITHUB_WORKFLOW:-local}"
  printf 'workflow_ref: %s\n' "${GITHUB_WORKFLOW_REF:-local}"
  printf 'workflow_sha: %s\n' "${GITHUB_WORKFLOW_SHA:-$expected_commit}"
  printf 'run_id: %s\n' "${GITHUB_RUN_ID:-NOT_AVAILABLE}"
  printf 'run_attempt: %s\n' "${GITHUB_RUN_ATTEMPT:-NOT_AVAILABLE}"
  printf 'runner_name: %s\n' "${RUNNER_NAME:-NOT_AVAILABLE}"
  printf 'runner_os: %s\n' "$runner_os"
  printf 'runner_arch: %s\n' "$runner_arch"
  printf 'kernel: '
  uname -a
  printf 'source_commit: %s\n' "$actual_commit"
  printf 'per_case_timeout_seconds: %s\n' "$timeout_seconds"
  printf 'R: '
  R --version 2>&1 | sed -n '1p'
  printf 'R_platform: '
  Rscript -e 'cat(R.version$platform, "\n", sep = "")'
  printf 'CXX17: %s\n' "$cxx17"
  printf 'CXX17STD: %s\n' "$cxx17std"
} > "${evidence_dir}/ENVIRONMENT.txt"

source_tar="${runner_temp}/SplitAlignerR-cold-start-${expected_commit}.tar"
run_logged "01_archive_exact_source" "$source_root" \
  git archive --format=tar --output="$source_tar" "$expected_commit"

snapshot="$(mktemp -d "${runner_temp}/splitalignerr-cold-source.XXXXXX")"
source_tar_for_tar="$source_tar"
snapshot_for_tar="$snapshot"
if [[ "$runner_os" == "Windows" ]]; then
  source_tar_for_tar="$(cygpath -u "$source_tar")"
  snapshot_for_tar="$(cygpath -u "$snapshot")"
fi
run_logged "02_extract_exact_source" "$runner_temp" \
  tar -xf "$source_tar_for_tar" -C "$snapshot_for_tar"

build_dir="$(mktemp -d "${runner_temp}/splitalignerr-cold-build.XXXXXX")"
run_logged "03_build_exact_source" "$build_dir" R CMD build "$snapshot"
shopt -s nullglob
built_tars=("${build_dir}"/SplitAlignerR_*.tar.gz)
shopt -u nullglob
if [[ ${#built_tars[@]} -ne 1 ]]; then
  echo "expected exactly one built source tar" >&2
  exit 65
fi
built_tar="${built_tars[0]}"
cp "$built_tar" "$evidence_dir/"

install_lib="$(mktemp -d "${runner_temp}/splitalignerr-cold-lib.XXXXXX")"
run_logged "04_install_exact_source" "$runner_temp" \
  R CMD INSTALL --library="$install_lib" "$built_tar"

microprobe_source="${snapshot}/.github/recert/windows_numeric_microprobe.cpp"
numeric_source="${snapshot}/src/numeric_policy.cpp"
include_dir="${snapshot}/src"
microprobe_exe="${evidence_dir}/windows_numeric_microprobe"
if [[ "$runner_os" == "Windows" ]]; then
  microprobe_exe="${microprobe_exe}.exe"
fi
cp "$microprobe_source" "${evidence_dir}/windows_numeric_microprobe.cpp"

compile_microprobe_source="$microprobe_source"
compile_numeric_source="$numeric_source"
compile_include_dir="$include_dir"
compile_microprobe_exe="$microprobe_exe"
if [[ "$runner_os" == "Windows" ]]; then
  compile_microprobe_source="$(cygpath -u "$microprobe_source")"
  compile_numeric_source="$(cygpath -u "$numeric_source")"
  compile_include_dir="$(cygpath -u "$include_dir")"
  compile_microprobe_exe="$(cygpath -u "$microprobe_exe")"
fi
read -r -a cxx_command <<< "$cxx17"
read -r -a cxxstd_flags <<< "$cxx17std"
compile_command=(
  "${cxx_command[@]}" "${cxxstd_flags[@]}" -O0
  "-I${compile_include_dir}"
  "$compile_microprobe_source" "$compile_numeric_source"
  -o "$compile_microprobe_exe"
)
{
  printf 'working_directory: %s\n' "$snapshot"
  printf 'command:'
  printf ' %q' "${compile_command[@]}"
  printf '\n'
} > "${evidence_dir}/05_compile_standalone_microprobe.log"
set +e
(cd "$snapshot" && "${compile_command[@]}") \
  >> "${evidence_dir}/05_compile_standalone_microprobe.log" 2>&1
compile_status=$?
set -e
printf 'exit_status: %s\n' "$compile_status" \
  >> "${evidence_dir}/05_compile_standalone_microprobe.log"
if [[ $compile_status -ne 0 || ! -f "$microprobe_exe" ]]; then
  exit 65
fi
python3 -c \
  'import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); print(hashlib.sha256(p.read_bytes()).hexdigest(), p.name)' \
  "$microprobe_exe" > "${evidence_dir}/MICROPROBE_BINARY_SHA256.txt"

probe_status=0
env \
  "R_LIBS=${install_lib}" \
  "SPLITALIGNERR_COLD_START_MICROPROBE=${microprobe_exe}" \
  "SPLITALIGNERR_COLD_START_TIMEOUT_SECONDS=${timeout_seconds}" \
  python3 -B "${snapshot}/.github/recert/windows_cold_start_probe.py" \
  "$snapshot" "${evidence_dir}/COLD_START_PROBE" \
  > "${evidence_dir}/06_windows_cold_start_probe.log" 2>&1 || probe_status=$?
printf 'exit_status: %s\n' "$probe_status" \
  >> "${evidence_dir}/06_windows_cold_start_probe.log"
if [[ $probe_status -ne 0 ]]; then
  exit "$probe_status"
fi

run_logged "07_verify_windows_cold_start_evidence" "$snapshot" \
  python3 -B \
  "${snapshot}/.github/recert/verify_windows_cold_start_evidence.py" \
  "${evidence_dir}/COLD_START_PROBE"

run_logged "08_clean_source_after_diagnosis" "$source_root" \
  git status --porcelain
if [[ -n "$(git -C "$source_root" status --porcelain)" ]]; then
  echo "source working tree is dirty after cold-start diagnosis" >&2
  exit 65
fi

{
  printf 'source_commit: %s\n' "$actual_commit"
  printf 'exact_source_build_and_install: PASS\n'
  printf 'standalone_microprobe_build: PASS\n'
  printf 'fresh_process_case_schedule: 8/8 CAPTURED\n'
  printf 'cold_start_evidence_integrity: PASS\n'
  printf 'source_checkout_immutable_after_diagnosis: PASS\n'
  printf 'root_cause_interpretation: DEFERRED_TO_MAIN_CONSOLE_REVIEW\n'
  printf 'overall_status: EVIDENCE_CAPTURED\n'
  printf 'finished_utc: '
  date -u '+%Y-%m-%dT%H:%M:%SZ'
} > "${evidence_dir}/RUN_SUMMARY.txt"
