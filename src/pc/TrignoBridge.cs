// Route B on the lab PC without installing anything: one .exe built with the C# compiler that ships with Windows
// (.NET Framework 4: C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe), C# 5. Same protocol as
// src/pc/protocol.py and src/c/protocol.h; same TCU handling as src/pc/trigno_bridge.py (to be verified on the lab PC).
//
//   TrignoBridge check  [--tcu 127.0.0.1] [--seconds 60] [--out emg_check.csv]
//       TCU only (no STM32): START, record, then the measured sample rate (frames / time) and per channel the
//       largest |value| and the RMS; warns when a channel comes near the +-8.19 mV the MCU encoding can carry.
//   TrignoBridge run    --port COM5 [--tcu 127.0.0.1] [--rate 2000] [--emg-csv emg.csv] [--mcu-csv mcu.csv]
//                       [--script commands.txt]          (--port file:<path>: write the serial bytes to a file)
//       TCU -> (resampled to 2000 Hz when --rate is not 2000) -> int16 0.25 uV -> packets -> COM port at 921600;
//       MCU packets -> mcu.csv and the console. Commands typed while running:
//         reset | cal <0-5> | calend | calibrate | align | decision <tau_permille> <k> | report <0|1> | status | quit
//       cal <g> = reset + CAL_START; CAL_END follows by itself after 2 s of samples (10 windows per gesture).
//       align = reset + ALIGN_START; ALIGN_END follows by itself after 8 s (70 windows; the MCU needs >= 60 and
//       several gestures, report 20): start-up alignment after the sensors were put on again.
//       --script: lines "<seconds> <command>" run at those times after START (for tests).
//   TrignoBridge replay --port COM5 --dir <board_replay folder>
//       board test without the Trigno: the recorded stream of src/board_replay.py (stream.bin, schedule.csv,
//       windows.csv) sent in real time; prints the board's status events and its accuracy per block.
// Gestures: 0 Power, 1 Lateral, 2 Tripod, 3 Pointer, 4 Open, 5 Rest.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Ports;
using System.Net.Sockets;
using System.Text;
using System.Threading;

static class Proto
{
    public const byte SAMPLES = 0x01, CONTROL = 0x02, COMMAND = 0x81, STATUS = 0x82, PRED = 0x83;
    public const byte STREAM_RESET = 1, CAL_START = 2, CAL_END = 3, CALIBRATE = 4, SET_DECISION = 5, SET_REPORT = 6,
                      ALIGN_START = 7, ALIGN_END = 8;
    public const int CH = 8, FRAMES_PER_PACKET = 20, MAX_PAYLOAD = 512, OVERHEAD = 9;
    public const double LSB_VOLT = 2.5e-7;
    public static readonly string[] GESTURES = { "Power", "Lateral", "Tripod", "Pointer", "Open", "Rest" };
    public static readonly string[] COMMANDS = { "none", "pose_A", "grip", "pose_B", "release" };
    static ushort seqSamples, seqControl;

    public static ushort Crc16(byte[] b, int off, int n)          // CRC-16/CCITT-FALSE
    {
        ushort crc = 0xFFFF;
        for (int i = 0; i < n; i++) {
            crc ^= (ushort)(b[off + i] << 8);
            for (int k = 0; k < 8; k++)
                crc = (ushort)((crc & 0x8000) != 0 ? (crc << 1) ^ 0x1021 : crc << 1);
        }
        return crc;
    }

    public static byte[] Build(byte type, byte[] payload)
    {
        ushort seq = type == SAMPLES ? seqSamples++ : seqControl++;
        var b = new byte[OVERHEAD + payload.Length];
        b[0] = 0xA5; b[1] = 0x5A; b[2] = type;
        b[3] = (byte)seq; b[4] = (byte)(seq >> 8);
        b[5] = (byte)payload.Length; b[6] = (byte)(payload.Length >> 8);
        Array.Copy(payload, 0, b, 7, payload.Length);
        ushort c = Crc16(b, 2, 5 + payload.Length);
        b[7 + payload.Length] = (byte)c; b[8 + payload.Length] = (byte)(c >> 8);
        return b;
    }

    public static byte[] Control(byte sub, params int[] args)
    {
        if (sub == CAL_START || sub == SET_REPORT) return Build(CONTROL, new byte[] { sub, (byte)args[0] });
        if (sub == SET_DECISION)
            return Build(CONTROL, new byte[] { sub, (byte)args[0], (byte)(args[0] >> 8), (byte)args[1] });
        return Build(CONTROL, new byte[] { sub });
    }
}

