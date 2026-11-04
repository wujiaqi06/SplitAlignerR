#ifndef SPLITALIGNERR_ENGINE002_SPECIES_AUTHORITY_BINDING_HPP
#define SPLITALIGNERR_ENGINE002_SPECIES_AUTHORITY_BINDING_HPP

#include "engine002_hash.h"

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace splitaligner {
namespace engine002 {

constexpr std::uint32_t kInternalTaxon = UINT32_C(0xffffffff);

struct SpeciesAuthority {
  std::uint32_t global_taxon_count = 0;
  std::uint32_t primitive_count = 0;
  std::vector<std::string> taxon_labels;
  std::vector<std::uint32_t> terminal_taxon_ids;
  std::vector<std::vector<std::uint8_t>> primitive_splits;
  Sha256 fingerprint{};
};

using SpeciesAuthorityPtr = std::shared_ptr<const SpeciesAuthority>;

SpeciesAuthorityPtr make_species_authority(
    const std::vector<std::string>& taxon_labels,
    const std::vector<std::uint32_t>& terminal_taxon_ids,
    const std::vector<std::vector<std::uint8_t>>& primitive_splits);

Sha256 retained_pattern_fingerprint(std::uint32_t global_taxon_count,
                                    const std::vector<std::uint8_t>& retained);

Sha256 truth_semantics_fingerprint();
Sha256 pattern_registry_fingerprint(
    std::uint32_t global_taxon_count,
    const std::vector<std::vector<std::uint8_t>>& retained_patterns);
Sha256 store_identity_fingerprint(const Sha256& species_authority,
                                  const Sha256& pattern_registry,
                                  const Sha256& truth_semantics);

bool bit_is_set(const std::uint8_t* bytes, std::uint32_t id) noexcept;
std::uint32_t popcount_bytes(const std::uint8_t* bytes,
                             std::size_t size) noexcept;
void validate_padding_bits(const std::vector<std::uint8_t>& bytes,
                           std::uint32_t bit_count,
                           const char* context);
void validate_canonical_query(const std::vector<std::uint8_t>& selected,
                              const std::vector<std::uint8_t>& retained,
                              std::uint32_t global_taxon_count,
                              const char* context);

}  // namespace engine002
}  // namespace splitaligner

#endif
