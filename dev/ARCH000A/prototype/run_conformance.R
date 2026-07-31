#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", args, value = TRUE)
script_dir <- dirname(normalizePath(sub("^--file=", "", script_arg[[1L]])))
repo_root <- normalizePath(file.path(script_dir, "..", "..", ".."), mustWork = TRUE)
setwd(repo_root)
source("dev/ARCH000A/prototype/load_arch000a.R")
suppressPackageStartupMessages(library(SplitAlignerR))

output_dir <- Sys.getenv(
  "ARCH000A_EVIDENCE_DIR",
  file.path(repo_root, "dev", "ARCH000A", "evidence")
)
work_dir <- Sys.getenv("ARCH000A_WORK_DIR", tempfile("arch000a-conformance-"))
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(work_dir, recursive = TRUE, showWarnings = FALSE)
run_full <- identical(Sys.getenv("ARCH000A_RUN_FULL", "0"), "1")

gates <- store_rows <- determinism_rows <- interruption_rows <- character()
addendum_rows <- character()
full_rows <- character()

record <- function(target, gate, status, detail = "") {
  line <- paste(gate, status, detail, sep = "	")
  if (target == "gate") gates <<- c(gates, line)
  if (target == "store") store_rows <<- c(store_rows, line)
  if (target == "determinism") determinism_rows <<- c(determinism_rows, line)
  if (target == "interruption") interruption_rows <<- c(interruption_rows, line)
  if (target == "addendum") addendum_rows <<- c(addendum_rows, line)
  if (target == "full") full_rows <<- c(full_rows, line)
  message(line)
  invisible(status)
}

try_gate <- function(target, gate, expression) {
  tryCatch({
    force(expression)
    record(target, gate, "PASS")
    TRUE
  }, error = function(e) {
    record(target, gate, "FAIL", conditionMessage(e))
    FALSE
  })
}

a_numeric_equal <- function(left, right, tolerance = 1e-10) {
  identical(dimnames(left), dimnames(right)) &&
    identical(is.na(left), is.na(right)) &&
    (all(is.na(left)) ||
       max(abs(left[!is.na(left)] - right[!is.na(right)])) <= tolerance)
}

a_read_records <- function(path) {
  values <- ids <- character()
  arch_iterate_records(path, function(record, index) {
    values[[index]] <<- record$newick
    ids[[index]] <<- record$id
  })
  stats::setNames(values, ids)
}

a_build_test_context <- function(species, records, prefix) {
  authority <- arch_species_authority(species)
  scan <- a_scan_gene_patterns(records, authority)
  registry <- a_make_pattern_registry(list(scan), authority)
  store_path <- file.path(work_dir, paste0(prefix, ".truth.bin"))
  catalog <- a_make_catalog(registry, authority, store_path)
  list(
    authority = authority, scan = scan, registry = registry,
    catalog = catalog, path = store_path, mapping = registry$mappings[[1L]]
  )
}

a_compare_to_production <- function(species, newicks, mode = "free",
                                    tolerance = 1e-10, prefix = "compare") {
  records <- a_as_records(newicks)
  context <- a_build_test_context(species, records, prefix)
  disk <- a_open_packed_store(
    context$path, context$registry, context$authority, verify_all_records = TRUE
  )
  hybrid <- a_new_packed_body_lru(disk, 32 * 1024^2)
  observed <- a_process_with_store(
    records, context$mapping, context$catalog, hybrid, "compact", prefix
  )
  production <- align_branches(
    species, unname(newicks), mode = mode, gene_ids = names(newicks)
  )
  a_assert(
    identical(arch_decode_state_matrix(observed$state_matrix),
              production$state_matrix),
    paste(prefix, "categorical state differs from production")
  )
  a_assert(
    identical(colnames(observed$numeric_matrix),
              colnames(production$numeric_matrix)),
    paste(prefix, "coordinate order differs from production")
  )
  a_assert(
    a_numeric_equal(observed$numeric_matrix, production$numeric_matrix, tolerance),
    paste(prefix, "numeric matrix differs from production")
  )
  expected_members <- if (nrow(production$composite_coordinates)) {
    as.character(production$composite_coordinates$member_text)
  } else character()
  actual_members <- vapply(context$catalog$bstar_members, function(ids) {
    paste(context$authority$primitive_id[ids], collapse = "|")
  }, character(1))
  a_assert(
    identical(actual_members, expected_members),
    paste(prefix, "composite registry differs from production")
  )
  a_assert(observed$terminal_na_topo_count == 0L,
           paste(prefix, "created terminal NA_topo"))
  hybrid$close()
  disk$close()
  unlink(context$path)
  observed
}

