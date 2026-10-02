#!/usr/bin/env python3
"""Compact portable PURE test runner (NRP2 FIX001 RESUME001).

Never uses unittest discovery and never runs a whole module.  Two steps:

  enumerate --src LINUX_EXEC --tmp TMP --out ENUM.json --modules M1,M2,...
      installs the host-effect guard FIRST, imports the named test modules
      (import effects happen under the guard), lists every test ID of every
      TestCase class DEFINED in that module (imported classes are ignored)
      and source-scans each test method plus its class setUp/setUpClass for
      host-effect markers.  Executes no test.

  run --src LINUX_EXEC --tmp TMP --manifest MANIFEST.json --out RESULT.json
      installs the guard FIRST, imports, then APPROVES the manifest before
      executing anything: every allowed ID must be an explicit
      module.Class.method that exists, be defined in its module, not be in
      the fixed forbidden set, not be excluded, and have a clean source scan
      (or an explicit reviewed waiver).  Any approval failure => exit 3, no
      test executed.  Approved IDs run sequentially, one by one, by explicit
      name.  Exit 0 only if every test passed AND the guard recorded no
      violation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pure_guard  # noqa: E402

FORBIDDEN_EXACT = {
    "test_linux_exec.ProcSourceTests.test_real_source_self_reads_only":
        "real /proc self reads (RealProcSource)",
    "test_dev007_fix002.DispatchJournalTests.test_file_storage_no_clobber":
        "real candidate FileStorage on a host directory (os.link)",
}
FORBIDDEN_CLASSES = {
    "test_linux_exec.ObservingGuardTests": "real subprocess.run of guard script",
    "test_linux_exec.StuckGuardTests": "real subprocess.run of stuck-hook script",
}
MARKERS = [
    r"subprocess\.(run|Popen|call|check_call|check_output)", r"RealProcSource",
    r"[\"']/proc", r"FileStorage", r"os\.link\b", r"os\.kill\b", r"killpg",
    r"pidfd", r"os\.fork", r"os\.pipe", r"sys\.executable", r"ctypes",
    r"posix_spawn", r"GUARD_SCRIPT", r"STUCK_SCRIPT", r"os\.wait",
    r"signal\.signal\(", r"\bmain\(\[", r"_cli\(",
]


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def prepare(src, tmp):
    os.makedirs(tmp, exist_ok=True)
    pure_guard.install(tmp)                     # BEFORE any candidate import
    os.environ["TMPDIR"] = tmp
    tempfile.tempdir = tmp
    sys.dont_write_bytecode = True
    sys.path.insert(0, src)


def scan(obj):
    try:
        text = inspect.getsource(obj)
    except (OSError, TypeError):
        return ["SOURCE_UNAVAILABLE"]
    return sorted({m for m in MARKERS if re.search(m, text)})


def enumerate_ids(modules):
    ids = {}
    for name in modules:
        mod = importlib.import_module(name)
        for cname, cls in sorted(vars(mod).items()):
            if not (isinstance(cls, type) and issubclass(cls, unittest.TestCase)
                    and cls.__module__ == name):
                continue
            fixture = []
            for f in ("setUp", "setUpClass", "tearDown"):
                if f in cls.__dict__:
                    fixture += scan(cls.__dict__[f])
            skip = getattr(cls, "__unittest_skip__", False)
            for meth in unittest.TestLoader().getTestCaseNames(cls):
                fn = getattr(cls, meth)
                ids[f"{name}.{cname}.{meth}"] = {
                    "markers": sorted(set(scan(fn)) | set(fixture)),
                    "class_skip": bool(skip),
                    "file": os.path.basename(inspect.getsourcefile(cls))}
    return ids


def forbidden(tid):
    if tid in FORBIDDEN_EXACT:
        return FORBIDDEN_EXACT[tid]
    return FORBIDDEN_CLASSES.get(tid.rsplit(".", 1)[0])


def approve(manifest, ids):
    problems = []
    allowed = manifest["allowed"]
    if len(set(allowed)) != len(allowed):
        problems.append("DUPLICATE_IDS")
    for tid in allowed:
        if tid.count(".") != 2:
            problems.append(f"NOT_EXPLICIT_ID:{tid}")
        elif tid not in ids:
            problems.append(f"UNKNOWN_OR_IMPORTED_ID:{tid}")
        elif forbidden(tid):
            problems.append(f"FORBIDDEN:{tid}:{forbidden(tid)}")
        elif tid in manifest.get("excluded", {}):
            problems.append(f"ALSO_EXCLUDED:{tid}")
        elif ids[tid]["markers"] and tid not in manifest.get("waivers", {}):
            problems.append(f"UNREVIEWED_MARKERS:{tid}:{ids[tid]['markers']}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("enumerate", "run"))
    ap.add_argument("--src", required=True)
    ap.add_argument("--tmp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest")
    ap.add_argument("--modules", default="", help="comma-separated test modules")
    a = ap.parse_args(argv)
    src, tmp = os.path.abspath(a.src), os.path.abspath(a.tmp)
    prepare(src, tmp)
    report = {"step": a.step, "src": src, "tmp": tmp, "python": sys.version,
              "guard": {"installed": pure_guard.INSTALLED["installed"],
                        "names": list(pure_guard.INSTALLED["names"])},
              "runner_sha256": sha(__file__), "guard_sha256": sha(pure_guard.__file__)}
    if a.step == "enumerate":
        mods = [m for m in a.modules.split(",") if m]
        ids = enumerate_ids(mods)
        report.update(modules=mods, ids=ids,
                      forbidden={t: forbidden(t) for t in ids if forbidden(t)},
                      guard_violations=list(pure_guard.VIOLATIONS))
        json.dump(report, open(a.out, "w"), indent=1, sort_keys=True)
        print(f"enumerated {len(ids)} ids; violations {len(pure_guard.VIOLATIONS)}")
        return 1 if pure_guard.VIOLATIONS else 0
    manifest = json.load(open(a.manifest))
    report["manifest_sha256"] = sha(a.manifest)
    modules = sorted({t.split(".")[0] for t in manifest["allowed"]})
    ids = enumerate_ids(modules)
    problems = approve(manifest, ids)
    report.update(approval_problems=problems, import_violations=list(pure_guard.VIOLATIONS))
    if problems or pure_guard.VIOLATIONS:
        report["executed"] = []
        json.dump(report, open(a.out, "w"), indent=1, sort_keys=True)
        print("APPROVAL_REFUSED; no test executed:", *problems, sep="\n  ")
        return 3
    print(f"APPROVED {len(manifest['allowed'])} explicit ids; guard installed "
          f"({len(pure_guard.INSTALLED['names'])} entry points)", flush=True)
    results, loader = [], unittest.TestLoader()
    for tid in manifest["allowed"]:
        pure_guard.rescan_filestorage()
        before = len(pure_guard.VIOLATIONS)
        suite = loader.loadTestsFromName(tid)
        if suite.countTestCases() != 1:
            results.append({"id": tid, "outcome": "NOT_SINGLE_TEST"})
            continue
        buf = io.StringIO()
        t0 = time.monotonic()
        r = unittest.TextTestRunner(stream=buf, verbosity=2).run(suite)
        outcome = ("ERROR" if r.errors else "FAIL" if r.failures else
                   "SKIP" if r.skipped else "OK")
        viol = pure_guard.VIOLATIONS[before:]
        if viol:
            outcome = "GUARD_VIOLATION"
        sys.stderr.write(buf.getvalue())
        results.append({"id": tid, "outcome": outcome, "seconds":
                        round(time.monotonic() - t0, 3), "violations": viol,
                        "skip_reason": [s[1] for s in r.skipped]})
    counts = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    report.update(executed=results, counts=counts,
                  guard_violations=list(pure_guard.VIOLATIONS))
    json.dump(report, open(a.out, "w"), indent=1, sort_keys=True)
    print("COUNTS", json.dumps(counts, sort_keys=True))
    for r in results:
        if r["outcome"] != "OK":
            print(r["outcome"], r["id"])
    ok = set(counts) <= {"OK"} and not pure_guard.VIOLATIONS
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
