## What changes for the user

## How it was verified

- [ ] `python -m pytest`
- [ ] `python scripts/validate_specs.py`
- [ ] `python scripts/check_links.py`
- [ ] `python scripts/check_public_tree.py --history`
- [ ] UI changes: screenshots at 320 px and 390 px, light/dark, RU/EN (fixtures only)

## Contracts

- [ ] No breaking change to `contracts/` (only optional fields, wider enums, smaller `minItems`)
- [ ] Members still cannot receive administrator data (tests updated if role projections changed)

## Privacy

- [ ] No real addresses, domains, tokens, Telegram IDs or personal data anywhere in this PR
