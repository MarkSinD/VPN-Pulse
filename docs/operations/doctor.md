# Operations: doctor and installation

> **Status: `vpn-pulse doctor` works; `install.sh` is planned.** The doctor checks below run
> against a real installation directory (`vpn-pulse init`) and print the same next steps the
> administrator sees in the Mini App. HTTPS and backup checks arrive with the installer.

## Two entry points

- `./install.sh demo` — runs the interface on fixtures, prints a local URL, asks for no
  Telegram token, domain or SSH. "Demo data" is always visible.
- `./install.sh preflight` then `sudo ./install.sh install` — a seven-step wizard: environment,
  application, configuration, secrets, HTTPS, Telegram, final diagnostics. Preflight changes
  nothing; the dry-run summary lists every change before it is made.

The wizard asks only what cannot be derived safely: language and timezone, the Mini App
domain, the bot token (file path or hidden prompt), group and admin IDs, confirmation.
Servers and probes are connected afterwards with separate commands, so you get a working
interface even before the sources are ready.

## Every step reports the same way

```text
[4/7] HTTPS
Checking A/AAAA records for monitor.example.org ... FAILED
Expected: this server's public address
Found: no record
Next: create the DNS record, then run `vpn-pulse doctor https`
No system changes were made in this step.
```

Success is never signalled by colour alone; every failure carries a safe re-check command.
Full debug output is behind `--verbose` and redacts secrets.

## `vpn-pulse doctor`

```text
$ vpn-pulse doctor
doctor: FAIL
  [FAIL] servers: Connect the first server  →  vpn-pulse server add
  [WARN] probes: After the server, enroll the probes  →  vpn-pulse probe enroll pc
  [WARN] telegram: Telegram is not configured — messages are printed to the console; …  →  vpn-pulse doctor telegram
```

One line per finding, one next step each, failures first. Exit code `0` when everything passed,
`1` with warnings, `2` with failures — so `vpn-pulse doctor` works as a post-install gate.
`--json` prints `{"result", "items", "next_command"}`; `--lang ru|en` picks the language of the
hints (default: `app.default_language`).

| Check | Where it comes from | What it says |
|---|---|---|
| `servers` | configuration | no servers yet → connect the first one |
| `probes` | `probes` table | none enrolled → enroll; enrolled but silent (no report for 15 min) → wake the computer / check the network |
| `collector` | `collection_runs` | never ran → start the `vpn-pulse` service; last run failed or older than three intervals → check the service and server access |
| `queue` | `notification_queue` | messages pending for more than ten minutes → check the bot |
| `storage` | the database file | missing → `vpn-pulse init`; cannot be opened → path and permissions |
| `telegram` | `telegram` block and the token file | not configured (warning: messages go to the console); token file missing or empty (failure); readable by others (`chmod 600`) |

`servers`, `probes`, `collector` and `queue` are computed by the same code that serves
`GET /admin/overview`, so the terminal and the Mini App never disagree; `storage` and `telegram`
look at files the Mini App cannot see. `vpn-pulse doctor <check>` limits the output to one check
and adds details (per-probe last report, last collection run, queue counts, database size and
schema version, token-file status — never its contents).

Planned additions: `https` (records and certificate of the Mini App domain, with the installer),
`backup` (age of the last archive) and `--support-bundle`, a local redacted archive that lists
its contents first; nothing is ever uploaded automatically.

In the Mini App the administrator sees the compact doctor summary from `/admin/overview` plus
`/health/ready` and `/admin/probes` — there is no separate doctor endpoint.

## Final screen

After installation only four results are shown: the Mini App URL, Telegram state, the number
of connected sources and the doctor result. The installer does not declare success while
API, HTTPS or secret storage fail a mandatory check.

## Related

- [upgrade-rollback.md](upgrade-rollback.md) · [backup-restore.md](backup-restore.md) · [uninstall.md](uninstall.md)
