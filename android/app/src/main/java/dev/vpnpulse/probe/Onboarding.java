package dev.vpnpulse.probe;

import android.app.Activity;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * The four screens of Э1, built the way the approved prototype builds them (the onboarding(),
 * ring() and stepper() functions of web/src/android.js): a step bar at the top, the step's own
 * body, and the buttons docked at the bottom edge where a thumb reaches them.
 *
 * This class only draws. Every decision — is the code good, did the route check pass, where does
 * "back" lead — belongs to the host, so the flow lives in one place and the screens stay dumb.
 */
final class Onboarding {

    /**
     * The shape of an enrolment code, not a word: the same eight characters and a dash in every
     * language, which is why it is written here and not in the dictionaries.
     */
    private static final String CODE_MASK = "XXXX-XXXX";

    private Onboarding() {
    }

    interface Host {
        Text text();

        void onCodeTyped(String code);

        void onBind();

        void onExcluded();

        void onRetry();

        void onOpenSettings();

        void onCellularConfirmed();

        void onStartProbe();

        /** Review hook: the prototype has a state selector, the app has a long press on the ring. */
        void onCycleCellular();
    }

    /** @return the code field when the step has one, so the host can put the cursor back in it. */
    static EditText build(Activity a, Host host, Flow flow, LinearLayout content, LinearLayout dock) {
        int gap = Views.px(a, flow.isStage() ? R.dimen.space_5 : R.dimen.space_4);
        Views.add(content, new StepBar(a, host.text(), flow.step), 0);
        switch (flow.step) {
            case BIND:
                return bind(a, host, flow, content, dock, gap);
            case EXCLUDE:
                exclude(a, host, content, dock, gap);
                return null;
            case CELLULAR:
                cellular(a, host, flow, content, dock, gap);
                return null;
            default:
                done(a, host, content, dock, gap);
                return null;
        }
    }

    // ---------- 1. the code from the Mini App ----------

