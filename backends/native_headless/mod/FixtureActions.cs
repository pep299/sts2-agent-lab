using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Potions;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using HarmonyLib;
using MegaCrit.Sts2.Core.Entities.Merchant;
using Godot;

namespace Sts2.NativeSim.FullAppBridge;

// Diagnostic inputs are absent unless the launcher explicitly marks a non-training fixture.
public static class FixtureActions
{
    public static bool Enabled => System.Environment.GetEnvironmentVariable("STS2_DIAGNOSTIC_FIXTURE") == "1";
    public static Dictionary<string, object?> LastResult { get; private set; } = new();
    private static readonly string[] shopRelics = ["DOLLYS_MIRROR", "GNARLED_HAMMER", "KIFUDA", "PUNCH_DAGGER", "ROYAL_STAMP"];
    private static string? pendingShopRelic;
    public static void Apply(Harmony harmony) => harmony.Patch(
        AccessTools.Method(typeof(MerchantInventory), nameof(MerchantInventory.CreateForNormalMerchant)),
        postfix: new HarmonyMethod(typeof(FixtureActions), nameof(ReplaceShopRelic)));

    private static void ReplaceShopRelic(MerchantInventory __result)
    {
        if (pendingShopRelic is not { } id) return;
        if (!Enabled) throw new NotSupportedException("Fixture inputs disabled");
        var model = ModelDb.AllRelics.Single(r => r.Id.Entry == id).ToMutable();
        var entry = __result.RelicEntries.First();
        AccessTools.Method(typeof(MerchantRelicEntry), "SetModel").Invoke(entry, [model]);
        pendingShopRelic = null;
        LastResult = new() { ["fixture"] = "merchant", ["relic_id"] = id };
    }
    public static void Add(List<LegalActionDto> actions, string phase)
    {
        if (!Enabled || phase is not ("event" or "combat")) return;
        var names = phase == "combat" ? new[] { "combat_potion" } : new[] { "grid2", "bundle", "relic", "potions", "draw_order", "merchant", "crystal_assets" };
        foreach (var name in names)
            actions.Add(new LegalActionDto { ActionId = "fixture:" + name, ActionType = "fixture", Description = "Diagnostic native fixture: " + name });
        if (phase == "event") foreach (var id in shopRelics)
            actions.Add(new LegalActionDto { ActionId = "fixture:merchant:" + id, ActionType = "fixture", Description = "Diagnostic merchant relic: " + id });
    }
    public static async Task Apply(string action)
    {
        if (!Enabled) throw new NotSupportedException("Fixture inputs disabled");
        var player = LocalContext.GetMe(RunManager.Instance!.DebugOnlyGetState())!;
        var cards = player.Deck.Cards.Take(4).ToList();
        if (action == "fixture:crystal_assets")
        {
            string output = Path.GetFullPath(Path.Combine(OS.GetUserDataDir(), "diagnostic-crystal-assets.json"));
            File.WriteAllText(output, NativeCrystalAssets.CatalogJson);
            LastResult = new() { ["fixture"] = "crystal_assets", ["catalog"] = output, ["count"] = 10 };
        }
        else if (action == "fixture:merchant" || action.StartsWith("fixture:merchant:", StringComparison.Ordinal))
        {
            string? id = action == "fixture:merchant" ? null : action["fixture:merchant:".Length..];
            if (id != null && !shopRelics.Contains(id)) throw new NotSupportedException("Unknown merchant fixture relic");
            pendingShopRelic = id;
            try
            {
                await RunManager.Instance!.EnterRoomDebug(MegaCrit.Sts2.Core.Rooms.RoomType.Shop,
                    MegaCrit.Sts2.Core.Map.MapPointType.Shop, null, showTransition: false);
                if (pendingShopRelic != null) throw new InvalidOperationException("Merchant fixture did not initialize stock");
            }
            finally { pendingShopRelic = null; }
            await FullAppBridgeMod.RunShopRoomLoopAsync(MegaCrit.Sts2.Core.Random.Rng.Chaotic, CancellationToken.None);
            LastResult = new() { ["fixture"] = "merchant", ["relic_id"] = id };
        }
        else if (action == "fixture:draw_order")
        {
            var deck = player.Deck.Cards;
            var projection = new Sts2Recorder.CardProjection();
            if (!deck.GroupBy(card => projection.SortKey(card)).Any(group => group.Count() > 1))
                throw new InvalidOperationException("Draw-order fixture needs identical card copies");
            PublicObservation.ProjectPile(deck, false);
            string before = System.Text.Json.JsonSerializer.Serialize(PublicObservation.ProjectPile(deck, true));
            string reversed = System.Text.Json.JsonSerializer.Serialize(PublicObservation.ProjectPile(deck.Reverse(), true));
            if (before != reversed) throw new InvalidOperationException("Hidden pile order changes public projection");
            LastResult = new() { ["fixture"] = "draw_order", ["permutation_invariant"] = true };
        }
        else if (action == "fixture:combat_potion")
        {
            var combat = CombatManager.Instance!.DebugOnlyGetState()!;
            foreach (var enemy in combat.HittableEnemies.ToArray()) await CreatureCmd.SetCurrentHp(enemy, 1);
            if (!(await PotionCmd.TryToProcure<ExplosiveAmpoule>(player)).success)
                throw new InvalidOperationException("Fixture potion could not be procured");
            LastResult = new() { ["fixture"] = "combat_potion" };
        }
        else if (action == "fixture:grid2")
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
