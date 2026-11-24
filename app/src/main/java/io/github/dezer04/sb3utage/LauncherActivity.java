package io.github.dezer04.sb3utage;

import android.app.Activity;
import android.app.ActivityManager;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.IOException;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * The app's entry. On a tap of the icon it checks what must come first (file access, a required update,
 * What's New, the game file on the first start), then shows the first page: the game
 * (its file, how it is loaded, the patch in use) and the translation patches to choose and install
 * (HomePage), with Play. The game holds every other setting in its own menu. The player's ISO or RVZ is
 * chosen once, on the first start.
 *
 * The game asks for this screen again for what its own process cannot do: a new game file
 * (ACTION_DISC), an update check (ACTION_UPDATE), the patch list (ACTION_PATCHES), or a restart
 * (EXTRA_RESTART_GAME).
 */
public final class LauncherActivity extends Activity {
    private static final int REQUEST_DISC = 1;
    /** Set by GameActivity.restartForSession: open the game again once its old process is gone. */
    static final String EXTRA_RESTART_GAME = "restartGame";
    /** Set by the game's menu: what to do here before going back to it (ACTION_*). */
    static final String EXTRA_ACTION = "action";
    /** Choose another game file: the running game is ended first. */
    static final String ACTION_DISC = "disc";
    /** Check for updates by hand; the game waits in the background. */
    static final String ACTION_UPDATE = "update";
    /** Replace the save with EXTRA_FILE (a backup), or undo the last import when there is none. */
    static final String ACTION_IMPORT_SAVE = "importSave";
    /** Settings > Reset and Clear from inside the game: EXTRA_FILE holds the picks (DevTools.pack). */
    static final String ACTION_RESET = "reset";
    /** The first page's patch list: the running game is ended first. */
    static final String ACTION_PATCHES = "patches";
    static final String EXTRA_FILE = "file";

    /** The app's name wherever it is shown; never translated. */
    static final String APP = "SB3 UTAGE:INDO";
    static final String PROJECT_URL = "https://github.com/DeZer04";
    /** How long the start waits for the update check before opening the game anyway (no network). */
    private static final int UPDATE_WAIT_MS = 5000;

    private AppSettings settings;
    private boolean updating;
    /** An update waiting for the player to allow installs from this app. */
    private Updater.Release waitingUpdate;
    private static final String STATE_WAITING_UPDATE = "waiting_update";
    /** Gone to allow "All files access" for the file browser: open it on the way back. */
    private boolean waitingFileAccess;
    private static final String STATE_WAITING_FILE_ACCESS = "waiting_file_access";
    /** Gone to allow "All files access" before playing (the log goes to /sdcard): carry on on the way back. */
    private boolean waitingPlayAccess;
    private static final String STATE_WAITING_PLAY_ACCESS = "waiting_play_access";
    /** The required "All files access" sheet is on screen. */
    private Sheet accessSheet;

    // The steps before the game (next()).
    private boolean checked;     // the update check is done (or skipped)
    private boolean notesDone;   // What's New was shown, or had nothing new
    private boolean warned;      // the disc and GPU notices were given for this start
    private boolean launched;    // the game was opened: this screen is on its way out
    private boolean importing;   // a game file is being unpacked
    private boolean playChosen;  // Play was tapped on the first page
    private HomePage home;
    /** What follows the update check: the next step at start, or back to the game. */
    private Runnable afterCheck;

