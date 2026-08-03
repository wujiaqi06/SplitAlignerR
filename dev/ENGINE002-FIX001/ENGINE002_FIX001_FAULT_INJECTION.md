# ENGINE002-FIX001 fault injection

## Deterministic seams

The internal writer exposes one disabled-by-default I/O fault selector:

| stage | injected condition |
|---:|---|
| 1 | short record write |
| 2 | partial index write |
| 3 | partial header write |
| 4 | partial footer write |
| 5 | flush failure |
| 6 | close failure |
| 7 | short header placeholder write |
| 8 | ENOSPC |
| 9 | simulated cancellation |

The pre-existing atomic-publication selector now covers stages 1 through 15,
including index/header/footer completion, sync, both complete validations,
candidate/validated manifest creation, component publication, manifest
publication, directory sync, and temporary cleanup.

For every injected case the tests require a typed error, no accepted manifest,
no accepted current-run component, no unrecognized temporary residue, and no
replacement of a prior completed store. The selector is reset after every
case.

## Real interruption

tools/engine002/fix001_interrupt_probe.R creates an authority-sized streaming
construction. A real SIGINT/Ctrl-C reaches the periodic R interrupt check and
is translated to [ENGINE_INTERRUPTED]. The observed filesystem result is no
manifest, no component, and zero recognized temporary files. This is separate
from the deterministic cancellation seam.

## Scope

These seams are internal and introduce no public export. They do not simulate
process kill after the operating system has terminated the process; recovery
from such a kill is based on manifest-last acceptance and identifiable
temporary naming, not destructor execution.
