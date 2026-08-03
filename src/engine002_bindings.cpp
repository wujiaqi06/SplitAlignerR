#include <Rcpp.h>

#include "engine002_endian.h"
#include "engine002_atomic_publish.h"
#include "engine002_checked_math.h"
#include "engine002_disk_store.h"
#include "engine002_errors.h"
#include "engine002_hash.h"
#include "engine002_plan_codec.h"
#include "engine002_species_authority_binding.h"
#include "engine002_store.h"

#include <array>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

using splitaligner::engine002::DecodedPlan;
using splitaligner::engine002::EngineError;
using splitaligner::engine002::ErrorCode;
using splitaligner::engine002::PlanInput;
using splitaligner::engine002::Sha256;
using splitaligner::engine002::SpeciesAuthorityPtr;
using splitaligner::engine002::TruthPlanView;

namespace {

constexpr std::uint64_t kAuthorityMagic = UINT64_C(0x5341453241555448);
constexpr std::uint64_t kStoreMagic = UINT64_C(0x5341453253544f52);
constexpr std::uint64_t kPinMagic = UINT64_C(0x5341453250494e30);
constexpr std::uint32_t kAbiMajor = 1;

struct AuthorityHandle {
  std::uint64_t magic = kAuthorityMagic;
  std::uint32_t abi_major = kAbiMajor;
  std::uint64_t generation = 1;
  bool open = true;
  SpeciesAuthorityPtr authority;

  explicit AuthorityHandle(SpeciesAuthorityPtr value)
      : authority(std::move(value)) {}

  void close() noexcept {
    if (!open) return;
    open = false;
    ++generation;
    authority.reset();
  }

  ~AuthorityHandle() noexcept { close(); }
};

struct StoreHandle {
  std::uint64_t magic = kStoreMagic;
  std::uint32_t abi_major = kAbiMajor;
  std::uint64_t generation = 1;
  bool open = true;
  std::shared_ptr<splitaligner::engine002::PackedMemoryStore> memory;
  std::shared_ptr<splitaligner::engine002::PackedDiskStore> disk;

  void close_noexcept() noexcept {
    if (!open) return;
    try {
      if (memory) memory->close();
      if (disk) disk->close();
    } catch (...) {
      // Finalizers are no-throw. Active pin owners retain their shared backing.
    }
    open = false;
    ++generation;
    memory.reset();
    disk.reset();
  }
  ~StoreHandle() noexcept { close_noexcept(); }
};

struct PinHandle {
  std::uint64_t magic = kPinMagic;
  std::uint32_t abi_major = kAbiMajor;
  std::shared_ptr<const void> owner;
  explicit PinHandle(std::shared_ptr<const void> value)
      : owner(std::move(value)) {}
  void release() noexcept { owner.reset(); }
  ~PinHandle() noexcept { release(); }
};

template <typename Function>
auto translate_engine_errors(Function&& function) -> decltype(function()) {
  try {
    return function();
  } catch (const EngineError& error) {
    Rcpp::stop("[%s] %s",
               splitaligner::engine002::error_code_name(error.code()),
               error.what());
  } catch (const std::bad_alloc&) {
    Rcpp::stop("[ENGINE_ALLOCATION_FAILURE] native allocation failed");
  } catch (const std::exception& error) {
    Rcpp::stop("[ENGINE_INTERNAL_FAILURE] %s", error.what());
  } catch (...) {
    Rcpp::stop("[ENGINE_INTERNAL_FAILURE] unknown native exception");
  }
}

std::vector<std::uint8_t> as_bytes(const Rcpp::RawVector& value) {
  return std::vector<std::uint8_t>(value.begin(), value.end());
}

Rcpp::RawVector as_raw(const std::vector<std::uint8_t>& value) {
  return Rcpp::RawVector(value.begin(), value.end());
}

std::string u64_hex(std::uint64_t value) {
  std::ostringstream stream;
  stream << std::hex << std::setfill('0') << std::setw(16) << value;
  return stream.str();
}

AuthorityHandle& authority_handle(SEXP pointer) {
  if (TYPEOF(pointer) != EXTPTRSXP) {
    splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                  "authority handle is not an external pointer");
  }
  Rcpp::XPtr<AuthorityHandle> handle(pointer);
  if (handle.get() == nullptr || handle->magic != kAuthorityMagic ||
      handle->abi_major != kAbiMajor) {
    splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                  "authority handle type or ABI is invalid");
  }
  if (!handle->open || !handle->authority) {
    splitaligner::engine002::fail(ErrorCode::context_closed,
                                  "authority context is closed");
  }
  return *handle;
}

