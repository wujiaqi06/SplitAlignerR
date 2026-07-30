args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop(
    "usage: release_metadata_gate.R SOURCE_ROOT OUTPUT_REPORT",
    call. = FALSE
  )
}

source_root <- normalizePath(args[[1L]], mustWork = TRUE)
output_report <- args[[2L]]
expected <- list(
  package = "0.1.0.9000",
  core = "0.1.0",
  general_schema = "1.0.0",
  paired_schema = "1.0.0",
  candidate = "v0.1.0-rc3",
  certified_release = "v0.1.0",
  certified_commit = "17a0927095c7a067817bf598a2556cbe7348a6d0",
  development_status = "post-release development",
  recert_status = "not covered by v0.1.0 Pro PASS",
  certified_release_tag_created = TRUE,
  certified_github_release_published = TRUE,
  development_release_authorized = FALSE,
  doi = "10.64898/2026.02.24.707838",
  software_title = paste(
    "SplitAlignerR: R Interface and Independent Graph Oracle for SplitAligner"
  ),
  paper_title = paste(
    "SplitAligner: A Gene-Species Tree Reconciliation Framework",
    "Using Split-Based Branch Mapping"
  )
)

checks <- list()
add_check <- function(check, pass, details) {
  checks[[length(checks) + 1L]] <<- data.frame(
    check = check,
    status = if (isTRUE(pass)) "PASS" else "FAIL",
    details = as.character(details),
    stringsAsFactors = FALSE
  )
}

read_text <- function(relative_path) {
  paste(
    readLines(file.path(source_root, relative_path), warn = FALSE),
    collapse = "\n"
  )
}

normalized_text <- function(relative_path) {
  text <- gsub(
    "(?m)^\\s*(?:#'|>)\\s?", "", read_text(relative_path), perl = TRUE
  )
  gsub("[[:space:]]+", " ", text)
}

json_string <- function(relative_path, key) {
  lines <- readLines(file.path(source_root, relative_path), warn = FALSE)
  pattern <- sprintf(
    '^\\s*"%s"\\s*:\\s*"([^"]+)"\\s*,?\\s*$', key
  )
  hits <- grep(pattern, lines, perl = TRUE, value = TRUE)
  if (length(hits) != 1L) {
    stop(
      sprintf("expected one `%s` string in %s", key, relative_path),
      call. = FALSE
    )
  }
  sub(pattern, "\\1", hits, perl = TRUE)
}

json_boolean <- function(relative_path, key) {
  lines <- readLines(file.path(source_root, relative_path), warn = FALSE)
  pattern <- sprintf(
    '^\\s*"%s"\\s*:\\s*(true|false)\\s*,?\\s*$', key
  )
  hits <- grep(pattern, lines, perl = TRUE, value = TRUE)
  if (length(hits) != 1L) {
    stop(
      sprintf("expected one `%s` boolean in %s", key, relative_path),
      call. = FALSE
    )
  }
  identical(sub(pattern, "\\1", hits, perl = TRUE), "true")
}

description <- read.dcf(file.path(source_root, "DESCRIPTION"))
package_version <- unname(description[1L, "Version"])
add_check(
  "DESCRIPTION_package_version",
  identical(package_version, expected$package),
  package_version
)

suppressPackageStartupMessages(library(SplitAlignerR))
core_info <- splitaligner_core_info()
add_check(
  "runtime_cpp_core_version",
  identical(core_info$core_version, expected$core),
  core_info$core_version
)
add_check(
  "runtime_general_schema",
  identical(core_info$schema_version, expected$general_schema),
  core_info$schema_version
)

tiny_species <- "((A:1,B:1):1,(C:1,D:1):1);"
tiny_fixed <- align_branches(
  tiny_species, c(g = tiny_species), mode = "fixed"
)
tiny_free <- align_branches(
  tiny_species, c(g = tiny_species), mode = "free"
)
tiny_paired <- pair_alignment_results(tiny_fixed, tiny_free)
runtime_paired_schema <- tiny_paired$metadata$paired_schema
add_check(
  "runtime_paired_schema",
  identical(runtime_paired_schema, expected$paired_schema),
  runtime_paired_schema
)

conventions <- "inst/spec/conventions-v1.json"
release_identity <- "inst/recert/RELEASE_IDENTITY.json"
convention_core <- json_string(conventions, "core_version")
convention_general <- json_string(conventions, "schema_version")
convention_paired <- json_string(conventions, "paired_schema")
add_check(
  "conventions_core_version",
  identical(convention_core, expected$core),
  convention_core
)
add_check(
  "conventions_general_schema",
  identical(convention_general, expected$general_schema),
  convention_general
)
add_check(
  "conventions_paired_schema",
  identical(convention_paired, expected$paired_schema),
  convention_paired
)

