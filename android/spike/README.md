# R-19 spike: can the probe leave through the mobile network while a VPN is up?

A throwaway, dependency-free app that answers the one question the Android probe stands or falls
on. It is not the probe: no enrolment, no reports, nothing is sent anywhere. Everything it finds
is printed on screen and to `logcat -s vpnpulse-spike`.

What it does, in order: reads the app's active network (transports, interface, whether the VPN is
on it), fetches a control page over the **default** network and notes the address the outside
world sees, then asks for the cellular network (`requestNetwork(TRANSPORT_CELLULAR)`), resolves a
name and fetches the same page **bound to that network** (`Network.openConnection`), and prints a
verdict.

## Result on a Galaxy S23 Ultra, Android 16, AmneziaWG connected (2026-10-13)

| App in Amnezia's Split App Tunneling | The app's active network | Socket bound to cellular | Verdict |
|---|---|---|---|
| not excluded | `CELLULAR+VPN`, `tun0` | `EPERM — Operation not permitted` | the tunnel owns the app's sockets |
| excluded, tunnel reconnected | `CELLULAR`, `rmnet_data7`, `NOT_VPN` | HTTPS 157 ms, `generate_204` → 204 in 200 ms, DNS 28 ms | **route confirmed** |

So the mechanism the probe needs is real: Android refuses to bind a socket to another network for
an app inside a VPN, and Split App Tunneling lifts that completely. Two things learned on the way:

- **A full reinstall changes the app's UID**, and the running tunnel keeps excluding the old one —
  the exclusion looks lost until Amnezia is reconnected. Keep the keystore and use `install -r`.
- Equal egress addresses on the two paths do **not** mean the VPN captured the socket: an excluded
  app has the carrier as its default network too. The verdict only calls it capture when the app's
  own active network carries `TRANSPORT_VPN`.

The Wi-Fi case (Wi-Fi on, VPN up, explicit cellular binding) was not run — the owner judged it
analogous, since the refusal came from the VPN and not from Wi-Fi. What stays unproven there is
only whether the system brings the cellular radio up on request while Wi-Fi is the default; that
shows up immediately in the probe's own first run.

## Building

```bash
./build.sh            # out/vpn-pulse-spike.apk
./build.sh install    # build, install and start it on the attached phone
```

No Gradle, no Kotlin, no libraries: `aapt2 → javac → d8 → zipalign → apksigner` with the JDK and
the Android SDK already on the machine. The same chain is the offline fallback for the real app
(`plans/android-app-plan.md` in the private planning repository).
