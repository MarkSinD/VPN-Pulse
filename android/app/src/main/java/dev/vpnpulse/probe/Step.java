package dev.vpnpulse.probe;

/** The four screens of enrolment, in the order the step bar shows them. */
enum Step {

    BIND(R.string.android_step_bind),
    EXCLUDE(R.string.android_step_exclude),
    CELLULAR(R.string.android_step_cellular),
    DONE(R.string.android_step_done);

    static final Step[] ALL = values();

    final int labelRes;

    Step(int labelRes) {
        this.labelRes = labelRes;
    }

    /** null on the first step: there is nothing to go back to, and the shell hides the arrow. */
    Step previous() {
        return ordinal() == 0 ? null : ALL[ordinal() - 1];
    }

    static Step byName(String name, Step fallback) {
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
