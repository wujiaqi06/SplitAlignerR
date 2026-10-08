#ifndef SPLITALIGNERR_NUMERIC_POLICY_H
#define SPLITALIGNERR_NUMERIC_POLICY_H

#include <string>

namespace splitaligner {

struct NumericResult {
  std::string classification;
  bool accepted = false;
  double value = 0.0;
  bool is_zero = false;
  bool is_negative = false;
  std::string diagnostic;
};

std::string trim_ascii_whitespace(const std::string& input);
NumericResult validate_numeric_token(const std::string& input);

}  // namespace splitaligner

#endif
