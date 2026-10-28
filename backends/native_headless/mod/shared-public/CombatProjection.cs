using System.Runtime.CompilerServices;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Combat.History;
using MegaCrit.Sts2.Core.Combat.History.Entries;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;

namespace Sts2Recorder;

public sealed class CombatProjection
{
    private readonly CardProjection cards;
    public CombatProjection(CardProjection cards){this.cards=cards;KnownDrawTop.EnsureApplied();}
    public object[] DrawKnownTop(Player player)=>KnownDrawTop.Read(player.PlayerCombatState!.DrawPile)
        .Select(card=>cards.Read(card)).ToArray();
    private sealed record Identity(long Value);
    private readonly ConditionalWeakTable<CardPlay,Identity> plays=new();
    private long nextPlay;
    private long PlayId(CardPlay play)=>plays.GetValue(play,_=>new Identity(++nextPlay)).Value;
    private object Play(CardPlay play,CombatState combat,int turn,int sequence)=>new {
        playId=PlayId(play),card=new{id=play.Card.Id.ToString(),instance=cards.Instance(play.Card),type=play.Card.Type.ToString()},
        ownerId=play.Player.Creature.CombatId,round=combat.RoundNumber,side=combat.CurrentSide.ToString(),turn,sequence,
        isAutoPlay=play.IsAutoPlay,playIndex=play.PlayIndex,playCount=play.PlayCount};
    public object Read(CombatHistory history,CombatState combat,Player player)
    {
        var creature=player.Creature;int turn=player.PlayerCombatState!.TurnNumber;
        var started=new List<object>();var finished=new List<object>();var block=new List<object>();var drawn=new List<object>();
        foreach(var entry in history.Entries)
        {
            if(!entry.HappenedThisTurn(combat))continue;
            int sequence=started.Count+finished.Count+block.Count+drawn.Count;
            switch(entry)
            {
                case CardPlayStartedEntry e when e.CardPlay.Player==player:
                    started.Add(Play(e.CardPlay,combat,turn,sequence));break;
                case CardPlayFinishedEntry e when e.CardPlay.Player==player:
                    finished.Add(Play(e.CardPlay,combat,turn,sequence));break;
                case BlockGainedEntry e when e.Receiver==creature:
                    block.Add(new{amount=e.Amount,receiverId=creature.CombatId,round=combat.RoundNumber,
                        side=combat.CurrentSide.ToString(),turn,sequence,
                        cardPlay=e.CardPlay?.Player==player?Play(e.CardPlay,combat,turn,sequence):null,props=e.Props.ToString()});break;
                case CardDrawnEntry e when e.Card.Owner==player:
                    drawn.Add(new{card=cards.Reference(e.Card),fromHandDraw=e.FromHandDraw,ownerId=creature.CombatId,
                        round=combat.RoundNumber,side=combat.CurrentSide.ToString(),turn,sequence});break;
            }
        }
        return new{coverage="current_turn",playsStarted=started,playsFinished=finished,blockGained=block,draws=drawn};
    }
    public static bool? BoundUsed(Creature creature)
    {
        var bound=creature.Powers.SingleOrDefault(p=>p.Id.Entry=="CHAINS_OF_BINDING_POWER");
        if(bound==null)return false;
        var data=PublicData.Field(bound,"_internalData");
        return data==null?null:PublicData.Field(data,"boundCardPlayed") as bool?;
    }
}
