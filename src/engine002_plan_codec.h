#ifndef SPLITALIGNERR_ENGINE002_PLAN_CODEC_HPP
#define SPLITALIGNERR_ENGINE002_PLAN_CODEC_HPP

#include "engine002_hash.h"
#include "engine002_species_authority_binding.h"

#include <cstdint>
#include <memory>
#include <vector>

namespace splitaligner {
namespace engine002 {

constexpr std::size_t kPlanHeaderBytes = 144;

struct PlanInput {
  std::uint64_t pattern_id = 0;
  std::vector<std::uint8_t> retained;
  std::vector<std::uint8_t> states;
  std::vector<std::vector<std::uint8_t>> primitive_queries;
};

struct DecodedPlan {
  std::uint64_t pattern_id = 0;
  std::vector<std::uint8_t> retained;
  std::vector<std::uint8_t> states;
  std::vector<std::vector<std::uint8_t>> primitive_queries;
  std::vector<std::uint32_t> eligible_primitives;
  std::vector<std::vector<std::uint32_t>> fibers;
  std::vector<std::vector<std::uint8_t>> fiber_queries;
  Sha256 retained_pattern_sha256{};
  Sha256 species_authority_sha256{};
  std::uint64_t payload_xxh64 = 0;
  std::uint64_t header_xxh64 = 0;
  std::uint64_t record_xxh64 = 0;
};

std::vector<std::uint8_t> encode_plan_record(
    const SpeciesAuthority& authority, const PlanInput& input);

DecodedPlan decode_plan_record(const SpeciesAuthority& authority,
                               const std::vector<std::uint8_t>& record);
DecodedPlan decode_plan_record(const SpeciesAuthority& authority,
                               const std::uint8_t* record,
                               std::size_t record_size);

class TruthPlanView {
 public:
  TruthPlanView(SpeciesAuthorityPtr authority,
                std::shared_ptr<const std::vector<std::uint8_t>> record,
                std::uint64_t generation);
  TruthPlanView(SpeciesAuthorityPtr authority,
                std::shared_ptr<const void> owner,
                const std::uint8_t* record,
                std::size_t record_size,
                std::uint64_t generation);
  TruthPlanView(const TruthPlanView&) = delete;
  TruthPlanView& operator=(const TruthPlanView&) = delete;
  TruthPlanView(TruthPlanView&&) noexcept = default;
  TruthPlanView& operator=(TruthPlanView&&) noexcept = default;

  std::uint64_t pattern_id() const noexcept { return pattern_id_; }
  std::uint64_t generation() const noexcept { return generation_; }
  bool retained(std::uint32_t taxon_id) const;
  std::uint8_t state(std::uint32_t primitive_id) const;
  std::vector<std::uint8_t> primitive_query(
      std::uint32_t primitive_id) const;
  DecodedPlan snapshot() const;

 private:
  SpeciesAuthorityPtr authority_;
  std::shared_ptr<const void> owner_;
  const std::uint8_t* record_;
  std::size_t record_size_;
  std::uint64_t generation_;
  std::uint64_t pattern_id_;
};

}  // namespace engine002
}  // namespace splitaligner

#endif