    private static EditText bind(final Activity a, final Host host, Flow flow,
                                 LinearLayout content, LinearLayout dock, int gap) {
        Text t = host.text();
        LinearLayout body = Views.column(a);
        Views.add(body, Views.heading(a, t.get(R.string.android_bind_title)), 0);
        Views.add(body, Views.muted(a, t.get(R.string.android_bind_body)), Views.px(a, R.dimen.space_3));

        String message = flow.codeError ? t.get(R.string.android_bind_error) : null;
        LinearLayout field = Views.column(a);
        TextView label = Views.label(a, t.get(R.string.android_bind_code));
        EditText code = Views.codeField(a, flow.code, CODE_MASK, message);
        label.setLabelFor(code.getId());
        Views.add(field, label, 0);
        Views.add(field, code, Views.px(a, R.dimen.space_1));
        if (message != null) {
            Views.add(field, Views.error(a, message), Views.px(a, R.dimen.space_1));
        }
        Views.add(body, field, Views.px(a, R.dimen.space_3));
        Views.add(content, body, gap);

        Views.onTextChanged(code, new Views.Typed() {
            @Override
            public void onTyped(String value) {
                host.onCodeTyped(value);
            }
        });
        code.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView v, int actionId, KeyEvent event) {
                if (actionId == EditorInfo.IME_ACTION_DONE) {
                    host.onBind();
                    return true;
                }
                return false;
            }
        });
        Views.add(dock, Views.primary(a, t.get(R.string.android_bind_action), null, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                host.onBind();
            }
        }), 0);
        return code;
    }

    // ---------- 2. let the probe out of the tunnel ----------

    private static void exclude(final Activity a, final Host host, LinearLayout content,
                                LinearLayout dock, int gap) {
        Text t = host.text();
        LinearLayout body = Views.column(a);
        Views.add(body, Views.heading(a, t.get(R.string.android_exclude)), 0);
        Views.add(body, Views.body(a, t.get(R.string.android_exclude_body)), Views.px(a, R.dimen.space_3));
        Views.add(body, Views.note(a, t.get(R.string.android_exclude_why)), Views.px(a, R.dimen.space_3));
        Views.add(content, body, gap);

        Views.add(dock, Views.primary(a, t.get(R.string.android_exclude_confirm),
                GlyphDrawable.Glyph.CHECK, new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        host.onExcluded();
                    }
                }), 0);
    }

    // ---------- 3. does the check really leave through the mobile network ----------

    private static void cellular(final Activity a, final Host host, Flow flow,
                                 LinearLayout content, LinearLayout dock, int gap) {
        Text t = host.text();
        CellularState cell = flow.cellular;
        String title = t.get(cell.titleRes);
        String caption = cell.captionRes == 0 ? null : t.get(cell.captionRes);

        LinearLayout hero = Views.column(a);
        hero.setGravity(Gravity.CENTER_HORIZONTAL);
        RingView ring = new RingView(a);
        ring.show(cell.ring, title, caption, cell.busy);
        ring.setContentDescription(caption == null ? title : title + ". " + caption);
        ring.setOnLongClickListener(new View.OnLongClickListener() {
            @Override
            public boolean onLongClick(View v) {
                host.onCycleCellular();
                return true;
            }
        });
        Views.addCentered(hero, ring, 0);

        TextView hint = Views.note(a, t.get(cell.hintRes));
        hint.setGravity(Gravity.CENTER_HORIZONTAL);
        Views.add(hero, hint, Views.px(a, R.dimen.space_4));
        Views.add(content, hero, gap);

        if (cell == CellularState.OK) {
            Views.add(dock, Views.primary(a, t.get(R.string.android_step_done), null,
                    new View.OnClickListener() {
                        @Override
                        public void onClick(View v) {
                            host.onCellularConfirmed();
                        }
                    }), 0);
            return;
        }
        if (cell == CellularState.CHECKING) {
            return;   // nothing to press while the check is running, as in the prototype
        }
        Views.add(dock, Views.primary(a, t.get(R.string.android_cellular_retry),
                GlyphDrawable.Glyph.REFRESH, new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        host.onRetry();
                    }
                }), 0);
        if (cell == CellularState.FAIL) {
            Views.add(dock, Views.outline(a, t.get(R.string.android_permission_action),
                    GlyphDrawable.Glyph.SETTINGS, new View.OnClickListener() {
                        @Override
                        public void onClick(View v) {
                            host.onOpenSettings();
                        }
                    }), Views.px(a, R.dimen.space_2));
        }
    }

    // ---------- 4. enrolled ----------

    private static void done(final Activity a, final Host host, LinearLayout content,
                             LinearLayout dock, int gap) {
        Text t = host.text();
        CellularState confirmed = CellularState.OK;
        String title = t.get(confirmed.titleRes);
        String caption = t.get(confirmed.captionRes);

        LinearLayout hero = Views.column(a);
        hero.setGravity(Gravity.CENTER_HORIZONTAL);
        RingView ring = new RingView(a);
        ring.show(confirmed.ring, title, caption, false);
        ring.setContentDescription(title + ". " + caption);
        Views.addCentered(hero, ring, 0);
        Views.add(content, hero, gap);

        LinearLayout body = Views.column(a);
        Views.add(body, Views.heading(a, t.get(R.string.android_step_done)), 0);
        Views.add(body, Views.muted(a, t.get(R.string.android_done_body)), Views.px(a, R.dimen.space_3));
        Views.add(body, Views.panel(a, GlyphDrawable.Glyph.PC, t.get(R.string.android_pcchecksvpn)),
                Views.px(a, R.dimen.space_3));
        Views.add(content, body, gap);

        Views.add(dock, Views.primary(a, t.get(R.string.android_start),
                GlyphDrawable.Glyph.PLAY, new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        host.onStartProbe();
                    }
                }), 0);
    }
}
