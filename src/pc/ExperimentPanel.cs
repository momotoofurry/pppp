// ExperimentPanel: buttons for the self-test procedure (SOP_自我測試.md). It only starts the existing tools in the
// same folder (TrignoBridge.exe, TaskScreen.exe) with the same arguments as the .bat files and types the same
// commands into TrignoBridge run; recordings, file names and cue orders are unchanged. The .bat files still work.
//   csc /nologo /optimize+ /target:winexe /out:ExperimentPanel.exe ExperimentPanel.cs
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Ports;
using System.Text;
using System.Windows.Forms;

class ExperimentPanel : Form
{
    static readonly string DIR = AppDomain.CurrentDomain.BaseDirectory;
    static readonly string[] GESTURE6_ZH = { "握拳", "側捏", "三指捏", "食指指出", "張開", "放鬆" };
    // 9 directional gestures (2026-11-17; TrignoBridge --classes 9, firmware rtl_task_9c); files <subj>_d<day>_G_*
    static readonly string[] GESTURE9_ZH = { "手腕上翹（上）", "手腕下彎（下）", "往拇指側偏（左）", "往小指側偏（右）",
                                             "食指指出（前）", "比讚（後）", "五指張開（夾開）", "握拳（夾緊）", "放鬆（停）" };
    string[] GESTURE_ZH { get { return Nine ? GESTURE9_ZH : GESTURE6_ZH; } }
    readonly ComboBox gset = new ComboBox();
    bool Nine { get { return gset.SelectedIndex != 1; } }
    string Cond { get { return Nine ? "G" : "A"; } }
    static readonly Font UI = new Font("Microsoft JhengHei UI", 10.5f);
    static readonly Font UIB = new Font("Microsoft JhengHei UI", 11f, FontStyle.Bold);

    readonly TextBox subj = new TextBox(), rate = new TextBox(), slots = new TextBox(), tcu = new TextBox();
    readonly ComboBox day = new ComboBox(), com = new ComboBox();
    readonly Label nameLbl = new Label(), state = new Label();
    readonly RichTextBox log = new RichTextBox();
    readonly TextBox cmdBox = new TextBox();
    readonly List<Control> needBridge = new List<Control>(), needIdle = new List<Control>();
    readonly Button[] calBtn = new Button[9];
    readonly int[] calCount = new int[9];          // cued passes done per gesture since 開始錄製
    // cued passes per gesture before calibrate: 9 gestures 2 (2026-11-17, report 35.48: firmware rtl_task_9c2 keeps
    // RTL_LABEL_MAX = 810 = 3 passes, room to redo); 6 gestures 1
    int Passes { get { return Nine ? 2 : 1; } }
    Button calibrateBtn;
    Label calHint;
    TextBox room, skin, strap, photo, exercise, freeNote, dest;

    Process bridge, tool;
    StreamWriter bridgeIn;
    bool verifyAfterQuit;

    string Name0 { get { return subj.Text.Trim() + "_d" + day.Text + "_" + Cond; } }
    bool BridgeOn { get { return bridge != null && !bridge.HasExited; } }
    bool ToolOn { get { return tool != null && !tool.HasExited; } }

    ExperimentPanel()
    {
        Text = "實驗控制面板（自我測試）";
        Font = UI; Width = 1280; Height = 900; StartPosition = FormStartPosition.CenterScreen;

        var split = new SplitContainer { Dock = DockStyle.Fill, SplitterDistance = 560, FixedPanel = FixedPanel.Panel1 };
        Controls.Add(split);
        var left = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false,
                                         AutoScroll = true, Padding = new Padding(6) };
        split.Panel1.Controls.Add(left);

