"""Assembly of lifecycle ports: native (real host) and synthetic (fake kernel)."""
import hashlib
import os
import sys
import types

import control_plane
import lifecycle
from lifecycle import Ports, RealOps, need
from proc_source import RealProcSource
import native_close_smoke as smoke

HERE = os.path.dirname(os.path.realpath(__file__))
DEFAULT_PINS = os.path.realpath(os.path.join(
    HERE, "..", "..", "..", "..", "..", "INPUTS", "SOURCE_PINS.json"))
BUNDLED_PINS = os.path.join(HERE, "testsupport", "SOURCE_PINS.json")
if not os.path.isfile(DEFAULT_PINS):
    # Portable checkout: the byte-identical copy bundled for tests
    # (testsupport/MANIFEST.json records its sha256 and origin).
    DEFAULT_PINS = BUNDLED_PINS
PARSERS_ALIAS = "p18_parsers_verified"


def load_verified_parsers(pins_path=DEFAULT_PINS, root=smoke.SOURCE_ROOT):
    """p18 parsers.py from pin-verified bytes, under an alias module name so
    the candidate name `parsers` stays free for the native verified import."""
    if PARSERS_ALIAS in sys.modules:
        return sys.modules[PARSERS_ALIAS]
    pins = smoke.load_pins(pins_path)
    verified = smoke.verify_source_tree(root, pins)
    module = types.ModuleType(PARSERS_ALIAS)
    module.__file__ = os.path.join(root, "parsers.py")
    sys.modules[PARSERS_ALIAS] = module
    exec(compile(verified["parsers.py"], module.__file__, "exec", dont_inherit=True),
         module.__dict__)
    return module


def _ports(ops, backend, controller, custody, source, parsers):
    return Ports(
        ops=ops, backend=backend,
        sampler_factory=lambda pid, b: control_plane.make_sampler(controller, pid, b),
        sample=control_plane.sample_once, sampler_report=control_plane.sampler_report,
        custody=custody,
        mounts=lambda: parsers.parse_mountinfo(source.read_self("mountinfo")))


def synthetic_ports(kernel=None, behaviour="normal", ops_fail=None,
                    custody_fail=None, confirm=True):
    from synthetic import FakeKernel, FakeOps, FakeProcSource, SyntheticCustody
    kernel = kernel or FakeKernel()
    ops = FakeOps(kernel, behaviour, ops_fail)
    source = FakeProcSource(kernel)
    parsers = load_verified_parsers()
    controller, _ = control_plane.load_controller()
    backend = control_plane.linux_backend(controller, source, parsers.parse_proc_stat,
                                          sleep=ops.sleep)
    custody = SyntheticCustody(ops, custody_fail, confirm)
    return _ports(ops, backend, controller, custody, source, parsers), kernel


def native_ports(cfg, pins_path, out, root=smoke.SOURCE_ROOT):
    """Verified p18 import + runtime + unchanged controller; no fork, no fd."""
    from p18_custody import P18Custody
    stages = {}
    pins = smoke.load_pins(pins_path)
    verified = smoke.verify_source_tree(root, pins)
    m = smoke.import_shell(root, verified)
    runtime, native, policy = smoke.setup_runtime(m, pins, root)
    parsers = sys.modules["parsers"]
    need(parsers.__spec__.loader is m["p01"].__spec__.loader
         and m["p01"].parse_proc_stat is parsers.parse_proc_stat,
         "PARSERS_NOT_FROM_VERIFIED_LOADER")
    controller, stages["controller_sha256"] = control_plane.load_controller()
    source = RealProcSource()
    backend = control_plane.linux_backend(controller, source, parsers.parse_proc_stat)
    custody = P18Custody(m, runtime, native, policy, pins, out, cfg.run_id, cfg.owner_id)
    stages["runtime"] = runtime.report()
    stages["native_provenance"] = native.provenance
    return _ports(RealOps(), backend, controller, custody, source, parsers), stages


def file_digests():
    """sha256 of the development files this layer runs (evidence only)."""
    rows = {}
    paths = [os.path.join(HERE, n) for n in sorted(os.listdir(HERE)) if n.endswith(".py")]
    paths += [os.path.join(lifecycle.DEV_BUILD001, "native_close_smoke.py"),
              control_plane.CONTROLLER_FILE]
    for path in paths:
        with open(path, "rb") as fh:
            rows[os.path.relpath(path, os.path.join(HERE, ".."))] = \
                hashlib.sha256(fh.read()).hexdigest()
    return rows
