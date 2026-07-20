package org.syncora.client;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String PREFS = "syncora";
    private static final String SERVER_KEY = "server_url";
    private final ExecutorService networkExecutor = Executors.newSingleThreadExecutor();
    private EditText address;
    private TextView status;
    private Button connect;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(createContent());
        connect.requestFocus();
    }

    private View createContent() {
        int padding = dp(32);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(padding, padding, padding, padding);
        root.setBackgroundColor(Color.rgb(8, 12, 20));

        TextView title = text(getString(R.string.app_name), 34, Color.WHITE);
        title.setGravity(Gravity.CENTER);
        root.addView(title, matchWrap());

        TextView subtitle = text(getString(R.string.slogan), 18, Color.rgb(150, 165, 190));
        subtitle.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subtitleParams = matchWrap();
        subtitleParams.setMargins(0, dp(8), 0, dp(32));
        root.addView(subtitle, subtitleParams);

        address = new EditText(this);
        address.setSingleLine(true);
        address.setTextColor(Color.WHITE);
        address.setHintTextColor(Color.rgb(120, 135, 160));
        address.setHint(R.string.address_hint);
        address.setText(getPreferences().getString(SERVER_KEY, "http://192.168.1.42:8080"));
        address.setImeOptions(EditorInfo.IME_ACTION_GO);
        address.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_GO ||
                    (event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER)) {
                checkServer();
                return true;
            }
            return false;
        });
        root.addView(address, new LinearLayout.LayoutParams(dp(520), dp(64)));

        connect = new Button(this);
        connect.setText(R.string.connect);
        connect.setTextSize(18);
        connect.setOnClickListener(view -> checkServer());
        LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(dp(260), dp(64));
        buttonParams.setMargins(0, dp(20), 0, 0);
        root.addView(connect, buttonParams);

        status = text(getString(R.string.ready), 16, Color.rgb(150, 165, 190));
        status.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams statusParams = matchWrap();
        statusParams.setMargins(0, dp(24), 0, 0);
        root.addView(status, statusParams);
        return root;
    }

    private void checkServer() {
        String baseUrl = normalize(address.getText().toString());
        address.setText(baseUrl);
        connect.setEnabled(false);
        status.setText(R.string.connecting);
        status.setTextColor(Color.rgb(150, 165, 190));

        networkExecutor.execute(() -> {
            String error = null;
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(baseUrl + "/health").openConnection();
                connection.setConnectTimeout(2500);
                connection.setReadTimeout(2500);
                connection.setRequestMethod("GET");
                if (connection.getResponseCode() != 200) {
                    error = getString(R.string.server_error, connection.getResponseCode());
                }
            } catch (IOException exception) {
                error = getString(R.string.unreachable);
            } finally {
                if (connection != null) connection.disconnect();
            }
            String result = error;
            runOnUiThread(() -> showResult(baseUrl, result));
        });
    }

    private void showResult(String baseUrl, String error) {
        connect.setEnabled(true);
        if (error == null) {
            getPreferences().edit().putString(SERVER_KEY, baseUrl).apply();
            status.setText(R.string.connected);
            status.setTextColor(Color.rgb(78, 220, 150));
        } else {
            status.setText(error);
            status.setTextColor(Color.rgb(255, 120, 120));
        }
    }

    private SharedPreferences getPreferences() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private String normalize(String raw) {
        String value = raw.trim();
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://" + value;
        }
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        return value;
    }

    private TextView text(String value, float size, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        return view;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onDestroy() {
        networkExecutor.shutdownNow();
        super.onDestroy();
    }
}
