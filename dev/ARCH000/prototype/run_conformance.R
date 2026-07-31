#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = FALSE)
script_arg <- grep("^--file=", args, value = TRUE)
script_dir <- dirname(normalizePath(sub("^--file=", "", script_arg[[1L]])))
arch_root <- normalizePath(file.path(script_dir, ".."), mustWork = TRUE)
source(file.path(script_dir, "arch000_common.R"))
source(file.path(script_dir, "pattern_truth_cache.R"))
source(file.path(script_dir, "bounded_bstar_dedup.R"))
source(file.path(script_dir, "taxa_scan_baseline.R"))
source(file.path(script_dir, "taxa_scan_candidate.R"))
source(file.path(script_dir, "compact_streaming_matrix.R"))

suppressPackageStartupMessages(library(SplitAlignerR))

output_dir <- Sys.getenv("ARCH000_EVIDENCE_DIR", file.path(arch_root, "evidence"))
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
run_full <- identical(Sys.getenv("ARCH000_RUN_FULL", "0"), "1")
results <- character()
determinism <- character()

record <- function(gate, status, detail = "") {
  line <- paste(gate, status, detail, sep = "\t")
  results <<- c(results, line)
  message(line)
  invisible(status == "PASS")
}

assert <- function(condition, message) {
  if (!isTRUE(condition)) arch_stop(message)
}

as_records <- function(newicks, ids = names(newicks)) {
  if (is.null(ids) || length(ids) != length(newicks) || any(!nzchar(ids))) {
    ids <- sprintf("gene_%06d", seq_along(newicks))
  }
  paste0(ids, unname(newicks))
}

read_record_vector <- function(path) {
  output <- character()
  ids <- character()
  arch_iterate_records(path, function(record, index) {
    output[[index]] <<- record$newick
    ids[[index]] <<- record$id
  })
  stats::setNames(output, ids)
}

numeric_equal <- function(left, right, tolerance = 1e-10) {
  identical(dimnames(left), dimnames(right)) &&
    identical(is.na(left), is.na(right)) &&
    (all(is.na(left)) || max(abs(left[!is.na(left)] - right[!is.na(right)])) <= tolerance)
}

compare_production <- function(label, species, newicks, tolerance = 1e-10) {
  ids <- names(newicks)
  if (is.null(ids)) ids <- sprintf("gene_%06d", seq_along(newicks))
  production <- align_branches(species, unname(newicks), mode = "free", gene_ids = ids)
  compact <- arch_stream_compact(species, as_records(newicks, ids))
  assert(
    identical(arch_decode_state_matrix(compact$state_matrix), production$state_matrix),
    paste(label, "state matrix differs from production")
  )
  assert(
    identical(colnames(compact$numeric_matrix), colnames(production$numeric_matrix)),
    paste(label, "coordinate order differs from production")
  )
  assert(
    numeric_equal(compact$numeric_matrix, production$numeric_matrix, tolerance),
    paste(label, "numeric matrix differs from production")
  )
  expected_members <- if (nrow(production$composite_coordinates)) {
    as.character(production$composite_coordinates$member_text)
  } else character()
  assert(
    identical(as.character(compact$composite_provenance$member_text), expected_members),
    paste(label, "composite-member provenance differs from production")
  )
  compact
}

try_gate <- function(gate, code) {
  tryCatch({
    force(code)
    record(gate, "PASS")
    TRUE
  }, error = function(e) {
    record(gate, "FAIL", conditionMessage(e))
    FALSE
  })
}

toy_ok <- try_gate("toy_complete_discordance_fusion", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  genes <- c(
    complete = "((A:1,B:2):3,(C:4,D:5):6);",
    discordant = "((A:1,C:1):1,(B:1,D:1):1);",
    fusion = "(A:4,B:5);",
    multifurcation = "(A:1,B:2,C:3,D:4);"
  )
  compact <- compare_production("toy", species, genes)
  assert(!any(arch_decode_state_matrix(compact$state_matrix)[,
    compact$authority$branch_type == "terminal", drop = FALSE] == "NA_topo"),
    "terminal NA_topo occurred")
})

