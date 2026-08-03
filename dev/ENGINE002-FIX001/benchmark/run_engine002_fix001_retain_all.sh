#!/bin/sh
set -eu

if [ "$#" -ne 5 ]; then
  echo "usage: $0 <retain-all-binary> <output-directory> <counts-csv> <repetitions> <run-prefix-8hex>" >&2
  exit 64
fi

binary=$1
output=$2
counts=$3
repetitions=$4
prefix=$5
runtime_csv="$output/FIX001_RUNTIME_RESULTS.csv"
memory_csv="$output/FIX001_MEMORY_RESULTS.csv"
mkdir -p "$output"

sample_rss() {
  pid=$1
  peak=0
  while kill -0 "$pid" 2>/dev/null; do
    rss=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ' || true)
    case "$rss" in
      ''|*[!0-9]*) ;;
      *) [ "$rss" -le "$peak" ] || peak=$rss ;;
    esac
    sleep 0.05
  done
  echo $((peak * 1024))
}

value() {
  key=$1
  file=$2
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$file"
}

old_ifs=$IFS
IFS=,
set -- $counts
IFS=$old_ifs
for count do
  rep=1
  while [ "$rep" -le "$repetitions" ]; do
    case_dir="$output/retain_all_store_"$count"_rep_"$rep
    mkdir -p "$case_dir"
    run_id=$(printf "%s%08x%08x%08x" "$prefix" "$count" "$rep" 0)
    result="$output/retain_all_"$count"_rep_"$rep".txt"
    "$binary" "$case_dir" "$count" "$run_id" >"$result" 2>&1 &
    run_pid=$!
    peak_rss=$(sample_rss "$run_pid")
    wait "$run_pid"
    builder=$(value builder "$result")
    insert=$(value insert_record_generation_seconds "$result")
    finalize=$(value finalize_validate_publish_seconds "$result")
    total=$(value total_record_bytes "$result")
    final=$(value final_store_bytes "$result")
    mean=$(value mean_record_bytes "$result")
    minimum=$(value minimum_record_bytes "$result")
    maximum=$(value maximum_record_bytes "$result")
    index=$(value index_charged_bytes "$result")
    rps=$(awk -v n="$count" -v s="$insert" 'BEGIN {printf "%.9f", n / s}')
    mbps=$(awk -v b="$total" -v s="$insert" 'BEGIN {printf "%.9f", b / 1048576 / s}')
    builder_high=$(value builder_charged_high_water "$result")
    [ -n "$builder_high" ] || builder_high=$total
    record_high=$(value current_record_high_water "$result")
    [ -n "$record_high" ] || record_high=NA
    write_high=$(value write_buffer_high_water "$result")
    [ -n "$write_high" ] || write_high=NA
    temp_high=$(value temporary_disk_high_water "$result")
    [ -n "$temp_high" ] || temp_high=$final
    echo "$builder,$count,$rep,insert_record_generation,WARM,$insert,$rps,$mbps" >> "$runtime_csv"
    echo "$builder,$count,$rep,finalize_validate_publish,WARM,$finalize,NA,NA" >> "$runtime_csv"
    echo "$builder,$count,$rep,$mean,$minimum,$maximum,$total,$final,$peak_rss,$builder_high,$record_high,$write_high,$index,$temp_high" >> "$memory_csv"
    rep=$((rep + 1))
  done
done
