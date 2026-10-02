"""Focused tests for the Linux execution/lifecycle layer. No native effects.

Everything runs on the synthetic fake kernel except: read-only /proc reads of
this test process itself (RealProcSource), and one subprocess that installs
the real p18 DevelopmentGuard base (verified bytes) under a stub runtime to
test the observation-window subclass. No fork of a child to observe, no
pidfd, no signal.

    cd linux_exec && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_linux_exec
"""
import copy
import errno
import json
import os
import subprocess
import sys
import textwrap
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import control_plane  # noqa: E402
import lifecycle  # noqa: E402
import wiring  # noqa: E402
from lifecycle import LifecycleConfig  # noqa: E402
from linux_proc_backend import (LinuxProcSamplerBackend, STANDALONE_ERRORS,  # noqa: E402
                                kernel_thread_tolerant)
from proc_source import (ProcAbsent, ProcReadError, RealProcSource,  # noqa: E402
                         RollupParseError, parse_smaps_rollup_rss_bytes)
from synthetic import SELF_PID, FakeKernel, FakeProcSource  # noqa: E402

PARSERS = wiring.load_verified_parsers()
CONTROLLER, CONTROLLER_SHA = control_plane.load_controller()
C_ERR = control_plane.controller_errors(CONTROLLER)
CFG = LifecycleConfig()


def no_sleep(_seconds):
    return None


def world_with_group():
    """SELF -> root R (own group/session) -> member M (same group)."""
    k = FakeKernel()
    root = k.spawn(SELF_PID)
    member = k.spawn(root.pid, pgid=root.pid, session=root.pid, rss_kb=5000)
    return k, root, member


def backend_for(k, errors=C_ERR):
    return LinuxProcSamplerBackend(FakeProcSource(k), kernel_thread_tolerant(
        PARSERS.parse_proc_stat), errors=errors, sleep=no_sleep)


def outcome(fn):
    try:
        return ("ok", fn())
    except BaseException as exc:
        return ("raise", type(exc).__name__, str(exc).split(":")[0])


# ---------------------------------------------------------------------------
# /proc source and parsers
# ---------------------------------------------------------------------------

class ProcSourceTests(unittest.TestCase):
    GOOD = (b"55e0c0a00000-7ffd12345000 ---p 00000000 00:00 0"
            b"                          [rollup]\nRss:                1768 kB\n"
            b"Pss:                 135 kB\n")

    def test_rollup_strict_grammar(self):
        self.assertEqual(parse_smaps_rollup_rss_bytes(self.GOOD), 1768 * 1024)
        bad = {
            b"": "SMAPS_ROLLUP_EMPTY",
            self.GOOD[:-1]: "SMAPS_ROLLUP_FRAMING",
            b"junk header\nRss: 1 kB\n": "SMAPS_ROLLUP_HEADER",
            self.GOOD + b"Rss: 2 kB\n": "SMAPS_ROLLUP_DUPLICATE_FIELD",
            self.GOOD.replace(b"Rss:", b"Rsx:"): "SMAPS_ROLLUP_RSS_MISSING",
            self.GOOD.replace(b"1768 kB", b"1768 MB"): "SMAPS_ROLLUP_FIELD",
            self.GOOD.replace(b"1768", b"-1768"): "SMAPS_ROLLUP_FIELD",
            self.GOOD + b"\0": "SMAPS_ROLLUP_FRAMING",
        }
        for raw, code in bad.items():
            with self.assertRaises(RollupParseError) as ctx:
                parse_smaps_rollup_rss_bytes(raw)
            self.assertEqual(ctx.exception.code, code, raw)

    def test_real_source_self_reads_only(self):
        src = RealProcSource()
        me = os.getpid()
        stat = PARSERS.parse_proc_stat(src.read(me, "stat"))
        self.assertEqual((stat.pid, stat.ppid), (me, os.getppid()))
        self.assertGreater(parse_smaps_rollup_rss_bytes(src.read(me, "smaps_rollup")), 0)
        self.assertIn(me, src.list_pids())
        rows = PARSERS.parse_mountinfo(src.read_self("mountinfo"))
        self.assertTrue(any(r.mount_point == b"/proc" for r in rows))
        with self.assertRaises(ProcAbsent):
            src.read(4194305, "stat")          # above x86_64 pid_max
        for pid, name in ((me, "status"), (me, "../stat"), (0, "stat"), (True, "stat")):
            with self.assertRaises(ProcReadError):
                src.read(pid, name)


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

