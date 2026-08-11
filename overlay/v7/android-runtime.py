#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit('usage: android-runtime.py <godot-project> <android-build-root>')

project = Path(sys.argv[1]).resolve()
android_root = Path(sys.argv[2]).resolve()
java_dirs = [p.parent for p in android_root.rglob('DeskSawOverlayService.java')]
if len(java_dirs) != 1:
    raise SystemExit(f'Expected one DeskSawOverlayService.java, got {java_dirs}')
java_dir = java_dirs[0]

service = r'''package com.godot.game;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Point;
import android.graphics.Rect;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Process;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceView;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;

import androidx.annotation.Nullable;

import org.godotengine.godot.Godot;
import org.godotengine.godot.GodotHost;
import org.godotengine.godot.GodotRenderView;
import org.godotengine.godot.plugin.GodotPlugin;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Foreground Android desktop-pet host.
 *
 * Android 12+ deliberately distrusts pass-through TYPE_APPLICATION_OVERLAY windows.
 * Therefore the Godot visual window is NOT full-screen and NOT FLAG_NOT_TOUCHABLE.
 * It is continuously cropped around the visible DeskSaw interaction regions. Outside
 * those bounds there is no DeskSaw window at all, so launcher/app touches are native.
 */
public final class DeskSawOverlayService extends Service implements GodotHost, SensorEventListener {
    private static final String TAG = "DeskSawOverlay";
    public static final String ACTION_START = "org.deedee14.desksaw.android.action.START";
    public static final String ACTION_STOP = "org.deedee14.desksaw.android.action.STOP";

    private static final String PREFS = "desksaw_overlay_state";
    private static final String PREF_RUNNING = "running";
    private static final String CHANNEL_ID = "desksaw_overlay";
    private static final int NOTIFICATION_ID = 1402;

    private static final int REGION_MIN_SIZE = 4;
    private static final int VISUAL_MIN_SIZE = 8;
    private static final int VISUAL_MARGIN = 40;
    private static final long VISUAL_REFRAME_DELAY_MS = 16L;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Map<String, TouchProxy> touchProxies = new LinkedHashMap<>();

    private WindowManager windowManager;
    private Godot godot;
    private DeskSawOverlayPlugin overlayPlugin;
    private FrameLayout godotContainer;
    private WindowManager.LayoutParams visualParams;
    private boolean engineStarted = false;
    private boolean shuttingDown = false;
    private boolean visualReframeScheduled = false;

    private volatile int visualOriginX = 0;
    private volatile int visualOriginY = 0;
    private volatile int visualWidth = VISUAL_MIN_SIZE;
    private volatile int visualHeight = VISUAL_MIN_SIZE;

    private volatile boolean pointerDown = false;
    private volatile float pointerX = 0.0f;
    private volatile float pointerY = 0.0f;
    private volatile int pointerSequence = 0;
    private volatile String pointerOwner = "";

    private SensorManager sensorManager;
    private Sensor activeGravitySensor;
    private boolean accelerometerFallback = false;
    private volatile boolean hasGravitySample = false;
    private volatile float gravityScreenX = 0.0f;
    private volatile float gravityScreenY = 1.0f;
    private float filteredAccelX = 0.0f;
    private float filteredAccelY = 0.0f;
    private boolean accelFilterReady = false;

    public static boolean isMarkedRunning(Context context) {
        return context.getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean(PREF_RUNNING, false);
    }

    public static void setMarkedRunning(Context context, boolean running) {
        SharedPreferences.Editor editor = context.getSharedPreferences(PREFS, MODE_PRIVATE).edit();
        editor.putBoolean(PREF_RUNNING, running).apply();
    }

    @Override
    public void onCreate() {
        super.onCreate();
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        sensorManager = (SensorManager) getSystemService(SENSOR_SERVICE);
        createNotificationChannel();
        startAsForeground();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            Log.e(TAG, "Overlay permission is missing; stopping service.");
            stopSelf();
            return;
        }

        setMarkedRunning(this, true);
        registerGravitySensor();
        initializeGodotOverlay();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            setMarkedRunning(this, false);
            stopSelf();
            return START_NOT_STICKY;
        }
        return START_STICKY;
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void initializeGodotOverlay() {
        try {
            godot = Godot.getInstance(getApplicationContext());
            overlayPlugin = new DeskSawOverlayPlugin(godot, this);

            if (!godot.initEngine(this, Collections.emptyList(), getHostPlugins(godot))) {
                throw new IllegalStateException("Godot.initEngine() failed");
            }

            godotContainer = godot.onInitRenderView(this);
            if (godotContainer == null) {
                throw new IllegalStateException("Godot render view was not created");
            }

            godotContainer.setBackgroundColor(Color.TRANSPARENT);
            GodotRenderView renderView = godot.getRenderView();
            if (renderView != null) {
                SurfaceView surface = renderView.getView();
                surface.setZOrderOnTop(true);
                surface.getHolder().setFormat(PixelFormat.TRANSLUCENT);
                surface.setBackgroundColor(Color.TRANSPARENT);
            }

            addVisualOverlay();
            godot.onStart(this);
            godot.onResume(this);
            engineStarted = true;
            Log.i(TAG, "DeskSaw overlay engine started.");
        } catch (Throwable error) {
            Log.e(TAG, "Unable to start DeskSaw overlay", error);
            setMarkedRunning(this, false);
            stopSelf();
        }
    }

    private int overlayWindowType() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            return WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY;
        }
        return WindowManager.LayoutParams.TYPE_PHONE;
    }

    private void addVisualOverlay() {
        visualParams = new WindowManager.LayoutParams(
                VISUAL_MIN_SIZE,
                VISUAL_MIN_SIZE,
                overlayWindowType(),
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);
        visualParams.gravity = Gravity.TOP | Gravity.START;
        visualParams.x = 0;
        visualParams.y = 0;
        visualParams.alpha = 1.0f;
        visualParams.setTitle("deskSaw");
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            visualParams.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        }
        windowManager.addView(godotContainer, visualParams);
    }

    public void setTouchRegion(String id, float x, float y, float width, float height) {
        final RegionSpec requested = new RegionSpec(x, y, width, height);
        mainHandler.post(() -> applyTouchRegion(id, requested));
    }

    public void removeTouchRegion(String id) {
        mainHandler.post(() -> {
            TouchProxy proxy = touchProxies.get(id);
            if (proxy != null) {
                if (proxy.gestureActive) {
                    proxy.removeAfterGesture = true;
                } else {
                    touchProxies.remove(id);
                    safeRemoveView(proxy.view);
                }
            }
            scheduleVisualReframe();
        });
    }

    private void applyTouchRegion(String id, RegionSpec requested) {
        if (shuttingDown || windowManager == null || godot == null) {
            return;
        }

        RegionSpec spec = requested.clamp(getDisplaySize());
        if (spec.width < REGION_MIN_SIZE || spec.height < REGION_MIN_SIZE) {
            removeTouchRegion(id);
            return;
        }

        TouchProxy proxy = touchProxies.get(id);
        if (proxy == null) {
            TouchProxyView view = new TouchProxyView(this);
            WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                    spec.width,
                    spec.height,
                    overlayWindowType(),
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                            | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                            | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                            | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                    PixelFormat.TRANSLUCENT);
            params.gravity = Gravity.TOP | Gravity.START;
            params.x = spec.x;
            params.y = spec.y;
            params.alpha = 0.01f;
            params.setTitle("deskSaw touch " + id);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                params.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
            }
            proxy = new TouchProxy(id, view, params, spec);
            view.proxy = proxy;
            touchProxies.put(id, proxy);
            try {
                windowManager.addView(view, params);
            } catch (RuntimeException error) {
                touchProxies.remove(id);
                Log.e(TAG, "Failed to add touch region " + id, error);
            }
            scheduleVisualReframe();
            return;
        }

        if (proxy.gestureActive) {
            proxy.pendingSpec = spec;
            scheduleVisualReframe();
            return;
        }
        applyProxySpec(proxy, spec);
        scheduleVisualReframe();
    }

    private void applyProxySpec(TouchProxy proxy, RegionSpec spec) {
        if (proxy.spec.nearlyEquals(spec)) {
            proxy.pendingSpec = null;
            return;
        }
        proxy.spec = spec;
        proxy.pendingSpec = null;
        proxy.params.x = spec.x;
        proxy.params.y = spec.y;
        proxy.params.width = spec.width;
        proxy.params.height = spec.height;
        try {
            windowManager.updateViewLayout(proxy.view, proxy.params);
        } catch (RuntimeException error) {
            Log.w(TAG, "Failed to update touch region " + proxy.id, error);
        }
    }

    private void finishProxyGesture(TouchProxy proxy) {
        proxy.gestureActive = false;
        if (proxy.removeAfterGesture) {
            proxy.removeAfterGesture = false;
            touchProxies.remove(proxy.id);
            safeRemoveView(proxy.view);
            scheduleVisualReframe();
            return;
        }
        if (proxy.pendingSpec != null) {
            applyProxySpec(proxy, proxy.pendingSpec);
        }
        scheduleVisualReframe();
    }

    private void updateNativePointer(TouchProxy proxy, MotionEvent event) {
        int action = event.getActionMasked();
        float screenX = event.getX(0) + proxy.params.x;
        float screenY = event.getY(0) + proxy.params.y;

        if (action == MotionEvent.ACTION_DOWN) {
            pointerSequence += 1;
            pointerOwner = proxy.id;
            pointerX = screenX;
            pointerY = screenY;
            pointerDown = true;
        } else if (pointerDown && proxy.id.equals(pointerOwner)) {
            pointerX = screenX;
            pointerY = screenY;
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                pointerDown = false;
            }
        }
    }

    private boolean forwardTouch(TouchProxy proxy, MotionEvent event) {
        if (godot == null) {
            return false;
        }
        GodotRenderView renderView = godot.getRenderView();
        if (renderView == null || renderView.getInputHandler() == null) {
            return false;
        }

        MotionEvent translated = MotionEvent.obtain(event);
        translated.offsetLocation(proxy.params.x - visualOriginX, proxy.params.y - visualOriginY);
        try {
            return renderView.getInputHandler().onTouchEvent(translated);
        } finally {
            translated.recycle();
        }
    }

    private void scheduleVisualReframe() {
        if (visualReframeScheduled || shuttingDown) {
            return;
        }
        visualReframeScheduled = true;
        mainHandler.postDelayed(() -> {
            visualReframeScheduled = false;
            updateVisualFrame();
        }, VISUAL_REFRAME_DELAY_MS);
    }

    private void updateVisualFrame() {
        if (visualParams == null || godotContainer == null || windowManager == null) {
            return;
        }

        RegionSpec bounds = null;
        for (TouchProxy proxy : touchProxies.values()) {
            RegionSpec candidate = (proxy.gestureActive && proxy.pendingSpec != null) ? proxy.pendingSpec : proxy.spec;
            if (candidate == null || candidate.width <= 0 || candidate.height <= 0) {
                continue;
            }
            bounds = bounds == null ? candidate : bounds.union(candidate);
        }

        Point display = getDisplaySize();
        if (bounds == null) {
            bounds = new RegionSpec(0, 0, VISUAL_MIN_SIZE, VISUAL_MIN_SIZE);
        } else {
            bounds = bounds.grow(VISUAL_MARGIN).clamp(display);
            if (bounds.width < VISUAL_MIN_SIZE || bounds.height < VISUAL_MIN_SIZE) {
                bounds = new RegionSpec(0, 0, VISUAL_MIN_SIZE, VISUAL_MIN_SIZE);
            }
        }

        if (Math.abs(visualParams.x - bounds.x) <= 1
                && Math.abs(visualParams.y - bounds.y) <= 1
                && Math.abs(visualParams.width - bounds.width) <= 1
                && Math.abs(visualParams.height - bounds.height) <= 1) {
            return;
        }

        visualParams.x = bounds.x;
        visualParams.y = bounds.y;
        visualParams.width = bounds.width;
        visualParams.height = bounds.height;
        visualOriginX = bounds.x;
        visualOriginY = bounds.y;
        visualWidth = bounds.width;
        visualHeight = bounds.height;
        try {
            windowManager.updateViewLayout(godotContainer, visualParams);
        } catch (RuntimeException error) {
            Log.w(TAG, "Unable to reframe visual overlay", error);
        }
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        if (godot != null) {
            try {
                godot.onConfigurationChanged(newConfig);
            } catch (Throwable error) {
                Log.w(TAG, "Godot configuration update failed", error);
            }
        }
        mainHandler.postDelayed(this::reclampAfterRotation, 80L);
    }

    private void reclampAfterRotation() {
        Point display = getDisplaySize();
        for (TouchProxy proxy : touchProxies.values()) {
            if (proxy.gestureActive) {
                if (proxy.pendingSpec != null) {
                    proxy.pendingSpec = proxy.pendingSpec.clamp(display);
                }
                continue;
            }
            applyProxySpec(proxy, proxy.spec.clamp(display));
        }
        scheduleVisualReframe();
    }

    private Point getDisplaySize() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Rect bounds = windowManager.getMaximumWindowMetrics().getBounds();
            return new Point(Math.max(1, bounds.width()), Math.max(1, bounds.height()));
        }
        Point point = new Point();
        windowManager.getDefaultDisplay().getRealSize(point);
        point.x = Math.max(1, point.x);
        point.y = Math.max(1, point.y);
        return point;
    }

    public int getDisplayWidth() { return getDisplaySize().x; }
    public int getDisplayHeight() { return getDisplaySize().y; }
    public int getVisualX() { return visualOriginX; }
    public int getVisualY() { return visualOriginY; }
    public int getVisualWidth() { return visualWidth; }
    public int getVisualHeight() { return visualHeight; }
    public boolean isPointerDown() { return pointerDown; }
    public float getPointerX() { return pointerX; }
    public float getPointerY() { return pointerY; }
    public int getPointerSequence() { return pointerSequence; }
    public String getPointerOwner() { return pointerOwner == null ? "" : pointerOwner; }

    private void registerGravitySensor() {
        if (sensorManager == null) {
            return;
        }
        activeGravitySensor = sensorManager.getDefaultSensor(Sensor.TYPE_GRAVITY);
        accelerometerFallback = false;
        if (activeGravitySensor == null) {
            activeGravitySensor = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
            accelerometerFallback = true;
        }
        if (activeGravitySensor != null) {
            sensorManager.registerListener(this, activeGravitySensor, SensorManager.SENSOR_DELAY_GAME, mainHandler);
            Log.i(TAG, "Native gravity sensor=" + activeGravitySensor.getName() + " accelerometerFallback=" + accelerometerFallback);
        } else {
            Log.w(TAG, "No gravity or accelerometer sensor is available.");
        }
    }

    @Override
    public void onSensorChanged(SensorEvent event) {
        if (event == null || event.sensor != activeGravitySensor || event.values.length < 2) {
            return;
        }
        float x = event.values[0];
        float y = event.values[1];
        if (accelerometerFallback) {
            final float alpha = 0.18f;
            if (!accelFilterReady) {
                filteredAccelX = x;
                filteredAccelY = y;
                accelFilterReady = true;
            } else {
                filteredAccelX += alpha * (x - filteredAccelX);
                filteredAccelY += alpha * (y - filteredAccelY);
            }
            x = filteredAccelX;
            y = filteredAccelY;
        }

        int rotation = windowManager.getDefaultDisplay().getRotation();
        float rx;
        float ry;
        switch (rotation) {
            case Surface.ROTATION_90:
                rx = y;
                ry = -x;
                break;
            case Surface.ROTATION_180:
                rx = -x;
                ry = -y;
                break;
            case Surface.ROTATION_270:
                rx = -y;
                ry = x;
                break;
            case Surface.ROTATION_0:
            default:
                rx = x;
                ry = y;
                break;
        }
        gravityScreenX = rx;
        gravityScreenY = -ry;
        hasGravitySample = (rx * rx + ry * ry) > 0.08f;
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {
    }

    public boolean hasGravitySample() { return hasGravitySample; }
    public float getGravityX() { return gravityScreenX; }
    public float getGravityY() { return gravityScreenY; }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "DeskSaw desktop pet", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("Keeps DeskSaw visible above other apps.");
        channel.setShowBadge(false);
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    private void startAsForeground() {
        Intent stopIntent = new Intent(this, DeskSawOverlayService.class).setAction(ACTION_STOP);
        PendingIntent stopPending = PendingIntent.getService(this, 2, stopIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Intent launcherIntent = getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent launcherPending = launcherIntent == null ? null : PendingIntent.getActivity(this, 1, launcherIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        int icon = getApplicationInfo().icon != 0 ? getApplicationInfo().icon : android.R.drawable.sym_def_app_icon;
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O ? new Notification.Builder(this, CHANNEL_ID) : new Notification.Builder(this);
        builder.setSmallIcon(icon)
                .setContentTitle("DeskSaw is roaming")
                .setContentText("Tap the app icon again or press Stop to close it.")
                .setOngoing(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setShowWhen(false)
                .addAction(new Notification.Action.Builder(null, "Stop", stopPending).build());
        if (launcherPending != null) builder.setContentIntent(launcherPending);
        Notification notification = builder.build();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    @Override
    public void onDestroy() {
        if (shuttingDown) {
            super.onDestroy();
            return;
        }
        shuttingDown = true;
        setMarkedRunning(this, false);
        if (sensorManager != null) sensorManager.unregisterListener(this);
        pointerDown = false;

        for (TouchProxy proxy : touchProxies.values()) safeRemoveView(proxy.view);
        touchProxies.clear();
        if (godotContainer != null) safeRemoveView(godotContainer);

        try {
            if (godot != null && godot.isInitialized()) {
                if (engineStarted) {
                    godot.onPause(this);
                    godot.onStop(this);
                }
                godot.onDestroy(this);
            }
        } catch (Throwable error) {
            Log.w(TAG, "Error while stopping Godot", error);
        }

        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
        mainHandler.postDelayed(() -> {
            Process.killProcess(Process.myPid());
            Runtime.getRuntime().exit(0);
        }, 80L);
    }

    private void safeRemoveView(View view) {
        if (view == null || windowManager == null) return;
        try { windowManager.removeViewImmediate(view); } catch (RuntimeException ignored) { }
    }

    @Nullable @Override public Activity getActivity() { return null; }
    @Override public Godot getGodot() { return godot; }
    @Override public List<String> getCommandLine() { return Collections.emptyList(); }
    @Override public Set<GodotPlugin> getHostPlugins(Godot engine) {
        if (overlayPlugin == null) overlayPlugin = new DeskSawOverlayPlugin(engine, this);
        return Collections.singleton(overlayPlugin);
    }
    @Override public void runOnHostThread(Runnable action) {
        if (action == null) return;
        if (Looper.myLooper() == Looper.getMainLooper()) action.run(); else mainHandler.post(action);
    }
    @Override public void onGodotForceQuit(Godot instance) { if (instance == godot) stopSelf(); }
    @Override public void onGodotRestartRequested(Godot instance) { if (instance == godot) stopSelf(); }

    private final class TouchProxyView extends View {
        TouchProxy proxy;
        TouchProxyView(Context context) {
            super(context);
            setBackgroundColor(Color.TRANSPARENT);
            setClickable(true);
        }
        @Override
        public boolean onTouchEvent(MotionEvent event) {
            if (proxy == null) return false;
            final int action = event.getActionMasked();
            if (action == MotionEvent.ACTION_DOWN) {
                proxy.gestureActive = true;
                proxy.pendingSpec = null;
                proxy.removeAfterGesture = false;
            }
            updateNativePointer(proxy, event);
            boolean handled = forwardTouch(proxy, event);
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                mainHandler.post(() -> finishProxyGesture(proxy));
            }
            return action == MotionEvent.ACTION_DOWN || proxy.gestureActive || handled;
        }
    }

    private static final class TouchProxy {
        final String id;
        final TouchProxyView view;
        final WindowManager.LayoutParams params;
        RegionSpec spec;
        RegionSpec pendingSpec;
        boolean gestureActive;
        boolean removeAfterGesture;
        TouchProxy(String id, TouchProxyView view, WindowManager.LayoutParams params, RegionSpec spec) {
            this.id = id;
            this.view = view;
            this.params = params;
            this.spec = spec;
        }
    }

    private static final class RegionSpec {
        final int x;
        final int y;
        final int width;
        final int height;
        RegionSpec(float x, float y, float width, float height) {
            int left = (int) Math.floor(x);
            int top = (int) Math.floor(y);
            int right = (int) Math.ceil(x + Math.max(0.0f, width));
            int bottom = (int) Math.ceil(y + Math.max(0.0f, height));
            this.x = left;
            this.y = top;
            this.width = Math.max(0, right - left);
            this.height = Math.max(0, bottom - top);
        }
        RegionSpec(int x, int y, int width, int height) {
            this.x = x; this.y = y; this.width = width; this.height = height;
        }
        RegionSpec clamp(Point display) {
            int left = Math.max(0, Math.min(x, display.x));
            int top = Math.max(0, Math.min(y, display.y));
            int right = Math.max(left, Math.min(x + width, display.x));
            int bottom = Math.max(top, Math.min(y + height, display.y));
            return new RegionSpec(left, top, right - left, bottom - top);
        }
        RegionSpec grow(int amount) { return new RegionSpec(x - amount, y - amount, width + amount * 2, height + amount * 2); }
        RegionSpec union(RegionSpec other) {
            int left = Math.min(x, other.x);
            int top = Math.min(y, other.y);
            int right = Math.max(x + width, other.x + other.width);
            int bottom = Math.max(y + height, other.y + other.height);
            return new RegionSpec(left, top, right - left, bottom - top);
        }
        boolean nearlyEquals(RegionSpec other) {
            return Math.abs(x - other.x) <= 1 && Math.abs(y - other.y) <= 1 && Math.abs(width - other.width) <= 1 && Math.abs(height - other.height) <= 1;
        }
    }
}
'''

