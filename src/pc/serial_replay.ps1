# Real-time replay of a packet stream to the MCU (route B) with Windows' own System.IO.Ports (no pyserial needed).
# Input (from src/board_replay.py make): <dir>/stream.bin, <dir>/schedule.csv (end byte offset, send time in s).
# Sends every packet at its time (one Stopwatch for sending and receiving), reads everything the MCU sends back,
# keeps reading for -TailS seconds after the last packet. Writes <dir>/rx.bin, rx_log.csv (bytes received so far,
# ms) and tx_log.csv (packet index, ms when it was written).
# Usage: powershell -ExecutionPolicy Bypass -File serial_replay.ps1 -Dir <dir> -Port COM6 [-Baud 921600] [-TailS 5]
param([Parameter(Mandatory = $true)][string]$Dir, [string]$Port = 'COM6', [int]$Baud = 921600, [double]$TailS = 5)

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Ports;
using System.Threading;

public static class SerialReplay {
    public static string Run(string dir, string port, int baud, double tailS) {
        byte[] stream = File.ReadAllBytes(Path.Combine(dir, "stream.bin"));
        var ends = new List<int>(); var times = new List<double>();
        foreach (var line in File.ReadAllLines(Path.Combine(dir, "schedule.csv"))) {
            if (line.StartsWith("end")) continue;
            var f = line.Split(',');
            ends.Add(int.Parse(f[0], CultureInfo.InvariantCulture));
            times.Add(double.Parse(f[1], CultureInfo.InvariantCulture));
        }
        var rx = new MemoryStream(); var rxLog = new List<string>(); var txLog = new List<string>();
        var buf = new byte[65536];
        using (var sp = new SerialPort(port, baud, Parity.None, 8, StopBits.One)) {
            sp.ReadTimeout = 1; sp.WriteTimeout = 2000; sp.ReadBufferSize = 1 << 20; sp.WriteBufferSize = 1 << 16;
            sp.Open(); sp.DiscardInBuffer();
            var sw = Stopwatch.StartNew();
            int start = 0, i = 0;
            double endT = times[times.Count - 1] + tailS;
            while (sw.Elapsed.TotalSeconds < endT) {
                double now = sw.Elapsed.TotalSeconds;
                while (i < ends.Count && times[i] <= now) {
                    sp.Write(stream, start, ends[i] - start);
                    txLog.Add(i.ToString() + "," + sw.Elapsed.TotalMilliseconds.ToString("F3", CultureInfo.InvariantCulture));
                    start = ends[i]; i++;
                }
                int n = sp.BytesToRead;
                if (n > 0) {
                    int got = sp.Read(buf, 0, Math.Min(n, buf.Length));
                    rx.Write(buf, 0, got);
                    rxLog.Add(rx.Length.ToString() + "," + sw.Elapsed.TotalMilliseconds.ToString("F3", CultureInfo.InvariantCulture));
                } else {
                    Thread.Sleep(0);
                }
            }
        }
        File.WriteAllBytes(Path.Combine(dir, "rx.bin"), rx.ToArray());
        File.WriteAllLines(Path.Combine(dir, "rx_log.csv"), new[] { "end,ms" });
        File.AppendAllLines(Path.Combine(dir, "rx_log.csv"), rxLog);
        File.WriteAllLines(Path.Combine(dir, "tx_log.csv"), new[] { "packet,ms" });
        File.AppendAllLines(Path.Combine(dir, "tx_log.csv"), txLog);
        return string.Format("sent {0} packets ({1} bytes), received {2} bytes", ends.Count, stream.Length, rx.Length);
    }
}
'@

[SerialReplay]::Run($Dir, $Port, $Baud, $TailS)
