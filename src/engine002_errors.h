#ifndef SPLITALIGNERR_ENGINE002_ERRORS_HPP
#define SPLITALIGNERR_ENGINE002_ERRORS_HPP

#include <stdexcept>
#include <string>

namespace splitaligner {
namespace engine002 {

enum class ErrorCode {
  invalid_argument,
  schema_mismatch,
  authority_mismatch,
  pattern_mismatch,
  store_corrupt,
  incomplete_run,
  duplicate_record,
  duplicate_pattern,
  invalid_state,
  store_busy,
  context_closed,
  memory_budget,
  allocation_failure,
  io_failure,
  disk_full,
  unsupported_atomicity,
  interrupted,
  scientific_invariant,
  internal_failure
};

inline const char* error_code_name(ErrorCode code) noexcept {
  switch (code) {
    case ErrorCode::invalid_argument: return "ENGINE_INVALID_ARGUMENT";
    case ErrorCode::schema_mismatch: return "ENGINE_SCHEMA_MISMATCH";
    case ErrorCode::authority_mismatch: return "ENGINE_AUTHORITY_MISMATCH";
    case ErrorCode::pattern_mismatch: return "ENGINE_PATTERN_MISMATCH";
    case ErrorCode::store_corrupt: return "ENGINE_STORE_CORRUPT";
    case ErrorCode::incomplete_run: return "ENGINE_INCOMPLETE_RUN";
    case ErrorCode::duplicate_record: return "ENGINE_DUPLICATE_RECORD";
    case ErrorCode::duplicate_pattern: return "ENGINE_DUPLICATE_PATTERN";
    case ErrorCode::invalid_state: return "ENGINE_INVALID_STATE";
    case ErrorCode::store_busy: return "ENGINE_STORE_BUSY";
    case ErrorCode::context_closed: return "ENGINE_CONTEXT_CLOSED";
    case ErrorCode::memory_budget: return "ENGINE_MEMORY_BUDGET";
    case ErrorCode::allocation_failure: return "ENGINE_ALLOCATION_FAILURE";
    case ErrorCode::io_failure: return "ENGINE_IO_FAILURE";
    case ErrorCode::disk_full: return "ENGINE_DISK_FULL";
    case ErrorCode::unsupported_atomicity: return "ENGINE_UNSUPPORTED_ATOMICITY";
    case ErrorCode::interrupted: return "ENGINE_INTERRUPTED";
    case ErrorCode::scientific_invariant: return "ENGINE_SCIENTIFIC_INVARIANT";
    case ErrorCode::internal_failure: return "ENGINE_INTERNAL_FAILURE";
  }
  return "ENGINE_INTERNAL_FAILURE";
}

class EngineError : public std::runtime_error {
 public:
  EngineError(ErrorCode code, const std::string& message)
      : std::runtime_error(message), code_(code) {}

  ErrorCode code() const noexcept { return code_; }

 private:
  ErrorCode code_;
};

[[noreturn]] inline void fail(ErrorCode code, const std::string& message) {
  throw EngineError(code, message);
}

}  // namespace engine002
}  // namespace splitaligner

#endif

