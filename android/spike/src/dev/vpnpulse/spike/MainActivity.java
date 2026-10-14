package dev.vpnpulse.spike;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.HttpsURLConnection;

/** R-19 spike: does this app's socket really leave through mobile while Wi-Fi + VPN are up? */
public class MainActivity extends Activity {

    private static final String TAG = "vpnpulse-spike";
    private static final String TRACE = "https://1.1.1.1/cdn-cgi/trace";
    private static final String GEN204 = "https://www.gstatic.com/generate_204";
    private static final int HTTP_MS = 10000;
    private static final int CELL_MS = 15000;
    private static final String BAR = "========================================";

    private final Handler ui = new Handler(Looper.getMainLooper());
    private TextView out;
    private ScrollView scroll;
    private Button again;
    private volatile boolean busy;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        int pad = Math.round(8 * getResources().getDisplayMetrics().density);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        // targetSdk 35 draws edge to edge: keep the button out from under the status bar.
        root.setFitsSystemWindows(true);

        again = new Button(this);
        again.setText("Повторить");
        again.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { start(); }
        });
        root.addView(again, new LinearLayout.LayoutParams(-1, -2));

        out = new TextView(this);
        out.setTypeface(Typeface.MONOSPACE);
        out.setTextSize(12);
        out.setTextColor(Color.BLACK);
        out.setTextIsSelectable(true);
        scroll = new ScrollView(this);
        scroll.setPadding(pad, pad, pad, pad);
        scroll.addView(out, new ScrollView.LayoutParams(-1, -2));
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1f));

        setContentView(root);
        start();
    }

    private void start() {
        if (busy) return;
        busy = true;
        again.setEnabled(false);
        out.setText("");
        new Thread(new Runnable() { @Override public void run() { work(); } }, "spike").start();
    }

    /** The whole test. Runs on a background thread; every line is posted back to the UI. */
    private void work() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        ConnectivityManager.NetworkCallback cb = null;
        Network cell = null;
        String defIp = null, cellIp = null, why = "причина не установлена";
        boolean defaultIsVpn = false, defaultIsCellular = false;
        boolean cellOk = false, cellClean = false;
        try {
            try {
                log("1. Окружение: Android " + Build.VERSION.RELEASE + ", SDK " + Build.VERSION.SDK_INT);
                Network active = cm.getActiveNetwork();
                NetworkCapabilities nc = active == null ? null : cm.getNetworkCapabilities(active);
                LinkProperties lp = active == null ? null : cm.getLinkProperties(active);
                boolean vpn = nc != null && nc.hasTransport(NetworkCapabilities.TRANSPORT_VPN);
                defaultIsVpn = vpn;
                defaultIsCellular = nc != null && nc.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) && !vpn;
                log("   VPN на активной сети: " + (vpn ? "ДА" : "нет (приложение вне туннеля)"));
                log("   активная сеть: транспорты=" + transports(nc) + ", интерфейс=" + iface(lp));
            } catch (Throwable t) {
                log("1. Окружение: ошибка " + err(t));
            }

            try {
                long t0 = now();
                defIp = traceIp(http(null, TRACE)[1]);
                log("2. Сеть по умолчанию — виден снаружи как: " + defIp + " (" + (now() - t0) + " мс)");
            } catch (Throwable t) {
                log("2. Сеть по умолчанию: ошибка " + err(t));
                why = "не удалось узнать адрес выхода сети по умолчанию: " + err(t);
            }

            final ArrayBlockingQueue<Object> box = new ArrayBlockingQueue<Object>(1);
            try {
                NetworkRequest req = new NetworkRequest.Builder()
                        .addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR)
                        .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                        .build();
                cb = new ConnectivityManager.NetworkCallback() {
                    @Override public void onAvailable(Network n) { box.offer(n); }
                    @Override public void onUnavailable() { box.offer("unavailable"); }
                };
                log("3. Запрашиваю мобильную сеть, таймаут " + (CELL_MS / 1000) + " с ...");
                cm.requestNetwork(req, cb, CELL_MS);
                Object got = box.poll(CELL_MS + 3000L, TimeUnit.MILLISECONDS);
                if (got instanceof Network) {
                    cell = (Network) got;
                    log("   мобильная сеть получена");
                } else {
                    log("   нет мобильного интернета");
                    why = "нет мобильного интернета (нет SIM или мобильные данные выключены) — это нет данных, а не поломка";
                }
            } catch (Throwable t) {
                log("3. Запрос мобильной сети: ошибка " + err(t));
                why = "запрос мобильной сети не удался: " + err(t);
            }

            if (cell != null) {
                try {
                    NetworkCapabilities nc = cm.getNetworkCapabilities(cell);
                    LinkProperties lp = cm.getLinkProperties(cell);
                    boolean notVpn = nc != null && nc.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN);
                    cellClean = nc != null && nc.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) && notVpn;
                    log("4. Мобильная сеть: транспорты=" + transports(nc) + ", интерфейс=" + iface(lp));
                    log("   NET_CAPABILITY_NOT_VPN: " + (notVpn ? "да" : "нет"));
                    if (!cellClean) why = "у полученной сети нет CELLULAR и/или NOT_VPN";
                } catch (Throwable t) {
                    log("4. Свойства мобильной сети: ошибка " + err(t));
                }

                try {
                    long t0 = now();
                    InetAddress[] addrs = cell.getAllByName("www.gstatic.com");
                    int n = addrs == null ? 0 : addrs.length;
                    log("5. DNS через мобильную сеть: " + n + " адрес(ов) за " + (now() - t0) + " мс");
                } catch (Throwable t) {
                    log("5. DNS через мобильную сеть: ошибка " + err(t));
                }

                try {
                    long t0 = now();
                    cellIp = traceIp(http(cell, TRACE)[1]);
                    cellOk = true;
                    log("6. Через мобильную сеть — виден снаружи как: " + cellIp + " (" + (now() - t0) + " мс)");
                } catch (Throwable t) {
                    log("6. HTTPS через мобильную сеть: ошибка " + err(t));
                    why = "HTTPS через мобильную сеть не удался: " + err(t);
                }

                try {
                    long t0 = now();
                    String code = http(cell, GEN204)[0];
                    log("   generate_204 через мобильную сеть: код " + code + " за " + (now() - t0) + " мс");
                } catch (Throwable t) {
                    log("   generate_204 через мобильную сеть: ошибка " + err(t));
                }
            }

            raw("");
            log("   случай: сеть по умолчанию " + (defaultIsVpn ? "в туннеле (приложение НЕ исключено)"
                    : defaultIsCellular ? "мобильная вне туннеля (приложение исключено, Wi-Fi выключен)"
                    : "не мобильная и не VPN (вероятно Wi-Fi, приложение исключено)"));
            raw(BAR);
            boolean sameIp = defIp != null && cellIp != null && cellIp.equals(defIp);
            if (cellOk && cellClean && (!sameIp || !defaultIsVpn)) {
                raw("   МАРШРУТ ПОДТВЕРЖДЁН");
                raw("   сокеты уходят в мобильную сеть мимо VPN");
                if (sameIp) {
                    raw("   приложение исключено из VPN целиком: обе проверки видны как " + cellIp);
                    raw("   (у приложения вне туннеля сеть по умолчанию — та же мобильная)");
                } else {
                    raw("   адрес выхода: " + defIp + " (по умолчанию) -> " + cellIp + " (мобильная)");
                }
                raw("   совет: так и нужно — ничего менять не надо.");
            } else if (sameIp && defaultIsVpn) {
                raw("   ИДЁТ ЧЕРЕЗ VPN");
                raw("   адрес выхода одинаковый (" + defIp + ") — сокет перехватил VPN");
                raw("   совет: в Amnezia -> Split App Tunneling добавьте это приложение в список"
                        + " приложений, работающих без VPN, и переподключите Amnezia.");
            } else {
                raw("   НЕ УДАЛОСЬ ПРОВЕРИТЬ");
                raw("   причина: " + why);
                raw("   совет: включите мобильные данные при включённом Wi-Fi и нажмите «Повторить».");
            }
            raw(BAR);
        } catch (Throwable t) {
            log("Прогон прерван: " + err(t));
        } finally {
            if (cb != null) {
                try { cm.unregisterNetworkCallback(cb); } catch (Throwable ignored) { }
            }
            busy = false;
            ui.post(new Runnable() { @Override public void run() { again.setEnabled(true); } });
        }
    }

    /** GET over the given network (null = default network). Returns {http code, body}. */
    private String[] http(Network net, String spec) throws Exception {
        URL url = new URL(spec);
        HttpsURLConnection c = (HttpsURLConnection)
                (net == null ? url.openConnection() : net.openConnection(url));
        try {
            c.setConnectTimeout(HTTP_MS);
            c.setReadTimeout(HTTP_MS);
            c.setRequestMethod("GET");
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(false);
            int code = c.getResponseCode();
            StringBuilder body = new StringBuilder();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            if (in != null) {
                BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"));
                String line;
                while ((line = r.readLine()) != null) body.append(line).append('\n');
                r.close();
            }
            return new String[] { String.valueOf(code), body.toString() };
        } finally {
            c.disconnect();
        }
    }

    private static String traceIp(String body) throws Exception {
        for (String line : body.split("\n")) {
            if (line.startsWith("ip=")) return line.substring(3).trim();
        }
        throw new IllegalStateException("в ответе нет строки ip=");
    }

    private static String transports(NetworkCapabilities nc) {
        if (nc == null) return "нет данных";
        int[] ids = { NetworkCapabilities.TRANSPORT_CELLULAR, NetworkCapabilities.TRANSPORT_WIFI,
                NetworkCapabilities.TRANSPORT_ETHERNET, NetworkCapabilities.TRANSPORT_VPN,
                NetworkCapabilities.TRANSPORT_BLUETOOTH };
        String[] names = { "CELLULAR", "WIFI", "ETHERNET", "VPN", "BLUETOOTH" };
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < ids.length; i++) {
            if (nc.hasTransport(ids[i])) {
                if (sb.length() > 0) sb.append('+');
                sb.append(names[i]);
            }
        }
        return sb.length() == 0 ? "нет" : sb.toString();
    }

    private static String iface(LinkProperties lp) {
        String name = lp == null ? null : lp.getInterfaceName();
        return name == null ? "неизвестен" : name;
    }

    private static String err(Throwable t) { return t.getClass().getSimpleName() + ": " + t.getMessage(); }

    private static long now() { return System.currentTimeMillis(); }

    private void log(String s) {
        raw(new SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date()) + "  " + s);
    }

    private void raw(String s) {
        final String line = s;
        Log.i(TAG, line);
        ui.post(new Runnable() {
            @Override public void run() {
                out.append(line + "\n");
                scroll.post(new Runnable() {
                    @Override public void run() { scroll.fullScroll(View.FOCUS_DOWN); }
                });
            }
        });
    }
}
