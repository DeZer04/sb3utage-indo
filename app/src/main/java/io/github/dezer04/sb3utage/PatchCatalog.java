package io.github.dezer04.sb3utage;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Where the launcher's patches come from: the online list (patches.json beside the releases) and .patch
 * files on the phone (SB3UtageINDO/Patch, Download). One Choice per patch id, in the list's order: Full
 * Patch Indo and Deskripsi Only always, any other found after them.
 */
final class PatchCatalog {
    /** The online list: {"patches":[{"id","name","version","description","url","size","sha256"}]}. */
    static final String CATALOG_URL = "https://raw.githubusercontent.com/DeZer04/sb3utage-indo/main/patches.json";

    /** One patch in the launcher's list: what is installed, what can be downloaded, what is on the phone. */
    static final class Choice {
        final String id;
        String name, description;
        GamePatch.Info installed;
        GamePatch.Info local;      // a .patch on the phone
        Online online;             // the online list's entry

        Choice(String id, String name, String description) {
            this.id = id;
            this.name = name;
            this.description = description;
        }

        /** The newest version there is to install (on the phone or online), or null. */
        String newest() {
            final String l = local != null ? local.version : null, o = online != null ? online.version : null;
            if (l == null) return o;
            if (o == null) return l;
            return Updater.isNewer(o, l) ? o : l;
        }

        /** Something newer than what is installed (or anything, when nothing is). */
        boolean installable() {
            final String newest = newest();
            return newest != null && (installed == null || Updater.isNewer(newest, installed.version));
        }
    }

    static final class Online {
        String version, url, sha256;
        long size;
    }

    private PatchCatalog() {}

    /** The list as known without the network: installed patches and .patch files on the phone. */
    static List<Choice> local() {
        final Map<String, Choice> choices = new LinkedHashMap<>();
        choices.put(GamePatch.FULL, new Choice(GamePatch.FULL, "Full Patch Indo",
                Tr.t("The whole game in Indonesian: menus, story, items and descriptions.")));
        choices.put(GamePatch.DESC, new Choice(GamePatch.DESC, Tr.t("Descriptions Only"),
                Tr.t("Only the descriptions are in Indonesian; the rest of the game stays Japanese.")));
        for (File file : patchFiles()) {
            try {
                final GamePatch.Info info = GamePatch.read(file);
                final Choice choice = choice(choices, info.id, info.name, info.description);
                if (choice.local == null || Updater.isNewer(info.version, choice.local.version)) choice.local = info;
            } catch (IOException ignored) {
                // not a patch, or not whole yet (still downloading)
            }
        }
        for (GamePatch.Info info : GamePatch.installedAll()) {
            final String about = info.id.equals(GamePatch.MANUAL)
                    ? Tr.t("Copied by hand into SB3UtageINDO/Riivolution.") : info.description;
            choice(choices, info.id, info.name, about).installed = info;
        }
        return new ArrayList<>(choices.values());
    }

    private static Choice choice(Map<String, Choice> choices, String id, String name, String description) {
        Choice choice = choices.get(id);
        if (choice == null) {
            choice = new Choice(id, name, description);
            choices.put(id, choice);
        }
        return choice;
    }

    /** The .patch files in SB3UtageINDO/Patch and Download (not their subfolders). */
    static List<File> patchFiles() {
        final List<File> files = new ArrayList<>();
        for (File dir : new File[] {AppFiles.homeSub("Patch"), FileBrowser.downloads()}) {
            final File[] found = dir != null ? dir.listFiles((d, name) -> name.toLowerCase(Locale.ROOT).endsWith(".patch")) : null;
            if (found != null) for (File file : found) if (file.isFile()) files.add(file);
        }
        return files;
    }

    /**
     * The online list's text (network; off the UI thread), or null when there is none yet (404). Thrown
     * when it can't be reached.
     */
    static String fetchOnline() throws IOException {
        final HttpURLConnection connection = Updater.open(Updater.debugProperty("debug.basara.patch_catalog", CATALOG_URL));
        try {
            final int code = connection.getResponseCode();
            if (code == HttpURLConnection.HTTP_NOT_FOUND) return null;
            if (code != HttpURLConnection.HTTP_OK) throw new IOException(Tr.t("The patch list answered ") + code);
            return Updater.readAll(connection.getInputStream());
        } finally {
            connection.disconnect();
        }
    }

