using System.Text;
using System.Text.Json.Nodes;

namespace DvWin;

/// <summary>JSON commands the custom-face upload and runtime switching use (see apps/clauddy/lib/clauddy-lib.sh).</summary>
public static class FaceCommands
{
    public static string CleanCustom(int page, long deviceId) =>
        $"{{\"Command\":\"Channel/CleanCustom\",\"CustomPageIndex\":{page},\"ClockId\":0,\"ParentClockId\":0,\"ParentItemId\":\"\",\"DeviceId\":{deviceId}}}";

    public static string SetCustom(int page, string fileId, long deviceId) =>
        $"{{\"Command\":\"Channel/SetCustom\",\"CustomPageIndex\":{page},\"CustomId\":0,\"FileId\":\"{fileId}\",\"ClockId\":0,\"ParentClockId\":0,\"ParentItemId\":\"\",\"LcdIndependence\":0,\"LcdIndex\":0,\"Language\":\"en\",\"DeviceId\":{deviceId}}}";

    public static string SetClockStyle(long clockId, int styleId, long deviceId) =>
        $"{{\"Command\":\"Channel/SetClockStyle\",\"ClockId\":{clockId},\"StyleId\":{styleId},\"DeviceId\":{deviceId},\"ParentClockId\":0,\"ParentItemId\":\"\",\"PageIndex\":0,\"LcdIndependence\":0,\"LcdIndex\":0,\"Language\":\"en\"}}";

    public static string SelectClock(long clockId, long deviceId) =>
        $"{{\"Command\":\"Channel/SetClockSelectId\",\"ClockId\":{clockId},\"DeviceId\":{deviceId},\"ParentClockId\":0,\"ParentItemId\":\"\",\"PageIndex\":0,\"LcdIndependence\":0,\"LcdIndex\":0,\"Language\":\"en\"}}";
}

/// <summary>
/// Stores a face on one of the device's custom pages. The device drives the transfer: after SetCustom it asks
/// for the file by id (0xBD 0x30), asks for the data (0xBE 0x00) and for missing chunks (0xBE 0x01), and
/// confirms with `bd 55 13 01 05 00`. Port of AutoCustomResponder in core/divoom-send.swift.
/// </summary>
public static class FaceUploader
{
    private const int ChunkSize = 256;
    private static readonly byte[] UploadDone = [0xBD, 0x55, 0x13, 0x01, 0x05, 0x00];

    public static async Task<bool> UploadAsync(DivoomLink link, EncodedFace face, string fileId, int page, long deviceId,
        int chunkDelayMs, TimeSpan timeout, Action<string> log)
    {
        var payload = face.Payload;
        var idBytes = Encoding.ASCII.GetBytes(fileId);
        var start = Divoom.Frame(0xBE, [0x00, .. BitConverter.GetBytes((uint)payload.Length), (byte)idBytes.Length, .. idBytes]);
        var chunks = Enumerable.Range(0, (payload.Length + ChunkSize - 1) / ChunkSize)
            .Select(i => Divoom.Frame(0xBE, [0x01, .. BitConverter.GetBytes((uint)payload.Length), .. BitConverter.GetBytes((ushort)i),
                .. payload.AsSpan(i * ChunkSize, Math.Min(ChunkSize, payload.Length - i * ChunkSize)).ToArray()]))
            .ToList();

        var done = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        int sendingChunks = 0;

        void Fire(Func<Task> work) => _ = Task.Run(async () =>
        {
            try { await work(); }
            catch (Exception e) { log($"upload: {e.Message}"); done.TrySetResult(false); }
        });

        void OnFrame(byte[] frame)
        {
            var (op, args) = Divoom.Unwrap(frame);
            if (op != Divoom.OpReply || args.Length < 3) return;

            if (Divoom.ArgsStartWith(frame, UploadDone)) { done.TrySetResult(true); return; }

            if (args[0] == 0xBD && args[1] == 0x55 && args[2] == 0x30 && args.Length >= 4 + args[3])
            {
                var requested = Encoding.UTF8.GetString(args, 4, args[3]);
                if (requested == fileId) Fire(() => link.SendAsync(start));
                else log($"upload: ignoring request for unexpected file {requested}");
            }
            else if (args[0] == 0xBE && args[1] == 0x55)
            {
                if (args[2] == 0)
                {
                    if (Interlocked.Exchange(ref sendingChunks, 1) == 0)
                        Fire(async () =>
                        {
                            log($"upload: sending {chunks.Count} chunks ({payload.Length:N0} bytes)");
                            foreach (var chunk in chunks)
                            {
                                await link.SendAsync(chunk);
                                if (chunkDelayMs > 0) await Task.Delay(chunkDelayMs);
                            }
                        });
                }
                else if (args[2] == 1 && args.Length >= 5)
                {
                    int index = args[3] | args[4] << 8;
                    if (index < chunks.Count) Fire(() => link.SendAsync(chunks[index]));
                }
            }
            else if (args[0] == 0x01 && args[1] == 0x55 && Divoom.ReplyJson(frame) is { } json)
            {
                var node = JsonNode.Parse(json);
                switch (node?["Command"]?.GetValue<string>())
                {
                    case "Channel/GetOneCustom":
                        Fire(() => link.SendAsync(Divoom.JsonFrame(new JsonObject
                        {
                            ["Command"] = "Channel/GetOneCustom", ["ReturnCode"] = 0, ["ReturnMessage"] = "", ["DeviceId"] = deviceId,
                            ["CustomPageIndex"] = (int?)node["CustomPageIndex"] ?? 0, ["CustomId"] = (int?)node["CustomId"] ?? 0, ["FileId"] = fileId,
                        }.ToJsonString())));
                        break;
                    case "Device/GetFileVersion":
                        Fire(() => link.SendAsync(Divoom.JsonFrame(new JsonObject
                        {
                            ["Command"] = "Device/GetFileVersion", ["ReturnCode"] = 0, ["ReturnMessage"] = "", ["DeviceId"] = deviceId,
                            ["FileType"] = (int?)node["FileType"] ?? 1, ["FileId"] = fileId, ["Version"] = 1,
                        }.ToJsonString())));
                        break;
                }
            }
        }

        link.FrameReceived += OnFrame;
        try
        {
            await link.SendAsync(Divoom.JsonFrame(FaceCommands.CleanCustom(page, deviceId)));
            await Task.Delay(100);
            await link.SendAsync(Divoom.JsonFrame(FaceCommands.SetCustom(page, fileId, deviceId)));
            return await Task.WhenAny(done.Task, Task.Delay(timeout)) == done.Task && done.Task.Result;
        }
        finally { link.FrameReceived -= OnFrame; }
    }
}