class BackendIdentityTests(unittest.TestCase):
    def test_live_zombie_absent_and_fail_closed(self):
        k, root, _ = world_with_group()
        b = backend_for(k)
        self.assertEqual(b.identity_and_group(root.pid),
                         (SELF_PID, root.pid, (root.pid, root.starttime, 0)))
        k.exit(root.pid)
        with self.assertRaises(C_ERR.ProcessAbsent):
            b.identity_and_group(root.pid)
        self.assertEqual(b.observe(root.pid).state, "Z")
        with self.assertRaises(C_ERR.ProcessAbsent):
            b.identity_and_group(999999)
        k.read_errors[(4100, "stat")] = errno.EACCES
        with self.assertRaises(C_ERR.CapabilityError) as ctx:
            b.identity_and_group(4100)
        self.assertNotIsInstance(ctx.exception, C_ERR.ProcessAbsent)
        k.stat_override[1] = b"1 (init) S 0 1\n"
        with self.assertRaisesRegex(C_ERR.CapabilityError, "PROC_STAT_PARSE"):
            b.identity_and_group(1)
        k.stat_override[1] = k.stat_bytes(k.procs[4100])
        with self.assertRaisesRegex(C_ERR.CapabilityError, "PROC_STAT_PID_MISMATCH"):
            b.identity_and_group(1)

    def test_kernel_thread_group_zero(self):
        # Found by native_preflight_1: kthreadd has pgrp 0. The census must
        # accept it; it can never be a worker, so identity_and_group refuses it.
        k, root, member = world_with_group()
        b = backend_for(k)
        self.assertEqual(b.observe(2).pgid, 0)
        self.assertEqual(b.process_group_pids(root.pid), (root.pid, member.pid))
        with self.assertRaisesRegex(C_ERR.CapabilityError, "PROC_STAT_PGID_INVALID"):
            b.identity_and_group(2)

    def test_long_comm_accepted_only_for_kernel_threads(self):
        # Found by native_preflight_2: 5.4 kworker comm exceeds 15 bytes.
        k, root, member = world_with_group()
        b = backend_for(k)
        self.assertEqual(b.observe(8).pgid, 0)
        self.assertEqual(b.process_group_pids(root.pid), (root.pid, member.pid))
        strict = LinuxProcSamplerBackend(FakeProcSource(k), PARSERS.parse_proc_stat,
                                         errors=C_ERR, sleep=no_sleep)
        with self.assertRaisesRegex(C_ERR.CapabilityError, "STAT_COMM_LENGTH"):
            strict.process_group_pids(root.pid)
        k.procs[member.pid].comm = "a-user-process-with-long-name"
        with self.assertRaisesRegex(C_ERR.CapabilityError, "NOT_KERNEL_THREAD"):
            b.process_group_pids(root.pid)
        k.procs[member.pid].comm = "x" * 64
        with self.assertRaisesRegex(C_ERR.CapabilityError, "STAT_COMM_LENGTH"):
            b.process_group_pids(root.pid)
        k.procs[member.pid].comm = "p) S 1 2 3 (q"       # parenthesis trickery
        self.assertEqual(b.observe(member.pid).pgid, root.pid)

    def test_identity_validation_raises_bound_error_class(self):
        b = backend_for(FakeKernel())
        for bad in ((5, 1), (5, 0, 0), (5, 1, 7), (5, 1, 0.0), [5, 1, 0]):
            with self.assertRaises(C_ERR.CapabilityError):
                b._validate_identity(bad)
        with self.assertRaises(C_ERR.CapabilityError):
            b._validate_identity((5, 1, 0), 6)


class BackendCensusTests(unittest.TestCase):
    def test_stable_census_and_children(self):
        k, root, member = world_with_group()
        b = backend_for(k)
        self.assertEqual(b.process_group_pids(root.pid), (root.pid, member.pid))
        self.assertEqual(b.children(root.pid), (member.pid,))
        ev = b.authority_evidence()
        self.assertEqual(ev["proc_scans"], 4)
        self.assertEqual(ev["group_census_unresolved_count"], 0)

    def test_entry_vanishing_mid_scan_is_skipped(self):
        k, root, _ = world_with_group()
        b = backend_for(k)

        def vanish(kernel, pid, name):
            if pid == 4100:
                kernel.procs.pop(4100, None)
        k.on_read.append(vanish)
        self.assertEqual(b.process_group_pids(root.pid)[0], root.pid)
        self.assertEqual(b.authority_evidence()["scan_vanished_entries"], 1)

    def test_unreadable_unrelated_entry_fails_closed(self):
        k, root, _ = world_with_group()
        k.read_errors[(4100, "stat")] = errno.EACCES
        with self.assertRaisesRegex(C_ERR.CapabilityError, "PROC_CENSUS_READ_FAILED"):
            backend_for(k).process_group_pids(root.pid)

    def test_unstable_census_bounded_then_unresolved(self):
        k, root, member = world_with_group()
        b = backend_for(k)
        flip = {"n": 0}

        def toggle(kernel, pid, name):
            if pid == member.pid and name == "stat":
                flip["n"] += 1
                kernel.procs[member.pid].pgid = root.pid if flip["n"] % 2 else 4100
        k.on_read.append(toggle)
        with self.assertRaisesRegex(C_ERR.CapabilityError,
                                    "GROUP_CENSUS_DISAGREEMENT_UNRESOLVED"):
            b.process_group_pids(root.pid)
        ev = b.authority_evidence()
        self.assertEqual((ev["group_census_attempt_count"],
                          ev["group_census_followup_round_count"],
                          ev["group_census_unresolved_count"]), (5, 4, 1))

    def test_unstable_census_recovers_within_budget(self):
        k, root, member = world_with_group()
        b = backend_for(k)
        flip = {"n": 0}

        def toggle(kernel, pid, name):
            if pid == member.pid and name == "stat":
                flip["n"] += 1
                if flip["n"] <= 3:
                    kernel.procs[member.pid].pgid = root.pid if flip["n"] % 2 else 4100
        k.on_read.append(toggle)
        self.assertEqual(b.process_group_pids(root.pid), (root.pid, member.pid))
        self.assertEqual(b.authority_evidence()["group_census_recovery_count"], 1)


def tree_scenarios():
    """(name, mutate(kernel, root, member), known(root, member))."""
    def known_both(r, m):
        return {r.pid: (r.pid, r.starttime, 0), m.pid: (m.pid, m.starttime, 0)}
    return [
        ("live", lambda k, r, m: None, known_both),
        ("member_exit_zombie", lambda k, r, m: k.exit(m.pid), known_both),
        ("member_reaped", lambda k, r, m: k.procs.pop(m.pid), known_both),
        ("member_reuse", lambda k, r, m: k.reuse(m.pid), known_both),
        ("member_escape", lambda k, r, m: setattr(k.procs[m.pid], "pgid", 4100),
         known_both),
        ("new_member_predates_root",
         lambda k, r, m: k.add(__import__("synthetic").FakeProcess(
             4300, 1, r.pid, r.pid, r.starttime - 1, 100)), known_both),
        ("new_member_joins", lambda k, r, m: k.spawn(m.pid, pgid=r.pid), known_both),
        ("group_retired", lambda k, r, m: [k.procs.pop(r.pid), k.procs.pop(m.pid)],
         known_both),
        ("census_unreadable",
         lambda k, r, m: k.read_errors.__setitem__((4100, "stat"), errno.EACCES),
         known_both),
    ]


