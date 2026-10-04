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

def dump_ui(name="window"):
    remote = "/sdcard/window.xml"
    adb("shell", "uiautomator", "dump", remote, timeout=60)
    raw = subprocess.run(["adb", "exec-out", "cat", remote], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
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
    remote = "/sdcard/window.xml"
    adb("shell", "uiautomator", "dump", remote, timeout=60)
    raw = subprocess.run(
        ["adb", "exec-out", "cat", remote],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout
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
        if "mResumedActivity" in line:
            return line.strip()
    return ""

def package_installed(pkg):
    return bool(adb("shell", "pm", "path", pkg).strip())

def wait_for_package(pkg, timeout):
    end = time.time() + timeout
    last_shot = 0
    while time.time() < end:
        if package_installed(pkg):
            return True
        # Handle occasional Play Store confirmation dialogs.
        tap_needles(["continue", "tiếp tục", "ok", "accept", "chấp nhận"], timeout=2)
        if time.time() - last_shot > 90:
            screenshot("install-progress")
            last_shot = time.time()
        time.sleep(5)
    return False

def has_google_account():
    # Do not log dumpsys output because it can contain the account email.
    out = adb("shell", "dumpsys", "account", timeout=60)
    return "type=com.google" in out or "com.google" in out and "Account {" in out

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
    return PKG_PLAY in resumed_activity() and not any("sign in" in b or "đăng nhập" in b for b in blobs)

def handle_google_login():
    log("Opening Play Store...")
    adb("shell", "monkey", "-p", PKG_PLAY, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(8)
    screenshot("01-playstore-start")

    if play_store_signed_in():
        log("Play Store already appears signed in.")
        return True

    tap_needles(["sign in", "đăng nhập"], timeout=20)
    time.sleep(5)

    # Important: Google can put a modal saying "Your device works better with
    # a Google Account" over the account-add page. Close it before touching
    # the email field.
    dismiss_google_account_info_dialog()
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
    (OUT / "google-login-state.txt").write_text("CREDENTIALS_SUBMITTED\n", encoding="utf-8")

    log(f"Waiting up to {VERIFY_TIMEOUT}s for Google verification / sign-in completion.")
    end = time.time() + VERIFY_TIMEOUT
    verification_saved = False
    last_number_match = None
    last_heartbeat = 0
    while time.time() < end:
        # Common consent screens after login.
        tap_needles(["i agree", "tôi đồng ý", "accept", "chấp nhận"], timeout=2)
        tap_needles(["more", "thêm"], timeout=1)

        if play_store_signed_in():
            log("Google account detected on Android; sign-in completed.")
            screenshot("05-playstore-signed-in")
            return True

        verification_blob = ui_text()
        if verification_blob:
            last_number_match = report_google_verification(
                verification_blob,
                previous_number=last_number_match,
            )

        if not verification_saved and any(x in verification_blob.lower() for x in [
            "2-step", "check your phone", "verify", "xác minh",
            "kiểm tra điện thoại", "confirm", "security", "number match",
        ]):
            verification_saved = True
            log("Google verification appears to be required. Keep this job open while approving it on your trusted device.")

        now = time.time()
        if now - last_heartbeat >= 30:
            remaining = max(0, int(end - now))
            log(f"Google verification wait still active; {remaining}s remaining.")
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

def install_aov():
    if package_installed(PKG_AOV):
        log("AOV package is already installed.")
        return True

    if not tap_needles(["install", "cài đặt"], timeout=25):
        screenshot("aov-install-button-not-found")
        return False

    log(f"Install requested. Waiting up to {INSTALL_TIMEOUT}s for package {PKG_AOV}.")
    ok = wait_for_package(PKG_AOV, INSTALL_TIMEOUT)
    screenshot("07-aov-after-install-wait")
    return ok

def launch_aov():
    log("Launching AOV...")
    out = adb("shell", "monkey", "-p", PKG_AOV, "-c", "android.intent.category.LAUNCHER", "1", timeout=60)
    log("Launch command sent.")
    time.sleep(30)
    # Handle Android permission prompts only.
    end = time.time() + 45
    while time.time() < end:
        hit = tap_needles([
            "while using the app", "only this time", "allow", "cho phép",
            "while using", "khi dùng ứng dụng"
        ], timeout=2)
        if not hit:
            time.sleep(2)
    screenshot("08-aov-launched")
    dump_ui("aov-launched")
    return package_installed(PKG_AOV)

def attempt_garena_login():
    log("Attempting Garena login without emulator-detection bypasses.")

    # Let splash/update screens settle and try obvious Continue/Agree buttons.
    end = time.time() + 240
    garena_clicked = False
    while time.time() < end:
        tap_needles(["agree", "đồng ý", "accept", "xác nhận", "continue", "tiếp tục"], timeout=2)
        if tap_needles(["garena"], timeout=2):
            garena_clicked = True
            break
        time.sleep(4)

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
        tap_needles(["login", "đăng nhập"], timeout=20)
        time.sleep(30)
        screenshot("11-aov-after-login-submit")
        dump_ui("aov-after-login-submit")
        return "AOV_LOGIN_ATTEMPTED"

    if len(edits) == 1:
        log("Only one login text field found; attempting sequential login flow.")
        _, (x, y), _ = edits[0]
        tap_xy(x, y)
        focused_type(AOV_USERNAME)
        if tap_needles(["next", "tiếp theo", "continue", "tiếp tục"], timeout=15):
            time.sleep(3)
            edits2 = edit_nodes()
            if edits2:
                _, (x2, y2), _ = edits2[-1]
                tap_xy(x2, y2)
                focused_type(AOV_PASSWORD)
                tap_needles(["login", "đăng nhập"], timeout=20)
                time.sleep(30)
                screenshot("11-aov-after-login-submit")
                return "AOV_LOGIN_ATTEMPTED"

    # Game-rendered UI may not expose controls to uiautomator.
    if garena_clicked:
        return "GARENA_LOGIN_UI_NOT_ACCESSIBLE"
    return "GARENA_BUTTON_NOT_ACCESSIBLE"

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
        write_result(state,
                     "Google sign-in did not complete. Screenshots/UI dumps were saved.")
        return 0

    open_aov_listing()
    if not install_aov():
        write_result("AOV_INSTALL_NOT_STARTED",
                     "The Play Store listing opened, but the Install button could not be activated.")
        return 0

    if not package_installed(PKG_AOV):
        write_result("AOV_INSTALL_TIMEOUT", "AOV was not installed before the timeout.")
        return 0

    log("AOV installed successfully.")
    if not launch_aov():
        write_result("AOV_LAUNCH_FAILED")
        return 0

    state = attempt_garena_login()
    write_result(state,
                 "No emulator-identification bypass, root hiding, Play Integrity bypass, or anti-cheat bypass was used.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
