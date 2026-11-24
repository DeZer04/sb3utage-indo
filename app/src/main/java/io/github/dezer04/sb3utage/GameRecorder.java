package io.github.dezer04.sb3utage;

import android.content.Context;
import android.media.Image;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.media.MediaScannerConnection;
import android.os.Environment;
import android.os.SystemClock;
import android.util.Log;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * The in-app recorder: the game's own picture (no touch buttons, no overlay) and its sound into an MP4
 * in Movies/SB3UtageINDO. aurora/lib/recorder.cpp turns each frame into NV12 on the GPU and calls
 * onVideoFrame and onAudio from its own thread; here they go through the phone's hardware H.264 and AAC
 * encoders into a MediaMuxer. Lighter than a screen recording: no second copy of the whole screen, the
 * game's size instead of the panel's, and no microphone or system sounds.
 */
final class GameRecorder {
    private static final String TAG = "Basara";
    /** Settings > System > Recording Quality: lines and frames per second. */
    static final int[][] QUALITIES = {{720, 30}, {720, 60}, {1080, 30}, {1080, 60}};
    private static final int[] BITRATES = {8_000_000, 12_000_000, 14_000_000, 20_000_000};
    /** No sound this long after the start: the file is made with the picture only. */
    private static final long AUDIO_WAIT_MS = 1500;

    private static volatile GameRecorder current;

    private final File file;
    private final int width, height, frameBytes;
    private final MediaCodec video;
    private volatile MediaCodec audio;  // made at the first sound block (its sample rate)
    private volatile boolean audioRefused;
    private final MediaMuxer muxer;
    private final long startedAt = SystemClock.elapsedRealtime();
    private final Object muxLock = new Object();
    private int videoTrack = -1, audioTrack = -1;
    private boolean muxing;
    private final List<Sample> early = new ArrayList<>();  // encoded before the muxer could start
    private final Thread drain;
    private volatile boolean stopping;
    private boolean videoDone, audioDone;
    private volatile long lastVideoUs = -1, lastAudioUs = -1;
    private volatile int frames;

    private static final class Sample {
        final boolean isVideo;
        final ByteBuffer data;
        final MediaCodec.BufferInfo info;

        Sample(boolean isVideo, ByteBuffer data, MediaCodec.BufferInfo info) {
            this.isVideo = isVideo;
            this.data = data;
            this.info = info;
        }
    }

    private static native long nativeFrameSize(int lines);
    private static native boolean nativeStart(int width, int height, int fps);
    private static native void nativeStop();
    private static native boolean nativeFillImage(ByteBuffer y, int yRowStride, ByteBuffer u, ByteBuffer v,
                                                  int uvRowStride, int uvPixelStride);

    static boolean recording() {
        return current != null;
    }

    /** Milliseconds since the recording started, or -1. */
    static long elapsedMs() {
        final GameRecorder r = current;
        return r == null ? -1 : SystemClock.elapsedRealtime() - r.startedAt;
    }

    /** Starts a recording at QUALITIES[quality]; returns why it could not, or null. */
    static String start(Context context, int quality) {
        if (current != null) return null;
        final int q = Math.max(0, Math.min(QUALITIES.length - 1, quality));
        final long size = nativeFrameSize(QUALITIES[q][0]);
        int width = (int) (size >>> 32), height = (int) size;
        final int fps = QUALITIES[q][1];
        MediaFormat format = videoFormat(width, height, fps, BITRATES[q]);
        String encoder = new MediaCodecList(MediaCodecList.REGULAR_CODECS).findEncoderForFormat(format);
        if (encoder == null && height > 720) {
            // The phone's encoder stops below 1080 lines: 720 instead.
            final long smaller = nativeFrameSize(720);
            width = (int) (smaller >>> 32);
            height = (int) smaller;
            format = videoFormat(width, height, fps, BITRATES[fps > 30 ? 1 : 0]);
            encoder = new MediaCodecList(MediaCodecList.REGULAR_CODECS).findEncoderForFormat(format);
        }
        if (encoder == null) return Tr.t("This phone has no video encoder for ") + width + "×" + height + ".";
        final File file = outputFile(context);
        try {
            final GameRecorder recorder = new GameRecorder(file, width, height, encoder, format);
            current = recorder;
            if (!nativeStart(width, height, fps)) {
                current = null;
                recorder.stopping = true;
                recorder.release(false);
                //noinspection ResultOfMethodCallIgnored
                file.delete();
                return Tr.t("The game is not ready to record yet.");
            }
            Log.i(TAG, "recording " + width + "x" + height + " at " + fps + " FPS (" + encoder + ") to " + file);
            return null;
        } catch (IOException | RuntimeException e) {
            Log.e(TAG, "the recording could not start", e);
            current = null;
            //noinspection ResultOfMethodCallIgnored
            file.delete();
            return Tr.t("The recording could not start: ") + e.getMessage();
        }
    }

