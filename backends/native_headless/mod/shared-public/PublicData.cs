using System.Collections;
using System.Reflection;
using System.Text.Json;
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
    public static object Card(object card)
    {
        var cost=Required(card,"EnergyCost");
        var preview=Call(Required(card,"DynamicVars"),"Clone",card)!;
        var mode=Enum.Parse(card.GetType().Assembly.GetType("MegaCrit.Sts2.Core.Entities.Cards.CardPreviewMode",true)!,"Normal");
        Call(card,"UpdateDynamicVarPreview",mode,null,preview);
        return new{title=Title(card),type=Required(card,"Type").ToString(),rarity=Required(card,"Rarity").ToString(),
            targetType=Required(card,"TargetType").ToString(),rules=Localization(Required(card,"Description")),
            energyCost=new{canonical=Required(cost,"Canonical"),costsX=Required(cost,"CostsX"),current=Call(cost,"GetResolved")},
            starCost=new{current=Required(card,"CurrentStarCost"),costsX=Required(card,"HasStarCostX")},
            dynamicVars=DynamicVarValues(preview),retain=Required(card,"ShouldRetainThisTurn"),sly=Required(card,"IsSlyThisTurn")};
    }
    public static object Relic(object relic)=>new{id=Id(relic),title=Title(relic),
        rules=Localization(Required(relic,"Description")),dynamicVars=DynamicVars(relic),
        showCounter=Required(relic,"ShowCounter"),
        counter=(bool)Required(relic,"ShowCounter")?Required(relic,"DisplayAmount"):null,
        stackCount=Required(relic,"StackCount"),isMelted=Required(relic,"IsMelted"),isUsedUp=Required(relic,"IsUsedUp")};
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
