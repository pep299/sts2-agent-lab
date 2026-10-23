using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Potions;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;

namespace Sts2.NativeSim.FullAppBridge;

public static class PotionActions
{
    public static bool IsPotion(string action) => action.StartsWith("use_potion:", StringComparison.Ordinal) || action.StartsWith("discard_potion:", StringComparison.Ordinal);
    public static void Add(List<LegalActionDto> actions, string phase)
    {
        actions.RemoveAll(a => IsPotion(a.ActionId));
        if (phase is "card_select" or "deck_card_select" or "simple_card_select" or "deck_upgrade" or "game_over" or "victory") return;
        var run = RunManager.Instance?.DebugOnlyGetState();
        var player = run == null ? null : LocalContext.GetMe(run);
        if (player == null || player.Creature.IsDead || !player.CanUseOrRemovePotions) return;
        bool combat = CombatManager.Instance?.IsInProgress == true;
        for (int slot = 0; slot < player.PotionSlots.Count; slot++)
        {
            if (player.PotionSlots[slot] is not { } potion || potion.IsQueued) continue;
            var metadata = new Dictionary<string, object?> { ["potion_index"] = slot, ["potion_id"] = potion.Id.Entry };
            actions.Add(new LegalActionDto { ActionId = $"discard_potion:{slot}", ActionType = "discard_potion", Description = $"Discard {potion.Id.Entry}", Metadata = new(metadata) });
            bool usable = potion.PassesCustomUsabilityCheck && (potion.Usage == PotionUsage.AnyTime || potion.Usage == PotionUsage.CombatOnly && combat);
            if (!usable) continue;
            if (potion.TargetType == TargetType.AnyEnemy)
            {
                if (!combat) continue;
                foreach (var enemy in CombatManager.Instance!.DebugOnlyGetState()!.HittableEnemies.OrderBy(e => e.CombatId))
                    if (potion.IsValidTarget(enemy)) AddUse(actions, slot, potion, metadata, enemy);
            }
            else if (potion.TargetType == TargetType.AnyAlly)
            {
                if (!combat) continue;
                foreach (var ally in CombatManager.Instance!.DebugOnlyGetState()!.Allies.OrderBy(e => e.CombatId))
                    if (potion.IsValidTarget(ally)) AddUse(actions, slot, potion, metadata, ally);
            }
            else if (potion.TargetType is TargetType.AnyPlayer or TargetType.Self)
            {
                if (potion.IsValidTarget(player.Creature))
                    actions.Add(new LegalActionDto { ActionId = $"use_potion:{slot}:self", ActionType = "use_potion", Description = $"Use {potion.Id.Entry} on the solo player",
                        Metadata = new(metadata) { ["target"] = "self" } });
            }
            else AddUse(actions, slot, potion, metadata, null);
        }
    }
    private static void AddUse(List<LegalActionDto> actions, int slot, PotionModel potion, Dictionary<string, object?> source, Creature? target)
    {
        var metadata = new Dictionary<string, object?>(source);
        if (target != null) metadata["target_id"] = target.CombatId;
        actions.Add(new LegalActionDto { ActionId = $"use_potion:{slot}" + (target == null ? "" : $":target:{target.CombatId}"), ActionType = "use_potion", Description = $"Use {potion.Id.Entry}", Metadata = metadata });
    }
    public static async Task Apply(string actionId)
    {
        var manager = RunManager.Instance!;
        var player = LocalContext.GetMe(manager.DebugOnlyGetState())!;
        var parts = actionId.Split(':');
        int slot = int.Parse(parts[1]);
        bool combat = CombatManager.Instance?.IsInProgress == true;
        var current = new List<LegalActionDto>(); Add(current, combat ? "combat" : "map");
        if (!current.Any(a => a.ActionId == actionId)) throw new InvalidOperationException("Potion candidate changed before execution");
        if (parts[0] == "discard_potion") manager.ActionQueueSynchronizer.RequestEnqueue(new DiscardPotionGameAction(player, (uint)slot, combat));
        else
        {
            Creature? target = null;
            if (parts.Length == 3 && parts[2] == "self") target = player.Creature;
            if (parts.Length == 4)
            {
                ulong id = ulong.Parse(parts[3]);
                var state = CombatManager.Instance!.DebugOnlyGetState()!;
                target = state.Allies.Concat(state.Enemies).Single(c => c.CombatId == id);
            }
            player.PotionSlots[slot]!.EnqueueManualUse(target);
        }
        await manager.ActionExecutor.FinishedExecutingActions();
    }
}
