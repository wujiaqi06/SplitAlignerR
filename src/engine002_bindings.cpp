#include <Rcpp.h>

#include "engine002_endian.hpp"
#include "engine002_errors.hpp"
#include "engine002_hash.hpp"
#include "engine002_plan_codec.hpp"
#include "engine002_species_authority_binding.hpp"

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
    return decoded_to_list(view.decoded());
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
