#include "engine002_store.h"

#include "engine002_checked_math.h"
#include "engine002_errors.h"

#include <algorithm>

namespace splitaligner {
namespace engine002 {

PatternRegistryPtr make_pattern_registry(
    SpeciesAuthorityPtr authority,
    std::vector<std::vector<std::uint8_t>> retained_patterns) {
  if (!authority) {
    fail(ErrorCode::invalid_argument, "pattern registry requires authority");
  }
  if (retained_patterns.size() > static_cast<std::size_t>(UINT64_MAX)) {
    fail(ErrorCode::memory_budget, "pattern registry exceeds u64 count");
  }
  auto registry = std::make_shared<PatternRegistry>();
  registry->authority = std::move(authority);
  registry->pattern_sha256.reserve(retained_patterns.size());
  for (std::size_t i = 0; i < retained_patterns.size(); ++i) {
    const auto& retained = retained_patterns[i];
    if (i != 0 && !(retained_patterns[i - 1] < retained)) {
      fail(ErrorCode::pattern_mismatch,
           "pattern registry must be exact, unique, and canonical");
    }
    registry->pattern_sha256.push_back(retained_pattern_fingerprint(
        registry->authority->global_taxon_count, retained));
  }
  registry->pattern_registry_sha256 = pattern_registry_fingerprint(
      registry->authority->global_taxon_count, retained_patterns);
  registry->truth_semantics_sha256 = truth_semantics_fingerprint();
  registry->store_identity_sha256 = store_identity_fingerprint(
      registry->authority->fingerprint,
      registry->pattern_registry_sha256,
      registry->truth_semantics_sha256);
  registry->retained_patterns = std::move(retained_patterns);
  return registry;
}

StoreBuilder::StoreBuilder(SpeciesAuthorityPtr authority,
                           std::uint64_t expected_count)
    : authority_(std::move(authority)), expected_count_(expected_count),
      by_id_(),
      by_pattern_(0, ExactBytesHasher(FastHashDomain::retained_pattern)) {
  if (!authority_) fail(ErrorCode::invalid_argument, "store requires authority");
  if (expected_count_ > static_cast<std::uint64_t>(SIZE_MAX)) {
    fail(ErrorCode::memory_budget, "pattern count exceeds host size limit");
  }
}

void StoreBuilder::insert(
    std::shared_ptr<const std::vector<std::uint8_t>> record) {
  if (!record) fail(ErrorCode::invalid_argument, "cannot insert null record");
  const DecodedPlan decoded = decode_plan_record(*authority_, *record);
  if (decoded.pattern_id >= expected_count_) {
    fail(ErrorCode::pattern_mismatch, "record pattern ID is outside store range");
  }
  if (by_id_.count(decoded.pattern_id) != 0) {
    fail(ErrorCode::duplicate_record, "duplicate pattern ID insertion");
  }
  const auto duplicate = by_pattern_.find(decoded.retained);
  if (duplicate != by_pattern_.end()) {
    fail(ErrorCode::duplicate_pattern,
         "exact retained pattern already exists under another ID");
  }
  PlanRecordEntry entry;
  entry.pattern_id = decoded.pattern_id;
  entry.retained = decoded.retained;
  entry.pattern_sha256 = decoded.retained_pattern_sha256;
  entry.record = std::move(record);
  entry.record_xxh64 = decoded.record_xxh64;
  by_pattern_.emplace(entry.retained, entry.pattern_id);
  by_id_.emplace(entry.pattern_id, std::move(entry));
}

FinalizedPlanSet StoreBuilder::finalize() const {
  if (by_id_.size() != expected_count_) {
    fail(ErrorCode::pattern_mismatch,
         "store does not contain every contiguous pattern ID");
  }
  FinalizedPlanSet result;
  result.authority = authority_;
  result.records.reserve(by_id_.size());
  std::vector<std::vector<std::uint8_t>> patterns;
  patterns.reserve(by_id_.size());
  std::uint64_t expected_id = 0;
  for (const auto& item : by_id_) {
    if (item.first != expected_id) {
      fail(ErrorCode::pattern_mismatch, "store pattern IDs are not contiguous");
    }
    if (!patterns.empty() && !(patterns.back() < item.second.retained)) {
      fail(ErrorCode::pattern_mismatch,
           "pattern IDs do not follow exact retained-bitset sort order");
    }
    result.records.push_back(item.second);
    patterns.push_back(item.second.retained);
    ++expected_id;
  }
  result.pattern_registry_sha256 = pattern_registry_fingerprint(
      authority_->global_taxon_count, patterns);
  result.truth_semantics_sha256 = truth_semantics_fingerprint();
  result.store_identity_sha256 = store_identity_fingerprint(
      authority_->fingerprint, result.pattern_registry_sha256,
      result.truth_semantics_sha256);
  return result;
}

struct PackedMemoryStore::PinOwner {
  std::shared_ptr<PackedMemoryStore> store;
  std::shared_ptr<const std::vector<std::uint8_t>> arena;
  PinOwner(std::shared_ptr<PackedMemoryStore> value,
           std::shared_ptr<const std::vector<std::uint8_t>> bytes)
      : store(std::move(value)), arena(std::move(bytes)) {}
  ~PinOwner() noexcept {
    if (store) store->release_pin();
  }
};

PackedMemoryStore::PackedMemoryStore(SpeciesAuthorityPtr authority,
                                     std::uint64_t pattern_count)
    : authority_(std::move(authority)),
      constant_fast_hash_(constant_fast_hash_for_tests()),
      state_(StoreState::building),
      generation_(1),
      inserted_(0),
      lookups_(0),
      active_pins_(0),
      builder_(new StoreBuilder(authority_, pattern_count)),
      finalized_(),
      arena_(),
      index_() {}

void PackedMemoryStore::insert(
    std::shared_ptr<const std::vector<std::uint8_t>> record) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_ == StoreState::closed) {
    fail(ErrorCode::context_closed, "memory store is closed");
  }
  if (state_ != StoreState::building) {
    fail(ErrorCode::invalid_state, "insertion requires BUILDING state");
  }
  builder_->insert(std::move(record));
  inserted_ = checked_add<std::uint64_t>(inserted_, 1U,
                                         "memory-store insertion counter");
}

