using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using MegaCrit.Sts2.Core.AutoSlay;

namespace Sts2.NativeSim.FullAppBridge;

public static class FullAppBridgeServer
{
    private static readonly object Gate = new();
    private static readonly HashSet<string> Requests = new(StringComparer.Ordinal);
    private static TaskCompletionSource<string>? pendingAction;
    private static TaskCompletionSource<object>? nextBoundary;
    private static object? snapshot;
    private static CardSelectContext? selection;
    private static long decisionId;
    private static bool inFlight, connected;
    private static readonly string InstanceId = Guid.NewGuid().ToString("N");
    public static int BoundPort { get; private set; }
    public static ObservationDto? CurrentObservation { get; private set; }
    public static List<LegalActionDto> CurrentLegalActions { get; private set; } = new();
    public static List<string> ActionHistory { get; } = new();
    public static string RequestedSeed { get; private set; } = "";
    public static string RequestedCharacter { get; private set; } = "IRONCLAD";
    public static int RequestedAscension { get; private set; } = -1;
    public static bool ContinueRequested { get; private set; }
    public static bool IsRunStarted { get; private set; }
    private static TaskCompletionSource<T> Completion<T>() => new(TaskCreationOptions.RunContinuationsAsynchronously);

    public static void Start(int preferredPort, string portFilePath)
    {
        var expected = Environment.GetEnvironmentVariable("STS2_EXPECTED_USERDATA")
            ?? throw new InvalidOperationException("STS2_EXPECTED_USERDATA is required");
        var actual = Path.GetFullPath(Godot.ProjectSettings.GlobalizePath("user://"));
        if (actual.TrimEnd('/') != Path.GetFullPath(expected).TrimEnd('/'))
            throw new InvalidOperationException($"User-data isolation mismatch: {actual}");
        var listener = new TcpListener(IPAddress.Loopback, preferredPort);
        listener.Start();
        BoundPort = ((IPEndPoint)listener.LocalEndpoint).Port;
        Directory.CreateDirectory(Path.GetDirectoryName(portFilePath)!);
        File.WriteAllText(portFilePath, BoundPort.ToString());
        _ = Task.Run(async () =>
        {
            while (true)
            {
                var client = await listener.AcceptTcpClientAsync();
                lock (Gate)
                {
                    if (connected) { client.Dispose(); continue; }
                    connected = true;
                }
                _ = Serve(client);
            }
        });
    }

