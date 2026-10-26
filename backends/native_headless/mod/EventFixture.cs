using System.Text.Json;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Events;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;

namespace Sts2.NativeSim.FullAppBridge;

internal static class EventFixture
{
    private static string? requestedEvent;
    private static int? hp, maxHp, gold, act;
    private static string?[]? potions;
    private static string[] addCards = [], relics = [];
    private static string[]? deck;
    public static bool Pending => requestedEvent != null;
    public static object? Initialization { get; private set; }

    public static void Configure(Dictionary<string, object?>? parameters, bool continuing)
    {
        if (parameters == null || !parameters.Keys.Any(k => k.StartsWith("fixture_", StringComparison.Ordinal))) return;
        if (!FixtureActions.Enabled || continuing)
            throw new NotSupportedException("Event fixtures require diagnostic mode and a fresh run");
        string[] allowed = ["fixture_event", "fixture_hp", "fixture_max_hp", "fixture_gold", "fixture_act",
            "fixture_potions", "fixture_add_cards", "fixture_relics", "fixture_deck"];
        if (parameters.Keys.Any(k => k.StartsWith("fixture_", StringComparison.Ordinal) && !allowed.Contains(k)))
            throw new ArgumentException("Unknown event fixture parameter");
        string eventId = Text(parameters, "fixture_event");
        if (eventId.Length is < 1 or > 80 || eventId.Any(c => c != '_' && !char.IsAsciiLetterOrDigit(c)))
            throw new ArgumentException("Invalid fixture event ID");
        int? requestedHp = Number(parameters, "fixture_hp");
        int? requestedMaxHp = Number(parameters, "fixture_max_hp");
        int? requestedGold = Number(parameters, "fixture_gold");
        int? requestedAct = Number(parameters, "fixture_act");
        if (eventId == "THE_ARCHITECT" && requestedAct != 3)
            throw new ArgumentException("The Architect fixture requires explicit act=3");
        if (requestedHp.HasValue != requestedMaxHp.HasValue
            || requestedHp is < 1 || requestedMaxHp is < 1 || requestedGold is < 0
            || requestedHp > requestedMaxHp || requestedAct is < 1 or > 3)
            throw new ArgumentException("Invalid fixture HP, gold or act");
        hp = requestedHp;
        maxHp = requestedMaxHp;
        gold = requestedGold;
        act = requestedAct;
        potions = Ids(parameters, "fixture_potions", allowNull: true);
        addCards = Ids(parameters, "fixture_add_cards")?.Select(id => id!).ToArray() ?? [];
        relics = Ids(parameters, "fixture_relics")?.Select(id => id!).ToArray() ?? [];
        deck = Ids(parameters, "fixture_deck")?.Select(id => id!).ToArray();
        requestedEvent = eventId;
    }

