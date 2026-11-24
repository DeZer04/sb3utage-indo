package io.github.dezer04.sb3utage;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.util.TypedValue;
import android.view.Gravity;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * What changed in each build: the versions in a strip across the top, the
 * chosen version's changes below. Opens once after an install or update (on the newest
 * version) and from the launcher's What's New tile. The newest entry is first and describes the
 * build installed; add one for every release, listing only what that build changed.
 */
final class ReleaseNotes {
    private static final class Entry {
        final String version, title, date;
        final String[] added, fixed, known;
        Entry(String version, String title, String date, String[] added, String[] fixed, String[] known) {
            this.version = version;
            this.title = title;
            this.date = date;
            this.added = added;
            this.fixed = fixed;
            this.known = known;
        }
    }

    private static final Entry[] ALL = {
        new Entry("1.0.2", "A lighter recorder", "2026-11-24",
                new String[] {
                    "A lighter recorder: about 0.4 ms of GPU time a frame on a Poco X6 instead of 1.2. Each recorded frame is a third lighter (the picture is read with hardware filtering), and it records at 720p 30 FPS at first, half as many frames as 60. 60 FPS and 1080p stay in Settings > System > Recording Quality.",
                },
                new String[] {
                    "The small REC badge at the screen's edge could miss a tap: its touch area is wider now.",
                },
                new String[] {
                    "Recording costs some GPU time: in busy battles on mid-range phones the game can drop a few more frames while it records.",
                    "Busy battles may still drop below 30 FPS on slower phones.",
                }),
        new Entry("1.0.1", "Built-in recorder, PS3 button names", "2026-11-24",
                new String[] {
                    "Built-in recorder: Record at the bottom of the game's menu saves the game's own picture and sound (no touch buttons, no overlay) as an MP4 in Movies/SB3UtageINDO. It uses the phone's video encoder at the game's size, so it is lighter than a screen recording. A red REC badge shows the time; tap it to stop. Quality: Settings > System > Recording Quality (720p or 1080p, 30 or 60 FPS).",
                    "Buttons are named as on the PS3: □ attack, △ skill, ○ BASARA, × jump, L1 guard, L2 boost, R1 skill 3, R2 ougi, SELECT and START, on the touch buttons and in Gamepad Buttons.",
                    "Settings > System > Source Code & License: the GNU GPL v3 notice, the license and the third-party notices, with the link to each version's source code.",
                },
                new String[] {
                    "A translation patch did nothing when the game was played straight from the ISO or RVZ (Read from File): the patch was skipped at boot. It now applies as with the unpacked game.",
                },
                new String[] {
                    "A recording keeps what the game shows: moments that drop frames drop them in the video too.",
                    "Busy battles may still drop below 30 FPS on slower phones.",
                }),
        new Entry("1.0.0", "Game Speed, no more Preparing shaders, Thermal Control", "2026-11-23",
                new String[] {
                    "Translation patches on the first page: choose No Patch, Full Patch Indo or Descriptions Only and install it from a .patch file (downloaded in the app or on the phone). It is made from your own game file, read or unpacked, and each patch keeps its own folder, so switching between Indonesian and the original Japanese is instant (also in Settings > System > Translation Patch, after Restart).",
                    "The app is in Indonesian from the start. Bahasa Indonesia or English can be picked on the first page (and in Settings > Display > Language).",
                    "The app now opens on a first page with the game's details (file, how it is loaded, the patch in use) and Play, instead of going straight into the game.",
                    "No more Preparing shaders screen: the game starts at once and builds its shaders in the background on the phone's small cores while you play. A small counter in the corner shows how far it is, and the buttons work the whole time. A shader that is not ready yet is left out for a moment instead of freezing the game.",
                    "Far fewer shaders to build: shaders that differed only in the fog style or the vertex precision are now one (the built-in list goes from 7683 to 2498, then 2850 with the shaders found while testing 1.0.0). On a Poco X6 the first build takes about 4.5 minutes in the background instead of over 9.",
                    "Built shaders are kept on the phone in a ready form and load only when a scene needs them: later starts are much quicker and the game uses less memory.",
                    "Thermal Control is back (Settings > Performance, off at first). On phones that report a temperature forecast (most on Android 12 and newer), the game draws at 30 FPS for at least a minute when the phone warms up while it keeps full speed; elsewhere it only lowers the resolution when the battery runs hot.",
                    "New touch button icons, one for each move: attack, skills, BASARA, jump, guard, Sengoku Boost, ougi and taunt. Credits now name this port.",
                    "Rumble (Settings > Controls): the game's own rumble on a gamepad, and in short pulses on the phone too with Controller and Phone.",
                    "Cheats for Utage (Settings > Cheats): Infinite HP, Infinite BASARA, money (Infinite or Once, up to 9,999,999) and Unlock All (generals, extra costumes, Japan game destinations, gallery). Back up your save first: what the game saves stays.",
                    "Two Players (Settings > Controls): the touch controls play player 1 and a Bluetooth gamepad player 2, for the game's two-player mode.",
                    "Game Speed (Settings > Performance): battles and menus at 110% up to 200% of normal. Cutscenes keep their speed and the music plays as usual; the phone has to hold the frame rate for a smooth result.",
                },
                new String[] {
                    "On a phone in landscape, the last sections of the game's Settings (Textures, System) were hidden below the list. Every section now fits.",
                    "The Upscaler could not be changed while a Preset was on. It is free now, as Render Resolution, and the GPU driver install shows what it needs (a driver .zip with a meta.json).",
                    "The Cheats tab was missing from the game's menu, so the cheats could not be turned on. It is there again (Settings > Cheats).",
                    "While shaders built in the background, menus and dialogs could ignore the buttons for up to 3 minutes.",
                    "Code left over from the Sengoku Basara 2 Heroes port is gone: unused parts and settings, a disc check that called every Utage dump changed, a camera value written to the wrong memory each frame, and Basara 2 addresses in the thread and sound setup.",
                    "Swiping the game out of Recents while the shaders built in the background threw away the ones already built. They are now saved when the game leaves the screen and every 30 seconds while they build, and the next start builds the rest instead of taking the half-done list for finished.",
                    "After a system update or a change of GPU driver, the shaders build again in the background instead of one by one in the middle of the game.",
                    "Reset and Clear and the HD texture cache's Clear did nothing from the in-game settings. They now go back to the start screen, close the game and then clear; start the game again from there.",
                    "With the Performance Overlay on, counting the draws cost the graphics thread about 5% of its time in busy battles. It is now nearly free.",
                    "Renderer > WebGPU 1.0 is gone: this app never carried the 1.0 renderer, so the choice ran the normal one. A phone set to it uses Auto.",
                    "Closing the game by swiping it out of Recents (HyperOS, MIUI) showed \"The game closed unexpectedly\" at the next start. Only real crashes are reported now.",
                },
                new String[] {
                    "The first start after this update builds the shaders again in the background (a few minutes): some effects can appear a moment late until it finishes. It happens once.",
                    "Busy battles may still drop below 30 FPS on slower phones.",
                }),
        new Entry("0.5.9", "Lock target (experimental), shaders for every setting", "2026-11-23",
                new String[] {
                    "Lock Target is now an experimental setting (Settings > Display, off at first): turn it on for the LOCK button and R3. It locks only enemy generals and named officers, never plain soldiers or your own side, and the camera turns only when the target leaves the middle of the screen, calmer up close. Flick the right stick left or right to move to the next enemy on that side.",
                    "The built-in shader list grows to 7683 shaders: more story stages, the character select and the Unification map.",
                },
                new String[] {
                    "With Disable Fog on, Preparing shaders built thousands of shaders the game never draws and left the ones it needs for the middle of a battle. Phones whose GPU needs the vertex loader (PowerVR, some Mali on OpenGL ES) matched almost none of the list. The list now fits each player's settings and GPU.",
                    "Every start copied the whole built-in shader list into the phone's own again (about 30 MB of writing). It is now merged once per update, so starts are quicker.",
                    "Lock target spun the camera around when several named enemies were near, or when an enemy circled the player up close.",
                },
                new String[] {
                    "The first start after this update stays on Preparing shaders a little longer while the new shaders build. It happens once.",
                    "Busy battles may still drop below 30 FPS on slower phones.",
                }),
        new Entry("0.5.8", "Lock target, faster battles, camera zoom, shaders ready sooner", "2026-11-23",
                new String[] {
                    "Lock target: R3 on a gamepad or the new LOCK button (up and left of the right stick) turns the camera toward the nearest enemy general, else the nearest enemy, and moves on to the next one when the target falls. Press again to let go; your own right stick always wins.",
                    "Faster battles: the game no longer naps 1 ms at a time while the GPU draws (about 6 ms of every battle frame on a Poco X6), and the graphics bookkeeping for each draw is lighter.",
                    "Camera zoom: Settings > Display > Camera Distance (Default, 1.25x, 1.5x, 2x) or the new zoom button right of + (L3 on a gamepad) shows more of the battlefield. Cutscenes keep their framing. Things at the edges of a wide view can appear a moment late.",
                    "The built-in shader list grows from 1212 to 7218 shaders, recorded while playing Free Battle and story stages: far fewer shaders build in the middle of a battle.",
                },
                new String[] {
                    "Preparing shaders ran at every start. It now runs only on the first start after a new install; later starts and updates go straight to the game and finish the shaders in the background.",
                    "After Graphics Compatibility was changed, the game could stop answering buttons for minutes while every shader rebuilt. Shader building now gives the game the CPU first.",
                },
                new String[] {
                    "The first start after a new install stays longer on Preparing shaders (3 to 4 minutes on a mid-range phone). It happens once.",
                    "Busy battles may still drop below 30 FPS on slower phones.",
                }),
        new Entry("0.5.6", "Faster battles, GX Thread, fixes", "2026-11-22",
                new String[] {
                    "The game code is rebuilt from a profile of real battles (PGO and ThinLTO): less CPU work every frame.",
                    "GX Thread is on in every preset and on new installs: the graphics work leaves the game's own thread, the part that limits battles.",
                },
                new String[] {
                    "The game closed when HOME was pressed: the Wii HOME Menu is a part of the game this port cannot run. HOME is now ignored, and the touch HOME button is gone; the app's own menu replaces it.",
                    "With GX Thread on, the game could close right after the Preparing shaders screen (\"Final render pass must not have resolve target\").",
                    "Switching between presets no longer builds a second copy of every shader: presets leave Disable Fog as it is.",
                },
                new String[] {
                    "Busy battles may still drop below 30 FPS on slower phones.",
                }),
        new Entry("0.5.4", "Graphics presets", "2026-11-22",
                new String[] {
                    "Performance > Preset has five levels: Extreme Low, Low, Default, Medium and High (and Custom for your own settings). Each one keeps the game at full speed.",
                },
                new String[] {
                },
                new String[] {
                    "Busy battles run at about 20 to 30 FPS on mid-range phones: the game's own work on the CPU is the limit, and is being worked on.",
                }),
        new Entry("0.5.3", "Skill 4 button", "2026-11-22",
                new String[] {
                },
                new String[] {
                    "The Skill 4 button (L+X) often gave only a guard: it now holds guard a moment before X, as the game expects.",
                    "Button names match the game's own Classic Controller screen: R is Skill 3 (Y + X).",
                },
                new String[] {
                    "Busy battles run at about 20 to 30 FPS on mid-range phones: the game's own work on the CPU is the limit, and is being worked on.",
                }),
        new Entry("0.5.2", "Shaders ready from the start, no grey flash, Basara 3 buttons", "2026-11-22",
                new String[] {
                    "The app brings its own shader list: a new install prepares about 1,200 shaders once on the Preparing shaders screen, so battles and cutscenes no longer stop to build them.",
                    "Touch and gamepad buttons follow Sengoku Basara 3's layout: R is Skill 3, the L+X button is Skill 4, ZL is Boost / Drive, − is Taunt / Assist.",
                    "Gamepads: guard (L) and Skill 3 (R) are on the bumpers, Boost (ZL) and Ougi (ZR) on the triggers, as on the PS3. A layout you set yourself stays as it is.",
                },
                new String[] {
                    "A grey picture flashed before the Wii Remote strap screen at every start.",
                },
                new String[] {
                    "Busy battles run at about 20 to 30 FPS on mid-range phones: the game's own work on the CPU is the limit, and is being worked on.",
                }),
        new Entry("0.5.0", "SB3 UTAGE:INDO", "2026-11-22",
                new String[] {
                    "New name and look: SB3 UTAGE:INDO, with its own icon. It installs as a new app next to the old one: the save comes back by itself from Saves/Auto (with \"All files access\"); choose the game file once more.",
                    "Full game speed on slower phones: with Frameskip Auto the game moves by the real time each frame took, so battles and cutscenes no longer play in slow motion (down to about 15 FPS).",
                    "Far fewer shaders built while playing: the game's fades and dissolves no longer each need a shader of their own, so the list shrinks to about a sixth and the first start prepares them faster.",
                    "A clearer Preparing shaders screen at the first start: larger text, a count and a percentage.",
                    "The phone folder is now SB3UtageINDO (Logs, Saves, Textures); the old Basara3Utage folder is moved there by itself.",
                },
                new String[] {
                    "Back Up and Import Save work with this game's save (save_h.bin); they still looked for Sengoku Basara 2 Heroes' file.",
                    "Settings left over from Sengoku Basara 2 Heroes that did nothing here (Real Widescreen, Camera Distance, Thermal Control, Skip Boot, Tilt, Shake and the Cheats tab) are gone.",
                    "Yellow and white pre-battle cutscenes, invisible battle fields, exploding character models and cut-off dialogue text.",
                },
                new String[] {
                    "Busy battles run at about 20 to 28 FPS on mid-range phones: the game's own work on the CPU is the limit, and is being worked on.",
                }),
    };

