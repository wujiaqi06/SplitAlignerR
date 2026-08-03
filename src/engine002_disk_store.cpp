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

std::vector<std::uint8_t> build_header(const FinalizedPlanSet& plans,
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
  store_u32_le(header.data() + 32, plans.authority->global_taxon_count);
  store_u32_le(header.data() + 36, plans.authority->primitive_count);
  store_u64_le(header.data() + 40, plans.records.size());
  store_u64_le(header.data() + 48, 256U);
  store_u64_le(header.data() + 56, index_offset);
  store_u64_le(header.data() + 64, footer_offset);
  store_u64_le(header.data() + 72, file_bytes);
  store_u64_le(header.data() + 80, records_bytes);
  store_u64_le(header.data() + 88,
               checked_mul<std::uint64_t>(plans.records.size(), 64U,
                                          "index bytes"));
  copy_sha(header.data() + 96, plans.authority->fingerprint);
  copy_sha(header.data() + 128, plans.pattern_registry_sha256);
  copy_sha(header.data() + 160, plans.truth_semantics_sha256);
  copy_sha(header.data() + 192, plans.store_identity_sha256);
  store_u64_le(header.data() + 224, xxh64(header.data(), 224, 0));
  return header;
}

std::vector<std::uint8_t> build_index(const FinalizedPlanSet& plans) {
  const std::size_t bytes = checked_size(checked_mul<std::uint64_t>(
      plans.records.size(), 64U, "index allocation"), "index allocation");
  std::vector<std::uint8_t> index(bytes, 0);
  std::uint64_t offset = 256;
  for (std::size_t i = 0; i < plans.records.size(); ++i) {
    const auto& plan = plans.records[i];
    std::uint8_t* entry = index.data() + i * kIndexEntryBytes;
    store_u64_le(entry, plan.pattern_id);
    store_u64_le(entry + 8, offset);
    store_u64_le(entry + 16, plan.record->size());
    copy_sha(entry + 24, plan.pattern_sha256);
    store_u64_le(entry + 56, plan.record_xxh64);
    offset = checked_add<std::uint64_t>(offset, plan.record->size(),
                                        "record offset");
  }
  return index;
}

Sha256 payload_aggregate(const FinalizedPlanSet& plans) {
  Sha256State state;
  append_domain(state, "SplitAlignerR/TruthPlanPayloadAggregate/v1");
  update_u64(state, plans.records.size());
  for (const auto& plan : plans.records) {
    update_u64(state, plan.pattern_id);
    const std::uint64_t payload_bytes = plan.record->size() - kPlanHeaderBytes;
    update_blob(state, plan.record->data() + kPlanHeaderBytes, payload_bytes);
  }
  return state.digest();
}

std::vector<std::uint8_t> build_footer(
    const FinalizedPlanSet& plans, std::uint64_t file_bytes,
    std::uint64_t records_xxh64, std::uint64_t index_xxh64,
    const Sha256& payload_sha, const std::vector<std::uint8_t>& header,
    const std::vector<std::uint8_t>& index) {
  std::vector<std::uint8_t> footer(kStoreFooterBytes, 0);
  std::copy_n(reinterpret_cast<const std::uint8_t*>("SATDONE1"), 8,
              footer.data());
  store_u16_le(footer.data() + 8, 1U);
  store_u16_le(footer.data() + 10, 0U);
  store_u16_le(footer.data() + 12, 128U);
  store_u16_le(footer.data() + 14, 0U);
  store_u64_le(footer.data() + 16, plans.records.size());
  store_u64_le(footer.data() + 24, file_bytes);
  store_u64_le(footer.data() + 32, records_xxh64);
  store_u64_le(footer.data() + 40, index_xxh64);
  copy_sha(footer.data() + 48, payload_sha);
  std::vector<std::uint8_t> footer_for_hash = footer;
  std::fill(footer_for_hash.begin() + 80, footer_for_hash.begin() + 120, 0);
  store_u64_le(footer.data() + 112, xxh64(footer_for_hash));

  Sha256State complete;
  complete.update(header.data(), header.size());
  for (const auto& plan : plans.records) {
    complete.update(plan.record->data(), plan.record->size());
  }
  complete.update(index.data(), index.size());
  complete.update(footer.data(), footer.size());
  copy_sha(footer.data() + 80, complete.digest());
  return footer;
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
    SpeciesAuthorityPtr authority, std::uint64_t pattern_count,
    std::uint64_t cache_budget, std::uint64_t scratch_budget,
    std::uint64_t index_budget, std::uint64_t metadata_budget,
    std::uint64_t combined_runtime_bound)
    : authority_(std::move(authority)), state_(StoreState::building),
      generation_(1), builder_(new StoreBuilder(authority_, pattern_count)),
      finalized_(), component_path_(), manifest_path_(), index_(),
      cache_(std::make_shared<HardBoundedLru>(cache_budget, scratch_budget)),
      cache_budget_(cache_budget), scratch_budget_(scratch_budget),
      index_budget_(index_budget), metadata_budget_(metadata_budget),
      combined_runtime_bound_(combined_runtime_bound), file_bytes_(0),
      index_charged_bytes_(0), metadata_charged_bytes_(4096) {
  validate_runtime_budgets();
}