// incremental parser, same resync rule as protocol.c / protocol.py
class Decoder
{
    List<byte> buf = new List<byte>();
    public int Ok, CrcErrors, Skipped;

    public List<KeyValuePair<byte, byte[]>> Feed(byte[] data, int n)
    {
        for (int i = 0; i < n; i++) buf.Add(data[i]);
        var outp = new List<KeyValuePair<byte, byte[]>>();
        while (buf.Count > 0) {
            if (buf[0] != 0xA5 || (buf.Count >= 2 && buf[1] != 0x5A)) { Resync(); continue; }
            if (buf.Count < 7) break;
            int len = buf[5] | (buf[6] << 8);
            if (len > Proto.MAX_PAYLOAD) { Resync(); continue; }
            if (buf.Count < Proto.OVERHEAD + len) break;
            byte[] pk = buf.GetRange(0, Proto.OVERHEAD + len).ToArray();
            ushort crc = (ushort)(pk[7 + len] | (pk[8 + len] << 8));
            if (Proto.Crc16(pk, 2, 5 + len) != crc) { CrcErrors++; Resync(); continue; }
            var payload = new byte[len];
            Array.Copy(pk, 7, payload, 0, len);
            outp.Add(new KeyValuePair<byte, byte[]>(pk[2], payload));
            Ok++;
            buf.RemoveRange(0, Proto.OVERHEAD + len);
        }
        return outp;
    }

    void Resync()
    {
        int k = buf.IndexOf(0xA5, 1);
        if (k < 0) k = buf.Count;
        Skipped += k;
        buf.RemoveRange(0, k);
    }
}

// windowed-sinc resampler for a steady stream (any rate -> 2000 Hz), per channel, latency TAPS / rate_in
class Resampler
{
    const int TAPS = 16;                                          // per side
    readonly double step, cutoff;
    readonly List<double[]> hist = new List<double[]>();
    long histStart;                                               // input index of hist[0]
    long nIn;                                                     // input samples seen
    double tNext;                                                 // next output time in input samples

    public Resampler(double rateIn, double rateOut)
    {
        step = rateIn / rateOut;
        cutoff = Math.Min(1.0, 1.0 / step) * 0.95;                // relative to the input Nyquist
    }

    public List<double[]> Push(double[] x)
    {
        hist.Add(x);
        nIn++;
        var outp = new List<double[]>();
        while (tNext + TAPS < nIn) {                              // all taps of the next output are available
            long c = (long)Math.Floor(tNext);
            var y = new double[x.Length];
            double wsum = 0;
            for (long k = c - TAPS + 1; k <= c + TAPS; k++) {
                if (k < histStart || k < 0) continue;
                double d = tNext - k;
                double w = Sinc(cutoff * d) * (0.5 + 0.5 * Math.Cos(Math.PI * d / (TAPS + 1)));
                double[] s = hist[(int)(k - histStart)];
                for (int ch = 0; ch < y.Length; ch++) y[ch] += w * s[ch];
                wsum += w;
            }
            for (int ch = 0; ch < y.Length; ch++) y[ch] /= wsum; // unit DC gain
            outp.Add(y);
            tNext += step;
            long keep = (long)Math.Floor(tNext) - TAPS;
            while (histStart < keep && hist.Count > 0) { hist.RemoveAt(0); histStart++; }
        }
        return outp;
    }

    static double Sinc(double x) { return Math.Abs(x) < 1e-12 ? 1.0 : Math.Sin(Math.PI * x) / (Math.PI * x); }
}

class Tcu
{
    public const int CHANNELS = 16;
    TcpClient cmd, emg;
    NetworkStream cs, es;
    public string Banner;

    public Tcu(string host)
    {
        cmd = new TcpClient(host, 50040);
        emg = new TcpClient(host, 50041);
        cs = cmd.GetStream(); es = emg.GetStream();
        cs.ReadTimeout = 10000;
        Banner = Reply();
    }

    string Reply()
    {
        var sb = new StringBuilder();
        var b = new byte[1024];
        while (!sb.ToString().EndsWith("\r\n\r\n")) {
            int n = cs.Read(b, 0, b.Length);
            if (n <= 0) break;
            sb.Append(Encoding.ASCII.GetString(b, 0, n));
        }
        return sb.ToString().Trim();
    }

