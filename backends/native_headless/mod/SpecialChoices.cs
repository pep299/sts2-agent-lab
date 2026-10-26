using System.Reflection;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Screens;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Relics;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;

namespace Sts2.NativeSim.FullAppBridge;

public sealed class SpecialChoiceContext
{
    public List<LegalActionDto> Actions { get; init; } = new();
    public IReadOnlyList<IReadOnlyList<CardModel>>? Bundles { get; init; }
    public IReadOnlyList<RelicModel>? Relics { get; init; }
    public object? CrystalSphere { get; init; }
    public string? CrystalSphereVisualsUnavailable { get; init; }
}

public static class SpecialChoices
{
    public static bool HasScreen => NOverlayStack.Instance?.Peek() is NChooseABundleSelectionScreen or NChooseARelicSelection || NativeCrystalSphere.HasScreen;
    public static void Apply(Harmony harmony)
    {
        harmony.Patch(AccessTools.Method(typeof(ChooseABundleScreenHandler), "HandleAsync"), prefix: new HarmonyMethod(typeof(SpecialChoices), nameof(BundlePrefix)));
        harmony.Patch(AccessTools.Method(typeof(ChooseARelicScreenHandler), "HandleAsync"), prefix: new HarmonyMethod(typeof(SpecialChoices), nameof(RelicPrefix)));
        NativeCrystalSphere.Apply(harmony);
        // These card operations normally enter our ICardSelector. If a content path bypasses it,
        // refuse the unconnected UI rather than allowing AutoSlay's random input.
        foreach (Type type in new[] { typeof(DeckTransformScreenHandler), typeof(DeckEnchantScreenHandler), typeof(ChooseACardScreenHandler) })
            harmony.Patch(AccessTools.Method(type, "HandleAsync"), prefix: new HarmonyMethod(typeof(SpecialChoices), nameof(UnsupportedPrefix)));
    }
    private static bool BundlePrefix(CancellationToken ct, ref Task __result) { __result = Guard(Bundles(ct)); return false; }
    private static bool RelicPrefix(CancellationToken ct, ref Task __result) { __result = Guard(Relics(ct)); return false; }
    private static bool UnsupportedPrefix(object __instance, ref Task __result)
    {
        var error = new NotSupportedException("Unconnected native screen: " + __instance.GetType().Name);
        FullAppBridgeServer.Fault(error); __result = Task.FromException(error); return false;
    }
    private static async Task Guard(Task task) { try { await task; } catch (Exception error) { FullAppBridgeServer.Fault(error); throw; } }
    public static async Task<bool> Handle(CancellationToken ct, Func<Task<bool>>? handleRewards = null)
    {
        if (NOverlayStack.Instance?.Peek() is NChooseABundleSelectionScreen) { await Bundles(ct); return true; }
        if (NOverlayStack.Instance?.Peek() is NChooseARelicSelection) { await Relics(ct); return true; }
        if (NativeCrystalSphere.HasScreen) { await NativeCrystalSphere.Handle(ct, handleRewards ?? (() => Task.FromResult(false))); return true; }
        return false;
    }
    private static async Task Bundles(CancellationToken ct)
    {
        var screen = NOverlayStack.Instance?.Peek() as NChooseABundleSelectionScreen ?? throw new InvalidOperationException("Bundle screen missing");
        var bundles = UiHelper.FindAll<NCardBundle>(screen).Where(b => b.IsVisibleInTree()).ToList();
        if (bundles.Count == 0) throw new NotSupportedException("Bundle screen has no visible bundles");
        var context = new SpecialChoiceContext { Bundles = bundles.Select(b => b.Bundle).ToList(),
            Actions = bundles.Select((b, index) => new LegalActionDto { ActionId = "choose_bundle:" + index, ActionType = "choose_bundle",
                Description = "Choose bundle " + index, Metadata = new() { ["bundle_index"] = index } }).ToList() };
        string action = await FullAppBridgeServer.WaitForCoordinatorActionAsync("bundle_selection", false, false, context);
        int chosen = int.Parse(action.Split(':')[1]);
        await UiHelper.Click(bundles[chosen].Hitbox, 0);
        var confirm = UiHelper.FindFirst<NConfirmButton>(screen) ?? throw new NotSupportedException("Bundle confirmation missing");
        await WaitHelper.Until(() => confirm.IsEnabled, ct, TimeSpan.FromSeconds(10), "Bundle confirm disabled");
        await UiHelper.Click(confirm, 0);
        await WaitHelper.Until(() => !GodotObject.IsInstanceValid(screen) || !screen.IsVisibleInTree(), ct, TimeSpan.FromSeconds(15), "Bundle screen did not close");
    }
    private static async Task Relics(CancellationToken ct)
    {
        var screen = NOverlayStack.Instance?.Peek() as NChooseARelicSelection ?? throw new InvalidOperationException("Relic screen missing");
        var holders = UiHelper.FindAll<NRelicBasicHolder>(screen).Where(h => h.IsVisibleInTree()).ToList();
        var context = new SpecialChoiceContext { Relics = holders.Select(h => h.Relic.Model).ToList(),
            Actions = holders.Select((h, index) => new LegalActionDto { ActionId = "choose_relic:" + index, ActionType = "choose_relic",
                Description = "Choose " + h.Relic.Model.Id.Entry, Metadata = new() { ["relic_index"] = index, ["relic_id"] = h.Relic.Model.Id.Entry } }).ToList() };
        var skip = screen.GetNodeOrNull<NChoiceSelectionSkipButton>("SkipButton");
        if (skip?.IsEnabled == true) context.Actions.Add(new LegalActionDto { ActionId = "skip_relic", ActionType = "skip_relic", Description = "Leave relic selection" });
        string action = await FullAppBridgeServer.WaitForCoordinatorActionAsync("relic_selection", false, false, context);
        if (action == "skip_relic") await UiHelper.Click(skip!, 0);
        else await UiHelper.Click(holders[int.Parse(action.Split(':')[1])], 0);
        await WaitHelper.Until(() => !GodotObject.IsInstanceValid(screen) || !screen.IsVisibleInTree(), ct, TimeSpan.FromSeconds(15), "Relic screen did not close");
    }
}
