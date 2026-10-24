using System.Text;

namespace DvWin;

/// <summary>Divoom SPP frame format (FINDINGS.md section 3) and helpers for reading replies.</summary>
public static class Divoom
{
    public const byte OpJson = 0x01;
    public const byte OpReply = 0x04;

    // 01 len_lo len_hi opcode args... csum_lo csum_hi 02, len = args + 3, csum = sum(len, opcode, args) & 0xFFFF.
    public static byte[] Frame(byte opcode, byte[] args)
    {
        int length = args.Length + 3;
        var payload = new List<byte> { (byte)(length & 0xFF), (byte)(length >> 8), opcode };
        payload.AddRange(args);
        int sum = payload.Sum(b => (int)b);
        var frame = new List<byte> { 0x01 };
        frame.AddRange(payload);
        frame.Add((byte)(sum & 0xFF));
        frame.Add((byte)((sum >> 8) & 0xFF));
        frame.Add(0x02);
        return frame.ToArray();
    }

    public static byte[] JsonFrame(string json) => Frame(OpJson, Encoding.UTF8.GetBytes(json));

    /// <summary>Opcode and arguments of a received frame (without delimiters, length and checksum).</summary>
    public static (byte Opcode, byte[] Args) Unwrap(byte[] frame) => (frame[3], frame[4..^3]);

    /// <summary>The JSON body of a reply frame, or null. Replies are `04 01 55 {json}`.</summary>
    public static string? ReplyJson(byte[] frame)
    {
        var (opcode, args) = Unwrap(frame);
        return opcode == OpReply && args.Length > 2 && args[1] == 0x55 && args[2] == (byte)'{'
            ? Encoding.UTF8.GetString(args[2..])
            : null;
    }

    /// <summary>The DeviceId from the reply to `bd 2b 00` (`04 bd 55 2b <u32>...`), or null.</summary>
    public static long? ReplyDeviceId(byte[] frame)
    {
        var (opcode, args) = Unwrap(frame);
        if (opcode != OpReply || args.Length < 7 || args[0] != 0xBD || args[1] != 0x55 || args[2] != 0x2B) return null;
        // Little endian first (matches the app's SPP payloads), big endian as a fallback for other firmware.
        foreach (var value in new[] { BitConverter.ToUInt32(args, 3), BitConverter.ToUInt32(args[3..7].Reverse().ToArray()) })
            if (value is >= 10_000_000 and <= 4_000_000_000) return value;
        return null;
    }

    public static bool ArgsStartWith(byte[] frame, params byte[] prefix)
    {
        var (opcode, args) = Unwrap(frame);
        return opcode == OpReply && args.Length >= prefix.Length && args.AsSpan(0, prefix.Length).SequenceEqual(prefix);
    }

    public static string Describe(byte[] frame)
    {
        if (ReplyJson(frame) is { } json)
            return string.Join(" ", json.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        var (opcode, args) = Unwrap(frame);
        return $"op {opcode:x2}: {Hex(args)}";
    }

    // ---------------------------------------------------------------- addresses and text

    public static bool IsDivoom(string? name) =>
        name != null && new[] { "divoom", "minitoo", "tiivoo" }.Any(t => name.Contains(t, StringComparison.OrdinalIgnoreCase));

    public static bool LooksLikeMac(string s) =>
        System.Text.RegularExpressions.Regex.IsMatch(s, "^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$");

    public static ulong ParseMac(string mac) => Convert.ToUInt64(mac.Replace(":", "").Replace("-", ""), 16);

    public static string FormatMac(ulong address) =>
        string.Join(":", Convert.ToHexString(BitConverter.GetBytes(address).Reverse().Skip(2).ToArray()).Chunk(2).Select(c => new string(c)));

    public static string Hex(byte[] bytes) => BitConverter.ToString(bytes).Replace('-', ' ').ToLowerInvariant();
}

/// <summary>Reassembles frames from the byte stream. Replies can arrive split across reads or several to a read.</summary>
public sealed class FrameAssembler
{
    private readonly List<byte> _buffer = new();

    public IEnumerable<byte[]> Feed(byte[] chunk)
    {
        _buffer.AddRange(chunk);
        var frames = new List<byte[]>();
        while (_buffer.Count >= 5)
        {
            if (_buffer[0] != 0x01) { _buffer.RemoveAt(0); continue; }
            int total = (_buffer[1] | _buffer[2] << 8) + 4;
            if (total < 7 || total > 1 << 16) { _buffer.RemoveAt(0); continue; }
            if (_buffer.Count < total) break;
            if (_buffer[total - 1] != 0x02) { _buffer.RemoveAt(0); continue; }
            frames.Add(_buffer.GetRange(0, total).ToArray());
            _buffer.RemoveRange(0, total);
        }
        return frames;
    }
}
