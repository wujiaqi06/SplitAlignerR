.sx_legacy_id <- "marine302-user-bound-20260908-v1"
.sx_legacy_pins <- list(
  old_ape = "b24e8be5fb45ba6c207e4c4a86d3a522c0f8f48ec93a03ebc2c76c7dcc35e045",
  old_new = "0dee04dc349ff193e3d125391ce47dca3b807dce05562011fc056fcf7a822e52",
  trees = c("b032a99796f146816e93d3efd585f21fe908e9fabe57366e8c6ac24f410f287e",
            "eb07d58b0ef08194523570639ed23b6a6f3019e91a3950ca9797a8d59f0978cf",
            "bb046d5072a6e86841515dd77b76b4b09cb113f22883d181aac63660e530dc68"))

.sx_legacy_build <- function(sources) {
  .sx_fields(sources, c("old_ape", "old_new", "reference_tree"), "source-bound profile sources")
  for (source in sources) {
    .sx_fields(source, c("path", "bytes", "sha256"), "legacy source")
    .sx_need(.sx_string(source$path) && is.raw(source$bytes) && identical(source$sha256, .sx_raw_hash(source$bytes)),
             "legacy source bytes/hash mismatch")
  }
  .sx_need(identical(sources$old_ape$sha256, .sx_legacy_pins$old_ape) &&
             identical(sources$old_new$sha256, .sx_legacy_pins$old_new) &&
             sources$reference_tree$sha256 %in% .sx_legacy_pins$trees,
           "unknown source-bound legacy provenance; this profile accepts only the three named tree sources and two user tables")
  table <- function(raw) utils::read.delim(text = rawToChar(raw), check.names = FALSE,
                                    stringsAsFactors = FALSE, quote = "", comment.char = "", na.strings = character())
  old <- table(sources$old_ape$bytes); cross <- table(sources$old_new$bytes)
  .sx_need(identical(names(old), c("anc", "offspring", "branch_label", "order")) &&
             identical(names(cross), c("Old", "New")), "unrecognized historical table schema")
  .sx_need(nrow(old) == 601L && .sx_keys(old$branch_label) &&
             setequal(old$branch_label, paste0("B", seq_len(601L))) &&
             identical(old$order, seq_len(601L)), "historical old branch ledger/order is not complete and unique")
  branch <- grepl("^B[1-9][0-9]*$", cross$Old) & grepl("^B[1-9][0-9]*$", cross$New)
  extra <- which(!branch)
  .sx_need(nrow(cross) == 602L && identical(extra, 602L) && identical(cross$Old[extra], ";") &&
             identical(cross$New[extra], ";"), "unknown nonbranch historical record; only the exact final semicolon pair is recognized")
  pairs <- cross[branch, , drop = FALSE]
  .sx_need(.sx_keys(pairs$Old) && .sx_keys(pairs$New) &&
             setequal(pairs$Old, old$branch_label) && setequal(pairs$New, paste0("B", seq_len(601L))),
           "historical branch crosswalk is not a complete bijection")
  tree <- ape::read.tree(text = rawToChar(sources$reference_tree$bytes))
  .sx_need(length(tree$tip.label) == 302L && nrow(tree$edge) == 601L, "source-bound tree is not the 302/601 profile")
  # Rebuild native coordinates from the named original tree, not a derived old ledger.
  validated <- validate_species_tree(tree)
  reference <- .sx_reference(list(primitive_coordinates = validated$coordinates,
                                  metadata = list(split_key_schema = "SplitAligner-canonical-split-key-v2")), tree)
  coordinates <- reference$coordinates; native <- .sx_label_ledger(coordinates, .sx_native_scheme)
  edges <- .sx_tree_map(tree, coordinates, native)$edges
  .sx_need(identical(as.integer(old$anc), as.integer(tree$edge[old$order, 1L])) &&
             identical(as.integer(old$offspring), as.integer(tree$edge[old$order, 2L])),
           "old anc/offspring/order do not bind these exact phylo edges")
  mapped_new <- pairs$New[match(old$branch_label, pairs$Old)]
  .sx_need(identical(mapped_new, edges$source_alias[old$order]),
           "user old-to-new aliases disagree with independently rebuilt native tree coordinates")
  old_by_coordinate <- old$branch_label[match(coordinates$coordinate_id, edges$coordinate_id[old$order])]
  legacy <- .sx_label_ledger(coordinates, .sx_old_scheme, old_by_coordinate)
  mapping <- data.frame(old_alias = old$branch_label, new_alias = mapped_new,
                         coordinate_id = edges$coordinate_id[old$order], edge_row = old$order,
                         parent_node = old$anc, child_node = old$offspring,
                         branch_type = edges$branch_type[old$order], terminal_taxon = edges$terminal_taxon[old$order],
                         stringsAsFactors = FALSE, check.names = FALSE)
  .sx_need(sum(mapping$branch_type == "terminal") == 302L && sum(mapping$branch_type == "internal") == 299L &&
             setequal(mapping$new_alias[mapping$branch_type == "terminal"], paste0("B", seq_len(302L))),
           "source-bound terminal/internal label identity disagrees")
  profile <- list(schema = list(id = "SplitAlignerR.legacy-label-profile", version = "0.2.0-development",
                                exchange_version = .sx_version, hash_schema = .sx_hash_schema),
                  profile_id = .sx_legacy_id,
                  status = "SOURCE_BOUND_COORDINATE_AGREEMENT_NOT_GENERATION_HISTORY_CERTIFICATION",
                  sources = sources, tree = tree, reference_tree_sha256 = .sx_hash(tree),
                  coordinates = coordinates, ordered_branch_ledger_sha256 = .sx_hash(coordinates),
                  label_ledgers = list(native = native, legacy = legacy), mapping = mapping,
                  non_branch_rows = data.frame(input_row = extra, Old = cross$Old[extra], New = cross$New[extra], stringsAsFactors = FALSE),
                  counts = list(taxa = 302L, ordinary_branches = 601L, raw_crosswalk_rows = 602L,
                                unchanged_aliases = sum(pairs$Old == pairs$New), changed_aliases = sum(pairs$Old != pairs$New),
                                terminal = 302L, internal = 299L),
                  limits = c("Only the named original source bytes and their R phylo instances are accepted",
                             "Coordinates were rebuilt from the original trees without a derived old-ledger authority",
                             "Generation history and all-version compatibility are not certified",
                             "No historical numerical matrix, Lasso, model, replay or publication result was changed",
                             "Semicolon record is retained separately, not counted as an ordinary branch"))
  profile$content_sha256 <- .sx_hash(profile)
  class(profile) <- c("splitaligner_legacy_label_profile", "list")
  profile
}

