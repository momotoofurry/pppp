// Cue screen of PROTOCOL.md sections 4.1, 5 and 6 for one condition (subject x day x condition), built like
// TrignoBridge.exe with the C# compiler that ships with Windows (.NET Framework 4, C# 5, WinForms):
//   csc /nologo /optimize+ /target:winexe /out:build\pc\TaskScreen.exe src\pc\TaskScreen.cs
//
//   TaskScreen --subject S01 --day 2 --cond A [--out .] [--segments labelled,practice,task,labelled,noncontrol]
//              [--commands grip,release,pose_A,pose_B] [--n 40] [--timeout 5] [--rest 2.5]
//              [--reps 5] [--cue 2] [--gap 3] [--practice 120] [--items 1,2,3,5] [--item 60]
//              [--udp 50555] [--fake] [--auto] [--windowed]
//
// The board's commands come from TrignoBridge.exe (run, same PC) as UDP datagrams "<unix_ms>,<mcu.csv line>" on
// 127.0.0.1:<udp>. Segments, in the order of --segments; the experimenter starts each one with the space bar:
//   labelled   <reps> x 6 gestures in a random order without repeats, each cued <cue> s after a <gap> s rest:
//              labels for offline accuracy (the windows of emg.csv / mcu.csv inside the cue times)
//   practice   <practice> s free practice, the last command shown
//   task       cued-command task (primary endpoint): <n> trials, the targets of --commands balanced and in a
//              random order without repeats (the board sends a held gesture once; a repeat needs Rest between).
//              Success = the first command within <timeout> s of the cue is the target; a wrong command or none
//              = failure. <rest> s rest between trials (feedback shown); commands there are 'rest' false commands.
//   noncontrol the items of section 6 (default day 1: 1,2,3,5; day 2: 1-8), <item> s each; every command counts
//   (safety endpoint). The experimenter starts each item with the space bar.
// Random orders come from a seed made from subject|day|cond|segment|index, so they are fixed in advance.
// The condition (A / F) is only in the file name, never on the screen (single blind).
// Keys: space = start the next segment / item; Esc = abort the running segment (logged; it can be run again);
// Q = quit while waiting. --fake: keys 1-5 act as the board's commands pose_A, grip, pose_B, release, home
// (dry run without the board). --auto: start segments and items by themselves (tests).
// Output <out>/<subject>_d<day>_<cond>_task.csv (never overwritten), one row per event, time = Unix ms, the same
// clock as TrignoBridge's emg.csv / mcu.csv / ops.csv. src/task_summary.py computes the endpoints from it.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows.Forms;

class Step
{
    public string Kind;              // rest, cue, trial, practice, wait, item
    public double Ms;                // duration; 0 = until the space bar (wait)
    public string Text, Target;      // Target: gesture (cue) or command (trial)
    public int Trial = -1;
}

class TaskForm : Form
{
    static readonly CultureInfo IC = CultureInfo.InvariantCulture;
    static readonly string[] GESTURES = { "Power", "Lateral", "Tripod", "Pointer", "Open", "Rest" };
    static readonly Dictionary<string, string> GESTURE_ZH = new Dictionary<string, string> {
        { "Power", "握拳" }, { "Lateral", "側捏" }, { "Tripod", "三指捏" }, { "Pointer", "食指指出" }, { "Open", "張開" }, { "Rest", "放鬆" } };
    // command -> (screen name, gesture) of decision.c; 'home' (Lateral) only exists if the firmware adds it (PROTOCOL.md 5)
    static readonly Dictionary<string, string[]> COMMAND = new Dictionary<string, string[]> {
        { "grip", new[] { "夾", "Tripod" } }, { "release", new[] { "放", "Open" } }, { "pose_A", new[] { "位置 A", "Power" } },
        { "pose_B", new[] { "位置 B", "Pointer" } }, { "home", new[] { "回原位", "Lateral" } } };
    static readonly string[] FAKE_KEYS = { "pose_A", "grip", "pose_B", "release", "home" };
    static readonly string[] ITEMS = { "", "放鬆，手自然放在桌上", "拿杯子喝水、放回", "打鍵盤", "摸臉、扶眼鏡", "前臂旋前、旋後",
                                       "轉頭、交談", "站起來走幾步再坐下", "在機器人旁邊，但不打算控制" };
    static readonly Dictionary<string, string> SEG_ZH = new Dictionary<string, string> {
        { "labelled", "有標籤段" }, { "practice", "練習" }, { "task", "提示指令任務" }, { "noncontrol", "非控制動作段" } };

