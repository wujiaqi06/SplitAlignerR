#include "engine002_atomic_publish.h"
#include "engine002_disk_store.h"
#include "engine002_errors.h"
#include "engine002_fast_hash.h"
#include "engine002_plan_codec.h"
#include "engine002_species_authority_binding.h"
#include "engine002_store.h"

#include <cassert>
#include <filesystem>
#include <iostream>
#include <memory>
#include <vector>

using namespace splitaligner::engine002;

namespace {

std::vector<std::uint8_t> one(std::uint8_t value) {
  return std::vector<std::uint8_t>{value};
}

SpeciesAuthorityPtr authority() {
  return make_species_authority(
      {"A", "B", "C", "D"},
      {0, 1, 2, 3, kInternalTaxon},
      {one(1), one(2), one(4), one(8), one(3)});
}

std::shared_ptr<const std::vector<std::uint8_t>> record_ab(
    const SpeciesAuthority& value) {
  PlanInput input;
  input.pattern_id = 0;
  input.retained = one(3);
  input.states = {2, 2, 1, 1, 1};
  input.primitive_queries = {one(1), one(1), {}, {}, {}};
  return std::make_shared<const std::vector<std::uint8_t>>(
      encode_plan_record(value, input));
}

std::shared_ptr<const std::vector<std::uint8_t>> record_abc(
    const SpeciesAuthority& value) {
  PlanInput input;
  input.pattern_id = 1;
  input.retained = one(7);
  input.states = {0, 0, 2, 1, 2};
  input.primitive_queries = {one(1), one(2), one(4), {}, one(4)};
  return std::make_shared<const std::vector<std::uint8_t>>(
      encode_plan_record(value, input));
}

}  // namespace

int main() {
  const auto root = std::filesystem::canonical(
                        std::filesystem::temp_directory_path()) /
      ("splitalignerr-fix001-sanitizer-" + random_nonce_hex());
  std::filesystem::create_directory(root);
  try {
    const auto species = authority();
    const auto first = record_ab(*species);
    const auto second = record_abc(*species);
    assert(decode_plan_record(*species, *first).retained == one(3));
    TruthPlanView view(species, first, first->data(), first->size(), 1);
    assert(view.snapshot().states == std::vector<std::uint8_t>(
        {2, 2, 1, 1, 1}));

    auto memory = std::make_shared<PackedMemoryStore>(species, 2);
    memory->insert(second);
    memory->insert(first);
    memory->finalize();
    const auto copied = memory->lookup_snapshot(0, one(3));
    memory->close();
    assert(copied.retained == one(3));

    const auto registry =
        make_pattern_registry(species, {one(3), one(7)});
    const std::string run_id = "11111111111111111111111111111111";
    auto disk = std::make_shared<PackedDiskStore>(
        species, registry, root, run_id, 512, UINT64_C(1048576),
        UINT64_C(1048576), UINT64_C(1048576), UINT64_C(3146240));
    disk->insert(first);
    disk->insert(second);
    const auto manifest = disk->finalize_publish(root, run_id);
    assert(disk->lookup_snapshot(0, one(3)).retained == one(3));
    assert(disk->lookup_snapshot(1, one(7)).retained == one(7));
    disk->close();

    auto reopened = PackedDiskStore::open_existing(
        species, manifest, 0, UINT64_C(1048576), UINT64_C(1048576),
        UINT64_C(1048576), UINT64_C(3145728));
    assert(reopened->lookup_snapshot(1, one(7)).retained == one(7));
    assert(reopened->stats().lru.oversized_bypasses == 1);
    reopened->close();

    set_constant_fast_hash_for_tests(true);
    const auto collision_record = record_abc(*species);
    assert(*collision_record == *second);
    StoreBuilder exact_registry(species, 2);
    exact_registry.insert(first);
    exact_registry.insert(collision_record);
    assert(exact_registry.finalize().records.size() == 2);
    set_constant_fast_hash_for_tests(false);

    const std::string fault_id = "22222222222222222222222222222222";
    auto faulted = std::make_shared<PackedDiskStore>(
        species, registry, root, fault_id, 0, UINT64_C(1048576),
        UINT64_C(1048576), UINT64_C(1048576), UINT64_C(3145728));
    set_io_faultpoint(3);
    bool caught = false;
    try {
      faulted->insert(first);
    } catch (const EngineError& error) {
      caught = error.code() == ErrorCode::io_failure;
    }
    set_io_faultpoint(0);
    assert(caught);
    assert(!std::filesystem::exists(
        root / (fault_id + ".truthstore.manifest")));

    std::error_code cleanup;
    std::filesystem::remove_all(root, cleanup);
    std::cout << "FIX001_SANITIZER_HARNESS_PASS\n";
    return 0;
  } catch (const std::exception& error) {
    set_io_faultpoint(0);
    set_constant_fast_hash_for_tests(false);
    std::error_code cleanup;
    std::filesystem::remove_all(root, cleanup);
    std::cerr << error.what() << '\n';
    return 1;
  }
}
