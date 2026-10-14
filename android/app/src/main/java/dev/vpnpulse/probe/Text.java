package dev.vpnpulse.probe;

import android.content.Context;
import android.content.res.Configuration;
import java.util.Locale;

/**
 * Every word the probe says comes from res/values[-ru]/strings.xml, which is generated from the
 * product's own dictionaries (scripts/build_android_strings.py). This is the only way the app
 * reads them, and the only place that knows which language is on screen.
 *
 * The language is part of the screen's state, not of the device's settings: the shell has a button
 * that flips it, and the flip must not restart the activity. So instead of recreating the task we
 * keep a context whose configuration carries the chosen locale and resolve every string through it.
 * Colours and metrics still come from the activity, which already follows the system's dark mode.
 */
final class Text {

    static final String RU = "ru";
    static final String EN = "en";

    private final Context localized;
    private final String lang;

    private Text(Context localized, String lang) {
        this.localized = localized;
        this.lang = lang;
    }

    /** @param chosen "ru", "en", or null to follow the system (English is the generated default). */
    static Text of(Context base, String chosen) {
        String lang = RU.equals(chosen) || EN.equals(chosen) ? chosen : systemLang(base);
        Locale locale = new Locale(lang);
        Configuration config = new Configuration(base.getResources().getConfiguration());
        config.setLocale(locale);
        config.setLayoutDirection(locale);
        return new Text(base.createConfigurationContext(config), lang);
    }

    static String systemLang(Context base) {
        Locale first = base.getResources().getConfiguration().getLocales().get(0);
        return first != null && RU.equals(first.getLanguage()) ? RU : EN;
    }

    String lang() {
        return lang;
    }

    /** The language the shell's button switches to. */
    String other() {
        return RU.equals(lang) ? EN : RU;
    }

    /**
     * The name of that other language, in that language ("русский", "English"). The dictionaries
     * carry no such key — app.lang.other is the two-letter badge — so the name comes from the
     * platform's own locale data rather than from a literal in this file.
     */
    String otherLanguageName() {
        Locale o = new Locale(other());
        return o.getDisplayLanguage(o);
    }

    String get(int stringRes) {
        return localized.getString(stringRes);
    }

    String get(int stringRes, Object... args) {
        return localized.getString(stringRes, args);
    }
}
