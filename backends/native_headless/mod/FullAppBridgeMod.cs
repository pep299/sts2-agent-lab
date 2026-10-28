using System.Linq;
using System.Reflection;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Rooms;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Screens;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.RestSite;
using MegaCrit.Sts2.Core.Events;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Modding;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Events;
using MegaCrit.Sts2.Core.Multiplayer.Game.Lobby;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.Events.Custom;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.GameOverScreen;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Nodes.Screens.TreasureRoomRelic;
using Sts2Recorder;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;

namespace Sts2.NativeSim.FullAppBridge;

[ModInitializer(nameof(Initialize))]
public static class FullAppBridgeMod
{

    private static async Task Guard(Task task)
    {
        try { await task; }
        catch (Exception error) { FullAppBridgeServer.Fault(error); throw; }
    }
    private static CardSelectContext GridContext(object screen, List<CardModel> cards, string purpose)
    {
        var prefs = PublicData.Field(screen, "_prefs") ?? throw new NotSupportedException("Grid selection preferences unavailable");
        return new CardSelectContext { Purpose = purpose, Cards = cards,
            MinSelect = Convert.ToInt32(PublicData.Required(prefs, "MinSelect")), MaxSelect = Convert.ToInt32(PublicData.Required(prefs, "MaxSelect")) };
    }
    private static AutoSlayer? _autoSlayer;
    private static bool _initialized;

    public static void Initialize()
    {
        if (_initialized) return;
        _initialized = true;

        string portEnv = System.Environment.GetEnvironmentVariable("STS2_FULL_APP_BRIDGE_PORT") ?? "0";
        int.TryParse(portEnv, out int port);

        string portFile = System.Environment.GetEnvironmentVariable("STS2_FULL_APP_BRIDGE_PORT_FILE") ??
            Path.Combine(OS.GetUserDataDir(), "bridge_port.txt");

        Harmony harmony = new("sts2-native-sim.full-app-bridge");
        KnownDrawTop.EnsureApplied();
        PresentationSuppression.Apply(harmony);
        CardSelectBridge.Apply(harmony);
        SpecialChoices.Apply(harmony);
        NativeEventCompletion.Apply(harmony);
        NativeRunOutcome.Apply(harmony);
        FixtureActions.Apply(harmony);

        TryPatchPostfix(harmony, typeof(NGame), "LaunchMainMenu", nameof(OnMainMenuLaunched));
        TryPatchPrefix(harmony, typeof(StartRunLobby), "BeginRunForAllPlayersIfAllReady", nameof(OnBeginRunForAllPlayers));

        TryPatchPrefix(harmony, typeof(CombatRoomHandler), nameof(CombatRoomHandler.HandleAsync), nameof(HandleCombatAsync));
        TryPatchPrefix(harmony, typeof(MapScreenHandler), nameof(MapScreenHandler.HandleAsync), nameof(HandleMapAsync));
        TryPatchPrefix(harmony, typeof(RewardsScreenHandler), nameof(RewardsScreenHandler.HandleAsync), nameof(HandleRewardsScreenAsync));
        TryPatchPrefix(harmony, typeof(CardRewardScreenHandler), nameof(CardRewardScreenHandler.HandleAsync), nameof(HandleCardRewardScreenAsync));
        TryPatchPrefix(harmony, typeof(RestSiteRoomHandler), nameof(RestSiteRoomHandler.HandleAsync), nameof(HandleRestSiteAsync));
        TryPatchPrefix(harmony, typeof(DeckUpgradeScreenHandler), nameof(DeckUpgradeScreenHandler.HandleAsync), nameof(HandleDeckUpgradeScreenAsync));
        TryPatchPrefix(harmony, typeof(DeckCardSelectScreenHandler), nameof(DeckCardSelectScreenHandler.HandleAsync), nameof(HandleDeckCardSelectScreenAsync));
        TryPatchPrefix(harmony, typeof(SimpleCardSelectScreenHandler), nameof(SimpleCardSelectScreenHandler.HandleAsync), nameof(HandleSimpleCardSelectScreenAsync));
        TryPatchPrefix(harmony, typeof(ShopRoomHandler), nameof(ShopRoomHandler.HandleAsync), nameof(HandleShopRoomAsync));
        TryPatchPrefix(harmony, typeof(EventRoomHandler), nameof(EventRoomHandler.HandleAsync), nameof(HandleEventRoomAsync));
        TryPatchPrefix(harmony, typeof(TreasureRoomHandler), nameof(TreasureRoomHandler.HandleAsync), nameof(HandleTreasureRoomAsync));
        TryPatchPrefix(harmony, typeof(VictoryRoomHandler), nameof(VictoryRoomHandler.HandleAsync), nameof(HandleVictoryRoomAsync));
        TryPatchPrefix(harmony, typeof(GameOverScreenHandler), nameof(GameOverScreenHandler.HandleAsync), nameof(HandleGameOverAsync));
        TryPatchPrefix(harmony, typeof(AutoSlayer), "WaitForRewardsScreenAsync", nameof(HandleWaitForRewardsScreenAsync));
        TryPatchPrefix(harmony, typeof(AutoSlayer), "PlayMainMenuAsync", nameof(HandlePlayMainMenuAsync));
        // Native AutoSlay otherwise abandons before the final boss.
        try
        {
            MethodInfo? moveNext = AccessTools.AsyncMoveNext(AccessTools.Method(typeof(AutoSlayer), "PlayRunAsync"));
            if (moveNext != null) harmony.Patch(moveNext, transpiler: new HarmonyMethod(typeof(FullAppBridgeMod), nameof(RaiseMaxFloor)));
        }
        catch (Exception ex) { GD.PrintErr($"[FullAppBridge] max floor: {ex}"); }
        // Native screen/room deadlines must also cover an external policy deciding.
        try
        {
            MethodInfo? withTimeout = AccessTools.Method(typeof(WaitHelper), nameof(WaitHelper.WithTimeout));
            if (withTimeout != null) harmony.Patch(withTimeout, prefix: new HarmonyMethod(typeof(FullAppBridgeMod), nameof(LongerWait)));
        }
        catch (Exception ex) { GD.PrintErr($"[FullAppBridge] timeouts: {ex}"); }
        // spire-jev: every new run is made here, whoever starts it (AutoSlay starts ours at ascension 0).
        TryPatchPrefix(harmony, typeof(RunState), nameof(RunState.CreateForNewRun), nameof(OnCreateForNewRun));

        FullAppBridgeServer.Start(port, portFile);
    }

