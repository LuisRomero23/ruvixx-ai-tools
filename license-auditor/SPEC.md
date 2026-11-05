# SPEC: License Compliance Auditor

Internal CLI tool (Python 3.10+, stdlib only: `csv`, `difflib`, `datetime`, `argparse`). Compares messy usage logs against active client licenses and writes a plain-English report.

**Reference date ("today"):** configurable via `--today YYYY-MM-DD`, default = system date. Test fixtures assume `2026-11-04`.

## 1. Inputs

### `active_licenses.csv` (clean, trusted)
| column | notes |
|---|---|
| license_id | unique, e.g. LIC-001 |
| company_name | canonical name |
| contact_email | licensing contact |
| seats_purchased | int > 0 |
| expiry_date | ISO `YYYY-MM-DD` |

### `messy_logs.csv` (untrusted)
| column | notes |
|---|---|
| log_id | may repeat |
| timestamp | mixed formats (see Normalization) |
| company_name | typos, casing, stray whitespace |
| user_email | may be blank, padded, or mixed case |
| product | free text |
| action | free text |

## 2. Normalization (do before any checks)
- Strip whitespace; collapse internal runs of spaces.
- Company: compare case-insensitively.
- Email: strip + lowercase.
- Timestamps: accept `YYYY-MM-DD HH:MM[:SS]`, `YYYY-MM-DDTHH:MM:SSZ`, `MM/DD/YYYY HH:MM` (US order assumed), and `Mon D YYYY`. Unparseable -> flag `BAD_TIMESTAMP`, keep the row, exclude it from date-based checks.
- Never mutate input files; never crash on a bad row. Report instead.

## 3. Anomalies to detect
| code | rule |
|---|---|
| `DUPLICATE` | Same normalized (company, email, timestamp, product, action), or repeated log_id with identical content. Keep first, drop the rest, and exclude dropped rows from all other counts. |
| `COMPANY_TYPO` | No exact (case-insensitive) match, but `difflib.SequenceMatcher` ratio >= 0.85 to exactly one licensed company. Treat as that company for the remaining checks; report the suggested correction. |
| `UNLICENSED` | No exact or fuzzy match (< 0.85). Report company name and row count. |
| `MISSING_EMAIL` | Blank/whitespace email, or lacks `@`. Row still counts as activity but cannot count toward seats. |
| `EXPIRED_LICENSE` | License `expiry_date` < today (license lapsed), and/or a log event dated after `expiry_date`. Report the license, expiry date, number of post-expiry events. |
| `SEAT_OVERAGE` | Distinct valid normalized emails (after dedupe) for a company > `seats_purchased`. Report used vs purchased and the list of users. |
| `BAD_TIMESTAMP` | See Normalization. |

A row can raise multiple codes. Row numbers in the report refer to the CSV line number (header = line 1).

## 4. Output: `audit_report.txt`
Plain English, readable by a non-technical account manager. Structure:

1. **Header**: report date, files audited, rows read, rows dropped as duplicates.
2. **Executive summary** (3-5 sentences): overall status and count of issues by severity.
3. **Findings grouped by company**, each with a one-line verdict (`OK` / `NEEDS ATTENTION`) and sentences like:
   - "Stark Dynamics has 2 seats but 3 different people used the product (frank@..., gina@..., hank@...). That is 1 over the limit."
   - "Initech LLC's license expired on 2026-09-30, but we saw 1 login after that date (line 7)."
   - "Line 5 has no user email, so we cannot tell who logged in."
4. **Unlicensed activity** section for unmatched companies.
5. **Data quality notes**: duplicates removed, typos auto-corrected (with original -> matched name), bad timestamps.
6. **Suggested next actions**: one bullet per issue (e.g. "Contact licenses@initech.com about renewal").

No raw tracebacks or code names in the prose. Anomaly codes may appear in brackets, e.g. `[SEAT_OVERAGE]`.

## 5. CLI
```
python audit.py --logs messy_logs.csv --licenses active_licenses.csv --out audit_report.txt [--today 2026-11-04]
```
Exit code 0 on success (even with findings); non-zero only for unreadable/missing files or missing required columns.

## 6. Expected findings for the supplied fixtures (today = 2026-11-04)
Use as acceptance tests.

| line | issue |
|---|---|
| 4 | Exact duplicate of line 2 -> `DUPLICATE` (dropped) |
| 5 | "Globex Industires" -> `COMPANY_TYPO` -> Globex Industries |
| 6 | Globex row with blank email -> `MISSING_EMAIL` |
| 7 | Initech LLC event 2026-11-03, license expired 2026-09-30 -> `EXPIRED_LICENSE` |
| 8-10 | Stark Dynamics: 3 distinct users vs 2 seats -> `SEAT_OVERAGE` (line 10 email has padding/mixed case; must normalize to avoid counting as a different user than expected) |
| 11 | "Wayne Enterprises" -> `UNLICENSED`, and invalid timestamp -> `BAD_TIMESTAMP` |
| 2-3 | "ACME Corporation " and `11/02/2026 14:30` must normalize cleanly -> no findings; Acme = 2 users / 10 seats = OK |
| - | Umbrella Biotech: no activity, no findings (optionally note "unused license") |

Expected totals: 10 rows read, 1 duplicate dropped, 1 typo, 1 missing email, 1 expired, 1 overage (Stark, 1 over), 1 unlicensed, 1 bad timestamp.

## 7. Non-goals
No database, no network, no third-party dependencies, no GUI. Keep `audit.py` under ~250 lines with a small `tests/test_audit.py` asserting Section 6.