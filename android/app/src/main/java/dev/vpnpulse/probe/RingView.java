package dev.vpnpulse.probe;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.text.Layout;
import android.text.StaticLayout;
import android.text.TextPaint;
import android.util.DisplayMetrics;
import android.view.View;
import android.view.animation.AnimationUtils;

/**
 * The ring: the piece the whole screen is built around, copied from the VPN client the owner
 * already uses. It says what is happening — colour, word, caption — and on the main screen of Э2
 * it will also be the control that starts and stops the checks, which is why it can be clicked.
 *
 * What the prototype's CSS asks for, and how it is drawn here (web/src/android.css, .ring):
 *   border: 3px solid currentColor               a 3 px stroke in the state's lamp colour
 *   box-shadow: 0 0 26px currentColor 42 %       a radial halo that peaks on the stroke; a blur
 *                                                mask filter is ignored on a hardware canvas, a
 *                                                gradient is not, and it needs no software layer
 *   inset 0 0 36px currentColor 10 %             a faint tint that gathers along the inside edge
 *   border-style: dashed + @keyframes rotate     the busy mode: a dashed stroke turning once per
 *                                                2.4 s, still unless the system says no animation
 *   width: min(248px, 64vw)                      four ring-size units, or 64 % of the screen
 *
 * The halo is drawn inside the view's own box (the circle plus one space-3 ring of room), because
 * a parent clips its children: nothing of the glow is cut off, and the view never grows wider than
 * the screen less its two space-4 margins.
 */
final class RingView extends View {

    /** .ring { width: min(248px, 64vw) } — 4 x ring_size is the 256 dp the token scale gives. */
    private static final float SCREEN_FRACTION = 0.64f;
    private static final int RING_UNITS = 4;
    /** @keyframes rotate: 2.4s linear infinite. */
    private static final long SPIN_MS = 2400L;
    /** box-shadow 42 % and inset 10 % of the state colour. */
    private static final int GLOW_ALPHA = 107;
    private static final int TINT_ALPHA = 26;
    /** Where the inner tint starts, as a share of the radius: the inset blur reaches about here. */
    private static final float TINT_FROM = 0.45f;
    /** .ring:active { transform: scale(.985) }. */
    private static final float PRESS_SCALE = 0.985f;
    /** .ring .sub { max-width: 18ch } — "ch" is the width of a zero. */
    private static final int CAPTION_MAX_CH = 18;
    private static final String CH = "0";
    /** Room for 200 % system text inside a circle that cannot grow: shrink, never spill. */
    private static final int SHRINK_STEPS = 4;
    private static final float SHRINK_BY = 0.12f;

    private final Paint solid = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dashed = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint halo = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint tint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint focusRing = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final TextPaint titlePaint = new TextPaint(Paint.ANTI_ALIAS_FLAG);
    private final TextPaint captionPaint = new TextPaint(Paint.ANTI_ALIAS_FLAG);
    private final Path circle = new Path();

    private final int strokeWidth;
    private final int glowWidth;
    private final int padding;
    private final int innerGap;
    private final int focusGap;
    private final float titleSize;
    private final float captionSize;
    private final int diameter;
    private final boolean animated;

    private RingState state = RingState.UNKNOWN;
    private String title = "";
    private String caption;
    private boolean busy;
    private StaticLayout titleLayout;
    private StaticLayout captionLayout;
    private boolean textDirty = true;
    private int haloColor;
    private float haloRadius;

    RingView(Context c) {
        super(c);
        strokeWidth = Views.hairline(c) * 3;   // the prototype's 3 px ring; the tokens carry no 3 dp
        glowWidth = Views.px(c, R.dimen.space_3);
        padding = Views.px(c, R.dimen.space_5);
        innerGap = Views.px(c, R.dimen.space_1);
        focusGap = Views.px(c, R.dimen.focus_width);
        titleSize = c.getResources().getDimension(R.dimen.text_lg);
        captionSize = c.getResources().getDimension(R.dimen.text_xs);
        diameter = diameter(c, glowWidth);
        animated = Views.animationsEnabled(c);

        solid.setStyle(Paint.Style.STROKE);
        solid.setStrokeWidth(strokeWidth);
        dashed.setStyle(Paint.Style.STROKE);
        dashed.setStrokeWidth(strokeWidth);
        dashed.setPathEffect(new DashPathEffect(
                new float[]{Views.px(c, R.dimen.space_3), Views.px(c, R.dimen.space_2)}, 0f));
        halo.setStyle(Paint.Style.FILL);
        tint.setStyle(Paint.Style.FILL);
        focusRing.setStyle(Paint.Style.STROKE);
        focusRing.setStrokeWidth(focusGap);
        focusRing.setColor(c.getColor(R.color.color_focus));
        titlePaint.setTypeface(Typeface.DEFAULT_BOLD);
        titlePaint.setTextSize(titleSize);
        captionPaint.setTextSize(captionSize);
        captionPaint.setColor(c.getColor(R.color.color_muted));
    }

    private static int diameter(Context c, int glowWidth) {
        DisplayMetrics screen = c.getResources().getDisplayMetrics();
        // the short side, so a phone on its side does not get a ring taller than the screen
        int across = Math.min(screen.widthPixels, screen.heightPixels);
        int units = Views.px(c, R.dimen.ring_size) * RING_UNITS;
        int share = Math.round(across * SCREEN_FRACTION);
        int fits = across - 2 * Views.px(c, R.dimen.space_4) - 2 * glowWidth;
        return Math.max(1, Math.min(units, Math.min(share, fits)));
    }

