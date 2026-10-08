# SAR-C14N-1: explicit typed logical identity; independent of R serialization.
# The byte grammar and claim ceiling are in HASH_CONTRACT_H01_PROPOSAL_R1.md.
.sx_utf8 <- function(x) {
  .sx_need(is.character(x), "canonical text must be character")
  out <- x
  for (i in seq_along(x)) {
    if (is.na(x[[i]])) next
    flag <- Encoding(x[[i]])
    .sx_need(flag != "bytes", "bytes-marked text is unsupported; use raw vectors")
    value <- if (flag == "latin1") iconv(x[[i]], from = "latin1", to = "UTF-8", sub = NA) else {
      # The profile explicitly defines unmarked bytes as UTF-8, not native locale.
      raw_text <- rawToChar(charToRaw(x[[i]]))
      iconv(raw_text, from = "UTF-8", to = "UTF-8", sub = NA)
    }
    .sx_need(!is.na(value), "canonical text contains invalid UTF-8")
    Encoding(value) <- "UTF-8"
    out[[i]] <- value
  }
  out
}

.sx_canonical_bytes <- function(x) {
  con <- rawConnection(raw(), "wb"); on.exit(close(con))
  writeBin(charToRaw("SAR-C14N-1\n"), con)
  count <- function(n) {
    .sx_need(length(n) == 1L && is.finite(n) && n >= 0 && n <= 2147483647 && n == floor(n),
             "canonical length exceeds v1 bounds")
    writeBin(as.integer(n), con, size = 4L, endian = "big")
  }
  emit <- function(z, depth = 0L) {
    .sx_need(depth <= 128L && !isS4(z), "unsupported canonical object depth or S4 value")
    if (is.null(z)) { writeBin(as.raw(0L), con); return(invisible(NULL)) }
    types <- c(logical = 1L, integer = 2L, double = 3L, character = 4L, raw = 5L, list = 6L)
    type <- typeof(z)
    .sx_need(type %in% names(types), paste("unsupported canonical R type", type))
    attrs <- attributes(z); attributes(z) <- NULL
    writeBin(as.raw(types[[type]]), con); count(length(z))
    if (type == "logical") {
      writeBin(as.raw(ifelse(is.na(z), 2L, as.integer(z))), con)
    } else if (type == "integer") {
      writeBin(z, con, size = 4L, endian = "big")
    } else if (type == "double") {
      for (v in z) {
        tag <- if (is.nan(v)) 2L else if (is.na(v)) 1L else if (is.infinite(v)) {
          if (v > 0) 3L else 4L
        } else 0L
        writeBin(as.raw(tag), con)
        if (tag == 0L) writeBin(v, con, size = 8L, endian = "big")
      }
    } else if (type == "character") {
      z <- .sx_utf8(z)
      for (v in z) {
        writeBin(as.raw(if (is.na(v)) 0L else 1L), con)
        if (!is.na(v)) { bytes <- charToRaw(v); count(length(bytes)); writeBin(bytes, con) }
      }
    } else if (type == "raw") {
      writeBin(z, con)
    } else {
      for (member in z) emit(member, depth + 1L)
    }
    # Attributes use a structural block, not a named-list wrapper with its own attributes.
    count(length(attrs))
    if (length(attrs)) for (i in seq_along(attrs)) {
      name <- charToRaw(.sx_utf8(names(attrs)[[i]]))
      count(length(name)); writeBin(name, con)
      emit(attrs[[i]], depth + 1L)
    }
    invisible(NULL)
  }
  emit(x)
  rawConnectionValue(con)
}
.sx_hash <- function(x) digest::digest(.sx_canonical_bytes(x), algo = "sha256", serialize = FALSE)
