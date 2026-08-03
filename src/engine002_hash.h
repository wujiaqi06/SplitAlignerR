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

class Xxh64State {
 public:
  explicit Xxh64State(std::uint64_t seed = 0) noexcept;
  void update(const std::uint8_t* data, std::size_t size) noexcept;
  std::uint64_t digest() const noexcept;

 private:
  std::uint64_t seed_;
  std::uint64_t total_;
  std::uint64_t v1_;
  std::uint64_t v2_;
  std::uint64_t v3_;
  std::uint64_t v4_;
  std::array<std::uint8_t, 32> buffer_{};
  std::size_t buffered_;
};

class Sha256State {
 public:
  Sha256State() noexcept;
  void update(const std::uint8_t* data, std::size_t size);
  Sha256 digest() const;

 private:
  friend Sha256 sha256_guard_probe_for_test(std::uint64_t total,
                                             std::size_t buffered);
  std::array<std::uint32_t, 8> state_;
  std::array<std::uint8_t, 64> buffer_{};
  std::uint64_t total_;
  std::size_t buffered_;
};

std::uint64_t xxh64(const std::uint8_t* data, std::size_t size,
                    std::uint64_t seed = 0) noexcept;
inline std::uint64_t xxh64(const std::vector<std::uint8_t>& data,
                           std::uint64_t seed = 0) noexcept {
  return xxh64(data.data(), data.size(), seed);
}

Sha256 sha256(const std::uint8_t* data, std::size_t size);
Sha256 sha256_guard_probe_for_test(std::uint64_t total,
                                   std::size_t buffered);
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
