using System;
using System.IO;
using System.Collections.Generic;
using System.IO.Compression;
using System.Text.Json;
using System.Reflection;
using System.Security.Cryptography;

namespace Sts2Recorder;

public sealed record CrystalSphereFragment(int Col, int Row, int Width, int Height, string RgbaGzipBase64);
public sealed record CrystalSphereTemplate(string Kind, int WidthCells, int HeightCells, int Width, int Height, string RgbaGzipBase64);
public sealed record CrystalSphereVisuals(IReadOnlyList<CrystalSphereFragment> VisibleFragments, string? Unavailable)
{
    public IReadOnlyList<CrystalSphereTemplate> VisualTemplates { get; init; } = Array.Empty<CrystalSphereTemplate>();
}

public sealed class CrystalSphereAssets
{
    internal sealed record Raster(int Width, int Height, byte[] Rgba);
    private readonly Dictionary<string, Raster> images;
    private IReadOnlyList<CrystalSphereTemplate>? templates;
    private CrystalSphereAssets(Dictionary<string, Raster> images) => this.images = images;

    public static CrystalSphereAssets Load(string directory) => FromCatalog(File.ReadAllText(Path.Combine(directory, "catalog.json")));

    public static CrystalSphereAssets FromCatalog(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.GetProperty("schema").GetString() != "crystal-assets-v1" || root.GetProperty("gameVersion").GetString() != "v0.111.0" ||
            root.GetProperty("gameAssemblySha256").GetString() != "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4")
            throw new InvalidDataException("Crystal assets must use crystal-assets-v1 for v0.111.0.");
        var images = new Dictionary<string, Raster>(StringComparer.Ordinal);
        foreach (var image in root.GetProperty("images").EnumerateArray())
        {
            int width = image.GetProperty("width").GetInt32(), height = image.GetProperty("height").GetInt32();
            if (width <= 0 || height <= 0 || width > 4096 || height > 4096) throw new InvalidDataException("Invalid Crystal asset dimensions.");
            byte[] rgba = Decode(image.GetProperty("rgbaGzipBase64").GetString()!, checked(width * height * 4));
            if (Convert.ToHexString(SHA256.HashData(rgba)).ToLowerInvariant() != image.GetProperty("rgbaSha256").GetString())
                throw new InvalidDataException("Crystal asset raster hash mismatch.");
            images.Add(image.GetProperty("path").GetString()!, new Raster(width, height, rgba));
        }
        return new CrystalSphereAssets(images);
    }

    internal Raster Required(string path) => images.TryGetValue(path, out var raster)
        ? raster : throw new InvalidDataException("The fixed Crystal asset catalog is incomplete.");

    internal IReadOnlyList<CrystalSphereTemplate> Templates(Func<IReadOnlyList<CrystalSphereTemplate>> build)
    {
        lock (images) return templates ??= build();
    }

    internal static byte[] Decode(string encoded, int expectedLength)
    {
        using var input = new MemoryStream(Convert.FromBase64String(encoded));
        using var gzip = new GZipStream(input, CompressionMode.Decompress);
        var data = new byte[expectedLength];
        gzip.ReadExactly(data);
        if (gzip.ReadByte() != -1) throw new InvalidDataException("Unexpected Crystal raster length.");
        return data;
    }
}

/// <summary>掘ったセル内の画像片を再構成し、実アイテムの識別子や配置は出力しない。</summary>
public static class CrystalSphereProjection
{
    public const int CellPixels = 57;
    private const string ImageRoot = "res://images/events/crystal_sphere/";
    public const string Representation = "uncovered-cell-item-art-rgba-v1; background, fog edge and reveal animation omitted";
    private const BindingFlags Instance = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    private static object? Property(object value, string name)
    {
        for (Type? type = value.GetType(); type != null; type = type.BaseType)
            if (type.GetProperty(name, Instance | BindingFlags.DeclaredOnly) is { } property) return property.GetValue(value);
        return null;
    }
    private static object Required(object value, string name) => Property(value, name) ?? throw new InvalidDataException("Missing Crystal visual input.");
    private static object? Field(object value, string name)
    {
        for (Type? type = value.GetType(); type != null; type = type.BaseType)
            if (type.GetField(name, Instance | BindingFlags.DeclaredOnly) is { } field) return field.GetValue(value);
        return null;
    }