a_cross_strategy_output <- function(species, newicks, prefix) {
  records <- a_as_records(newicks)
  context <- a_build_test_context(species, records, prefix)
  disk <- a_open_packed_store(
    context$path, context$registry, context$authority,
    verify_all_records = TRUE
  )
  stores <- list(
    retain_all = a_new_retain_all_store(
      context$registry, context$authority, loader = disk$get
    ),
    recompute = a_new_recompute_store(context$registry, context$authority),
    lru_very_small = a_new_lru_truth_store(
      context$registry, context$authority, 4096
    ),
    lru_moderate = a_new_lru_truth_store(
      context$registry, context$authority, 32 * 1024^2
    ),
    disk = disk,
    packed_disk_lru = a_new_packed_body_lru(disk, 32 * 1024^2)
  )
  results <- lapply(stores, function(store) {
    a_process_with_store(
      records, context$mapping, context$catalog, store, "sink", prefix
    )
  })
  signatures <- vapply(
    results, function(x) x$normalized_scientific_checksum, character(1)
  )
  terminal <- vapply(
    results, function(x) x$terminal_na_topo_count, integer(1)
  )
  a_assert(length(unique(signatures)) == 1L,
           paste(prefix, "truth-store strategies changed scientific output."))
  a_assert(all(terminal == 0L),
           paste(prefix, "truth-store strategy created terminal NA_topo."))
  lapply(stores, function(store) store$close())
  unlink(context$path)
  invisible(signatures)
}

try_gate("gate", "compact_pattern_registry_exact_collision_reverse", {
  patterns <- lapply(
    list(c(1, 3, 5), c(1, 3, 5), c(2, 4), c(1, 2, 5)),
    a_pack_ids, universe_size = 8L
  )
  expected <- sort(unique(vapply(patterns, a_pattern_exact_key, character(1))),
                   method = "radix")
  collision <- a_exact_bucket_registry(patterns, function(x) "constant")
  truncated <- a_exact_bucket_registry(
    patterns, function(x) substring(a_pattern_exact_key(x), 1L, 5L)
  )
  a_assert(identical(collision, expected), "Constant hash merged exact patterns.")
  a_assert(identical(truncated, expected), "Truncated hash merged exact patterns.")
  species <- "(((A,B),C),((D,E),F));"
  genes <- a_as_records(c(
    g1 = "((A:1,B:1):1,(D:1,E:1):1);",
    g2 = "((A:2,D:2):2,(B:2,E:2):2);",
    g3 = "((A:1,C:1):1,(D:1,F:1):1);"
  ))
  authority <- arch_species_authority(species)
  scan <- a_scan_gene_patterns(genes, authority)
  a_assert(a_reverse_registry_invariant(list(scan), authority),
           "Pattern IDs changed under gene reversal.")
})

try_gate("addendum", "degenerate_zero_one_rejected_two_three_exact", {
  species <- "((((A:1,B:1):1,C:1):1,D:1):1,(E:1,F:1):1);"
  authority <- arch_species_authority(species)
  stable_error <- function(gene_trees) {
    capture <- function() tryCatch(
      {
        align_branches(species, gene_trees, mode = "free")
        NA_character_
      },
      error = conditionMessage
    )
    first <- capture()
    second <- capture()
    a_assert(!is.na(first) && identical(first, second),
             "Rejected degenerate input did not return a stable error.")
    first
  }
  zero_error <- stable_error(character())
  one_error <- stable_error("[&R]A;")
  a_assert(grepl("nonempty", zero_error, fixed = TRUE),
           "Zero-tree/taxon boundary used an unexpected validation class.")
  a_assert(grepl("at least two terminal taxa", one_error, fixed = TRUE),
           "One-taxon boundary used an unexpected validation class.")

  state_name <- c("mapped", "NA_struct", "NA_fuse")
  accepted <- list(
    two = list(taxa = c("A", "E"), newick = "(A:1,E:1);"),
    three = list(taxa = c("A", "C", "E"), newick = "(A:1,C:1,E:1);")
  )
  for (label in names(accepted)) {
    case <- accepted[[label]]
    retained <- unname(authority$taxon_id[case$taxa])
    reference <- arch_build_truth_plan(authority, retained)
    packed <- a_pack_truth_plan(reference, authority)
    observed <- a_unpack_truth_plan(packed, authority)
    a_assert(a_plan_scientific_equal(observed, reference, authority),
             paste(label, "taxon packed truth differs from reference."))
    production <- align_branches(
      species, stats::setNames(case$newick, label), mode = "free"
    )
    expected <- state_name[reference$state_template + 1L]
    a_assert(identical(unname(production$state_matrix[1L, ]), expected),
             paste(label, "taxon production states differ from truth plan."))
    a_assert(!any(reference$state_template == 3L),
             paste(label, "taxon truth plan contains empirical NA_topo."))
    for (composite in reference$composites) {
      a_assert(length(composite$members) > 1L,
               paste(label, "taxon truth plan created singleton B*."))
      a_assert(!is.na(composite$projected_split),
               paste(label, "taxon B* has no queryable split."))
    }
    no_query <- is.na(reference$projected_split)
    a_assert(all(reference$state_template[no_query] == 1L),
             paste(label, "taxon plan queried a structurally absent branch."))
  }
})