StoreHandle& store_handle(SEXP pointer) {
  if (TYPEOF(pointer) != EXTPTRSXP) {
    splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                  "store handle is not an external pointer");
  }
  Rcpp::XPtr<StoreHandle> handle(pointer);
  if (handle.get() == nullptr || handle->magic != kStoreMagic ||
      handle->abi_major != kAbiMajor) {
    splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                  "store handle type or ABI is invalid");
  }
  if (!handle->open || (!handle->memory && !handle->disk)) {
    splitaligner::engine002::fail(ErrorCode::context_closed,
                                  "store context is closed");
  }
  return *handle;
}

std::uint64_t exact_u64(double value, const char* context) {
  if (!R_finite(value) || value < 0 || value > 9007199254740991.0 ||
      std::floor(value) != value) {
    splitaligner::engine002::fail(
        ErrorCode::invalid_argument,
        std::string(context) + " is not an exact nonnegative R integer");
  }
  return static_cast<std::uint64_t>(value);
}

const char* store_state_name(splitaligner::engine002::StoreState state) {
  using splitaligner::engine002::StoreState;
  switch (state) {
    case StoreState::building: return "BUILDING";
    case StoreState::finalized: return "FINALIZED";
    case StoreState::open_validated: return "OPEN_VALIDATED";
    case StoreState::closed: return "CLOSED";
  }
  return "CLOSED";
}

Rcpp::List decoded_to_list(const DecodedPlan& decoded) {
  Rcpp::IntegerVector states(decoded.states.begin(), decoded.states.end());
  Rcpp::List queries(decoded.primitive_queries.size());
  for (std::size_t i = 0; i < decoded.primitive_queries.size(); ++i) {
    if (decoded.states[i] == 1U) {
      queries[i] = R_NilValue;
    } else {
      queries[i] = as_raw(decoded.primitive_queries[i]);
    }
  }
  Rcpp::IntegerVector eligible(decoded.eligible_primitives.size());
  for (std::size_t i = 0; i < decoded.eligible_primitives.size(); ++i) {
    eligible[i] = static_cast<int>(decoded.eligible_primitives[i]);
  }
  Rcpp::List fibers(decoded.fibers.size());
  Rcpp::List fiber_queries(decoded.fiber_queries.size());
  for (std::size_t i = 0; i < decoded.fibers.size(); ++i) {
    Rcpp::IntegerVector members(decoded.fibers[i].size());
    for (std::size_t j = 0; j < decoded.fibers[i].size(); ++j) {
      members[j] = static_cast<int>(decoded.fibers[i][j]);
    }
    fibers[i] = members;
    fiber_queries[i] = as_raw(decoded.fiber_queries[i]);
  }
  return Rcpp::List::create(
      Rcpp::_["pattern_id"] = static_cast<double>(decoded.pattern_id),
      Rcpp::_["retained"] = as_raw(decoded.retained),
      Rcpp::_["states"] = states,
      Rcpp::_["primitive_queries"] = queries,
      Rcpp::_["eligible_primitives"] = eligible,
      Rcpp::_["fibers"] = fibers,
      Rcpp::_["fiber_queries"] = fiber_queries,
      Rcpp::_["retained_pattern_sha256"] =
          splitaligner::engine002::hex_lower(decoded.retained_pattern_sha256),
      Rcpp::_["species_authority_sha256"] =
          splitaligner::engine002::hex_lower(decoded.species_authority_sha256),
      Rcpp::_["payload_xxh64"] = u64_hex(decoded.payload_xxh64),
      Rcpp::_["header_xxh64"] = u64_hex(decoded.header_xxh64),
      Rcpp::_["record_xxh64"] = u64_hex(decoded.record_xxh64));
}

