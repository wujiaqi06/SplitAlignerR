#include "numeric_policy.h"

#include <cstdint>
#include <iostream>
#include <regex>
#include <string>
#include <vector>

namespace splitaligner {
namespace detail {
bool has_decimal_numeric_grammar(const std::string& token);
}
}

namespace {

class FixedGenerator {
 public:
  explicit FixedGenerator(std::uint64_t seed) : state_(seed) {}

  std::uint64_t next() {
    state_ ^= state_ << 13;
    state_ ^= state_ >> 7;
    state_ ^= state_ << 17;
    return state_;
  }

  std::size_t bounded(std::size_t bound) {
    return static_cast<std::size_t>(next() % bound);
  }

 private:
  std::uint64_t state_;
};

std::string digits(FixedGenerator& generator,
                   std::size_t minimum,
                   std::size_t maximum) {
  const std::size_t count = minimum +
    generator.bounded(maximum - minimum + 1);
  std::string result;
  result.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    result.push_back(static_cast<char>('0' + generator.bounded(10)));
  }
  return result;
}

std::string independently_generated_valid(FixedGenerator& generator) {
  std::string token;
  const std::size_t sign = generator.bounded(3);
  if (sign == 1) {
    token.push_back('+');
  } else if (sign == 2) {
    token.push_back('-');
  }

  if (generator.bounded(2) == 0) {
    token += digits(generator, 1, 18);
    if (generator.bounded(2) == 0) {
      token.push_back('.');
      token += digits(generator, 0, 18);
    }
  } else {
    token.push_back('.');
    token += digits(generator, 1, 18);
  }

  if (generator.bounded(2) == 0) {
    token.push_back(generator.bounded(2) == 0 ? 'e' : 'E');
    const std::size_t exponent_sign = generator.bounded(3);
    if (exponent_sign == 1) {
      token.push_back('+');
    } else if (exponent_sign == 2) {
      token.push_back('-');
    }
    token += digits(generator, 1, 6);
  }
  return token;
}

std::string independently_generated_arbitrary(FixedGenerator& generator) {
  static const std::string alphabet =
    "+-0123456789.eE,x_Xabcdef?/ ";
  const std::size_t count = generator.bounded(32);
  std::string token;
  token.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    token.push_back(alphabet[generator.bounded(alphabet.size())]);
  }
  return token;
}

bool old_regex_predicate(const std::string& token) {
  static const std::regex decimal_pattern(
    R"(^[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?$)",
    std::regex::ECMAScript
  );
  return std::regex_match(token, decimal_pattern);
}

std::string quoted(const std::string& token) {
  std::string result = "\"";
  for (char ch : token) {
    if (ch == '\\' || ch == '"') {
      result.push_back('\\');
    }
    result.push_back(ch);
  }
  result.push_back('"');
  return result;
}

}  // namespace

int main() {
  constexpr std::uint64_t seed = UINT64_C(0x6a09e667f3bcc909);
  constexpr std::size_t target_count = 100000;
  FixedGenerator generator(seed);

  std::vector<std::string> corpus = {
    "0", "-0", "+0", "1", "1.", ".5", "-.5", "1.5", "1e8",
    "1E+8", "-1.2e-8", "2.2250738585072014e-308",
    "4.9406564584124654e-324", "", "   ", "+", "-", ".", "e1",
    "1e", "1e+", "1..2", "1,5", "1_000", "0x10", "1 2", "1e2x",
    "NA", "N/A", "?", "NULL", "NONE", "NaN", "Inf", "Infinity",
    "na", "n/a", "null", "none", "nan", "inf", "infinity"
  };
  corpus.reserve(target_count);
  while (corpus.size() < target_count) {
    if (corpus.size() % 2 == 0) {
      corpus.push_back(independently_generated_valid(generator));
    } else {
      corpus.push_back(independently_generated_arbitrary(generator));
    }
  }

  std::size_t old_accept_count = 0;
  std::size_t manual_accept_count = 0;
  std::size_t mismatch_count = 0;
  for (const std::string& token : corpus) {
    const bool old_accepts = old_regex_predicate(token);
    const bool manual_accepts =
      splitaligner::detail::has_decimal_numeric_grammar(token);
    old_accept_count += old_accepts ? 1 : 0;
    manual_accept_count += manual_accepts ? 1 : 0;
    if (old_accepts != manual_accepts) {
      if (mismatch_count < 20) {
        std::cerr << "mismatch: token=" << quoted(token)
                  << " old_regex=" << old_accepts
                  << " manual=" << manual_accepts << std::endl;
      }
      ++mismatch_count;
    }
  }

  std::cout << "differential_id: numeric-grammar-old-regex-vs-manual-v1\n";
  std::cout << "generator_seed_hex: 6a09e667f3bcc909\n";
  std::cout << "expected_generation_independent_of_manual_parser: TRUE\n";
  std::cout << "token_count: " << corpus.size() << "\n";
  std::cout << "old_regex_accept_count: " << old_accept_count << "\n";
  std::cout << "manual_accept_count: " << manual_accept_count << "\n";
  std::cout << "mismatch_count: " << mismatch_count << "\n";
  std::cout << "differential_status: "
            << (mismatch_count == 0 ? "PASS" : "FAIL") << "\n";
  return mismatch_count == 0 ? 0 : 1;
}
