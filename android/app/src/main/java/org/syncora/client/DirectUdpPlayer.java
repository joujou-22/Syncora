package org.syncora.client;

import android.media.MediaCodec;
import android.media.MediaFormat;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.SurfaceView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/** Minimal one-frame-queue H.264/RTP player for interactive LAN display. */
final class DirectUdpPlayer {
    interface Listener {
        void onFirstFrame();
        void onError(String message);
    }

    private static final int UDP_PORT = 5004;
    private static final int UDP_RECEIVE_BUFFER_BYTES = 64 * 1024;
    private static final String TAG = "SyncoraDirect";
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService controlExecutor = Executors.newSingleThreadExecutor();
    private final AtomicReference<byte[]> latestFrame = new AtomicReference<>();
    private final AtomicBoolean firstFrame = new AtomicBoolean(false);
    private final AtomicLong replacedFrames = new AtomicLong();
    private final AtomicLong codecInputDrops = new AtomicLong();
    private final AtomicBoolean metricsPending = new AtomicBoolean(false);
    private final SurfaceView surface;
    private final Listener listener;
    private volatile boolean running;
    private DatagramSocket socket;
    private Thread receiverThread;
    private Thread decoderThread;
    private volatile int width;
    private volatile int height;

    DirectUdpPlayer(SurfaceView surface, Listener listener) {
        this.surface = surface;
        this.listener = listener;
    }

