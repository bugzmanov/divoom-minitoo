using System.Text;
using DvWin;

// Minimal Divoom BT protocol sender for Windows. Counterpart of core/divoom-send.swift (macOS).
//
// Usage:
//   dv-win list                                  paired Bluetooth devices, Divoom ones marked
//   dv-win [<MAC>] device-id                     the DeviceId the device reports (needed by upload-face)
//   dv-win [<MAC>] brightness <0-100>
//   dv-win [<MAC>] screen on|off
//   dv-win [<MAC>] face <id>
//   dv-win [<MAC>] clock
//   dv-win [<MAC>] select <ClockId> <DeviceId>   Channel/SetClockSelectId (what Clauddy uses)
//   dv-win [<MAC>] json '<body>' | json - | json @file
//   dv-win [<MAC>] raw <opcode> [args...]        hex bytes, e.g. "raw 32 32"
//   dv-win [<MAC>] rawfile <path> [delay_ms]     one `raw` line per frame, '#' starts a comment
//   dv-win [<MAC>] upload-face <gif> --page <0-2> [--device-id <id>] [--file-id <id>]
//                  [--quality 95] [--speed-ms <ms>] [--speed-scale <f>] [--clock-id <id> --style-id <id>]
//
// <MAC> may be omitted when DIVOOM_MAC is set. Options (anywhere before or after the command):
//   --listen <ms>   how long to wait for replies (default 1500, returns early once idle)
//   --delay <ms>    pause between frames (default 40)
//   --settle <ms>   pause after the channel opens (default 1500)
//   --uuid <guid>   SPP service to open (default 00001101-..., the standard SPP record)
//
// The device must already be paired in Windows Settings > Bluetooth & devices.

var options = new Dictionary<string, string>();
var rest = new List<string>();
string? mac = Environment.GetEnvironmentVariable("DIVOOM_MAC");
string[] valueOptions = ["listen", "delay", "settle", "uuid", "page", "device-id", "file-id", "quality", "speed-ms", "speed-scale", "clock-id", "style-id"];

for (int i = 0; i < args.Length; i++)
{
    if (args[i].StartsWith("--") && valueOptions.Contains(args[i][2..]) && i + 1 < args.Length) options[args[i][2..]] = args[++i];
    else if (args[i].StartsWith("--")) return Usage();
    else rest.Add(args[i]);
}

int Int(string key, int fallback) => options.TryGetValue(key, out var v) && int.TryParse(v, out var n) ? n : fallback;

int listenMs = Int("listen", 1500);
int delayMs = Int("delay", 40);
int settleMs = Int("settle", 1500);
var service = options.TryGetValue("uuid", out var u) ? Guid.Parse(u) : DivoomLink.Spp;

if (rest.Count > 0 && rest[0] == "list") return await ListPaired();
if (rest.Count > 0 && Divoom.LooksLikeMac(rest[0])) { mac = rest[0]; rest.RemoveAt(0); }
if (rest.Count == 0 || mac == null || !Divoom.LooksLikeMac(mac)) return Usage();

try
{
    return rest[0] switch
    {
        "device-id" => await RunDeviceId(),
        "upload-face" => await RunUploadFace(rest.Skip(1).ToList()),
        _ => BuildFrames(rest[0], rest.Skip(1).ToList()) is { } frames ? await RunFrames(frames) : Usage(),
    };
}
catch (DivoomLinkException e)
{
    Console.Error.WriteLine("error: " + e.Message);
    return e.ExitCode;
}

// ---------------------------------------------------------------- commands

List<byte[]>? BuildFrames(string command, List<string> a)
{
    switch (command)
    {
        case "brightness":
            // Minitoo uses the legacy opcode 0x32; 0x74 is invisible on it (FINDINGS.md section 4).
            return a.Count == 1 && byte.TryParse(a[0], out var pct) && pct <= 100
                ? [Divoom.Frame(0x32, [pct])] : null;
        case "screen":
            return a.Count == 1 && (a[0] == "on" || a[0] == "off")
                ? [Divoom.JsonFrame($"{{\"Command\":\"Channel/OnOffScreen\",\"OnOff\":{(a[0] == "on" ? 1 : 0)}}}")] : null;
        case "face":
            // show_design: view = design, then pick the design tab.
            return a.Count == 1 && byte.TryParse(a[0], out var id)
                ? [Divoom.Frame(0x45, [0x05]), Divoom.Frame(0xBD, [0x17, id])] : null;
        case "clock":
            return [Divoom.Frame(0x45, [0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00])];
        case "select":
            return a.Count == 2 && long.TryParse(a[0], out var clockId) && long.TryParse(a[1], out var deviceId)
                ? [Divoom.JsonFrame(FaceCommands.SelectClock(clockId, deviceId))] : null;
        case "json":
            return a.Count >= 1 ? [Divoom.JsonFrame(ReadJsonArg(string.Join(" ", a)))] : null;
        case "raw":
            return a.Count >= 1 && ParseRawLine(string.Join(" ", a)) is { } raw ? [raw] : null;
        case "rawfile":
            if (a.Count == 2 && int.TryParse(a[1], out var fileDelay)) delayMs = fileDelay;
            return a.Count is 1 or 2 ? ReadRawFile(a[0]) : null;
        default:
            return null;
    }
}

async Task<int> ListPaired()
{
    foreach (var dev in await DivoomLink.ListPairedAsync())
    {
        var divoom = Divoom.IsDivoom(dev.Name) ? "  <- Divoom" : "";
        Console.WriteLine($"{Divoom.FormatMac(dev.Address)}  {dev.Name}  ({(dev.Connected ? "Connected" : "Disconnected")}){divoom}");
    }
    return 0;
}

