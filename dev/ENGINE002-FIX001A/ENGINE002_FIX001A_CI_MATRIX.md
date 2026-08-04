# ENGINE002-FIX001A CI Matrix

Mandatory jobs:

| Key | Runner | R | Role |
|---|---|---|---|
| `linux-release` | `ubuntu-latest` | release | package, R boundary, bytes, authority |
| `macos-release` | `macos-latest` | release | package, R boundary, bytes, authority |
| `windows-release` | `windows-latest` | release | package, R boundary, bytes, authority, Windows offset/atomicity |

Advisory jobs:

| Key | Runner | R | Role |
|---|---|---|---|
| `linux-devel` | `ubuntu-latest` | devel | forward-compatibility signal |

The dedicated Linux sanitizer job builds the package shared library with
AddressSanitizer and UndefinedBehaviorSanitizer, preloads both runtimes, and
runs targeted ENGINE002 tests through the installed R/Rcpp boundary. Leak
detection is disabled because the host R executable is not sanitizer-built;
address and undefined-behavior failures remain fatal.

The final comparison job consumes the three mandatory release artifacts and
requires exact equality of plan bytes, store component and manifest bytes,
the concatenated 1,974 authority records, and the authority-scale store.
No byte normalization is performed.

All timings are labelled:

```text
HOSTED-RUNNER DIAGNOSTIC - NOT A CONTROLLED CROSS-PLATFORM PERFORMANCE COMPARISON
```