        // ---- settings
        var g = Group(left, "設定");
        subj.Text = "T00"; subj.Width = 70; subj.AccessibleName = "代號";
        day.DropDownStyle = ComboBoxStyle.DropDownList; day.Items.AddRange(new object[] { "1", "2", "3" }); day.SelectedIndex = 0; day.Width = 50;
        com.Width = 90; RefreshPorts();
        var refresh = Btn("重新找", delegate { RefreshPorts(); }); refresh.Width = 80;
        rate.Width = 70; slots.Width = 90; tcu.Width = 110;
        rate.AccessibleName = "採樣率"; slots.AccessibleName = "slots"; tcu.AccessibleName = "TCU 位址"; com.AccessibleName = "板子"; day.AccessibleName = "第幾天";
        Row(g, Lbl("代號"), subj, Lbl("第幾天"), day, Lbl("板子"), com, refresh);
        Row(g, Lbl("採樣率"), rate, Lbl("slots"), slots, Lbl("TCU 位址"), tcu);
        gset.DropDownStyle = ComboBoxStyle.DropDownList; gset.Width = 260; gset.AccessibleName = "手勢組";
        gset.Items.AddRange(new object[] { "9 方向手勢（檔名 _G，板子要 9 類韌體）", "6 抓握手勢（舊，檔名 _A）" });
        gset.SelectedIndex = 0;
        Row(g, Lbl("手勢組"), gset);
        g.Controls.Add(Hint("空白 = 預設（2000 Hz、slots 1-8、本機）。採樣率只在 check 量到不是 2000 時才填。"));
        nameLbl.AutoSize = true; nameLbl.Font = UIB; g.Controls.Add(nameLbl);
        subj.TextChanged += delegate { UpdateName(); }; day.SelectedIndexChanged += delegate { UpdateName(); };

        // ---- SOP 2: first time
        g = Group(left, "① 第一次（只做一次，SOP 第 2 節）");
        var b1 = Btn("探測 TCU", delegate { RunTool("probe" + TcuArg() + " --out tcu_probe.txt", "probe"); });
        var b2 = Btn("量採樣率（60 秒）", delegate { RunTool("check" + TcuArg() + " --seconds 60 --out emg_check.csv", "check"); });
        var b3 = Btn("把 emg_check 存成今天的檔名", delegate { SaveCheck(); });
        Row(g, b1, b2); Row(g, b3);
        needIdle.AddRange(new Control[] { b1, b2 });

        // ---- SOP 5.1: bridge
        g = Group(left, "② 開始錄製（5.1）");
        var start = Btn("開始錄製（開橋接程式）", delegate { StartBridge(); }); start.Width = 260; start.Font = UIB;
        state.AutoSize = true; state.Font = UIB;
        Row(g, start, state);
        needIdle.Add(start);

        // ---- SOP 5.2: environment notes
        g = Group(left, "③ 記環境（5.2）");
        room = Box(60, "", "室溫"); skin = Box(60, "", "皮膚溫度"); strap = Box(60, "0", "帶子偏移"); photo = Box(110, "IMG_", "照片"); exercise = Box(200, "none today", "上次前臂運動");
        Row(g, Lbl("室溫"), room, Lbl("皮膚溫度"), skin, Hint("（沒有就空白 = NA）"));
        Row(g, Lbl("帶子偏移 mm"), strap, Lbl("照片"), photo);
        Row(g, Lbl("上次前臂運動"), exercise);
        var envBtn = Btn("送出環境記錄", delegate { SendEnv(); });
        Row(g, envBtn); needBridge.Add(envBtn);

        // ---- SOP 5.3: cue pass
        g = Group(left, "④ 提示輪（中立姿勢，5.3；9 手勢做兩輪）");
        calHint = Hint(""); g.Controls.Add(calHint);
        for (int i = 0; i < 9; i++) {
            int k = i;
            calBtn[i] = Btn("cal " + i, delegate { Send("cal " + k); calCount[k]++; ShowCal(k); });
            calBtn[i].Width = 170; needBridge.Add(calBtn[i]);
        }
        Row(g, calBtn[0], calBtn[1], calBtn[2]); Row(g, calBtn[3], calBtn[4], calBtn[5]); Row(g, calBtn[6], calBtn[7], calBtn[8]);
        calibrateBtn = Btn("calibrate", delegate { Calibrate(); }); calibrateBtn.Width = 300;
        gset.SelectedIndexChanged += delegate { UpdateGestures(); UpdateName(); };
        UpdateGestures();
        Row(g, calibrateBtn); needBridge.Add(calibrateBtn);