    public string Command(string text)
    {
        var b = Encoding.ASCII.GetBytes(text + "\r\n\r\n");
        cs.Write(b, 0, b.Length);
        return Reply();
    }

    byte[] rbuf = new byte[1 << 16];
    byte[] carry = new byte[0];

    // next frames (CHANNELS floats each, volts); empty when the stream ended
    public List<float[]> Read()
    {
        var outp = new List<float[]>();
        int n = es.Read(rbuf, 0, rbuf.Length);
        if (n <= 0) return outp;
        var all = new byte[carry.Length + n];
        Array.Copy(carry, all, carry.Length);
        Array.Copy(rbuf, 0, all, carry.Length, n);
        int fb = CHANNELS * 4, m = all.Length / fb;
        for (int i = 0; i < m; i++) {
            var f = new float[CHANNELS];
            for (int c = 0; c < CHANNELS; c++) f[c] = BitConverter.ToSingle(all, i * fb + c * 4);
            outp.Add(f);
        }
        carry = new byte[all.Length - m * fb];
        Array.Copy(all, m * fb, carry, 0, carry.Length);
        return outp;
    }

    public void Close()
    {
        try { Command("STOP"); } catch (Exception) { }
        cmd.Close(); emg.Close();
    }
}

static class Program
{
    static readonly CultureInfo IC = CultureInfo.InvariantCulture;
    const double CLIP_V = 32767 * Proto.LSB_VOLT;                  // 8.19 mV

    static Dictionary<string, string> Args(string[] a, int from)
    {
        var d = new Dictionary<string, string>();
        for (int i = from; i + 1 < a.Length; i += 2) d[a[i].TrimStart('-')] = a[i + 1];
        return d;
    }

    static string Get(Dictionary<string, string> d, string k, string def) { return d.ContainsKey(k) ? d[k] : def; }

    // --port must name a serial port (COMx) or file:<path>; anything else (e.g. an empty %1 in a .bat) stops here
    static string PortArg(Dictionary<string, string> d)
    {
        string p = Get(d, "port", "");
        if (p.StartsWith("COM", StringComparison.OrdinalIgnoreCase) || p.StartsWith("file:")) return p;
        Console.WriteLine("請指定 STM32 的 COM port，例如 --port COM5（裝置管理員 → 連接埠 → STMicroelectronics STLink Virtual COM Port）");
        Console.WriteLine("ports on this PC: " + string.Join(" ", SerialPort.GetPortNames()));
        return null;
    }

    static int Main(string[] argv)
    {
        if (argv.Length < 1) { Console.WriteLine("usage: TrignoBridge check|run|replay [options] (see the top of TrignoBridge.cs)"); return 1; }
        var a = Args(argv, 1);
        try {
            if (argv[0] == "check") return Check(a);
            if (argv[0] == "run") return Run(a);
            if (argv[0] == "replay") return Replay(a);
        } catch (Exception e) {
            Console.WriteLine("ERROR: " + e.Message);
            return 2;
        }
        Console.WriteLine("unknown mode " + argv[0]);
        return 1;
    }

    // ------------------------------------------------------------------ check: TCU only
    static int Check(Dictionary<string, string> a)
    {
        double seconds = double.Parse(Get(a, "seconds", "60"), IC);
        string outPath = Get(a, "out", "emg_check.csv");
        var tcu = new Tcu(Get(a, "tcu", "127.0.0.1"));
        Console.WriteLine("TCU banner: " + tcu.Banner);
        Console.WriteLine("START -> " + tcu.Command("START"));
        var max = new double[Tcu.CHANNELS]; var sq = new double[Tcu.CHANNELS];
        long frames = 0;
        var sw = new Stopwatch();
        using (var w = new StreamWriter(outPath)) {
            w.WriteLine("pc_ms,frame," + string.Join(",", Enumerable(Tcu.CHANNELS, "ch{0}_V")));
            while (true) {
                var fr = tcu.Read();
                if (fr.Count == 0) break;
                if (!sw.IsRunning) sw.Start();                    // rate from the first data on
                double t = sw.Elapsed.TotalMilliseconds;
                foreach (var f in fr) {
                    var sb = new StringBuilder();
                    sb.Append(t.ToString("F1", IC)).Append(',').Append(frames);
                    for (int c = 0; c < Tcu.CHANNELS; c++) {
                        sb.Append(',').Append(f[c].ToString("G9", IC));
                        max[c] = Math.Max(max[c], Math.Abs(f[c])); sq[c] += (double)f[c] * f[c];
                    }
                    w.WriteLine(sb.ToString());
                    frames++;
                }
                if (sw.Elapsed.TotalSeconds >= seconds) break;
            }
        }
        double el = sw.Elapsed.TotalSeconds;
        tcu.Close();
        Console.WriteLine(string.Format(IC, "{0} frames in {1:F2} s -> measured rate {2:F1} Hz (2000 = no resampling needed)",
                                        frames, el, frames / el));
        Console.WriteLine("channel  max|V| (mV)  RMS (uV)");
        for (int c = 0; c < Tcu.CHANNELS; c++) {
            double rms = frames > 0 ? Math.Sqrt(sq[c] / frames) : 0;
            string note = max[c] == 0 ? "  (no signal)" : max[c] > 0.8 * CLIP_V ? "  WARNING: near the 8.19 mV limit" : "";
            Console.WriteLine(string.Format(IC, "  {0,2}      {1,8:F3}    {2,8:F1}{3}", c + 1, max[c] * 1e3, rms * 1e6, note));
        }
        Console.WriteLine("saved " + outPath);
        return 0;
    }

