package dev.vpnpulse.probe;

import android.content.Context;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Four bars with their names under them, the prototype's .stepper: the step in hand is bold and in
 * the accent colour, every step already behind it keeps its bar filled, the ones ahead are a
 * hairline track. A screen reader hears the four names once, in order, as one line.
 *
 * At a large system font the four names cannot share the width — a quarter of the screen is not
 * enough for "Enrollment", and the line breaks in the middle of the word. So past LARGE_TEXT only
 * the step in hand is named, across the whole width, and the bars alone say where the other three
 * are. The prototype does the same under html[data-text200="true"].
 */
final class StepBar extends LinearLayout {

    private static final String SEPARATOR = " → ";
    /** .stepper { gap: 6px } — between the bars and the names under them. */
    private static final int LABEL_GAP_DP = 6;
    private static final float LARGE_TEXT = 1.3f;

    StepBar(Context c, Text t, Step current) {
        super(c);
        setOrientation(VERTICAL);

        StringBuilder spoken = new StringBuilder();
        for (Step step : Step.ALL) {
            if (spoken.length() > 0) {
                spoken.append(SEPARATOR);
            }
            spoken.append(t.get(step.labelRes));
        }
        setContentDescription(spoken.toString());

        int bar = Views.px(c, R.dimen.space_1);
        int gap = Math.round(LABEL_GAP_DP * c.getResources().getDisplayMetrics().density);
        boolean roomy = c.getResources().getConfiguration().fontScale < LARGE_TEXT;

        LinearLayout bars = new LinearLayout(c);
        bars.setOrientation(HORIZONTAL);
        bars.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        for (Step step : Step.ALL) {
            boolean filled = step.ordinal() <= current.ordinal();
            View track = new View(c);
            GradientDrawable face = new GradientDrawable();
            face.setShape(GradientDrawable.RECTANGLE);
            face.setCornerRadius(bar / 2f);
            face.setColor(c.getColor(filled ? R.color.color_accent : R.color.color_border));
            track.setBackground(face);
            bars.addView(track, segment(bar, step.ordinal(), bar));
        }
        addView(bars, new LinearLayout.LayoutParams(Views.MATCH, Views.WRAP));

        LinearLayout names = new LinearLayout(c);
        names.setOrientation(HORIZONTAL);
        names.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        if (roomy) {
            for (Step step : Step.ALL) {
                names.addView(name(c, t, step, step == current),
                        segment(Views.WRAP, step.ordinal(), bar));
            }
        } else {
            names.addView(name(c, t, current, true),
                    new LinearLayout.LayoutParams(Views.MATCH, Views.WRAP));
        }
        LinearLayout.LayoutParams under = new LinearLayout.LayoutParams(Views.MATCH, Views.WRAP);
        under.topMargin = gap;
        addView(names, under);
    }

    private static TextView name(Context c, Text t, Step step, boolean here) {
        // .stepper .names span[data-on]: the step in hand is the strong colour, not the accent —
        // the accent belongs to the bars, which are the thing that says where you are
        TextView name = Views.text(c, t.get(step.labelRes), R.dimen.text_xs,
                here ? R.color.color_text : R.color.color_muted, here, Views.LH_CAPTION);
        name.setGravity(Gravity.CENTER_HORIZONTAL);
        return name;
    }

    /** One of four equal columns, with the bar's own width as the space between them. */
    private static LinearLayout.LayoutParams segment(int height, int index, int between) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, height, 1f);
        if (index > 0) {
            params.setMarginStart(between);
        }
        return params;
    }
}
