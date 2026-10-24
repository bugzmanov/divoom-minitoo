using Clauddy;
using DvWin;

// Clauddy for Windows: Claude Code status faces on a Divoom MiniToo / Tiivoo 2.
//
//   clauddy-win install [--mac <MAC>] [--assets <dir>] [--skip-upload] [--login [--email <login>]] [--clock-ids <a,b,c>]
//   clauddy-win start [--settings <path>]         start the daemon and add the hooks to Claude Code's settings.json
//   clauddy-win stop  [--settings <path>]         stop the daemon and remove the hooks again
//   clauddy-win status [--settings <path>]
//   clauddy-win set <chilling|working|alerting>   switch now
//   clauddy-win hook <chilling|working|alerting>  same, with the multi-session gating; what the hooks call
//   clauddy-win hooks                             print the hooks without touching any file
//
// The daemon keeps the Bluetooth channel open (so the Divoom phone app cannot connect meanwhile).

if (args.Length == 0) return Usage();

var options = new Dictionary<string, string>();
var rest = new List<string>();
string[] valueOptions = ["mac", "email", "assets", "device-id", "clock-ids", "settings"];
for (int i = 0; i < args.Length; i++)
{
    if (args[i] is "--skip-upload" or "--login") options[args[i][2..]] = "1";
    else if (args[i].StartsWith("--") && valueOptions.Contains(args[i][2..]) && i + 1 < args.Length) options[args[i][2..]] = args[++i];
    else if (args[i].StartsWith("--")) return Usage();
    else rest.Add(args[i]);
}
var settingsPath = Hooks.SettingsPath(options.GetValueOrDefault("settings"));

try
{
    switch (rest.FirstOrDefault())
    {
        case "install":
            return await Install.RunAsync(options);

        case "daemon":
            Console.SetOut(TextWriter.Null);
            Console.SetError(TextWriter.Null);
            return Config.Load() is { } cfg ? await new Daemon(cfg).RunAsync() : 1;

        case "start":
            return await Start();

        case "stop":
            return await Stop();

        case "status":
            var status = await Client.SendAsync("status", startDaemon: false);
            Console.WriteLine(status == null ? "daemon:  not running" : $"daemon:  running ({status})");
            Console.WriteLine($"hooks:   {(Hooks.IsInstalled(settingsPath) ? "installed in " + settingsPath : "not installed")}");
            return 0;

        case "set" or "hook" when rest.Count == 2 && Config.States.Contains(rest[1]):
            // A hook must never get in the way of a prompt: stay quiet, and when Clauddy is stopped do nothing at
            // all (sessions started while the hooks were installed keep calling it after `stop`).
            bool isHook = rest[0] == "hook";
            if (Config.Load() == null) return isHook ? 0 : Fail("no config. Run `clauddy-win install` first.");
            var reply = await Client.SendAsync($"{rest[0]} {rest[1]}", startDaemon: !isHook || File.Exists(Config.EnabledMarker));
            if (reply == "ok") { if (!isHook) Console.WriteLine($"clauddy state: {rest[1]}"); return 0; }
            return isHook ? 0 : Fail(reply ?? "could not reach the daemon. See " + Path.Combine(Config.Dir, "daemon.log"));

        case "hooks":
            PrintHooks();
            return 0;

        default:
            return Usage();
    }
}
catch (DivoomLinkException e)
{
    return Fail(e.Message, e.ExitCode);
}
catch (InvalidDataException e)
{
    return Fail(e.Message);
}

async Task<int> Start()
{
    if (Config.Load() == null) return Fail("no config. Run `clauddy-win install` first.");

    Hooks.Add(settingsPath);
    Directory.CreateDirectory(Config.Dir);
    File.WriteAllText(Config.EnabledMarker, "");
    Console.WriteLine($"hooks added to {settingsPath}");
    Console.WriteLine("If an already open Claude Code session does not react, restart it or reload hooks in /hooks.");

    // Starting the daemon with the resting face also proves the Bluetooth link works.
    if (await Client.SendAsync("set chilling") != "ok")
        return Fail("could not start the daemon. See " + Path.Combine(Config.Dir, "daemon.log"));
    for (int i = 0; i < 40; i++)
    {
        if ((await Client.SendAsync("status", startDaemon: false))?.Contains("connected=True") == true)
        {
            Console.WriteLine("daemon running, device connected");
            return 0;
        }
        await Task.Delay(500);
    }
    Console.Error.WriteLine("warning: the daemon is running but the device is not connected yet. See " + Path.Combine(Config.Dir, "daemon.log"));
    return 0;
}

async Task<int> Stop()
{
    try { Console.WriteLine($"hooks removed from {settingsPath}: {Hooks.Remove(settingsPath)}"); }
    catch (InvalidDataException e) { Console.Error.WriteLine("warning: " + e.Message); }
    if (File.Exists(Config.EnabledMarker)) File.Delete(Config.EnabledMarker);
    Console.WriteLine(await Client.SendAsync("quit", startDaemon: false) == "ok" ? "daemon stopped" : "daemon not running");
    return 0;
}

static int Fail(string message, int code = 1)
{
    Console.Error.WriteLine("error: " + message);
    return code;
}

static void PrintHooks()
{
    string Entry(string command) => $$"""[ { "hooks": [ { "type": "command", "command": {{System.Text.Json.JsonSerializer.Serialize(command)}} } ] } ]""";
    var lines = Hooks.Entries().Select(e => $"    \"{e.Event}\": {Entry(e.Command)}");
    Console.WriteLine("{\n  \"hooks\": {\n" + string.Join(",\n", lines) + "\n  }\n}");
}

static int Usage()
{
    Console.Error.WriteLine("""
        usage: clauddy-win install [--mac <MAC>] [--assets <dir>] [--skip-upload] [--login [--email <login>]] [--clock-ids <a,b,c>]
               clauddy-win start [--settings <path>]
               clauddy-win stop [--settings <path>]
               clauddy-win status [--settings <path>]
               clauddy-win set <chilling|working|alerting>
               clauddy-win hook <chilling|working|alerting>
               clauddy-win hooks
        """);
    return 64;
}