    /// <summary>A wait for a screen (AutoSlayConfig.defaultScreenTimeout) or a room (defaultRoomTimeout), made longer.</summary>
    private static void LongerWait(ref TimeSpan timeout)
    {
        TimeSpan was = timeout;
        if (timeout == AutoSlayConfig.defaultScreenTimeout) timeout = TimeSpan.FromMinutes(3);
        else if (timeout == AutoSlayConfig.defaultRoomTimeout) timeout = TimeSpan.FromMinutes(8);
        if (timeout != was && !_waitLogged)
        {
            _waitLogged = true;
            GD.Print($"[spire-jev] AutoSlay's waits lengthened ({was} -> {timeout}, and the others)");
        }
    }
    private static bool _waitLogged;

    /// <summary>PlayRunAsync's `TotalFloor < 49` (its only 49 after a TotalFloor read) becomes `< 99`.</summary>
    private static IEnumerable<CodeInstruction> RaiseMaxFloor(IEnumerable<CodeInstruction> instructions)
    {
        var list = instructions.ToList();
        MethodInfo? totalFloor = AccessTools.PropertyGetter(typeof(RunState), nameof(RunState.TotalFloor));
        int changed = 0;
        for (int i = 1; i < list.Count; i++)
        {
            if (list[i].opcode == System.Reflection.Emit.OpCodes.Ldc_I4_S && Convert.ToInt32(list[i].operand) == 49 && list[i - 1].Calls(totalFloor))
            {
                list[i].operand = (sbyte)99;
                changed++;
            }
        }
        GD.Print($"[spire-jev] AutoSlay's max floor raised in {changed} place(s)");
        return list;
    }

    private static void TryPatchPrefix(Harmony harmony, Type type, string methodName, string patchMethodName)
    {
        try
        {
            MethodInfo? method = AccessTools.Method(type, methodName);
            MethodInfo? patch = AccessTools.Method(typeof(FullAppBridgeMod), patchMethodName);
            if (method != null && patch != null)
            {
                harmony.Patch(method, prefix: new HarmonyMethod(patch));
            }
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[FullAppBridge] Failed to patch prefix {type.Name}.{methodName}: {ex}"); throw;
        }
    }

    private static void TryPatchPostfix(Harmony harmony, Type type, string methodName, string patchMethodName)
    {
        try
        {
            MethodInfo? method = AccessTools.Method(type, methodName);
            MethodInfo? patch = AccessTools.Method(typeof(FullAppBridgeMod), patchMethodName);
            if (method != null && patch != null)
            {
                harmony.Patch(method, postfix: new HarmonyMethod(patch));
            }
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[FullAppBridge] Failed to patch postfix {type.Name}.{methodName}: {ex}"); throw;
        }
    }

    private static void OnMainMenuLaunched(ref Task __result)
    {
        __result = StartAfterMainMenuAsync(__result);
    }

    private static async Task StartAfterMainMenuAsync(Task startup)
    {
        await startup;
        while (!FullAppBridgeServer.IsRunStarted)
        {
            await Task.Delay(10);
        }

        string seed = FullAppBridgeServer.RequestedSeed;
        string logFile = Path.Combine(OS.GetUserDataDir(), $"autoplay_{seed}.log");

        _autoSlayer = new AutoSlayer();
        _autoSlayer.Start(seed, logFile);
    }

    /// <summary>
    /// spire-jev: with start_run's "continue", press the main menu's Continue instead of starting a
    /// new run, so a saved run (copied into the profile before launch) resumes where it was saved —
    /// a boss fight replayed from the rest site before it, as often as needed.
    /// </summary>
    private static bool HandlePlayMainMenuAsync(ref Task __result)
    {
        if (!FullAppBridgeServer.ContinueRequested) return true;
        __result = ContinueFromMainMenuAsync();
        return false;
    }

    private static async Task ContinueFromMainMenuAsync()
    {
        var tree = (SceneTree)Engine.GetMainLoop();
        Node? menu = null;
        for (int i = 0; i < 300 && menu == null; i++)
        {
            menu = FindNode(tree.Root, n => n.GetType().Name == "NMainMenu");
            if (menu == null) await Task.Delay(100);
        }
        if (menu == null) throw new InvalidOperationException("[spire-jev] continue: no main menu");
        // Let the menu read the save and show its Continue info before pressing it.
        await Task.Delay(500);
        MethodInfo? press = menu.GetType().GetMethod("OnContinueButtonPressedAsync", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (press == null) throw new InvalidOperationException("[spire-jev] continue: no OnContinueButtonPressedAsync");
        object?[] args = press.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : (p.ParameterType.IsValueType ? Activator.CreateInstance(p.ParameterType) : null)).ToArray();
        GD.Print("[spire-jev] continue: pressing Continue");
        if (press.Invoke(menu, args) is Task pressed) await pressed;
        // The run is loaded once the game has a run state again.
        for (int i = 0; i < 600; i++)
        {
            if (RunManager.Instance?.DebugOnlyGetState() != null) break;
            await Task.Delay(100);
        }
        GD.Print("[spire-jev] continue: run resumed");
    }

    private static Node? FindNode(Node root, Func<Node, bool> test)
    {
        if (test(root)) return root;
        foreach (Node child in root.GetChildren())
        {
            Node? found = FindNode(child, test);
            if (found != null) return found;
        }
        return null;
    }

    private static void OnCreateForNewRun(ref int ascensionLevel)
    {
        // Zero is a requested difficulty; only -1 means no request.
        int requested = FullAppBridgeServer.RequestedAscension;
        if (requested >= 0 && ascensionLevel != requested)
        {
            GD.Print($"[spire-jev] new run at ascension {requested} (was asked for {ascensionLevel})");
            ascensionLevel = requested;
        }
    }

