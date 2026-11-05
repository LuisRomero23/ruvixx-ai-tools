import argparse
import csv
from datetime import date, datetime
from difflib import SequenceMatcher


LOG_COLUMNS = ("log_id", "timestamp", "company_name", "user_email", "product", "action")
LICENSE_COLUMNS = ("license_id", "company_name", "contact_email", "seats_purchased", "expiry_date")
TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%SZ",
    "%m/%d/%Y %H:%M",
    "%b %d %Y",
)


def clean(value):
    return " ".join((value or "").split())


def parse_timestamp(value):
    value = clean(value)
    for timestamp_format in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, timestamp_format)
        except ValueError:
            pass
    return None


def read_csv(path, required_columns):
    with open(path, newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        missing = [column for column in required_columns if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        return list(reader)


def duplicate_key(row):
    timestamp = parse_timestamp(row.get("timestamp"))
    normalized_timestamp = timestamp.isoformat() if timestamp else clean(row.get("timestamp")).casefold()
    return (
        clean(row.get("company_name")).casefold(),
        clean(row.get("user_email")).casefold(),
        normalized_timestamp,
        clean(row.get("product")).casefold(),
        clean(row.get("action")).casefold(),
    )


def audit_report(log_path, license_path, today):
    raw_logs = read_csv(log_path, LOG_COLUMNS)
    license_rows = read_csv(license_path, LICENSE_COLUMNS)
    licenses = []
    for row in license_rows:
        license_record = dict(row)
        license_record["company_key"] = clean(row.get("company_name")).casefold()
        license_record["seats"] = int(clean(row.get("seats_purchased")))
        license_record["expiry"] = date.fromisoformat(clean(row.get("expiry_date")))
        licenses.append(license_record)

    seen = set()
    logs = []
    duplicate_lines = []
    for line_number, row in enumerate(raw_logs, start=2):
        key = duplicate_key(row)
        if key in seen:
            duplicate_lines.append(line_number)
            continue
        seen.add(key)
        record = dict(row)
        record["line"] = line_number
        record["email"] = clean(row.get("user_email")).lower()
        record["timestamp_parsed"] = parse_timestamp(row.get("timestamp"))
        record["company_original"] = clean(row.get("company_name"))
        logs.append(record)

    exact = {license_record["company_key"]: license_record for license_record in licenses}
    activity = {license_record["company_key"]: [] for license_record in licenses}
    typos = {}
    unlicensed = {}
    missing_emails = []
    bad_timestamps = []

    for row in logs:
        if row["timestamp_parsed"] is None:
            bad_timestamps.append(row)
        if not row["email"] or "@" not in row["email"]:
            missing_emails.append(row)

        company_key = row["company_original"].casefold()
        license_record = exact.get(company_key)
        if license_record is None:
            candidates = [
                candidate for candidate in licenses
                if SequenceMatcher(None, company_key, candidate["company_key"]).ratio() >= 0.85
            ]
            if len(candidates) == 1:
                license_record = candidates[0]
                typos.setdefault(row["company_original"], license_record["company_name"])
            else:
                unlicensed.setdefault(company_key, {"name": row["company_original"], "rows": []})
                unlicensed[company_key]["rows"].append(row)
        if license_record is not None:
            activity[license_record["company_key"]].append(row)

    issues = {"high": 0, "medium": 0, "low": 0}
    expired = {}
    overages = {}
    for license_record in licenses:
        key = license_record["company_key"]
        rows = activity[key]
        post_expiry = [
            row for row in rows
            if row["timestamp_parsed"] is not None
            and row["timestamp_parsed"].date() > license_record["expiry"]
        ]
        if license_record["expiry"] < today or post_expiry:
            expired[key] = (license_record, post_expiry)
            issues["high"] += 1
        valid_users = sorted({row["email"] for row in rows if row["email"] and "@" in row["email"]})
        if len(valid_users) > license_record["seats"]:
            overages[key] = (license_record, valid_users)
            issues["high"] += 1

    issues["high"] += len(unlicensed)
    issues["medium"] = len(missing_emails) + len(bad_timestamps)
    issues["low"] = len(typos) + len(duplicate_lines)

    lines = [
        "LICENSE COMPLIANCE AUDIT",
        f"Report date: {today.isoformat()}",
        f"Files audited: {log_path} and {license_path}",
        f"Rows read: {len(raw_logs)}; rows dropped as duplicates: {len(duplicate_lines)}.",
        "",
        "EXECUTIVE SUMMARY",
    ]
    total_issues = sum(issues.values())
    status = "NEEDS ATTENTION" if total_issues else "OK"
    lines.extend([
        f"Overall status: {status}.",
        f"We found {total_issues} issues: {issues['high']} high, {issues['medium']} medium, and {issues['low']} low severity.",
        f"The audit kept {len(logs)} unique activity rows and checked them against {len(licenses)} licenses.",
        "Review the findings and suggested next actions below.",
        "",
        "FINDINGS BY COMPANY",
    ])

    for license_record in licenses:
        key = license_record["company_key"]
        company_issues = []
        if key in expired:
            _, post_expiry = expired[key]
            row_detail = ", ".join(str(row["line"]) for row in post_expiry)
            suffix = f" (lines {row_detail})" if row_detail else ""
            company_issues.append(
                f"{license_record['company_name']}'s license expired on "
                f"{license_record['expiry'].isoformat()}; we saw {len(post_expiry)} "
                f"post-expiry {'event' if len(post_expiry) == 1 else 'events'}{suffix}. [EXPIRED_LICENSE]"
            )
        if key in overages:
            _, users = overages[key]
            company_issues.append(
                f"{license_record['company_name']} has {license_record['seats']} seats but "
                f"{len(users)} different people used the product ({', '.join(users)}). "
                f"That is {len(users) - license_record['seats']} over the limit. [SEAT_OVERAGE]"
            )
        company_rows = activity[key]
        typo_sources = [source for source, target in typos.items() if target == license_record["company_name"]]
        if typo_sources:
            company_issues.append(
                f"Company name typo(s) {', '.join(typo_sources)} were matched to "
                f"{license_record['company_name']}. [COMPANY_TYPO]"
            )
        missing_for_company = [
            row for row in missing_emails
            if row in company_rows
        ]
        company_issues.extend(
            f"Line {row['line']} has no valid user email, so we cannot tell who logged in. [MISSING_EMAIL]"
            for row in missing_for_company
        )
        lines.append(f"{license_record['company_name']}: {'NEEDS ATTENTION' if company_issues else 'OK'}.")
        lines.extend(f"- {finding}" for finding in company_issues)

    lines.extend(["", "UNLICENSED ACTIVITY"])
    if unlicensed:
        for group in unlicensed.values():
            lines.append(
                f"{group['name']} has {len(group['rows'])} unlicensed activity "
                f"{'row' if len(group['rows']) == 1 else 'rows'} "
                f"(lines {', '.join(str(row['line']) for row in group['rows'])}). [UNLICENSED]"
            )
    else:
        lines.append("No unlicensed activity was found.")

    lines.extend(["", "DATA QUALITY NOTES"])
    lines.append(
        f"Removed {len(duplicate_lines)} duplicate row(s)"
        + (f" at lines {', '.join(map(str, duplicate_lines))}." if duplicate_lines else ".")
    )
    for source, target in typos.items():
        lines.append(f"Corrected company name: {source} -> {target}.")
    for row in bad_timestamps:
        lines.append(f"Line {row['line']} has an unparseable timestamp. [BAD_TIMESTAMP]")
    if not bad_timestamps and not typos and not duplicate_lines:
        lines.append("No data quality issues were found.")

    lines.extend(["", "SUGGESTED NEXT ACTIONS"])
    actions = []
    if duplicate_lines:
        actions.append(f"Keep duplicate rows out of future usage exports (lines {', '.join(map(str, duplicate_lines))}).")
    for license_record, _ in expired.values():
        actions.append(f"Contact {license_record['contact_email']} about renewal.")
    for license_record, users in overages.values():
        actions.append(
            f"Review the {len(users)} users on {license_record['company_name']} "
            f"and contact {license_record['contact_email']} about additional seats."
        )
    for group in unlicensed.values():
        actions.append(f"Verify the licensing status for {group['name']} activity.")
    for row in missing_emails:
        actions.append(f"Follow up on line {row['line']} to identify the user.")
    for row in bad_timestamps:
        actions.append(f"Correct the timestamp on line {row['line']} before relying on date checks.")
    for source, target in typos.items():
        actions.append(f"Confirm the company name {source} should be recorded as {target}.")
    if not actions:
        actions.append("No action is required; all checked activity is within the recorded licenses.")
    lines.extend(f"- {action}" for action in actions)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Compare usage logs against active client licenses.")
    parser.add_argument("--logs", required=True, help="Path to messy_logs.csv")
    parser.add_argument("--licenses", required=True, help="Path to active_licenses.csv")
    parser.add_argument("--out", required=True, help="Path for audit_report.txt")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(), help="Reference date (YYYY-MM-DD)")
    args = parser.parse_args()
    try:
        report = audit_report(args.logs, args.licenses, args.today)
        with open(args.out, "w", encoding="utf-8", newline="") as destination:
            destination.write(report)
    except (OSError, ValueError, csv.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
