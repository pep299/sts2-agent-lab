using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;
using Sts2Recorder;

namespace Sts2.NativeSim.FullAppBridge;

public static class PublicObservation
{
    private static readonly CardProjection Cards = new();
    private static readonly Dictionary<string, object> OfferHistory = new(StringComparer.Ordinal);
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private static object R(object x, string name) => PublicData.Required(x, name);
    private static object? P(object? x, string name) => PublicData.Property(x, name);
    private static object[] Items(object? x) => PublicData.Items(x);
    private static object Card(object card, bool assignIdentity = true) => new { state = Cards.Read(card, assignIdentity), rendered = (object?)null };
    private static object Pile(object pc, string name, bool unordered = false)
        => ProjectPile(Items(R(R(pc, name), "Cards")), unordered);
    internal static object ProjectPile(IEnumerable<object> source, bool unordered)
    {
        var cards = source.ToArray();
        if (unordered) cards = cards.OrderBy(Cards.SortKey, StringComparer.Ordinal).ToArray();
        return new { count = cards.Length, order = unordered ? "unordered" : "pile_display", cards = cards.Select(card => Card(card, !unordered)).ToArray() };
    }
    private static object[] Powers(object creature) => Items(R(creature, "Powers")).Where(p => (bool)R(p, "IsVisible")).Select(p => (object)new {
        id = PublicData.Id(p), amount = R(p, "DisplayAmount"), title = PublicData.Title(p), rules = PublicData.Localization(R(p, "Description")), dynamicVars = PublicData.DynamicVars(p),
        facing = p.GetType().Name == "SurroundedPower" ? R(p, "Facing").ToString() : null,
        applierCombatId = p.GetType().Name == "FlankingPower" ? P(P(p, "Applier"), "CombatId") : null,
        targetCombatId = p.GetType().Name == "SandpitPower" ? P(P(p, "Target"), "CombatId") : null }).ToArray();
    private static bool IsType(object value, string name) { for (Type? t = value.GetType(); t != null; t = t.BaseType) if (t.Name == name) return true; return false; }
    private static object[] Enemies(object combat) => Items(R(combat, "Enemies")).Select(enemy => (object)new {
        id = R(enemy, "CombatId"), modelId = R(enemy, "ModelId").ToString(), name = R(enemy, "Name").ToString(),
        hp = R(enemy, "CurrentHp"), maxHp = R(enemy, "MaxHp"), block = R(enemy, "Block"), powers = Powers(enemy),
        intents = Items(P(P(enemy, "Monster"), "NextMove") is object move ? P(move, "Intents") : null).Select(intent => new {
            type = P(intent, "IntentType")?.ToString(), title = PublicData.Localization(P(intent, "IntentTitle")),
            damage = IsType(intent, "AttackIntent") ? PublicData.Call(intent, "GetSingleDamage", R(combat, "Allies"), enemy) : null,
            totalDamage = IsType(intent, "AttackIntent") ? PublicData.Call(intent, "GetTotalDamage", R(combat, "Allies"), enemy) : null,
            icon = (string?)null, text = (string?)null }).ToArray() }).ToArray();
    private static object? Combat(object player)
    {
        if (CombatManager.Instance?.IsInProgress != true || P(player, "PlayerCombatState") is not object pc) return null;
        var combat = CombatManager.Instance.DebugOnlyGetState()!; var queue = R(pc, "OrbQueue");
        return new { turn = R(pc, "TurnNumber"), phase = R(pc, "Phase").ToString(), maxEnergy = R(pc, "MaxEnergy"), stars = R(pc, "Stars"),
            hand = Pile(pc, "Hand"), draw = Pile(pc, "DrawPile", true), discard = Pile(pc, "DiscardPile"), exhaust = Pile(pc, "ExhaustPile"), play = Pile(pc, "PlayPile"),
            orbCapacity = R(queue, "Capacity"), orbs = Items(R(queue, "Orbs")).Select(o => new { id = PublicData.Id(o), title = PublicData.Title(o), passive = R(o, "PassiveVal"), evoke = R(o, "EvokeVal"), rules = PublicData.Localization(R(o, "Description")) }).ToArray(),
            pets = Items(R(pc, "Pets")).Select(p => new { id = R(p, "CombatId"), modelId = R(p, "ModelId").ToString(), hp = R(p, "CurrentHp"), maxHp = R(p, "MaxHp"), block = R(p, "Block"), powers = Powers(p) }).ToArray(), enemies = Enemies(combat) };
    }
    private static string Kind(string action) => action switch {
        "play_card" => "play", "choose_map" => "map", "choose_event" => "event", "choose_rest" => "rest", "shop_buy" => "buy",
        "use_potion" => "potion", "choose_card_select" or "choose_cards" or "choose_upgrade" => "select_grid", "choose_card" => "reward",
        "card_alternative" => "reward_alternative", "choose_reward" => "reward", _ => action };
    private static string NativeKind(string action) => action switch { "choose_card" => "TakeReward", "card_alternative" => "TakeCardRewardAlternative", "discard_potion" => "DiscardPotion", _ => action };
    private static string Phase(string phase) => phase switch { "card_select" or "deck_card_select" or "simple_card_select" or "deck_upgrade" => "grid_selection", "card_reward" => "rewards", "rest_site" => "rest", "game_over" or "victory" => "terminal", _ => phase };

