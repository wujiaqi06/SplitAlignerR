#ifndef SPLITALIGNERR_ENGINE002_CHECKED_MATH_HPP
#define SPLITALIGNERR_ENGINE002_CHECKED_MATH_HPP

#include "engine002_errors.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <type_traits>

namespace splitaligner {
namespace engine002 {

template <typename T>
inline T checked_add(T a, T b, const char* context) {
  static_assert(std::is_unsigned<T>::value, "checked_add needs unsigned type");
  if (b > std::numeric_limits<T>::max() - a) {
    fail(ErrorCode::store_corrupt, std::string("overflow in ") + context);
  }
  return static_cast<T>(a + b);
}

template <typename T>
inline T checked_mul(T a, T b, const char* context) {
  static_assert(std::is_unsigned<T>::value, "checked_mul needs unsigned type");
  if (a != 0 && b > std::numeric_limits<T>::max() / a) {
    fail(ErrorCode::store_corrupt, std::string("overflow in ") + context);
  }
  return static_cast<T>(a * b);
}

inline std::size_t checked_size(std::uint64_t value, const char* context) {
  if (value > static_cast<std::uint64_t>(
                  std::numeric_limits<std::size_t>::max())) {
    fail(ErrorCode::memory_budget,
         std::string("host size limit exceeded in ") + context);
  }
  return static_cast<std::size_t>(value);
}

inline std::uint32_t checked_u32(std::uint64_t value, const char* context) {
  if (value > std::numeric_limits<std::uint32_t>::max()) {
    fail(ErrorCode::schema_mismatch,
         std::string("u32 limit exceeded in ") + context);
  }
  return static_cast<std::uint32_t>(value);
}

inline std::uint32_t ceil_div_u32(std::uint32_t value,
                                  std::uint32_t divisor) {
  if (divisor == 0) {
    fail(ErrorCode::internal_failure, "zero divisor");
  }
  return value / divisor + (value % divisor != 0 ? 1U : 0U);
}

}  // namespace engine002
}  // namespace splitaligner

#endif