class BackendOwnedTreeTests(unittest.TestCase):
    def run_both(self, mutate, known):
        """Linux live_owned_tree vs the controller's shared (Darwin-class)
        algorithm run on this backend: identical outcome required."""
        results = []
        for which in ("linux", "controller"):
            k, root, member = world_with_group()
            b = backend_for(k)
            b.bind_process_group_authority(root.pid, (root.pid, root.starttime, 0))
            mutate(k, root, member)
            fn = (b.live_owned_tree if which == "linux" else
                  lambda kn: CONTROLLER.DarwinLibprocSamplerBackend.live_owned_tree(b, kn))
            results.append(outcome(lambda: fn(known(root, member))))
        return results

    def test_linux_and_controller_algorithm_agree(self):
        expected = {
            "live": "ok", "member_exit_zombie": "ok", "member_reaped": "ok",
            "member_reuse": "OWNED_PID_REUSE_REJECTED",
            "member_escape": "OWNED_PROCESS_ESCAPED_WORKER_PGID",
            "new_member_predates_root": "GROUP_MEMBER_PREDATES_AUTHORITY_ROOT",
            "new_member_joins": "ok", "group_retired": "ok",
            "census_unreadable": "PROC_CENSUS_READ_FAILED",
        }
        for name, mutate, known in tree_scenarios():
            linux, shared = self.run_both(mutate, known)
            self.assertEqual(linux, shared, name)
            self.assertEqual(linux[0] if linux[0] == "ok" else linux[2],
                             expected[name], (name, linux))
            if linux[0] == "raise":
                self.assertEqual(linux[1], "NativeSamplerCapabilityError", name)

    def test_member_exit_is_absent_not_live(self):
        k, root, member = world_with_group()
        b = backend_for(k)
        b.bind_process_group_authority(root.pid, (root.pid, root.starttime, 0))
        k.exit(member.pid)
        live, absent = b.live_owned_tree({root.pid: (root.pid, root.starttime, 0),
                                          member.pid: (member.pid, member.starttime, 0)})
        self.assertEqual((set(live), absent), ({root.pid}, {member.pid}))

    def test_retired_group_never_reacquired(self):
        k, root, member = world_with_group()
        b = backend_for(k)
        known = {root.pid: (root.pid, root.starttime, 0)}
        b.bind_process_group_authority(root.pid, known[root.pid])
        k.procs.pop(root.pid)
        k.procs.pop(member.pid)
        self.assertEqual(b.live_owned_tree(known), ({}, {root.pid}))
        k.spawn(1, pgid=root.pid)                 # PGID number reused
        with self.assertRaisesRegex(C_ERR.CapabilityError, "PGID_REUSE_OR_AMBIGUITY"):
            b.live_owned_tree(known)

    def test_authority_binding_rules(self):
        k, root, _ = world_with_group()
        b = backend_for(k)
        with self.assertRaisesRegex(C_ERR.CapabilityError, "NOT_BOUND"):
            b.live_owned_tree({root.pid: (root.pid, root.starttime, 0)})
        with self.assertRaisesRegex(C_ERR.CapabilityError, "EMPTY"):
            b.live_owned_tree({})
        b.bind_process_group_authority(root.pid, (root.pid, root.starttime, 0))
        b.bind_process_group_authority(root.pid, (root.pid, root.starttime, 0))
        with self.assertRaisesRegex(C_ERR.CapabilityError, "REBIND_REJECTED"):
            b.bind_process_group_authority(root.pid, (root.pid, root.starttime + 1, 0))


class BackendRssTests(unittest.TestCase):
    def setUp(self):
        self.k, self.root, self.member = world_with_group()
        self.b = backend_for(self.k)
        self.ident = (self.root.pid, self.root.starttime, 0)

    def test_identity_bound_rss(self):
        with self.assertRaisesRegex(C_ERR.CapabilityError, "RSS_IDENTITY_AUTHORITY_REQUIRED"):
            self.b.rss(self.root.pid)
        self.b.identity_and_group(self.root.pid)
        self.assertEqual(self.b.rss(self.root.pid), self.root.rss_kb * 1024)
        self.assertEqual(self.b.rss(self.root.pid, self.ident, self.root.pid),
                         self.root.rss_kb * 1024)

    def test_reuse_before_read_rejected(self):
        self.b.identity_and_group(self.root.pid)
        self.k.reuse(self.root.pid)
        with self.assertRaisesRegex(C_ERR.CapabilityError, "RSS_PID_REUSE_REJECTED"):
            self.b.rss(self.root.pid)

    def test_identity_change_during_read_rejected(self):
        def swap(kernel, pid, name):
            if name == "smaps_rollup":
                kernel.on_read.clear()
                kernel.reuse(pid)
        self.k.on_read.append(swap)
        with self.assertRaisesRegex(C_ERR.CapabilityError, "IDENTITY_CHANGED_DURING_READ"):
            self.b.rss(self.root.pid, self.ident, self.root.pid)

    def test_exit_during_read_is_exit_race(self):
        def die(kernel, pid, name):
            if name == "smaps_rollup":
                kernel.on_read.clear()
                kernel.exit(pid)
        self.k.on_read.append(die)
        with self.assertRaises(C_ERR.IdentityAwareExitRace):
            self.b.rss(self.root.pid, self.ident, self.root.pid)

    def test_zero_rss_followup_bounded(self):
        self.root.rss_kb = 0
        with self.assertRaisesRegex(C_ERR.CapabilityError, "ZERO_RSS_UNRESOLVED"):
            self.b.rss(self.root.pid, self.ident, self.root.pid)
        ev = self.b.authority_evidence()
        self.assertEqual((ev["zero_rss_initial_count"], ev["zero_rss_followup_round_count"],
                          ev["zero_rss_unresolved_count"]), (1, 4, 1))

    def test_zero_rss_recovers(self):
        self.root.rss_kb = 0
        reads = {"n": 0}

        def grow(kernel, pid, name):
            if name == "smaps_rollup":
                reads["n"] += 1
                if reads["n"] == 3:
                    kernel.procs[pid].rss_kb = 64
        self.k.on_read.append(grow)
        self.assertEqual(self.b.rss(self.root.pid, self.ident, self.root.pid), 64 * 1024)
        self.assertEqual(self.b.authority_evidence()["zero_rss_recovery_count"], 1)

    def test_empty_rollup_on_live_process_fails_closed(self):
        self.k.rollup_bytes = lambda proc: b""
        with self.assertRaisesRegex(C_ERR.CapabilityError, "UNAVAILABLE_LIVE_PROCESS"):
            self.b.rss(self.root.pid, self.ident, self.root.pid)

    def test_standalone_errors_without_controller(self):
        b = backend_for(self.k, STANDALONE_ERRORS)
        with self.assertRaises(STANDALONE_ERRORS.ProcessAbsent):
            b.identity_and_group(999999)


