#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: run_fix001b_platform.sh <repo> <authority-examples> <evidence-dir> <platform-key>" >&2
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

build_work="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fix001b-build-${platform_key}"
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

library_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fix001b-library-${platform_key}"
mkdir -p "$library_dir"
R CMD INSTALL --install-tests --library="$library_dir" "$tarball" \
  2>&1 | tee "$evidence/R_CMD_INSTALL.log"

Rscript "$repo/tools/engine002/fix001a_testthat.R" \
  "$library_dir" "$evidence/testthat_results.txt" \
  2>&1 | tee "$evidence/testthat_console.log"

Rscript "$repo/tools/engine002/fix001a_platform_evidence.R" \
  "$repo" "$library_dir" "$authority_examples" "$evidence" "$platform_key" \
  2>&1 | tee "$evidence/platform_console.log"

read -r -a cxx_command <<< "$(R CMD config CXX17)"
"${cxx_command[@]}" -std=c++17 -Wall -Wextra -Werror -pedantic -I"$repo/src" \
  "$repo/dev/ENGINE002-FIX001B/pro_original/SAR_PRO_ENGINE002_FIX001A_SHA256_MRE_20260804.cpp" \
  "$repo/src/engine002_hash.cpp" -o "$build_work/pro_sha_mre"
"$build_work/pro_sha_mre" | tee "$evidence/PRO_MRE_REPAIRED_RESULTS.txt"
expected_abc="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
grep -Fx "one_shot=$expected_abc" "$evidence/PRO_MRE_REPAIRED_RESULTS.txt"
grep -Fx "single_update=$expected_abc" "$evidence/PRO_MRE_REPAIRED_RESULTS.txt"
grep -Fx "three_updates=$expected_abc" "$evidence/PRO_MRE_REPAIRED_RESULTS.txt"

"${cxx_command[@]}" -std=c++17 -Wall -Wextra -Werror -pedantic -I"$repo/src" \
  "$repo/tools/engine002/fix001b_sha_probe.cpp" \
  "$repo/src/engine002_hash.cpp" -o "$build_work/fix001b_sha_probe"
python3 "$repo/dev/ENGINE002-FIX001B/independent/partition_differential.py" \
  --probe "$build_work/fix001b_sha_probe" \
  --output-dir "$evidence/partition_differential" \
  --random-cases 10000

python3 "$repo/dev/ENGINE002-FIX001B/independent/payload_aggregate_check.py" \
  "$evidence/golden_store.bin" \
  "$evidence/authority_store.bin" \
  "$evidence/stress_store.bin" \
  --output "$evidence/INDEPENDENT_AGGREGATE_RESULTS.txt"
python3 "$repo/dev/ENGINE002-FIX001B/independent/payload_aggregate_check.py" \
  "$repo/tests/testthat/fixtures/engine002/history/fix1a_bad_aggregate.bin" \
  --allow-mismatch --output "$evidence/OLD_GOLDEN_INDEPENDENT_RESULTS.txt"
python3 "$repo/dev/ENGINE002-FIX001B/independent/store_tamper.py" \
  --component "$evidence/golden_store.bin" \
  --manifest "$evidence/golden_store.manifest" \
  --output-dir "$evidence/targeted_tamper" \
  --report "$evidence/AGGREGATE_ONLY_TAMPER_RESULTS.txt"
Rscript "$repo/tools/engine002/fix001b_targeted_validator.R" \
  "$repo" "$library_dir" "$evidence/TARGETED_VALIDATOR_RESULTS.txt" \
  2>&1 | tee "$evidence/targeted_validator_console.log"

{
  echo "platform_key=$platform_key"
  echo "package_build_seconds=$build_seconds"
  echo "package_check_seconds=$check_seconds"
  echo "completed_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$evidence/package_timings.txt"

python3 "$repo/tools/engine002/fix001a_sha256.py" \
  --root "$evidence" --output "$evidence/SHA256SUMS"

echo "ENGINE002_FIX001B_PLATFORM_PASS platform=$platform_key"