try_gate("toy_residual_literal_NA_boundary", {
  species <- paste0("(((A:1,B:1):1,C:1):1,", "((D:1,E:1):1,F:1):1);")
  fixed_newick <- c(g = "((A:1,B:1):1,(D:1,E:1):1);")
  free_newick <- c(g = "((A:1,D:1):1,(B:1,E:1):1);")
  fixed <- arch_stream_compact(species, as_records(fixed_newick))
  free <- arch_stream_compact(species, as_records(free_newick))
  paired <- arch_paired_final_tokens(fixed, free)
  production <- pair_alignment_results(
    align_branches(species, fixed_newick, mode = "fixed"),
    align_branches(species, free_newick, mode = "free")
  )
  assert(identical(paired$final, production$final_matrix),
         "compact paired finalization lost literal residual NA")
})

try_gate("pattern_cache_and_reverse_order", {
  species <- "(((A,B),C),((D,E),F));"
  genes <- c(
    g1 = "((A:1,B:1):1,(D:1,E:1):1);",
    g2 = "((A:2,D:2):2,(B:2,E:2):2);",
    g3 = "((A:1,C:1):1,(D:1,F:1):1);"
  )
  forward <- arch_pattern_cache_demo(species, genes)
  reverse <- arch_pattern_cache_demo(species, rev(genes))
  assert(forward$truth_construction_count == 2L,
         "truth plan was not shared by equal retained-taxa patterns")
  assert(identical(forward$pattern_keys, reverse$pattern_keys),
         "canonical pattern order changed after gene reversal")
  same_pattern <- forward$gene_to_pattern[1:2]
  assert(length(unique(same_pattern)) == 1L,
         "same retained-taxa set did not share one plan")
})

try_gate("bounded_bstar_exact_dedup_and_hash_collision", {
  members <- list(c(1, 2), c(1, 2, 3), c(2, 3), c(1, 2),
                  c(2, 3, 4), c(1, 3), c(1, 2, 3))
  reference <- arch_bstar_reference(members)
  bounded <- arch_bstar_bounded(members, threshold_bytes = 100)
  collision_safe <- arch_exact_hash_bucket_dedup(
    members, hash_fn = function(x) "deliberate-collision"
  )
  truncated_safe <- arch_exact_hash_bucket_dedup(
    members, hash_fn = function(x) substr(arch_member_key(x), 1L, 8L)
  )
  assert(identical(bounded$keys, reference), "bounded B* differs from reference")
  assert(identical(collision_safe, reference), "hash collision manufactured identity")
  assert(identical(truncated_safe, reference), "truncated hash manufactured identity")
  assert(bounded$flush_count > 1L, "test did not exercise periodic compaction")
})

try_gate("taxa_scanner_accepted_grammar", {
  cases <- c(
    quoted = "[&R]((\u0027A a\u0027:1e-9,B:2)95[&x=1]:3,(C:4,D:5):6);",
    multifurcation = "(A:1,B:2,C:3,D:4);",
    root_length = "((A:1,B:2):3,(C:4,D:5):6)root:9;",
    failure_marker = "((A:NaN,B:2):3,(C:4,D:5):6);"
  )
  for (one in cases) {
    assert(
      identical(arch_taxa_scan_candidate(one), arch_taxa_scan_baseline(one)),
      paste("taxa-only scanner differs for", one)
    )
  }
  tmp <- tempfile(fileext = ".nwk")
  writeLines(c(cases[[1L]], cases[[2L]]), tmp)
  seen <- list()
  n <- arch_iterate_records(tmp, function(record, index) {
    seen[[index]] <<- arch_scan_tips(record$newick)
  })
  assert(n == 2L && length(seen) == 2L, "multiple-tree file scan failed")
})

try_gate("catnip10_272_primitive_and_composites", {
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
    compact <- compare_production(
      paste("Catnip10", regime), catnip10_oracle$species_tree, newicks, 1e-9
    )
    frozen <- catnip10_oracle[[regime]]$status_long
    expected <- matrix(NA_character_, length(ids), 17L,
                       dimnames = list(ids, paste0("B", 1:17)))
    for (row in seq_len(nrow(frozen))) {
      state <- if (frozen$status[[row]] == "observed") "mapped" else frozen$status[[row]]
      expected[frozen$gene_id[[row]], crosswalk[[frozen$branch_id[[row]]]]] <- state
    }
    assert(identical(arch_decode_state_matrix(compact$state_matrix), expected),
           paste("Catnip10", regime, "differs from frozen state authority"))
  }
})