class BackendRssGroupBindingTests(unittest.TestCase):
    """A004-2: identity AND group are bound across the whole RSS bracket."""

    def setUp(self):
        self.k, self.root, self.member = world_with_group()
        self.b = backend_for(self.k)
        self.rid = (self.root.pid, self.root.starttime, 0)
        self.mid = (self.member.pid, self.member.starttime, 0)
        self.b.bind_process_group_authority(self.root.pid, self.rid)
        live, _ = self.b.live_owned_tree({self.root.pid: self.rid})
        self.assertEqual(set(live), {self.root.pid, self.member.pid})

    def escape_on(self, name, nth=1, pid=None, to=5700):
        """Identity-preserving setpgid of `pid` at the nth read of `name`."""
        pid = pid or self.member.pid
        seen = {"n": 0}

        def hook(kernel, read_pid, read_name):
            if read_pid == pid and read_name == name:
                seen["n"] += 1
                if seen["n"] == nth:
                    kernel.on_read.remove(hook)
                    kernel.procs[pid].pgid = to
        self.k.on_read.append(hook)

    def assert_refused(self, code, *args):
        with self.assertRaisesRegex(C_ERR.CapabilityError, code) as ctx:
            self.b.rss(*args)
        self.assertNotIsInstance(ctx.exception, C_ERR.ProcessAbsent)

    def test_default_path_binds_census_authority(self):
        self.assertEqual(self.b.rss(self.member.pid), self.member.rss_kb * 1024)

    def test_default_path_escape_before_read(self):
        self.member.pgid = 5700          # after identity_and_group, before rss
        self.assert_refused("RSS_PGID_CHANGED:", self.member.pid)

    def test_default_path_escape_during_read(self):
        self.escape_on("smaps_rollup")
        self.assert_refused("RSS_PGID_CHANGED_DURING_READ", self.member.pid)

    def test_explicit_escape_during_read(self):
        # Astra A004-2 repro: explicit (pid, identity, 5000), 5000 -> 5700
        # while smaps_rollup is read.
        self.assertEqual(self.root.pid, 5000)
        self.escape_on("smaps_rollup", pid=self.root.pid)
        self.assert_refused("RSS_PGID_CHANGED_DURING_READ", self.root.pid, self.rid, 5000)

    def test_explicit_escape_visible_only_at_after_read_stat(self):
        self.escape_on("stat", nth=2, pid=self.root.pid)   # 1 = before, 2 = after
        self.assert_refused("RSS_PGID_CHANGED_DURING_READ", self.root.pid, self.rid, 5000)

    def test_escape_during_zero_rss_followup(self):
        self.member.rss_kb = 0
        self.escape_on("smaps_rollup", nth=3)
        self.assert_refused("RSS_PGID_CHANGED", self.member.pid)

    def test_contradictory_group_sources_fail_closed(self):
        # Caller claims the escaped group; census authority says 5000.
        self.member.pgid = 5700
        self.assert_refused("RSS_GROUP_AUTHORITY_CONTRADICTION",
                            self.member.pid, self.mid, 5700)
        # A fresh identity_and_group that observes the escape does not
        # launder it: remembered 5700 vs census authority 5000.
        self.b.identity_and_group(self.member.pid)
        self.assert_refused("RSS_GROUP_AUTHORITY_CONTRADICTION", self.member.pid)

    def test_no_group_or_invalid_group_fails_closed(self):
        b = backend_for(self.k)
        self.assertRaisesRegex(C_ERR.CapabilityError, "RSS_GROUP_AUTHORITY_REQUIRED",
                               b.rss, self.root.pid, self.rid)
        for bad in (0, -1, True, "5000"):
            self.assertRaisesRegex(C_ERR.CapabilityError, "RSS_EXPECTED_PGID_INVALID",
                                   b.rss, self.root.pid, self.rid, bad)

    def test_self_admission_rss_not_bound_to_child_group(self):
        _ppid, pgid, _ident = self.b.identity_and_group(SELF_PID)
        self.assertNotEqual(pgid, self.root.pid)
        self.assertEqual(self.b.rss(SELF_PID), 20000 * 1024)
        self.escape_on("smaps_rollup", pid=SELF_PID, to=4100)
        self.assert_refused("RSS_PGID_CHANGED_DURING_READ", SELF_PID)

    def test_unchanged_controller_sampler_default_path_fails_closed(self):
        sampler = control_plane.make_sampler(CONTROLLER, self.root.pid, self.b)
        control_plane.sample_once(sampler)
        self.escape_on("smaps_rollup")
        with self.assertRaisesRegex(CONTROLLER.NativeSamplerCapabilityError,
                                    "RSS_PGID_CHANGED_DURING_READ"):
            control_plane.sample_once(sampler)

    def test_escape_after_read_caught_by_next_census(self):
        self.assertGreater(self.b.rss(self.member.pid), 0)
        self.member.pgid = 5700
        with self.assertRaisesRegex(C_ERR.CapabilityError, "ESCAPED_WORKER_PGID"):
            self.b.live_owned_tree({self.root.pid: self.rid, self.member.pid: self.mid})


