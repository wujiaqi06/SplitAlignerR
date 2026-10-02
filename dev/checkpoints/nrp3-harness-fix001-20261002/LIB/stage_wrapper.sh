#!/bin/bash
# NRP3_HARNESS_IMPL001 controller-side per-run wrapper (test infrastructure).
# Repair FIX001: STAGE_ROOT relocated to the FIX001 stage (fixed literal, not
# configurable); run ids I1..I3 only (no I0 reset); the invocation budget is
# CUMULATIVE: 32 wrapped calls were made in the previous stage (their RUNS stay
# there), so the first invocation here is cumulative index 33 and the limit of
# 128 leaves at most 96 here.  Every invocation that creates RUNS/<run_id>
# counts, including a preflight refusal or a failed run.
#
# Usage: stage_wrapper.sh <run_id> <enumerate|run> [<manifest-name>]
#
# Runs OUTSIDE the guarded child and is the only writer of RUNS/<run_id>/
# outside tmp.  Append-only: an existing RUNS/<run_id> is refused; nothing in
# RUNS is ever removed, renamed or rewritten.  The launcher receives only
# --run-id/--step/--manifest-name (no path argument).  Serial; no affinity or
# priority change; single-thread environment.  The evidence helper below is
# plain bookkeeping (hashes, listings, strict-JSON checks) run with
# /usr/bin/python3.10 -B -I -S; it imports no project file.
set -u
STAGE_ROOT='/home/jiaqi/Documents/work/SplitAligner/SplitAlignerR/ENGINE003_LINUXPORT001_development_20260908_JST/DEV_NRP3_HARNESS_IMPL001_FIX001_OPUS55_20261002'
HELPER_PY='/usr/bin/python3.10'
RUN_ID="${1:-}"
STEP="${2:-}"
MANIFEST_NAME="${3:-}"
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "WRAPPER_REFUSED:ARGUMENT_COUNT" >&2
    exit 64
fi
if ! [[ "$RUN_ID" =~ ^I[1-3]_(ENUM|U|H[IB][0-9]{2})_py(38|310)$ ]]; then
    echo "WRAPPER_REFUSED:RUN_ID" >&2
    exit 64
fi
case "$RUN_ID" in
    *_py310) PY='/usr/bin/python3.10' ;;
    *_py38) PY='/usr/bin/python3.8' ;;
    *) echo "WRAPPER_REFUSED:INTERPRETER" >&2; exit 64 ;;
esac
case "$STEP" in
    enumerate) [ -z "$MANIFEST_NAME" ] || { echo "WRAPPER_REFUSED:ENUMERATE_TAKES_NO_MANIFEST" >&2; exit 64; } ;;
    run) [[ "$MANIFEST_NAME" =~ ^MANIFEST_(U|H[IB][0-9]{2})\.json$ ]] || { echo "WRAPPER_REFUSED:MANIFEST_NAME" >&2; exit 64; } ;;
    *) echo "WRAPPER_REFUSED:STEP" >&2; exit 64 ;;
esac
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
RUN_DIR="$STAGE_ROOT/RUNS/$RUN_ID"

read -r -d '' HELPER <<'PYEOF'
import hashlib, json, os, stat, sys, time

phase, stage, run_id, step, manifest_name, py = sys.argv[1:7]
run_dir = os.path.join(stage, "RUNS", run_id)
tmp = os.path.join(run_dir, "tmp")
NEW_FILES = ["HARNESS/nrp3_root_canary_harness.py", "HARNESS/test_nrp3_harness.py",
             "LIB/harness_guard_aux.py", "LIB/run_pure_harness.py", "LIB/stage_wrapper.sh"]
PINS = {"LIB/pure_guard.py": "a775347eae114020c1563ab36706e08a86f7cd7e064df4fac616211f7dead077",
        "LIB/run_pure.py": "1642e9453246fa445df246850517233d2ef29bebab8d8b76fcdbc4953585a161"}
LISTING = {"HARNESS": ["nrp3_root_canary_harness.py", "test_nrp3_harness.py"],
           "LIB": ["harness_guard_aux.py", "pure_guard.py", "run_pure.py",
                   "run_pure_harness.py", "stage_wrapper.sh"]}
