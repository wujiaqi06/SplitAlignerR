"""Launcher for the NRP3 harness pure runs (NRP3_HARNESS_IMPL001, repair FIX001:
STAGE_ROOT relocated to the FIX001 stage; run ids I1..I3 only, no I0).

Usage (only form): <py> -B -I -S run_pure_harness.py --run-id <id>
                   --step {enumerate,run} [--manifest-name <name>]

There is no path argument.  Every filesystem root is fixed: the STAGE_ROOT
literal below (already a realpath, recorded at S0) and names validated by
fullmatch.  The launcher creates nothing: RUNS/<run_id>/tmp must already exist
(wrapper) and be empty.  Sequence: validate -> LIB on sys.path -> import
harness_guard_aux and run_pure (run_pure import installs nothing) ->
harness_guard_aux.install(TMP) -> run_pure.main(argv) (which installs the
frozen pure_guard on top) -> finally TMP/AUX_GUARD.json.

Exit: 0 only if the aux guard installed, the runner returned 0, the stacking
is pure_guard-over-aux and no aux or pure_guard violation was recorded;
4 refused / aux install failed / stacking wrong; 5 guard violation recorded;
6 runner raised; otherwise the runner's nonzero rc.
"""
import json
import os
import re
import stat
import sys

STAGE_ROOT = ("/home/jiaqi/Documents/work/SplitAligner/SplitAlignerR/"
              "ENGINE003_LINUXPORT001_development_20260908_JST/"
              "DEV_NRP3_HARNESS_IMPL001_FIX001_OPUS55_20261002")
RUN_ID_RE = re.compile(r"I[1-3]_(ENUM|U|H[IB][0-9]{2})_py(38|310)")
MANIFEST_RE = re.compile(r"MANIFEST_(U|H[IB][0-9]{2})\.json")
GROUPS = ("ENUM", "U") + tuple("HI%02d" % i for i in range(1, 11)) \
    + tuple("HB%02d" % i for i in range(1, 5))
TEST_MODULE = "test_nrp3_harness"
SCHEMA = "SplitAlignerR/NRP3HarnessAuxGuardRecord/v1"


class Refuse(Exception):
    pass


def parse(argv):
    if len(argv) not in (4, 6) or len(argv) % 2:
        raise Refuse("ARGUMENT_COUNT")
    args = {}
    for flag, value in zip(argv[0::2], argv[1::2]):
        if flag not in ("--run-id", "--step", "--manifest-name") or flag in args:
            raise Refuse("ARGUMENT_FLAG:%s" % flag)
        args[flag] = value
    run_id, step, manifest = args.get("--run-id"), args.get("--step"), args.get("--manifest-name")
    match = RUN_ID_RE.fullmatch(run_id or "")
    if match is None or match.group(1) not in GROUPS:
        raise Refuse("RUN_ID")
    if "py%d%d" % sys.version_info[:2] != "py" + match.group(2):
        raise Refuse("RUN_ID_INTERPRETER_MISMATCH")
    if step == "enumerate":
        if manifest is not None or match.group(1) != "ENUM":
            raise Refuse("ENUMERATE_ARGUMENTS")
    elif step == "run":
        found = MANIFEST_RE.fullmatch(manifest or "")
        if found is None or found.group(1) != match.group(1) or match.group(1) == "ENUM":
            raise Refuse("RUN_MANIFEST_NAME")
    else:
        raise Refuse("STEP")
    return run_id, step, manifest


def real_dir(path):
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def validate_roots(run_id):
    here = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if here != STAGE_ROOT or os.path.realpath(STAGE_ROOT) != STAGE_ROOT:
        raise Refuse("STAGE_ROOT_MISMATCH")
    run_dir = os.path.join(STAGE_ROOT, "RUNS", run_id)
    tmp = os.path.join(run_dir, "tmp")
    if not real_dir(run_dir) or not real_dir(tmp) or os.path.realpath(tmp) != tmp:
        raise Refuse("RUN_TMP_NOT_A_REAL_DIRECTORY")
    if os.listdir(tmp):
        raise Refuse("RUN_TMP_NOT_EMPTY")
    return tmp


def runner_argv(step, tmp, manifest):
    src = os.path.join(STAGE_ROOT, "HARNESS")
    if step == "run":
        return ["run", "--src", src, "--tmp", tmp, "--out", os.path.join(tmp, "RESULT.json"),
                "--manifest", os.path.join(STAGE_ROOT, "RUNS", "manifests", manifest)]
    return ["enumerate", "--src", src, "--tmp", tmp, "--out", os.path.join(tmp, "ENUM.json"),
            "--modules", TEST_MODULE]


def main(argv):
    try:
        run_id, step, manifest = parse(argv)
        tmp = validate_roots(run_id)
    except Refuse as refused:
        sys.stderr.write("LAUNCHER_REFUSED:%s\n" % refused)
        return 4
    record = {"schema": SCHEMA, "run_id": run_id, "step": step, "manifest_name": manifest,
              "aux_sha256": None, "install": None, "install_error": None,
              "aux_violations": None, "aux_counters": None, "stacking": None,
              "pure_guard_violation_count": None, "runner_rc": None,
              "runner_exception": None, "sys_path_start": list(sys.path),
              "sys_path_end": None, "launcher_exit": None}
    exit_code, aux, guard = 4, None, None
    try:
        sys.path.insert(0, os.path.join(STAGE_ROOT, "LIB"))
        record["sys_path_after_lib_insert"] = list(sys.path)
        try:
            import harness_guard_aux as aux
            import run_pure
            import pure_guard as guard
            record["aux_sha256"] = aux.own_sha256()
            record["install"] = aux.install(tmp)
        except BaseException as error:
            record["install_error"] = "AUX_INSTALL_FAILED:%r" % (error,)
            return exit_code
        try:
            record["runner_rc"] = run_pure.main(runner_argv(step, tmp, manifest))
        except BaseException as error:
            record["runner_exception"] = repr(error)
        record["stacking"] = aux.stacking_report()
        aux_violations = list(aux.VIOLATIONS)
        pure_violations = len(guard.VIOLATIONS)
        if aux_violations or pure_violations:
            exit_code = 5
        elif record["runner_exception"] is not None:
            exit_code = 6
        elif record["runner_rc"] != 0:
            exit_code = record["runner_rc"] if type(record["runner_rc"]) is int else 6
        elif record["stacking"]["all_ok"] is not True:
            exit_code = 4
        else:
            exit_code = 0
        return exit_code
    finally:
        record["aux_violations"] = None if aux is None else list(aux.VIOLATIONS)
        record["aux_counters"] = None if aux is None else dict(aux.COUNTERS)
        record["pure_guard_violation_count"] = None if guard is None else len(guard.VIOLATIONS)
        record["sys_path_end"] = list(sys.path)
        record["launcher_exit"] = exit_code
        record["record_complete"] = True          # last key
        with open(os.path.join(tmp, "AUX_GUARD.json"), "w") as handle:
            handle.write(json.dumps(record, indent=1) + "\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
