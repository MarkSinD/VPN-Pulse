package dev.vpnpulse.probe;

import android.os.Bundle;

/**
 * Everything a rotation or a process restart must not lose: which step the owner is on, what the
 * route check answered, the code already typed, and the language chosen in the shell. Enums travel
 * by name so a reordering of the constants cannot silently change a restored screen.
 */
final class Flow {

    private static final String KEY_STEP = "vpnpulse.step";
    private static final String KEY_CELLULAR = "vpnpulse.cellular";
    private static final String KEY_CODE = "vpnpulse.code";
    private static final String KEY_CODE_ERROR = "vpnpulse.codeError";
    private static final String KEY_LANG = "vpnpulse.lang";

    Step step = Step.BIND;
    CellularState cellular = CellularState.CHECKING;
    String code = "";
    boolean codeError;
    /** null: follow the system. "ru" or "en" once the owner has used the language button. */
    String lang;

    void save(Bundle out) {
        out.putString(KEY_STEP, step.name());
        out.putString(KEY_CELLULAR, cellular.name());
        out.putString(KEY_CODE, code);
        out.putBoolean(KEY_CODE_ERROR, codeError);
        out.putString(KEY_LANG, lang);
    }

    static Flow restore(Bundle in) {
        Flow flow = new Flow();
        if (in == null) {
            return flow;
        }
        flow.step = Step.byName(in.getString(KEY_STEP), Step.BIND);
        flow.cellular = CellularState.byName(in.getString(KEY_CELLULAR), CellularState.CHECKING);
        String code = in.getString(KEY_CODE);
        flow.code = code == null ? "" : code;
        flow.codeError = in.getBoolean(KEY_CODE_ERROR, false);
        flow.lang = in.getString(KEY_LANG);
        return flow;
    }
}