    /**
     * @param caption the second, quieter line, or null when the state says it in one word.
     * @param busy    the check is running: dash the stroke and turn it.
     */
    void show(RingState state, String title, String caption, boolean busy) {
        this.state = state;
        this.title = title == null ? "" : title;
        this.caption = caption;
        this.busy = busy;
        textDirty = true;
        invalidate();
    }

    @Override
    protected void onMeasure(int widthSpec, int heightSpec) {
        int size = diameter + 2 * glowWidth;
        setMeasuredDimension(resolveSize(size, widthSpec), resolveSize(size, heightSpec));
    }

    @Override
    public void setPressed(boolean pressed) {
        super.setPressed(pressed);
        if (!isClickable()) {
            return;
        }
        float scale = pressed ? PRESS_SCALE : 1f;
        setScaleX(scale);
        setScaleY(scale);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int color = getContext().getColor(state.colorRes);
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        float radius = Math.min(getWidth(), getHeight()) / 2f - glowWidth - strokeWidth / 2f;
        if (radius <= 0f) {
            return;
        }

        float reach = radius + strokeWidth / 2f + glowWidth;
        if (halo.getShader() == null || haloColor != color || haloRadius != reach) {
            halo.setShader(new RadialGradient(cx, cy, reach,
                    new int[]{0, Views.withAlpha(color, GLOW_ALPHA), 0},
                    new float[]{Math.max(0f, (radius - strokeWidth) / reach),
                            (radius + strokeWidth / 2f) / reach, 1f},
                    Shader.TileMode.CLAMP));
            tint.setShader(new RadialGradient(cx, cy, radius,
                    new int[]{0, Views.withAlpha(color, TINT_ALPHA)},
                    new float[]{TINT_FROM, 1f}, Shader.TileMode.CLAMP));
            haloColor = color;
            haloRadius = reach;
        }
        canvas.drawCircle(cx, cy, reach, halo);
        canvas.drawCircle(cx, cy, radius, tint);

        if (busy) {
            float angle = 0f;
            if (animated) {
                angle = 360f * (AnimationUtils.currentAnimationTimeMillis() % SPIN_MS) / SPIN_MS;
                postInvalidateOnAnimation();
            }
            dashed.setColor(color);
            circle.reset();
            circle.addCircle(cx, cy, radius, Path.Direction.CW);
            canvas.save();
            canvas.rotate(angle, cx, cy);
            canvas.drawPath(circle, dashed);
            canvas.restore();
        } else {
            solid.setColor(color);
            canvas.drawCircle(cx, cy, radius, solid);
        }
        if (isFocused()) {
            canvas.drawCircle(cx, cy, radius + strokeWidth / 2f + 2 * focusGap, focusRing);
        }

        int room = diameter - 2 * padding - 2 * strokeWidth;
        if (textDirty || titleLayout == null) {
            layoutText(Math.max(1, room), Math.max(1, room));
            textDirty = false;
        }
        float stack = titleLayout.getHeight()
                + (captionLayout == null ? 0 : innerGap + captionLayout.getHeight());
        float top = cy - stack / 2f;
        titlePaint.setColor(color);
        canvas.save();
        canvas.translate(cx - titleLayout.getWidth() / 2f, top);
        titleLayout.draw(canvas);
        canvas.restore();
        if (captionLayout != null) {
            canvas.save();
            canvas.translate(cx - captionLayout.getWidth() / 2f,
                    top + titleLayout.getHeight() + innerGap);
            captionLayout.draw(canvas);
            canvas.restore();
        }
    }

    /** Wraps both lines to the circle's inner width, shrinking them until the stack fits. */
    private void layoutText(int width, int height) {
        float scale = 1f;
        for (int attempt = 0; ; attempt++) {
            titlePaint.setTextSize(titleSize * scale);
            captionPaint.setTextSize(captionSize * scale);
            titleLayout = layout(title, titlePaint, width, Views.LH_TIGHT);
            if (caption == null || caption.length() == 0) {
                captionLayout = null;
            } else {
                int narrow = Math.min(width, Math.round(captionPaint.measureText(CH) * CAPTION_MAX_CH));
                captionLayout = layout(caption, captionPaint, narrow, Views.LH_CAPTION);
            }
            int used = titleLayout.getHeight()
                    + (captionLayout == null ? 0 : innerGap + captionLayout.getHeight());
            if (used <= height || attempt >= SHRINK_STEPS) {
                return;
            }
            scale -= SHRINK_BY;
        }
    }

    /** Leading as a length, like Views.lineHeight: the multiplier would scale the font's own box. */
    private static StaticLayout layout(String s, TextPaint paint, int width, float lineHeight) {
        Paint.FontMetricsInt metrics = paint.getFontMetricsInt();
        int target = Math.round(paint.getTextSize() * lineHeight);
        return StaticLayout.Builder.obtain(s, 0, s.length(), paint, Math.max(1, width))
                .setAlignment(Layout.Alignment.ALIGN_CENTER)
                .setLineSpacing(target - (metrics.descent - metrics.ascent), 1f)
                .setIncludePad(false)
                .build();
    }
}
