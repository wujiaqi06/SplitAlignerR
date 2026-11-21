\name{reference_truth}
\alias{reference_truth}
\title{Construct reference-only branch truth by pruning and contraction}
\usage{
reference_truth(species_tree, retained_taxa, gene_ids = NULL,
  tree_semantics = c("unrooted", "rooted"),
  fusion_view = c("whole", "direct"))
}
\arguments{
\item{species_tree}{Reference Newick text/file or one \code{ape::phylo} object.
At least two distinct reference taxa are required. Every internal node in
the original input, including its root, must have at least two children.
Non-root branch lengths provide expected values; a display-root length is ignored.}
\item{retained_taxa}{One character vector, or a list of character vectors of
retained reference labels. List names supply optional row identifiers. Each
set must contain unique, nonmissing reference labels. Empty sets are allowed.}
\item{gene_ids}{Optional unique row identifiers, one per retained-taxon set.}
\item{tree_semantics}{\code{"unrooted"} (default) or \code{"rooted"}. Rooted truth
preserves the original root and its path to the retained-tip MRCA. That root
is never promoted or suppressed. With one retained taxon, the original
root-to-tip path remains. Empty sets have no edges; unrooted sets of one taxon
also have no surviving edges.}
\item{fusion_view}{\code{"whole"} constructs expected shared-column values
from complete current reference components. \code{"direct"} retains only
active fused edges.}
}
\value{
A \code{splitaligner_truth_result} list with a primitive-only \code{state_matrix}
(\code{observed}, \code{NA_struct}, \code{NA_fuse}), numeric \code{original_matrix},
separate \code{fusion_matrix}, coordinate tables, \code{component_ledger},
\code{fusion_ledger}, \code{reference_provenance}, \code{metadata} and \code{input}.
Component \code{expected_value} and \code{expected_status} refer only to reference
lengths. \code{reference_source_nodes} are zero-based incoming-edge addresses
in the input reference Newick, used only for provenance. The fusion ledger
records reference representability, expected-value status, construction mode
and contributing reference components; it contains no empirical recovery status.
}
\description{
Algorithm S3 restricts a reference tree to retained-taxon sets by graph pruning
and contraction while carrying complete original-edge memberships. It accepts
no empirical gene trees and does not infer recovery. \code{align_branches()}
remains the default split-based mapping entry.
}
\details{
The rooted S3 original-root convention also defines the reference layer of
\code{\link{align_fixed_topology}}. S4 records only the measurements actually
represented by its gene input, without changing this reference truth.

\code{observed} denotes a separately represented original reference branch,
not an empirical observation. Expected component lengths require every
contributing reference length to be finite. Missing lengths never change
structural identity and are never skipped in a partial sum. Zero, negative
lengths and failure markers follow the package's existing numeric policy.
No \code{NA_topo} or \code{NA_fuse_topo} classification occurs in this layer.
}
\examples{
truth <- reference_truth("((A:1,B:2):3,C:4);",
  list(full = c("A", "B", "C"), without_C = c("A", "B"), only_A = "A"),
  tree_semantics = "rooted")
truth$state_matrix
truth$original_matrix
truth$fusion_matrix
}
