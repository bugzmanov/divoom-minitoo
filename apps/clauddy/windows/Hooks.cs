using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Clauddy;

/// <summary>
/// Adds and removes Clauddy's entries in Claude Code's settings.json, leaving everything else in the file
/// (other hooks, other settings) as it is. An entry is ours when its command runs `clauddy-win ... hook <state>`.
/// </summary>
public static class Hooks
{
    // Same mapping as the macOS setup (apps/clauddy/README.md).
    private static readonly (string Event, string State)[] Mapping =
    [
        ("UserPromptSubmit", "working"),
        ("PreToolUse", "working"),
        ("Notification", "alerting"),
        ("Stop", "chilling"),
    ];

    private static readonly JsonSerializerOptions WriteOptions = new() { WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    public static string SettingsPath(string? given)
    {
        if (given != null) return given;
        var configDir = Environment.GetEnvironmentVariable("CLAUDE_CONFIG_DIR")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".claude");
        return Path.Combine(configDir, "settings.json");
    }

    public static string Command(string state)
    {
        var exe = (Environment.ProcessPath ?? "clauddy-win.exe").Replace('\\', '/');
        return $"{(exe.Contains(' ') ? $"\"{exe}\"" : exe)} hook {state}";
    }

    public static IEnumerable<(string Event, string Command)> Entries() => Mapping.Select(m => (m.Event, Command(m.State)));

    private static bool IsOurs(string? command) =>
        command != null && command.Contains("clauddy-win", StringComparison.OrdinalIgnoreCase) && command.Contains(" hook ");

    public static bool IsInstalled(string path)
    {
        if (!File.Exists(path)) return false;
        try { return Load(path)["hooks"] is JsonObject hooks && hooks.Any(e => e.Value is JsonArray groups && groups.Any(g => OurHooks(g).Any())); }
        catch (InvalidDataException) { return false; }
    }

    /// <summary>Installs the hooks, replacing any earlier Clauddy entries (for example from another install path).</summary>
    public static void Add(string path)
    {
        var root = File.Exists(path) ? Load(path) : new JsonObject();
        RemoveFrom(root);
        var hooks = root["hooks"] as JsonObject ?? (JsonObject)(root["hooks"] = new JsonObject());
        foreach (var (eventName, command) in Entries())
        {
            var groups = hooks[eventName] as JsonArray ?? (JsonArray)(hooks[eventName] = new JsonArray());
            groups.Add(new JsonObject { ["hooks"] = new JsonArray(new JsonObject { ["type"] = "command", ["command"] = command }) });
        }
        Save(path, root);
    }

    /// <summary>Removes Clauddy's hooks and returns how many entries went. The file is left alone when there are none.</summary>
    public static int Remove(string path)
    {
        if (!File.Exists(path)) return 0;
        var root = Load(path);
        int removed = RemoveFrom(root);
        if (removed > 0) Save(path, root);
        return removed;
    }

    private static IEnumerable<JsonNode> OurHooks(JsonNode? group) =>
        group?["hooks"] is JsonArray inner ? inner.Where(h => h != null && IsOurs((string?)h["command"])).Select(h => h!) : [];

    private static int RemoveFrom(JsonObject root)
    {
        if (root["hooks"] is not JsonObject hooks) return 0;
        int removed = 0;
        foreach (var eventName in hooks.Select(e => e.Key).ToList())
        {
            if (hooks[eventName] is not JsonArray groups) continue;
            foreach (var group in groups.ToList())
            {
                if (group?["hooks"] is not JsonArray inner) continue;
                foreach (var entry in OurHooks(group).ToList()) { inner.Remove(entry); removed++; }
                if (inner.Count == 0) groups.Remove(group); // a group that held only ours
            }
            if (groups.Count == 0) hooks.Remove(eventName);
        }
        if (hooks.Count == 0) root.Remove("hooks");
        return removed;
    }

    private static JsonObject Load(string path)
    {
        try { return JsonNode.Parse(File.ReadAllText(path)) as JsonObject ?? throw new InvalidDataException($"{path} is not a JSON object"); }
        catch (JsonException e) { throw new InvalidDataException($"{path} is not valid JSON ({e.Message}); not touching it."); }
    }

    // Keep one pristine copy of the file before the first change, and replace the file in one step.
    private static void Save(string path, JsonObject root)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        var backup = path + ".clauddy-backup";
        if (File.Exists(path) && !File.Exists(backup)) File.Copy(path, backup);
        var temp = path + ".clauddy-tmp";
        File.WriteAllText(temp, root.ToJsonString(WriteOptions) + Environment.NewLine);
        File.Move(temp, path, overwrite: true);
    }
}
