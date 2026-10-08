#ifndef SPLITALIGNERR_ENGINE002_MANIFEST_HPP
#define SPLITALIGNERR_ENGINE002_MANIFEST_HPP

#include "engine002_hash.h"

#include <cstdint>
#include <string>

namespace splitaligner {
namespace engine002 {

enum class ManifestState { incomplete, validated };

struct StoreManifest {
  ManifestState state = ManifestState::incomplete;
  std::string run_store_id;
  std::string store_component;
  std::uint64_t store_bytes = 0;
  Sha256 store_sha256{};
  Sha256 species_authority_sha256{};
  Sha256 pattern_registry_sha256{};
  Sha256 truth_semantics_sha256{};
  std::uint64_t pattern_count = 0;
};

bool valid_run_store_id(const std::string& value) noexcept;
bool valid_component_basename(const std::string& value) noexcept;
std::string render_manifest(const StoreManifest& manifest);
StoreManifest parse_manifest(const std::string& bytes);
Sha256 parse_sha256_hex(const std::string& value, const char* context);

}  // namespace engine002
}  // namespace splitaligner

#endif

