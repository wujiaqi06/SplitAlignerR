#include "engine002_species_authority_binding.h"

#include "engine002_checked_math.h"
#include "engine002_endian.h"
#include "engine002_errors.h"

#include <algorithm>
#include <array>
#include <set>

namespace splitaligner {
namespace engine002 {
namespace {

void append_domain(std::vector<std::uint8_t>& out, const char* text) {
  const auto* bytes = reinterpret_cast<const std::uint8_t*>(text);
  append_bytes(out, bytes, std::char_traits<char>::length(text));
  out.push_back(0);
}

void append_blob(std::vector<std::uint8_t>& out,
                 const std::uint8_t* bytes,
                 std::size_t size) {
  append_u64_le(out, static_cast<std::uint64_t>(size));
  append_bytes(out, bytes, size);
}

std::vector<std::uint8_t> full_retained(std::uint32_t taxon_count) {
  std::vector<std::uint8_t> out(ceil_div_u32(taxon_count, 8U), 0xffU);
  if (!out.empty() && taxon_count % 8U != 0) {
    out.back() = static_cast<std::uint8_t>((1U << (taxon_count % 8U)) - 1U);
  }
  return out;
}

}  // namespace

bool bit_is_set(const std::uint8_t* bytes, std::uint32_t id) noexcept {
  return (bytes[id / 8U] & static_cast<std::uint8_t>(1U << (id % 8U))) != 0;
}

std::uint32_t popcount_bytes(const std::uint8_t* bytes,
                             std::size_t size) noexcept {
  std::uint32_t count = 0;
  for (std::size_t i = 0; i < size; ++i) {
    std::uint8_t value = bytes[i];
    while (value != 0) {
      value = static_cast<std::uint8_t>(value & (value - 1U));
      ++count;
    }
  }
  return count;
}

void validate_padding_bits(const std::vector<std::uint8_t>& bytes,
                           std::uint32_t bit_count,
                           const char* context) {
  const std::size_t expected = ceil_div_u32(bit_count, 8U);
  if (bytes.size() != expected) {
    fail(ErrorCode::scientific_invariant,
         std::string(context) + " has wrong bitset width");
  }
  if (!bytes.empty() && bit_count % 8U != 0) {
    const std::uint8_t allowed =
        static_cast<std::uint8_t>((1U << (bit_count % 8U)) - 1U);
    if ((bytes.back() & static_cast<std::uint8_t>(~allowed)) != 0) {
      fail(ErrorCode::scientific_invariant,
           std::string(context) + " has nonzero padding bits");
    }
  }
}

void validate_canonical_query(const std::vector<std::uint8_t>& selected,
                              const std::vector<std::uint8_t>& retained,
                              std::uint32_t global_taxon_count,
                              const char* context) {
  validate_padding_bits(selected, global_taxon_count, context);
  validate_padding_bits(retained, global_taxon_count, "retained pattern");
  std::vector<std::uint8_t> complement(selected.size(), 0);
  for (std::size_t i = 0; i < selected.size(); ++i) {
    if ((selected[i] & static_cast<std::uint8_t>(~retained[i])) != 0) {
      fail(ErrorCode::scientific_invariant,
           std::string(context) + " selects a non-retained taxon");
    }
    complement[i] = static_cast<std::uint8_t>(retained[i] ^ selected[i]);
  }
  const std::uint32_t selected_count =
      popcount_bytes(selected.data(), selected.size());
  const std::uint32_t complement_count =
      popcount_bytes(complement.data(), complement.size());
  if (selected_count == 0 || complement_count == 0) {
    fail(ErrorCode::scientific_invariant,
         std::string(context) + " must have two nonempty retained sides");
  }
  if (selected_count > complement_count ||
      (selected_count == complement_count && complement < selected)) {
    fail(ErrorCode::scientific_invariant,
         std::string(context) + " violates the canonical-side rule");
  }
}

SpeciesAuthorityPtr make_species_authority(
    const std::vector<std::string>& taxon_labels,
    const std::vector<std::uint32_t>& terminal_taxon_ids,
    const std::vector<std::vector<std::uint8_t>>& primitive_splits) {
  if (taxon_labels.empty()) {
    fail(ErrorCode::invalid_argument, "species authority has no taxa");
  }
  if (taxon_labels.size() > UINT32_MAX || primitive_splits.size() > UINT32_MAX) {
    fail(ErrorCode::schema_mismatch, "species authority count exceeds u32");
  }
  if (terminal_taxon_ids.size() != primitive_splits.size()) {
    fail(ErrorCode::invalid_argument,
         "terminal axis and primitive split axis differ in length");
  }
  std::set<std::string> unique_labels;
  for (const auto& label : taxon_labels) {
    if (label.empty() || !unique_labels.insert(label).second) {
      fail(ErrorCode::invalid_argument,
           "species authority labels must be nonempty and unique");
    }
  }

  auto authority = std::make_shared<SpeciesAuthority>();
  authority->global_taxon_count =
      static_cast<std::uint32_t>(taxon_labels.size());
  authority->primitive_count =
      static_cast<std::uint32_t>(primitive_splits.size());
  authority->taxon_labels = taxon_labels;
  authority->terminal_taxon_ids = terminal_taxon_ids;
  authority->primitive_splits = primitive_splits;

  const auto all = full_retained(authority->global_taxon_count);
  for (std::uint32_t primitive = 0; primitive < authority->primitive_count;
       ++primitive) {
    const auto& split = authority->primitive_splits[primitive];
    const std::uint32_t terminal = authority->terminal_taxon_ids[primitive];
    if (terminal != kInternalTaxon) {
      validate_padding_bits(split, authority->global_taxon_count,
                            "authority terminal split");
      if (terminal >= authority->global_taxon_count) {
        fail(ErrorCode::invalid_argument,
             "terminal primitive taxon ID is out of range");
      }
      if (popcount_bytes(split.data(), split.size()) != 1U ||
          !bit_is_set(split.data(), terminal)) {
        fail(ErrorCode::scientific_invariant,
             "terminal primitive split is not its singleton taxon");
      }
    } else {
      validate_canonical_query(split, all, authority->global_taxon_count,
                               "authority internal primitive split");
    }
  }

  std::vector<std::uint8_t> bytes;
  append_domain(bytes, "SplitAlignerR/SpeciesAuthority/v1");
  append_u32_le(bytes, authority->global_taxon_count);
  append_u32_le(bytes, authority->primitive_count);
  for (std::uint32_t i = 0; i < authority->global_taxon_count; ++i) {
    append_u32_le(bytes, i);
    const auto& label = authority->taxon_labels[i];
    append_blob(bytes, reinterpret_cast<const std::uint8_t*>(label.data()),
                label.size());
  }
  for (std::uint32_t i = 0; i < authority->primitive_count; ++i) {
    append_u32_le(bytes, i);
    const std::uint32_t terminal = authority->terminal_taxon_ids[i];
    bytes.push_back(terminal == kInternalTaxon ? 0U : 1U);
    bytes.insert(bytes.end(), 3, 0U);
    append_u32_le(bytes, terminal);
    append_blob(bytes, authority->primitive_splits[i].data(),
                authority->primitive_splits[i].size());
  }
  authority->fingerprint = sha256(bytes);
  return authority;
}

Sha256 retained_pattern_fingerprint(
    std::uint32_t global_taxon_count,
    const std::vector<std::uint8_t>& retained) {
  validate_padding_bits(retained, global_taxon_count, "retained pattern");
  std::vector<std::uint8_t> bytes;
  append_domain(bytes, "SplitAlignerR/RetainedPattern/v1");
  append_u32_le(bytes, global_taxon_count);
  append_blob(bytes, retained.data(), retained.size());
  return sha256(bytes);
}

Sha256 truth_semantics_fingerprint() {
  static const std::array<const char*, 8> clauses = {{
      "state:0=eligible;1=NA_struct;2=NA_fuse;3=invalid",
      "state0:eligible-not-mapped;NA_topo=absent",
      "primitive_axis:SpeciesAuthority-v1",
      "fiber:same-query;all-state2;size>=2;members=u32le-sorted",
      "query:canonical-dense-selected-side;unsigned-byte-lex",
      "bstar:exact-canonical-primitive-member-set",
      "terminal:retained-terminal!=NA_struct;missing-terminal=NA_struct",
      "schema:TruthPlanRecord-v1.0"}};
  std::vector<std::uint8_t> bytes;
  append_domain(bytes, "SplitAlignerR/TruthSemantics/v1");
  append_u32_le(bytes, static_cast<std::uint32_t>(clauses.size()));
  for (const char* clause : clauses) {
    const std::size_t length = std::char_traits<char>::length(clause);
    append_u32_le(bytes, checked_u32(length, "truth semantics clause"));
    append_bytes(bytes, reinterpret_cast<const std::uint8_t*>(clause), length);
  }
  return sha256(bytes);
}

Sha256 pattern_registry_fingerprint(
    std::uint32_t global_taxon_count,
    const std::vector<std::vector<std::uint8_t>>& retained_patterns) {
  std::vector<std::uint8_t> bytes;
  append_domain(bytes, "SplitAlignerR/PatternRegistry/v1");
  append_u32_le(bytes, global_taxon_count);
  append_u64_le(bytes, static_cast<std::uint64_t>(retained_patterns.size()));
  std::vector<std::uint8_t> previous;
  for (std::size_t i = 0; i < retained_patterns.size(); ++i) {
    const auto& retained = retained_patterns[i];
    validate_padding_bits(retained, global_taxon_count, "registry pattern");
    if (i != 0 && !(previous < retained)) {
      fail(ErrorCode::duplicate_pattern,
           "pattern registry is not strictly sorted and unique");
    }
    append_u64_le(bytes, static_cast<std::uint64_t>(i));
    append_blob(bytes, retained.data(), retained.size());
    previous = retained;
  }
  return sha256(bytes);
}

Sha256 store_identity_fingerprint(const Sha256& species_authority,
                                  const Sha256& pattern_registry,
                                  const Sha256& truth_semantics) {
  std::vector<std::uint8_t> bytes;
  append_domain(bytes, "SplitAlignerR/TruthPlanStoreIdentity/v1");
  append_array(bytes, species_authority);
  append_array(bytes, pattern_registry);
  append_array(bytes, truth_semantics);
  append_u16_le(bytes, 1U);
  append_u16_le(bytes, 0U);
  append_u16_le(bytes, 1U);
  append_u16_le(bytes, 0U);
  return sha256(bytes);
}

}  // namespace engine002
}  // namespace splitaligner
