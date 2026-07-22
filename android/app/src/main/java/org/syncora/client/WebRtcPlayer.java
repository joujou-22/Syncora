package org.syncora.client;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;
import org.webrtc.AudioTrack;
import org.webrtc.DefaultVideoDecoderFactory;
import org.webrtc.EglBase;
import org.webrtc.MediaConstraints;
import org.webrtc.MediaStreamTrack;
import org.webrtc.PeerConnection;
import org.webrtc.PeerConnectionFactory;
import org.webrtc.RtpReceiver;
import org.webrtc.RtpTransceiver;
import org.webrtc.SessionDescription;
import org.webrtc.SurfaceViewRenderer;
import org.webrtc.VideoTrack;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

final class WebRtcPlayer {
    interface Listener {
        void onConnected();
        void onError(String message);
    }

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService signalingExecutor = Executors.newSingleThreadExecutor();
    private final SurfaceViewRenderer renderer;
    private final Listener listener;
    private final EglBase eglBase;
    private final PeerConnectionFactory factory;
    private final AtomicBoolean offerSent = new AtomicBoolean(false);
    private PeerConnection peer;
    private String serverUrl;

    WebRtcPlayer(Context context, SurfaceViewRenderer renderer, Listener listener) {
        this.renderer = renderer;
        this.listener = listener;
        PeerConnectionFactory.initialize(
                PeerConnectionFactory.InitializationOptions.builder(context)
                        .createInitializationOptions()
        );
        eglBase = EglBase.create();
        renderer.init(eglBase.getEglBaseContext(), null);
        renderer.setEnableHardwareScaler(true);
        renderer.setMirror(false);
        factory = PeerConnectionFactory.builder()
                .setVideoDecoderFactory(new DefaultVideoDecoderFactory(eglBase.getEglBaseContext()))
                .createPeerConnectionFactory();
    }

    void connect(String serverUrl) {
        this.serverUrl = serverUrl;
        PeerConnection.RTCConfiguration configuration =
                new PeerConnection.RTCConfiguration(Collections.emptyList());
        configuration.sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN;
        configuration.audioJitterBufferMaxPackets = 20;
        configuration.audioJitterBufferFastAccelerate = true;
        configuration.disableIPv6OnWifi = true;
        peer = factory.createPeerConnection(configuration, new SimplePeerObserver() {
            @Override
            public void onIceGatheringChange(PeerConnection.IceGatheringState state) {
                // Some 32-bit Android 9 WebRTC builds invoke this observer from
                // network_thread and abort when a PeerConnection JNI method is
                // re-entered synchronously. Always leave the native callback first.
                if (state == PeerConnection.IceGatheringState.COMPLETE) {
                    mainHandler.post(WebRtcPlayer.this::sendOffer);
                }
            }

            @Override
            public void onIceCandidate(org.webrtc.IceCandidate candidate) {
                // For LAN-only use the first host candidate is enough. Sending
                // immediately avoids Android's several-second gathering timeout.
                mainHandler.postDelayed(WebRtcPlayer.this::sendOffer, 50);
            }

            @Override
            public void onConnectionChange(PeerConnection.PeerConnectionState state) {
                if (state == PeerConnection.PeerConnectionState.CONNECTED) {
                    mainHandler.post(listener::onConnected);
                } else if (state == PeerConnection.PeerConnectionState.FAILED) {
                    fail("La connexion vidéo WebRTC a échoué.");
                }
            }

            @Override
            public void onAddTrack(RtpReceiver receiver, org.webrtc.MediaStream[] streams) {
                MediaStreamTrack track = receiver.track();
                if (track instanceof VideoTrack) {
                    ((VideoTrack) track).addSink(renderer);
                } else if (track instanceof AudioTrack) {
                    track.setEnabled(true);
                }
            }
        });
        if (peer == null) {
            fail("Impossible de créer le lecteur WebRTC.");
            return;
        }

        peer.addTransceiver(
                MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO,
                new RtpTransceiver.RtpTransceiverInit(
                        RtpTransceiver.RtpTransceiverDirection.RECV_ONLY
                )
        );
        peer.addTransceiver(
                MediaStreamTrack.MediaType.MEDIA_TYPE_AUDIO,
                new RtpTransceiver.RtpTransceiverInit(
                        RtpTransceiver.RtpTransceiverDirection.RECV_ONLY
                )
        );
        peer.createOffer(new SimpleSdpObserver() {
            @Override
            public void onCreateSuccess(SessionDescription description) {
                peer.setLocalDescription(new SimpleSdpObserver() {
                    @Override
                    public void onSetSuccess() {
                        mainHandler.post(() -> {
                            if (peer != null && peer.iceGatheringState() ==
                                    PeerConnection.IceGatheringState.COMPLETE) sendOffer();
                        });
                    }

                    @Override
                    public void onSetFailure(String error) {
                        fail("Offre locale refusée : " + error);
                    }
                }, description);
            }

            @Override
            public void onCreateFailure(String error) {
                fail("Création de l’offre impossible : " + error);
            }
        }, new MediaConstraints());
    }

    private void sendOffer() {
        if (peer == null || peer.getLocalDescription() == null ||
                !offerSent.compareAndSet(false, true)) return;
        SessionDescription offer = peer.getLocalDescription();
        signalingExecutor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                JSONObject payload = new JSONObject();
                payload.put("type", offer.type.canonicalForm());
                payload.put("sdp", offer.description);
                byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
                connection = (HttpURLConnection) new URL(serverUrl + "/webrtc/offer").openConnection();
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(20000);
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type", "application/json");
                connection.setDoOutput(true);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(body);
                }
                if (connection.getResponseCode() != 200) {
                    throw new IllegalStateException("HTTP " + connection.getResponseCode());
                }
                StringBuilder response = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                        connection.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) response.append(line);
                }
                JSONObject answer = new JSONObject(response.toString());
                SessionDescription remote = new SessionDescription(
                        SessionDescription.Type.fromCanonicalForm(answer.getString("type")),
                        answer.getString("sdp")
                );
                mainHandler.post(() -> {
                    if (peer == null) return;
                    peer.setRemoteDescription(new SimpleSdpObserver() {
                        @Override
                        public void onSetFailure(String error) {
                            fail("Réponse vidéo refusée : " + error);
                        }
                    }, remote);
                });
            } catch (Exception exception) {
                fail("Négociation vidéo impossible : " + exception.getMessage());
            } finally {
                if (connection != null) connection.disconnect();
            }
        });
    }

    private void fail(String message) {
        mainHandler.post(() -> listener.onError(message));
    }

    void release() {
        if (peer != null) {
            peer.close();
            peer.dispose();
            peer = null;
        }
        signalingExecutor.shutdownNow();
        renderer.release();
        factory.dispose();
        eglBase.release();
    }
}
