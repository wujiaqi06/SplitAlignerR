#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cctype>
#include <clocale>
#include <regex>
#include <string>
#include <unordered_set>

#define R_NO_REMAP 1
#include <R.h>
#include <Rinternals.h>

#include "numeric_policy.h"

#if defined(_WIN32)
#define FIX007_EXPORT __declspec(dllexport)
#else
#define FIX007_EXPORT
#endif

namespace {

SEXP logical_result(bool value) {
  return Rf_ScalarLogical(value ? TRUE : FALSE);
}

std::string frozen_ascii_lower(std::string input) {
  for (char& ch : input) {
    ch = static_cast<char>(
      std::tolower(static_cast<unsigned char>(ch))
    );
  }
  return input;
}

bool frozen_marker_path(const std::string& input) {
  static const std::unordered_set<std::string> markers = {
    "na", "n/a", ".", "?", "null", "none",
    "nan", "+nan", "-nan",
    "inf", "+inf", "-inf",
    "infinity", "+infinity", "-infinity"
  };
  return markers.find(frozen_ascii_lower(input)) != markers.end();
}

const char* decimal_grammar() {
  return R"(^[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?$)";
}

}  // namespace

extern "C" FIX007_EXPORT SEXP sar_fix007_noop() {
  return logical_result(true);
}

extern "C" FIX007_EXPORT SEXP sar_fix007_locale() {
  const int categories[] = {LC_CTYPE, LC_COLLATE, LC_NUMERIC};
  const char* names[] = {"LC_CTYPE", "LC_COLLATE", "LC_NUMERIC"};
  SEXP result = PROTECT(Rf_allocVector(STRSXP, 3));
  SEXP result_names = PROTECT(Rf_allocVector(STRSXP, 3));
  for (R_xlen_t index = 0; index < 3; ++index) {
    const char* value = std::setlocale(categories[index], nullptr);
    SET_STRING_ELT(
      result,
      index,
      Rf_mkChar(value == nullptr ? "NOT_AVAILABLE" : value)
    );
    SET_STRING_ELT(result_names, index, Rf_mkChar(names[index]));
  }
  Rf_setAttrib(result, R_NamesSymbol, result_names);
  UNPROTECT(2);
  return result;
}

extern "C" FIX007_EXPORT SEXP sar_fix007_strtod() {
  const std::string token = "1";
  errno = 0;
  char* end = nullptr;
  const double value = std::strtod(token.c_str(), &end);
  const bool consumed = end != nullptr &&
    static_cast<std::size_t>(end - token.c_str()) == token.size();
  return logical_result(
    consumed && errno == 0 && std::isfinite(value) && value == 1.0
  );
}

extern "C" FIX007_EXPORT SEXP sar_fix007_ascii_marker() {
  return logical_result(
    frozen_marker_path("NA") && frozen_marker_path("InFiNiTy") &&
    !frozen_marker_path("1")
  );
}

extern "C" FIX007_EXPORT SEXP sar_fix007_regex_automatic() {
  try {
    const std::regex pattern(decimal_grammar(), std::regex::ECMAScript);
    return logical_result(std::regex_match(std::string("1"), pattern));
  } catch (...) {
    return logical_result(false);
  }
}

extern "C" FIX007_EXPORT SEXP sar_fix007_regex_static() {
  try {
    static const std::regex pattern(
      decimal_grammar(), std::regex::ECMAScript
    );
    return logical_result(std::regex_match(std::string("1"), pattern));
  } catch (...) {
    return logical_result(false);
  }
}

extern "C" FIX007_EXPORT SEXP sar_fix007_frozen_numeric() {
  const splitaligner::NumericResult result =
    splitaligner::validate_numeric_token("1");
  return logical_result(
    result.accepted && result.classification == "finite_numeric" &&
    result.value == 1.0 && !result.is_zero && !result.is_negative
  );
}
