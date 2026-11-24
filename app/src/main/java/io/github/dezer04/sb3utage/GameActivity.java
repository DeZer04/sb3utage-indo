package io.github.dezer04.sb3utage;

import android.content.Context;
import android.content.Intent;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.os.Process;
import android.system.Os;
import android.util.Log;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.Toast;

import org.libsdl.app.SDLActivity;

/**
 * The game: SDL's activity running libmain.so (the translated game, its runtime, SDL and Dawn,
 * linked into one library), with the on-screen remote on top.
 */
public final class GameActivity extends SDLActivity
        implements TouchControlsView.Listener {
    private static final String TAG = "Basara";

    /** Player 1's on-screen remote (runtime/src/android/android_bridge.cpp); shake and tilt stay off. */
    static native void nativeSetTouchState(int buttons, boolean shake, float tilt);
    static native void nativeSetTouchSticks(float leftX, float leftY, float rightX, float rightY);

    /** The Display menu: aspect, render scale (480 lines per 1x), FPS counter (DisplaySettings). */
    static native void nativeApplyDisplaySettings(int aspect, float renderScale, boolean showFps,
            boolean dynamicResolution, int overlayItems, boolean frameGraph, boolean thermalControl,
            int textureFilter);

    /** Settings > Cheats (runtime/src/cheats.cpp); a new onceSeq sets the money once at the next frame. */
    static native void nativeApplyCheats(int money, int amount, int onceSeq, boolean infiniteHp,
            boolean infiniteBasara, boolean unlockAll);

    /** Settings > Display > Camera Distance (1 = the game's camera). */
    static native void nativeSetCameraDistance(float distance);
    /** Settings > Performance > Game Speed, in percent (100-200). */
    static native void nativeSetGameSpeed(int percent);
    /** Settings > Controls > Rumble (AppSettings.RUMBLE_*). */
    static native void nativeSetRumble(int mode);
    /** The Wii Remote motors the game has on now (bit 0 = the player's). */
    static native int nativeRumbleBits();
    /** Settings > Controls > Two Players (Touch + Gamepad). */
    static native void nativeSetTouchPlusPad(boolean on);
    /** Lock target on or off (R3, the touch LOCK button); returns whether it is now on. */
    static native boolean nativeToggleLockOn();
    static native void nativeSetDisableFog(boolean disabled);
    static native void nativeSetReduceEffects(boolean on);

    /** Settings > Controls > Gamepad Buttons (GamepadButtons): "a=b,b=a,...", "" = the default layout. */
    static native void nativeSetGamepadMap(String map);

    /** The in-game settings: upscaler (0 off, 1 FSR Light, 2 FSR Full, 3 SGSR), frameskip (0 off, 1 auto, 2 30 FPS lock). */
    static native void nativeApplyLiveSettings(int upscaler, int frameskip);
    /** Sustained Performance while playing: the CPU boost lets go (true) or comes back (cpu_boost.cpp). */
    static native void nativeSetSustained(boolean on);
    /** VSync while playing, from the next present. */
    static native void nativeSetVSync(boolean on);

    /** What this phone is called in LAN room lists (netplay). */
    static native void nativeSetDeviceName(String name);

    /** Whether this run is a LAN session, and leaving one (the host keeps the session's save). */
    static native boolean nativeSessionActive();
    static native void nativePrepareToLeave();
    /** A tap on the game's menus, as fractions of the screen. */
    static native void nativeTap(float x, float y);
    static native void nativePointer(float x, float y, boolean held);
    /** Whether a menu that taps drive is up (the remote is hidden then). */
    static native boolean nativeTapScreen();
    /** {render scale, show FPS, aspect} after the game's own settings window changed them, else null. */
    static native float[] nativeTakeSettings();
    /**
     * The app left the screen (true) or came back (false). Leaving, the game writes a backup Quick Save
     * of the progress so far (deleted again when the app comes back) and pauses; nativeGamePaused says
     * when it has (runtime/src/host_suspend.h).
     */
    static native void nativeSetBackground(boolean background);
    static native boolean nativeGamePaused();
    /** The overlay's battery: many phones deny the power_supply files to apps, so it comes from here. */
    static native void nativeSetBattery(int percent, float tempC);
    /** The Back menu: pause the game while it is open (true), carry on (false). */
    static native void nativeSetMenuPause(boolean paused);

    /** How long leaving the app waits for the backup save and the pause, before SDL's own pause. */
    private static final long SUSPEND_WAIT_MS = 1500;

    private WifiManager.MulticastLock multicastLock;

    private AppSettings settings;
    private TouchControlsView touch;
    /** "● REC 1:23" while the in-app recorder runs (GameRecorder); a tap stops it. */
    private android.widget.TextView recBadge;
    /** The badge with a wider touch area around it (it sits at the screen's edge). */
    private android.widget.FrameLayout recArea;
    private final android.os.Handler recTick = new android.os.Handler(android.os.Looper.getMainLooper());
    private boolean nativeReady;
    private boolean lockOn;  // lock target is on (onLock)
    private int touchButtons;

    /**
     * Display Resolution: the game draws into a surface of that many lines and the compositor stretches
     * it to the screen for free (ARMSX2's hardware scaler), so the swapchain and every full-screen pass
     * (presentation, snapshot, overlay) cost less GPU time. Nothing when it is at or above the screen.
     */
    /** The Display Resolution in use (0: the screen's own), so a change while playing resizes once. */
    private int appliedLines = -1;

    /**
     * Display Resolution: the surface's own size, below the screen's. Changed while playing, the
     * surface is resized and the renderer makes its swapchain again, as after a rotation.
     */
    private void applyDisplayResolution() {
        if (mSurface == null) return;
        int lines = settings.displayLines();
        final android.util.DisplayMetrics m = new android.util.DisplayMetrics();
        getWindowManager().getDefaultDisplay().getRealMetrics(m);
        final int longSide = Math.max(m.widthPixels, m.heightPixels), shortSide = Math.min(m.widthPixels, m.heightPixels);
        if (shortSide <= 0 || lines >= shortSide * 0.95f) lines = 0;
        if (lines == appliedLines) return;
        final boolean first = appliedLines < 0;
        appliedLines = lines;
        if (lines <= 0) {
            if (!first) mSurface.getHolder().setSizeFromLayout();  // the screen's own size again
            if (!first) Log.i(TAG, "display resolution: the screen's own");
            return;
        }
        final int width = Math.round(longSide * (float) lines / shortSide) & ~1;
        mSurface.getHolder().setFixedSize(width, lines);  // the game is landscape (sensorLandscape)
        Log.i(TAG, "display resolution: " + width + "x" + lines + " on a " + longSide + "x" + shortSide + " screen");
    }

    /**
     * Always landscape, either way up by the sensor, whether or not auto-rotate is on. SDL would ask
     * for USER_LANDSCAPE, which stays on one side while the player has rotation locked.
     */
    @Override
    public void setOrientationBis(int w, int h, boolean resizable, String hint) {
        setRequestedOrientation(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
    }

    private static void notePrepareError(StringBuilder errors, String step, Exception e) {
        Log.e(TAG, "could not prepare the game's files (" + step + ")", e);
        errors.append(step).append(": ").append(e).append('\n')
                .append(Log.getStackTraceString(e)).append('\n');
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        CrashReport.installJavaHandler(this);
        CrashReport.testCrashIfAsked();
        settings = new AppSettings(this);
        Tr.init(this);  // the in-game menu speaks the launcher's language
        // Each step on its own: one failing (a full disk while the runtime files are copied after an
        // update) used to skip Config.toml and the env below, and the game then stopped at once with
        // "No DVD root is configured". The failures go to the run's log folder for tester reports.
        final StringBuilder prepareErrors = new StringBuilder();
        java.io.File runLogs = null;
        try {
            runLogs = AppFiles.newRunLogDir();
        } catch (Exception e) {
            notePrepareError(prepareErrors, "newRunLogDir", e);
        }
        final java.io.File logs = runLogs;
        try {
            AppFiles.prepareRuntime(this);
        } catch (Exception e) {
            notePrepareError(prepareErrors, "prepareRuntime", e);
        }
        try {
            final String driverOff = GpuDrivers.checkLastStart(this, settings);
            if (driverOff != null) Toast.makeText(this, driverOff, Toast.LENGTH_LONG).show();
            GpuDrivers.applyToGame(this, settings);
        } catch (Exception e) {
            notePrepareError(prepareErrors, "gpu drivers", e);
        }
        try {
            AppFiles.writeConfig(this, settings);
        } catch (Exception e) {
            notePrepareError(prepareErrors, "writeConfig", e);
        }
        // Saves: back after a new install or Clear data (from SB3UtageINDO/Saves/Auto), and the last
        // session's save copied out, before the game opens its NAND.
        if (SaveData.autoRestore(this)) {
            Toast.makeText(this, Tr.t("Your save was restored from SB3UtageINDO/Saves/Auto."), Toast.LENGTH_LONG).show();
        }
        SaveData.autoBackup(this);
        try {
            DevTools.onGameStart(this);  // before the runtime reads env.txt
        } catch (Exception e) {
            notePrepareError(prepareErrors, "DevTools", e);
        }
        if (prepareErrors.length() > 0) {
            Toast.makeText(this, "Could not prepare the game's files: " + prepareErrors.toString().split("\n", 2)[0],
                    Toast.LENGTH_LONG).show();
            if (logs != null) {
                try (java.io.FileOutputStream out = new java.io.FileOutputStream(new java.io.File(logs, "prepare_errors.txt"))) {
                    out.write(prepareErrors.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
                } catch (Exception ignored) {
                }
            }
        }
        try {
            // Read by runtime/src/platform/host_platform.cpp before anything else starts.
            Os.setenv("WIICOMPILED_RUNTIME_DIR", AppFiles.runtimeDir(this).getAbsolutePath(), true);
            Os.setenv("WIICOMPILED_DATA_DIR", AppFiles.dataDir(this).getAbsolutePath(), true);
            // The driver's Vulkan pipeline cache outside the runtime folder, which prepareRuntime wipes
            // on every APK update: kept there, each update recompiled ~1300 pipelines in the driver on
            // its first start (about a minute of stutter on an Adreno 710).
            Os.setenv("AURORA_VK_CACHE_DIR", new java.io.File(AppFiles.dataDir(this), "Cache").getAbsolutePath(), true);
            // Read mode: the game file, opened here (the system picker's grant is the app's, not a path
            // the game could open) and kept open while the game runs; the runtime reads it in place.
            final android.net.Uri source = AppFiles.gameSource(this);
            if (source != null) {
                try {
                    gameFile = getContentResolver().openFileDescriptor(source, "r");
                } catch (Exception e) {
                    Log.e(TAG, "could not open the game file " + source, e);
                }
                // Not opened: fd -1, so the game says the file can't be opened rather than that no folder is set.
                Os.setenv("BASARA_DVD_IMAGE", "/proc/self/fd/" + (gameFile != null ? gameFile.getFd() : -1), true);
            }
            // Written by the Vulkan renderer when the GPU stops responding (GpuDrivers.checkGpuLost).
            Os.setenv("AURORA_GPU_LOST_FILE", GpuDrivers.gpuLostFile(this).getAbsolutePath(), true);
            // Disable Fog keys the shaders, so the renderer needs it before the cached ones load
            // (gfx/pipeline_cache.cpp); nativeSetDisableFog only comes once the game runs.
            Os.setenv("AURORA_DISABLE_FOG", settings.disableFog() ? "1" : "0", true);
            if (logs != null) Os.setenv("BASARA_LOG_DIR", logs.getAbsolutePath(), true);
            // HD Textures keeps its own cache folder; without Custom Textures it is the only one indexed.
            final java.io.File hdCache = settings.hdTextures() != 0 ? AppFiles.hdCacheDir() : null;
            final java.io.File textures = settings.customTextures() ? AppFiles.textureDir() : hdCache;
            if (textures != null) Os.setenv("BASARA_TEXTURE_DIR", textures.getAbsolutePath(), true);
            // Only the mods ticked in Settings, in their order (TexturePacks).
            if (settings.customTextures() && textures != null) {
                Os.setenv("BASARA_TEXTURE_PACKS",
                        TexturePacks.envValue(TexturePacks.load(settings, textures), textures), true);
            }
            if (hdCache != null) Os.setenv("BASARA_HD_CACHE_DIR", hdCache.getAbsolutePath(), true);
            // Sustained Performance: the system holds steady clocks, so the game thread is not pinned to
            // the fastest cores and no ADPF boost is asked for (runtime/src/cpu_boost.cpp). env.txt wins.
            appliedSustained = sustainedMode();
            if (appliedSustained) Os.setenv("BASARA_CPU_BOOST", "0", false);
            if (settings.recordingAudio()) Os.setenv("BASARA_AUDIO_RECORDABLE", "1", false);
            // Low RAM (ARMSX2 caps its texture pools on weak phones): a smaller cache for replaced textures.
            final long ram = DeviceProfile.ramMb(this);
            if (ram > 0 && ram < 4608) Os.setenv("AURORA_REPLACEMENT_CACHE_MB", settings.hdTextures() != 0 ? "192" : "512", false);
            // Upload Memory: Auto leaves the choice to the start-up measurement (vk_webgpu.cpp).
            if (settings.uploadMemory() != 0) {
                Os.setenv("AURORA_VK_CACHED_STAGING", settings.uploadMemory() == 2 ? "1" : "0", false);
            }
            try {
                // For the log's device line: the screen's refresh rate.
                Os.setenv("BASARA_DISPLAY_HZ", String.valueOf(Math.round((android.os.Build.VERSION.SDK_INT >= 30 ? getDisplay()
                        : getWindowManager().getDefaultDisplay()).getRefreshRate())), true);
            } catch (Exception ignored) {
            }
        } catch (Exception e) {
            Log.e(TAG, "could not prepare the game's files", e);
            Toast.makeText(this, "Could not prepare the game's files: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
        super.onCreate(savedInstanceState);
        applyDisplayResolution();
        nativeReady = !SDLActivity.mBrokenLibraries;
        if (nativeReady) {
            nativeSetDeviceName(deviceName());
        }
        // LAN rooms are found with broadcasts, which many Wi-Fi drivers drop unless an app holds this.
        final WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (wifi != null) {
            multicastLock = wifi.createMulticastLock("basara-lan");
            multicastLock.setReferenceCounted(false);
            multicastLock.acquire();
        }

        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        touch = new TouchControlsView(this);
        touch.setListener(this);
        applyControlSettings();
        addContentView(touch, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        // Small and faint in the top right corner, over the bar beside the picture: it is not recorded.
        recBadge = Ui.text(this, "", 10, android.graphics.Color.WHITE);
        recBadge.setTypeface(Ui.MEDIUM);
        recBadge.setPadding(dp(7), dp(2), dp(7), dp(2));
        recBadge.setBackground(Ui.box(this, 0x80B71C1C, 0, Ui.RADIUS_PILL));
        recBadge.setAlpha(0.7f);
        recArea = new android.widget.FrameLayout(this);
        recArea.setPadding(dp(16), dp(4), dp(8), dp(16));
        recArea.addView(recBadge);
        recArea.setVisibility(android.view.View.GONE);
        recArea.setOnClickListener(v -> stopRecording());
        addContentView(recArea, new android.widget.FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                android.view.Gravity.TOP | android.view.Gravity.END));
        layoutEditor = new LayoutEditor(this, touch, new LayoutEditor.Host() {
            @Override public AppSettings settings() { return settings; }
            @Override public void onEditorClosed() { resumeFromMenu(); }
        });
    }

    // --- the in-app recorder ----------------------------------------------------------------------

    /** Record in the menu: starts a recording, or ends the one running. */
    private void toggleRecording() {
        if (GameRecorder.recording()) {
            stopRecording();
            return;
        }
        final String problem = GameRecorder.start(this, settings.recordQuality());
        if (problem != null) {
            Toast.makeText(this, problem, Toast.LENGTH_LONG).show();
            return;
        }
        recTick.removeCallbacks(tickRecording);
        recTick.post(tickRecording);
    }

    private final Runnable tickRecording = new Runnable() {
        @Override
        public void run() {
            final long ms = GameRecorder.elapsedMs();
            if (ms < 0) {
                recArea.setVisibility(android.view.View.GONE);
                return;
            }
            recBadge.setText(String.format(java.util.Locale.ROOT, "\u25CF REC %d:%02d", ms / 60000, ms / 1000 % 60));
            recArea.setVisibility(android.view.View.VISIBLE);
            recTick.postDelayed(this, 500);
        }
    };

    /** Ends the recording; the file is finished off the UI thread, then named in a toast. */
    private void stopRecording() {
        if (!GameRecorder.recording()) return;
        recTick.removeCallbacks(tickRecording);
        recArea.setVisibility(android.view.View.GONE);
        final Context app = getApplicationContext();
        new Thread(() -> {
            final java.io.File saved = GameRecorder.stop(app);
            runOnUiThread(() -> showSaved(app, saved));
        }, "SB3 recorder stop").start();
    }

    private static void showSaved(Context context, java.io.File saved) {
        Toast.makeText(context, saved != null
                ? Tr.t("Recording saved: ") + saved.getAbsolutePath().replace("/storage/emulated/0/", "")
                : Tr.t("The recording was empty."), Toast.LENGTH_LONG).show();
    }

    /** The touch layout editor, over the paused game (it carries on when the editor closes). */
    private void startLayoutEdit() {
        touch.release();
        menuOpen = true;
        setMenuPause(true);
        layoutEditor.open();
    }

    /** SDL is linked into libmain.so, so that one library is all there is to load. */
    @Override
    protected String[] getLibraries() {
        return new String[] {"main"};
    }

    // The game's menus take taps and the remote hides while they are up; it comes back a moment
    // after they go, so it doesn't blink while one menu screen hands over to the next.
    private final android.os.Handler menuPoll = new android.os.Handler(android.os.Looper.getMainLooper());
    private long lastTapScreen;
    private long lastBattery = -100000;
    private boolean menuOpen;
    private LayoutEditor layoutEditor;

    private void setMenuPause(boolean paused) {
        if (!nativeReady) return;
        try {
            nativeSetMenuPause(paused);
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "menu pause bridge missing from libmain.so", e);
        }
    }

    private void pushBattery() {
        final Intent battery = registerReceiver(null,
                new android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (battery == null) return;
        final int level = battery.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1);
        final int scale = battery.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, 100);
        final int temp = battery.getIntExtra(android.os.BatteryManager.EXTRA_TEMPERATURE, -10);
        try {
            nativeSetBattery(level >= 0 && scale > 0 ? level * 100 / scale : -1, temp / 10f);
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "battery bridge missing from libmain.so", e);
        }
    }

    // Rumble on the phone (Rumble = Controller and Phone): the game turns the Wii Remote motor on and off
    // as often as every frame, so the vibrator gets short pulses while it is on, refreshed before they
    // end, capped at RUMBLE_MAX_MS of one unbroken buzz, and cancelled when the motor stops.
    private static final long RUMBLE_PULSE_MS = 90, RUMBLE_MAX_MS = 1500;
    private final android.os.Handler rumblePoll = new android.os.Handler(android.os.Looper.getMainLooper());
    private android.os.Vibrator vibrator;
    private long rumbleSince, rumbleUntil;
    private final Runnable pollRumble = new Runnable() {
        @Override
        public void run() {
            final long now = android.os.SystemClock.uptimeMillis();
            boolean on = false;
            if (nativeReady && settings.rumble() == AppSettings.RUMBLE_PHONE) {
                try {
                    on = (nativeRumbleBits() & 1) != 0;
                } catch (UnsatisfiedLinkError e) {
                    return;  // an older libmain.so: no rumble, no more polling
                }
            }
            if (on) {
                if (rumbleSince == 0) rumbleSince = now;
                if (now - rumbleSince < RUMBLE_MAX_MS && now >= rumbleUntil - 20) {
                    if (vibrator == null) vibrator = getSystemService(android.os.Vibrator.class);
                    if (vibrator != null && vibrator.hasVibrator()) {
                        vibrator.vibrate(android.os.VibrationEffect.createOneShot(RUMBLE_PULSE_MS,
                                android.os.VibrationEffect.DEFAULT_AMPLITUDE));
                        rumbleUntil = now + RUMBLE_PULSE_MS;
                    }
                }
            } else {
                stopRumble(now);
            }
            rumblePoll.postDelayed(this, 33);
        }
    };

    private void stopRumble(long now) {
        if (rumbleSince != 0 && vibrator != null && rumbleUntil > now + 30) vibrator.cancel();
        rumbleSince = 0;
        rumbleUntil = 0;
    }

    private final Runnable pollMenu = new Runnable() {
        @Override
        public void run() {
            final long now = android.os.SystemClock.uptimeMillis();
            if (nativeReady) {
                // The game's settings window: keep its choices, the config is rewritten at each start.
                final float[] changed = nativeTakeSettings();
                if (changed != null) {
                    settings.setResolutionScale(changed[0]);
                    settings.setShowFps(changed[1] > 0.5f);
                    if (changed.length > 2) settings.setAspectMode(Math.round(changed[2]));
                    if (changed.length > 3) settings.setSpinningCoins(changed[3] > 0.5f);
                    if (changed.length > 4) settings.setFrameGraph(changed[4] > 0.5f);
                    if (changed.length > 5) settings.setVSync(changed[5] > 0.5f);
                }
            }
            if (nativeReady && now - lastBattery > 10000) {
                lastBattery = now;
                pushBattery();
            }
            if (nativeReady && nativeTapScreen()) {
                lastTapScreen = now;
                touch.setMenuMode(true);
            } else if (now - lastTapScreen > 600) {
                touch.setMenuMode(false);
            }
            menuPoll.postDelayed(this, 100);
        }
    };

    @Override
    public void onTap(float x, float y) {
        if (nativeReady) nativeTap(x, y);
    }

    @Override
    public void onPointer(float x, float y, boolean held) {
        if (nativeReady) nativePointer(x, y, held);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (nativeReady) {
            nativeSetBackground(false);  // the game carries on where it stopped
            if (menuOpen) setMenuPause(true);  // ...unless its menu is still open
            // Back from the start screen (an update check): read the settings file again, it may
            // have been written from the other process.
            settings = new AppSettings(this);
            applyNativeSettings();
        }
        applyControlSettings();
        getWindow().setSustainedPerformanceMode(sustainedMode());
        menuPoll.removeCallbacks(pollMenu);
        menuPoll.post(pollMenu);
        rumblePoll.removeCallbacks(pollRumble);
        rumblePoll.post(pollRumble);
        hideSystemBars();
    }

    @Override
    protected void onPause() {
        // Leaving the app ends a recording, with its file finished before the game pauses (or the
        // process ends, on Quit).
        if (GameRecorder.recording()) {
            recTick.removeCallbacks(tickRecording);
            recArea.setVisibility(android.view.View.GONE);
            showSaved(getApplicationContext(), GameRecorder.stop(this));
        }
        if (nativeReady) {
            // Before SDL's pause stops the game thread: let the game write its backup Quick Save (in
            // case Android ends the app while it is away) and pause itself. Bounded: a save that takes
            // longer is simply not published (the NAND only commits closed files).
            nativeSetBackground(true);
            final long until = android.os.SystemClock.uptimeMillis() + SUSPEND_WAIT_MS;
            while (!nativeGamePaused() && android.os.SystemClock.uptimeMillis() < until) {
                try {
                    Thread.sleep(10);
                } catch (InterruptedException e) {
                    break;
                }
            }
        }
        // The save the game has written so far, copied out of app storage (an uninstall deletes it).
        final android.content.Context app = getApplicationContext();
        new Thread(() -> SaveData.autoBackup(app), "save-copy").start();
        menuPoll.removeCallbacks(pollMenu);
        rumblePoll.removeCallbacks(pollRumble);
        if (vibrator != null) vibrator.cancel();
        rumbleSince = 0;
        rumbleUntil = 0;
        if (touch != null) touch.release();
        super.onPause();
    }

    /** Sustained Performance as the CPU boost has it now (set at start by BASARA_CPU_BOOST). */
    private boolean appliedSustained;
    /** Read mode's game file, open for as long as this process (the game) lives. */
    private static android.os.ParcelFileDescriptor gameFile;

    private boolean sustainedMode() {
        return settings.sustainedPerformance() && AppSettings.sustainedSupported(this);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            hideSystemBars();
        } else if (touch != null) {
            touch.release();  // a dialog or the shade took the screen: let go of every button
        }
    }

    @Override
    public void onBackPressed() {
        onMenu();
    }

    /** SDL takes the Back key as keyboard input before onBackPressed: the Back menu gets it first. */
    @Override
    public boolean dispatchKeyEvent(android.view.KeyEvent event) {
        if (event.getKeyCode() == android.view.KeyEvent.KEYCODE_BACK) {
            if (event.getAction() == android.view.KeyEvent.ACTION_UP && !event.isCanceled()) {
                onMenu();
            }
            return true;
        }
        // R3 (the right stick's click): lock target while Lock Target (Experimental) is on, unless
        // the player gave it to a Classic button.
        if (event.getKeyCode() == android.view.KeyEvent.KEYCODE_BUTTON_THUMBR && settings.lockTarget()
                && !settings.gamepadMapInUse().contains("=rightstick")) {
            if (event.getAction() == android.view.KeyEvent.ACTION_UP && !event.isCanceled()) onLock();
            return true;
        }
        // L3 (the left stick's click; a Classic Controller has none): the camera zoom, unless the
        // player gave it to a Classic button in Gamepad Buttons.
        if (event.getKeyCode() == android.view.KeyEvent.KEYCODE_BUTTON_THUMBL
                && !settings.gamepadMapInUse().contains("=leftstick")) {
            if (event.getAction() == android.view.KeyEvent.ACTION_UP && !event.isCanceled()) onZoom();
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    /**
     * What this process cannot do itself (LauncherActivity.ACTION_*): a new game file, an update check,
     * a save import. The start screen does it and opens the game again; `file` goes with an import.
     */
    void toLauncher(String action, String file) {
        final Intent intent = new Intent(this, LauncherActivity.class).putExtra(LauncherActivity.EXTRA_ACTION, action);
        if (file != null) intent.putExtra(LauncherActivity.EXTRA_FILE, file);
        startActivity(intent);
    }

    /** "Restart": the game starts again in a fresh process, so settings read at start apply. */
    private void confirmRestart(Runnable cancelled) {
        // What Restart will change: the restart-only settings set since the game started.
        final StringBuilder text = new StringBuilder(Tr.t("Restart the game? Progress since your last save is lost."));
        final java.util.Map<String, String> pending = SettingsMenu.pendingRestarts();
        if (!pending.isEmpty()) {
            text.append("\n\n").append(Tr.t("Will change:"));
            for (java.util.Map.Entry<String, String> e : pending.entrySet()) {
                text.append("\n• ").append(e.getKey()).append(": ").append(e.getValue());
            }
        }
        new Sheet(this, Tr.t("Restart"), text.toString())
                .action(Tr.t("Restart"), null, true, false, this::restartGame)
                .action(Tr.t("Cancel"), null, false, false, cancelled)
                .onCancel(cancelled)
                .show();
    }

    /** "Quit": asked first, like Restart, since progress since the last save goes. */
    private void confirmQuit() {
        new Sheet(this, Tr.t("Quit"), Tr.t("Quit the game? Progress since your last save is lost."))
                .action(Tr.t("Quit"), null, true, false, this::quitApp)
                .action(Tr.t("Cancel"), null, false, false, null)
                .show();
    }

    void restartGame() {
        if (nativeReady && nativeSessionActive()) nativePrepareToLeave();  // the host keeps the session's progress
        restartForSession();
    }

    /** Settings > System in the game: the game file, updates and the report tools. */
    private void systemRows(SettingsMenu rows) {
        rows.valueRow(Tr.t("Game File"), "S3HJ08", Tr.t("Change"), () ->
                new Sheet(this, Tr.t("Choose another game file?"), Tr.t("The game closes without saving; it "
                        + "starts again from the new file."))
                        .action(Tr.t("Choose"), null, true, false, () -> toLauncher(LauncherActivity.ACTION_DISC, null))
                        .action(Tr.t("Cancel"), null, false, false, null)
                        .show());
        // The installed patches and the original Japanese game: switching needs no new install.
        final java.util.List<GamePatch.Info> patches = GamePatch.installedAll();
        final String[] patchNames = new String[patches.size() + 1];
        patchNames[0] = Tr.t("None (Japanese)");
        int patchIndex = 0;
        for (int i = 0; i < patches.size(); ++i) {
            patchNames[i + 1] = patches.get(i).name;
            if (patches.get(i).id.equals(settings.activePatch())) patchIndex = i + 1;
        }
        rows.restart(null);
        rows.choiceRow(Tr.t("Translation Patch"), patches.isEmpty()
                        ? Tr.t("None installed: install one with Manage Patches.")
                        : Tr.t("Laid over your game file; a change applies after Restart."),
                patchNames, patchIndex, !patches.isEmpty(),
                which -> settings.setActivePatch(which == 0 ? "" : patches.get(which - 1).id));
        rows.actionRow(Tr.t("Manage Patches"), Tr.t("Install, update or remove patches on the app's first page."),
                Tr.t("Open"), () -> new Sheet(this, Tr.t("Go to the patch list?"), Tr.t("The game closes without saving; "
                        + "start it again from the first page."))
                        .action(Tr.t("Open"), null, true, false, () -> toLauncher(LauncherActivity.ACTION_PATCHES, null))
                        .action(Tr.t("Cancel"), null, false, false, null)
                        .show());
        final String[] qualities = new String[GameRecorder.QUALITIES.length];
        for (int i = 0; i < qualities.length; ++i) {
            qualities[i] = GameRecorder.QUALITIES[i][0] + "p · " + GameRecorder.QUALITIES[i][1] + " FPS";
        }
        rows.choiceRow(Tr.t("Recording Quality"), Tr.t("Record (at the bottom of this menu) saves the game's own "
                        + "picture and sound to Movies/SB3UtageINDO, without the touch buttons. 60 FPS and 1080p "
                        + "make bigger files."),
                qualities, settings.recordQuality(), true, which -> settings.setRecordQuality(which));
        rows.valueRow(Tr.t("Check for Updates"), Updater.displayVersion(this), Tr.t("Check"),
                () -> toLauncher(LauncherActivity.ACTION_UPDATE, null));
        rows.toggleRow(Tr.t("Auto Update"), BuildConfig.ONLINE_UPDATES ? Tr.t("Update on launch")
                        : Tr.t("Updates are sent by hand for now."),
                settings.autoUpdate(), BuildConfig.ONLINE_UPDATES, on -> settings.setAutoUpdate(on));
        rows.actionRow(Tr.t("What's New"), Tr.t("What each version brought."), Tr.t("Open"),
                () -> ReleaseNotes.showAll(this));
        rows.reportRows(true);
        rows.valueRow(Tr.t("Credits"), "DeZer04", Tr.t("Open"), () ->
                new Sheet(this, Tr.t("Credits"), null)
                        .paragraph(Tr.t("SB3 UTAGE:INDO: the Sengoku Basara 3 Utage port and its Indonesian translation, by DeZer04."))
                        .paragraph(Tr.t("Based on the Sengoku Basara 2 Heroes port by xu@shiinobu; menu and touch button design by hikki@datfooldive."))
                        .paragraph(Tr.t("Based on NSMB-Wii-Multiplayer-Recompilation (WitherBlitz) and WiiCompiled (GPLv3). Renderer techniques studied from Dolphin (GPLv2+)."))
                        .note(Tr.t("Touch control icons from game-icons.net by Lorc, Delapouite and contributors "
                                + "(CC BY 3.0)."))
                        .action(Tr.t("Close"), null, true, false, null)
                        .show());
        // GPLv3: the license's notice, its text and the notices inside the APK, the source on the project page.
        rows.actionRow(Tr.t("Source Code & License"), LauncherActivity.PROJECT_URL.replace("https://", "") + " · GPLv3",
                Tr.t("Open"), () -> new Sheet(this, Tr.t("Source Code & License"), "GNU GPL v3")
                        .paragraph(Tr.t("SB3 UTAGE:INDO is free software: you may share and change it under the terms of "
                                + "the GNU General Public License, version 3. It comes with ABSOLUTELY NO WARRANTY."))
                        .paragraph(Tr.t("The source code of each version is on the project page, at that version's release."))
                        .action(Tr.t("Open the Project Page"), LauncherActivity.PROJECT_URL.replace("https://", ""), true,
                                false, () -> openUrl(LauncherActivity.PROJECT_URL))
                        .action(Tr.t("Read the License"), "GNU GPL v3", false, false,
                                () -> showAssetText("licenses/LICENSE.txt", Tr.t("License")))
                        .action(Tr.t("Third-Party Notices"), null, false, false,
                                () -> showAssetText("licenses/THIRD-PARTY-NOTICES.md", Tr.t("Third-Party Notices")))
                        .action(Tr.t("Close"), null, false, false, null)
                        .show());
    }

    private void openUrl(String url) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url)));
        } catch (android.content.ActivityNotFoundException ignored) {
            // no browser
        }
    }

    /** A text file from the APK's assets in a sheet (the license and the notices). */
    private void showAssetText(String path, String title) {
        String text;
        try {
            text = Updater.readAll(getAssets().open(path));
        } catch (java.io.IOException e) {
            text = Tr.t("Not found in this APK: ") + path;
        }
        new Sheet(this, title, null).note(text).action(Tr.t("Close"), null, true, false, null).show();
    }

    /**
     * "Quit Game": closes the whole app, not just the game. The task (launcher included) leaves the
     * recent apps, the launcher's process ends, and onDestroy ends this one.
     */
    private void quitApp() {
        final android.app.ActivityManager am = getSystemService(android.app.ActivityManager.class);
        // The launcher can sit in a task of its own: every task of the app goes, or it would come back.
        if (am != null) {
            for (android.app.ActivityManager.AppTask task : am.getAppTasks()) {
                task.finishAndRemoveTask();
            }
        }
        if (am != null && am.getRunningAppProcesses() != null) {
            for (android.app.ActivityManager.RunningAppProcessInfo info : am.getRunningAppProcesses()) {
                if (info.pid != Process.myPid() && info.uid == Process.myUid()
                        && info.processName.equals(getPackageName())) {
                    Process.killProcess(info.pid);
                }
            }
        }
        finishAndRemoveTask();
    }

    /** "Leave LAN Game": keep the host's progress, then start the game again on its own. */
    private void leaveSession() {
        nativePrepareToLeave();
        restartForSession();  // with the session file gone, the next start is an ordinary one
    }

    /** The name the user gave the phone, else its model. */
    private String deviceName() {
        String name = Settings.Global.getString(getContentResolver(), Settings.Global.DEVICE_NAME);
        if (name == null || name.trim().isEmpty()) {
            name = Build.MODEL;
        }
        return name == null ? "Phone" : name.trim();
    }

    /**
     * Network play: the runtime has written the session (netplay_start.cpp); start the game again in a
     * fresh process. The launcher waits for this one to end, then opens the game, which finds the
     * session and boots into it. Called from the game thread.
     */
    void restartForSession() {
        runOnUiThread(() -> {
            final Intent intent = new Intent(this, LauncherActivity.class)
                    .putExtra(LauncherActivity.EXTRA_RESTART_GAME, true)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            startActivity(intent);
            finish();
        });
    }

    @Override
    protected void onDestroy() {
        if (multicastLock != null && multicastLock.isHeld()) {
            multicastLock.release();
        }
        super.onDestroy();
        if (isFinishing()) {
            GpuDrivers.endedOnPurpose(this);
            CrashReport.endedOnPurpose(this, Process.myPid());
            // The runtime starts once per process; the next start must get a fresh one.
            Process.killProcess(Process.myPid());
        }
    }

    // --- input ---------------------------------------------------------------------------------

    @Override
    public void onTouchInput(int buttons) {
        touchButtons = buttons;
        pushInput();
    }

    @Override
    public void onTouchSticks(float leftX, float leftY, float rightX, float rightY) {
        if (!nativeReady) return;
        try {
            nativeSetTouchSticks(leftX, leftY, rightX, rightY);
        } catch (UnsatisfiedLinkError e) {
            nativeReady = false;
            Log.e(TAG, "touch input bridge missing from libmain.so", e);
        }
    }

    private void pushInput() {
        if (!nativeReady) return;
        try {
            nativeSetTouchState(touchButtons, false, 0f);
        } catch (UnsatisfiedLinkError e) {
            nativeReady = false;
            Log.e(TAG, "touch input bridge missing from libmain.so", e);
        }
    }

    private void applyControlSettings() {
        touch.setControlsVisible(settings.touchControls());
        touch.setHaptics(settings.haptics());
        touch.setTouchCamera(settings.touchCamera());
        touch.setStyle(TouchControlsView.STYLE_MODERN);  // one look only, from PR #3
        touch.setInvertCamera(settings.invertCamera());
        touch.setLockShown(settings.lockTarget());
        if (!settings.lockTarget() && lockOn) onLock();  // turned off in the settings while locked
        if (layoutEditor != null && layoutEditor.isOpen()) return;  // the editor holds unsaved changes
        touch.setOpacity(settings.touchOpacity());
        touch.setFixedStick(settings.fixedStick());
        touch.setLayout(settings.touchLayout());
    }

    /** What the game can change while it runs: picture, upscaler, frame pacing, overlay, cheats. */
    private void applyNativeSettings() {
        if (!nativeReady) return;
        nativeApplyDisplaySettings(settings.aspectMode(), settings.resolutionScale(), settings.showFps(),
                settings.dynamicResolution(), settings.overlayFlags(), settings.frameGraph(),
                settings.thermalControl(), settings.textureFilter());
        nativeApplyCheats(settings.cheatMoney(), settings.cheatMoneyAmount(), settings.cheatMoneySeq(),
                settings.cheatInfiniteHp(), settings.cheatInfiniteBasara(), settings.cheatUnlockAll());
        try {
            nativeSetCameraDistance(settings.cameraDistanceFactor());
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "camera distance bridge missing from libmain.so", e);
        }
        try {
            nativeSetGameSpeed(settings.gameSpeed());
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "game speed bridge missing from libmain.so", e);
        }
        try {
            nativeSetRumble(settings.rumble());
            nativeSetTouchPlusPad(settings.touchPlusPad());
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "rumble or two-player bridge missing from libmain.so", e);
        }
        try {
            nativeSetDisableFog(settings.disableFog());
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "fog bridge missing from libmain.so", e);
        }
        try {
            nativeSetReduceEffects(settings.reduceEffects());
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "effects bridge missing from libmain.so", e);
        }
        try {
            nativeSetGamepadMap(settings.gamepadMapInUse());
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "gamepad map bridge missing from libmain.so", e);
        }
        try {
            nativeApplyLiveSettings(settings.fsr(), settings.fpsLock30() ? 2 : settings.frameskip() ? 1 : 0);
            // Only a change: the start's own choice (or env.txt's BASARA_CPU_BOOST) stays otherwise.
            if (sustainedMode() != appliedSustained) {
                appliedSustained = sustainedMode();
                nativeSetSustained(appliedSustained);
            }
            nativeSetVSync(settings.vsync());
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "live settings bridge missing from libmain.so", e);
        }
    }

    /** A change in the in-game settings: everything that applies while playing, at once. */
    private void applyLiveSettings() {
        settings = new AppSettings(this);
        applyNativeSettings();
        applyDisplayResolution();
        getWindow().setSustainedPerformanceMode(sustainedMode());
        applyControlSettings();
    }

    private void hideSystemBars() {
        SystemBars.hide(getWindow());
    }

    // --- menu ----------------------------------------------------------------------------------

    /**
     * The in-game menu, from the phone's Back gesture or the gear on the touch controls: the game
     * pauses while it is open.
     */
    @Override
    public void onMenu() {
        if (layoutEditor != null && layoutEditor.isOpen()) {
            layoutEditor.save();  // Back while editing: keep what was arranged
            return;
        }
        touch.release();
        final boolean inSession = nativeReady && nativeSessionActive();
        // The game stands still while the menu is open (no backup save: it isn't leaving the screen).
        menuOpen = true;
        setMenuPause(true);
        new PauseMenu(inSession).show();
    }

    /**
     * R3 or the touch LOCK button (Settings: Lock Target, experimental): the camera turns toward an
     * enemy general or named officer. Turning the setting off releases a lock that is on.
     */
    @Override
    public void onLock() {
        if (!nativeReady || (!settings.lockTarget() && !lockOn)) return;
        boolean on;
        try {
            on = nativeToggleLockOn();
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "lock bridge missing from libmain.so", e);
            return;
        }
        lockOn = on;
        touch.setLockOn(on);
        Toast.makeText(this, on ? Tr.t("Lock target: on") : Tr.t("Lock target: off"), Toast.LENGTH_SHORT).show();
    }

    /** The touch zoom button: the next Camera Distance, applied at once. */
    @Override
    public void onZoom() {
        final int next = (settings.cameraDistance() + 1) % AppSettings.CAMERA_DISTANCES.length;
        settings.setCameraDistance(next);
        if (nativeReady) {
            try {
                nativeSetCameraDistance(settings.cameraDistanceFactor());
            } catch (UnsatisfiedLinkError e) {
                Log.e(TAG, "camera distance bridge missing from libmain.so", e);
            }
        }
        Toast.makeText(this, Tr.t("Camera Distance") + ": " + AppSettings.cameraDistanceLabel(next),
                Toast.LENGTH_SHORT).show();
    }

    /**
     * The in-game menu, as an ImGui window over the dimmed game (the look hikki made for DefJam): a
     * title bar, the sections as a row of tabs, their settings, and the actions in the footer. What the
     * game can change while playing applies at once; settings read only at start carry a "*".
     */
    private final class PauseMenu {
        private final android.app.Dialog dialog;
        private final android.widget.LinearLayout tabs;
        private final android.widget.ScrollView rowsScroll;
        private final SettingsMenu menu;
        private final int[] sections = SettingsMenu.gameSections();
        /** A section row's height and the gap under it: smaller when the window is short (fitTabs). */
        private int tabHeight = dp(42), tabGap = dp(4);
        private android.widget.TextView note;
        private android.widget.TextView restartButton;
        private android.graphics.drawable.Drawable restartLook;
        private android.content.res.ColorStateList restartText;

        /** The footer note, or the settings waiting for Restart, with Restart lit in amber. */
        private void showPending() {
            if (note == null || restartButton == null) return;
            final java.util.Map<String, String> pending = SettingsMenu.pendingRestarts();
            if (pending.isEmpty()) {
                note.setText(Tr.t("Changes are saved as you make them. ⟳ Restart = applies after Restart."));
                note.setTextColor(Ui.MUTED);
                note.setBackground(null);
                note.setPadding(0, 0, 0, 0);
                restartButton.setBackground(restartLook);
                restartButton.setTextColor(restartText);
                return;
            }
            note.setText("⟳ " + (pending.size() == 1 ? Tr.t("1 change waiting for Restart")
                    : pending.size() + Tr.t(" changes waiting for Restart")));
            note.setTextColor(Ui.PENDING);
            note.setBackground(Ui.box(GameActivity.this, Ui.PENDING_BG, 0, Ui.RADIUS_PILL));
            note.setPadding(dp(10), dp(3), dp(10), dp(3));
            restartButton.setBackground(Ui.box(GameActivity.this, Ui.PENDING, 0, Ui.RADIUS_PILL));
            restartButton.setTextColor(0xFF1B1300);
        }

        PauseMenu(boolean inSession) {
            final GameActivity a = GameActivity.this;
            final android.widget.LinearLayout window = new android.widget.LinearLayout(a);
            window.setOrientation(android.widget.LinearLayout.VERTICAL);
            window.setBackground(Ui.box(a, Ui.WINDOW, Ui.BORDER, Ui.RADIUS_WINDOW));
            window.setClipToOutline(true);
            window.setElevation(dp(12));
            window.addView(Ui.titleBar(a, Tr.t("Settings"), "SB3 UTAGE:INDO"), Ui.matchWidth(0));

            // The sections down the left (icon and name), their settings as cards on the right.
            final android.widget.LinearLayout body = new android.widget.LinearLayout(a);
            body.setOrientation(android.widget.LinearLayout.HORIZONTAL);
            body.setPadding(dp(12), 0, dp(12), 0);
            window.addView(body, new android.widget.LinearLayout.LayoutParams(
                    android.widget.LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

            tabs = new android.widget.LinearLayout(a);
            tabs.setOrientation(android.widget.LinearLayout.VERTICAL);
            final android.widget.ScrollView navScroll = new android.widget.ScrollView(a);
            navScroll.setVerticalScrollBarEnabled(false);
            navScroll.setVerticalFadingEdgeEnabled(true);  // a list still too long fades out at its edge
            navScroll.setFadingEdgeLength(dp(20));
            navScroll.addView(tabs);
            navScroll.addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> {
                if (b - t != ob - ot) v.post(() -> fitTabs(b - t));
            });
            body.addView(navScroll, new android.widget.LinearLayout.LayoutParams(dp(176),
                    android.widget.LinearLayout.LayoutParams.MATCH_PARENT));

            final android.widget.LinearLayout root = new android.widget.LinearLayout(a);
            root.setOrientation(android.widget.LinearLayout.VERTICAL);
            final android.widget.LinearLayout.LayoutParams rootParams = new android.widget.LinearLayout.LayoutParams(
                    0, android.widget.LinearLayout.LayoutParams.MATCH_PARENT, 1f);
            rootParams.leftMargin = dp(12);
            body.addView(root, rootParams);

            final android.widget.LinearLayout rows = new android.widget.LinearLayout(a);
            rows.setOrientation(android.widget.LinearLayout.VERTICAL);
            rowsScroll = new android.widget.ScrollView(a);
            rowsScroll.setScrollBarStyle(android.view.View.SCROLLBARS_OUTSIDE_OVERLAY);
            rowsScroll.setPadding(0, 0, dp(6), 0);
            rowsScroll.setClipToPadding(false);
            rowsScroll.addView(rows);
            root.addView(rowsScroll, new android.widget.LinearLayout.LayoutParams(
                    android.widget.LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

            // The footer: what the "⟳ Restart" tag means, or (once one changed) the settings that wait
            // for Restart in amber; then the actions with Resume last (the bright one).
            final android.widget.LinearLayout footer = new android.widget.LinearLayout(a);
            footer.setGravity(android.view.Gravity.CENTER_VERTICAL);
            footer.setPadding(dp(18), dp(10), dp(14), dp(12));
            note = Ui.text(a, "", 11, Ui.MUTED);
            note.setMaxLines(2);
            note.setEllipsize(android.text.TextUtils.TruncateAt.END);
            footer.addView(note, new android.widget.LinearLayout.LayoutParams(0,
                    android.widget.LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
            footer.addView(action(GameRecorder.recording() ? Tr.t("Stop Recording") : Tr.t("Record"), false, v -> {
                close();
                toggleRecording();
            }), actionParams());
            footer.addView(action(Tr.t("Layout"), false, v -> {
                close();
                startLayoutEdit();
            }), actionParams());
            restartButton = action(Tr.t("Restart"), false, v -> confirmRestart(null));
            restartLook = restartButton.getBackground();
            restartText = restartButton.getTextColors();
            footer.addView(restartButton, actionParams());
            if (inSession) {
                footer.addView(action(Tr.t("Leave LAN"), false, v -> {
                    close();
                    leaveSession();
                }), actionParams());
            }
            footer.addView(action(Tr.t("Quit"), false, v -> confirmQuit()), actionParams());
            footer.addView(action(Tr.t("Resume"), true, v -> close()), actionParams());
            window.addView(Ui.line(a));
            window.addView(footer, Ui.matchWidth(0));

            menu = new SettingsMenu(a, rows, true, GameActivity.this::applyLiveSettings);
            menu.pendingChanged = this::showPending;
            showPending();
            menu.systemRows = GameActivity.this::systemRows;
            // A new language: the window is made again around the same tab (the game stays paused).
            menu.languageChanged = () -> tabs.post(() -> {
                final int open = menu.section();
                PauseMenu.this.dialog.dismiss();
                final PauseMenu again = new PauseMenu(inSession);
                again.select(open);
                again.show();
            });

            // The game shows dimmed around the window, as DefJam's panel (most of the screen's height).
            final android.widget.FrameLayout backdrop = new android.widget.FrameLayout(a);
            backdrop.setBackgroundColor(android.graphics.Color.argb(166, 0, 0, 0));
            final android.util.DisplayMetrics screen = getResources().getDisplayMetrics();
            final int width = Math.min(dp(920), Math.round(screen.widthPixels * 0.9f));  // the section list and the cards side by side
            final int height = Math.round(screen.heightPixels * 0.92f);
            backdrop.addView(window, new android.widget.FrameLayout.LayoutParams(width, height,
                    android.view.Gravity.CENTER));
            backdrop.setOnClickListener(v -> close());  // a tap beside the window resumes, as DefJam's
            window.setClickable(true);

            dialog = new android.app.Dialog(a, android.R.style.Theme_DeviceDefault_NoActionBar_Fullscreen);
            dialog.setContentView(backdrop);
            final android.view.Window w = dialog.getWindow();
            if (w != null) {
                w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT));
                w.setLayout(android.view.WindowManager.LayoutParams.MATCH_PARENT,
                        android.view.WindowManager.LayoutParams.MATCH_PARENT);
            }
            dialog.setOnShowListener(d -> SystemBars.hide(w));
            dialog.setOnCancelListener(d -> resumeFromMenu());
            dialog.setOnDismissListener(d -> hideSystemBars());
            select(SettingsMenu.DISPLAY);
        }

        void show() { dialog.show(); }

        private void close() {
            dialog.dismiss();
            resumeFromMenu();
        }

        /** A footer button: a pill, the primary one (Resume) filled in the accent. */
        private android.widget.TextView action(String label, boolean primary, android.view.View.OnClickListener onClick) {
            final android.widget.TextView button = Ui.chip(GameActivity.this, label, primary, true, onClick);
            button.setPadding(dp(16), 0, dp(16), 0);
            button.setMinWidth(dp(84));
            button.setContentDescription(label);
            return button;
        }

        private android.widget.LinearLayout.LayoutParams actionParams() {
            // At least 84 dp, wider when the label needs it ("Mulai Ulang"): the note beside them shrinks.
            final android.widget.LinearLayout.LayoutParams params = new android.widget.LinearLayout.LayoutParams(
                    android.widget.LinearLayout.LayoutParams.WRAP_CONTENT, dp(38));
            params.leftMargin = dp(8);
            return params;
        }

        /** The section list: icon and name, the open one lit in the accent with a bar at its edge. */
        private void select(int section) {
            menu.show(section);
            rowsScroll.scrollTo(0, 0);
            tabs.removeAllViews();
            for (int id : sections) {
                final boolean open = id == section, enabled = !SettingsMenu.disabled(id);
                final android.widget.LinearLayout item = new android.widget.LinearLayout(GameActivity.this);
                item.setGravity(android.view.Gravity.CENTER_VERTICAL);
                item.setPadding(dp(12), 0, dp(10), 0);
                item.setBackground(open ? Ui.box(GameActivity.this, Ui.ACCENT_SUBTLE, 0, Ui.RADIUS_CONTROL)
                        : Ui.touchBox(GameActivity.this, 0x00000000, 0, Ui.RADIUS_CONTROL));
                final int tint = open ? Ui.ACCENT_PRESSED : SettingsMenu.risky(id) ? Ui.WARNING : Ui.SECONDARY;
                final int iconRes = SettingsMenu.icon(id);
                if (iconRes != 0) item.addView(Ui.icon(GameActivity.this, iconRes, tint, 18));
                final android.widget.TextView name = Ui.text(GameActivity.this, SettingsMenu.name(id), 13.5f,
                        open ? Ui.TEXT : Ui.SECONDARY);
                name.setTypeface(open ? android.graphics.Typeface.DEFAULT_BOLD : Ui.MEDIUM);
                name.setSingleLine(true);
                name.setEllipsize(android.text.TextUtils.TruncateAt.END);
                final android.widget.LinearLayout.LayoutParams nameParams = new android.widget.LinearLayout.LayoutParams(
                        0, android.widget.LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
                nameParams.leftMargin = dp(10);
                item.addView(name, nameParams);
                if (!enabled) item.setAlpha(0.4f);
                if (enabled && !open) item.setOnClickListener(v -> select(id));
                final android.widget.LinearLayout.LayoutParams params = new android.widget.LinearLayout.LayoutParams(
                        android.widget.LinearLayout.LayoutParams.MATCH_PARENT, tabHeight);
                params.bottomMargin = tabGap;
                tabs.addView(item, params);
            }
        }

        /**
         * Every section in sight without scrolling: on a phone in landscape the window is short, so the
         * rows shrink (down to 30 dp) to fit `height`, the section list's own.
         */
        private void fitTabs(int height) {
            final int gap = height >= sections.length * dp(46) ? dp(4) : dp(2);
            final int fit = Math.max(dp(30), Math.min(dp(42), height / sections.length - gap));
            if (fit == tabHeight && gap == tabGap) return;
            tabHeight = fit;
            tabGap = gap;
            for (int i = 0; i < tabs.getChildCount(); ++i) {
                final android.view.View item = tabs.getChildAt(i);
                final android.widget.LinearLayout.LayoutParams params =
                        (android.widget.LinearLayout.LayoutParams) item.getLayoutParams();
                params.height = fit;
                params.bottomMargin = gap;
                item.setLayoutParams(params);
            }
        }
    }

    private void resumeFromMenu() {
        menuOpen = false;
        setMenuPause(false);
    }

    private android.view.View line() {
        final android.view.View view = new android.view.View(this);
        view.setBackgroundColor(Ui.BORDER);
        return view;
    }

    private int dp(int value) {
        return Ui.dp(this, value);
    }
}
