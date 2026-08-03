#include "engine002_plan_codec.hpp"

#include "engine002_checked_math.hpp"
#include "engine002_endian.hpp"
#include "engine002_errors.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <string>

namespace splitaligner {
namespace engine002 {
namespace {

struct EncodedQuery {
  std::vector<std::uint8_t> dense;
  std::vector<std::uint8_t> wire;
};

std::vector<std::uint8_t> pack_states(const std::vector<std::uint8_t>& states) {
  std::vector<std::uint8_t> packed(ceil_div_u32(
      checked_u32(states.size(), "primitive states"), 4U), 0);
  for (std::size_t i = 0; i < states.size(); ++i) {
    if (states[i] > 2U) {
      fail(ErrorCode::scientific_invariant,
           "truth state must be 0, 1, or 2");
    }
    packed[i / 4U] |= static_cast<std::uint8_t>(states[i] << (2U * (i % 4U)));
  }
  return packed;
}

std::vector<std::uint8_t> unpack_states(const std::uint8_t* packed,
                                        std::uint32_t primitive_count,
                                        std::uint32_t state_bytes) {
  if (state_bytes != ceil_div_u32(primitive_count, 4U)) {
    fail(ErrorCode::store_corrupt, "state byte count is not canonical");
  }
  std::vector<std::uint8_t> states(primitive_count);
  for (std::uint32_t i = 0; i < primitive_count; ++i) {
    const std::uint8_t state =
        static_cast<std::uint8_t>((packed[i / 4U] >> (2U * (i % 4U))) & 3U);
    if (state == 3U) {
      fail(ErrorCode::scientific_invariant,
           "state code 3 is invalid in a truth plan");
    }
    states[i] = state;
  }
  if (state_bytes != 0 && primitive_count % 4U != 0) {
    const unsigned used = 2U * (primitive_count % 4U);
    const std::uint8_t allowed = static_cast<std::uint8_t>((1U << used) - 1U);
    if ((packed[state_bytes - 1U] & static_cast<std::uint8_t>(~allowed)) != 0) {
      fail(ErrorCode::store_corrupt, "state vector has nonzero padding bits");
    }
  }
  return states;
}

void validate_terminal_states(const SpeciesAuthority& authority,
                              const std::vector<std::uint8_t>& retained,
                              const std::vector<std::uint8_t>& states) {
  for (std::uint32_t primitive = 0; primitive < authority.primitive_count;
       ++primitive) {
    const std::uint32_t taxon = authority.terminal_taxon_ids[primitive];
    if (taxon == kInternalTaxon) continue;
    const bool is_retained = bit_is_set(retained.data(), taxon);
    if (is_retained && states[primitive] == 1U) {
      fail(ErrorCode::scientific_invariant,
           "retained terminal primitive cannot be NA_struct");
    }
    if (!is_retained && states[primitive] != 1U) {
      fail(ErrorCode::scientific_invariant,
           "missing terminal primitive must be NA_struct");
    }
  }
}

EncodedQuery encode_query(const std::vector<std::uint8_t>& dense,
                          const std::vector<std::uint8_t>& retained,
                          std::uint32_t taxon_count) {
  validate_canonical_query(dense, retained, taxon_count, "plan query");
  const std::uint32_t selected_count =
      popcount_bytes(dense.data(), dense.size());
  const std::uint64_t sparse_bytes64 =
      checked_mul<std::uint64_t>(selected_count, 4U, "sparse query bytes");
  const bool sparse = sparse_bytes64 < dense.size();

  EncodedQuery result;
  result.dense = dense;
  result.wire.resize(12, 0);
  result.wire[0] = sparse ? 2U : 1U;
  store_u32_le(result.wire.data() + 4, selected_count);
  if (sparse) {
    const std::uint32_t payload_bytes =
        checked_u32(sparse_bytes64, "sparse query bytes");
    store_u32_le(result.wire.data() + 8, payload_bytes);
    result.wire.reserve(checked_add<std::size_t>(12, payload_bytes,
                                                "query entry bytes"));
    for (std::uint32_t taxon = 0; taxon < taxon_count; ++taxon) {
      if (bit_is_set(dense.data(), taxon)) append_u32_le(result.wire, taxon);
    }
  } else {
    store_u32_le(result.wire.data() + 8,
                 checked_u32(dense.size(), "dense query bytes"));
    append_bytes(result.wire, dense.data(), dense.size());
  }
  return result;
}

struct ParsedQuery {
  std::vector<std::uint8_t> dense;
  std::size_t wire_offset = 0;
  std::size_t wire_bytes = 0;
};

ParsedQuery parse_query(const std::uint8_t* entry, std::size_t entry_bytes,
                        const std::vector<std::uint8_t>& retained,
                        std::uint32_t taxon_count) {
  if (entry_bytes < 12) {
    fail(ErrorCode::store_corrupt, "query entry is truncated");
  }
  const std::uint8_t encoding = entry[0];
  if (entry[1] != 0 || entry[2] != 0 || entry[3] != 0) {
    fail(ErrorCode::store_corrupt, "query entry reserved bytes are nonzero");
  }
  const std::uint32_t selected_count = load_u32_le(entry + 4);
  const std::uint32_t payload_bytes = load_u32_le(entry + 8);
  if (entry_bytes != checked_add<std::size_t>(12, payload_bytes,
                                             "query entry length")) {
    fail(ErrorCode::store_corrupt, "query entry length is inconsistent");
  }
  const std::uint32_t dense_bytes = ceil_div_u32(taxon_count, 8U);
  std::vector<std::uint8_t> dense(dense_bytes, 0);
  if (encoding == 1U) {
    if (payload_bytes != dense_bytes ||
        checked_mul<std::uint64_t>(selected_count, 4U,
                                  "canonical sparse comparison") < dense_bytes) {
      fail(ErrorCode::store_corrupt, "dense query encoding is not canonical");
    }
    std::copy(entry + 12, entry + 12 + payload_bytes, dense.begin());
  } else if (encoding == 2U) {
    if (payload_bytes != checked_mul<std::uint64_t>(
                             selected_count, 4U, "sparse query width") ||
        payload_bytes >= dense_bytes) {
      fail(ErrorCode::store_corrupt, "sparse query encoding is not canonical");
    }
    std::uint32_t previous = 0;
    for (std::uint32_t i = 0; i < selected_count; ++i) {
      const std::uint32_t taxon = load_u32_le(entry + 12 + 4U * i);
      if (taxon >= taxon_count || (i != 0 && taxon <= previous)) {
        fail(ErrorCode::store_corrupt,
             "sparse query IDs are not strictly increasing and in range");
      }
      if (!bit_is_set(retained.data(), taxon)) {
        fail(ErrorCode::scientific_invariant,
             "sparse query contains a non-retained taxon");
      }
      dense[taxon / 8U] |= static_cast<std::uint8_t>(1U << (taxon % 8U));
      previous = taxon;
    }
  } else {
    fail(ErrorCode::schema_mismatch, "unsupported query encoding");
  }
  if (popcount_bytes(dense.data(), dense.size()) != selected_count) {
    fail(ErrorCode::store_corrupt, "query selected_count is inconsistent");
  }
  validate_canonical_query(dense, retained, taxon_count, "decoded query");
  return ParsedQuery{dense, 0, entry_bytes};
}

void copy_sha(const std::uint8_t* src, Sha256& destination) {
  std::copy(src, src + destination.size(), destination.begin());
}

bool sha_matches(const std::uint8_t* bytes, const Sha256& expected) {
  Sha256 observed{};
  copy_sha(bytes, observed);
  return constant_time_equal(observed, expected);
}

void validate_magic(const std::uint8_t* bytes, const char* expected,
                    std::size_t count, const char* context) {
  if (!std::equal(bytes, bytes + count,
                  reinterpret_cast<const std::uint8_t*>(expected))) {
    fail(ErrorCode::schema_mismatch, std::string("wrong ") + context + " magic");
  }
}

}  // namespace

std::vector<std::uint8_t> encode_plan_record(
    const SpeciesAuthority& authority, const PlanInput& input) {
  if (input.states.size() != authority.primitive_count ||
      input.primitive_queries.size() != authority.primitive_count) {
    fail(ErrorCode::invalid_argument,
         "plan primitive arrays differ from the authority axis");
  }
  validate_padding_bits(input.retained, authority.global_taxon_count,
                        "retained pattern");
  const auto packed_states = pack_states(input.states);
  validate_terminal_states(authority, input.retained, input.states);

  std::map<std::vector<std::uint8_t>, EncodedQuery> unique_queries;
  std::vector<std::vector<std::uint8_t>> active_dense;
  std::vector<std::uint8_t> active_states;
  for (std::uint32_t primitive = 0; primitive < authority.primitive_count;
       ++primitive) {
    const std::uint8_t state = input.states[primitive];
    const auto& query = input.primitive_queries[primitive];
    if (state == 1U) {
      if (!query.empty()) {
        fail(ErrorCode::scientific_invariant,
             "NA_struct primitive has a query");
      }
      continue;
    }
    const auto encoded = encode_query(query, input.retained,
                                      authority.global_taxon_count);
    unique_queries.emplace(query, encoded);
    active_dense.push_back(query);
    active_states.push_back(state);
  }

  std::map<std::vector<std::uint8_t>, std::uint32_t> query_ids;
  std::vector<EncodedQuery> sorted_queries;
  for (const auto& item : unique_queries) {
    const std::uint32_t id = checked_u32(sorted_queries.size(), "query ID");
    query_ids.emplace(item.first, id);
    sorted_queries.push_back(item.second);
  }
  std::vector<std::vector<std::uint8_t>> grouped_states(sorted_queries.size());
  for (std::size_t i = 0; i < active_dense.size(); ++i) {
    grouped_states[query_ids.at(active_dense[i])].push_back(active_states[i]);
  }
  for (const auto& states : grouped_states) {
    if (states.size() == 1 && states[0] == 0U) continue;
    if (states.size() >= 2 &&
        std::all_of(states.begin(), states.end(),
                    [](std::uint8_t x) { return x == 2U; })) continue;
    fail(ErrorCode::scientific_invariant,
         "query group is not a singleton eligible primitive or a valid fiber");
  }

  std::vector<std::uint8_t> payload;
  append_bytes(payload, input.retained.data(), input.retained.size());
  append_bytes(payload, packed_states.data(), packed_states.size());
  for (const auto& query : active_dense) {
    append_u32_le(payload, query_ids.at(query));
  }
  std::vector<std::uint8_t> query_pool;
  append_u32_le(payload, 0U);
  for (const auto& query : sorted_queries) {
    append_bytes(query_pool, query.wire.data(), query.wire.size());
    append_u32_le(payload, checked_u32(query_pool.size(), "query pool offset"));
  }
  append_bytes(payload, query_pool.data(), query_pool.size());
  if (payload.size() >= UINT64_C(0x100000000)) {
    fail(ErrorCode::schema_mismatch,
         "TruthPlanRecord-v1 payload must be smaller than 2^32 bytes");
  }

  std::vector<std::uint8_t> record(kPlanHeaderBytes, 0);
  std::copy_n(reinterpret_cast<const std::uint8_t*>("TPLN"), 4, record.data());
  store_u16_le(record.data() + 4, 1U);
  store_u16_le(record.data() + 6, 0U);
  store_u16_le(record.data() + 8, 144U);
  store_u16_le(record.data() + 10, 0U);
  store_u64_le(record.data() + 12, input.pattern_id);
  store_u32_le(record.data() + 20, authority.global_taxon_count);
  store_u32_le(record.data() + 24, authority.primitive_count);
  store_u32_le(record.data() + 28,
               checked_u32(input.retained.size(), "retained bytes"));
  store_u32_le(record.data() + 32,
               checked_u32(packed_states.size(), "state bytes"));
  store_u32_le(record.data() + 36,
               checked_u32(active_dense.size(), "active count"));
  store_u32_le(record.data() + 40,
               checked_u32(sorted_queries.size(), "query count"));
  record[44] = 1U;
  record[45] = 4U;
  record[46] = 1U;
  record[47] = 0U;
  store_u64_le(record.data() + 48, payload.size());
  const Sha256 pattern_sha = retained_pattern_fingerprint(
      authority.global_taxon_count, input.retained);
  std::copy(pattern_sha.begin(), pattern_sha.end(), record.begin() + 56);
  std::copy(authority.fingerprint.begin(), authority.fingerprint.end(),
            record.begin() + 88);
  store_u64_le(record.data() + 120, xxh64(payload));
  store_u64_le(record.data() + 128, xxh64(record.data(), 128, 0));
  append_bytes(record, payload.data(), payload.size());
  return record;
}

DecodedPlan decode_plan_record(const SpeciesAuthority& authority,
                               const std::vector<std::uint8_t>& record) {
  if (record.size() < kPlanHeaderBytes) {
    fail(ErrorCode::store_corrupt, "plan header is truncated");
  }
  const std::uint8_t* header = record.data();
  validate_magic(header, "TPLN", 4, "plan");
  if (load_u16_le(header + 4) != 1U || load_u16_le(header + 6) != 0U ||
      load_u16_le(header + 8) != 144U || load_u16_le(header + 10) != 0U ||
      header[44] != 1U || header[45] != 4U || header[46] != 1U) {
    fail(ErrorCode::schema_mismatch,
         "unsupported plan schema, flags, encoding, or byte order");
  }
  if (header[47] != 0U ||
      std::any_of(header + 136, header + 144,
                  [](std::uint8_t x) { return x != 0U; })) {
    fail(ErrorCode::store_corrupt, "plan reserved bytes are nonzero");
  }
  if (load_u32_le(header + 20) != authority.global_taxon_count ||
      load_u32_le(header + 24) != authority.primitive_count ||
      !sha_matches(header + 88, authority.fingerprint)) {
    fail(ErrorCode::authority_mismatch,
         "plan is not bound to the open SpeciesAuthority");
  }
  const std::uint32_t retained_bytes = load_u32_le(header + 28);
  const std::uint32_t state_bytes = load_u32_le(header + 32);
  const std::uint32_t active_count = load_u32_le(header + 36);
  const std::uint32_t query_count = load_u32_le(header + 40);
  const std::uint64_t payload_bytes64 = load_u64_le(header + 48);
  if (retained_bytes != ceil_div_u32(authority.global_taxon_count, 8U) ||
      state_bytes != ceil_div_u32(authority.primitive_count, 4U) ||
      payload_bytes64 >= UINT64_C(0x100000000)) {
    fail(ErrorCode::store_corrupt, "plan count-derived widths are invalid");
  }
  const std::size_t payload_bytes = checked_size(payload_bytes64, "plan payload");
  if (record.size() != checked_add<std::size_t>(kPlanHeaderBytes, payload_bytes,
                                               "plan record length")) {
    fail(ErrorCode::store_corrupt,
         "plan payload length or trailing-byte boundary is invalid");
  }
  const std::uint8_t* payload = header + kPlanHeaderBytes;
  if (load_u64_le(header + 120) != xxh64(payload, payload_bytes, 0) ||
      load_u64_le(header + 128) != xxh64(header, 128, 0)) {
    fail(ErrorCode::store_corrupt, "plan header or payload checksum mismatch");
  }

  std::size_t cursor = 0;
  const std::size_t retained_end = checked_add<std::size_t>(
      cursor, retained_bytes, "retained section end");
  const std::size_t state_end = checked_add<std::size_t>(
      retained_end, state_bytes, "state section end");
  const std::size_t refs_bytes = checked_mul<std::size_t>(
      active_count, 4U, "query refs bytes");
  const std::size_t refs_end = checked_add<std::size_t>(
      state_end, refs_bytes, "query refs end");
  const std::size_t offsets_bytes = checked_mul<std::size_t>(
      checked_add<std::size_t>(query_count, 1U, "query offset count"), 4U,
      "query offsets bytes");
  const std::size_t offsets_end = checked_add<std::size_t>(
      refs_end, offsets_bytes, "query offsets end");
  if (offsets_end > payload_bytes) {
    fail(ErrorCode::store_corrupt, "plan payload sections are truncated");
  }

  DecodedPlan out;
  out.pattern_id = load_u64_le(header + 12);
  out.retained.assign(payload, payload + retained_bytes);
  validate_padding_bits(out.retained, authority.global_taxon_count,
                        "retained pattern");
  out.states = unpack_states(payload + retained_end, authority.primitive_count,
                             state_bytes);
  validate_terminal_states(authority, out.retained, out.states);
  std::uint32_t observed_active = 0;
  for (std::uint8_t state : out.states) {
    if (state == 0U || state == 2U) ++observed_active;
  }
  if (observed_active != active_count) {
    fail(ErrorCode::store_corrupt, "active_count does not match truth states");
  }

  std::vector<std::uint32_t> refs(active_count);
  for (std::uint32_t i = 0; i < active_count; ++i) {
    refs[i] = load_u32_le(payload + state_end + 4U * i);
    if (refs[i] >= query_count) {
      fail(ErrorCode::store_corrupt, "query reference is out of range");
    }
  }
  std::vector<std::uint32_t> offsets(query_count + 1U);
  for (std::uint32_t i = 0; i <= query_count; ++i) {
    offsets[i] = load_u32_le(payload + refs_end + 4U * i);
    if (i == 0 && offsets[i] != 0U) {
      fail(ErrorCode::store_corrupt, "first query offset is not zero");
    }
    if (i != 0 && offsets[i] <= offsets[i - 1U]) {
      fail(ErrorCode::store_corrupt,
           "query offsets are not strict entry boundaries");
    }
  }
  const std::size_t pool_bytes = payload_bytes - offsets_end;
  if (query_count == 0) {
    if (active_count != 0 || offsets[0] != 0 || pool_bytes != 0) {
      fail(ErrorCode::store_corrupt, "zero-query representation is invalid");
    }
  } else if (offsets.back() != pool_bytes) {
    fail(ErrorCode::store_corrupt, "last query offset does not end the pool");
  }

  std::vector<std::vector<std::uint8_t>> queries;
  queries.reserve(query_count);
  const std::uint8_t* pool = payload + offsets_end;
  for (std::uint32_t i = 0; i < query_count; ++i) {
    const std::size_t begin = offsets[i];
    const std::size_t end = offsets[i + 1U];
    if (end > pool_bytes || begin >= end) {
      fail(ErrorCode::store_corrupt, "query offset is outside the pool");
    }
    const auto parsed = parse_query(pool + begin, end - begin, out.retained,
                                    authority.global_taxon_count);
    if (!queries.empty() && !(queries.back() < parsed.dense)) {
      fail(ErrorCode::store_corrupt,
           "query pool is not strictly sorted and unique");
    }
    queries.push_back(parsed.dense);
  }
  std::vector<std::uint32_t> reference_counts(query_count, 0);
  std::vector<std::vector<std::uint32_t>> group_members(query_count);
  std::vector<std::vector<std::uint8_t>> group_states(query_count);
  out.primitive_queries.resize(authority.primitive_count);
  std::size_t active_index = 0;
  for (std::uint32_t primitive = 0; primitive < authority.primitive_count;
       ++primitive) {
    const std::uint8_t state = out.states[primitive];
    if (state == 1U) continue;
    const std::uint32_t ref = refs[active_index++];
    out.primitive_queries[primitive] = queries[ref];
    ++reference_counts[ref];
    group_members[ref].push_back(primitive);
    group_states[ref].push_back(state);
    if (state == 0U) out.eligible_primitives.push_back(primitive);
  }
  for (std::uint32_t query = 0; query < query_count; ++query) {
    if (reference_counts[query] == 0) {
      fail(ErrorCode::store_corrupt, "query pool has an unreferenced entry");
    }
    const auto& states = group_states[query];
    if (states.size() == 1 && states[0] == 0U) continue;
    if (states.size() >= 2 &&
        std::all_of(states.begin(), states.end(),
                    [](std::uint8_t x) { return x == 2U; })) {
      out.fibers.push_back(group_members[query]);
      out.fiber_queries.push_back(queries[query]);
      continue;
    }
    fail(ErrorCode::scientific_invariant,
         "decoded query group is not a valid eligible/fiber group");
  }

  out.retained_pattern_sha256 = retained_pattern_fingerprint(
      authority.global_taxon_count, out.retained);
  if (!sha_matches(header + 56, out.retained_pattern_sha256)) {
    fail(ErrorCode::pattern_mismatch,
         "retained-pattern fingerprint does not match exact bits");
  }
  out.species_authority_sha256 = authority.fingerprint;
  out.payload_xxh64 = load_u64_le(header + 120);
  out.header_xxh64 = load_u64_le(header + 128);
  out.record_xxh64 = xxh64(record);
  return out;
}

TruthPlanView::TruthPlanView(
    SpeciesAuthorityPtr authority,
    std::shared_ptr<const std::vector<std::uint8_t>> record,
    std::uint64_t generation)
    : authority_(std::move(authority)),
      record_(std::move(record)),
      generation_(generation),
      decoded_() {
  if (!authority_ || !record_) {
    fail(ErrorCode::invalid_argument, "view requires authority and record owner");
  }
  decoded_ = decode_plan_record(*authority_, *record_);
}

}  // namespace engine002
}  // namespace splitaligner