MAX_INVOCATIONS = 128                 # cumulative, across the previous stage and this one
PRIOR_WRAPPED_CALLS = 32              # fixed carry; INPUTS/CUMULATIVE_BUDGET.json must agree
BUDGET_FILE = "INPUTS/CUMULATIVE_BUDGET.json"
BUDGET_SHA256 = "9fbdaccba7370b2df0bc681b35d317e0d0daab1ab17695980c040c7d08a11ac0"


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def put(name, obj, text=False):
    path = os.path.join(run_dir, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)   # never overwrite
    with os.fdopen(fd, "w") as handle:
        handle.write(obj if text else json.dumps(obj, indent=1, sort_keys=True) + "\n")


def strict_json(data):
    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_KEY")
        return dict(items)

    def constant(name):
        raise ValueError("NON_FINITE:" + name)
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def manifest_path():
    return os.path.join(stage, "RUNS", "manifests", manifest_name)


def hashed_set():
    files, worktree = {}, os.path.join(stage, "WORKTREE")
    for base, dirs, names in os.walk(worktree):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(base, name)
            rel = "WORKTREE/" + os.path.relpath(path, worktree)
            files[rel] = "SYMLINK" if os.path.islink(path) else sha(path)
    for rel in NEW_FILES + sorted(PINS):
        path = os.path.join(stage, rel)
        files[rel] = sha(path) if os.path.isfile(path) else "MISSING"
    if step == "run":
        files["RUNS/manifests/" + manifest_name] = (
            sha(manifest_path()) if os.path.isfile(manifest_path()) else "MISSING")
    files["INTERPRETER:" + os.path.realpath(py)] = sha(os.path.realpath(py))
    listing = {d: sorted(os.listdir(os.path.join(stage, d))) for d in LISTING}
    return {"files": files, "listing": listing,
            "worktree_file_count": sum(1 for k in files if k.startswith("WORKTREE/"))}


def preflight_problems(before):
    problems = []
    if before["listing"] != LISTING:
        problems.append("LISTING_MISMATCH:%s" % json.dumps(before["listing"], sort_keys=True))
    for rel, pin in PINS.items():
        if before["files"].get(rel) != pin:
            problems.append("PIN_MISMATCH:" + rel)
    try:
        with open(os.path.join(stage, "BEFORE_WORKTREE.json"), "rb") as handle:
            frozen = {"WORKTREE/" + row["path"]: row["sha256"] for row in strict_json(handle.read())}
        current = {k: v for k, v in before["files"].items() if k.startswith("WORKTREE/")}
        if frozen != current or len(current) != 996:
            problems.append("WORKTREE_DIFFERS_FROM_BEFORE_WORKTREE_JSON")
    except Exception as error:
        problems.append("BEFORE_WORKTREE_JSON_UNREADABLE:%r" % (error,))
    try:
        with open(os.path.join(stage, "BUILD", "STATIC_AUDIT.json"), "rb") as handle:
            audit = strict_json(handle.read())
        audited = audit["audited_files_sha256"]
        if sorted(audited) != sorted(NEW_FILES):
            problems.append("STATIC_AUDIT_FILE_SET")
        for rel in NEW_FILES:
            if audited.get(rel) != before["files"].get(rel):
                problems.append("STATIC_AUDIT_HASH_MISMATCH:" + rel)
        if audit.get("audit_complete_all_five_files") is not True \
                or audit.get("verdict") != "STATIC_AUDIT_PASS":
            problems.append("STATIC_AUDIT_NOT_COMPLETE_PASS")
    except Exception as error:
        problems.append("STATIC_AUDIT_UNREADABLE:%r" % (error,))
    if step == "run" and before["files"].get("RUNS/manifests/" + manifest_name) == "MISSING":
        problems.append("MANIFEST_MISSING")
    return problems


def pycache_scan():
    hits = []
    for top in ("HARNESS", "LIB", "WORKTREE", os.path.join("RUNS", run_id)):
        for base, dirs, names in os.walk(os.path.join(stage, top)):
            hits += [os.path.join(base, d) for d in dirs if d == "__pycache__"]
            hits += [os.path.join(base, n) for n in names if n.endswith((".pyc", ".pyo"))]
    return sorted(hits)


def budget(prior_here):
    """Cumulative accounting.  prior_here = RUNS/<run_id> directories already
    created in THIS stage (each one is a counted invocation)."""
    index = PRIOR_WRAPPED_CALLS + prior_here + 1
    return {"prior_wrapped_calls_previous_stage": PRIOR_WRAPPED_CALLS,
            "invocations_before_this_one_in_this_stage": prior_here,
            "stage_invocation_index": prior_here + 1, "cumulative_invocation_index": index,
            "max_cumulative_invocations": MAX_INVOCATIONS,
            "remaining_after_this_one": MAX_INVOCATIONS - index,
            "repair_iteration": int(run_id[1]), "max_repair_iterations": 3,
            "budget_file": BUDGET_FILE, "budget_file_sha256_pinned": BUDGET_SHA256}