        // ---- SOP 5.3b / 5.4: screens
        g = Group(left, "⑤ 提示畫面（5.3b 暖身 → 5.4 正式）");
        var warm = Btn("暖身（不算數）", delegate { StartScreen(true); });
        var task = Btn("正式提示畫面", delegate { StartScreen(false); }); task.Font = UIB;
        Row(g, warm, task); needBridge.Add(warm); needBridge.Add(task);
        g.Controls.Add(Hint("暖身結束後關掉暖身視窗再開正式的。每段開始按空白鍵，Esc 中止該段。\n要把畫面移到另一個螢幕：點一下畫面，按 Win + Shift + ← 或 →。"));

        // ---- notes during the recording
        g = Group(left, "⑥ 備註（隨時）");
        freeNote = Box(380, "", "備註");
        var noteBtn = Btn("送出", delegate { if (freeNote.Text.Trim() != "") { Send("note " + freeNote.Text.Trim()); freeNote.Clear(); } });
        Row(g, freeNote, noteBtn); needBridge.Add(noteBtn);
        var n1 = Btn("某段中止…", delegate { freeNote.Text = "segment T1 aborted: "; freeNote.Focus(); freeNote.SelectionStart = freeNote.Text.Length; });
        var n2 = Btn("感測器重貼…", delegate { freeNote.Text = "sensor 3 reattached"; freeNote.Focus(); });
        Row(g, n1, n2);

        // ---- SOP 5.5: end
        g = Group(left, "⑦ 結束（5.5）");
        var end = Btn("結束錄製並檢查檔案", delegate { EndSession(); }); end.Font = UIB; end.Width = 260;
        var ver = Btn("只檢查檔案（verify）", delegate { Verify(); });
        Row(g, end); Row(g, ver);
        needBridge.Add(end); needIdle.Add(ver);

        // ---- SOP 5.6: save
        g = Group(left, "⑧ 存資料（5.6，複製不是移動）");
        dest = Box(330, @"D:\selftest_data\T00", "存檔資料夾");
        var pick = Btn("選…", delegate {
            using (var d = new FolderBrowserDialog()) if (d.ShowDialog() == DialogResult.OK) dest.Text = d.SelectedPath; });
        var copy = Btn("複製今天的檔案", delegate { CopyFiles(); });
        Row(g, dest, pick); Row(g, copy); needIdle.Add(copy);
        g.Controls.Add(Hint("帶子位置照片請自己改名成 <代號>_d<天>_strap.jpg（例如 T00_d1_strap.jpg）一起放進去，再另外備份一份。"));

        // ---- right: log and raw command line
        log.Dock = DockStyle.Fill; log.ReadOnly = true; log.BackColor = Color.Black; log.ForeColor = Color.Gainsboro;
        log.Font = new Font("Consolas", 10f); log.HideSelection = false;
        var bottom = new Panel { Dock = DockStyle.Bottom, Height = 36 };
        cmdBox.Dock = DockStyle.Fill; cmdBox.AccessibleName = "指令"; cmdBox.Font = new Font("Consolas", 11f);
        var sendBtn = new Button { Text = "送出指令", Dock = DockStyle.Right, Width = 100 };
        sendBtn.Click += delegate { SendRaw(); };
        cmdBox.KeyDown += (s, e) => { if (e.KeyCode == Keys.Enter) { SendRaw(); e.SuppressKeyPress = true; } };
        bottom.Controls.Add(cmdBox); bottom.Controls.Add(sendBtn);
        var head = new Label { Dock = DockStyle.Top, Height = 26, Text = "橋接程式的輸出（下面可以直接輸入任何指令，例如 status）", ForeColor = Color.DimGray };
        split.Panel2.Controls.Add(log); split.Panel2.Controls.Add(bottom); split.Panel2.Controls.Add(head);
        needBridge.Add(sendBtn);

