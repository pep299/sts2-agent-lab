using System;
using System.Collections.Generic;
using System.Reflection;

namespace Sts2Recorder;

public sealed record CrystalSphereRevealedCell(int Col, int Row, string Content);

public static class CrystalSphereProjection
{
    private const BindingFlags Instance = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

    public static IReadOnlyList<CrystalSphereRevealedCell> Project(object minigame)
    {
        var cells = ReadField(minigame, "cells") as Array
            ?? throw new InvalidOperationException("Crystalのセル配列がない");
        if (cells.Rank != 2) throw new InvalidOperationException("Crystalのセル配列が二次元ではない");
        var revealed = new List<CrystalSphereRevealedCell>();
        for (int col = 0; col < cells.GetLength(0); col++)
            for (int row = 0; row < cells.GetLength(1); row++)
            {
                object cell = cells.GetValue(col, row) ?? throw new InvalidOperationException("Crystalのセルがない");
                if (ReadProperty(cell, "IsHidden") is not bool hidden)
                    throw new InvalidOperationException("Crystalセルの公開状態が不正");
                if (hidden) continue;
                // 未開セルのItem、全Items一覧、実アイテムの原点・サイズ・rarityは読まない。
                object? item = ReadProperty(cell, "Item");
                string content = item?.GetType().Name switch
                {
                    null => "empty",
                    "CrystalSphereGold" => "gold",
                    "CrystalSpherePotion" => "potion",
                    "CrystalSphereCardReward" => "card_reward",
                    "CrystalSphereRelic" => "relic",
                    "CrystalSphereCurse" => "curse",
                    _ => throw new NotSupportedException("Crystalの公開セルに未対応の内容がある")
                };
                revealed.Add(new(col, row, content));
            }
        return revealed.AsReadOnly();
    }

    private static object? ReadProperty(object value, string name)
    {
        for (Type? type = value.GetType(); type != null; type = type.BaseType)
            if (type.GetProperty(name, Instance | BindingFlags.DeclaredOnly) is { } property) return property.GetValue(value);
        throw new MissingMemberException(value.GetType().Name, name);
    }

    private static object? ReadField(object value, string name)
    {
        for (Type? type = value.GetType(); type != null; type = type.BaseType)
            if (type.GetField(name, Instance | BindingFlags.DeclaredOnly) is { } field) return field.GetValue(value);
        throw new MissingFieldException(value.GetType().Name, name);
    }
}