void PackedMemoryStore::finalize() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_ == StoreState::closed) {
    fail(ErrorCode::context_closed, "memory store is closed");
  }
  if (state_ == StoreState::finalized) return;
  if (state_ != StoreState::building) {
    fail(ErrorCode::invalid_state, "memory store cannot be finalized");
  }
  auto candidate = std::make_unique<FinalizedPlanSet>(builder_->finalize());
  std::uint64_t arena_bytes = 0;
  for (const auto& entry : candidate->records) {
    arena_bytes = checked_add<std::uint64_t>(
        arena_bytes, entry.record->size(), "memory arena bytes");
  }
  auto arena = std::make_shared<std::vector<std::uint8_t>>();
  arena->reserve(checked_size(arena_bytes, "memory arena"));
  std::vector<ArenaEntry> index;
  index.reserve(candidate->records.size());
  for (const auto& entry : candidate->records) {
    ArenaEntry target;
    target.offset = arena->size();
    target.bytes = entry.record->size();
    target.retained = entry.retained;
    target.pattern_sha256 = entry.pattern_sha256;
    target.lookup_fast_hash = fast_hash_bytes(
        FastHashDomain::memory_lookup, entry.retained, constant_fast_hash_);
    arena->insert(arena->end(), entry.record->begin(), entry.record->end());
    index.push_back(std::move(target));
  }
  finalized_ = std::move(candidate);
  arena_ = std::move(arena);
  index_ = std::move(index);
  builder_.reset();
  state_ = StoreState::finalized;
}

void PackedMemoryStore::require_open_immutable() const {
  if (state_ == StoreState::closed) {
    fail(ErrorCode::context_closed, "memory store is closed");
  }
  if (state_ != StoreState::finalized) {
    fail(ErrorCode::invalid_state, "lookup requires FINALIZED state");
  }
}

std::shared_ptr<PackedMemoryStore::PinOwner> PackedMemoryStore::acquire_pin(
    std::uint64_t pattern_id, const std::vector<std::uint8_t>& retained) {
  std::lock_guard<std::mutex> lock(mutex_);
  require_open_immutable();
  if (pattern_id >= index_.size()) {
    fail(ErrorCode::pattern_mismatch, "lookup pattern ID is out of range");
  }
  if (index_[pattern_id].lookup_fast_hash != fast_hash_bytes(
          FastHashDomain::memory_lookup, retained, constant_fast_hash_) ||
      index_[pattern_id].retained != retained) {
    fail(ErrorCode::pattern_mismatch,
         "lookup retained bits do not match pattern ID");
  }
  active_pins_ = checked_add<std::uint64_t>(
      active_pins_, 1U, "memory-store active-pin counter");
  lookups_ = checked_add<std::uint64_t>(lookups_, 1U,
                                        "memory-store lookup counter");
  return std::make_shared<PinOwner>(shared_from_this(), arena_);
}

void PackedMemoryStore::release_pin() noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  if (active_pins_ != 0) --active_pins_;
}

DecodedPlan PackedMemoryStore::lookup_snapshot(
    std::uint64_t pattern_id, const std::vector<std::uint8_t>& retained) {
  auto pin = acquire_pin(pattern_id, retained);
  ArenaEntry entry;
  std::uint64_t generation;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    entry = index_[pattern_id];
    generation = generation_;
  }
  TruthPlanView view(authority_, std::static_pointer_cast<const void>(pin),
                     pin->arena->data() + checked_size(entry.offset, "arena offset"),
                     checked_size(entry.bytes, "record bytes"), generation);
  return view.snapshot();
}

std::shared_ptr<const void> PackedMemoryStore::debug_pin(
    std::uint64_t pattern_id, const std::vector<std::uint8_t>& retained) {
  return std::static_pointer_cast<const void>(acquire_pin(pattern_id, retained));
}

void PackedMemoryStore::close() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_ == StoreState::closed) return;
  if (active_pins_ != 0) {
    fail(ErrorCode::store_busy, "memory store has active views");
  }
  state_ = StoreState::closed;
  ++generation_;
  builder_.reset();
  finalized_.reset();
  arena_.reset();
  index_.clear();
}

StoreState PackedMemoryStore::state() const noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  return state_;
}

MemoryStoreStats PackedMemoryStore::stats() const noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  MemoryStoreStats out;
  out.inserted = inserted_;
  out.lookups = lookups_;
  out.active_pins = active_pins_;
  out.generation = generation_;
  out.arena_bytes = arena_ ? arena_->size() : 0;
  return out;
}

}  // namespace engine002
}  // namespace splitaligner
