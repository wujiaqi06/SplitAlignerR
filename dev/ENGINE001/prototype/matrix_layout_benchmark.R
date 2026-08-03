## ENGINE001 isolated matrix layout benchmark.
## Synthetic payloads only; this does not run the SplitAligner mapper.

e1_matrix_header_bytes <- 192
e1_matrix_footer_bytes <- 96
e1_tile_rows <- 256L
e1_tile_cols <- 256L
e1_materialization_limit <- 1024^3

e1_elapsed <- function(expression) {
  started <- proc.time()[["elapsed"]]
  value <- force(expression)
  list(value = value, seconds = unname(proc.time()[["elapsed"]] - started))
}

e1_preallocate <- function(path, payload_bytes) {
  total <- e1_matrix_header_bytes + payload_bytes + e1_matrix_footer_bytes
  con <- file(path, open = "w+b")
  writeBin(raw(e1_matrix_header_bytes), con)
  seek(con, where = total - 1, origin = "start", rw = "write")
  writeBin(as.raw(0L), con)
  seek(con, where = e1_matrix_header_bytes, origin = "start", rw = "write")
  con
}

e1_make_block <- function(first_row, last_row, cols) {
  row_ids <- seq.int(first_row, last_row)
  col_ids <- seq_len(cols)
  numeric <- outer(as.double(row_ids) * 1e-6, as.double(col_ids), "+")
  state <- outer(as.integer(row_ids), as.integer(col_ids),
                 function(left, right) (left + right) %% 3L)
  list(state = state, numeric = numeric)
}

e1_write_row_major <- function(state_con, numeric_con, rows, cols) {
  block_rows <- e1_tile_rows
  for (first in seq.int(1L, rows, by = block_rows)) {
    last <- min(rows, first + block_rows - 1L)
    block <- e1_make_block(first, last, cols)
    writeBin(as.raw(as.vector(t(block$state))), state_con)
    writeBin(as.double(as.vector(t(block$numeric))), numeric_con,
             size = 8L, endian = "little")
  }
}

e1_write_column_major <- function(state_con, numeric_con, rows, cols) {
  block_rows <- if (rows >= 100000L) 4096L else 512L
  for (first in seq.int(1L, rows, by = block_rows)) {
    last <- min(rows, first + block_rows - 1L)
    block <- e1_make_block(first, last, cols)
    for (column in seq_len(cols)) {
      state_offset <- e1_matrix_header_bytes +
        (as.double(column - 1L) * rows + first - 1L)
      numeric_offset <- e1_matrix_header_bytes +
        (as.double(column - 1L) * rows + first - 1L) * 8
      seek(state_con, where = state_offset, origin = "start", rw = "write")
      writeBin(as.raw(block$state[, column]), state_con)
      seek(numeric_con, where = numeric_offset, origin = "start", rw = "write")
      writeBin(as.double(block$numeric[, column]), numeric_con,
               size = 8L, endian = "little")
    }
  }
}

e1_write_tiled <- function(state_con, numeric_con, rows, cols) {
  for (first in seq.int(1L, rows, by = e1_tile_rows)) {
    last <- min(rows, first + e1_tile_rows - 1L)
    block <- e1_make_block(first, last, cols)
    for (first_col in seq.int(1L, cols, by = e1_tile_cols)) {
      last_col <- min(cols, first_col + e1_tile_cols - 1L)
      index <- first_col:last_col
      writeBin(as.raw(as.vector(t(block$state[, index, drop = FALSE]))), state_con)
      writeBin(as.double(as.vector(t(block$numeric[, index, drop = FALSE]))),
               numeric_con, size = 8L, endian = "little")
    }
  }
}

e1_read_block <- function(layout, state_path, numeric_path, rows, cols) {
  count <- min(rows, e1_tile_rows)
  state_con <- file(state_path, open = "rb")
  numeric_con <- file(numeric_path, open = "rb")
  on.exit(close(state_con), add = TRUE)
  on.exit(close(numeric_con), add = TRUE)
  state <- raw()
  numeric <- numeric()
  if (layout %in% c("row_major", "tiled_256x256")) {
    seek(state_con, e1_matrix_header_bytes, origin = "start", rw = "read")
    seek(numeric_con, e1_matrix_header_bytes, origin = "start", rw = "read")
    state <- readBin(state_con, "raw", n = count * cols)
    numeric <- readBin(numeric_con, double(), n = count * cols,
                       size = 8L, endian = "little")
  } else {
    state <- raw(count * cols)
    numeric <- numeric(count * cols)
    for (column in seq_len(cols)) {
      state_offset <- e1_matrix_header_bytes + as.double(column - 1L) * rows
      numeric_offset <- e1_matrix_header_bytes +
        as.double(column - 1L) * rows * 8
      seek(state_con, state_offset, origin = "start", rw = "read")
      seek(numeric_con, numeric_offset, origin = "start", rw = "read")
      target <- (column - 1L) * count + seq_len(count)
      state[target] <- readBin(state_con, "raw", n = count)
      numeric[target] <- readBin(numeric_con, double(), n = count,
                                 size = 8L, endian = "little")
    }
  }
  sum(as.integer(state)) + sum(numeric)
}