    /** The first public release: what came before it (test builds) is not shown. */
    private static final String FIRST_RELEASE = "1.0.0";
    private static final Entry[] ENTRIES = releaseEntries();

    private static Entry[] releaseEntries() {
        for (int i = 0; i < ALL.length; ++i) {
            if (ALL[i].version.equals(FIRST_RELEASE)) return java.util.Arrays.copyOf(ALL, i + 1);
        }
        return ALL;
    }

    /** The build installed: its notes are shown once. */
    private static String build(Activity activity) {
        try {
            return activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0).getLongVersionCode()
                    + ":" + ENTRIES[0].title;
        } catch (Exception e) {
            return ENTRIES[0].title;
        }
    }

    /** After an install or update: the screen, on the newest version, once. */
    static void showIfNew(Activity activity, AppSettings settings) {
        final String build = build(activity);
        if (build.equals(settings.notesSeen())) return;
        settings.setNotesSeen(build);
        showAll(activity);
    }

    /** As above, with `after` run once it is closed. False (and `after` not run) when nothing is new. */
    static boolean showIfNew(Activity activity, AppSettings settings, Runnable after) {
        final String build = build(activity);
        if (build.equals(settings.notesSeen())) return false;
        settings.setNotesSeen(build);
        final ReleaseNotes notes = new ReleaseNotes(activity);
        notes.dialog.setOnDismissListener(d -> after.run());
        notes.dialog.show();
        return true;
    }

    /** The full screen, on the newest version. */
    static void showAll(Activity activity) {
        new ReleaseNotes(activity).dialog.show();
    }

    // --- the screen (same layout and look as SettingsMenu) ---------------------------------------

    private final Activity activity;
    private final Dialog dialog;
    private final LinearLayout nav;
    private final LinearLayout rows;
    private final ScrollView rowsScroll;

    private ReleaseNotes(Activity activity) {
        this.activity = activity;

        // Upright page: the title, a sideways strip of versions, the chosen version's notes, Done in view.
        final TextView title = text(Tr.t("What's New"), 24, Color.WHITE);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        final TextView installed = text(Tr.t("Installed: ") + LauncherActivity.APP + " " + Updater.displayVersion(activity), 12,
                LauncherActivity.MUTED);
        installed.setPadding(0, dp(2), 0, dp(10));
        nav = new LinearLayout(activity);
        nav.setOrientation(LinearLayout.HORIZONTAL);
        for (int i = 0; i < ENTRIES.length; ++i) {
            final int index = i;
            final LinearLayout item = new LinearLayout(activity);
            item.setOrientation(LinearLayout.VERTICAL);
            item.setPadding(dp(14), dp(8), dp(14), dp(8));
            item.setClickable(true);
            item.setOnClickListener(v -> showEntry(index));
            final TextView name = text(ENTRIES[i].version, 15, Color.WHITE);
            name.setTypeface(LauncherActivity.MEDIUM);
            item.addView(name);
            item.addView(text(i == 0 ? Tr.t("this version") : ENTRIES[i].date, 11, LauncherActivity.MUTED));
            final LinearLayout.LayoutParams itemParams = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            if (i > 0) itemParams.leftMargin = dp(6);
            nav.addView(item, itemParams);
        }
        final HorizontalScrollView navScroll = new HorizontalScrollView(activity);
        navScroll.setHorizontalScrollBarEnabled(false);
        navScroll.addView(nav);

        rows = new LinearLayout(activity);
        rows.setOrientation(LinearLayout.VERTICAL);
        rows.setPadding(0, dp(14), 0, 0);
        rowsScroll = new ScrollView(activity);
        rowsScroll.setVerticalScrollBarEnabled(false);
        rowsScroll.addView(rows);

        final TextView done = text(Tr.t("Done"), 17, Color.WHITE);
        done.setTypeface(Typeface.DEFAULT_BOLD);
        done.setGravity(Gravity.CENTER);
        done.setPadding(0, dp(12), 0, dp(12));
        done.setBackground(rounded(LauncherActivity.ACCENT, dp(24)));

        final LinearLayout page = new LinearLayout(activity);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setBackgroundColor(LauncherActivity.BACKGROUND);
        page.addView(title);
        page.addView(installed);
        page.addView(navScroll, matchWidth(0));
        page.addView(rowsScroll, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        page.addView(done, matchWidth(dp(10)));

        dialog = new Dialog(activity, android.R.style.Theme_DeviceDefault_NoActionBar_Fullscreen);
        dialog.setContentView(page);
        // Bars stay visible (like the launcher); the page keeps clear of them.
        SystemBars.edgeToEdge(dialog.getWindow());
        page.setOnApplyWindowInsetsListener((v, insets) -> {
            final android.graphics.Insets bars = SystemBars.bars(insets, false);
            v.setPadding(dp(16) + bars.left, dp(16) + bars.top, dp(16) + bars.right, dp(16) + bars.bottom);
            return SystemBars.consumed(insets);
        });
        done.setOnClickListener(v -> dialog.dismiss());
        showEntry(0);
    }


    private void showEntry(int index) {
        for (int i = 0; i < ENTRIES.length; ++i) {
            nav.getChildAt(i).setBackground(i == index ? rounded(LauncherActivity.RAISED, dp(16)) : null);
        }
        rows.removeAllViews();
        final Entry e = ENTRIES[index];
        final TextView heading = text(e.version, 22, Color.WHITE);
        heading.setTypeface(Typeface.DEFAULT_BOLD);
        rows.addView(heading);
        final TextView about = text(Tr.t(e.title) + " · " + e.date, 13, LauncherActivity.MUTED);
        about.setPadding(0, dp(2), 0, 0);
        rows.addView(about);
        group(Tr.t("Added"), "+", LauncherActivity.ACCENT, e.added);
        group(Tr.t("Fixed"), "✓", LauncherActivity.GREEN, e.fixed);
        group(Tr.t("Known issues"), "!", Sheet.WARNING_TEXT, e.known);
        rowsScroll.scrollTo(0, 0);
    }

    /** A label, then one card per change, each with its mark on the left. */
    private void group(String label, String mark, int markColor, String[] lines) {
        if (lines.length == 0) return;
        final TextView title = text(label, 13, LauncherActivity.MUTED);
        title.setTypeface(LauncherActivity.MEDIUM);
        rows.addView(title, matchWidth(dp(18)));
        for (String line : lines) {
            final LinearLayout card = new LinearLayout(activity);
            card.setOrientation(LinearLayout.HORIZONTAL);
            card.setGravity(Gravity.CENTER_VERTICAL);
            card.setPadding(dp(18), dp(14), dp(14), dp(14));
            card.setBackground(rounded(LauncherActivity.SURFACE, dp(18)));
            final TextView markView = text(mark, 16, markColor);
            markView.setTypeface(Typeface.DEFAULT_BOLD);
            markView.setGravity(Gravity.CENTER);
            card.addView(markView, new LinearLayout.LayoutParams(dp(22), LinearLayout.LayoutParams.WRAP_CONTENT));
            final TextView words = text(Tr.t(line), 15, Color.WHITE);
            final LinearLayout.LayoutParams wordsParams =
                    new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
            wordsParams.leftMargin = dp(10);
            card.addView(words, wordsParams);
            rows.addView(card, matchWidth(dp(8)));
        }
    }

    private TextView text(String value, int sp, int color) {
        final TextView view = new TextView(activity);
        view.setText(value);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        view.setTextColor(color);
        return view;
    }

    private static GradientDrawable rounded(int color, int radius) {
        final GradientDrawable shape = new GradientDrawable();
        shape.setCornerRadius(radius);
        shape.setColor(color);
        return shape;
    }

    private static LinearLayout.LayoutParams matchWidth(int topMargin) {
        final LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = topMargin;
        return params;
    }

    private int dp(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }
}