    static string[] Enumerable(int n, string fmt)
    {
        var s = new string[n];
        for (int i = 0; i < n; i++) s[i] = string.Format(fmt, i + 1);
        return s;
    }

    // ------------------------------------------------------------------ run: TCU -> MCU
    static object txLock = new object();
    static SerialPort port;
    static volatile bool stop;
    static StreamWriter mcuCsv;
    static Stopwatch clock = Stopwatch.StartNew();
    static int mcuPackets, preds;
    // cal <g> = reset + CAL_START, then CAL_END by itself after CAL_FRAMES samples have gone out (2 s: windows 9..18
    // after the reset = 10 windows per gesture, as the data set; rt.c caps the total at 60, not per gesture)
    // align = reset + ALIGN_START, then ALIGN_END by itself after ALIGN_FRAMES (8 s: 79 windows - 9 warmup = 70)
    const long CAL_FRAMES = 4000, ALIGN_FRAMES = 16000;
    static long framesSent, autoStart = -1, autoFrames;
    static byte autoEnd;                                          // CAL_END or ALIGN_END while one is pending
    static string autoMsg;

    static void StartAuto(byte start, int arg, byte end, long frames, string msg)
    {
        lock (txLock) {
            if (autoStart >= 0) Send(Proto.Control(autoEnd));      // the previous gesture / alignment was not finished
            Send(Proto.Control(Proto.STREAM_RESET));
            Send(arg >= 0 ? Proto.Control(start, arg) : Proto.Control(start));
            autoStart = framesSent; autoFrames = frames; autoEnd = end; autoMsg = msg;
        }
    }

    static FileStream fileOut;                                    // --port file:<path> (test without the MCU)

    static void Send(byte[] b)
    {
        lock (txLock) {
            if (fileOut != null) fileOut.Write(b, 0, b.Length);
            else port.Write(b, 0, b.Length);
        }
    }

    static bool DoCommand(string line)
    {
        var p = line.Trim().Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
        if (p.Length == 0) return true;
        string c = p[0].ToLowerInvariant();
        if (c == "quit") { stop = true; return true; }
        if (c == "reset") Send(Proto.Control(Proto.STREAM_RESET));
        else if (c == "cal" && p.Length == 2) {
            int g = int.Parse(p[1]);
            if (g < 0 || g > 5) { Console.WriteLine("gesture 0-5: 0 Power, 1 Lateral, 2 Tripod, 3 Pointer, 4 Open, 5 Rest"); return false; }
            StartAuto(Proto.CAL_START, g, Proto.CAL_END, CAL_FRAMES, "calend (auto, 2 s): you can relax");
            Console.WriteLine(string.Format(IC, "[{0:F1} s] cal {1} ({2}): do the gesture now and hold it; calend comes by itself after 2 s",
                                            clock.Elapsed.TotalSeconds, g, Proto.GESTURES[g]));
            return true;
        }
        else if (c == "calend") { lock (txLock) { Send(Proto.Control(Proto.CAL_END)); autoStart = -1; } }
        else if (c == "align") {
            StartAuto(Proto.ALIGN_START, -1, Proto.ALIGN_END, ALIGN_FRAMES, "alignend (auto, 8 s): the MCU answers with 'rotation'");
            Console.WriteLine(string.Format(IC, "[{0:F1} s] align: for 8 s do each gesture about 1 s: Power, Lateral, Tripod, Pointer, Open, Rest",
                                            clock.Elapsed.TotalSeconds));
            return true;
        }
        else if (c == "calibrate") Send(Proto.Control(Proto.CALIBRATE));
        else if (c == "decision" && p.Length == 3) Send(Proto.Control(Proto.SET_DECISION, int.Parse(p[1]), int.Parse(p[2])));
        else if (c == "report" && p.Length == 2) Send(Proto.Control(Proto.SET_REPORT, int.Parse(p[1])));
        else if (c == "status") return true;
        else { Console.WriteLine("? reset | cal <0-5> | calend | calibrate | align | decision <tau_permille> <k> | report <0|1> | status | quit"); return false; }
        Console.WriteLine(string.Format(IC, "[{0:F1} s] sent: {1}", clock.Elapsed.TotalSeconds, line.Trim()));
        return true;
    }

