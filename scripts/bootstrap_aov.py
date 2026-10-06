#!/usr/bin/env python3
import os
import base64
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path("output")
OUT.mkdir(exist_ok=True)

PKG_PLAY = "com.android.vending"
PKG_AOV = "com.garena.game.kgvn"

GOOGLE_EMAIL = os.environ.get("GOOGLE_EMAIL", "")
GOOGLE_PASSWORD = os.environ.get("GOOGLE_PASSWORD", "")
AOV_USERNAME = os.environ.get("AOV_USERNAME", "")
AOV_PASSWORD = os.environ.get("AOV_PASSWORD", "")

VERIFY_TIMEOUT = int(os.environ.get("GOOGLE_VERIFY_TIMEOUT", "900"))
INSTALL_TIMEOUT = int(os.environ.get("AOV_INSTALL_TIMEOUT", "1200"))
GAME_READY_TIMEOUT = int(os.environ.get("AOV_GAME_READY_TIMEOUT", "900"))
AOV_RESOURCE_TIMEOUT = int(os.environ.get("AOV_RESOURCE_TIMEOUT", "600"))
AOV_RESOURCE_MIN_WAIT = int(os.environ.get("AOV_RESOURCE_MIN_WAIT", "60"))

def log(msg):
    print(msg, flush=True)

def run(cmd, check=False, capture=True, timeout=120):
    if isinstance(cmd, str):
        raise TypeError("cmd must be a list")
    p = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        timeout=timeout,
        check=False,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}\n{p.stdout or ''}")
    return (p.stdout or "").strip()

def adb(*args, check=False, timeout=120):
    return run(["adb", *args], check=check, timeout=timeout)

def write_result(state, detail=""):
    text = state + ("\n" + detail if detail else "") + "\n"
    (OUT / "result.txt").write_text(text, encoding="utf-8")
    log(f"RESULT={state}")
    if detail:
        log(detail)

def screenshot(name):
    path = OUT / f"{name}.png"
    with path.open("wb") as f:
        subprocess.run(["adb", "exec-out", "screencap", "-p"], stdout=f, stderr=subprocess.DEVNULL, check=False)
    return path

LAST_DUMP_OUTPUT = ""

