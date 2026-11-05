# SPEC: Leaked License Key Piracy Analyzer

Client: **Chaos** (enterprise). Incident: a premium license key was leaked on a public forum.
Goal: turn the raw activity export (`leaked_logs.csv`) into a trustworthy count of **unique devices** using the key, per country, and a plain-English ranking of the worst offenders.

> Status: **spec only. No implementation yet.** The local coding agent should build to this spec, test-first.

---

## 1. Scope and decisions

| Topic | Decision |
|---|---|
| Language | Python 3.10+, standard library only (`csv`, `ipaddress`, `argparse`, `collections`). Test runner: `pytest`. |
| Input | CSV with header `ip_address,device_id,country`. Encoding UTF-8 (tolerate BOM). |
| Unit of counting | **Unique Device ID**, never IP address. IPs are noisy (NAT, VPN, mobile carriers); one device on 5 IPs is still 1 device, and 5 devices behind one IP are 5 devices. |
| Device in 2+ countries | Counted once in **each** country it appears in (per-country view), counted once in the **global** total, and listed in a "seen in multiple countries" note (possible VPN or shared key). |
| Missing Device ID | Row is **rejected** (cannot be counted as a device) and tallied in the report. Missing = empty, whitespace only, or `N/A`, `NA`, `NULL`, `NONE`, `-`, `?` (case-insensitive). |
| Invalid IP | Row is **rejected** (syntactic check via `ipaddress`; IPv4 and IPv6 allowed; private or reserved ranges are still valid). |
| Missing country | Row is kept, country becomes `Unknown`. `Unknown` is reported separately and **never ranked**. |
| Ties in ranking | Higher device count first, then country name A to Z. |
| Original file | Never modified. Outputs go to a separate directory. |

---

## 2. Technical architecture (3 steps)

```
leaked_logs.csv ──► [1 Ingest + Normalize] ──► [2 Validate + Deduplicate] ──► [3 Aggregate + Report]
                          │                              │                            │
                          └─────────── Stats counters (rows read / rejected / deduped) ┘
```

### Step 1: Ingest and normalize (make values comparable)
Read rows with `csv.DictReader`. Missing columns in the header is a fatal error (exit code 2). For each row apply, in order:

- **Whitespace:** strip leading and trailing whitespace on every field; collapse internal runs of whitespace in country.
- **IP:** strip, then keep the raw string for validation in Step 2 (normalize valid ones to canonical form via `ipaddress`).
- **Device ID:** strip, **uppercase** (`dev-2003` and `DEV-2003` are the same device). Convert null-like tokens (see table above) to `None`.
- **Country:** strip, remove dots, casefold, then map through an alias table to a canonical Title Case name.
  - Required aliases: `usa`, `us`, `u.s.`, `u.s.a.`, `united states of america`, `united states` → **United States**; `uk`, `u.k.`, `great britain`, `united kingdom` → **United Kingdom**.
  - Unmapped values: Title Case the casefolded string (`germany` → `Germany`).
  - Empty after cleaning → `Unknown`.

### Step 2: Validate and deduplicate (match the data)
1. **Reject** rows with `device_id is None` (reason `missing_device_id`).
2. **Reject** rows whose IP fails `ipaddress.ip_address()` (reason `invalid_ip`).
3. **Deduplicate** exact duplicates on the normalized tuple `(ip, device_id, country)`; keep the first occurrence and count the rest as `duplicates_removed`.
4. Rejected rows are written to `rejected_rows.csv` (original row number + raw values + reason) so analysts can audit, never silently dropped.

Note: same IP with different devices is **not** a duplicate. Same device on different IPs is **not** a duplicate. Both are kept (the device set handles correctness in Step 3).

### Step 3: Aggregate and report (count and rank)
- Build `dict[country] -> set[device_id]`. The set size is the per-country device count.
- Global unique devices = size of the union of all sets (includes `Unknown`).
- Rank countries (excluding `Unknown`) by count desc, then name asc.
- Emit:
  - `summary_report.txt`: plain-English report (format in section 4).
  - `country_counts.csv`: `rank,country,unique_devices`.
  - `cleaned_logs.csv`: the normalized, validated, deduplicated rows.
  - `rejected_rows.csv`: see Step 2.

CLI: `python analyze_leaks.py --input leaked_logs.csv --outdir out/`
Exit codes: `0` success (even if rows were rejected), `2` bad or missing input or header.

Suggested layout: `analyze_leaks.py` (CLI), `cleaning.py` (Step 1), `validation.py` (Step 2), `reporting.py` (Step 3), `tests/`.

---

## 3. Automated test definition

