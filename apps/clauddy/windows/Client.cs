using System.Diagnostics;
using System.IO.Pipes;

namespace Clauddy;

/// <summary>Talks to the daemon, starting it in the background when it is not running.</summary>
public static class Client
{
    /// <summary>Sends one command and returns the reply, or null when the daemon cannot be reached.</summary>
    public static async Task<string?> SendAsync(string command, bool startDaemon = true)
    {
        // Nothing to wait for when the daemon is not running and we are not going to start it.
        if (!startDaemon && !File.Exists($@"\\.\pipe\{Daemon.PipeName}")) return null;

        var pipe = await TryConnect(250);
        if (pipe == null && startDaemon)
        {
            StartDaemon();
            for (int i = 0; i < 80 && pipe == null; i++) pipe = await TryConnect(100);
        }
        if (pipe == null) return null;

        using (pipe)
        {
            try
            {
                var writer = new StreamWriter(pipe) { AutoFlush = true };
                await writer.WriteLineAsync(command);
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                return await new StreamReader(pipe).ReadLineAsync(cts.Token);
            }
            catch (Exception e) when (e is IOException or OperationCanceledException) { return null; }
        }
    }

    private static async Task<NamedPipeClientStream?> TryConnect(int timeoutMs)
    {
        var pipe = new NamedPipeClientStream(".", Daemon.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
        try { await pipe.ConnectAsync(timeoutMs); return pipe; }
        catch (Exception e) when (e is TimeoutException or IOException) { pipe.Dispose(); return null; }
    }

    [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int stdHandle);

    [System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);

    // Whoever runs a hook reads its output until every holder of the pipe has closed it. Redirecting the
    // daemon's stdio is not enough: Windows still hands a child every inheritable handle of its parent, the
    // hook's stdout pipe included, which would keep Claude Code waiting for as long as the daemon lives.
    private static void KeepStdioPrivate()
    {
        foreach (var std in new[] { -10, -11, -12 }) // stdin, stdout, stderr
        {
            var handle = GetStdHandle(std);
            if (handle != IntPtr.Zero && handle != new IntPtr(-1)) SetHandleInformation(handle, 1 /* HANDLE_FLAG_INHERIT */, 0);
        }
    }

    // The daemon's own stdio goes to fresh pipes that nobody reads; it logs to a file.
    private static void StartDaemon()
    {
        KeepStdioPrivate();
        var host = Environment.ProcessPath!;
        bool viaDotnet = Path.GetFileNameWithoutExtension(host).Equals("dotnet", StringComparison.OrdinalIgnoreCase);
        var info = new ProcessStartInfo(host)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        if (viaDotnet) info.ArgumentList.Add(typeof(Client).Assembly.Location);
        info.ArgumentList.Add("daemon");
        Process.Start(info)?.Dispose();
    }
}
