# ENGINE001 matrix backend freeze

## Decision

Select a 256-row by 256-column tiled layout for the production file-backed
backend. Retain an in-memory compact backend for runs that pass the conservative
planner. Both implement one interface and write the same canonical row/column
axes.

The isolated benchmark measured row-major, R-compatible column-major, and
256x256 tiled files at:

```text
2,275 x 1,086
100,000 x 4,913
```

The larger case is a synthetic layout workload based on the 1,000-taxon stress
coordinate projection; it is not a SplitAligner scientific run. Results are in
`benchmark/MATRIX_LAYOUT_RESULTS.csv`.

## Logical products

State and numeric components are distinct typed files under one manifest:

```text
primitive_state:
  rows = genes
  columns = frozen primitive B
  type = u8

branch_length:
  rows = genes
  columns = B followed by finalized B-star
  type = IEEE-754 binary64 plus validity bitmap

future numeric extension:
  same coordinate axis unless its schema declares a narrower frozen axis
  type = IEEE-754 binary64 plus validity bitmap
```

Primitive state codes in the finalized matrix are:

```text
0 Mapped
1 NA_struct
2 NA_fuse
3 NA_topo
255 unwritten/invalid
```

Numeric missingness uses a one-bit validity bitmap. Missing payload positions
are canonical `+0.0`; readers use the bitmap, not NaN payload identity. Values
must be finite when valid. This is portable and distinguishes unwritten,
missing, and valid zero without relying on R's NA bit pattern.

Composite/fiber provenance is not duplicated into a per-cell long table. It is
reconstructed from gene-to-pattern, packed truth plans, and the coordinate
registry. This retains paired finalization evidence without a second expanded
fusion matrix.

## Backend interface

```text
allocate(dimensions, axes, component_schemas, control)
write_row(gene_index, primitive_state_row, numeric_rows)
read_row(gene_index, components)
read_block(row_range, column_range, components)
read_columns(column_ids, row_range, components)
finalize()
validate(level)
materialize_to_R(component, limit)
export(component, format, destination)
close()
```

Rows must be written exactly once. The backend rejects duplicate, skipped,
out-of-range, or wrong-width rows. Matrix order is finalized before allocation.

## Why tiled layout

Row-major had the fastest streaming writes but required a full scan for a
column. Column-major made column extraction trivial but had costly row-oriented
writes and the highest measured RSS because large row blocks were needed to
amortize seeks. The 256x256 tile retained near-row-major write throughput while
reducing large-case single-column extraction substantially and keeping RSS far
below the column-major case.

Tiles also provide natural units for checksums, optional compression, block
parallelism, and bounded R materialization. The tile dimensions are frozen for
schema v1; a future schema may add alternate tile sizes after cross-platform
evidence.

## In-memory backend

The in-memory backend stores primitive states as raw bytes, validity as packed
bits, and numeric data in contiguous C++ binary64 arrays. R matrices are created
only on explicit materialization or when the planner proves the complete result
safe. The backend does not retain expanded long tables.

The in-memory scientific content and axes are identical to the tiled backend.
Normalized comparison reads through the interface rather than comparing raw
physical layout bytes.

## File-backed component format

Every typed component is a separate file with:

```text
192-byte fixed header
tile payloads in tile-row, then tile-column order
40-byte fixed tile-index entry per tile
96-byte completion footer
```

Separate files were selected over an interleaved container because state-only
and one-numeric-component reads avoid unrelated payload, numeric extensions can
be added without rewriting state, and a corrupt component is named precisely.
The manifest atomically binds the component set.

### Header

The 192-byte header includes:

```text
magic[8]
schema major/minor u16
endianness u8 = little
element type u8
layout u8 = tiled
flags u8
header bytes u32
tile rows u32 = 256
tile columns u32 = 256
row count u64
column count u64
payload bytes u64
tile count u64
index offset u64
footer offset u64
species SHA-256[32]
coordinate-axis SHA-256[32]
gene-axis SHA-256[32]
header xxHash64[8]
reserved zero bytes
```

Checked multiplication validates dimensions, cell count, tile count, payload,
index and final file length before allocation or seek.

### Tile index

Each 40-byte entry contains:

```text
tile_row u32
tile_column u32
payload_offset u64
stored_bytes u64
uncompressed_bytes u64
tile_xxHash64 u64
```

Tiles are row-major internally. Edge tiles use their exact smaller dimensions.
Compression flag 0 means uncompressed. Schema v1 permits a future registered
compression flag but the initial production implementation must be
uncompressed until deterministic cross-platform evidence exists.

### Footer

The 96-byte footer binds completion magic, schema, exact file length, tile
count, index xxHash64, ordered tile-hash xxHash64, payload SHA-256 and footer
xxHash64. A footer does not by itself publish a run; the validated manifest is
published last.

## Planner and memory budgets

The user-facing API does not request a layout. The internal planner calculates:

```text
state payload and tile/index overhead
numeric payload, validity bitmap and tile/index overhead per component
truth-store budget
maximum GeneWorkBuffer bytes
coordinate/pattern registry bytes
R orchestration reserve
available memory and writable storage
```

Default safe memory is 70% of detected available memory or an explicit lower
control budget. In-memory matrices are selected only when:

```text
1.25 * projected matrix bytes
+ truth-store budget
+ maximum gene buffer
+ 256 MiB R/orchestration reserve
<= safe memory

and

projected ordinary-R materialization bytes
<= min(2 GiB, 35% of detected available memory)
```

Otherwise the tiled file backend is selected when free destination storage is
at least 110% of projected component plus manifest bytes. If neither backend is
safe, preflight fails before truth construction.

Advanced users may supply one optional control object with memory, storage and
materialization limits. Backend names, tile sizes, cache mechanics, and pointers
remain internal by default.

## Support and branch-wise access

Support(b) does not require a column scan: `BranchCounters` update while each
primitive state row is written. Post-scan support therefore remains O(B) and
does not dictate column-major storage.

Branch-wise downstream analysis uses `read_columns()` over tiled files. It reads
only tiles intersecting requested columns and row blocks.

## Materialization and export

`materialize_to_R()` checks predicted allocation plus a 25% reserve before
reading. It returns ordinary state/numeric matrices with stable dimnames only
when safe. It never silently attempts a multi-gigabyte R allocation.

`export()` streams blocks and may produce TSV/CSV or future documented formats
without full materialization. Expanded long data frames are derived exports,
not the stored authority.

## Parallel boundary

Future workers own non-overlapping tile-row blocks and thread-local counters.
Only one coordinator writes the final tile index and manifest in canonical
order. Thread count cannot change component bytes, axis order, checksums, or
counter reduction results.