// Opens the channel and prints everything the device sends, including its start-up requests.
async Task<DivoomLink> Connect()
{
    var link = await DivoomLink.OpenReadyAsync(Divoom.ParseMac(mac!), service, settleMs, log: Console.Error.WriteLine);
    link.FrameReceived += frame => Console.WriteLine("<- " + Divoom.Describe(frame));
    return link;
}

async Task<int> RunFrames(List<byte[]> toSend)
{
    using var link = await Connect();
    for (int i = 0; i < toSend.Count; i++)
    {
        if (i > 0) await Task.Delay(delayMs);
        Console.WriteLine("-> " + Divoom.Hex(toSend[i]));
        await link.SendAsync(toSend[i]);
    }
    await Task.Delay(listenMs);
    return 0;
}

async Task<int> RunDeviceId()
{
    using var link = await DivoomLink.OpenReadyAsync(Divoom.ParseMac(mac!), service, settleMs, log: Console.Error.WriteLine);
    Console.WriteLine(await link.QueryDeviceIdAsync());
    return 0;
}

async Task<int> RunUploadFace(List<string> a)
{
    if (a.Count != 1 || !options.ContainsKey("page") || !File.Exists(a[0])) return Usage();
    int page = Int("page", -1);
    if (page is < 0 or > 2) { Console.Error.WriteLine("error: --page must be 0, 1 or 2"); return 64; }

    var face = FaceEncoder.Encode(a[0], new FaceOptions(
        Quality: Int("quality", 95),
        SpeedMs: options.ContainsKey("speed-ms") ? Int("speed-ms", 0) : null,
        SpeedScale: options.TryGetValue("speed-scale", out var s) ? double.Parse(s, System.Globalization.CultureInfo.InvariantCulture) : 1.0));
    Console.WriteLine($"encoded {Path.GetFileName(a[0])}: {face.SourceFrames} source frames -> {face.Frames} frames, {face.SpeedMs} ms/frame, {face.Payload.Length:N0} bytes");

    using var link = await DivoomLink.OpenReadyAsync(Divoom.ParseMac(mac!), service, settleMs, log: Console.Error.WriteLine);
    long deviceId = options.ContainsKey("device-id") ? Int("device-id", 0) : await link.QueryDeviceIdAsync();
    var fileId = options.TryGetValue("file-id", out var f) ? f : $"dvwin-{Path.GetFileNameWithoutExtension(a[0])}-{DateTimeOffset.UtcNow.ToUnixTimeSeconds()}";

    var started = DateTime.UtcNow;
    bool ok = await FaceUploader.UploadAsync(link, face, fileId, page, deviceId, chunkDelayMs: 5, TimeSpan.FromMinutes(3),
        log: m => Console.WriteLine(m));
    if (!ok) { Console.Error.WriteLine("error: the device did not confirm the upload."); return 3; }
    Console.WriteLine($"uploaded to custom page {page} in {(DateTime.UtcNow - started).TotalSeconds:F1} s");

    if (options.ContainsKey("clock-id") && options.ContainsKey("style-id"))
        await link.SendAsync(Divoom.JsonFrame(FaceCommands.SetClockStyle(long.Parse(options["clock-id"]), Int("style-id", 0), deviceId)));
    await Task.Delay(500);
    return 0;
}

// ---------------------------------------------------------------- input

static byte[]? ParseRawLine(string line)
{
    try
    {
        var bytes = line.Split(' ', StringSplitOptions.RemoveEmptyEntries).Select(x => Convert.ToByte(x, 16)).ToArray();
        return bytes.Length == 0 ? null : Divoom.Frame(bytes[0], bytes[1..]);
    }
    catch (FormatException) { return null; }
}

static List<byte[]>? ReadRawFile(string path)
{
    var frames = new List<byte[]>();
    foreach (var raw in File.ReadLines(path))
    {
        var line = raw.Split('#')[0].Trim();
        if (line.Length == 0) continue;
        var frame = ParseRawLine(line);
        if (frame == null) { Console.Error.WriteLine($"error: bad hex line: {raw}"); return null; }
        frames.Add(frame);
    }
    return frames.Count > 0 ? frames : null;
}

// `json -` reads stdin and `json @file` a file. Windows PowerShell 5.1 strips the double quotes
// out of native-command arguments, so inline JSON is only reliable from other shells. It also
// prefixes piped text with a UTF-8 BOM, which the device would take for part of the JSON.
static string ReadJsonArg(string arg) =>
    arg == "-" ? Console.In.ReadToEnd().Trim().TrimStart('﻿')
    : arg.StartsWith('@') ? File.ReadAllText(arg[1..]).Trim().TrimStart('﻿')
    : arg;

static int Usage()
{
    Console.Error.WriteLine("""
        usage: dv-win list
               dv-win [<MAC>] device-id
               dv-win [<MAC>] brightness <0-100>
               dv-win [<MAC>] screen on|off
               dv-win [<MAC>] face <id>
               dv-win [<MAC>] clock
               dv-win [<MAC>] select <ClockId> <DeviceId>
               dv-win [<MAC>] json '<body>' | json - | json @file
               dv-win [<MAC>] raw <opcode> [args...]
               dv-win [<MAC>] rawfile <path> [delay_ms]
               dv-win [<MAC>] upload-face <gif> --page <0-2> [--device-id <id>] [--file-id <id>]
                              [--quality 95] [--speed-ms <ms>] [--speed-scale <f>] [--clock-id <id> --style-id <id>]
        options: --listen <ms>  --delay <ms>  --settle <ms>  --uuid <guid>
        <MAC> may be omitted when DIVOOM_MAC is set.
        """);
    return 64;
}