    /** Adds the online list's entries (fetchOnline's text) to `choices`; a list that can't be read adds nothing. */
    static void merge(List<Choice> choices, String json) {
        if (json == null) return;
        try {
            final JSONArray patches = new JSONObject(json).getJSONArray("patches");
            for (int i = 0; i < patches.length(); ++i) {
                final JSONObject p = patches.getJSONObject(i);
                final String id = p.getString("id");
                if (!id.matches("[a-z0-9_-]{1,32}") || id.equals(GamePatch.MANUAL)) continue;
                Choice choice = null;
                for (Choice c : choices) if (c.id.equals(id)) choice = c;
                if (choice == null) {
                    choice = new Choice(id, p.optString("name", id), p.optString("description", ""));
                    choices.add(choice);
                }
                if (p.has("name")) choice.name = p.getString("name");
                if (p.has("description")) choice.description = p.getString("description");
                final Online online = new Online();
                online.version = p.getString("version");
                online.url = p.getString("url");
                online.size = p.optLong("size");
                online.sha256 = p.optString("sha256", null);
                choice.online = online;
            }
        } catch (org.json.JSONException ignored) {
            // a list this version can't read: the patches on the phone still show
        }
    }

    /**
     * Downloads `choice`'s online patch to SB3UtageINDO/Patch (going on from a stopped download), checks
     * it and returns it read. Off the UI thread; returns null when `cancel` was set.
     */
    static GamePatch.Info download(Choice choice, Updater.Progress progress, AtomicBoolean cancel) throws IOException {
        final Online online = choice.online;
        final File dir = AppFiles.homeSub("Patch");
        if (dir == null) throw new IOException(Tr.t("Allow file access first."));
        final File file = new File(dir, "sb3utage-" + choice.id + "-" + online.version.replaceAll("[^0-9A-Za-z._-]", "_") + ".patch");
        final File part = new File(dir, file.getName() + ".part");
        if (online.size > 0 && dir.getUsableSpace() < online.size - part.length() + (32L << 20)) {
            throw new IOException(String.format(Locale.ROOT, Tr.t("Not enough space: the download needs %.0f MB, %.0f MB is free."),
                    online.size / 1e6, dir.getUsableSpace() / 1e6));
        }
        long have = part.isFile() ? part.length() : 0;
        if (online.size > 0 && have > online.size) {
            //noinspection ResultOfMethodCallIgnored
            part.delete();
            have = 0;
        }
        final HttpURLConnection connection = Updater.open(online.url);
        try {
            if (have > 0) connection.setRequestProperty("Range", "bytes=" + have + "-");
            final int code = connection.getResponseCode();
            if (code == HttpURLConnection.HTTP_OK) {
                have = 0;  // the server sends it from the start
            } else if (code != HttpURLConnection.HTTP_PARTIAL) {
                throw new IOException(Tr.t("The download answered ") + code);
            }
            final long total = online.size > 0 ? online.size : have + connection.getContentLengthLong();
            try (InputStream in = connection.getInputStream(); OutputStream out = new FileOutputStream(part, have > 0)) {
                final byte[] buffer = new byte[1 << 16];
                long done = have;
                for (int n; (n = in.read(buffer)) > 0; ) {
                    if (cancel.get()) return null;
                    out.write(buffer, 0, n);
                    done += n;
                    progress.update(done, total);
                }
            }
        } finally {
            connection.disconnect();
        }
        if (online.size > 0 && part.length() != online.size) throw new IOException(Tr.t("The download stopped. Try again."));
        if (online.sha256 != null && !online.sha256.isEmpty() && !online.sha256.equalsIgnoreCase(sha256(part))) {
            //noinspection ResultOfMethodCallIgnored
            part.delete();
            throw new IOException(Tr.t("The download is damaged. Try again."));
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
        if (!part.renameTo(file)) throw new IOException(Tr.t("Couldn't write ") + file);
        return GamePatch.read(file);
    }

    private static String sha256(File file) throws IOException {
        final MessageDigest digest;
        try {
            digest = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IOException("SHA-256 unavailable");
        }
        try (InputStream in = new java.io.FileInputStream(file)) {
            final byte[] buffer = new byte[1 << 16];
            for (int n; (n = in.read(buffer)) > 0; ) digest.update(buffer, 0, n);
        }
        final StringBuilder hex = new StringBuilder();
        for (byte b : digest.digest()) hex.append(String.format(Locale.ROOT, "%02x", b));
        return hex.toString();
    }

    /** A downloaded .patch (in SB3UtageINDO/Patch) once it is installed: the installed copy is what counts. */
    static boolean isDownload(File file) {
        final File dir = AppFiles.homeSub("Patch");
        return dir != null && dir.equals(file.getParentFile()) && file.getName().startsWith("sb3utage-");
    }
}