    private static void OnBeginRunForAllPlayers(StartRunLobby __instance)
    {
        if (NGame.Instance is not null)
        {
            NGame.Instance.DebugSeedOverride = FullAppBridgeServer.RequestedSeed;
        }

        string requested = FullAppBridgeServer.RequestedCharacter;
        if (!string.IsNullOrWhiteSpace(requested))
        {
            try
            {
                CharacterModel? targetChar = ModelDb.AllCharacters.FirstOrDefault(c =>
                    c.Id.Entry.Equals(requested, StringComparison.OrdinalIgnoreCase) ||
                    c.Id.Entry.Equals($"CHARACTER.{requested}", StringComparison.OrdinalIgnoreCase) ||
                    c.Id.Entry.EndsWith(requested, StringComparison.OrdinalIgnoreCase));

                if (targetChar != null)
                {
                    __instance.SetLocalCharacter(targetChar);
                }
            }
            catch (Exception ex)
            {
                GD.PrintErr($"[FullAppBridge] Failed to set character {requested}: {ex}");
            }
        }

        // Selecting a character resets difficulty; apply the requested difficulty afterwards.
        int ascension = FullAppBridgeServer.RequestedAscension;
        if (ascension >= 0)
        {
            try
            {
                void SetInt(string name)
                {
                    var prop = typeof(StartRunLobby).GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    if (prop?.SetMethod != null) prop.SetValue(__instance, ascension);
                    else typeof(StartRunLobby).GetField($"<{name}>k__BackingField", BindingFlags.Instance | BindingFlags.NonPublic)?.SetValue(__instance, ascension);
                }
                if (ascension > __instance.MaxAscension) SetInt("MaxAscension");
                SetInt("Ascension");
                __instance.SyncAscensionChange(ascension);
                GD.Print($"[spire-jev] ascension requested {ascension}, lobby now {__instance.Ascension} (max {__instance.MaxAscension})");
            }
            catch (Exception ex) { GD.PrintErr($"[spire-jev] ascension {ascension}: {ex}"); }
        }
    }