dir302 <- Sys.getenv("ARCH000_302_DIR", "")
if (nzchar(dir302) && dir.exists(dir302)) {
  try_gate("302mammal_5x601_fixed_free", {
    species <- file.path(dir302, "input", "speciesTree302.nwk")
    fixed_file <- file.path(dir302, "input", "fix_tree.examples.nwk")
    free_file <- file.path(dir302, "input", "free_tree.examples.nwk")
    fixed_input <- read_record_vector(fixed_file)
    free_input <- read_record_vector(free_file)
    common <- intersect(names(fixed_input), names(free_input))
    assert(identical(common, c("A1BG", "A1CF", "A2M", "A4GALT", "A4GNT")),
           "302 common five-gene axis differs from frozen gate")
    fixed <- arch_stream_compact(species, as_records(fixed_input[common]))
    free <- arch_stream_compact(species, as_records(free_input[common]))
    paired <- arch_paired_final_tokens(fixed, free)
    read_expected <- function(path) {
      table <- utils::read.delim(
        path, check.names = FALSE, quote = "", na.strings = character(0),
        stringsAsFactors = FALSE
      )
      output <- as.matrix(table[-1L])
      rownames(output) <- table[[1L]]
      output
    }
    expected_fixed <- read_expected(file.path(
      dir302, "expected", "final.fix.na_classified.txt"
    ))
    expected_free <- read_expected(file.path(
      dir302, "expected", "final.free.na_classified.txt"
    ))
    numeric_pattern <- paste0(
      "^[+-]?(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)(?:[eE][+-]?[0-9]+)?$"
    )
    classify <- function(x) {
      out <- x
      out[grepl(numeric_pattern, out)] <- "numeric"
      out
    }
    assert(identical(classify(paired$fixed), classify(expected_fixed)),
           "302 fixed categorical output differs")
    assert(identical(classify(paired$final), classify(expected_free)),
           "302 free categorical output differs")
    numeric_max <- function(observed, expected) {
      cells <- grepl(numeric_pattern, expected)
      max(abs(as.numeric(observed[cells]) - as.numeric(expected[cells])))
    }
    assert(numeric_max(paired$fixed, expected_fixed) <= 1e-12,
           "302 fixed numeric output differs")
    assert(numeric_max(paired$final, expected_free) <= 5e-8,
           "302 free numeric output differs")
  })
} else {
  record("302mammal_5x601_fixed_free", "INCOMPLETE", "ARCH000_302_DIR unavailable")
}

full_dir <- Sys.getenv("ARCH000_2275_DIR", "")
ledger_file <- Sys.getenv("ARCH000_RESIDUAL_LEDGER", "")
if (run_full && nzchar(dir302) && nzchar(full_dir) && nzchar(ledger_file) &&
    dir.exists(full_dir) && file.exists(ledger_file)) {
  try_gate("full_2275_and_residual_407", {
    species <- file.path(dir302, "input", "speciesTree302.nwk")
    fixed_file <- file.path(full_dir, "fix.2275genes.nwk")
    free_file <- file.path(full_dir, "free.2275genes.nwk")
    fixed <- arch_stream_compact(species, fixed_file)
    free <- arch_stream_compact(species, free_file)

    compare_production_chunks <- function(path, compact, mode, chunk_size = 100L) {
      input <- read_record_vector(path)
      assert(identical(names(input), rownames(compact$state_matrix)),
             paste(mode, "chunk input gene axis differs"))
      observed_members <- character()
      b <- compact$authority$primitive_count
      for (start in seq.int(1L, length(input), by = chunk_size)) {
        index <- start:min(length(input), start + chunk_size - 1L)
        production <- align_branches(
          species, unname(input[index]), mode = mode, gene_ids = names(input)[index]
        )
        compact_state <- arch_decode_state_matrix(
          compact$state_matrix[index, , drop = FALSE]
        )
        assert(identical(compact_state, production$state_matrix),
               paste(mode, "full primitive-state chunk differs from production"))
        production_columns <- colnames(production$numeric_matrix)
        compact_numeric <- compact$numeric_matrix[
          index, production_columns, drop = FALSE
        ]
        assert(numeric_equal(compact_numeric, production$numeric_matrix, 1e-9),
               paste(mode, "full primitive/composite numeric chunk differs"))
        observed_members <- c(
          observed_members,
          as.character(production$composite_coordinates$member_text)
        )
        rm(production, compact_state, compact_numeric)
        invisible(gc(FALSE))
      }
      assert(identical(
        sort(unique(observed_members), method = "radix"),
        sort(unique(compact$composite_provenance$member_text), method = "radix")
      ), paste(mode, "full composite-member registry differs from production"))
      invisible(TRUE)
    }
    compare_production_chunks(fixed_file, fixed, "fixed")
    compare_production_chunks(free_file, free, "free")
    record(
      "full_2275_production_state_numeric_composite", "PASS",
      "2 x 1,367,275 primitive cells plus every observed composite numeric column"
    )

    paired <- arch_paired_final_tokens(fixed, free)
    residual_index <- which(paired$final == "NA", arr.ind = TRUE)
    observed <- paste(
      rownames(paired$final)[residual_index[, "row"]],
      colnames(paired$final)[residual_index[, "col"]], sep = "\r"
    )
    authority <- utils::read.delim(
      ledger_file, quote = "", na.strings = character(0),
      stringsAsFactors = FALSE, check.names = FALSE
    )
    expected <- paste(authority$gene_id, authority$branch_id, sep = "\r")
    assert(length(observed) == 407L, "compact paired output did not contain 407 residual cells")
    assert(setequal(observed, expected), "compact residual key set differs from authority")
    record(
      "full_2275_residual_authority", "PASS",
      "407/407 exact literal-NA keys"
    )

    saveRDS(list(
      fixed_metrics = fixed$metrics,
      free_metrics = free$metrics,
      observed_residual_keys = sort(observed, method = "radix"),
      production_primitive_cells_per_side = 2275L * 601L,
      production_state_numeric_composite_comparison = "PASS"
    ), file.path(output_dir, "FULL_2275_COMPACT_SUMMARY.rds"), version = 3)
  })
} else {
  record(
    "full_2275_and_residual_407", "INCOMPLETE",
    if (run_full) "required authority path unavailable" else "ARCH000_RUN_FULL was not enabled"
  )
}