e1_read_column <- function(layout, numeric_path, rows, cols) {
  column <- as.integer(ceiling(cols / 2))
  con <- file(numeric_path, open = "rb")
  on.exit(close(con), add = TRUE)
  output <- numeric(rows)
  if (layout == "column_major") {
    offset <- e1_matrix_header_bytes + as.double(column - 1L) * rows * 8
    seek(con, offset, origin = "start", rw = "read")
    output <- readBin(con, double(), n = rows, size = 8L, endian = "little")
  } else if (layout == "row_major") {
    block_rows <- e1_tile_rows
    for (first in seq.int(1L, rows, by = block_rows)) {
      last <- min(rows, first + block_rows - 1L)
      count <- last - first + 1L
      offset <- e1_matrix_header_bytes + as.double(first - 1L) * cols * 8
      seek(con, offset, origin = "start", rw = "read")
      values <- readBin(con, double(), n = count * cols,
                        size = 8L, endian = "little")
      matrix_block <- matrix(values, nrow = count, ncol = cols, byrow = TRUE)
      output[first:last] <- matrix_block[, column]
    }
  } else {
    tile_column <- ((column - 1L) %/% e1_tile_cols) + 1L
    local_column <- ((column - 1L) %% e1_tile_cols) + 1L
    columns_before <- (tile_column - 1L) * e1_tile_cols
    for (first in seq.int(1L, rows, by = e1_tile_rows)) {
      last <- min(rows, first + e1_tile_rows - 1L)
      count <- last - first + 1L
      tile_first_col <- (tile_column - 1L) * e1_tile_cols + 1L
      tile_width <- min(e1_tile_cols, cols - tile_first_col + 1L)
      previous_rows <- first - 1L
      element_offset <- as.double(previous_rows) * cols +
        as.double(count) * columns_before
      seek(con, e1_matrix_header_bytes + element_offset * 8,
           origin = "start", rw = "read")
      values <- readBin(con, double(), n = count * tile_width,
                        size = 8L, endian = "little")
      tile <- matrix(values, nrow = count, ncol = tile_width, byrow = TRUE)
      output[first:last] <- tile[, local_column]
    }
  }
  sum(output)
}

e1_full_payload_scan <- function(state_path, numeric_path, cells) {
  state_con <- file(state_path, open = "rb")
  numeric_con <- file(numeric_path, open = "rb")
  on.exit(close(state_con), add = TRUE)
  on.exit(close(numeric_con), add = TRUE)
  seek(state_con, e1_matrix_header_bytes, origin = "start", rw = "read")
  seek(numeric_con, e1_matrix_header_bytes, origin = "start", rw = "read")
  remaining <- as.double(cells)
  state_sum <- 0
  numeric_sum <- 0
  observed <- 0
  chunk <- 1024L * 1024L
  while (remaining > 0) {
    count <- as.integer(min(remaining, chunk))
    state <- readBin(state_con, "raw", n = count)
    numeric <- readBin(numeric_con, double(), n = count,
                       size = 8L, endian = "little")
    if (length(state) != count || length(numeric) != count) {
      stop("Matrix payload full scan encountered truncation.", call. = FALSE)
    }
    state_sum <- state_sum + sum(as.integer(state))
    numeric_sum <- numeric_sum + sum(numeric)
    observed <- observed + count
    remaining <- remaining - count
  }
  list(cells = observed, state_sum = state_sum, numeric_sum = numeric_sum)
}

e1_materialize <- function(layout, state_path, numeric_path, rows, cols) {
  predicted <- as.double(rows) * cols * 9
  if (predicted > e1_materialization_limit) {
    return(list(status = "NOT_ATTEMPTED_PLANNER_LIMIT", checksum = NA_real_))
  }
  state_con <- file(state_path, open = "rb")
  numeric_con <- file(numeric_path, open = "rb")
  on.exit(close(state_con), add = TRUE)
  on.exit(close(numeric_con), add = TRUE)
  seek(state_con, e1_matrix_header_bytes, origin = "start", rw = "read")
  seek(numeric_con, e1_matrix_header_bytes, origin = "start", rw = "read")
  if (layout != "tiled_256x256") {
    state_values <- readBin(state_con, "raw", n = rows * cols)
    numeric_values <- readBin(numeric_con, double(), n = rows * cols,
                              size = 8L, endian = "little")
    byrow <- layout == "row_major"
    state <- matrix(state_values, nrow = rows, ncol = cols, byrow = byrow)
    numeric <- matrix(numeric_values, nrow = rows, ncol = cols, byrow = byrow)
  } else {
    state <- matrix(raw(rows * cols), nrow = rows, ncol = cols)
    numeric <- matrix(NA_real_, nrow = rows, ncol = cols)
    for (first in seq.int(1L, rows, by = e1_tile_rows)) {
      last <- min(rows, first + e1_tile_rows - 1L)
      row_count <- last - first + 1L
      for (first_col in seq.int(1L, cols, by = e1_tile_cols)) {
        last_col <- min(cols, first_col + e1_tile_cols - 1L)
        col_count <- last_col - first_col + 1L
        count <- row_count * col_count
        state_tile <- readBin(state_con, "raw", n = count)
        numeric_tile <- readBin(numeric_con, double(), n = count,
                                size = 8L, endian = "little")
        state[first:last, first_col:last_col] <- matrix(
          state_tile, nrow = row_count, ncol = col_count, byrow = TRUE
        )
        numeric[first:last, first_col:last_col] <- matrix(
          numeric_tile, nrow = row_count, ncol = col_count, byrow = TRUE
        )
      }
    }
  }
  list(status = "MEASURED", checksum = sum(as.integer(state)) + sum(numeric))
}

