using System.Text.Json;

namespace Clauddy;

/// <summary>One of the three status faces: the custom page it is stored on and the cloud ids used to select it.</summary>
public sealed record Face(long ClockId, int Page, int Style);

/// <summary>%USERPROFILE%\.clauddy\config.json. Holds no credentials: Bluetooth address, DeviceId and face ids only.</summary>
public sealed class Config
{
    public static readonly string[] States = ["chilling", "working", "alerting"];

    // Same pages and frame styles as apps/clauddy/tools/clauddy-cloud.py.
    public static readonly Dictionary<string, (int Page, int Style)> Defaults = new()
    {
        ["chilling"] = (0, 798),
        ["working"] = (1, 828),
        ["alerting"] = (2, 798),
    };

    // The "Custom1/2/3" entries of the Divoom store (clock types 3, 4, 5). Same ids as on the author's account
    // and verified on a second MiniToo, so a Divoom login is normally not needed.
    public static readonly Dictionary<string, long> DefaultClockIds = new()
    {
        ["chilling"] = 984,
        ["working"] = 986,
        ["alerting"] = 988,
    };

    public string Mac { get; set; } = "";
    public long DeviceId { get; set; }
    public Dictionary<string, Face> Faces { get; set; } = new();

    public static string Dir => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".clauddy");
    public static string FilePath => Path.Combine(Dir, "config.json");

    /// <summary>Exists between `start` and `stop`: hooks only (re)start the daemon while it does.</summary>
    public static string EnabledMarker => Path.Combine(Dir, "enabled");

    public static Config? Load()
    {
        try { return JsonSerializer.Deserialize<Config>(File.ReadAllText(FilePath)); }
        catch (Exception e) when (e is IOException or JsonException) { return null; }
    }

    public void Save()
    {
        Directory.CreateDirectory(Dir);
        File.WriteAllText(FilePath, JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
    }
}
