package dev.vpnpulse.probe;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Build;
import android.provider.Settings;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.util.DisplayMetrics;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * The small, dull part of the instrument panel: text, buttons, panels and fields, each built from
 * the generated resources and nothing else. No XML layout, no AndroidX, so every widget the probe
 * shows is assembled here once and reused by the screens.
 *
 * Four numbers in this file are not resources, and cannot be: a hairline is one physical pixel,
 * the tint under an informational panel is a CSS color-mix the theme generator does not export,
 * letter spacing and line height are ratios rather than lengths, and the widest the content may
 * grow is the prototype's own device frame. Each is named and commented below.
 */
final class Views {

    static final int MATCH = ViewGroup.LayoutParams.MATCH_PARENT;
    static final int WRAP = ViewGroup.LayoutParams.WRAP_CONTENT;

    /** --lh-tight, --lh-caption, --lh-normal of web/src/ui-tokens.css. */
    static final float LH_TIGHT = 1.2f;
    static final float LH_CAPTION = 1.4f;
    static final float LH_NORMAL = 1.5f;

    /** .device { max-width: 480px }: past that, a line of text is too long to read comfortably. */
    private static final int CONTENT_MAX_DP = 480;

    /** .banner-info: color-mix(var(--color-muted) var(--tint)) — --tint is 12 % light, 16 % dark. */
    private static final int PANEL_TINT_ALPHA = 0x24;
    private static final int RIPPLE_ALPHA = 0x3D;
    /** .field input { letter-spacing: .08em } and .lang-btn { letter-spacing: .06em }. */
    private static final float CODE_TRACKING = 0.08f;
    private static final float BADGE_TRACKING = 0.06f;

    private Views() {
    }

    // ---------- metrics ----------

    static int px(Context c, int dimenRes) {
        return c.getResources().getDimensionPixelSize(dimenRes);
    }

    /** One physical pixel, the thinnest line the screen can draw: the CSS 1 px border. */
    static int hairline(Context c) {
        return Math.max(1, Math.round(c.getResources().getDisplayMetrics().density));
    }

    /**
     * Half of whatever the screen has beyond a comfortable measure, so a wide screen gets margins
     * instead of 70-character lines. Zero on a phone, where the screen is narrower than the cap.
     */
    static int gutter(Context c) {
        DisplayMetrics screen = c.getResources().getDisplayMetrics();
        int cap = Math.round(CONTENT_MAX_DP * screen.density);
        return Math.max(0, (screen.widthPixels - cap) / 2);
    }

    static int withAlpha(int color, int alpha) {
        return (color & 0x00FFFFFF) | (alpha << 24);
    }

    /** False when the owner has turned animations off in the developer or accessibility settings. */
    static boolean animationsEnabled(Context c) {
        try {
            return Settings.Global.getFloat(c.getContentResolver(),
                    Settings.Global.ANIMATOR_DURATION_SCALE, 1f) != 0f;
        } catch (Throwable unreadable) {
            return true;
        }
    }

    // ---------- type ----------

    /** sp from the generated dimens, resolved as pixels, so 200 % system text scaling still works. */
    static void size(TextView v, int dimenRes) {
        v.setTextSize(TypedValue.COMPLEX_UNIT_PX, v.getResources().getDimension(dimenRes));
    }

    static TextView text(Context c, CharSequence s, int sizeRes, int colorRes, boolean bold, float lineHeight) {
        TextView v = new TextView(c);
        v.setText(s);
        size(v, sizeRes);
        v.setTextColor(c.getColor(colorRes));
        if (bold) {
            v.setTypeface(Typeface.DEFAULT_BOLD);
        }
        lineHeight(v, lineHeight);
        return v;
    }