try_gate("addendum", "endpoint_collapse_terminal_fusion_torture", {
  species <- "((((A:1,B:1):1,C:1):1,D:1):1,(E:1,(F:1,(G:1,H:1):1):1):1);"
  authority <- arch_species_authority(species)
  terminal <- which(authority$branch_type == "terminal")
  candidate_sets <- unlist(lapply(2:6, function(size) {
    utils::combn(authority$taxa, size, simplify = FALSE)
  }), recursive = FALSE)
  cases <- vector("list", length(candidate_sets))
  member_sets <- list()
  primitive_patterns <- vector("list", authority$primitive_count)
  endpoint_index <- terminal_index <- multiple_terminal_index <- NA_integer_
  for (i in seq_along(candidate_sets)) {
    taxa <- candidate_sets[[i]]
    retained <- unname(authority$taxon_id[taxa])
    plan <- arch_build_truth_plan(authority, retained)
    cases[[i]] <- list(taxa = taxa, retained = retained, plan = plan)
    fused_endpoint <- (plan$side_a_size == 1L | plan$side_b_size == 1L) &
      plan$state_template == 2L
    if (is.na(endpoint_index) && any(fused_endpoint)) endpoint_index <- i
    if (length(plan$composites)) {
      for (composite in plan$composites) {
        member_sets[[length(member_sets) + 1L]] <- composite$members
        for (member in composite$members) {
          primitive_patterns[[member]] <- c(primitive_patterns[[member]], i)
        }
        terminal_count <- sum(composite$members %in% terminal)
        if (is.na(terminal_index) && terminal_count >= 1L &&
            length(composite$members) > 1L) terminal_index <- i
        if (is.na(multiple_terminal_index) && terminal_count >= 2L) {
          multiple_terminal_index <- i
        }
      }
    }
  }
  a_assert(!anyNA(c(endpoint_index, terminal_index, multiple_terminal_index)),
           "Torture search did not construct every endpoint/fusion case.")
  same_primitive <- which(vapply(
    primitive_patterns,
    function(index) length(unique(index)) >= 3L,
    logical(1)
  ))
  a_assert(length(same_primitive) > 0L,
           "No primitive edge was exercised under three retained patterns.")
  repeated_indices <- unique(primitive_patterns[[same_primitive[[1L]]]])[1:3]
  selected <- unique(c(
    endpoint_index, terminal_index, multiple_terminal_index, repeated_indices
  ))

  exact_members <- sort(unique(vapply(
    member_sets, arch_member_key, character(1)
  )), method = "radix")
  collision_members <- arch_exact_hash_bucket_dedup(
    member_sets, function(members) "forced-collision"
  )
  a_assert(identical(collision_members, exact_members),
           "Forced B* hash collision changed exact member-set identity.")

  detail <- c(
    "status=PASS",
    paste0("species_taxa=", length(authority$taxa)),
    paste0("candidate_patterns=", length(candidate_sets)),
    paste0("selected_patterns=", length(selected)),
    paste0("unique_exact_Bstar=", length(exact_members)),
    paste0("repeated_primitive=", authority$primitive_id[same_primitive[[1L]]])
  )
  for (i in selected) {
    case <- cases[[i]]
    reference <- case$plan
    observed <- a_unpack_truth_plan(
      a_pack_truth_plan(reference, authority), authority
    )
    a_assert(a_plan_scientific_equal(observed, reference, authority),
             paste("Torture pattern", i, "differs after packed round-trip."))
    observed_keys <- sort(names(observed$composites), method = "radix")
    reference_keys <- sort(names(reference$composites), method = "radix")
    a_assert(identical(observed_keys, reference_keys),
             paste("Torture pattern", i, "changed composite identity."))

    star <- paste0("(", paste0(case$taxa, ":1", collapse = ","), ");")
    production <- align_branches(
      species, stats::setNames(star, paste0("pattern_", i)), mode = "free"
    )
    production_state <- unname(production$state_matrix[1L, ])
    a_assert(all(production_state[reference$state_template == 1L] == "NA_struct"),
             paste("Torture pattern", i, "NA_struct differs from production."))
    a_assert(all(production_state[reference$state_template == 2L] == "NA_fuse"),
             paste("Torture pattern", i, "NA_fuse differs from production."))
    retained_terminal <- terminal[vapply(terminal, function(branch) {
      left <- intersect(authority$side_a[[branch]], case$retained)
      right <- intersect(authority$side_b[[branch]], case$retained)
      length(left) > 0L && length(right) > 0L
    }, logical(1))]
    a_assert(!any(production_state[retained_terminal] %in%
                    c("NA_struct", "NA_topo")),
             paste("Torture pattern", i, "violated terminal-state invariant."))
    detail <- c(detail, paste0(
      "pattern_", i, "_taxa=", paste(case$taxa, collapse = ","),
      ";NA_struct=", sum(reference$state_template == 1L),
      ";NA_fuse=", sum(reference$state_template == 2L),
      ";Bstar=", length(reference$composites)
    ))
  }

  topology_taxa <- c("A", "C", "E", "G")
  topology_records <- a_as_records(c(
    topology_one = "((A:1,C:1):1,(E:1,G:1):1);",
    topology_two = "((A:1,E:1):1,(C:1,G:1):1);"
  ))
  topology_scan <- a_scan_gene_patterns(topology_records, authority)
  topology_registry <- a_make_pattern_registry(list(topology_scan), authority)
  a_assert(length(topology_registry$pattern_ids) == 1L,
           "Gene topology leaked into retained-pattern identity.")
  a_assert(a_reverse_registry_invariant(list(topology_scan), authority),
           "Gene order changed the topology-torture pattern registry.")
  topology_plan <- a_plan_for_pattern(
    topology_registry, authority, topology_registry$pattern_ids[[1L]]
  )
  expected_plan <- arch_build_truth_plan(
    authority, unname(authority$taxon_id[topology_taxa])
  )
  a_assert(a_plan_scientific_equal(topology_plan, expected_plan, authority),
           "Same retained taxa produced topology-dependent truth plans.")
  writeLines(detail, file.path(
    output_dir, "DEGENERATE_AND_FUSION_DETAILS.raw.txt"
  ))
})

