#include "numeric_policy.h"

#include <chrono>
#include <iomanip>
#include <iostream>
#include <regex>
#include <string>

namespace {

using Clock = std::chrono::steady_clock;

double elapsed_seconds(const Clock::time_point& started) {
  return std::chrono::duration<double>(Clock::now() - started).count();
}

void marker(const std::string& value) {
  std::cout << "stage_marker: " << value << std::endl;
}

void timing(const std::string& name, double seconds) {
  std::cout << "timing_" << name << "_wall_seconds: "
            << std::fixed << std::setprecision(9) << seconds << std::endl;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: windows_numeric_microprobe MODE" << std::endl;
    return 64;
  }
  const std::string mode = argv[1];
  marker("SCRIPT_STARTED");
  std::cout << "probe_mode: " << mode << std::endl;
  marker("OPERATION_STARTED");

  if (mode == "numeric_policy") {
    marker("NUMERIC_FIRST_CALL_STARTED");
    const auto first_started = Clock::now();
    const auto first = splitaligner::validate_numeric_token("1");
    timing("numeric_first_call", elapsed_seconds(first_started));
    marker("NUMERIC_FIRST_CALL_FINISHED");

    marker("NUMERIC_SECOND_CALL_STARTED");
    const auto second_started = Clock::now();
    const auto second = splitaligner::validate_numeric_token("1");
    timing("numeric_second_call", elapsed_seconds(second_started));
    marker("NUMERIC_SECOND_CALL_FINISHED");

    if (!first.accepted || !second.accepted ||
        first.classification != "finite_numeric" ||
        second.classification != "finite_numeric") {
      std::cerr << "numeric policy rejected the token" << std::endl;
      std::cout << "case_status: FAILURE" << std::endl;
      return 2;
    }
  } else if (mode == "regex_construction") {
    marker("REGEX_CONSTRUCTION_STARTED");
    const auto regex_started = Clock::now();
    const std::regex decimal_pattern(
      R"(^[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?$)",
      std::regex::ECMAScript
    );
    timing("regex_construction", elapsed_seconds(regex_started));
    marker("REGEX_CONSTRUCTION_FINISHED");

    marker("REGEX_MATCH_STARTED");
    const auto match_started = Clock::now();
    const bool matched = std::regex_match(std::string("1"), decimal_pattern);
    timing("regex_match", elapsed_seconds(match_started));
    marker("REGEX_MATCH_FINISHED");
    if (!matched) {
      std::cerr << "standalone regex did not match token 1" << std::endl;
      std::cout << "case_status: FAILURE" << std::endl;
      return 2;
    }
  } else {
    std::cerr << "MODE must be numeric_policy or regex_construction" << std::endl;
    return 64;
  }

  marker("OPERATION_FINISHED");
  std::cout << "case_status: PASS" << std::endl;
  return 0;
}
