#ifndef SPLITALIGNERR_ENGINE002_LRU_HPP
#define SPLITALIGNERR_ENGINE002_LRU_HPP

#include "engine002_hash.h"

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <vector>

namespace splitaligner {
namespace engine002 {

struct LruStats {
  std::uint64_t hits = 0;
  std::uint64_t misses = 0;
  std::uint64_t insertions = 0;
  std::uint64_t evictions = 0;
  std::uint64_t oversized_bypasses = 0;
  std::uint64_t pin_failures = 0;
  std::uint64_t cache_high_water = 0;
  std::uint64_t scratch_high_water = 0;
  std::uint64_t charged_cache_bytes = 0;
  std::uint64_t active_scratch_bytes = 0;
};

struct LruLease {
  std::shared_ptr<const void> owner;
  std::shared_ptr<const std::vector<std::uint8_t>> record;
  bool scratch = false;
};

class HardBoundedLru : public std::enable_shared_from_this<HardBoundedLru> {
 public:
  using Loader = std::function<std::shared_ptr<const std::vector<std::uint8_t>>() >;

  HardBoundedLru(std::uint64_t cache_budget,
                 std::uint64_t scratch_budget);
  LruLease acquire(std::uint64_t pattern_id,
                   const std::vector<std::uint8_t>& retained,
                   std::uint64_t record_bytes,
                   const Loader& loader);
  LruStats stats() const noexcept;
  void clear();
  std::uint64_t cache_budget() const noexcept { return cache_budget_; }
  std::uint64_t scratch_budget() const noexcept { return scratch_budget_; }

  static std::uint64_t charged_bytes(std::uint64_t record_bytes,
                                     std::size_t retained_bytes);

 private:
  struct Entry {
    std::vector<std::uint8_t> retained;
    std::shared_ptr<const std::vector<std::uint8_t>> record;
    std::uint64_t charge = 0;
    std::uint64_t last_use = 0;
    std::uint64_t pins = 0;
  };
  struct LeaseOwner;

  void release(std::uint64_t pattern_id, bool scratch,
               std::uint64_t scratch_bytes) noexcept;
  void assert_bounds() const;

  mutable std::mutex mutex_;
  std::uint64_t cache_budget_;
  std::uint64_t scratch_budget_;
  std::uint64_t sequence_;
  std::map<std::uint64_t, Entry> entries_;
  LruStats stats_;
};

}  // namespace engine002
}  // namespace splitaligner

#endif

