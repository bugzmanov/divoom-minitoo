using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.Rfcomm;
using Windows.Devices.Enumeration;
using Windows.Networking.Sockets;
using Windows.Storage.Streams;

namespace DvWin;

public sealed class DivoomLinkException(string message, int exitCode = 1) : Exception(message)
{
    public int ExitCode { get; } = exitCode;
}

/// <summary>
/// An open RFCOMM channel to the device. Received frames are delivered through <see cref="FrameReceived"/>
/// from a background read loop; sends are serialized.
/// </summary>
public sealed class DivoomLink : IDisposable
{
    public static readonly Guid Spp = Guid.Parse("00001101-0000-1000-8000-00805f9b34fb");

    private readonly StreamSocket _socket;
    private readonly DataReader _reader;
    private readonly DataWriter _writer;
    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private readonly FrameAssembler _assembler = new();
    private readonly CancellationTokenSource _cts = new();

    public string DeviceName { get; }
    public bool IsOpen { get; private set; }
    public event Action<byte[]>? FrameReceived;
    public event Action? Closed;

    private DivoomLink(StreamSocket socket, string deviceName)
    {
        _socket = socket;
        _reader = new DataReader(socket.InputStream) { InputStreamOptions = InputStreamOptions.Partial };
        _writer = new DataWriter(socket.OutputStream);
        DeviceName = deviceName;
        IsOpen = true;
    }

    public sealed record PairedDevice(ulong Address, string Name, bool Connected);

    public static async Task<List<PairedDevice>> ListPairedAsync()
    {
        var infos = await DeviceInformation.FindAllAsync(BluetoothDevice.GetDeviceSelectorFromPairingState(true));
        var devices = new List<PairedDevice>();
        foreach (var info in infos.OrderBy(i => i.Name))
        {
            using var dev = await BluetoothDevice.FromIdAsync(info.Id);
            if (dev != null) devices.Add(new PairedDevice(dev.BluetoothAddress, dev.Name, dev.ConnectionStatus == BluetoothConnectionStatus.Connected));
        }
        return devices;
    }

    public static async Task<DivoomLink> OpenAsync(ulong address, Guid service)
    {
        var dev = await BluetoothDevice.FromBluetoothAddressAsync(address)
            ?? throw new DivoomLinkException($"no Bluetooth device {Divoom.FormatMac(address)}. Pair it first, or check the address with `dv-win list`.");
        var found = await dev.GetRfcommServicesAsync(BluetoothCacheMode.Uncached);
        var svc = found.Services.FirstOrDefault(s => s.ServiceId.Uuid == service)
            ?? throw new DivoomLinkException($"{dev.Name} has no RFCOMM service {service} (query: {found.Error}). Is it paired and powered on?");

        var socket = new StreamSocket();
        try
        {
            await socket.ConnectAsync(svc.ConnectionHostName, svc.ConnectionServiceName,
                SocketProtectionLevel.BluetoothEncryptionAllowNullAuthentication);
        }
        catch (Exception e)
        {
            socket.Dispose();
            throw new DivoomLinkException(
                $"could not open the RFCOMM channel (0x{e.HResult:x8}: {e.Message.Trim()}).\n" +
                "The device accepts one client at a time: close the Divoom phone app, or power-cycle the device.", 2);
        }

        var link = new DivoomLink(socket, dev.Name);
        _ = link.ReadLoop();
        return link;
    }

    public async Task SendAsync(byte[] frame)
    {
        await _writeLock.WaitAsync();
        try
        {
            if (!IsOpen) throw new DivoomLinkException("the Bluetooth channel is closed.", 2);
            _writer.WriteBytes(frame);
            await _writer.StoreAsync();
        }
        catch (Exception e) when (e is not DivoomLinkException)
        {
            IsOpen = false;
            throw new DivoomLinkException($"write failed (0x{e.HResult:x8}: {e.Message.Trim()}).", 2);
        }
        finally { _writeLock.Release(); }
    }

    /// <summary>
    /// Opens the channel and checks that the device answers, reconnecting if it does not. Right after a
    /// connection the device sometimes accepts the channel but ignores what it is sent, and a command
    /// that does not expect a reply would be lost silently.
    /// </summary>
    public static async Task<DivoomLink> OpenReadyAsync(ulong address, Guid service, int settleMs = 1500, int attempts = 5, Action<string>? log = null)
    {
        for (int attempt = 1; ; attempt++)
        {
            var link = await OpenAsync(address, service);
            await Task.Delay(settleMs);
            if (await link.PingAsync()) return link;

            link.Dispose();
            log?.Invoke($"the device is not answering (attempt {attempt} of {attempts})");
            if (attempt == attempts)
                throw new DivoomLinkException("connected, but the device does not answer. Power-cycle it and try again.", 2);
            await Task.Delay(1000);
        }
    }

    /// <summary>Sends a read-only query and waits for its reply.</summary>
    public async Task<bool> PingAsync(int timeoutMs = 2000)
    {
        var answered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        void OnFrame(byte[] frame) { if (Divoom.ReplyJson(frame) is { } json && json.Contains("Device/GetStorageStatus")) answered.TrySetResult(true); }
        FrameReceived += OnFrame;
        try
        {
            await SendAsync(Divoom.JsonFrame("{\"Command\":\"Device/GetStorageStatus\"}"));
            return await Task.WhenAny(answered.Task, Task.Delay(timeoutMs)) == answered.Task;
        }
        finally { FrameReceived -= OnFrame; }
    }

    /// <summary>Asks the device for its DeviceId (`bd 2b 00`), retrying a couple of times.</summary>
    public async Task<long> QueryDeviceIdAsync(int attempts = 3)
    {
        var found = new TaskCompletionSource<long>(TaskCreationOptions.RunContinuationsAsynchronously);
        void OnFrame(byte[] frame) { if (Divoom.ReplyDeviceId(frame) is { } id) found.TrySetResult(id); }
        FrameReceived += OnFrame;
        try
        {
            for (int i = 0; i < attempts; i++)
            {
                await SendAsync(Divoom.Frame(0xBD, [0x2B, 0x00]));
                if (await Task.WhenAny(found.Task, Task.Delay(2000)) == found.Task) return found.Task.Result;
            }
        }
        finally { FrameReceived -= OnFrame; }
        throw new DivoomLinkException("the device did not report its DeviceId. Pass it with --device-id.");
    }

    private async Task ReadLoop()
    {
        try
        {
            while (!_cts.IsCancellationRequested)
            {
                uint n = await _reader.LoadAsync(4096).AsTask(_cts.Token);
                if (n == 0) break;
                var chunk = new byte[n];
                _reader.ReadBytes(chunk);
                foreach (var frame in _assembler.Feed(chunk)) FrameReceived?.Invoke(frame);
            }
        }
        catch (Exception) { /* closed or cancelled */ }
        IsOpen = false;
        Closed?.Invoke();
    }

    public void Dispose()
    {
        IsOpen = false;
        _cts.Cancel();
        _socket.Dispose();
    }
}
