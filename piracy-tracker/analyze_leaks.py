import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from cleaning import normalize_country, normalize_device_id
from reporting import build_summary, write_country_counts
from validation import NormalizedRow, validate_and_deduplicate


REQUIRED_COLUMNS = ("ip_address", "device_id", "country")


class InputError(Exception):
    pass


@dataclass(frozen=True)
class AnalysisStats:
    rows_read: int
    rejected_missing_device_id: int
    rejected_invalid_ip: int
    duplicates_removed: int
    rows_analyzed: int
    global_unique_devices: int
    multiple_country_devices: int

    @property
    def rejected_rows(self):
        return self.rejected_missing_device_id + self.rejected_invalid_ip


def _read_rows(input_path):
    rows = []
    try:
        with input_path.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None:
                raise InputError("input file is missing the required CSV header")
            missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
            if missing:
                raise InputError(
                    "missing required column(s): {}".format(", ".join(missing))
                )

            for row_number, raw in enumerate(reader, start=2):
                ip_value = raw.get("ip_address")
                device_value = raw.get("device_id")
                country_value = raw.get("country")
                rows.append(
                    NormalizedRow(
                        row_number=row_number,
                        ip_address=(ip_value or "").strip(),
                        device_id=normalize_device_id(device_value),
                        country=normalize_country(country_value),
                        raw_ip_address=ip_value,
                        raw_device_id=device_value,
                        raw_country=country_value,
                    )
                )
    except (OSError, UnicodeError, csv.Error) as error:
        raise InputError("could not read input file: {}".format(error)) from error
    return rows


def run_analysis(input_path, output_dir):
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    rows = _read_rows(input_path)
    accepted, rejected, rejection_counts, duplicates_removed = validate_and_deduplicate(rows)

    countries = defaultdict(set)
    device_countries = defaultdict(list)
    for row in accepted:
        countries[row.country].add(row.device_id)
        if row.country not in device_countries[row.device_id]:
            device_countries[row.device_id].append(row.country)

    multi_country_devices = {
        device_id: seen_countries
        for device_id, seen_countries in device_countries.items()
        if len(seen_countries) > 1
    }
    all_devices = set().union(*countries.values()) if countries else set()
    stats = AnalysisStats(
        rows_read=len(rows),
        rejected_missing_device_id=rejection_counts["missing_device_id"],
        rejected_invalid_ip=rejection_counts["invalid_ip"],
        duplicates_removed=duplicates_removed,
        rows_analyzed=len(accepted),
        global_unique_devices=len(all_devices),
        multiple_country_devices=len(multi_country_devices),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "cleaned_logs.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.writer(file)
        writer.writerow(REQUIRED_COLUMNS)
        for row in accepted:
            writer.writerow([row.ip_address, row.device_id, row.country])

    with (output_dir / "rejected_rows.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.writer(file)
        writer.writerow(["row_number", *REQUIRED_COLUMNS, "reason"])
        for row in rejected:
            writer.writerow(
                [
                    row.row_number,
                    row.ip_address,
                    row.device_id,
                    row.country,
                    row.reason,
                ]
            )

    write_country_counts(output_dir / "country_counts.csv", countries)
    report = build_summary(
        input_path.name,
        stats.rows_read,
        stats.rejected_missing_device_id,
        stats.rejected_invalid_ip,
        stats.duplicates_removed,
        stats.rows_analyzed,
        countries,
        len(all_devices),
        multi_country_devices,
    )
    (output_dir / "summary_report.txt").write_text(report, encoding="utf-8")
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze leaked license key activity logs.")
    parser.add_argument("--input", required=True, help="Path to the source CSV")
    parser.add_argument("--outdir", required=True, help="Directory for generated reports")
    arguments = parser.parse_args(argv)
    try:
        stats = run_analysis(arguments.input, arguments.outdir)
    except InputError as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2
    except OSError as error:
        print("error: could not write output: {}".format(error), file=sys.stderr)
        return 2

    print(
        "Analysis complete: {} rows read, {} analyzed, {} rejected, {} duplicates removed."
        .format(stats.rows_read, stats.rows_analyzed, stats.rejected_rows, stats.duplicates_removed)
    )
    print("Reports written to {}".format(Path(arguments.outdir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
