using System.Reflection;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Models;

namespace Sts2.NativeSim.FullAppBridge;

// spire-jev: every card selection the game makes through its selector —
// the smith's upgrade, a shop removal, an event's transform or enchant,
// True Grit+ or Burning Pact choosing from the hand — goes to the
// coordinator as a "card_select" decision instead of AutoSlay's random pick.
// What the selection is for is the name of the CardSelectCmd method that
// asked (FromDeckForRemoval, FromDeckForUpgrade, FromHand, ...).
public sealed class CardSelectContext
{
    public string Purpose { get; init; } = "";
    public int MinSelect { get; init; }
    public int MaxSelect { get; init; }
    public List<CardModel> Cards { get; init; } = new();
}

public static class CardSelectBridge
{
    private static string _purpose = "";

    public static void Apply(Harmony harmony)
    {
        MethodInfo setPurpose = AccessTools.Method(typeof(CardSelectBridge), nameof(SetPurpose));
        foreach (MethodInfo method in typeof(CardSelectCmd).GetMethods(BindingFlags.Public | BindingFlags.Static))
        {
            if (!method.Name.StartsWith("From", StringComparison.Ordinal)) continue;
            try { harmony.Patch(method, prefix: new HarmonyMethod(setPurpose)); }
            catch (Exception ex) { Godot.GD.PrintErr($"[FullAppBridge] card select purpose {method.Name}: {ex.Message}"); }
        }
        try
        {
            MethodInfo? select = AccessTools.Method(typeof(AutoSlayCardSelector), nameof(AutoSlayCardSelector.GetSelectedCards));
            if (select != null) harmony.Patch(select, prefix: new HarmonyMethod(AccessTools.Method(typeof(CardSelectBridge), nameof(HandleGetSelectedCards))));
        }
        catch (Exception ex) { Godot.GD.PrintErr($"[FullAppBridge] card selector: {ex.Message}"); }
    }

    private static void SetPurpose(MethodBase __originalMethod)
    {
        _purpose = __originalMethod.Name;
    }

    private static bool HandleGetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect, ref Task<IEnumerable<CardModel>> __result)
    {
        __result = SelectAsync(options.ToList(), minSelect, maxSelect);
        return false;
    }

    /// <summary>Selections waiting on the planner: an event's options are hidden meanwhile (FullAppBridgeMod's event loop waits).</summary>
    public static int Pending;

    private static async Task<IEnumerable<CardModel>> SelectAsync(List<CardModel> cards, int minSelect, int maxSelect)
    {
        string purpose = _purpose;
        _purpose = "";
        if (cards.Count == 0) return Array.Empty<CardModel>();
        var context = new CardSelectContext { Purpose = purpose, MinSelect = minSelect, MaxSelect = maxSelect, Cards = cards };
        string actionId;
        Interlocked.Increment(ref Pending);
        try
        {
            actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("card_select", isTerminal: false, isVictory: false, context);
        }
        finally
        {
            Interlocked.Decrement(ref Pending);
        }

        int[] indices = actionId.StartsWith("choose_cards:", StringComparison.Ordinal)
            ? SelectionValidation.Parse(actionId, cards.Count, minSelect, maxSelect)
            : SelectionValidation.Parse("choose_cards:" + actionId.Split(':')[1], cards.Count, minSelect, maxSelect);
        return indices.Select(i => cards[i]).ToArray();
    }
}
