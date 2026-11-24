package io.github.dezer04.sb3utage;

import android.content.res.ColorStateList;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * The launcher's first page under the title card: the game (its file, how it is loaded, the patch in use)
 * and the translation patches, one to choose and install (GamePatch, PatchCatalog): No Patch, Full Patch
 * Indo, Descriptions Only, and any other the online list or the phone has. LauncherActivity keeps Play
 * and the steps before the game.
 */
final class HomePage {
    private final LauncherActivity activity;
    private final AppSettings settings;
    private final Runnable changed;  // the launcher's own refresh (Play hides while a patch installs)
    private final Handler main = new Handler(Looper.getMainLooper());
    private final LinearLayout view;
    private final LinearLayout gameRows;
    private final LinearLayout patchRows;
    private final LinearLayout patchActions;
    private final TextView patchNote;

    private List<PatchCatalog.Choice> choices = new ArrayList<>();
    /** The row chosen in the list (GamePatch ids; "" for No Patch), or null: the one in use. */
    private String selected;
    /** The online list's text once read (null: none yet or unreachable). */
    private String online;
    private boolean onlineAsked, onlineDone, onlineFailed;
    private boolean busy;
    private String fileName, fileSize;

    HomePage(LauncherActivity activity, AppSettings settings, Runnable changed) {
        this.activity = activity;
        this.settings = settings;
        this.changed = changed;
        view = new LinearLayout(activity);
        view.setOrientation(LinearLayout.VERTICAL);

        final LinearLayout game = card(Tr.t("Game"));
        gameRows = new LinearLayout(activity);
        gameRows.setOrientation(LinearLayout.VERTICAL);
        game.addView(gameRows, Ui.matchWidth(dp(6)));
        view.addView(game, Ui.matchWidth(dp(14)));

        final LinearLayout patches = card(Tr.t("Translation Patch"));
        patchRows = new LinearLayout(activity);
        patchRows.setOrientation(LinearLayout.VERTICAL);
        patches.addView(patchRows, Ui.matchWidth(dp(8)));
        patchActions = new LinearLayout(activity);
        patchActions.setOrientation(LinearLayout.VERTICAL);
        patches.addView(patchActions, Ui.matchWidth(dp(12)));
        patchNote = Ui.text(activity, "", 11.5f, Ui.MUTED);
        patches.addView(patchNote, Ui.matchWidth(dp(10)));
        view.addView(patches, Ui.matchWidth(dp(14)));
    }

    View view() { return view; }

    /** A patch is being downloaded or installed: the game must not start. */
    boolean busy() { return busy; }

    /** Reads the game and the patches again (the phone first, the online list once), then shows them. */
    void reload() {
        final boolean askOnline = !onlineAsked;
        onlineAsked = true;
        new Thread(() -> {
            final List<PatchCatalog.Choice> local = PatchCatalog.local();
            describeGameFile();
            main.post(() -> show(local));
            if (!askOnline) return;
            try {
                online = PatchCatalog.fetchOnline();
            } catch (IOException e) {
                onlineFailed = true;
            }
            onlineDone = true;
            final List<PatchCatalog.Choice> withOnline = PatchCatalog.local();
            main.post(() -> show(withOnline));
        }, "patch-list").start();
    }

    private void show(List<PatchCatalog.Choice> found) {
        if (activity.isFinishing()) return;
        PatchCatalog.merge(found, online);
        choices = found;
        showGame();
        showPatches();
    }

    // --- the game ------------------------------------------------------------------------------

    /** Read mode's file name and size (the content resolver, so off the UI thread). */
    private void describeGameFile() {
        final Uri source = AppFiles.gameSource(activity);
        String name = null, size = null;
        if (source != null) {
            if ("file".equals(source.getScheme()) && source.getPath() != null) {
                final File file = new File(source.getPath());
                name = file.getName();
                if (file.isFile()) size = gb(file.length());
            } else {
                try (Cursor c = activity.getContentResolver().query(source,
                        new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, null, null, null)) {
                    if (c != null && c.moveToFirst()) {
                        name = c.getString(0);
                        if (!c.isNull(1)) size = gb(c.getLong(1));
                    }
                } catch (RuntimeException ignored) {
                    // the grant is gone: gameProblem says so
                }
            }
        }
        fileName = name;
        fileSize = size;
    }

