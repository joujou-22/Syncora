package org.syncora.client;

import java.io.ByteArrayOutputStream;

/** Reassembles complete Annex-B H.264 access units from RTP payloads. */
final class RtpH264Assembler {
    interface Listener { void onFrame(byte[] frame); }

    private static final byte[] START_CODE = {0, 0, 0, 1};
    private final Listener listener;
    private final ByteArrayOutputStream frame = new ByteArrayOutputStream(256 * 1024);
    private long timestamp = -1;
    private int expectedSequence = -1;
    private boolean damaged;
    private boolean fragmentedNal;

    RtpH264Assembler(Listener listener) {
        this.listener = listener;
    }

    void accept(byte[] packet, int length) {
        if (length < 13 || (packet[0] & 0xc0) != 0x80) return;
        int csrcCount = packet[0] & 0x0f;
        boolean extension = (packet[0] & 0x10) != 0;
        boolean padding = (packet[0] & 0x20) != 0;
        boolean marker = (packet[1] & 0x80) != 0;
        int sequence = ((packet[2] & 0xff) << 8) | (packet[3] & 0xff);
        long packetTimestamp = ((long) (packet[4] & 0xff) << 24)
                | ((long) (packet[5] & 0xff) << 16)
                | ((long) (packet[6] & 0xff) << 8)
                | (packet[7] & 0xffL);
        int offset = 12 + csrcCount * 4;
        if (offset >= length) return;
        if (extension) {
            if (offset + 4 > length) return;
            int words = ((packet[offset + 2] & 0xff) << 8) | (packet[offset + 3] & 0xff);
            offset += 4 + words * 4;
        }
        int end = length;
        if (padding) end -= packet[length - 1] & 0xff;
        if (offset >= end) return;

        if (expectedSequence != -1 && sequence != expectedSequence) damaged = true;
        expectedSequence = (sequence + 1) & 0xffff;
        if (timestamp != packetTimestamp) {
            resetFrame();
            timestamp = packetTimestamp;
        }

        int nalType = packet[offset] & 0x1f;
        if (nalType >= 1 && nalType <= 23) {
            appendNal(packet, offset, end - offset);
        } else if (nalType == 24) {
            appendStapA(packet, offset + 1, end);
        } else if (nalType == 28) {
            appendFuA(packet, offset, end);
        } else {
            damaged = true;
        }

        if (marker) {
            if (!damaged && !fragmentedNal && frame.size() > 0) {
                listener.onFrame(frame.toByteArray());
            }
            resetFrame();
            timestamp = -1;
        }
    }

    private void appendStapA(byte[] packet, int offset, int end) {
        while (offset + 2 <= end) {
            int size = ((packet[offset] & 0xff) << 8) | (packet[offset + 1] & 0xff);
            offset += 2;
            if (size <= 0 || offset + size > end) {
                damaged = true;
                return;
            }
            appendNal(packet, offset, size);
            offset += size;
        }
        if (offset != end) damaged = true;
    }

    private void appendFuA(byte[] packet, int offset, int end) {
        if (offset + 2 > end) { damaged = true; return; }
        int indicator = packet[offset] & 0xff;
        int header = packet[offset + 1] & 0xff;
        boolean start = (header & 0x80) != 0;
        boolean finish = (header & 0x40) != 0;
        if (start) {
            frame.write(START_CODE, 0, START_CODE.length);
            frame.write((indicator & 0xe0) | (header & 0x1f));
            fragmentedNal = true;
        } else if (!fragmentedNal) {
            damaged = true;
            return;
        }
        frame.write(packet, offset + 2, end - offset - 2);
        if (finish) fragmentedNal = false;
    }

    private void appendNal(byte[] data, int offset, int size) {
        frame.write(START_CODE, 0, START_CODE.length);
        frame.write(data, offset, size);
    }

    private void resetFrame() {
        frame.reset();
        damaged = false;
        fragmentedNal = false;
    }
}
