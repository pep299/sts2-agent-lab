using System.Reflection;
using System.Runtime.CompilerServices;
using HarmonyLib;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;

namespace Sts2Recorder;

internal static class KnownDrawTop
{
    private sealed record Move(CardModel Card,CardPile? Target,PileType? Source,CardPilePosition Position);
    private sealed class Knowledge{internal readonly List<CardModel> Prefix=new();internal long Revision;}
    private sealed record Addition(Knowledge Knowledge,long Revision,CardModel[] Previous);
    private static readonly AsyncLocal<Move?> current=new();
    private static readonly ConditionalWeakTable<CardPile,Knowledge> known=new();
    private static readonly object gate=new();
    private static bool installed;
    internal static void EnsureApplied()
    {
        lock(gate)
        {
            if(installed)return;
            var harmony=new Harmony("sts2.public-observation.known-draw-top."+typeof(KnownDrawTop).Assembly.GetName().Name);
            foreach(var method in typeof(CardPileCmd).GetMethods(BindingFlags.Public|BindingFlags.Static)
                .Where(m=>m.Name=="Add"&&m.GetParameters()[0].ParameterType==typeof(CardModel)))
                harmony.Patch(method,prefix:new HarmonyMethod(typeof(KnownDrawTop),nameof(BeforeMove)),
                    finalizer:new HarmonyMethod(typeof(KnownDrawTop),nameof(Restore)));
            void Patch(string method,string hook,bool prefix=false)=>harmony.Patch(AccessTools.Method(typeof(CardPile),method),
                prefix:prefix?new HarmonyMethod(typeof(KnownDrawTop),hook):null,
                postfix:prefix?null:new HarmonyMethod(typeof(KnownDrawTop),hook));
            harmony.Patch(AccessTools.Method(typeof(CardPile),"AddInternal"),
                prefix:new HarmonyMethod(typeof(KnownDrawTop),nameof(BeforeAdd)),
                postfix:new HarmonyMethod(typeof(KnownDrawTop),nameof(Added)));
            Patch("RemoveInternal",nameof(Removed));
            Patch("MoveToBottomInternal",nameof(Removed));
            Patch("MoveToTopInternal",nameof(Forget),true);
            Patch("RandomizeOrderInternal",nameof(Forget),true);
            Patch("Clear",nameof(Forget),true);
            installed=true;
        }
    }
    private static void BeforeMove(object[] __args,out Move? __state)
    {
        __state=current.Value;
        var card=(CardModel)__args[0];
        var target=__args[1] is CardPile pile?pile:CardPile.Get((PileType)__args[1],card.Owner);
        current.Value=new(card,target,card.Pile?.Type,(CardPilePosition)__args[2]);
    }
    private static void Restore(Move? __state)=>current.Value=__state;
    private static void BeforeAdd(CardPile __instance,out Addition? __state)
    {
        __state=null;if(__instance.Type!=PileType.Draw)return;
        var knowledge=known.GetOrCreateValue(__instance);var previous=knowledge.Prefix.ToArray();
        knowledge.Prefix.Clear();__state=new(knowledge,++knowledge.Revision,previous);
    }
    private static void Added(CardPile __instance,CardModel __0,Addition? __state)
    {
        if(__state==null||__state.Knowledge.Revision!=__state.Revision)return;
        var knowledge=__state.Knowledge;knowledge.Revision++;
        var move=current.Value;var prefix=knowledge.Prefix;
        if(move?.Card!=__0||move.Target!=__instance)return;
        if(move.Position==CardPilePosition.Bottom){prefix.AddRange(__state.Previous);return;}
        if(move.Position==CardPilePosition.Top&&move.Source is PileType.Hand or PileType.Discard or PileType.Exhaust or PileType.Play)
        {prefix.Add(__0);prefix.AddRange(__state.Previous);}
    }
    private static void Removed(CardPile __instance,CardModel __0)
    {if(known.TryGetValue(__instance,out var knowledge)){knowledge.Revision++;knowledge.Prefix.Remove(__0);}}
    private static void Forget(CardPile __instance)
    {if(known.TryGetValue(__instance,out var knowledge)){knowledge.Revision++;knowledge.Prefix.Clear();}}
    internal static CardModel[] Read(CardPile pile)=>known.TryGetValue(pile,out var knowledge)?knowledge.Prefix.ToArray():Array.Empty<CardModel>();
}
