package io.github.dezer04.sb3utage;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.Process;
import android.util.Log;

/**
 * A foreground service in the game's process for as long as the game runs, so a game left in the
 * background stays a foreground-service process instead of a cached one. Without it Android ended
 * the paused game for memory within seconds of the player opening another app (Poco X6, HyperOS:
 * three times in one evening, LOW_MEMORY at importance 400, 1.0.6-dev9).
 *
 * <p>The notification needs no permission to keep the service: on Android 13 and later without
 * "notifications allowed" it is simply not shown. Swiping the game out of Recents still ends it
 * (onTaskRemoved), as it did when nothing kept the process.
 */
public final class GameSessionService extends Service {
    private static final String TAG = "Basara";
    private static final String CHANNEL = "game_session";
    private static final int NOTIFICATION_ID = 1;

    /** From GameActivity.onCreate, while the game is on screen (a background start is refused). */
    static void start(Context context) {
        try {
            context.startForegroundService(new Intent(context, GameSessionService.class));
        } catch (RuntimeException e) {
            Log.w(TAG, "could not start the game session service", e);
        }
    }

    static void stop(Context context) {
        context.stopService(new Intent(context, GameSessionService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTIFICATION_ID, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(NOTIFICATION_ID, notification());
            }
        } catch (RuntimeException e) {
            Log.w(TAG, "game session service could not go to the foreground", e);
            stopSelf();
        }
        // Not restarted on its own: the game process ends with the game.
        return START_NOT_STICKY;
    }

    private Notification notification() {
        final NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null && nm.getNotificationChannel(CHANNEL) == null) {
            final NotificationChannel channel = new NotificationChannel(CHANNEL, Tr.t("Game running"),
                    NotificationManager.IMPORTANCE_LOW);
            channel.setDescription(Tr.t("Keeps the game in memory while you use another app."));
            channel.setShowBadge(false);
            nm.createNotificationChannel(channel);
        }
        final Intent open = new Intent(this, GameActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        final PendingIntent tap = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_play)
                .setContentTitle(getApplicationInfo().loadLabel(getPackageManager()))
                .setContentText(Tr.t("The game is kept in memory. Tap to go back to it."))
                .setContentIntent(tap)
                .setOngoing(true)
                .setShowWhen(false)
                .setCategory(Notification.CATEGORY_SERVICE)
                .build();
    }

    /**
     * Swiped out of Recents: end the game as before. A process with a foreground service outlives its
     * removed task, and the runtime starts only once per process, so the next start would find it.
     */
    @Override
    public void onTaskRemoved(Intent rootIntent) {
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
        CrashReport.endedOnPurpose(this, Process.myPid());
        Process.killProcess(Process.myPid());
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
