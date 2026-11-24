package io.github.dezer04.sb3utage;

import java.io.IOException;
import java.util.Arrays;
import java.util.zip.Adler32;

/**
 * VCDIFF (RFC 3284) decoder for the launcher's patches (GamePatch, tools/u_make_patch.py), as xdelta3 3.1
 * writes them with -S none -A: no secondary compression, no application header, per-window Adler-32,
 * copies from the source file only. One game file at a time, all in memory (the largest is a few MB).
 * Adapted from DeZer04's earlier xdelta patcher decoder, without its LZMA secondary.
 */
final class Vcdiff {
    private static final int NOOP = 0, ADD = 1, RUN = 2, COPY = 3;
    private static final int S_NEAR = 4, S_SAME = 3;
    // The default code table (RFC 3284 5.6): type1, size1, mode1, type2, size2, mode2.
    private static final byte[][] TABLE = new byte[256][];

    static {
        int i = 0;
        TABLE[i++] = new byte[] {RUN, 0, 0, NOOP, 0, 0};
        TABLE[i++] = new byte[] {ADD, 0, 0, NOOP, 0, 0};
        for (int s = 1; s <= 17; s++) TABLE[i++] = new byte[] {ADD, (byte) s, 0, NOOP, 0, 0};
        for (int m = 0; m < 9; m++) {
            TABLE[i++] = new byte[] {COPY, 0, (byte) m, NOOP, 0, 0};
            for (int s = 4; s <= 18; s++) TABLE[i++] = new byte[] {COPY, (byte) s, (byte) m, NOOP, 0, 0};
        }
        for (int m = 0; m < 6; m++)
            for (int a = 1; a <= 4; a++)
                for (int c = 4; c <= 6; c++) TABLE[i++] = new byte[] {ADD, (byte) a, 0, COPY, (byte) c, (byte) m};
        for (int m = 6; m < 9; m++)
            for (int a = 1; a <= 4; a++) TABLE[i++] = new byte[] {ADD, (byte) a, 0, COPY, 4, (byte) m};
        for (int m = 0; m < 9; m++) TABLE[i++] = new byte[] {COPY, 4, (byte) m, ADD, 1, 0};
        if (i != 256) throw new AssertionError(i);
    }

    private Vcdiff() {}

    /** `patch` applied to `source`: the new file, `size` bytes. Thrown when the patch is damaged. */
    static byte[] decode(byte[] source, byte[] patch, int size) throws IOException {
        final In in = new In(patch);
        if (in.u8() != 0xD6 || in.u8() != 0xC3 || in.u8() != 0xC4 || in.u8() != 0) throw damaged("header");
        final int hdr = in.u8();
        if ((hdr & 1) != 0) throw damaged("secondary compression");
        if ((hdr & 2) != 0) throw damaged("code table");
        if ((hdr & 4) != 0) in.p += (int) in.varint();  // application header
        final byte[] out = new byte[size];
        final Adler32 adler = new Adler32();
        final int[] near = new int[S_NEAR], same = new int[S_SAME * 256];
        int written = 0;
        while (in.p < patch.length) {
            final int wi = in.u8();
            if ((wi & 2) != 0) throw damaged("VCD_TARGET");
            int srcLen = 0, srcPos = 0;
            if ((wi & 1) != 0) {
                srcLen = (int) in.varint();
                srcPos = (int) in.varint();
                if (srcPos < 0 || srcLen < 0 || srcPos + srcLen > source.length) throw damaged("source window");
            }
            in.varint();  // the length of the delta encoding
            final int tgtLen = (int) in.varint();
            if (in.u8() != 0) throw damaged("compressed sections");
            final int dataLen = (int) in.varint(), instLen = (int) in.varint(), addrLen = (int) in.varint();
            final long sum = (wi & 4) != 0 ? in.be32() : -1;
            int dp = in.p, ip = dp + dataLen, ap = ip + instLen;
            final int instEnd = ap, end = ap + addrLen;
            if (end > patch.length || written + tgtLen > size) throw damaged("window size");
            Arrays.fill(near, 0);
            Arrays.fill(same, 0);
            final int base = written;  // the window's first byte in `out`
            int nextSlot = 0, t = 0;
            while (ip < instEnd) {
                final byte[] e = TABLE[patch[ip++] & 0xFF];
                for (int half = 0; half < 2; half++) {
                    final int type = e[half * 3], mode = e[half * 3 + 2];
                    int n = e[half * 3 + 1] & 0xFF;
                    if (type == NOOP) continue;
                    if (n == 0) {  // the size follows in the instruction section
                        long v = 0;
                        int c;
                        do { c = patch[ip++] & 0xFF; v = (v << 7) | (c & 0x7F); } while ((c & 0x80) != 0);
                        n = (int) v;
                    }
                    if (n < 0 || t + n > tgtLen) throw damaged("instruction size");
                    if (type == ADD) {
                        System.arraycopy(patch, dp, out, base + t, n);
                        dp += n;
                        t += n;
                    } else if (type == RUN) {
                        Arrays.fill(out, base + t, base + t + n, patch[dp++]);
                        t += n;
                    } else {  // COPY: the address (RFC 3284 5.4)
                        final int here = srcLen + t;
                        int a;
                        if (mode < 2 + S_NEAR) {
                            long v = 0;
                            int c;
                            do { c = patch[ap++] & 0xFF; v = (v << 7) | (c & 0x7F); } while ((c & 0x80) != 0);
                            a = mode == 0 ? (int) v : mode == 1 ? here - (int) v : near[mode - 2] + (int) v;
                        } else {
                            a = same[(mode - 2 - S_NEAR) * 256 + (patch[ap++] & 0xFF)];
                        }
                        near[nextSlot] = a;
                        nextSlot = (nextSlot + 1) % S_NEAR;
                        same[a % (S_SAME * 256)] = a;
                        if (a < 0 || a >= here) throw damaged("copy address");
                        if (a < srcLen) {  // from the source segment, maybe on into the target
                            final int k = Math.min(n, srcLen - a);
                            System.arraycopy(source, srcPos + a, out, base + t, k);
                            t += k;
                            n -= k;
                            a = srcLen;
                        }
                        final int from = base + a - srcLen;  // from this window's output: may overlap
                        for (int k = 0; k < n; k++) out[base + t + k] = out[from + k];
                        t += n;
                    }
                }
            }
            if (t != tgtLen || dp != instEnd - instLen || ap != end) throw damaged("window end");
            if (sum >= 0) {
                adler.reset();
                adler.update(out, base, tgtLen);
                if (adler.getValue() != sum) throw damaged("window checksum");
            }
            written += tgtLen;
            in.p = end;
        }
        if (written != size) throw damaged("size");
        return out;
    }

    private static IOException damaged(String what) {
        return new IOException("damaged patch (" + what + ")");
    }

    private static final class In {
        final byte[] b;
        int p;

        In(byte[] b) { this.b = b; }

        int u8() throws IOException {
            if (p >= b.length) throw damaged("truncated");
            return b[p++] & 0xFF;
        }

        long varint() throws IOException {
            long v = 0;
            int c;
            do { c = u8(); v = (v << 7) | (c & 0x7F); } while ((c & 0x80) != 0);
            return v;
        }

        long be32() throws IOException { return ((long) u8() << 24) | (u8() << 16) | (u8() << 8) | u8(); }
    }
}