PackedDiskStore::PackedDiskStore(
    SpeciesAuthorityPtr authority, const ValidatedDiskStore& validated,
    const std::filesystem::path& manifest_path, std::uint64_t cache_budget,
    std::uint64_t scratch_budget, std::uint64_t index_budget,
    std::uint64_t metadata_budget, std::uint64_t combined_runtime_bound)
    : authority_(std::move(authority)), state_(StoreState::open_validated),
      generation_(1), builder_(), finalized_(),
      component_path_(validated.component_path), manifest_path_(manifest_path),
      index_(validated.index),
      cache_(std::make_shared<HardBoundedLru>(cache_budget, scratch_budget)),
      cache_budget_(cache_budget), scratch_budget_(scratch_budget),
      index_budget_(index_budget), metadata_budget_(metadata_budget),
      combined_runtime_bound_(combined_runtime_bound),
      file_bytes_(validated.manifest.store_bytes),
      index_charged_bytes_(index_charge(index_)), metadata_charged_bytes_(4096) {
  validate_runtime_budgets();
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
  builder_->insert(std::move(record));
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
  if (!valid_run_store_id(run_store_id)) {
    fail(ErrorCode::invalid_argument, "run_store_id must be 32 lowercase hex");
  }
  reject_symlink_path(directory);
  auto plans = std::make_unique<FinalizedPlanSet>(builder_->finalize());
  std::uint64_t records_bytes = 0;
  Xxh64State records_hash;
  for (const auto& plan : plans->records) {
    records_bytes = checked_add<std::uint64_t>(
        records_bytes, plan.record->size(), "store records bytes");
    records_hash.update(plan.record->data(), plan.record->size());
  }
  const std::uint64_t index_offset = checked_add<std::uint64_t>(
      256U, records_bytes, "store index offset");
  const std::uint64_t index_bytes = checked_mul<std::uint64_t>(
      plans->records.size(), 64U, "store index bytes");
  if (index_bytes > index_budget_) {
    fail(ErrorCode::memory_budget, "store index exceeds disk-index budget");
  }
  const std::uint64_t footer_offset = checked_add<std::uint64_t>(
      index_offset, index_bytes, "store footer offset");
  const std::uint64_t file_bytes = checked_add<std::uint64_t>(
      footer_offset, 128U, "store file bytes");
  const auto header = build_header(*plans, records_bytes, index_offset,
                                   footer_offset, file_bytes);
  const auto index = build_index(*plans);
  const auto footer = build_footer(
      *plans, file_bytes, records_hash.digest(), xxh64(index),
      payload_aggregate(*plans), header, index);

  const std::string nonce = random_nonce_hex();
  const std::string component_name = run_store_id + ".truthstore.bin";
  const std::string manifest_name = run_store_id + ".truthstore.manifest";
  const auto component_final = directory / component_name;
  const auto manifest_final = directory / manifest_name;
  const auto component_temp = directory /
      (component_name + ".engine002-tmp-" + nonce);
  const auto candidate_temp = directory /
      (manifest_name + ".candidate.engine002-tmp-" + nonce);
  const auto validated_temp = directory /
      (manifest_name + ".validated.engine002-tmp-" + nonce);
  bool manifest_published = false;
  try {
    ExclusiveBinaryWriter writer(component_temp);
    publication_failpoint(1);
    std::vector<std::uint8_t> placeholder(kStoreHeaderBytes, 0);
    writer.write_all(placeholder.data(), placeholder.size());
    for (const auto& plan : plans->records) {
      writer.write_all(plan.record->data(), plan.record->size());
    }
    writer.write_all(index.data(), index.size());
    publication_failpoint(2);
    writer.seek(0);
    writer.write_all(header.data(), header.size());
    publication_failpoint(3);
    writer.seek(footer_offset);
    writer.write_all(footer.data(), footer.size());
    publication_failpoint(4);
    writer.sync();
    publication_failpoint(5);
    writer.close();
    publication_failpoint(6);
    const auto temporary_validated = validate_disk_store(
        *authority_, component_temp, nullptr, scratch_budget_, index_budget_,
        metadata_budget_);
    publication_failpoint(7);
    const Sha256 actual_sha = temporary_validated.manifest.store_sha256;
    publication_failpoint(8);
    StoreManifest candidate;
    candidate.state = ManifestState::incomplete;
    candidate.run_store_id = run_store_id;
    candidate.store_component = component_name;
    candidate.store_bytes = file_bytes;
    candidate.store_sha256 = actual_sha;
    candidate.species_authority_sha256 = authority_->fingerprint;
    candidate.pattern_registry_sha256 = plans->pattern_registry_sha256;
    candidate.truth_semantics_sha256 = plans->truth_semantics_sha256;
    candidate.pattern_count = plans->records.size();
    write_text_exclusive(candidate_temp, render_manifest(candidate));
    parse_manifest(read_text_file(candidate_temp, UINT64_C(1048576)));
    publication_failpoint(9);
    StoreManifest final_manifest = candidate;
    final_manifest.state = ManifestState::validated;
    write_text_exclusive(validated_temp, render_manifest(final_manifest));
    parse_manifest(read_text_file(validated_temp, UINT64_C(1048576)));
    publication_failpoint(10);
    publish_no_replace(component_temp, component_final);
    publication_failpoint(11);
    const auto final_validated = validate_disk_store(
        *authority_, component_final, &final_manifest, scratch_budget_,
        index_budget_, metadata_budget_);
    publication_failpoint(12);
    publish_no_replace(validated_temp, manifest_final);
    manifest_published = true;
    publication_failpoint(13);
    sync_directory(directory);
    publication_failpoint(14);
    remove_recognized_temp(candidate_temp);
    publication_failpoint(15);

    finalized_ = std::move(plans);
    builder_.reset();
    component_path_ = component_final;
    manifest_path_ = manifest_final;
    index_ = final_validated.index;
    file_bytes_ = file_bytes;
    index_charged_bytes_ = index_charge(index_);
    validate_runtime_budgets();
    state_ = StoreState::open_validated;
    return manifest_path_;
  } catch (...) {
    if (manifest_published) {
      std::error_code cleanup_error;
      const auto status = std::filesystem::symlink_status(
          manifest_final, cleanup_error);
      if (!cleanup_error && !std::filesystem::is_symlink(status)) {
        std::filesystem::remove(manifest_final, cleanup_error);
      }
    }
    remove_recognized_temp(component_temp);
    remove_recognized_temp(candidate_temp);
    remove_recognized_temp(validated_temp);
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
    if (entry.retained != retained) {
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
  state_ = StoreState::closed;
  ++generation_;
  builder_.reset();
  finalized_.reset();
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
  out.pattern_count = index_.size();
  out.file_bytes = file_bytes_;
  out.index_charged_bytes = index_charged_bytes_;
  out.metadata_charged_bytes = metadata_charged_bytes_;
  out.combined_runtime_bound = combined_runtime_bound_;
  out.lru = cache_->stats();
  return out;
}

}  // namespace engine002
}  // namespace splitaligner