Run with `pytest -q`. Fixture: `tests/fixtures/leaked_logs.csv` (the mock file delivered with this spec). **Tests are written before the code.**

### 3.1 Unit tests
| Area | Case | Expected |
|---|---|---|
| Country | `brazil`, `BRAZIL`, ` Brazil ` | `Brazil` |
| Country | `united states`, `USA`, `  U.S.  ` | `United States` |
| Country | `` (empty) | `Unknown` |
| Device ID | `dev-2003` | `DEV-2003` |
| Device ID | ``, `N/A`, `null`, `   ` | `None` |
| IP | `999.1.1.1`, `abc`, `` | invalid |
| IP | ` 192.0.2.41` (leading space) | valid, `192.0.2.41` |

### 3.2 Golden-file integration test (fixture, exact expected values)
Run the full pipeline on the fixture and assert:

| Metric | Expected |
|---|---|
| Rows read | **31** |
| Rejected: `missing_device_id` | **3** (blank, `N/A`, `null`) |
| Rejected: `invalid_ip` | **1** (`999.1.1.1`) |
| Duplicates removed | **2** |
| Rows analyzed (cleaned rows) | **25** |
| Unique devices, global | **21** |
| Devices seen in more than one country | **1** (`DEV-3001`: Germany and Canada) |

Per-country unique devices:

| Rank | Country | Unique devices |
|---|---|---|
| 1 | India | 6 |
| 2 | United States | 4 |
| 3 | Brazil | 3 |
| 4 | Germany | 3 |
| 5 | Russia | 2 |
| 6 | Vietnam | 2 |
| 7 | Canada | 1 |
| n/a | Unknown (unranked) | 1 |

What each fixture trap checks:
- `DEV-1001` repeats on identical and different IPs → Brazil stays 3, not 5.
- `192.0.2.40` is shared by `DEV-4001` and `DEV-4006` → India counts **devices**, so 6.
- `dev-2003` vs `DEV-2003` on the same IP → case-insensitive dedup.
- `USA`, `united states`, `  U.S.  ` → one United States bucket.
- Germany ties Brazil at 3 → Brazil ranks first (alphabetical).
- `DEV-6002` appears on two IPs with different country casing → Vietnam stays 2.

### 3.3 Property and robustness tests
- **Idempotent:** running the cleaner on `cleaned_logs.csv` changes nothing and rejects nothing.
- **Order-independent:** shuffling input rows gives identical counts and ranking.
- **Input untouched:** the SHA-256 of the input file is the same before and after the run.
- **No double counting:** sum of per-country counts minus global unique = number of extra country appearances (here 22 − 21 = 1).
- **Bad input:** missing header column → exit code 2 and a clear message; empty file (header only) → exit code 0 with a "no usable activity found" report; BOM-prefixed file parses correctly.
- **Accounting identity:** `rows_read = rejected + duplicates_removed + rows_analyzed` (31 = 4 + 2 + 25).

### 3.4 Done criteria
All tests pass, the report text matches section 4 exactly for the fixture (golden-file diff), and no network or third-party dependency is used.

---

## 4. Expected plain-English summary output

Fixture run should produce `summary_report.txt` exactly like this:

```
LEAKED LICENSE KEY: PIRACY SUMMARY
Client: Chaos | Source: leaked_logs.csv

WHAT WE FOUND
21 unique devices are using the leaked key.
The log had 31 entries. 4 were unusable (3 had no Device ID, 1 had an
invalid IP address) and 2 were exact duplicates. 25 entries were analyzed.

TOP OFFENDING COUNTRIES (by unique devices, not IP addresses)
 1. India          - 6 devices
 2. United States  - 4 devices
 3. Brazil         - 3 devices
 4. Germany        - 3 devices
 5. Russia         - 2 devices
 6. Vietnam        - 2 devices
 7. Canada         - 1 device

Not ranked: 1 device had no country listed (Unknown).

KEY TAKEAWAYS
- India is the largest source, with 6 of 21 devices (28.6%).
- The top 3 countries (India, United States, Brazil) account for 13 of
  21 devices (61.9%).
- 1 device (DEV-3001) appeared in more than one country (Germany and
  Canada). This may indicate VPN use or the key being shared.

NOTES
- Counts are based on unique Device IDs. Several devices shared the same
  IP address, and some devices used several IPs, so IP counts would be
  misleading.
- Rejected entries are listed in rejected_rows.csv for review.
```

Formatting rules: devices pluralize (`1 device`, `2 devices`); percentages to one decimal place; the multi-country note appears only when at least one such device exists; the "Not ranked" line appears only when `Unknown` count is greater than 0.