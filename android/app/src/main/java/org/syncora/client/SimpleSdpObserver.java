package org.syncora.client;

import org.webrtc.SdpObserver;
import org.webrtc.SessionDescription;

abstract class SimpleSdpObserver implements SdpObserver {
    @Override public void onCreateSuccess(SessionDescription description) { }
    @Override public void onSetSuccess() { }
    @Override public void onCreateFailure(String error) { }
    @Override public void onSetFailure(String error) { }
}
