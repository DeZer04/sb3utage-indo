package io.github.dezer04.sb3utage;

import android.content.Context;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.EOFException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;

/**
 * The translation patches the launcher installs (tools/u_make_patch.py): a .patch holds, for every game
 * file the translation changes, a VCDIFF against the original disc's file (or the whole file when it is
 * new), so only differences ship. Installing reads the originals from the player's own game (the ISO/RVZ
 * in Read mode, or the unpacked folder), checks them, and writes the results with the package's
 * Riivolution XML into SB3UtageINDO/Riivolution/<id>; the runtime lays the chosen one over the game
 * (Config.toml overlay_roots, AppFiles.writeConfig). Each patch keeps its own folder, so switching is
 * instant. An install that stops (cancelled, app closed) carries on where it was: finished files whose
 * SHA-1 matches are kept. A format 2 patch also carries a texture pack (tools/u_patch_add_textures.py):
 * whole files under Textures/, installed in the patch's own Textures folder and played while the patch is
 * on (textures()), ahead of the player's own texture mods.
 *
 * Format (big-endian): "SB3UPAT1", u32 header length, header JSON (format, game, id, name, version,
 * description, files, bytes, xml_name, xml), then per file: u16+UTF-8 output path (S3HJ08/... or, format
 * 2, Textures/...), u16+UTF-8 disc path (empty for a new file), u8 kind (0 VCDIFF, 1 whole), u32 source
 * size, 20-byte source SHA-1, u32 result size, 20-byte result SHA-1, u32 payload length, payload (zlib);
 * then "SB3UEND1" and u32 file count.
 */
final class GamePatch {
    static final String FULL = "full", DESC = "desc";
    /** Full Patch Indo with Sin-Nohara's texture mod fitted to it (tools/u_rehash_textures.py). */
    static final String FULL_SN = "full-sn";
    /** A Riivolution package copied by hand into SB3UtageINDO/Riivolution (riivolution/, S3HJ08/). */
    static final String MANUAL = "manual";
    private static final byte[] MAGIC = "SB3UPAT1".getBytes(StandardCharsets.US_ASCII);
    private static final byte[] END = "SB3UEND1".getBytes(StandardCharsets.US_ASCII);
    private static final String MARKER = "patch.json";

    /** What a .patch (or an installed patch's patch.json) says about itself. */
    static final class Info {
        String id, name, version, description = "";
        int files;
        long bytes;          // the game data it writes
        String xmlName, xml;
        File file;           // the .patch, when read from one
    }

    interface Progress {
        void update(long done, long total, int files, int totalFiles);
    }

    private GamePatch() {}

    /** The header of the .patch at `file`, checked to be whole; thrown when it isn't a patch for this game. */
    static Info read(File file) throws IOException {
        final Info info;
        try (RandomAccessFile in = new RandomAccessFile(file, "r")) {
            final byte[] magic = new byte[8];
            in.readFully(magic);
            if (!Arrays.equals(magic, MAGIC)) throw new IOException(Tr.t("Not a patch for SB3 UTAGE:INDO."));
            final int length = in.readInt();
            if (length <= 0 || length > (16 << 20)) throw new IOException(Tr.t("The patch is damaged."));
            final byte[] header = new byte[length];
            in.readFully(header);
            info = parse(new String(header, StandardCharsets.UTF_8));
            if (in.length() < 8 + 4 + length + 12) throw new IOException(Tr.t("The patch is incomplete. Download it again."));
            in.seek(in.length() - 12);
            final byte[] end = new byte[8];
            in.readFully(end);
            if (!Arrays.equals(end, END) || in.readInt() != info.files) {
                throw new IOException(Tr.t("The patch is incomplete. Download it again."));
            }
        } catch (EOFException e) {
            throw new IOException(Tr.t("The patch is incomplete. Download it again."));
        }
        info.file = file;
        return info;
    }

    private static Info parse(String json) throws IOException {
        try {
            final JSONObject o = new JSONObject(json);
            final int format = o.optInt("format");
            if (format < 1 || format > 2) throw new IOException(Tr.t("This patch needs a newer SB3 UTAGE:INDO."));
            if (!"S3HJ08".equals(o.optString("game"))) throw new IOException(Tr.t("Not a patch for SB3 UTAGE:INDO."));
            final Info info = new Info();
            info.id = o.getString("id");
            if (!info.id.matches("[a-z0-9_-]{1,32}") || info.id.equals(MANUAL)) throw new IOException(Tr.t("The patch is damaged."));
            info.name = o.optString("name", info.id);
            info.version = o.optString("version", "");
            info.description = o.optString("description", "");
            info.files = o.optInt("files");
            info.bytes = o.optLong("bytes");
            info.xmlName = o.optString("xml_name", "S3HJ08.xml");
            info.xml = o.optString("xml", null);
            return info;
        } catch (JSONException e) {
            throw new IOException(Tr.t("The patch is damaged."));
        }
    }