class UnchangedControllerSamplerTests(unittest.TestCase):
    """The controller's own ProcessTreeRssSampler, driven with the Linux backend."""

    def test_root_must_lead_its_group(self):
        k = FakeKernel()
        root = k.spawn(SELF_PID, pgid=SELF_PID, session=SELF_PID)
        with self.assertRaisesRegex(CONTROLLER.NativeSamplerCapabilityError,
                                    "NOT_DEDICATED_PROCESS_GROUP_LEADER"):
            control_plane.make_sampler(CONTROLLER, root.pid, backend_for(k))

    def test_samples_whole_group_then_identity_aware_exit(self):
        k, root, member = world_with_group()
        both = (root.rss_kb + member.rss_kb) * 1024
        sampler = control_plane.make_sampler(CONTROLLER, root.pid, backend_for(k))
        tick = control_plane.sample_once(sampler)
        self.assertEqual(tick["current_bytes"], both)
        self.assertEqual(tick["active_owned_pids"], [root.pid, member.pid])
        k.exit(member.pid)
        tick = control_plane.sample_once(sampler)
        self.assertEqual(tick["active_owned_pids"], [root.pid])
        self.assertIn(member.pid, tick["identity_aware_exit_pids"])
        report = control_plane.sampler_report(sampler)
        self.assertEqual(report["maximum_bytes"], both)
        self.assertEqual(report["owned_identities"][str(root.pid)],
                         "%d:%d:0" % (root.pid, root.starttime))
        self.assertEqual(report["authority"]["mechanism_id"],
                         "LINUX_PROCFS_PROCESS_TREE_DEVELOPMENT_V1")

    def test_reuse_surfaces_as_controller_error(self):
        k, root, member = world_with_group()
        sampler = control_plane.make_sampler(CONTROLLER, root.pid, backend_for(k))
        control_plane.sample_once(sampler)
        k.reuse(member.pid)
        with self.assertRaisesRegex(CONTROLLER.NativeSamplerCapabilityError,
                                    "OWNED_PID_REUSE_REJECTED"):
            control_plane.sample_once(sampler)

    def test_controller_dispatch_still_refuses_linux(self):
        # This layer is opt-in; the controller's own factory is unchanged.
        with self.assertRaisesRegex(CONTROLLER.NativeSamplerCapabilityError,
                                    "UNSUPPORTED_PLATFORM_NO_FALLBACK"):
            CONTROLLER._sampler_capability_backend()


# ---------------------------------------------------------------------------
# Lifecycle (synthetic)
# ---------------------------------------------------------------------------

def run(behaviour="normal", ops_fail=None, custody_fail=None, confirm=True,
        mutate=None, cfg=CFG):
    ports, k = wiring.synthetic_ports(behaviour=behaviour, ops_fail=ops_fail,
                                      custody_fail=custody_fail, confirm=confirm)
    if mutate:
        mutate(ports, k)
    result = lifecycle.run_lifecycle(cfg, ports)
    json.dumps(lifecycle.safe(result))
    return ports, k, result["admission"], result


def names(ops, kind):
    return [c for c in ops.calls if c[0] == kind]


EFFECT_CALLS = ("pipe", "fork", "close", "write", "read", "wait_readable", "waitpid")


def assert_no_effects(test, ports):
    """Zero pipe/fork/fd/child effects and zero custody effects."""
    test.assertEqual([c for c in ports.ops.calls if c[0] in EFFECT_CALLS], [])
    test.assertEqual(ports.ops.open_fds, {})
    test.assertEqual(ports.custody.calls, [])
    test.assertFalse(ports.custody.installed)


class LifecycleSuccessTests(unittest.TestCase):
    def test_synthetic_end_to_end(self):
        ports, k, admission, result = run()
        checks = lifecycle.evaluate(CFG, result)
        self.assertEqual([c["name"] for c in checks if not c["ok"]], [])
        self.assertTrue(admission["admitted"])
        self.assertEqual(ports.custody.calls, ["acquire", "close", "finish"])
        calls = ports.ops.calls
        first_wait = next(i for i, c in enumerate(calls) if c[0] == "waitpid")
        stop = calls.index(("write", 11, b"S"))
        self.assertLess(stop, first_wait)
        self.assertEqual(len(names(ports.ops, "write")), 1)
        self.assertEqual(result["child"]["signals_sent"], 0)
        self.assertEqual(ports.ops.open_fds, {})
        self.assertFalse(any(hasattr(ports.ops, n) for n in ("kill", "killpg", "signal")))

    def test_real_ops_has_no_signal_member(self):
        self.assertFalse({"kill", "killpg", "send_signal", "signal"} & lifecycle.OPS_INTERFACE)
        from synthetic import FakeOps
        self.assertTrue(lifecycle.OPS_INTERFACE <= set(vars(FakeOps)))


class LifecycleAdmissionTests(unittest.TestCase):
    def refused(self, mutate, check_name, cfg=CFG):
        ports, k = wiring.synthetic_ports()
        mutate(ports, k)
        admission = lifecycle.preflight(cfg, ports)
        self.assertFalse(admission["admitted"])
        self.assertIn(check_name, [c["name"] for c in admission["checks"] if not c["ok"]])
        with self.assertRaisesRegex(lifecycle.LifecycleError, "NOT_ADMITTED|CONFIG_BOUNDS"):
            lifecycle.run_lifecycle(cfg, ports)
        assert_no_effects(self, ports)

    def test_hidepid(self):
        self.refused(lambda p, k: setattr(k, "mountinfo", k.mountinfo.replace(
            b"proc rw\n", b"proc rw,hidepid=2\n")), "proc_mounted_without_hidepid")

    def test_preexisting_child(self):
        self.refused(lambda p, k: k.spawn(SELF_PID), "no_preexisting_children")

    def test_threads(self):
        self.refused(lambda p, k: setattr(p.ops, "thread_count", lambda: 2), "single_thread")

    def test_platform(self):
        import types
        self.refused(lambda p, k: setattr(p.ops, "uname", lambda: types.SimpleNamespace(
            sysname="Darwin", machine="arm64", release="23")), "platform_linux_x86_64")

    def test_config_bounds(self):
        for bad in (LifecycleConfig(exit_timeout_s=float("inf")),
                    LifecycleConfig(ballast_bytes=1 << 30),
                    LifecycleConfig(observe_samples=0)):
            self.refused(lambda p, k: None, "config_bounds", bad)


