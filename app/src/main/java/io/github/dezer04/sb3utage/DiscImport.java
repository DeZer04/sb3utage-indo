package io.github.dezer04.sb3utage;

import java.io.IOException;

/** Unpacks the player's ISO or RVZ into the game folder, or looks into it (libbasara_disc.so, runtime/disc). */
final class DiscImport {
    static {
        System.loadLibrary("basara_disc");
    }

    private DiscImport() {}

    interface Listener {
        /** False stops the extraction. Called on the extracting thread. */
        boolean onProgress(long done, long total);
    }

    /** What extract returns when the listener stopped it. */
    static final String CANCELLED = "";

    /** The disc's first 8 bytes (game ID and revision); thrown when the file can't be read as a disc. */
    static native byte[] readHeader(int fd) throws IOException;

    /** Null when the game is in `outDir`, CANCELLED, or why it failed. */
    static native String extract(int fd, String outDir, long freeBytes, Listener listener);

    /** The game in the image at `fd`, for readFile until closeGame (the fd stays open meanwhile); thrown as readHeader. */
    static native long openGame(int fd) throws IOException;

    /** The game's file at `path` ("files/nativeWii/..."), whole, or null when it has none. Any thread. */
    static native byte[] readFile(long game, String path) throws IOException;

    static native void closeGame(long game);
}