    /** SB3UtageINDO/Riivolution/<id>, where patch `id` is installed; null without file access. */
    static File root(String id) {
        final File dir = AppFiles.patchDir();
        if (dir == null) return null;
        return MANUAL.equals(id) ? dir : new File(dir, id);
    }

    /**
     * The texture pack installed with patch `id` (its Textures folder, when the patch is whole and has one),
     * or null. The game plays it while that patch is on, whether or not Custom Textures is.
     */
    static File textures(String id) {
        if (id.isEmpty() || MANUAL.equals(id) || installed(id) == null) return null;
        final File dir = new File(root(id), "Textures");
        final String[] names = dir.list();
        return names != null && names.length > 0 ? dir : null;
    }

    /** The patch installed as `id` (whole: its marker is written last), or null. */
    static Info installed(String id) {
        final File root = root(id);
        if (root == null) return null;
        if (MANUAL.equals(id)) {
            final String name = AppFiles.patchName(root);
            if (name == null) return null;
            final Info info = new Info();
            info.id = MANUAL;
            info.name = name;
            info.version = "";
            return info;
        }
        if (!id.matches("[a-z0-9_-]{1,32}")) return null;
        final File marker = new File(root, MARKER);
        if (!marker.isFile() || AppFiles.patchName(root) == null) return null;
        try {
            final JSONObject o = new JSONObject(AppFiles.readText(marker));
            final Info info = new Info();
            info.id = id;
            info.name = o.optString("name", id);
            info.version = o.optString("version", "");
            info.description = o.optString("description", "");
            info.files = o.optInt("files");
            info.bytes = o.optLong("bytes");
            return info;
        } catch (JSONException | RuntimeException e) {
            return null;
        }
    }

    /** For the log: the patch played, "none", or the id and why it isn't used. */
    static String logName(String id) {
        if (id.isEmpty()) return "none";
        final Info info = installed(id);
        return info == null ? id + " (not installed)" : info.name + (info.version.isEmpty() ? "" : " " + info.version);
    }

    /** Every installed patch: the folders under SB3UtageINDO/Riivolution, then a package copied by hand. */
    static List<Info> installedAll() {
        final List<Info> all = new ArrayList<>();
        final File dir = AppFiles.patchDir();
        final File[] roots = dir != null ? dir.listFiles(File::isDirectory) : null;
        if (roots != null) {
            Arrays.sort(roots);
            for (File root : roots) {
                final Info info = installed(root.getName());
                if (info != null) all.add(info);
            }
        }
        final Info manual = installed(MANUAL);
        if (manual != null) all.add(manual);
        return all;
    }

    /** Patch `id`'s folder and everything in it. A hand-copied package (MANUAL) loses only its two folders. */
    static void remove(String id) {
        final File root = root(id);
        if (root == null) return;
        if (MANUAL.equals(id)) {
            AppFiles.deleteRecursively(new File(root, "riivolution"));
            AppFiles.deleteRecursively(new File(root, "S3HJ08"));
        } else {
            AppFiles.deleteRecursively(root);
        }
    }

