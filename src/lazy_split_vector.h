#ifndef SPLITALIGNERR_LAZY_SPLIT_VECTOR_H
#define SPLITALIGNERR_LAZY_SPLIT_VECTOR_H

#ifndef R_NO_REMAP
#define R_NO_REMAP
#endif
#include <Rinternals.h>
#include <R_ext/Rdynload.h>

namespace splitaligner_lazy {

// Called by R_init_SplitAlignerR, including namespace loading during readRDS().
void init(DllInfo* dll);

// A character vector with unchanged public values and deferred display text.
// context contains, in this order: taxa (UTF-8 character), reference_bits,
// coverage_bits (raw row-major little-endian words), words, n_primitives,
// n_genes (integer scalars). Indices are zero-based; NA yields NA_STRING.
// The inputs become immutable backing storage owned by R, not native handles.
SEXP make(SEXP context, SEXP gene_index, SEXP primitive_index);

}  // namespace splitaligner_lazy

#endif