plugin = r'''package com.godot.game;

import androidx.annotation.NonNull;
import org.godotengine.godot.Godot;
import org.godotengine.godot.plugin.GodotPlugin;
import org.godotengine.godot.plugin.UsedByGodot;

public final class DeskSawOverlayPlugin extends GodotPlugin {
    private final DeskSawOverlayService service;
    DeskSawOverlayPlugin(Godot godot, DeskSawOverlayService service) {
        super(godot);
        this.service = service;
    }
    @NonNull @Override public String getPluginName() { return "DeskSawOverlay"; }
    @UsedByGodot public void setTouchRegion(String id, float x, float y, float width, float height) { if (id != null && !id.isEmpty()) service.setTouchRegion(id, x, y, width, height); }
    @UsedByGodot public void removeTouchRegion(String id) { if (id != null && !id.isEmpty()) service.removeTouchRegion(id); }
    @UsedByGodot public boolean isOverlayRunning() { return true; }
    @UsedByGodot public boolean isPointerDown() { return service.isPointerDown(); }
    @UsedByGodot public float getPointerX() { return service.getPointerX(); }
    @UsedByGodot public float getPointerY() { return service.getPointerY(); }
    @UsedByGodot public int getPointerSequence() { return service.getPointerSequence(); }
    @UsedByGodot public String getPointerOwner() { return service.getPointerOwner(); }
    @UsedByGodot public int getDisplayWidth() { return service.getDisplayWidth(); }
    @UsedByGodot public int getDisplayHeight() { return service.getDisplayHeight(); }
    @UsedByGodot public int getVisualX() { return service.getVisualX(); }
    @UsedByGodot public int getVisualY() { return service.getVisualY(); }
    @UsedByGodot public int getVisualWidth() { return service.getVisualWidth(); }
    @UsedByGodot public int getVisualHeight() { return service.getVisualHeight(); }
    @UsedByGodot public boolean hasGravitySample() { return service.hasGravitySample(); }
    @UsedByGodot public float getGravityX() { return service.getGravityX(); }
    @UsedByGodot public float getGravityY() { return service.getGravityY(); }
}
'''

(java_dir / 'DeskSawOverlayService.java').write_text(service, encoding='utf-8')
(java_dir / 'DeskSawOverlayPlugin.java').write_text(plugin, encoding='utf-8')

import re
preset = project / 'export_presets.cfg'
text = preset.read_text(encoding='utf-8')
text = re.sub(r'version/code=\d+', 'version/code=203', text)
text = re.sub(r'version/name="[^"]+"', 'version/name="0.2.2"', text)
preset.write_text(text, encoding='utf-8')
print('Applied Android runtime v7: cropped touchable visual overlay + native pointer + native gravity')
