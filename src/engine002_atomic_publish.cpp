#include "engine002_atomic_publish.h"

#include "engine002_checked_math.h"
#include "engine002_errors.h"

#include <array>
#include <atomic>
#include <cerrno>
#include <cstring>
#include <fstream>
#include <random>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#endif

namespace splitaligner {
namespace engine002 {
namespace {

std::atomic<int> g_publication_failpoint{0};
std::atomic<int> g_io_failpoint{0};

std::string system_message(const char* context) {
  return std::string(context) + ": " + std::strerror(errno);
}

int open_exclusive_binary(const std::filesystem::path& path) {
#ifdef _WIN32
  const int descriptor = _wopen(path.wstring().c_str(),
      _O_CREAT | _O_EXCL | _O_WRONLY | _O_BINARY,
      _S_IREAD | _S_IWRITE);
#else
  const int descriptor = ::open(path.c_str(),
      O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, S_IRUSR | S_IWUSR);
#endif
  if (descriptor < 0) {
    fail(errno == ENOSPC ? ErrorCode::disk_full : ErrorCode::io_failure,
         system_message("exclusive file creation failed"));
  }
  return descriptor;
}

int close_descriptor(int descriptor) noexcept {
#ifdef _WIN32
  return _close(descriptor);
#else
  return ::close(descriptor);
#endif
}

bool consume_io_fault(int expected) noexcept {
  int observed = expected;
  return g_io_failpoint.compare_exchange_strong(observed, 0);
}

void write_descriptor_all(int descriptor, const std::uint8_t* data,
                          std::size_t size) {
  std::size_t written = 0;
  while (written < size) {
#ifdef _WIN32
    const unsigned chunk = static_cast<unsigned>(
        std::min<std::size_t>(size - written, UINT_MAX));
    const int result = _write(descriptor, data + written, chunk);
#else
    const ssize_t result = ::write(descriptor, data + written, size - written);
#endif
    if (result <= 0) {
      fail(errno == ENOSPC ? ErrorCode::disk_full : ErrorCode::io_failure,
           system_message("binary short write"));
    }
    written += static_cast<std::size_t>(result);
  }
}

int partial_fault_for_region(WriterRegion region) noexcept {
  switch (region) {
    case WriterRegion::header: return 2;
    case WriterRegion::record: return 3;
    case WriterRegion::index: return 4;
    case WriterRegion::footer: return 5;
    case WriterRegion::generic: return 0;
  }
  return 0;
}

}  // namespace

ExclusiveBinaryWriter::ExclusiveBinaryWriter(const std::filesystem::path& path)
    : descriptor_(open_exclusive_binary(path)) {}

ExclusiveBinaryWriter::~ExclusiveBinaryWriter() noexcept {
  if (descriptor_ >= 0) close_descriptor(descriptor_);
}

void ExclusiveBinaryWriter::write_all(const std::uint8_t* data,
                                      std::size_t size,
                                      WriterRegion region) {
  if (consume_io_fault(8)) {
    fail(ErrorCode::disk_full, "injected ENOSPC before binary write");
  }
  const int regional_fault = partial_fault_for_region(region);
  if (consume_io_fault(1) ||
      (regional_fault != 0 && consume_io_fault(regional_fault))) {
    const std::size_t partial = size == 0 ? 0 : std::max<std::size_t>(1, size / 2);
    write_descriptor_all(descriptor_, data, partial);
    fail(ErrorCode::io_failure, "injected partial binary write");
  }
  write_descriptor_all(descriptor_, data, size);
}

void ExclusiveBinaryWriter::seek(std::uint64_t offset) {
#ifdef _WIN32
  if (offset > static_cast<std::uint64_t>(LLONG_MAX) ||
      _lseeki64(descriptor_, static_cast<__int64>(offset), SEEK_SET) < 0) {
#else
  if (offset > static_cast<std::uint64_t>(
                   std::numeric_limits<off_t>::max()) ||
      ::lseek(descriptor_, static_cast<off_t>(offset), SEEK_SET) < 0) {
#endif
    fail(ErrorCode::io_failure, system_message("binary seek failed"));
  }
}

void ExclusiveBinaryWriter::sync() {
  if (consume_io_fault(6)) {
    fail(ErrorCode::io_failure, "injected file flush failure");
  }
#ifdef _WIN32
  if (_commit(descriptor_) != 0) {
#else
  if (::fsync(descriptor_) != 0) {
#endif
    fail(ErrorCode::io_failure, system_message("file durability request failed"));
  }
}

void ExclusiveBinaryWriter::close() {
  if (descriptor_ < 0) return;
  const int descriptor = descriptor_;
  descriptor_ = -1;
  const int result = close_descriptor(descriptor);
  if (consume_io_fault(7)) {
    fail(ErrorCode::io_failure, "injected file close failure");
  }
  if (result != 0) {
    fail(ErrorCode::io_failure, system_message("file close failed"));
  }
}

void reject_symlink_path(const std::filesystem::path& directory) {
  std::error_code error;
  const auto absolute = std::filesystem::absolute(directory, error);
  if (error) fail(ErrorCode::io_failure, "cannot resolve destination directory");
  std::filesystem::path current;
  for (const auto& component : absolute) {
    current /= component;
    const auto status = std::filesystem::symlink_status(current, error);
    if (error) {
      fail(ErrorCode::io_failure, "cannot inspect destination path components");
    }
    if (std::filesystem::is_symlink(status)) {
      fail(ErrorCode::unsupported_atomicity,
           "destination path contains a symlink");
    }
  }
  if (!std::filesystem::is_directory(absolute, error) || error) {
    fail(ErrorCode::io_failure, "destination is not an existing directory");
  }
}

std::string random_nonce_hex() {
  std::random_device source;
  static const char digits[] = "0123456789abcdef";
  std::string result(32, '0');
  for (std::size_t i = 0; i < result.size(); i += 8) {
    const std::uint32_t value = source();
    for (std::size_t j = 0; j < 8; ++j) {
      result[i + j] = digits[(value >> (4U * (7U - j))) & 0x0fU];
    }
  }
  return result;
}

std::uint64_t exact_file_size(const std::filesystem::path& path) {
  std::error_code error;
  if (std::filesystem::is_symlink(std::filesystem::symlink_status(path, error))) {
    fail(ErrorCode::io_failure, "refusing to read a symlink component");
  }
  const auto size = std::filesystem::file_size(path, error);
  if (error) fail(ErrorCode::io_failure, "cannot determine component size");
  return static_cast<std::uint64_t>(size);
}

std::vector<std::uint8_t> read_file_range(const std::filesystem::path& path,
                                          std::uint64_t offset,
                                          std::uint64_t bytes,
                                          std::uint64_t allocation_limit) {
  if (bytes > allocation_limit) {
    fail(ErrorCode::memory_budget, "file range exceeds scratch budget");
  }
  const std::uint64_t size = exact_file_size(path);
  if (offset > size || bytes > size - offset) {
    fail(ErrorCode::store_corrupt, "file range is outside component");
  }
  std::ifstream input(path, std::ios::binary);
  if (!input) fail(ErrorCode::io_failure, "cannot open component for reading");
  if (offset > static_cast<std::uint64_t>(
                   std::numeric_limits<std::streamoff>::max())) {
    fail(ErrorCode::io_failure, "file offset exceeds streamoff");
  }
  input.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
  if (!input) fail(ErrorCode::io_failure, "component seek failed");
  std::vector<std::uint8_t> result(checked_size(bytes, "file range"));
  std::size_t cursor = 0;
  while (cursor < result.size()) {
    const std::size_t chunk = std::min<std::size_t>(
        result.size() - cursor,
        static_cast<std::size_t>(std::numeric_limits<std::streamsize>::max()));
    input.read(reinterpret_cast<char*>(result.data() + cursor),
               static_cast<std::streamsize>(chunk));
    if (input.gcount() != static_cast<std::streamsize>(chunk)) {
      fail(ErrorCode::io_failure, "component short read");
    }
    cursor += chunk;
  }
  return result;
}

std::string read_text_file(const std::filesystem::path& path,
                           std::uint64_t byte_limit) {
  const auto bytes = read_file_range(path, 0, exact_file_size(path), byte_limit);
  return std::string(bytes.begin(), bytes.end());
}

Sha256 sha256_file(const std::filesystem::path& path) {
  exact_file_size(path);
  std::ifstream input(path, std::ios::binary);
  if (!input) fail(ErrorCode::io_failure, "cannot open component for SHA-256");
  Sha256State state;
  std::array<std::uint8_t, 1U << 20U> buffer{};
  while (input) {
    input.read(reinterpret_cast<char*>(buffer.data()), buffer.size());
    const std::streamsize count = input.gcount();
    if (count > 0) state.update(buffer.data(), static_cast<std::size_t>(count));
  }
  if (!input.eof()) fail(ErrorCode::io_failure, "component hash read failed");
  return state.digest();
}

void write_text_exclusive(const std::filesystem::path& path,
                          const std::string& text) {
  ExclusiveBinaryWriter writer(path);
  writer.write_all(reinterpret_cast<const std::uint8_t*>(text.data()), text.size());
  writer.sync();
  writer.close();
}

void publish_no_replace(const std::filesystem::path& temporary,
                        const std::filesystem::path& final_path) {
  std::error_code error;
  if (std::filesystem::is_symlink(
          std::filesystem::symlink_status(final_path, error))) {
    fail(ErrorCode::io_failure, "refusing to replace a symlink destination");
  }
#ifdef _WIN32
  if (!MoveFileExW(temporary.wstring().c_str(), final_path.wstring().c_str(),
                   MOVEFILE_WRITE_THROUGH)) {
    const DWORD code = GetLastError();
    fail(code == ERROR_ALREADY_EXISTS || code == ERROR_FILE_EXISTS
             ? ErrorCode::io_failure
             : ErrorCode::unsupported_atomicity,
         "Windows no-replace publication failed");
  }
#else
  if (::link(temporary.c_str(), final_path.c_str()) != 0) {
    fail(errno == EEXIST ? ErrorCode::io_failure
                         : ErrorCode::unsupported_atomicity,
         system_message("POSIX no-replace publication failed"));
  }
  if (::unlink(temporary.c_str()) != 0) {
    fail(ErrorCode::io_failure,
         system_message("published temporary unlink failed"));
  }
#endif
}

void sync_directory(const std::filesystem::path& directory) {
#ifdef _WIN32
  (void)directory;
#else
  const int descriptor = ::open(directory.c_str(), O_RDONLY | O_CLOEXEC);
  if (descriptor < 0) {
    fail(ErrorCode::io_failure, system_message("directory open failed"));
  }
  const int result = ::fsync(descriptor);
  const int saved = errno;
  ::close(descriptor);
  if (result != 0 && saved != EINVAL && saved != ENOTSUP) {
    errno = saved;
    fail(ErrorCode::io_failure, system_message("directory sync failed"));
  }
#endif
}

void remove_recognized_temp(const std::filesystem::path& path) noexcept {
  const std::string name = path.filename().string();
  if (name.find(".engine002-tmp-") == std::string::npos) return;
  std::error_code error;
  std::filesystem::remove(path, error);
}

void set_publication_failpoint(int stage) noexcept {
  g_publication_failpoint.store(stage);
}

void publication_failpoint(int stage) {
  if (g_publication_failpoint.load() == stage) {
    fail(ErrorCode::io_failure,
         std::string("injected publication failpoint after stage ") +
             std::to_string(stage));
  }
}

void set_io_faultpoint(int fault) noexcept {
  g_io_failpoint.store(fault);
}

void cancellation_point() {
  if (consume_io_fault(9)) {
    fail(ErrorCode::interrupted, "injected streaming-store cancellation");
  }
}

}  // namespace engine002
}  // namespace splitaligner