identity_package <- json_string(release_identity, "package_version")
identity_core <- json_string(release_identity, "core_version")
identity_general <- json_string(release_identity, "general_schema")
identity_paired <- json_string(release_identity, "paired_schema")
identity_candidate <- json_string(release_identity, "rc_identifier")
identity_certified_release <- json_string(
  release_identity, "certified_release_tag"
)
identity_certified_commit <- json_string(
  release_identity, "certified_release_commit"
)
identity_development <- json_string(release_identity, "development_version")
identity_development_status <- json_string(
  release_identity, "development_status"
)
identity_recert_status <- json_string(release_identity, "recert_status")
identity_certified_tag_created <- json_boolean(
  release_identity, "certified_release_tag_created"
)
identity_certified_release_published <- json_boolean(
  release_identity, "certified_github_release_published"
)
identity_development_release_authorized <- json_boolean(
  release_identity, "development_release_authorized"
)
identity_values <- c(
  identity_package, identity_core, identity_general, identity_paired
)
add_check(
  "release_identity_versions_and_schemas",
  identical(
    identity_values,
    c(
      expected$package, expected$core,
      expected$general_schema, expected$paired_schema
    )
  ),
  paste(identity_values, collapse = ",")
)
add_check(
  "release_identity_candidate",
  identical(identity_candidate, expected$candidate),
  identity_candidate
)
add_check(
  "release_identity_certified_release",
  identical(identity_certified_release, expected$certified_release),
  identity_certified_release
)
add_check(
  "release_identity_certified_commit",
  identical(identity_certified_commit, expected$certified_commit),
  identity_certified_commit
)
add_check(
  "release_identity_development_version",
  identical(identity_development, expected$package),
  identity_development
)
add_check(
  "release_identity_development_status",
  identical(identity_development_status, expected$development_status),
  identity_development_status
)
add_check(
  "release_identity_recert_status",
  identical(identity_recert_status, expected$recert_status),
  identity_recert_status
)
add_check(
  "release_identity_certified_tag_created",
  identical(
    identity_certified_tag_created,
    expected$certified_release_tag_created
  ),
  identity_certified_tag_created
)
add_check(
  "release_identity_certified_github_release_published",
  identical(
    identity_certified_release_published,
    expected$certified_github_release_published
  ),
  identity_certified_release_published
)
add_check(
  "release_identity_development_release_not_authorized",
  identical(
    identity_development_release_authorized,
    expected$development_release_authorized
  ),
  identity_development_release_authorized
)

legacy_authorization_fields <- c(
  paste0("final_release_tag_", "authorized"),
  paste0("github_release_", "authorized")
)
identity_text <- read_text(release_identity)
legacy_authorization_hits <- legacy_authorization_fields[
  vapply(
    sprintf('"%s"', legacy_authorization_fields),
    grepl,
    logical(1),
    x = identity_text,
    fixed = TRUE
  )
]
add_check(
  "release_identity_has_no_ambiguous_legacy_authorization_fields",
  !length(legacy_authorization_hits),
  if (length(legacy_authorization_hits)) {
    paste(legacy_authorization_hits, collapse = ",")
  } else {
    "no ambiguous legacy authorization fields"
  }
)

cff_lines <- readLines(file.path(source_root, "CITATION.cff"), warn = FALSE)
preferred_start <- grep("^preferred-citation:\\s*$", cff_lines)
if (length(preferred_start) != 1L) {
  stop("CITATION.cff must contain one preferred-citation block", call. = FALSE)
}
extract_cff_title <- function(lines) {
  hit <- grep("^\\s*title:\\s*\"[^\"]+\"\\s*$", lines, value = TRUE)
  if (length(hit) != 1L) {
    stop("expected exactly one CFF title in selected block", call. = FALSE)
  }
  sub('^\\s*title:\\s*"([^"]+)"\\s*$', "\\1", hit, perl = TRUE)
}
software_title <- extract_cff_title(cff_lines[seq_len(preferred_start - 1L)])
preferred_title <- extract_cff_title(
  cff_lines[preferred_start:length(cff_lines)]
)
add_check(
  "cff_software_title",
  identical(software_title, expected$software_title),
  software_title
)
add_check(
  "cff_preferred_paper_title",
  identical(preferred_title, expected$paper_title),
  preferred_title
)

