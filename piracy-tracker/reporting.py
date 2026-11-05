import csv
import textwrap


def _plural(count, singular, plural=None):
    return singular if count == 1 else (plural or singular + "s")


def _paragraph(text, prefix="", width=78):
    return textwrap.fill(text, width=width, initial_indent=prefix, subsequent_indent="  ")


def build_summary(
    source_name,
    rows_read,
    rejected_missing_device_id,
    rejected_invalid_ip,
    duplicates_removed,
    rows_analyzed,
    countries,
    global_unique_devices,
    multi_country_devices,
):
    total_rejected = rejected_missing_device_id + rejected_invalid_ip
    ranked = sorted(
        ((country, len(devices)) for country, devices in countries.items() if country != "Unknown"),
        key=lambda item: (-item[1], item[0]),
    )
    unknown_count = len(countries.get("Unknown", set()))
    lines = [
        "LEAKED LICENSE KEY: PIRACY SUMMARY",
        "Client: Chaos | Source: {}".format(source_name),
        "",
        "WHAT WE FOUND",
    ]

    if global_unique_devices:
        lines.append(
            "{} unique devices are using the leaked key.".format(global_unique_devices)
        )
    else:
        lines.append("No usable activity found.")

    activity_prefix = (
        "The log had {} entries. {} were unusable ({} had no Device ID, {} had an"
    ).format(
        rows_read,
        total_rejected,
        rejected_missing_device_id,
        rejected_invalid_ip,
    )
    activity_suffix = (
        "invalid IP address) and {} were exact duplicates. {} entries were analyzed."
    ).format(
        duplicates_removed,
        rows_analyzed,
    )
    lines.extend([activity_prefix, activity_suffix])
    lines.extend(["", "TOP OFFENDING COUNTRIES (by unique devices, not IP addresses)"])

    if ranked:
        for rank, (country, count) in enumerate(ranked, start=1):
            lines.append(
                "{:2}. {:<14} - {} {}".format(
                    rank, country, count, _plural(count, "device")
                )
            )
    else:
        lines.append("No ranked countries.")

    if unknown_count:
        lines.extend(
            [
                "",
                "Not ranked: {} {} {} no country listed (Unknown).".format(
                    unknown_count,
                    _plural(unknown_count, "device"),
                    "had" if unknown_count == 1 else "had",
                ),
            ]
        )

    if ranked:
        lines.extend(["", "KEY TAKEAWAYS"])
        top_country, top_count = ranked[0]
        lines.append(
            _paragraph(
                "- {} is the largest source, with {} of {} devices ({:.1f}%).".format(
                    top_country,
                    top_count,
                    global_unique_devices,
                    top_count * 100 / global_unique_devices,
                )
            )
        )
        top_three = ranked[:3]
        top_three_count = sum(count for _, count in top_three)
        country_names = ", ".join(country for country, _ in top_three)
        lines.extend(
            [
                "- The top {} countries ({}) account for {} of".format(
                    len(top_three), country_names, top_three_count
                ),
                "  {} devices ({:.1f}%).".format(
                    global_unique_devices,
                    top_three_count * 100 / global_unique_devices,
                ),
            ]
        )
        if multi_country_devices:
            for device_id, seen_countries in sorted(multi_country_devices.items()):
                first_country = seen_countries[0]
                other_countries = " and ".join(seen_countries[1:])
                lines.extend(
                    [
                        "- 1 device ({}) appeared in more than one country ({} and".format(
                            device_id, first_country
                        ),
                        "  {}). This may indicate VPN use or the key being shared.".format(
                            other_countries
                        ),
                    ]
                )

    lines.extend(
        [
            "",
            "NOTES",
            "- Counts are based on unique Device IDs. Several devices shared the same",
            "  IP address, and some devices used several IPs, so IP counts would be",
            "  misleading.",
            "- Rejected entries are listed in rejected_rows.csv for review.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_country_counts(path, countries):
    ranked = sorted(
        ((country, len(devices)) for country, devices in countries.items() if country != "Unknown"),
        key=lambda item: (-item[1], item[0]),
    )
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["rank", "country", "unique_devices"])
        for rank, (country, count) in enumerate(ranked, start=1):
            writer.writerow([rank, country, count])
