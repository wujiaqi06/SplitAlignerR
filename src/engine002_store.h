#ifndef SPLITALIGNERR_ENGINE002_STORE_HPP
#define SPLITALIGNERR_ENGINE002_STORE_HPP

#include "engine002_plan_codec.h"

#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace splitaligner {
namespace engine002 {

enum class StoreState { building, finalized, open_validated, closed };

struct PlanRecordEntry {
  std::uint64_t pattern_id = 0;
  std::vector<std::uint8_t> retained;
  Sha256 pattern_sha256{};
  std::shared_ptr<const std::vector<std::uint8_t>> record;
  std::uint64_t record_xxh64 = 0;
};

struct FinalizedPlanSet {
  SpeciesAuthorityPtr authority;
  std::vector<PlanRecordEntry> records;
  Sha256 pattern_registry_sha256{};
  Sha256 truth_semantics_sha256{};
  Sha256 store_identity_sha256{};
};

class StoreBuilder {
 public:
  StoreBuilder(SpeciesAuthorityPtr authority, std::uint64_t expected_count);
  void insert(std::shared_ptr<const std::vector<std::uint8_t>> record);
  FinalizedPlanSet finalize() const;
  std::uint64_t expected_count() const noexcept { return expected_count_; }
  std::size_t inserted_count() const noexcept { return by_id_.size(); }

 private:
  SpeciesAuthorityPtr authority_;
  std::uint64_t expected_count_;
  std::map<std::uint64_t, PlanRecordEntry> by_id_;
  std::map<std::vector<std::uint8_t>, std::uint64_t> by_pattern_;
};

struct MemoryStoreStats {
  std::uint64_t inserted = 0;
  std::uint64_t lookups = 0;
  std::uint64_t active_pins = 0;
  std::uint64_t generation = 1;
  std::uint64_t arena_bytes = 0;
};

class PackedMemoryStore
    : public std::enable_shared_from_this<PackedMemoryStore> {
 public:
  PackedMemoryStore(SpeciesAuthorityPtr authority, std::uint64_t pattern_count);
  void insert(std::shared_ptr<const std::vector<std::uint8_t>> record);
  void finalize();
  DecodedPlan lookup_snapshot(std::uint64_t pattern_id,
                              const std::vector<std::uint8_t>& retained);
  std::shared_ptr<const void> debug_pin(std::uint64_t pattern_id,
                                        const std::vector<std::uint8_t>& retained);
  void close();
  StoreState state() const noexcept;
  MemoryStoreStats stats() const noexcept;
  const FinalizedPlanSet& finalized() const;

 private:
  struct ArenaEntry {
    std::uint64_t offset = 0;
    std::uint64_t bytes = 0;
    std::vector<std::uint8_t> retained;
    Sha256 pattern_sha256{};
  };
  struct PinOwner;

  std::shared_ptr<PinOwner> acquire_pin(
      std::uint64_t pattern_id,
      const std::vector<std::uint8_t>& retained);
  void release_pin() noexcept;
  void require_open_immutable() const;

  SpeciesAuthorityPtr authority_;
  mutable std::mutex mutex_;
  StoreState state_;
  std::uint64_t generation_;
  std::uint64_t inserted_;
  std::uint64_t lookups_;
  std::uint64_t active_pins_;
  std::unique_ptr<StoreBuilder> builder_;
  std::unique_ptr<FinalizedPlanSet> finalized_;
  std::shared_ptr<const std::vector<std::uint8_t>> arena_;
  std::vector<ArenaEntry> index_;
};

}  // namespace engine002
}  // namespace splitaligner

#endif