    private static string? DisplayedEventText()
    {
        var root = ((Godot.SceneTree)Godot.Engine.GetMainLoop()).Root.GetNodeOrNull<Godot.Node>("/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom");
        if (root == null) return null;
        var text = new List<string>();
        void Read(Godot.Node node)
        {
            if (node is Godot.Control control && !control.IsVisibleInTree()) return;
            if (node is Godot.Label label && !string.IsNullOrWhiteSpace(label.Text)) text.Add(label.Text);
            else if (node is Godot.RichTextLabel rich && !string.IsNullOrWhiteSpace(rich.Text)) text.Add(rich.Text);
            foreach (Godot.Node child in node.GetChildren()) Read(child);
        }
        Read(root); return string.Join("\n", text);
    }

    public static object Capture(ObservationDto raw, List<LegalActionDto> options, object? context)
    {
        var run = RunManager.Instance?.DebugOnlyGetState() ?? throw new InvalidOperationException("Run unavailable at boundary");
        var player = LocalContext.GetMe(run) ?? throw new InvalidOperationException("Player unavailable at boundary");
        if (run.Players.Count != 1) throw new NotSupportedException("Only solo is qualified");
        var pc = player.PlayerCombatState;
        bool active = CombatManager.Instance?.IsInProgress == true && pc != null;
        var offeredCards = context is CardSelectContext selected ? selected.Cards : context as IReadOnlyList<CardModel>;
        var actions = options.Select((a, index) => {
            var m = a.Metadata ?? new();
            CardModel? card = null;
            if (m.TryGetValue("card_index", out var pos) && pos is int i)
            {
                if (a.ActionType == "play_card" && active) card = PileType.Hand.GetPile(player).Cards[i];
                else if (offeredCards != null && i < offeredCards.Count) card = offeredCards[i];
            }
            return (object)new { id = a.ActionId, kind = Kind(a.ActionType), label = a.Description,
                detail = new { nativeActionId = a.ActionId, nativeOptionIndex = index, nativeKind = NativeKind(a.ActionType),
                    metadata = m, cardDetails = card == null ? null : Card(card) } };
        }).ToArray();
        var offers = new List<object>();
        var merchantEntries = context is MerchantChoiceContext shop ? shop.Entries : context as IEnumerable<MerchantEntry>;
        if (raw.Phase == "shop" && merchantEntries is { } entries)
        {
            int index = 0;
            foreach (var entry in entries)
            {
                offers.Add(PublicData.Offer(entry, index, true, false, player.HasOpenPotionSlots));
                var model = PublicData.EntryModel(entry);
                if (model != null && entry.IsStocked)
                    OfferHistory.TryAdd($"{run.CurrentActIndex}:{run.TotalFloor}:{index}:{PublicData.Id(model)}:{entry.Cost}", new { act = run.CurrentActIndex + 1, floor = run.TotalFloor, index, kind = entry.GetType().Name, modelId = PublicData.Id(model), cost = entry.Cost });
                index++;
            }
        }
        var selection = context is CardSelectContext c ? new { min = c.MinSelect, max = c.MaxSelect,
            purpose = c.Purpose is "FromSimpleGridForRewards" or "FromDeckGeneric" or "FromChooseACardScreen" ? null : c.Purpose,
            cards = c.Cards.Select((card, index) => new { index, cardDetails = Card(card) }).ToArray() } : null;
        var hand = active ? PileType.Hand.GetPile(player).Cards.Select((card, index) => (object)new { index, id = PublicData.Id(card), title = PublicData.Title(card),
            cost = card.EnergyCost.CostsX ? "X" : card.EnergyCost.GetResolved().ToString(), targetType = card.TargetType.ToString(), cardDetails = Card(card), canPlay = card.CanPlay() }).ToArray() : Array.Empty<object>();
        var combatView = Combat(player);
        var status = new { act = run.CurrentActIndex + 1, floor = run.TotalFloor, actFloor = run.ActFloor, hp = player.Creature.CurrentHp, maxHp = player.Creature.MaxHp,
            gold = player.Gold, block = player.Creature.Block, energy = active ? pc!.Energy : 0, maxEnergy = player.MaxEnergy, powers = Powers(player.Creature),
            character = PublicData.Id(player.Character), ascension = run.AscensionLevel, potionBelt = PublicData.Slots(player),
            potions = player.Potions.Select(p => PublicData.Id(p)).ToArray(), relics = player.Relics.Select(PublicData.Id).ToArray(), relicDetails = player.Relics.Select(PublicData.Relic).ToArray(),
            deckCards = player.Deck.Cards.OrderBy(Cards.SortKey, StringComparer.Ordinal).Select((card, index) => new { index, cardDetails = Card(card) }).ToArray(),
            map = PublicData.Map(run), combat = combatView, room = new { type = run.CurrentRoom?.GetType().Name, id = P(run.CurrentRoom, "ModelId")?.ToString() } };
        var unavailable = new Dictionary<string, string> { ["intentIcons"] = "headless renderer", ["renderedCardText"] = "template and existing dynamic variables only" };
        if (context is SpecialChoiceContext { CrystalSphereVisualsUnavailable: { } visualError })
            unavailable["crystalSphereVisualItems"] = visualError;
        return new { state = new { phase = Phase(raw.Phase), status, hand, enemies = active ? Enemies(CombatManager.Instance!.DebugOnlyGetState()!) : Array.Empty<object>(), offers,
                shop = raw.Phase == "shop" && context is MerchantChoiceContext merchant ? new { inventoryOpen = merchant.InventoryOpen } : null,
                selection, eventId = raw.Phase == "event" ? raw.Room?.Details.GetValueOrDefault("event_id") : null,
                options = raw.Phase == "event" ? EventOptions(raw.Room?.Details.GetValueOrDefault("options")) : null,
                text = raw.Phase == "event" ? DisplayedEventText() : null,
                rewards = raw.Phase == "rewards" ? DescribeRewards(context) : null,
                treasure = raw.Phase == "treasure" && context is IReadOnlyList<RelicModel> treasures ? treasures.Select(PublicData.Relic).ToArray() : null,
                rest = raw.Phase == "rest_site" ? Items(context).Select(option => new { id = R(option, "OptionId"), title = PublicData.Localization(R(option, "Title")),
                    description = PublicData.Localization(R(option, "Description")), enabled = R(option, "IsEnabled") }).ToArray() : null,
                bundles = context is SpecialChoiceContext { Bundles: not null } bundleChoice ? bundleChoice.Bundles.Select(bundle => bundle.Select(card => Card(card)).ToArray()).ToArray() : null,
                relicChoices = context is SpecialChoiceContext { Relics: not null } relicChoice ? relicChoice.Relics.Select(PublicData.Relic).ToArray() : null,
                crystalSphere = (context as SpecialChoiceContext)?.CrystalSphere,
                terminal = raw.IsTerminal ? raw.IsVictory ? "victory" : "death" : null }, actions,
            publicHistory = new { coverage = "current_recorded_segment_only", shopOffers = OfferHistory.Values.ToArray() },
            resolution = new { evidence = "native_coordinator_boundary", pendingChoice = selection != null || context is SpecialChoiceContext, parentEffectMayBePending = selection != null || context is SpecialChoiceContext },
            capabilities = new { backend = "native_headless", gameVersion = "v0.111.0", observationRevision = "public-state-v3", renderedCardText = false,
                diagnosticFixture = FixtureActions.Enabled, diagnosticFixtureResult = FixtureActions.Enabled ? FixtureActions.LastResult : null,
                explicitMultiCardIndices = true, supportedCharacters = new[] { "IRONCLAD" }, supportedAscensions = new[] { 0 },
                unavailable } };
    }
    private static object[] EventOptions(object? descriptions)
    {
        if (descriptions is not IEnumerable<Dictionary<string, object?>> options)
            throw new NotSupportedException("Public event options unavailable");
        return options.Select(option => (object)new Dictionary<string, object?>(option)
            { ["enabled"] = NativeEventCompletion.IsButtonReady(Convert.ToInt32(option["index"])) }).ToArray();
    }
    internal static RelicModel? RewardRelic(object reward) => (P(reward, "Relic")
        ?? (reward.GetType().Name == "RelicReward" ? PublicData.Field(reward, "_relic") : null)) as RelicModel;
    private static object[] DescribeRewards(object? context) => Items(context).Select((r, index) => (object)new { index, type = r.GetType().Name,
        amount = P(r, "Amount"), potion = P(r, "Potion") is object p ? PublicData.Potion(p) : null,
        description = P(r, "Description") is object description ? PublicData.Call(description, "GetFormattedText") : null,
        relic = RewardRelic(r) is { } relic ? PublicData.Relic(relic) : null }).ToArray();
}