    void connect(String serverUrl) {
        try {
            socket = new DatagramSocket(null);
            socket.setReuseAddress(true);
            // Keep only a few video frames in the kernel. A large UDP buffer
            // preserves obsolete packets and turns network jitter into latency.
            socket.setReceiveBufferSize(UDP_RECEIVE_BUFFER_BYTES);
            socket.bind(new InetSocketAddress(UDP_PORT));
            running = true;
            startReceiver(serverUrl);
        } catch (Exception exception) {
            fail("Port UDP indisponible : " + exception.getMessage());
            return;
        }

        controlExecutor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                JSONObject request = new JSONObject();
                request.put("port", UDP_PORT);
                byte[] body = request.toString().getBytes(StandardCharsets.UTF_8);
                connection = (HttpURLConnection) new URL(serverUrl + "/direct/start")
                        .openConnection();
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(15000);
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(body.length);
                try (OutputStream output = connection.getOutputStream()) { output.write(body); }
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
                width = info.getInt("width");
                height = info.getInt("height");
                startDecoder();
            } catch (Exception exception) {
                fail("Flux UDP impossible : " + exception.getMessage());
            } finally {
                if (connection != null) connection.disconnect();
            }
        });
    }

    private void startReceiver(String serverUrl) {
        receiverThread = new Thread(() -> {
            byte[] buffer = new byte[2048];
            DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
            RtpH264Assembler assembler = new RtpH264Assembler(frame -> {
                if (latestFrame.getAndSet(frame) != null) replacedFrames.incrementAndGet();
            });
            long nextReport = System.nanoTime() + 5_000_000_000L;
            while (running) {
                try {
                    packet.setLength(buffer.length);
                    socket.receive(packet);
                    assembler.accept(packet.getData(), packet.getLength());
                    if (System.nanoTime() >= nextReport) {
                        // Some Android TV firmwares discard application INFO logs.
                        Log.w(TAG, "rtp packets=" + assembler.packets()
                                + " missing=" + assembler.missingPackets()
                                + " frames=" + assembler.completedFrames()
                                + " damaged=" + assembler.damagedFrames()
                                + " replaced=" + replacedFrames.get()
                                + " codecDrops=" + codecInputDrops.get());
                        reportMetrics(serverUrl, assembler);
                        nextReport = System.nanoTime() + 5_000_000_000L;
                    }
                } catch (Exception exception) {
                    if (running) fail("Réception UDP arrêtée : " + exception.getMessage());
                    return;
                }
            }
        }, "syncora-udp-receiver");
        receiverThread.setPriority(Thread.MAX_PRIORITY);
        receiverThread.start();
    }

    private void reportMetrics(String serverUrl, RtpH264Assembler assembler) {
        if (!metricsPending.compareAndSet(false, true)) return;
        JSONObject metrics = new JSONObject();
        try {
            metrics.put("packets", assembler.packets());
            metrics.put("missing", assembler.missingPackets());
            metrics.put("frames", assembler.completedFrames());
            metrics.put("damaged", assembler.damagedFrames());
            metrics.put("replaced", replacedFrames.get());
            metrics.put("codec_drops", codecInputDrops.get());
        } catch (Exception ignored) {
            metricsPending.set(false);
            return;
        }
        controlExecutor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                byte[] body = metrics.toString().getBytes(StandardCharsets.UTF_8);
                connection = (HttpURLConnection) new URL(serverUrl + "/direct/metrics")
                        .openConnection();
                connection.setConnectTimeout(1000);
                connection.setReadTimeout(1000);
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(body.length);
                try (OutputStream output = connection.getOutputStream()) { output.write(body); }
                connection.getResponseCode();
            } catch (Exception ignored) {
                // Diagnostics must never interrupt video playback.
            } finally {
                if (connection != null) connection.disconnect();
                metricsPending.set(false);
            }
        });
    }

    private void startDecoder() {
        decoderThread = new Thread(this::decodeLoop, "syncora-h264-decoder");
        decoderThread.setPriority(Thread.MAX_PRIORITY);
        decoderThread.start();
    }

    private void decodeLoop() {
        MediaCodec codec = null;
        MediaCodec.BufferInfo outputInfo = new MediaCodec.BufferInfo();
        byte[] sps = null;
        byte[] pps = null;
        try {
            while (running) {
                byte[] frame = latestFrame.getAndSet(null);
                if (frame == null) {
                    Thread.sleep(1);
                    if (codec != null) drain(codec, outputInfo);
                    continue;
                }
                if (codec == null) {
                    byte[] candidate = findNal(frame, 7);
                    if (candidate != null) sps = candidate;
                    candidate = findNal(frame, 8);
                    if (candidate != null) pps = candidate;
                    if (sps == null || pps == null || !surface.getHolder().getSurface().isValid()) {
                        continue;
                    }
                    MediaFormat format = MediaFormat.createVideoFormat("video/avc", width, height);
                    format.setByteBuffer("csd-0", ByteBuffer.wrap(withStartCode(sps)));
                    format.setByteBuffer("csd-1", ByteBuffer.wrap(withStartCode(pps)));
                    format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 2 * 1024 * 1024);
                    format.setInteger(MediaFormat.KEY_PRIORITY, 0);
                    format.setFloat(MediaFormat.KEY_OPERATING_RATE, 60.0f);
                    codec = MediaCodec.createDecoderByType("video/avc");
                    codec.configure(format, surface.getHolder().getSurface(), null, 0);
                    codec.start();
                }
                int input = codec.dequeueInputBuffer(0);
                if (input >= 0) {
                    ByteBuffer target = codec.getInputBuffer(input);
                    if (target != null && target.capacity() >= frame.length) {
                        target.clear();
                        target.put(frame);
                        codec.queueInputBuffer(input, 0, frame.length,
                                System.nanoTime() / 1000, 0);
                    } else {
                        // Always return a dequeued buffer to MediaCodec, even when a
                        // corrupt or unexpectedly large access unit must be dropped.
                        codec.queueInputBuffer(input, 0, 0,
                                System.nanoTime() / 1000, 0);
                    }
                } else {
                    codecInputDrops.incrementAndGet();
                }
                drain(codec, outputInfo);
            }
        } catch (Exception exception) {
            if (running) fail("Décodage H.264 arrêté : " + exception.getMessage());
        } finally {
            if (codec != null) {
                try { codec.stop(); } catch (Exception ignored) { }
                codec.release();
            }
        }
    }

    private void drain(MediaCodec codec, MediaCodec.BufferInfo info) {
        int newest = -1;
        while (true) {
            int output = codec.dequeueOutputBuffer(info, 0);
            if (output < 0) break;
            if (newest >= 0) codec.releaseOutputBuffer(newest, false);
            newest = output;
        }
        if (newest >= 0) {
            codec.releaseOutputBuffer(newest, true);
            if (firstFrame.compareAndSet(false, true)) {
                mainHandler.post(listener::onFirstFrame);
            }
        }
    }

    private byte[] findNal(byte[] frame, int wantedType) {
        int offset = 0;
        while (offset + 5 <= frame.length) {
            int start = startCodeAt(frame, offset);
            if (start < 0) break;
            int nalStart = start + 4;
            int next = startCodeAt(frame, nalStart);
            if (next < 0) next = frame.length;
            if ((frame[nalStart] & 0x1f) == wantedType) {
                return Arrays.copyOfRange(frame, nalStart, next);
            }
            offset = next;
        }
        return null;
    }

    private int startCodeAt(byte[] data, int from) {
        for (int index = Math.max(0, from); index + 3 < data.length; index++) {
            if (data[index] == 0 && data[index + 1] == 0 &&
                    data[index + 2] == 0 && data[index + 3] == 1) return index;
        }
        return -1;
    }

    private byte[] withStartCode(byte[] nal) {
        byte[] result = new byte[nal.length + 4];
        result[3] = 1;
        System.arraycopy(nal, 0, result, 4, nal.length);
        return result;
    }

    private void fail(String message) {
        mainHandler.post(() -> listener.onError(message));
    }

    void release() {
        running = false;
        if (socket != null) socket.close();
        controlExecutor.shutdownNow();
        try {
            if (receiverThread != null) receiverThread.join(500);
            if (decoderThread != null) decoderThread.join(500);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }
}