    /**
     * Ends the recording and finishes the file (blocking: call off the UI thread, or from onPause while
     * the app goes away). Returns the file, or null when there was none or it holds nothing.
     */
    static File stop(Context context) {
        final GameRecorder r = current;
        if (r == null) return null;
        nativeStop();  // no more frames: the recorder thread has stopped
        current = null;
        return r.finish(context.getApplicationContext());
    }

    private static MediaFormat videoFormat(int width, int height, int fps, int bitrate) {
        final MediaFormat format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height);
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible);
        format.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
        format.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
        format.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2);
        // What recorder.cpp writes: BT.709, limited range.
        format.setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT709);
        format.setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED);
        format.setInteger(MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.COLOR_TRANSFER_SDR_VIDEO);
        return format;
    }

    /** Movies/SB3UtageINDO (in the Gallery) with All files access, else the app's own Movies folder. */
    private static File outputFile(Context context) {
        File dir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES), "SB3UtageINDO");
        if (!AppFiles.hasFileAccess(context) || !(dir.isDirectory() || dir.mkdirs())) {
            dir = context.getExternalFilesDir(Environment.DIRECTORY_MOVIES);
        }
        final String name = "SB3U_" + new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.ROOT).format(new Date()) + ".mp4";
        return new File(dir, name);
    }

    private GameRecorder(File file, int width, int height, String encoder, MediaFormat format) throws IOException {
        this.file = file;
        this.width = width;
        this.height = height;
        this.frameBytes = width * height * 3 / 2;
        muxer = new MediaMuxer(file.getAbsolutePath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
        video = MediaCodec.createByCodecName(encoder);
        try {
            video.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            video.start();
        } catch (RuntimeException e) {
            video.release();
            muxer.release();
            throw e;
        }
        drain = new Thread(this::drainLoop, "SB3 recorder out");
        drain.start();
    }

    // --- from recorder.cpp's thread --------------------------------------------------------------

    @SuppressWarnings("unused")  // called from native code
    private static void onVideoFrame(long ptsUs) {
        final GameRecorder r = current;
        if (r == null || r.stopping) return;
        try {
            final int index = r.video.dequeueInputBuffer(2000);
            if (index < 0) return;  // the encoder is behind: this frame is left out
            final Image image = r.video.getInputImage(index);
            boolean filled = false;
            if (image != null) {
                final Image.Plane[] planes = image.getPlanes();
                filled = planes.length == 3 && nativeFillImage(planes[0].getBuffer(), planes[0].getRowStride(),
                        planes[1].getBuffer(), planes[2].getBuffer(), planes[1].getRowStride(),
                        planes[1].getPixelStride());
            }
            long pts = Math.max(ptsUs, r.lastVideoUs + 1);
            r.lastVideoUs = pts;
            r.video.queueInputBuffer(index, 0, filled ? r.frameBytes : 0, pts, 0);
            if (filled) ++r.frames;
        } catch (IllegalStateException e) {
            Log.w(TAG, "recording: video frame lost", e);
        }
    }

    @SuppressWarnings("unused")  // called from native code
    private static void onAudio(ByteBuffer pcm, int bytes, long ptsUs, int sampleRate) {
        final GameRecorder r = current;
        if (r == null || r.stopping || r.audioRefused) return;
        try {
            MediaCodec codec = r.audio;
            if (codec == null) {
                synchronized (r.muxLock) {
                    if (r.muxing) {  // too late: the file went on without sound
                        r.audioRefused = true;
                        return;
                    }
                }
                codec = r.makeAudio(sampleRate);
                if (codec == null) return;
            }
            int offset = 0;
            while (offset < bytes) {
                final int index = codec.dequeueInputBuffer(5000);
                if (index < 0) return;  // behind: the rest of this block is left out
                final ByteBuffer in = codec.getInputBuffer(index);
                if (in == null) return;
                in.clear();
                final int n = Math.min(bytes - offset, in.remaining() & ~3);
                if (n <= 0) {
                    codec.queueInputBuffer(index, 0, 0, r.lastAudioUs + 1, 0);
                    return;
                }
                pcm.limit(offset + n).position(offset);
                in.put(pcm);
                final long pts = Math.max(ptsUs + (offset / 4) * 1_000_000L / sampleRate, r.lastAudioUs + 1);
                r.lastAudioUs = pts;
                codec.queueInputBuffer(index, 0, n, pts, 0);
                offset += n;
            }
        } catch (IllegalStateException e) {
            Log.w(TAG, "recording: sound block lost", e);
        } finally {
            pcm.clear();
        }
    }

    private MediaCodec makeAudio(int sampleRate) {
        try {
            final MediaFormat format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, sampleRate, 2);
            format.setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC);
            format.setInteger(MediaFormat.KEY_BIT_RATE, 160_000);
            format.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 16384);
            final MediaCodec codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC);
            codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
            codec.start();
            audio = codec;
            return codec;
        } catch (IOException | RuntimeException e) {
            Log.e(TAG, "recording: no sound encoder for " + sampleRate + " Hz", e);
            audioRefused = true;
            return null;
        }
    }

    // --- the encoded stream into the file -------------------------------------------------------

    private void drainLoop() {
        final MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        try {
            while (!(videoDone && (audioDone || audio == null))) {
                videoDone |= drainOnce(video, true, info);
                final MediaCodec a = audio;
                if (a != null && !audioDone) audioDone |= drainOnce(a, false, info);
                synchronized (muxLock) {
                    maybeStartLocked();
                }
            }
        } catch (IllegalStateException e) {
            Log.w(TAG, "recording: the encoder stopped", e);
        }
    }

    /** One output buffer (or a 10 ms wait) from `codec`; true at its end of stream. */
    private boolean drainOnce(MediaCodec codec, boolean isVideo, MediaCodec.BufferInfo info) {
        final int index = codec.dequeueOutputBuffer(info, 10_000);
        if (index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
            synchronized (muxLock) {
                if (!muxing) {
                    if (isVideo) videoTrack = muxer.addTrack(codec.getOutputFormat());
                    else audioTrack = muxer.addTrack(codec.getOutputFormat());
                    maybeStartLocked();
                }
            }
            return false;
        }
        if (index < 0) return false;
        final ByteBuffer out = codec.getOutputBuffer(index);
        final boolean end = (info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0;
        if (out != null && info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
            out.position(info.offset).limit(info.offset + info.size);
            synchronized (muxLock) {
                final int track = isVideo ? videoTrack : audioTrack;
                if (muxing && track >= 0) {
                    muxer.writeSampleData(track, out, info);
                } else if (!muxing) {
                    final ByteBuffer copy = ByteBuffer.allocateDirect(info.size);
                    copy.put(out).flip();
                    final MediaCodec.BufferInfo copyInfo = new MediaCodec.BufferInfo();
                    copyInfo.set(0, info.size, info.presentationTimeUs, info.flags);
                    early.add(new Sample(isVideo, copy, copyInfo));
                }
            }
        }
        codec.releaseOutputBuffer(index, false);
        return end;
    }

    /** The muxer starts once the picture's track is known and the sound's too (or never came). */
    private void maybeStartLocked() {
        if (muxing || videoTrack < 0) return;
        final boolean soundLate = audio == null && SystemClock.elapsedRealtime() - startedAt > AUDIO_WAIT_MS;
        if (audioTrack < 0 && !soundLate && !audioRefused && !stopping) return;
        if (audioTrack < 0) audioRefused = true;
        muxer.start();
        muxing = true;
        for (Sample s : early) {
            final int track = s.isVideo ? videoTrack : audioTrack;
            if (track >= 0) muxer.writeSampleData(track, s.data, s.info);
        }
        early.clear();
    }

    private File finish(Context context) {
        stopping = true;
        endOfStream(video, lastVideoUs);
        final MediaCodec a = audio;
        if (a != null) endOfStream(a, lastAudioUs);
        try {
            drain.join(3000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        final boolean wrote;
        synchronized (muxLock) {
            if (!muxing && videoTrack >= 0) maybeStartLocked();
            wrote = muxing && frames > 0;
        }
        release(wrote);
        if (!wrote) {
            //noinspection ResultOfMethodCallIgnored
            file.delete();
            return null;
        }
        MediaScannerConnection.scanFile(context, new String[] {file.getAbsolutePath()}, new String[] {"video/mp4"}, null);
        Log.i(TAG, "recording saved: " + file + " (" + frames + " frames, " + file.length() / 1024 + " KB)");
        return file;
    }

    private static void endOfStream(MediaCodec codec, long lastUs) {
        try {
            final int index = codec.dequeueInputBuffer(200_000);
            if (index >= 0) {
                codec.queueInputBuffer(index, 0, 0, Math.max(0, lastUs + 1), MediaCodec.BUFFER_FLAG_END_OF_STREAM);
            }
        } catch (IllegalStateException e) {
            Log.w(TAG, "recording: no end of stream", e);
        }
    }

    private void release(boolean stopMuxer) {
        try {
            video.stop();
        } catch (IllegalStateException ignored) {
            // already stopped
        }
        video.release();
        final MediaCodec a = audio;
        if (a != null) {
            try {
                a.stop();
            } catch (IllegalStateException ignored) {
                // already stopped
            }
            a.release();
        }
        try {
            if (stopMuxer) muxer.stop();
        } catch (IllegalStateException e) {
            Log.w(TAG, "recording: the file could not be closed", e);
        }
        muxer.release();
    }
}
