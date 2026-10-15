package dev.vpnpulse.probe;

import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.drawable.Drawable;

/**
 * The prototype's line icons, drawn rather than shipped. The web mock uses an inline SVG sprite
 * with a 1.8-wide round-capped stroke on a 22-unit box (svg.i in web/src/android.css); the same
 * geometry is spelled out here in unit coordinates so the app needs no drawable resources and no
 * second copy of the sprite.
 */
final class GlyphDrawable extends Drawable {

    enum Glyph { BACK, CHECK, REFRESH, SETTINGS, PLAY }

    /** svg.i: stroke-width 1.8 on a 22-unit viewport. */
    private static final float STROKE_RATIO = 1.8f / 22f;

    private final Glyph glyph;
    private final int size;
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final RectF box = new RectF();

    GlyphDrawable(Glyph glyph, int color, int size) {
        this.glyph = glyph;
        this.size = size;
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeWidth(Math.max(1f, size * STROKE_RATIO));
        stroke.setStrokeCap(Paint.Cap.ROUND);
        stroke.setStrokeJoin(Paint.Join.ROUND);
        stroke.setColor(color);
        fill.setStyle(Paint.Style.FILL);
        fill.setColor(color);
        setBounds(0, 0, size, size);
    }

    @Override
    public int getIntrinsicWidth() {
        return size;
    }

    @Override
    public int getIntrinsicHeight() {
        return size;
    }

    @Override
    public void draw(Canvas canvas) {
        Rect bounds = getBounds();
        float side = Math.min(bounds.width(), bounds.height());
        if (side <= 0f) {
            return;
        }
        float left = bounds.left + (bounds.width() - side) / 2f;
        float top = bounds.top + (bounds.height() - side) / 2f;
        path.reset();
        switch (glyph) {
            case BACK:
                move(left, top, side, 0.60f, 0.18f);
                line(left, top, side, 0.32f, 0.50f);
                line(left, top, side, 0.60f, 0.82f);
                canvas.drawPath(path, stroke);
                break;
            case CHECK:
                move(left, top, side, 0.20f, 0.53f);
                line(left, top, side, 0.41f, 0.73f);
                line(left, top, side, 0.80f, 0.27f);
                canvas.drawPath(path, stroke);
                break;
            case REFRESH:
                // an almost closed circle, with a filled head on the open end: "check again"
                box.set(left + side * 0.20f, top + side * 0.20f, left + side * 0.80f, top + side * 0.80f);
                path.addArc(box, 40f, 285f);
                canvas.drawPath(path, stroke);
                path.reset();
                move(left, top, side, 0.72f, 0.16f);
                line(left, top, side, 0.88f, 0.40f);
                line(left, top, side, 0.60f, 0.40f);
                path.close();
                canvas.drawPath(path, fill);
                break;
            case SETTINGS:
                // two sliders: the gear of the sprite reads as mud at 24 dp, sliders do not
                move(left, top, side, 0.16f, 0.34f);
                line(left, top, side, 0.84f, 0.34f);
                move(left, top, side, 0.16f, 0.66f);
                line(left, top, side, 0.84f, 0.66f);
                canvas.drawPath(path, stroke);
                canvas.drawCircle(left + side * 0.64f, top + side * 0.34f, side * 0.10f, stroke);
                canvas.drawCircle(left + side * 0.36f, top + side * 0.66f, side * 0.10f, stroke);
                break;
            default:
                move(left, top, side, 0.32f, 0.20f);
                line(left, top, side, 0.82f, 0.50f);
                line(left, top, side, 0.32f, 0.80f);
                path.close();
                canvas.drawPath(path, fill);
                break;
        }
    }

    private void move(float left, float top, float side, float x, float y) {
        path.moveTo(left + side * x, top + side * y);
    }

    private void line(float left, float top, float side, float x, float y) {
        path.lineTo(left + side * x, top + side * y);
    }

    @Override
    public void setAlpha(int alpha) {
        stroke.setAlpha(alpha);
        fill.setAlpha(alpha);
        invalidateSelf();
    }

    @Override
    public void setColorFilter(ColorFilter filter) {
        stroke.setColorFilter(filter);
        fill.setColorFilter(filter);
        invalidateSelf();
    }

    @Override
    public int getOpacity() {
        return PixelFormat.TRANSLUCENT;
    }
}
