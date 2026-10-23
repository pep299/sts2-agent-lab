"""利用者が用意した入力から、repo内の追跡しない専用環境を作る。"""
from pathlib import Path
import json
import shutil
import subprocess

from configuration import LOCAL, PROFILE_TEMPLATE, MANIFEST, RESULTS, load_config, resolve_path, dotnet_command
from runtime import sha, write_json, GAME_HASH

def prepare():
    config = load_config()
    source = resolve_path(config['paths']['source_app'])
    progress = resolve_path(config['paths']['progress'])
    settings = resolve_path(config['paths']['settings'])
    app = LOCAL / 'apps/SlayTheSpire2.app'
    if app.exists() or PROFILE_TEMPLATE.exists():
        raise FileExistsError('Prepared app or profile already exists; use a new configured local_root')
    for path in [source, progress, settings]:
        if not path.exists():
            raise FileNotFoundError(path)
    game = source / 'Contents/Resources/data_sts2_macos_arm64/sts2.dll'
    if config['qualification']['game_sha256'] != GAME_HASH or sha(game) != GAME_HASH:
        raise ValueError('Game identity differs from the qualified v0.111.0 Mac build')
    if sha(progress) != config['qualification']['progress_sha256']:
        raise ValueError('Progress identity differs from the explicit configuration')
    dotnet = dotnet_command()
    app.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['/bin/cp', '-cR', str(source), str(app)], check=True)
    saves = PROFILE_TEMPLATE / 'default/1/modded/profile1/saves'
    saves.mkdir(parents=True)
    shutil.copy2(progress, saves / 'progress.save')
    options = json.loads(settings.read_text())
    options.update(language='eng', skip_intro_logo=True)
    write_json(PROFILE_TEMPLATE / 'default/1/settings.save', options)
    prefs = dict(bestiary_actions_preferred=True, fast_mode='normal', keyboard_mode=False,
                 long_press=False, mute_in_background=True, phobia_mode=False, schema_version=2,
                 screenshake=2, show_card_indices=False, show_mp_drawings=True,
                 show_run_timer=False, text_effects_enabled=True, upload_data=False)
    (saves / 'prefs.save').write_text(json.dumps(prefs))
    override = '[application]\nconfig/use_custom_user_dir=true\nconfig/custom_user_dir_name="profile"\n[display]\nwindow/size/mode=0\n'
    for folder in [app / 'Contents/MacOS', app / 'Contents/Resources']:
        (folder / 'override.cfg').write_text(override)
    manifest = dict(executable=str(app / 'Contents/MacOS/Slay the Spire 2'),
                    gameData=str(app / 'Contents/Resources/data_sts2_macos_arm64'),
                    dotnet=dotnet, gameVersion='v0.111.0', gameCommit='41cef1ea',
                    executableSha256=sha(app / 'Contents/MacOS/Slay the Spire 2'), gameSha256=GAME_HASH,
                    progressSource=str(progress), progressSha256=sha(progress),
                    profileFiles={str(p.relative_to(PROFILE_TEMPLATE)):sha(p) for p in PROFILE_TEMPLATE.rglob('*') if p.is_file()},
                    sourceApp=str(source))
    RESULTS.mkdir(parents=True, exist_ok=True)
    write_json(MANIFEST, manifest)
    print(json.dumps({'prepared':str(app), 'gameSha256':GAME_HASH}))

if __name__ == '__main__':
    prepare()
