using System;
using System.Linq;
using System.Reflection;
using System.Threading;
using HarmonyLib;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Models;

namespace Sts2.NativeSim.FullAppBridge;

public sealed record CardSelectionSource(string Kind,string ModelId,string Hook);
public sealed record CardSelectionContext(string? Api,bool CanCancel,bool? CanSkip,CardSelectionSource? Source);

internal static class SelectionCapture
{
    private static readonly AsyncLocal<CardSelectionContext?> current=new();
    internal static CardSelectionContext? Current=>current.Value;
    internal static void Apply(Harmony harmony)
    {
        var apiPrefix=new HarmonyMethod(typeof(SelectionCapture),nameof(BeforeApi));
        var restore=new HarmonyMethod(typeof(SelectionCapture),nameof(Restore));
        foreach(var method in typeof(CardSelectCmd).GetMethods(BindingFlags.Public|BindingFlags.Static)
            .Where(m=>m.Name.StartsWith("From",StringComparison.Ordinal)&&!m.IsGenericMethodDefinition))
            harmony.Patch(method,prefix:apiPrefix,finalizer:restore);
        foreach(string name in new[]{"Toolbox","ToastyMittens","GamblingChip","ChoicesParadox"})
        {
            var type=typeof(RelicModel).Assembly.GetType("MegaCrit.Sts2.Core.Models.Relics."+name,true)!;
            foreach(string hook in new[]{"BeforeHandDraw","AfterPlayerTurnStart"})
            {
                var method=type.GetMethod(hook,BindingFlags.Public|BindingFlags.Instance|BindingFlags.DeclaredOnly);
                if(method!=null)harmony.Patch(method,
                    prefix:new HarmonyMethod(typeof(SelectionCapture),nameof(BeforeSource)),finalizer:restore);
            }
        }
    }
    private static void BeforeApi(MethodBase __originalMethod,object[] __args,out CardSelectionContext? __state)
    {
        __state=current.Value;
        var prefs=__args.OfType<CardSelectorPrefs>().ToArray();
        int skipIndex=Array.FindIndex(__originalMethod.GetParameters(),p=>p.Name=="canSkip"&&p.ParameterType==typeof(bool));
        current.Value=new(__state?.Api??__originalMethod.Name,
            prefs.Length==1?prefs[0].Cancelable:__state?.CanCancel??false,
            skipIndex>=0?(bool)__args[skipIndex]:__state?.CanSkip,__state?.Source);
    }
    private static void BeforeSource(RelicModel __instance,MethodBase __originalMethod,out CardSelectionContext? __state)
    {
        __state=current.Value;
        current.Value=new(null,false,null,new("relic",__instance.Id.ToString(),__originalMethod.Name));
    }
    private static void Restore(CardSelectionContext? __state)=>current.Value=__state;
}
