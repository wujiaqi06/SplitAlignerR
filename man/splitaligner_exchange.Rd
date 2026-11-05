\name{splitaligner_exchange}
\title{Versioned primitive branch exchange and scoped aliases}
\description{An additive development RDS interface retaining complete result, tree and provenance. Single fixed branch-length profile only. Coordinates are independent of B aliases and tree-local node numbers.}
\usage{
export_splitaligner_exchange(result, species_tree, tree_source, producer,
  label_scheme, payload, file = NULL, branch_margin = 2L)
validate_splitaligner_exchange(x)
read_splitaligner_exchange(file)
transpose_splitaligner_exchange(x)
annotate_splitaligner_exchange(x, gene_id, tree = x$tree$phylo)
splitaligner_label_registry()
splitaligner_exchange_schema()
new_splitaligner_label_migration(x, to_scheme, target_aliases, authority,
  allow_synthetic = FALSE)
migrate_splitaligner_labels(x, migration, allow_synthetic = FALSE)
}
\arguments{
\item{result}{A single fixed-mode splitaligner_result.}
\item{species_tree, tree}{Explicit complete phylo reference or display instance.}
\item{tree_source}{Explicit named provenance list with kind and id; original source bytes are preserved.}
\item{producer}{Declared source commit/tree/parent, dirty scope, file hashes and development provenance.}
\item{label_scheme, to_scheme}{Registered list with id and version.}
\item{payload}{Branch_length type, name, units, identity scale, origin and spec_id.}
\item{file}{New output path or existing input RDS, as appropriate.}
\item{branch_margin}{2 for gene by branch, explicitly 1 for branch by gene.}
\item{x}{A checked exchange envelope.}
\item{gene_id}{One exact gene key.}
\item{target_aliases}{Target B aliases in coordinate order.}
\item{authority}{Explicit synthetic or source-bound migration evidence.}
\item{allow_synthetic}{Explicit opt-in for synthetic fixture migration.}
\item{migration}{A migration bound to exact tree and ledgers.}
}
\value{An envelope, schema, registry, migration, or edge annotation table as named by the function. Validation returns the input invisibly.}
\details{Schema 0.2.0-development. Unknown mode, payload, alias scope or provenance and non-bijective root/edge representations are rejected. No rerooting, pruning or composite expansion is performed. Tree geometry is separate from gene values. Use splitaligner_exchange_schema() for the profile and its required fields. La Terra reader and plotting compatibility remain untested.}
\alias{splitaligner_label_registry}
\alias{export_splitaligner_exchange}
\alias{validate_splitaligner_exchange}
\alias{read_splitaligner_exchange}
\alias{transpose_splitaligner_exchange}
\alias{annotate_splitaligner_exchange}
\alias{new_splitaligner_label_migration}
\alias{migrate_splitaligner_labels}
\alias{splitaligner_exchange_schema}
\examples{
# Synthetic provenance for a toy example; supply real source identities for real data.
ref <- ape::read.tree(text = "(A,B,C);")
result <- align_branches(ref, c(g1 = "(A:1,B:2,C:3);"), mode = "fixed")
producer <- list(source_commit = strrep("a", 40), source_tree = strrep("b", 40),
  source_parent = strrep("c", 40), dirty_scope = character(),
  source_files = c(toy = digest::digest("toy", algo = "sha256", serialize = FALSE)),
  provenance_status = "synthetic_fixture")
payload <- list(type = "branch_length", name = "length", units = "substitutions/site",
  scale = "identity", origin = "toy gene tree", spec_id = "toy-example")
path <- tempfile(fileext = ".rds")
x <- export_splitaligner_exchange(result, ref, list(kind = "provided_phylo", id = "toy"),
  producer, splitaligner_label_registry()$native$scheme, payload, file = path)
read_back <- read_splitaligner_exchange(path)
validate_splitaligner_exchange(read_back)
transpose_splitaligner_exchange(read_back)$axes$orientation
unlink(path)
}
