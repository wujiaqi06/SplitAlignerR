"""Linux /proc process-tree backend for the Stage-B development control plane.

DEVELOPMENT ONLY. This is not LINUX platform authority and is not frozen.

It implements the sampler-backend protocol that the unchanged
`stage_b_controller.ProcessTreeRssSampler` consumes (and that
`DarwinLibprocSamplerBackend` implements on Darwin), with Linux semantics:

    identity      (pid, starttime_ticks, 0) from /proc/<pid>/stat field 22.
                  Linux has no sub-tick start component, so slot 3 is a
                  reserved 0 (keeps the controller's 3-int identity text and
                  its `identity[1:]` ordering valid).
    live/exit     a missing /proc entry (ENOENT/ESRCH) is absence; a readable
                  Z/X record is an exit only after its identity and PGID
                  matched the caller's expectation (observe_expected); every
                  other read/parse failure fails closed.
    PGID census   two consecutive complete /proc scans must agree, with the
                  same bounded follow-up budget as Darwin's dual census.
                  A scan tolerates only entries that vanish mid-scan (ENOENT/
                  ESRCH); EACCES or malformed stat anywhere fails closed,
                  because an unreadable entry could hide a group member.
    RSS           smaps_rollup Rss (kB * 1024), bracketed by stat reads
                  before and after that must both show the expected identity
                  AND the expected PGID; zero RSS gets the Darwin-equivalent
                  bounded identity-revalidated follow-up.

Known limits (unchanged from the D1 design): sequential /proc scans are not
an atomic snapshot and cannot see a process that lives wholly between scans;
PGID is not a security boundary; polling cannot prove a lifetime RSS maximum.

The controller dispatches on OWNED_TREE_PROTOCOL and calls this class's own
`live_owned_tree` (DEV006; the Darwin algorithm called unbound collapsed a
readable Z/X into absence before checking identity/PGID). `classify_group_
members` is the single census + classification + retirement entry shared by
the owned-tree refresh and the signal route; `observe_expected` is the single
read -> identity -> PGID -> live/Z/X order for rss, zero-RSS retry, known-
member refresh and the controller's post-RSS-absence revalidation.
"""
import dataclasses
import threading
import time
import types

from proc_source import ProcAbsent, ProcReadError, RollupParseError, \
    parse_smaps_rollup_rss_bytes

MECHANISM_ID = "LINUX_PROCFS_PROCESS_TREE_DEVELOPMENT_V1"
GROUP_CENSUS_FOLLOWUP_ROUNDS = 4
GROUP_CENSUS_FOLLOWUP_INTERVAL_SECONDS = 0.001
ZERO_RSS_FOLLOWUP_ROUNDS = 4
ZERO_RSS_FOLLOWUP_INTERVAL_SECONDS = 0.001
ABSENT_STATES = frozenset(("Z", "X"))
PF_KTHREAD = 0x00200000            # include/linux/sched.h, Linux 5.4
KTHREAD_COMM_MAX = 63              # proc_task_name() tcomm[64] for wq workers


class StatParseError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def kernel_thread_tolerant(parse_proc_stat):
    """Wrap the strict p18 stat parser for whole-/proc census use.

    Linux 5.4 appends the workqueue name to kworker comm in /proc/<pid>/stat
    (e.g. `kworker/u128:0-efi_rts_wq`, up to 63 bytes); the p18 parser caps
    comm at 15 (TASK_COMM_LEN - 1) and raises STAT_COMM_LENGTH. Only in that
    case, and only for a 16..63 byte comm, the unchanged strict parser is run
    again with a 15-byte placeholder comm, and the record is accepted only if
    stat field 9 (flags) has PF_KTHREAD. Any other process with an overlong
    comm, and every other parse error, still fails closed.
    """
    def parse(raw):
        try:
            return parse_proc_stat(raw)
        except ValueError as exc:
            if getattr(exc, "code", None) != "STAT_COMM_LENGTH":
                raise
        first, last = raw.find(b" ("), raw.rfind(b") ")
        comm = raw[first + 2:last]
        if not 16 <= len(comm) <= KTHREAD_COMM_MAX:
            raise StatParseError("STAT_COMM_LENGTH")
        stat = parse_proc_stat(raw[:first + 2] + b"x" * 15 + raw[last:])
        if not stat.values[9 - 4] & PF_KTHREAD:
            raise StatParseError("STAT_COMM_LENGTH_NOT_KERNEL_THREAD")
        return dataclasses.replace(stat, comm=comm)
    parse.wrapped = parse_proc_stat
    return parse