    private static bool HandleCombatAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunCombatLoopAsync(random, ct));
        return false;
    }

    private static async Task RunCombatLoopAsync(Rng random, CancellationToken ct)
    {
        CombatManager manager = CombatManager.Instance ?? throw new InvalidOperationException("CombatManager is unavailable.");
        RunManager runManager = RunManager.Instance ?? throw new InvalidOperationException("RunManager is unavailable.");

        await WaitHelper.Until(() => manager.IsInProgress || runManager.DebugOnlyGetState()?.CurrentRoom is CombatRoom { IsPreFinished: true },
            ct, TimeSpan.FromSeconds(15), "Combat did not start and no finished combat was restored");
        if (!manager.IsInProgress) return;
        Player player = LocalContext.GetMe(runManager.DebugOnlyGetState()) ?? throw new InvalidOperationException("Local player is unavailable.");

        while (manager.IsInProgress)
        {
            await WaitHelper.Until(
                () => player.PlayerCombatState?.Phase == PlayerTurnPhase.Play || !manager.IsInProgress,
                ct, TimeSpan.FromSeconds(30), "Player play phase did not begin");

            if (!manager.IsInProgress) break;

            while (player.PlayerCombatState?.Phase == PlayerTurnPhase.Play && manager.IsInProgress)
            {
                string actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("combat", isTerminal: false, isVictory: false);
                if (actionId == "end_turn")
                {
                    PlayerCombatState state = player.PlayerCombatState!;
                    runManager.ActionQueueSynchronizer.RequestEnqueue(new EndPlayerTurnAction(player, state.TurnNumber));
                    await runManager.ActionExecutor.FinishedExecutingActions();
                    break;
                }
                else if (actionId.StartsWith("play_card:", StringComparison.Ordinal))
                {
                    string[] parts = actionId.Split(':');
                    int cardIndex = int.Parse(parts[1]);
                    var hand = PileType.Hand.GetPile(player).Cards;
                    if (cardIndex < 0 || cardIndex >= hand.Count)
                        throw new InvalidOperationException($"Invalid hand card index: {cardIndex}");

                    CardModel card = hand[cardIndex];
                    Creature? target = null;
                    if (parts.Length >= 4 && parts[2] == "target" && ulong.TryParse(parts[3], out ulong targetId))
                    {
                        target = card.CombatState?.HittableEnemies.FirstOrDefault(e => e.CombatId == targetId)
                            ?? manager.DebugOnlyGetState()?.HittableEnemies.FirstOrDefault(e => e.CombatId == targetId)
                            ?? throw new InvalidOperationException("Requested card target disappeared");
                    }
                    else if (card.TargetType.IsSingleTarget() && card.TargetType != TargetType.Self)
                    {
                        throw new InvalidOperationException("Missing card target");
                    }

                    if (card.TargetType.IsSingleTarget() && card.TargetType != TargetType.Self && target is null)
                    {
                        continue;
                    }

                    if (!card.TryManualPlay(target)) throw new InvalidOperationException("Native card play rejected");
                    await runManager.ActionExecutor.FinishedExecutingActions();
                }

            }
        }
    }

    private static bool HandleMapAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunMapLoopAsync(random, ct));
        return false;
    }

    private static async Task RunMapLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.Until(() => NMapScreen.Instance != null && NMapScreen.Instance.IsOpen, ct, TimeSpan.FromSeconds(15), "Map screen not active");

        RunManager runManager = RunManager.Instance!;

        // Act changes replace map points; publish only after the scene settles.
        List<NMapPoint> travelableNodes = await SettledTravelableNodesAsync(ct);
        var reachablePoints = travelableNodes.Select(n => n.Point).ToList();

        string actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("map", isTerminal: false, isVictory: false, reachablePoints);
        string[] parts = actionId.Split(':');
        int rawIdx = int.Parse(parts[1]);

        if (travelableNodes.Count == 0 || travelableNodes.Any(n => !GodotObject.IsInstanceValid(n)))
            travelableNodes = await SettledTravelableNodesAsync(ct);
        if (travelableNodes.Count == 0)
            throw new InvalidOperationException("No map point to travel to");

        int branchIdx = (rawIdx >= 1 && rawIdx <= travelableNodes.Count) ? rawIdx - 1 : rawIdx;
        if (branchIdx < 0 || branchIdx >= travelableNodes.Count) throw new InvalidOperationException("Map candidate no longer exists");

        NMapPoint chosenNode = travelableNodes[branchIdx];
        if (chosenNode.Point.coord != reachablePoints[rawIdx - 1].coord) throw new InvalidOperationException("Map candidate moved before execution");

        var roomEnteredTcs = new TaskCompletionSource<bool>();
        Action onRoomEntered = () => roomEnteredTcs.TrySetResult(true);
        runManager.RoomEntered += onRoomEntered;

        try
        {
            await UiHelper.Click(chosenNode, 0);
            await WaitHelper.ForTask(roomEnteredTcs.Task, ct, TimeSpan.FromSeconds(15), "Room was not entered after map selection");
        }
        finally
        {
            runManager.RoomEntered -= onRoomEntered;
        }
    }

    private static async Task<List<NMapPoint>> SettledTravelableNodesAsync(CancellationToken ct)
    {
        List<NMapPoint> nodes = TravelableNodes();
        for (int tries = 0; tries < 20; tries++)
        {
            await Task.Delay(250, ct);
            List<NMapPoint> again = TravelableNodes();
            if (again.Count > 0 && again.SequenceEqual(nodes)) return again;
            nodes = again;
        }
        return nodes;
    }

    private static List<NMapPoint> TravelableNodes()
    {
        NMapScreen? mapScreen = NMapScreen.Instance;
        RunState? runState = RunManager.Instance?.DebugOnlyGetState();
        if (mapScreen is null || !GodotObject.IsInstanceValid(mapScreen) || runState is null) return new List<NMapPoint>();

        var allMapPoints = UiHelper.FindAll<NMapPoint>(mapScreen).Where(p => GodotObject.IsInstanceValid(p)).ToList();
        List<NMapPoint> travelableNodes;

        if (runState.VisitedMapCoords.Count == 0)
        {
            travelableNodes = allMapPoints
                .Where(p => p.Point.coord.row == 0)
                .OrderBy(p => p.Point.coord.col)
                .ToList();
        }
        else
        {
            MapCoord lastCoord = runState.VisitedMapCoords[^1];
            MapPoint? lastPoint = allMapPoints.FirstOrDefault(p => p.Point.coord == lastCoord)?.Point;
            if (lastPoint is not null && lastPoint.Children.Count > 0)
            {
                travelableNodes = allMapPoints
                    .Where(p => lastPoint.Children.Contains(p.Point))
                    .OrderBy(p => p.Point.coord.col)
                    .ToList();
            }
            else
            {
                travelableNodes = allMapPoints
                    .Where(p => p.State == MapPointState.Travelable)
                    .OrderBy(p => p.Point.coord.col)
                    .ToList();
            }
        }

        if (travelableNodes.Count == 0)
        {
            travelableNodes = allMapPoints
                .Where(p => p.State == MapPointState.Travelable)
                .OrderBy(p => p.Point.coord.col)
                .ToList();
        }

        return travelableNodes;
    }

    private static T? GetTopScreen<T>() where T : class
    {
        return NOverlayStack.Instance?.Peek() as T;
    }

    private static bool HandleCardRewardScreenAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunCardRewardLoopAsync(random, ct));
        return false;
    }

    private static async Task RunCardRewardLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.Until(() => GetTopScreen<NCardRewardSelectionScreen>() != null, ct, TimeSpan.FromSeconds(15), "Card reward screen not open");
        NCardRewardSelectionScreen screen = GetTopScreen<NCardRewardSelectionScreen>()!;

        var cardHolders = UiHelper.FindAll<NCardHolder>(screen);
        List<CardModel> cardModels = cardHolders.Select(h => h.CardModel).Where(c => c != null).ToList()!;

        var alternatives = UiHelper.FindAll<NCardRewardAlternativeButton>(screen).Where(b => b.IsEnabled && b.Visible).ToList();
        RewardAlternatives.Current = alternatives.Select((b, index) => new LegalActionDto {
            ActionId = "card_alternative:" + index, ActionType = "card_alternative",
            Description = PublicData.Field(b, "_optionName")?.ToString() ?? throw new InvalidOperationException("Missing alternative label"),
            Metadata = new() { ["alternative_index"] = index } }).ToList();
        string actionId;
        try { actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("card_reward", false, false, cardModels); }
        finally { RewardAlternatives.Current = new(); }

        if (actionId.StartsWith("card_alternative:", StringComparison.Ordinal))
        {
            int index = int.Parse(actionId.Split(':')[1]);
            await UiHelper.Click(alternatives[index], 0);
        }
        else if (actionId.StartsWith("choose_card:", StringComparison.Ordinal))
        {
            string[] parts = actionId.Split(':');
            int cardIdx = int.Parse(parts[1]);
            if (cardIdx >= 0 && cardIdx < cardHolders.Count)
            {
                NCardHolder chosenHolder = cardHolders[cardIdx];
                chosenHolder.EmitSignal(NCardHolder.SignalName.Pressed, chosenHolder);
            }
            else throw new InvalidOperationException("Card reward candidate disappeared");
        }

        await WaitHelper.Until(() => GetTopScreen<NCardRewardSelectionScreen>() == null, ct, TimeSpan.FromSeconds(15), "Card reward screen did not close");
    }

    private static bool HandleRewardsScreenAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunRewardsLoopAsync(random, ct));
        return false;
    }

    private static async Task RunRewardsLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.Until(() => GetTopScreen<NRewardsScreen>() != null, ct, TimeSpan.FromSeconds(15), "Rewards screen not open");
        NRewardsScreen screen = GetTopScreen<NRewardsScreen>()!;

        while (GetTopScreen<NRewardsScreen>() != null)
        {
            var rewardButtons = UiHelper.FindAll<NRewardButton>(screen).Where(b => b.Reward != null && !b.Reward.SuccessfullySelected).ToList();
            var proceedBtn = UiHelper.FindFirst<NProceedButton>(screen);

            string actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("rewards", isTerminal: false, isVictory: false, rewardButtons.Select(b => b.Reward).ToList());

            if (actionId == "proceed" || actionId.StartsWith("skip", StringComparison.OrdinalIgnoreCase))
            {
                if (proceedBtn != null)
                {
                    await UiHelper.Click(proceedBtn, 0);
                }
                await Task.Delay(50);
                // Terminal event rewards may leave Proceed disabled; resume the parent through RunManager.
                if (GodotObject.IsInstanceValid(screen) && GetTopScreen<NRewardsScreen>() == screen)
                {
                    GD.Print($"[spire-jev] rewards: proceed did not close the screen (button enabled {proceedBtn?.IsEnabled}); proceeding from the terminal rewards screen");
                    try
                    {
                        var proceedNow = typeof(RunManager).GetMethod("ProceedFromTerminalRewardsScreen", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
                        if (proceedNow?.Invoke(RunManager.Instance, null) is Task proceeding) await proceeding;
                    }
                    catch (Exception ex) { GD.PrintErr($"[spire-jev] rewards proceed: {ex.InnerException?.Message ?? ex.Message}"); }
                    await Task.Delay(100);
                    // Resuming the event leaves the screen on the stack: take it off, as a screen that is
                    // not the room's last takes itself off.
                    if (GodotObject.IsInstanceValid(screen) && GetTopScreen<NRewardsScreen>() == screen && screen is IOverlayScreen overlay)
                    {
                        NOverlayStack.Instance?.Remove(overlay);
                        await Task.Delay(100);
                    }
                }
                break;
            }
            else if (actionId.StartsWith("choose_reward:", StringComparison.Ordinal))
            {
                string[] parts = actionId.Split(':');
                int rewardIdx = int.Parse(parts[1]);
                if (rewardIdx >= 0 && rewardIdx < rewardButtons.Count)
                {
                    NRewardButton chosenBtn = rewardButtons[rewardIdx];
                    await UiHelper.Click(chosenBtn, 0);
                    await Task.Delay(50);
                    if (GetTopScreen<NRewardsScreen>() == null)
                    {
                        break;
                    }
                }
            }
            else
            {
                if (proceedBtn != null)
                {
                    await UiHelper.Click(proceedBtn, 0);
                }
                break;
            }
        }

        await WaitHelper.Until(
            () => !GodotObject.IsInstanceValid(screen) || NOverlayStack.Instance?.Peek() != screen || (NMapScreen.Instance != null && NMapScreen.Instance.IsOpen),
            ct, TimeSpan.FromSeconds(15), "Rewards screen did not close");
    }

    private static bool HandleRestSiteAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunRestSiteLoopAsync(random, ct));
        return false;
    }

    private static async Task RunRestSiteLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.Until(() => NRestSiteRoom.Instance != null, ct, TimeSpan.FromSeconds(15), "Rest site not loaded");
        NRestSiteRoom room = NRestSiteRoom.Instance!;
        var options = room.Options.Where(o => o.IsEnabled).ToList();

        string actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("rest_site", isTerminal: false, isVictory: false, options);
        string optKey = actionId.Replace("choose_rest:", "");
        RestSiteOption chosen = options.Single(o => o.OptionId == optKey && o.IsEnabled);

        if (chosen != null)
        {
            // UI buttons run the native option mutation first, then update the
            // room presentation. Calling AfterSelectingOption alone skips Heal,
            // Smith, and other native effects and can fault the headless room.
            // Rest effects can await a reward choice before the room itself finishes.
            Task<bool> selecting = chosen.OnSelect();
            while (!selecting.IsCompleted)
            {
                if (!await HandleOfferedScreenAsync(random, ct)) await Task.Delay(20);
            }
            bool selected = await selecting;
            if (!selected) throw new InvalidOperationException("Native rest selection rejected");
            if (selected)
            {
                room.AfterSelectingOption(chosen);
            }
            await Task.Delay(50);
        }

        DateTime waiting = DateTime.UtcNow;
        bool told = false;
        while (NOverlayStack.Instance?.ScreenCount > 0)
        {
            if (await HandleOfferedScreenAsync(random, ct)) continue;
            if (!told && DateTime.UtcNow - waiting > TimeSpan.FromSeconds(5))
            {
                told = true;
                GD.Print($"[spire-jev] rest site: no handler for screen {(NOverlayStack.Instance?.Peek() as object)?.GetType().Name ?? "?"}");
            }
            await Task.Delay(20);
        }

        if (room.ProceedButton != null)
        {
            await WaitHelper.Until(() => room.ProceedButton.IsEnabled, ct, TimeSpan.FromSeconds(10), "Rest site proceed button not enabled");
            await UiHelper.Click(room.ProceedButton, 0);
        }
    }

    /// <summary>
    /// A rewards screen a room's option opened and waits on, or the card choice one of its rewards
    /// opened; false if neither is on top. AutoSlay drains such screens only after the room.
    /// </summary>
    private static async Task<bool> HandleOfferedScreenAsync(Rng random, CancellationToken ct)
    {
        if (await HandleRewardScreenAsync(random, ct)) return true;
        return await SpecialChoices.Handle(ct, () => HandleRewardScreenAsync(random, ct));
    }

    internal static async Task<bool> HandleRewardScreenAsync(Rng random, CancellationToken ct)
    {
        if (GetTopScreen<NCardRewardSelectionScreen>() != null)
        {
            await RunCardRewardLoopAsync(random, ct);
            return true;
        }
        if (GetTopScreen<NRewardsScreen>() != null)
        {
            await RunRewardsLoopAsync(random, ct);
            return true;
        }
        return false;
    }

    private static bool HandleDeckUpgradeScreenAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunDeckUpgradeLoopAsync(random, ct));
        return false;
    }

    private static async Task RunDeckUpgradeLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.Until(() => GetTopScreen<NDeckUpgradeSelectScreen>() != null, ct, TimeSpan.FromSeconds(15), "Deck upgrade screen not open");
        NDeckUpgradeSelectScreen screen = GetTopScreen<NDeckUpgradeSelectScreen>()!;

        var cardHolders = UiHelper.FindAll<NGridCardHolder>(screen).Where(h => h.CardModel != null && h.CardModel.CurrentUpgradeLevel < h.CardModel.MaxUpgradeLevel).ToList();
        List<CardModel> upgradableCards = cardHolders.Select(h => h.CardModel).ToList();

        var selectionContext = GridContext(screen, upgradableCards, "deck_upgrade");
        string actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("card_select", false, false, selectionContext);

        int[] indices = actionId.StartsWith("choose_cards:", StringComparison.Ordinal)
            ? SelectionValidation.Parse(actionId, selectionContext.Cards.Count, selectionContext.MinSelect, selectionContext.MaxSelect)
            : SelectionValidation.Parse("choose_cards:" + actionId.Split(':')[1], selectionContext.Cards.Count, selectionContext.MinSelect, selectionContext.MaxSelect);
        foreach (int index in indices) cardHolders[index].EmitSignal(NCardHolder.SignalName.Pressed, cardHolders[index]);
        await Task.Delay(50);
        var confirmBtn = UiHelper.FindFirst<NConfirmButton>(screen);
        if (confirmBtn != null)
        {
            await WaitHelper.Until(() => confirmBtn.IsEnabled, ct, TimeSpan.FromSeconds(10), "Upgrade confirm button not enabled");
            await UiHelper.Click(confirmBtn, 0);
        }

        await WaitHelper.Until(() => GetTopScreen<NDeckUpgradeSelectScreen>() == null, ct, TimeSpan.FromSeconds(15), "Upgrade screen did not close");
    }

    private static bool HandleDeckCardSelectScreenAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunDeckCardSelectLoopAsync(random, ct));
        return false;
    }

    private static async Task RunDeckCardSelectLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.Until(() => GetTopScreen<NDeckCardSelectScreen>() != null, ct, TimeSpan.FromSeconds(15), "Deck card select screen not open");
        NDeckCardSelectScreen screen = GetTopScreen<NDeckCardSelectScreen>()!;

        var cardHolders = UiHelper.FindAll<NGridCardHolder>(screen).Where(h => h.CardModel != null).ToList();
        List<CardModel> selectableCards = cardHolders.Select(h => h.CardModel).ToList();

        var selectionContext = GridContext(screen, selectableCards, "deck_card_select");
        string actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("card_select", false, false, selectionContext);

        int[] indices = actionId.StartsWith("choose_cards:", StringComparison.Ordinal)
            ? SelectionValidation.Parse(actionId, selectionContext.Cards.Count, selectionContext.MinSelect, selectionContext.MaxSelect)
            : SelectionValidation.Parse("choose_cards:" + actionId.Split(':')[1], selectionContext.Cards.Count, selectionContext.MinSelect, selectionContext.MaxSelect);
        foreach (int index in indices) cardHolders[index].EmitSignal(NCardHolder.SignalName.Pressed, cardHolders[index]);
        await Task.Delay(50);
        var confirmBtn = UiHelper.FindFirst<NConfirmButton>(screen);
        if (confirmBtn != null)
        {
            await WaitHelper.Until(() => confirmBtn.IsEnabled, ct, TimeSpan.FromSeconds(10), "Card select confirm button not enabled");
            await UiHelper.Click(confirmBtn, 0);
        }

        await WaitHelper.Until(() => GetTopScreen<NDeckCardSelectScreen>() == null, ct, TimeSpan.FromSeconds(15), "Deck card select screen did not close");
    }

    private static bool HandleSimpleCardSelectScreenAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunSimpleCardSelectLoopAsync(random, ct));
        return false;
    }

    private static async Task RunSimpleCardSelectLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.Until(() => GetTopScreen<NSimpleCardSelectScreen>() != null, ct, TimeSpan.FromSeconds(15), "Simple card select screen not open");
        NSimpleCardSelectScreen screen = GetTopScreen<NSimpleCardSelectScreen>()!;

        var cardHolders = UiHelper.FindAll<NGridCardHolder>(screen).Where(h => h.CardModel != null).ToList();
        List<CardModel> selectableCards = cardHolders.Select(h => h.CardModel).ToList();

        var selectionContext = GridContext(screen, selectableCards, "simple_card_select");
        string actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("card_select", false, false, selectionContext);

        int[] indices = actionId.StartsWith("choose_cards:", StringComparison.Ordinal)
            ? SelectionValidation.Parse(actionId, selectionContext.Cards.Count, selectionContext.MinSelect, selectionContext.MaxSelect)
            : SelectionValidation.Parse("choose_cards:" + actionId.Split(':')[1], selectionContext.Cards.Count, selectionContext.MinSelect, selectionContext.MaxSelect);
        foreach (int index in indices) cardHolders[index].EmitSignal(NCardHolder.SignalName.Pressed, cardHolders[index]);
        await Task.Delay(50);
        var confirmBtn = UiHelper.FindFirst<NConfirmButton>(screen);
        if (confirmBtn != null)
        {
            await WaitHelper.Until(() => confirmBtn.IsEnabled, ct, TimeSpan.FromSeconds(10), "Confirm button not enabled");
            await UiHelper.Click(confirmBtn, 0);
        }

        await WaitHelper.Until(() => GetTopScreen<NSimpleCardSelectScreen>() == null, ct, TimeSpan.FromSeconds(15), "Simple card select screen did not close");
    }

    private static bool HandleShopRoomAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunShopRoomLoopAsync(random, ct));
        return false;
    }

    internal static async Task RunShopRoomLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.ForNode<NMerchantRoom>(((SceneTree)Engine.GetMainLoop()).Root, "/root/Game/RootSceneContainer/Run/RoomContainer/MerchantRoom", ct, TimeSpan.FromSeconds(15));
        NMerchantRoom merchantRoom = (NMerchantRoom)((SceneTree)Engine.GetMainLoop()).Root.GetNode("/root/Game/RootSceneContainer/Run/RoomContainer/MerchantRoom");

        if (await NativeMerchant.Handle(merchantRoom.Inventory, merchantRoom.MerchantButton, merchantRoom.ProceedButton,
            () => HandleOfferedScreenAsync(random, ct), ct))
            throw new NotSupportedException("Unexpected combat transition in normal merchant room");
    }

    private static bool HandleEventRoomAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunEventRoomLoopAsync(random, ct));
        return false;
    }

    private static async Task RunEventRoomLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.ForNode<Node>(((SceneTree)Engine.GetMainLoop()).Root, "/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom", ct, TimeSpan.FromSeconds(15));
        Node eventRoom = ((SceneTree)Engine.GetMainLoop()).Root.GetNode("/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom");
        if (EventFixture.Pending)
        {
            await WaitHelper.Until(() => UiHelper.FindAll<NEventOptionButton>(eventRoom)
                .Any(b => b.Option != null && b.IsVisibleInTree() && b.IsEnabled && !b.Option.IsLocked),
                ct, TimeSpan.FromSeconds(15), "Initial event is not ready for fixture replacement");
            await EventFixture.EnterAsync();
            eventRoom = ((SceneTree)Engine.GetMainLoop()).Root.GetNode("/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom");
        }

        while (GodotObject.IsInstanceValid(eventRoom) && eventRoom.IsInsideTree())
        {
            RunState? runState = RunManager.Instance?.DebugOnlyGetState();
            if (runState == null || runState.IsGameOver || runState.BaseRoom == null || runState.BaseRoom.RoomType != RoomType.Event) break;

            // Resolve an offered screen before accepting another event choice.
            if (await HandleOfferedScreenAsync(random, ct)) continue;
            // Play embedded fights without AutoSlay's test-only combat mutations.
            if (CombatManager.Instance?.IsInProgress == true)
            {
                await RunCombatLoopAsync(random, ct);
                await Task.Delay(100);
                continue;
            }

            if (runState.BaseRoom is EventRoom { LocalMutableEvent: FakeMerchant fakeEvent })
            {
                var fake = fakeEvent.Node as NFakeMerchant ?? throw new NotSupportedException("Fake Merchant controls missing");
                var proceed = fake.GetNode<NProceedButton>("%ProceedButton");
                if (!fakeEvent.StartedFight)
                {
                    bool combatStarted = await NativeMerchant.Handle(fake.Inventory, fake.MerchantButton, proceed,
                        () => HandleOfferedScreenAsync(random, ct), ct);
                    if (combatStarted) continue;
                }
                else
                {
                    await WaitHelper.Until(() => proceed.IsEnabled, ct, TimeSpan.FromSeconds(15), "Fake Merchant proceed not ready");
                    await UiHelper.Click(proceed, 0);
                }
                break;
            }

            var optionButtons = UiHelper.FindAll<NEventOptionButton>(eventRoom).Where(b => b.Option != null && b.IsVisibleInTree()).ToList();
            if (!optionButtons.Any(b => b.IsEnabled && !b.Option.IsLocked))
            {
                // Native options can be delayed or hidden while a child choice is pending.
                bool appeared = false;
                var since = System.Diagnostics.Stopwatch.StartNew();
                for (int wait = 0; wait < 50 && !appeared && GodotObject.IsInstanceValid(eventRoom) && since.Elapsed < TimeSpan.FromMinutes(5); wait++)
                {
                    await Task.Delay(100);
                    if (CardSelectBridge.Pending > 0) wait = 0;
                    appeared = !GodotObject.IsInstanceValid(eventRoom) || !eventRoom.IsInsideTree()
                        || CombatManager.Instance?.IsInProgress == true || GetTopScreen<NRewardsScreen>() != null || SpecialChoices.HasScreen
                        || RunManager.Instance?.DebugOnlyGetState()?.IsGameOver == true
                        || UiHelper.FindAll<NEventOptionButton>(eventRoom).Any(b => b.Option != null && b.IsVisibleInTree() && b.IsEnabled && !b.Option.IsLocked);
                }
                if (!appeared)
                {
                    // spire-jev: say which event this is and what its room holds, to handle it next time.
                    try
                    {
                        string id = (RunManager.Instance?.DebugOnlyGetState()?.BaseRoom as MegaCrit.Sts2.Core.Rooms.EventRoom)?.CanonicalEvent?.Id.Entry ?? "?";
                        var kinds = new SortedSet<string>();
                        void Walk(Node n, int depth)
                        {
                            kinds.Add(n.GetType().Name);
                            if (depth < 6) foreach (Node c in n.GetChildren()) Walk(c, depth + 1);
                        }
                        Walk(eventRoom, 0);
                        GD.Print($"[spire-jev] event {id} shows no option buttons; its room holds: {string.Join(", ", kinds)}");
                    }
                    catch (Exception ex) { GD.PrintErr($"[spire-jev] event diagnosis failed: {ex}"); }
                    if (RunManager.Instance?.DebugOnlyGetState()?.IsGameOver == true) break;
                    throw new NotSupportedException("Event room has no supported public decision; automatic exit is disabled");
                }
                continue;
            }

            string actionId;
            NativeEventCompletion.SetButtons(optionButtons);
            try { actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("event", false, false, optionButtons.Select(b => b.Option).ToList()); }
            finally { NativeEventCompletion.SetButtons(null); }
            if (actionId == "event_room_changed") break;

            int choiceIdx = int.Parse(actionId.Split(':')[1]);
            if (choiceIdx < 0 || choiceIdx >= optionButtons.Count || optionButtons[choiceIdx].Option.IsLocked || !optionButtons[choiceIdx].IsEnabled)
                throw new InvalidOperationException("Event option changed before execution");

            NEventOptionButton chosenBtn = optionButtons[choiceIdx];
            EventOption chosenOption = chosenBtn.Option;
            bool isProceed = chosenOption.IsProceed;

            var eventManager = RunManager.Instance ?? throw new InvalidOperationException("Missing event run manager");
            Task eventEffect = await NativeEventCompletion.ClickAndCapture(chosenBtn, ct);
            await WaitHelper.Until(() => eventEffect.IsCompleted || CardSelectBridge.Pending > 0
                || CombatManager.Instance?.IsInProgress == true || GetTopScreen<NRewardsScreen>() != null
                || eventManager.DebugOnlyGetState()?.IsGameOver == true || SpecialChoices.HasScreen,
                ct, TimeSpan.FromSeconds(30), "Event effect did not finish or expose a decision");
            while (!eventEffect.IsCompleted && eventManager.DebugOnlyGetState()?.IsGameOver != true)
            {
                if (!await HandleOfferedScreenAsync(random, ct)) await Task.Delay(20, ct);
            }
            if (eventEffect.IsCompleted)
            {
                await eventEffect;
                await eventManager.EventSynchronizer.AwaitPendingOptionTasks();
            }
            await NativeEventCompletion.CompleteLethalProceedAsync(chosenOption, ct);
            // Native effects can finish before the room publishes its next controls.
            var tree = (SceneTree)Engine.GetMainLoop();
            for (int frame = 0; frame < 2; frame++)
            {
                ct.ThrowIfCancellationRequested();
                await tree.ToSignal(tree, SceneTree.SignalName.ProcessFrame);
            }

            if (isProceed) break;
        }

        // An event can remove its own room before its combat starts.
        if (!GodotObject.IsInstanceValid(eventRoom) || !eventRoom.IsInsideTree())
        {
            for (int wait = 0; wait < 40 && CombatManager.Instance?.IsInProgress != true; wait++) await Task.Delay(50);
            if (CombatManager.Instance?.IsInProgress == true)
            {
                GD.Print("[spire-jev] event: its fight replaced the room; playing it");
                await RunCombatLoopAsync(random, ct);
                await Task.Delay(200);
                while (await HandleOfferedScreenAsync(random, ct)) await Task.Delay(50);
            }
        }
    }

    private static bool HandleTreasureRoomAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunTreasureRoomLoopAsync(random, ct));
        return false;
    }

    private static async Task RunTreasureRoomLoopAsync(Rng random, CancellationToken ct)
    {
        await WaitHelper.ForNode<NTreasureRoom>(((SceneTree)Engine.GetMainLoop()).Root, "/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom", ct, TimeSpan.FromSeconds(15));
        NTreasureRoom treasureRoom = (NTreasureRoom)((SceneTree)Engine.GetMainLoop()).Root.GetNode("/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom");

        var chest = treasureRoom.GetNodeOrNull<NClickableControl>("Chest");
        if (chest != null && chest.IsEnabled)
        {
            await UiHelper.Click(chest, 0);
            await Task.Delay(50);
        }

        await WaitHelper.Until(() => RunManager.Instance!.TreasureRoomRelicSynchronizer.CurrentRelics != null, ct, TimeSpan.FromSeconds(15), "Treasure relics unavailable");
        var offered = RunManager.Instance!.TreasureRoomRelicSynchronizer.CurrentRelics!;
        string actionId = await FullAppBridgeServer.WaitForCoordinatorActionAsync("treasure", false, false, offered);
        if (actionId.StartsWith("take_treasure:", StringComparison.Ordinal))
        {
            int index = int.Parse(actionId.Split(':')[1]);
            var holder = UiHelper.FindAll<NTreasureRoomRelicHolder>(treasureRoom).Single(h => h.Visible && h.Index == index);
            await UiHelper.Click(holder, 0);
            while (await HandleOfferedScreenAsync(random, ct)) await Task.Delay(20);
        }

        if (treasureRoom.ProceedButton != null)
        {
            await WaitHelper.Until(() => treasureRoom.ProceedButton.IsEnabled, ct, TimeSpan.FromSeconds(10), "Treasure proceed button not enabled");
            await UiHelper.Click(treasureRoom.ProceedButton, 0);
        }
    }

    private static bool HandleVictoryRoomAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunVictoryRoomLoopAsync(random, ct));
        return false;
    }

    private static async Task RunVictoryRoomLoopAsync(Rng random, CancellationToken ct)
    {
        if (RunManager.Instance?.DebugOnlyGetState() is not { } run || !NativeRunOutcome.IsVictory(run))
            throw new InvalidOperationException("Victory room reached without native victory confirmation");
        await FullAppBridgeServer.WaitForCoordinatorActionAsync("victory", isTerminal: true, isVictory: true);
    }

    private static bool HandleGameOverAsync(Rng random, CancellationToken ct, ref Task __result)
    {
        __result = Guard(RunGameOverLoopAsync(random, ct));
        return false;
    }

    private static async Task RunGameOverLoopAsync(Rng random, CancellationToken ct)
    {
        var run = RunManager.Instance?.DebugOnlyGetState();
        bool victory = run != null && NativeRunOutcome.IsVictory(run);
        await FullAppBridgeServer.WaitForCoordinatorActionAsync("game_over", isTerminal: true, isVictory: victory);
    }

    private static bool HandleWaitForRewardsScreenAsync(CancellationToken ct, ref Task __result)
    {
        __result = SafeWaitForRewardsOrGameOverScreenAsync(ct);
        return false;
    }

    private static async Task SafeWaitForRewardsOrGameOverScreenAsync(CancellationToken ct)
    {
        // A fight with no rewards can return directly to the map.
        await WaitHelper.Until(
            () => GetTopScreen<NRewardsScreen>() != null || GetTopScreen<MegaCrit.Sts2.Core.Nodes.Screens.GameOverScreen.NGameOverScreen>() != null
                || (NMapScreen.Instance != null && NMapScreen.Instance.IsOpen),
            ct, TimeSpan.FromSeconds(15), "Neither rewards nor game over screen appeared after combat");
    }
}
