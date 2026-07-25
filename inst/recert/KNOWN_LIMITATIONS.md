# V1 release-candidate known limitations

- SAR-ARCH-001 — DEFER TO FUTURE VERSION: the production C++ implementation is
  coupled to Rcpp. Shared-core extraction and a stable C ABI are outside V1.
- Python bindings are outside V1.
- Gene-tree inference, branch-length estimation, La Terra, GBI/Log-GBI,
  LASSO, PCA/SVD, downstream analysis, and GUI work are outside V1.
- Graph state, recovery, numeric evidence, and paired-finalization layers remain
  separate. residual_NA is only the summary name for finalized literal NA.
- A release-candidate tag is not independent RECERT and is not final release
  approval. Platform items not run must be reported as NOT RUN, FAILED, or
  BLOCKED BY ENVIRONMENT.