toy_species <- "((A:1,B:2):3,(C:4,D:5):6);"
toy_genes <- c(
  complete = "((A:1,B:2):3,(C:4,D:5):6);",
  discordant = "((A:1,C:1):1,(B:1,D:1):1);",
  fusion = "(A:4,B:5);",
  multifurcation = "(A:1,B:2,C:3,D:4);"
)
try_gate("gate", "toy_production_and_terminal_invariant", {
  a_compare_to_production(
    toy_species, toy_genes, tolerance = 1e-10, prefix = "toy"
  )
})

try_gate("store", "cross_strategy_toy_equality", {
  records <- a_as_records(toy_genes)
  context <- a_build_test_context(toy_species, records, "toy-cross")
  disk <- a_open_packed_store(
    context$path, context$registry, context$authority, verify_all_records = TRUE
  )
  stores <- list(
    retain_all = a_new_retain_all_store(
      context$registry, context$authority, loader = disk$get
    ),
    recompute = a_new_recompute_store(context$registry, context$authority),
    lru_very_small = a_new_lru_truth_store(
      context$registry, context$authority, 4096
    ),
    lru_moderate = a_new_lru_truth_store(
      context$registry, context$authority, 32 * 1024^2
    ),
    disk = disk,
    packed_disk_lru = a_new_packed_body_lru(disk, 4096)
  )
  results <- lapply(stores, function(store) {
    a_process_with_store(
      records, context$mapping, context$catalog, store, "sink", "toy"
    )
  })
  signatures <- vapply(
    results, function(x) x$normalized_scientific_checksum, character(1)
  )
  a_assert(length(unique(signatures)) == 1L,
           "Truth-store strategy changed toy scientific output.")
  a_assert(all(vapply(
    results, function(x) x$terminal_na_topo_count, integer(1)
  ) == 0L), "A store strategy created terminal NA_topo.")
  a_assert(stores$lru_very_small$stats()$budget_respected,
           "Very-small LRU exceeded byte budget.")
  a_assert(stores$lru_moderate$stats()$budget_respected,
           "Moderate LRU exceeded byte budget.")
  lapply(stores, function(x) x$close())
  unlink(context$path)
})

try_gate("store", "packed_roundtrip_all_test_patterns", {
  species <- "(((A:1,B:1):1,C:1):1,((D:1,E:1):1,F:1):1);"
  genes <- a_as_records(c(
    g1 = "((A:1,B:1):1,(D:1,E:1):1);",
    g2 = "((A:2,D:2):2,(B:2,E:2):2);",
    g3 = "((A:1,C:1):1,(D:1,F:1):1);"
  ))
  context <- a_build_test_context(species, genes, "roundtrip")
  a_assert(context$catalog$write_result$roundtrip_all_equal,
           "Catalog builder observed a packed round-trip difference.")
  disk <- a_open_packed_store(
    context$path, context$registry, context$authority, verify_all_records = TRUE
  )
  for (pattern_id in context$registry$pattern_ids) {
    expected <- a_plan_for_pattern(
      context$registry, context$authority, pattern_id
    )
    observed <- disk$get(pattern_id)
    a_assert(a_plan_scientific_equal(observed, expected, context$authority),
             paste("Round-trip differs for", pattern_id))
  }
  disk$close()
  unlink(context$path)
})

