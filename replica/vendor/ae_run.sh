#!/bin/bash
# ae_run.sh — After Effects 统一脚本执行入口
#
# 规则：
#   1. 单实例：检测到 >1 个 AE 主进程直接拒绝；未运行才 open（永不用 -n）
#   2. 串行派发：共享外置目录锁及每个 AE 进程的 pending 记录，避免并发 DoScriptFile
#   3. 错误不弹窗：包装层 $.level=0 + beginSuppressDialogs + try/catch，
#      脚本错误（含语法错误）一律写 result JSON，返回结构化 PASS/FAIL
#
# 用法：
#   ae_run.sh check                  # 只报告实例状态，不派发
#   ae_run.sh <script.jsx>           # 派发执行，等待结果
#   AE_TIMEOUT=300 ae_run.sh x.jsx   # 覆盖默认 600s 等待超时
#   AE_APP=/path/to/App.app ae_run.sh x.jsx   # 覆盖目标版本
#
# 退出码：0=PASS  1=脚本FAIL  2=用法错误  3=多实例  4=锁冲突  5=超时  6=派发失败

set -u

AE_APP="${AE_APP:-/Applications/Adobe After Effects 2026/Adobe After Effects 2026.app}"
AE_BIN="$AE_APP/Contents/MacOS/After Effects"
TIMEOUT="${AE_TIMEOUT:-600}"
READY_TIMEOUT="${AE_READY_TIMEOUT:-180}"
STATE="/Volumes/data/Codex/agent-video-editing/tmp/ae-dispatch"

count_instances() { pgrep -f "^$AE_BIN" | wc -l | tr -d ' '; }

list_instances() { pgrep -fl "^$AE_BIN"; }

if [ "${1:-}" = "check" ]; then
    n=$(count_instances)
    echo "instances=$n"
    list_instances
    [ "$n" -le 1 ] && exit 0 || exit 3
fi

