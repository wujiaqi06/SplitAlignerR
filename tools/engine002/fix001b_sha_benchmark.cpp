#include "engine002_hash.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <string>
#include <vector>

int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "usage: fix001b_sha_benchmark <bytes> <chunk> <repetitions>\n";
    return 64;
  }
  const std::size_t bytes = std::stoull(argv[1]);
  const std::size_t chunk = std::stoull(argv[2]);
  const std::size_t repetitions = std::stoull(argv[3]);
  if (chunk == 0 || repetitions == 0) return 64;
  std::vector<std::uint8_t> block(chunk);
  for (std::size_t i = 0; i < block.size(); ++i) {
    block[i] = static_cast<std::uint8_t>((i * 131U + 17U) & 0xffU);
  }
  std::vector<double> seconds;
  std::string observed;
  for (std::size_t repetition = 0; repetition < repetitions; ++repetition) {
    splitaligner::engine002::Sha256State state;
    const auto started = std::chrono::steady_clock::now();
    std::size_t supplied = 0;
    while (supplied < bytes) {
      const std::size_t take = std::min(chunk, bytes - supplied);
      state.update(block.data(), take);
      supplied += take;
    }
    const auto digest = state.digest();
    seconds.push_back(std::chrono::duration<double>(
        std::chrono::steady_clock::now() - started).count());
    const std::string current = splitaligner::engine002::hex_lower(digest);
    if (!observed.empty() && observed != current) return 1;
    observed = current;
  }
  const auto bounds = std::minmax_element(seconds.begin(), seconds.end());
  const double minimum = *bounds.first;
  const double maximum = *bounds.second;
  std::sort(seconds.begin(), seconds.end());
  const double median = seconds[seconds.size() / 2U];
  std::cout << "bytes=" << bytes << '\n'
            << "chunk_bytes=" << chunk << '\n'
            << "repetitions=" << repetitions << '\n'
            << "minimum_seconds=" << minimum << '\n'
            << "median_seconds=" << median << '\n'
            << "maximum_seconds=" << maximum << '\n'
            << "digest=" << observed << '\n';
}