try_gate("interruption", "incomplete_store_rejected", {
  species <- "((A:1,B:1):1,(C:1,D:1):1);"
  records <- a_as_records(c(
    g1 = "((A:1,B:1):1,C:1);",
    g2 = "((A:1,C:1):1,D:1);"
  ))
  authority <- arch_species_authority(species)
  scan <- a_scan_gene_patterns(records, authority)
  registry <- a_make_pattern_registry(list(scan), authority)
  partial <- file.path(work_dir, "interrupted.partial")
  invisible(a_write_packed_store(
    partial, registry, authority, complete = FALSE, max_patterns = 1L
  ))
  rejected <- inherits(
    try(a_open_packed_store(partial, registry, authority), silent = TRUE),
    "try-error"
  )
  a_assert(rejected, "Incomplete store was mistaken for complete.")
  unlink(partial)
})

try_gate("interruption", "record_corruption_rejected", {
  species <- "((A:1,B:1):1,(C:1,D:1):1);"
  records <- a_as_records(c(
    g1 = "((A:1,B:1):1,C:1);",
    g2 = "((A:1,C:1):1,D:1);"
  ))
  authority <- arch_species_authority(species)
  scan <- a_scan_gene_patterns(records, authority)
  registry <- a_make_pattern_registry(list(scan), authority)
  good <- file.path(work_dir, "corruption-good.bin")
  bad <- file.path(work_dir, "corruption-bad.bin")
  invisible(a_write_packed_store(good, registry, authority))
  a_corrupt_copy_byte(good, bad, 40L)
  rejected <- inherits(
    try(a_open_packed_store(
      bad, registry, authority, verify_all_records = TRUE
    ), silent = TRUE),
    "try-error"
  )
  a_assert(rejected, "Corrupted packed record passed validation.")
  unlink(c(good, bad))
})

try_gate("determinism", "three_repeats_reversal_grouped_interleaved_seeded_random_budgets", {
  species <- "(((A:1,B:1):1,C:1):1,((D:1,E:1):1,F:1):1);"
  newicks <- c(
    g1 = "((A:1,B:1):1,(D:1,E:1):1);",
    g2 = "((A:2,D:2):2,(B:2,E:2):2);",
    g3 = "((A:1,C:1):1,(D:1,F:1):1);",
    g4 = "((A:1,B:1):1,(D:1,E:1):1);"
  )
  base_records <- a_as_records(newicks)
  authority <- arch_species_authority(species)
  base_scan <- a_scan_gene_patterns(base_records, authority)
  registry <- a_make_pattern_registry(list(base_scan), authority)
  path <- file.path(work_dir, "determinism.bin")
  catalog <- a_make_catalog(registry, authority, path)
  set.seed(20260731L)
  orderings <- list(
    original = seq_along(newicks),
    reversed = rev(seq_along(newicks)),
    grouped = order(base_scan$exact_pattern_keys, method = "radix"),
    interleaved = order(
      ave(seq_along(newicks), base_scan$exact_pattern_keys, FUN = seq_along),
      base_scan$exact_pattern_keys, method = "radix"
    ),
    random_seed_20260731 = sample(seq_along(newicks), replace = FALSE)
  )
  signatures <- character()
  for (repeat_id in 1:3) {
    for (ordering_name in names(orderings)) {
      index <- orderings[[ordering_name]]
      records <- base_records[index]
      scan <- a_scan_gene_patterns(records, authority)
      mapping <- data.frame(
        gene_id = scan$gene_ids,
        pattern_id = registry$pattern_ids[
          match(scan$exact_pattern_keys, registry$exact_pattern_keys)
        ],
        exact_pattern_key = scan$exact_pattern_keys,
        stringsAsFactors = FALSE
      )
      for (budget in c(4096, 32768)) {
        disk <- a_open_packed_store(
          path, registry, authority, verify_all_records = FALSE
        )
        store <- a_new_packed_body_lru(disk, budget)
        result <- a_process_with_store(
          records, mapping, catalog, store, "sink",
          paste(repeat_id, ordering_name, budget, sep = "-")
        )
        signatures <- c(signatures, result$normalized_scientific_checksum)
        store$close()
        disk$close()
      }
    }
  }
  a_assert(length(unique(signatures)) == 1L,
           "Order/repeat/cache budget changed normalized output.")
  unlink(path)
})

