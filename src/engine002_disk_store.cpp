#include "engine002_disk_store.h"

#include "engine002_atomic_publish.h"
#include "engine002_checked_math.h"
#include "engine002_endian.h"
#include "engine002_errors.h"

#include <algorithm>
#include <array>
#include <fstream>
#include <limits>

namespace splitaligner {
namespace engine002 {
namespace {

constexpr std::size_t kStoreHeaderBytes = 256;
constexpr std::size_t kIndexEntryBytes = 64;
constexpr std::size_t kStoreFooterBytes = 128;
constexpr std::uint64_t kBuilderMetadataCharge = 4096;

void append_domain(Sha256State& state, const char* domain) {
  const std::size_t length = std::char_traits<char>::length(domain);
  state.update(reinterpret_cast<const std::uint8_t*>(domain), length);
  const std::uint8_t zero = 0;
  state.update(&zero, 1);
}

void update_u64(Sha256State& state, std::uint64_t value) {
  std::array<std::uint8_t, 8> bytes{};
  store_u64_le(bytes.data(), value);
  state.update(bytes.data(), bytes.size());
}

void update_blob(Sha256State& state, const std::uint8_t* bytes,
                 std::uint64_t size) {
  update_u64(state, size);
  state.update(bytes, checked_size(size, "SHA-256 blob"));
}

void copy_sha(std::uint8_t* destination, const Sha256& source) {
  std::copy(source.begin(), source.end(), destination);
}

Sha256 sha_at(const std::uint8_t* bytes) {
  Sha256 out{};
  std::copy(bytes, bytes + out.size(), out.begin());
  return out;
}

bool all_zero(const std::uint8_t* begin, const std::uint8_t* end) {
  return std::all_of(begin, end, [](std::uint8_t value) { return value == 0; });
}

std::vector<std::uint8_t> build_header(const PatternRegistry& registry,
                                       std::uint64_t pattern_count,
                                       std::uint64_t records_bytes,
                                       std::uint64_t index_offset,
                                       std::uint64_t footer_offset,
                                       std::uint64_t file_bytes) {
  std::vector<std::uint8_t> header(kStoreHeaderBytes, 0);
  std::copy_n(reinterpret_cast<const std::uint8_t*>("SATRST01"), 8,
              header.data());
  store_u16_le(header.data() + 8, 1U);
  store_u16_le(header.data() + 10, 0U);
  store_u16_le(header.data() + 12, 256U);
  store_u16_le(header.data() + 14, 0U);
  header[16] = 1U;
  header[17] = 1U;
  store_u16_le(header.data() + 18, 1U);
  store_u16_le(header.data() + 20, 0U);
  store_u16_le(header.data() + 22, 144U);
  store_u16_le(header.data() + 24, 64U);
  store_u16_le(header.data() + 26, 128U);
  store_u32_le(header.data() + 32, registry.authority->global_taxon_count);
  store_u32_le(header.data() + 36, registry.authority->primitive_count);
  store_u64_le(header.data() + 40, pattern_count);
  store_u64_le(header.data() + 48, 256U);
  store_u64_le(header.data() + 56, index_offset);
  store_u64_le(header.data() + 64, footer_offset);
  store_u64_le(header.data() + 72, file_bytes);
  store_u64_le(header.data() + 80, records_bytes);
  store_u64_le(header.data() + 88,
               checked_mul<std::uint64_t>(pattern_count, 64U,
                                          "index bytes"));
  copy_sha(header.data() + 96, registry.authority->fingerprint);
  copy_sha(header.data() + 128, registry.pattern_registry_sha256);
  copy_sha(header.data() + 160, registry.truth_semantics_sha256);
  copy_sha(header.data() + 192, registry.store_identity_sha256);
  store_u64_le(header.data() + 224, xxh64(header.data(), 224, 0));
  return header;
}

std::vector<std::uint8_t> build_footer(
    std::uint64_t pattern_count, std::uint64_t file_bytes,
    std::uint64_t records_xxh64, std::uint64_t index_xxh64,
    const Sha256& payload_sha) {
  std::vector<std::uint8_t> footer(kStoreFooterBytes, 0);
  std::copy_n(reinterpret_cast<const std::uint8_t*>("SATDONE1"), 8,
              footer.data());
  store_u16_le(footer.data() + 8, 1U);
  store_u16_le(footer.data() + 10, 0U);
  store_u16_le(footer.data() + 12, 128U);
  store_u16_le(footer.data() + 14, 0U);
  store_u64_le(footer.data() + 16, pattern_count);
  store_u64_le(footer.data() + 24, file_bytes);
  store_u64_le(footer.data() + 32, records_xxh64);
  store_u64_le(footer.data() + 40, index_xxh64);
  copy_sha(footer.data() + 48, payload_sha);
  std::vector<std::uint8_t> footer_for_hash = footer;
  std::fill(footer_for_hash.begin() + 80, footer_for_hash.begin() + 120, 0);
  store_u64_le(footer.data() + 112, xxh64(footer_for_hash));
  return footer;
}

void append_index_entry(std::vector<std::uint8_t>& index,
                        const DecodedPlan& decoded,
                        std::uint64_t record_offset,
                        std::uint64_t record_bytes) {
  const std::size_t begin = index.size();
  index.resize(checked_add<std::size_t>(
      begin, kIndexEntryBytes, "streaming index append"), 0);
  std::uint8_t* entry = index.data() + begin;
  store_u64_le(entry, decoded.pattern_id);
  store_u64_le(entry + 8, record_offset);
  store_u64_le(entry + 16, record_bytes);
  copy_sha(entry + 24, decoded.retained_pattern_sha256);
  store_u64_le(entry + 56, decoded.record_xxh64);
}

std::uint64_t xxh_file_region(const std::filesystem::path& path,
                              std::uint64_t offset, std::uint64_t bytes) {
  std::ifstream input(path, std::ios::binary);
  if (!input) fail(ErrorCode::io_failure, "cannot open store checksum region");
  if (offset > static_cast<std::uint64_t>(
                   std::numeric_limits<std::streamoff>::max())) {
    fail(ErrorCode::io_failure, "store checksum offset exceeds streamoff");
  }
  input.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
  Xxh64State state;
  std::array<std::uint8_t, 1U << 20U> buffer{};
  std::uint64_t remaining = bytes;
  while (remaining != 0) {
    const std::size_t chunk = static_cast<std::size_t>(
        std::min<std::uint64_t>(remaining, buffer.size()));
    input.read(reinterpret_cast<char*>(buffer.data()), chunk);
    if (input.gcount() != static_cast<std::streamsize>(chunk)) {
      fail(ErrorCode::io_failure, "store checksum short read");
    }
    state.update(buffer.data(), chunk);
    remaining -= chunk;
  }
  return state.digest();
}

Sha256 normalized_file_sha(const std::filesystem::path& path,
                           std::uint64_t file_bytes,
                           std::uint64_t zero_offset,
                           std::uint64_t zero_bytes) {
  std::ifstream input(path, std::ios::binary);
  if (!input) fail(ErrorCode::io_failure, "cannot open store for normalized SHA");
  Sha256State state;
  std::array<std::uint8_t, 1U << 20U> buffer{};
  std::uint64_t position = 0;
  while (position < file_bytes) {
    const std::size_t chunk = static_cast<std::size_t>(
        std::min<std::uint64_t>(file_bytes - position, buffer.size()));
    input.read(reinterpret_cast<char*>(buffer.data()), chunk);
    if (input.gcount() != static_cast<std::streamsize>(chunk)) {
      fail(ErrorCode::io_failure, "normalized SHA short read");
    }
    const std::uint64_t chunk_end = position + chunk;
    const std::uint64_t zero_end = zero_offset + zero_bytes;
    if (position < zero_end && chunk_end > zero_offset) {
      const std::size_t begin = static_cast<std::size_t>(
          std::max(position, zero_offset) - position);
      const std::size_t end = static_cast<std::size_t>(
          std::min(chunk_end, zero_end) - position);
      std::fill(buffer.begin() + begin, buffer.begin() + end, 0);
    }
    state.update(buffer.data(), chunk);
    position = chunk_end;
  }
  return state.digest();
}

std::uint64_t index_charge(const std::vector<DiskIndexEntry>& index) {
  std::uint64_t charge = 0;
  for (const auto& entry : index) {
    charge = checked_add<std::uint64_t>(
        charge,
        HardBoundedLru::charged_bytes(64U, entry.retained.size()),
        "disk index charged bytes");
  }
  return charge;
}

}  // namespace

ValidatedDiskStore validate_disk_store(
    const SpeciesAuthority& authority,
    const std::filesystem::path& component_path,
    const StoreManifest* manifest,
    std::uint64_t scratch_budget,
    std::uint64_t index_budget,
    std::uint64_t metadata_budget) {
  const std::uint64_t file_size = exact_file_size(component_path);
  if (file_size < kStoreHeaderBytes + kStoreFooterBytes) {
    fail(ErrorCode::store_corrupt, "store component is truncated");
  }
  const auto header = read_file_range(component_path, 0, kStoreHeaderBytes,
                                      kStoreHeaderBytes);
  if (!std::equal(header.begin(), header.begin() + 8,
                  reinterpret_cast<const std::uint8_t*>("SATRST01")) ||
      load_u16_le(header.data() + 8) != 1U ||
      load_u16_le(header.data() + 10) != 0U ||
      load_u16_le(header.data() + 12) != 256U ||
      load_u16_le(header.data() + 14) != 0U || header[16] != 1U ||
      header[17] != 1U || load_u16_le(header.data() + 18) != 1U ||
      load_u16_le(header.data() + 20) != 0U ||
      load_u16_le(header.data() + 22) != 144U ||
      load_u16_le(header.data() + 24) != 64U ||
      load_u16_le(header.data() + 26) != 128U) {
    fail(ErrorCode::schema_mismatch, "store header schema is unsupported");
  }
  if (!all_zero(header.data() + 28, header.data() + 32) ||
      !all_zero(header.data() + 232, header.data() + 256) ||
      load_u64_le(header.data() + 224) != xxh64(header.data(), 224, 0)) {
    fail(ErrorCode::store_corrupt, "store header reserved/checksum bytes fail");
  }
  const std::uint64_t pattern_count = load_u64_le(header.data() + 40);
  const std::uint64_t records_start = load_u64_le(header.data() + 48);
  const std::uint64_t index_offset = load_u64_le(header.data() + 56);
  const std::uint64_t footer_offset = load_u64_le(header.data() + 64);
  const std::uint64_t exact_bytes = load_u64_le(header.data() + 72);
  const std::uint64_t records_bytes = load_u64_le(header.data() + 80);
  const std::uint64_t index_bytes = load_u64_le(header.data() + 88);
  if (load_u32_le(header.data() + 32) != authority.global_taxon_count ||
      load_u32_le(header.data() + 36) != authority.primitive_count ||
      !constant_time_equal(sha_at(header.data() + 96), authority.fingerprint)) {
    fail(ErrorCode::authority_mismatch, "store authority binding failed");
  }
  if (records_start != 256U || index_offset != 256U + records_bytes ||
      index_bytes != checked_mul<std::uint64_t>(pattern_count, 64U,
                                                "store index bytes") ||
      footer_offset != index_offset + index_bytes ||
      exact_bytes != footer_offset + 128U || exact_bytes != file_size) {
    fail(ErrorCode::store_corrupt, "store section geometry is invalid");
  }
  if (index_bytes > index_budget) {
    fail(ErrorCode::memory_budget, "wire index exceeds disk-index budget");
  }
  const auto index_wire = read_file_range(component_path, index_offset,
                                           index_bytes, index_budget);
  const auto footer = read_file_range(component_path, footer_offset,
                                       kStoreFooterBytes, kStoreFooterBytes);
  if (!std::equal(footer.begin(), footer.begin() + 8,
                  reinterpret_cast<const std::uint8_t*>("SATDONE1")) ||
      load_u16_le(footer.data() + 8) != 1U ||
      load_u16_le(footer.data() + 10) != 0U ||
      load_u16_le(footer.data() + 12) != 128U ||
      load_u16_le(footer.data() + 14) != 0U ||
      load_u64_le(footer.data() + 16) != pattern_count ||
      load_u64_le(footer.data() + 24) != file_size ||
      !all_zero(footer.data() + 120, footer.data() + 128)) {
    fail(ErrorCode::store_corrupt, "completion footer is invalid");
  }
  auto footer_normalized = footer;
  std::fill(footer_normalized.begin() + 80, footer_normalized.begin() + 120, 0);
  if (load_u64_le(footer.data() + 112) != xxh64(footer_normalized)) {
    fail(ErrorCode::store_corrupt, "footer checksum mismatch");
  }
  if (load_u64_le(footer.data() + 32) !=
          xxh_file_region(component_path, records_start, records_bytes) ||
      load_u64_le(footer.data() + 40) != xxh64(index_wire)) {
    fail(ErrorCode::store_corrupt, "records or index checksum mismatch");
  }
  const Sha256 normalized = normalized_file_sha(
      component_path, file_size, footer_offset + 80U, 32U);
  if (!constant_time_equal(normalized, sha_at(footer.data() + 80))) {
    fail(ErrorCode::store_corrupt, "complete-file SHA-256 mismatch");
  }

  ValidatedDiskStore result;
  result.component_path = component_path;
  result.index.reserve(checked_size(pattern_count, "disk index count"));
  std::vector<std::vector<std::uint8_t>> patterns;
  patterns.reserve(result.index.capacity());
  Sha256State payload_state;
  append_domain(payload_state, "SplitAlignerR/TruthPlanPayloadAggregate/v1");
  update_u64(payload_state, pattern_count);
  std::uint64_t expected_offset = records_start;
  for (std::uint64_t i = 0; i < pattern_count; ++i) {
    const std::uint8_t* entry = index_wire.data() + i * 64U;
    DiskIndexEntry parsed;
    parsed.pattern_id = load_u64_le(entry);
    parsed.record_offset = load_u64_le(entry + 8);
    parsed.record_bytes = load_u64_le(entry + 16);
    parsed.pattern_sha256 = sha_at(entry + 24);
    parsed.record_xxh64 = load_u64_le(entry + 56);
    if (parsed.pattern_id != i || parsed.record_offset != expected_offset ||
        parsed.record_bytes < kPlanHeaderBytes ||
        parsed.record_bytes > index_offset - parsed.record_offset) {
      fail(ErrorCode::store_corrupt, "index record boundary is invalid");
    }
    if (parsed.record_bytes > scratch_budget) {
      fail(ErrorCode::memory_budget,
           "record exceeds validation single-plan scratch budget");
    }
    const auto record = read_file_range(component_path, parsed.record_offset,
                                        parsed.record_bytes, scratch_budget);
    const DecodedPlan decoded = decode_plan_record(authority, record);
    if (decoded.pattern_id != i ||
        !constant_time_equal(decoded.retained_pattern_sha256,
                             parsed.pattern_sha256) ||
        decoded.record_xxh64 != parsed.record_xxh64) {
      fail(ErrorCode::store_corrupt, "index and record identity differ");
    }
    parsed.retained = decoded.retained;
    parsed.lookup_fast_hash = fast_hash_bytes(
        FastHashDomain::record_index, parsed.retained,
        constant_fast_hash_for_tests());
    if (!patterns.empty() && !(patterns.back() < parsed.retained)) {
      fail(ErrorCode::duplicate_pattern,
           "disk patterns are not canonical and unique");
    }
    patterns.push_back(parsed.retained);
    update_u64(payload_state, i);
    update_blob(payload_state, record.data() + kPlanHeaderBytes,
                record.size() - kPlanHeaderBytes);
    expected_offset = checked_add<std::uint64_t>(
        expected_offset, parsed.record_bytes, "validated record end");
    result.index.push_back(std::move(parsed));
  }
  if (expected_offset != index_offset ||
      !constant_time_equal(payload_state.digest(), sha_at(footer.data() + 48))) {
    fail(ErrorCode::store_corrupt,
         "record region end or payload aggregate SHA-256 mismatch");
  }
  const Sha256 registry = pattern_registry_fingerprint(
      authority.global_taxon_count, patterns);
  const Sha256 semantics = truth_semantics_fingerprint();
  const Sha256 identity = store_identity_fingerprint(
      authority.fingerprint, registry, semantics);
  if (!constant_time_equal(registry, sha_at(header.data() + 128)) ||
      !constant_time_equal(semantics, sha_at(header.data() + 160)) ||
      !constant_time_equal(identity, sha_at(header.data() + 192))) {
    fail(ErrorCode::pattern_mismatch, "store registry/semantics identity failed");
  }
  result.store_identity_sha256 = identity;
  result.manifest.state = ManifestState::incomplete;
  result.manifest.store_bytes = file_size;
  result.manifest.store_sha256 = sha256_file(component_path);
  result.manifest.species_authority_sha256 = authority.fingerprint;
  result.manifest.pattern_registry_sha256 = registry;
  result.manifest.truth_semantics_sha256 = semantics;
  result.manifest.pattern_count = pattern_count;
  if (index_charge(result.index) > index_budget) {
    fail(ErrorCode::memory_budget, "decoded index exceeds disk-index budget");
  }
  if (metadata_budget < 4096U) {
    fail(ErrorCode::memory_budget, "metadata budget is below v1 minimum");
  }
  if (manifest != nullptr) {
    if (manifest->state != ManifestState::validated ||
        manifest->store_bytes != file_size ||
        manifest->pattern_count != pattern_count ||
        !constant_time_equal(manifest->store_sha256,
                             result.manifest.store_sha256) ||
        !constant_time_equal(manifest->species_authority_sha256,
                             authority.fingerprint) ||
        !constant_time_equal(manifest->pattern_registry_sha256, registry) ||
        !constant_time_equal(manifest->truth_semantics_sha256, semantics)) {
      fail(ErrorCode::incomplete_run,
           "final manifest and store component do not agree");
    }
    result.manifest = *manifest;
  }
  return result;
}

PackedDiskStore::PackedDiskStore(
    SpeciesAuthorityPtr authority, PatternRegistryPtr registry,
    const std::filesystem::path& directory, const std::string& run_store_id,
    std::uint64_t cache_budget, std::uint64_t scratch_budget,
    std::uint64_t index_budget, std::uint64_t metadata_budget,
    std::uint64_t combined_runtime_bound)
    : authority_(std::move(authority)), registry_(std::move(registry)),
      constant_fast_hash_(constant_fast_hash_for_tests()),
      state_(StoreState::building), generation_(1), writer_(),
      directory_(directory), run_store_id_(run_store_id), component_temp_(),
      candidate_temp_(), validated_temp_(), component_final_(),
      manifest_final_(), index_wire_(), records_hash_(), payload_hash_(),
      next_pattern_id_(0), records_bytes_(0),
      builder_charged_bytes_(kBuilderMetadataCharge),
      builder_charged_high_water_(kBuilderMetadataCharge),
      current_record_high_water_(0), write_buffer_high_water_(0),
      temporary_disk_high_water_(0), component_path_(), manifest_path_(),
      index_(),
      cache_(std::make_shared<HardBoundedLru>(cache_budget, scratch_budget)),
      cache_budget_(cache_budget), scratch_budget_(scratch_budget),
      index_budget_(index_budget), metadata_budget_(metadata_budget),
      combined_runtime_bound_(combined_runtime_bound), file_bytes_(0),
      index_charged_bytes_(0), metadata_charged_bytes_(4096) {
  if (!authority_ || !registry_ || registry_->authority.get() != authority_.get()) {
    fail(ErrorCode::authority_mismatch,
         "streaming disk store requires its exact authority registry");
  }
  if (!valid_run_store_id(run_store_id_)) {
    fail(ErrorCode::invalid_argument, "run_store_id must be 32 lowercase hex");
  }
  reject_symlink_path(directory_);
  const std::uint64_t index_bytes = checked_mul<std::uint64_t>(
      registry_->retained_patterns.size(), kIndexEntryBytes,
      "streaming index bytes");
  if (index_bytes > index_budget_) {
    fail(ErrorCode::memory_budget, "streaming index exceeds disk-index budget");
  }
  index_wire_.reserve(checked_size(index_bytes, "streaming index reserve"));
  validate_runtime_budgets();
  append_domain(payload_hash_, "SplitAlignerR/TruthPlanPayloadAggregate/v1");
  update_u64(payload_hash_, registry_->retained_patterns.size());

  const std::string nonce = random_nonce_hex();
  const std::string component_name = run_store_id_ + ".truthstore.bin";
  const std::string manifest_name = run_store_id_ + ".truthstore.manifest";
  component_final_ = directory_ / component_name;
  manifest_final_ = directory_ / manifest_name;
  component_temp_ = directory_ /
      (component_name + ".engine002-tmp-" + nonce);
  candidate_temp_ = directory_ /
      (manifest_name + ".candidate.engine002-tmp-" + nonce);
  validated_temp_ = directory_ /
      (manifest_name + ".validated.engine002-tmp-" + nonce);
  try {
    writer_ = std::make_unique<ExclusiveBinaryWriter>(component_temp_);
    std::array<std::uint8_t, kStoreHeaderBytes> placeholder{};
    writer_->write_all(placeholder.data(), placeholder.size(),
                       WriterRegion::header);
    temporary_disk_high_water_ = kStoreHeaderBytes;
  } catch (...) {
    cleanup_builder_temporary();
    throw;
  }
}

PackedDiskStore::PackedDiskStore(
    SpeciesAuthorityPtr authority, const ValidatedDiskStore& validated,
    const std::filesystem::path& manifest_path, std::uint64_t cache_budget,
    std::uint64_t scratch_budget, std::uint64_t index_budget,
    std::uint64_t metadata_budget, std::uint64_t combined_runtime_bound)
    : authority_(std::move(authority)), registry_(),
      constant_fast_hash_(constant_fast_hash_for_tests()),
      state_(StoreState::open_validated), generation_(1), writer_(),
      directory_(), run_store_id_(), component_temp_(), candidate_temp_(),
      validated_temp_(), component_final_(), manifest_final_(), index_wire_(),
      records_hash_(), payload_hash_(), next_pattern_id_(0), records_bytes_(0),
      builder_charged_bytes_(0), builder_charged_high_water_(0),
      current_record_high_water_(0), write_buffer_high_water_(0),
      temporary_disk_high_water_(0),
      component_path_(validated.component_path), manifest_path_(manifest_path),
      index_(validated.index),
      cache_(std::make_shared<HardBoundedLru>(cache_budget, scratch_budget)),
      cache_budget_(cache_budget), scratch_budget_(scratch_budget),
      index_budget_(index_budget), metadata_budget_(metadata_budget),
      combined_runtime_bound_(combined_runtime_bound),
      file_bytes_(validated.manifest.store_bytes),
      index_charged_bytes_(index_charge(index_)), metadata_charged_bytes_(4096) {
  for (auto& entry : index_) {
    entry.lookup_fast_hash = fast_hash_bytes(
        FastHashDomain::disk_lookup, entry.retained, constant_fast_hash_);
  }
  validate_runtime_budgets();
}

PackedDiskStore::~PackedDiskStore() noexcept {
  cleanup_builder_temporary();
}

void PackedDiskStore::cleanup_builder_temporary() noexcept {
  writer_.reset();
  remove_recognized_temp(component_temp_);
  remove_recognized_temp(candidate_temp_);
  remove_recognized_temp(validated_temp_);
}

void PackedDiskStore::update_builder_high_water(
    std::uint64_t current_record_bytes) {
  current_record_high_water_ = std::max(current_record_high_water_,
                                        current_record_bytes);
  builder_charged_bytes_ = checked_add<std::uint64_t>(
      index_wire_.size(), kBuilderMetadataCharge,
      "streaming builder charged bytes");
  std::uint64_t working = checked_add<std::uint64_t>(
      builder_charged_bytes_, current_record_bytes,
      "streaming builder working bytes");
  working = checked_add<std::uint64_t>(
      working, write_buffer_high_water_, "streaming builder working bytes");
  builder_charged_high_water_ = std::max(builder_charged_high_water_, working);
}

void PackedDiskStore::validate_runtime_budgets() const {
  if (index_charged_bytes_ > index_budget_ ||
      metadata_charged_bytes_ > metadata_budget_) {
    fail(ErrorCode::memory_budget, "disk index or metadata budget is exceeded");
  }
  std::uint64_t total = checked_add<std::uint64_t>(
      cache_budget_, scratch_budget_, "combined truth-store budget");
  total = checked_add<std::uint64_t>(total, index_budget_,
                                     "combined truth-store budget");
  total = checked_add<std::uint64_t>(total, metadata_budget_,
                                     "combined truth-store budget");
  if (total > combined_runtime_bound_) {
    fail(ErrorCode::memory_budget,
         "declared truth-store sub-budgets exceed combined bound");
  }
}

std::shared_ptr<PackedDiskStore> PackedDiskStore::open_existing(
    SpeciesAuthorityPtr authority, const std::filesystem::path& manifest_path,
    std::uint64_t cache_budget, std::uint64_t scratch_budget,
    std::uint64_t index_budget, std::uint64_t metadata_budget,
    std::uint64_t combined_runtime_bound) {
  if (!authority) fail(ErrorCode::invalid_argument, "disk open requires authority");
  const StoreManifest manifest = parse_manifest(
      read_text_file(manifest_path, UINT64_C(1048576)));
  if (manifest.state != ManifestState::validated) {
    fail(ErrorCode::incomplete_run, "manifest is not VALIDATED");
  }
  const auto directory = manifest_path.parent_path();
  reject_symlink_path(directory);
  if (manifest.store_component !=
      manifest.run_store_id + ".truthstore.bin") {
    fail(ErrorCode::store_corrupt,
         "manifest component name is not bound to run_store_id");
  }
  const auto component = directory / manifest.store_component;
  const auto validated = validate_disk_store(
      *authority, component, &manifest, scratch_budget, index_budget,
      metadata_budget);
  return std::shared_ptr<PackedDiskStore>(new PackedDiskStore(
      authority, validated, manifest_path, cache_budget, scratch_budget,
      index_budget, metadata_budget, combined_runtime_bound));
}

void PackedDiskStore::insert(
    std::shared_ptr<const std::vector<std::uint8_t>> record) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_ == StoreState::closed) {
    fail(ErrorCode::context_closed, "disk store is closed");
  }
  if (state_ != StoreState::building) {
    fail(ErrorCode::invalid_state, "disk insertion requires BUILDING state");
  }
  if (!record) fail(ErrorCode::invalid_argument, "cannot insert null record");
  cancellation_point();
  const std::uint64_t pattern_count = registry_->retained_patterns.size();
  if (next_pattern_id_ >= pattern_count) {
    fail(ErrorCode::pattern_mismatch,
         "streaming disk store received too many records");
  }
  const DecodedPlan decoded = decode_plan_record(*authority_, *record);
  if (decoded.pattern_id < next_pattern_id_) {
    fail(ErrorCode::duplicate_record,
         "streaming disk store received a duplicate prior pattern ID");
  }
  if (decoded.pattern_id > next_pattern_id_) {
    fail(ErrorCode::pattern_mismatch,
         "streaming disk store requires the next contiguous pattern ID");
  }
  const std::size_t position = checked_size(
      next_pattern_id_, "streaming registry position");
  if (decoded.retained != registry_->retained_patterns[position] ||
      !constant_time_equal(decoded.retained_pattern_sha256,
                           registry_->pattern_sha256[position])) {
    fail(ErrorCode::pattern_mismatch,
         "record retained identity differs from finalized registry");
  }
  const std::uint64_t record_bytes = record->size();
  const std::uint64_t record_offset = checked_add<std::uint64_t>(
      kStoreHeaderBytes, records_bytes_, "streaming record offset");
  update_builder_high_water(record_bytes);
  try {
    writer_->write_all(record->data(), record->size(), WriterRegion::record);
  } catch (...) {
    state_ = StoreState::closed;
    ++generation_;
    cleanup_builder_temporary();
    throw;
  }
  records_hash_.update(record->data(), record->size());
  update_u64(payload_hash_, decoded.pattern_id);
  update_blob(payload_hash_, record->data() + kPlanHeaderBytes,
              record_bytes - kPlanHeaderBytes);
  append_index_entry(index_wire_, decoded, record_offset, record_bytes);
  records_bytes_ = checked_add<std::uint64_t>(
      records_bytes_, record_bytes, "streaming records bytes");
  next_pattern_id_ = checked_add<std::uint64_t>(
      next_pattern_id_, 1U, "streaming next pattern ID");
  temporary_disk_high_water_ = checked_add<std::uint64_t>(
      kStoreHeaderBytes, records_bytes_, "streaming temporary bytes");
  update_builder_high_water(0);
}

