#ifndef SPLITALIGNERR_ENGINE002_FAST_HASH_H
#define SPLITALIGNERR_ENGINE002_FAST_HASH_H

#include "engine002_hash.h"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace splitaligner {
namespace engine002 {

enum class FastHashDomain : std::uint8_t {
  retained_pattern = 1,
  query_pool = 2,
  bstar_members = 3,
  record_index = 4,
  memory_lookup = 5,
  disk_lookup = 6,
  lru_key = 7
};

void set_constant_fast_hash_for_tests(bool enabled) noexcept;
bool constant_fast_hash_for_tests() noexcept;

std::uint64_t fast_hash_bytes(FastHashDomain domain,
                              const std::uint8_t* data,
                              std::size_t size,
                              bool force_constant) noexcept;

inline std::uint64_t fast_hash_bytes(FastHashDomain domain,
                                     const std::vector<std::uint8_t>& data,
                                     bool force_constant) noexcept {
  return fast_hash_bytes(domain, data.data(), data.size(), force_constant);
}

class ExactBytesHasher {
 public:
  explicit ExactBytesHasher(FastHashDomain domain) noexcept
      : domain_(domain), force_constant_(constant_fast_hash_for_tests()) {}

  std::size_t operator()(const std::vector<std::uint8_t>& value) const noexcept;

 private:
  FastHashDomain domain_;
  bool force_constant_;
};

}  // namespace engine002
}  // namespace splitaligner

#endif