PlanInput plan_input_from_r(double pattern_id,
                            const Rcpp::RawVector& retained,
                            const Rcpp::IntegerVector& states,
                            const Rcpp::List& queries,
                            std::uint32_t primitive_count) {
  if (!R_finite(pattern_id) || pattern_id < 0 ||
      pattern_id > 9007199254740991.0 || std::floor(pattern_id) != pattern_id) {
    splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                  "pattern ID is not an exact nonnegative integer");
  }
  if (states.size() != primitive_count || queries.size() != primitive_count) {
    splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                  "plan arrays differ from primitive count");
  }
  PlanInput input;
  input.pattern_id = static_cast<std::uint64_t>(pattern_id);
  input.retained = as_bytes(retained);
  input.states.resize(primitive_count);
  input.primitive_queries.resize(primitive_count);
  for (std::uint32_t i = 0; i < primitive_count; ++i) {
    if (Rcpp::IntegerVector::is_na(states[i]) || states[i] < 0 || states[i] > 3) {
      splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                    "state vector contains an invalid value");
    }
    input.states[i] = static_cast<std::uint8_t>(states[i]);
    SEXP query = queries[i];
    if (Rf_isNull(query)) continue;
    if (TYPEOF(query) != RAWSXP) {
      splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                    "primitive query is not raw or NULL");
    }
    input.primitive_queries[i] = as_bytes(Rcpp::RawVector(query));
  }
  return input;
}

}  // namespace

// [[Rcpp::export]]
SEXP cpp_engine002_authority_create(Rcpp::CharacterVector taxon_labels,
                                    Rcpp::IntegerVector terminal_taxon_ids,
                                    Rcpp::List primitive_splits) {
  return translate_engine_errors([&]() -> SEXP {
    std::vector<std::string> labels;
    labels.reserve(taxon_labels.size());
    for (R_xlen_t i = 0; i < taxon_labels.size(); ++i) {
      if (Rcpp::CharacterVector::is_na(taxon_labels[i])) {
        splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                      "authority label is missing");
      }
      labels.push_back(Rcpp::as<std::string>(taxon_labels[i]));
    }
    if (terminal_taxon_ids.size() != primitive_splits.size()) {
      splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                    "authority primitive axes differ");
    }
    std::vector<std::uint32_t> terminal_ids(terminal_taxon_ids.size());
    std::vector<std::vector<std::uint8_t>> splits(primitive_splits.size());
    for (R_xlen_t i = 0; i < terminal_taxon_ids.size(); ++i) {
      if (Rcpp::IntegerVector::is_na(terminal_taxon_ids[i])) {
        terminal_ids[i] = splitaligner::engine002::kInternalTaxon;
      } else if (terminal_taxon_ids[i] < 0) {
        splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                      "terminal taxon ID is negative");
      } else {
        terminal_ids[i] = static_cast<std::uint32_t>(terminal_taxon_ids[i]);
      }
      SEXP split = primitive_splits[i];
      if (TYPEOF(split) != RAWSXP) {
        splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                      "authority primitive split is not raw");
      }
      splits[i] = as_bytes(Rcpp::RawVector(split));
    }
    auto authority = splitaligner::engine002::make_species_authority(
        labels, terminal_ids, splits);
    Rcpp::XPtr<AuthorityHandle> pointer(new AuthorityHandle(authority), true);
    return pointer;
  });
}

// [[Rcpp::export]]
Rcpp::List cpp_engine002_authority_info(SEXP authority_pointer) {
  return translate_engine_errors([&]() {
    const auto& handle = authority_handle(authority_pointer);
    return Rcpp::List::create(
        Rcpp::_["global_taxon_count"] = handle.authority->global_taxon_count,
        Rcpp::_["primitive_count"] = handle.authority->primitive_count,
        Rcpp::_["fingerprint"] =
            splitaligner::engine002::hex_lower(handle.authority->fingerprint),
        Rcpp::_["generation"] = static_cast<double>(handle.generation),
        Rcpp::_["open"] = handle.open);
  });
}

// [[Rcpp::export]]
bool cpp_engine002_authority_close(SEXP authority_pointer) {
  return translate_engine_errors([&]() {
    if (TYPEOF(authority_pointer) != EXTPTRSXP) {
      splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                    "authority handle is not an external pointer");
    }
    Rcpp::XPtr<AuthorityHandle> handle(authority_pointer);
    if (handle.get() == nullptr || handle->magic != kAuthorityMagic ||
        handle->abi_major != kAbiMajor) {
      splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                    "authority handle type or ABI is invalid");
    }
    handle->close();
    return true;
  });
}

