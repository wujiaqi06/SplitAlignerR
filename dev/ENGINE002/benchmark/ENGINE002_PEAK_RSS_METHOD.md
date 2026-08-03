# ENGINE002 peak RSS method

The benchmark is executed as a fresh external R process under macOS
`/usr/bin/time -l`. The reported `maximum resident set size` is the
process-level peak, not `object.size()` and not serialization size.

Command:

```text
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 /usr/bin/time -l \
  Rscript dev/ENGINE002/benchmark/run_engine002_benchmarks.R \
  <installed-library> dev/ENGINE002/benchmark 100000
```

Accepted final run:

```text
elapsed wall:              44.23 seconds
user:                      20.73 seconds
system:                    23.23 seconds
maximum resident set size: 417759232 bytes
peak memory footprint:     296208832 bytes
```

The first 100,000-record run exposed linear victim scanning and took 544.52
seconds. That run was rejected as final benchmark evidence. The final run uses
the semantics-equivalent intrusive LRU implemented after that diagnosis.
