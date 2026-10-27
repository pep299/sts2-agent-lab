using HarmonyLib;
using MegaCrit.Sts2.Core.Runs;

namespace Sts2.NativeSim.FullAppBridge;

internal static class NativeRunOutcome
{
    private static RunState? endedRun;
    private static bool endedVictory;

    public static void Apply(Harmony harmony) => harmony.Patch(AccessTools.Method(typeof(RunManager), "OnEnded"),
        postfix: new HarmonyMethod(typeof(NativeRunOutcome), nameof(Record)));

    private static void Record(RunManager __instance, bool __0)
    {
        var run = __instance.DebugOnlyGetState();
        if (run == null || ReferenceEquals(run, endedRun)) return;
        // WinRunはプレイヤーを死亡させる前に勝利を記録する。後続の死亡通知では結果を置き換えない。
        endedRun = run;
        endedVictory = __0;
    }

    public static bool IsVictory(RunState run) => run.IsGameOver &&
        (ReferenceEquals(run, endedRun) ? endedVictory : RunManager.Instance!.WinTime > 0);
}
