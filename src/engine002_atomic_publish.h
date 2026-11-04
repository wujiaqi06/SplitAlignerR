#ifndef SPLITALIGNERR_ENGINE002_ATOMIC_PUBLISH_HPP
#define SPLITALIGNERR_ENGINE002_ATOMIC_PUBLISH_HPP

#include "engine002_hash.h"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace splitaligner {
namespace engine002 {

enum class WriterRegion {
  generic,
  header,
  record,
  index,
  footer
};

class ExclusiveBinaryWriter {
 public:
  explicit ExclusiveBinaryWriter(const std::filesystem::path& path);
  ExclusiveBinaryWriter(const ExclusiveBinaryWriter&) = delete;
  ExclusiveBinaryWriter& operator=(const ExclusiveBinaryWriter&) = delete;
  ~ExclusiveBinaryWriter() noexcept;

  void write_all(const std::uint8_t* data, std::size_t size,
                 WriterRegion region = WriterRegion::generic);
  void seek(std::uint64_t offset);
  void sync();
  void close();
  bool open() const noexcept { return descriptor_ >= 0; }

 private:
  int descriptor_;
};

void reject_symlink_path(const std::filesystem::path& directory);
std::string random_nonce_hex();
std::uint64_t exact_file_size(const std::filesystem::path& path);
std::vector<std::uint8_t> read_file_range(const std::filesystem::path& path,
                                          std::uint64_t offset,
                                          std::uint64_t bytes,
                                          std::uint64_t allocation_limit);
std::string read_text_file(const std::filesystem::path& path,
                           std::uint64_t byte_limit);
Sha256 sha256_file(const std::filesystem::path& path);
void write_text_exclusive(const std::filesystem::path& path,
                          const std::string& text);
void publish_no_replace(const std::filesystem::path& temporary,
                        const std::filesystem::path& final_path);
void sync_directory(const std::filesystem::path& directory);
void remove_recognized_temp(const std::filesystem::path& path) noexcept;
void set_publication_failpoint(int stage) noexcept;
void publication_failpoint(int stage);
void set_io_faultpoint(int fault) noexcept;
void cancellation_point();

}  // namespace engine002
}  // namespace splitaligner

#endif
