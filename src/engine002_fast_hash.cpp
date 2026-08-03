#include "engine002_fast_hash.h"

#include <atomic>

namespace splitaligner {
namespace engine002 {
namespace {

std::atomic<bool> g_constant_fast_hash{false};

std::uint64_t domain_seed(FastHashDomain domain) noexcept {
  return UINT64_C(0x9e3779b185ebca87) ^
         (static_cast<std::uint64_t>(domain) * UINT64_C(0xc2b2ae3d27d4eb4f));
}

}  // namespace

void set_constant_fast_hash_for_tests(bool enabled) noexcept {
  g_constant_fast_hash.store(enabled);
}

bool constant_fast_hash_for_tests() noexcept {
  return g_constant_fast_hash.load();
}

std::uint64_t fast_hash_bytes(FastHashDomain domain,
                              const std::uint8_t* data,
                              std::size_t size,
                              bool force_constant) noexcept {
  if (force_constant) return 0;
  return xxh64(data, size, domain_seed(domain));
}

std::size_t ExactBytesHasher::operator()(
    const std::vector<std::uint8_t>& value) const noexcept {
  const std::uint64_t hash =
      fast_hash_bytes(domain_, value, force_constant_);
  if constexpr (sizeof(std::size_t) >= sizeof(std::uint64_t)) {
    return static_cast<std::size_t>(hash);
  }
  return static_cast<std::size_t>(hash ^ (hash >> 32U));
}

}  // namespace engine002
}  // namespace splitaligner