try_gate("addendum", "support_denominator_zero_is_missing", {
  species <- "(((A:1,B:1):1,C:1):1,((D:1,E:1):1,F:1):1);"
  genes <- c(
    deletion_1 = "(A:1,B:1,C:1);",
    deletion_2 = "((A:1,B:1):1,C:1);",
    deletion_3 = "(A:2,(B:1,C:1):1);"
  )
  records <- a_as_records(genes)
  context <- a_build_test_context(species, records, "support-zero")
  disk <- a_open_packed_store(
    context$path, context$registry, context$authority,
    verify_all_records = TRUE
  )
  store <- a_new_packed_body_lru(disk, 4096)
  result <- a_process_with_store(
    records, context$mapping, context$catalog, store, "compact", "support-zero"
  )
  counts <- result$internal_counts
  denominator <- counts$mapped_count + counts$NA_topo_count
  zero <- which(denominator == 0L)
  a_assert(length(zero) > 0L,
           "Full-clade deletion did not create denominator-zero internals.")
  missing_support <- counts$support[zero]
  a_assert(
    is.double(missing_support) && all(is.na(missing_support)) &&
      !any(is.nan(missing_support)) && !any(is.infinite(missing_support)),
    "Denominator-zero Support(b) was not plain NA_real_."
  )
  decoded <- arch_decode_state_matrix(result$state_matrix)
  zero_ids <- counts$coordinate_id[zero]
  a_assert(all(decoded[, zero_ids, drop = FALSE] %in% c("NA_struct", "NA_fuse")),
           "Denominator-zero branch was not structurally unevaluable.")
  phy <- ape::read.tree(text = species)
  phy$node.label <- rep("placeholder", phy$Nnode)
  phy$node.label[[1L]] <- as.character(missing_support[[1L]])
  a_assert(is.na(phy$node.label[[1L]]) &&
             !identical(phy$node.label[[1L]], "0"),
           "Missing Support(b) became zero when attached to node.label.")
  a_assert(result$terminal_na_topo_count == 0L,
           "Support boundary test created terminal NA_topo.")
  writeLines(c(
    "status=PASS",
    paste0("loci=", length(genes)),
    paste0("denominator_zero_internal_count=", length(zero)),
    paste0("coordinate_ids=", paste(zero_ids, collapse = ",")),
    "support_value=NA_real_",
    "ape_node_label_value=NA"
  ), file.path(output_dir, "SUPPORT_BOUNDARY_DETAILS.raw.txt"))
  store$close()
  disk$close()
  unlink(context$path)
})

try_gate("gate", "catnip10_272_primitive_and_composites", {
  data("catnip10_oracle", package = "SplitAlignerR")
  crosswalk <- subset(catnip10_oracle$branch_map, splitaligner_branch != "-")
  crosswalk <- stats::setNames(
    crosswalk$splitaligner_branch, crosswalk$benchmark_unrooted_branch
  )
  for (regime in c("global", "local")) {
    species_phy <- ape::read.tree(text = catnip10_oracle$species_tree)
    deletion <- catnip10_oracle[[regime]]$deletion_order
    trees <- lapply(0:length(deletion), function(step) {
      if (!step) species_phy else ape::drop.tip(species_phy, deletion[seq_len(step)])
    })
    ids <- paste0("main_step", 0:length(deletion))
    newicks <- stats::setNames(vapply(trees, ape::write.tree, character(1)), ids)
    observed <- a_compare_to_production(
      catnip10_oracle$species_tree, newicks, tolerance = 1e-9,
      prefix = paste0("catnip-", regime)
    )
    frozen <- catnip10_oracle[[regime]]$status_long
    expected <- matrix(
      NA_character_, length(ids), 17L,
      dimnames = list(ids, paste0("B", 1:17))
    )
    for (row in seq_len(nrow(frozen))) {
      state <- if (frozen$status[[row]] == "observed") {
        "mapped"
      } else frozen$status[[row]]
      expected[frozen$gene_id[[row]],
               crosswalk[[frozen$branch_id[[row]]]]] <- state
    }
    a_assert(
      identical(arch_decode_state_matrix(observed$state_matrix), expected),
      paste("Catnip10", regime, "differs from frozen state authority")
    )
  }
})

dir302 <- Sys.getenv("ARCH000A_302_DIR", "")
full_dir <- Sys.getenv("ARCH000A_2275_DIR", "")
ledger_file <- Sys.getenv("ARCH000A_RESIDUAL_LEDGER", "")

