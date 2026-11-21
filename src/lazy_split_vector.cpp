#include "lazy_split_vector.h"

#include <R_ext/Altrep.h>
#include <R_ext/Print.h>
#include <R_ext/Utils.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace splitaligner_lazy {
namespace {

R_altrep_class_t split_class;
bool initialized = false;

enum ContextIndex {
  TAXA = 0, REFERENCE_BITS = 1, COVERAGE_BITS = 2, WORDS = 3,
  N_PRIMITIVES = 4, N_GENES = 5
};
enum PayloadIndex {
  CONTEXT = 0, GENE_INDEX = 1, PRIMITIVE_INDEX = 2, NATIVE_UTF8_DISPLAY = 3
};

// Use the public R API rather than unexported locale globals. Query once per
// vector (and again when restoring one), never once per displayed cell.
bool native_locale_is_utf8() {
  SEXP call = PROTECT(Rf_lang1(Rf_install("l10n_info")));
  SEXP info = PROTECT(Rf_eval(call, R_BaseEnv));
  SEXP names = Rf_getAttrib(info, R_NamesSymbol);
  bool utf8 = false;
  if (TYPEOF(info) == VECSXP && TYPEOF(names) == STRSXP) {
    for (R_xlen_t i = 0; i < XLENGTH(info); ++i) {
      if (std::strcmp(CHAR(STRING_ELT(names, i)), "UTF-8") != 0) continue;
      SEXP value = VECTOR_ELT(info, i);
      utf8 = TYPEOF(value) == LGLSXP && XLENGTH(value) == 1 && LOGICAL(value)[0] == TRUE;
      break;
    }
  }
  UNPROTECT(2);
  return utf8;
}

int scalar_count(SEXP x, const char* label) {
  if (TYPEOF(x) != INTSXP || XLENGTH(x) != 1 ||
      INTEGER(x)[0] == NA_INTEGER || INTEGER(x)[0] < 1)
    Rf_error("Invalid compact split %s.", label);
  return INTEGER(x)[0];
}

void validate_context(SEXP context) {
  if (TYPEOF(context) != VECSXP || XLENGTH(context) != 6)
    Rf_error("Invalid compact split context.");
  SEXP taxa = VECTOR_ELT(context, TAXA);
  if (TYPEOF(taxa) != STRSXP || XLENGTH(taxa) < 2 ||
      XLENGTH(taxa) > std::numeric_limits<int>::max())
    Rf_error("Invalid compact split taxon dictionary.");
  for (R_xlen_t i = 0; i < XLENGTH(taxa); ++i)
    if (STRING_ELT(taxa, i) == NA_STRING || LENGTH(STRING_ELT(taxa, i)) == 0)
      Rf_error("Invalid compact split taxon label.");
  const int words = scalar_count(VECTOR_ELT(context, WORDS), "word count");
  const int branches = scalar_count(VECTOR_ELT(context, N_PRIMITIVES), "branch count");
  const int genes = scalar_count(VECTOR_ELT(context, N_GENES), "gene count");
  if (words != (XLENGTH(taxa) + 63) / 64)
    Rf_error("Compact split word count disagrees with taxon dictionary.");
  const R_xlen_t stride = static_cast<R_xlen_t>(words) * 8;
  if (stride > R_XLEN_T_MAX / branches || stride > R_XLEN_T_MAX / genes)
    Rf_error("Compact split backing dimensions exceed R vector limits.");
  if (TYPEOF(VECTOR_ELT(context, REFERENCE_BITS)) != RAWSXP ||
      XLENGTH(VECTOR_ELT(context, REFERENCE_BITS)) != stride * branches ||
      TYPEOF(VECTOR_ELT(context, COVERAGE_BITS)) != RAWSXP ||
      XLENGTH(VECTOR_ELT(context, COVERAGE_BITS)) != stride * genes)
    Rf_error("Compact split backing dimensions are inconsistent.");
}

void validate_indices(SEXP context, SEXP genes, SEXP primitives) {
  if (TYPEOF(genes) != INTSXP || TYPEOF(primitives) != INTSXP ||
      XLENGTH(genes) != XLENGTH(primitives))
    Rf_error("Invalid compact split row indices.");
  const int ng = INTEGER(VECTOR_ELT(context, N_GENES))[0];
  const int np = INTEGER(VECTOR_ELT(context, N_PRIMITIVES))[0];
  for (R_xlen_t i = 0; i < XLENGTH(genes); ++i) {
    const int g = INTEGER(genes)[i], p = INTEGER(primitives)[i];
    if ((g != NA_INTEGER && (g < 0 || g >= ng)) ||
        (p != NA_INTEGER && (p < 0 || p >= np)))
      Rf_error("Compact split row index is out of range.");
  }
}

SEXP payload(SEXP x) { return R_altrep_data1(x); }
SEXP context(SEXP x) { return VECTOR_ELT(payload(x), CONTEXT); }
SEXP genes(SEXP x) { return VECTOR_ELT(payload(x), GENE_INDEX); }
SEXP primitives(SEXP x) { return VECTOR_ELT(payload(x), PRIMITIVE_INDEX); }
R_xlen_t length(SEXP x) { return XLENGTH(genes(x)); }

// Display formatting intentionally agrees with tree_core.cpp's historical
// canonical_split(). These are labels for the audit column, not mapping keys.
bool legacy_safe_label(const std::string& s) {
  return !s.empty() && s.front() != '.' && s.back() != '.' &&
    s.find('|') == std::string::npos && s.find("..") == std::string::npos &&
    s.find(':') == std::string::npos;
}

std::string join(const std::vector<std::string>& values, const char* separator) {
  std::string result;
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i) result += separator;
    result += values[i];
  }
  return result;
}

