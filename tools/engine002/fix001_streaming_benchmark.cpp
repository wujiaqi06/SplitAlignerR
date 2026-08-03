#include "engine002_checked_math.h"
#include "engine002_disk_store.h"
#include "engine002_stress_fixture.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <limits>
#include <memory>
#include <string>

namespace e2 = splitaligner::engine002;

int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "usage: fix001_streaming_benchmark <directory> <count> <run-id>\n";
    return 64;
  }
  using Clock = std::chrono::steady_clock;
  const std::filesystem::path directory(argv[1]);
  const std::uint64_t count = std::stoull(argv[2]);
  const std::string run_id(argv[3]);
  const std::uint64_t MiB = UINT64_C(1024) * 1024U;
  const std::uint64_t index_budget =
      std::max<std::uint64_t>(64U * MiB, count * 320U);
  auto fixture = e2::make_authority_scale_fixture(count);
  auto store = std::make_shared<e2::PackedDiskStore>(
      fixture.authority, fixture.registry, directory, run_id, 0, MiB,
      index_budget, MiB, index_budget + 2U * MiB);
  std::uint64_t total = 0;
  std::uint64_t minimum =
      count == 0 ? 0 : std::numeric_limits<std::uint64_t>::max();
  std::uint64_t maximum = 0;
  const auto insert_started = Clock::now();
  for (std::uint64_t pattern = 0; pattern < count; ++pattern) {
    const auto& retained = fixture.registry->retained_patterns[
        e2::checked_size(pattern, "streaming benchmark registry position")];
    const auto record = e2::make_authority_scale_record(
        *fixture.authority, pattern, retained);
    total = e2::checked_add<std::uint64_t>(
        total, record->size(), "streaming benchmark record bytes");
    minimum = std::min<std::uint64_t>(minimum, record->size());
    maximum = std::max<std::uint64_t>(maximum, record->size());
    store->insert(record);
  }
  const auto insert_finished = Clock::now();
  const auto finalize_started = Clock::now();
  const auto manifest = store->finalize_publish(directory, run_id);
  const auto finalize_finished = Clock::now();
  const auto stats = store->stats();
  store->close();
  std::cout << "status=PASS\n"
            << "builder=streaming_core_fix001\n"
            << "pattern_count=" << count << '\n'
            << "total_record_bytes=" << total << '\n'
            << "mean_record_bytes="
            << (count == 0 ? 0.0 : static_cast<double>(total) / count) << '\n'
            << "minimum_record_bytes=" << minimum << '\n'
            << "maximum_record_bytes=" << maximum << '\n'
            << "insert_record_generation_seconds="
            << std::chrono::duration<double>(
                   insert_finished - insert_started).count() << '\n'
            << "finalize_validate_publish_seconds="
            << std::chrono::duration<double>(
                   finalize_finished - finalize_started).count() << '\n'
            << "final_store_bytes=" << stats.file_bytes << '\n'
            << "builder_charged_high_water="
            << stats.builder_charged_high_water << '\n'
            << "current_record_high_water="
            << stats.current_record_high_water << '\n'
            << "write_buffer_high_water="
            << stats.write_buffer_high_water << '\n'
            << "temporary_disk_high_water="
            << stats.temporary_disk_high_water << '\n'
            << "index_charged_bytes=" << stats.index_charged_bytes << '\n'
            << "manifest=" << manifest.string() << '\n';
  return 0;
}