// [[Rcpp::export]]
Rcpp::RawVector cpp_engine002_plan_encode(SEXP authority_pointer,
                                           double pattern_id,
                                           Rcpp::RawVector retained,
                                           Rcpp::IntegerVector states,
                                           Rcpp::List primitive_queries) {
  return translate_engine_errors([&]() {
    const auto& handle = authority_handle(authority_pointer);
    const auto input = plan_input_from_r(
        pattern_id, retained, states, primitive_queries,
        handle.authority->primitive_count);
    return as_raw(splitaligner::engine002::encode_plan_record(
        *handle.authority, input));
  });
}

// [[Rcpp::export]]
Rcpp::List cpp_engine002_plan_decode(SEXP authority_pointer,
                                     Rcpp::RawVector record) {
  return translate_engine_errors([&]() {
    const auto& handle = authority_handle(authority_pointer);
    return decoded_to_list(splitaligner::engine002::decode_plan_record(
        *handle.authority, as_bytes(record)));
  });
}

// [[Rcpp::export]]
Rcpp::List cpp_engine002_plan_view_snapshot(SEXP authority_pointer,
                                            Rcpp::RawVector record) {
  return translate_engine_errors([&]() {
    const auto& handle = authority_handle(authority_pointer);
    auto owner = std::make_shared<const std::vector<std::uint8_t>>(
        as_bytes(record));
    TruthPlanView view(handle.authority, owner, handle.generation);
    return decoded_to_list(view.snapshot());
  });
}

// [[Rcpp::export]]
Rcpp::List cpp_engine002_plan_view_probe(SEXP authority_pointer,
                                         Rcpp::RawVector record,
                                         Rcpp::IntegerVector primitive_ids,
                                         int repeats) {
  return translate_engine_errors([&]() {
    if (repeats < 1) {
      splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                    "view probe repeats must be positive");
    }
    const auto& handle = authority_handle(authority_pointer);
    auto owner = std::make_shared<const std::vector<std::uint8_t>>(
        as_bytes(record));
    TruthPlanView view(handle.authority, owner, handle.generation);
    std::uint64_t query_bytes = 0;
    std::uint64_t state_sum = 0;
    for (int iteration = 0; iteration < repeats; ++iteration) {
      for (int primitive : primitive_ids) {
        if (primitive < 0) {
          splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                        "view probe primitive ID is negative");
        }
        const auto id = static_cast<std::uint32_t>(primitive);
        const std::uint8_t state = view.state(id);
        state_sum = splitaligner::engine002::checked_add<std::uint64_t>(
            state_sum, state, "view-probe state checksum");
        if (state != 1U) {
          query_bytes = splitaligner::engine002::checked_add<std::uint64_t>(
              query_bytes, view.primitive_query(id).size(),
              "view-probe query bytes");
        }
      }
    }
    return Rcpp::List::create(
        Rcpp::_["pattern_id"] = static_cast<double>(view.pattern_id()),
        Rcpp::_["state_sum"] = static_cast<double>(state_sum),
        Rcpp::_["query_bytes"] = static_cast<double>(query_bytes));
  });
}

// [[Rcpp::export]]
Rcpp::List cpp_engine002_hash_reference_vectors() {
  return translate_engine_errors([&]() {
    const std::vector<std::string> values = {"", "a", "abc"};
    Rcpp::CharacterVector input(values.size());
    Rcpp::CharacterVector xxhash64(values.size());
    Rcpp::CharacterVector sha256(values.size());
    for (std::size_t i = 0; i < values.size(); ++i) {
      const auto* bytes = reinterpret_cast<const std::uint8_t*>(values[i].data());
      input[i] = values[i];
      xxhash64[i] = u64_hex(splitaligner::engine002::xxh64(
          bytes, values[i].size(), 0));
      sha256[i] = splitaligner::engine002::hex_lower(
          splitaligner::engine002::sha256(bytes, values[i].size()));
    }
    return Rcpp::List::create(
        Rcpp::_["input"] = input,
        Rcpp::_["xxhash64_seed0"] = xxhash64,
        Rcpp::_["sha256"] = sha256,
        Rcpp::_["truth_semantics_sha256"] =
            splitaligner::engine002::hex_lower(
                splitaligner::engine002::truth_semantics_fingerprint()));
  });
}

// [[Rcpp::export]]
SEXP cpp_engine002_memory_store_create(SEXP authority_pointer,
                                       double pattern_count) {
  return translate_engine_errors([&]() -> SEXP {
    const auto& authority = authority_handle(authority_pointer);
    auto store = std::make_shared<splitaligner::engine002::PackedMemoryStore>(
        authority.authority, exact_u64(pattern_count, "pattern_count"));
    auto* handle = new StoreHandle();
    handle->memory = std::move(store);
    Rcpp::XPtr<StoreHandle> pointer(handle, true);
    return pointer;
  });
}