doi_files <- c(
  "README.md", "DESCRIPTION", "CITATION.cff", "inst/CITATION",
  "R/data.R", "man/catnip10_oracle.Rd", "man/SplitAlignerR-package.Rd"
)
for (relative_path in doi_files) {
  text <- normalized_text(relative_path)
  add_check(
    paste0("citation_doi_and_title_", gsub("[^A-Za-z0-9]+", "_", relative_path)),
    grepl(expected$doi, text, fixed = TRUE) &&
      grepl(expected$paper_title, text, fixed = TRUE),
    relative_path
  )
}

documentation_text <- c(
  normalized_text("README.md"),
  normalized_text("inst/CITATION"),
  normalized_text("inst/recert/README.md")
)
add_check(
  "documentation_package_version",
  grepl("0.1.0.9000", documentation_text[[1L]], fixed = TRUE) &&
    grepl("package version 0.1.0.9000", documentation_text[[2L]], fixed = TRUE),
  "README.md and inst/CITATION declare development version 0.1.0.9000"
)
add_check(
  "documentation_certified_release_boundary",
  grepl(expected$certified_release, documentation_text[[1L]], fixed = TRUE) &&
    grepl(expected$certified_release, documentation_text[[2L]], fixed = TRUE) &&
    grepl(expected$certified_release, documentation_text[[3L]], fixed = TRUE) &&
    grepl(
      "not covered by the `v0.1.0` RECERT decision",
      documentation_text[[1L]],
      fixed = TRUE
    ),
  paste(
    expected$certified_release,
    "development not covered by the v0.1.0 RECERT decision",
    sep = "; "
  )
)

readme <- read_text("README.md")
add_check(
  "readme_stable_install_targets_certified_tag",
  grepl(
    'remotes::install_github("wujiaqi06/SplitAlignerR@v0.1.0")',
    readme,
    fixed = TRUE
  ),
  "stable install uses @v0.1.0"
)
add_check(
  "readme_development_install_targets_default_branch",
  grepl(
    'remotes::install_github("wujiaqi06/SplitAlignerR")',
    readme,
    fixed = TRUE
  ),
  "development install uses the default branch"
)
stale_readme_phrases <- c(
  "release-candidate line",
  "candidate is not a final release certificate",
  "independent RECERT remains pending",
  "Install the annotated RC3 candidate"
)
stale_readme_hits <- stale_readme_phrases[
  vapply(stale_readme_phrases, grepl, logical(1), x = readme, fixed = TRUE)
]
add_check(
  "readme_has_no_stale_candidate_wording",
  !length(stale_readme_hits),
  if (length(stale_readme_hits)) paste(stale_readme_hits, collapse = "; ") else
    "no stale candidate wording"
)

forbidden <- c(
  paste0("0.0.2", ".9002"),
  paste0("0.1.0", "-dev.2"),
  paste0("1.0.0", "-draft.2"),
  paste0("1.0.0", "-draft.3")
)
tracked <- system2(
  "git", c("-C", shQuote(source_root), "ls-files"),
  stdout = TRUE, stderr = TRUE
)
if (!identical(attr(tracked, "status"), NULL)) {
  stop("git ls-files failed while scanning active source", call. = FALSE)
}
active <- tracked[
  tracked != "NEWS.md" &
    grepl(
      "(?:^|/)(?:[^/]+\\.(?:R|Rmd|Rd|md|json|ya?ml|cff|cpp|h|sh|py)|DESCRIPTION)$",
      tracked,
      perl = TRUE
    )
]
forbidden_hits <- character()
for (relative_path in active) {
  text <- read_text(relative_path)
  present <- forbidden[vapply(forbidden, grepl, logical(1), x = text, fixed = TRUE)]
  if (length(present)) {
    forbidden_hits <- c(
      forbidden_hits,
      paste(relative_path, paste(present, collapse = ","), sep = ":")
    )
  }
}
add_check(
  "active_source_has_no_forbidden_development_versions",
  !length(forbidden_hits),
  if (length(forbidden_hits)) paste(forbidden_hits, collapse = "; ") else
    "no forbidden development identifiers outside historical NEWS"
)

result <- do.call(rbind, checks)
utils::write.table(
  result,
  file = output_report,
  sep = "\t",
  quote = FALSE,
  row.names = FALSE,
  na = ""
)
if (any(result$status != "PASS")) {
  stop("release metadata consistency gate failed", call. = FALSE)
}
cat(sprintf("release_metadata_gate: PASS (%d checks)\n", nrow(result)))