    private int endedGame;  // the pid endGame just ended
    private TextView status;
    private LinearLayout primary;
    private TextView primaryLabel;
    private android.widget.ImageView primaryIcon;
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Portrait for the first start and a game file import (the manifest's); landscape when the
        // game only passes through here (Restart, update check, save import), so the screen does not turn.
        final Intent start = getIntent();
        if (start != null && (start.getBooleanExtra(EXTRA_RESTART_GAME, false)
                || ACTION_UPDATE.equals(start.getStringExtra(EXTRA_ACTION))
                || ACTION_IMPORT_SAVE.equals(start.getStringExtra(EXTRA_ACTION))
                || ACTION_RESET.equals(start.getStringExtra(EXTRA_ACTION)))) {
            setRequestedOrientation(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
        }
        CrashReport.installLauncherHandler(this);
        settings = new AppSettings(this);
        Tr.init(this);
        if (DeviceProfile.applyOnce(this, settings)) {
            Toast.makeText(this, Tr.t("This phone now uses the Low-End preset: steadier, a bit blurrier. "
                    + "Undo it in the game's menu: Performance > Preset."), Toast.LENGTH_LONG).show();
        }
        setContentView(page());

        if (savedInstanceState != null) {
            // Android 11 ends this process when "Allow from this source" changes.
            waitingUpdate = Updater.Release.from(savedInstanceState.getBundle(STATE_WAITING_UPDATE));
            waitingFileAccess = savedInstanceState.getBoolean(STATE_WAITING_FILE_ACCESS, false);
            waitingPlayAccess = savedInstanceState.getBoolean(STATE_WAITING_PLAY_ACCESS, false);
        }
        if (!handleIntent(getIntent())) main.post(this::next);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    /** What the game asked for (restart, new game file, update check). False: an ordinary start. */
    private boolean handleIntent(Intent intent) {
        if (intent == null) return false;
        if (intent.getBooleanExtra(EXTRA_RESTART_GAME, false)) {
            intent.removeExtra(EXTRA_RESTART_GAME);
            checked = notesDone = warned = true;
            launched = true;
            showState(Tr.t("Restarting the game…"));
            // The old game process ends as its activity finishes: open the new one once it is gone.
            main.postDelayed(this::openGame, 700);
            return true;
        }
        final String action = intent.getStringExtra(EXTRA_ACTION);
        if (action == null) return false;
        intent.removeExtra(EXTRA_ACTION);
        checked = notesDone = true;
        launched = false;
        if (ACTION_PATCHES.equals(action)) {
            endGame();  // it reads the patch's files
            playChosen = false;
            refresh();
            home.reload();
        } else if (ACTION_DISC.equals(action)) {
            warned = false;
            endGame();
            refresh();
            pickDisc();
        } else if (ACTION_IMPORT_SAVE.equals(action)) {
            // The game's process ends first, so it cannot write over the save being put in.
            warned = true;
            final String path = intent.getStringExtra(EXTRA_FILE);
            final Runnable done = () -> {
                launched = false;
                refresh();  // Play, under the outcome
            };
            launched = true;  // no button while it works
            refresh();
            if (path != null) SaveData.importFile(this, new File(path), this::endGame, done);
            else SaveData.undoLastImport(this, this::endGame, done);
        } else if (ACTION_RESET.equals(action)) {
            // The game's process ends first: it holds these files open.
            warned = true;
            endGame();
            launched = true;  // no button while it works
            refresh();
            DevTools.runPacked(this, intent.getStringExtra(EXTRA_FILE), () -> {
                launched = false;
                refresh();  // Play
            });
        } else if (ACTION_UPDATE.equals(action)) {
            warned = true;
            refresh();
            afterCheck = this::launch;
            checkForUpdates(false);
        }
        return true;
    }

    /**
     * The next thing before the game: each step that has to wait (a sheet, the network, the file
     * browser) calls this again when it is done. Opens the game once nothing is left.
     */
    private void next() {
        if (launched || isFinishing()) return;
        refresh();
        if (requiredUpdate != null) {
            requireUpdate(requiredUpdate);
            return;
        }
        if (!AppFiles.hasFileAccess(this)) {
            if (accessSheet == null && !waitingPlayAccess) requireAccess();
            return;
        }
        if (!checked) {
            if (!updating) {
                afterCheck = () -> {
                    checked = true;
                    next();
                };
                checkForUpdates(true);
                // No answer in time (no network): play now, the next start checks again.
                main.postDelayed(() -> {
                    if (!checked && updating) finishCheck();
                }, UPDATE_WAIT_MS);
            }
            return;
        }
        if (!notesDone) {
            notesDone = true;
            if (ReleaseNotes.showIfNew(this, settings, this::next)) return;
        }
        if (importing) return;
        if (!AppFiles.gameReady(this)) {
            // The first start: the game file, once.
            pickDisc();
            return;
        }
        // The first page (the game and its patches) until the player taps Play.
        if (!playChosen) {
            refresh();
            home.reload();  // a game file just chosen
            return;
        }
        if (!warned) {
            warned = true;
            if (!warnOldGpu(this::launch)) launch();
            return;
        }
        launch();
    }

    /** Into the game; this screen goes. */
    private void launch() {
        if (launched) return;
        launched = true;
        showState(Tr.t("Starting…"));
        openGame();
    }

    private void openGame() {
        // A game waiting in the background comes back; otherwise a new one starts.
        startActivity(new Intent(this, GameActivity.class).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT));
        finish();
        overridePendingTransition(0, 0);
    }

    // --- the page: the title, one line of state and Play; the game and its patches under them -------

    private View page() {
        final android.widget.ScrollView scroll = new android.widget.ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setClipToPadding(false);
        // A dark backdrop with a faint crimson glow from the top.
        scroll.setBackground(new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,
                new int[] {0xFF2A1114, Ui.BG, Ui.BG}));
        final LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setGravity(Gravity.CENTER);
        scroll.addView(page, new android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT, android.widget.FrameLayout.LayoutParams.WRAP_CONTENT));

