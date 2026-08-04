#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: run_fix001a_platform.sh <repo> <authority-examples> <evidence-dir> <platform-key>" >&2
  exit 64
fi

repo="$1"
authority_examples="$2"
evidence="$3"
platform_key="$4"
mkdir -p "$evidence"

export NOT_CRAN=true
export R_KEEP_PKG_SOURCE=yes

{
  echo "platform_key=$platform_key"
  echo "github_sha=${GITHUB_SHA:-LOCAL}"
  echo "runner_os=${RUNNER_OS:-LOCAL}"
  echo "runner_arch=${RUNNER_ARCH:-UNKNOWN}"
  echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  git -C "$repo" status --short --branch
  git -C "$repo" rev-parse HEAD
  git -C "$repo" rev-parse 'HEAD^{tree}'
} > "$evidence/repo_state.txt"

Rscript -e 'sessionInfo()' > "$evidence/session_info.txt" 2>&1
{
  R CMD config CC
  R CMD config CXX17
  R CMD config CXX17FLAGS
  R CMD config SHLIB_CXX17LD || true
  R CMD config SHLIB_CXX17LDFLAGS || true
} > "$evidence/compiler_info.txt" 2>&1

build_work="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fix001a-build-${platform_key}"
mkdir -p "$build_work"
cd "$build_work"
build_started=$SECONDS
R CMD build --no-manual "$repo" 2>&1 | tee "$evidence/R_CMD_build.log"
build_seconds=$((SECONDS - build_started))
tarball="$(find "$build_work" -maxdepth 1 -type f -name 'SplitAlignerR_*.tar.gz' -print -quit)"
if [[ -z "$tarball" ]]; then
  echo "installable source archive not found" >&2
  exit 1
fi

check_started=$SECONDS
R CMD check --no-manual "$tarball" 2>&1 | tee "$evidence/R_CMD_check.log"
check_seconds=$((SECONDS - check_started))
if [[ -f SplitAlignerR.Rcheck/00check.log ]]; then
  cp SplitAlignerR.Rcheck/00check.log "$evidence/00check.log"
fi

library_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fix001a-library-${platform_key}"
mkdir -p "$library_dir"
R CMD INSTALL --install-tests --library="$library_dir" "$tarball" \
  2>&1 | tee "$evidence/R_CMD_INSTALL.log"

Rscript "$repo/tools/engine002/fix001a_testthat.R" \
  "$library_dir" "$evidence/testthat_results.txt" \
  2>&1 | tee "$evidence/testthat_console.log"

Rscript "$repo/tools/engine002/fix001a_platform_evidence.R" \
  "$repo" "$library_dir" "$authority_examples" "$evidence" "$platform_key" \
  2>&1 | tee "$evidence/platform_console.log"

{
  echo "platform_key=$platform_key"
  echo "package_build_seconds=$build_seconds"
  echo "package_check_seconds=$check_seconds"
  echo "completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$evidence/package_timings.txt"

python3 "$repo/tools/engine002/fix001a_sha256.py" \
  --root "$evidence" --output "$evidence/SHA256SUMS"

echo "ENGINE002_FIX001A_PLATFORM_PASS platform=$platform_key"