if (nzchar(dir302) && dir.exists(dir302)) {
  try_gate("gate", "302mammal_5x601_fixed_free", {
    species <- file.path(dir302, "input", "speciesTree302.nwk")
    fixed <- a_read_records(file.path(dir302, "input", "fix_tree.examples.nwk"))
    free <- a_read_records(file.path(dir302, "input", "free_tree.examples.nwk"))
    common <- intersect(names(fixed), names(free))
    a_assert(
      identical(common, c("A1BG", "A1CF", "A2M", "A4GALT", "A4GNT")),
      "302 five-gene axis differs."
    )
    fixed_observed <- a_compare_to_production(
      species, fixed[common], mode = "fixed", tolerance = 1e-12,
      prefix = "302-fixed"
    )
    free_observed <- a_compare_to_production(
      species, free[common], mode = "free", tolerance = 5e-8,
      prefix = "302-free"
    )
    paired <- a_paired_final_tokens(fixed_observed, free_observed)
    read_expected <- function(path) {
      table <- utils::read.delim(
        path, check.names = FALSE, quote = "", na.strings = character(0),
        stringsAsFactors = FALSE
      )
      result <- as.matrix(table[-1L])
      rownames(result) <- table[[1L]]
      result
    }
    expected_fixed <- read_expected(file.path(
      dir302, "expected", "final.fix.na_classified.txt"
    ))
    expected_free <- read_expected(file.path(
      dir302, "expected", "final.free.na_classified.txt"
    ))
    number <- paste0(
      "^[+-]?(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)(?:[eE][+-]?[0-9]+)?$"
    )
    classify <- function(x) {
      result <- x
      result[grepl(number, result)] <- "numeric"
      result
    }
    a_assert(identical(classify(paired$fixed), classify(expected_fixed)),
             "302 fixed categorical authority differs.")
    a_assert(identical(classify(paired$final), classify(expected_free)),
             "302 free categorical authority differs.")
  })
  try_gate("store", "cross_strategy_302_5x601_fixed_free", {
    species <- file.path(dir302, "input", "speciesTree302.nwk")
    fixed <- a_read_records(file.path(dir302, "input", "fix_tree.examples.nwk"))
    free <- a_read_records(file.path(dir302, "input", "free_tree.examples.nwk"))
    common <- intersect(names(fixed), names(free))
    a_cross_strategy_output(species, fixed[common], "302-fixed-cross")
    a_cross_strategy_output(species, free[common], "302-free-cross")
  })
} else {
  record("gate", "302mammal_5x601_fixed_free", "INCOMPLETE",
         "ARCH000A_302_DIR unavailable")
  record("store", "cross_strategy_302_5x601_fixed_free", "INCOMPLETE",
         "ARCH000A_302_DIR unavailable")
}