    public static async Task EnterAsync()
    {
        if (requestedEvent == null) return;
        string eventId = requestedEvent;
        requestedEvent = null;
        var manager = RunManager.Instance ?? throw new InvalidOperationException("Missing fixture run manager");
        var player = LocalContext.GetMe(manager.DebugOnlyGetState())
            ?? throw new InvalidOperationException("Missing fixture player");
        var canonical = ModelDb.AllEvents.Concat(ModelDb.AllAncients.Cast<EventModel>()).Append(ModelDb.Event<TheArchitect>())
            .DistinctBy(e => e.Id).SingleOrDefault(e => e.Id.Entry == eventId)
            ?? throw new ArgumentException("Unknown fixture event: " + eventId);
        if (!manager.ShouldSave)
            throw new InvalidOperationException("Fixture event requires an active run save");
        var run = manager.DebugOnlyGetState() ?? throw new InvalidOperationException("Missing fixture run state");
        var cardIds = (deck ?? []).Concat(addCards).ToArray();
        var cards = cardIds.Select(id => ModelDb.AllCards.SingleOrDefault(c => c.Id.Entry == id)
            ?? throw new ArgumentException("Unknown fixture card: " + id)).ToArray();
        var requestedRelics = relics.Select(id => ModelDb.AllRelics.SingleOrDefault(r => r.Id.Entry == id)
            ?? throw new ArgumentException("Unknown fixture relic: " + id)).ToArray();
        var requestedPotions = potions?.Select(id => id == null ? null : ModelDb.AllPotions.SingleOrDefault(p => p.Id.Entry == id)
            ?? throw new ArgumentException("Unknown fixture potion: " + id)).ToArray();
        if (act is int actNumber && actNumber != run.CurrentActIndex + 1)
            await manager.EnterAct(actNumber - 1, doTransition: false);
        foreach (var relic in requestedRelics) await RelicCmd.Obtain(relic.ToMutable(), player);
        if (deck != null) await CardPileCmd.RemoveFromDeck(player.Deck.Cards.ToArray());
        foreach (var card in cards) await CardPileCmd.Add(run.CreateCard(card, player), PileType.Deck);
        if (requestedPotions != null)
        {
            if (requestedPotions.Length > player.MaxPotionCount) throw new ArgumentException("Fixture potion slots exceed capacity");
            foreach (var potion in player.Potions.ToArray()) await PotionCmd.Discard(potion);
            for (int slot = 0; slot < requestedPotions.Length; slot++)
                if (requestedPotions[slot] is { } potion && !(await PotionCmd.TryToProcure(potion.ToMutable(), player, slot)).success)
                    throw new InvalidOperationException("Fixture potion could not be procured at slot " + slot);
        }
        if (maxHp is int maximum) player.Creature.SetMaxHpInternal(maximum);
        if (hp is int current) player.Creature.SetCurrentHpInternal(current);
        if (gold is int amount) player.Gold = amount;
        Initialization = new { requestedEvent = eventId, allowedBeforeEntry = canonical.IsAllowed(run),
            act = run.CurrentActIndex + 1, hp = player.Creature.CurrentHp, maxHp = player.Creature.MaxHp, gold = player.Gold,
            deck = player.Deck.Cards.Select(c => c.Id.Entry).ToArray(), relics = player.Relics.Select(r => r.Id.Entry).ToArray(),
            potions = player.PotionSlots.Select(p => p?.Id.Entry).ToArray() };
        await manager.EnterRoomDebug(RoomType.Event, MapPointType.Unassigned, canonical, showTransition: false);
        if (manager.DebugOnlyGetState()?.BaseRoom is not EventRoom room || room.CanonicalEvent.Id != canonical.Id)
            throw new InvalidOperationException("Fixture entered a different event room");
        await SaveManager.Instance.SaveRun(preFinishedRoom: null, saveProgress: false);
    }

    private static string Text(Dictionary<string, object?> parameters, string key) =>
        parameters.TryGetValue(key, out var value) ? value?.ToString() ?? "" : "";

    private static int? Number(Dictionary<string, object?> parameters, string key) =>
        !parameters.ContainsKey(key) ? null : int.TryParse(Text(parameters, key), out int value)
            ? value : throw new ArgumentException("Invalid fixture integer: " + key);

    private static string?[]? Ids(Dictionary<string, object?> parameters, string key, bool allowNull = false)
    {
        if (!parameters.TryGetValue(key, out var value)) return null;
        var json = JsonSerializer.SerializeToElement(value);
        if (json.ValueKind != JsonValueKind.Array) throw new ArgumentException("Fixture field must be an array: " + key);
        return json.EnumerateArray().Select(item => {
            if (allowNull && item.ValueKind == JsonValueKind.Null) return null;
            string id = item.ValueKind == JsonValueKind.String ? item.GetString()! : "";
            if (id.Length is < 1 or > 80 || id.Any(c => c != '_' && !char.IsAsciiLetterOrDigit(c)))
                throw new ArgumentException("Invalid fixture model ID: " + key);
            return id;
        }).ToArray();
    }
}