try_gate("determinism_three_repeats_and_reversal", {
  species <- "(((A:1,B:1):1,C:1):1,((D:1,E:1):1,F:1):1);"
  genes <- c(
    g1 = "((A:1,B:1):1,(D:1,E:1):1);",
    g2 = "((A:2,D:2):2,(B:2,E:2):2);",
    g3 = "((A:1,C:1):1,(D:1,F:1):1);"
  )
  runs <- replicate(3L, arch_stream_compact(species, as_records(genes)), simplify = FALSE)
  signatures <- vapply(runs, function(x) {
    paste(
      paste(x$pattern_registry$exact_pattern_key, collapse = ";"),
      paste(x$composite_provenance$exact_member_key, collapse = ";"),
      paste(as.integer(x$state_matrix), collapse = ","),
      paste(format(x$numeric_matrix, digits = 17), collapse = ","),
      sep = "\n"
    )
  }, character(1))
  assert(length(unique(signatures)) == 1L, "three repeated runs differ")
  reversed <- arch_stream_compact(species, as_records(rev(genes)))
  assert(identical(
    runs[[1L]]$pattern_registry$exact_pattern_key,
    reversed$pattern_registry$exact_pattern_key
  ), "pattern registry changed after input reversal")
  assert(identical(
    runs[[1L]]$composite_provenance$exact_member_key,
    reversed$composite_provenance$exact_member_key
  ), "coordinate registry changed after input reversal")
  order_forward <- order(rownames(runs[[1L]]$state_matrix), method = "radix")
  order_reverse <- order(rownames(reversed$state_matrix), method = "radix")
  assert(identical(
    runs[[1L]]$state_matrix[order_forward, , drop = FALSE],
    reversed$state_matrix[order_reverse, , drop = FALSE]
  ), "normalized categorical output changed after input reversal")
  determinism <<- c(
    determinism,
    "three_repeated_runs\tPASS\tcanonical registries and matrix payload identical",
    "reversed_gene_order\tPASS\tregistries identical; rows identical after gene-ID normalization"
  )
})

writeLines(c(
  "gate\tstatus\tdetail",
  results
), file.path(output_dir, "CONFORMANCE_RESULTS.txt"), useBytes = TRUE)
writeLines(c(
  "gate\tstatus\tdetail",
  determinism
), file.path(output_dir, "DETERMINISM_RESULTS.txt"), useBytes = TRUE)

if (any(grepl("\tFAIL\t", results, fixed = TRUE))) quit(status = 1L)