std::string hex_encode(const std::string& label) {
  static const char digits[] = "0123456789abcdef";
  std::string encoded;
  encoded.reserve(label.size() * 2);
  for (unsigned char c : label) {
    encoded += digits[c >> 4];
    encoded += digits[c & 15];
  }
  return encoded;
}

std::string set_key(const std::vector<std::string>& labels) {
  std::vector<std::string> encoded;
  encoded.reserve(labels.size());
  for (const auto& label : labels) encoded.push_back(hex_encode(label));
  std::sort(encoded.begin(), encoded.end());
  return "HS1:" + join(encoded, ",");
}

std::string display(std::vector<std::string>& left,
                    std::vector<std::string>& right) {
  std::sort(left.begin(), left.end());
  std::sort(right.begin(), right.end());
  bool safe = true;
  for (const auto& label : left) safe = safe && legacy_safe_label(label);
  for (const auto& label : right) safe = safe && legacy_safe_label(label);
  const std::string a = safe ? join(left, "..") : set_key(left);
  const std::string b = safe ? join(right, "..") : set_key(right);
  return (safe ? "" : "HX1:") + (a <= b ? a + "||" + b : b + "||" + a);
}

bool projection_missing(SEXP x, R_xlen_t i) {
  const int gene = INTEGER(genes(x))[i];
  const int branch = INTEGER(primitives(x))[i];
  if (gene == NA_INTEGER || branch == NA_INTEGER) return true;
  SEXP ctx = context(x);
  const R_xlen_t stride = static_cast<R_xlen_t>(INTEGER(VECTOR_ELT(ctx, WORDS))[0]) * 8;
  const Rbyte* ref = RAW(VECTOR_ELT(ctx, REFERENCE_BITS)) + branch * stride;
  const Rbyte* mask = RAW(VECTOR_ELT(ctx, COVERAGE_BITS)) + gene * stride;
  const R_xlen_t taxa = XLENGTH(VECTOR_ELT(ctx, TAXA));
  const R_xlen_t bytes = (taxa + 7) / 8;
  bool left = false, right = false;
  for (R_xlen_t j = 0; j < bytes; ++j) {
    Rbyte retained = mask[j];
    // Padding is not a taxon. Keep No_NA consistent with Elt even if an
    // externally supplied serialized payload has nonzero unused bits.
    if (j == bytes - 1 && taxa % 8)
      retained &= static_cast<Rbyte>((1U << (taxa % 8)) - 1U);
    left = left || (ref[j] & retained);
    right = right || (static_cast<Rbyte>(~ref[j]) & retained);
  }
  return !left || !right;
}

