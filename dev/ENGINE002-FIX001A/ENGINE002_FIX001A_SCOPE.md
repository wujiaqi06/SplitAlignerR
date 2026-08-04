# ENGINE002-FIX001A Scope

Starting identity:

```text
branch: engine002-fix001a-cross-platform-evidence
base commit: 94b45820b811e95ce29c9a9c062cbf8e8bbfbbdf
base tree: 5c54821018de8f3a03d67e319c23eeceb46488d8
```

This narrow task closes cross-platform and R-boundary evidence gaps for the
accepted ENGINE002-FIX001 implementation. It does not add a public API, change
scientific or wire-format semantics, select a default engine, or begin
ENGINE003.

Production source is frozen unless hosted CI demonstrates a concrete
portability, lifecycle, warning, or correctness defect. Any such correction
must be minimal, isolated in a separate commit, and followed by a complete
three-platform replay.

The certified `v0.1.0` release remains immutable at peeled commit
`17a0927095c7a067817bf598a2556cbe7348a6d0`.
