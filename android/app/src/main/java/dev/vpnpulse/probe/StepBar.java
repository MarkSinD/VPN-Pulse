package dev.vpnpulse.probe;

import android.content.Context;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Four segments with their names under them, the prototype's .stepper: the step in hand is bold
 * and in the accent colour, every step already behind it keeps its bar filled, the ones ahead are
 * a hairline track. A screen reader hears the four names once, in order, as one line.
 */
final class StepBar extends LinearLayout {

    private static final String SEPARATOR = " → ";
    /** .stepper div { gap: 6px } — between the bar and its name. */
    private static final int LABEL_GAP_DP = 6;

    StepBar(Context c, Text t, Step current) {
        super(c);
        setOrientation(HORIZONTAL);

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
        for (Step step : Step.ALL) {
            boolean here = step == current;
            boolean behind = step.ordinal() < current.ordinal();

            LinearLayout segment = Views.column(c);
            segment.setGravity(Gravity.CENTER_HORIZONTAL);
            segment.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);

            View track = new View(c);
            GradientDrawable face = new GradientDrawable();
            face.setShape(GradientDrawable.RECTANGLE);
            face.setCornerRadius(bar / 2f);
            face.setColor(c.getColor(here || behind ? R.color.color_accent : R.color.color_border));
            track.setBackground(face);
            segment.addView(track, new LinearLayout.LayoutParams(Views.MATCH, bar));

            TextView name = Views.text(c, t.get(step.labelRes), R.dimen.text_xs,
                    here ? R.color.color_accent : R.color.color_muted, here, Views.LH_CAPTION);
            // no line cap: at 200 % text the names have to wrap, and a cut-off step is worse
            name.setGravity(Gravity.CENTER_HORIZONTAL);
            LinearLayout.LayoutParams nameParams = new LinearLayout.LayoutParams(Views.MATCH, Views.WRAP);
            nameParams.topMargin = gap;
            segment.addView(name, nameParams);

            LinearLayout.LayoutParams segmentParams = new LinearLayout.LayoutParams(0, Views.WRAP, 1f);
            if (step.ordinal() > 0) {
                segmentParams.setMarginStart(bar);
            }
            addView(segment, segmentParams);
        }
    }
}
