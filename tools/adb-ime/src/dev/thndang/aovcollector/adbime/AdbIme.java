package dev.thndang.aovcollector.adbime;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.inputmethodservice.InputMethodService;
import android.os.Build;
import android.util.Base64;
import android.view.View;
import android.view.inputmethod.InputConnection;

import java.nio.charset.StandardCharsets;

public class AdbIme extends InputMethodService {
    public static final String ACTION_INPUT = "dev.thndang.aovcollector.adbime.INPUT";
    public static final String EXTRA_B64 = "text_b64";

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (!ACTION_INPUT.equals(intent.getAction())) {
                return;
            }
            String encoded = intent.getStringExtra(EXTRA_B64);
            if (encoded == null) {
                return;
            }
            try {
                String text = new String(
                    Base64.decode(encoded, Base64.DEFAULT),
                    StandardCharsets.UTF_8
                );
                InputConnection connection = getCurrentInputConnection();
                if (connection != null) {
                    connection.commitText(text, 1);
                }
            } catch (Exception ignored) {
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        IntentFilter filter = new IntentFilter(ACTION_INPUT);
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED);
        } else {
            registerReceiver(receiver, filter);
        }
    }

    @Override
    public void onDestroy() {
        try {
            unregisterReceiver(receiver);
        } catch (Exception ignored) {
        }
        super.onDestroy();
    }

    @Override
    public View onCreateInputView() {
        return null;
    }

    @Override
    public boolean onEvaluateFullscreenMode() {
        return false;
    }
}