class LifecycleAdmissionBoundaryTests(unittest.TestCase):
    """A004-1: no OS or custody effect without a current, bound admission."""

    def test_caller_supplied_approval_is_not_accepted(self):
        for approval in (None, True, False, {"admitted": True}, {"admitted": False}):
            ports, k = wiring.synthetic_ports()
            with self.assertRaises(TypeError):
                lifecycle.run_lifecycle(CFG, ports, approval)
            with self.assertRaises(TypeError):
                lifecycle.run_lifecycle(CFG, ports, admission=approval)
            assert_no_effects(self, ports)

    def test_stale_admission_is_not_reused(self):
        ports, k = wiring.synthetic_ports()
        self.assertTrue(lifecycle.preflight(CFG, ports)["admitted"])
        k.spawn(SELF_PID)                      # world changed after approval
        with self.assertRaisesRegex(lifecycle.LifecycleError, "NOT_ADMITTED") as ctx:
            lifecycle.run_lifecycle(CFG, ports)
        self.assertIn("no_preexisting_children", str(ctx.exception))
        self.assertFalse(ctx.exception.admission["admitted"])
        assert_no_effects(self, ports)

    def test_incompatible_cfg_and_ports_rejected_before_admission(self):
        import types
        ports, k = wiring.synthetic_ports()
        fake_cfg = types.SimpleNamespace(**lifecycle.asdict(CFG), problems=lambda: [])
        fake_ports = types.SimpleNamespace(**vars(ports))
        for cfg, p, code in ((fake_cfg, ports, "CONFIG_TYPE"),
                             (CFG, fake_ports, "PORTS_TYPE"),
                             (LifecycleConfig(observe_samples=0), ports, "CONFIG_BOUNDS")):
            with self.assertRaisesRegex(lifecycle.LifecycleError, code):
                lifecycle.run_lifecycle(cfg, p)
        assert_no_effects(self, ports)

    def test_custody_or_probe_refusal_blocks_all_effects(self):
        def custody_refuses(p, k):
            p.custody.preflight = lambda: [{"name": "custody_env", "ok": False,
                                            "observed": None}]

        def census_raises(p, k):
            k.read_errors[(4100, "stat")] = errno.EACCES
        for mutate, name in ((custody_refuses, "custody_env"),
                             (census_raises, "no_preexisting_children")):
            ports, k = wiring.synthetic_ports()
            mutate(ports, k)
            with self.assertRaisesRegex(lifecycle.LifecycleError, "NOT_ADMITTED") as ctx:
                lifecycle.run_lifecycle(CFG, ports)
            self.assertIn(name, str(ctx.exception))
            assert_no_effects(self, ports)

    def test_admission_runs_immediately_before_first_pipe(self):
        ports, k = wiring.synthetic_ports()
        mounts = ports.mounts

        def logged_mounts():
            ports.ops.calls.append(("preflight_mounts",))
            return mounts()
        ports.mounts = logged_mounts
        result = lifecycle.run_lifecycle(CFG, ports)
        kinds = [c[0] for c in ports.ops.calls]
        self.assertEqual(kinds.count("preflight_mounts"), 1)
        self.assertLess(kinds.index("preflight_mounts"), kinds.index("pipe"))
        self.assertTrue(result["admission"]["admitted"])
        self.assertEqual(result["admission"]["config"], result["config"])
        self.assertEqual([c["name"] for c in lifecycle.evaluate(CFG, result)
                          if not c["ok"]], [])