SEXP compute_elt(SEXP x, R_xlen_t i) {
  if (i < 0 || i >= length(x)) Rf_error("Compact split index is out of range.");
  const int gene = INTEGER(genes(x))[i];
  const int branch = INTEGER(primitives(x))[i];
  if (gene == NA_INTEGER || branch == NA_INTEGER) return NA_STRING;
  SEXP ctx = context(x), taxa = VECTOR_ELT(ctx, TAXA);
  const R_xlen_t stride = static_cast<R_xlen_t>(INTEGER(VECTOR_ELT(ctx, WORDS))[0]) * 8;
  const Rbyte* ref = RAW(VECTOR_ELT(ctx, REFERENCE_BITS)) + branch * stride;
  const Rbyte* mask = RAW(VECTOR_ELT(ctx, COVERAGE_BITS)) + gene * stride;
  std::vector<std::string> left, right;
  for (R_xlen_t t = 0; t < XLENGTH(taxa); ++t) {
    const Rbyte bit = static_cast<Rbyte>(1U << (t % 8));
    if (!(mask[t / 8] & bit)) continue;
    // Context labels originate in the parser's UTF-8 dictionary. Encoding is
    // preserved on serialization, so no locale-dependent conversion is used.
    (ref[t / 8] & bit ? left : right).emplace_back(CHAR(STRING_ELT(taxa, t)));
  }
  if (left.empty() || right.empty()) return NA_STRING;
  const std::string value = display(left, right);
  if (value.size() > static_cast<std::size_t>(std::numeric_limits<int>::max()))
    throw std::length_error("Expanded split text exceeds R's string-size limit.");
  // Preserve the historical Rcpp native marker on UTF-8 hosts. Elsewhere the
  // bytes must be marked UTF-8: treating them as native would silently change
  // the meaning of a compact RDS when it moves to a non-UTF-8 locale.
  const cetype_t encoding = LOGICAL(VECTOR_ELT(payload(x), NATIVE_UTF8_DISPLAY))[0]
    ? CE_NATIVE : CE_UTF8;
  return Rf_mkCharLenCE(value.data(), static_cast<int>(value.size()), encoding);
}

SEXP elt(SEXP x, R_xlen_t i) {
  SEXP cache = R_altrep_data2(x);
  if (cache != R_NilValue) return STRING_ELT(cache, i);
  try { return compute_elt(x, i); }
  catch (const std::exception& e) { Rf_error("Cannot display compact split: %s", e.what()); }
  return R_NilValue;
}

SEXP materialize(SEXP x) {
  SEXP cached = R_altrep_data2(x);
  if (cached != R_NilValue) return cached;
  SEXP out = PROTECT(Rf_allocVector(STRSXP, length(x)));
  for (R_xlen_t i = 0; i < length(x); ++i) {
    if (i % 16384 == 0) R_CheckUserInterrupt();
    SET_STRING_ELT(out, i, elt(x, i));
  }
  R_set_altrep_data2(x, out);
  UNPROTECT(1);
  return out;
}

void* dataptr(SEXP x, Rboolean) { return DATAPTR(materialize(x)); }
const void* dataptr_or_null(SEXP x) {
  SEXP cached = R_altrep_data2(x);
  return cached == R_NilValue ? nullptr : DATAPTR_RO(cached);
}

void set_elt(SEXP x, R_xlen_t i, SEXP value) {
  SET_STRING_ELT(materialize(x), i, value);
}

