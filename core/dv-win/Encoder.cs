using SkiaSharp;

namespace DvWin;

public sealed record FaceOptions(int Quality = 95, int? SpeedMs = null, double SpeedScale = 1.0);

public sealed record EncodedFace(byte[] Payload, int SourceFrames, int Frames, int SpeedMs);

/// <summary>
/// GIF to MiniToo custom-face payload. Port of apps/clauddy/tools/encode-custom-raw.py: frames are cropped to
/// the 160x128 canvas (cover fit, nearest neighbour), JPEG encoded at 4:4:4, and per-frame delays are folded
/// into one frame delay by repeating frames.
/// </summary>
public static class FaceEncoder
{
    public const int Width = 160;
    public const int Height = 128;
    private const int CellRows = 8;
    private const int CellCols = 10;
    private const int MinSpeedMs = 40;
    private const int MaxFrames = 255;

    public static EncodedFace Encode(string gifPath, FaceOptions options)
    {
        var gif = File.ReadAllBytes(gifPath);
        using var codec = SKCodec.Create(new SKMemoryStream(gif))
            ?? throw new InvalidDataException($"cannot decode {gifPath}");
        int count = Math.Max(1, codec.FrameCount);
        var info = new SKImageInfo(codec.Info.Width, codec.Info.Height, SKColorType.Bgra8888, SKAlphaType.Premul);

        var canvases = new List<SKBitmap>();
        var jpegs = new List<byte[]>();
        try
        {
            for (int i = 0; i < count; i++)
            {
                var bitmap = new SKBitmap(info);
                int required = count > 1 ? codec.FrameInfo[i].RequiredFrame : -1;
                if (required >= 0) canvases[required].GetPixelSpan().CopyTo(bitmap.GetPixelSpan());
                var result = codec.GetPixels(info, bitmap.GetPixels(), new SKCodecOptions(i, required));
                if (result is not (SKCodecResult.Success or SKCodecResult.IncompleteInput))
                    throw new InvalidDataException($"cannot decode frame {i} of {gifPath}: {result}");
                canvases.Add(bitmap);
                jpegs.Add(EncodeJpeg(bitmap, options.Quality));
            }

            var durations = GifDelaysMs(gif, count) ?? Enumerable.Range(0, count).Select(i => count > 1 ? codec.FrameInfo[i].Duration : 0).ToList();
            var (frames, speed) = ApplyTiming(jpegs, durations, options);
            if (speed is <= 0 or > 65535) throw new InvalidDataException($"speed must fit uint16 milliseconds, got {speed}");

            var payload = new List<byte> { 0x23, (byte)frames.Count, (byte)(speed >> 8), (byte)(speed & 0xFF), CellRows, CellCols };
            foreach (var jpeg in frames)
            {
                payload.Add(0x01);
                payload.AddRange(BitConverter.GetBytes((uint)jpeg.Length).Reverse()); // big endian length
                payload.AddRange(jpeg);
            }
            return new EncodedFace(payload.ToArray(), count, frames.Count, speed);
        }
        finally { foreach (var c in canvases) c.Dispose(); }
    }

    private static byte[] EncodeJpeg(SKBitmap source, int quality)
    {
        using var canvas = RenderCover(source);
        using var pixmap = canvas.PeekPixels();
        using var stream = new MemoryStream();
        using (var sk = new SKManagedWStream(stream))
        {
            pixmap.Encode(sk, new SKJpegEncoderOptions(quality, SKJpegEncoderDownsample.Downsample444, SKJpegEncoderAlphaOption.Ignore));
        }
        return stream.ToArray();
    }

    // Cover fit with Pillow's NEAREST sampling. The canvas is premultiplied, so reading the colour channels
    // directly is the same as compositing the frame over black.
    private static SKBitmap RenderCover(SKBitmap src)
    {
        int w = src.Width, h = src.Height;
        double scale = Math.Max((double)Width / w, (double)Height / h);
        int rw = Math.Max(1, (int)Math.Round(w * scale));
        int rh = Math.Max(1, (int)Math.Round(h * scale));
        int cx = (rw - Width) / 2, cy = (rh - Height) / 2;

        var output = new SKBitmap(new SKImageInfo(Width, Height, SKColorType.Bgra8888, SKAlphaType.Opaque));
        var from = src.GetPixelSpan();
        var to = output.GetPixelSpan();
        int fromStride = src.RowBytes, toStride = output.RowBytes;
        for (int y = 0; y < Height; y++)
        {
            int sy = Math.Min(h - 1, (int)Math.Floor((y + cy + 0.5) * h / rh));
            for (int x = 0; x < Width; x++)
            {
                int sx = Math.Min(w - 1, (int)Math.Floor((x + cx + 0.5) * w / rw));
                int s = sy * fromStride + sx * 4, d = y * toStride + x * 4;
                to[d] = from[s]; to[d + 1] = from[s + 1]; to[d + 2] = from[s + 2]; to[d + 3] = 0xFF;
            }
        }
        return output;
    }

    private static (List<byte[]> Frames, int Speed) ApplyTiming(List<byte[]> frames, List<int> durations, FaceOptions o)
    {
        var nonZero = durations.Where(d => d > 0).ToList();
        if (o.SpeedMs is { } fixedSpeed) return (frames, (int)Math.Round(fixedSpeed * o.SpeedScale));
        if (nonZero.Count == 0) return (frames, (int)Math.Round(200 * o.SpeedScale));

        var scaled = durations.Select(d => Math.Max(1, (int)Math.Round((d > 0 ? d : nonZero[0]) * o.SpeedScale))).ToList();
        int baseSpeed = Math.Max(MinSpeedMs, scaled.Aggregate(Gcd));
        var expanded = new List<byte[]>();
        for (int i = 0; i < frames.Count; i++)
            for (int r = Math.Max(1, (int)Math.Round((double)scaled[i] / baseSpeed)); r > 0; r--) expanded.Add(frames[i]);

        if (expanded.Count > MaxFrames)
            throw new InvalidDataException(
                $"GIF timing expands {frames.Count} source frames into {expanded.Count} encoded frames, " +
                $"exceeding the MiniToo {MaxFrames}-frame header limit. Simplify the GIF timing or use --speed-ms for one fixed delay.");
        return (expanded, baseSpeed);
    }

    private static int Gcd(int a, int b) => b == 0 ? a : Gcd(b, a % b);

    // Frame delays straight from the GIF's graphic control extensions (1/100 s units), in file order.
    private static List<int>? GifDelaysMs(byte[] gif, int expectedFrames)
    {
        var delays = new List<int>();
        for (int i = 0; i + 7 < gif.Length; i++)
            if (gif[i] == 0x21 && gif[i + 1] == 0xF9 && gif[i + 2] == 0x04 && gif[i + 7] == 0x00)
                delays.Add((gif[i + 4] | gif[i + 5] << 8) * 10);
        return delays.Count == expectedFrames ? delays : null;
    }
}
