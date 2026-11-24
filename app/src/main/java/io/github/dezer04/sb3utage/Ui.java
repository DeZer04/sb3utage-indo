package io.github.dezer04.sb3utage;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * The app's look, shared by the start screen, the in-game menu and every dialog: a dark, rounded
 * style (cards, pill buttons, switches) with Basara's crimson as the accent. Every view is built in
 * code from these pieces, so the tokens below restyle the whole app.
 */
final class Ui {
    private Ui() {}

    // Surfaces, darkest to lightest
    static final int BG = 0xFF0C0D11;        // the start screen behind everything
    static final int WINDOW = 0xF5121318;    // a panel over the game (slightly see-through)
    static final int CARD = 0xFF1A1C23;      // one setting, one group
    static final int RAISED = 0xFF242731;    // controls inside a card (stepper value, slider track)
    static final int HOVER = 0xFF2E3240;     // a plain button
    static final int BORDER = 0xFF2C2F3A;
    static final int BORDER_STRONG = 0xFF3A3E4C;

    // The accent: Basara crimson, brighter while pressed or on
    static final int ACCENT = 0xFFE5484D;
    static final int ACCENT_PRESSED = 0xFFFF6369;
    static final int ACCENT_SUBTLE = 0x33E5484D;

    // The older names, kept for every view that uses them
    static final int TITLE = WINDOW;
    static final int FRAME = RAISED;
    static final int BUTTON = HOVER;
    static final int BUTTON_ON = ACCENT;
    static final int GRAB = ACCENT;
    static final int SELECTED = ACCENT_SUBTLE;
    static final int SURFACE = RAISED;
    static final int ACTIVE = HOVER;

    static final int TEXT = 0xFFF2F3F5;
    static final int SECONDARY = 0xFFB4B8C2;
    static final int MUTED = 0xFF7D8290;
    static final int WARNING = 0xFFFF6B6B;  // red, as the warning frames (Sheet.WARNING_TEXT)
    static final int SUCCESS = 0xFF46C37B;
    static final int PENDING = 0xFFF5B942;     // amber: a setting that waits for Restart
    static final int PENDING_BG = 0x26F5B942;
    static final int DANGER_TEXT = 0xFFFF7A7F;

    // Corner radii (dp)
    static final float RADIUS_WINDOW = 18, RADIUS_CARD = 12, RADIUS_CONTROL = 10, RADIUS_PILL = 999;

    static final Typeface MEDIUM = Typeface.create("sans-serif-medium", Typeface.NORMAL);
    static final Typeface MONO = Typeface.MONOSPACE;

