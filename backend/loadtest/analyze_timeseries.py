"""Reads k6's --out csv= time-series export and prints latency bucketed by concurrent VU count —
the thing the plain --summary-export=summary.json can't show (that's one aggregate percentile
across the whole run; this correlates http_req_duration against the vus metric's own timeline,
both present in the same CSV by default, confirmed against Grafana's own k6 CSV-output docs).

Two passes over the same rows: first build a timestamp->vus lookup from every 'vus' row, then for
every 'http_req_duration' row, find the vus level active at that moment (bisect on the sorted vus
timestamps — a linear scan per row would be O(n*m), fine at 50 VUs/~5k rows but not at the
thousands-of-VUs scale a real capacity run targets) and bucket its duration under that VU level.
"""

import argparse
import bisect
import csv
import sys
from collections import defaultdict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path")
    parser.add_argument(
        "--bucket-size",
        type=int,
        default=10,
        help="round VU counts to the nearest multiple of this before grouping (default 10)",
    )
    args = parser.parse_args()

    with open(args.csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    vus_by_time: dict[int, float] = {}
    for row in rows:
        if row["metric_name"] == "vus":
            vus_by_time[int(float(row["timestamp"]))] = float(row["metric_value"])

    if not vus_by_time:
        sys.exit(
            "No 'vus' rows found — was this CSV generated with `k6 run --out csv=...`? "
            "(the default --summary-export=summary.json alone won't have them)"
        )

    sorted_times = sorted(vus_by_time)

    def vus_at(ts: int) -> float:
        idx = max(bisect.bisect_right(sorted_times, ts) - 1, 0)
        return vus_by_time[sorted_times[idx]]

    durations_by_bucket: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        if row["metric_name"] != "http_req_duration":
            continue
        vus = vus_at(int(float(row["timestamp"])))
        bucket = round(vus / args.bucket_size) * args.bucket_size
        durations_by_bucket[bucket].append(float(row["metric_value"]))

    print(f"{'VUs (bucketed)':>15} {'requests':>10} {'avg ms':>10} {'p95 ms':>10}")
    for bucket in sorted(durations_by_bucket):
        values = sorted(durations_by_bucket[bucket])
        avg = sum(values) / len(values)
        p95 = values[int(len(values) * 0.95)]
        print(f"{bucket:>15} {len(values):>10} {avg:>10.2f} {p95:>10.2f}")


if __name__ == "__main__":
    main()