std::filesystem::path PackedDiskStore::finalize_publish(
    const std::filesystem::path& directory, const std::string& run_store_id) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_ == StoreState::closed) {
    fail(ErrorCode::context_closed, "disk store is closed");
  }
  if (state_ == StoreState::open_validated) return manifest_path_;
  if (state_ != StoreState::building) {
    fail(ErrorCode::invalid_state, "disk finalization requires BUILDING state");
  }
  if (directory != directory_ || run_store_id != run_store_id_) {
    fail(ErrorCode::invalid_argument,
         "finalization destination differs from construction destination");
  }
  const std::uint64_t pattern_count = registry_->retained_patterns.size();
  if (next_pattern_id_ != pattern_count) {
    fail(ErrorCode::incomplete_run,
         "streaming disk store was finalized before all records arrived");
  }
  const std::uint64_t index_offset = checked_add<std::uint64_t>(
      kStoreHeaderBytes, records_bytes_, "store index offset");
  const std::uint64_t index_bytes = checked_mul<std::uint64_t>(
      pattern_count, kIndexEntryBytes, "store index bytes");
  if (index_bytes != index_wire_.size()) {
    fail(ErrorCode::internal_failure,
         "streaming index size differs from finalized registry");
  }
  const std::uint64_t footer_offset = checked_add<std::uint64_t>(
      index_offset, index_bytes, "store footer offset");
  const std::uint64_t file_bytes = checked_add<std::uint64_t>(
      footer_offset, 128U, "store file bytes");
  const auto header = build_header(*registry_, pattern_count, records_bytes_,
                                   index_offset, footer_offset, file_bytes);
  auto footer = build_footer(pattern_count, file_bytes,
                             records_hash_.digest(), xxh64(index_wire_),
                             payload_hash_.digest());

  const std::string component_name = run_store_id_ + ".truthstore.bin";
  bool manifest_published = false;
  bool component_published = false;
  try {
    cancellation_point();
    publication_failpoint(1);
    writer_->write_all(index_wire_.data(), index_wire_.size(),
                       WriterRegion::index);
    publication_failpoint(2);
    writer_->seek(0);
    writer_->write_all(header.data(), header.size(), WriterRegion::header);
    publication_failpoint(3);
    writer_->seek(footer_offset);
    writer_->write_all(footer.data(), footer.size(), WriterRegion::footer);
    publication_failpoint(4);
    writer_->sync();
    publication_failpoint(5);
    const Sha256 complete_sha = normalized_file_sha(
        component_temp_, file_bytes, footer_offset + 80U, 32U);
    writer_->seek(footer_offset + 80U);
    writer_->write_all(complete_sha.data(), complete_sha.size(),
                       WriterRegion::footer);
    writer_->sync();
    writer_->close();
    writer_.reset();
    publication_failpoint(6);
    const auto temporary_validated = validate_disk_store(
        *authority_, component_temp_, nullptr, scratch_budget_, index_budget_,
        metadata_budget_);
    publication_failpoint(7);
    const Sha256 actual_sha = temporary_validated.manifest.store_sha256;
    publication_failpoint(8);
    StoreManifest candidate;
    candidate.state = ManifestState::incomplete;
    candidate.run_store_id = run_store_id_;
    candidate.store_component = component_name;
    candidate.store_bytes = file_bytes;
    candidate.store_sha256 = actual_sha;
    candidate.species_authority_sha256 = authority_->fingerprint;
    candidate.pattern_registry_sha256 = registry_->pattern_registry_sha256;
    candidate.truth_semantics_sha256 = registry_->truth_semantics_sha256;
    candidate.pattern_count = pattern_count;
    write_text_exclusive(candidate_temp_, render_manifest(candidate));
    parse_manifest(read_text_file(candidate_temp_, UINT64_C(1048576)));
    publication_failpoint(9);
    StoreManifest final_manifest = candidate;
    final_manifest.state = ManifestState::validated;
    write_text_exclusive(validated_temp_, render_manifest(final_manifest));
    parse_manifest(read_text_file(validated_temp_, UINT64_C(1048576)));
    publication_failpoint(10);
    publish_no_replace(component_temp_, component_final_);
    component_published = true;
    publication_failpoint(11);
    const auto final_validated = validate_disk_store(
        *authority_, component_final_, &final_manifest, scratch_budget_,
        index_budget_, metadata_budget_);
    publication_failpoint(12);
    publish_no_replace(validated_temp_, manifest_final_);
    manifest_published = true;
    publication_failpoint(13);
    sync_directory(directory_);
    publication_failpoint(14);
    remove_recognized_temp(candidate_temp_);
    publication_failpoint(15);

    registry_.reset();
    index_wire_.clear();
    index_wire_.shrink_to_fit();
    builder_charged_bytes_ = 0;
    component_path_ = component_final_;
    manifest_path_ = manifest_final_;
    index_ = final_validated.index;
    for (auto& entry : index_) {
      entry.lookup_fast_hash = fast_hash_bytes(
          FastHashDomain::disk_lookup, entry.retained, constant_fast_hash_);
    }
    file_bytes_ = file_bytes;
    temporary_disk_high_water_ = std::max(temporary_disk_high_water_, file_bytes);
    index_charged_bytes_ = index_charge(index_);
    validate_runtime_budgets();
    state_ = StoreState::open_validated;
    return manifest_path_;
  } catch (...) {
    if (manifest_published) {
      std::error_code cleanup_error;
      const auto status = std::filesystem::symlink_status(
          manifest_final_, cleanup_error);
      if (!cleanup_error && !std::filesystem::is_symlink(status)) {
        std::filesystem::remove(manifest_final_, cleanup_error);
      }
    }
    if (component_published) {
      std::error_code cleanup_error;
      const auto status = std::filesystem::symlink_status(
          component_final_, cleanup_error);
      if (!cleanup_error && !std::filesystem::is_symlink(status)) {
        std::filesystem::remove(component_final_, cleanup_error);
      }
    }
    state_ = StoreState::closed;
    ++generation_;
    registry_.reset();
    index_wire_.clear();
    cleanup_builder_temporary();
    throw;
  }
}