def budget_problems():
    """The immutable input must still say what the fixed carry says."""
    try:
        with open(os.path.join(stage, BUDGET_FILE), "rb") as handle:
            data = handle.read()
        if hashlib.sha256(data).hexdigest() != BUDGET_SHA256:
            return ["CUMULATIVE_BUDGET_FILE_HASH_MISMATCH"]
        record = strict_json(data)
        if record.get("prior_wrapped_calls") != PRIOR_WRAPPED_CALLS \
                or record.get("max_cumulative_wrapped_calls") != MAX_INVOCATIONS \
                or record.get("max_cumulative_repair_iterations") != 3:
            return ["CUMULATIVE_BUDGET_FILE_DISAGREES_WITH_FIXED_CARRY"]
    except Exception as error:
        return ["CUMULATIVE_BUDGET_FILE_UNREADABLE:%r" % (error,)]
    return []


def before():
    runs = os.path.join(stage, "RUNS")
    prior = sorted(n for n in os.listdir(runs) if n != "manifests")
    if PRIOR_WRAPPED_CALLS + len(prior) >= MAX_INVOCATIONS:
        print("WRAPPER_REFUSED:CUMULATIVE_INVOCATION_LIMIT_%d_REACHED" % MAX_INVOCATIONS)
        return 65
    try:
        os.mkdir(run_dir)                     # append-only: an existing run id is refused
    except FileExistsError:
        print("WRAPPER_REFUSED:RUN_DIR_EXISTS")
        return 65
    os.mkdir(tmp)
    put("START_UTC.txt", utc() + "\n", True)
    command = [py, "-B", "-I", "-S", os.path.join(stage, "LIB", "run_pure_harness.py"),
               "--run-id", run_id, "--step", step]
    if step == "run":
        command += ["--manifest-name", manifest_name]
    count = budget(len(prior))
    put("COMMAND.txt", " ".join(command) + "\ncwd=" + tmp
        + "\nstdout=stdout.txt stderr=stderr.txt\ninvocation_index=%d\n"
        "stage_invocation_index=%d\nrepair_iteration=%d\n"
        % (count["cumulative_invocation_index"], count["stage_invocation_index"],
           count["repair_iteration"]), True)
    put("BUDGET.json", count)
    snapshot = hashed_set()
    put("BEFORE_HASHES.json", snapshot)
    if step == "run" and os.path.isfile(manifest_path()):
        with open(manifest_path(), "rb") as handle:
            data = handle.read()
        fd = os.open(os.path.join(run_dir, "MANIFEST.json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        put("MANIFEST_SHA256.txt", hashlib.sha256(data).hexdigest() + "  " + manifest_name + "\n", True)
    put("INTERPRETER.json", {"interpreter": py, "realpath": os.path.realpath(py),
                             "sha256": sha(os.path.realpath(py)),
                             "sys_version_file": "INTERPRETER_VERSION.txt",
                             "evidence_helper_interpreter": os.path.realpath(sys.executable),
                             "evidence_helper_sha256": sha(os.path.realpath(sys.executable)),
                             "flags": "-B -I -S"})
    problems = budget_problems() + preflight_problems(snapshot)
    if problems:
        put("PREFLIGHT_REFUSED.json", {"problems": problems})
        print("WRAPPER_PREFLIGHT_REFUSED:" + ";".join(problems))
        return 66
    return 0


def after():
    child_exit = sys.argv[7]
    put("END_UTC.txt", utc() + "\n", True)
    put("EXIT.txt", child_exit + "\n", True)
    with open(os.path.join(run_dir, "BEFORE_HASHES.json"), "rb") as handle:
        first = strict_json(handle.read())
    second = hashed_set()
    put("AFTER_HASHES.json", second)
    keys = sorted(set(first["files"]) | set(second["files"]))
    delta = {k: {"before": first["files"].get(k), "after": second["files"].get(k)}
             for k in keys if first["files"].get(k) != second["files"].get(k)}
    if first["listing"] != second["listing"]:
        delta["LISTING"] = {"before": first["listing"], "after": second["listing"]}
    put("HASH_DELTA.json", delta)
    scan = pycache_scan()
    put("PYCACHE_SCAN.txt", "".join(p + "\n" for p in scan), True)
    reasons = []
    refused = os.path.exists(os.path.join(run_dir, "PREFLIGHT_REFUSED.json"))
    if refused:
        reasons.append("PREFLIGHT_REFUSED_CHILD_NOT_LAUNCHED")
    if child_exit != "0":
        reasons.append("NONZERO_EXIT:" + child_exit)
    if delta:
        reasons.append("HASH_DELTA_NON_EMPTY")
    if second["listing"] != LISTING or first["listing"] != LISTING:
        reasons.append("LISTING_MISMATCH")
    if scan:
        reasons.append("PYCACHE_PRESENT")
    main_name = "RESULT.json" if step == "run" else "ENUM.json"
    expected = sorted([main_name, "AUX_GUARD.json"])
    listing = []
    for base, dirs, names in os.walk(tmp):
        for name in sorted(dirs) + sorted(names):
            path = os.path.join(base, name)
            mode = os.lstat(path).st_mode
            listing.append({"path": os.path.relpath(path, tmp),
                            "kind": "dir" if stat.S_ISDIR(mode) else
                            "file" if stat.S_ISREG(mode) else "other"})
    put("TMP_LISTING.json", {"expected": expected, "entries": listing})
    if sorted(e["path"] for e in listing) != expected or any(e["kind"] != "file" for e in listing):
        reasons.append("TMP_LISTING_NOT_EXACTLY_EXPECTED")
    copies, parsed = [], {}
    for name in expected:
        row = {"name": name, "bytes": None, "tmp_sha256": None, "copy_sha256": None, "equal": False}
        source = os.path.join(tmp, name)
        try:
            with open(source, "rb") as handle:
                data = handle.read()
            row["bytes"], row["tmp_sha256"] = len(data), hashlib.sha256(data).hexdigest()
            fd = os.open(os.path.join(run_dir, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            row["copy_sha256"] = sha(os.path.join(run_dir, name))
            row["equal"] = row["copy_sha256"] == row["tmp_sha256"] == sha(source)
            if not row["equal"]:
                reasons.append("COPY_MISMATCH:" + name)
            try:
                parsed[name] = strict_json(data)
                if not isinstance(parsed[name], dict):
                    raise ValueError("NOT_AN_OBJECT")
            except Exception as error:
                parsed.pop(name, None)
                reasons.append("OUTPUT_NOT_STRICT_JSON:%s:%r" % (name, error))
        except Exception as error:
            reasons.append("OUTPUT_MISSING_OR_COPY_FAILED:%s:%r" % (name, error))
        copies.append(row)
    put("COPY_RECORD.json", copies)
    aux, result = parsed.get("AUX_GUARD.json"), parsed.get(main_name)
    counts = {}
    if aux is not None:
        if aux.get("record_complete") is not True or list(aux)[-1] != "record_complete":
            reasons.append("AUX_GUARD_RECORD_INCOMPLETE")
        if aux.get("install_error") is not None or not (aux.get("install") or {}).get("installed"):
            reasons.append("AUX_GUARD_NOT_INSTALLED")
        if aux.get("aux_violations") != []:
            reasons.append("AUX_VIOLATIONS")
        if aux.get("pure_guard_violation_count") != 0:
            reasons.append("PURE_GUARD_VIOLATIONS(AUX_RECORD)")
        if not (aux.get("stacking") or {}).get("all_ok"):
            reasons.append("GUARD_STACKING_NOT_PURE_OVER_AUX")
        if aux.get("aux_sha256") != second["files"].get("LIB/harness_guard_aux.py"):
            reasons.append("AUX_SHA_MISMATCH")
        if aux.get("runner_rc") != 0 or aux.get("runner_exception") is not None:
            reasons.append("RUNNER_RC_OR_EXCEPTION")
    if result is not None:
        guard = result.get("guard") or {}
        if guard.get("installed") is not True:
            reasons.append("PURE_GUARD_NOT_INSTALLED")
        if result.get("guard_sha256") != PINS["LIB/pure_guard.py"] \
                or result.get("runner_sha256") != PINS["LIB/run_pure.py"]:
            reasons.append("GUARD_OR_RUNNER_SHA_IN_RESULT")
        if result.get("guard_violations") != []:
            reasons.append("PURE_GUARD_VIOLATIONS_OR_FIELD_MISSING")
        if step == "run":
            if result.get("approval_problems") != [] or result.get("import_violations") != []:
                reasons.append("APPROVAL_PROBLEMS_OR_IMPORT_VIOLATIONS")
            executed = result.get("executed")
            if not isinstance(executed, list) or not executed:
                reasons.append("NOTHING_EXECUTED")
                executed = []
            for row in executed:
                counts[row.get("outcome")] = counts.get(row.get("outcome"), 0) + 1
                if row.get("outcome") != "OK" or row.get("violations") != []:
                    reasons.append("OUTCOME_NOT_OK:%s:%s" % (row.get("id"), row.get("outcome")))
            try:
                with open(os.path.join(run_dir, "MANIFEST.json"), "rb") as handle:
                    allowed = strict_json(handle.read())["allowed"]
                if [row.get("id") for row in executed] != allowed:
                    reasons.append("EXECUTED_IDS_DIFFER_FROM_MANIFEST")
                if result.get("manifest_sha256") != second["files"].get("RUNS/manifests/" + manifest_name):
                    reasons.append("MANIFEST_SHA_MISMATCH")
            except Exception as error:
                reasons.append("MANIFEST_COPY_UNREADABLE:%r" % (error,))
        else:
            if not isinstance(result.get("ids"), dict) or result.get("forbidden") != {}:
                reasons.append("ENUM_IDS_MISSING_OR_FORBIDDEN")
    with open(os.path.join(run_dir, "BUDGET.json"), "rb") as handle:
        count = strict_json(handle.read())
    verdict = {"run_id": run_id, "step": step, "manifest_name": manifest_name or None,
               "verdict": "FAILED" if reasons else "OK", "reasons": reasons,
               "cumulative_invocation_index": count["cumulative_invocation_index"],
               "stage_invocation_index": count["stage_invocation_index"],
               "repair_iteration": count["repair_iteration"],
               "remaining_cumulative_invocations": count["remaining_after_this_one"],
               "exit": child_exit, "counts": counts,
               "enumerated_ids": len(result["ids"]) if step == "enumerate" and result
               and isinstance(result.get("ids"), dict) else None,
               "stdout_sha256": sha(os.path.join(run_dir, "stdout.txt")),
               "stderr_sha256": sha(os.path.join(run_dir, "stderr.txt")),
               "new_files_sha256": {rel: second["files"].get(rel) for rel in NEW_FILES},
               "before_hashes_sha256": sha(os.path.join(run_dir, "BEFORE_HASHES.json")),
               "after_hashes_sha256": sha(os.path.join(run_dir, "AFTER_HASHES.json")),
               "worktree_file_count": second["worktree_file_count"],
               "interpreter": os.path.realpath(py), "retried": False}
    put("RUN_VERDICT.json", verdict)
    print("%s %s %s" % (run_id, verdict["verdict"], ";".join(reasons)))
    return 0 if not reasons else 1


sys.exit(before() if phase == "before" else after())
PYEOF

"$HELPER_PY" -B -I -S -c "$HELPER" before "$STAGE_ROOT" "$RUN_ID" "$STEP" "$MANIFEST_NAME" "$PY"
PRE=$?
if [ "$PRE" -eq 65 ]; then
    exit 65
fi
if [ "$PRE" -eq 0 ]; then
    "$PY" -I -S -c 'import sys; print(sys.version)' > "$RUN_DIR/INTERPRETER_VERSION.txt" 2>&1
    if [ "$STEP" = "run" ]; then
        ( cd "$RUN_DIR/tmp" && exec "$PY" -B -I -S "$STAGE_ROOT/LIB/run_pure_harness.py" --run-id "$RUN_ID" --step "$STEP" --manifest-name "$MANIFEST_NAME" ) > "$RUN_DIR/stdout.txt" 2> "$RUN_DIR/stderr.txt"
        RC=$?
    else
        ( cd "$RUN_DIR/tmp" && exec "$PY" -B -I -S "$STAGE_ROOT/LIB/run_pure_harness.py" --run-id "$RUN_ID" --step "$STEP" ) > "$RUN_DIR/stdout.txt" 2> "$RUN_DIR/stderr.txt"
        RC=$?
    fi
else
    : > "$RUN_DIR/stdout.txt"
    : > "$RUN_DIR/stderr.txt"
    RC="NOT_LAUNCHED_PREFLIGHT_$PRE"
fi
"$HELPER_PY" -B -I -S -c "$HELPER" after "$STAGE_ROOT" "$RUN_ID" "$STEP" "$MANIFEST_NAME" "$PY" "$RC"
exit $?