SEXP duplicate(SEXP x, Rboolean) {
  SEXP cached = R_altrep_data2(x);
  SEXP copy = PROTECT(cached == R_NilValue ? R_NilValue : Rf_shallow_duplicate(cached));
  SEXP out = R_new_altrep(split_class, payload(x), copy);
  UNPROTECT(1);
  return out;  // R's default DuplicateEX copies user attributes separately.
}

SEXP subset(SEXP x, SEXP index, SEXP) {
  if (TYPEOF(index) != INTSXP && TYPEOF(index) != REALSXP) return R_NilValue;
  const R_xlen_t n = XLENGTH(index), old_n = length(x);
  SEXP old_cache = R_altrep_data2(x);
  SEXP g = PROTECT(Rf_allocVector(INTSXP, n));
  SEXP b = PROTECT(Rf_allocVector(INTSXP, n));
  SEXP cached = PROTECT(old_cache == R_NilValue ? R_NilValue : Rf_allocVector(STRSXP, n));
  for (R_xlen_t i = 0; i < n; ++i) {
    const double position = TYPEOF(index) == INTSXP ? INTEGER(index)[i] : std::trunc(REAL(index)[i]);
    if (!R_FINITE(position) || position < 1 || position > old_n) {
      INTEGER(g)[i] = INTEGER(b)[i] = NA_INTEGER;
      if (cached != R_NilValue) SET_STRING_ELT(cached, i, NA_STRING);
    } else {
      const R_xlen_t old_i = static_cast<R_xlen_t>(position - 1);
      INTEGER(g)[i] = INTEGER(genes(x))[old_i];
      INTEGER(b)[i] = INTEGER(primitives(x))[old_i];
      if (cached != R_NilValue) SET_STRING_ELT(cached, i, STRING_ELT(old_cache, old_i));
    }
  }
  SEXP data = PROTECT(Rf_allocVector(VECSXP, 4));
  SET_VECTOR_ELT(data, CONTEXT, context(x));
  SET_VECTOR_ELT(data, GENE_INDEX, g);
  SET_VECTOR_ELT(data, PRIMITIVE_INDEX, b);
  SET_VECTOR_ELT(data, NATIVE_UTF8_DISPLAY, VECTOR_ELT(payload(x), NATIVE_UTF8_DISPLAY));
  SEXP out = R_new_altrep(split_class, data, cached);
  UNPROTECT(4);
  return out;
}

int no_na(SEXP x) {
  SEXP cached = R_altrep_data2(x);
  if (cached != R_NilValue) {
    for (R_xlen_t i = 0; i < length(x); ++i)
      if (STRING_ELT(cached, i) == NA_STRING) return 0;
  } else {
    for (R_xlen_t i = 0; i < length(x); ++i)
      if (projection_missing(x, i)) return 0;
  }
  return 1;
}

Rboolean inspect(SEXP x, int, int, int, void (*)(SEXP, int, int, int)) {
  Rprintf("splitaligner_lazy_split_v1 (length=%lld, materialized=%s)\n",
          static_cast<long long>(length(x)),
          R_altrep_data2(x) == R_NilValue ? "no" : "yes");
  return TRUE;
}

SEXP serialized_state(SEXP x) {
  SEXP out = PROTECT(Rf_allocVector(VECSXP, 3));
  SET_VECTOR_ELT(out, 0, Rf_ScalarInteger(2));
  SET_VECTOR_ELT(out, 1, payload(x));
  SET_VECTOR_ELT(out, 2, R_altrep_data2(x));
  UNPROTECT(1);
  return out;
}

