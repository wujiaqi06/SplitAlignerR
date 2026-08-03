#ifndef SPLITALIGNERR_ENGINE002_DISK_STORE_HPP
#define SPLITALIGNERR_ENGINE002_DISK_STORE_HPP

#include "engine002_lru.h"
#include "engine002_manifest.h"
#include "engine002_store.h"

#include <filesystem>
#include <memory>
#include <mutex>
#include <vector>

namespace splitaligner {
namespace engine002 {

struct DiskIndexEntry {
  std::uint64_t pattern_id = 0;
  std::uint64_t record_offset = 0;
  std::uint64_t record_bytes = 0;
  Sha256 pattern_sha256{};
  std::uint64_t record_xxh64 = 0;
  std::vector<std::uint8_t> retained;
};

struct ValidatedDiskStore {
  StoreManifest manifest;
  std::filesystem::path component_path;
  std::vector<DiskIndexEntry> index;
  Sha256 store_identity_sha256{};
};

struct DiskStoreStats {
  std::uint64_t generation = 1;
  std::uint64_t pattern_count = 0;
  std::uint64_t file_bytes = 0;
  std::uint64_t index_charged_bytes = 0;
  std::uint64_t metadata_charged_bytes = 0;
  std::uint64_t combined_runtime_bound = 0;
  LruStats lru;
};

ValidatedDiskStore validate_disk_store(
    const SpeciesAuthority& authority,
    const std::filesystem::path& component_path,
    const StoreManifest* manifest,
    std::uint64_t scratch_budget,
    std::uint64_t index_budget,
    std::uint64_t metadata_budget);

class PackedDiskStore : public std::enable_shared_from_this<PackedDiskStore> {
 public:
  PackedDiskStore(SpeciesAuthorityPtr authority,
                  std::uint64_t pattern_count,
                  std::uint64_t cache_budget,
                  std::uint64_t scratch_budget,
                  std::uint64_t index_budget,
                  std::uint64_t metadata_budget,
                  std::uint64_t combined_runtime_bound);

  static std::shared_ptr<PackedDiskStore> open_existing(
      SpeciesAuthorityPtr authority,
      const std::filesystem::path& manifest_path,
      std::uint64_t cache_budget,
      std::uint64_t scratch_budget,
      std::uint64_t index_budget,
      std::uint64_t metadata_budget,
      std::uint64_t combined_runtime_bound);

  void insert(std::shared_ptr<const std::vector<std::uint8_t>> record);
  std::filesystem::path finalize_publish(
      const std::filesystem::path& directory,
      const std::string& run_store_id);
  DecodedPlan lookup_snapshot(std::uint64_t pattern_id,
                              const std::vector<std::uint8_t>& retained);
  std::shared_ptr<const void> debug_pin(
      std::uint64_t pattern_id,
      const std::vector<std::uint8_t>& retained);
  void close();
  StoreState state() const noexcept;
  DiskStoreStats stats() const noexcept;
  const std::filesystem::path& manifest_path() const { return manifest_path_; }

 private:
  PackedDiskStore(SpeciesAuthorityPtr authority,
                  const ValidatedDiskStore& validated,
                  const std::filesystem::path& manifest_path,
                  std::uint64_t cache_budget,
                  std::uint64_t scratch_budget,
                  std::uint64_t index_budget,
                  std::uint64_t metadata_budget,
                  std::uint64_t combined_runtime_bound);

  LruLease acquire(std::uint64_t pattern_id,
                   const std::vector<std::uint8_t>& retained);
  void validate_runtime_budgets() const;

  SpeciesAuthorityPtr authority_;
  mutable std::mutex mutex_;
  StoreState state_;
  std::uint64_t generation_;
  std::unique_ptr<StoreBuilder> builder_;
  std::unique_ptr<FinalizedPlanSet> finalized_;
  std::filesystem::path component_path_;
  std::filesystem::path manifest_path_;
  std::vector<DiskIndexEntry> index_;
  std::shared_ptr<HardBoundedLru> cache_;
  std::uint64_t cache_budget_;
  std::uint64_t scratch_budget_;
  std::uint64_t index_budget_;
  std::uint64_t metadata_budget_;
  std::uint64_t combined_runtime_bound_;
  std::uint64_t file_bytes_;
  std::uint64_t index_charged_bytes_;
  std::uint64_t metadata_charged_bytes_;
};

}  // namespace engine002
}  // namespace splitaligner

#endif