#' Independently bind the supplied legacy label tables to a named original tree
#' @param old_ape_file Exact user-supplied old alias to anc/offspring/order table.
#' @param old_new_file Exact user-supplied old/new table including its semicolon record.
#' @param tree_file One of the three named original 302-taxon tree files.
#' @param file Optional new RDS destination for this source-bound profile.
#' @return A source-bound profile; not a whole-generation-history certificate.
#' @export
audit_splitaligner_legacy_labels <- function(old_ape_file, old_new_file, tree_file, file = NULL) {
  read <- function(path) {
    .sx_need(.sx_string(path) && file.exists(path) && !dir.exists(path), "legacy source file is missing")
    bytes <- readBin(path, "raw", n = file.info(path)$size)
    list(path = normalizePath(path), bytes = bytes, sha256 = .sx_raw_hash(bytes))
  }
  profile <- .sx_legacy_build(list(old_ape = read(old_ape_file), old_new = read(old_new_file), reference_tree = read(tree_file)))
  if (!is.null(file)) {
    .sx_need(.sx_string(file) && dir.exists(dirname(file)) && !file.exists(file), "legacy profile output must be a new RDS path")
    saveRDS(profile, file, version = 3L)
  }
  profile
}

#' Revalidate a source-bound legacy profile from its embedded original bytes
#' @param profile A profile returned by audit_splitaligner_legacy_labels.
#' @return Invisibly the profile; no original file is reopened.
#' @export
validate_splitaligner_legacy_profile <- function(profile) {
  .sx_need(inherits(profile, "splitaligner_legacy_label_profile") && is.list(profile), "unknown legacy profile object")
  .sx_need(identical(profile, .sx_legacy_build(profile$sources)), "legacy profile/tree/ledger was modified")
  invisible(profile)
}

.sx_validate_legacy_authority <- function(authority, migration) {
  .sx_fields(authority, c("kind", "profile"), "source-bound migration authority")
  .sx_need(identical(authority$kind, "source_bound_profile"), "unknown legacy authority")
  profile <- authority$profile; validate_splitaligner_legacy_profile(profile)
  .sx_need(identical(migration$reference_tree_sha256, profile$reference_tree_sha256) &&
             identical(migration$ordered_branch_ledger_sha256, profile$ordered_branch_ledger_sha256),
           "source-bound profile belongs to a different tree or ordered ledger")
  ledger <- function(scheme) if (identical(scheme, .sx_native_scheme)) profile$label_ledgers$native else profile$label_ledgers$legacy
  .sx_need(identical(migration$from_ledger, ledger(migration$from_scheme)) &&
             identical(migration$to_ledger, ledger(migration$to_scheme)), "migration aliases disagree with the independently bound historical profile")
  invisible(authority)
}

#' Create an alias migration using an exact source-bound legacy profile
#' @param x A validated exchange with the exact reference instance and ordered ledger.
#' @param profile An independently bound legacy profile.
#' @param to_scheme Explicit registered target scheme.
#' @return A migration usable by migrate_splitaligner_labels.
#' @export
legacy_profile_label_migration <- function(x, profile, to_scheme) {
  validate_splitaligner_exchange(x); validate_splitaligner_legacy_profile(profile); .sx_scheme(to_scheme)
  .sx_need(identical(x$identity$reference_tree_sha256, profile$reference_tree_sha256) &&
             identical(x$identity$ordered_branch_ledger_sha256, profile$ordered_branch_ledger_sha256),
           "source-bound profile belongs to a different tree or ordered ledger")
  target <- if (identical(to_scheme, .sx_native_scheme)) profile$label_ledgers$native else profile$label_ledgers$legacy
  new_splitaligner_label_migration(x, to_scheme, target$alias,
                                  list(kind = "source_bound_profile", profile = profile))
}
