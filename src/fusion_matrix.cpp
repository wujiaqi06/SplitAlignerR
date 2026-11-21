// Global fusion coordinates are evaluated only from the current reference fibers.
// Each positive owner indexes one singleton or one active-group ledger record.
#include <Rcpp.h>
#include <algorithm>
#include <cmath>
#include <vector>

namespace {
enum Structure { Active = 1, Decomposable, Unavailable };
enum Recovery { Recovered = 1, Unrecovered, NotTestable };
enum ValueStatus { Available = 1, Deleted, Cut, DeletedAndCut, Absent,
                   MissingLength, Overflow, DirectOnly };
}

// [[Rcpp::export]]
Rcpp::List cpp_fusion_cells(Rcpp::IntegerVector owners, Rcpp::IntegerVector sizes,
                            Rcpp::LogicalVector recovered, Rcpp::NumericVector lengths,
                            int primitive_count, Rcpp::IntegerVector gene_rows,
                            Rcpp::List target_members, bool whole, bool details) {
  if (primitive_count <= 0 || owners.size() % primitive_count ||
      sizes.size() != recovered.size() || sizes.size() != lengths.size())
    Rcpp::stop("Inconsistent component ledger dimensions.");
  const int ng = gene_rows.size(), nc = target_members.size();
  const R_xlen_t cells = static_cast<R_xlen_t>(ng) * nc;
  Rcpp::NumericMatrix values(ng, nc);
  std::fill(values.begin(), values.end(), NA_REAL);
  Rcpp::IntegerVector structure(details ? cells : 0), recovery(details ? cells : 0),
    status(details ? cells : 0);
  Rcpp::List sources(details ? cells : 0);
  std::vector<int> touched;
  std::vector<double> terms;
  std::vector<bool> seen(sizes.size(), false);
  for (int col = 0; col < nc; ++col) {
    Rcpp::checkUserInterrupt();
    const Rcpp::IntegerVector members = target_members[col];
    for (const int m : members)
      if (m < 1 || m > primitive_count) Rcpp::stop("Invalid target member.");
    for (int row = 0; row < ng; ++row) {
      const int gene = gene_rows[row];
      if (gene < 1 || gene > owners.size() / primitive_count)
        Rcpp::stop("Invalid gene row.");
      const R_xlen_t offset = static_cast<R_xlen_t>(gene - 1) * primitive_count;
      touched.clear();
      bool deleted = false, all_recovered = true, all_lengths = true;
      R_xlen_t present = 0, covered = 0;
      for (const int m : members) {
        const int id = owners[offset + m - 1];
        if (id == 0) { deleted = true; continue; }
        if (id < 1 || id > sizes.size()) Rcpp::stop("Invalid current component.");
        ++present;
        if (seen[id - 1]) continue;
        seen[id - 1] = true;
        touched.push_back(id);
        covered += sizes[id - 1];
        all_recovered = all_recovered && recovered[id - 1];
        const double length = lengths[id - 1];
        if (!std::isfinite(length)) all_lengths = false;
      }
      // Owners are gene-specific, and the current fibers form a partition.
      // Excess covered members mean that C cuts at least one whole fiber.
      const bool cut = covered != present;
      int ref = touched.size() == 1 ? Active : Decomposable;
      int rec = all_recovered ? Recovered : Unrecovered;
      int why = Available;
      if (deleted || cut) {
        ref = Unavailable; rec = NotTestable;
        why = deleted && cut ? DeletedAndCut : (deleted ? Deleted : Cut);
      } else if (!all_recovered) why = Absent;
      // The direct view never constructs a sum across current components.
      // Component lengths and source records remain independently available.
      else if (ref == Decomposable && !whole) why = DirectOnly;
      else if (!all_lengths) why = MissingLength;
      else if (ref == Active) values(row, col) = lengths[touched.front() - 1];
      else {
        terms.clear();
        for (const int id : touched) terms.push_back(lengths[id - 1]);
        std::sort(terms.begin(), terms.end(), [](double a, double b) {
          return std::abs(a) == std::abs(b) ? a < b : std::abs(a) < std::abs(b);
        });
        double sum = 0;
        for (const double term : terms) sum += term;
        if (!std::isfinite(sum)) why = Overflow;
        else values(row, col) = sum;
      }
      if (details) {
        const R_xlen_t cell = static_cast<R_xlen_t>(col) * ng + row;
        structure[cell] = ref; recovery[cell] = rec; status[cell] = why;
        sources[cell] = Rcpp::wrap(touched);
      }
      for (const auto id : touched) seen[id - 1] = false;
    }
  }
  return Rcpp::List::create(Rcpp::_["values"] = values, Rcpp::_["structure"] = structure,
                            Rcpp::_["recovery"] = recovery, Rcpp::_["status"] = status,
                            Rcpp::_["sources"] = sources);
}
