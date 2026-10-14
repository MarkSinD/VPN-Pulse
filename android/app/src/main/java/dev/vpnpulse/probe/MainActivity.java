package dev.vpnpulse.probe;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.res.Configuration;
import android.graphics.Insets;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.inputmethod.InputMethodManager;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Э1 — enrolment: the shell and the four screens that end with a phone ready to check the mobile
 * network from Russia. The composition is the approved prototype's (docs/prototypes/android.html,
 * built from web/src/android.css and web/src/android.js): a quiet app bar, the step's body in the
 * middle, the buttons docked at the bottom, and from the third screen on the ring in the centre.
 *
 * Nothing here talks to the network. The two places where R-20b will — the enrolment code and the
 * route check — are the stub methods at the end of this file, and they behave exactly as the
 * prototype's fixtures do: a code of eight characters or more is accepted, the route check answers
 * after about 1.2 s.
 */
public class MainActivity extends Activity implements Onboarding.Host {

    private static final String TAG = "vpnpulse";
    /** The prototype's rule for the mock: S.code.trim().length >= 8. */
    private static final int CODE_MIN_LENGTH = 8;
    /** The prototype's setTimeout(..., 1200) for the route check. */
    private static final long ROUTE_CHECK_MS = 1200L;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable routeChecked = new Runnable() {
        @Override
        public void run() {
            onRouteCheckFinished();
        }
    };

    private Flow flow = new Flow();
    private Text text;
    /** An OnBackInvokedCallback on API 33 and up; untyped so older systems never load the class. */
    private Object backCallback;
    private boolean backRegistered;

    private LinearLayout bar;
    private LinearLayout steps;
    private LinearLayout content;
    private View dockLine;
    private LinearLayout dock;
    private EditText codeField;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        try {
            requestWindowFeature(Window.FEATURE_NO_TITLE);
        } catch (Throwable themeKeepsItsTitle) {
            Log.d(TAG, "no-title feature refused by the theme", themeKeepsItsTitle);
        }
        if (getActionBar() != null) {
            getActionBar().hide();
        }
        flow = Flow.restore(saved);
        buildShell();
        render();
        // a check interrupted by a rotation or a process restart is asked again, not forgotten
        if (flow.step == Step.CELLULAR && flow.cellular == CellularState.CHECKING) {
            startRouteCheck();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        flow.save(out);
    }

    /**
     * The manifest keeps this activity alive through a rotation, a resize and a switch between
     * light and dark (android:configChanges). Nothing of the flow is lost that way, but every
     * view here was built with the colours and the metrics of the configuration that has just
     * been replaced, so the tree is built again from the new one.
     */
    @Override
    public void onConfigurationChanged(Configuration now) {
        super.onConfigurationChanged(now);
        if (flow.lang == null) {
            text = null;   // still following the system, and the system may have changed language
        }
        buildShell();
        render();
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacks(routeChecked);
        super.onDestroy();
    }

    /** The path the system takes when the manifest has not opted into predictive back. */
    @Override
    public void onBackPressed() {
        if (flow.step.previous() == null) {
            super.onBackPressed();
        } else {
            goBack();
        }
    }