class LifecycleAdverseTests(unittest.TestCase):
    def assert_released(self, result):
        self.assertTrue(result["child"]["reaped"], result["cleanup"])
        self.assertEqual(result["child"]["signals_sent"], 0)

    def test_never_ready(self):
        ports, k, _, result = run("never_ready")
        self.assertEqual(result["primary_failure"]["code"], "CHILD_READY_TIMEOUT")
        self.assertEqual(ports.custody.calls, [])
        self.assert_released(result)
        self.assertTrue(result["cleanup"]["complete"])
        self.assertEqual(result["forks"], 1)

    def test_child_ignores_stop_no_signal_close_once_then_eof(self):
        ports, k, _, result = run("ignore_stop")
        self.assertEqual(result["primary_failure"]["code"], "CHILD_EXIT_TIMEOUT_NO_SIGNAL")
        self.assertEqual(ports.custody.calls, ["acquire", "close", "finish"])
        self.assertEqual(len(names(ports.ops, "write")), 1)     # no second stop byte
        self.assert_released(result)                            # EOF stopped it
        self.assertTrue(result["cleanup"]["complete"])

    def test_child_never_exits_bounded_no_signal(self):
        ports, k, _, result = run("never_exit")
        self.assertFalse(result["cleanup"]["complete"])
        self.assertFalse(result["child"]["reaped"])
        self.assertEqual(result["cleanup"]["still_owned"]["pid"], result["pid"])
        self.assertEqual(result["child"]["reap_deadline_s"], CFG.reap_timeout_s)
        self.assertEqual(result["child"]["signals_sent"], 0)

    def test_parent_pipe_close_failure_after_fork_is_counted(self):
        def fail_close(fd):
            return OSError(errno.EIO, "close") if fd == 10 else None
        ports, k, _, result = run(ops_fail={"close": fail_close})
        self.assertEqual(result["primary_failure"]["code"], "PARENT_PIPE_CLOSE_FAILED")
        self.assertEqual((result["forks"], result["pid"] is not None), (1, True))
        self.assertEqual(ports.custody.calls, [])
        self.assert_released(result)
        self.assertEqual(len([c for c in ports.ops.calls if c == ("close", 10)]), 1)

    def test_fork_failure_closes_each_pipe_end_once(self):
        ports, k, _, result = run(ops_fail={"fork": BlockingIOError(errno.EAGAIN, "fork")})
        self.assertEqual(result["forks"], 0)
        self.assertEqual(sorted(c[1] for c in names(ports.ops, "close")), [10, 11, 12, 13])
        self.assertEqual(ports.ops.open_fds, {})
        self.assertTrue(result["cleanup"]["complete"])

    def test_acquire_failure_no_close_child_released(self):
        ports, k, _, result = run(custody_fail={"acquire": RuntimeError("acquire")})
        self.assertEqual(result["primary_failure"]["stage"], "SAMPLER_BOUND")
        self.assertEqual(ports.custody.calls, ["acquire", "finish"])
        self.assertEqual(ports.custody.close_attempts, 0)
        self.assert_released(result)

    def test_close_failure_not_retried(self):
        ports, k, _, result = run(custody_fail={"close": OSError(errno.EIO, "close")})
        self.assertEqual(result["primary_failure"]["stage"], "POST_EXIT_OBSERVED")
        self.assertEqual(ports.custody.close_attempts, 1)
        self.assertEqual(ports.custody.calls.count("close"), 1)
        self.assert_released(result)

    def test_close_not_confirmed(self):
        ports, k, _, result = run(confirm=False)
        self.assertEqual(result["primary_failure"]["code"], "CUSTODY_CLOSE_NOT_CONFIRMED")
        self.assertEqual(ports.custody.close_attempts, 1)
        self.assertNotIn("RELEASED", result["states"])

    def test_sampling_failure_then_finish_failure_still_releases(self):
        def reuse_after_first(ports, k):
            real = ports.sample

            def sample(sampler):
                tick = real(sampler)
                k.reuse(sampler.root_pid)
                return tick
            ports.sample = sample
        ports, k, _, result = run(custody_fail={"finish": RuntimeError("hooks stuck")},
                                  mutate=reuse_after_first)
        self.assertIn("REUSE", result["primary_failure"]["repr"])
        steps = {s["step"]: s["ok"] for s in result["cleanup"]["steps"]}
        self.assertEqual(steps["custody_close_single_attempt"], True)
        self.assertEqual(steps["custody_finish"], False)
        self.assertTrue(steps["cleanup_stop_byte"])
        self.assertFalse(result["cleanup"]["complete"])

    def test_pidfd_ready_before_stop(self):
        def die_after_first(ports, k):
            real = ports.sample

            def sample(sampler):
                tick = real(sampler)
                k.exit(sampler.root_pid)
                return tick
            ports.sample = sample
        ports, k, _, result = run(mutate=die_after_first)
        self.assertEqual(result["primary_failure"]["code"], "PIDFD_READY_BEFORE_STOP")
        self.assertEqual(ports.custody.close_attempts, 1)
        self.assert_released(result)

    def test_exit_identity_contradiction(self):
        def tamper(ports, k):
            real = ports.ops.write

            def write(fd, data):
                n = real(fd, data)
                k.procs[ports.ops.child.pid].starttime += 1
                return n
            ports.ops.write = write
        ports, k, _, result = run(mutate=tamper)
        # DEV006/F3: the shared owned-tree refresh now rejects the readable
        # zombie with a changed identity itself (it no longer counts it as
        # an exit), one step before the lifecycle's own exit-identity check.
        failure = result["primary_failure"]
        self.assertEqual((failure["stage"], failure["type"]),
                         ("EXITED", "NativeSamplerCapabilityError"))
        self.assertIn("OWNED_PID_REUSE_REJECTED", failure["repr"])
        self.assertIn("state=Z", failure["repr"])

    def test_foreign_reaper_detected(self):
        def steal(ports, k):
            real = ports.ops.write

            def write(fd, data):
                n = real(fd, data)
                k.procs.pop(ports.ops.child.pid)
                return n
            ports.ops.write = write
        ports, k, _, result = run(mutate=steal)
        self.assertIn("PROCESS_ABSENT", result["primary_failure"]["repr"])
        self.assertFalse(result["child"]["reaped"])

    def test_evaluation_never_reads_source_lines(self):
        import linecache
        ports, k, admission, result = run("never_ready")
        real = linecache.getlines

        def refuse(*a, **kw):
            raise AssertionError("linecache read")
        linecache.getlines = refuse
        try:
            checks = lifecycle.evaluate(CFG, result)
        finally:
            linecache.getlines = real
        self.assertEqual(checks[-1]["name"], "evaluation")
        self.assertIn(checks[-1]["observed"]["type"], ("TypeError", "KeyError"))


# ---------------------------------------------------------------------------
# Observation-window guard subclass on the real p18 DevelopmentGuard base
# ---------------------------------------------------------------------------

GUARD_SCRIPT = textwrap.dedent(r"""
    import os, sys, types, json
    sys.dont_write_bytecode = True
    sys.path.insert(0, %(here)r)
    import wiring, native_close_smoke as smoke
    pins = smoke.load_pins(wiring.DEFAULT_PINS)
    verified = smoke.verify_source_tree(smoke.SOURCE_ROOT, pins)
    mod = types.ModuleType("p18_guard_verified")
    sys.modules[mod.__name__] = mod
    exec(compile(verified["development_guard.py"],
                 os.path.join(smoke.SOURCE_ROOT, "development_guard.py"), "exec"), mod.__dict__)
    from p18_custody import observing_guard_class
    class Cap: pass
    rt = types.SimpleNamespace(p01_path="/nonexistent/p01.py", effects_path="/nonexistent/e.py",
        os_close=os.close, native_class=Cap, handle_class=Cap, prepare_capability_class=Cap,
        capture_capability_class=Cap, proof_capability_class=Cap, view_capability_class=Cap)
    out = {}
    g = observing_guard_class(mod.DevelopmentGuard)(rt, "/nonexistent-run-root", [])
    me = os.getpid()
    def attempt(name, fn):
        try:
            fn(); out[name] = "allowed"
        except BaseException as exc:
            out[name] = type(exc).__name__ + ":" + str(exc)
    def read(path):
        with open(path, "rb", buffering=0) as fh: fh.read(64)
    r, w = os.pipe()
    g.install()
    attempt("stat_outside_window", lambda: read("/proc/%%d/stat" %% me))
    with g.observe_window():
        attempt("stat_in_window", lambda: read("/proc/%%d/stat" %% me))
        attempt("rollup_in_window", lambda: read("/proc/%%d/smaps_rollup" %% me))
        attempt("status_in_window", lambda: read("/proc/%%d/status" %% me))
        attempt("self_stat_in_window", lambda: read("/proc/self/stat"))
        attempt("close_in_window", lambda: os.close(w))
        attempt("phase_in_window", lambda: g.enter_phase("REGISTER", {}, None))
        attempt("nested_window", lambda: g.observe_window().__enter__())
    g.enter_phase("REGISTER", {}, None)
    attempt("window_in_phase", lambda: g.observe_window().__enter__())
    g.leave_phase()
    g.finish()
    rep = g.report()
    out["observe_reads"] = rep["observe_reads"]
    out["observe_windows"] = rep["observe_windows"]
    out["events"] = [e["kind"] for e in rep["events"]]
    out["denied"] = [d["reason"] for d in rep["denied"]]
    print(json.dumps(out))
""")


