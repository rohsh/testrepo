# Introduction
This repository consists of tools to:
 - publish test-results of community SONIC images
 - view test-results
 - detect regressions
 - apply filters such as branch, topology, etc

# 1. Publishing Test Results

The `results` script ingests `tr.xml` files produced by sonic-mgmt runs,
normalizes them into the repo's JSON format, and commits/pushes them to
the appropriate location under `data/`.

## Help
```
$ ./results
Usage: results [OPTIONS] COMMAND [ARGS]...

  Manage test results

Commands:
  add   Add test results from tr.xml files
```

## `results add`
```
$ ./results add --help
Options:
  --org TEXT           Organization name (required)
  --sku-map TEXT       SKU mapping in format ORIGINAL:MAPPED (repeatable)
  --src TEXT           Comma-separated list of XML files, directories,
                       archives, or URLs (required)
  --dry-run            Show what would be processed without committing
```

### Source types
`--src` accepts a comma-separated list of any of:
 - Local XML files (e.g. `tr.xml`)
 - Local directories (scanned recursively for XML files)
 - Local or remote archives (`.tar.gz`, `.tar`, `.zip`, ...)
 - HTTP(S) URLs pointing to XML files or archives

### SKU mapping
`--sku-map ORIGINAL:MAPPED` (repeatable) rewrites the raw hardware SKU
found in the XML into a normalized, org-prefixed SKU. This keeps
vendor-specific part numbers out of the public dataset.

### Examples
```
# Ingest a directory, mapping two physical SKUs to org-prefixed aliases
./results add --org org1 \
  --sku-map ABC-2500--32:sku1 \
  --sku-map ABC-2500--64:sku2 \
  --src /path/to/tr_dir

# Mix local files, directories, and archives
./results add --org org1 --sku-map NH-4010:org1-sku1 \
  --src /tmp/foo3,/tmp/bar.xml,/tmp/foo1.tar.gz

# Pull an archive from a URL
./results add --org org1 --sku-map NH-4010:org1-sku1 \
  --src http://example.com/test.tar.gz

# Dry-run (no commit/push)
./results add --org org1 --sku-map ABC-2500--32:sku1 \
  --src /path/to/dir --dry-run
```

Unless `--dry-run` is set, the script performs a `git pull` before
ingesting and a `git push` after commit to keep the dataset consistent.

# 2. Organization of the `data/` Folder

Ingested results are stored as JSON under `data/`, partitioned by org
and by week so that the web page can fetch a small, bounded number of
files for a given query window.

## Directory layout
```
data/
  <org>/
    <YYYY>/
      <MM>/
        week<N>/
          results.json
```

Example:
```
data/org1/2026/04/week4/results.json
```

Week number (`week1`..`week5`) is derived from the day-of-month
(`ceil(day / 7)`) to match how the web page generates its query URLs.

## Record format (`results.json`)
Each `results.json` is a JSON array of test-run records. Every record
describes one invocation of a sonic-mgmt test file on one testbed:

```json
{
  "format": "v1",
  "org": "org1",
  "time": "2026/04/22 04:12",
  "file": "platform_tests/test_reboot.py",
  "branch": "main",
  "os_version": "57317-10b4f26662",
  "testbed": "testbed7646",
  "topology": "t0-8",
  "hwsku": "org1-sku1",
  "duration": 2288.1,
  "total_testcases": 7,
  "failed_testcases": 0,
  "error_testcases": 0,
  "skipped_testcases": 2,
  "testcase_statuses": [
    ["test_cold_reboot[gnoi_based-testbed7646]", "PASS"],
    ["test_soft_reboot[testbed7646]",            "SKIP"]
  ]
}
```

Only records with `"format": "v1"` are rendered by the web page;
unknown formats are skipped so the schema can be evolved.

# 3. Web Page (`index.html`)

`index.html` is a self-contained, static HTML page (no build
step, no server) that fetches the per-week `results.json` files
directly from this repo via raw GitHub URLs and renders them in the
browser.

## Layout
 - **Filters** — dropdowns for `Duration`, `Branch`, `Topology`,
   `Status`, and `Org`. Changes re-render the page in place.
 - **Metrics**
   - **Pass Rate** — overall percentage plus a small inline
     chart of daily pass-rate over the selected duration window.
     Hovering a point on the chart shows the date, rate, and TC count.
   - **Total Runs** — number of runs in the selected window.
   - **Failed Runs** — runs with at least one fail or error, with
     fail/error breakdown.
   - **Regressions** — tests whose most recent run failed and whose
     immediately-previous run passed (per branch × file × topology).
 - **Test Results table** — one row per run, with status badge, time,
   branch, org, file, build, topology, hwsku, duration, and a compact
   pass/fail/error/skip bar. Each row expands to show the full
   per-testcase status list (failures and errors sorted to the top).

## Filters
| Filter    | Values                                                       |
|-----------|--------------------------------------------------------------|
| Duration  | 1 day / 1 week / 2 week / 6 week / 6 month                   |
| Branch    | `any`, `main`, `202611`, `202605`, `202511`, `202505`, `202411` |
| Topology  | `any`, `t0`, `t1`, `t2` (prefix match on `topology`)         |
| Status    | `any`, `Regression`, `Fail`, `Pass`                          |
| Org       | `any`, or a specific org                                     |

## Data fetching
On load the page computes the set of week paths that fall inside the
query window (default 6 weeks) and fetches
`https://raw.githubusercontent.com/<repo>/main/data/<org>/<YYYY>/<MM>/week<N>/results.json`
for every enabled org. 

## Theme
The page ships both dark and light themes driven by CSS custom properties; the selection persists in `localStorage`.
