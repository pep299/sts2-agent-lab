using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Potions;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;

namespace Sts2.NativeSim.FullAppBridge;

// Diagnostic inputs are absent unless the launcher explicitly marks a non-training fixture.
public static class FixtureActions
{
    public static bool Enabled => Environment.GetEnvironmentVariable("STS2_DIAGNOSTIC_FIXTURE") == "1";
    public static Dictionary<string, object?> LastResult { get; private set; } = new();
    public static void Add(List<LegalActionDto> actions, string phase)
    {
        if (!Enabled || phase != "event") return;
        foreach (var name in new[] { "grid2", "bundle", "relic", "potions" })
            actions.Add(new LegalActionDto { ActionId = "fixture:" + name, ActionType = "fixture", Description = "Diagnostic native fixture: " + name });
    }
    public static async Task Apply(string action)
    {
        if (!Enabled) throw new NotSupportedException("Fixture inputs disabled");
        var player = LocalContext.GetMe(RunManager.Instance!.DebugOnlyGetState())!;
        var cards = player.Deck.Cards.Take(4).ToList();
        if (action == "fixture:grid2")
        {
            var context = new CardSelectContext { Purpose = "diagnostic_selector_two_cards", MinSelect = 2, MaxSelect = 2, Cards = cards };
            string selected = await FullAppBridgeServer.WaitForCoordinatorActionAsync("card_select", false, false, context);
            var indices = SelectionValidation.Parse(selected, cards.Count, 2, 2);
            LastResult = new() { ["fixture"] = "grid2", ["indices"] = indices, ["card_ids"] = indices.Select(i => cards[i].Id.Entry).ToArray() };
        }
        else if (action == "fixture:bundle")
        {
            IReadOnlyList<IReadOnlyList<CardModel>> bundles = new[] { (IReadOnlyList<CardModel>)cards.Take(2).ToArray(), cards.Skip(2).Take(2).ToArray() };
            var screen = NChooseABundleSelectionScreen.ShowScreen(bundles);
            var selecting = screen.CardsSelected();
            await SpecialChoices.Handle(CancellationToken.None);
            var result = (await selecting).Single();
            LastResult = new() { ["fixture"] = "bundle", ["card_ids"] = result.Select(c => c.Id.Entry).ToArray() };
        }
        else if (action == "fixture:relic")
        {
            var screen = NChooseARelicSelection.ShowScreen(player.Relics.ToList()) ?? throw new InvalidOperationException("Relic fixture screen missing");
            var selecting = screen.RelicsSelected();
            await SpecialChoices.Handle(CancellationToken.None);
            LastResult = new() { ["fixture"] = "relic", ["relic_ids"] = (await selecting).Select(r => r.Id.Entry).ToArray() };
        }
        else if (action == "fixture:potions")
        {
            if (!player.HasOpenPotionSlots) throw new InvalidOperationException("Fixture potion space unavailable");
            await PotionCmd.TryToProcure<FruitJuice>(player);
            await PotionCmd.TryToProcure<StrengthPotion>(player);
            LastResult = new() { ["fixture"] = "potions", ["potion_ids"] = player.Potions.Select(p => p.Id.Entry).ToArray() };
        }
        else throw new NotSupportedException("Unknown diagnostic fixture");
    }
}