LruLease PackedDiskStore::acquire(
    std::uint64_t pattern_id, const std::vector<std::uint8_t>& retained) {
  DiskIndexEntry entry;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ == StoreState::closed) {
      fail(ErrorCode::context_closed, "disk store is closed");
    }
    if (state_ != StoreState::open_validated) {
      fail(ErrorCode::invalid_state, "disk lookup requires OPEN_VALIDATED state");
    }
    if (pattern_id >= index_.size()) {
      fail(ErrorCode::pattern_mismatch, "disk lookup ID is out of range");
    }
    entry = index_[pattern_id];
    if (entry.lookup_fast_hash != fast_hash_bytes(
            FastHashDomain::disk_lookup, retained, constant_fast_hash_) ||
        entry.retained != retained) {
      fail(ErrorCode::pattern_mismatch,
           "disk lookup retained bits do not match pattern ID");
    }
  }
  const std::uint64_t allocation_limit =
      std::max(cache_budget_, scratch_budget_);
  return cache_->acquire(
      pattern_id, retained, entry.record_bytes,
      [path = component_path_, entry, limit = allocation_limit]() {
        auto bytes = read_file_range(path, entry.record_offset,
                                     entry.record_bytes, limit);
        return std::make_shared<const std::vector<std::uint8_t>>(
            std::move(bytes));
      });
}

