#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: run_deep_tree_job.sh SOURCE_ROOT EXPECTED_COMMIT" >&2
  exit 64
fi

source_root="$(cd "$1" && pwd)"
expected_commit="$2"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runner_temp="${RUNNER_TEMP:?RUNNER_TEMP is required}"
runner_os="${RUNNER_OS:-unknown-os}"
runner_arch="${RUNNER_ARCH:-unknown-arch}"

evidence_dir="${runner_temp}/splitalignerr-deep-tree-evidence-${runner_os}-${runner_arch}"
artifact_dir="${runner_temp}/splitalignerr-deep-tree-artifacts"
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
  if [[ -d "$evidence_dir" && ! -f "${evidence_dir}/RUN_SUMMARY.txt" ]]; then
    {
      printf 'source_commit: %s\n' "$expected_commit"
      printf 'recursive_depth_probe: FAILED; see DEEP_TREE_PROBE and logs\n'
      printf 'overall_status: FAILED\n'
      printf 'exit_status: %s\n' "$status"
    } > "${evidence_dir}/RUN_SUMMARY.txt"
  fi
  if [[ -d "$evidence_dir" ]]; then
    mkdir -p "$artifact_dir"
    artifact_zip="${artifact_dir}/SplitAlignerR_deep_tree_evidence_${runner_os}_${runner_arch}.zip"
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

if [[ -e "$evidence_dir" ]]; then
  echo "refusing to overwrite evidence directory: $evidence_dir" >&2
  exit 73
fi
mkdir -p "$evidence_dir"

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

for command_name in R Rscript python3 git tar gzip; do
  command -v "$command_name" >> "${evidence_dir}/PRECHECK.log" 2>&1 || {
    printf 'missing_command: %s\n' "$command_name" >> "${evidence_dir}/PRECHECK.log"
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
printf 'source_identity_and_cleanliness: PASS\n' >> "${evidence_dir}/PRECHECK.log"

{
  printf 'workflow: %s\n' "${GITHUB_WORKFLOW:-local}"
  printf 'run_id: %s\n' "${GITHUB_RUN_ID:-NOT_AVAILABLE}"
  printf 'run_attempt: %s\n' "${GITHUB_RUN_ATTEMPT:-NOT_AVAILABLE}"
  printf 'runner_name: %s\n' "${RUNNER_NAME:-NOT_AVAILABLE}"
  printf 'runner_os: %s\n' "$runner_os"
  printf 'runner_arch: %s\n' "$runner_arch"
  printf 'source_commit: %s\n' "$actual_commit"
  printf 'kernel: '
  uname -a
  printf 'R: '
  R --version 2>&1 | sed -n '1p'
  printf 'R_platform: '
  Rscript -e 'cat(R.version$platform, "\n", sep = "")'
  printf 'CXX17: %s\n' "$(R CMD config CXX17)"
} > "${evidence_dir}/ENVIRONMENT.txt"

build_dir="$(mktemp -d "${runner_temp}/splitalignerr-deep-tree-build.XXXXXX")"
run_logged "01_build_clean_source" "$build_dir" \
  R CMD build --no-build-vignettes "$source_root"
shopt -s nullglob
built_tars=("${build_dir}"/SplitAlignerR_*.tar.gz)
shopt -u nullglob
if [[ ${#built_tars[@]} -ne 1 ]]; then
  echo "expected exactly one newly built source tar" >&2
  exit 65
fi
built_tar="${built_tars[0]}"
python3 - "$built_tar" > "${evidence_dir}/BUILT_TAR_SHA256.txt" <<'PY'
import hashlib
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
PY

install_lib="$(mktemp -d "${runner_temp}/splitalignerr-deep-tree-lib.XXXXXX")"
run_logged "02_install_clean_source_tar" "$runner_temp" \
  R CMD INSTALL --library="$install_lib" "$built_tar"
library_path_separator="$(Rscript -e 'cat(.Platform$path.sep)')"
existing_libraries="$(Rscript -e 'cat(paste(.libPaths(), collapse = .Platform$path.sep))')"
probe_libraries="${install_lib}${library_path_separator}${existing_libraries}"
run_logged "03_recursive_depth_probe" "$runner_temp" \
  env "R_LIBS=${probe_libraries}" python3 -B \
  "${script_dir}/deep_tree_probe.py" "$source_root" \
  "${evidence_dir}/DEEP_TREE_PROBE"
run_logged "04_verify_deep_tree_evidence" "$source_root" \
  python3 -B "${script_dir}/verify_deep_tree_evidence.py" \
  "${evidence_dir}/DEEP_TREE_PROBE"
run_logged "05_clean_source_after_probe" "$source_root" git status --porcelain
if [[ -n "$(git -C "$source_root" status --porcelain)" ]]; then
  echo "source working tree is dirty after deep-tree probe" >&2
  exit 65
fi

{
  printf 'source_commit: %s\n' "$actual_commit"
  printf 'clean_source_build_and_install: PASS\n'
  printf 'recursive_depth_probe: PASS; see DEEP_TREE_PROBE\n'
  printf 'source_checkout_immutable_after_probe: PASS\n'
  printf 'overall_status: PASS\n'
  printf 'finished_utc: '
  date -u '+%Y-%m-%dT%H:%M:%SZ'
} > "${evidence_dir}/RUN_SUMMARY.txt"