if (run_full && nzchar(dir302) && nzchar(full_dir) &&
    nzchar(ledger_file) && file.exists(ledger_file)) {
  try_gate("full", "full_2275_selected_packed_disk_lru", {
    species <- file.path(dir302, "input", "speciesTree302.nwk")
    fixed_path <- file.path(full_dir, "fix.2275genes.nwk")
    free_path <- file.path(full_dir, "free.2275genes.nwk")
    authority <- arch_species_authority(species)
    fixed_scan <- a_scan_gene_patterns(fixed_path, authority)
    free_scan <- a_scan_gene_patterns(free_path, authority)
    registry <- a_make_pattern_registry(list(fixed_scan, free_scan), authority)
    store_path <- file.path(work_dir, "full-authority.truth.bin")
    catalog <- a_make_catalog(registry, authority, store_path)
    a_assert(catalog$write_result$roundtrip_all_equal,
             "Not every authority pattern round-tripped.")
    disk <- a_open_packed_store(
      store_path, registry, authority, verify_all_records = TRUE
    )
    budget <- as.numeric(Sys.getenv(
      "ARCH000A_SELECTED_CACHE_BYTES", 64 * 1024^2
    ))
    selected_store <- a_new_packed_body_lru(disk, budget)
    baseline_stats <- selected_store$stats()
    fixed_result <- a_process_with_store(
      fixed_path, registry$mappings[[1L]], catalog, selected_store,
      "compact", "authority-fixed"
    )
    fixed_stats <- selected_store$stats()
    free_result <- a_process_with_store(
      free_path, registry$mappings[[2L]], catalog, selected_store,
      "compact", "authority-free"
    )
    combined_stats <- selected_store$stats()
    selected_store$close()
    free_stats <- list(
      hits = combined_stats$hits - fixed_stats$hits,
      misses = combined_stats$misses - fixed_stats$misses,
      evictions = combined_stats$evictions - fixed_stats$evictions,
      reloads = combined_stats$reloads - fixed_stats$reloads
    )
    fixed_reloads <- fixed_stats$reloads - baseline_stats$reloads
    a_assert(fixed_result$terminal_na_topo_count == 0L,
             "Fixed authority contains terminal NA_topo.")
    a_assert(free_result$terminal_na_topo_count == 0L,
             "Free authority contains terminal NA_topo.")

    compare_chunks <- function(path, result, mode, chunk_size = 100L) {
      input <- a_read_records(path)
      observed_members <- character()
      for (start in seq.int(1L, length(input), by = chunk_size)) {
        index <- start:min(length(input), start + chunk_size - 1L)
        production <- align_branches(
          species, unname(input[index]), mode = mode,
          gene_ids = names(input)[index]
        )
        observed_state <- arch_decode_state_matrix(
          result$state_matrix[index, , drop = FALSE]
        )
        a_assert(identical(observed_state, production$state_matrix),
                 paste(mode, "authority primitive state differs."))
        columns <- colnames(production$numeric_matrix)
        a_assert(a_numeric_equal(
          result$numeric_matrix[index, columns, drop = FALSE],
          production$numeric_matrix, 1e-9
        ), paste(mode, "authority numeric/composite values differ."))
        observed_members <- c(
          observed_members,
          as.character(production$composite_coordinates$member_text)
        )
      }
      actual_members <- vapply(catalog$bstar_members, function(ids) {
        paste(authority$primitive_id[ids], collapse = "|")
      }, character(1))
      a_assert(
        identical(sort(unique(observed_members), method = "radix"),
                  sort(unique(actual_members), method = "radix")),
        paste(mode, "authority composite registry differs.")
      )
    }
    compare_chunks(fixed_path, fixed_result, "fixed")
    compare_chunks(free_path, free_result, "free")
    paired <- a_paired_final_tokens(fixed_result, free_result)
    residual <- which(paired$final == "NA", arr.ind = TRUE)
    observed_keys <- paste(
      rownames(paired$final)[residual[, "row"]],
      colnames(paired$final)[residual[, "col"]], sep = "\r"
    )
    ledger <- utils::read.delim(
      ledger_file, quote = "", na.strings = character(0),
      stringsAsFactors = FALSE, check.names = FALSE
    )
    expected_keys <- paste(ledger$gene_id, ledger$branch_id, sep = "\r")
    a_assert(length(observed_keys) == 407L, "Residual count is not 407.")
    a_assert(setequal(observed_keys, expected_keys),
             "Residual 407 exact key set differs.")
    summary <- c(
      "status=PASS",
      sprintf("fixed_loci=%d", nrow(fixed_result$state_matrix)),
      sprintf("free_loci=%d", nrow(free_result$state_matrix)),
      sprintf("unique_patterns=%d", length(registry$pattern_ids)),
      sprintf("unique_pattern_fraction=%.12f",
              length(registry$pattern_ids) / nrow(fixed_result$state_matrix)),
      sprintf("unique_Bstar=%d", length(catalog$bstar_keys)),
      sprintf("packed_store_bytes=%.0f", catalog$write_result$file_bytes),
      sprintf("packed_body_bytes_per_pattern=%d",
              catalog$write_result$packed_body_bytes),
      sprintf("verbose_plan_bytes_total=%.0f",
              sum(catalog$write_result$plan_bytes)),
      sprintf("selected_cache_budget_bytes=%.0f", budget),
      sprintf("fixed_cache_hits=%d", fixed_stats$hits),
      sprintf("fixed_cache_misses=%d", fixed_stats$misses),
      sprintf("fixed_cache_evictions=%d", fixed_stats$evictions),
      sprintf("fixed_cache_reloads=%d", fixed_reloads),
      sprintf("free_cache_hits=%d", free_stats$hits),
      sprintf("free_cache_misses=%d", free_stats$misses),
      sprintf("free_cache_evictions=%d", free_stats$evictions),
      sprintf("free_cache_reloads=%d", free_stats$reloads),
      sprintf("fixed_terminal_NA_topo=%d",
              fixed_result$terminal_na_topo_count),
      sprintf("free_terminal_NA_topo=%d",
              free_result$terminal_na_topo_count),
      "residual_keys=407/407",
      "production_primitive_cells_per_side=1367275",
      sprintf("fixed_checksum=%s",
              fixed_result$normalized_scientific_checksum),
      sprintf("free_checksum=%s",
              free_result$normalized_scientific_checksum),
      paste0(
        "fixed_phase_seconds=",
        paste(names(fixed_result$phase_seconds),
              format(fixed_result$phase_seconds, digits = 12), sep = ":",
              collapse = ",")
      ),
      paste0(
        "free_phase_seconds=",
        paste(names(free_result$phase_seconds),
              format(free_result$phase_seconds, digits = 12), sep = ":",
              collapse = ",")
      )
    )
    writeLines(summary, file.path(output_dir, "FULL_AUTHORITY_SUMMARY.raw.txt"))
    disk$close()
    unlink(store_path)
  })
} else {
  record(
    "full", "full_2275_selected_packed_disk_lru", "INCOMPLETE",
    if (run_full) "required authority path unavailable" else
      "ARCH000A_RUN_FULL was not enabled"
  )
}

writeLines(c("gate\tstatus\tdetail", gates),
           file.path(output_dir, "CONFORMANCE_RESULTS.raw.txt"))
writeLines(c("gate\tstatus\tdetail", store_rows),
           file.path(output_dir, "CROSS_STRATEGY_CONFORMANCE.raw.txt"))
writeLines(c("gate\tstatus\tdetail", determinism_rows),
           file.path(output_dir, "DETERMINISM_RESULTS.raw.txt"))
writeLines(c("gate\tstatus\tdetail", interruption_rows),
           file.path(output_dir, "INTERRUPTION_RESULTS.raw.txt"))
writeLines(c("gate\tstatus\tdetail", addendum_rows),
           file.path(output_dir, "ADDENDUM_RESULTS.raw.txt"))
writeLines(c("gate\tstatus\tdetail", full_rows),
           file.path(output_dir, "FULL_AUTHORITY_RESULTS.raw.txt"))

all_rows <- c(
  gates, store_rows, determinism_rows, interruption_rows, addendum_rows,
  full_rows
)
if (any(grepl("\tFAIL\t", all_rows, fixed = TRUE))) quit(status = 1L)