// [[Rcpp::export]]
SEXP cpp_engine002_disk_store_create(
    SEXP authority_pointer, double pattern_count, double cache_budget,
    double scratch_budget, double index_budget, double metadata_budget,
    double combined_runtime_bound) {
  return translate_engine_errors([&]() -> SEXP {
    const auto& authority = authority_handle(authority_pointer);
    auto store = std::make_shared<splitaligner::engine002::PackedDiskStore>(
        authority.authority, exact_u64(pattern_count, "pattern_count"),
        exact_u64(cache_budget, "cache_budget"),
        exact_u64(scratch_budget, "scratch_budget"),
        exact_u64(index_budget, "index_budget"),
        exact_u64(metadata_budget, "metadata_budget"),
        exact_u64(combined_runtime_bound, "combined_runtime_bound"));
    auto* handle = new StoreHandle();
    handle->disk = std::move(store);
    Rcpp::XPtr<StoreHandle> pointer(handle, true);
    return pointer;
  });
}

// [[Rcpp::export]]
SEXP cpp_engine002_disk_store_open(
    SEXP authority_pointer, std::string manifest_path, double cache_budget,
    double scratch_budget, double index_budget, double metadata_budget,
    double combined_runtime_bound) {
  return translate_engine_errors([&]() -> SEXP {
    const auto& authority = authority_handle(authority_pointer);
    auto store = splitaligner::engine002::PackedDiskStore::open_existing(
        authority.authority, std::filesystem::path(manifest_path),
        exact_u64(cache_budget, "cache_budget"),
        exact_u64(scratch_budget, "scratch_budget"),
        exact_u64(index_budget, "index_budget"),
        exact_u64(metadata_budget, "metadata_budget"),
        exact_u64(combined_runtime_bound, "combined_runtime_bound"));
    auto* handle = new StoreHandle();
    handle->disk = std::move(store);
    Rcpp::XPtr<StoreHandle> pointer(handle, true);
    return pointer;
  });
}

// [[Rcpp::export]]
bool cpp_engine002_store_insert(SEXP store_pointer, Rcpp::RawVector record) {
  return translate_engine_errors([&]() {
    auto& handle = store_handle(store_pointer);
    auto owner = std::make_shared<const std::vector<std::uint8_t>>(
        as_bytes(record));
    if (handle.memory) handle.memory->insert(owner);
    else handle.disk->insert(owner);
    return true;
  });
}

// [[Rcpp::export]]
SEXP cpp_engine002_store_finalize(SEXP store_pointer,
                                  std::string directory,
                                  std::string run_store_id) {
  return translate_engine_errors([&]() -> SEXP {
    auto& handle = store_handle(store_pointer);
    if (handle.memory) {
      handle.memory->finalize();
      return Rcpp::wrap(true);
    }
    return Rcpp::wrap(handle.disk->finalize_publish(
        std::filesystem::path(directory), run_store_id).string());
  });
}

// [[Rcpp::export]]
Rcpp::List cpp_engine002_store_lookup_snapshot(SEXP store_pointer,
                                               double pattern_id,
                                               Rcpp::RawVector retained) {
  return translate_engine_errors([&]() {
    auto& handle = store_handle(store_pointer);
    const std::uint64_t id = exact_u64(pattern_id, "pattern_id");
    const auto exact = as_bytes(retained);
    const DecodedPlan decoded = handle.memory
        ? handle.memory->lookup_snapshot(id, exact)
        : handle.disk->lookup_snapshot(id, exact);
    return decoded_to_list(decoded);
  });
}

// [[Rcpp::export]]
SEXP cpp_engine002_store_debug_pin(SEXP store_pointer, double pattern_id,
                                   Rcpp::RawVector retained) {
  return translate_engine_errors([&]() -> SEXP {
    auto& handle = store_handle(store_pointer);
    const std::uint64_t id = exact_u64(pattern_id, "pattern_id");
    const auto exact = as_bytes(retained);
    auto owner = handle.memory ? handle.memory->debug_pin(id, exact)
                               : handle.disk->debug_pin(id, exact);
    Rcpp::XPtr<PinHandle> pointer(new PinHandle(std::move(owner)), true);
    return pointer;
  });
}

