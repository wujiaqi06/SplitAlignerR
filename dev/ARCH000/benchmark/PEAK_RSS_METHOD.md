# Peak RSS method

Each reported benchmark case is executed in a fresh process under macOS BSD
`/usr/bin/time -l`:

```text
/usr/bin/time -l -o CASE.time.txt Rscript ... case ...
```

`maximum resident set size` is parsed as bytes and joined to the case's RDS
metric row only after the process exits. This is an OS high-water mark for the
complete process, including package loading, pass 1, allocation, pass 2, and
the retained compact result. It is not `object.size()` and is not an
instantaneous `ps` sample.

Stage-local RSS samples from `ps` are supplementary diagnostics only. The CSV
column `peak_rss_bytes` comes exclusively from BSD time. Projected 500,000-locus
rows deliberately report peak RSS as `NOT_MEASURED`.

The full fixed+free conformance command is also measured as one process, but
that peak includes both returned compact objects and paired comparison work;
single-dataset benchmark rows are the proper values for mode comparison.
