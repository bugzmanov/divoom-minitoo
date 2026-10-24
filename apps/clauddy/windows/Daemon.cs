using System.IO.Pipes;
using System.Threading.Channels;
using DvWin;

namespace Clauddy;

/// <summary>
/// Holds the Bluetooth channel open and applies faces on request, like the macOS `dv start` daemon. Hooks talk
/// to it over a named pipe, so a switch costs one pipe write instead of a Bluetooth connection, and several
/// Claude sessions share one owner of the device (it accepts a single client).
///
/// Also carries the severity model of apps/clauddy/clauddy-hook.sh: chilling &lt; working &lt; alerting, a
/// higher face is held against downgrades for a short TTL, deferred downgrades re-check once the hold expires,
/// and a request for the face already showing costs nothing.
/// </summary>
public sealed class Daemon
{
    public const string PipeName = "clauddy-minitoo";
    private const int SettleMs = 1500; // the firmware drops commands sent right after the channel opens

    private readonly Config _config;
    private readonly Channel<string> _requests = Channel.CreateUnbounded<string>();
    private readonly object _sync = new();
    private readonly CancellationTokenSource _stop = new();
    private readonly double _alertHold = Hold("CLAUDDY_ALERT_HOLD", 5);
    private readonly double _workHold = Hold("CLAUDDY_WORK_HOLD", 2);
    private DivoomLink? _link;
    private string? _state;
    private DateTime _stateAt;

    public Daemon(Config config) => _config = config;

    private static double Hold(string variable, double fallback) =>
        double.TryParse(Environment.GetEnvironmentVariable(variable), out var v) && v >= 0 ? v : fallback;

    private static int Severity(string state) => Array.IndexOf(Config.States, state);

    public static void Log(string message)
    {
        try
        {
            Directory.CreateDirectory(Config.Dir);
            File.AppendAllText(Path.Combine(Config.Dir, "daemon.log"), $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {message}{Environment.NewLine}");
        }
        catch (IOException) { }
    }

    public async Task<int> RunAsync()
    {
        using var single = new Mutex(true, @"Local\clauddy-win-daemon", out var owned);
        if (!owned) return 0; // another daemon is already running

        var logFile = Path.Combine(Config.Dir, "daemon.log");
        try { if (File.Exists(logFile) && new FileInfo(logFile).Length > 256 * 1024) File.Delete(logFile); } catch (IOException) { }
        Log($"daemon started for {_config.Mac}");

        _ = Task.Run(ApplyLoop);
        try
        {
            while (!_stop.IsCancellationRequested)
            {
                var server = new NamedPipeServerStream(PipeName, PipeDirection.InOut, NamedPipeServerStream.MaxAllowedServerInstances,
                    PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                await server.WaitForConnectionAsync(_stop.Token);
                _ = Task.Run(() => HandleClient(server));
            }
        }
        catch (OperationCanceledException) { }
        _link?.Dispose();
        Log("daemon stopped");
        return 0;
    }

    private async Task HandleClient(NamedPipeServerStream pipe)
    {
        using (pipe)
        {
            try
            {
                using var reader = new StreamReader(pipe);
                using var writer = new StreamWriter(pipe) { AutoFlush = true };
                var line = (await reader.ReadLineAsync())?.Trim() ?? "";
                await writer.WriteLineAsync(Handle(line));
            }
            catch (IOException) { }
        }
    }

    private string Handle(string line)
    {
        var parts = line.Split(' ', 2, StringSplitOptions.RemoveEmptyEntries);
        switch (parts.FirstOrDefault())
        {
            case "ping": return "ok";
            case "status": return $"ok state={_state ?? "unknown"} connected={_link?.IsOpen == true}";
            case "quit": _stop.Cancel(); return "ok";
            case "set" or "hook" when parts.Length == 2 && Severity(parts[1]) >= 0:
                if (parts[0] == "set") Apply(parts[1]); else Hook(parts[1]);
                return "ok";
            default: return "error: unknown command";
        }
    }

    private void Apply(string state)
    {
        lock (_sync) { _state = state; _stateAt = DateTime.UtcNow; }
        _requests.Writer.TryWrite(state);
    }

    private void Hook(string state)
    {
        lock (_sync)
        {
            var now = DateTime.UtcNow;
            if (_state == state) { _stateAt = now; return; }

            if (_state != null && Severity(state) < Severity(_state))
            {
                double age = (now - _stateAt).TotalSeconds;
                double hold = _state == "alerting" ? _alertHold : _workHold;
                if (age < hold)
                {
                    _ = Task.Delay(TimeSpan.FromSeconds(hold - age + 1)).ContinueWith(_ => Hook(state));
                    return;
                }
            }
            _state = state;
            _stateAt = now;
        }
        _requests.Writer.TryWrite(state);
    }

    // One worker applies faces in order; if several piled up while the device was busy only the latest matters.
    private async Task ApplyLoop()
    {
        var reader = _requests.Reader;
        while (await reader.WaitToReadAsync())
        {
            string state = "";
            while (reader.TryRead(out var next)) state = next;
            if (state == "") continue;
            try { await SendFace(state); }
            catch (Exception e)
            {
                Log($"apply {state} failed: {e.Message}");
                lock (_sync) _state = null; // let the next request retry instead of assuming the face is showing
            }
        }
    }

    private async Task SendFace(string state)
    {
        if (!_config.Faces.TryGetValue(state, out var face)) throw new InvalidOperationException($"no face configured for {state}");
        var frame = Divoom.JsonFrame(FaceCommands.SelectClock(face.ClockId, _config.DeviceId));

        for (int attempt = 0; ; attempt++)
        {
            try
            {
                if (_link is not { IsOpen: true }) await Connect();
                await _link!.SendAsync(frame);
                Log($"face {state} (ClockId={face.ClockId})");
                return;
            }
            catch (DivoomLinkException) when (attempt == 0)
            {
                _link?.Dispose();
                _link = null; // channel dropped: reconnect once and resend
            }
        }
    }

    private async Task Connect()
    {
        _link = await DivoomLink.OpenReadyAsync(Divoom.ParseMac(_config.Mac), DivoomLink.Spp, SettleMs, log: Log);
        _link.Closed += () => Log("bluetooth channel closed");
        Log($"connected to {_link.DeviceName}");
    }
}
