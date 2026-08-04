#include "engine002_hash.h"

#include "engine002_endian.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>

namespace splitaligner {
namespace engine002 {
namespace {

constexpr std::uint64_t kPrime1 = UINT64_C(11400714785074694791);
constexpr std::uint64_t kPrime2 = UINT64_C(14029467366897019727);
constexpr std::uint64_t kPrime3 = UINT64_C(1609587929392839161);
constexpr std::uint64_t kPrime4 = UINT64_C(9650029242287828579);
constexpr std::uint64_t kPrime5 = UINT64_C(2870177450012600261);

inline std::uint64_t rotl64(std::uint64_t x, unsigned r) noexcept {
  return (x << r) | (x >> (64U - r));
}

inline std::uint64_t xxh_round(std::uint64_t acc, std::uint64_t input) noexcept {
  acc += input * kPrime2;
  acc = rotl64(acc, 31);
  acc *= kPrime1;
  return acc;
}

inline std::uint64_t xxh_merge(std::uint64_t acc, std::uint64_t value) noexcept {
  acc ^= xxh_round(0, value);
  return acc * kPrime1 + kPrime4;
}

inline std::uint32_t rotr32(std::uint32_t x, unsigned r) noexcept {
  return (x >> r) | (x << (32U - r));
}

constexpr std::array<std::uint32_t, 64> kShaK = {{
    UINT32_C(0x428a2f98), UINT32_C(0x71374491), UINT32_C(0xb5c0fbcf),
    UINT32_C(0xe9b5dba5), UINT32_C(0x3956c25b), UINT32_C(0x59f111f1),
    UINT32_C(0x923f82a4), UINT32_C(0xab1c5ed5), UINT32_C(0xd807aa98),
    UINT32_C(0x12835b01), UINT32_C(0x243185be), UINT32_C(0x550c7dc3),
    UINT32_C(0x72be5d74), UINT32_C(0x80deb1fe), UINT32_C(0x9bdc06a7),
    UINT32_C(0xc19bf174), UINT32_C(0xe49b69c1), UINT32_C(0xefbe4786),
    UINT32_C(0x0fc19dc6), UINT32_C(0x240ca1cc), UINT32_C(0x2de92c6f),
    UINT32_C(0x4a7484aa), UINT32_C(0x5cb0a9dc), UINT32_C(0x76f988da),
    UINT32_C(0x983e5152), UINT32_C(0xa831c66d), UINT32_C(0xb00327c8),
    UINT32_C(0xbf597fc7), UINT32_C(0xc6e00bf3), UINT32_C(0xd5a79147),
    UINT32_C(0x06ca6351), UINT32_C(0x14292967), UINT32_C(0x27b70a85),
    UINT32_C(0x2e1b2138), UINT32_C(0x4d2c6dfc), UINT32_C(0x53380d13),
    UINT32_C(0x650a7354), UINT32_C(0x766a0abb), UINT32_C(0x81c2c92e),
    UINT32_C(0x92722c85), UINT32_C(0xa2bfe8a1), UINT32_C(0xa81a664b),
    UINT32_C(0xc24b8b70), UINT32_C(0xc76c51a3), UINT32_C(0xd192e819),
    UINT32_C(0xd6990624), UINT32_C(0xf40e3585), UINT32_C(0x106aa070),
    UINT32_C(0x19a4c116), UINT32_C(0x1e376c08), UINT32_C(0x2748774c),
    UINT32_C(0x34b0bcb5), UINT32_C(0x391c0cb3), UINT32_C(0x4ed8aa4a),
    UINT32_C(0x5b9cca4f), UINT32_C(0x682e6ff3), UINT32_C(0x748f82ee),
    UINT32_C(0x78a5636f), UINT32_C(0x84c87814), UINT32_C(0x8cc70208),
    UINT32_C(0x90befffa), UINT32_C(0xa4506ceb), UINT32_C(0xbef9a3f7),
    UINT32_C(0xc67178f2)}};

inline std::uint32_t load_u32_be(const std::uint8_t* p) noexcept {
  return (static_cast<std::uint32_t>(p[0]) << 24U) |
         (static_cast<std::uint32_t>(p[1]) << 16U) |
         (static_cast<std::uint32_t>(p[2]) << 8U) |
         static_cast<std::uint32_t>(p[3]);
}

inline void store_u32_be(std::uint8_t* p, std::uint32_t value) noexcept {
  p[0] = static_cast<std::uint8_t>((value >> 24U) & 0xffU);
  p[1] = static_cast<std::uint8_t>((value >> 16U) & 0xffU);
  p[2] = static_cast<std::uint8_t>((value >> 8U) & 0xffU);
  p[3] = static_cast<std::uint8_t>(value & 0xffU);
}

void sha256_block(const std::uint8_t* block,
                  std::array<std::uint32_t, 8>& state) {
  std::array<std::uint32_t, 64> w{};
  for (std::size_t i = 0; i < 16; ++i) {
    w[i] = load_u32_be(block + 4 * i);
  }
  for (std::size_t i = 16; i < 64; ++i) {
    const std::uint32_t s0 = rotr32(w[i - 15], 7) ^
                             rotr32(w[i - 15], 18) ^ (w[i - 15] >> 3U);
    const std::uint32_t s1 = rotr32(w[i - 2], 17) ^
                             rotr32(w[i - 2], 19) ^ (w[i - 2] >> 10U);
    w[i] = w[i - 16] + s0 + w[i - 7] + s1;
  }

  std::uint32_t a = state[0];
  std::uint32_t b = state[1];
  std::uint32_t c = state[2];
  std::uint32_t d = state[3];
  std::uint32_t e = state[4];
  std::uint32_t f = state[5];
  std::uint32_t g = state[6];
  std::uint32_t h = state[7];

  for (std::size_t i = 0; i < 64; ++i) {
    const std::uint32_t s1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
    const std::uint32_t ch = (e & f) ^ ((~e) & g);
    const std::uint32_t temp1 = h + s1 + ch + kShaK[i] + w[i];
    const std::uint32_t s0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
    const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
    const std::uint32_t temp2 = s0 + maj;
    h = g;
    g = f;
    f = e;
    e = d + temp1;
    d = c;
    c = b;
    b = a;
    a = temp1 + temp2;
  }

  state[0] += a;
  state[1] += b;
  state[2] += c;
  state[3] += d;
  state[4] += e;
  state[5] += f;
  state[6] += g;
  state[7] += h;
}

void require_sha256_invariants(std::uint64_t total, std::size_t buffered) {
  constexpr std::uint64_t kMaxShaBytes =
      std::numeric_limits<std::uint64_t>::max() / 8U;
  if (buffered > 63U) {
    fail(ErrorCode::internal_failure,
         "SHA-256 buffered-byte invariant exceeds 63");
  }
  if (total > kMaxShaBytes) {
    fail(ErrorCode::internal_failure,
         "SHA-256 bit-length invariant overflow");
  }
  if (buffered != static_cast<std::size_t>(total % 64U)) {
    fail(ErrorCode::internal_failure,
         "SHA-256 buffered-byte invariant disagrees with total length");
  }
}

}  // namespace

Xxh64State::Xxh64State(std::uint64_t seed) noexcept
    : seed_(seed),
      total_(0),
      v1_(seed + kPrime1 + kPrime2),
      v2_(seed + kPrime2),
      v3_(seed),
      v4_(seed - kPrime1),
      buffer_(),
      buffered_(0) {}

void Xxh64State::update(const std::uint8_t* data, std::size_t size) noexcept {
  if (size == 0) return;
  total_ += static_cast<std::uint64_t>(size);
  const std::uint8_t* p = data;
  const std::uint8_t* const end = data + size;
  if (buffered_ + size < 32) {
    std::copy(p, end, buffer_.begin() + buffered_);
    buffered_ += size;
    return;
  }
  if (buffered_ != 0) {
    const std::size_t fill = 32 - buffered_;
    std::copy(p, p + fill, buffer_.begin() + buffered_);
    const std::uint8_t* b = buffer_.data();
    v1_ = xxh_round(v1_, load_u64_le(b)); b += 8;
    v2_ = xxh_round(v2_, load_u64_le(b)); b += 8;
    v3_ = xxh_round(v3_, load_u64_le(b)); b += 8;
    v4_ = xxh_round(v4_, load_u64_le(b));
    p += fill;
    buffered_ = 0;
  }
  while (p + 32 <= end) {
    v1_ = xxh_round(v1_, load_u64_le(p)); p += 8;
    v2_ = xxh_round(v2_, load_u64_le(p)); p += 8;
    v3_ = xxh_round(v3_, load_u64_le(p)); p += 8;
    v4_ = xxh_round(v4_, load_u64_le(p)); p += 8;
  }
  buffered_ = static_cast<std::size_t>(end - p);
  if (buffered_ != 0) std::copy(p, end, buffer_.begin());
}

std::uint64_t Xxh64State::digest() const noexcept {
  std::uint64_t hash;
  if (total_ >= 32) {
    hash = rotl64(v1_, 1) + rotl64(v2_, 7) + rotl64(v3_, 12) +
           rotl64(v4_, 18);
    hash = xxh_merge(hash, v1_);
    hash = xxh_merge(hash, v2_);
    hash = xxh_merge(hash, v3_);
    hash = xxh_merge(hash, v4_);
  } else {
    hash = seed_ + kPrime5;
  }
  hash += total_;
  const std::uint8_t* p = buffer_.data();
  const std::uint8_t* const end = p + buffered_;
  while (p + 8 <= end) {
    const std::uint64_t lane = xxh_round(0, load_u64_le(p));
    hash ^= lane;
    hash = rotl64(hash, 27) * kPrime1 + kPrime4;
    p += 8;
  }
  if (p + 4 <= end) {
    hash ^= static_cast<std::uint64_t>(load_u32_le(p)) * kPrime1;
    hash = rotl64(hash, 23) * kPrime2 + kPrime3;
    p += 4;
  }
  while (p < end) {
    hash ^= static_cast<std::uint64_t>(*p) * kPrime5;
    hash = rotl64(hash, 11) * kPrime1;
    ++p;
  }
  hash ^= hash >> 33U;
  hash *= kPrime2;
  hash ^= hash >> 29U;
  hash *= kPrime3;
  hash ^= hash >> 32U;
  return hash;
}

Sha256State::Sha256State() noexcept
    : state_({{UINT32_C(0x6a09e667), UINT32_C(0xbb67ae85),
               UINT32_C(0x3c6ef372), UINT32_C(0xa54ff53a),
               UINT32_C(0x510e527f), UINT32_C(0x9b05688c),
               UINT32_C(0x1f83d9ab), UINT32_C(0x5be0cd19)}}),
      buffer_(),
      total_(0),
      buffered_(0) {}

void Sha256State::update(const std::uint8_t* data, std::size_t size) {
  require_sha256_invariants(total_, buffered_);
  if (size == 0) return;
  if (data == nullptr) {
    fail(ErrorCode::invalid_argument,
         "SHA-256 update data is null for nonzero length");
  }
  constexpr std::uint64_t kMaxShaBytes =
      std::numeric_limits<std::uint64_t>::max() / 8U;
  if (total_ > kMaxShaBytes ||
      static_cast<std::uint64_t>(size) > kMaxShaBytes - total_) {
    fail(ErrorCode::internal_failure, "SHA-256 bit-length overflow");
  }
  total_ += static_cast<std::uint64_t>(size);
  const std::uint8_t* p = data;
  std::size_t remaining = size;
  if (buffered_ != 0) {
    const std::size_t fill =
        std::min<std::size_t>(64U - buffered_, remaining);
    std::copy(p, p + fill, buffer_.begin() + buffered_);
    buffered_ += fill;
    p += fill;
    remaining -= fill;
    if (buffered_ != 64U) {
      require_sha256_invariants(total_, buffered_);
      return;
    }
    sha256_block(buffer_.data(), state_);
    buffered_ = 0;
  }
  while (remaining >= 64U) {
    sha256_block(p, state_);
    p += 64;
    remaining -= 64U;
  }
  buffered_ = remaining;
  if (buffered_ != 0) {
    std::copy(p, p + buffered_, buffer_.begin());
  }
  require_sha256_invariants(total_, buffered_);
}

Sha256 Sha256State::digest() const {
  require_sha256_invariants(total_, buffered_);
  Sha256State copy = *this;
  std::array<std::uint8_t, 128> tail{};
  if (copy.buffered_ != 0) {
    std::copy(copy.buffer_.begin(), copy.buffer_.begin() + copy.buffered_,
              tail.begin());
  }
  tail[copy.buffered_] = 0x80U;
  const std::size_t blocks = copy.buffered_ < 56 ? 1 : 2;
  const std::uint64_t bit_length = copy.total_ * 8U;
  const std::size_t length_offset = blocks * 64 - 8;
  for (unsigned i = 0; i < 8; ++i) {
    tail[length_offset + i] = static_cast<std::uint8_t>(
        (bit_length >> (56U - 8U * i)) & 0xffU);
  }
  for (std::size_t block = 0; block < blocks; ++block) {
    sha256_block(tail.data() + 64 * block, copy.state_);
  }
  Sha256 result{};
  for (std::size_t i = 0; i < copy.state_.size(); ++i) {
    store_u32_be(result.data() + 4 * i, copy.state_[i]);
  }
  return result;
}

std::uint64_t xxh64(const std::uint8_t* data, std::size_t size,
                    std::uint64_t seed) noexcept {
  static const std::uint8_t empty = 0;
  if (size == 0) data = &empty;
  const std::uint8_t* p = data;
  const std::uint8_t* const end = data + size;
  std::uint64_t hash;

  if (size >= 32) {
    std::uint64_t v1 = seed + kPrime1 + kPrime2;
    std::uint64_t v2 = seed + kPrime2;
    std::uint64_t v3 = seed;
    std::uint64_t v4 = seed - kPrime1;
    const std::uint8_t* const limit = end - 32;
    do {
      v1 = xxh_round(v1, load_u64_le(p)); p += 8;
      v2 = xxh_round(v2, load_u64_le(p)); p += 8;
      v3 = xxh_round(v3, load_u64_le(p)); p += 8;
      v4 = xxh_round(v4, load_u64_le(p)); p += 8;
    } while (p <= limit);
    hash = rotl64(v1, 1) + rotl64(v2, 7) + rotl64(v3, 12) + rotl64(v4, 18);
    hash = xxh_merge(hash, v1);
    hash = xxh_merge(hash, v2);
    hash = xxh_merge(hash, v3);
    hash = xxh_merge(hash, v4);
  } else {
    hash = seed + kPrime5;
  }

  hash += static_cast<std::uint64_t>(size);
  while (p + 8 <= end) {
    const std::uint64_t lane = xxh_round(0, load_u64_le(p));
    hash ^= lane;
    hash = rotl64(hash, 27) * kPrime1 + kPrime4;
    p += 8;
  }
  if (p + 4 <= end) {
    hash ^= static_cast<std::uint64_t>(load_u32_le(p)) * kPrime1;
    hash = rotl64(hash, 23) * kPrime2 + kPrime3;
    p += 4;
  }
  while (p < end) {
    hash ^= static_cast<std::uint64_t>(*p) * kPrime5;
    hash = rotl64(hash, 11) * kPrime1;
    ++p;
  }
  hash ^= hash >> 33U;
  hash *= kPrime2;
  hash ^= hash >> 29U;
  hash *= kPrime3;
  hash ^= hash >> 32U;
  return hash;
}

Sha256 sha256(const std::uint8_t* data, std::size_t size) {
  constexpr std::uint64_t kMaxShaBytes =
      std::numeric_limits<std::uint64_t>::max() / 8U;
  if (static_cast<std::uint64_t>(size) > kMaxShaBytes) {
    fail(ErrorCode::internal_failure, "SHA-256 one-shot bit-length overflow");
  }
  std::array<std::uint32_t, 8> state = {{
      UINT32_C(0x6a09e667), UINT32_C(0xbb67ae85), UINT32_C(0x3c6ef372),
      UINT32_C(0xa54ff53a), UINT32_C(0x510e527f), UINT32_C(0x9b05688c),
      UINT32_C(0x1f83d9ab), UINT32_C(0x5be0cd19)}};

  std::size_t offset = 0;
  while (size - offset >= 64) {
    sha256_block(data + offset, state);
    offset += 64;
  }

  std::array<std::uint8_t, 128> tail{};
  const std::size_t remaining = size - offset;
  if (remaining != 0) {
    std::copy(data + offset, data + size, tail.begin());
  }
  tail[remaining] = 0x80U;
  const std::size_t blocks = remaining < 56 ? 1 : 2;
  const std::uint64_t bit_length = static_cast<std::uint64_t>(size) * 8U;
  const std::size_t length_offset = blocks * 64 - 8;
  for (unsigned i = 0; i < 8; ++i) {
    tail[length_offset + i] =
        static_cast<std::uint8_t>((bit_length >> (56U - 8U * i)) & 0xffU);
  }
  for (std::size_t block = 0; block < blocks; ++block) {
    sha256_block(tail.data() + 64 * block, state);
  }

  Sha256 digest{};
  for (std::size_t i = 0; i < state.size(); ++i) {
    store_u32_be(digest.data() + 4 * i, state[i]);
  }
  return digest;
}

Sha256 sha256_guard_probe_for_test(std::uint64_t total,
                                   std::size_t buffered) {
  Sha256State state;
  state.total_ = total;
  state.buffered_ = buffered;
  return state.digest();
}

std::string hex_lower(const std::uint8_t* data, std::size_t size) {
  static const char digits[] = "0123456789abcdef";
  std::string out;
  out.resize(size * 2);
  for (std::size_t i = 0; i < size; ++i) {
    out[2 * i] = digits[(data[i] >> 4U) & 0x0fU];
    out[2 * i + 1] = digits[data[i] & 0x0fU];
  }
  return out;
}

bool constant_time_equal(const Sha256& left, const Sha256& right) noexcept {
  std::uint8_t difference = 0;
  for (std::size_t i = 0; i < left.size(); ++i) {
    difference |= static_cast<std::uint8_t>(left[i] ^ right[i]);
  }
  return difference == 0;
}

}  // namespace engine002
}  // namespace splitaligner
