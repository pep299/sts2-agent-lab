using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Events;
using MegaCrit.Sts2.Core.Nodes.Events;

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
}
