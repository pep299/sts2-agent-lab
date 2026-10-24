using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;

namespace Sts2.NativeSim.FullAppBridge;

internal static class EventFixture
{
    private static string? requestedEvent;
    private static int? hp, maxHp, gold;
    public static bool Pending => requestedEvent != null;

    public static void Configure(Dictionary<string, object?>? parameters, bool continuing)
    {
        if (parameters == null || !parameters.Keys.Any(k => k.StartsWith("fixture_", StringComparison.Ordinal))) return;
        if (!FixtureActions.Enabled || continuing)
            throw new NotSupportedException("Event fixtures require diagnostic mode and a fresh run");
        string[] allowed = ["fixture_event", "fixture_hp", "fixture_max_hp", "fixture_gold"];
        if (parameters.Keys.Any(k => k.StartsWith("fixture_", StringComparison.Ordinal) && !allowed.Contains(k)))
            throw new ArgumentException("Unknown event fixture parameter");
        string eventId = Text(parameters, "fixture_event");
        if (eventId.Length is < 1 or > 80 || eventId.Any(c => c != '_' && !char.IsAsciiLetterOrDigit(c)))
            throw new ArgumentException("Invalid fixture event ID");
        int? requestedHp = Number(parameters, "fixture_hp");
        int? requestedMaxHp = Number(parameters, "fixture_max_hp");
        int? requestedGold = Number(parameters, "fixture_gold");
        if (requestedHp.HasValue != requestedMaxHp.HasValue
            || requestedHp is < 1 || requestedMaxHp is < 1 || requestedGold is < 0
            || requestedHp > requestedMaxHp)
            throw new ArgumentException("Invalid fixture HP or gold");
        requestedEvent = eventId;
        hp = requestedHp;
        maxHp = requestedMaxHp;
        gold = requestedGold;
    }

    public static async Task EnterAsync()
    {
        if (requestedEvent == null) return;
        string eventId = requestedEvent;
        requestedEvent = null;
        var manager = RunManager.Instance ?? throw new InvalidOperationException("Missing fixture run manager");
        var player = LocalContext.GetMe(manager.DebugOnlyGetState())
            ?? throw new InvalidOperationException("Missing fixture player");
        var canonical = ModelDb.AllEvents.Concat(ModelDb.AllAncients.Cast<EventModel>())
            .DistinctBy(e => e.Id).SingleOrDefault(e => e.Id.Entry == eventId)
            ?? throw new ArgumentException("Unknown fixture event: " + eventId);
        if (!manager.ShouldSave)
            throw new InvalidOperationException("Fixture event requires an active run save");
        if (maxHp is int maximum) player.Creature.SetMaxHpInternal(maximum);
        if (hp is int current) player.Creature.SetCurrentHpInternal(current);
        if (gold is int amount) player.Gold = amount;
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
}
