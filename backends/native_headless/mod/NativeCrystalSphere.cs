using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Screens;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Events.Custom.CrystalSphereEvent;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Random;
using Sts2Recorder;

namespace Sts2.NativeSim.FullAppBridge;

internal static class NativeCrystalSphere
{
    private static Task? clicked;
    public static bool HasScreen => NOverlayStack.Instance?.Peek() is NCrystalSphereScreen;

    public static void Apply(Harmony harmony)
    {
        harmony.Patch(AccessTools.Method(typeof(CrystalSphereScreenHandler), "HandleAsync"),
            prefix: new HarmonyMethod(typeof(NativeCrystalSphere), nameof(HandlePrefix)));
        harmony.Patch(AccessTools.Method(typeof(NCrystalSphereScreen), "OnCellClicked"),
            postfix: new HarmonyMethod(typeof(NativeCrystalSphere), nameof(CaptureClick)));
    }

    private static bool HandlePrefix(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(Handle(ct, () => FullAppBridgeMod.HandleRewardScreenAsync(random, ct)));
        return false;
    }

    private static void CaptureClick(Task __result) => clicked = __result;
    private static async Task Guard(Task task)
    {
        try { await task; }
        catch (Exception error) { FullAppBridgeServer.Fault(error); throw; }
    }

    public static async Task Handle(CancellationToken ct, Func<Task<bool>> handleRewards)
    {
        var screen = NOverlayStack.Instance?.Peek() as NCrystalSphereScreen
            ?? throw new InvalidOperationException("Crystal Sphere screen missing");
        var game = PublicData.Field(screen, "_entity") as CrystalSphereMinigame
            ?? throw new NotSupportedException("Crystal Sphere public controls unavailable");
        var cells = UiHelper.FindAll<NCrystalSphereCell>(screen).OrderBy(c => c.Entity.Y).ThenBy(c => c.Entity.X).ToList();
        var big = screen.GetNode<NDivinationButton>("%BigDivinationButton");
        var small = screen.GetNode<NDivinationButton>("%SmallDivinationButton");
        await WaitHelper.Until(() => cells.Count == game.GridSize.X * game.GridSize.Y && big.IsEnabled && small.IsEnabled
            && game.CrystalSphereTool != CrystalSphereMinigame.CrystalSphereToolType.None,
            ct, TimeSpan.FromSeconds(15), "Crystal Sphere controls not ready");

        while (!game.IsFinished)
        {
            var available = cells.Where(c => c.Entity.IsHidden && c.IsVisibleInTree() && c.IsEnabled).ToList();
            var actions = available.Select(c => new LegalActionDto {
                ActionId = $"crystal_sphere_click:{c.Entity.X}:{c.Entity.Y}", ActionType = "crystal_sphere_click",
                Description = $"Divine cell ({c.Entity.X}, {c.Entity.Y})",
                Metadata = new() { ["col"] = c.Entity.X, ["row"] = c.Entity.Y }
            }).ToList();
            foreach (var (tool, button) in new[] { ("Big", big), ("Small", small) })
                if (game.CrystalSphereTool.ToString() != tool && button.IsEnabled && button.IsVisibleInTree())
                    actions.Add(new LegalActionDto { ActionId = "crystal_sphere_tool:" + tool, ActionType = "crystal_sphere_tool",
                        Description = "Select " + tool + " divination", Metadata = new() { ["tool"] = tool } });
            if (available.Count == 0) throw new NotSupportedException("Crystal Sphere has divinations but no visible hidden cell");
            var visuals = CrystalSphereProjection.Project(game, NativeCrystalAssets.Value);
            var context = new SpecialChoiceContext { Actions = actions, CrystalSphereVisualsUnavailable = visuals.Unavailable, CrystalSphere = new {
                width = game.GridSize.X, height = game.GridSize.Y, divinationsLeft = game.DivinationCount,
                tool = game.CrystalSphereTool.ToString(),
                hiddenCells = cells.Where(c => c.Entity.IsHidden).Select(c => new { col = c.Entity.X, row = c.Entity.Y }).ToArray(),
                revealedCells = cells.Where(c => !c.Entity.IsHidden).Select(c => new { col = c.Entity.X, row = c.Entity.Y }).ToArray(),
                visibleItems = Array.Empty<object>(), visibleFragments = visuals.VisibleFragments.Select(f => new {
                    col = f.Col, row = f.Row, width = f.Width, height = f.Height, rgbaGzipBase64 = f.RgbaGzipBase64 }).ToArray(),
                visualTemplates = visuals.VisualTemplates.Select(t => new {
                    kind = t.Kind, widthCells = t.WidthCells, heightCells = t.HeightCells,
                    width = t.Width, height = t.Height, rgbaGzipBase64 = t.RgbaGzipBase64 }).ToArray(),
                visualRepresentation = CrystalSphereProjection.Representation } };
            string chosen = await FullAppBridgeServer.WaitForCoordinatorActionAsync("crystal_sphere", false, false, context);
            string[] parts = chosen.Split(':');
            if (parts[0] == "crystal_sphere_tool")
            {
                await UiHelper.Click(parts[1] == "Big" ? big : small, 0);
                if (game.CrystalSphereTool.ToString() != parts[1]) throw new InvalidOperationException("Crystal Sphere tool did not change");
                continue;
            }
            var cell = available.Single(c => c.Entity.X == int.Parse(parts[1]) && c.Entity.Y == int.Parse(parts[2]));
            clicked = null;
            await UiHelper.Click(cell, 0);
            Task effect = clicked ?? throw new InvalidOperationException("Crystal Sphere click was not captured");
            while (!effect.IsCompleted)
                if (!await handleRewards()) await Task.Delay(20, ct);
            await effect;
        }

        while (await handleRewards()) await Task.Delay(20, ct);
        if (!GodotObject.IsInstanceValid(screen) || !screen.IsInsideTree()) return;
        var proceed = screen.GetNode<NProceedButton>("%ProceedButton");
        await WaitHelper.Until(() => proceed.IsEnabled && proceed.IsVisibleInTree(), ct, TimeSpan.FromSeconds(15), "Crystal Sphere proceed not ready");
        await UiHelper.Click(proceed, 0);
        await WaitHelper.Until(() => !GodotObject.IsInstanceValid(screen) || !screen.IsVisibleInTree()
            || NMapScreen.Instance?.IsVisibleInTree() == true, ct, TimeSpan.FromSeconds(15), "Crystal Sphere did not finish");
        if (GodotObject.IsInstanceValid(screen) && NOverlayStack.Instance?.Peek() == screen && NMapScreen.Instance?.IsVisibleInTree() == true)
            NOverlayStack.Instance.Remove(screen);
    }
}