    /**
     * Installs `info` (read from its .patch) over the player's game. Thrown with what went wrong (in the
     * player's language); returns normally when done, or early when `cancel` was set (the files so far stay
     * for the next try). Off the UI thread.
     */
    static void install(Context context, Info info, Progress progress, AtomicBoolean cancel) throws IOException {
        final File root = root(info.id);
        if (root == null) throw new IOException(Tr.t("Allow file access first."));
        if (!AppFiles.gameReady(context)) throw new IOException(Tr.t("Choose your game file first."));
        //noinspection ResultOfMethodCallIgnored
        root.mkdirs();
        // Not whole until the marker is back: the runtime must not use a half-written patch.
        //noinspection ResultOfMethodCallIgnored
        new File(root, MARKER).delete();
        final long free = root.getUsableSpace();
        if (free < info.bytes - AppFiles.folderSize(root) + (64L << 20)) {
            throw new IOException(String.format(java.util.Locale.ROOT,
                    Tr.t("Not enough space: the patch needs %.1f GB on the phone's storage, %.1f GB is free."),
                    info.bytes / 1e9, free / 1e9));
        }
        final Originals originals = Originals.open(context);
        final int threads = Math.max(1, Math.min(4, Runtime.getRuntime().availableProcessors() - 2));
        final ExecutorService pool = Executors.newFixedThreadPool(threads);
        final Semaphore inFlight = new Semaphore(threads + 1);
        final List<Future<?>> jobs = new ArrayList<>();
        final Set<String> outputs = new HashSet<>();
        final AtomicLong done = new AtomicLong();
        final java.util.concurrent.atomic.AtomicInteger filesDone = new java.util.concurrent.atomic.AtomicInteger();
        final java.util.concurrent.atomic.AtomicReference<IOException> failure = new java.util.concurrent.atomic.AtomicReference<>();
        try (DataInputStream in = new DataInputStream(new BufferedInputStream(new FileInputStream(info.file), 1 << 16))) {
            in.skipBytes(8);
            in.skipBytes(in.readInt());
            for (int i = 0; i < info.files; ++i) {
                if (cancel.get() || failure.get() != null) break;
                final Entry entry;
                try {
                    entry = Entry.read(in);
                    if (!(entry.output.startsWith("S3HJ08/") || entry.output.startsWith("Textures/"))
                            || entry.output.contains("..")) {
                        throw new IOException(Tr.t("The patch is damaged."));
                    }
                } catch (IOException e) {
                    failure.compareAndSet(null, e);  // the jobs still queued skip themselves
                    break;
                }
                outputs.add(entry.output);
                inFlight.acquireUninterruptibly();
                jobs.add(pool.submit(() -> {
                    try {
                        if (failure.get() == null && !cancel.get()) {
                            apply(entry, root, originals);
                            done.addAndGet(entry.resultSize);
                            progress.update(done.get(), info.bytes, filesDone.incrementAndGet(), info.files);
                        }
                    } catch (IOException e) {
                        failure.compareAndSet(null, e);
                    } catch (RuntimeException | OutOfMemoryError e) {
                        failure.compareAndSet(null, new IOException(entry.output + ": " + e));
                    } finally {
                        inFlight.release();
                    }
                }));
            }
        } finally {
            // Every job ends before the disc closes: they read from it.
            for (Future<?> job : jobs) {
                try {
                    job.get();
                } catch (Exception ignored) {
                    // its failure is in `failure`
                }
            }
            pool.shutdown();
            originals.close();
        }
        if (failure.get() != null) throw failure.get();
        if (cancel.get()) return;
        // Files an older version of this patch wrote and this one no longer has.
        pruneOthers(new File(root, "S3HJ08"), "S3HJ08", outputs);
        pruneOthers(new File(root, "Textures"), "Textures", outputs);
        final File xmlDir = new File(root, "riivolution");
        AppFiles.deleteRecursively(xmlDir);
        //noinspection ResultOfMethodCallIgnored
        xmlDir.mkdirs();
        if (info.xml == null || info.xmlName.contains("/") || info.xmlName.contains("\\")) {
            throw new IOException(Tr.t("The patch is damaged."));
        }
        AppFiles.writeText(new File(xmlDir, info.xmlName), info.xml);
        try {
            final JSONObject marker = new JSONObject()
                    .put("id", info.id).put("name", info.name).put("version", info.version)
                    .put("description", info.description).put("files", info.files).put("bytes", info.bytes);
            AppFiles.writeText(new File(root, MARKER), marker.toString(1));
        } catch (JSONException e) {
            throw new IOException(e.toString());
        }
    }

    private static void pruneOthers(File dir, String rel, Set<String> keep) {
        final File[] children = dir.listFiles();
        if (children == null) return;
        for (File child : children) {
            final String path = rel + "/" + child.getName();
            if (child.isDirectory()) {
                pruneOthers(child, path, keep);
                final String[] left = child.list();
                //noinspection ResultOfMethodCallIgnored
                if (left != null && left.length == 0) child.delete();
            } else if (!keep.contains(path)) {
                //noinspection ResultOfMethodCallIgnored
                child.delete();
            }
        }
    }

    /** One game file of a patch. */
    private static final class Entry {
        String output, discPath;
        int kind;
        long sourceSize, resultSize;
        byte[] sourceSha1 = new byte[20], resultSha1 = new byte[20], payload;

        static Entry read(DataInputStream in) throws IOException {
            final Entry e = new Entry();
            e.output = utf(in);
            e.discPath = utf(in);
            e.kind = in.readUnsignedByte();
            e.sourceSize = in.readInt() & 0xFFFFFFFFL;
            in.readFully(e.sourceSha1);
            e.resultSize = in.readInt() & 0xFFFFFFFFL;
            in.readFully(e.resultSha1);
            final long length = in.readInt() & 0xFFFFFFFFL;
            if (e.kind > 1 || e.resultSize > (256 << 20) || length > (256 << 20)) {
                throw new IOException(Tr.t("The patch is damaged."));
            }
            e.payload = new byte[(int) length];
            in.readFully(e.payload);
            return e;
        }

