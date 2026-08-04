# ENGINE002-FIX001B schema and semantics audit

| Contract surface | Result |
|---|---|
| `TruthPlanRecord` schema major/minor | unchanged `1.0` |
| `TruthPlanStore` schema major/minor | unchanged `1.0` |
| header bytes and offsets | unchanged |
| index bytes and offsets | unchanged |
| footer bytes and offsets | unchanged |
| domain strings | unchanged |
| length-prefix rules | unchanged |
| primitive state meanings | unchanged |
| retained-taxa pattern identity | unchanged |
| B* identity and member ordering | unchanged |
| truth/fiber semantics | unchanged |
| scientific mapper | unchanged |
| public API/exports | unchanged |
| package version and release metadata | unchanged |
| certified `v0.1.0` tag | unchanged |

The frozen v1 specification already requires standard SHA-256.  Therefore no
schema-version increment is warranted or authorized.  The old incremental
implementation was nonconforming; the correction brings the implementation
back to the existing wire contract.

The only intended durable-byte changes are the footer
`payload_aggregate_sha256` values produced by standard incremental SHA-256 and
the enclosing footer/component/manifest hashes derived from those bytes.
Decoded records and exact 1,974-authority scientific objects remain equal.
