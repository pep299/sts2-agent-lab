using System.Collections;
using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };
Console.SetOut(Console.Error);
try { return Serve(args, output); }
catch (Exception error) { Console.Error.WriteLine(error); return 1; }

static int Serve(string[] args, TextWriter output)
{
    if (args.Length != 4 || args[0] != "--host-dir" || args[2] != "--log")
        throw new ArgumentException("--host-dir <既存Sts2DllRecorderの出力先> --log <新しいJSONL>");
    string directory = Path.GetFullPath(args[1]);
    string log = Path.GetFullPath(args[3]);
    string gamePath = Path.Combine(directory, "sts2.dll");
    string gameHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(gamePath))).ToLowerInvariant();
    if (gameHash != "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4")
        throw new InvalidDataException("対象v0.111.0のゲームDLLと異なる");
    AssemblyLoadContext.Default.Resolving += (context, name) =>
        File.Exists(Path.Combine(directory, name.Name + ".dll"))
            ? context.LoadFromAssemblyPath(Path.Combine(directory, name.Name + ".dll")) : null;
    var recorderAssembly = Assembly.LoadFrom(Path.Combine(directory, "Sts2DllRecorder.dll"));
    var harness = Assembly.LoadFrom(Path.Combine(directory, "Lts2.Harness.dll"));
    var game = Assembly.LoadFrom(gamePath);
    var godot = Assembly.LoadFrom(Path.Combine(directory, "GodotSharp.dll"));
    var gd = godot.GetType("Godot.GD", true)!;
    gd.GetProperty("Out")!.SetValue(null, Console.Error);
    gd.GetProperty("Err")!.SetValue(null, Console.Error);
    harness.GetType("Lts2.Harness.GameRuntime", true)!.GetMethod("EnsureInitialized")!.Invoke(null, null);
    Directory.CreateDirectory(Path.GetDirectoryName(log)!);
    using var recorder = (IDisposable)Activator.CreateInstance(recorderAssembly.GetType("DllRecorder", true)!, log)!;
    var json = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    var db = game.GetType("MegaCrit.Sts2.Core.Models.ModelDb", true)!;
    var registered = Events(db);
    bool entered = false;
    Write(recorder, "fixture_host_initialized", new { fixture = true, expertData = false, gameHash });
    string? line;
    while ((line = Console.ReadLine()) is not null)
    {
        if (string.IsNullOrWhiteSpace(line)) continue;
        try
        {
            using var document = JsonDocument.Parse(line);
            var command = document.RootElement;
            string name = command.GetProperty("cmd").GetString()!;
            if (name == "close") { ValidateFields(command, "cmd"); break; }
            if (name == "inventory")
            {
                ValidateFields(command, "cmd");
                var inventory = registered.Select(pair => new
                {
                    name = pair.Key.GetType().Name, id = Get(pair.Key, "Id").ToString(),
                    category = IsAncient(pair.Key) ? "ancient" : "event", pools = pair.Value.Order().ToArray()
                }).OrderBy(row => row.name).ToArray();
                output.WriteLine(JsonSerializer.Serialize(new { fixture = true, expertData = false, gameHash, events = inventory }, json));
                continue;
            }
            if (name == "reset_event")
            {
                ValidateFields(command, "cmd", "eventName", "seed", "hp", "maxHp", "gold");
                string eventName = RequiredString(command, "eventName");
                string seed = RequiredString(command, "seed");
                var matching = registered.Keys.Where(e => e.GetType().Name == eventName || Get(e, "Id").ToString() == eventName).ToArray();
                if (matching.Length != 1) throw new ArgumentException("登録済みイベントを一意に指定できない: " + eventName);
                int hp = command.TryGetProperty("hp", out var hpNode) ? hpNode.GetInt32() : 40;
                int maxHp = command.TryGetProperty("maxHp", out var maxNode) ? maxNode.GetInt32() : 80;
                int gold = command.TryGetProperty("gold", out var goldNode) ? goldNode.GetInt32() : 100;
                if (maxHp < 1 || hp < 1 || hp > maxHp || gold < 0) throw new ArgumentOutOfRangeException("hp/maxHp/gold");
                entered = false;
                Call(recorder, "Reset", seed, "seeded_all_unlocked");
                object host = Get(recorder, "Host");
                var player = Items(Get(Get(host, "Run"), "Players")).Single();
                var creature = Get(player, "Creature");
                Call(creature, "SetMaxHpInternal", maxHp);
                Call(creature, "SetCurrentHpInternal", hp);
                var goldProperty = player.GetType().GetProperty("Gold")!;
                goldProperty.SetValue(player, Coerce(gold, goldProperty.PropertyType));
                if (matching[0].GetType().Name != "Neow") Call(host, "EnterEventDebug", matching[0]);
                entered = true;
                Write(recorder, "event_fixture_initialized", new
                {
                    fixture = true, expertData = false, eventName,
                    requested = new { hp, maxHp, gold },
                    actual = new { hp = Get(creature, "CurrentHp"), maxHp = Get(creature, "MaxHp"), gold = Get(player, "Gold") }
                });
            }
            else if (name == "step")
            {
                ValidateFields(command, "cmd", "index", "cardIndices");
                if (!entered) throw new InvalidOperationException("reset_eventが必要");
                bool hasIndex = command.TryGetProperty("index", out var index);
                bool hasCards = command.TryGetProperty("cardIndices", out var cards);
                if (hasIndex == hasCards) throw new ArgumentException("indexかcardIndicesの一方を指定");
                if (hasIndex) Call(recorder, "Step", index.GetInt32());
                else Call(recorder, "SelectCards", cards.EnumerateArray().Select(v => v.GetInt32()).ToArray());
            }
            else if (name == "observe")
            {
                ValidateFields(command, "cmd");
                if (!entered) throw new InvalidOperationException("reset_eventが必要");
            }
            else throw new ArgumentException("未対応のcmd: " + name);
            var observation = JsonSerializer.SerializeToNode(Call(recorder, "Observe"), json)!.AsObject();
            observation["capabilities"]!["fixture"] = true;
            observation["capabilities"]!["expertData"] = false;
            output.WriteLine(observation.ToJsonString(json));
        }
        catch (Exception error)
        {
            while (error is TargetInvocationException { InnerException: not null }) error = error.InnerException;
            Write(recorder, "fixture_command_error", new { fixture = true, expertData = false, error = error.ToString() });
            output.WriteLine(JsonSerializer.Serialize(new { error = error.Message, errorType = error.GetType().Name, fixture = true, expertData = false }, json));
        }
    }
    return 0;
}

