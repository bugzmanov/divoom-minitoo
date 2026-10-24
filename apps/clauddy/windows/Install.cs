using System.Globalization;
using System.Text;
using DvWin;

namespace Clauddy;

/// <summary>
/// Port of apps/clauddy/install.sh: finds the device, logs in to Divoom to learn the three custom face ids,
/// writes the config and uploads the bundled GIFs. The Divoom password is typed at a hidden prompt.
/// </summary>
public static class Install
{
    public static async Task<int> RunAsync(Dictionary<string, string> options)
    {
        // The daemon owns the Bluetooth channel and the device takes one client at a time.
        await Client.SendAsync("quit", startDaemon: false);
        await Task.Delay(500);

        bool skipUpload = options.ContainsKey("skip-upload");
        var assets = FindAssets(options.GetValueOrDefault("assets"));
        if (!skipUpload && assets == null)
        {
            Console.Error.WriteLine("error: cannot find the bundled GIFs (chilling.gif, working.gif, alerting.gif). Pass --assets <dir>.");
            return 64;
        }

        var address = await PickDevice(options.GetValueOrDefault("mac"));
        Console.WriteLine($"Connecting to {Divoom.FormatMac(address)}...");
        using var link = await DivoomLink.OpenReadyAsync(address, DivoomLink.Spp, log: Console.WriteLine);
        long deviceId = options.TryGetValue("device-id", out var given) ? long.Parse(given) : await link.QueryDeviceIdAsync();
        Console.WriteLine($"DeviceId={deviceId}");

        Dictionary<string, long> clocks;
        if (options.TryGetValue("clock-ids", out var ids))
        {
            var parsed = ids.Split(',').Select(s => long.TryParse(s, out var id) ? id : 0).ToArray();
            if (parsed.Length != Config.States.Length || parsed.Contains(0))
            {
                Console.Error.WriteLine("error: --clock-ids takes three ids: chilling,working,alerting");
                return 64;
            }
            clocks = Config.States.Zip(parsed).ToDictionary(p => p.First, p => p.Second);
        }
        else if (options.ContainsKey("login") || options.ContainsKey("email"))
        {
            var found = await LookUpClocks(deviceId, options.GetValueOrDefault("email"));
            if (found == null) return 1;
            clocks = found;
        }
        else
        {
            clocks = Config.DefaultClockIds;
            Console.WriteLine("Using the custom-face ids of the Divoom store (no Divoom login). If switching does nothing visible, run again with --login.");
        }

        var config = new Config { Mac = Divoom.FormatMac(address), DeviceId = deviceId };
        foreach (var state in Config.States)
        {
            var (page, style) = Config.Defaults[state];
            config.Faces[state] = new Face(clocks[state], page, style);
            Console.WriteLine($"  {state,-8} -> ClockId={clocks[state]} page={page} style={style}");
        }
        config.Save();
        Console.WriteLine($"wrote {Config.FilePath}");

        foreach (var state in Config.States)
        {
            var face = config.Faces[state];
            if (!skipUpload && !await Upload(link, assets!, state, face, deviceId)) return 3;
            await link.SendAsync(Divoom.JsonFrame(FaceCommands.SetClockStyle(face.ClockId, face.Style, deviceId)));
            await Task.Delay(200);
        }

        await link.SendAsync(Divoom.JsonFrame(FaceCommands.SelectClock(config.Faces["chilling"].ClockId, deviceId)));
        await Task.Delay(500);
        Console.WriteLine();
        Console.WriteLine("Clauddy install complete. Try: clauddy-win set working");
        return 0;
    }

    // Optional: ask Divoom for this account's custom-face ids. The password is typed at a hidden prompt, never
    // stored, and the token stays in memory.
    private static async Task<Dictionary<string, long>?> LookUpClocks(long deviceId, string? email)
    {
        Console.WriteLine();
        Console.WriteLine("Divoom account: the login is used only to look up the ids of the three custom faces and to set their frame");
        Console.WriteLine("styles through Divoom's own API.");
        email ??= Prompt("Divoom email/username: ");
        var password = ReadSecret("Divoom password (not stored): ");
        if (email.Length == 0 || password.Length == 0) { Console.Error.WriteLine("error: the Divoom email and password are required."); return null; }

        var cloud = new DivoomCloud(deviceId);
        try
        {
            await cloud.LoginAsync(email, password);
            var clocks = await cloud.FindCustomClocksAsync();
            foreach (var state in Config.States) await cloud.SetStyleAsync(clocks[state], Config.Defaults[state].Style);
            return clocks;
        }
        catch (DivoomCloudException e)
        {
            Console.Error.WriteLine("error: " + e.Message);
            return null;
        }
    }

