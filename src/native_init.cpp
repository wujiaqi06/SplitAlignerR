#include "lazy_split_vector.h"

// Keep ALTREP registration in the generated package initialization routine.
// Rcpp::compileAttributes() preserves this hook via the init attribute.
// [[Rcpp::init]]
void splitaligner_init(DllInfo* dll) {
  splitaligner_lazy::init(dll);
}