    private void showGame() {
        gameRows.removeAllViews();
        final boolean present = AppFiles.hasGameData(activity);
        // The title card names the game; here the disc, the file and the patch, one row each.
        gameRows.addView(infoRow(Tr.t("Disc"), "S3HJ08 · Wii · " + Tr.t("Japan"), null));
        if (!present) {
            gameRows.addView(infoRow(Tr.t("Game File"), Tr.t("Not chosen yet"), null));
            return;
        }
        final Uri source = AppFiles.gameSource(activity);
        if (source != null) {
            gameRows.addView(infoRow(Tr.t("Game File"), (fileName != null ? fileName : source.getLastPathSegment())
                    + (fileSize != null ? "  ·  " + fileSize : ""), Tr.t("Read from File")));
        } else {
            gameRows.addView(infoRow(Tr.t("Game File"), Tr.t("Unpacked in the app"), null));
        }
        final PatchCatalog.Choice active = activeChoice();
        gameRows.addView(infoRow(Tr.t("Patch"), active != null ? label(active.installed)
                : Tr.t("None (original Japanese)"), null));
    }

    /** A label and its value; `note` (or null) a smaller line under the value. */
    private View infoRow(String label, String value, String note) {
        final LinearLayout row = new LinearLayout(activity);
        row.setGravity(Gravity.TOP);
        row.setPadding(0, dp(5), 0, dp(5));
        final TextView name = Ui.text(activity, label, 13, Ui.MUTED);
        row.addView(name, new LinearLayout.LayoutParams(dp(96), LinearLayout.LayoutParams.WRAP_CONTENT));
        final LinearLayout values = new LinearLayout(activity);
        values.setOrientation(LinearLayout.VERTICAL);
        final TextView text = Ui.text(activity, value, 13, Ui.TEXT);
        text.setTypeface(Ui.MEDIUM);
        values.addView(text);
        if (note != null) values.addView(Ui.text(activity, note, 11.5f, Ui.MUTED), Ui.matchWidth(dp(2)));
        row.addView(values, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        return row;
    }

    // --- the patches ---------------------------------------------------------------------------

    /** The patch in use, when it is installed. */
    private PatchCatalog.Choice activeChoice() {
        final String id = settings.activePatch();
        for (PatchCatalog.Choice c : choices) if (c.id.equals(id) && c.installed != null) return c;
        return null;
    }

    private String activeId() {
        final PatchCatalog.Choice active = activeChoice();
        return active != null ? active.id : "";
    }

    private PatchCatalog.Choice selectedChoice() {
        final String id = selected != null ? selected : activeId();
        for (PatchCatalog.Choice c : choices) if (c.id.equals(id)) return c;
        return null;
    }

    private void showPatches() {
        patchRows.removeAllViews();
        final String chosen = selected != null ? selected : activeId();
        final boolean noneActive = activeId().isEmpty();
        patchRows.addView(patchRow("", Tr.t("No Patch"), null, Tr.t("The original Japanese game."),
                noneActive ? Tr.t("In use") : null, noneActive ? Ui.SUCCESS : Ui.MUTED, chosen.isEmpty()));
        for (PatchCatalog.Choice c : choices) {
            final String state;
            final int color;
            if (c.installed != null && c.id.equals(activeId())) {
                state = c.installable() ? Tr.t("In use · update ") + c.newest() + Tr.t(" available") : Tr.t("In use");
                color = c.installable() ? Ui.PENDING : Ui.SUCCESS;
            } else if (c.installed != null) {
                state = c.installable() ? Tr.t("Installed · update ") + c.newest() + Tr.t(" available") : Tr.t("Installed");
                color = c.installable() ? Ui.PENDING : Ui.SECONDARY;
            } else if (c.local != null && (c.online == null || !Updater.isNewer(c.online.version, c.local.version))) {
                state = Tr.t("On this phone: ") + c.local.file.getName();
                color = Ui.PENDING;
            } else if (c.online != null) {
                state = Tr.t("Download") + (c.online.size > 0 ? " · " + mb(c.online.size) : "");
                color = Ui.PENDING;
            } else {
                state = onlineFailed ? Tr.t("Not on this phone; the online list can't be reached")
                        : !onlineDone ? Tr.t("Checking the online list…") : Tr.t("Not available yet");
                color = Ui.MUTED;
            }
            final String version = c.installed != null ? c.installed.version : c.newest();
            patchRows.addView(patchRow(c.id, c.name, version, c.description, state, color, c.id.equals(chosen)));
        }
        showActions();
    }

    private View patchRow(String id, String name, String version, String about, String state, int stateColor,
                          boolean chosen) {
        final LinearLayout row = new LinearLayout(activity);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(12), dp(10), dp(12), dp(10));
        row.setBackground(Ui.touchBox(activity, chosen ? Ui.SELECTED : Ui.RAISED, chosen ? Ui.ACCENT : Ui.BORDER,
                Ui.RADIUS_CONTROL + 2));
        row.addView(radio(chosen), new LinearLayout.LayoutParams(dp(20), dp(20)));
        final LinearLayout text = new LinearLayout(activity);
        text.setOrientation(LinearLayout.VERTICAL);
        final LinearLayout titleLine = new LinearLayout(activity);
        titleLine.setGravity(Gravity.CENTER_VERTICAL);
        final TextView title = Ui.text(activity, name, 14.5f, Ui.TEXT);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        titleLine.addView(title, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        if (version != null && !version.isEmpty()) titleLine.addView(Ui.text(activity, "v" + version, 11.5f, Ui.MUTED));
        text.addView(titleLine);
        if (about != null && !about.isEmpty()) text.addView(Ui.text(activity, about, 12, Ui.SECONDARY), Ui.matchWidth(dp(2)));
        if (state != null) {
            final TextView line = Ui.text(activity, state, 11.5f, stateColor);
            line.setTypeface(Ui.MEDIUM);
            text.addView(line, Ui.matchWidth(dp(4)));
        }
        final LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        textParams.leftMargin = dp(12);
        row.addView(text, textParams);
        row.setClickable(true);
        row.setOnClickListener(v -> {
            if (busy) return;
            selected = id;
            showPatches();
        });
        final LinearLayout.LayoutParams params = Ui.matchWidth(dp(8));
        row.setLayoutParams(params);
        return row;
    }

    /** A radio mark: a ring, filled with a dot when chosen. */
    private View radio(boolean chosen) {
        final FrameLayout mark = new FrameLayout(activity);
        mark.setBackground(Ui.box(activity, Color.TRANSPARENT, chosen ? Ui.ACCENT : Ui.BORDER_STRONG, 10));
        if (chosen) {
            final View dot = new View(activity);
            dot.setBackground(Ui.box(activity, Ui.ACCENT, 0, 5));
            mark.addView(dot, new FrameLayout.LayoutParams(dp(10), dp(10), Gravity.CENTER));
        }
        return mark;
    }

    /** The buttons under the list, for the chosen row. */
    private void showActions() {
        patchActions.removeAllViews();
        patchNote.setText("");
        final boolean ready = AppFiles.gameReady(activity);
        final PatchCatalog.Choice c = selectedChoice();
        final String chosen = selected != null ? selected : activeId();
        if (chosen.isEmpty()) {
            if (!activeId().isEmpty()) {
                patchActions.addView(button(R.drawable.ic_play, Tr.t("Use the Original Game"), Ui.PRIMARY, () -> use("")));
            }
        } else if (c != null) {
            if (c.installable()) {
                final boolean update = c.installed != null;
                final boolean download = c.local == null || c.online != null && Updater.isNewer(c.online.version, c.local.version);
                final String label = (update ? Tr.t("Update") : Tr.t("Install"))
                        + (download && c.online != null && c.online.size > 0 ? " (" + mb(c.online.size) + ")" : "");
                final View install = button(R.drawable.ic_save, label, Ui.PRIMARY, () -> install(c, null));
                if (!ready) install.setAlpha(0.4f);
                patchActions.addView(install);
                if (!ready) patchNote.setText(Tr.t("Choose your game file first: the patch is made from it."));
                else if (c.installed == null) {
                    patchNote.setText(Tr.t("Made from your own game file and kept in SB3UtageINDO/Riivolution; "
                            + "your game file isn't changed."));
                }
            }
            if (c.installed != null && !c.id.equals(activeId())) {
                patchActions.addView(button(R.drawable.ic_play, Tr.t("Use This Patch"),
                        c.installable() ? Ui.PLAIN : Ui.PRIMARY, () -> use(c.id)));
            }
            if (c.installed == null && !c.installable()) {
                patchNote.setText(Tr.t("Not released yet. When you have its .patch file, put it in Download or "
                        + "SB3UtageINDO/Patch, or choose it below."));
            }
            if (c.installed != null) {
                patchActions.addView(button(0, Tr.t("Remove"), Ui.DANGER, () -> remove(c)));
            }
        }
        patchActions.addView(button(R.drawable.ic_folder, Tr.t("Choose a .patch File"), Ui.PLAIN, this::chooseFile));
    }

    private View button(int icon, String label, int style, Runnable run) {
        final LinearLayout button = Ui.button(activity, icon, label, style, v -> {
            if (!busy) run.run();
        });
        button.setLayoutParams(Ui.matchWidth(dp(8)));
        return button;
    }

    // --- actions -------------------------------------------------------------------------------

    /** Plays with patch `id` ("" none) from the next start; a game waiting in the background ends. */
    private void use(String id) {
        activity.endGame();
        settings.setActivePatch(id);
        selected = null;
        reload();
        changed.run();
    }

    private void remove(PatchCatalog.Choice c) {
        new Sheet(activity, Tr.t("Remove ") + c.name + "?",
                Tr.t("Its files are deleted from SB3UtageINDO/Riivolution. You can install it again later."))
                .action(Tr.t("Remove"), null, true, true, () -> {
                    activity.endGame();
                    busy = true;
                    changed.run();
                    new Thread(() -> {
                        GamePatch.remove(c.id);
                        main.post(() -> {
                            busy = false;
                            if (c.id.equals(settings.activePatch())) settings.setActivePatch("");
                            selected = null;
                            reload();
                            changed.run();
                        });
                    }, "patch-remove").start();
                })
                .action(Tr.t("Cancel"), null, false, false, null)
                .show();
    }

    /** A .patch from anywhere on the phone. */
    private void chooseFile() {
        FileBrowser.showFiles(activity, FileBrowser.downloads(), Tr.t("Choose a .patch file"), null,
                file -> file.getName().toLowerCase(Locale.ROOT).endsWith(".patch"),
                Tr.t("No folders or .patch files here."), file -> new Thread(() -> {
                    try {
                        final GamePatch.Info info = GamePatch.read(file);
                        main.post(() -> confirmFile(info));
                    } catch (IOException e) {
                        main.post(() -> message(Tr.t("Can't use this file"), e.getMessage()));
                    }
                }, "patch-read").start());
    }

    private void confirmFile(GamePatch.Info info) {
        new Sheet(activity, info.name + (info.version.isEmpty() ? "" : " v" + info.version),
                info.description.isEmpty() ? null : info.description)
                .action(Tr.t("Install"), null, true, false, () -> install(null, info))
                .action(Tr.t("Cancel"), null, false, false, null)
                .show();
    }

    /**
     * Installs `choice` (from the phone's .patch, downloading it first when the online one is newer) or the
     * chosen file `file`, then uses it. Shows its progress; Cancel keeps what is done for the next try.
     */
    private void install(PatchCatalog.Choice choice, GamePatch.Info file) {
        if (!AppFiles.gameReady(activity)) {
            message(Tr.t("Choose your game file first"), Tr.t("The patch is made from your own game file."));
            return;
        }
        activity.endGame();  // a game in the background reads these files
        final ProgressBar bar = progressBar();
        final TextView label = Ui.text(activity, Tr.t("Starting…"), 14, Ui.SECONDARY);
        final LinearLayout box = new LinearLayout(activity);
        box.setOrientation(LinearLayout.VERTICAL);
        box.addView(bar, Ui.matchWidth(dp(4)));
        box.addView(label, Ui.matchWidth(dp(6)));
        final AtomicBoolean cancel = new AtomicBoolean();
        final String name = choice != null ? choice.name : file.name;
        final Sheet sheet = new Sheet(activity, Tr.t("Installing ") + name,
                Tr.t("Keep the app open until it is done. Your game file isn't changed."))
                .view(box)
                .cancelable(false);
        sheet.actionStay(Tr.t("Cancel"), true, button -> {
            cancel.set(true);
            button.setText(Tr.t("Stopping…"));
            label.setText(Tr.t("Stopping…"));
        });
        sheet.show();
        busy = true;
        changed.run();
        activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        new Thread(() -> {
            String failure = null;
            GamePatch.Info info = file;
            try {
                if (info == null) {
                    final boolean download = choice.local == null || choice.online != null
                            && Updater.isNewer(choice.online.version, choice.local.version);
                    info = download ? PatchCatalog.download(choice, (done, total) -> main.post(() -> {
                        if (cancel.get()) return;
                        bar.setIndeterminate(total <= 0);
                        if (total > 0) bar.setProgress((int) (done * 1000 / total));
                        label.setText(String.format(Locale.ROOT, Tr.t("Downloading… %d of %d MB"),
                                done >> 20, total >> 20));
                    }), cancel) : choice.local;
                }
                if (info != null && !cancel.get()) {
                    main.post(() -> {
                        bar.setIndeterminate(true);
                        label.setText(Tr.t("Checking your game file…"));
                    });
                    GamePatch.install(activity, info, (done, total, files, totalFiles) -> main.post(() -> {
                        if (cancel.get()) return;
                        bar.setIndeterminate(false);
                        bar.setProgress((int) (done * 1000 / Math.max(total, 1)));
                        label.setText(String.format(Locale.ROOT, Tr.t("Installing… %d of %d files"), files, totalFiles));
                    }), cancel);
                    if (!cancel.get()) {
                        settings.setActivePatch(info.id);
                        // A download was only the way in: the installed copy is what is played.
                        if (PatchCatalog.isDownload(info.file)) {
                            //noinspection ResultOfMethodCallIgnored
                            info.file.delete();
                        }
                    }
                }
            } catch (IOException e) {
                failure = e.getMessage() != null ? e.getMessage() : e.toString();
            } catch (RuntimeException | OutOfMemoryError e) {
                failure = e.toString();
            }
            final String error = failure;
            final GamePatch.Info done = info;
            main.post(() -> {
                busy = false;
                activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                sheet.dismiss();
                selected = null;
                reload();
                changed.run();
                if (error != null) {
                    message(Tr.t("The patch couldn't be installed"), error
                            + Tr.t("\n\nWhat was done is kept: Install again carries on from there."));
                } else if (cancel.get()) {
                    Toast.makeText(activity, Tr.t("Stopped. Install again to carry on."), Toast.LENGTH_LONG).show();
                } else if (done != null) {
                    Toast.makeText(activity, done.name + Tr.t(" is installed and in use."), Toast.LENGTH_LONG).show();
                }
            });
        }, "patch-install").start();
    }

    // --- views ---------------------------------------------------------------------------------

    private LinearLayout card(String title) {
        final LinearLayout card = new LinearLayout(activity);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(Ui.box(activity, Ui.CARD, Ui.BORDER, Ui.RADIUS_WINDOW));
        card.setPadding(dp(18), dp(16), dp(18), dp(16));
        card.addView(Ui.caption(activity, title));
        return card;
    }

    private ProgressBar progressBar() {
        final ProgressBar bar = new ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal);
        bar.setProgressTintList(ColorStateList.valueOf(Ui.GRAB));
        bar.setProgressBackgroundTintList(ColorStateList.valueOf(Ui.FRAME));
        bar.setIndeterminateTintList(ColorStateList.valueOf(Ui.GRAB));
        bar.setMax(1000);
        bar.setIndeterminate(true);
        return bar;
    }

    private void message(String title, String body) {
        new Sheet(activity, title, body).action(Tr.t("OK"), null, true, false, null).show();
    }

    private static String label(GamePatch.Info info) {
        return info.name + (info.version == null || info.version.isEmpty() ? "" : " v" + info.version);
    }

    private static String gb(long bytes) {
        return String.format(Locale.ROOT, "%.2f GB", bytes / (double) (1L << 30));
    }

    private static String mb(long bytes) {
        return String.format(Locale.ROOT, "%d MB", Math.max(1, bytes >> 20));
    }

    private int dp(int value) { return Ui.dp(activity, value); }
}
