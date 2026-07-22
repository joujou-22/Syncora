package org.syncora.client;

import org.webrtc.CandidatePairChangeEvent;
import org.webrtc.DataChannel;
import org.webrtc.IceCandidate;
import org.webrtc.MediaStream;
import org.webrtc.PeerConnection;
import org.webrtc.RtpReceiver;

abstract class SimplePeerObserver implements PeerConnection.Observer {
    @Override public void onSignalingChange(PeerConnection.SignalingState state) { }
    @Override public void onIceConnectionChange(PeerConnection.IceConnectionState state) { }
    @Override public void onStandardizedIceConnectionChange(PeerConnection.IceConnectionState state) { }
    @Override public void onConnectionChange(PeerConnection.PeerConnectionState state) { }
    @Override public void onIceConnectionReceivingChange(boolean receiving) { }
    @Override public void onIceGatheringChange(PeerConnection.IceGatheringState state) { }
    @Override public void onIceCandidate(IceCandidate candidate) { }
    @Override public void onIceCandidatesRemoved(IceCandidate[] candidates) { }
    @Override public void onSelectedCandidatePairChanged(CandidatePairChangeEvent event) { }
    @Override public void onAddStream(MediaStream stream) { }
    @Override public void onRemoveStream(MediaStream stream) { }
    @Override public void onDataChannel(DataChannel channel) { }
    @Override public void onRenegotiationNeeded() { }
    @Override public void onAddTrack(RtpReceiver receiver, MediaStream[] streams) { }
}
