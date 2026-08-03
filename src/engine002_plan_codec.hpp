#ifndef SPLITALIGNERR_ENGINE002_PLAN_CODEC_HPP
#define SPLITALIGNERR_ENGINE002_PLAN_CODEC_HPP

#include "engine002_hash.hpp"
#include "engine002_species_authority_binding.hpp"

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

class TruthPlanView {
 public:
  TruthPlanView(SpeciesAuthorityPtr authority,
                std::shared_ptr<const std::vector<std::uint8_t>> record,
                std::uint64_t generation);
  TruthPlanView(const TruthPlanView&) = delete;
  TruthPlanView& operator=(const TruthPlanView&) = delete;
  TruthPlanView(TruthPlanView&&) noexcept = default;
  TruthPlanView& operator=(TruthPlanView&&) noexcept = default;

  std::uint64_t pattern_id() const noexcept { return decoded_.pattern_id; }
  std::uint64_t generation() const noexcept { return generation_; }
  const DecodedPlan& decoded() const noexcept { return decoded_; }

 private:
  SpeciesAuthorityPtr authority_;
  std::shared_ptr<const std::vector<std::uint8_t>> record_;
  std::uint64_t generation_;
  DecodedPlan decoded_;
};

}  // namespace engine002
}  // namespace splitaligner

#endif