    private static async Task<bool> Upload(DivoomLink link, string assets, string state, Face face, long deviceId)
    {
        var env = (string name) => Environment.GetEnvironmentVariable(name);
        var encoded = FaceEncoder.Encode(Path.Combine(assets, state + ".gif"), new FaceOptions(
            Quality: int.TryParse(env("CLAUDDY_JPEG_QUALITY"), out var q) ? q : 95,
            SpeedMs: int.TryParse(env($"CLAUDDY_SPEED_{state.ToUpperInvariant()}"), out var ms) ? ms : null,
            SpeedScale: double.TryParse(env("CLAUDDY_SPEED_SCALE"), CultureInfo.InvariantCulture, out var scale) ? scale : 1.0));

        Console.WriteLine($"Uploading {state} to custom page {face.Page}: {encoded.Frames} frames, {encoded.Payload.Length:N0} bytes...");
        var fileId = $"clauddy-{state}-{DateTimeOffset.UtcNow.ToUnixTimeSeconds()}";
        bool ok = await FaceUploader.UploadAsync(link, encoded, fileId, face.Page, deviceId, chunkDelayMs: 5, TimeSpan.FromMinutes(5), log: Console.WriteLine);
        if (!ok) Console.Error.WriteLine($"error: timed out waiting for the device to confirm the {state} upload.");
        return ok;
    }

    private static async Task<ulong> PickDevice(string? mac)
    {
        if (mac != null)
        {
            if (!Divoom.LooksLikeMac(mac)) throw new DivoomLinkException($"invalid Bluetooth MAC address: {mac}");
            return Divoom.ParseMac(mac);
        }
        var candidates = (await DivoomLink.ListPairedAsync()).Where(d => Divoom.IsDivoom(d.Name)).ToList();
        if (candidates.Count == 0)
            throw new DivoomLinkException("no paired Divoom device found. Pair it in Windows Settings > Bluetooth & devices, or pass --mac.");
        if (candidates.Count == 1)
        {
            Console.WriteLine($"Found paired Divoom device: {candidates[0].Name} ({Divoom.FormatMac(candidates[0].Address)})");
            return candidates[0].Address;
        }
        for (int i = 0; i < candidates.Count; i++) Console.WriteLine($"  {i + 1}. {candidates[i].Name} ({Divoom.FormatMac(candidates[i].Address)})");
        return int.TryParse(Prompt("Choose device number: "), out var n) && n >= 1 && n <= candidates.Count
            ? candidates[n - 1].Address
            : throw new DivoomLinkException("invalid selection.");
    }

    private static string? FindAssets(string? given)
    {
        if (given != null) return Directory.Exists(given) ? given : null;
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (int i = 0; i < 8 && dir != null; i++, dir = dir.Parent)
            foreach (var sub in new[] { "assets", Path.Combine("apps", "clauddy", "assets") })
                if (File.Exists(Path.Combine(dir.FullName, sub, "chilling.gif"))) return Path.Combine(dir.FullName, sub);
        return null;
    }

    private static string Prompt(string text)
    {
        Console.Write(text);
        return Console.ReadLine()?.Trim() ?? "";
    }

    private static string ReadSecret(string text)
    {
        Console.Write(text);
        if (Console.IsInputRedirected) return Console.ReadLine() ?? "";
        var secret = new StringBuilder();
        while (true)
        {
            var key = Console.ReadKey(intercept: true);
            if (key.Key == ConsoleKey.Enter) break;
            if (key.Key == ConsoleKey.Backspace) { if (secret.Length > 0) secret.Length--; }
            else if (!char.IsControl(key.KeyChar)) secret.Append(key.KeyChar);
        }
        Console.WriteLine();
        return secret.ToString();
    }
}
