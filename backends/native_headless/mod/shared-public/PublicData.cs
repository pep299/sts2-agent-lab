using System.Collections;
using System.Reflection;
using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
namespace Sts2Recorder;

// 公開状態の読み取りだけを許可し、乱数・抽選袋・AIの内部状態はたどらない。
public static class PublicData
{
    private const BindingFlags Instance=BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic;
    public static object? Property(object? value,string name)
    {
        for(Type? type=value?.GetType();type!=null;type=type.BaseType)
        {var property=type.GetProperty(name,Instance|BindingFlags.DeclaredOnly);if(property!=null)return property.GetValue(value);}
        return null;
    }
    public static object Required(object value,string name)=>Property(value,name)??throw new MissingMemberException(value.GetType().Name,name);
    public static object? Field(object value,string name)
    {
        for(Type? type=value.GetType();type!=null;type=type.BaseType)
        {var field=type.GetField(name,Instance|BindingFlags.DeclaredOnly);if(field!=null)return field.GetValue(value);}
        return null;
    }
    public static object[] Items(object? value)=>value is IEnumerable items?items.Cast<object>().ToArray():Array.Empty<object>();
    public static object? Call(object value,string name,params object?[] args)
        =>value.GetType().GetMethods(Instance).Single(m=>m.Name==name&&m.GetParameters().Length==args.Length).Invoke(value,args);
    public static string Id(object model)=>Required(model,"Id").ToString()!;
    public static object? Localization(object? value)=>value==null?null:value is string text?new{text}:new
    {
        table=Property(value,"LocTable"),key=Property(value,"LocEntryKey"),
        text=Call(value,"GetRawText")?.ToString()
    };
    public static string? Title(object model)
    {
        var title=Property(model,"Title");
        return title is string text?text:title==null?null:Call(title,"GetFormattedText")?.ToString();
    }
    private static object[] DynamicVarValues(object? vars) =>
        Items(Property(vars,"Values")).OrderBy(v=>Required(v,"Name").ToString(),StringComparer.Ordinal)
            .Select(v=>(object)new{name=Required(v,"Name"),baseValue=Required(v,"BaseValue"),
                enchantedValue=Required(v,"EnchantedValue"),previewValue=Required(v,"PreviewValue")}).ToArray();
    public static object[] DynamicVars(object model)=>DynamicVarValues(Property(model,"DynamicVars"));
    public static object Power(object power)=>new{id=Id(power),amount=Required(power,"Amount"),
        displayAmount=Required(power,"DisplayAmount"),title=Title(power),rules=Localization(Required(power,"Description")),
        dynamicVars=DynamicVars(power),facing=power.GetType().Name=="SurroundedPower"?Required(power,"Facing").ToString():null,
        applierCombatId=power.GetType().Name=="FlankingPower"?Property(Property(power,"Applier"),"CombatId"):null,
        targetCombatId=power.GetType().Name=="SandpitPower"?Property(Property(power,"Target"),"CombatId"):null};
    private static readonly FieldInfo? LocalModifiersField=typeof(CardEnergyCost).GetField("_localModifiers",Instance);
    public static object EnergyCost(object value)
    {
        var cost=((CardModel)value).EnergyCost;
        var modifiers=LocalModifiersField?.GetValue(cost) as IEnumerable<LocalCostModifier>;
        if(cost.HasLocalModifiers&&modifiers==null)
            throw new MissingFieldException(cost.GetType().Name,"_localModifiers");
        var lifetimes=new[]{(LocalCostModifierExpiration)0,LocalCostModifierExpiration.EndOfTurn,
            LocalCostModifierExpiration.WhenPlayed,LocalCostModifierExpiration.EndOfTurn|LocalCostModifierExpiration.WhenPlayed};
        int basis=cost.GetWithModifiers(CostModifiers.None);
        var amounts=Enumerable.Repeat(basis,4).ToArray();var effects=new List<object>();
        foreach(var modifier in modifiers??Enumerable.Empty<LocalCostModifier>())
        {
            effects.Add(new{type=modifier.Type.ToString(),amount=modifier.Amount,isReduceOnly=modifier.IsReduceOnly,
                expiration=(int)modifier.Expiration});
            for(int i=0;i<lifetimes.Length;i++)
                if((modifier.Expiration&lifetimes[i])==0)
                    if(basis>=0&&!cost.CostsX)amounts[i]=modifier.Modify(amounts[i]);
        }
        for(int i=0;i<amounts.Length;i++)amounts[i]=cost.CostsX?-1:basis<0?basis:Math.Max(0,amounts[i]);
        return new{canonical=cost.Canonical,costsX=cost.CostsX,current=cost.GetResolved(),unmodified=basis,modifiers=effects,
            local=amounts[0],afterTurn=amounts[1],afterPlay=amounts[2],afterTurnAndPlay=amounts[3]};
    }
    public static object Card(object card)
    {
        var preview=Call(Required(card,"DynamicVars"),"Clone",card)!;
        var mode=Enum.Parse(card.GetType().Assembly.GetType("MegaCrit.Sts2.Core.Entities.Cards.CardPreviewMode",true)!,"Normal");
        Call(card,"UpdateDynamicVarPreview",mode,null,preview);
        return new{title=Title(card),type=Required(card,"Type").ToString(),rarity=Required(card,"Rarity").ToString(),
            targetType=Required(card,"TargetType").ToString(),rules=Localization(Required(card,"Description")),
            energyCost=EnergyCost(card),
            starCost=new{current=Required(card,"CurrentStarCost"),costsX=Required(card,"HasStarCostX")},
            dynamicVars=DynamicVarValues(preview),retain=Required(card,"ShouldRetainThisTurn"),sly=Required(card,"IsSlyThisTurn")};
    }
    private static object? RelicEffectState(object relic,Func<object,object>? reference)
    {
        if(reference==null)return null;
        object? Card(string name)=>Property(relic,name) is {} card?reference?.Invoke(card):null;
        return Id(relic) switch {
            "RELIC.PEN_NIB"=>new{attacksPlayed=Required(relic,"AttacksPlayed"),attackToDouble=Card("AttackToDouble")},
            "RELIC.CENTENNIAL_PUZZLE"=>new{usedThisCombat=Required(relic,"UsedThisCombat")},
            "RELIC.VAMBRACE"=>new{blockGainedThisCombat=Required(relic,"BlockGainedThisCombat"),triggeringCard=Card("TriggeringCard")},
            _=>null};
    }
    public static object Relic(object relic)=>Relic(relic,null);
    public static object Relic(object relic,Func<object,object>? reference)=>new{id=Id(relic),title=Title(relic),
        rules=Localization(Required(relic,"Description")),dynamicVars=DynamicVars(relic),
        showCounter=Required(relic,"ShowCounter"),
        counter=(bool)Required(relic,"ShowCounter")?Required(relic,"DisplayAmount"):null,
        stackCount=Required(relic,"StackCount"),isMelted=Required(relic,"IsMelted"),isUsedUp=Required(relic,"IsUsedUp"),
        effectState=RelicEffectState(relic,reference)};
    public static object Potion(object potion)=>new{id=Id(potion),title=Title(potion),
        rules=Localization(Required(potion,"Description")),dynamicVars=DynamicVars(potion),
        targetType=Required(potion,"TargetType").ToString(),queued=Required(potion,"IsQueued")};
    public static object Slots(object player)=>new{capacity=Required(player,"MaxPotionCount"),
        slots=Items(Required(player,"PotionSlots")).Select((p,index)=>new{index,potion=p==null?null:Potion(p)}).ToArray()};
    public static object? Coord(object? coord)=>coord==null?null:new{row=Field(coord,"row"),col=Field(coord,"col")};
    private static string CoordKey(object point)=>JsonSerializer.Serialize(Coord(Field(point,"coord")));
    public static object? Map(object state)
    {
        var map=Property(state,"Map");if(map==null)return null;
        var points=Items(Call(map,"GetAllMapPoints"))
            .Concat(new[]{Property(map,"StartingMapPoint"),Property(map,"BossMapPoint"),Property(map,"SecondBossMapPoint")}.Where(p=>p!=null)!)
            .DistinctBy(p=>CoordKey(p!)).OrderBy(p=>Convert.ToInt32(Field(Field(p!,"coord")!,"row")))
            .ThenBy(p=>Convert.ToInt32(Field(Field(p!,"coord")!,"col"))).ToArray();
        var visited=Items(Required(state,"VisitedMapCoords")).Select(c=>JsonSerializer.Serialize(Coord(c))).ToHashSet();
        var act=Required(state,"Act");
        return new{actId=Id(act),current=Coord(Property(state,"CurrentMapCoord")),
            bossId=Property(act,"BossEncounter") is object boss?Id(boss):null,
            secondBossId=(bool)Required(act,"HasSecondBoss")&&Property(act,"SecondBossEncounter") is object second?Id(second):null,
            start=Coord(Field(Required(map,"StartingMapPoint"),"coord")),
            boss=Coord(Field(Required(map,"BossMapPoint"),"coord")),
            secondBoss=Property(map,"SecondBossMapPoint") is object sb?Coord(Field(sb,"coord")):null,
            nodes=points.Select(p=>new{coord=Coord(Field(p!,"coord")),roomType=Required(p!,"PointType").ToString(),
                visited=visited.Contains(CoordKey(p!)),
                children=Items(Required(p!,"Children")).OrderBy(CoordKey,StringComparer.Ordinal).Select(c=>Coord(Field(c,"coord"))).ToArray()}).ToArray()};
    }
    public static object? EntryModel(object entry)=>Property(entry,"Model")??Property(Property(entry,"CreationResult"),"Card");
    public static object Offer(object entry,int index,bool visible,bool inputBlocked,bool potionSpace)
    {
        var model=EntryModel(entry);string kind=entry.GetType().Name;
        var stocked=(bool)Required(entry,"IsStocked");var affordable=(bool)Required(entry,"EnoughGold");
        return new{index,kind,modelId=model==null?null:Id(model),title=model==null?null:Title(model),
            cost=Required(entry,"Cost"),stocked,affordable,visible,
            canBuy=visible&&stocked&&affordable&&!inputBlocked&&(kind!="MerchantPotionEntry"||potionSpace),
            onSale=Property(entry,"IsOnSale"),
            item=model==null?null:kind=="MerchantCardEntry"?Card(model):kind=="MerchantRelicEntry"?Relic(model):kind=="MerchantPotionEntry"?Potion(model):null};
    }
    public static object Selection(object node,Func<object,object> cardDetails)
    {
        var prefs=Field(node,"_prefs");var selected=Items(Field(node,"_selectedCards"));
        return new{min=Property(prefs,"MinSelect"),max=Property(prefs,"MaxSelect"),
            selected=selected.Select(cardDetails).ToArray(),selectedCount=selected.Length};
    }
}
