#include <Rcpp.h>

#include "numeric_policy.h"

#include <string>

// [[Rcpp::export]]
Rcpp::List cpp_splitaligner_core_info() {
  return Rcpp::List::create(
    Rcpp::Named("core_version") = "0.1.0-dev.2",
    Rcpp::Named("schema_version") = "1.0.0-draft.2",
    Rcpp::Named("production_language") = "C++17",
    Rcpp::Named("numeric_policy") = "finite-double-v1",
    Rcpp::Named("oracle_language") = "pure R node-edge graph surgery",
    Rcpp::Named("oracle_calls_production_core") = false
  );
}

// [[Rcpp::export]]
Rcpp::DataFrame cpp_validate_branch_length_tokens(Rcpp::CharacterVector tokens) {
  const R_xlen_t n = tokens.size();
  Rcpp::CharacterVector classification(n);
  Rcpp::LogicalVector accepted(n);
  Rcpp::NumericVector value(n, NA_REAL);
  Rcpp::LogicalVector is_zero(n, NA_LOGICAL);
  Rcpp::LogicalVector is_negative(n, NA_LOGICAL);
  Rcpp::CharacterVector diagnostic(n);

  for (R_xlen_t i = 0; i < n; ++i) {
    if (tokens[i] == NA_STRING) {
      classification[i] = "missing";
      accepted[i] = false;
      diagnostic[i] = "R missing value; numeric evidence unavailable";
      continue;
    }

    const splitaligner::NumericResult parsed =
      splitaligner::validate_numeric_token(
        Rcpp::as<std::string>(tokens[i])
      );
    classification[i] = parsed.classification;
    accepted[i] = parsed.accepted;
    diagnostic[i] = parsed.diagnostic;
    if (parsed.accepted) {
      value[i] = parsed.value;
      is_zero[i] = parsed.is_zero;
      is_negative[i] = parsed.is_negative;
    }
  }

  return Rcpp::DataFrame::create(
    Rcpp::Named("token") = tokens,
    Rcpp::Named("classification") = classification,
    Rcpp::Named("accepted") = accepted,
    Rcpp::Named("value") = value,
    Rcpp::Named("is_zero") = is_zero,
    Rcpp::Named("is_negative") = is_negative,
    Rcpp::Named("diagnostic") = diagnostic,
    Rcpp::Named("stringsAsFactors") = false
  );
}