    static int dp(Context context, float value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    /** A filled rounded box with a one pixel border (none when `border` is 0); `radiusDp` 0 is square. */
    static GradientDrawable box(Context context, int fill, int border, float radiusDp) {
        final GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        if (border != 0) shape.setStroke(Math.max(1, dp(context, 1)), border);
        if (radiusDp > 0) shape.setCornerRadius(dp(context, radiusDp));
        return shape;
    }

    /** `box`, with a ripple in the accent while pressed. */
    static Drawable touchBox(Context context, int fill, int border, float radiusDp) {
        return new RippleDrawable(ColorStateList.valueOf(Color.argb(70, 255, 99, 105)),
                box(context, fill, border, radiusDp), box(context, Color.WHITE, 0, radiusDp));
    }

    static TextView text(Context context, String value, float sp, int color) {
        final TextView view = new TextView(context);
        view.setText(value);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        view.setTextColor(color);
        view.setIncludeFontPadding(true);
        return view;
    }

    /** A section heading over a group: small, spaced capitals in the accent. */
    static TextView caption(Context context, String value) {
        final TextView view = text(context, value.toUpperCase(java.util.Locale.ROOT), 11.5f, ACCENT);
        view.setTypeface(MEDIUM);
        view.setLetterSpacing(0.08f);
        return view;
    }

    static ImageView icon(Context context, int drawable, int tint, float sizeDp) {
        final ImageView view = new ImageView(context);
        view.setImageResource(drawable);
        view.setImageTintList(ColorStateList.valueOf(tint));
        view.setLayoutParams(new LinearLayout.LayoutParams(dp(context, sizeDp), dp(context, sizeDp)));
        return view;
    }

    /** A pill button: the chosen one filled in the accent, the others raised with a hairline border. */
    static TextView chip(Context context, String label, boolean active, boolean enabled, View.OnClickListener onClick) {
        final TextView chip = text(context, label, 13, active ? Color.WHITE : TEXT);
        chip.setGravity(Gravity.CENTER);
        chip.setSingleLine(true);
        chip.setTypeface(MEDIUM);
        chip.setPadding(dp(context, 14), dp(context, 6), dp(context, 14), dp(context, 6));
        chip.setMinWidth(dp(context, 36));
        chip.setMinHeight(dp(context, 32));
        chip.setBackground(touchBox(context, active ? ACCENT : RAISED, active ? 0 : BORDER, RADIUS_PILL));
        if (!enabled) chip.setAlpha(0.4f);
        if (enabled && onClick != null) chip.setOnClickListener(onClick);
        return chip;
    }

    /** A switch: a rounded track (the accent when on) and a white knob at its end. */
    static View toggle(Context context, boolean on) {
        final View knob = new View(context) {
            private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

            @Override
            protected void onDraw(Canvas canvas) {
                final float w = getWidth(), h = getHeight(), r = h / 2f;
                paint.setColor(on ? ACCENT : HOVER);
                canvas.drawRoundRect(0, 0, w, h, r, r, paint);
                if (!on) {
                    paint.setStyle(Paint.Style.STROKE);
                    paint.setStrokeWidth(dp(context, 1));
                    paint.setColor(BORDER_STRONG);
                    canvas.drawRoundRect(0.5f, 0.5f, w - 0.5f, h - 0.5f, r, r, paint);
                    paint.setStyle(Paint.Style.FILL);
                }
                final float inset = dp(context, 3), knobR = r - inset;
                paint.setColor(on ? Color.WHITE : SECONDARY);
                canvas.drawCircle(on ? w - r : r, r, knobR, paint);
            }
        };
        knob.setLayoutParams(new LinearLayout.LayoutParams(dp(context, 46), dp(context, 26)));
        return knob;
    }

    /** A rounded button with an optional icon: primary (accent fill), plain (raised), or danger (red text). */
    static LinearLayout button(Context context, int iconRes, String label, int style, View.OnClickListener onClick) {
        final LinearLayout row = new LinearLayout(context);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        row.setPadding(dp(context, 18), dp(context, 10), dp(context, 18), dp(context, 10));
        row.setMinimumHeight(dp(context, 44));
        row.setBackground(touchBox(context, style == PRIMARY ? ACCENT : RAISED, style == PRIMARY ? 0 : BORDER,
                RADIUS_CONTROL + 2));
        final int color = style == DANGER ? DANGER_TEXT : style == PRIMARY ? Color.WHITE : TEXT;
        if (iconRes != 0) row.addView(icon(context, iconRes, color, 18));
        final TextView name = text(context, label, 14, color);
        name.setTypeface(MEDIUM);
        name.setSingleLine(true);
        final LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.leftMargin = iconRes != 0 ? dp(context, 9) : 0;
        row.addView(name, params);
        row.setClickable(true);
        row.setOnClickListener(onClick);
        return row;
    }

    static final int PLAIN = 0, PRIMARY = 1, DANGER = 2;

    /** A hairline divider across. */
    static View line(Context context) {
        final View rule = new View(context);
        rule.setBackgroundColor(BORDER);
        final LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                Math.max(1, dp(context, 1)));
        params.setMargins(0, dp(context, 6), 0, dp(context, 6));
        rule.setLayoutParams(params);
        return rule;
    }

    /** A panel's header: an accent bar, the title in bold on the left, `right` (small, dim) on the right or nothing. */
    static LinearLayout titleBar(Context context, String title, String right) {
        final LinearLayout bar = new LinearLayout(context);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(context, 18), dp(context, 14), dp(context, 18), dp(context, 10));
        final View mark = new View(context);
        mark.setBackground(box(context, ACCENT, 0, RADIUS_PILL));
        final LinearLayout.LayoutParams markParams = new LinearLayout.LayoutParams(dp(context, 4), dp(context, 20));
        markParams.rightMargin = dp(context, 10);
        bar.addView(mark, markParams);
        final TextView name = text(context, title, 18, TEXT);
        name.setTypeface(Typeface.DEFAULT_BOLD);
        name.setSingleLine(true);
        name.setEllipsize(android.text.TextUtils.TruncateAt.END);
        bar.addView(name, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        if (right != null) bar.addView(text(context, right, 11, MUTED));
        return bar;
    }

    static LinearLayout.LayoutParams matchWidth(int topMarginPx) {
        final LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = topMarginPx;
        return params;
    }

    /**
     * A slider over the steps: the value written above a rounded track (filled in the accent up to a
     * round knob). A finger anywhere on it takes the knob there; `released` runs when it lets go.
     */
    static final class Slider extends View {
        interface Listener {
            void changed(int step);
            void released(int step);
        }

        private final int steps;
        private int step;
        private String label = "";
        private boolean held;
        private Listener listener;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final float grab;

