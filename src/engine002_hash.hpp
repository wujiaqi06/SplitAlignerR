#ifndef SPLITALIGNERR_ENGINE002_HASH_HPP
#define SPLITALIGNERR_ENGINE002_HASH_HPP

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace splitaligner {
namespace engine002 {

using Sha256 = std::array<std::uint8_t, 32>;

std::uint64_t xxh64(const std::uint8_t* data, std::size_t size,
                    std::uint64_t seed = 0) noexcept;
inline std::uint64_t xxh64(const std::vector<std::uint8_t>& data,
                           std::uint64_t seed = 0) noexcept {
  return xxh64(data.data(), data.size(), seed);
}

Sha256 sha256(const std::uint8_t* data, std::size_t size);
inline Sha256 sha256(const std::vector<std::uint8_t>& data) {
  return sha256(data.data(), data.size());
}

std::string hex_lower(const std::uint8_t* data, std::size_t size);
inline std::string hex_lower(const Sha256& digest) {
  return hex_lower(digest.data(), digest.size());
}

bool constant_time_equal(const Sha256& left, const Sha256& right) noexcept;

}  // namespace engine002
}  // namespace splitaligner

#endif