    static void Reader()
    {
        var dec = new Decoder();
        var b = new byte[4096];
        while (!stop) {
            int n = 0;
            try { n = port.Read(b, 0, b.Length); } catch (TimeoutException) { continue; } catch (Exception) { break; }
            foreach (var pk in dec.Feed(b, n)) {
                mcuPackets++;
                string line = Describe(pk.Key, pk.Value);
                lock (mcuCsv) mcuCsv.WriteLine(clock.Elapsed.TotalMilliseconds.ToString("F1", IC) + "," + line);
                if (pk.Key == Proto.PRED) preds++;
                else Console.WriteLine(string.Format(IC, "[{0:F1} s] MCU: {1}", clock.Elapsed.TotalSeconds, line));
            }
        }
    }

    // csv columns: kind,window,t_us,gesture,command,accepted,ratio,pushed,event,value
    static string Describe(byte type, byte[] p)
    {
        if (type == Proto.COMMAND && p.Length >= 12) {
            int cmd = p[8], cls = p[9];
            return string.Format(IC, "command,{0},{1},{2},{3},,{4:F3},,,", BitConverter.ToUInt32(p, 0), BitConverter.ToUInt32(p, 4),
                                 cls < 6 ? Proto.GESTURES[cls] : cls.ToString(), cmd < 5 ? Proto.COMMANDS[cmd] : cmd.ToString(),
                                 BitConverter.ToUInt16(p, 10) / 1000.0);
        }
        if (type == Proto.PRED && p.Length >= 13) {
            int cls = p[8];
            return string.Format(IC, "pred,{0},{1},{2},,{3},{4:F3},{5},,", BitConverter.ToUInt32(p, 0), BitConverter.ToUInt32(p, 4),
                                 cls < 6 ? Proto.GESTURES[cls] : cls.ToString(), p[9], BitConverter.ToUInt16(p, 10) / 1000.0, p[12]);
        }
        if (type == Proto.STATUS && p.Length >= 8) {
            int ev = p[0], v = BitConverter.ToInt32(p, 4);
            string[] names = { "", "calibrated (0 = ok)", "self-calibration blocks", "packets lost", "calibration windows", "rotation",
                               "alignment too short, rotation unchanged (windows)",
                               "self-calibration start (windows so far)", "self-calibration took (us)", "receive ring high-water (bytes)",
                               "stack peak (bytes)", "UART bytes dropped", "UART errors" };
            return string.Format(IC, "status,,,,,,,,{0},{1}", ev < names.Length ? names[ev] : ev.ToString(), v);
        }
        return "unknown,type " + type + ",len " + p.Length + ",,,,,,,";
    }