def uiautomator_dump(remote="/sdcard/window.xml"):
    # Delete the previous dump first. When uiautomator cannot get an idle
    # screen (e.g. an autoplaying video) it writes nothing, and reading the old
    # file would silently return a stale screen.
    global LAST_DUMP_OUTPUT
    adb("shell", "rm", "-f", remote, timeout=30)
    LAST_DUMP_OUTPUT = adb("shell", "uiautomator", "dump", remote, timeout=60)
    return subprocess.run(
        ["adb", "exec-out", f"cat {remote} 2>/dev/null"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout

def dump_ui(name="window"):
    raw = uiautomator_dump()
    path = OUT / f"{name}.xml"
    path.write_bytes(raw)
    try:
        return ET.fromstring(raw)
    except Exception:
        return None

def bounds_center(bounds):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)

def node_blob(node):
    vals = [
        node.attrib.get("text", ""),
        node.attrib.get("content-desc", ""),
        node.attrib.get("resource-id", ""),
        node.attrib.get("class", ""),
    ]
    return " ".join(vals).lower()

def label_blob(node):
    # Human-visible labels only. Do not include package/resource-id here:
    # com.garena.game.kgvn:id/unitySurfaceView previously matched "garena".
    vals = [
        node.attrib.get("text", ""),
        node.attrib.get("content-desc", ""),
    ]
    return " ".join(vals).strip().lower()

def visible_label_blob(node):
    vals = [
        node.attrib.get("text", ""),
        node.attrib.get("content-desc", ""),
    ]
    return " ".join(vals).strip().lower()


def find_visible_label_nodes(needles):
    root = dump_ui("latest-ui")
    if root is None:
        return []

    wanted = [n.lower() for n in needles]
    out = []
    for n in root.iter("node"):
        blob = visible_label_blob(n)
        if not blob or not any(x in blob for x in wanted):
            continue
        center = bounds_center(n.attrib.get("bounds", ""))
        if center:
            out.append((n, center, blob))
    return out


def tap_visible_label_needles(needles, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        nodes = find_visible_label_nodes(needles)
        if nodes:
            nodes.sort(key=lambda item: item[0].attrib.get("clickable") != "true")
            n, (x, y), label = nodes[0]
            log(f"Tapping visible UI label: {label[:140]}")
            tap_xy(x, y)
            time.sleep(2)
            return True
        time.sleep(2)
    return False


def find_nodes(needles=None, class_contains=None):
    root = dump_ui("latest-ui")
    if root is None:
        return []
    needles = [n.lower() for n in (needles or [])]
    out = []
    for n in root.iter("node"):
        blob = node_blob(n)
        if needles and not any(x in blob for x in needles):
            continue
        if class_contains and class_contains.lower() not in n.attrib.get("class", "").lower():
            continue
        c = bounds_center(n.attrib.get("bounds", ""))
        if c:
            out.append((n, c, blob))
    return out

def find_label_nodes(needles=None):
    root = dump_ui("latest-ui")
    if root is None:
        return []
    needles = [n.lower() for n in (needles or [])]
    out = []
    for n in root.iter("node"):
        blob = label_blob(n)
        if not blob:
            continue
        if needles and not any(x in blob for x in needles):
            continue
        center = bounds_center(n.attrib.get("bounds", ""))
        if center:
            out.append((n, center, blob))
    return out

def tap_label_needles(needles, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        nodes = find_label_nodes(needles)
        if nodes:
            nodes.sort(key=lambda item: item[0].attrib.get("clickable") != "true")
            _, (x, y), blob = nodes[0]
            log(f"Tapping visible UI label: {blob[:120]}")
            tap_xy(x, y)
            time.sleep(2)
            return True
        time.sleep(2)
    return False

def tap_xy(x, y):
    adb("shell", "input", "tap", str(x), str(y))

def screen_size():
    out = adb("shell", "wm", "size")
    m = re.search(r"(\d+)x(\d+)", out)
    if not m:
        return (1080, 2400)
    return (int(m.group(1)), int(m.group(2)))

def tap_fraction(xf, yf):
    w, h = screen_size()
    x = int(w * xf)
    y = int(h * yf)
    log(f"Tapping fallback coordinate at {xf:.2f}w, {yf:.2f}h -> ({x},{y})")
    tap_xy(x, y)

def ui_text():
    raw = uiautomator_dump()
    try:
        root = ET.fromstring(raw)
    except Exception:
        return ""
    return "\n".join(node_blob(n) for n in root.iter("node"))

def wait_ui_contains(markers, timeout=30):
    markers = [m.lower() for m in markers]
    end = time.time() + timeout
    while time.time() < end:
        blob = ui_text()
        if any(m in blob for m in markers):
            return blob
        time.sleep(2)
    return ""

def extract_google_number_match(blob):
    # Prefer an accessibility node/text fragment that is exactly a 2-digit
    # number. Google number matching normally renders the challenge number as
    # standalone text.
    exact = re.findall(r"(?m)^\s*(\d{2})\s*$", blob)
    if exact:
        return exact[0]

    # Fallback to contextual phrases used by Google verification screens.
    patterns = [
        r"(?:tap|select|choose|pick)\D{0,50}(\d{2})\b",
        r"\b(\d{2})\b\D{0,50}(?:on your phone|on your device)",
    ]
    for pattern in patterns:
        m = re.search(pattern, blob, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def report_google_verification(blob, previous_number=None):
    number = extract_google_number_match(blob)
    if number and number != previous_number:
        log("=" * 56)
        log(f"GOOGLE_NUMBER_MATCH={number}")
        log(f"On your trusted phone, approve the sign-in and choose {number}.")
        log("=" * 56)
        return number

    lower = blob.lower()
    if any(marker in lower for marker in [
        "enter the number shown on your phone",
        "enter the number shown on your device",
        "nhập số hiển thị trên điện thoại",
    ]):
        log("GOOGLE_VERIFICATION_REQUIRES_NUMBER_INPUT_FROM_TRUSTED_DEVICE")
        log("This flow needs a number from your trusted phone entered into the emulator.")
    return previous_number

def handle_google_signin_intro():
    blob = ui_text().lower()
    if any(x in blob for x in [
        "sign in with ease",
        "search for accounts connected to this phone number",
        "we can search for accounts connected to this phone number",
    ]):
        log("Google 'Sign in with ease' intro detected.")
        if not tap_exact_text(["Skip", "Bỏ qua"], timeout=5):
            log("Skip is not exposed; using fixed bottom-left Pixel 7 coordinate.")
            tap_fraction(0.08, 0.93)
            time.sleep(2)
        return True
    return False

def dismiss_google_account_info_dialog():
    # Google may show an informational modal immediately after opening the
    # account-add screen. It blocks the identifier field and must be closed
    # before we try to type.
    if tap_exact_text(["Close", "Đóng"], timeout=3):
        log("Dismissed Google Account informational dialog via button label.")
        return True

    blob = ui_text()
    if any(marker in blob for marker in [
        "your device works better with a google account",
        "sign in to google services",
        "your device works better",
    ]):
        log("Google Account informational dialog detected; dismissing by fixed Pixel 7 coordinate.")
        tap_fraction(0.82, 0.57)
        time.sleep(2)
        return True

    # On this Google account screen the modal is not always fully exposed to
    # UIAutomator. A single tap at the known Close-button position is harmless
    # on the underlying identifier page and dismisses the modal when present.
    log("Trying one safe fallback tap at the Google Account dialog Close position.")
    tap_fraction(0.82, 0.57)
    time.sleep(2)
    return False

def tap_needles(needles, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        nodes = find_nodes(needles=needles)
        if nodes:
            # Prefer explicitly clickable nodes.
            nodes.sort(key=lambda item: item[0].attrib.get("clickable") != "true")
            n, (x, y), blob = nodes[0]
            log(f"Tapping UI match: {blob[:140]}")
            tap_xy(x, y)
            time.sleep(2)
            return True
        time.sleep(2)
    return False

def tap_exact_text(labels, timeout=20):
    wanted = {x.strip().lower() for x in labels}
    end = time.time() + timeout
    while time.time() < end:
        root = dump_ui("latest-ui")
        if root is not None:
            matches = []
            for n in root.iter("node"):
                text = n.attrib.get("text", "").strip().lower()
                desc = n.attrib.get("content-desc", "").strip().lower()
                if text in wanted or desc in wanted:
                    center = bounds_center(n.attrib.get("bounds", ""))
                    if center:
                        matches.append((n, center, text or desc))
            if matches:
                matches.sort(key=lambda item: item[0].attrib.get("clickable") != "true")
                n, (x, y), label = matches[0]
                log(f"Tapping exact UI label: {label}")
                tap_xy(x, y)
                time.sleep(2)
                return True
        time.sleep(2)
    return False

def edit_nodes():
    return find_nodes(class_contains="EditText")

ADB_IME_ID = "dev.thndang.aovcollector.adbime/.AdbIme"
ADB_IME_ACTION = "dev.thndang.aovcollector.adbime.INPUT"
ADB_IME_READY = False

def setup_adb_ime():
    global ADB_IME_READY
    try:
        apk = run(["bash", "tools/adb-ime/build.sh"], check=True, timeout=180).splitlines()[-1].strip()
        adb("install", "-r", apk, check=True, timeout=120)

        listed = adb("shell", "ime", "list", "-s", timeout=60)
        log("Installed IMEs: " + ", ".join(line.strip() for line in listed.splitlines() if line.strip()))

        enable_out = adb("shell", "ime", "enable", ADB_IME_ID, timeout=60)
        set_out = adb("shell", "ime", "set", ADB_IME_ID, timeout=60)
        state = adb("shell", "settings", "get", "secure", "default_input_method", timeout=60)

        log("IME enable result: " + (enable_out or "<empty>"))
        log("IME set result: " + (set_out or "<empty>"))
        log("Default IME: " + (state or "<empty>"))

        ADB_IME_READY = ADB_IME_ID in state
        log("ADB input method selected." if ADB_IME_READY else "ADB input method selection could not be confirmed; native ADB text input will be used.")
    except Exception as exc:
        ADB_IME_READY = False
        log("ADB IME setup failed; native ADB text input will be used instead: " + str(exc).splitlines()[0])

def restore_system_ime():
    # The custom IME is only needed to enter credentials. Return to Gboard
    # before Google's verification/setup phase to keep the Android account-add
    # flow as close as possible to a normal device session.
    preferred = "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"
    listed = adb("shell", "ime", "list", "-s", timeout=60)
    if preferred in listed:
        adb("shell", "ime", "enable", preferred, timeout=60)
        out = adb("shell", "ime", "set", preferred, timeout=60)
        log("Restored system Google keyboard before verification.")
        return True
    log("System Google keyboard was not available to restore.")
    return False


def input_text(value):
    if ADB_IME_READY:
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        # The secret itself is never printed. It is delivered to our temporary IME over an ADB broadcast.
        adb(
            "shell", "am", "broadcast",
            "-a", ADB_IME_ACTION,
            "--es", "text_b64", encoded,
            timeout=60,
        )
    else:
        # Now that the Google informational modal is dismissed before focusing
        # the field, native ADB text injection can work as a reliable fallback.
        # Passing argv avoids exposing the secret in our own logs.
        adb("shell", "input", "text", value, timeout=60)
    time.sleep(1)

def focused_type(value):
    adb("shell", "input", "keyevent", "KEYCODE_CTRL_A")
    time.sleep(0.3)
    input_text(value)
    time.sleep(0.8)

def resumed_activity():
    out = adb("shell", "dumpsys", "activity", "activities")
    for line in out.splitlines():
        if "mResumedActivity" in line or "topResumedActivity" in line:
            return line.strip()
    return ""


def package_is_foreground(pkg):
    # Android 15 emulator output is not consistent about mResumedActivity.
    # Check multiple system signals, then fall back to the UI hierarchy package.
    activity = adb("shell", "dumpsys", "activity", "activities", timeout=60)
    for line in activity.splitlines():
        if ("mResumedActivity" in line or "topResumedActivity" in line or "ResumedActivity" in line) and pkg in line:
            return True

    windows = adb("shell", "dumpsys", "window", "windows", timeout=60)
    for line in windows.splitlines():
        if ("mCurrentFocus" in line or "mFocusedApp" in line) and pkg in line:
            return True

    raw = uiautomator_dump("/sdcard/foreground.xml").decode("utf-8", errors="ignore")
    return f'package="{pkg}"' in raw

def package_installed(pkg):
    return bool(adb("shell", "pm", "path", pkg).strip())

def aov_pid():
    return adb("shell", "pidof", PKG_AOV, timeout=30).strip()

def start_aov_like_launcher():
    # Send the same intent the launcher icon sends (MAIN/LAUNCHER +
    # NEW_TASK|RESET_TASK_IF_NEEDED). If AOV is already running, Android then
    # just brings its existing task forward. A bare `am start -n <component>`
    # does not match the task's root intent and stacks a second launcher
    # activity on top of the running Unity activity, which can make the game
    # restart or exit.
    resolved = adb(
        "shell", "cmd", "package", "resolve-activity", "--brief",
        "-c", "android.intent.category.LAUNCHER", PKG_AOV,
        timeout=60,
    )
    components = [line.strip() for line in resolved.splitlines() if "/" in line]
    if not components:
        adb("shell", "monkey", "-p", PKG_AOV, "-c", "android.intent.category.LAUNCHER", "1", timeout=60)
        return ""
    return adb(
        "shell", "am", "start", "-W",
        "-a", "android.intent.action.MAIN",
        "-c", "android.intent.category.LAUNCHER",
        "-f", "0x10200000",
        "-n", components[-1],
        timeout=60,
    )

def save_aov_exit_diagnostics(name):
    # Why did AOV leave the foreground? ApplicationExitInfo (Android 11+)
    # records the exit reason (crash, native crash, ANR, low memory, ...).
    # Native crash details (abort message, backtrace) live in the logcat
    # crash buffer and in dropbox; the main buffer is quickly flooded by our
    # own uiautomator calls.
    pid = aov_pid()
    exit_info = adb("shell", "dumpsys", "activity", "exit-info", PKG_AOV, timeout=60)
    crash_buf = adb("logcat", "-d", "-b", "crash", timeout=60)
    tombstones = adb("shell", "dumpsys", "dropbox", "--print", "data_app_native_crash", timeout=60)
    raw = adb("logcat", "-d", "-t", "2000", timeout=60)
    markers = [
        PKG_AOV.lower(),
        "fatal exception",
        "force finishing activity",
        "has died",
        "sigsegv",
        "sigabrt",
        "abort message",
        "lowmemorykiller",
    ]
    keep = [line for line in raw.splitlines() if any(m in line.lower() for m in markers)]

    # Also put the exit reasons and crash lines in the job log itself (the
    # artifact is not always reachable). Job logs of a public repo are public,
    # so emails are redacted.
    for line in exit_info.splitlines():
        line = line.strip()
        if line.startswith("timestamp=") or "reason=" in line:
            log("AOV exit-info: " + line[:200])
    crash_lines = [
        line for line in crash_buf.splitlines()
        if any(m in line.lower() for m in [
            "fatal signal", "abort message", "cause:", ">>> ", "signal ",
        ]) or re.search(r"#\d\d pc ", line)
    ]
    for line in crash_lines[:40]:
        log("AOV crash: " + EMAIL_RE.sub("<email>", line)[:220])
    if not crash_lines:
        log("AOV crash: <no native crash in logcat crash buffer>")

    (OUT / f"{name}.txt").write_text(
        f"pid={pid or 'none'}\n"
        f"foreground={current_focus_component()}\n\n"
        "=== exit-info (latest first) ===\n"
        + "\n".join(exit_info.splitlines()[:80])
        + "\n\n=== logcat crash buffer ===\n"
        + "\n".join(crash_buf.splitlines()[-400:])
        + "\n\n=== dropbox data_app_native_crash ===\n"
        + "\n".join(tombstones.splitlines()[-400:])
        + "\n\n=== logcat main (filtered) ===\n"
        + "\n".join(keep[-250:])
        + "\n",
        encoding="utf-8",
    )
    return pid

def wait_for_package(pkg, timeout):
    end = time.time() + timeout
    last_shot = 0
    while time.time() < end:
        if package_installed(pkg):
            return True
        # Use exact labels here. Substring matching "ok" previously matched
        # FaceboOK and navigated away from the AOV listing.
        tap_exact_text(["Continue", "Tiếp tục", "OK", "Accept", "Chấp nhận"], timeout=2)
        if time.time() - last_shot > 90:
            screenshot("install-progress")
            last_shot = time.time()
        time.sleep(5)
    return False

def finish_google_post_login_setup(timeout=180):
    log("Handling Google post-sign-in setup screens.")
    end = time.time() + timeout

    while time.time() < end:
        blob = ui_text().lower()

        # Optional setup screens: prefer the privacy-minimizing choice.
        if any(x in blob for x in [
            "back up",
            "backup",
            "google one",
            "add a phone number",
            "phone number",
            "set up payment",
            "payment method",
            "use your number",
        ]):
            if tap_exact_text([
                "Not now", "No thanks", "Skip", "Don't turn on",
                "Bỏ qua", "Không phải bây giờ", "Không, cảm ơn",
            ], timeout=3):
                time.sleep(2)
                continue

        # Mandatory account/terms/service confirmations.
        if tap_exact_text(["I agree", "Tôi đồng ý"], timeout=2):
            time.sleep(2)
            continue

        if tap_exact_text(["More", "Thêm"], timeout=2):
            time.sleep(1)
            continue

        if any(x in blob for x in [
            "google services",
            "terms of service",
            "privacy policy",
        ]):
            if tap_exact_text(["Accept", "Chấp nhận", "Continue", "Tiếp tục"], timeout=3):
                time.sleep(2)
                continue

        # If Android already has the Google account, try to leave setup and
        # reopen Play Store. This is our strongest completion signal.
        if has_google_account():
            log("Google account is present in Android account manager.")
            adb("shell", "am", "force-stop", PKG_PLAY, timeout=30)
            adb("shell", "monkey", "-p", PKG_PLAY, "-c", "android.intent.category.LAUNCHER", "1", timeout=30)
            time.sleep(6)
            return True

        time.sleep(3)

    return has_google_account()

def has_google_account():
    # Do not log dumpsys output because it can contain the account email.
    # Only count a real Account record; generic references to com.google in
    # AccountManager internals are not proof that a user Google account exists.
    out = adb("shell", "dumpsys", "account", timeout=60)
    return bool(re.search(r"Account \{name=.*?, type=com\.google\}", out))

def play_store_signed_in():
    if has_google_account():
        return True

    root = dump_ui("playstore-state")
    if root is None:
        return False
    blobs = [node_blob(n) for n in root.iter("node")]
    joined = "\n".join(blobs)
    signed_in_markers = [
        "search apps & games",
        "search apps",
        "tìm kiếm ứng dụng",
        "for you",
        "dành cho bạn",
        "manage apps",
        "quản lý ứng dụng",
    ]
    sign_in_markers = ["sign in", "đăng nhập"]
    if any(m in joined for m in signed_in_markers) and not any(m == b.strip() for b in blobs for m in sign_in_markers):
        return True

    # Being inside the Play Store activity is not enough: the unauthenticated
    # splash/login screen is also com.android.vending.
    return False

def dismiss_system_anr_dialog():
    blob = ui_text()
    lower = blob.lower()
    if not any(x in lower for x in [
        "isn't responding",
        "is not responding",
        "không phản hồi",
    ]):
        return False

    log("Android app-not-responding dialog detected.")

    # Pixel Launcher can get stuck in a repeated ANR loop on the hosted
    # emulator. Waiting does not recover it; close the launcher and keep the
    # foreground Play Store flow alive.
    if "pixel launcher" in lower:
        if tap_exact_text(["Close app", "Đóng ứng dụng"], timeout=3):
            log("Closed unresponsive Pixel Launcher.")
            time.sleep(4)
            return True

    # For other apps, try Wait once before falling back to Close app.
    if tap_exact_text(["Wait", "Chờ"], timeout=2):
        log("Tapped Wait on Android ANR dialog.")
        time.sleep(3)
        return True

    if tap_exact_text(["Close app", "Đóng ứng dụng"], timeout=2):
        log("Closed the unresponsive app from Android ANR dialog.")
        time.sleep(3)
        return True

    return False


def wait_for_google_identifier_screen(timeout=90):
    end = time.time() + timeout
    sign_in_attempts = 0

    while time.time() < end:
        if dismiss_system_anr_dialog():
            # Give Android a moment to restart the launcher process in the
            # background, then explicitly bring Play Store back to foreground.
            time.sleep(2)
            adb("shell", "am", "force-stop", PKG_PLAY, timeout=30)
            time.sleep(1)
            adb("shell", "monkey", "-p", PKG_PLAY, "-c", "android.intent.category.LAUNCHER", "1")
            time.sleep(6)
            continue

        blob = ui_text()
        lower = blob.lower()

        if play_store_signed_in():
            return "SIGNED_IN"

        if any(x in lower for x in [
            "email or phone",
            "forgot email",
            "create account",
            "email hoặc số điện thoại",
        ]):
            return "IDENTIFIER"

        if any(x in lower for x in [
            "sign in with ease",
            "search for accounts connected to this phone number",
        ]):
            handle_google_signin_intro()
            time.sleep(3)
            continue

        if "com.google.android.gms" in resumed_activity().lower():
            # We are inside Google's account-add UI, so it is safe to handle
            # the informational account dialog here.
            dismiss_google_account_info_dialog()
            time.sleep(3)
            continue

        if any(x in lower for x in [
            "sign in to find the latest android apps",
            "sign in",
            "đăng nhập",
        ]):
            if tap_exact_text(["Sign in", "Đăng nhập"], timeout=4):
                sign_in_attempts += 1
                log(f"Play Store sign-in attempt #{sign_in_attempts}.")
                time.sleep(6)
                continue

        # The Play Store may have restarted after a launcher/system ANR.
        # Re-open it periodically and retry instead of assuming Google login is open.
        if sign_in_attempts == 0 or sign_in_attempts % 2 == 0:
            adb("shell", "monkey", "-p", PKG_PLAY, "-c", "android.intent.category.LAUNCHER", "1")
            time.sleep(4)

        time.sleep(2)

    return "TIMEOUT"


def current_focus_component():
    # Return only package/activity metadata; never log account text or credentials.
    activity = resumed_activity()
    m = re.search(r"([A-Za-z0-9._]+/[A-Za-z0-9._$]+)", activity)
    if m:
        return m.group(1)

    windows = adb("shell", "dumpsys", "window", "windows", timeout=60)
    for line in windows.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            m = re.search(r"([A-Za-z0-9._]+/[A-Za-z0-9._$]+)", line)
            if m:
                return m.group(1)

    return "UNKNOWN"


def classify_google_auth_state(blob):
    lower = (blob or "").lower()
    states = [
        ("NUMBER_MATCH", ["choose the number", "select the number", "number match", "chọn số"]),
        ("CHECK_PHONE", ["check your phone", "tap yes on your phone", "kiểm tra điện thoại"]),
        ("GOOGLE_SERVICES", ["google services"]),
        ("TERMS", ["terms of service", "privacy policy", "điều khoản"]),
        ("BACKUP", ["back up", "backup", "google one"]),
        ("PHONE_SETUP", ["add a phone number", "use your number"]),
        ("PAYMENT_SETUP", ["set up payment", "payment method"]),
        ("PLAY_GAMES_PROFILE", ["create a play games profile", "sync progress and achievements"]),
        ("PLAY_STORE_HOME", ["search apps & games", "search apps", "manage apps"]),
    ]
    for name, markers in states:
        if any(marker in lower for marker in markers):
            return name
    if "com.google.android.gms" in resumed_activity().lower():
        return "GOOGLE_ACCOUNT_UI"
    return "UNKNOWN"


def google_account_present_diagnostic():
    # Keep account names private; only return a boolean/count-like diagnostic.
    out = adb("shell", "dumpsys", "account", timeout=60)
    matches = re.findall(r"Account \{name=[^,}]+,\s*type=com\.google\}", out)
    return len(matches)

def handle_google_login():
    log("Opening Play Store...")
    adb("shell", "monkey", "-p", PKG_PLAY, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(8)
    screenshot("01-playstore-start")

    if play_store_signed_in():
        log("Play Store already appears signed in.")
        return True

    state = wait_for_google_identifier_screen(timeout=90)
    if state == "SIGNED_IN":
        log("Play Store became signed in while recovering the login flow.")
        return True
    if state != "IDENTIFIER":
        log("Could not reach the Google email/phone screen after Play Store recovery.")
        (OUT / "google-login-state.txt").write_text("IDENTIFIER_SCREEN_NOT_REACHED\n", encoding="utf-8")
        screenshot("02-google-login-not-reached")
        return False

    screenshot("02-google-login")

    # Email / identifier.
    edits = edit_nodes()
    if not edits:
        log("Google identifier input is rendered but not exposed as EditText. Using the fixed Pixel 7 screen location as a fallback.")
        screenshot("03-google-email-field-visual-fallback")
        tap_fraction(0.50, 0.29)
        input_text(GOOGLE_EMAIL)
        time.sleep(1)
    else:
        _, (x, y), _ = edits[0]
        tap_xy(x, y)
        focused_type(GOOGLE_EMAIL)
    if not tap_exact_text(["Next", "Tiếp theo"], timeout=10):
        log("Google Next button is not exposed in UIAutomator; using fixed Pixel 7 Next-button coordinates.")
        tap_fraction(0.87, 0.93)
        time.sleep(2)

    time.sleep(5)

    blob = wait_ui_contains([
        "enter your password",
        "password",
        "show password",
        "welcome",
        "nhập mật khẩu",
        "mật khẩu",
        "hiện mật khẩu",
    ], timeout=30)
    if not blob:
        log("Could not confirm that Google advanced to the password screen.")
        (OUT / "google-password-screen-not-confirmed.txt").write_text("Password screen was not confirmed.\n", encoding="utf-8")
        (OUT / "google-login-state.txt").write_text("PASSWORD_SCREEN_NOT_CONFIRMED\n", encoding="utf-8")
        return False

    # Password.
    edits = edit_nodes()
    if not edits:
        log("Google password input is rendered but not exposed as EditText. Using the fixed Pixel 7 screen location as a fallback.")
        tap_fraction(0.50, 0.30)
        input_text(GOOGLE_PASSWORD)
        time.sleep(1)
    else:
        _, (x, y), _ = edits[-1]
        tap_xy(x, y)
        focused_type(GOOGLE_PASSWORD)
    if tap_exact_text(["Close", "Đóng"], timeout=3):
        log("Dismissed informational dialog before password submit.")

    if not tap_exact_text(["Next", "Tiếp theo"], timeout=10):
        log("Google Next button after password is not exposed; using fixed Pixel 7 Next-button coordinates.")
        tap_fraction(0.87, 0.93)
        time.sleep(2)

    time.sleep(5)
    restore_system_ime()
    (OUT / "google-login-state.txt").write_text("CREDENTIALS_SUBMITTED\n", encoding="utf-8")

    log(f"Waiting up to {VERIFY_TIMEOUT}s for Google verification / sign-in completion.")
    end = time.time() + VERIFY_TIMEOUT
    verification_saved = False
    last_number_match = None
    last_heartbeat = 0
    last_state = None
    account_seen = False
    challenge_seen = False
    unknown_since = None
    unknown_evidence_saved = False
    unknown_recovery_attempted = False
    while time.time() < end:
        # Strongest success signal: once Android AccountManager contains a real
        # Google account, phone verification has completed even if the old
        # verification WebView has not visually refreshed yet.
        if has_google_account():
            if not account_seen:
                account_seen = True
                log("Google account appeared in Android AccountManager; phone verification is complete.")
            finish_google_post_login_setup(timeout=20)
            screenshot("05-playstore-signed-in")
            return True

        verification_blob = ui_text()
        verification_lower = verification_blob.lower() if verification_blob else ""

        current_state = classify_google_auth_state(verification_blob)
        if current_state != last_state:
            account_count = google_account_present_diagnostic()
            log(f"GOOGLE_AUTH_STATE={current_state}; google_accounts={account_count}")
            last_state = current_state

        if verification_blob:
            last_number_match = report_google_verification(
                verification_blob,
                previous_number=last_number_match,
            )
            if last_number_match is not None:
                challenge_seen = True

        # Keep this list strict. Generic words such as "security", "confirm" or
        # "verify" also occur on normal post-login/setup pages and previously
        # caused the workflow to wait forever after successful phone approval.
        verification_markers = [
            "2-step verification",
            "check your phone",
            "tap yes on your phone",
            "choose the number",
            "select the number",
            "number match",
            "kiểm tra điện thoại",
            "chọn số",
            "enter the number shown on your phone",
            "enter the number shown on your device",
        ]
        current_number_match = extract_google_number_match(verification_blob) if verification_blob else None
        verification_visible = (
            current_number_match is not None
            or any(x in verification_lower for x in verification_markers)
        )

        if verification_visible:
            challenge_seen = True
            unknown_since = None
            if not verification_saved:
                verification_saved = True
                log("Google verification appears to be required. Keep this job open while approving it on your trusted device.")
        else:
            # After a real number-match/check-phone challenge has been seen,
            # returning to Play Store is a strong completion signal even if the
            # transient Google WebView becomes unreadable to UIAutomator.
            focus = current_focus_component()
            focus_lower = focus.lower()
            if (
                challenge_seen
                and PKG_PLAY in focus_lower
                and "sign in" not in verification_lower
                and "đăng nhập" not in verification_lower
            ):
                log(f"Google verification completed; foreground returned to Play Store ({focus}).")
                screenshot("05-playstore-signed-in")
                return True

            if challenge_seen and current_state == "UNKNOWN":
                if unknown_since is None:
                    unknown_since = time.time()
                    log(f"Post-verification UI became UNKNOWN; foreground={focus}.")
                if not unknown_evidence_saved:
                    screenshot("google-post-verify-unknown")
                    dump_ui("google-post-verify-unknown")
                    unknown_evidence_saved = True

                # If Google verification closes back to Pixel Launcher and no
                # Google account appears, do not wait for the full 15-minute
                # timeout. Give the account service a short grace period, then
                # reopen Play Store once to determine whether sign-in actually
                # completed or the account-add flow was abandoned.
                if (
                    not unknown_recovery_attempted
                    and unknown_since is not None
                    and time.time() - unknown_since >= 20
                    and "nexuslauncher" in focus_lower
                    and google_account_present_diagnostic() == 0
                ):
                    unknown_recovery_attempted = True
                    log("Post-verification returned to Pixel Launcher without a Google account; reopening Play Store to verify completion.")
                    adb("shell", "am", "force-stop", PKG_PLAY, timeout=30)
                    time.sleep(1)
                    adb("shell", "monkey", "-p", PKG_PLAY, "-c", "android.intent.category.LAUNCHER", "1", timeout=30)
                    time.sleep(8)

                    if has_google_account() or play_store_signed_in():
                        log("Google sign-in completed after Play Store recovery.")
                        screenshot("05-playstore-signed-in")
                        return True

                    recovered_blob = ui_text().lower()
                    if any(x in recovered_blob for x in [
                        "sign in to find the latest android apps",
                        "sign in",
                        "đăng nhập",
                    ]):
                        screenshot("google-approved-but-account-not-added")
                        (OUT / "google-login-state.txt").write_text(
                            "GOOGLE_APPROVED_BUT_ACCOUNT_NOT_ADDED\n",
                            encoding="utf-8",
                        )
                        log("Phone approval completed, but Android did not add the Google account; Play Store returned to Sign in.")
                        return False
            else:
                unknown_since = None

            # Only run setup-page handling when the foreground is still part of
            # Google/Play Store. Running it on Pixel Launcher just wastes time.
            if (
                "com.google.android.gms" in focus_lower
                or PKG_PLAY in focus_lower
                or current_state != "UNKNOWN"
            ):
                finish_google_post_login_setup(timeout=5)

            if play_store_signed_in():
                log("Google sign-in/setup completed.")
                screenshot("05-playstore-signed-in")
                return True

        now = time.time()
        if now - last_heartbeat >= 30:
            remaining = max(0, int(end - now))
            account_count = google_account_present_diagnostic()
            log(
                f"Google verification wait still active; {remaining}s remaining; "
                f"state={current_state}; google_accounts={account_count}."
            )
            last_heartbeat = now

        time.sleep(5)

    screenshot("google-login-timeout")
    return False

def open_aov_listing():
    log("Opening Garena Liên Quân Mobile Play Store listing...")
    adb(
        "shell", "am", "start", "-W",
        "-a", "android.intent.action.VIEW",
        "-d", f"market://details?id={PKG_AOV}",
        "-p", PKG_PLAY,
        timeout=60,
    )
    time.sleep(12)
    screenshot("06-aov-listing")
    dump_ui("aov-listing")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

def log_visible_labels(tag, limit=40):
    # Put what is on screen into the job log itself, so a failure can be
    # diagnosed without downloading the artifact. Job logs of a public repo
    # are public, so email addresses are redacted.
    root = dump_ui(tag)
    focus = current_focus_component()
    if root is None:
        log(f"{tag}: foreground={focus}; UI dump failed: {LAST_DUMP_OUTPUT[:160] or '<no output>'}")
        return
    labels = []
    for n in root.iter("node"):
        label = EMAIL_RE.sub("<email>", visible_label_blob(n))[:80]
        if label and label not in labels:
            labels.append(label)
    log(f"{tag}: foreground={focus}; visible labels: " + (" | ".join(labels[:limit]) or "<none>"))

def install_aov():
    if package_installed(PKG_AOV):
        log("AOV package is already installed.")
        return True

    attempts = 3
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            if attempt == attempts:
                adb("shell", "am", "force-stop", PKG_PLAY, timeout=30)
                time.sleep(2)
            log(f"Reopening AOV listing (attempt {attempt}/{attempts}).")
            open_aov_listing()

        if tap_needles(["install", "cài đặt"], timeout=25):
            break

        blob = ui_text().lower()
        screenshot(f"aov-install-button-not-found-{attempt}")
        log_visible_labels(f"aov-listing-attempt-{attempt}")

        if "sign in" in blob or "đăng nhập" in blob:
            (OUT / "aov-install-state.txt").write_text("PLAY_STORE_SIGN_IN_REQUIRED\n", encoding="utf-8")
            log("Play Store is still unauthenticated; AOV install cannot start.")
            return False
        if any(x in blob for x in [
            "isn't available for your device",
            "not available for your device",
            "not compatible with your device",
            "this app won't work for your device",
            "không tương thích với thiết bị",
            "không có sẵn cho thiết bị",
        ]):
            (OUT / "aov-install-state.txt").write_text("AOV_DEVICE_INCOMPATIBLE\n", encoding="utf-8")
            log("AOV appears unavailable/incompatible for this emulator device.")
            return False
        if any(x in blob for x in [
            "not available in your country",
            "not available in your region",
            "không có sẵn ở quốc gia",
            "không có sẵn tại khu vực",
        ]):
            (OUT / "aov-install-state.txt").write_text("AOV_REGION_UNAVAILABLE\n", encoding="utf-8")
            log("AOV appears unavailable for the Play Store region.")
            return False

        # A freshly added account can get optional Play Store sheets (Play
        # Protect, Play Points, payment setup) over the listing, or the listing
        # may still be loading. Dismiss optional sheets and try again.
        if tap_exact_text([
            "Not now", "No thanks", "Skip", "Got it",
            "Bỏ qua", "Không phải bây giờ", "Không, cảm ơn", "Đã hiểu",
        ], timeout=3):
            log("Dismissed an optional Play Store sheet over the AOV listing.")
        time.sleep(15)
    else:
        (OUT / "aov-install-state.txt").write_text("AOV_INSTALL_BUTTON_NOT_FOUND\n", encoding="utf-8")
        log(f"AOV listing opened {attempts} times, but no recognized Install button/state was found.")
        return False

    log(f"Install requested. Waiting up to {INSTALL_TIMEOUT}s for package {PKG_AOV}.")
    ok = wait_for_package(PKG_AOV, INSTALL_TIMEOUT)

    if ok:
        # Play Store can show an optional Play Pass promo after Install is tapped.
        # It does not mean installation failed; dismiss it so later screenshots are clear.
        if tap_exact_text(["Not now", "No thanks", "Bỏ qua", "Không phải bây giờ"], timeout=5):
            log("Dismissed optional Google Play promo after install.")

    screenshot("07-aov-after-install-wait")
    return ok

def launch_aov():
    log("Launching AOV...")
    adb("shell", "monkey", "-p", PKG_AOV, "-c", "android.intent.category.LAUNCHER", "1", timeout=60)
    log("Launch command sent.")

    time.sleep(8)
    if tap_exact_text(["Got it", "Đã hiểu", "OK"], timeout=12):
        log("Dismissed Android 'Viewing full screen' hint.")
        time.sleep(3)

    # Handle Android permission/system prompts and optional Google Play Games
    # onboarding while also checking whether AOV really stays in foreground.
    end = time.time() + 45
    while time.time() < end:
        hit = False

        if tap_exact_text(["Cancel", "Hủy"], timeout=1):
            log("Dismissed optional onboarding prompt.")
            hit = True

        if tap_needles([
            "while using the app", "only this time", "allow", "cho phép",
            "while using", "khi dùng ứng dụng"
        ], timeout=2):
            hit = True

        if tap_exact_text(["Got it", "Đã hiểu", "OK"], timeout=1):
            log("Dismissed remaining Android full-screen/system hint.")
            hit = True

        if package_is_foreground(PKG_AOV):
            # Give the game a little time to settle after it first becomes foreground.
            time.sleep(8)
            break

        if not hit:
            time.sleep(2)

    # If monkey returned to the launcher, retry using the app's resolved launcher
    # activity. This is a normal launch retry, not an emulator-detection bypass.
    if not package_is_foreground(PKG_AOV):
        log("AOV is not in foreground after the first launch attempt; retrying the resolved launcher activity.")
        start_out = start_aov_like_launcher()
        for line in start_out.splitlines():
            if line.startswith(("Status:", "LaunchState:", "Activity:", "TotalTime:")):
                log("AOV launch: " + line)
        time.sleep(12)

    screenshot("08-aov-launched")
    dump_ui("aov-launched")

    if package_is_foreground(PKG_AOV):
        log("AOV is confirmed in foreground.")
        return True

    # Save focused crash/activity diagnostics without dumping account data.
    pid = save_aov_exit_diagnostics("aov-launch-diagnostics")
    state = "AOV_EXITED_AFTER_LAUNCH" if not pid else "AOV_NOT_FOREGROUND"
    (OUT / "aov-launch-state.txt").write_text(state + "\n", encoding="utf-8")
    log(f"AOV did not remain in foreground after launch: {state}.")
    return False

def capture_screen_samples(step=48):
    raw = subprocess.run(
        ["adb", "exec-out", "screencap"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
    if len(raw) < 16:
        return None

    w = int.from_bytes(raw[0:4], "little")
    h = int.from_bytes(raw[4:8], "little")
    if w <= 0 or h <= 0 or w > 10000 or h > 10000:
        return None

    pixel_bytes = w * h * 4
    if len(raw) >= 16 + pixel_bytes:
        offset = 16
    elif len(raw) >= 12 + pixel_bytes:
        offset = 12
    else:
        return None

    full = []
    bottom = []
    bottom_start = int(h * 0.65)
    for y in range(0, h, step):
        row = offset + y * w * 4
        for x in range(0, w, step):
            i = row + x * 4
            if i + 2 >= len(raw):
                continue
            rgb = (raw[i], raw[i + 1], raw[i + 2])
            full.extend(rgb)
            if y >= bottom_start:
                bottom.extend(rgb)

    return full, bottom


def sample_diff(a, b):
    if not a or not b or len(a) != len(b):
        return 1.0
    total = sum(abs(x - y) for x, y in zip(a, b))
    return total / (len(a) * 255.0)


def reopen_aov_after_external_prompt(reason):
    # The Play Games sign-in activity sits on top of AOV's task. Once it is
    # cancelled, Android returns to AOV by itself, so wait for that before
    # sending any launch intent of our own.
    end = time.time() + 20
    while time.time() < end:
        if package_is_foreground(PKG_AOV):
            log(f"AOV returned to foreground by itself after external UI: {reason}.")
            return True
        time.sleep(3)

    pid = aov_pid()
    log(
        f"AOV did not return by itself after external UI: {reason}; "
        f"process={'alive' if pid else 'gone'}. Bringing its task to front like the launcher icon."
    )
    start_aov_like_launcher()
    time.sleep(10)
    return package_is_foreground(PKG_AOV)


def recover_optional_play_games_prompt():
    focus = current_focus_component()
    blob = ui_text()
    lower = blob.lower()

    markers = [
        "google play games",
        "create a play games profile",
        "sync progress and achievements",
        "play across devices",
        "no profile",
        "make it easier to pick up where you",
    ]
    looks_like_play_games = any(marker in lower for marker in markers)

    if not looks_like_play_games:
        return False

    log(f"Optional Google Play Games profile/sync prompt detected; foreground={focus}.")
    screenshot("09-google-play-games-prompt")

    dismissed = tap_exact_text(["Cancel", "Hủy"], timeout=4)
    if not dismissed:
        log("Play Games Cancel was not exposed; sending Android Back once.")
        adb("shell", "input", "keyevent", "KEYCODE_BACK", timeout=30)
        time.sleep(3)

    return reopen_aov_after_external_prompt("Google Play Games profile prompt")


def wait_for_aov_scene_ready():
    log(
        f"Waiting up to {AOV_RESOURCE_TIMEOUT}s for AOV resource loading/scene transition "
        f"before attempting login."
    )
    start = time.time()
    end = start + AOV_RESOURCE_TIMEOUT
    previous = None
    initial = None
    stable_count = 0
    next_shot = start + 30
    shot_index = 1
    external_recoveries = 0

    while time.time() < end:
        if not package_is_foreground(PKG_AOV):
            focus = current_focus_component()
            log(f"AOV temporarily left foreground during resource wait; foreground={focus}.")

            if recover_optional_play_games_prompt():
                external_recoveries += 1
                previous = None
                stable_count = 0
                log(f"Returned to AOV after optional Play Games prompt (recovery #{external_recoveries}).")
                continue

            # Some Google overlays take a moment to expose their accessibility
            # labels. Give them a short grace period before declaring a real exit.
            time.sleep(5)
            if package_is_foreground(PKG_AOV):
                log("AOV returned to foreground after a transient external UI.")
                previous = None
                stable_count = 0
                continue

            if recover_optional_play_games_prompt():
                external_recoveries += 1
                previous = None
                stable_count = 0
                log(f"Returned to AOV after delayed Play Games prompt (recovery #{external_recoveries}).")
                continue

            screenshot("09-aov-left-foreground")
            pid = save_aov_exit_diagnostics(f"aov-left-foreground-{external_recoveries}")

            # Still running but sent to background: bring it back like the
            # launcher icon would, a limited number of times.
            if pid and external_recoveries < 3:
                external_recoveries += 1
                log(f"AOV process is still alive in background; bringing it to front (recovery #{external_recoveries}).")
                start_aov_like_launcher()
                time.sleep(10)
                previous = None
                stable_count = 0
                continue

            (OUT / "aov-resource-foreground.txt").write_text(
                f"foreground={focus}\nprocess={'alive' if pid else 'gone'}\n",
                encoding="utf-8",
            )
            if not pid:
                log("AOV process is gone; see aov-left-foreground-*.txt for the exit reason.")
                return "AOV_EXITED_DURING_RESOURCE_WAIT"
            return "AOV_LEFT_FOREGROUND_DURING_RESOURCE_WAIT"

        # If a real visible login/provider label is exposed, the scene is ready.
        if find_label_nodes(["garena", "login", "đăng nhập"]):
            log("A visible login/provider label is available; AOV scene is ready.")
            screenshot("09-aov-scene-ready")
            return "READY_ACCESSIBLE"

        current = capture_screen_samples()
        elapsed = time.time() - start

        if current is not None and initial is None:
            initial = current

        if current is not None and previous is not None and elapsed >= AOV_RESOURCE_MIN_WAIT:
            full_diff = sample_diff(previous[0], current[0])
            bottom_diff = sample_diff(previous[1], current[1])
            scene_diff = sample_diff(initial[0], current[0]) if initial is not None else 0.0

            # A first-launch resource screen may appear visually stable while
            # waiting on the network. Do not call it "ready" unless the overall
            # scene has changed materially from the initial loading scene.
            scene_changed = scene_diff >= 0.08

            if scene_changed and full_diff < 0.018 and bottom_diff < 0.025:
                stable_count += 1
            else:
                stable_count = 0

            log(
                f"AOV scene stability: elapsed={int(elapsed)}s "
                f"scene_diff={scene_diff:.4f} full_diff={full_diff:.4f} "
                f"bottom_diff={bottom_diff:.4f} stable={stable_count}/3"
            )

            if stable_count >= 3:
                screenshot("09-aov-scene-stable")
                log("AOV transitioned away from the initial loading scene and is now stable.")
                return "READY_STABLE"

        if current is not None:
            previous = current

        if time.time() >= next_shot:
            screenshot(f"09-aov-resource-progress-{shot_index}")
            shot_index += 1
            next_shot = time.time() + 45

        time.sleep(15)

    screenshot("09-aov-resource-wait-timeout")
    return "AOV_RESOURCE_WAIT_TIMEOUT"


def attempt_garena_login():
    log("Attempting Garena login without emulator-detection bypasses.")

    # First wait for the first-launch resource/update phase to settle. Unity
    # exposes almost no accessibility text during this phase, so use screen
    # stability plus periodic screenshots instead of assuming a fixed delay.
    resource_state = wait_for_aov_scene_ready()
    log(f"AOV pre-login scene state: {resource_state}")

    if resource_state in [
        "AOV_LEFT_FOREGROUND_DURING_RESOURCE_WAIT",
        "AOV_EXITED_DURING_RESOURCE_WAIT",
        "AOV_RESOURCE_WAIT_TIMEOUT",
    ]:
        (OUT / "aov-login-state.txt").write_text(resource_state + "\n", encoding="utf-8")
        return resource_state

    # The loading phase may finish into another Unity-rendered scene whose
    # buttons are still not exposed to UIAutomator. Give that scene time to
    # transition, but only act on human-visible labels/text fields.
    end = time.time() + 180
    garena_clicked = False
    next_progress_shot = time.time() + 45
    progress_index = 1

    while time.time() < end:
        if not package_is_foreground(PKG_AOV):
            screenshot("09-aov-left-foreground-after-resource-wait")
            return "AOV_LEFT_FOREGROUND_BEFORE_LOGIN"

        tap_exact_text(["Cancel", "Hủy"], timeout=1)
        tap_exact_text(["Got it", "Đã hiểu", "OK"], timeout=1)
        tap_exact_text(
            ["Agree", "Đồng ý", "Accept", "Xác nhận", "Continue", "Tiếp tục"],
            timeout=1,
        )

        edits = edit_nodes()
        if edits:
            log(f"AOV login form is accessible with {len(edits)} text field(s).")
            break

        garena_nodes = find_label_nodes(["garena"])
        if garena_nodes:
            garena_nodes.sort(key=lambda item: item[0].attrib.get("clickable") != "true")
            _, (x, y), label = garena_nodes[0]
            log(f"Garena visible label detected: {label[:120]}")
            tap_xy(x, y)
            time.sleep(3)
            garena_clicked = True
            break

        if time.time() >= next_progress_shot:
            screenshot(f"09-aov-login-wait-{progress_index}")
            progress_index += 1
            next_progress_shot = time.time() + 45

        time.sleep(5)

    screenshot("09-aov-login-area")
    dump_ui("aov-login-area")

    # Some Garena login screens expose Android/WebView EditText fields.
    edits = edit_nodes()
    if len(edits) >= 2:
        log("Two login text fields are accessible via UI automation.")
        _, (x1, y1), _ = edits[0]
        _, (x2, y2), _ = edits[1]
        tap_xy(x1, y1)
        focused_type(AOV_USERNAME)
        tap_xy(x2, y2)
        focused_type(AOV_PASSWORD)
        screenshot("10-garena-filled")
        tap_label_needles(["login", "đăng nhập"], timeout=20)
        time.sleep(30)
        screenshot("11-aov-after-login-submit")
        dump_ui("aov-after-login-submit")
        return "AOV_LOGIN_ATTEMPTED"

    if len(edits) == 1:
        log("Only one login text field found; attempting sequential login flow.")
        _, (x, y), _ = edits[0]
        tap_xy(x, y)
        focused_type(AOV_USERNAME)
        if tap_label_needles(["next", "tiếp theo", "continue", "tiếp tục"], timeout=15):
            time.sleep(3)
            edits2 = edit_nodes()
            if edits2:
                _, (x2, y2), _ = edits2[-1]
                tap_xy(x2, y2)
                focused_type(AOV_PASSWORD)
                tap_label_needles(["login", "đăng nhập"], timeout=20)
                time.sleep(30)
                screenshot("11-aov-after-login-submit")
                return "AOV_LOGIN_ATTEMPTED"

    if garena_clicked:
        return "GARENA_LOGIN_UI_NOT_ACCESSIBLE"

    # Do not tap the Unity surface or arbitrary coordinates. Preserve the final
    # scene so the next iteration can decide whether a coordinate strategy is
    # appropriate from a real login screenshot.
    if resource_state == "READY_STABLE":
        state = "GARENA_BUTTON_NOT_ACCESSIBLE_AFTER_RESOURCE_WAIT"
    else:
        state = "GARENA_BUTTON_NOT_ACCESSIBLE"
    (OUT / "aov-login-state.txt").write_text(state + "\n", encoding="utf-8")
    return state


def main():
    missing = [name for name, value in {
        "GOOGLE_EMAIL": GOOGLE_EMAIL,
        "GOOGLE_PASSWORD": GOOGLE_PASSWORD,
        "AOV_USERNAME": AOV_USERNAME,
        "AOV_PASSWORD": AOV_PASSWORD,
    }.items() if not value]
    if missing:
        write_result("MISSING_SECRETS", ", ".join(missing))
        return 0

    log(adb("devices", "-l"))
    setup_adb_ime()

    if not handle_google_login():
        state_file = OUT / "google-login-state.txt"
        state = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else "GOOGLE_LOGIN_NOT_COMPLETED"

        if state == "GOOGLE_APPROVED_BUT_ACCOUNT_NOT_ADDED":
            log("Google phone approval succeeded but the account-add transaction was abandoned; retrying sign-in once on the same emulator.")
            time.sleep(8)
            if not handle_google_login():
                state = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else "GOOGLE_LOGIN_NOT_COMPLETED"
                write_result(state,
                             "Google sign-in still did not complete after one same-emulator retry. Evidence was saved.")
                return 0
        else:
            write_result(state,
                         "Google sign-in did not complete. Screenshots/UI dumps were saved.")
            return 0

    open_aov_listing()
    if not install_aov():
        state_file = OUT / "aov-install-state.txt"
        state = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else "AOV_INSTALL_NOT_STARTED"
        write_result(state,
                     "The Play Store listing did not reach an installable AOV state. Evidence was saved.")
        return 0

    if not package_installed(PKG_AOV):
        write_result("AOV_INSTALL_TIMEOUT", "AOV was not installed before the timeout.")
        return 0

    log("AOV installed successfully.")
    if not launch_aov():
        state_file = OUT / "aov-launch-state.txt"
        state = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else "AOV_LAUNCH_FAILED"
        write_result(state, "AOV was installed but did not remain active after launch. Diagnostics were saved.")
        return 0

    state = attempt_garena_login()
    write_result(state,
                 "No emulator-identification bypass, root hiding, Play Integrity bypass, or anti-cheat bypass was used.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