        Slider(Context context, int steps, int step) {
            super(context);
            this.steps = Math.max(steps, 1);
            this.step = Math.max(0, Math.min(step, this.steps));
            grab = dp(context, 24);  // a wide handle, easy to find and hold with a thumb
            paint.setTextSize(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, 13,
                    context.getResources().getDisplayMetrics()));
            paint.setTextAlign(Paint.Align.CENTER);
        }

        void setListener(Listener listener) { this.listener = listener; }

        void setLabel(String value) {
            label = value;
            invalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            final float w = getWidth(), h = getHeight();
            // The value in the upper part, the track and knob in the lower part.
            final float knobR = Math.min(grab / 2.4f, h / 4.2f);
            final float trackY = h - knobR - 2, trackH = Math.max(4f, knobR * 0.55f);
            final float left = knobR, right = w - knobR;
            final float x = left + (right - left) * step / steps;
            paint.setColor(RAISED);
            canvas.drawRoundRect(left, trackY - trackH / 2, right, trackY + trackH / 2, trackH, trackH, paint);
            paint.setColor(held ? ACCENT_PRESSED : ACCENT);
            canvas.drawRoundRect(left, trackY - trackH / 2, x, trackY + trackH / 2, trackH, trackH, paint);
            paint.setColor(Color.WHITE);
            canvas.drawCircle(x, trackY, held ? knobR * 1.12f : knobR, paint);
            paint.setColor(TEXT);
            final float textY = (trackY - knobR) / 2 - (paint.descent() + paint.ascent()) / 2;
            canvas.drawText(label, w / 2, textY, paint);
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            if (!isEnabled()) return false;
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    held = true;
                    getParent().requestDisallowInterceptTouchEvent(true);
                    // fall through: the press moves the grab as a drag does
                case MotionEvent.ACTION_MOVE: {
                    final float span = Math.max(getWidth() - grab, 1);
                    final int at = Math.max(0, Math.min(steps, Math.round((e.getX() - grab / 2) / span * steps)));
                    if (at != step) {
                        step = at;
                        if (listener != null) listener.changed(at);
                    }
                    invalidate();
                    return true;
                }
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    held = false;
                    invalidate();
                    // Posted like a click: the listener may rebuild the menu (removeAllViews), and doing
                    // that inside this touch dispatch crashed the next draw (NullPointerException in
                    // ViewGroup.dispatchDraw, tester video 2026-11-07, reproduced on a Redmi).
                    if (listener != null) {
                        final Listener l = listener;
                        final int picked = step;
                        post(() -> l.released(picked));
                    }
                    return true;
                default:
                    return true;
            }
        }
    }

    /** Children left to right, starting a new line when the next one does not fit. */
    static final class FlowLayout extends ViewGroup {
        private final int gap;

        FlowLayout(Context context, int gap) {
            super(context);
            this.gap = gap;
        }

        @Override
        protected void onMeasure(int widthSpec, int heightSpec) {
            final int max = MeasureSpec.getSize(widthSpec) - getPaddingLeft() - getPaddingRight();
            final boolean bounded = MeasureSpec.getMode(widthSpec) != MeasureSpec.UNSPECIFIED;
            int x = 0, y = 0, lineH = 0, widest = 0;
            for (int i = 0; i < getChildCount(); ++i) {
                final View c = getChildAt(i);
                if (c.getVisibility() == GONE) continue;
                c.measure(MeasureSpec.makeMeasureSpec(bounded ? max : 0,
                                bounded ? MeasureSpec.AT_MOST : MeasureSpec.UNSPECIFIED),
                        MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED));
                if (x > 0 && bounded && x + c.getMeasuredWidth() > max) {
                    x = 0;
                    y += lineH + gap;
                    lineH = 0;
                }
                x += c.getMeasuredWidth();
                widest = Math.max(widest, x);
                x += gap;
                lineH = Math.max(lineH, c.getMeasuredHeight());
            }
            final int w = bounded ? MeasureSpec.getSize(widthSpec) : widest + getPaddingLeft() + getPaddingRight();
            setMeasuredDimension(w, resolveSize(y + lineH + getPaddingTop() + getPaddingBottom(), heightSpec));
        }

        @Override
        protected void onLayout(boolean changed, int l, int t, int r, int b) {
            final int max = r - l - getPaddingRight();
            int x = getPaddingLeft(), y = getPaddingTop(), lineH = 0;
            for (int i = 0; i < getChildCount(); ++i) {
                final View c = getChildAt(i);
                if (c.getVisibility() == GONE) continue;
                final int cw = c.getMeasuredWidth(), ch = c.getMeasuredHeight();
                if (x > getPaddingLeft() && x + cw > max) {
                    x = getPaddingLeft();
                    y += lineH + gap;
                    lineH = 0;
                }
                c.layout(x, y, x + cw, y + ch);
                x += cw + gap;
                lineH = Math.max(lineH, ch);
            }
        }
    }
}