DecodedPlan PackedDiskStore::lookup_snapshot(
    std::uint64_t pattern_id, const std::vector<std::uint8_t>& retained) {
  const auto lease = acquire(pattern_id, retained);
  std::uint64_t generation;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    generation = generation_;
  }
  TruthPlanView view(authority_, lease.owner, lease.record->data(),
                     lease.record->size(), generation);
  return view.snapshot();
}

std::shared_ptr<const void> PackedDiskStore::debug_pin(
    std::uint64_t pattern_id, const std::vector<std::uint8_t>& retained) {
  return acquire(pattern_id, retained).owner;
}

void PackedDiskStore::close() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (state_ == StoreState::closed) return;
  cache_->clear();
  cleanup_builder_temporary();
  state_ = StoreState::closed;
  ++generation_;
  registry_.reset();
  index_wire_.clear();
  index_.clear();
}

StoreState PackedDiskStore::state() const noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  return state_;
}

DiskStoreStats PackedDiskStore::stats() const noexcept {
  std::lock_guard<std::mutex> lock(mutex_);
  DiskStoreStats out;
  out.generation = generation_;
  out.pattern_count = registry_ ? registry_->retained_patterns.size()
                                : index_.size();
  out.inserted_count = next_pattern_id_;
  out.file_bytes = file_bytes_;
  out.index_charged_bytes = index_charged_bytes_;
  out.metadata_charged_bytes = metadata_charged_bytes_;
  out.combined_runtime_bound = combined_runtime_bound_;
  out.builder_charged_bytes = builder_charged_bytes_;
  out.builder_charged_high_water = builder_charged_high_water_;
  out.current_record_high_water = current_record_high_water_;
  out.write_buffer_high_water = write_buffer_high_water_;
  out.temporary_disk_high_water = temporary_disk_high_water_;
  out.lru = cache_->stats();
  return out;
}

}  // namespace engine002
}  // namespace splitaligner