    readonly Dictionary<string, string> a;
    readonly string subject, day, cond;
    readonly string[] segs, commands;
    readonly bool fake, auto;
    readonly double timeoutMs, restMs, cueMs, gapMs, practiceMs, itemMs;
    readonly int nTrials, reps;
    readonly int[] items;
    readonly StreamWriter log;
    readonly Label big = new Label(), small = new Label();
    readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
    readonly Stopwatch clock = Stopwatch.StartNew();
    readonly double epochMs;
    readonly Queue<string[]> inbox = new Queue<string[]>();      // [unix_ms, kind, window, t_us, gesture, command, ..., event, value]
    UdpClient udp;

    int segIdx = 0;                  // next / running segment
    string segName;                  // running segment ("" = waiting)
    List<Step> steps;
    int stepIdx;
    double stepStart;
    bool answered;                   // trial: first command seen
    int nSuccess, nTrialsDone, nRestCmds, nItemCmds;
    double itemMinutes;
    string lastCommand = "";

    public TaskForm(Dictionary<string, string> args)
    {
        a = args;
        int port = int.Parse(Get("udp", "50555"));                 // listen first: datagrams wait in the socket from now on
        if (port > 0) udp = new UdpClient(new IPEndPoint(IPAddress.Loopback, port));
        subject = Get("subject", null); day = Get("day", null); cond = Get("cond", null);
        if (subject == null || day == null || cond == null) throw new ArgumentException("--subject, --day and --cond are required");
        segs = Get("segments", "labelled,practice,task,labelled,noncontrol").Split(',');
        commands = Get("commands", "grip,release,pose_A,pose_B").Split(',');
        foreach (var c in commands) if (!COMMAND.ContainsKey(c)) throw new ArgumentException("unknown command " + c);
        nTrials = int.Parse(Get("n", "40")); reps = int.Parse(Get("reps", "5"));
        if (nTrials % commands.Length != 0) throw new ArgumentException("--n must be a multiple of the number of commands (balanced targets)");
        timeoutMs = 1000 * D("timeout", "5"); restMs = 1000 * D("rest", "2.5"); cueMs = 1000 * D("cue", "2"); gapMs = 1000 * D("gap", "3");
        practiceMs = 1000 * D("practice", "120"); itemMs = 1000 * D("item", "60");
        var it = Get("items", day == "1" ? "1,2,3,5" : "1,2,3,4,5,6,7,8").Split(',');
        items = new int[it.Length];
        for (int i = 0; i < it.Length; i++) items[i] = int.Parse(it[i]);
        fake = a.ContainsKey("fake"); auto = a.ContainsKey("auto");
        epochMs = (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalMilliseconds - clock.Elapsed.TotalMilliseconds;

        string dir = Get("out", ".");
        Directory.CreateDirectory(dir);
        string path = Path.Combine(dir, string.Format("{0}_d{1}_{2}_task.csv", subject, day, cond));
        for (int k = 2; File.Exists(path); k++) path = Path.Combine(dir, string.Format("{0}_d{1}_{2}_task_{3}.csv", subject, day, cond, k));
        log = new StreamWriter(path, false, new UTF8Encoding(false));
        log.WriteLine("unix_ms,segment,event,step,trial,target,command,command_gesture,window,phase,result,latency_ms,text");
        Log(Now(), "", "session", -1, -1, "", "", "", "", "", "", "",
            string.Format("subject {0} day {1} segments {2} commands {3} n {4} timeout_s {5} fake {6}",
                          subject, day, string.Join(" ", segs), string.Join(" ", commands), nTrials, timeoutMs / 1000, fake ? 1 : 0)
            + (udp != null ? " udp " + port : " udp off"));

        Text = "TaskScreen";
        BackColor = Color.Black;
        KeyPreview = true;
        if (!a.ContainsKey("windowed")) { FormBorderStyle = FormBorderStyle.None; WindowState = FormWindowState.Maximized; }
        else ClientSize = new Size(900, 600);
        big.Dock = DockStyle.Fill; big.TextAlign = ContentAlignment.MiddleCenter; big.ForeColor = Color.White;
        big.Font = new Font("Microsoft JhengHei UI", 56, FontStyle.Bold);
        small.Dock = DockStyle.Bottom; small.Height = 40; small.ForeColor = Color.Gray;
        small.Font = new Font("Microsoft JhengHei UI", 14);
        Controls.Add(big); Controls.Add(small);
        KeyDown += OnKey;
        FormClosed += delegate { Shutdown(); };

        if (udp != null) {
            var th = new Thread(Listen) { IsBackground = true };
            th.Start();
        }
        timer.Interval = 15;
        timer.Tick += delegate { Tick(); };
        timer.Start();
        segName = "";
        ShowWaiting();
    }

    string Get(string k, string def) { return a.ContainsKey(k) ? a[k] : def; }
    double D(string k, string def) { return double.Parse(Get(k, def), IC); }
    double Now() { return epochMs + clock.Elapsed.TotalMilliseconds; }

    void Log(double ms, string seg, string ev, int step, int trial, string target, string command, string cg, string window,
             string phase, string result, string latency, string text)
    {
        log.WriteLine(string.Join(",", new[] { ms.ToString("F1", IC), seg, ev, step < 0 ? "" : step.ToString(IC),
                                               trial < 0 ? "" : trial.ToString(IC), target, command, cg, window, phase, result,
                                               latency, text.Replace(',', ' ') }));
        log.Flush();
    }

    void Listen()
    {
        var ep = new IPEndPoint(IPAddress.Any, 0);
        while (true) {
            byte[] b;
            try { b = udp.Receive(ref ep); } catch (SocketException) { continue; } catch (ObjectDisposedException) { return; }
            var f = Encoding.ASCII.GetString(b).Split(',');
            if (f.Length < 3) continue;
            lock (inbox) inbox.Enqueue(f);
        }
    }

    // ------------------------------------------------------------------ segments
    static uint Fnv(string s)
    {
        uint h = 2166136261;
        foreach (char c in s) { h ^= c; h *= 16777619; }
        return h;
    }

    // each item count times, random order, no item twice in a row (weighted draw, restart on a dead end)
    static List<string> Order(string[] set, int count, Random r)
    {
        for (int attempt = 0; attempt < 10000; attempt++) {
            var left = new int[set.Length];
            for (int i = 0; i < set.Length; i++) left[i] = count;
            var o = new List<string>();
            int prev = -1;
            for (int n = 0; n < set.Length * count; n++) {
                int tot = 0;
                for (int i = 0; i < set.Length; i++) if (i != prev) tot += left[i];
                if (tot == 0) break;
                int x = r.Next(tot), pick = -1;
                for (int i = 0; i < set.Length && pick < 0; i++) if (i != prev) { if (x < left[i]) pick = i; else x -= left[i]; }
                left[pick]--; o.Add(set[pick]); prev = pick;
            }
            if (o.Count == set.Length * count) return o;
        }
        throw new InvalidOperationException("no order without repeats");
    }

    List<Step> Build(string seg)
    {
        var r = new Random((int)Fnv(string.Join("|", subject, day, cond, seg, segIdx.ToString(IC))));
        var s = new List<Step>();
        if (seg == "labelled") {
            foreach (var g in Order(GESTURES, reps, r)) {
                s.Add(new Step { Kind = "rest", Ms = gapMs, Text = "休息" });
                s.Add(new Step { Kind = "cue", Ms = cueMs, Target = g, Text = GESTURE_ZH[g] + "\n" + g });
            }
            s.Add(new Step { Kind = "rest", Ms = gapMs, Text = "休息" });
        } else if (seg == "practice") {
            s.Add(new Step { Kind = "practice", Ms = practiceMs, Text = "練習：自由做手勢" });
        } else if (seg == "task") {
            s.Add(new Step { Kind = "rest", Ms = restMs, Text = "休息" });
            int t = 0;
            foreach (var c in Order(commands, nTrials / commands.Length, r)) {
                var g = COMMAND[c][1];
                s.Add(new Step { Kind = "trial", Ms = timeoutMs, Target = c, Trial = t++,
                                 Text = COMMAND[c][0] + "\n" + GESTURE_ZH[g] + " " + g });
                s.Add(new Step { Kind = "rest", Ms = restMs, Text = "休息" });
            }
        } else if (seg == "noncontrol") {
            foreach (int i in items) {
                s.Add(new Step { Kind = "wait", Ms = 0, Target = i.ToString(IC), Text = "下一項：" + ITEMS[i] + "\n（實驗者按空白鍵開始）" });
                s.Add(new Step { Kind = "item", Ms = itemMs, Target = i.ToString(IC), Text = ITEMS[i] });
            }
        } else throw new ArgumentException("unknown segment " + seg);
        return s;
    }

    void ShowWaiting()
    {
        if (segIdx >= segs.Length) {
            big.ForeColor = Color.White;
            big.Text = "完成，謝謝";
            small.Text = Summary();
            if (auto) Close();
            return;
        }
        big.ForeColor = Color.Gray;
        big.Text = "下一段：" + SEG_ZH[segs[segIdx]] + "\n（實驗者按空白鍵開始）";
        small.Text = string.Format("{0} 第 {1} 天   段落 {2}/{3}   {4}", subject, day, segIdx + 1, segs.Length, Summary());
    }

    string Summary()
    {
        var p = new List<string>();
        if (nTrialsDone > 0) p.Add(string.Format(IC, "任務成功 {0}/{1}，休息中誤觸發 {2}", nSuccess, nTrialsDone, nRestCmds));
        if (itemMinutes > 0) p.Add(string.Format(IC, "非控制段指令 {0:F2}/分", nItemCmds / itemMinutes));
        return string.Join("   ", p);
    }

    void StartSegment()
    {
        segName = segs[segIdx];
        steps = Build(segName);
        Log(Now(), segName, "seg_start", -1, -1, "", "", "", "", "", "", "", segIdx.ToString(IC));
        stepIdx = -1;
        NextStep();
    }

    void EndSegment(bool aborted)
    {
        double now = Now();
        if (stepIdx >= 0 && stepIdx < steps.Count) StepOff(now, aborted ? "aborted" : "");
        Log(now, segName, aborted ? "seg_abort" : "seg_end", -1, -1, "", "", "", "", "", "", "", segIdx.ToString(IC));
        if (!aborted) segIdx++;
        segName = "";
        ShowWaiting();
    }

    void NextStep()
    {
        double now = Now();
        if (stepIdx >= 0) StepOff(now, "");
        stepIdx++;
        if (stepIdx >= steps.Count) { EndSegment(false); return; }
        var s = steps[stepIdx];
        stepStart = now;
        answered = false;
        if (s.Kind != "rest" || stepIdx == 0 || steps[stepIdx - 1].Kind != "trial") {   // keep the trial feedback during its rest
            big.ForeColor = s.Kind == "rest" || s.Kind == "wait" ? Color.Gray : Color.White;
            big.Text = s.Kind == "practice" ? s.Text + "\n" + lastCommand : s.Text;
        }
        small.Text = string.Format(IC, "{0}   {1} {2}/{3}", subject, SEG_ZH[segName], stepIdx + 1, steps.Count);
        Log(now, segName, s.Kind + "_on", stepIdx, s.Trial, s.Target ?? "", "", "", "", "", "", "", s.Kind == "item" ? s.Text : "");
        if (s.Kind == "wait" && auto) NextStep();
    }

    void StepOff(double now, string note)
    {
        var s = steps[stepIdx];
        if (s.Kind == "trial" && !answered) {                        // aborted mid-trial: not a trial result
            if (note == "") Result(now, s, "timeout", "", "", "", 0);
            else Log(now, segName, "trial_end", stepIdx, s.Trial, s.Target, "", "", "", "", "aborted", "", "");
        }
        if (s.Kind == "item") itemMinutes += (now - stepStart) / 60000.0;
        Log(now, segName, s.Kind + "_off", stepIdx, s.Trial, s.Target ?? "", "", "", "", "", "", "", note);
    }

    void Result(double now, Step s, string result, string cmd, string cg, string window, double latency)
    {
        answered = true;
        nTrialsDone++;
        if (result == "success") nSuccess++;
        Log(now, segName, "trial_end", stepIdx, s.Trial, s.Target, cmd, cg, window, "", result,
            result == "timeout" ? "" : latency.ToString("F1", IC), "");
        big.ForeColor = result == "success" ? Color.LimeGreen : Color.OrangeRed;
        big.Text = result == "success" ? "✓ 正確" : result == "timeout" ? "超時" : "✗ " + COMMAND_NAME(cmd);
    }

    static string COMMAND_NAME(string c) { return COMMAND.ContainsKey(c) ? COMMAND[c][0] : c; }

    // ------------------------------------------------------------------ events
    void OnCommand(double ms, string cmd, string cg, string window, string text)
    {
        lastCommand = COMMAND_NAME(cmd);
        bool running = segName != "";
        Step s = running && stepIdx >= 0 && stepIdx < steps.Count ? steps[stepIdx] : null;
        // a command time-stamped before this step started belongs to the step before (it was still in transit)
        string phase = s == null ? "waiting" : ms < stepStart && stepIdx > 0 ? steps[stepIdx - 1].Kind : s.Kind;
        Log(ms, segName, "command", running ? stepIdx : -1, s != null ? s.Trial : -1, s != null ? s.Target ?? "" : "", cmd, cg, window,
            phase, "", "", text);
        if (s == null) return;
        if (phase == "trial" && s.Kind == "trial" && !answered && ms <= stepStart + s.Ms) {
            Result(ms, s, cmd == s.Target ? "success" : "wrong", cmd, cg, window, ms - stepStart);
            NextStep();
        } else if (phase == "rest" && segName == "task") nRestCmds++;
        else if (phase == "item") nItemCmds++;
        if (s.Kind == "practice") big.Text = s.Text + "\n" + lastCommand;
    }

    void Tick()
    {
        while (true) {
            string[] f;
            lock (inbox) { if (inbox.Count == 0) break; f = inbox.Dequeue(); }
            double ms;
            if (!double.TryParse(f[0], NumberStyles.Float, IC, out ms)) continue;
            if (f[1] == "command" && f.Length >= 6) OnCommand(ms, f[5], f[4], f[2], "");
            else if (f[1] == "status" && f.Length >= 11)
                Log(ms, segName, "status", segName != "" ? stepIdx : -1, -1, "", "", "", "", "", "", "", f[9] + " " + f[10]);
        }
        if (segName == "" || stepIdx < 0 || stepIdx >= steps.Count) {
            if (segName == "" && auto && segIdx < segs.Length) StartSegment();
            return;
        }
        var s = steps[stepIdx];
        double now = Now();
        // a trial waits 150 ms past its time limit for a command sent in time but still in transit
        double end = stepStart + s.Ms + (s.Kind == "trial" ? 150 : 0);
        if (s.Ms > 0 && now >= end) {
            if (s.Kind == "trial" && !answered) Result(stepStart + s.Ms, s, "timeout", "", "", "", 0);
            NextStep();
        }
    }

    void OnKey(object sender, KeyEventArgs e)
    {
        double now = Now();
        if (fake && e.KeyCode >= Keys.D1 && e.KeyCode <= Keys.D5) {
            string c = FAKE_KEYS[e.KeyCode - Keys.D1];
            OnCommand(now, c, COMMAND[c][1], "", "fake");
            return;
        }
        if (e.KeyCode == Keys.Space) {
            if (segName == "") { if (segIdx < segs.Length) StartSegment(); }
            else if (steps[stepIdx].Kind == "wait") NextStep();
        } else if (e.KeyCode == Keys.Escape && segName != "") {
            Log(now, segName, "key", stepIdx, -1, "", "", "", "", "", "", "", "Esc");
            EndSegment(true);
        } else if (e.KeyCode == Keys.Q && segName == "") Close();
    }

    void Shutdown()
    {
        timer.Stop();
        if (udp != null) udp.Close();
        Log(Now(), "", "session_end", -1, -1, "", "", "", "", "", "", "", Summary());
        log.Close();
    }
}

static class TaskProgram
{
    [STAThread]
    static int Main(string[] argv)
    {
        var d = new Dictionary<string, string>();
        for (int i = 0; i < argv.Length; i++) {
            string k = argv[i].TrimStart('-');
            if (k == "fake" || k == "auto" || k == "windowed") d[k] = "1";
            else if (i + 1 < argv.Length) d[k] = argv[++i];
        }
        try {
            Application.EnableVisualStyles();
            Application.Run(new TaskForm(d));
        } catch (Exception e) {
            MessageBox.Show(e.Message + "\n\nTaskScreen --subject S01 --day 2 --cond A [options]; see the top of TaskScreen.cs", "TaskScreen");
            return 1;
        }
        return 0;
    }
}
