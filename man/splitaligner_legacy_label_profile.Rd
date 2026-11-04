\name{splitaligner_legacy_label_profile}
\title{A named source-bound historical branch alias profile}
\description{Rebuild coordinates from explicitly named original tree bytes and bind the two user-provided historical tables. No historical numerical analysis is performed.}
\usage{
audit_splitaligner_legacy_labels(old_ape_file, old_new_file, tree_file, file = NULL)
validate_splitaligner_legacy_profile(profile)
legacy_profile_label_migration(x, profile, to_scheme)
}
\arguments{
\item{old_ape_file, old_new_file}{Exact original user tables.}
\item{tree_file}{One of the three explicitly named original tree sources.}
\item{file}{Optional new RDS destination.}
\item{profile}{A source-bound profile.}
\item{x}{A checked exchange with the exact reference instance and ordered ledger.}
\item{to_scheme}{An explicit registered scheme list with id and version.}
}
\value{A checked profile or a bound migration. Validation returns the profile invisibly.}
\details{Scope is marine302-user-bound-20260908-v1 only. Unknown provenance, tree/ledger mismatch, unrecognized nonbranch records and arbitrary claimed authority are rejected. The exact final semicolon record is preserved separately. This is coordinate agreement for named sources, not all-version or whole-generation-history certification.}
\alias{audit_splitaligner_legacy_labels}
\alias{validate_splitaligner_legacy_profile}
\alias{legacy_profile_label_migration}
