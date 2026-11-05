import ipaddress
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NormalizedRow:
    row_number: int
    ip_address: str
    device_id: Optional[str]
    country: str
    raw_ip_address: Optional[str]
    raw_device_id: Optional[str]
    raw_country: Optional[str]


@dataclass(frozen=True)
class RejectedRow:
    row_number: int
    ip_address: Optional[str]
    device_id: Optional[str]
    country: Optional[str]
    reason: str


def normalize_ip(value):
    return str(ipaddress.ip_address(value.strip()))


def validate_and_deduplicate(rows):
    accepted = []
    rejected = []
    rejection_counts = {"missing_device_id": 0, "invalid_ip": 0}
    seen = set()
    duplicates_removed = 0

    for row in rows:
        if row.device_id is None:
            rejected.append(
                RejectedRow(
                    row.row_number,
                    row.raw_ip_address,
                    row.raw_device_id,
                    row.raw_country,
                    "missing_device_id",
                )
            )
            rejection_counts["missing_device_id"] += 1
            continue

        try:
            ip_address = normalize_ip(row.ip_address)
        except ValueError:
            rejected.append(
                RejectedRow(
                    row.row_number,
                    row.raw_ip_address,
                    row.raw_device_id,
                    row.raw_country,
                    "invalid_ip",
                )
            )
            rejection_counts["invalid_ip"] += 1
            continue

        key = (ip_address, row.device_id, row.country)
        if key in seen:
            duplicates_removed += 1
            continue

        seen.add(key)
        accepted.append(
            NormalizedRow(
                row.row_number,
                ip_address,
                row.device_id,
                row.country,
                row.raw_ip_address,
                row.raw_device_id,
                row.raw_country,
            )
        )

    return accepted, rejected, rejection_counts, duplicates_removed
