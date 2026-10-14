package dev.vpnpulse.probe;

/**
 * The four lamp colours of the instrument panel. The same four the Mini App uses, so a phone and a
 * dashboard never disagree about what green means.
 */
enum RingState {

    OPERATIONAL(R.color.color_operational),
    DEGRADED(R.color.color_degraded),
    UNAVAILABLE(R.color.color_unavailable),
    UNKNOWN(R.color.color_unknown);

    final int colorRes;

    RingState(int colorRes) {
        this.colorRes = colorRes;
    }
}