class LinuxSamplerCapabilityError(RuntimeError):
    pass


class LinuxSamplerProcessAbsent(LinuxSamplerCapabilityError):
    pass


class LinuxSamplerIdentityAwareExitRace(LinuxSamplerProcessAbsent):
    pass


STANDALONE_ERRORS = types.SimpleNamespace(
    CapabilityError=LinuxSamplerCapabilityError,
    ProcessAbsent=LinuxSamplerProcessAbsent,
    IdentityAwareExitRace=LinuxSamplerIdentityAwareExitRace)


class ProcRecord:
    __slots__ = ("pid", "ppid", "pgid", "session", "state", "starttime_ticks")

    def __init__(self, pid, ppid, pgid, session, state, starttime_ticks):
        self.pid, self.ppid, self.pgid = pid, ppid, pgid
        self.session, self.state = session, state
        self.starttime_ticks = starttime_ticks

    @property
    def identity(self):
        return (self.pid, self.starttime_ticks, 0)

    @property
    def absent(self):
        return self.state in ABSENT_STATES

    def report(self):
        return {name: getattr(self, name) for name in self.__slots__}


class LinuxProcSamplerBackend:
    """Fail-closed identity-aware /proc process-tree RSS authority (dev)."""

    # Tells a protocol-dispatching controller that `rss` accepts and checks
    # (pid, expected_identity, expected_pgid) across the whole read bracket.
    RSS_BINDS_IDENTITY_AND_GROUP = True

    def __init__(self, source, parse_proc_stat, errors=STANDALONE_ERRORS,
                 sleep=time.sleep, clock=time.monotonic_ns):
        self._source = source
        self._parse_stat = parse_proc_stat
        self._errors = errors
        self._sleep = sleep
        self._clock = clock
        self._authority_lock = threading.Lock()
        self._authority_pgid = None
        self._authority_root_identity = None
        self._group_retired = False
        self._retirement_count = 0
        self._retirement_source = None
        self._last_live_identities = {}    # pid -> (identity, observed pgid)
        self._last_group_census_pgid = None
        self._last_group_census = ()
        self._counts = dict.fromkeys((
            "stat_reads", "rollup_reads", "proc_scans", "scan_vanished_entries",
            "group_census_count", "group_census_attempt_count",
            "dual_census_agreement_count", "group_census_disagreement_count",
            "group_census_followup_round_count", "group_census_recovery_count",
            "group_census_unresolved_count", "maximum_group_census_size",
            "zero_rss_initial_count", "zero_rss_followup_round_count",
            "zero_rss_recovery_count", "zero_rss_exit_race_count",
            "zero_rss_unresolved_count",
            "known_identity_absence_revalidation_count",
            "known_identity_absence_exit_count",
            "known_identity_absence_fail_closed_count",
            "rss_identity_bracket_count", "scan_ns_total", "scan_ns_maximum"), 0)

    # ------------------------------------------------------------------
    # single-process observation
    # ------------------------------------------------------------------
    def _fail(self, code):
        return self._errors.CapabilityError(code)

    def observe(self, pid):
        """One stat read -> ProcRecord (zombies included); absence raises."""
        if type(pid) is not int or isinstance(pid, bool) or pid <= 0:
            raise self._fail("INVALID_PID:%r" % (pid,))
        self._counts["stat_reads"] += 1
        try:
            raw = self._source.read(pid, "stat")
        except ProcAbsent:
            raise self._errors.ProcessAbsent("PROCESS_ABSENT:pid=%d" % pid)
        except ProcReadError as exc:
            raise self._fail("PROC_STAT_READ_FAILED:pid=%d:%s:errno=%s"
                             % (pid, exc.code, exc.errno))
        return self._record(pid, raw)

    def _record(self, pid, raw):
        try:
            stat = self._parse_stat(raw)
        except ValueError as exc:
            raise self._fail("PROC_STAT_PARSE:pid=%d:%s"
                             % (pid, getattr(exc, "code", type(exc).__name__)))
        if stat.pid != pid:
            raise self._fail("PROC_STAT_PID_MISMATCH:requested=%d:observed=%d"
                             % (pid, stat.pid))
        # pgrp/session 0 is legitimate for kthreadd and kernel threads; such a
        # record can never match a positive worker PGID. A process that is
        # itself the subject of identity_and_group must have pgid > 0.
        if stat.pgrp < 0 or stat.starttime_ticks <= 0:
            raise self._fail("PROC_STAT_IDENTITY_INVALID:pid=%d" % pid)
        return ProcRecord(pid, stat.ppid, stat.pgrp, stat.session, stat.state,
                          stat.starttime_ticks)

    def identity_and_group(self, pid):
        record = self.observe(pid)
        if record.absent:
            raise self._errors.ProcessAbsent(
                "PROCESS_ZOMBIE:pid=%d:state=%s" % (pid, record.state))
        if record.pgid <= 0:
            raise self._fail("PROC_STAT_PGID_INVALID:pid=%d:pgid=%d" % (pid, record.pgid))
        self._last_live_identities[pid] = (record.identity, record.pgid)
        return record.ppid, record.pgid, record.identity

    def identity(self, pid):
        ppid, _pgid, identity = self.identity_and_group(pid)
        return ppid, identity

    CODES = {"RSS": ("RSS_PID_REUSE_REJECTED", "RSS_PGID_CHANGED"),
             "KNOWN_IDENTITY": ("OWNED_PID_REUSE_REJECTED",
                                "OWNED_PROCESS_ESCAPED_WORKER_PGID"),
             "RSS_ABSENCE": ("RSS_PID_REUSE_REJECTED", "RSS_PGID_CHANGED")}

    def observe_expected(self, pid, expected_identity, expected_pgid, where):
        """The single F3 classification order for a pid with known expectations.

            read     ENOENT/ESRCH -> ProcessAbsent (no contradicting evidence);
                     EACCES, other read errors, parse errors -> fail closed;
            identity a readable record (live, Z or X) with another identity
                     -> fail closed (PID reuse), never an exit;
            PGID     a readable record in another group -> fail closed
                     (group escape), never an exit;
            state    only then Z/X -> IdentityAwareExitRace (validated exit)
                     and live -> the record is returned.
        A readable Z/X is therefore never collapsed into absence before the
        caller's identity and PGID expectations were checked.
        """
        record = self.observe(pid)
        reuse_code, group_code = self.CODES[where]
        if record.identity != expected_identity:
            raise self._fail("%s:pid=%d:state=%s:expected=%r:observed=%r"
                             % (reuse_code, pid, record.state,
                                expected_identity, record.identity))
        if expected_pgid is not None and record.pgid != expected_pgid:
            raise self._fail("%s:pid=%d:state=%s:expected=%d:observed=%d"
                             % (group_code, pid, record.state, expected_pgid,
                                record.pgid))
        if record.absent:
            raise self._errors.IdentityAwareExitRace(
                "%s_VALIDATED_EXIT:pid=%d:state=%s" % (where, pid, record.state))
        return record

    def revalidate_expected_exit(self, pid, expected_identity, expected_pgid):
        """Controller hook after an RSS absence: exit only if validated."""
        self._validate_identity(expected_identity, pid)
        try:
            self.observe_expected(pid, expected_identity, expected_pgid, "RSS_ABSENCE")
        # Order matters: IdentityAwareExitRace < ProcessAbsent < CapabilityError.
        except self._errors.IdentityAwareExitRace:
            return "VALIDATED_EXIT"
        except self._errors.ProcessAbsent:
            return "ABSENT_ENOENT"
        raise self._fail("RSS_UNREADABLE_LIVE_PROCESS:pid=%d" % pid)

    def _validate_identity(self, identity, expected_pid=None):
        """Instance method: the controller's shared algorithm calls it on us."""
        if (type(identity) is not tuple or len(identity) != 3
                or any(type(v) is not int for v in identity)
                or identity[0] <= 0 or identity[1] <= 0 or identity[2] != 0
                or (expected_pid is not None and identity[0] != expected_pid)):
            raise self._fail("PROCESS_IDENTITY_INVALID:%r" % (identity,))

    # ------------------------------------------------------------------
    # census
    # ------------------------------------------------------------------
    def _scan(self):
        """One complete /proc scan -> {pid: ProcRecord}; fails closed."""
        start = self._clock()
        try:
            pids = self._source.list_pids()
        except ProcReadError as exc:
            raise self._fail("PROC_LIST_FAILED:%s:errno=%s" % (exc.code, exc.errno))
        table = {}
        for pid in pids:
            self._counts["stat_reads"] += 1
            try:
                raw = self._source.read(pid, "stat")
            except ProcAbsent:
                self._counts["scan_vanished_entries"] += 1
                continue
            except ProcReadError as exc:
                raise self._fail("PROC_CENSUS_READ_FAILED:pid=%d:%s:errno=%s"
                                 % (pid, exc.code, exc.errno))
            table[pid] = self._record(pid, raw)
        elapsed = self._clock() - start
        self._counts["proc_scans"] += 1
        self._counts["scan_ns_total"] += elapsed
        self._counts["scan_ns_maximum"] = max(self._counts["scan_ns_maximum"], elapsed)
        return table

    def _stable_selection(self, select, label):
        """Two consecutive scans must select the same pids (bounded retries)."""
        first = select(self._scan())
        second = select(self._scan())
        self._counts["group_census_attempt_count"] += 1
        if first == second:
            return second, False
        self._counts["group_census_disagreement_count"] += 1
        for round_number in range(1, GROUP_CENSUS_FOLLOWUP_ROUNDS + 1):
            if round_number > 1:
                self._sleep(GROUP_CENSUS_FOLLOWUP_INTERVAL_SECONDS)
            first = select(self._scan())
            second = select(self._scan())
            self._counts["group_census_attempt_count"] += 1
            self._counts["group_census_followup_round_count"] += 1
            if first == second:
                self._counts["group_census_recovery_count"] += 1
                return second, True
            self._counts["group_census_disagreement_count"] += 1
        self._counts["group_census_unresolved_count"] += 1
        raise self._fail("%s_CENSUS_DISAGREEMENT_UNRESOLVED:first=%r:second=%r:"
                         "followup_rounds=%d" % (label, first, second,
                                                 GROUP_CENSUS_FOLLOWUP_ROUNDS))

    def process_group_pids(self, pgid):
        if type(pgid) is not int or pgid <= 0:
            raise self._fail("INVALID_GROUP_PID")
        census, _recovered = self._stable_selection(
            lambda table: tuple(sorted(p for p, r in table.items() if r.pgid == pgid)),
            "GROUP")
        self._counts["group_census_count"] += 1
        self._counts["dual_census_agreement_count"] += 1
        self._last_group_census = census
        self._last_group_census_pgid = pgid
        self._counts["maximum_group_census_size"] = max(
            self._counts["maximum_group_census_size"], len(census))
        return census

    def children(self, pid):
        if type(pid) is not int or pid <= 0:
            raise self._fail("INVALID_PARENT_PID")
        census, _recovered = self._stable_selection(
            lambda table: tuple(sorted(p for p, r in table.items() if r.ppid == pid)),
            "CHILD")
        return census

    # ------------------------------------------------------------------
    # authority
    # ------------------------------------------------------------------
    def bind_process_group_authority(self, pgid, root_identity):
        if type(pgid) is not int or pgid <= 0:
            raise self._fail("INVALID_AUTHORITY_PGID")
        self._validate_identity(root_identity, pgid)
        with self._authority_lock:
            if self._authority_pgid is None:
                self._authority_pgid = pgid
                self._authority_root_identity = root_identity
                return
            if (self._authority_pgid != pgid
                    or self._authority_root_identity != root_identity):
                raise self._fail("PROCESS_GROUP_AUTHORITY_REBIND_REJECTED")

    def _revalidate_known_identity_absent_from_stable_census(
            self, pid, expected_identity, expected_pgid):
        """A census omission is not exit proof: re-query this exact pid once."""
        self._validate_identity(expected_identity, pid)
        if type(expected_pgid) is not int or expected_pgid <= 0:
            raise self._fail("KNOWN_IDENTITY_EXPECTED_PGID_INVALID:pid=%d" % pid)
        self._counts["known_identity_absence_revalidation_count"] += 1
        try:
            self.observe_expected(pid, expected_identity, expected_pgid, "KNOWN_IDENTITY")
        except self._errors.ProcessAbsent as exc:     # ENOENT or validated Z/X
            self._counts["known_identity_absence_exit_count"] += 1
            raise self._errors.IdentityAwareExitRace(
                "KNOWN_IDENTITY_NATIVE_EXIT:pid=%d" % pid) from exc
        except self._errors.CapabilityError:
            self._counts["known_identity_absence_fail_closed_count"] += 1
            raise
        self._counts["known_identity_absence_fail_closed_count"] += 1
        raise self._fail("STABLE_GROUP_CENSUS_IDENTITY_CONTRADICTION:pid=%d:"
                         "identity=%r:pgid=%d" % (pid, expected_identity, expected_pgid))

    # Tells the controller to use this class's own live_owned_tree (which
    # classifies readable Z/X members before treating them as exits) instead
    # of the Darwin algorithm called unbound.
    OWNED_TREE_PROTOCOL = "LINUX_IDENTITY_BEFORE_EXIT_V1"

    def _retire_group_locked(self, pgid, source):
        """The one irreversible 'group observed empty' transition.

        Every entry that discovers the bound group empty (owned-tree refresh,
        the signal route, cleanup) calls this; nothing ever clears it."""
        if pgid != self._authority_pgid:
            raise self._fail("RETIREMENT_PGID_NOT_BOUND:pgid=%r" % (pgid,))
        if not self._group_retired:
            self._group_retired = True
            self._retirement_count += 1
            self._retirement_source = source

    def classify_group_members(self, pgid, known_identities, source):
        """Census + F3 classification + retirement, under the authority lock.

        -> (live {pid: identity}, absent set). Empty -> retired (irreversible);
        retired and non-empty -> PGID reuse, fail closed. Readable members in
        another group, predating the root, or contradicting a known identity
        fail closed even when they are Z/X."""
        with self._authority_lock:
            if self._authority_pgid is None or self._authority_root_identity is None:
                raise self._fail("PROCESS_GROUP_AUTHORITY_NOT_BOUND")
            if pgid != self._authority_pgid:
                raise self._fail("GROUP_AUTHORITY_NOT_BOUND_TO_TARGET:pgid=%r" % (pgid,))
            root_identity = self._authority_root_identity
            census = self.process_group_pids(pgid)
            absent = set()
            for missing in sorted(set(known_identities) - set(census)):
                try:
                    self._revalidate_known_identity_absent_from_stable_census(
                        missing, known_identities[missing], pgid)
                except self._errors.IdentityAwareExitRace:
                    absent.add(missing)
            if self._group_retired:
                if census:
                    raise self._fail("PGID_REUSE_OR_AMBIGUITY:pgid=%d:pids=%r"
                                     % (pgid, census))
                return {}, absent
            if not census:
                self._retire_group_locked(pgid, source)
                return {}, absent
            live = {}
            for member in census:
                try:
                    record = self.observe(member)
                except self._errors.ProcessAbsent:
                    absent.add(member)          # ENOENT after the census
                    continue
                if record.pgid != pgid:
                    raise self._fail("GROUP_MEMBER_PGID_MISMATCH:pid=%d:expected=%d:"
                                     "observed=%d:state=%s"
                                     % (member, pgid, record.pgid, record.state))
                if record.identity[1:] < root_identity[1:]:
                    raise self._fail("GROUP_MEMBER_PREDATES_AUTHORITY_ROOT:pid=%d:"
                                     "identity=%r:root=%r"
                                     % (member, record.identity, root_identity))
                known = known_identities.get(member)
                if known is not None and known != record.identity:
                    raise self._fail("OWNED_PID_REUSE_REJECTED:pid=%d:state=%s"
                                     % (member, record.state))
                if record.absent:
                    absent.add(member)          # validated Z/X
                    continue
                self._last_live_identities[member] = (record.identity, record.pgid)
                live[member] = record.identity
            # Validated zombies still pin the PGID, so a census holding only
            # them is not yet "empty"; the next empty census retires.
            return live, absent

    def live_owned_tree(self, known_identities):
        """Refresh exact ownership from the bound dedicated-PGID census."""
        if not known_identities:
            raise self._fail("OWNED_IDENTITY_SET_EMPTY")
        for pid, expected in sorted(known_identities.items()):
            self._validate_identity(expected, pid)
        with self._authority_lock:
            pgid = self._authority_pgid
        live, absent = self.classify_group_members(pgid, known_identities, "OWNED_TREE")
        unclassified = set(known_identities) - set(live) - absent
        if unclassified:
            raise self._fail("KNOWN_IDENTITY_CLASSIFICATION_INCOMPLETE:pids=%r"
                             % sorted(unclassified))
        return live, absent

    # ------------------------------------------------------------------
    # RSS
    # ------------------------------------------------------------------
    def _rss_once(self, pid, expected_identity, expected_pgid):
        """Identity-bracketed smaps_rollup Rss read. Returns bytes (may be 0)."""
        # F3: identity and PGID are checked on the readable record before a
        # Z/X state may be classified as exit (same rule as after the read).
        try:
            before = self.observe_expected(pid, expected_identity, expected_pgid, "RSS")
        except self._errors.IdentityAwareExitRace as exc:
            raise self._errors.ProcessAbsent("PROCESS_ABSENT_RSS:pid=%d" % pid) from exc
        self._counts["rollup_reads"] += 1
        empty = False
        try:
            resident = parse_smaps_rollup_rss_bytes(
                self._source.read(pid, "smaps_rollup"))
        except ProcAbsent:
            resident, empty = None, True
        except RollupParseError as exc:
            if exc.code != "SMAPS_ROLLUP_EMPTY":
                raise self._fail("SMAPS_ROLLUP_PARSE:pid=%d:%s" % (pid, exc.code))
            resident, empty = None, True
        except ProcReadError as exc:
            raise self._fail("SMAPS_ROLLUP_READ_FAILED:pid=%d:%s:errno=%s"
                             % (pid, exc.code, exc.errno))
        try:
            after = self.observe(pid)
        except self._errors.ProcessAbsent as exc:
            raise self._errors.IdentityAwareExitRace(
                "PROCESS_EXITED_DURING_RSS:pid=%d" % pid) from exc
        self._counts["rss_identity_bracket_count"] += 1
        if after.identity != before.identity:
            raise self._fail("RSS_IDENTITY_CHANGED_DURING_READ:pid=%d" % pid)
        # Checked before exit classification: a contradictory group is never
        # reported as an ordinary exit race.
        if after.pgid != expected_pgid:
            raise self._fail("RSS_PGID_CHANGED_DURING_READ:pid=%d:expected=%d:"
                             "observed=%d" % (pid, expected_pgid, after.pgid))
        if after.absent:
            raise self._errors.IdentityAwareExitRace(
                "PROCESS_EXITED_DURING_RSS:pid=%d" % pid)
        if empty:
            raise self._fail("SMAPS_ROLLUP_UNAVAILABLE_LIVE_PROCESS:pid=%d" % pid)
        return resident

    def _rss_authority(self, pid, expected_identity, expected_pgid):
        """-> (identity, pgid) the whole RSS bracket must observe.

        Sources, all of which that apply must agree (else fail closed):
          explicit     the caller's expected_identity / expected_pgid;
          remembered   (identity, pgid) from this backend's latest
                       identity_and_group(pid) - only if it is the same
                       identity;
          authority    the bound dedicated PGID, if pid is in the latest
                       stable census of that PGID (both this class's and the
                       controller's shared live_owned_tree take that census
                       immediately before sampling RSS).
        A pid never verified as owned (e.g. the harness itself during
        admission) is bound only to its own remembered group, never to the
        child-group authority. No identity or no group -> fail closed.
        """
        remembered = self._last_live_identities.get(pid)
        if expected_identity is None:
            if remembered is None:
                raise self._fail("RSS_IDENTITY_AUTHORITY_REQUIRED:pid=%r" % (pid,))
            expected_identity = remembered[0]
        self._validate_identity(expected_identity, pid)
        if expected_pgid is not None and (type(expected_pgid) is not int
                                          or expected_pgid <= 0):
            raise self._fail("RSS_EXPECTED_PGID_INVALID:pid=%d:%r" % (pid, expected_pgid))
        groups = {}
        if expected_pgid is not None:
            groups["explicit"] = expected_pgid
        if remembered is not None and remembered[0] == expected_identity:
            groups["remembered"] = remembered[1]
        with self._authority_lock:
            if (self._authority_pgid is not None
                    and self._last_group_census_pgid == self._authority_pgid
                    and pid in self._last_group_census):
                groups["authority"] = self._authority_pgid
        if not groups:
            raise self._fail("RSS_GROUP_AUTHORITY_REQUIRED:pid=%d" % pid)
        if len(set(groups.values())) != 1:
            raise self._fail("RSS_GROUP_AUTHORITY_CONTRADICTION:pid=%d:%r"
                             % (pid, sorted(groups.items())))
        return expected_identity, next(iter(groups.values()))

    def rss(self, pid, expected_identity=None, expected_pgid=None):
        """RSS bound to an identity AND a process group across the read.

        The unchanged controller passes only pid; then the identity and PGID
        come from `_rss_authority` (the controller always calls
        `live_owned_tree` -> `identity_and_group` immediately before `rss`).
        """
        if type(pid) is not int or isinstance(pid, bool) or pid <= 0:
            raise self._fail("INVALID_PID:%r" % (pid,))
        expected_identity, expected_pgid = self._rss_authority(
            pid, expected_identity, expected_pgid)
        resident = self._rss_once(pid, expected_identity, expected_pgid)
        if resident > 0:
            return resident
        self._counts["zero_rss_initial_count"] += 1
        for round_number in range(1, ZERO_RSS_FOLLOWUP_ROUNDS + 1):
            if round_number > 1:
                self._sleep(ZERO_RSS_FOLLOWUP_INTERVAL_SECONDS)
            self._counts["zero_rss_followup_round_count"] += 1
            try:
                resident = self._rss_once(pid, expected_identity, expected_pgid)
            except self._errors.ProcessAbsent:
                self._counts["zero_rss_exit_race_count"] += 1
                raise
            if resident > 0:
                self._counts["zero_rss_recovery_count"] += 1
                return resident
        self._counts["zero_rss_unresolved_count"] += 1
        raise self._fail("SMAPS_ROLLUP_ZERO_RSS_UNRESOLVED:pid=%d:followup_rounds=%d"
                         % (pid, ZERO_RSS_FOLLOWUP_ROUNDS))

    # ------------------------------------------------------------------
    # evidence
    # ------------------------------------------------------------------
    def capability_evidence(self):
        return {
            "mechanism_id": MECHANISM_ID,
            "development_only": True,
            "source": getattr(self._source, "description", type(self._source).__name__),
            "identity_tuple": "(pid, /proc/<pid>/stat starttime_ticks, 0)",
            "group_member_pgid_field": "/proc/<pid>/stat field 5 (pgrp)",
            "census": "two consecutive complete /proc scans must agree",
            "group_census_followup_rounds": GROUP_CENSUS_FOLLOWUP_ROUNDS,
            "group_census_followup_interval_ns":
                int(GROUP_CENSUS_FOLLOWUP_INTERVAL_SECONDS * 1e9),
            "rss_field": "/proc/<pid>/smaps_rollup Rss kB * 1024, identity-bracketed",
            "zero_rss_followup_rounds": ZERO_RSS_FOLLOWUP_ROUNDS,
            "zero_rss_followup_interval_ns": int(ZERO_RSS_FOLLOWUP_INTERVAL_SECONDS * 1e9),
            "once_empty_never_reacquire": True,
            "external_process_table_call_count": 0,
            "fallback_available": False,
            "atomic_snapshot": False,
            "transient_lifetime_between_scans_visible": False,
        }

    def authority_evidence(self):
        with self._authority_lock:
            evidence = {
                "mechanism_id": MECHANISM_ID,
                "authority_pgid": self._authority_pgid,
                "authority_root_identity": list(self._authority_root_identity)
                    if self._authority_root_identity is not None else None,
                "group_retired": self._group_retired,
                "retirement_count": self._retirement_count,
                "retirement_source": self._retirement_source,
                "last_group_census_pids": list(self._last_group_census),
                "external_process_table_call_count": 0,
            }
            evidence.update(self._counts)
            return evidence