    /**
     * The tokens are written for the web box: a line is exactly size × ratio, with nothing above
     * the first line or below the last. Android instead multiplies the font's own line box — 1.17 em
     * for Roboto — and adds its recommended padding on top, which turns --lh-normal into 1.76 and
     * gives every block invisible edges. So the leading is set as a length, and the padding goes.
     */
    static void lineHeight(TextView v, float ratio) {
        v.setIncludeFontPadding(false);
        int target = Math.round(v.getTextSize() * ratio);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            v.setLineHeight(target);
            return;
        }
        Paint.FontMetricsInt metrics = v.getPaint().getFontMetricsInt();
        v.setLineSpacing(target - (metrics.descent - metrics.ascent), 1f);
    }

    static TextView heading(Context c, CharSequence s) {
        TextView v = text(c, s, R.dimen.text_xl, R.color.color_text, true, LH_TIGHT);
        heading(v);
        return v;
    }

    /** The h1 of the step, announced as a heading where the platform knows the concept (API 28+). */
    static void heading(View v) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            v.setAccessibilityHeading(true);
        }
    }

    static TextView body(Context c, CharSequence s) {
        return text(c, s, R.dimen.text_md, R.color.color_text, false, LH_NORMAL);
    }

    static TextView muted(Context c, CharSequence s) {
        return text(c, s, R.dimen.text_md, R.color.color_muted, false, LH_NORMAL);
    }

    /** .muted.small and .hero .hint: the quiet line of a step. */
    static TextView note(Context c, CharSequence s) {
        return text(c, s, R.dimen.text_sm, R.color.color_muted, false, LH_CAPTION);
    }

    static TextView label(Context c, CharSequence s) {
        return text(c, s, R.dimen.text_sm, R.color.color_muted, false, LH_CAPTION);
    }

    static TextView error(Context c, CharSequence s) {
        TextView v = text(c, s, R.dimen.text_sm, R.color.color_unavailable, false, LH_CAPTION);
        v.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        return v;
    }

    /**
     * Three actions, numbered, instead of a paragraph about three actions: .steps-list of the
     * prototype — an accent disc with the number, the step beside it.
     */
    static LinearLayout stepsList(Context c, CharSequence... items) {
        LinearLayout list = column(c);
        int disc = px(c, R.dimen.space_5);
        for (int index = 0; index < items.length; index++) {
            LinearLayout row = new LinearLayout(c);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);

            TextView number = text(c, String.valueOf(index + 1), R.dimen.text_xs,
                    R.color.color_accent_text, true, LH_TIGHT);
            number.setGravity(Gravity.CENTER);
            GradientDrawable face = new GradientDrawable();
            face.setShape(GradientDrawable.OVAL);
            face.setColor(c.getColor(R.color.color_accent));
            number.setBackground(face);
            number.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            row.addView(number, new LinearLayout.LayoutParams(disc, disc));

            TextView what = body(c, items[index]);
            LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(0, WRAP, 1f);
            textParams.setMarginStart(px(c, R.dimen.space_3));
            row.addView(what, textParams);

            add(list, row, index == 0 ? 0 : px(c, R.dimen.space_2));
        }
        return list;
    }

    /** The engraved line of the Mini App: one hairline, the width of whatever holds it. */
    static View divider(Context c) {
        View line = new View(c);
        line.setBackgroundColor(c.getColor(R.color.color_border));
        return line;
    }

    // ---------- stacking ----------

    static LinearLayout column(Context c) {
        LinearLayout column = new LinearLayout(c);
        column.setOrientation(LinearLayout.VERTICAL);
        return column;
    }

    static void add(LinearLayout parent, View child, int topMargin) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(MATCH, WRAP);
        lp.topMargin = topMargin;
        parent.addView(child, lp);
    }

    static void addCentered(LinearLayout parent, View child, int topMargin) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(WRAP, WRAP);
        lp.topMargin = topMargin;
        lp.gravity = Gravity.CENTER_HORIZONTAL;
        parent.addView(child, lp);
    }

    // ---------- controls ----------

    /** .btn.btn-primary: a filled 48 dp pill, the one thing on the screen that is not quiet. */
    static View primary(Context c, CharSequence label, GlyphDrawable.Glyph glyph, View.OnClickListener onClick) {
        int ink = c.getColor(R.color.color_accent_text);
        return button(c, label, glyph, ink, pill(c, c.getColor(R.color.color_accent), 0, 0), onClick);
    }

    /** .btn.btn-outline: the same pill, drawn as a hairline instead of filled. */
    static View outline(Context c, CharSequence label, GlyphDrawable.Glyph glyph, View.OnClickListener onClick) {
        int ink = c.getColor(R.color.color_text);
        Drawable face = pill(c, Color.TRANSPARENT, hairline(c), c.getColor(R.color.color_border_strong));
        return button(c, label, glyph, ink, face, onClick);
    }

    private static GradientDrawable pill(Context c, int fill, int strokeWidth, int strokeColor) {
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.RECTANGLE);
        // a fully rounded 48 dp control: the prototype's border-radius 24 px
        d.setCornerRadius(px(c, R.dimen.accordion_min) / 2f);
        d.setColor(fill);
        if (strokeWidth > 0) {
            d.setStroke(strokeWidth, strokeColor);
        }
        return d;
    }

    /**
     * A row with the icon and the label centred together. A plain Button would park a compound
     * drawable against its own edge, far from the centred text, which is not what the prototype
     * shows; the label still wraps rather than clipping on a 320 dp screen at 200 % text.
     */
    private static View button(Context c, CharSequence label, GlyphDrawable.Glyph glyph, int ink,
                               Drawable face, View.OnClickListener onClick) {
        LinearLayout b = new LinearLayout(c);
        b.setOrientation(LinearLayout.HORIZONTAL);
        b.setGravity(Gravity.CENTER);
        b.setMinimumHeight(px(c, R.dimen.accordion_min));
        b.setPadding(px(c, R.dimen.space_4), px(c, R.dimen.space_2), px(c, R.dimen.space_4), px(c, R.dimen.space_2));
        b.setBackground(ripple(c, face, ink, null));
        b.setClickable(true);
        b.setFocusable(true);
        b.setOnClickListener(onClick);
        b.setAccessibilityDelegate(buttonRole());
        if (glyph != null) {
            int icon = px(c, R.dimen.space_5);
            ImageView image = new ImageView(c);
            image.setImageDrawable(new GlyphDrawable(glyph, ink, icon));
            image.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(icon, icon);
            lp.setMarginEnd(px(c, R.dimen.space_2));
            b.addView(image, lp);
        }
        TextView caption = new TextView(c);
        caption.setText(label);
        size(caption, R.dimen.text_md);
        caption.setTypeface(Typeface.DEFAULT_BOLD);
        caption.setTextColor(ink);
        caption.setGravity(Gravity.CENTER);
        lineHeight(caption, LH_TIGHT);
        b.addView(caption, new LinearLayout.LayoutParams(WRAP, WRAP));
        return b;
    }

    /** The round 44 dp icon button of the app bar — the back arrow, and whatever Э2 adds beside it. */
    static View iconButton(Context c, GlyphDrawable.Glyph glyph, CharSequence description,
                           View.OnClickListener onClick) {
        int ink = c.getColor(R.color.color_text);
        ImageView b = new ImageView(c);
        b.setImageDrawable(new GlyphDrawable(glyph, ink, px(c, R.dimen.space_5)));
        b.setScaleType(ImageView.ScaleType.CENTER);
        b.setContentDescription(description);
        b.setClickable(true);
        b.setFocusable(true);
        b.setOnClickListener(onClick);
        b.setAccessibilityDelegate(buttonRole());
        GradientDrawable face = new GradientDrawable();
        face.setShape(GradientDrawable.OVAL);
        face.setColor(Color.TRANSPARENT);
        GradientDrawable mask = new GradientDrawable();
        mask.setShape(GradientDrawable.OVAL);
        mask.setColor(Color.WHITE);
        b.setBackground(ripple(c, face, ink, mask));
        return b;
    }

    /** .lang-btn: a two-letter badge that flips the language of the whole app. */
    static View languageButton(Context c, Text t, View.OnClickListener onClick) {
        TextView b = new TextView(c);
        b.setText(t.get(R.string.app_lang_other));
        b.setContentDescription(t.get(R.string.app_lang_switch, t.otherLanguageName()));
        size(b, R.dimen.text_sm);
        b.setTypeface(Typeface.DEFAULT_BOLD);
        lineHeight(b, LH_TIGHT);
        b.setLetterSpacing(BADGE_TRACKING);
        b.setTextColor(c.getColor(R.color.color_text));
        b.setGravity(Gravity.CENTER);
        b.setMinWidth(px(c, R.dimen.control_min));
        b.setMinHeight(px(c, R.dimen.control_min));
        b.setMinimumWidth(px(c, R.dimen.control_min));
        b.setMinimumHeight(px(c, R.dimen.control_min));
        b.setPadding(px(c, R.dimen.space_3), 0, px(c, R.dimen.space_3), 0);
        GradientDrawable face = new GradientDrawable();
        face.setShape(GradientDrawable.RECTANGLE);
        face.setCornerRadius(px(c, R.dimen.radius_md));
        face.setColor(Color.TRANSPARENT);
        face.setStroke(hairline(c), c.getColor(R.color.color_border_strong));
        b.setBackground(ripple(c, face, c.getColor(R.color.color_text), null));
        b.setClickable(true);
        b.setFocusable(true);
        b.setOnClickListener(onClick);
        b.setAccessibilityDelegate(buttonRole());
        return b;
    }

    /** .banner-info: a tinted strip that states a fact and asks for nothing. */
    static View panel(Context c, GlyphDrawable.Glyph glyph, CharSequence s) {
        int quiet = c.getColor(R.color.color_muted);
        LinearLayout p = new LinearLayout(c);
        p.setOrientation(LinearLayout.HORIZONTAL);
        p.setGravity(Gravity.TOP);
        p.setPadding(px(c, R.dimen.space_4), px(c, R.dimen.space_3), px(c, R.dimen.space_4), px(c, R.dimen.space_3));
        GradientDrawable face = new GradientDrawable();
        face.setShape(GradientDrawable.RECTANGLE);
        face.setCornerRadius(px(c, R.dimen.radius_md));
        face.setColor(withAlpha(quiet, PANEL_TINT_ALPHA));
        p.setBackground(face);
        int icon = px(c, R.dimen.space_5);
        ImageView image = new ImageView(c);
        image.setImageDrawable(new GlyphDrawable(glyph, quiet, icon));
        image.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        LinearLayout.LayoutParams iconParams = new LinearLayout.LayoutParams(icon, icon);
        iconParams.setMarginEnd(px(c, R.dimen.space_3));
        p.addView(image, iconParams);
        p.addView(text(c, s, R.dimen.text_sm, R.color.color_text, false, LH_CAPTION),
                new LinearLayout.LayoutParams(0, WRAP, 1f));
        return p;
    }

    /**
     * The enrolment code: monospace, large and tracked out, in the recessed well the Mini App uses
     * for code. An invalid code reddens the border and, for a screen reader, marks the field itself
     * invalid — the message below it is a polite live region.
     */
    static EditText codeField(Context c, String value, String hint, CharSequence error) {
        EditText f = new EditText(c);
        f.setId(View.generateViewId());
        f.setSingleLine(true);
        f.setTypeface(Typeface.MONOSPACE);
        size(f, R.dimen.text_lg);
        f.setLetterSpacing(CODE_TRACKING);
        f.setText(value);
        f.setSelection(value.length());
        f.setHint(hint);
        f.setTextColor(c.getColor(R.color.color_text));
        f.setHintTextColor(c.getColor(R.color.color_muted));
        f.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        f.setImeOptions(EditorInfo.IME_ACTION_DONE);
        f.setGravity(Gravity.CENTER_VERTICAL);
        f.setMinimumHeight(px(c, R.dimen.accordion_min));
        f.setMinHeight(px(c, R.dimen.accordion_min));
        f.setPadding(px(c, R.dimen.space_3), 0, px(c, R.dimen.space_3), 0);
        GradientDrawable well = new GradientDrawable();
        well.setShape(GradientDrawable.RECTANGLE);
        well.setCornerRadius(px(c, R.dimen.radius_md));
        well.setColor(c.getColor(R.color.color_well));
        well.setStroke(error == null ? hairline(c) : px(c, R.dimen.focus_width),
                c.getColor(error == null ? R.color.color_border : R.color.color_unavailable));
        f.setBackground(well);
        if (error != null) {
            final CharSequence message = error;
            f.setAccessibilityDelegate(new View.AccessibilityDelegate() {
                @Override
                public void onInitializeAccessibilityNodeInfo(View host, AccessibilityNodeInfo info) {
                    super.onInitializeAccessibilityNodeInfo(host, info);
                    info.setContentInvalid(true);
                    info.setError(message);
                }
            });
        }
        return f;
    }

    /** Reports each keystroke, so a rotation never loses a half-typed code. */
    static void onTextChanged(EditText field, final Typed typed) {
        field.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
            }

            @Override
            public void afterTextChanged(Editable s) {
                typed.onTyped(s.toString());
            }
        });
    }

    interface Typed {
        void onTyped(String value);
    }

    private static Drawable ripple(Context c, Drawable face, int ink, Drawable mask) {
        return new RippleDrawable(ColorStateList.valueOf(withAlpha(ink, RIPPLE_ALPHA)), face, mask);
    }

    /** Tells a screen reader that this assembled row is a button, like the markup's <button>. */
    private static View.AccessibilityDelegate buttonRole() {
        return new View.AccessibilityDelegate() {
            @Override
            public void onInitializeAccessibilityNodeInfo(View host, AccessibilityNodeInfo info) {
                super.onInitializeAccessibilityNodeInfo(host, info);
                info.setClassName(Button.class.getName());
            }
        };
    }
}
