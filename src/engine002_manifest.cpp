#include "engine002_manifest.hpp"

#include "engine002_errors.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <limits>
#include <sstream>
#include <vector>

namespace splitaligner {
namespace engine002 {
namespace {

std::uint8_t hex_value(char value) {
  if (value >= '0' && value <= '9') return static_cast<std::uint8_t>(value - '0');
  if (value >= 'a' && value <= 'f') {
    return static_cast<std::uint8_t>(10 + value - 'a');
  }
  fail(ErrorCode::store_corrupt, "manifest digest is not lowercase hexadecimal");
}

std::uint64_t parse_u64_decimal(const std::string& value,
                                const char* context) {
  if (value.empty() || (value.size() > 1 && value[0] == '0')) {
    fail(ErrorCode::store_corrupt,
         std::string(context) + " is not canonical unsigned decimal");
  }
  std::uint64_t result = 0;
  for (char digit : value) {
    if (digit < '0' || digit > '9') {
      fail(ErrorCode::store_corrupt,
           std::string(context) + " is not unsigned decimal");
    }
    const std::uint64_t part = static_cast<std::uint64_t>(digit - '0');
    if (result > (std::numeric_limits<std::uint64_t>::max() - part) / 10U) {
      fail(ErrorCode::store_corrupt,
           std::string(context) + " exceeds u64");
    }
    result = result * 10U + part;
  }
  return result;
}

std::string value_after(const std::string& line, const char* key) {
  const std::string prefix = std::string(key) + "=";
  if (line.compare(0, prefix.size(), prefix) != 0) {
    fail(ErrorCode::store_corrupt,
         std::string("manifest expected key ") + key);
  }
  return line.substr(prefix.size());
}

}  // namespace

bool valid_run_store_id(const std::string& value) noexcept {
  return value.size() == 32 &&
         std::all_of(value.begin(), value.end(), [](char c) {
           return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
         });
}

bool valid_component_basename(const std::string& value) noexcept {
  if (value.empty() || value.size() > 127 || value == "." || value == "..") {
    return false;
  }
  if (!std::isalnum(static_cast<unsigned char>(value[0]))) return false;
  return std::all_of(value.begin(), value.end(), [](char c) {
    const auto byte = static_cast<unsigned char>(c);
    return std::isalnum(byte) || c == '.' || c == '_' || c == '-';
  });
}

std::string render_manifest(const StoreManifest& manifest) {
  if (!valid_run_store_id(manifest.run_store_id) ||
      !valid_component_basename(manifest.store_component)) {
    fail(ErrorCode::invalid_argument, "manifest name or run ID is invalid");
  }
  std::ostringstream out;
  out << "magic=SplitAlignerR-TruthPlanStore-Manifest\n"
      << "manifest_schema_major=1\n"
      << "manifest_schema_minor=0\n"
      << "completion_state="
      << (manifest.state == ManifestState::validated ? "VALIDATED" : "INCOMPLETE")
      << "\n"
      << "run_store_id=" << manifest.run_store_id << "\n"
      << "store_component=" << manifest.store_component << "\n"
      << "store_bytes=" << manifest.store_bytes << "\n"
      << "store_sha256=" << hex_lower(manifest.store_sha256) << "\n"
      << "store_schema=1.0\n"
      << "plan_schema=1.0\n"
      << "species_authority_sha256="
      << hex_lower(manifest.species_authority_sha256) << "\n"
      << "pattern_registry_sha256="
      << hex_lower(manifest.pattern_registry_sha256) << "\n"
      << "truth_semantics_sha256="
      << hex_lower(manifest.truth_semantics_sha256) << "\n"
      << "pattern_count=" << manifest.pattern_count << "\n"
      << "publication_timestamp_policy=OMITTED_V1\n";
  return out.str();
}

Sha256 parse_sha256_hex(const std::string& value, const char* context) {
  if (value.size() != 64) {
    fail(ErrorCode::store_corrupt,
         std::string(context) + " SHA-256 width is invalid");
  }
  Sha256 result{};
  for (std::size_t i = 0; i < result.size(); ++i) {
    result[i] = static_cast<std::uint8_t>(
        (hex_value(value[2 * i]) << 4U) | hex_value(value[2 * i + 1]));
  }
  return result;
}

StoreManifest parse_manifest(const std::string& bytes) {
  if (bytes.empty() || bytes.back() != '\n' || bytes.find('\r') != std::string::npos ||
      bytes.find('\0') != std::string::npos) {
    fail(ErrorCode::store_corrupt, "manifest text encoding is not canonical");
  }
  std::vector<std::string> lines;
  std::size_t begin = 0;
  while (begin < bytes.size()) {
    const std::size_t end = bytes.find('\n', begin);
    lines.push_back(bytes.substr(begin, end - begin));
    begin = end + 1;
  }
  if (lines.size() != 15) {
    fail(ErrorCode::store_corrupt, "manifest key count is invalid");
  }
  if (lines[0] != "magic=SplitAlignerR-TruthPlanStore-Manifest" ||
      lines[1] != "manifest_schema_major=1" ||
      lines[2] != "manifest_schema_minor=0" ||
      lines[8] != "store_schema=1.0" || lines[9] != "plan_schema=1.0" ||
      lines[14] != "publication_timestamp_policy=OMITTED_V1") {
    fail(ErrorCode::schema_mismatch, "manifest schema or key order is invalid");
  }
  StoreManifest result;
  const std::string state = value_after(lines[3], "completion_state");
  if (state == "INCOMPLETE") result.state = ManifestState::incomplete;
  else if (state == "VALIDATED") result.state = ManifestState::validated;
  else fail(ErrorCode::schema_mismatch, "manifest completion state is invalid");
  result.run_store_id = value_after(lines[4], "run_store_id");
  result.store_component = value_after(lines[5], "store_component");
  result.store_bytes = parse_u64_decimal(
      value_after(lines[6], "store_bytes"), "store_bytes");
  result.store_sha256 = parse_sha256_hex(
      value_after(lines[7], "store_sha256"), "store");
  result.species_authority_sha256 = parse_sha256_hex(
      value_after(lines[10], "species_authority_sha256"), "species authority");
  result.pattern_registry_sha256 = parse_sha256_hex(
      value_after(lines[11], "pattern_registry_sha256"), "pattern registry");
  result.truth_semantics_sha256 = parse_sha256_hex(
      value_after(lines[12], "truth_semantics_sha256"), "truth semantics");
  result.pattern_count = parse_u64_decimal(
      value_after(lines[13], "pattern_count"), "pattern_count");
  if (!valid_run_store_id(result.run_store_id) ||
      !valid_component_basename(result.store_component)) {
    fail(ErrorCode::store_corrupt, "manifest run ID or component is invalid");
  }
  if (render_manifest(result) != bytes) {
    fail(ErrorCode::store_corrupt, "manifest is not canonical byte-for-byte");
  }
  return result;
}

}  // namespace engine002
}  // namespace splitaligner

