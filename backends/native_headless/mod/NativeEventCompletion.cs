using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Events;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Runs;

namespace Sts2.NativeSim.FullAppBridge;

public static class NativeEventCompletion
{
    private static readonly object Gate = new();
    private static EventOption? expected;
    private static TaskCompletionSource<Task>? accepted;
    private static IReadOnlyList<NEventOptionButton>? buttons;

    public static void SetButtons(IReadOnlyList<NEventOptionButton>? value) => buttons = value;

    public static bool IsButtonReady(int index) => buttons != null && index >= 0 && index < buttons.Count
        && GodotObject.IsInstanceValid(buttons[index]) && buttons[index].IsVisibleInTree()
        && buttons[index].IsEnabled && buttons[index].Option is { IsLocked: false };

    public static void Apply(Harmony harmony)
    {
        var chosen = AccessTools.Method(typeof(EventOption), nameof(EventOption.Chosen), Type.EmptyTypes)
            ?? throw new NotSupportedException("Native event option task unavailable");
        harmony.Patch(chosen, postfix: new HarmonyMethod(typeof(NativeEventCompletion), nameof(Chosen)));
    }

    private static void Chosen(EventOption __instance, Task __result)
    {
        lock (Gate)
            if (ReferenceEquals(expected, __instance)) accepted?.TrySetResult(__result);
    }

    public static async Task<Task> ClickAndCapture(NEventOptionButton button, CancellationToken ct)
    {
        var receipt = new TaskCompletionSource<Task>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (Gate)
        {
            if (accepted != null) throw new InvalidOperationException("Overlapping native event choice");
            expected = button.Option;
            accepted = receipt;
        }
        try
        {
            await UiHelper.Click(button, 0);
            await WaitHelper.Until(() => receipt.Task.IsCompleted, ct, TimeSpan.FromSeconds(15),
                "Native event option was not accepted");
            return await receipt.Task;
        }
        finally
        {
            lock (Gate) { expected = null; accepted = null; }
        }
    }

    public static async Task CompleteLethalProceedAsync(EventOption option, CancellationToken ct)
    {
        var manager = RunManager.Instance ?? throw new InvalidOperationException("Missing event run manager");
        var run = manager.DebugOnlyGetState() ?? throw new InvalidOperationException("Missing event run state");
        var player = LocalContext.GetMe(run) ?? throw new InvalidOperationException("Missing event player");
        if (!option.IsProceed || option.WillKillPlayer?.Invoke(player) != true || run.IsGameOver) return;

        NAbandonRunConfirmPopup? Popup() => UiHelper.FindAll<NAbandonRunConfirmPopup>(((SceneTree)Engine.GetMainLoop()).Root)
            .SingleOrDefault(p => GodotObject.IsInstanceValid(p) && p.IsVisibleInTree());
        await WaitHelper.Until(() => run.IsGameOver || Popup() != null, ct, TimeSpan.FromSeconds(15),
            "Lethal proceed did not reach death or an abandon confirmation");
        if (run.IsGameOver) return;
        var popup = Popup() ?? throw new InvalidOperationException("Abandon confirmation disappeared");
        var controls = UiHelper.FindFirst<NVerticalPopup>(popup)
            ?? throw new NotSupportedException("Abandon confirmation controls unavailable");
        await WaitHelper.Until(() => GodotObject.IsInstanceValid(popup) && controls.YesButton.IsEnabled,
            ct, TimeSpan.FromSeconds(10), "Abandon confirmation is not ready");
        await UiHelper.Click(controls.YesButton, 0);
        await WaitHelper.Until(() => manager.IsAbandoned && run.IsGameOver, ct, TimeSpan.FromSeconds(15),
            "Confirmed abandon did not end the selected run");
    }
}
