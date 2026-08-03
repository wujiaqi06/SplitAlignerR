// Compile this diagnostic only against the frozen ENGINE002 base commit
// 8c0d494f57f4594ff5acfd8e02ef546fcc387f0b. It intentionally exercises the
// superseded retain-all PackedDiskStore constructor for a controlled comparison.

#include "engine002_checked_math.h"
#include "engine002_disk_store.h"
#include "engine002_errors.h"
#include "engine002_plan_codec.h"
#include "engine002_species_authority_binding.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace e2 = splitaligner::engine002;

namespace {

constexpr std::uint32_t kTaxa = 302;
constexpr std::uint32_t kInternal = 299;
constexpr std::uint32_t kPrimitives = kTaxa + kInternal;
constexpr std::size_t kRetainedBytes = (kTaxa + 7U) / 8U;

void set_bit(std::vector<std::uint8_t>& bytes, std::uint32_t id) {
  bytes[id / 8U] |= static_cast<std::uint8_t>(1U << (id % 8U));
}

std::vector<std::uint8_t> retained_for_id(std::uint64_t pattern_id) {
  std::vector<std::uint8_t> retained(kRetainedBytes, UINT8_C(0xff));
  for (std::size_t i = 0; i < 8; ++i) {
    retained[i] = static_cast<std::uint8_t>(
        (pattern_id >> (8U * (7U - i))) & UINT64_C(0xff));
  }
  retained.back() = UINT8_C(0x3f);
  return retained;
}

std::vector<std::uint32_t> retained_taxa(
    const std::vector<std::uint8_t>& retained) {
  std::vector<std::uint32_t> taxa;
  taxa.reserve(kTaxa);
  for (std::uint32_t taxon = 0; taxon < kTaxa; ++taxon) {
    if (e2::bit_is_set(retained.data(), taxon)) taxa.push_back(taxon);
  }
  return taxa;
}

e2::SpeciesAuthorityPtr make_authority() {
  std::vector<std::string> labels;
  labels.reserve(kTaxa);
  for (std::uint32_t taxon = 0; taxon < kTaxa; ++taxon) {
    std::ostringstream label;
    label << 'T' << std::setw(3) << std::setfill('0') << taxon;
    labels.push_back(label.str());
  }
  std::vector<std::uint32_t> terminals(kPrimitives, e2::kInternalTaxon);
  std::vector<std::vector<std::uint8_t>> splits(
      kPrimitives, std::vector<std::uint8_t>(kRetainedBytes, 0));
  for (std::uint32_t taxon = 0; taxon < kTaxa; ++taxon) {
    terminals[taxon] = taxon;
    set_bit(splits[taxon], taxon);
  }
  std::uint32_t internal = 0;
  for (std::uint32_t left = 0; left < kTaxa && internal < kInternal; ++left) {
    for (std::uint32_t right = left + 1;
         right < kTaxa && internal < kInternal; ++right) {
      set_bit(splits[kTaxa + internal], left);
      set_bit(splits[kTaxa + internal], right);
      ++internal;
    }
  }
  return e2::make_species_authority(
      std::move(labels), std::move(terminals), std::move(splits));
}

std::shared_ptr<const std::vector<std::uint8_t>> make_record(
    const e2::SpeciesAuthority& authority, std::uint64_t pattern_id) {
  e2::PlanInput input;
  input.pattern_id = pattern_id;
  input.retained = retained_for_id(pattern_id);
  input.states.assign(kPrimitives, 0);
  input.primitive_queries.resize(kPrimitives);
  const auto taxa = retained_taxa(input.retained);
  for (std::uint32_t taxon = 0; taxon < kTaxa; ++taxon) {
    if (e2::bit_is_set(input.retained.data(), taxon)) {
      input.primitive_queries[taxon].assign(kRetainedBytes, 0);
      set_bit(input.primitive_queries[taxon], taxon);
    } else {
      input.states[taxon] = 1;
    }
  }
  std::uint32_t internal = 0;
  for (std::size_t left = 0;
       left < taxa.size() && internal < kInternal; ++left) {
    for (std::size_t middle = left + 1;
         middle < taxa.size() && internal < kInternal; ++middle) {
      for (std::size_t right = middle + 1;
           right < taxa.size() && internal < kInternal; ++right) {
        auto& query = input.primitive_queries[kTaxa + internal];
        query.assign(kRetainedBytes, 0);
        set_bit(query, taxa[left]);
        set_bit(query, taxa[middle]);
        set_bit(query, taxa[right]);
        ++internal;
      }
    }
  }
  return std::make_shared<const std::vector<std::uint8_t>>(
      e2::encode_plan_record(authority, input));
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 4) {
    std::cerr << "usage: fix001_retain_all_benchmark <directory> <count> <run-id>\n";
    return 64;
  }
  using Clock = std::chrono::steady_clock;
  const std::filesystem::path directory(argv[1]);
  const std::uint64_t count = std::stoull(argv[2]);
  const std::string run_id(argv[3]);
  const std::uint64_t MiB = UINT64_C(1024) * 1024U;
  const std::uint64_t index_budget =
      std::max<std::uint64_t>(64U * MiB, count * 320U);
  const auto authority = make_authority();
  auto store = std::make_shared<e2::PackedDiskStore>(
      authority, count, 0, MiB, index_budget, MiB, index_budget + 2U * MiB);
  std::uint64_t total = 0;
  std::uint64_t minimum =
      count == 0 ? 0 : std::numeric_limits<std::uint64_t>::max();
  std::uint64_t maximum = 0;
  const auto insert_started = Clock::now();
  for (std::uint64_t pattern = 0; pattern < count; ++pattern) {
    const auto record = make_record(*authority, pattern);
    total = e2::checked_add<std::uint64_t>(
        total, record->size(), "retain-all benchmark record bytes");
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
            << "builder=retain_all_base_8c0d494f\n"
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
            << "builder_retained_payload_lower_bound=" << total << '\n'
            << "index_charged_bytes=" << stats.index_charged_bytes << '\n'
            << "manifest=" << manifest.string() << '\n';
  return 0;
}
