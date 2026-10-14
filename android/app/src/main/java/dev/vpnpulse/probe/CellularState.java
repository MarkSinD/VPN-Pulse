package dev.vpnpulse.probe;

/**
 * What the route check through the mobile network is saying right now. One place decides how each
 * answer looks — ring colour, the words inside the ring, the line under it — exactly as the RING
 * table in web/src/android.js does for the prototype.
 */
enum CellularState {

    CHECKING(RingState.UNKNOWN, R.string.android_cellular_checking, 0, R.string.android_cellularready, true),
    OK(RingState.OPERATIONAL, R.string.android_route_ok, R.string.android_cellular_ok, R.string.android_wifion, false),
    FAIL(RingState.UNAVAILABLE, R.string.android_route_bad, R.string.android_cellular_fail, R.string.android_cellularready, false),
    NO_SIM(RingState.UNKNOWN, R.string.android_cellular_nosim, R.string.android_cellular_fix, R.string.android_cellularready, false);

    static final CellularState[] ALL = values();

    final RingState ring;
    final int titleRes;
    /** 0 when the ring carries no caption, as while the check is running. */
    final int captionRes;
    final int hintRes;
    final boolean busy;

    CellularState(RingState ring, int titleRes, int captionRes, int hintRes, boolean busy) {
        this.ring = ring;
        this.titleRes = titleRes;
        this.captionRes = captionRes;
        this.hintRes = hintRes;
        this.busy = busy;
    }

    CellularState following() {
        return ALL[(ordinal() + 1) % ALL.length];
    }

    static CellularState byName(String name, CellularState fallback) {
        if (name == null) {
            return fallback;
        }
        try {
            return valueOf(name);
        } catch (IllegalArgumentException wrongName) {
            return fallback;
        }
    }
}
