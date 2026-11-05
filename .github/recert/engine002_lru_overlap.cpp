// Run from the repository root:
// c++ -std=c++17 -pthread -Isrc .github/recert/engine002_lru_overlap.cpp \
//   src/engine002_{lru,fast_hash,hash}.cpp -o /tmp/engine002-lru && /tmp/engine002-lru
#include "engine002_errors.h"
#include "engine002_lru.h"

#include <future>
#include <iostream>
#include <stdexcept>

using namespace splitaligner::engine002;
using Bytes = std::vector<std::uint8_t>;

static void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

template <typename F>
static void require_error(ErrorCode code, F action, const char* message) {
  try {
    action();
  } catch (const EngineError& error) {
    if (error.code() == code) return;
    throw;
  }
  throw std::runtime_error(message);
}

int main() try {
  const Bytes key{1};
  const auto record = std::make_shared<const Bytes>(64, 0);
  const auto load = [&] { return record; };
  const auto charge = HardBoundedLru::charged_bytes(record->size(), key.size());
  auto cache = std::make_shared<HardBoundedLru>(charge, 0);

  // Start the competing calls from within the first loader. Its reservation
  // stays live until both calls finish, with no dependence on timing or sleep.
  auto first = cache->acquire(1, key, record->size(), [&] {
    std::async(std::launch::async, [&] {
      require_error(ErrorCode::memory_budget, [&] {
        cache->acquire(2, key, record->size(), load);
      }, "a second load spent the reserved cache bytes");
      require_error(ErrorCode::store_busy, [&] { cache->clear(); },
                    "clear discarded an active reservation");
    }).get();
    return record;
  });
  require(cache->stats().cache_high_water == charge, "high-water exceeds budget");
  first.owner.reset();
  cache->clear();

  require_error(ErrorCode::io_failure, [&] {
    cache->acquire(2, key, record->size(), [] {
      return std::shared_ptr<const Bytes>{};
    });
  }, "bad loader succeeded");
  require(cache->stats().charged_cache_bytes == 0, "bad loader leaked its reservation");
  cache->acquire(2, key, record->size(), load);
  cache->clear();

  // Two overlapping loads for the same key each fit. The losing insert must
  // release only its own reservation and leave the winner's pin intact.
  cache = std::make_shared<HardBoundedLru>(2 * charge, 0);
  LruLease winner;
  require_error(ErrorCode::internal_failure, [&] {
    cache->acquire(3, key, record->size(), [&] {
      winner = std::async(std::launch::async, [&] {
        return cache->acquire(3, key, record->size(), load);
      }).get();
      return record;
    });
  }, "duplicate insertion succeeded");
  require(cache->stats().charged_cache_bytes == charge, "duplicate charge leaked");
  require_error(ErrorCode::store_busy, [&] { cache->clear(); },
                "duplicate rollback released the winner's pin");
  winner.owner.reset();
  cache->clear();
  require(cache->stats().charged_cache_bytes == 0, "cache did not drain");
  std::cout << "Concurrent ENGINE002 cache reservations and rollback passed\n";
  return 0;
} catch (const std::exception& error) {
  std::cerr << error.what() << '\n';
  return 1;
}
