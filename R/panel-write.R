# A panel is readable only after its final manifest is in place.
align_panel_to_disk <- function(species_tree, gene_file, output_dir,
                                mode = c("free", "fixed", "paired"),
                                fixed_file = NULL, batch_size = 32L,
                                fusion_view = c("whole", "direct")) {
  fusion_view <- match.arg(fusion_view)
  mode <- match.arg(mode)
  if (identical(mode, "paired") != !is.null(fixed_file)) {
    stop("Supply fixed_file in paired mode only.", call. = FALSE)
  }
  if (!is.numeric(batch_size) || length(batch_size) != 1L ||
      !is.finite(batch_size) || batch_size < 1 ||
      batch_size > .Machine$integer.max || batch_size != floor(batch_size)) {
    stop("batch_size must be a positive integer.", call. = FALSE)
  }
  path_string <- function(path) {
    is.character(path) && length(path) == 1L && !is.na(path) && nzchar(path)
  }
  input_path <- function(path) {
    if (!path_string(path) || !utils::file_test("-f", path)) {
      stop("Expected an existing input file.", call. = FALSE)
    }
    normalizePath(path, winslash = "/", mustWork = TRUE)
  }
  paths <- c(reference = input_path(species_tree), genes = input_path(gene_file))
  if (mode == "paired") paths["fixed"] <- input_path(fixed_file)
  hash_inputs <- function() {
    vapply(paths, function(p) digest::digest(file = p, algo = "sha256"),
           character(1), USE.NAMES = TRUE)
  }
  source_hash <- hash_inputs()
  scratch <- tempfile("splitaligner-panel-")
  if (!dir.create(scratch)) stop("Cannot create panel worker directory.", call. = FALSE)
  genes_in <- fixed_in <- NULL
  on.exit({
    if (!is.null(genes_in)) try(close(genes_in), silent = TRUE)
    if (!is.null(fixed_in)) try(close(fixed_in), silent = TRUE)
    .unlink_literal(scratch, recursive = TRUE, force = TRUE)
  }, add = TRUE)
  snapshots <- stats::setNames(file.path(scratch, paste0(names(paths), ".input")), names(paths))
  if (!all(file.copy(paths, snapshots, overwrite = FALSE, copy.mode = FALSE))) {
    stop("Cannot snapshot panel inputs.", call. = FALSE)
  }
  snapshot_hash <- vapply(snapshots, function(p) digest::digest(file = p, algo = "sha256"),
                          character(1), USE.NAMES = TRUE)
  if (!identical(source_hash, snapshot_hash)) {
    stop("An input file changed while preparing the panel.", call. = FALSE)
  }
  # Both parsing and the recorded hash refer to these private copies, even if
  # another process changes and later restores an original input pathname.
  reference <- as_species_newick(snapshots[["reference"]])$text
  if (!path_string(output_dir) || !dir.create(output_dir, showWarnings = FALSE)) {
    stop("output_dir must be a new directory under an existing parent.", call. = FALSE)
  }
  output_dir <- normalizePath(output_dir, winslash = "/", mustWork = TRUE)
  complete <- FALSE
  on.exit(if (!complete) .unlink_literal(output_dir, recursive = TRUE), add = TRUE)

  genes_in <- file(snapshots[["genes"]], open = "rt")
  if (mode == "paired") {
    fixed_in <- file(snapshots[["fixed"]], open = "rt")
  }
  job_file <- file.path(scratch, "job.rds")
  result_file <- file.path(scratch, "index.rds")
  package_dir <- system.file(package = "SplitAlignerR", mustWork = TRUE)
  worker <- system.file("panel", "write-batch.R", package = "SplitAlignerR", mustWork = TRUE)
  rscript <- file.path(R.home("bin"), if (.Platform$OS.type == "windows") "Rscript.exe" else "Rscript")
  job <- list(reference = reference, mode = mode, result_file = result_file,
              libs = unique(c(dirname(package_dir), .libPaths())))
  id_batches <- list()
  patterns <- list()
  known_patterns <- list(free = new.env(parent = emptyenv()),
                         fixed = new.env(parent = emptyenv()))
  branches <- NULL
  components <- NULL
  support <- list()

  repeat {
    chunk <- panel_read_records(genes_in, batch_size)
    if (mode == "paired") {
      fixed <- panel_read_records(fixed_in, batch_size)
      if (!identical(chunk$ids, fixed$ids)) {
        stop("Paired inputs require the same gene IDs in the same order.", call. = FALSE)
      }
      job$fixed <- fixed$newicks
    }
    if (!length(chunk$ids)) break
    i <- length(id_batches) + 1L
    shard_name <- sprintf("batch-%08d.rds", i)
    job$shard <- file.path(output_dir, shard_name)
    job$trees <- chunk$newicks
    job$ids <- chunk$ids
    saveRDS(job, job_file, compress = FALSE)
    log <- suppressWarnings(system2(rscript, c("--vanilla", shQuote(worker), shQuote(job_file)),
                                    stdout = TRUE, stderr = TRUE))
    if (!is.null(attr(log, "status")) || !file.exists(result_file)) {
      stop("Panel worker failed for gene ", chunk$ids[[1L]], ".\n",
           paste(log, collapse = "\n"), call. = FALSE)
    }
    index <- readRDS(result_file)
    .unlink_literal(result_file)
    if (i == 1L) {
      branches <- index$branches
      components <- index$components
    } else if (!identical(branches, index$branches) || !identical(components, index$components)) {
      stop("Panel worker produced inconsistent reference coordinates.", call. = FALSE)
    }
    for (role in names(index$support)) {
      batch <- index$support[[role]]
      if (!identical(batch$coordinate_id, branches) ||
          (!is.null(support[[role]]) &&
           !identical(batch$branch_type, support[[role]]$branch_type))) {
        stop("Panel worker produced inconsistent support coordinates.", call. = FALSE)
      }
      columns <- setdiff(names(batch), c("coordinate_id", "branch_type"))
      for (field in columns) {
        batch[[field]] <- as.double(batch[[field]])
        if (!is.null(support[[role]])) {
          batch[[field]] <- batch[[field]] + support[[role]][[field]]
        }
      }
      support[[role]] <- batch
    }
    id_batches[[i]] <- chunk$ids
    patterns[[i]] <- lapply(names(index$patterns), function(role) {
      definitions <- index$patterns[[role]]
      known <- known_patterns[[role]]
      keep <- logical(nrow(definitions))
      for (j in seq_len(nrow(definitions))) {
        id <- definitions$coordinate_id[[j]]
        members <- definitions$primitive_members[[j]]
        # Environment keys are R symbols and have a 10,000-byte limit.
        # Long pattern IDs use a disjoint key space; membership is still exact.
        key <- if (nchar(id, type = "bytes") > 10000L) {
          paste0("sha256:", digest::digest(id, algo = "sha256", serialize = FALSE))
        } else id
        if (!exists(key, known, inherits = FALSE)) {
          assign(key, members, known)
          keep[[j]] <- TRUE
        } else if (!identical(get(key, known, inherits = FALSE), members)) {
          stop("Inconsistent primitive members for ", id, call. = FALSE)
        }
      }
      definitions[keep, , drop = FALSE]
    })
    names(patterns[[i]]) <- names(index$patterns)
  }
  if (!length(id_batches)) stop("The gene file contains no named trees.", call. = FALSE)
  if (!identical(source_hash, hash_inputs())) stop("An input file changed during alignment.", call. = FALSE)
  ids <- unlist(id_batches, use.names = FALSE)
  duplicate <- anyDuplicated(ids)
  if (duplicate) stop("Duplicate gene ID in panel: ", ids[[duplicate]], call. = FALSE)
  last <- cumsum(as.double(lengths(id_batches)))
  files <- sprintf("batch-%08d.rds", seq_along(id_batches))
  shard_sha256 <- vapply(file.path(output_dir, files), function(path) {
    digest::digest(file = path, algo = "sha256")
  }, character(1), USE.NAMES = FALSE)
  manifest <- list(format = "SplitAlignerR-panel-v2", mode = mode, fusion_view = fusion_view,
                   genes = ids, branches = branches,
                   shards = data.frame(file = files, first = c(1, utils::head(last, -1L) + 1),
                                       last = last, sha256 = shard_sha256, stringsAsFactors = FALSE),
                   components = components, reference_newick = reference,
                   input_sha256 = source_hash,
                   package_version = as.character(utils::packageVersion("SplitAlignerR")))
  manifest$patterns <- panel_finish_patterns(patterns, branches)
  manifest$support <- list()
  roles <- if (mode == "paired") c("free", "fixed") else mode
  for (role in roles) {
    table <- support[[role]]
    if (is.null(table) || any(table$n_valid_topologies != length(ids))) {
      stop("Missing support counts for the completed gene set.", call. = FALSE)
    }
    eligible <- table$n_dec > 0
    table$support_fraction <- rep(NA_real_, nrow(table))
    table$support_percent <- rep(NA_real_, nrow(table))
    table$support_fraction[eligible] <- table$n_rec[eligible] / table$n_dec[eligible]
    table$support_percent[eligible] <- 100 * table$n_rec[eligible] / table$n_dec[eligible]
    tree <- cpp_support_newick(reference, stats::setNames(table$support_percent, table$coordinate_id))
    paths <- .write_branch_support_files(table, tree, file.path(output_dir, role))
    relative <- file.path(role, basename(paths))
    manifest$support[[role]] <- data.frame(
      file = relative,
      sha256 = vapply(paths, function(p) digest::digest(file = p, algo = "sha256"),
                      character(1), USE.NAMES = FALSE),
      stringsAsFactors = FALSE
    )
  }
  pending <- file.path(output_dir, "manifest.tmp")
  saveRDS(manifest, pending)
  if (!file.rename(pending, file.path(output_dir, "manifest.rds"))) {
    stop("Cannot publish the completed panel manifest.", call. = FALSE)
  }
  complete <- TRUE
  output_dir
}

# Blank and comment lines do not count as records. Both streams therefore
# advance by the same number of genes regardless of file formatting.
panel_read_records <- function(input, batch_size) {
  parts <- list()
  count <- 0
  while (count < batch_size) {
    lines <- trimws(readLines(input, n = batch_size - count, warn = FALSE, encoding = "UTF-8"))
    if (!length(lines)) break
    lines <- lines[nzchar(lines) & !startsWith(lines, "#")]
    if (length(lines)) {
      parts[[length(parts) + 1L]] <- lines
      count <- count + length(lines)
    }
  }
  if (!count) return(list(ids = character(), newicks = character()))
  records <- gene_records_from_lines(unlist(parts, use.names = FALSE))
  if (anyNA(records$ids)) {
    stop("Panel inputs need one named gene tree per line, for example gene1(A,B);", call. = FALSE)
  }
  records
}
