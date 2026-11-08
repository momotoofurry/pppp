// Route B on the lab PC without installing anything: one .exe built with the C# compiler that ships with Windows
// (.NET Framework 4: C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe), C# 5. Same protocol as
// src/pc/protocol.py and src/c/protocol.h; same TCU handling as src/pc/trigno_bridge.py (to be verified on the lab PC).
//
//   TrignoBridge probe  [--tcu 127.0.0.1] [--out tcu_probe.txt]
//       TCU only, before the first session: the banner, the answers to read-only queries (BACKWARDS COMPATIBILITY?,
//       UPSAMPLING?, SENSOR n PAIRED? / TYPE? / MODE?; an unknown query just gets the TCU's error reply) and, for 3 s of
//       START, the bytes per second on the data ports 50041-50044. Changes no TCU setting. Everything also -> --out.
//   TrignoBridge verify --name T00_d1 [--dir .] [--rate 2000 = the --rate run.bat had]
//       after a session: <name>_emg.csv (frames, minutes, rate, pauses > 0.2 s, silent channels), <name>_mcu.csv
//       (predictions, commands, calibrate / load results, packets lost after the start, UART drops), <name>_ops.csv
//       (typed commands, notes) and <name>_*_task.csv; exit code 0 = complete, 3 = warnings.
//   TrignoBridge check  [--tcu 127.0.0.1] [--seconds 60] [--out emg_check.csv]
//       TCU only (no STM32): START, record, then the measured sample rate (frames / time) and per channel the
//       largest |value| and the RMS; warns when a channel comes near the +-8.19 mV the MCU encoding can carry.
//   TrignoBridge run    --port COM5 [--tcu 127.0.0.1] [--rate 2000] [--emg-csv emg.csv] [--mcu-csv mcu.csv]
//                       [--ops-csv ops.csv] [--udp 50555] [--gate 1] [--script commands.txt]
//                       (--port file:<path>: write the serial bytes to a file; --udp 0: no forwarding;
//                        --udp 50555,50556: forward to TaskScreen and to src/pc/kinova_bridge.py)
//       TCU -> (resampled to 2000 Hz when --rate is not 2000) -> int16 0.25 uV -> packets -> COM port at 921600;
//       MCU packets -> mcu.csv and the console; COMMAND / STATUS packets also -> UDP 127.0.0.1:<udp> for
//       TaskScreen.exe; every typed command -> ops.csv. All three CSVs carry Unix time in ms (unix_ms).
//       Commands typed while running:
//         reset | cal <0-5> | calend | calibrate | align | decision <tau_permille> <k> | report <0|1> | status | quit
//       cal <g> = reset + CAL_START; CAL_END follows by itself after 2 s of samples (10 windows per gesture).
//       adapt 0|1 = study condition: 0 fixed day-1 model (no adaptation, no alignment), 1 full system (default);
//       start every condition with 'load' so that both begin from the same day-1 model (PROTOCOL.md).
//       load = restore the day-1 model from the board's Flash (after the board was off, e.g. on day 2; the
//       board answers 'day-1 model loaded (calibration rows)', a negative value = no valid model: calibrate).
//       verify <g> = reset, then the next 10 predictions are scored against gesture g (needs report 1); after all
//       6 gestures: PASS if >= 70 % of the 60 windows are right, else redo the calibration (report 22).
//       align = reset + ALIGN_START; ALIGN_END follows by itself after 8 s (70 windows; the MCU needs >= 60 and
//       several gestures, report 20): start-up alignment after the sensors were put on again.
//       --script: lines "<seconds> <command>" run at those times after START (for tests).
//       Alignment gate (--gate 1, default; PROTOCOL.md 3.1): after 'load' / 'calibrate' / 'adapt 1' the board's
//       commands are written to mcu.csv but NOT forwarded to TaskScreen / the robot until an 'align' ends with a
//       usable rotation. 'alignment too short' always asks for a new 'align'; 'alignment unsure' asks once to check
//       the strap mark and redo 'align'; on the second unsure in a row the gate opens with rotation 0 (the
//       firmware's choice). 'adapt 0' (fixed model) opens the gate. Held commands reach TaskScreen as a status line.
//       note <text> = free-text note in ops.csv (room / skin temperature, strap offset, ...).
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
                      ALIGN_START = 7, ALIGN_END = 8, LOAD = 9, SET_ADAPT = 10;
    public const int CH = 8, FRAMES_PER_PACKET = 20, MAX_PAYLOAD = 512, OVERHEAD = 9;
    public const double LSB_VOLT = 2.5e-7;
    public static readonly string[] GESTURES = { "Power", "Lateral", "Tripod", "Pointer", "Open", "Rest" };
    public static readonly string[] COMMANDS = { "none", "pose_A", "grip", "pose_B", "release", "home" };   // 5 = home: Lateral, pilot-freeze-5
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
        if (sub == CAL_START || sub == SET_REPORT || sub == SET_ADAPT) return Build(CONTROL, new byte[] { sub, (byte)args[0] });
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

    public Tcu(string host) : this(host, 0) { }

    // dataTimeoutMs > 0: Read() throws when the EMG port sends nothing for that long (check: no endless wait when the
    // TCU streams elsewhere); run keeps the blocking read so that a short stall never ends a recording
    public Tcu(string host, int dataTimeoutMs)
    {
        cmd = new TcpClient(host, 50040);
        emg = new TcpClient(host, 50041);
        cs = cmd.GetStream(); es = emg.GetStream();
        cs.ReadTimeout = 10000;
        if (dataTimeoutMs > 0) es.ReadTimeout = dataTimeoutMs;
        Banner = Reply();
        // Byte order (Delsys Trigno SDK samples, 2026-11-08): the C# sample reverses every float on a little-endian
        // PC, so the server's default is big-endian; the Linux sample sends "ENDIAN LITTLE" first. Ask for little
        // endian, then read it back; if the server still says BIG (or did not take the command and answers BIG),
        // swap the bytes of every float.
        EndianReply = Command("ENDIAN LITTLE");
        Endianness = Command("ENDIANNESS?");
        Swap = Endianness.ToUpperInvariant().Contains("BIG");
        Rate = Command("RATE?");
    }

    public string EndianReply, Endianness, Rate;
    public bool Swap;

    public string Describe()
    {
        return "ENDIAN LITTLE -> " + EndianReply + "; ENDIANNESS? -> " + Endianness + (Swap ? " (swapping bytes)" : "")
               + "; RATE? -> " + Rate;
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
            for (int c = 0; c < CHANNELS; c++) {
                int o = i * fb + c * 4;
                if (Swap) { byte t = all[o]; all[o] = all[o + 3]; all[o + 3] = t; t = all[o + 1]; all[o + 1] = all[o + 2]; all[o + 2] = t; }
                f[c] = BitConverter.ToSingle(all, o);
            }
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
        if (argv.Length < 1) { Console.WriteLine("usage: TrignoBridge probe|check|run|verify|replay [options] (see the top of TrignoBridge.cs)"); return 1; }
        var a = Args(argv, 1);
        try {
            if (argv[0] == "probe") return Probe(a);
            if (argv[0] == "verify") return Verify(a);
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

    // ------------------------------------------------------------------ probe: what the TCU answers (read-only)
    static string ReplyOf(NetworkStream s)
    {
        var sb = new StringBuilder();
        var b = new byte[1024];
        try {
            while (!sb.ToString().EndsWith("\r\n\r\n")) {
                int n = s.Read(b, 0, b.Length);
                if (n <= 0) break;
                sb.Append(Encoding.ASCII.GetString(b, 0, n));
            }
        } catch (IOException) { return sb.Length > 0 ? sb.ToString().Trim() + " (incomplete)" : "(no reply in 3 s)"; }
        return sb.ToString().Trim().Replace("\r\n", " | ");
    }

    static string Ask(NetworkStream s, string text)
    {
        var b = Encoding.ASCII.GetBytes(text + "\r\n\r\n");
        s.Write(b, 0, b.Length);
        return ReplyOf(s);
    }

    static int Probe(Dictionary<string, string> a)
    {
        string host = Get(a, "tcu", "127.0.0.1");
        string outPath = Get(a, "out", "tcu_probe.txt");
        var log = new StringBuilder();
        Action<string> say = s => { Console.WriteLine(s); log.AppendLine(s); };
        say("TrignoBridge probe " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", IC) + ", TCU host " + host);
        say("(only questions ending in '?' plus START / STOP: no TCU setting is changed)");
        TcpClient cmd;
        try { cmd = new TcpClient(host, 50040); }
        catch (Exception e) {
            say("cannot connect to " + host + ":50040 (" + e.Message + ")");
            say("-> is the Trigno Control Utility open (not only EMGworks / Trigno Discover)? on another PC: firewall for 50040-50044?");
            File.WriteAllText(outPath, log.ToString());
            return 2;
        }
        var cs = cmd.GetStream();
        cs.ReadTimeout = 3000;
        int[] ports = { 50041, 50042, 50043, 50044 };              // connected before the banner, as TrignoBridge does
        var cl = new TcpClient[ports.Length];
        for (int i = 0; i < ports.Length; i++) {
            try { cl[i] = new TcpClient(host, ports[i]); }
            catch (Exception e) { say(string.Format(IC, "  port {0}: no connection ({1})", ports[i], e.Message)); }
        }
        say("banner: " + ReplyOf(cs));
        var q = new List<string> { "VERSION?", "RATE?", "ENDIANNESS?", "BACKWARDS COMPATIBILITY?", "UPSAMPLING?",
                                   "UPSAMPLE?", "FRAME INTERVAL?", "MAX SAMPLES EMG?", "MAX SAMPLES AUX?", "TRIGGER?" };
        for (int s = 1; s <= 8; s++) { q.Add("SENSOR " + s + " PAIRED?"); q.Add("SENSOR " + s + " TYPE?"); q.Add("SENSOR " + s + " MODE?"); }
        foreach (var x in q) say(string.Format(IC, "  {0,-26} -> {1}", x, Ask(cs, x)));
        say("START -> " + Ask(cs, "START"));
        var counts = new long[ports.Length];
        var firstT = new double[ports.Length];                    // rate from each port's first data on (as check)
        for (int i = 0; i < ports.Length; i++) firstT[i] = -1;
        var buf = new byte[1 << 16];
        var sw = Stopwatch.StartNew();
        while (sw.Elapsed.TotalSeconds < 6) {
            for (int i = 0; i < ports.Length; i++) {
                if (cl[i] == null) continue;
                var st = cl[i].GetStream();
                while (st.DataAvailable) {
                    int n = st.Read(buf, 0, buf.Length);
                    if (n <= 0) break;
                    if (firstT[i] < 0) { firstT[i] = sw.Elapsed.TotalSeconds; continue; }   // first chunk starts the clock
                    counts[i] += n;
                }
            }
            Thread.Sleep(5);
        }
        double end = sw.Elapsed.TotalSeconds;
        say("STOP -> " + Ask(cs, "STOP"));
        say("data during 6 s of START (TrignoBridge reads 50041: 16 float32 channels, 2000 Hz = 128000 bytes/s):");
        var fps = new double[ports.Length];
        for (int i = 0; i < ports.Length; i++) {
            if (cl[i] == null) continue;
            double el = firstT[i] < 0 ? 0 : end - firstT[i];
            double bps = el > 0.5 ? counts[i] / el : 0;
            fps[i] = bps / 64;
            say(string.Format(IC, "  port {0}: {1,9:F0} bytes/s = {2,7:F1} frames/s if 16 float channels", ports[i], bps, fps[i]));
            cl[i].Close();
        }
        cmd.Close();
        if (fps[0] == 0) say("-> nothing on 50041: TrignoBridge would get no EMG. Bring " + outPath + " back (data may be on 50043).");
        else if (Math.Abs(fps[0] - 2000) > 40) say("-> 50041 is not 2000 Hz: confirm with check.bat (60 s), then run.bat ... --rate <its measured rate>.");
        else say("-> 50041 streams about 2000 Hz: as TrignoBridge expects (check.bat confirms over 60 s).");
        File.WriteAllText(outPath, log.ToString());
        Console.WriteLine("saved " + outPath);
        return 0;
    }

    // ------------------------------------------------------------------ verify: are one session's files complete?
    static int Verify(Dictionary<string, string> a)
    {
        string name = Get(a, "name", "");
        string dir = Get(a, "dir", ".");
        if (name.Length == 0) { Console.WriteLine("usage: TrignoBridge verify --name T00_d1 [--dir .]"); return 1; }
        int warn = 0;
        Action<string> W = s => { Console.WriteLine("  WARNING: " + s); warn++; };
        Console.WriteLine("files of " + name + " in " + Path.GetFullPath(dir));

        string emgPath = Path.Combine(dir, name + "_emg.csv");
        if (!File.Exists(emgPath)) W("missing " + emgPath);
        else {
            long rows = 0, bad = 0, gaps = 0;
            double first = double.NaN, last = double.NaN, maxGap = 0;
            var maxAbs = new double[Proto.CH];
            using (var r = new StreamReader(emgPath)) {
                r.ReadLine();
                string l;
                while ((l = r.ReadLine()) != null) {
                    var f = l.Split(',');
                    double ms;
                    if (f.Length < 2 + Proto.CH || !double.TryParse(f[0], NumberStyles.Float, IC, out ms)) { bad++; continue; }
                    if (double.IsNaN(first)) first = ms;
                    else if (ms - last > 200) { gaps++; maxGap = Math.Max(maxGap, ms - last); }
                    last = ms;
                    for (int c = 0; c < Proto.CH; c++) {
                        double v;
                        if (double.TryParse(f[2 + c], NumberStyles.Float, IC, out v)) maxAbs[c] = Math.Max(maxAbs[c], Math.Abs(v));
                    }
                    rows++;
                }
            }
            double dur = rows > 1 ? (last - first) / 1000 : 0;
            Console.WriteLine(string.Format(IC, "  emg: {0} frames, {1:F1} min, {2:F1} Hz", rows, dur / 60, dur > 0 ? rows / dur : 0));
            if (rows == 0) W("emg.csv has no data");
            if (bad > 0) W(bad + " unreadable lines in emg.csv");
            double expect = double.Parse(Get(a, "rate", "2000"), IC);   // emg.csv keeps the TCU's own frames
            if (dur > 60 && Math.Abs(rows / dur - expect) > 0.02 * expect)
                W(string.Format(IC, "EMG rate {0:F1} Hz, expected {1:F0} (if run.bat had --rate {0:F0}: verify.bat {2} --rate {0:F0})",
                                rows / dur, expect, name));
            if (gaps > 0) W(string.Format(IC, "{0} pauses > 0.2 s in the EMG stream (longest {1:F1} s)", gaps, maxGap / 1000));
            for (int c = 0; c < Proto.CH; c++) {
                if (maxAbs[c] == 0) W("channel " + (c + 1) + " has no signal");
                else if (maxAbs[c] > 0.8 * CLIP_V) Console.WriteLine(string.Format(IC, "  note: channel {0} reached {1:F2} mV (MCU limit 8.19 mV)", c + 1, maxAbs[c] * 1e3));
            }
        }

        string mcuPath = Path.Combine(dir, name + "_mcu.csv");
        if (!File.Exists(mcuPath)) W("missing " + mcuPath);
        else {
            long preds = 0, cmds = 0, lostAfterStart = 0, dropped = 0, scBlocks = -1, scSkipped = 0, aligns = 0;
            var calibrated = new List<string>(); var loaded = new List<string>();
            using (var r = new StreamReader(mcuPath)) {
                r.ReadLine();
                string l;
                while ((l = r.ReadLine()) != null) {
                    var f = l.Split(',');
                    if (f.Length < 3) continue;
                    if (f[1] == "pred") { preds++; continue; }
                    if (f[1] == "command") { cmds++; continue; }
                    if (f[1] != "status" || f.Length < 11) continue;
                    string ev = string.Join(",", f, 9, f.Length - 10);
                    string val = f[f.Length - 1];
                    long v; long.TryParse(val, NumberStyles.Integer, IC, out v);
                    if (ev == "packets lost" && preds > 0) lostAfterStart += v;
                    else if (ev == "UART bytes dropped") dropped += v;
                    else if (ev == "self-calibration blocks") scBlocks = v;
                    else if (ev.StartsWith("self-calibration skipped")) scSkipped++;
                    else if (ev == "rotation" || ev.StartsWith("alignment")) aligns++;
                    else if (ev.StartsWith("calibrated")) calibrated.Add(val);
                    else if (ev.StartsWith("day-1 model loaded")) loaded.Add(val);
                }
            }
            Console.WriteLine(string.Format(IC, "  mcu: {0} predictions, {1} commands, {2} alignment results, self-calibration blocks {3}, skipped {4}",
                                            preds, cmds, aligns, scBlocks < 0 ? "-" : scBlocks.ToString(IC), scSkipped));
            Console.WriteLine("  calibrate results (0 = ok): " + (calibrated.Count > 0 ? string.Join(" ", calibrated) : "-")
                              + "   load results (rows, < 0 = none): " + (loaded.Count > 0 ? string.Join(" ", loaded) : "-"));
            if (preds == 0) W("no predictions from the board (report 1 not sent, or the board did not run)");
            if (lostAfterStart > 0) W(lostAfterStart + " packets lost while running (the count before the first prediction is a restart, not loss)");
            if (dropped > 0) W(dropped + " UART bytes dropped by the board");
            foreach (var x in loaded) if (x.StartsWith("-")) W("a 'load' found no day-1 model (" + x + ")");
        }

        string opsPath = Path.Combine(dir, name + "_ops.csv");
        if (!File.Exists(opsPath)) W("missing " + opsPath);
        else {
            var n = new SortedDictionary<string, int>();
            int notes = 0;
            using (var r = new StreamReader(opsPath)) {
                r.ReadLine();
                string l;
                while ((l = r.ReadLine()) != null) {
                    int i = l.IndexOf(',');
                    if (i < 0) continue;
                    string c = l.Substring(i + 1).TrimStart('"');
                    string w0 = c.Split(' ', ',')[0];
                    if (w0 == "note") { notes++; continue; }
                    n[w0] = n.ContainsKey(w0) ? n[w0] + 1 : 1;
                }
            }
            var parts = new List<string>();
            foreach (var kv in n) parts.Add(kv.Key + " " + kv.Value);
            Console.WriteLine("  ops: " + string.Join(", ", parts) + "; notes " + notes);
            if (notes == 0) W("no 'note' lines: were the temperatures typed in (note temp room .. skin ..)?");
        }

        var tasks = Directory.GetFiles(dir, name + "_*_task.csv");
        if (tasks.Length == 0) W("no " + name + "_*_task.csv from TaskScreen");
        foreach (var t in tasks) {
            long rows = 0;
            using (var r = new StreamReader(t)) { while (r.ReadLine() != null) rows++; }
            Console.WriteLine(string.Format(IC, "  task: {0} ({1} lines)", Path.GetFileName(t), rows));
            if (rows <= 1) W(Path.GetFileName(t) + " is empty");
        }
        if (!File.Exists(Path.Combine(dir, name + "_emg_check.csv"))) Console.WriteLine("  note: no " + name + "_emg_check.csv (rename emg_check.csv after check.bat)");

        Console.WriteLine(warn == 0 ? "OK: all files are there. Copy them to the USB stick now." :
                          warn + " warning(s): write them on the paper record (note) and bring this screen back.");
        return warn == 0 ? 0 : 3;
    }

    // ------------------------------------------------------------------ check: TCU only
    static int Check(Dictionary<string, string> a)
    {
        double seconds = double.Parse(Get(a, "seconds", "60"), IC);
        string outPath = Get(a, "out", "emg_check.csv");
        var tcu = new Tcu(Get(a, "tcu", "127.0.0.1"), 10000);
        Console.WriteLine("TCU banner: " + tcu.Banner);
        Console.WriteLine("TCU: " + tcu.Describe());
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
        // surface EMG in volts stays far below 0.1 V; NaN or huge values mean the bytes are read in the wrong order
        bool absurd = false;
        for (int c = 0; c < Tcu.CHANNELS; c++) if (double.IsNaN(max[c]) || double.IsInfinity(max[c]) || max[c] > 0.1) absurd = true;
        if (absurd)
            Console.WriteLine("WARNING: values are not plausible EMG volts (NaN or > 100 mV): probably the byte order. "
                              + "Bring this screen and " + outPath + " back (TCU said: " + tcu.Endianness + ").");
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
    static StreamWriter mcuCsv, opsCsv;
    static Stopwatch clock = Stopwatch.StartNew();
    // one clock for every file of a session (PROTOCOL.md section 8): Unix time in ms, read once and then advanced
    // by the Stopwatch so it never jumps (TaskScreen.exe uses the same rule)
    static readonly double epochMs = (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalMilliseconds
                                     - clock.Elapsed.TotalMilliseconds;
    static double UnixMs() { return epochMs + clock.Elapsed.TotalMilliseconds; }
    // COMMAND and STATUS packets also go to TaskScreen.exe as UDP datagrams "<unix_ms>,<mcu.csv line>" (localhost)
    static UdpClient udp;
    static int[] udpPorts = new int[0];                           // --udp 50555,50556: TaskScreen and kinova_bridge.py

    static void OpenUdp(string arg)
    {
        var l = new List<int>();
        foreach (var x in arg.Split(',')) { int v = int.Parse(x.Trim()); if (v > 0) l.Add(v); }
        udpPorts = l.ToArray();
        if (udpPorts.Length > 0) udp = new UdpClient();
    }

    static void Forward(double ms, string line)
    {
        if (udp == null) return;
        var b = Encoding.ASCII.GetBytes(ms.ToString("F1", IC) + "," + line);
        foreach (int up in udpPorts)
            try { udp.Send(b, b.Length, "127.0.0.1", up); } catch (SocketException) { }   // nobody listening: fine
    }
    static int mcuPackets, preds;
    // alignment gate: commands reach TaskScreen / the robot only after a usable start-up alignment
    static bool gateOn = true;
    static volatile bool gateOpen = true, adaptOn = true;
    static int unsureInRow, heldCommands;
    // the board ignores ALIGN_START while it is busy (e.g. still building the model after 'calibrate'): when an
    // 'align' gets no answer within ANSWER_FRAMES after its ALIGN_END, say so
    const long ANSWER_FRAMES = 2000;
    static long alignAnswerDue = -1;

    static void Gate(bool open, string why)
    {
        bool was = gateOpen;
        gateOpen = open || !gateOn;
        if (gateOn && was != gateOpen)
            Console.WriteLine(string.Format(IC, "[{0:F1} s] {1}", clock.Elapsed.TotalSeconds,
                                            gateOpen ? "commands forwarded again (" + why + ")"
                                                     : "commands held until a good 'align' (" + why + ")"));
    }

    static void NeedAlign(string why) { unsureInRow = 0; if (adaptOn) Gate(false, why); }

    // board status -> gate (event numbers of rt.h)
    static void GateStatus(int ev, int v)
    {
        if (ev == 5 || ev == 6 || ev == 15) alignAnswerDue = -1;
        if (ev == 6) {                                            // RT_EV_ALIGN_SHORT
            Gate(false, "alignment too short");
            Console.WriteLine("  >>> 對齊太短（" + v + " 個視窗）：請再打 align，8 秒內依序做 6 個手勢 <<<");
        } else if (ev == 15) {                                    // RT_EV_ALIGN_UNSURE, sent before RT_EV_ALIGNED 0
            unsureInRow++;
            if (unsureInRow == 1) {
                Gate(false, "alignment unsure");
                Console.WriteLine("  >>> 對齊沒把握（估到 " + v + "）：檢查束帶記號（偏差 > 15 mm 就重戴），再打一次 align <<<");
            } else
                Console.WriteLine("  >>> 連續第 " + unsureInRow + " 次沒把握：照韌體規則用 rotation 0 繼續，記在配戴紀錄 <<<");
        } else if (ev == 5) {                                     // RT_EV_ALIGNED
            if (unsureInRow != 1) { Gate(true, "aligned, rotation " + v); unsureInRow = 0; }
        } else if (ev == 14 && v > 0)                             // RT_EV_LOADED: a condition starts from the day-1 model
            NeedAlign("day-1 model loaded");
        else if (ev == 1 && v == 0)                               // RT_EV_CALIBRATED, ok
            NeedAlign("calibrated");
    }
    // day-1 calibration check (report 22): 10 predictions per gesture, pass at >= 70 % of the 60
    const int VERIFY_WINDOWS = 10, VERIFY_PASS_PCT = 70;
    static int verifyG = -1, verifyLeft;
    static readonly int[] vOk = new int[6], vN = new int[6];
    static readonly object vLock = new object();

    static void VerifyPred(int cls)
    {
        lock (vLock) {
            if (verifyG < 0 || verifyLeft <= 0) return;
            vN[verifyG]++;
            if (cls == verifyG) vOk[verifyG]++;
            if (--verifyLeft > 0) return;
            Console.WriteLine(string.Format(IC, "[{0:F1} s] verify {1} ({2}): {3}/{4} right; you can relax",
                                            clock.Elapsed.TotalSeconds, verifyG, Proto.GESTURES[verifyG], vOk[verifyG], vN[verifyG]));
            verifyG = -1;
            int ok = 0, n = 0, done = 0;
            for (int g = 0; g < 6; g++) { ok += vOk[g]; n += vN[g]; done += vN[g] > 0 ? 1 : 0; }
            if (done == 6)
                Console.WriteLine(string.Format(IC, "verify total: {0}/{1} = {2:F0} % -> {3}", ok, n, 100.0 * ok / n,
                                                100 * ok >= VERIFY_PASS_PCT * n ? "PASS" : "FAIL: redo the calibration (cal 0-5, calibrate)"));
        }
    }
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
            alignAnswerDue = -1;
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
        double ms = UnixMs();
        bool ok = DoCommand1(line);
        if (opsCsv != null && line.Trim().Length > 0)
            lock (opsCsv) { opsCsv.WriteLine(ms.ToString("F1", IC) + "," + line.Trim().Replace(',', ' ') + "," + (ok ? 1 : 0)); opsCsv.Flush(); }
        return ok;
    }

    static bool DoCommand1(string line)
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
        else if (c == "verify" && p.Length == 2) {
            int g = int.Parse(p[1]);
            if (g < 0 || g > 5) { Console.WriteLine("gesture 0-5: 0 Power, 1 Lateral, 2 Tripod, 3 Pointer, 4 Open, 5 Rest"); return false; }
            lock (vLock) { vOk[g] = 0; vN[g] = 0; verifyG = g; verifyLeft = VERIFY_WINDOWS; }
            Send(Proto.Control(Proto.STREAM_RESET));
            Console.WriteLine(string.Format(IC, "[{0:F1} s] verify {1} ({2}): do the gesture now and hold it (about 2 s)",
                                            clock.Elapsed.TotalSeconds, g, Proto.GESTURES[g]));
            return true;
        }
        else if (c == "align") {
            StartAuto(Proto.ALIGN_START, -1, Proto.ALIGN_END, ALIGN_FRAMES, "alignend (auto, 8 s): the MCU answers with 'rotation'");
            Console.WriteLine(string.Format(IC, "[{0:F1} s] align: for 8 s do each gesture about 1 s: Power, Lateral, Tripod, Pointer, Open, Rest",
                                            clock.Elapsed.TotalSeconds));
            return true;
        }
        else if (c == "calibrate") Send(Proto.Control(Proto.CALIBRATE));
        else if (c == "load") Send(Proto.Control(Proto.LOAD));
        else if (c == "adapt" && p.Length == 2 && (p[1] == "0" || p[1] == "1")) {
            Send(Proto.Control(Proto.SET_ADAPT, int.Parse(p[1])));
            adaptOn = p[1] == "1";
            if (adaptOn) NeedAlign("adapt 1"); else Gate(true, "adapt 0: fixed model, no alignment");
        }
        else if (c == "note" && p.Length >= 2) { Console.WriteLine("  note saved in ops.csv"); return true; }
        else if (c == "decision" && p.Length == 3) Send(Proto.Control(Proto.SET_DECISION, int.Parse(p[1]), int.Parse(p[2])));
        else if (c == "report" && p.Length == 2) Send(Proto.Control(Proto.SET_REPORT, int.Parse(p[1])));
        else if (c == "status") return true;
        else { Console.WriteLine("? reset | cal <0-5> | calend | calibrate | load | adapt <0|1> | verify <0-5> | align | decision <tau_permille> <k> | report <0|1> | note <text> | status | quit"); return false; }
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
                double ms = UnixMs();
                lock (mcuCsv) mcuCsv.WriteLine(ms.ToString("F1", IC) + "," + line);
                if (pk.Key == Proto.PRED) { preds++; if (pk.Value.Length >= 13) VerifyPred(pk.Value[8]); }
                else {
                    if (pk.Key == Proto.COMMAND && !gateOpen) {
                        heldCommands++;
                        Forward(ms, string.Format(IC, "status,,,,,,,,command held before alignment ({0}),{1}",
                                                  line.Split(',')[4], BitConverter.ToUInt32(pk.Value, 0)));
                        Console.WriteLine(string.Format(IC, "[{0:F1} s] MCU: {1}  (HELD: no good alignment yet)",
                                                        clock.Elapsed.TotalSeconds, line));
                        continue;
                    }
                    Forward(ms, line);
                    Console.WriteLine(string.Format(IC, "[{0:F1} s] MCU: {1}", clock.Elapsed.TotalSeconds, line));
                    if (pk.Key == Proto.STATUS && pk.Value.Length >= 8) GateStatus(pk.Value[0], BitConverter.ToInt32(pk.Value, 4));
                    if (pk.Key == Proto.STATUS && pk.Value.Length >= 8 && pk.Value[0] == 3 && preds == 0)
                        Console.WriteLine("  (packets lost before the first PRED of this run: the board was not reset since the last run and"
                                          + " counts the restart of the packet numbers; not data loss. PROTOCOL 10)");
                }
            }
        }
    }

    // csv columns: kind,window,t_us,gesture,command,accepted,ratio,pushed,event,value
    static string Describe(byte type, byte[] p)
    {
        if (type == Proto.COMMAND && p.Length >= 12) {
            int cmd = p[8], cls = p[9];
            return string.Format(IC, "command,{0},{1},{2},{3},,{4:F3},,,", BitConverter.ToUInt32(p, 0), BitConverter.ToUInt32(p, 4),
                                 cls < 6 ? Proto.GESTURES[cls] : cls.ToString(), cmd < Proto.COMMANDS.Length ? Proto.COMMANDS[cmd] : cmd.ToString(),
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
                               "stack peak (bytes)", "UART bytes dropped", "UART errors",
                               "self-calibration skipped: too few gestures (classes)",
                               "day-1 model loaded (calibration rows; < 0 = none, calibrate)",
                               "alignment unsure, rotation kept 0 (rejected estimate); redo align if the strap moved" };
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
        Console.WriteLine("TCU: " + tcu.Describe());
        mcuCsv = new StreamWriter(Get(a, "mcu-csv", "mcu.csv"));
        mcuCsv.WriteLine("unix_ms,kind,window,t_us,gesture,command,accepted,ratio,pushed,event,value");
        opsCsv = new StreamWriter(Get(a, "ops-csv", "ops.csv"));
        opsCsv.WriteLine("unix_ms,command,accepted");
        OpenUdp(Get(a, "udp", "50555"));
        gateOn = Get(a, "gate", "1") != "0";
        Console.WriteLine(gateOn ? "alignment gate on: board commands are forwarded only after a good 'align' (--gate 0: off)"
                                 : "alignment gate off");
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
            Console.WriteLine("commands: reset | cal <0-5> | calend | calibrate | load | adapt <0|1> | verify <0-5> | align | decision <tau> <k> | report <0|1> | note <text> | status | quit");
        }

        Console.WriteLine("START -> " + tcu.Command("START"));
        double t0 = clock.Elapsed.TotalSeconds;
        int si = 0;
        long framesIn = 0, framesOut = 0, clipped = 0;
        var pending = new List<short[]>();
        double lastReport = 0;
        using (var emg = new StreamWriter(Get(a, "emg-csv", "emg.csv"))) {
            emg.WriteLine("unix_ms,frame," + string.Join(",", Enumerable(Proto.CH, "ch{0}_V")));
            while (!stop) {
                double now = clock.Elapsed.TotalSeconds - t0;
                while (si < script.Count && script[si].Key <= now) DoCommand(script[si++].Value);
                if (script.Count > 0 && si == script.Count) stop = true;
                var fr = tcu.Read();
                if (fr.Count == 0) break;
                double ms = UnixMs();
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
                            if (autoEnd == Proto.ALIGN_END) alignAnswerDue = framesSent + ANSWER_FRAMES;
                            Console.WriteLine(string.Format(IC, "[{0:F1} s] {1}", clock.Elapsed.TotalSeconds, autoMsg));
                        }
                        if (alignAnswerDue >= 0 && framesSent >= alignAnswerDue && port != null) {
                            alignAnswerDue = -1;
                            Console.WriteLine("  >>> 板子沒有回應這次 align（可能還在忙，例如 calibrate 後約 1 秒內）：請再打一次 align <<<");
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
        lock (opsCsv) opsCsv.Close();
        if (udp != null) udp.Close();
        Console.WriteLine(string.Format(IC, "done: {0} frames in, {1} out, {2} samples clipped, {3} MCU packets ({4} PRED), {5} commands held before alignment",
                                        framesIn, framesOut, clipped, mcuPackets, preds, heldCommands));
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
        var wl = File.ReadAllLines(Path.Combine(dir, "windows.csv"));
        var head = new List<string>(wl[0].Split(','));                // columns by name: newer files add test_block
        int iBlock = head.IndexOf("block"), iLabel = head.IndexOf("label");
        for (int k = 1; k < wl.Length; k++) {
            if (wl[k].Length == 0) continue;
            var f = wl[k].Split(',');
            blocks.Add(int.Parse(f[iBlock], IC)); labels.Add(int.Parse(f[iLabel], IC));
        }
        OpenUdp(Get(a, "udp", "50555"));                              // board commands -> TaskScreen.exe (end-to-end test)
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
                        else if (pk.Key == Proto.COMMAND) Forward(UnixMs(), Describe(pk.Key, pk.Value));
                        else if (pk.Key == Proto.STATUS) {
                            Forward(UnixMs(), Describe(pk.Key, pk.Value));
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
