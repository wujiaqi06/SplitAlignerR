#include "engine002_checked_math.h"
#include "engine002_disk_store.h"
#include "engine002_stress_fixture.h"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <string>

namespace e2 = splitaligner::engine002;

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: fix001_large_boundary_probe <manifest> <count>\n";
    return 64;
  }
  const std::filesystem::path manifest(argv[1]);
  const std::uint64_t count = std::stoull(argv[2]);
  if (count == 0) return 65;
  const std::uint64_t MiB = UINT64_C(1024) * 1024U;
  const std::uint64_t index_budget =
      std::max<std::uint64_t>(64U * MiB, count * 320U);
  auto fixture = e2::make_authority_scale_fixture(count);
  auto store = e2::PackedDiskStore::open_existing(
      fixture.authority, manifest, 64U * 1024U, MiB, index_budget, MiB,
      index_budget + 2U * MiB + 64U * 1024U);
  const std::uint64_t window = std::min<std::uint64_t>(count, 1024U);
  const std::uint64_t fixed_seed = UINT64_C(0xd1b54a32d192ed03);
  const std::uint64_t near_boundary_id =
      count - 1U - (fixed_seed % window);
  const auto& retained = fixture.registry->retained_patterns[
      e2::checked_size(near_boundary_id, "large-boundary lookup position")];
  const auto decoded = store->lookup_snapshot(near_boundary_id, retained);
  const bool pass = decoded.pattern_id == near_boundary_id &&
                    decoded.retained == retained;
  store->close();
  std::cout << "status=" << (pass ? "PASS" : "FAIL") << '\n'
            << "pattern_count=" << count << '\n'
            << "fixed_seed=" << fixed_seed << '\n'
            << "boundary_window=" << window << '\n'
            << "near_boundary_pattern_id=" << near_boundary_id << '\n'
            << "distance_from_last=" << (count - 1U - near_boundary_id)
            << '\n';
  return pass ? 0 : 1;
}
