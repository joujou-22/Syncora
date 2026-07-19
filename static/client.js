(function () {
  "use strict";
  var video = document.getElementById("screen");
  var fallback = document.getElementById("fallback");
  var status = document.getElementById("status");
  var peer = null;
  var remoteStream = null;
  var retryTimer = null;

  function setStatus(message, connected) {
    status.textContent = message;
    status.className = connected ? "connected" : "";
  }

  function waitForIceGathering(pc) {
    if (pc.iceGatheringState === "complete") { return Promise.resolve(); }
    return new Promise(function (resolve) {
      function checkState() {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", checkState);
          resolve();
        }
      }
      pc.addEventListener("icegatheringstatechange", checkState);
    });
  }

  function closePeer() {
    if (peer) { peer.close(); peer = null; }
    video.srcObject = null;
    remoteStream = null;
  }

  async function connectWebRTC() {
    if (!window.RTCPeerConnection) { throw new Error("WebRTC unsupported"); }
    closePeer();
    fallback.style.display = "none";
    video.style.display = "block";
    setStatus("Connecting with WebRTC…", false);

    var pc = new RTCPeerConnection({iceServers: []});
    peer = pc;
    remoteStream = new MediaStream();
    video.srcObject = remoteStream;
    var videoTransceiver = pc.addTransceiver("video", {direction: "recvonly"});
    if ("jitterBufferTarget" in videoTransceiver.receiver) {
      videoTransceiver.receiver.jitterBufferTarget = 0;
    }
    if ("playoutDelayHint" in videoTransceiver.receiver) {
      videoTransceiver.receiver.playoutDelayHint = 0;
    }
    pc.addTransceiver("audio", {direction: "recvonly"});
    pc.ontrack = function (event) {
      if (!remoteStream.getTracks().some(function (track) { return track.id === event.track.id; })) {
        remoteStream.addTrack(event.track);
      }
      video.play().catch(function () {});
      setStatus("Connected", true);
    };
    pc.onconnectionstatechange = function () {
      if (pc !== peer) { return; }
      if (pc.connectionState === "failed" || pc.connectionState === "disconnected" ||
          pc.connectionState === "closed") {
        setStatus("Connection lost — retrying…", false);
        clearTimeout(retryTimer);
        retryTimer = setTimeout(connect, 2000);
      }
    };

    var offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIceGathering(pc);
    var response = await fetch("/webrtc/offer", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(pc.localDescription)
    });
    if (!response.ok) { throw new Error("WebRTC negotiation failed"); }
    await pc.setRemoteDescription(await response.json());
  }

  function connectMJPEG() {
    closePeer();
    video.style.display = "none";
    fallback.style.display = "block";
    setStatus("WebRTC unavailable — using compatibility mode…", false);
    fallback.src = "/stream?time=" + Date.now();
  }

  fallback.onload = function () { setStatus("Connected (compatibility mode)", true); };
  fallback.onerror = function () {
    fallback.removeAttribute("src");
    setStatus("Connection lost — retrying…", false);
    clearTimeout(retryTimer);
    retryTimer = setTimeout(connect, 2000);
  };

  function connect() {
    clearTimeout(retryTimer);
    connectWebRTC().catch(function () { connectMJPEG(); });
  }

  document.getElementById("fullscreen").onclick = function () {
    var target = document.documentElement;
    var requestFullscreen = target.requestFullscreen || target.webkitRequestFullscreen;
    if (requestFullscreen) { requestFullscreen.call(target); }
  };

  document.getElementById("sound").onclick = function () {
    video.muted = false;
    video.volume = 1;
    video.play().then(function () {
      document.getElementById("sound").className = "enabled";
    }).catch(function () {
      setStatus("The TV browser blocked audio playback", false);
    });
  };

  window.addEventListener("beforeunload", closePeer);
  connect();
}());
