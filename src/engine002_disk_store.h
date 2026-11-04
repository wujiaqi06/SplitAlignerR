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

class ExclusiveBinaryWriter;

struct DiskIndexEntry {
  std::uint64_t pattern_id = 0;
  std::uint64_t record_offset = 0;
  std::uint64_t record_bytes = 0;
  Sha256 pattern_sha256{};
  std::uint64_t record_xxh64 = 0;
  std::uint64_t lookup_fast_hash = 0;
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
  std::uint64_t inserted_count = 0;
  std::uint64_t file_bytes = 0;
  std::uint64_t index_charged_bytes = 0;
  std::uint64_t metadata_charged_bytes = 0;
  std::uint64_t combined_runtime_bound = 0;
  std::uint64_t builder_charged_bytes = 0;
  std::uint64_t builder_charged_high_water = 0;
  std::uint64_t current_record_high_water = 0;
  std::uint64_t write_buffer_high_water = 0;
  std::uint64_t temporary_disk_high_water = 0;
  double finalize_io_seconds = 0;
  double temporary_validation_seconds = 0;
  double manifest_prepare_seconds = 0;
  double atomic_publication_seconds = 0;
  double published_validation_seconds = 0;
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
                  PatternRegistryPtr registry,
                  const std::filesystem::path& directory,
                  const std::string& run_store_id,
                  std::uint64_t cache_budget,
                  std::uint64_t scratch_budget,
                  std::uint64_t index_budget,
                  std::uint64_t metadata_budget,
                  std::uint64_t combined_runtime_bound);
  ~PackedDiskStore() noexcept;

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
  void cleanup_builder_temporary() noexcept;
  void update_builder_high_water(std::uint64_t current_record_bytes);

  SpeciesAuthorityPtr authority_;
  PatternRegistryPtr registry_;
  bool constant_fast_hash_;
  mutable std::mutex mutex_;
  StoreState state_;
  std::uint64_t generation_;
  std::unique_ptr<ExclusiveBinaryWriter> writer_;
  std::filesystem::path directory_;
  std::string run_store_id_;
  std::filesystem::path component_temp_;
  std::filesystem::path candidate_temp_;
  std::filesystem::path validated_temp_;
  std::filesystem::path component_final_;
  std::filesystem::path manifest_final_;
  std::vector<std::uint8_t> index_wire_;
  Xxh64State records_hash_;
  Sha256State payload_hash_;
  std::uint64_t next_pattern_id_;
  std::uint64_t records_bytes_;
  std::uint64_t builder_charged_bytes_;
  std::uint64_t builder_charged_high_water_;
  std::uint64_t current_record_high_water_;
  std::uint64_t write_buffer_high_water_;
  std::uint64_t temporary_disk_high_water_;
  double finalize_io_seconds_;
  double temporary_validation_seconds_;
  double manifest_prepare_seconds_;
  double atomic_publication_seconds_;
  double published_validation_seconds_;
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
