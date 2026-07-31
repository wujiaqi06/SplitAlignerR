## The implementation lives in arch000_common.R so every prototype uses the
## same exact member-set identity and bounded accumulator.

arch_bstar_reference <- function(member_sets) {
  sort(unique(vapply(member_sets, arch_member_key, character(1))),
       method = "radix")
}

arch_bstar_bounded <- function(member_sets, threshold_bytes = 32 * 1024^2) {
  accumulator <- arch_new_bstar_accumulator(threshold_bytes)
  for (members in member_sets) arch_bstar_add(accumulator, members)
  list(
    keys = arch_bstar_finalize(accumulator),
    peak_pending_bytes = accumulator$peak_pending_bytes,
    flush_count = accumulator$flush_count
  )
}
