package org.syncora.client;

import android.content.Context;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.view.SurfaceView;

import androidx.annotation.OptIn;
import androidx.media3.common.MediaItem;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.Player;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.exoplayer.DefaultLoadControl;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.rtsp.RtspMediaSource;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@OptIn(markerClass = UnstableApi.class)
final class DirectRtspPlayer {
    interface Listener {
        void onFirstFrame();
        void onError(String message);
    }

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService networkExecutor = Executors.newSingleThreadExecutor();
    private final Context context;
    private final SurfaceView surface;
    private final Listener listener;
    private ExoPlayer player;

    DirectRtspPlayer(Context context, SurfaceView surface, Listener listener) {
        this.context = context;
        this.surface = surface;
        this.listener = listener;
    }

    void connect(String serverUrl) {
        networkExecutor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(serverUrl + "/direct/start")
                        .openConnection();
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(15000);
                connection.setRequestMethod("POST");
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(0);
                if (connection.getResponseCode() != 200) {
                    throw new IllegalStateException("HTTP " + connection.getResponseCode());
                }
                StringBuilder response = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                        connection.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) response.append(line);
                }
                JSONObject info = new JSONObject(response.toString());
                URI base = URI.create(serverUrl);
                String host = base.getHost();
                if (host == null) throw new IllegalArgumentException("adresse du serveur invalide");
                if (host.contains(":")) host = "[" + host + "]";
                String rtspUrl = "rtsp://" + host + ":" + info.getInt("port") +
                        info.getString("path");
                mainHandler.post(() -> startPlayback(rtspUrl));
            } catch (Exception exception) {
                fail("Flux direct impossible : " + exception.getMessage());
            } finally {
                if (connection != null) connection.disconnect();
            }
        });
    }

    private void startPlayback(String rtspUrl) {
        DefaultLoadControl loadControl = new DefaultLoadControl.Builder()
                .setBufferDurationsMs(50, 100, 0, 0)
                .setPrioritizeTimeOverSizeThresholds(true)
                .build();
        player = new ExoPlayer.Builder(context)
                .setLoadControl(loadControl)
                .build();
        player.setVideoSurfaceView(surface);
        player.addListener(new Player.Listener() {
            @Override
            public void onRenderedFirstFrame() {
                listener.onFirstFrame();
            }

            @Override
            public void onPlayerError(PlaybackException error) {
                fail("Lecture RTSP impossible : " + error.getErrorCodeName());
            }
        });
        RtspMediaSource source = new RtspMediaSource.Factory()
                .setTimeoutMs(1500)
                .createMediaSource(MediaItem.fromUri(Uri.parse(rtspUrl)));
        player.setMediaSource(source);
        player.setPlayWhenReady(true);
        player.prepare();
    }

    private void fail(String message) {
        mainHandler.post(() -> listener.onError(message));
    }

    void release() {
        networkExecutor.shutdownNow();
        if (player != null) {
            player.release();
            player = null;
        }
    }
}
