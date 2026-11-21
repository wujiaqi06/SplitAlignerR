\name{align_panel_to_disk}
\alias{align_panel_to_disk}
\alias{export_panel_matrix}
\alias{panel_fusion_patterns}
\alias{read_panel_matrix}
\alias{read_panel_groups}
\alias{read_panel_fusions}
\alias{read_panel_fusion_cells}
\title{Align gene trees to disk and read selected genes}
\usage{
align_panel_to_disk(species_tree, gene_file, output_dir,
  mode = c("free", "fixed", "paired"), fixed_file = NULL, batch_size = 32L,
  fusion_view = c("whole", "direct"))
export_panel_matrix(path, file, component = "free_length", include_fusions = FALSE)
read_panel_fusion_cells(path, genes, patterns, role = "free")
panel_fusion_patterns(path)
read_panel_matrix(path, component, genes, branches = NULL)
read_panel_groups(path, genes, role = "free")
read_panel_fusions(path, genes, patterns, role = "free",
  field = c("numeric_value", "recovery_status"))
}
\arguments{
\item{species_tree}{Path to the reference Newick file.}
\item{gene_file}{Path to a file with one named record such as \code{gene1(A,B);} per line. The name follows the SplitAligner file convention (letters, digits, dot, underscore or hyphen). In paired mode, supply the free trees here.}
\item{output_dir}{A new directory under an existing parent.}
\item{mode}{Process free trees, fixed trees or paired tree sets.}
\item{fixed_file}{In paired mode, the matching fixed trees in the same gene order.}
\item{batch_size}{Positive number of genes per worker process. Reduce for wider reference trees.}
\item{path}{Path to a completed panel directory. Keep its manifest and batch files together.}
\item{genes}{Gene IDs or positive integer row positions, in the desired order.
For \code{read_panel_fusions()} and \code{read_panel_fusion_cells()}, an empty character or numeric vector requests zero rows or cells, respectively.}
\item{file}{A new TSV file under an existing parent directory on a filesystem that supports hard links. Existing paths, including dangling symbolic links, are never replaced.}
\item{include_fusions}{For length matrices, append one column for each indexed fusion pattern. Groups with no finite length write NA. Use the group reader to inspect the reason.}
\item{component}{One of \code{free_state}, \code{free_length}, \code{fixed_state}, \code{fixed_length}, \code{paired_free} or \code{paired_fixed}, depending on mode.}
\item{branches}{Primitive branch IDs or positive column positions. The default includes all primitive branches.}
\item{patterns}{Composite IDs or positive column positions from \code{panel_fusion_patterns()},
in the desired order. For \code{read_panel_fusions()} and \code{read_panel_fusion_cells()},
an empty character or numeric vector requests zero columns or cells, respectively.}
\item{role}{Tree set to read, either \code{"free"} or \code{"fixed"}.}
\item{fusion_view}{Recorded numerical rule for this panel. The default sums recovered whole components with usable lengths. Use \code{"direct"} to export only lengths of active groups.}
\item{field}{Numerical value under the recorded view, or the legacy recovery status of an active group. For recovery of decomposable coordinates use \code{read_panel_fusion_cells()}.}
}
\description{
The first pass aligns each batch in a separate R process, writes gene-level
evidence to disk and indexes distinct fusion patterns by their original reference
branches. In a second pass, readers return the genes and columns requested
from the relevant batches. Reference branch identifiers are local to the panel.
}
\details{
Every new panel writes \file{support.tsv} and \file{support.nwk} in its
\file{free} or \file{fixed} subdirectory. Paired panels write both sets.
Counts are added across batches before the support percentages are computed.
An internal branch with no eligible genes has NA in the table and a blank
tree label. Both files are indexed by relative path and SHA-256 in
\code{manifest$support}. Older panel directories remain readable and can
be rebuilt from the original inputs to generate these files.

A fusion pattern can occur on either side of a paired run. Within a gene and
role, a pattern that does not form has no sparse group row. In a new whole-view panel the numeric cell can still have a value if complete,
recovered branches cover exactly the target members and every branch has a
usable length. Source splits, Newick node indices and construction mode are
available from \code{read_panel_fusion_cells}. Legacy v1 panels retain their
original direct-only values. A group that forms has a recovery status of
\code{recovered_numeric}, \code{recovered_numeric_unavailable} or
\code{unrecovered}. Only free-tree group records use the \code{NA_fuse_topo}
classification. Primitive and fused lengths are available separately.

Memory scales with batch width, the gene and pattern indexes, and the requested
slice. Matrix reads default to a limit of 10 million requested cells. Set the
positive option \code{SplitAlignerR.max_panel_cells} to change the limit or
set it to \code{Inf} to remove it. Use \code{tempfile()} for an automatically named temporary output directory.
Readers verify each requested batch against its stored SHA-256 checksum.
A completed panel is marked by
\file{manifest.rds}. A new run requires a fresh directory. Full in-memory
provenance and exchange objects remain available via \code{align_branches}.
}
\value{
The writer returns the panel directory. The exporter streams one TSV row per gene and returns the file path. The catalog is a data frame of
\code{coordinate_id} and \code{primitive_members}. Matrix readers return
the requested rows and columns in selection order. Empty selections in
\code{read_panel_fusions()} retain the matrix type and the other axis's names.
The group reader returns
a data frame with one record per formed group and selected gene.
The fusion-cell reader identifies each cell by \code{gene_id} and
\code{composite_id}. Its rows follow the requested pattern order, with the
requested gene order within each pattern, matching \code{\link{fusion_cells}}.
Repeated selections repeat their rows. If either selection is empty, it
returns the same columns and types with zero rows.
}
\seealso{\link{align_branches}, \link{free_fusion_groups}, \link{pair_alignment_results}}
