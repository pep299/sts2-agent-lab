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
    if (args.Length is not (4 or 6) || args[0] != "--host-dir" || args[2] != "--log"
        || args.Length == 6 && args[4] != "--crystal-assets")
        throw new ArgumentException("--host-dir <既存Sts2DllRecorderの出力先> --log <新しいJSONL> [--crystal-assets <canonical RGBA directory>]");
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
    if (args.Length == 6) Call(recorder, "ConfigureCrystalAssets", Path.GetFullPath(args[5]));
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
            if (name is "reset_event" or "reset_shop")
            {
                bool shopFixture = name == "reset_shop";
                if (shopFixture)
                    ValidateFields(command, "cmd", "shop_relic", "seed", "hp", "maxHp", "gold", "act", "potions", "add_cards", "relics", "deck");
                else
                    ValidateFields(command, "cmd", "eventName", "seed", "hp", "maxHp", "gold", "act", "potions", "add_cards", "relics", "deck");
                string? shopRelic = shopFixture ? RequiredString(command, "shop_relic") : null;
                if (shopFixture && shopRelic is not ("DOLLYS_MIRROR" or "GNARLED_HAMMER" or "KIFUDA" or "PUNCH_DAGGER" or "ROYAL_STAMP"))
                    throw new ArgumentException("shop_relicは取得時選択5種のみ対応");
                string eventName = shopFixture ? "Neow" : RequiredString(command, "eventName");
                string seed = RequiredString(command, "seed");
                var candidates = registered.Keys.AsEnumerable();
                if (eventName is "TheArchitect" or "EVENT.THE_ARCHITECT" or "THE_ARCHITECT")
                {
                    var modelType = game.GetType("MegaCrit.Sts2.Core.Models.Events.TheArchitect", true)!;
                    var factory = db.GetMethods().Single(m => m.Name == "Event" && m.IsGenericMethodDefinition);
                    candidates = candidates.Append(factory.MakeGenericMethod(modelType).Invoke(null, null)!);
                }
                var matching = candidates.Where(e => e.GetType().Name == eventName || Get(e, "Id").ToString() == eventName
                    || Get(Get(e, "Id"), "Entry").ToString() == eventName).ToArray();
                if (matching.Length != 1) throw new ArgumentException("登録済みイベントを一意に指定できない: " + eventName);
                int hp = command.TryGetProperty("hp", out var hpNode) ? hpNode.GetInt32() : 40;
                int maxHp = command.TryGetProperty("maxHp", out var maxNode) ? maxNode.GetInt32() : 80;
                int gold = command.TryGetProperty("gold", out var goldNode) ? goldNode.GetInt32() : 100;
                int act = command.TryGetProperty("act", out var actNode) ? actNode.GetInt32() : 1;
                if (maxHp < 1 || hp < 1 || hp > maxHp || gold < 0 || act is < 1 or > 3)
                    throw new ArgumentOutOfRangeException("hp/maxHp/gold/act");
                if (matching[0].GetType().Name == "TheArchitect" && act != 3)
                    throw new ArgumentException("TheArchitectは最終Actのfixtureを指定する");
                var potions = Ids(command, "potions", allowNull: true);
                var added = Ids(command, "add_cards") ?? [];
                var relics = Ids(command, "relics") ?? [];
                var deck = Ids(command, "deck");
                entered = false;
                Call(recorder, "Reset", seed, "seeded_all_unlocked");
                object host = Get(recorder, "Host");
                object run = Get(host, "Run");
                var manager = game.GetType("MegaCrit.Sts2.Core.Runs.RunManager", true)!.GetProperty("Instance")!.GetValue(null)!;
                if (act != 1) Await(Call(manager, "EnterAct", act - 1, false));
                var player = Items(Get(run, "Players")).Single();
                foreach (var id in relics) Call(host, "ObtainRelicDebug", Model(db, "AllRelics", id!));
                if (Get(Get(host, "Selector"), "Pending") is not null || Get(host, "PendingRewards") is not null)
                    throw new ArgumentException("初期化時に追加選択を生むレリックはこのfixtureでは使用できない");
                var piles = game.GetType("MegaCrit.Sts2.Core.Commands.CardPileCmd", true)!;
                if (deck != null)
                    foreach (var card in Items(Get(Get(player, "Deck"), "Cards")))
                        Await(Static(piles, "RemoveFromDeck", card));
                var deckType = Enum.Parse(game.GetType("MegaCrit.Sts2.Core.Entities.Cards.PileType", true)!, "Deck");
                foreach (var id in (deck ?? []).Concat(added))
                    Await(Static(piles, "Add", Call(run, "CreateCard", Model(db, "AllCards", id!), player), deckType));
                if (potions != null)
                {
                    if (potions.Length > Convert.ToInt32(Get(player, "MaxPotionCount")))
                        throw new ArgumentException("ポーションの指定スロットが容量を超える");
                    var cmd = game.GetType("MegaCrit.Sts2.Core.Commands.PotionCmd", true)!;
                    foreach (var potion in Items(Get(player, "Potions"))) Await(Static(cmd, "Discard", potion));
                    for (int slot = 0; slot < potions.Length; slot++)
                        if (potions[slot] is string id)
                        {
                            var result = Await(Static(cmd, "TryToProcure", Call(Model(db, "AllPotions", id), "ToMutable"), player, slot))!;
                            if (result.GetType().GetField("success")?.GetValue(result) is not true)
                                throw new InvalidOperationException("ポーションの配置に失敗: " + slot);
                        }
                }
                var creature = Get(player, "Creature");
                Call(creature, "SetMaxHpInternal", maxHp);
                Call(creature, "SetCurrentHpInternal", hp);
                var goldProperty = player.GetType().GetProperty("Gold")!;
                goldProperty.SetValue(player, Coerce(gold, goldProperty.PropertyType));
                bool allowedBeforeEntry = (bool)Call(matching[0], "IsAllowed", run);
                var beforeEntry = new { act = Convert.ToInt32(Get(run, "CurrentActIndex")) + 1,
                    deck = Items(Get(Get(player, "Deck"), "Cards")).Select(c => Get(c, "Id").ToString()).ToArray(),
                    relics = Items(Get(player, "Relics")).Select(r => Get(r, "Id").ToString()).ToArray(),
                    potions = ((IEnumerable)Get(player, "PotionSlots")).Cast<object?>().Select(p => p == null ? null : Get(p, "Id").ToString()).ToArray() };
                object? shopInitialization = null;
                if (shopFixture)
                {
                    var roomType = Enum.Parse(game.GetType("MegaCrit.Sts2.Core.Rooms.RoomType", true)!, "Shop");
                    var pointType = Enum.Parse(game.GetType("MegaCrit.Sts2.Core.Map.MapPointType", true)!, "Shop");
                    Await(Call(manager, "EnterRoomDebug", roomType, pointType, null!, false));
                    var inventory = Get(host, "CurrentShopInventory");
                    var slot = Items(Get(inventory, "RelicEntries")).First();
                    Call(slot, "SetModel", Call(Model(db, "AllRelics", shopRelic!), "ToMutable"));
                    if (Get(Call(host, "GetState"), "Phase").ToString() != "Shop")
                        throw new InvalidOperationException("通常ショップへ入場できていない");
                    shopInitialization = new { relicId = Get(Get(slot, "Model"), "Id").ToString(),
                        cost = Get(slot, "Cost"), isStocked = Get(slot, "IsStocked"),
                        roomType = Get(run, "CurrentRoom").GetType().Name };
                }
                else if (matching[0].GetType().Name != "Neow") Call(host, "EnterEventDebug", matching[0]);
                entered = true;
                Write(recorder, shopFixture ? "shop_fixture_initialized" : "event_fixture_initialized", new
                {
                    fixture = true, expertData = false, eventName,
                    requested = new { hp, maxHp, gold, act, potions, add_cards = added, relics, deck, shop_relic = shopRelic },
                    allowedBeforeEntry, beforeEntry, shopInitialization,
                    actual = new { hp = Get(creature, "CurrentHp"), maxHp = Get(creature, "MaxHp"), gold = Get(player, "Gold") }
                });
            }
            else if (name == "step")
            {
                ValidateFields(command, "cmd", "index", "cardIndices");
                if (!entered) throw new InvalidOperationException("reset_eventまたはreset_shopが必要");
                bool hasIndex = command.TryGetProperty("index", out var index);
                bool hasCards = command.TryGetProperty("cardIndices", out var cards);
                if (hasIndex == hasCards) throw new ArgumentException("indexかcardIndicesの一方を指定");
                if (hasIndex) Call(recorder, "Step", index.GetInt32());
                else Call(recorder, "SelectCards", cards.EnumerateArray().Select(v => v.GetInt32()).ToArray());
            }
            else if (name == "observe")
            {
                ValidateFields(command, "cmd");
                if (!entered) throw new InvalidOperationException("reset_eventまたはreset_shopが必要");
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
    return Invoke(value.GetType(), value, BindingFlags.Instance, name, args);
}
static object Static(Type type, string name, params object[] args) => Invoke(type, null, BindingFlags.Static, name, args);
static object Invoke(Type type, object? instance, BindingFlags binding, string name, object[] args)
{
    var method = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | binding)
        .Single(m => m.Name == name && !m.ContainsGenericParameters
            && m.GetParameters().Count(p => !p.IsOptional) <= args.Length && m.GetParameters().Length >= args.Length
            && m.GetParameters().Take(args.Length).Select((p, i) => args[i] is null && !p.ParameterType.IsValueType
                || p.ParameterType.IsInstanceOfType(args[i])
                || args[i] is IConvertible && typeof(IConvertible).IsAssignableFrom(p.ParameterType)).All(ok => ok));
    object?[] supplied = args.Concat(method.GetParameters().Skip(args.Length).Select(p => p.DefaultValue!)).ToArray();
    supplied = supplied.Select((argument, index) => Coerce(argument, method.GetParameters()[index].ParameterType)).ToArray();
    return method.Invoke(instance, supplied)!;
}
static object? Await(object value)
{
    var task = (Task)value;
    task.GetAwaiter().GetResult();
    return task.GetType().GetProperty("Result")?.GetValue(task);
}
static object Model(Type db, string pool, string id) => Items(db.GetProperty(pool)!.GetValue(null)!)
    .Single(model => Get(Get(model, "Id"), "Entry").ToString() == id);
static string?[]? Ids(JsonElement command, string key, bool allowNull = false)
{
    if (!command.TryGetProperty(key, out var values)) return null;
    return values.EnumerateArray().Select(value => {
        if (allowNull && value.ValueKind == JsonValueKind.Null) return null;
        string id = value.ValueKind == JsonValueKind.String ? value.GetString()! : "";
        if (id.Length is < 1 or > 80 || id.Any(c => c != '_' && !char.IsAsciiLetterOrDigit(c)))
            throw new ArgumentException("モデルIDが不正: " + key);
        return id;
    }).ToArray();
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