        // Everything on one card in the middle.
        final LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER_HORIZONTAL);
        card.setBackground(Ui.box(this, Ui.CARD, Ui.BORDER, Ui.RADIUS_WINDOW));
        card.setPadding(dp(28), dp(26), dp(28), dp(24));
        card.setElevation(dp(8));
        final View mark = new View(this);
        mark.setBackground(Ui.box(this, Ui.ACCENT, 0, Ui.RADIUS_PILL));
        card.addView(mark, new LinearLayout.LayoutParams(dp(36), dp(4)));
        final TextView title = text("SB3 UTAGE:INDO", 24);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        card.addView(title, matchWidth(dp(14)));
        final TextView version = text("Sengoku BASARA 3 Utage  ·  v" + versionText(), 12);
        version.setTextColor(FAINT);
        card.addView(version, matchWidth(dp(4)));
        // The launcher's language (the game's menu has it too: Display > Language).
        final LinearLayout languages = new LinearLayout(this);
        languages.setGravity(Gravity.CENTER);
        final int shown = Tr.resolve(settings.language());
        languages.addView(Ui.chip(this, "Bahasa Indonesia", shown == Tr.INDONESIAN, true,
                v -> changeLanguage(Tr.INDONESIAN)));
        final LinearLayout.LayoutParams englishParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        englishParams.leftMargin = dp(8);
        languages.addView(Ui.chip(this, "English", shown == Tr.ENGLISH, true, v -> changeLanguage(Tr.ENGLISH)),
                englishParams);
        card.addView(languages, matchWidth(dp(14)));
        status = text("", 14);
        status.setTextColor(MUTED);
        card.addView(status, matchWidth(dp(20)));
        primary = Ui.button(this, R.drawable.ic_folder, Tr.t("Choose Game File"), Ui.PRIMARY, v -> onPrimary());
        final LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        buttonParams.topMargin = dp(18);
        card.addView(primary, buttonParams);
        final int cardWidth = Math.min(dp(420), getResources().getDisplayMetrics().widthPixels - dp(48));
        page.addView(card, new LinearLayout.LayoutParams(cardWidth, LinearLayout.LayoutParams.WRAP_CONTENT));
        home = new HomePage(this, settings, this::refresh);
        page.addView(home.view(), new LinearLayout.LayoutParams(cardWidth, LinearLayout.LayoutParams.WRAP_CONTENT));
        primaryLabel = findLabel(primary);
        primaryIcon = (android.widget.ImageView) primary.getChildAt(0);
        primary.setVisibility(View.GONE);
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            final android.graphics.Insets bars = SystemBars.bars(insets, true);
            v.setPadding(bars.left + dp(24), bars.top + dp(24), bars.right + dp(24), bars.bottom + dp(24));
            return SystemBars.consumed(insets);
        });
        return scroll;
    }

    /** The page again in `language`; not while a game file loads, an update or a patch runs. */
    private void changeLanguage(int language) {
        if (importing || updating || launched || home.busy() || Tr.resolve(settings.language()) == language) return;
        settings.setLanguage(language);
        Tr.init(this);
        setContentView(page());
        refresh();
        home.reload();
    }

    private static TextView findLabel(LinearLayout button) {
        for (int i = button.getChildCount() - 1; i >= 0; --i) {
            if (button.getChildAt(i) instanceof TextView) return (TextView) button.getChildAt(i);
        }
        return null;
    }

    /** The button under the state line: choose the game file, or play once one is there. */
    private void onPrimary() {
        if (importing || home.busy()) return;
        if (AppFiles.gameReady(this)) {
            playChosen = true;
            launched = false;
            next();
        } else {
            pickDisc();
        }
    }

    private void showState(String text) {
        if (status != null) status.setText(text);
    }

    private void refresh() {
        if (status == null) return;
        final boolean present = AppFiles.hasGameData(this);
        final String problem = present ? AppFiles.gameProblem(this) : null;
        final boolean ready = present && problem == null;
        if (importing) {
            showState(Tr.t("Loading your game…"));
        } else if (!present) {
            showState(Tr.t("Choose your own ISO or RVZ of the game (Japan, S3HJ08). Unpack it once (about 4 GB), "
                    + "or play it straight from the file."));
        } else if (problem != null) {
            showState(Tr.t("The game can't be played. ") + problem);
        } else if (updating) {
            showState(Tr.t("Checking for updates…"));
        } else {
            showState(Tr.t("Ready to play"));
        }
        // Hidden while something runs: the game file loads, an update, a patch installs, the game starts.
        final boolean act = !importing && !updating && !launched && (home == null || !home.busy());
        primary.setVisibility(act ? View.VISIBLE : View.GONE);
        if (primaryLabel != null) primaryLabel.setText(ready ? Tr.t("Play") : Tr.t("Choose Game File"));
        primaryIcon.setImageResource(ready ? R.drawable.ic_play : R.drawable.ic_folder);
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (waitingUpdate != null) {
            outState.putBundle(STATE_WAITING_UPDATE, waitingUpdate.toBundle());
        }
        outState.putBoolean(STATE_WAITING_FILE_ACCESS, waitingFileAccess);
        outState.putBoolean(STATE_WAITING_PLAY_ACCESS, waitingPlayAccess);
    }

    @Override
    protected void onResume() {
        super.onResume();
        // A .patch downloaded meanwhile, or a patch changed in the game's menu.
        if (home != null && !home.busy()) home.reload();
        DevTools.checkExpired(this);
        // The game died (maybe before its own log opened): say why and where the report is.
        final String crash = CrashReport.checkLastGameExit(this);
        if (crash != null) {
            Toast.makeText(this, Tr.t("The game closed unexpectedly: ") + crash, Toast.LENGTH_LONG).show();
        }
        // A custom GPU driver that failed or crashed the last start is switched back to the system one.
        if (gameProcess() == 0) {
            final String driver = GpuDrivers.checkLastStart(this, new AppSettings(this));
            if (driver != null) Toast.makeText(this, driver, Toast.LENGTH_LONG).show();
            final String lost = GpuDrivers.checkGpuLost(this, new AppSettings(this));
            if (lost != null) Toast.makeText(this, lost, Toast.LENGTH_LONG).show();
        }
        // Back from "Allow from this source": carry on with the update that was waiting for it.
        if (waitingUpdate != null && Updater.canInstall(this)) {
            final Updater.Release release = waitingUpdate;
            waitingUpdate = null;
            startUpdate(release);
        }
        // Back from "All files access".
        if (waitingFileAccess) {
            waitingFileAccess = false;
            if (AppFiles.hasFileAccess(this)) {
                browseDisc();
            }
        }
        if (waitingPlayAccess) {
            waitingPlayAccess = false;
            next();
        }
    }

    // --- the game's process ------------------------------------------------------------------------

    /** The pid of the game's process (":game") while it runs, else 0. */
    private int gameProcess() {
        final ActivityManager am = getSystemService(ActivityManager.class);
        final java.util.List<ActivityManager.RunningAppProcessInfo> all =
                am == null ? null : am.getRunningAppProcesses();
        if (all != null) {
            final String name = getPackageName() + ":game";
            for (ActivityManager.RunningAppProcessInfo info : all) {
                // One just ended still lists for a moment: it is no longer a game to Continue.
                if (!name.equals(info.processName) || info.pid == endedGame) continue;
                if (gameTaskAlive(am)) return info.pid;
                // Swiped from the recent apps: the task is gone, but some systems (MIUI) leave the
                // process behind with no game in it. Its runtime has already started once, so it must
                // not be reused; end it and start fresh.
                CrashReport.endedOnPurpose(this, info.pid);
                android.os.Process.killProcess(info.pid);
                endedGame = info.pid;
                return 0;
            }
        }
        return 0;
    }

    /** A task of this app still holds the game (paused behind this screen, or in a task of its own). */
    private boolean gameTaskAlive(ActivityManager am) {
        final String game = GameActivity.class.getName();
        for (ActivityManager.AppTask task : am.getAppTasks()) {
            try {
                final ActivityManager.RecentTaskInfo info = task.getTaskInfo();
                if (info == null) continue;
                if (info.numActivities > 1
                        || (info.baseActivity != null && game.equals(info.baseActivity.getClassName()))
                        || (info.topActivity != null && game.equals(info.topActivity.getClassName()))) {
                    return true;
                }
            } catch (IllegalArgumentException gone) {
                // The task ended while we looked.
            }
        }
        return false;
    }

    /** Ends a game still running in the background, so the next start is a fresh one. */
    void endGame() {
        final int pid = gameProcess();
        if (pid != 0) {
            GpuDrivers.endedOnPurpose(this);
            CrashReport.endedOnPurpose(this, pid);
            android.os.Process.killProcess(pid);
            endedGame = pid;
        }
    }

    // --- notices before playing --------------------------------------------------------------------

    /**
     * Adreno 5xx on Android 10 (DeviceProfile.oldAdreno5): not supported, said once, with Play Anyway
     * running `play` on OpenGL ES. True when the notice is showing.
     */
    private boolean warnOldGpu(Runnable play) {
        final String gpu = settings.gpuName();
        if (!DeviceProfile.oldAdreno5(gpu)) return false;
        final SharedPreferences prefs = getSharedPreferences("gpu_check", MODE_PRIVATE);
        if (gpu.equals(prefs.getString("warned", null))) return false;
        prefs.edit().putString("warned", gpu).apply();
        new Sheet(this, Tr.t("This GPU isn't supported"),
                gpu + Tr.t(" on Android 10 has a Vulkan driver that stops the game on its first screens. "
                        + "The game tries OpenGL ES instead, which may be slower or still close."))
                .action(Tr.t("Play Anyway"), null, true, false, play)
                .action(Tr.t("Cancel"), null, false, false, this::refresh)
                .onCancel(this::refresh)
                .show();
        return true;
    }

    /**
     * Asks for "All files access" and cannot be dismissed: the log, saves and textures live in
     * /sdcard/SB3UtageINDO. The start carries on once it is given.
     */
    private void requireAccess() {
        if (accessSheet != null) accessSheet.dismiss();
        final Sheet sheet = new Sheet(this, Tr.t("Allow file access first"), Tr.t("The game writes its log to the ")
                + AppFiles.HOME
                + Tr.t(" folder on your phone's storage, so problems can be reported."))
                .step("1", Tr.t("Open Settings"), AppFiles.fileAccessStep())
                .step("2", Tr.t("Come back"), Tr.t("The game starts by itself."))
                .cancelable(false);
        accessSheet = sheet;
        sheet.action(Tr.t("Open Settings"), null, true, false, () -> {
                    accessSheet = null;
                    waitingPlayAccess = true;
                    if (android.os.Build.VERSION.SDK_INT < 30) {
                        AppFiles.requestLegacyFileAccess(this);
                        return;
                    }
                    try {
                        startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                                Uri.parse("package:" + getPackageName())));
                    } catch (ActivityNotFoundException e) {
                        waitingPlayAccess = false;
                        try {
                            startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
                        } catch (ActivityNotFoundException ignored) {
                            Toast.makeText(this, Tr.t("Open Settings > Apps > special access > All files access"),
                                    Toast.LENGTH_LONG).show();
                        }
                    }
                });
        sheet.show();
    }

    /** Legacy storage permission (Android 10): carry on once answered. */
    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (waitingPlayAccess) {
            waitingPlayAccess = false;
            next();
        } else if (waitingFileAccess && AppFiles.hasFileAccess(this)) {
            waitingFileAccess = false;
            browseDisc();
        }
    }

    /** A short message in the Sheet look, with one button; `then` runs when it goes (may be null). */
    private void message(String title, String body, Runnable then) {
        final Sheet sheet = new Sheet(this, title, body).action(Tr.t("OK"), null, true, false, null);
        if (then != null) sheet.onDismiss(then);
        sheet.show();
    }

    /** A determinate progress bar in the accent colour. */
    private ProgressBar progressBar() {
        final ProgressBar bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setProgressTintList(ColorStateList.valueOf(Ui.GRAB));  // ImGui: the grab's blue on a frame
        bar.setProgressBackgroundTintList(ColorStateList.valueOf(Ui.FRAME));
        bar.setIndeterminateTintList(ColorStateList.valueOf(Ui.GRAB));
        bar.setMax(1000);
        return bar;
    }

    /** A progress bar and a line under it, for a Sheet. */
    private LinearLayout progressBox(ProgressBar bar, TextView label) {
        final LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.addView(bar, matchWidth(dp(4)));
        label.setGravity(Gravity.START);
        label.setTextColor(MUTED);
        box.addView(label, matchWidth(dp(6)));
        return box;
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) SystemBars.show(getWindow());
    }

    // --- updates -------------------------------------------------------------------------------

    /** Runs what follows the update check, once. */
    private void finishCheck() {
        final Runnable after = afterCheck;
        afterCheck = null;
        updating = false;
        refresh();
        if (after != null) after.run();
    }

    /** The latest GitHub release: installs it when newer. `automatic`: at app start, quiet unless there is news. */
    private void checkForUpdates(boolean automatic) {
        if (!BuildConfig.ONLINE_UPDATES) {
            if (!automatic) {
                message(Tr.t("Updates are sent by hand for now"),
                        Tr.t("New versions come straight from the developer. Install the new APK over this one; "
                                + "your settings and saves stay."), this::finishCheck);
            } else {
                finishCheck();
            }
            return;
        }
        if (updating) {
            return;
        }
        updating = true;
        refresh();
        new Thread(() -> {
            Updater.Release found = null;
            String failure = null;
            try {
                found = Updater.latest();
            } catch (Exception e) {
                failure = e.getMessage();
            }
            final Updater.Release release = found;
            final String error = failure;
            main.post(() -> {
                if (isFinishing()) return;
                if (automatic && afterCheck == null && release != null && !release.required(Updater.installedVersion(this))) {
                    return;  // answered after the start went on without it
                }
                updating = false;
                refresh();
                final String installed = Updater.installedVersion(this);
                if (release != null && release.apkUrl != null && Updater.isNewer(release.version, installed)) {
                    if (release.required(installed)) {
                        afterCheck = null;
                        requireUpdate(release);
                    } else if (!automatic || settings.autoUpdate()) {
                        startUpdate(release);
                    } else if (!release.version.equals(settings.offeredUpdate())) {
                        settings.setOfferedUpdate(release.version);
                        new Sheet(this, APP + " " + release.version + Tr.t(" is available"),
                                Tr.t("Your saves and settings stay."))
                                .action(Tr.t("Update"), null, true, false, () -> startUpdate(release))
                                .action(Tr.t("Not Now"), null, false, false, this::finishCheck)
                                .onCancel(this::finishCheck)
                                .show();
                    } else {
                        finishCheck();
                    }
                } else if (!automatic) {
                    if (error != null) {
                        message(Tr.t("Couldn't check for updates"), error, this::finishCheck);
                    } else if (release == null || release.apkUrl == null) {
                        message(Tr.t("No Android download"), Tr.t("The latest release has no Android download."),
                                this::finishCheck);
                    } else {
                        new Sheet(this, Tr.t("You're up to date"), APP + " " + installed + Tr.t(" is the latest version."))
                                .action(Tr.t("OK"), null, true, false, null)
                                .onDismiss(this::finishCheck)
                                .show();
                    }
                } else {
                    finishCheck();
                }
            });
        }, "update-check").start();
    }

    /** An update this version must take: the game waits for it, and its sheet can't be put away. */
    private Updater.Release requiredUpdate;

    private void requireUpdate(Updater.Release release) {
        requiredUpdate = release;
        new Sheet(this, Tr.t("Update required"),
                Tr.t("This version can't be played any more. Install ") + APP + " " + release.version
                        + Tr.t(" to keep playing; your saves and settings stay."))
                .action(Tr.t("Update"), null, true, false, () -> startUpdate(release))
                .cancelable(false)
                .show();
    }

    private void startUpdate(Updater.Release release) {
        final boolean required = release == requiredUpdate;
        if (!Updater.canInstall(this)) {
            final Sheet allow = new Sheet(this, APP + " " + release.version + Tr.t(" is available"),
                    Tr.t("To install updates, let SB3 UTAGE:INDO install apps."))
                    .step("1", Tr.t("Open Settings"), Tr.t("Turn on Allow from this source."))
                    .step("2", Tr.t("Come back"), Tr.t("The update carries on by itself."))
                    .action(Tr.t("Open Settings"), null, true, false, () -> {
                        waitingUpdate = release;
                        startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:" + getPackageName())));
                    });
            if (required) allow.cancelable(false);
            else allow.action(Tr.t("Not Now"), null, false, false, this::finishCheck).onCancel(this::finishCheck);
            allow.show();
            return;
        }
        final ProgressBar bar = progressBar();
        bar.setIndeterminate(true);
        final TextView label = text(Tr.t("Downloading…"), 14);
        final Sheet sheet = new Sheet(this, Tr.t("Updating to ") + APP + " " + release.version,
                Tr.t("Your saves and settings stay."))
                .view(progressBox(bar, label))
                .cancelable(false);
        sheet.show();
        new Thread(() -> {
            String failure = null;
            try {
                Updater.downloadAndInstall(getApplicationContext(), release, (done, total) -> main.post(() -> {
                    bar.setIndeterminate(total <= 0);
                    if (total > 0) {
                        bar.setProgress((int) (done * 1000 / total));
                        label.setText(String.format(Locale.US, Tr.t("Downloading… %d of %d MB"),
                                done >> 20, total >> 20));
                    }
                }));
            } catch (Exception e) {
                failure = e.getMessage();
            }
            final String error = failure;
            main.post(() -> {
                if (error != null) {
                    sheet.dismiss();
                    message(Tr.t("The update failed"), error,
                            requiredUpdate != null ? () -> requireUpdate(requiredUpdate) : this::finishCheck);
                    return;
                }
                // The sheet stays up while Android installs: on success it ends this app; if the
                // install fails or the player cancels, UpdateReceiver closes it (installEnded).
                bar.setIndeterminate(false);
                bar.setProgress(1000);
                label.setText(Tr.t("Installing… SB3 UTAGE:INDO closes when the update is in."));
                showState(Tr.t("Installing ") + APP + " " + release.version + "…");
                installing = sheet;
                afterInstall = requiredUpdate != null ? () -> requireUpdate(requiredUpdate) : this::finishCheck;
            });
        }, "update-download").start();
    }

    /** The update sheet while Android installs, so a failed or cancelled install can close it. */
    private static Sheet installing;
    /** What follows a failed or cancelled install: the required update's sheet again, or the game. */
    private static Runnable afterInstall;

    /** UpdateReceiver: the install failed or was cancelled. Main thread. */
    static void installEnded() {
        if (installing != null) {
            try {
                installing.dismiss();
            } catch (RuntimeException ignored) {
                // the screen went away meanwhile
            }
            installing = null;
        }
        final Runnable after = afterInstall;
        afterInstall = null;
        if (after != null) {
            try {
                after.run();
            } catch (RuntimeException ignored) {
                // the screen went away meanwhile
            }
        }
    }

    private String versionText() {
        try {
            final PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), 0);
            return info.versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "";
        }
    }

    // --- the game file -------------------------------------------------------------------------

    /**
     * The app's own file browser (FileBrowser), opening on Download. It needs "All files access";
     * without it the player can allow it, or use the system's picker instead.
     */
    private void pickDisc() {
        refresh();
        if (AppFiles.hasFileAccess(this)) {
            browseDisc();
            return;
        }
        new Sheet(this, Tr.t("Allow file access"), Tr.t("To list the folders on this phone and find your ISO or RVZ."))
                .step("1", Tr.t("Open Settings"), AppFiles.fileAccessStep())
                .step("2", Tr.t("Come back"), Tr.t("The file browser opens by itself."))
                .action(Tr.t("Open Settings"), null, true, false, () -> {
                    waitingFileAccess = true;
                    if (android.os.Build.VERSION.SDK_INT < 30) {
                        AppFiles.requestLegacyFileAccess(this);
                        return;
                    }
                    try {
                        startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                                Uri.parse("package:" + getPackageName())));
                    } catch (ActivityNotFoundException e) {
                        waitingFileAccess = false;
                        pickWithSystem();
                    }
                })
                .action(Tr.t("Use System Picker"), Tr.t("The phone's own file picker, without the permission"), false, false,
                        this::pickWithSystem)
                .action(Tr.t("Cancel"), null, false, false, null)
                .show();
    }

    private void browseDisc() {
        // Download, where a downloaded dump lands.
        FileBrowser.show(this, FileBrowser.downloads(), file -> chooseHow(Uri.fromFile(file)));
    }

    /**
     * Any file: the system has no type for .rvz, so the file itself is what gets checked. Opens on
     * the phone's Download folder rather than the picker's Recent view, where dumps usually are.
     */
    private void pickWithSystem() {
        final Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.putExtra(android.provider.DocumentsContract.EXTRA_INITIAL_URI, android.provider.DocumentsContract
                .buildDocumentUri("com.android.externalstorage.documents", "primary:Download"));
        intent.putExtra("android.content.extra.SHOW_ADVANCED", true);  // list the phone's own storage
        startActivityForResult(intent, REQUEST_DISC);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_DISC && resultCode == RESULT_OK && data != null && data.getData() != null) {
            chooseHow(data.getData());
        }
    }

    /**
     * Extract (the game unpacked once, about 4 GB: the fastest loading) or Read (straight from the ISO
     * or RVZ, which stays where it is: no space needed, for phones without 4 GB to spare).
     */
    private void chooseHow(Uri disc) {
        final boolean unpacked = AppFiles.isGameRoot(AppFiles.gameDir(this));
        new Sheet(this, Tr.t("How to load the game"), Tr.t("Both play the same game, and your saves stay."))
                .action(Tr.t("Extract"), Tr.t("Unpacks the game once, about 4 GB. The fastest loading."), true, false,
                        () -> loadGame(disc))
                .action(Tr.t("Read from File"), unpacked
                                ? Tr.t("Plays straight from the ISO or RVZ, which must stay where it is. Needs no space; "
                                        + "the unpacked copy (4 GB) is deleted.")
                                : Tr.t("Plays straight from the ISO or RVZ, which must stay where it is. Needs no space."),
                        false, false, () -> readInPlace(disc))
                .action(Tr.t("Cancel"), null, false, false, this::refresh)
                .onCancel(this::refresh)
                .show();
    }

    /** Read mode: the file is checked and kept (its grant too), and the unpacked copy goes. */
    private void readInPlace(Uri disc) {
        endGame();  // a game still running from the old file must not carry on with the new one
        final ProgressBar bar = progressBar();
        bar.setIndeterminate(true);
        final Sheet dialog = new Sheet(this, Tr.t("Loading your game"), Tr.t("Looking at the game file…"))
                .view(progressBox(bar, text("", 14)))
                .cancelable(false);
        dialog.show();
        importing = true;
        refresh();
        new Thread(() -> {
            String result;
            try {
                result = useInPlace(disc);
            } catch (Exception e) {
                result = e.getMessage() != null ? e.getMessage() : e.toString();
            }
            final String failure = result;
            main.post(() -> {
                importing = false;
                dialog.dismiss();
                refresh();
                if (failure != null) {
                    message(Tr.t("Couldn't load the game"), failure + Tr.t("\n\nNothing was changed."), null);
                } else {
                    warned = false;
                    launched = false;
                    next();
                }
            });
        }, "game-read").start();
    }

    /** Null, or what went wrong. */
    private String useInPlace(Uri disc) throws IOException {
        try (ParcelFileDescriptor file = getContentResolver().openFileDescriptor(disc, "r")) {
            if (file == null) throw new IOException(Tr.t("Couldn't open that file."));
            final String problem = AppFiles.headerProblem(DiscImport.readHeader(file.getFd()));
            if (problem != null) return problem;
        }
        if ("content".equals(disc.getScheme())) {
            try {
                // The system picker's grant, kept across restarts: the game opens the file every start.
                getContentResolver().takePersistableUriPermission(disc, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            } catch (SecurityException e) {
                return Tr.t("This file's location can't be kept for later. Move it to the phone's storage "
                        + "(Download), or choose Extract.");
            }
        }
        final Uri old = AppFiles.gameSource(this);
        if (old != null && !old.equals(disc)) AppFiles.clearGameSource(this);
        AppFiles.setGameSource(this, disc);
        AppFiles.deleteRecursively(AppFiles.gameDir(this));
        return null;
    }

    private void loadGame(Uri disc) {
        endGame();  // a game still running from the old file must not carry on with the new one
        final ProgressBar bar = progressBar();
        bar.setIndeterminate(true);
        final TextView label = text(Tr.t("Looking at the game file…"), 14);
        final AtomicBoolean cancel = new AtomicBoolean();
        final Sheet dialog = new Sheet(this, Tr.t("Loading your game"),
                Tr.t("Unpacked once, about 4 GB. Keep the app open until it is done."))
                .view(progressBox(bar, label))
                .cancelable(false);
        dialog.actionStay(Tr.t("Cancel"), true, name -> {
            cancel.set(true);
            name.setText(Tr.t("Stopping…"));
            label.setText(Tr.t("Stopping…"));
        });
        dialog.show();
        importing = true;
        refresh();
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        new Thread(() -> {
            String result;
            try {
                result = unpack(disc, (done, total) -> {
                    main.post(() -> {
                        if (cancel.get()) {
                            return;
                        }
                        bar.setIndeterminate(false);
                        bar.setProgress((int) (done * 1000 / Math.max(total, 1)));
                        label.setText(String.format(Locale.ROOT, Tr.t("%.1f of %.1f GB"),
                                done / (double) (1 << 30), total / (double) (1 << 30)));
                    });
                    return !cancel.get();
                });
            } catch (Exception e) {
                AppFiles.deleteRecursively(stagingDir());
                result = e.getMessage();
            }
            final String failure = result;
            main.post(() -> {
                importing = false;
                dialog.dismiss();
                getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                refresh();
                if (failure != null && !failure.equals(DiscImport.CANCELLED)) {
                    message(Tr.t("Couldn't load the game"), failure + Tr.t("\n\nNothing was changed."), null);
                } else if (failure == null) {
                    // A new game file: its notices again, then the game.
                    warned = false;
                    launched = false;
                    next();
                }
            });
        }, "game-import").start();
    }

    private File stagingDir() { return new File(AppFiles.dataDir(this), "game.importing"); }

    /** Into the staging folder, checked, then swapped in; saves stay. Null, or what went wrong. */
    private String unpack(Uri disc, DiscImport.Listener listener) throws IOException {
        try (ParcelFileDescriptor file = getContentResolver().openFileDescriptor(disc, "r")) {
            if (file == null) throw new IOException(Tr.t("Couldn't open that file."));
            final String problem = AppFiles.headerProblem(DiscImport.readHeader(file.getFd()));
            if (problem != null) return problem;
            final File staging = stagingDir();
            AppFiles.deleteRecursively(staging);
            if (!staging.mkdirs()) throw new IOException(Tr.t("Couldn't create ") + staging);
            final String failure = DiscImport.extract(file.getFd(), staging.getPath(),
                    AppFiles.dataDir(this).getUsableSpace(), listener);
            final String result = failure != null ? failure : install(staging);
            AppFiles.deleteRecursively(staging);
            return result;
        }
    }

    /** The checked game at `root` becomes the game. Null, or why it can't. */
    private String install(File root) throws IOException {
        final String problem = AppFiles.gameProblem(root);
        if (problem != null) return problem;
        final File game = AppFiles.gameDir(this);
        AppFiles.deleteRecursively(game);
        if (!root.renameTo(game)) throw new IOException(Tr.t("Couldn't move the game into place."));
        AppFiles.clearGameSource(this);  // unpacked: Read mode's file is no longer needed
        return null;
    }

    // --- views ---------------------------------------------------------------------------------

    private TextView text(String value, int sp) {
        final TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        view.setTextColor(Color.WHITE);
        view.setGravity(Gravity.CENTER_HORIZONTAL);
        return view;
    }

    // The app's colors (Ui), under the names the other screens use.
    static final int ACCENT = Ui.ACCENT;
    static final int SURFACE = Ui.SURFACE;
    static final int BACKGROUND = Ui.BG;
    static final int RAISED = Ui.ACTIVE;
    static final int MUTED = Ui.SECONDARY;
    static final int FAINT = Ui.MUTED;
    static final int GREEN = Ui.SUCCESS;
    static final int AMBER = Ui.WARNING;
    static final Typeface MEDIUM = Ui.MEDIUM;

    private LinearLayout.LayoutParams matchWidth(int topMargin) {
        return Ui.matchWidth(topMargin);
    }

    private int dp(int value) {
        return Ui.dp(this, value);
    }
}
