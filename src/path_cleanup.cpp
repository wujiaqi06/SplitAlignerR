#include <Rcpp.h>
#include <filesystem>
#include <system_error>

namespace {
namespace fs = std::filesystem;

// The force path changes only the permissions of entries actually reached.
// Directory symlinks are removed as links, including dangling symlinks.
void remove_forced(const fs::path& path, bool recursive, std::error_code& error) {
  const fs::file_status status = fs::symlink_status(path, error);
  if (error == std::errc::no_such_file_or_directory) {
    error.clear();
    return;
  }
  if (error || !fs::exists(status)) return;
  if (!fs::is_symlink(status)) {
    const fs::perms access = fs::is_directory(status)
        ? fs::perms::owner_all : fs::perms::owner_write;
    fs::permissions(path, access, fs::perm_options::add, error);
    if (error) return;
  }
  if (recursive && fs::is_directory(status)) {
    fs::directory_iterator entry(path, error);
    const fs::directory_iterator end;
    while (!error && entry != end) {
      const fs::path child = entry->path();
      entry.increment(error);
      if (error) return;
      remove_forced(child, true, error);
    }
    if (error) return;
  }
  fs::remove(path, error);
}
}

// [[Rcpp::export]]
int cpp_unlink_literal(Rcpp::CharacterVector paths, bool recursive, bool force) {
  int failed = 0;
  for (R_xlen_t i = 0; i < paths.size(); ++i) {
    const SEXP name = paths[i];
    if (name == NA_STRING) Rcpp::stop("Cleanup paths must not be missing.");
#ifdef _WIN32
    fs::path path = fs::u8path(Rf_translateCharUTF8(name));
#else
    fs::path path(Rf_translateChar(name));
#endif
    if (path.empty()) Rcpp::stop("Cleanup paths must not be empty.");
    // A trailing separator must not turn a directory symlink into its target.
    while (path.filename().empty() && path != path.root_path()) {
      path = path.parent_path();
    }
    std::error_code error;
    if (!recursive) {
      const fs::file_status status = fs::symlink_status(path, error);
      if (error == std::errc::no_such_file_or_directory) continue;
      // Match base unlink(): nonrecursive cleanup removes files and links,
      // but must preserve real directories, even when they are empty.
      if (error || fs::is_directory(status)) {
        failed = 1;
        continue;
      }
    }
    if (force) {
      remove_forced(path, recursive, error);
    } else if (recursive) {
      fs::remove_all(path, error);
    } else {
      fs::remove(path, error);
    }
    if (error) failed = 1;
  }
  return failed;
}
