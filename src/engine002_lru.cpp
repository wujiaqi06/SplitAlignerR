#include "engine002_lru.h"

#include "engine002_checked_math.h"
#include "engine002_errors.h"

#include <algorithm>
#include <limits>

namespace splitaligner {
namespace engine002 {
namespace {

std::uint64_t align64(std::uint64_t value) {
  return checked_add<std::uint64_t>(value, 63U, "LRU alignment") & ~UINT64_C(63);
}

void increment_counter(std::uint64_t& value, const char* context) {
  value = checked_add<std::uint64_t>(value, 1U, context);
}

}  // namespace

struct HardBoundedLru::LeaseOwner {
  std::shared_ptr<HardBoundedLru> cache;
  std::uint64_t pattern_id;
  bool scratch;
  std::uint64_t scratch_bytes;
  LeaseOwner(std::shared_ptr<HardBoundedLru> owner, std::uint64_t id,
             bool is_scratch, std::uint64_t bytes)
      : cache(std::move(owner)), pattern_id(id), scratch(is_scratch),
        scratch_bytes(bytes) {}
  ~LeaseOwner() noexcept {
    if (cache) cache->release(pattern_id, scratch, scratch_bytes);
  }
};

HardBoundedLru::HardBoundedLru(std::uint64_t cache_budget,
                               std::uint64_t scratch_budget)
    : cache_budget_(cache_budget),
      scratch_budget_(scratch_budget),
      sequence_(0),
      entries_(),
      stats_() {}

std::uint64_t HardBoundedLru::charged_bytes(std::uint64_t record_bytes,
                                            std::size_t retained_bytes) {
  // Two separately rounded reservations: record slab, then exact key and all
  // fixed metadata (entry object, verified flag, pin count, links, allocator
  // allowance). This is deliberately conservative and deterministic.
  const std::uint64_t metadata = checked_add<std::uint64_t>(
      static_cast<std::uint64_t>(retained_bytes), 8U + 96U + 1U + 16U + 16U + 15U,
      "LRU metadata charge");
  return checked_add<std::uint64_t>(align64(record_bytes), align64(metadata),
                                    "LRU entry charge");
}

void HardBoundedLru::assert_bounds() const {
  if (stats_.charged_cache_bytes > cache_budget_ ||
      stats_.active_scratch_bytes > scratch_budget_) {
    fail(ErrorCode::internal_failure, "LRU hard budget invariant was exceeded");
  }
}

LruLease HardBoundedLru::acquire(
    std::uint64_t pattern_id, const std::vector<std::uint8_t>& retained,
    std::uint64_t record_bytes, const Loader& loader) {
  std::unique_lock<std::mutex> lock(mutex_);
  if (sequence_ == std::numeric_limits<std::uint64_t>::max()) {
    fail(ErrorCode::memory_budget, "LRU request sequence overflow");
  }
  ++sequence_;
  auto found = entries_.find(pattern_id);
  if (found != entries_.end()) {
    if (found->second.retained != retained) {
      fail(ErrorCode::pattern_mismatch, "LRU key retained bits mismatch");
    }
    increment_counter(stats_.hits, "LRU hit counter");
    increment_counter(found->second.pins, "LRU pin counter");
    found->second.last_use = sequence_;
    auto owner = std::make_shared<LeaseOwner>(shared_from_this(), pattern_id,
                                              false, 0);
    return LruLease{std::static_pointer_cast<const void>(owner),
                    found->second.record, false};
  }
  increment_counter(stats_.misses, "LRU miss counter");
  const std::uint64_t charge = charged_bytes(record_bytes, retained.size());
  if (charge > cache_budget_) {
    if (record_bytes > scratch_budget_) {
      fail(ErrorCode::memory_budget,
           "record exceeds cache and single-plan scratch budgets");
    }
    if (stats_.active_scratch_bytes != 0) {
      increment_counter(stats_.pin_failures, "LRU pin-failure counter");
      fail(ErrorCode::memory_budget, "single-plan scratch is already pinned");
    }
    stats_.active_scratch_bytes = record_bytes;
    stats_.scratch_high_water = std::max(stats_.scratch_high_water, record_bytes);
    increment_counter(stats_.oversized_bypasses,
                      "LRU oversized-bypass counter");
    lock.unlock();
    std::shared_ptr<const std::vector<std::uint8_t>> record;
    try {
      record = loader();
      if (!record || record->size() != record_bytes) {
        fail(ErrorCode::io_failure, "scratch loader returned wrong record bytes");
      }
    } catch (...) {
      std::lock_guard<std::mutex> restore(mutex_);
      stats_.active_scratch_bytes = 0;
      throw;
    }
    auto owner = std::make_shared<LeaseOwner>(shared_from_this(), pattern_id,
                                              true, record_bytes);
    return LruLease{std::static_pointer_cast<const void>(owner), record, true};
  }

  while (stats_.charged_cache_bytes > cache_budget_ - charge) {
    auto victim = entries_.end();
    for (auto candidate = entries_.begin(); candidate != entries_.end();
         ++candidate) {
      if (candidate->second.pins != 0) continue;
      if (victim == entries_.end() ||
          candidate->second.last_use < victim->second.last_use ||
          (candidate->second.last_use == victim->second.last_use &&
           candidate->first < victim->first)) {
        victim = candidate;
      }
    }
    if (victim == entries_.end()) {
      increment_counter(stats_.pin_failures, "LRU pin-failure counter");
      fail(ErrorCode::memory_budget,
           "all eviction candidates are pinned under the hard budget");
    }
    stats_.charged_cache_bytes -= victim->second.charge;
    entries_.erase(victim);
    increment_counter(stats_.evictions, "LRU eviction counter");
  }
  lock.unlock();
  const auto record = loader();
  if (!record || record->size() != record_bytes) {
    fail(ErrorCode::io_failure, "cache loader returned wrong record bytes");
  }
  lock.lock();
  if (entries_.count(pattern_id) != 0) {
    fail(ErrorCode::internal_failure,
         "concurrent duplicate LRU insertion is unsupported in ENGINE002");
  }
  Entry entry;
  entry.retained = retained;
  entry.record = record;
  entry.charge = charge;
  entry.last_use = sequence_;
  entry.pins = 1;
  entries_.emplace(pattern_id, std::move(entry));
  stats_.charged_cache_bytes += charge;
  stats_.cache_high_water =
      std::max(stats_.cache_high_water, stats_.charged_cache_bytes);
  increment_counter(stats_.insertions, "LRU insertion counter");
  assert_bounds();
  auto owner = std::make_shared<LeaseOwner>(shared_from_this(), pattern_id,
                                            false, 0);
  return LruLease{std::static_pointer_cast<const void>(owner), record, false};
}

void HardBoundedLru::release(std::uint64_t pattern_id, bool scratch,
                             std::uint64_t scratch_bytes) noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  if (scratch) {
    if (stats_.active_scratch_bytes == scratch_bytes) {
      stats_.active_scratch_bytes = 0;
    }
    return;
  }
  const auto found = entries_.find(pattern_id);
  if (found != entries_.end() && found->second.pins != 0) {
    --found->second.pins;
  }
}

LruStats HardBoundedLru::stats() const noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  return stats_;
}

void HardBoundedLru::clear() {
  std::lock_guard<std::mutex> lock(mutex_);
  for (const auto& item : entries_) {
    if (item.second.pins != 0) {
      fail(ErrorCode::store_busy, "LRU cache has active pins");
    }
  }
  if (stats_.active_scratch_bytes != 0) {
    fail(ErrorCode::store_busy, "LRU scratch has an active pin");
  }
  entries_.clear();
  stats_.charged_cache_bytes = 0;
  assert_bounds();
}

}  // namespace engine002
}  // namespace splitaligner
