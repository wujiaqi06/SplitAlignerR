#include "engine002_stress_fixture.h"

#include "engine002_checked_math.h"
#include "engine002_errors.h"

#include <iomanip>
#include <sstream>

namespace splitaligner {
namespace engine002 {
namespace {

constexpr std::uint32_t kStressTaxa = 302;
constexpr std::uint32_t kStressInternal = 299;
constexpr std::uint32_t kStressPrimitives = kStressTaxa + kStressInternal;
constexpr std::size_t kStressRetainedBytes = (kStressTaxa + 7U) / 8U;

void set_bit(std::vector<std::uint8_t>& bytes, std::uint32_t id) {
  bytes[id / 8U] |= static_cast<std::uint8_t>(1U << (id % 8U));
}

std::vector<std::uint8_t> retained_for_id(std::uint64_t pattern_id) {
  std::vector<std::uint8_t> retained(kStressRetainedBytes, UINT8_C(0xff));
  for (std::size_t i = 0; i < 8; ++i) {
    retained[i] = static_cast<std::uint8_t>(
        (pattern_id >> (8U * (7U - i))) & UINT64_C(0xff));
  }
  retained.back() = UINT8_C(0x3f);
  return retained;
}

std::vector<std::uint32_t> retained_taxa(
    const std::vector<std::uint8_t>& retained) {
  std::vector<std::uint32_t> taxa;
  taxa.reserve(kStressTaxa);
  for (std::uint32_t taxon = 0; taxon < kStressTaxa; ++taxon) {
    if (bit_is_set(retained.data(), taxon)) taxa.push_back(taxon);
  }
  return taxa;
}

}  // namespace

AuthorityScaleFixture make_authority_scale_fixture(
    std::uint64_t pattern_count) {
  std::vector<std::string> labels;
  labels.reserve(kStressTaxa);
  for (std::uint32_t taxon = 0; taxon < kStressTaxa; ++taxon) {
    std::ostringstream label;
    label << 'T' << std::setw(3) << std::setfill('0') << taxon;
    labels.push_back(label.str());
  }

  std::vector<std::uint32_t> terminals(kStressPrimitives, kInternalTaxon);
  std::vector<std::vector<std::uint8_t>> splits(
      kStressPrimitives, std::vector<std::uint8_t>(kStressRetainedBytes, 0));
  for (std::uint32_t taxon = 0; taxon < kStressTaxa; ++taxon) {
    terminals[taxon] = taxon;
    set_bit(splits[taxon], taxon);
  }
  std::uint32_t internal = 0;
  for (std::uint32_t left = 0;
       left < kStressTaxa && internal < kStressInternal; ++left) {
    for (std::uint32_t right = left + 1;
         right < kStressTaxa && internal < kStressInternal; ++right) {
      auto& split = splits[kStressTaxa + internal];
      set_bit(split, left);
      set_bit(split, right);
      ++internal;
    }
  }
  if (internal != kStressInternal) {
    fail(ErrorCode::internal_failure,
         "authority-scale fixture could not create internal coordinates");
  }
  auto authority = make_species_authority(labels, terminals, splits);

  std::vector<std::vector<std::uint8_t>> retained_patterns;
  retained_patterns.reserve(checked_size(pattern_count,
                                         "stress registry count"));
  for (std::uint64_t pattern = 0; pattern < pattern_count; ++pattern) {
    retained_patterns.push_back(retained_for_id(pattern));
  }
  auto registry = make_pattern_registry(authority,
                                        std::move(retained_patterns));
  return AuthorityScaleFixture{std::move(authority), std::move(registry)};
}

std::shared_ptr<const std::vector<std::uint8_t>>
make_authority_scale_record(const SpeciesAuthority& authority,
                            std::uint64_t pattern_id,
                            const std::vector<std::uint8_t>& retained) {
  if (authority.global_taxon_count != kStressTaxa ||
      authority.primitive_count != kStressPrimitives) {
    fail(ErrorCode::authority_mismatch,
         "authority-scale record requires the synthetic 302-taxon authority");
  }
  PlanInput input;
  input.pattern_id = pattern_id;
  input.retained = retained;
  input.states.assign(kStressPrimitives, 0);
  input.primitive_queries.resize(kStressPrimitives);
  const auto taxa = retained_taxa(retained);
  if (taxa.size() < 26U) {
    fail(ErrorCode::scientific_invariant,
         "authority-scale retained pattern is unexpectedly small");
  }
  for (std::uint32_t taxon = 0; taxon < kStressTaxa; ++taxon) {
    if (bit_is_set(retained.data(), taxon)) {
      auto& query = input.primitive_queries[taxon];
      query.assign(kStressRetainedBytes, 0);
      set_bit(query, taxon);
    } else {
      input.states[taxon] = 1;
    }
  }
  std::uint32_t internal = 0;
  for (std::size_t left = 0;
       left < taxa.size() && internal < kStressInternal; ++left) {
    for (std::size_t middle = left + 1;
         middle < taxa.size() && internal < kStressInternal; ++middle) {
      for (std::size_t right = middle + 1;
           right < taxa.size() && internal < kStressInternal; ++right) {
        auto& query = input.primitive_queries[kStressTaxa + internal];
        query.assign(kStressRetainedBytes, 0);
        set_bit(query, taxa[left]);
        set_bit(query, taxa[middle]);
        set_bit(query, taxa[right]);
        ++internal;
      }
    }
  }
  if (internal != kStressInternal) {
    fail(ErrorCode::scientific_invariant,
         "authority-scale pattern has too few internal queries");
  }
  return std::make_shared<const std::vector<std::uint8_t>>(
      encode_plan_record(authority, input));
}

}  // namespace engine002
}  // namespace splitaligner
