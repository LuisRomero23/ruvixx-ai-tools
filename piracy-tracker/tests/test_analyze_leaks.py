import csv
import hashlib
from pathlib import Path

import pytest

from analyze_leaks import main, run_analysis
from cleaning import normalize_country, normalize_device_id
from validation import normalize_ip


ROOT = Path(__file__).resolve().parents[1]
MOCK_DATA = ROOT / "leaked_logs.csv"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("brazil", "Brazil"),
        ("BRAZIL", "Brazil"),
        (" Brazil ", "Brazil"),
        ("united states", "United States"),
        ("USA", "United States"),
        ("  U.S.  ", "United States"),
        ("", "Unknown"),
    ],
)
def test_normalize_country(value, expected):
    assert normalize_country(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("dev-2003", "DEV-2003"),
        ("", None),
        ("N/A", None),
        ("null", None),
        ("   ", None),
    ],
)
def test_normalize_device_id(value, expected):
    assert normalize_device_id(value) == expected


@pytest.mark.parametrize("value", ["999.1.1.1", "abc", ""])
def test_invalid_ip_is_rejected(value):
    with pytest.raises(ValueError):
        normalize_ip(value)


def test_ip_is_trimmed_and_canonicalized():
    assert normalize_ip(" 192.0.2.41") == "192.0.2.41"
    assert normalize_ip("2001:0db8::1") == "2001:db8::1"


def test_mock_data_generates_golden_outputs(tmp_path):
    before = hashlib.sha256(MOCK_DATA.read_bytes()).digest()

    stats = run_analysis(MOCK_DATA, tmp_path)

    assert stats.rows_read == 31
    assert stats.rejected_missing_device_id == 3
    assert stats.rejected_invalid_ip == 1
    assert stats.duplicates_removed == 2
    assert stats.rows_analyzed == 25
    assert stats.global_unique_devices == 21
    assert stats.multiple_country_devices == 1
    assert hashlib.sha256(MOCK_DATA.read_bytes()).digest() == before

    with (tmp_path / "country_counts.csv").open(newline="", encoding="utf-8") as file:
        counts = list(csv.DictReader(file))
    assert [(row["rank"], row["country"], row["unique_devices"]) for row in counts] == [
        ("1", "India", "6"),
        ("2", "United States", "4"),
        ("3", "Brazil", "3"),
        ("4", "Germany", "3"),
        ("5", "Russia", "2"),
        ("6", "Vietnam", "2"),
        ("7", "Canada", "1"),
    ]

    assert (tmp_path / "summary_report.txt").read_text(encoding="utf-8") == (
        "LEAKED LICENSE KEY: PIRACY SUMMARY\n"
        "Client: Chaos | Source: leaked_logs.csv\n"
        "\n"
        "WHAT WE FOUND\n"
        "21 unique devices are using the leaked key.\n"
        "The log had 31 entries. 4 were unusable (3 had no Device ID, 1 had an\n"
        "invalid IP address) and 2 were exact duplicates. 25 entries were analyzed.\n"
        "\n"
        "TOP OFFENDING COUNTRIES (by unique devices, not IP addresses)\n"
        " 1. India          - 6 devices\n"
        " 2. United States  - 4 devices\n"
        " 3. Brazil         - 3 devices\n"
        " 4. Germany        - 3 devices\n"
        " 5. Russia         - 2 devices\n"
        " 6. Vietnam        - 2 devices\n"
        " 7. Canada         - 1 device\n"
        "\n"
        "Not ranked: 1 device had no country listed (Unknown).\n"
        "\n"
        "KEY TAKEAWAYS\n"
        "- India is the largest source, with 6 of 21 devices (28.6%).\n"
        "- The top 3 countries (India, United States, Brazil) account for 13 of\n"
        "  21 devices (61.9%).\n"
        "- 1 device (DEV-3001) appeared in more than one country (Germany and\n"
        "  Canada). This may indicate VPN use or the key being shared.\n"
        "\n"
        "NOTES\n"
        "- Counts are based on unique Device IDs. Several devices shared the same\n"
        "  IP address, and some devices used several IPs, so IP counts would be\n"
        "  misleading.\n"
        "- Rejected entries are listed in rejected_rows.csv for review.\n"
    )

    with (tmp_path / "rejected_rows.csv").open(newline="", encoding="utf-8") as file:
        rejected = list(csv.DictReader(file))
    assert len(rejected) == 4
    assert [row["reason"] for row in rejected].count("missing_device_id") == 3
    assert [row["reason"] for row in rejected].count("invalid_ip") == 1


def test_cleaned_data_is_idempotent(tmp_path):
    first_out = tmp_path / "first"
    second_out = tmp_path / "second"
    run_analysis(MOCK_DATA, first_out)

    stats = run_analysis(first_out / "cleaned_logs.csv", second_out)

    assert stats.rejected_rows == 0
    assert stats.duplicates_removed == 0
    assert (first_out / "cleaned_logs.csv").read_bytes() == (
        second_out / "cleaned_logs.csv"
    ).read_bytes()


def test_order_independent(tmp_path):
    with MOCK_DATA.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    shuffled_path = tmp_path / "shuffled.csv"
    import random

    random.Random(42).shuffle(rows)
    with shuffled_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["ip_address", "device_id", "country"])
        writer.writeheader()
        writer.writerows(rows)

    original_out = tmp_path / "original"
    shuffled_out = tmp_path / "shuffled"
    run_analysis(MOCK_DATA, original_out)
    run_analysis(shuffled_path, shuffled_out)

    assert (original_out / "country_counts.csv").read_bytes() == (
        shuffled_out / "country_counts.csv"
    ).read_bytes()


def test_bad_header_returns_exit_code_2_and_clear_error(tmp_path, capsys):
    input_path = tmp_path / "bad.csv"
    input_path.write_text("ip_address,device_id\n1.2.3.4,DEV-1\n", encoding="utf-8")

    assert main(["--input", str(input_path), "--outdir", str(tmp_path / "out")]) == 2
    assert "missing required column" in capsys.readouterr().err.lower()


def test_header_only_input_succeeds_with_empty_report(tmp_path):
    input_path = tmp_path / "empty.csv"
    input_path.write_text("ip_address,device_id,country\n", encoding="utf-8")

    stats = run_analysis(input_path, tmp_path / "out")

    assert stats.rows_read == 0
    assert stats.rows_analyzed == 0
    assert "no usable activity found" in (
        tmp_path / "out" / "summary_report.txt"
    ).read_text(encoding="utf-8").lower()


def test_bom_prefixed_input_is_supported(tmp_path):
    input_path = tmp_path / "bom.csv"
    input_path.write_text(
        "\ufeffip_address,device_id,country\n192.0.2.1,DEV-1,Canada\n",
        encoding="utf-8",
    )

    stats = run_analysis(input_path, tmp_path / "out")

    assert stats.global_unique_devices == 1


def test_rows_are_accounted_for(tmp_path):
    stats = run_analysis(MOCK_DATA, tmp_path)

    assert stats.rows_read == (
        stats.rejected_rows + stats.duplicates_removed + stats.rows_analyzed
    )