    public static CrystalSphereVisuals Project(object minigame, CrystalSphereAssets? assets)
    {
        if (assets == null) return new(Array.Empty<CrystalSphereFragment>(), "Crystal image catalog is not configured; partial item artwork is unavailable.");
        var cells = (Array)(Field(minigame, "cells") ?? throw new MissingFieldException("CrystalSphereMinigame.cells"));
        var fragments = new List<CrystalSphereFragment>();
        try
        {
            for (int col = 0; col < cells.GetLength(0); col++)
                for (int row = 0; row < cells.GetLength(1); row++)
                {
                    object cell = cells.GetValue(col, row)!;
                    if ((bool)Required(cell, "IsHidden")) continue;
                    // 未公開セルのItemと盤面全体のItems一覧は読まない。
                    object? item = Property(cell, "Item");
                    byte[] rgba = item == null ? new byte[CellPixels * CellPixels * 4] : RenderCell(item, col, row, assets);
                    fragments.Add(new(col, row, CellPixels, CellPixels, Encode(rgba)));
                }
            return new(fragments, null) { VisualTemplates = Templates(assets) };
        }
        catch (InvalidDataException)
        {
            // 失敗理由にも実アイテムの種類や画像パスを含めない。
            return new(Array.Empty<CrystalSphereFragment>(), "Crystal artwork cannot be reconstructed from the configured fixed image catalog.");
        }
    }

    private sealed record Layer(CrystalSphereAssets.Raster Raster, double Left, double Top, double Width, double Height,
        double Hue = 1, double Saturation = 1, double Value = 1, bool Tint = false);

    public static IReadOnlyList<CrystalSphereTemplate> Templates(CrystalSphereAssets assets) => assets.Templates(() =>
    {
        (string Kind, int Width, int Height, string? Texture, string? Rarity)[] known =
        {
            ("gold_small", 1, 1, "gold", null), ("gold_big", 2, 1, "big_gold", null), ("curse", 2, 2, "curse", null),
            ("potion_common", 1, 3, "common_potion", null), ("potion_uncommon", 1, 3, "uncommon_potion", null),
            ("potion_rare", 2, 2, "rare_potion", null), ("relic", 4, 4, "relic", null),
            ("card_common", 2, 2, null, "Common"), ("card_uncommon", 2, 2, null, "Uncommon"), ("card_rare", 2, 2, null, "Rare")
        };
        var templates = new List<CrystalSphereTemplate>();
        foreach (var item in known)
        {
            int width = item.Width * CellPixels, height = item.Height * CellPixels;
            var layers = item.Rarity != null ? CardLayers(item.Rarity, width, height, assets)
                : IconLayers(ImageRoot + "crystal_sphere_" + item.Texture + ".png", width, height, assets);
            templates.Add(new(item.Kind, item.Width, item.Height, width, height, Encode(Render(layers, 0, 0, width, height))));
        }
        return templates.AsReadOnly();
    });

    private static byte[] RenderCell(object item, int col, int row, CrystalSphereAssets assets)
    {
        object position = Required(item, "Position"), size = Required(item, "Size");
        int x = Convert.ToInt32(Field(position, "X")), y = Convert.ToInt32(Field(position, "Y"));
        int width = Convert.ToInt32(Field(size, "X")) * CellPixels;
        int height = Convert.ToInt32(Field(size, "Y")) * CellPixels;
        List<Layer> layers;
        if (item.GetType().Name == "CrystalSphereCardReward")
        {
            object owner = Field(item, "_owner") ?? throw new InvalidDataException("Missing card owner.");
            object pool = Required(Required(owner, "Character"), "CardPool");
            // 検証対象Ironclad以外の枠素材は欠損として扱う。
            if (Required(pool, "CardFrameMaterialPath").ToString() != "card_frame_red")
                throw new InvalidDataException("Unsupported Crystal card frame.");
            var rarity = Field(item, "_rarity")?.ToString();
            layers = CardLayers(rarity, width, height, assets);
        }
        else
        {
            string path = Required(item, "TexturePath").ToString()!;
            if (!path.StartsWith(ImageRoot, StringComparison.Ordinal)) throw new InvalidDataException("Unsupported Crystal image.");
            layers = IconLayers(path, width, height, assets);
        }
        return Render(layers, (col - x) * CellPixels, (row - y) * CellPixels, CellPixels, CellPixels);
    }

