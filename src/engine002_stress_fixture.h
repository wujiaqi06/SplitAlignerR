#ifndef SPLITALIGNERR_ENGINE002_STRESS_FIXTURE_H
#define SPLITALIGNERR_ENGINE002_STRESS_FIXTURE_H

#include "engine002_store.h"

#include <cstdint>
#include <memory>
#include <vector>

namespace splitaligner {
namespace engine002 {

struct AuthorityScaleFixture {
  SpeciesAuthorityPtr authority;
  PatternRegistryPtr registry;
};

AuthorityScaleFixture make_authority_scale_fixture(
    std::uint64_t pattern_count);

std::shared_ptr<const std::vector<std::uint8_t>>
make_authority_scale_record(const SpeciesAuthority& authority,
                            std::uint64_t pattern_id,
                            const std::vector<std::uint8_t>& retained);

}  // namespace engine002
}  // namespace splitaligner

#endif
