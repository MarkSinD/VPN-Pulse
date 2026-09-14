# User guide: status and recommendations

You open VPN Pulse from the pinned message in your group. It answers three things at a glance.

## 1. Is the VPN working?

The headline says it: **Everything works**, **Some checks failed**, **Connection check
failed** or **No recent data**. Under it — when the data was last updated.

## 2. Which server should I use?

The row marked with a **★** ("Recommended") is a server whose work has just been confirmed
by a real check and whose data is complete. If nothing is confirmed right now, the app says
so instead of guessing.

## 3. How is each server doing?

Each row is one server:

| Element | Meaning |
|---|---|
| Ring around the flag | green — working; amber — some checks failed; red — check failed; grey dashes — no recent data |
| Word next to the flag | the same state in words, so colour is never the only signal |
| 💻 📶 🌍 dots | the three check sources: computer inside the country, mobile network, cross-check from abroad; a hollow dot means no data |
| Chart | connections over the last 24 hours; the bar under it shows the state history, a gap means no data |
| `99,9 %` on the right | availability over the last 24 hours (history). `—` means there is no current confirmation |

Tap a row (or press Enter on it) to open the server screen: checks by source with times,
load per protocol, what runs on the server, profile counts, and the server's own checks. The
Back button returns you to the same place in the list.

## Notes from the administrator

When something is going on, a note appears above the list — what happened and what to do.
Long notes show three lines and a "More" button.

## When it does not work for you

Open **Help**: four short steps in the right order — check the status, reconnect, switch to the
recommended server, enable your backup profile — and a button to contact the administrator.
"Why is that?" explains the technical reason without jargon.

## What you will not see

Server addresses, ports, hosting providers or other people's data. The app is about whether
you can connect and where, nothing else.

## Two things worth knowing

- **Nobody connected ≠ broken.** A quiet server stays green if a check confirmed it.
- **No recent data ≠ down.** It means the checks could not run (for example the probe
  computer is asleep). The server may be fine; the app simply refuses to guess.