static Dictionary<object, HashSet<string>> Events(Type db)
{
    var events = new Dictionary<object, HashSet<string>>();
    void Add(object model, string pool)
    {
        if (!events.TryGetValue(model, out var pools)) events[model] = pools = new();
        pools.Add(pool);
    }
    foreach (var act in Items(db.GetProperty("Acts")!.GetValue(null)!))
        foreach (var ev in Items(Get(act, "AllEvents"))) Add(ev, "act:" + Get(act, "Id"));
    foreach (string name in new[] { "AllSharedEvents", "AllAncients", "AllEvents" })
        foreach (var ev in Items(db.GetProperty(name)!.GetValue(null)!)) Add(ev, name);
    return events;
}

static object[] Items(object value) => ((IEnumerable)value).Cast<object>().ToArray();
static object Get(object value, string name) => value.GetType().GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(value)!;
static object Call(object value, string name, params object[] args)
{
    var method = value.GetType().GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
        .Single(m => m.Name == name && m.GetParameters().Count(p => !p.IsOptional) <= args.Length && m.GetParameters().Length >= args.Length);
    object?[] supplied = args.Concat(method.GetParameters().Skip(args.Length).Select(p => p.DefaultValue!)).ToArray();
    supplied = supplied.Select((argument, index) => Coerce(argument, method.GetParameters()[index].ParameterType)).ToArray();
    return method.Invoke(value, supplied)!;
}
static object? Coerce(object? value, Type target) => value is null || target.IsInstanceOfType(value)
    ? value : value is IConvertible ? Convert.ChangeType(value, Nullable.GetUnderlyingType(target) ?? target) : value;
static void Write(object recorder, string kind, object data) => Call(recorder, "Write", kind, data);
static bool IsAncient(object model)
{
    for (Type? type = model.GetType(); type is not null; type = type.BaseType)
        if (type.Name == "AncientEventModel") return true;
    return false;
}
static string RequiredString(JsonElement command, string name)
{
    string? value = command.GetProperty(name).GetString();
    return string.IsNullOrWhiteSpace(value) ? throw new ArgumentException(name + "は空にできない") : value;
}
static void ValidateFields(JsonElement command, params string[] fields)
{
    foreach (var field in command.EnumerateObject())
        if (!fields.Contains(field.Name)) throw new ArgumentException("未対応の引数: " + field.Name);
}
