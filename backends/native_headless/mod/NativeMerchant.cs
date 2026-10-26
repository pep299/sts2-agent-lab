using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Models.Events;
using MegaCrit.Sts2.Core.Models.Potions;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Rooms;

namespace Sts2.NativeSim.FullAppBridge;

internal sealed class MerchantChoiceContext
{
    public required IReadOnlyList<MerchantEntry> Entries { get; init; }
    public required bool InventoryOpen { get; init; }

    public void AddControls(List<LegalActionDto> actions)
    {
        if (!InventoryOpen) actions.Add(new LegalActionDto { ActionId = "shop_open", ActionType = "shop_open", Description = "View merchant inventory" });
        else actions.Add(new LegalActionDto { ActionId = "shop_close", ActionType = "shop_close", Description = "Close inventory and return to merchant" });
    }
}

internal static class NativeMerchant
{
    public static bool StartsEventCombat(string action)
    {
        if (!action.StartsWith("use_potion:", StringComparison.Ordinal)) return false;
        var run = RunManager.Instance?.DebugOnlyGetState();
        return run?.CurrentRoom is EventRoom { LocalMutableEvent: FakeMerchant { StartedFight: false } }
            && LocalContext.GetMe(run)!.PotionSlots[int.Parse(action.Split(':')[1])] is FoulPotion;
    }

    public static Task WaitForEventCombat() => WaitHelper.Until(() => CombatManager.Instance?.IsInProgress == true,
        CancellationToken.None, TimeSpan.FromSeconds(15), "Fake Merchant potion did not enter combat");

    public static async Task<bool> Handle(NMerchantInventory inventory, NMerchantButton merchant,
        NProceedButton proceed, Func<Task<bool>> handleRewards, CancellationToken ct)
    {
        while (GodotObject.IsInstanceValid(inventory) && CombatManager.Instance?.IsInProgress != true)
        {
            var slots = inventory.IsOpen ? inventory.GetAllSlots().Where(s => s.Entry != null).ToList() : new List<NMerchantSlot>();
            var context = new MerchantChoiceContext { InventoryOpen = inventory.IsOpen, Entries = slots.Select(s => s.Entry).ToList() };
            string action = await FullAppBridgeServer.WaitForCoordinatorActionAsync("shop", false, false, context);
            if (action == "shop_combat_started") return true;
            if (action == "shop_open")
            {
                await WaitHelper.Until(() => merchant.IsEnabled, ct, TimeSpan.FromSeconds(15), "Merchant button not ready");
                await UiHelper.Click(merchant, 0);
                await WaitHelper.Until(() => inventory.IsOpen, ct, TimeSpan.FromSeconds(15), "Merchant inventory did not open");
                continue;
            }
            if (action is "shop_close" or "shop_leave")
            {
                if (inventory.IsOpen)
                {
                    var back = UiHelper.FindFirst<NBackButton>(inventory) ?? throw new NotSupportedException("Merchant back button missing");
                    await UiHelper.Click(back, 0);
                    await WaitHelper.Until(() => !inventory.IsOpen, ct, TimeSpan.FromSeconds(15), "Merchant inventory did not close");
                }
                if (action == "shop_close") continue;
                await WaitHelper.Until(() => proceed.IsEnabled, ct, TimeSpan.FromSeconds(15), "Merchant proceed button not ready");
                await UiHelper.Click(proceed, 0);
                return false;
            }
            if (!action.StartsWith("shop_buy:", StringComparison.Ordinal)) throw new NotSupportedException("Unsupported merchant input: " + action);
            int index = int.Parse(action.Split(':')[1]);
            var entry = slots[index].Entry;
            var player = LocalContext.GetMe(RunManager.Instance!.DebugOnlyGetState())!;
            if (!inventory.IsOpen || !entry.EnoughGold || !entry.IsStocked || entry is MerchantPotionEntry && !player.HasOpenPotionSlots)
                throw new InvalidOperationException("Shop candidate is no longer purchasable");
            Task buying = entry.OnTryPurchaseWrapper(inventory.Inventory);
            while (!buying.IsCompleted)
                if (!await handleRewards()) await Task.Delay(20, ct);
            await buying;
            while (await handleRewards()) await Task.Delay(20, ct);
        }
        return CombatManager.Instance?.IsInProgress == true;
    }
}