class ObservingGuardTests(unittest.TestCase):
    def test_window_admits_only_pid_stat_and_rollup(self):
        proc = subprocess.run([sys.executable, "-c", GUARD_SCRIPT % {"here": HERE}],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["stat_in_window"], "allowed")
        self.assertEqual(out["rollup_in_window"], "allowed")
        for name, reason in (("stat_outside_window", "PROC_READ_PHASE"),
                             ("status_in_window", "PROC_READ_PHASE"),
                             ("self_stat_in_window", "PROC_READ_PHASE"),
                             ("close_in_window", "OS_CLOSE_ACCEPTED_BEGIN_ONLY"),
                             ("phase_in_window", "CONTROLLER_PHASE_DURING_OBSERVE_WINDOW"),
                             ("nested_window", "OBSERVE_WINDOW_STATE"),
                             ("window_in_phase", "OBSERVE_WINDOW_STATE")):
            self.assertEqual(out[name], "ScopeViolation:" + reason, name)
        self.assertEqual(out["observe_reads"], 2)
        self.assertEqual(out["observe_windows"], 1)
        self.assertEqual(out["events"][:2], ["observe_enter", "observe_leave"])


STUCK_SCRIPT = textwrap.dedent(r"""
    import os, sys, types, json, traceback
    sys.dont_write_bytecode = True
    sys.path.insert(0, %(here)r)
    import wiring, lifecycle, native_close_smoke as smoke
    pins = smoke.load_pins(wiring.DEFAULT_PINS)
    verified = smoke.verify_source_tree(smoke.SOURCE_ROOT, pins)
    mod = types.ModuleType("p18_guard_verified")
    sys.modules[mod.__name__] = mod
    exec(compile(verified["development_guard.py"],
                 os.path.join(smoke.SOURCE_ROOT, "development_guard.py"), "exec"), mod.__dict__)
    from p18_custody import observing_guard_class
    class Cap: pass
    rt = types.SimpleNamespace(p01_path="/nonexistent/p01.py", effects_path="/nonexistent/e.py",
        os_close=os.close, native_class=Cap, handle_class=Cap, prepare_capability_class=Cap,
        capture_capability_class=Cap, proof_capability_class=Cap, view_capability_class=Cap)
    out = {}
    def attempt(name, fn):
        try:
            value = fn()
            out[name] = ["allowed", value if isinstance(value, (int, str, type(None))) else None]
        except BaseException as exc:
            out[name] = [type(exc).__name__, str(exc)]
    def raised_in_lifecycle():
        try:
            lifecycle.need(False, "PROBE")
        except lifecycle.LifecycleError as exc:
            return exc
    g = observing_guard_class(mod.DevelopmentGuard)(rt, "/nonexistent-run-root", [])
    r, w = os.pipe()
    g.install()
    for _ in range(255):                      # public API only
        g.enter_phase("REGISTER", {}, None); g.leave_phase()
    with g.observe_window():
        pass
    attempt("enter_at_bound", lambda: g.enter_phase("REGISTER", {}, None))
    attempt("finish", g.finish)
    out["stuck"] = [g.installed, g.phase, sys.gettrace() is not None]
    exc = raised_in_lifecycle()
    attempt("format_exc", lambda: "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    attempt("describe_exception", lambda: lifecycle.describe_exception(exc)["type"])
    attempt("evaluate", lambda: lifecycle.evaluate(lifecycle.LifecycleConfig(),
                                                   {"primary_failure": None})[-1]["name"])
    attempt("stop_byte", lambda: os.write(w, b"S"))
    child = lifecycle.OwnedChild(); child.fds["ctl_w"] = w; steps = []
    attempt("release", lambda: lifecycle.release_child(lifecycle.LifecycleConfig(), child,
                                                       {}, steps, lifecycle.RealOps()) and None)
    out["steps"] = [[s["step"], s["ok"], s.get("retried"), s["error"]["repr"]] for s in steps]
    out["profile_after_denial"] = sys.getprofile() is not None
    sys.settrace(None)
    print(json.dumps(out))
""")


class StuckGuardTests(unittest.TestCase):
    """Real p18 guard base driven into finish() failure with hooks active.

    Reached through the public API only (the 512-event bound), in a
    subprocess, with a stub runtime and plain pipe fds: no child, no pidfd.
    """

    def test_cleanup_paths_under_stuck_hooks(self):
        proc = subprocess.run([sys.executable, "-c", STUCK_SCRIPT % {"here": HERE}],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=60,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        bound = ["ScopeViolation", "DEVELOPMENT_EVENT_BOUND"]
        self.assertEqual(out["enter_at_bound"], bound)
        self.assertEqual(out["finish"], bound)
        self.assertEqual(out["stuck"], [True, "REGISTER", True])
        # The DEV_VERIFY003 concern, now observed: traceback formatting reads
        # source files and is denied under stuck hooks ...
        self.assertEqual(out["format_exc"][0], "ScopeViolation")
        self.assertTrue(out["format_exc"][1].startswith("UNPLANNED_READ:"))
        # ... while the file-I/O-free paths used by this layer still work.
        self.assertEqual(out["describe_exception"], ["allowed", "LifecycleError"])
        self.assertEqual(out["evaluate"], ["allowed", "evaluation"])
        self.assertEqual(out["stop_byte"], ["allowed", 1])
        self.assertEqual(out["release"], ["allowed", None])
        self.assertEqual(out["steps"], [["close_ctl_w", False, False,
                                         "ScopeViolation('OS_CLOSE_ACCEPTED_BEGIN_ONLY')"]])
        # CPython removes a profile function that raises: after the first
        # profile-hook denial the base guard no longer sees C calls. Recorded
        # as a property of the p18 development monitor, not isolation.
        self.assertFalse(out["profile_after_denial"])


if __name__ == "__main__":
    unittest.main()
