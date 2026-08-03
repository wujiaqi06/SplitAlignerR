#ifndef SPLITALIGNERR_ENGINE002_ENDIAN_HPP
#define SPLITALIGNERR_ENGINE002_ENDIAN_HPP

#include "engine002_checked_math.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace splitaligner {
namespace engine002 {

inline std::uint16_t load_u16_le(const std::uint8_t* p) noexcept {
  return static_cast<std::uint16_t>(p[0]) |
         static_cast<std::uint16_t>(static_cast<std::uint16_t>(p[1]) << 8U);
}

inline std::uint32_t load_u32_le(const std::uint8_t* p) noexcept {
  return static_cast<std::uint32_t>(p[0]) |
         (static_cast<std::uint32_t>(p[1]) << 8U) |
         (static_cast<std::uint32_t>(p[2]) << 16U) |
         (static_cast<std::uint32_t>(p[3]) << 24U);
}

inline std::uint64_t load_u64_le(const std::uint8_t* p) noexcept {
  std::uint64_t value = 0;
  for (unsigned i = 0; i < 8; ++i) {
    value |= static_cast<std::uint64_t>(p[i]) << (8U * i);
  }
  return value;
}

inline void store_u16_le(std::uint8_t* p, std::uint16_t value) noexcept {
  p[0] = static_cast<std::uint8_t>(value & 0xffU);
  p[1] = static_cast<std::uint8_t>((value >> 8U) & 0xffU);
}

inline void store_u32_le(std::uint8_t* p, std::uint32_t value) noexcept {
  for (unsigned i = 0; i < 4; ++i) {
    p[i] = static_cast<std::uint8_t>((value >> (8U * i)) & 0xffU);
  }
}

inline void store_u64_le(std::uint8_t* p, std::uint64_t value) noexcept {
  for (unsigned i = 0; i < 8; ++i) {
    p[i] = static_cast<std::uint8_t>((value >> (8U * i)) & 0xffU);
  }
}

inline void append_u16_le(std::vector<std::uint8_t>& out,
                          std::uint16_t value) {
  const std::size_t old = out.size();
  out.resize(checked_add<std::size_t>(old, 2, "append u16"));
  store_u16_le(out.data() + old, value);
}

inline void append_u32_le(std::vector<std::uint8_t>& out,
                          std::uint32_t value) {
  const std::size_t old = out.size();
  out.resize(checked_add<std::size_t>(old, 4, "append u32"));
  store_u32_le(out.data() + old, value);
}

inline void append_u64_le(std::vector<std::uint8_t>& out,
                          std::uint64_t value) {
  const std::size_t old = out.size();
  out.resize(checked_add<std::size_t>(old, 8, "append u64"));
  store_u64_le(out.data() + old, value);
}

inline void append_bytes(std::vector<std::uint8_t>& out,
                         const std::uint8_t* bytes,
                         std::size_t count) {
  const std::size_t old = out.size();
  out.resize(checked_add<std::size_t>(old, count, "append bytes"));
  if (count != 0) {
    std::copy(bytes, bytes + count, out.data() + old);
  }
}

template <std::size_t N>
inline void append_array(std::vector<std::uint8_t>& out,
                         const std::array<std::uint8_t, N>& value) {
  append_bytes(out, value.data(), N);
}

}  // namespace engine002
}  // namespace splitaligner

#endif
