using Godot;
using MegaCrit.Sts2.Core.Models;
using Sts2Recorder;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace Sts2.NativeSim.FullAppBridge;

internal static class NativeCrystalAssets
{
    private static readonly Lazy<string> catalog = new(BuildCatalog);
    private static readonly Lazy<CrystalSphereAssets> assets = new(() => CrystalSphereAssets.FromCatalog(CatalogJson));
    public static string CatalogJson => catalog.Value;
    public static CrystalSphereAssets Value => assets.Value;

    private static string BuildCatalog()
    {
        string[] names = ["big_gold", "gold", "curse", "relic", "common_potion", "uncommon_potion", "rare_potion", "card_outline", "card_back", "card_banner"];
        var images = names.Select(name => {
            string path = "res://images/events/crystal_sphere/crystal_sphere_" + name + ".png";
            var texture = ResourceLoader.Load<Texture2D>(path)
                ?? throw new InvalidOperationException("Crystal texture missing: " + path);
            using var image = texture.GetImage();
            if (image == null || image.IsEmpty()) throw new InvalidOperationException("Crystal texture pixels unavailable: " + path);
            if (image.IsCompressed() && image.Decompress() != Error.Ok)
                throw new InvalidOperationException("Crystal texture decompression failed: " + path);
            image.Convert(Image.Format.Rgba8);
            image.ClearMipmaps();
            byte[] rgba = image.GetData();
            if (rgba.Length != image.GetWidth() * image.GetHeight() * 4)
                throw new InvalidOperationException("Crystal texture is not RGBA8: " + path);
            using var bytes = new MemoryStream();
            using (var gzip = new GZipStream(bytes, CompressionLevel.SmallestSize, leaveOpen: true)) gzip.Write(rgba);
            return new { path, width = image.GetWidth(), height = image.GetHeight(), rgbaGzipBase64 = Convert.ToBase64String(bytes.ToArray()),
                rgbaSha256 = Convert.ToHexString(SHA256.HashData(rgba)).ToLowerInvariant() };
        }).ToArray();
        string gameAssemblySha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(CardModel).Assembly.Location))).ToLowerInvariant();
        return JsonSerializer.Serialize(new { schema = "crystal-assets-v1", gameVersion = "v0.111.0", gameAssemblySha256, images });
    }
}