    static int Run(Dictionary<string, string> a)
    {
        double rate = double.Parse(Get(a, "rate", "2000"), IC);
        string portName = PortArg(a);
        if (portName == null) return 1;
        var tcu = new Tcu(Get(a, "tcu", "127.0.0.1"));
        Console.WriteLine("TCU banner: " + tcu.Banner);
        mcuCsv = new StreamWriter(Get(a, "mcu-csv", "mcu.csv"));
        mcuCsv.WriteLine("pc_ms,kind,window,t_us,gesture,command,accepted,ratio,pushed,event,value");
        if (portName.StartsWith("file:")) {
            fileOut = new FileStream(portName.Substring(5), FileMode.Create);
            Console.WriteLine("no MCU: the serial bytes go to " + portName.Substring(5));
        } else {
            port = new SerialPort(portName, 921600, Parity.None, 8, StopBits.One);
            port.ReadTimeout = 50; port.WriteTimeout = 2000;
            port.Open(); port.DiscardInBuffer();
            var reader = new Thread(Reader) { IsBackground = true };
            reader.Start();
        }
        Resampler rs = Math.Abs(rate - 2000) > 1e-6 ? new Resampler(rate, 2000) : null;
        Console.WriteLine(rs == null ? "input 2000 Hz: no resampling" : string.Format(IC, "input {0} Hz -> resampled to 2000 Hz", rate));

        var script = new List<KeyValuePair<double, string>>();
        if (a.ContainsKey("script"))
            foreach (var l in File.ReadAllLines(a["script"])) {
                var t = l.Trim();
                if (t.Length == 0 || t.StartsWith("#")) continue;
                int sp = t.IndexOf(' ');
                script.Add(new KeyValuePair<double, string>(double.Parse(t.Substring(0, sp), IC), t.Substring(sp + 1)));
            }
        else {
            var input = new Thread(() => { string l; while (!stop && (l = Console.ReadLine()) != null) DoCommand(l); });
            input.IsBackground = true;
            input.Start();
            Console.WriteLine("commands: reset | cal <0-5> | calend | calibrate | align | decision <tau> <k> | report <0|1> | status | quit");
        }

        Console.WriteLine("START -> " + tcu.Command("START"));
        double t0 = clock.Elapsed.TotalSeconds;
        int si = 0;
        long framesIn = 0, framesOut = 0, clipped = 0;
        var pending = new List<short[]>();
        double lastReport = 0;
        using (var emg = new StreamWriter(Get(a, "emg-csv", "emg.csv"))) {
            emg.WriteLine("pc_ms,frame," + string.Join(",", Enumerable(Proto.CH, "ch{0}_V")));
            while (!stop) {
                double now = clock.Elapsed.TotalSeconds - t0;
                while (si < script.Count && script[si].Key <= now) DoCommand(script[si++].Value);
                if (script.Count > 0 && si == script.Count) stop = true;
                var fr = tcu.Read();
                if (fr.Count == 0) break;
                double ms = clock.Elapsed.TotalMilliseconds;
                foreach (var f in fr) {
                    var sb = new StringBuilder();
                    sb.Append(ms.ToString("F1", IC)).Append(',').Append(framesIn);
                    var x = new double[Proto.CH];
                    for (int c = 0; c < Proto.CH; c++) { x[c] = f[c]; sb.Append(',').Append(f[c].ToString("G9", IC)); }
                    emg.WriteLine(sb.ToString());
                    framesIn++;
                    var outs = rs == null ? new List<double[]> { x } : rs.Push(x);
                    foreach (var y in outs) {
                        var q = new short[Proto.CH];
                        for (int c = 0; c < Proto.CH; c++) {
                            double v = Math.Round(y[c] / Proto.LSB_VOLT, MidpointRounding.ToEven);
                            if (v > 32767 || v < -32768) { clipped++; v = Math.Max(-32768, Math.Min(32767, v)); }
                            q[c] = (short)v;
                        }
                        pending.Add(q);
                        framesOut++;
                    }
                }
                while (pending.Count >= Proto.FRAMES_PER_PACKET) {
                    var pl = new byte[Proto.FRAMES_PER_PACKET * Proto.CH * 2];
                    for (int i = 0; i < Proto.FRAMES_PER_PACKET; i++)
                        for (int c = 0; c < Proto.CH; c++) {
                            short s = pending[i][c];
                            pl[(i * Proto.CH + c) * 2] = (byte)s; pl[(i * Proto.CH + c) * 2 + 1] = (byte)(s >> 8);
                        }
                    pending.RemoveRange(0, Proto.FRAMES_PER_PACKET);
                    lock (txLock) {
                        Send(Proto.Build(Proto.SAMPLES, pl));
                        framesSent += Proto.FRAMES_PER_PACKET;
                        if (autoStart >= 0 && framesSent - autoStart >= autoFrames) {
                            Send(Proto.Control(autoEnd));
                            autoStart = -1;
                            Console.WriteLine(string.Format(IC, "[{0:F1} s] {1}", clock.Elapsed.TotalSeconds, autoMsg));
                        }
                    }
                }
                if (now - lastReport >= 10) {
                    lastReport = now;
                    Console.WriteLine(string.Format(IC, "[{0:F0} s] in {1} frames ({2:F1} Hz measured), out {3}, clipped {4}, MCU packets {5} (PRED {6})",
                                                    now, framesIn, now > 0 ? framesIn / now : 0, framesOut, clipped, mcuPackets, preds));
                    if (rs == null && now > 20 && Math.Abs(framesIn / now - 2000) > 20)
                        Console.WriteLine("WARNING: the TCU is not sending 2000 Hz: restart with --rate <measured rate>");
                }
            }
        }
        stop = true;
        tcu.Close();
        Thread.Sleep(300);
        if (port != null) port.Close();
        if (fileOut != null) fileOut.Close();
        lock (mcuCsv) mcuCsv.Close();
        Console.WriteLine(string.Format(IC, "done: {0} frames in, {1} out, {2} samples clipped, {3} MCU packets ({4} PRED)",
                                        framesIn, framesOut, clipped, mcuPackets, preds));
        return 0;
    }