    private static List<Layer> IconLayers(string path, int width, int height, CrystalSphereAssets assets) =>
        new() { new(assets.Required(path), 6, 4, width - 10, height - 10) };

    private static List<Layer> CardLayers(string? rarity, int width, int height, CrystalSphereAssets assets)
    {
        (double h, double s, double v) = rarity switch
        {
            "Common" => (1, 0, .85), "Uncommon" => (1, 1, 1), "Rare" => (.563, 1.198, 1.14),
            _ => throw new InvalidDataException("Unsupported Crystal card banner.")
        };
        return new()
        {
            new(assets.Required(ImageRoot + "crystal_sphere_card_outline.png"), 0, 0, width, height),
            new(assets.Required(ImageRoot + "crystal_sphere_card_back.png"), 0, 0, width, height, .025, .85, 1, true),
            new(assets.Required(ImageRoot + "crystal_sphere_card_banner.png"), 0, 0, width, height, h, s, v, true)
        };
    }

    private static byte[] Render(List<Layer> layers, int offsetX, int offsetY, int width, int height)
    {
        var pixels = new byte[width * height * 4];
        for (int py = 0; py < height; py++)
            for (int px = 0; px < width; px++)
            {
                double localX = offsetX + px + .5, localY = offsetY + py + .5;
                var color = new double[4];
                foreach (var layer in layers)
                {
                    if (localX < layer.Left || localY < layer.Top || localX >= layer.Left + layer.Width || localY >= layer.Top + layer.Height) continue;
                    double[] source = Sample(layer.Raster, (localX - layer.Left) / layer.Width, (localY - layer.Top) / layer.Height);
                    if (layer.Tint) Tint(source, layer.Hue, layer.Saturation, layer.Value);
                    double alpha = source[3] + color[3] * (1 - source[3]);
                    for (int channel = 0; channel < 3; channel++)
                        color[channel] = alpha == 0 ? 0 : (source[channel] * source[3] + color[channel] * color[3] * (1 - source[3])) / alpha;
                    color[3] = alpha;
                }
                for (int channel = 0; channel < 4; channel++)
                    pixels[(py * width + px) * 4 + channel] = (byte)Math.Clamp((int)Math.Round(color[channel] * 255), 0, 255);
            }
        return pixels;
    }

    private static double[] Sample(CrystalSphereAssets.Raster raster, double u, double v)
    {
        double x = u * raster.Width - .5, y = v * raster.Height - .5;
        int x0 = (int)Math.Floor(x), y0 = (int)Math.Floor(y);
        double fx = x - x0, fy = y - y0;
        var result = new double[4];
        for (int dy = 0; dy < 2; dy++)
            for (int dx = 0; dx < 2; dx++)
            {
                int offset = (Math.Clamp(y0 + dy, 0, raster.Height - 1) * raster.Width + Math.Clamp(x0 + dx, 0, raster.Width - 1)) * 4;
                double weight = (dx == 0 ? 1 - fx : fx) * (dy == 0 ? 1 - fy : fy);
                for (int channel = 0; channel < 4; channel++) result[channel] += raster.Rgba[offset + channel] / 255.0 * weight;
            }
        return result;
    }

    // 配布物のhsv.gdshaderはHSV変換ではなくYIQ空間の回転を使う。
    private static void Tint(double[] color, double hue, double saturation, double value)
    {
        double yy = .2989 * color[0] + .5870 * color[1] + .1140 * color[2];
        double ii = .5959 * color[0] - .2774 * color[1] - .3216 * color[2];
        double qq = .2115 * color[0] - .5229 * color[1] + .3114 * color[2];
        double angle = (1 - hue) * 6.283185, c = Math.Cos(angle), s = Math.Sin(angle);
        (ii, qq) = ((ii * c - qq * s) * saturation, (ii * s + qq * c) * saturation);
        // 配布shaderの係数行列の逆行列。
        color[0] = (1.003061441 * yy + .955204739 * ii + .619283364 * qq) * value;
        color[1] = (.999257447 * yy - .271767480 * ii - .646486097 * qq) * value;
        color[2] = (.996673809 * yy - 1.105115663 * ii + 1.705118781 * qq) * value;
    }

    private static string Encode(byte[] rgba)
    {
        using var output = new MemoryStream();
        using (var gzip = new GZipStream(output, CompressionLevel.SmallestSize, true)) gzip.Write(rgba);
        return Convert.ToBase64String(output.ToArray());
    }
}