        private static String utf(DataInputStream in) throws IOException {
            final byte[] bytes = new byte[in.readUnsignedShort()];
            in.readFully(bytes);
            return new String(bytes, StandardCharsets.UTF_8);
        }
    }

    /** One file: skipped when already there and right, else rebuilt from the original and written. */
    private static void apply(Entry entry, File root, Originals originals) throws IOException {
        final File out = new File(root, entry.output);
        if (out.isFile() && out.length() == entry.resultSize && Arrays.equals(sha1(readAll(out)), entry.resultSha1)) {
            return;  // from an earlier, stopped install
        }
        final byte[] stored = inflate(entry.payload);
        final byte[] result;
        if (entry.kind == 0) {
            final byte[] source = originals.read(entry.discPath);
            if (source == null || source.length != entry.sourceSize || !Arrays.equals(sha1(source), entry.sourceSha1)) {
                throw new IOException(String.format(Tr.t("Your game's %s isn't the original disc's, so the patch "
                        + "can't be put on it. Use a dump of the original S3HJ08 disc (not one already patched)."),
                        entry.discPath.replace("files/", "")));
            }
            result = Vcdiff.decode(source, stored, (int) entry.resultSize);
        } else {
            result = stored;
        }
        if (result.length != entry.resultSize || !Arrays.equals(sha1(result), entry.resultSha1)) {
            throw new IOException(entry.output + ": " + Tr.t("The patch is damaged."));
        }
        final File dir = out.getParentFile();
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        final File temp = new File(dir, out.getName() + ".part");
        try (FileOutputStream stream = new FileOutputStream(temp)) {
            stream.write(result);
        }
        //noinspection ResultOfMethodCallIgnored
        out.delete();
        if (!temp.renameTo(out)) throw new IOException(Tr.t("Couldn't write ") + out);
    }

    private static byte[] inflate(byte[] compressed) throws IOException {
        final Inflater inflater = new Inflater();
        try {
            inflater.setInput(compressed);
            final java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream(compressed.length * 3);
            final byte[] buffer = new byte[1 << 16];
            while (!inflater.finished()) {
                final int n = inflater.inflate(buffer);
                if (n == 0 && (inflater.needsInput() || inflater.needsDictionary())) {
                    throw new IOException(Tr.t("The patch is damaged."));
                }
                out.write(buffer, 0, n);
            }
            return out.toByteArray();
        } catch (DataFormatException e) {
            throw new IOException(Tr.t("The patch is damaged."));
        } finally {
            inflater.end();
        }
    }

    static byte[] sha1(byte[] bytes) {
        try {
            return MessageDigest.getInstance("SHA-1").digest(bytes);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private static byte[] readAll(File file) throws IOException {
        final byte[] bytes = new byte[(int) file.length()];
        try (InputStream in = new FileInputStream(file)) {
            if (AppFiles.readFully(in, bytes) != bytes.length) throw new EOFException(file.getPath());
        }
        return bytes;
    }

    /** The original game's files: from the ISO/RVZ in Read mode (DiscImport), else the unpacked folder. */
    private static final class Originals implements AutoCloseable {
        private final File unpacked;
        private final ParcelFileDescriptor file;
        private final long disc;

        private Originals(File unpacked, ParcelFileDescriptor file, long disc) {
            this.unpacked = unpacked;
            this.file = file;
            this.disc = disc;
        }

        static Originals open(Context context) throws IOException {
            final Uri source = AppFiles.gameSource(context);
            if (source == null) return new Originals(AppFiles.gameDir(context), null, 0);
            final ParcelFileDescriptor file = context.getContentResolver().openFileDescriptor(source, "r");
            if (file == null) throw new IOException(Tr.t("Couldn't open that file."));
            try {
                return new Originals(null, file, DiscImport.openGame(file.getFd()));
            } catch (IOException | RuntimeException e) {
                file.close();
                throw e;
            }
        }

        /** The disc's file at `path` ("files/nativeWii/..."), or null when the game has none. */
        byte[] read(String path) throws IOException {
            if (unpacked == null) return DiscImport.readFile(disc, path);
            final File file = new File(unpacked, path);
            return file.isFile() ? readAll(file) : null;
        }

        @Override
        public void close() {
            if (file == null) return;
            DiscImport.closeGame(disc);
            try {
                file.close();
            } catch (IOException ignored) {
            }
        }
    }
}