    /**
     * And the path it takes when the manifest has. The callback is registered only while there is
     * a step to go back to, so the first screen still closes the app. Its class is touched inside
     * the version check alone, which keeps it off the ground on anything older than 33.
     */
    private void syncPredictiveBack() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return;
        }
        boolean wanted = flow.step.previous() != null;
        if (wanted == backRegistered) {
            return;
        }
        if (backCallback == null) {
            backCallback = new OnBackInvokedCallback() {
                @Override
                public void onBackInvoked() {
                    goBack();
                }
            };
        }
        OnBackInvokedCallback callback = (OnBackInvokedCallback) backCallback;
        if (wanted) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback);
        } else {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(callback);
        }
        backRegistered = wanted;
    }

    // ---------- the shell ----------

    private void buildShell() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(getColor(R.color.color_bg));
        fitSystemBars(root);
        // .device { max-width: 480px; margin: 0 auto }: on a wide screen the margins grow instead
        // of the lines, so the measure stays readable
        int side = Views.px(this, R.dimen.space_4) + Views.gutter(this);

        bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(side - Views.px(this, R.dimen.space_1), Views.px(this, R.dimen.space_1),
                side - Views.px(this, R.dimen.space_1), Views.px(this, R.dimen.space_1));
        // the prototype's 56 px app bar: a 44 dp control with a little air around it
        bar.setMinimumHeight(Views.px(this, R.dimen.control_min) + Views.px(this, R.dimen.space_3));
        root.addView(bar, new LinearLayout.LayoutParams(Views.MATCH, Views.WRAP));

        // the step bar: navigation, so it stays put under the title instead of travelling with
        // the content whenever the step's block is centred
        steps = Views.column(this);
        steps.setPadding(side, 0, side, Views.px(this, R.dimen.space_2));
        root.addView(steps, new LinearLayout.LayoutParams(Views.MATCH, Views.WRAP));

        content = Views.column(this);
        content.setPadding(side, Views.px(this, R.dimen.space_3), side, Views.px(this, R.dimen.space_4));
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);     // so a short step can be centred on its ring
        scroll.setVerticalScrollBarEnabled(false);
        scroll.addView(content, new ScrollView.LayoutParams(Views.MATCH, Views.WRAP));
        root.addView(scroll, new LinearLayout.LayoutParams(Views.MATCH, 0, 1f));

        dockLine = Views.divider(this);
        root.addView(dockLine, new LinearLayout.LayoutParams(Views.MATCH, Views.hairline(this)));

        dock = Views.column(this);
        dock.setPadding(side, Views.px(this, R.dimen.space_3), side, Views.px(this, R.dimen.space_4));
        root.addView(dock, new LinearLayout.LayoutParams(Views.MATCH, Views.WRAP));

        setContentView(root);
    }

    /** targetSdk 35 draws edge to edge: keep the bar and the dock out from under the system's own. */
    private void fitSystemBars(View root) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            root.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
                @Override
                public WindowInsets onApplyWindowInsets(View v, WindowInsets insets) {
                    Insets bars = insets.getInsets(
                            WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                    Insets keyboard = insets.getInsets(WindowInsets.Type.ime());
                    v.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, keyboard.bottom));
                    return insets;
                }
            });
        } else {
            root.setFitsSystemWindows(true);
        }
    }

    private void render() {
        if (text == null || (flow.lang != null && !flow.lang.equals(text.lang()))) {
            text = Text.of(this, flow.lang);
        }
        renderBar();
        steps.removeAllViews();
        steps.addView(new StepBar(this, text, flow.step),
                new LinearLayout.LayoutParams(Views.MATCH, Views.WRAP));
        content.removeAllViews();
        dock.removeAllViews();
        // every step centres its block in what the bar and the dock leave: the free space is then
        // split evenly instead of showing up as one half-screen hole
        content.setGravity(Gravity.CENTER_VERTICAL);
        codeField = Onboarding.build(this, this, flow, content, dock);
        boolean docked = dock.getChildCount() > 0;
        dock.setVisibility(docked ? View.VISIBLE : View.GONE);
        dockLine.setVisibility(docked ? View.VISIBLE : View.GONE);
        syncPredictiveBack();
        if (flow.step != Step.BIND) {
            hideKeyboard();
        }
    }

    private void renderBar() {
        bar.removeAllViews();
        View back = Views.iconButton(this, GlyphDrawable.Glyph.BACK, text.get(R.string.action_back),
                new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        goBack();
                    }
                });
        back.setVisibility(flow.step.previous() == null ? View.INVISIBLE : View.VISIBLE);
        int control = Views.px(this, R.dimen.control_min);
        bar.addView(back, new LinearLayout.LayoutParams(control, control));

        LinearLayout title = Views.column(this);
        title.setGravity(Gravity.CENTER);
        TextView name = Views.text(this, text.get(R.string.android_title), R.dimen.text_md,
                R.color.color_text, true, Views.LH_TIGHT);
        name.setGravity(Gravity.CENTER);
        TextView what = Views.text(this, text.get(R.string.android_subtitle), R.dimen.text_xs,
                R.color.color_muted, false, Views.LH_CAPTION);
        what.setGravity(Gravity.CENTER);
        Views.add(title, name, 0);
        Views.add(title, what, 0);
        Views.heading(title);
        LinearLayout.LayoutParams titleParams = new LinearLayout.LayoutParams(0, Views.WRAP, 1f);
        titleParams.setMarginStart(Views.px(this, R.dimen.space_2));
        titleParams.setMarginEnd(Views.px(this, R.dimen.space_2));
        bar.addView(title, titleParams);

        bar.addView(Views.languageButton(this, text, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                flow.lang = text.other();
                render();
            }
        }));
    }

    private void goBack() {
        Step previous = flow.step.previous();
        if (previous == null) {
            return;
        }
        cancelRouteCheck();
        if (previous == Step.CELLULAR) {
            flow.cellular = CellularState.OK;   // the route was confirmed to get past that step
        }
        flow.step = previous;
        flow.codeError = false;
        render();
    }

    private void hideKeyboard() {
        InputMethodManager imm = getSystemService(InputMethodManager.class);
        View focused = getCurrentFocus();
        if (imm != null && focused != null) {
            imm.hideSoftInputFromWindow(focused.getWindowToken(), 0);
        }
    }

    // ---------- what the screens ask for ----------

    @Override
    public Text text() {
        return text;
    }

    @Override
    public void onCodeTyped(String code) {
        flow.code = code;   // kept live so a rotation never loses a half-typed code
    }

    @Override
    public void onBind() {
        boolean accepted = submitEnrolmentCode(flow.code);
        flow.codeError = !accepted;
        if (accepted) {
            flow.step = Step.EXCLUDE;
            render();
            return;
        }
        render();
        if (codeField != null) {
            codeField.requestFocus();
            codeField.setSelection(codeField.getText().length());
            codeField.announceForAccessibility(text.get(R.string.android_bind_error));
        }
    }

    @Override
    public void onExcluded() {
        flow.step = Step.CELLULAR;
        flow.cellular = CellularState.CHECKING;
        render();
        startRouteCheck();
    }

    @Override
    public void onRetry() {
        flow.cellular = CellularState.CHECKING;
        render();
        startRouteCheck();
    }

    @Override
    public void onCellularConfirmed() {
        cancelRouteCheck();
        flow.step = Step.DONE;
        render();
    }

    @Override
    public void onOpenSettings() {
        openNetworkSettings();
    }

    @Override
    public void onStartProbe() {
        startProbe();
    }

    @Override
    public void onCycleCellular() {
        // The web mock has a state selector so the owner can look at every answer; on the phone the
        // same thing is a long press on the ring. It only changes what is drawn. Landing back on
        // "checking" leaves the dashes turning on purpose — nothing is scheduled.
        cancelRouteCheck();
        flow.cellular = flow.cellular.following();
        render();
    }

    // ---------- the two places R-20b will reach the outside world ----------

    /**
     * TODO(R-20b): send the code to the API (POST /api/android/enrol), keep the token it returns,
     * and report a refusal or an expiry separately. Until then the prototype's rule stands in:
     * anything of at least eight characters counts as a code.
     */
    private boolean submitEnrolmentCode(String typed) {
        return typed != null && typed.trim().length() >= CODE_MIN_LENGTH;
    }

    /**
     * TODO(R-20b): ask for the cellular network (requestNetwork(TRANSPORT_CELLULAR)), fetch the
     * control page bound to it and compare the egress address, as the R-19 spike does, then report
     * OK, FAIL or NO_SIM. Until then the answer arrives after about 1.2 s and is always OK, which
     * is what the prototype simulates.
     */
    private void startRouteCheck() {
        ui.removeCallbacks(routeChecked);
        ui.postDelayed(routeChecked, ROUTE_CHECK_MS);
    }

    private void cancelRouteCheck() {
        ui.removeCallbacks(routeChecked);
    }

    private void onRouteCheckFinished() {
        if (flow.step != Step.CELLULAR || flow.cellular != CellularState.CHECKING) {
            return;
        }
        flow.cellular = CellularState.OK;
        render();
    }

    /**
     * TODO(R-20b): hand over to the main screen — the ring as the control, the route line, the
     * sheet of results — and start the worker that checks on a schedule. Until Э2 exists, the
     * button says out loud what it will do.
     */
    private void startProbe() {
        Log.i(TAG, "start requested; the main screen arrives with Э2 (R-20b)");
        Toast.makeText(this, text.get(R.string.android_main_running), Toast.LENGTH_SHORT).show();
    }

    /** The system's own network settings: mobile data lives there, and so does the VPN switch. */
    private void openNetworkSettings() {
        try {
            startActivity(new Intent(Settings.ACTION_WIRELESS_SETTINGS));
        } catch (ActivityNotFoundException noWirelessScreen) {
            try {
                startActivity(new Intent(Settings.ACTION_SETTINGS));
            } catch (ActivityNotFoundException noSettingsAtAll) {
                Log.w(TAG, "no settings activity on this device", noSettingsAtAll);
            }
        }
    }
}
