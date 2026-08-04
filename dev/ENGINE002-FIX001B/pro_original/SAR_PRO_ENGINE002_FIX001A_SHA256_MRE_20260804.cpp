#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

#include "engine002_hash.h"

int main() {
  using namespace splitaligner::engine002;
  const std::string text = "abc";
  const std::vector<std::uint8_t> bytes(text.begin(), text.end());

  const Sha256 one_shot = sha256(bytes);

  Sha256State single_update;
  single_update.update(bytes.data(), bytes.size());

  Sha256State three_updates;
  three_updates.update(reinterpret_cast<const std::uint8_t*>("a"), 1U);
  three_updates.update(reinterpret_cast<const std::uint8_t*>("b"), 1U);
  three_updates.update(reinterpret_cast<const std::uint8_t*>("c"), 1U);

  std::cout << "one_shot=" << hex_lower(one_shot) << "\n";
  std::cout << "single_update=" << hex_lower(single_update.digest()) << "\n";
  std::cout << "three_updates=" << hex_lower(three_updates.digest()) << "\n";
  return 0;
}