e1_run_matrix_case <- function(layout, rows, cols, output_csv, work_root) {
  if (!layout %in% c("row_major", "column_major", "tiled_256x256")) {
    stop("Unknown ENGINE001 matrix layout.", call. = FALSE)
  }
  dir.create(work_root, recursive = TRUE, showWarnings = FALSE)
  case_root <- tempfile(sprintf("%s-", layout), tmpdir = work_root)
  dir.create(case_root)
  on.exit(unlink(case_root, recursive = TRUE, force = TRUE), add = TRUE)
  state_path <- file.path(case_root, "state.bin")
  numeric_path <- file.path(case_root, "numeric.bin")
  cells <- as.double(rows) * cols
  state_con <- e1_preallocate(state_path, cells)
  numeric_con <- e1_preallocate(numeric_path, cells * 8)
  write_result <- e1_elapsed({
    if (layout == "row_major") {
      e1_write_row_major(state_con, numeric_con, rows, cols)
    } else if (layout == "column_major") {
      e1_write_column_major(state_con, numeric_con, rows, cols)
    } else {
      e1_write_tiled(state_con, numeric_con, rows, cols)
    }
    flush(state_con)
    flush(numeric_con)
  })
  close(state_con)
  close(numeric_con)
  block_result <- e1_elapsed(
    e1_read_block(layout, state_path, numeric_path, rows, cols)
  )
  column_result <- e1_elapsed(
    e1_read_column(layout, numeric_path, rows, cols)
  )
  full_scan <- e1_elapsed(
    e1_full_payload_scan(state_path, numeric_path, cells)
  )
  if (full_scan$value$cells != cells) {
    stop("Matrix full-scan cell count differs.", call. = FALSE)
  }
  materialized <- e1_elapsed(
    e1_materialize(layout, state_path, numeric_path, rows, cols)
  )
  file_bytes <- sum(file.info(c(state_path, numeric_path))$size)
  validity_payload_bytes <- ceiling(cells / 8)
  projected_production_bytes <- file_bytes + validity_payload_bytes +
    e1_matrix_header_bytes + e1_matrix_footer_bytes
  result <- data.frame(
    workload = if (rows == 2275L) "AUTHORITY_SHAPE_SYNTHETIC" else
      "LARGE_PROJECTED_SHAPE_SYNTHETIC",
    layout = layout,
    rows = rows,
    columns = cols,
    cells = cells,
    tile_rows = if (layout == "tiled_256x256") e1_tile_rows else NA_integer_,
    tile_columns = if (layout == "tiled_256x256") e1_tile_cols else NA_integer_,
    row_write_seconds = write_result$seconds,
    row_write_cells_per_second = cells / write_result$seconds,
    block_read_seconds = block_result$seconds,
    column_extract_seconds = column_result$seconds,
    full_payload_scan_seconds = full_scan$seconds,
    r_materialization_seconds = if (materialized$value$status == "MEASURED")
      materialized$seconds else NA_real_,
    r_materialization_status = materialized$value$status,
    logical_file_bytes = file_bytes,
    derived_validity_component_bytes = validity_payload_bytes +
      e1_matrix_header_bytes + e1_matrix_footer_bytes,
    derived_production_total_bytes = projected_production_bytes,
    peak_rss_bytes = NA_real_,
    measured_or_projected = "MEASURED_SYNTHETIC_LAYOUT_ONLY",
    block_checksum = block_result$value,
    column_checksum = column_result$value,
    full_state_checksum = full_scan$value$state_sum,
    full_numeric_checksum = full_scan$value$numeric_sum,
    materialized_checksum = materialized$value$checksum,
    stringsAsFactors = FALSE
  )
  write.csv(result, output_csv, row.names = FALSE, quote = TRUE)
  invisible(result)
}

if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 5L) {
    stop("Usage: matrix_layout_benchmark.R layout rows cols output.csv work_root",
         call. = FALSE)
  }
  e1_run_matrix_case(args[[1L]], as.integer(args[[2L]]),
                     as.integer(args[[3L]]), args[[4L]], args[[5L]])
}
