using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace Clauddy;

public sealed class DivoomCloudException(string message) : Exception(message);

/// <summary>
/// The few Divoom cloud calls Clauddy needs, to find the ClockIds of the three custom faces. Port of
/// apps/clauddy/tools/clauddy-cloud.py. The password and token are kept in memory only.
/// </summary>
public sealed class DivoomCloud
{
    private const string BaseUrl = "https://appin.divoom-gz.com";
    public const int StyleRimless = 798;
    public const int StyleNoiseBars = 828;

    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(15) };
    private readonly long _deviceId;
    private readonly string _country;
    private readonly string _language;
    private readonly string _timezone;
    private long _userId;
    private long _token;

    public DivoomCloud(long deviceId)
    {
        _deviceId = deviceId;
        _country = RegionInfo.CurrentRegion.TwoLetterISORegionName is { Length: 2 } c && c != "IV" ? c : "US";
        var lang = CultureInfo.CurrentCulture.TwoLetterISOLanguageName;
        _language = lang == "zh" ? (_country is "CN" or "SG" ? "zh-hans" : "zh-hant") : lang is { Length: > 0 } and not "iv" ? lang : "en";
        int hours = (int)TimeZoneInfo.Local.BaseUtcOffset.TotalHours;
        _timezone = hours >= 0 ? $"+{hours}" : hours.ToString();
        _http.DefaultRequestHeaders.UserAgent.ParseAdd("clauddy-setup/1");
    }

    // The Divoom app hashes the password as Java does: each char truncated to a byte.
    private static string JavaMd5(string text) =>
        Convert.ToHexString(MD5.HashData(text.Select(ch => (byte)(ch & 0xFF)).ToArray())).ToLowerInvariant();

    private async Task<JsonNode> PostAsync(string command, JsonObject payload)
    {
        payload["Command"] = command;
        payload["DeviceId"] = _deviceId;
        payload["Token"] = _token;
        payload["UserId"] = _userId;
        string raw;
        try
        {
            using var response = await _http.PostAsync($"{BaseUrl}/{command}", new StringContent(payload.ToJsonString(), new UTF8Encoding(false), "application/json"));
            raw = await response.Content.ReadAsStringAsync();
            if (!response.IsSuccessStatusCode) throw new DivoomCloudException($"{command}: HTTP {(int)response.StatusCode}: {raw}");
        }
        catch (HttpRequestException e) { throw new DivoomCloudException($"{command}: network error: {e.Message}"); }
        catch (TaskCanceledException) { throw new DivoomCloudException($"{command}: timed out"); }

        JsonNode parsed;
        try { parsed = JsonNode.Parse(raw) ?? throw new System.Text.Json.JsonException(); }
        catch (System.Text.Json.JsonException) { throw new DivoomCloudException($"{command}: non-JSON response: {raw[..Math.Min(500, raw.Length)]}"); }

        var code = (int?)parsed["ReturnCode"];
        if (code is not (0 or null)) throw new DivoomCloudException($"{command}: ReturnCode={code} ReturnMessage={(string?)parsed["ReturnMessage"]}");
        return parsed;
    }

    public async Task LoginAsync(string email, string password)
    {
        var response = await PostAsync("UserLogin", new JsonObject
        {
            ["Email"] = email,
            ["Password"] = JavaMd5(password),
            ["TimeZone"] = _timezone,
            ["CountryISOCode"] = _country,
            ["Language"] = _language,
        });
        _userId = (long?)response["UserId"] ?? 0;
        _token = (long?)response["Token"] ?? 0;
        if (_userId == 0 || _token == 0) throw new DivoomCloudException("UserLogin succeeded but did not return UserId and Token");
    }

    /// <summary>ClockIds of the custom faces: clock types 3, 4 and 5 are chilling, working and alerting.</summary>
    public async Task<Dictionary<string, long>> FindCustomClocksAsync()
    {
        var found = MapCustomClocks(await ClockList("Channel/MyClockGetList", new JsonObject { ["StartNum"] = 1, ["EndNum"] = 100, ["Flag"] = 0 }));
        if (found.Count < Config.States.Length)
        {
            var classify = await PostAsync("Channel/StoreClockGetClassify", Localized(new JsonObject { ["StartNum"] = 0, ["EndNum"] = 0 }));
            if (classify["ClassifyList"] is JsonArray { Count: > 0 } list)
            {
                var items = await ClockList("Channel/StoreClockGetList",
                    new JsonObject { ["StartNum"] = 1, ["EndNum"] = 30, ["Flag"] = 0, ["ClassifyId"] = (long?)list[0]?["ClassifyId"] ?? 0 });
                foreach (var (state, id) in MapCustomClocks(items)) found.TryAdd(state, id);
            }
        }
        var missing = Config.States.Where(s => !found.ContainsKey(s)).ToList();
        if (missing.Count > 0) throw new DivoomCloudException($"could not find custom face IDs for: {string.Join(", ", missing)}");
        return found;
    }

    public Task SetStyleAsync(long clockId, int styleId) => PostAsync("Channel/SetClockStyle", Localized(new JsonObject
    {
        ["ClockId"] = clockId, ["StyleId"] = styleId, ["ParentClockId"] = 0, ["ParentItemId"] = "",
        ["PageIndex"] = 0, ["LcdIndependence"] = 0, ["LcdIndex"] = 0,
    }));

    private JsonObject Localized(JsonObject payload)
    {
        payload["CountryISOCode"] = _country;
        payload["Language"] = _language;
        return payload;
    }

    private async Task<JsonArray> ClockList(string command, JsonObject payload) =>
        (await PostAsync(command, Localized(payload)))["ClockList"] as JsonArray ?? [];

    private static Dictionary<string, long> MapCustomClocks(JsonArray items)
    {
        var byType = new Dictionary<int, string> { [3] = "chilling", [4] = "working", [5] = "alerting" };
        var found = new Dictionary<string, long>();
        foreach (var item in items)
        {
            if (item is null || !int.TryParse(item["ClockType"]?.ToString(), out var type) || !long.TryParse(item["ClockId"]?.ToString(), out var id)) continue;
            if (byType.TryGetValue(type, out var state) && id != 0) found[state] = id;
        }
        return found;
    }
}