    private static async Task Serve(TcpClient client)
    {
        using (client)
        using (var stream = client.GetStream())
        using (var reader = new StreamReader(stream, Encoding.UTF8))
        using (var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true })
        {
            try
            {
                while (await reader.ReadLineAsync() is string line)
                {
                    RpcRequest? request = null;
                    RpcResponse response;
                    try
                    {
                        if (line.Length > 1024 * 1024) throw new ArgumentException("Request too large");
                        request = JsonSerializer.Deserialize<RpcRequest>(line) ?? throw new ArgumentException("Missing request");
                        response = new RpcResponse { Id = request.Id, Result = await Dispatch(request.Method, request.Params) };
                    }
                    catch (Exception ex) { response = new RpcResponse { Id = request?.Id ?? 0, Error = ex.ToString() }; }
                    await writer.WriteLineAsync(JsonSerializer.Serialize(response));
                }
            }
            catch (IOException) { }
            finally { lock (Gate) connected = false; }
        }
    }

    private static string Text(Dictionary<string, object?>? p, string key) =>
        p != null && p.TryGetValue(key, out var value) ? value?.ToString() ?? "" : "";
    private static long Number(Dictionary<string, object?>? p, string key) =>
        long.TryParse(Text(p, key), out var value) ? value : throw new ArgumentException($"Missing integer: {key}");
    private static object ReadBoundary()
    {
        lock (Gate)
        {
            if (inFlight) throw new InvalidOperationException("An action is still resolving");
            return snapshot ?? throw new InvalidOperationException("No decision boundary");
        }
    }

    public static void Fault(Exception error)
    {
        lock (Gate)
        {
            inFlight = true;
            nextBoundary?.TrySetException(error);
            pendingAction?.TrySetException(error);
        }
        Godot.GD.PrintErr("HEADLESS_ENVIRONMENT_FAULT: " + error);
    }

    private static async Task<object?> Dispatch(string method, Dictionary<string, object?>? parameters)
    {
        switch (method)
        {
            case "hello":
                return new { protocol = "native-headless-1", instance_id = InstanceId, pid = Environment.ProcessId,
                    bound_port = BoundPort, user_data = Path.GetFullPath(Godot.ProjectSettings.GlobalizePath("user://")),
                    game_sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(MegaCrit.Sts2.Core.Runs.RunManager).Assembly.Location))).ToLowerInvariant(),
                    test_mode = MegaCrit.Sts2.Core.TestSupport.TestMode.IsOn,
                    non_interactive = MegaCrit.Sts2.Core.Helpers.NonInteractiveMode.IsActive,
                    time_scale = Godot.Engine.TimeScale, max_fps = Godot.Engine.MaxFps };
            case "start_run":
            {
                Task<object> ready;
                lock (Gate)
                {
                    if (IsRunStarted) throw new InvalidOperationException("One run per process; start already accepted");
                    RequestedSeed = Text(parameters, "seed");
                    if (RequestedSeed.Length == 0 || RequestedSeed.Length > 64 || RequestedSeed.Any(c => !char.IsAsciiLetterOrDigit(c)))
                        throw new ArgumentException("Seed must be 1-64 ASCII letters or digits");
                    if (Text(parameters, "character") != "IRONCLAD" || Number(parameters, "ascension") != 0)
                        throw new NotSupportedException("Only solo Ironclad A0 is qualified");
                    RequestedAscension = 0;
                    ContinueRequested = Text(parameters, "continue").Equals("true", StringComparison.OrdinalIgnoreCase);
                    nextBoundary = Completion<object>(); ready = nextBoundary.Task;
                    IsRunStarted = true; inFlight = true;
                }
                return await ready;
            }
            case "observe": return ReadBoundary();
            case "step":
            {
                Task<object> ready;
                TaskCompletionSource<string> action;
                var actionId = Text(parameters, "action_id");
                lock (Gate)
                {
                    if (inFlight || pendingAction == null) throw new InvalidOperationException("No input is currently accepted");
                    if (Number(parameters, "decision_id") != decisionId) throw new ArgumentException("Stale decision_id");
                    string requestId = Text(parameters, "request_id");
                    if (requestId.Length is < 1 or > 128 || Requests.Contains(requestId)) throw new ArgumentException("Missing or duplicate request_id");
                    if (CurrentObservation?.IsTerminal != false) throw new InvalidOperationException("Terminal boundary");
                    ValidateAction(actionId);
                    Requests.Add(requestId);
                    nextBoundary = Completion<object>(); ready = nextBoundary.Task;
                    inFlight = true; action = pendingAction; pendingAction = null;
                    ActionHistory.Add(actionId);
                }
                action.SetResult(actionId);
                return await ready;
            }
            case "diagnostic_snapshot":
                if (Environment.GetEnvironmentVariable("STS2_PRIVATE_DIAGNOSTICS") != "1") throw new NotSupportedException("Private diagnostics disabled");
                lock (Gate) return new { observation = CurrentObservation, legal_actions = CurrentLegalActions, actions = ActionHistory.ToArray() };
            case "close":
                _ = Task.Run(async () => { await Task.Delay(50); Godot.Callable.From(() => ((Godot.SceneTree)Godot.Engine.GetMainLoop()).Quit(0)).CallDeferred(); });
                return new { closed = true };
            default: throw new NotSupportedException($"Unsupported RPC method: {method}");
        }
    }

    private static void ValidateAction(string actionId)
    {
        if (selection != null)
        {
            if (actionId.StartsWith("choose_cards:", StringComparison.Ordinal))
            {
                SelectionValidation.Parse(actionId, selection.Cards.Count, selection.MinSelect, selection.MaxSelect);
                return;
            }
            if (selection.MinSelect > 1 || selection.MaxSelect < 1) throw new ArgumentException("This choice requires explicit indices");
        }
        if (!CurrentLegalActions.Any(a => a.ActionId == actionId)) throw new ArgumentException("Action is not a current legal candidate");
    }

    public static async Task<string> WaitForCoordinatorActionAsync(string phase, bool isTerminal, bool isVictory, object? contextObject = null)
    {
        while (true)
        {
            AutoSlayer.CurrentWatchdog?.Reset($"Bridge:{phase}");
            var (raw, actions) = FullAppStateTracker.CreateStateSnapshot(phase, isTerminal, isVictory, contextObject);
            if (contextObject is SpecialChoiceContext special) actions = special.Actions;
            if (isTerminal) actions.Clear();
            else PotionActions.Add(actions, phase);
            FixtureActions.Add(actions, phase);
            var publicObservation = PublicObservation.Capture(raw, actions, contextObject);
            Task<string>? waiting = null;
            lock (Gate)
            {
                if (pendingAction != null) throw new InvalidOperationException("Overlapping native decision boundaries");
                CurrentObservation = raw; CurrentLegalActions = actions;
                selection = contextObject as CardSelectContext;
                decisionId++;
                if (!isTerminal) { pendingAction = Completion<string>(); waiting = pendingAction.Task; }
                snapshot = new { decision_id = decisionId, observation = publicObservation };
                inFlight = false;
                var completion = nextBoundary; nextBoundary = null;
                completion?.TrySetResult(snapshot);
            }
            if (isTerminal) return "terminal_halt";
            string chosen = await waiting!;
            if (chosen.StartsWith("fixture:", StringComparison.Ordinal)) { await FixtureActions.Apply(chosen); continue; }
            if (PotionActions.IsPotion(chosen))
            {
                await PotionActions.Apply(chosen);
                // 古い戦闘の判断を作り直さず、部屋ハンドラーの報酬・終端処理へ戻す。
                if (phase == "combat" && MegaCrit.Sts2.Core.Combat.CombatManager.Instance?.IsInProgress != true)
                    return "combat_finished";
                continue;
            }
            return chosen;
        }
    }
}

public static class SelectionValidation
{
    public static int[] Parse(string actionId, int count, int min, int max)
    {
        if (!actionId.StartsWith("choose_cards:", StringComparison.Ordinal)) throw new ArgumentException("Expected choose_cards");
        string text = actionId["choose_cards:".Length..];
        int[] indices = text.Length == 0 ? Array.Empty<int>() : text.Split(',').Select(s =>
            int.TryParse(s, out int i) ? i : throw new ArgumentException("Noninteger card index")).ToArray();
        if (indices.Length < min || indices.Length > max || indices.Distinct().Count() != indices.Length || indices.Any(i => i < 0 || i >= count))
            throw new ArgumentException("Invalid card selection cardinality, duplicate, or index");
        return indices;
    }
}
