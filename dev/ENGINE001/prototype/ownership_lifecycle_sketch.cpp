#include <Rcpp.h>

#include <cstdint>
#include <string>
#include <vector>

class Engine001Context {
 public:
  Engine001Context(std::string fingerprint, std::vector<double> values)
      : fingerprint_(std::move(fingerprint)),
        values_(std::move(values)),
        open_(true) {}

  bool open() const noexcept { return open_; }

  void close() noexcept {
    if (!open_) return;
    values_.clear();
    values_.shrink_to_fit();
    open_ = false;
  }

  Rcpp::List snapshot() const {
    require_open();
    return Rcpp::List::create(
        Rcpp::Named("fingerprint") = fingerprint_,
        Rcpp::Named("values") = Rcpp::wrap(values_),
        Rcpp::Named("durable") = true);
  }

 private:
  void require_open() const {
    if (!open_) Rcpp::stop("[ENGINE_CONTEXT_CLOSED] context is invalidated.");
  }

  std::string fingerprint_;
  std::vector<double> values_;
  bool open_;
};

// [[Rcpp::export]]
SEXP engine001_context_create(std::string fingerprint,
                              Rcpp::NumericVector values) {
  std::vector<double> copied(values.begin(), values.end());
  Rcpp::XPtr<Engine001Context> pointer(
      new Engine001Context(std::move(fingerprint), std::move(copied)), true);
  pointer.attr("class") = Rcpp::CharacterVector::create(
      "engine001_context_xptr", "externalptr");
  return pointer;
}

// [[Rcpp::export]]
Rcpp::List engine001_context_snapshot(SEXP value) {
  Rcpp::XPtr<Engine001Context> pointer(value);
  return pointer->snapshot();
}

// [[Rcpp::export]]
bool engine001_context_close(SEXP value) {
  Rcpp::XPtr<Engine001Context> pointer(value);
  const bool was_open = pointer->open();
  pointer->close();
  return was_open;
}

// [[Rcpp::export]]
bool engine001_context_is_open(SEXP value) {
  Rcpp::XPtr<Engine001Context> pointer(value);
  return pointer->open();
}
