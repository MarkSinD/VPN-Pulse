# Operations: doctor and installation

> **Status: planned.** `install.sh` and `vpn-pulse doctor` are designed, not implemented.
> What exists today: `/health/live`, `/health/ready` in the API contract and the mock-first
> implementation, plus the doctor summary in the Mini App prototype.

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

Checks the whole chain — API, HTTPS, Telegram, collector freshness per source, storage,
queue, probes — and prints one next step per warning. `--json` for scripts,
`--support-bundle` builds a local redacted archive and lists its contents first; nothing is
uploaded automatically.

In the Mini App the administrator sees a compact doctor summary built from `/health/ready`,
`/admin/probes` and the attention items — there is no separate doctor endpoint.

## Final screen

After installation only four results are shown: the Mini App URL, Telegram state, the number
of connected sources and the doctor result. The installer does not declare success while
API, HTTPS or secret storage fail a mandatory check.

## Related

- [upgrade-rollback.md](upgrade-rollback.md) · [backup-restore.md](backup-restore.md) · [uninstall.md](uninstall.md)
