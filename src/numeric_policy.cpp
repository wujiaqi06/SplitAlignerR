#include "numeric_policy.h"

#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cctype>
#include <regex>
#include <unordered_set>

namespace splitaligner {
namespace {

std::string ascii_lower(std::string input) {
  for (char& ch : input) {
    ch = static_cast<char>(
      std::tolower(static_cast<unsigned char>(ch))
    );
  }
  return input;
}

bool is_software_failure_marker(const std::string& token) {
  static const std::unordered_set<std::string> markers = {
    "na", "n/a", ".", "?", "null", "none",
    "nan", "+nan", "-nan",
    "inf", "+inf", "-inf",
    "infinity", "+infinity", "-infinity"
  };
  return markers.find(ascii_lower(token)) != markers.end();
}

bool has_decimal_numeric_grammar(const std::string& token) {
  static const std::regex decimal_pattern(
    R"(^[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?$)",
    std::regex::ECMAScript
  );
  return std::regex_match(token, decimal_pattern);
}

}  // namespace

std::string trim_ascii_whitespace(const std::string& input) {
  std::size_t first = 0;
  while (first < input.size() &&
         std::isspace(static_cast<unsigned char>(input[first])) != 0) {
    ++first;
  }

  std::size_t last = input.size();
  while (last > first &&
         std::isspace(static_cast<unsigned char>(input[last - 1])) != 0) {
    --last;
  }
  return input.substr(first, last - first);
}

NumericResult validate_numeric_token(const std::string& input) {
  NumericResult result;
  const std::string token = trim_ascii_whitespace(input);

  if (token.empty()) {
    result.classification = "missing";
    result.diagnostic = "empty token; numeric evidence unavailable";
    return result;
  }
  if (is_software_failure_marker(token)) {
    result.classification = "software_failure_marker";
    result.diagnostic =
      "recognized unavailable marker; never converted to zero";
    return result;
  }
  if (!has_decimal_numeric_grammar(token)) {
    result.classification = "invalid_numeric";
    result.diagnostic =
      "token does not match the complete decimal numeric grammar";
    return result;
  }

  errno = 0;
  char* end = nullptr;
  const double parsed = std::strtod(token.c_str(), &end);
  const bool consumed_all = end != nullptr &&
    static_cast<std::size_t>(end - token.c_str()) == token.size();

  if (!consumed_all) {
    result.classification = "invalid_numeric";
    result.diagnostic = "numeric parser did not consume the complete token";
    return result;
  }
  if (!std::isfinite(parsed)) {
    result.classification = "out_of_range";
    result.diagnostic = "numeric value is not finite in double precision";
    return result;
  }
  if (errno == ERANGE && parsed == 0.0) {
    result.classification = "out_of_range";
    result.diagnostic = "numeric value underflows to zero in double precision";
    return result;
  }

  result.classification = "finite_numeric";
  result.accepted = true;
  result.value = parsed;
  result.is_zero = parsed == 0.0;
  result.is_negative = parsed < 0.0;
  result.diagnostic = "accepted finite double";
  if (result.is_negative) {
    result.diagnostic +=
      "; negative value is outside the nonnegative theorem scope";
  }
  if (std::fpclassify(parsed) == FP_SUBNORMAL) {
    result.diagnostic += "; representable subnormal value retained";
  }
  return result;
}

}  // namespace splitaligner