// [[Rcpp::export]]
bool cpp_engine002_pin_release(SEXP pin_pointer) {
  return translate_engine_errors([&]() {
    if (TYPEOF(pin_pointer) != EXTPTRSXP) {
      splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                    "pin handle is not an external pointer");
    }
    Rcpp::XPtr<PinHandle> pin(pin_pointer);
    if (pin.get() == nullptr || pin->magic != kPinMagic ||
        pin->abi_major != kAbiMajor) {
      splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                    "pin handle type or ABI is invalid");
    }
    pin->release();
    return true;
  });
}

// [[Rcpp::export]]
Rcpp::List cpp_engine002_store_stats(SEXP store_pointer) {
  return translate_engine_errors([&]() {
    auto& handle = store_handle(store_pointer);
    if (handle.memory) {
      const auto stats = handle.memory->stats();
      return Rcpp::List::create(
          Rcpp::_["backend"] = "memory",
          Rcpp::_["state"] = store_state_name(handle.memory->state()),
          Rcpp::_["generation"] = static_cast<double>(stats.generation),
          Rcpp::_["inserted"] = static_cast<double>(stats.inserted),
          Rcpp::_["lookups"] = static_cast<double>(stats.lookups),
          Rcpp::_["active_pins"] = static_cast<double>(stats.active_pins),
          Rcpp::_["arena_bytes"] = static_cast<double>(stats.arena_bytes));
    }
    const auto stats = handle.disk->stats();
    const auto& lru = stats.lru;
    return Rcpp::List::create(
        Rcpp::_["backend"] = "disk",
        Rcpp::_["state"] = store_state_name(handle.disk->state()),
        Rcpp::_["generation"] = static_cast<double>(stats.generation),
        Rcpp::_["pattern_count"] = static_cast<double>(stats.pattern_count),
        Rcpp::_["file_bytes"] = static_cast<double>(stats.file_bytes),
        Rcpp::_["index_charged_bytes"] =
            static_cast<double>(stats.index_charged_bytes),
        Rcpp::_["metadata_charged_bytes"] =
            static_cast<double>(stats.metadata_charged_bytes),
        Rcpp::_["combined_runtime_bound"] =
            static_cast<double>(stats.combined_runtime_bound),
        Rcpp::_["hits"] = static_cast<double>(lru.hits),
        Rcpp::_["misses"] = static_cast<double>(lru.misses),
        Rcpp::_["insertions"] = static_cast<double>(lru.insertions),
        Rcpp::_["evictions"] = static_cast<double>(lru.evictions),
        Rcpp::_["oversized_bypasses"] =
            static_cast<double>(lru.oversized_bypasses),
        Rcpp::_["pin_failures"] = static_cast<double>(lru.pin_failures),
        Rcpp::_["cache_high_water"] = static_cast<double>(lru.cache_high_water),
        Rcpp::_["scratch_high_water"] =
            static_cast<double>(lru.scratch_high_water),
        Rcpp::_["charged_cache_bytes"] =
            static_cast<double>(lru.charged_cache_bytes),
        Rcpp::_["active_scratch_bytes"] =
            static_cast<double>(lru.active_scratch_bytes));
  });
}

// [[Rcpp::export]]
bool cpp_engine002_store_close(SEXP store_pointer) {
  return translate_engine_errors([&]() {
    if (TYPEOF(store_pointer) != EXTPTRSXP) {
      splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                    "store handle is not an external pointer");
    }
    Rcpp::XPtr<StoreHandle> pointer(store_pointer);
    if (pointer.get() == nullptr || pointer->magic != kStoreMagic ||
        pointer->abi_major != kAbiMajor) {
      splitaligner::engine002::fail(ErrorCode::schema_mismatch,
                                    "store handle type or ABI is invalid");
    }
    auto& handle = *pointer;
    if (!handle.open) return true;
    if (handle.memory) handle.memory->close();
    else handle.disk->close();
    handle.open = false;
    ++handle.generation;
    handle.memory.reset();
    handle.disk.reset();
    return true;
  });
}

// [[Rcpp::export]]
bool cpp_engine002_set_publication_failpoint(int stage) {
  return translate_engine_errors([&]() {
    if (stage < 0 || stage > 15) {
      splitaligner::engine002::fail(ErrorCode::invalid_argument,
                                    "publication failpoint must be 0..15");
    }
    splitaligner::engine002::set_publication_failpoint(stage);
    return true;
  });
}