[ $# -ge 1 ] || { echo "usage: ae_run.sh check | <script.jsx>"; exit 2; }
[ -f "$1" ] || { echo "SCRIPT_NOT_FOUND: $1"; exit 2; }
SCRIPT="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
/sbin/mount | /usr/bin/grep -q ' on /Volumes/data ' || { echo 'EXTERNAL_STORAGE_UNAVAILABLE: /Volumes/data is not mounted'; exit 6; }
[ -w /Volumes/data ] || { echo 'EXTERNAL_STORAGE_UNAVAILABLE: /Volumes/data is not writable'; exit 6; }
mkdir -p "$STATE" || exit 6
export TMPDIR="$STATE" TMP="$STATE" TEMP="$STATE"
LOCK="$STATE/dispatch.lock"
RUN="$(mktemp -d "$STATE/run-XXXXXXXX")" || exit 6
RESULT="$RUN/result.json"
WRAP="$RUN/wrapper.jsx"
BODY="$RUN/body.jsx"

# --- 单实例守卫 ---
n=$(count_instances)
if [ "$n" -gt 1 ]; then
    echo "REFUSE_MULTI_INSTANCE: $n AE main processes running:"
    list_instances
    exit 3
fi

# --- 串行派发锁 ---
tries=0
while ! mkdir "$LOCK" 2>/dev/null; do
    tries=$((tries+1))
    if [ "$tries" -gt 150 ]; then
        echo "DISPATCH_LOCK_TIMEOUT: another ae_run is still holding $LOCK"
        exit 4
    fi
    sleep 2
done
printf '%s\n' "$$" > "$LOCK/owner.pid"
# Keep submitted files after a timeout: AE may still execute the queued event later.
cleanup() { rm -f "$LOCK/owner.pid"; rmdir "$LOCK" 2>/dev/null; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

send_script() {
    osascript -e 'ignoring application responses' \
        -e "tell application \"$AE_APP\" to DoScriptFile (POSIX file \"$1\")" \
        -e 'end ignoring' 2>"$RUN/dispatch-error.txt"
}

# --- 未运行则拉起（不用 -n），并等待可派发 ---
if [ "$n" -eq 0 ]; then
    open -a "$AE_APP" || { echo "LAUNCH_FAILED"; exit 6; }
    echo "launching AE, waiting for readiness..."
    waited=0
    while [ "$(count_instances)" -eq 0 ]; do
        waited=$((waited+2)); [ "$waited" -ge "$READY_TIMEOUT" ] && { echo "READY_TIMEOUT: AE process did not appear"; exit 5; }
        sleep 2
    done
fi

[ "$(count_instances)" -eq 1 ] || { echo 'REFUSE_MULTI_INSTANCE'; exit 3; }
AE_PID="$(pgrep -f "^$AE_BIN")"
AE_ID="$AE_PID-$(LC_ALL=C ps -p "$AE_PID" -o lstart= | tr -cd '[:alnum:]')"
PENDING="$STATE/pending-$AE_ID"
if [ -f "$PENDING" ]; then
    IFS= read -r previous_result < "$PENDING"
    if [ ! -f "$previous_result" ]; then
        echo "AE_SCRIPT_PENDING: previous event has no completion record; inspect AE before retrying: $PENDING"
        exit 5
    fi
    rm -f "$PENDING"
fi

# A running process (even isFinishedLaunching=true) can still be inside crash recovery.
# Inspect its main-thread modal state without sending another AppleEvent to AE.
if [ ! -f "$STATE/ready-$AE_ID" ]; then
    ready_end=$((SECONDS+READY_TIMEOUT))
    while :; do
        /usr/bin/sample "$AE_PID" 1 -file "$RUN/startup-sample.txt" >"$RUN/sample-log.txt" 2>&1 &
        sample_pid=$!
        while kill -0 "$sample_pid" 2>/dev/null; do
            if [ "$SECONDS" -ge "$ready_end" ]; then
                kill "$sample_pid" 2>/dev/null; wait "$sample_pid" 2>/dev/null
                echo "READY_TIMEOUT: could not establish AE readiness; no script sent; details: $RUN/sample-log.txt"
                exit 5
            fi
            sleep 1
        done
        wait "$sample_pid" || { echo "READY_TIMEOUT: readiness sample failed; no script sent"; exit 5; }
        if grep -Eq 'UI_MessageBox::RunModal|OS_Dialog::ModalLoop|Up_ReportErrorDialog' "$RUN/startup-sample.txt"; then
            echo "READY_TIMEOUT: AE has a startup or modal dialog; no script sent; details: $RUN/startup-sample.txt"
            exit 5
        fi
        grep -Fq -- '-[NSApplication run]' "$RUN/startup-sample.txt" && break
        [ "$SECONDS" -ge "$ready_end" ] && { echo 'READY_TIMEOUT: AE has not entered its main event loop; no script sent'; exit 5; }
        sleep 2
    done
    PROBE_OK="$RUN/probe.ok"
    PROBE="$RUN/probe.jsx"
    printf '#target aftereffects\nvar f=new File("%s");f.open("w");f.write("ok");f.close();\n' "$PROBE_OK" > "$PROBE"
    printf '%s\n' "$PROBE_OK" > "$PENDING"
    send_script "$PROBE" || { echo "DISPATCH_FAILED: $(cat "$RUN/dispatch-error.txt")"; exit 6; }
    waited=0
    while [ ! -f "$PROBE_OK" ]; do
        sleep 2; waited=$((waited+2))
        [ "$waited" -ge "$READY_TIMEOUT" ] && { echo "READY_TIMEOUT: AE did not acknowledge its single readiness probe; pending: $PENDING"; exit 5; }
    done
    rm -f "$PENDING"
    touch "$STATE/ready-$AE_ID"
fi

# --- 生成包装层：剥离 #指令行，evalFile 执行，错误落盘 ---
sed '/^#/d' "$SCRIPT" > "$BODY"
cat > "$WRAP" <<EOF
\$.level = 0;
(function () {
    var RESULT = new File("$RESULT");
    function jq(s){return '"'+String(s).replace(/\\\\/g,'\\\\\\\\').replace(/"/g,'\\\\"').replace(/\\r/g,'\\\\r').replace(/\\n/g,'\\\\n')+'"';}
    var r = {status:"FAIL", script:"$SCRIPT", error:null, line:null};
    try { app.beginSuppressDialogs(); } catch (e0) {}
    try {
        \$.evalFile("$BODY");
        r.status = "PASS";
    } catch (e) {
        try { r.error = String(e && e.message ? e.message : e); } catch (e2) { r.error = "unstringifiable"; }
        try { r.line = (e && e.line !== undefined) ? e.line : null; } catch (e3) {}
    }
    try { app.endSuppressDialogs(false); } catch (e4) {}
    try {
        RESULT.encoding = "UTF8";
        RESULT.open("w");
        RESULT.write("{\\"status\\":"+jq(r.status)+",\\"script\\":"+jq(r.script)+",\\"error\\":"+(r.error===null?"null":jq(r.error))+",\\"line\\":"+(r.line===null?"null":String(r.line))+"}");
        RESULT.close();
    } catch (e5) {}
})();
EOF

# --- 派发并等待结果 ---
printf '%s\n' "$RESULT" > "$PENDING"
if ! send_script "$WRAP"; then
    echo "DISPATCH_FAILED: $(cat "$RUN/dispatch-error.txt")"
    exit 6
fi

waited=0
while [ ! -f "$RESULT" ]; do
    sleep 2; waited=$((waited+2))
    if [ "$waited" -ge "$TIMEOUT" ]; then
        echo "RESULT_TIMEOUT after ${TIMEOUT}s — script may still be running inside AE or AE is stuck"
        exit 5
    fi
done
rm -f "$PENDING"

cat "$RESULT"
echo
grep -q '"status":"PASS"' "$RESULT" && exit 0 || exit 1
