# Pro FAIL adoption

Binding review:

```text
Review ID: SAR-PRO-ENGINE002-FIX001A-RECERT-20260804
Defect: SAR-PRO-E2-FIX001A-001
Severity: MAJOR - checkpoint/release blocking
Verdict: FAIL
```

The decision applies to the ENGINE002-FIX001A development checkpoint.  It does
not revoke or alter the independently certified `v0.1.0` release.

## Byte-identical source materials

| Pro material | Independently measured SHA-256 |
|---|---|
| decision markdown | `7a38b59b0c25f2b640d50c12aa3c1f33301d5ac53999d2c9d6f4f5363356051a` |
| decision sidecar file | `e555919cbed4e8730ccbf41f573b8fc9963d7cb306caf3e122d7ba5510b30181` |
| exact MRE source | `b23b6cdbb809836da5e1a5898c3bf61de30dde9ab19d89b26c7e47c3ad763482` |
| exact MRE output | `1430f3ad502458b8aae452540a9f8de134b67e2f8d40fa0375f24dcddfd5f051` |
| original aggregate checker | `aff5818edd501a1d9436be5389112712b573d1d19b9c3c00b43028eea86c10ad` |
| certificate ZIP | `4032abb15314f3a6d5436e2b57f1aea4d4e978640d9a0aa9a03a8e0a35e83cc8` |
| certificate sidecar file | `86dddd29c1fc3cdc40c9a5a4df71aea1b07f4b66f7a579b482fb67009a6dee2f` |
| reviewed FIX001A Pro ZIP | `679c9d75fd60c06fe535d27fbffc5ac330e944cc5341798dfb7fb5a45b03046b` |
| reviewed FIX001A handoff ZIP | `d3701ac46734d74e51b7fdf1c1c39e4288f85a333dc64ba703c8cb6fc6f7f74c` |
| reviewed FIX001A bundle | `d2bd6e07e34928014e1758a32ed3cfe1c43278c70015b5ad8715d948ef5f80ae` |

The external Pro RECERT package preserves these original files under a clearly
named `pro_original/` directory.  The original checker is historical evidence;
the maintained candidate checker is separate.

## Remediation map

| Pro-required remediation | Implementation | Test | CI evidence | Final RECERT evidence |
|---|---|---|---|---|
| preserve partial SHA blocks | `src/engine002_hash.cpp` | `test-engine002-fix001b.R`; partition driver | all platform jobs | implementation, SHA-contract, raw artifacts |
| stable invariants and edge cases | `src/engine002_hash.cpp` | null/zero, repeat digest, continuation, boundary partitions | all platform jobs + sanitizer | SHA-contract and sanitizer reports |
| exact Pro MRE | unchanged Pro source in `pro_original/` | compiled exact MRE | Linux/macOS/Windows | original and repaired result files |
| standard fixed vectors | `reference_vectors.txt` | independent `hashlib` driver | Linux/macOS/Windows + sanitizer subset | standard-vector results |
| exhaustive two-part differential | `partition_differential.py` | 34,191 cases | Linux/macOS/Windows | summary and all boundary splits |
| random multipart differential | same driver, seed `0x5a17b001` | 10,000 cases | Linux/macOS/Windows | random-partition results |
| independent payload aggregate | `payload_aggregate_check.py` | golden, authority, stress | Linux/macOS/Windows | independent aggregate results |
| reject old defective store | corrected production validator | frozen negative fixture | Linux/macOS/Windows | old-golden rejection results |
| aggregate-only and payload tamper | `store_tamper.py` | targeted validator gate | Linux/macOS/Windows | tamper/corruption results |
| regenerate affected bytes | corrected builder | deterministic fixture comparisons | all platform jobs + comparison | regeneration and golden bytes |
| full 1,974 authority | existing frozen authority path | exact decoded equality and invariants | Linux/macOS/Windows | authority results/artifacts |
| >2 GiB and >4 GiB stores | existing large generator | bounded independent checker, reopen, last lookup | designated host | large-offset results |
| R/Rcpp sanitizer boundary | existing package boundary | installed package sanitizer driver + standalone SHA probe | Linux sanitizer job | sanitizer logs/results |
| schema/science unchanged | no implementation change outside hash | metadata/scope audit | package checks and deterministic comparison | schema-semantics audit |

This file maps evidence; it does not issue the independent Pro verdict.