        UpdateName();
        var t = new Timer { Interval = 400 };
        t.Tick += delegate { UpdateState(); };
        t.Start();
        FormClosing += OnClosing;
        Log("工具資料夾：" + DIR, Color.DimGray);
        if (!File.Exists(Path.Combine(DIR, "TrignoBridge.exe"))) Log("找不到 TrignoBridge.exe：面板要放在工具資料夾裡", Color.OrangeRed);
    }

    // ---------------------------------------------------------------- layout helpers
    FlowLayoutPanel Group(FlowLayoutPanel parent, string title)
    {
        var gb = new GroupBox { Text = title, Font = UIB, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
                                Width = 520, MinimumSize = new Size(520, 0), Padding = new Padding(6, 4, 6, 6) };
        var f = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false,
                                      AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Font = UI };
        gb.Controls.Add(f); parent.Controls.Add(gb);
        return f;
    }

    static void Row(FlowLayoutPanel g, params Control[] cs)
    {
        var r = new FlowLayoutPanel { AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, WrapContents = false, Margin = new Padding(0, 2, 0, 2) };
        foreach (var c in cs) r.Controls.Add(c);
        g.Controls.Add(r);
    }

    static Label Lbl(string t) { return new Label { Text = t, AutoSize = true, Margin = new Padding(3, 7, 2, 0) }; }
    static Label Hint(string t) { return new Label { Text = t, AutoSize = true, MaximumSize = new Size(490, 0), ForeColor = Color.DimGray, Margin = new Padding(3, 2, 3, 4) }; }
    static TextBox Box(int w, string text, string name) { return new TextBox { Width = w, Text = text, AccessibleName = name }; }
    static Button Btn(string t, EventHandler h)
    {
        var b = new Button { Text = t, AutoSize = true, MinimumSize = new Size(120, 34) };
        b.Click += h; return b;
    }
    static void Mark(Button b) { b.BackColor = Color.PaleGreen; if (!b.Text.EndsWith(" ✓")) b.Text += " ✓"; }

    void RefreshPorts()
    {
        string cur = com.Text;
        com.Items.Clear();
        foreach (var p in SerialPort.GetPortNames()) com.Items.Add(p);
        if (cur != "" && com.Items.Contains(cur)) com.SelectedIndex = com.Items.IndexOf(cur);
        else if (com.Items.Contains("COM6")) com.SelectedIndex = com.Items.IndexOf("COM6");
        else if (com.Items.Count > 0) com.SelectedIndex = 0;
        else Log("找不到任何 COM 埠：板子有接上嗎？接上後按「重新找」。", Color.OrangeRed);
    }

    int K { get { return Nine ? 9 : 6; } }

    void UpdateGestures()
    {
        for (int i = 0; i < 9; i++) {
            calCount[i] = 0;
            calBtn[i].Visible = i < K;
            ShowCal(i);
        }
        calibrateBtn.Text = Passes == 1 ? "calibrate（" + K + " 個都做完再按）" : "calibrate（" + K + " 個各做 " + Passes + " 輪再按）";
        calibrateBtn.BackColor = SystemColors.Control;
        if (calHint != null)
            calHint.Text = Passes == 1
                ? "按下去就馬上做該手勢並維持，看到 calend 再放鬆 2–3 秒。做錯就再按一次同一個。"
                : "第一輪 cal 0 → cal " + (K - 1) + "，再第二輪 cal 0 → cal " + (K - 1) + "。按下去就馬上做該手勢並維持 4 秒，看到 calend 再放鬆 2–3 秒。\n按鈕後面會顯示做了幾次；做錯就再按一次同一個（會變 3 次，沒關係）。";
    }

    void ShowCal(int i)
    {
        if (i >= K) return;
        int n = calCount[i];
        calBtn[i].Text = "cal " + i + "  " + GESTURE_ZH[i] + (n > 0 ? "  " + n + " 次" : "");
        calBtn[i].BackColor = n >= Passes ? Color.PaleGreen : n > 0 ? Color.Khaki : SystemColors.Control;
    }

    void UpdateName()
    {
        nameLbl.Text = "今天的檔名：" + Name0;
        if (dest != null && dest.Text.StartsWith(@"D:\selftest_data\")) dest.Text = @"D:\selftest_data\" + subj.Text.Trim();
    }

    void UpdateState()
    {
        bool on = BridgeOn, busy = ToolOn;
        foreach (var c in needBridge) c.Enabled = on;
        foreach (var c in needIdle) c.Enabled = !on && !busy;
        subj.Enabled = day.Enabled = com.Enabled = rate.Enabled = slots.Enabled = tcu.Enabled = gset.Enabled = !on;
        state.Text = on ? "● 錄製中：" + Name0 : busy ? "… 工具執行中" : "○ 未開始";
        state.ForeColor = on ? Color.ForestGreen : busy ? Color.DarkOrange : Color.Gray;
    }

    // ---------------------------------------------------------------- log
    void Log(string line, Color c)
    {
        if (log.InvokeRequired) { log.BeginInvoke(new Action(() => Log(line, c))); return; }
        log.SelectionStart = log.TextLength; log.SelectionLength = 0; log.SelectionColor = c;
        log.AppendText(line + "\n"); log.ScrollToCaret();
        try { File.AppendAllText(Path.Combine(DIR, "ExperimentPanel_log.txt"), DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + line + Environment.NewLine); }
        catch (IOException) { }
    }

    static Color ColorOf(string l)
    {
        string u = l.ToUpperInvariant();
        if (u.Contains("WARNING") || u.Contains("ERROR") || u.Contains("CANNOT") || u.Contains("FAIL") || u.Contains("LOST")) return Color.OrangeRed;
        if (u.Contains("CALEND") || u.StartsWith("OK") || u.Contains(" OK")) return Color.LightGreen;
        if (u.StartsWith("?")) return Color.Gold;
        return Color.Gainsboro;
    }

    // ---------------------------------------------------------------- processes
    string TcuArg() { return tcu.Text.Trim() == "" ? "" : " --tcu " + tcu.Text.Trim(); }

    Process Launch(string args, bool input)
    {
        var psi = new ProcessStartInfo(Path.Combine(DIR, "TrignoBridge.exe"), args) {
            WorkingDirectory = DIR, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = input,
            StandardOutputEncoding = Encoding.Default, StandardErrorEncoding = Encoding.Default };
        var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
        p.OutputDataReceived += (s, e) => { if (e.Data != null) Log(e.Data, ColorOf(e.Data)); };
        p.ErrorDataReceived += (s, e) => { if (e.Data != null) Log(e.Data, Color.OrangeRed); };
        Log("> TrignoBridge " + args, Color.SkyBlue);
        p.Start(); p.BeginOutputReadLine(); p.BeginErrorReadLine();
        return p;
    }

    void RunTool(string args, string what)
    {
        if (BridgeOn || ToolOn) return;
        try {
            tool = Launch(args, false);
            tool.Exited += delegate { Log("（" + what + " 結束，代碼 " + tool.ExitCode + "）", Color.SkyBlue); };
        } catch (Exception e) { Log("無法啟動：" + e.Message, Color.OrangeRed); }
    }

    void SaveCheck()
    {
        string src = Path.Combine(DIR, "emg_check.csv"), dst = Path.Combine(DIR, Name0 + "_emg_check.csv");
        if (!File.Exists(src)) { MessageBox.Show("還沒有 emg_check.csv：先按「量採樣率」。", Text); return; }
        if (File.Exists(dst)) { MessageBox.Show(Path.GetFileName(dst) + " 已經存在，沒有覆蓋。", Text); return; }
        File.Copy(src, dst);
        Log("emg_check.csv → " + Path.GetFileName(dst) + "（複製，原檔保留）", Color.LightGreen);
    }

    void StartBridge()
    {
        if (BridgeOn || ToolOn) return;
        if (com.Text.Trim() == "") { MessageBox.Show("找不到板子的 COM 埠：接上板子後按「重新找」。", Text); return; }
        if (File.Exists(Path.Combine(DIR, Name0 + "_emg.csv"))) {
            MessageBox.Show(Name0 + "_emg.csv 已經存在：今天已經錄過。\n不要刪舊檔，先停下來問。", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        string args = "run --port " + com.Text.Trim() + " --firmware lda" + (Nine ? " --classes 9" : "");
        if (rate.Text.Trim() != "") args += " --rate " + rate.Text.Trim();
        if (slots.Text.Trim() != "") args += " --slots " + slots.Text.Trim();
        args += TcuArg();
        args += " --emg-csv " + Name0 + "_emg.csv --mcu-csv " + Name0 + "_mcu.csv --ops-csv " + Name0 + "_ops.csv";
        try {
            bridge = Launch(args, true);
            bridgeIn = new StreamWriter(bridge.StandardInput.BaseStream, Encoding.Default) { AutoFlush = true };
            for (int i = 0; i < 9; i++) { calCount[i] = 0; ShowCal(i); }
            calibrateBtn.BackColor = SystemColors.Control; calibrateBtn.Text = calibrateBtn.Text.Replace(" ✓", "");
            bridge.Exited += delegate {
                Log("（橋接程式已結束，代碼 " + bridge.ExitCode + "）", Color.SkyBlue);
                if (verifyAfterQuit) { verifyAfterQuit = false; BeginInvoke(new Action(Verify)); }
            };
        } catch (Exception e) { Log("無法啟動橋接程式：" + e.Message, Color.OrangeRed); }
    }

    void Send(string line)
    {
        if (!BridgeOn) { Log("橋接程式沒有在跑：先按「開始錄製」", Color.OrangeRed); return; }
        Log("> " + line, Color.SkyBlue);
        bridgeIn.WriteLine(line);
    }

    void SendRaw()
    {
        string l = cmdBox.Text.Trim();
        if (l == "") return;
        if (l == "quit" && MessageBox.Show("quit 會結束錄製。確定？", Text, MessageBoxButtons.YesNo) != DialogResult.Yes) return;
        Send(l); cmdBox.Clear();
    }

    void SendEnv()
    {
        string sk = skin.Text.Trim() == "" ? "NA" : skin.Text.Trim();
        string rm = room.Text.Trim() == "" ? "NA" : room.Text.Trim();
        Send("note temp room " + rm + " skin " + sk);
        Send("note strap mark offset " + (strap.Text.Trim() == "" ? "0" : strap.Text.Trim()) + " mm, photo " + photo.Text.Trim());
        Send("note last forearm exercise: " + (exercise.Text.Trim() == "" ? "none today" : exercise.Text.Trim()));
    }

    void Calibrate()
    {
        var missing = new List<string>();
        for (int i = 0; i < K; i++) if (calCount[i] < Passes) missing.Add("cal " + i + " " + GESTURE_ZH[i] + "（" + calCount[i] + "/" + Passes + "）");
        if (missing.Count > 0 && MessageBox.Show("次數不夠：" + string.Join("、", missing) + "\n還是要 calibrate？", Text, MessageBoxButtons.YesNo) != DialogResult.Yes) return;
        Send("calibrate"); Mark(calibrateBtn);
    }

    void StartScreen(bool warmup)
    {
        string exe = Path.Combine(DIR, "TaskScreen.exe");
        // 9 gestures (2026-11-17, report 35.49): as the 6-gesture day, labelled / task / labelled / task / labelled; each
        // labelled segment 3 x 9 cues, each task segment 40 trials = 8 arm commands x 5 (soft labels replayed offline)
        string args = Nine
            ? (warmup
               ? "--subject W00 --day " + day.Text + " --cond G --gestures nine --segments labelled,task --reps 1 --n 8 --postures selftest"
               : "--subject " + subj.Text.Trim() + " --day " + day.Text + " --cond G --gestures nine --segments labelled,task,labelled,task,labelled --reps 3 --n 40 --postures selftest")
            : (warmup
               ? "--subject W00 --day " + day.Text + " --cond A --segments labelled,task --reps 1 --n 10 --postures selftest"
               : "--subject " + subj.Text.Trim() + " --day " + day.Text + " --cond A --segments labelled,task,labelled,task,labelled --reps 2 --n 40 --postures selftest");
        if (!warmup && Directory.GetFiles(DIR, Name0 + "*_task.csv").Length > 0 &&
            MessageBox.Show("今天已經開過正式提示畫面（有 " + Name0 + "_task.csv）。\n只有畫面當掉或關掉時才需要再開。要再開嗎？", Text, MessageBoxButtons.YesNo) != DialogResult.Yes) return;
        if (!warmup && calibrateBtn.BackColor != Color.PaleGreen &&
            MessageBox.Show("還沒按 calibrate。還是要開正式提示畫面？", Text, MessageBoxButtons.YesNo) != DialogResult.Yes) return;
        try {
            Process.Start(new ProcessStartInfo(exe, args) { WorkingDirectory = DIR, UseShellExecute = false });
            Log("> TaskScreen " + args, Color.SkyBlue);
        } catch (Exception e) { Log("無法開提示畫面：" + e.Message, Color.OrangeRed); }
    }

    void EndSession()
    {
        if (MessageBox.Show("提示畫面都做完了嗎？按「是」會結束錄製，然後檢查檔案。", Text, MessageBoxButtons.YesNo) != DialogResult.Yes) return;
        Send("note end");
        verifyAfterQuit = true;
        Send("quit");
    }

    void Verify()
    {
        if (BridgeOn || ToolOn) return;
        string args = "verify --name " + Name0 + (rate.Text.Trim() != "" ? " --rate " + rate.Text.Trim() : "");
        RunTool(args, "verify");
        Log("看到「OK: all files are there」就好；有 WARNING 就截圖，不要刪任何檔案。", Color.Gold);
        Log("（自我測試沒有打 report 1，所以「no predictions from the board」這一條是預期的；分析用的是肌電檔，不受影響。）", Color.Gold);
    }

    void CopyFiles()
    {
        string to = dest.Text.Trim();
        try { Directory.CreateDirectory(to); }
        catch (Exception e) { MessageBox.Show("無法建立 " + to + "：" + e.Message + "\n按「選…」換一個資料夾。", Text); return; }
        var files = new List<string>();
        foreach (var suf in new[] { "_emg.csv", "_mcu.csv", "_ops.csv", "_emg_check.csv" })
            if (File.Exists(Path.Combine(DIR, Name0 + suf))) files.Add(Path.Combine(DIR, Name0 + suf));
        files.AddRange(Directory.GetFiles(DIR, Name0 + "*_task.csv"));
        int done = 0, same = 0;
        foreach (var f in files) {
            string d = Path.Combine(to, Path.GetFileName(f));
            if (File.Exists(d)) {
                if (new FileInfo(d).Length == new FileInfo(f).Length) { same++; continue; }
                Log("沒有覆蓋（大小不同）：" + d, Color.OrangeRed); continue;
            }
            File.Copy(f, d); done++;
            Log("複製 " + Path.GetFileName(f) + " → " + to, Color.LightGreen);
        }
        Log(string.Format("複製 {0} 個，已存在且相同 {1} 個（共找到 {2} 個）。原檔都還在工具資料夾。", done, same, files.Count), Color.Gold);
    }

    void OnClosing(object s, FormClosingEventArgs e)
    {
        if (!BridgeOn) return;
        if (MessageBox.Show("還在錄製。要結束錄製並關閉面板嗎？", Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) {
            e.Cancel = true; return;
        }
        try { bridgeIn.WriteLine("quit"); bridge.WaitForExit(5000); } catch (Exception) { }
    }

    [STAThread]
    static void Main()
    {
        Application.EnableVisualStyles();
        Application.Run(new ExperimentPanel());
    }
}
