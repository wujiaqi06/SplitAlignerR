#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  echo "usage: $0 <installed-library> <output-directory> <counts-csv> <repetitions>" >&2
  exit 64
fi

library=$1
output=$2
counts=$3
repetitions=$4
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
mkdir -p "$output"

runtime_csv="$output/FIX001_RUNTIME_RESULTS.csv"
memory_csv="$output/FIX001_MEMORY_RESULTS.csv"
large_csv="$output/FIX001_LARGE_OFFSET_RESULTS.csv"
if [ ! -f "$runtime_csv" ]; then
  echo "builder,pattern_count,repetition,phase,cache_state,seconds,records_per_second,megabytes_per_second" > "$runtime_csv"
fi
if [ ! -f "$memory_csv" ]; then
  echo "builder,pattern_count,repetition,mean_record_bytes,minimum_record_bytes,maximum_record_bytes,total_record_bytes,final_store_bytes,peak_rss_bytes,builder_charged_high_water,current_record_high_water,write_buffer_high_water,index_charged_bytes,temporary_disk_high_water" > "$memory_csv"
fi
if [ ! -f "$large_csv" ]; then
  echo "pattern_count,repetition,final_store_bytes,header_index_offset,header_footer_offset,header_exact_file_bytes,actual_file_bytes,last_index_pattern_id,footer_record_count,new_process_reopen,manifest" > "$large_csv"
fi

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
    case_dir="$output/store_"$count"_rep_"$rep
    mkdir -p "$case_dir"
    run_id=$(printf "%08x%08xfeedfacecafebeef" "$count" "$rep")
    result="$output/build_"$count"_rep_"$rep".txt"
    stdout="$output/build_"$count"_rep_"$rep".stdout.txt"
    Rscript "$repo/tools/engine002/fix001_large_offset.R" \
      "$library" "$case_dir" "$count" "$run_id" "$result" >"$stdout" 2>&1 &
    build_pid=$!
    peak_rss=$(sample_rss "$build_pid")
    wait "$build_pid"

    manifest=$(value manifest "$result")
    reopen="$output/reopen_"$count"_rep_"$rep".txt"
    reopen_stdout="$output/reopen_"$count"_rep_"$rep".stdout.txt"
    Rscript "$repo/tools/engine002/fix001_large_offset_reopen.R" \
      "$library" "$manifest" "$count" "$reopen" >"$reopen_stdout" 2>&1

    mean=$(value mean_record_bytes "$result")
    minimum=$(value minimum_record_bytes "$result")
    maximum=$(value maximum_record_bytes "$result")
    total=$(value total_record_bytes "$result")
    final=$(value final_store_bytes "$result")
    builder_high=$(value builder_charged_high_water "$result")
    record_high=$(value current_record_high_water "$result")
    write_high=$(value write_buffer_high_water "$result")
    index=$(value index_charged_bytes "$result")
    temp_high=$(value temporary_disk_high_water "$result")
    stream_seconds=$(value streaming_write_seconds "$result")
    finalize_seconds=$(value finalize_validate_publish_seconds "$result")
    finalize_io_seconds=$(value finalize_io_seconds "$result")
    temporary_validation_seconds=$(value temporary_validation_seconds "$result")
    manifest_prepare_seconds=$(value manifest_prepare_seconds "$result")
    atomic_publication_seconds=$(value atomic_publication_seconds "$result")
    published_validation_seconds=$(value published_validation_seconds "$result")
    total_seconds=$(value elapsed_seconds "$result")
    validate_seconds=$(value open_full_validation_seconds "$reopen")
    sequential_seconds=$(value sequential_lookup_seconds "$reopen")
    random_seconds=$(value random_lookup_seconds "$reopen")
    warm_seconds=$(value lru_warm_lookup_seconds "$reopen")
    sha_seconds=$(value complete_file_sha256_seconds "$reopen")
    probes=$(value functional_probe_count "$reopen")

    throughput() {
      numerator=$1
      seconds=$2
      awk -v n="$numerator" -v s="$seconds" 'BEGIN {if (s > 0) printf "%.9f", n / s; else print "NA"}'
    }
    mbps() {
      bytes=$1
      seconds=$2
      awk -v b="$bytes" -v s="$seconds" 'BEGIN {if (s > 0) printf "%.9f", b / 1048576 / s; else print "NA"}'
    }
    echo "streaming,$count,$rep,streaming_write,WARM,$stream_seconds,$(throughput "$count" "$stream_seconds"),$(mbps "$total" "$stream_seconds")" >> "$runtime_csv"
    echo "streaming,$count,$rep,finalize_validate_publish,WARM,$finalize_seconds,NA,$(mbps "$final" "$finalize_seconds")" >> "$runtime_csv"
    if [ -n "$finalize_io_seconds" ]; then
      echo "streaming,$count,$rep,finalize_io,WARM,$finalize_io_seconds,NA,$(mbps "$final" "$finalize_io_seconds")" >> "$runtime_csv"
      echo "streaming,$count,$rep,temporary_full_validation,WARM,$temporary_validation_seconds,NA,$(mbps "$final" "$temporary_validation_seconds")" >> "$runtime_csv"
      echo "streaming,$count,$rep,manifest_prepare,WARM,$manifest_prepare_seconds,NA,NA" >> "$runtime_csv"
      echo "streaming,$count,$rep,atomic_publication,WARM,$atomic_publication_seconds,NA,NA" >> "$runtime_csv"
      echo "streaming,$count,$rep,published_full_validation,WARM,$published_validation_seconds,NA,$(mbps "$final" "$published_validation_seconds")" >> "$runtime_csv"
    fi
    echo "streaming,$count,$rep,total_build,WARM,$total_seconds,$(throughput "$count" "$total_seconds"),$(mbps "$total" "$total_seconds")" >> "$runtime_csv"
    echo "streaming,$count,$rep,new_process_full_validation,PROCESS_COLD_FILE_CACHE_UNCONTROLLED,$validate_seconds,NA,$(mbps "$final" "$validate_seconds")" >> "$runtime_csv"
    echo "streaming,$count,$rep,sequential_lookup,PROCESS_COLD_FILE_CACHE_UNCONTROLLED,$sequential_seconds,$(throughput "$probes" "$sequential_seconds"),NA" >> "$runtime_csv"
    echo "streaming,$count,$rep,fixed_seed_random_lookup,PROCESS_COLD_FILE_CACHE_UNCONTROLLED,$random_seconds,$(throughput "$probes" "$random_seconds"),NA" >> "$runtime_csv"
    echo "streaming,$count,$rep,lru_warm_lookup,WARM,$warm_seconds,$(throughput "$probes" "$warm_seconds"),NA" >> "$runtime_csv"
    echo "streaming,$count,$rep,complete_file_sha256,WARM,$sha_seconds,NA,$(mbps "$final" "$sha_seconds")" >> "$runtime_csv"
    echo "streaming,$count,$rep,$mean,$minimum,$maximum,$total,$final,$peak_rss,$builder_high,$record_high,$write_high,$index,$temp_high" >> "$memory_csv"
    echo "$count,$rep,$final,$(value header_index_offset "$result"),$(value header_footer_offset "$result"),$(value header_exact_file_bytes "$result"),$(value actual_file_bytes "$result"),$(value last_index_pattern_id "$result"),$(value footer_record_count "$result"),$(value status "$reopen"),$manifest" >> "$large_csv"
    rep=$((rep + 1))
  done
done