SEXP unserialize(SEXP, SEXP state) {
  if (TYPEOF(state) != VECSXP || XLENGTH(state) != 3 ||
      TYPEOF(VECTOR_ELT(state, 0)) != INTSXP || XLENGTH(VECTOR_ELT(state, 0)) != 1 ||
      (INTEGER(VECTOR_ELT(state, 0))[0] != 1 && INTEGER(VECTOR_ELT(state, 0))[0] != 2))
    Rf_error("Unsupported compact split serialization schema.");
  const int schema = INTEGER(VECTOR_ELT(state, 0))[0];
  SEXP previous = VECTOR_ELT(state, 1), cached = VECTOR_ELT(state, 2);
  if (TYPEOF(previous) != VECSXP || XLENGTH(previous) != (schema == 1 ? 3 : 4))
    Rf_error("Invalid compact split serialized payload.");
  bool was_native_utf8 = true;  // Schema 1 had no explicit encoding policy.
  if (schema == 2) {
    SEXP policy = VECTOR_ELT(previous, NATIVE_UTF8_DISPLAY);
    if (TYPEOF(policy) != LGLSXP || XLENGTH(policy) != 1 ||
        (LOGICAL(policy)[0] != FALSE && LOGICAL(policy)[0] != TRUE))
      Rf_error("Invalid compact split serialized encoding policy.");
    was_native_utf8 = LOGICAL(policy)[0] == TRUE;
  }
  validate_context(VECTOR_ELT(previous, CONTEXT));
  validate_indices(VECTOR_ELT(previous, CONTEXT), VECTOR_ELT(previous, GENE_INDEX),
                   VECTOR_ELT(previous, PRIMITIVE_INDEX));
  if (cached != R_NilValue && (TYPEOF(cached) != STRSXP ||
      XLENGTH(cached) != XLENGTH(VECTOR_ELT(previous, GENE_INDEX))))
    Rf_error("Invalid compact split materialized payload.");
  SEXP data = PROTECT(Rf_allocVector(VECSXP, 4));
  for (int i = 0; i < 3; ++i) SET_VECTOR_ELT(data, i, VECTOR_ELT(previous, i));
  // Explicit UTF-8 remains explicit after moving back to a UTF-8 host, just
  // as it does for an ordinary serialized character vector. Otherwise the
  // encoding marker would depend on whether data2 happened to materialize.
  SET_VECTOR_ELT(data, NATIVE_UTF8_DISPLAY,
                 Rf_ScalarLogical(was_native_utf8 && native_locale_is_utf8()));
  SEXP out = R_new_altrep(split_class, data, cached);
  UNPROTECT(1);
  return out;
}

}  // namespace

void init(DllInfo* dll) {
  split_class = R_make_altstring_class("compact_projected_split_v1", "SplitAlignerR", dll);
  R_set_altrep_Length_method(split_class, length);
  R_set_altrep_Duplicate_method(split_class, duplicate);
  R_set_altrep_Inspect_method(split_class, inspect);
  R_set_altrep_Serialized_state_method(split_class, serialized_state);
  R_set_altrep_Unserialize_method(split_class, unserialize);
  R_set_altvec_Dataptr_method(split_class, dataptr);
  R_set_altvec_Dataptr_or_null_method(split_class, dataptr_or_null);
  R_set_altvec_Extract_subset_method(split_class, subset);
  R_set_altstring_Elt_method(split_class, elt);
  R_set_altstring_Set_elt_method(split_class, set_elt);
  R_set_altstring_No_NA_method(split_class, no_na);
  initialized = true;
}

SEXP make(SEXP ctx, SEXP gene_index, SEXP primitive_index) {
  if (!initialized) Rf_error("Compact split class has not been registered.");
  validate_context(ctx);
  validate_indices(ctx, gene_index, primitive_index);
  SEXP data = PROTECT(Rf_allocVector(VECSXP, 4));
  SET_VECTOR_ELT(data, CONTEXT, ctx);
  SET_VECTOR_ELT(data, GENE_INDEX, gene_index);
  SET_VECTOR_ELT(data, PRIMITIVE_INDEX, primitive_index);
  SET_VECTOR_ELT(data, NATIVE_UTF8_DISPLAY, Rf_ScalarLogical(native_locale_is_utf8()));
  SEXP out = R_new_altrep(split_class, data, R_NilValue);
  UNPROTECT(1);
  return out;
}

}  // namespace splitaligner_lazy
