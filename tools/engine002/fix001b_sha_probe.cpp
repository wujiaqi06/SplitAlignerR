#include "engine002_errors.h"
#include "engine002_hash.h"

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {

constexpr std::uint32_t kEnd = UINT32_C(0xffffffff);

void configure_binary_stdio() {
#ifdef _WIN32
  if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
      _setmode(_fileno(stdout), _O_BINARY) == -1) {
    throw std::runtime_error("cannot configure FIX001B SHA probe binary I/O");
  }
#endif
}

std::uint32_t read_u32_le(std::istream& input) {
  std::array<std::uint8_t, 4> bytes{};
  input.read(reinterpret_cast<char*>(bytes.data()), bytes.size());
  if (input.gcount() != static_cast<std::streamsize>(bytes.size())) {
    throw std::runtime_error("truncated FIX001B SHA probe request");
  }
  return static_cast<std::uint32_t>(bytes[0]) |
         (static_cast<std::uint32_t>(bytes[1]) << 8U) |
         (static_cast<std::uint32_t>(bytes[2]) << 16U) |
         (static_cast<std::uint32_t>(bytes[3]) << 24U);
}

void read_exact(std::istream& input, std::uint8_t* destination,
                std::size_t size) {
  std::size_t offset = 0;
  while (offset < size) {
    const std::size_t chunk = std::min<std::size_t>(
        size - offset,
        static_cast<std::size_t>(std::numeric_limits<std::streamsize>::max()));
    input.read(reinterpret_cast<char*>(destination + offset),
               static_cast<std::streamsize>(chunk));
    if (input.gcount() != static_cast<std::streamsize>(chunk)) {
      throw std::runtime_error("truncated FIX001B SHA probe message");
    }
    offset += chunk;
  }
}

void write_digest(const splitaligner::engine002::Sha256& digest) {
  std::cout.write(reinterpret_cast<const char*>(digest.data()),
                  static_cast<std::streamsize>(digest.size()));
}

void verify_edge_contract() {
  using splitaligner::engine002::ErrorCode;
  using splitaligner::engine002::EngineError;
  using splitaligner::engine002::Sha256State;
  using splitaligner::engine002::sha256;

  Sha256State empty;
  empty.update(nullptr, 0);
  if (empty.digest() != sha256(nullptr, 0)) {
    throw std::runtime_error("zero-length SHA update changed the digest");
  }
  bool rejected = false;
  try {
    empty.update(nullptr, 1);
  } catch (const EngineError& error) {
    rejected = error.code() == ErrorCode::invalid_argument;
  }
  if (!rejected) {
    throw std::runtime_error("nonzero null SHA update was not rejected");
  }
}

}  // namespace

int main() {
  using splitaligner::engine002::Sha256State;
  using splitaligner::engine002::sha256;

  try {
    configure_binary_stdio();
    verify_edge_contract();
    std::array<char, 8> magic{};
    std::cin.read(magic.data(), magic.size());
    if (std::cin.gcount() != static_cast<std::streamsize>(magic.size()) ||
        magic != std::array<char, 8>{{'S', 'A', 'H', 'C', 'A', 'S', 'E', '1'}}) {
      throw std::runtime_error("invalid FIX001B SHA probe protocol");
    }

    while (true) {
      const std::uint32_t message_bytes = read_u32_le(std::cin);
      if (message_bytes == kEnd) break;
      const std::uint32_t chunk_count = read_u32_le(std::cin);
      const std::uint32_t flags = read_u32_le(std::cin);
      if ((flags & ~UINT32_C(1)) != 0 || chunk_count > UINT32_C(2000000)) {
        throw std::runtime_error("invalid FIX001B SHA probe case header");
      }

      std::vector<std::uint32_t> chunks(chunk_count);
      std::uint64_t chunk_total = 0;
      for (auto& chunk : chunks) {
        chunk = read_u32_le(std::cin);
        chunk_total += chunk;
      }
      if (chunk_total != message_bytes) {
        throw std::runtime_error("SHA probe chunks do not cover the message");
      }
      std::vector<std::uint8_t> message(message_bytes);
      read_exact(std::cin, message.data(), message.size());

      Sha256State incremental;
      std::size_t offset = 0;
      for (const std::uint32_t chunk : chunks) {
        if (chunk == 0) {
          incremental.update(nullptr, 0);
        } else {
          incremental.update(message.data() + offset, chunk);
          offset += chunk;
        }
        if ((flags & UINT32_C(1)) != 0) {
          const auto first = incremental.digest();
          if (first != incremental.digest()) {
            throw std::runtime_error("repeated digest changed SHA state");
          }
        }
      }
      if (offset != message.size()) {
        throw std::runtime_error("SHA probe final chunk offset mismatch");
      }

      const auto one_shot = sha256(message.data(), message.size());
      const auto first = incremental.digest();
      const auto second = incremental.digest();
      write_digest(one_shot);
      write_digest(first);
      write_digest(second);
      std::cout.flush();
      if (!std::cout) {
        throw std::runtime_error("cannot write FIX001B SHA probe response");
      }
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
