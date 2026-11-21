% Please edit documentation in R/fusion-matrix.R
\name{fusion_cells}
\alias{fusion_cells}
\title{Inspect the source of shared fusion-column values}
\usage{
fusion_cells(result, gene_ids = NULL, coordinate_ids = NULL)
}
\arguments{
\item{result}{A result from \code{\link{align_branches}}.}
\item{gene_ids}{Optional gene IDs in the desired order.}
\item{coordinate_ids}{Optional shared fusion coordinate IDs.}
}
\description{Inspect whole current components, their empirical matches and their
lengths for selected shared fusion coordinates.}
\value{
One row per selected gene and fusion coordinate with its structural and
recovery states, value, numeric status, applicable construction mode and a
\code{components} list-column. Each component records its whole primitive member
set, projected split, recovery and numeric evidence. \code{source_nodes} lists
comma-separated, zero-based postorder node indices in the input gene Newick.
Each names the incoming edge at that node. Multiple indices for one split
identify degree-two aliases collapsed into one measurement. For an unavailable
target, the table shows surviving touched components, including whole components
crossing the target boundary. For historical direct-only objects, rerun the
alignment to record source indices.
}
\examples{
r <- align_branches("((A,B),(C,D));", c(g1 = "(A:1,B:2);",
                                       g2 = "((A:1,B:2):3,(C:4,D:5):6);"))
fusion_cells(r, "g2")
}