    // ------------------------------------------------------------------ replay: board test without the Trigno
    static int Replay(Dictionary<string, string> a)
    {
        string dir = Get(a, "dir", "board_replay");
        string portName = PortArg(a);
        if (portName == null || portName.StartsWith("file:")) return 1;
        byte[] stream = File.ReadAllBytes(Path.Combine(dir, "stream.bin"));
        var ends = new List<int>(); var times = new List<double>();
        foreach (var l in File.ReadAllLines(Path.Combine(dir, "schedule.csv"))) {
            if (l.StartsWith("end")) continue;
            var f = l.Split(',');
            ends.Add(int.Parse(f[0], IC)); times.Add(double.Parse(f[1], IC));
        }
        var labels = new List<int>(); var blocks = new List<int>();
        foreach (var l in File.ReadAllLines(Path.Combine(dir, "windows.csv"))) {
            if (l.StartsWith("block")) continue;
            var f = l.Split(',');
            blocks.Add(int.Parse(f[0], IC)); labels.Add(int.Parse(f[3], IC));
        }
        var dec = new Decoder();
        var predCls = new List<int>(); var events = new List<string>();
        var buf = new byte[65536];
        Console.WriteLine(string.Format(IC, "replaying {0} packets ({1:F0} s) to {2}...", ends.Count, times[times.Count - 1], portName));
        using (var sp = new SerialPort(portName, 921600, Parity.None, 8, StopBits.One)) {
            sp.ReadTimeout = 1; sp.WriteTimeout = 2000; sp.ReadBufferSize = 1 << 20;
            sp.Open(); sp.DiscardInBuffer();
            var sw = Stopwatch.StartNew();
            int start = 0, i = 0;
            double endT = times[times.Count - 1] + 5;
            while (sw.Elapsed.TotalSeconds < endT) {
                double now = sw.Elapsed.TotalSeconds;
                while (i < ends.Count && times[i] <= now) { sp.Write(stream, start, ends[i] - start); start = ends[i]; i++; }
                int n = sp.BytesToRead;
                if (n > 0) {
                    int got = sp.Read(buf, 0, Math.Min(n, buf.Length));
                    foreach (var pk in dec.Feed(buf, got)) {
                        if (pk.Key == Proto.PRED) predCls.Add(pk.Value[8]);
                        else if (pk.Key == Proto.STATUS) {
                            string d = Describe(pk.Key, pk.Value);
                            events.Add(d);
                            Console.WriteLine(string.Format(IC, "[{0:F1} s] MCU: {1}", now, d));
                        }
                    }
                } else Thread.Sleep(0);
            }
        }
        Console.WriteLine(string.Format(IC, "packets from the MCU: {0}, CRC errors {1}; PRED {2} (expected {3})", dec.Ok, dec.CrcErrors, predCls.Count, labels.Count));
        if (predCls.Count != labels.Count) { Console.WriteLine("FAIL: PRED count differs"); return 3; }
        for (int b = 0; b <= blocks[blocks.Count - 1]; b++) {
            int n = 0, ok = 0;
            for (int k = 0; k < labels.Count; k++) if (blocks[k] == b) { n++; if (predCls[k] == labels[k]) ok++; }
            Console.WriteLine(string.Format(IC, "block {0}: accuracy {1:F2}% ({2}/{3})", b, 100.0 * ok / n, ok, n));
        }
        return 0;
    }
}
