# yomiage

VOICEVOX COREでDiscordのテキストチャンネル投稿をボイスチャンネルへ読み上げるPython botです。
[`tanetakumi/voicebot`](https://github.com/tanetakumi/voicebot) のRust実装を参考に、
単体で動かしやすい構成へ移植しています。

- [初回セットアップ](#セットアップ)
- [更新と再起動](#更新と再起動)
- [起動時のトラブルシューティング](#起動時のトラブルシューティング)
- [音声合成モード](#音声合成モード)
- [Discord コマンド](#discord-コマンド)
- [読み上げの制限](#読み上げの制限)
- [環境変数](#環境変数)

## 機能

- `/join`: 実行者がいるボイスチャンネルへ参加
- Botへのメンション: メンションした人がいるボイスチャンネルへ参加
- `/leave`: ボイスチャンネルから退出
- `/skip`: 再生中の読み上げを停止
- `/s`: `/skip` の短縮版
- `/dict add|remove|list`: サーバー辞書の管理
- `/voice list|license`: VOICEVOXのキャラクター名、話者ID、クレジット表記を表示
- `/settings show|mention|read_name|serverchat|default_speaker|user_speaker|clear_user_speaker`: 読み上げ設定
- 参加時のテキストチャンネルに投稿されたメッセージをVOICEVOX COREで読み上げ
- VC接続時にBot自身をSelf Deafにして、他ユーザーの音声を受信しない
- 接続中のVCから人が全員退出したら自動退出
- Rust版と同じ考え方のトークンバケット式レート制限
- SQLiteによるローカル辞書保存
- URL、時刻、コード片、括弧などの簡易読み替え
- Discordメンション、ロール、チャンネル、DiscordチャンネルURLの読み替え
- 投稿者名の読み上げ
- ユーザーごとのVOICEVOX話者ID設定
- 音声合成モードの切り替え（通常合成 / ストリーミング合成 / 自動）。`.env` で設定

## 対応OS

**実行環境はLinux (x86_64) を想定しています。** CIも `ubuntu-latest` 上でのみ実行しています。

開発・テスト用に、Windows (x86_64) でも公式の `voicevox_core` wheel を使って `uv sync` と
`pytest` などを実行できるようにしています。ただしWindows上でのBot実行は検証していません。

## 必要なもの

- Linux
- Python 3.12
- uv
- ffmpeg
- Discord Bot Token
- VOICEVOX CORE の実行ファイル一式

Discord Developer Portalでは、Botに次の権限とIntentを付けてください。

- `MESSAGE CONTENT INTENT`
- `View Channels`
- `Send Messages`
- `Embed Links`（`/voice list`・`/voice license` の埋め込み表示に必要）
- `Read Message History`
- `Connect`
- `Speak`
- `Use Voice Activity`

VOICEVOX CORE はPyPIだけでは完結しません。このプロジェクトではPython wheelを依存に含めていますが、
実行時には別途VOICEVOX COREのONNX Runtime、OpenJTalk辞書、`.vvm` モデルが必要です。
`VOICEVOX_MODEL_PATH` に `.vvm` ファイルを指定した場合、そのファイルと同じディレクトリにある
`.vvm` もまとめてロードします。ディレクトリ自体を指定した場合は、その中の `.vvm` をロードします。

## セットアップ

以下は **Ubuntu / Linux x86_64・CPU実行** の手順です。
初回導入は上から順番に実行してください。すでに導入済みの場合は[更新と再起動](#更新と再起動)を参照してください。

### 1. OSのパッケージとuvを準備する

```bash
sudo apt update
sudo apt install -y git curl ca-certificates ffmpeg libopus0 unzip jq nano
curl -LsSf https://astral.sh/uv/install.sh | sh
```

uvのインストーラーが表示する案内に従ってシェルを開き直し、次を確認してください。
インストール方法の詳細は[uv公式ドキュメント](https://docs.astral.sh/uv/getting-started/installation/)を参照してください。

```bash
uv --version
ffmpeg -version
```

### 2. プロジェクトを取得して作業場所へ移動する

新規導入では、Botを置きたい親フォルダーで次を実行します。

```bash
git clone https://github.com/sudatti624/VoiceBot.py.git
cd VoiceBot.py
```

以降のコマンドは、`pyproject.toml` と `README.md` がある **プロジェクト直下** で実行します。
すでにclone済みの場合は、cloneせずにそのディレクトリへ移動します（パスは実際の配置に置き換えてください）。

```bash
cd /path/to/VoiceBot.py
pwd
ls pyproject.toml README.md
```

### 3. Pythonと依存関係をインストールする

```bash
uv python install 3.12
uv sync --locked
```

`.venv/` はuvが作成します。手動で仮想環境を有効化する必要はありません。
**`uv sync` で入るのはPython側の依存関係です。次のRuntime・辞書・モデルの取得も必要です。**

### 4. VOICEVOXのRuntime・辞書・モデルを取得する

[公式ダウンローダー](https://github.com/VOICEVOX/voicevox_core/blob/0.17.1/docs/guide/user/downloader.md)を使います。
モデルの利用条件は、ダウンロードしたファイル内のREADMEも確認してください。

```bash
curl -fL https://github.com/VOICEVOX/voicevox_core/releases/download/0.17.1/download-linux-x64 -o download
chmod +x download
./download --only onnxruntime --devices cpu
./download --only dict
./download --only models --models-version 0.17.0
```

標準の展開先はプロジェクト直下の `voicevox_core/` です。取得後、実際の配置を確認します。

```bash
find "$PWD/voicevox_core" -name 'libvoicevox_onnxruntime.so*' -type f
find "$PWD/voicevox_core/dict" -maxdepth 1 -type d
find "$PWD/voicevox_core/models" -name '*.vvm' -type f
```

**ONNX Runtimeのファイル名に含まれるバージョン番号は、取得したものによって異なります。**
`.env.example` の `1.17.3` をそのまま使わず、上のコマンドで表示された実在するファイルのパスを設定してください。

### 5. Discordと環境変数を設定する

Discord Developer PortalでBotを作成し、BotページでTokenを取得して
`MESSAGE CONTENT INTENT` を有効にします。OAuth2の招待URLでは `bot` と
`applications.commands` のスコープを指定し、[必要なもの](#必要なもの)に記載した権限でサーバーへ招待してください。

初回だけ環境変数ファイルを作ります。既存の `.env` がある場合は、このコピーを省略してください。

```bash
cp .env.example .env
```

`.env` をエディターで開き、最低限、次の値を設定します。
下のRuntimeパスは **1.23.2が見つかった場合の例** です。手順4で確認したパスに置き換えてください。

```bash
nano .env
```

nanoでは `Ctrl+O` → Enterで保存し、`Ctrl+X` で終了します。

```env
DISCORD_BOT_TOKEN=あなたのDiscord Botトークン
VOICEVOX_ONNXRUNTIME_PATH=./voicevox_core/onnxruntime/lib/libvoicevox_onnxruntime.so.1.23.2
OPEN_JTALK_DIC_DIR=./voicevox_core/dict/open_jtalk_dic_utf_8-1.11
VOICEVOX_MODEL_PATH=./voicevox_core/models/vvms
VOICEVOX_MODEL_EXCLUDE=
VOICEVOX_ACCELERATION_MODE=CPU
VOICEVOX_SYNTHESIS_MODE=normal
```

最初は `normal` で起動を確認してください。ストリーミングを使う場合は、
[音声合成モード](#音声合成モード)に従ってCORE・モデル・話者IDの対応を確認してから変更します。
Tokenを含む `.env` はGitに登録しないでください。

### 6. 起動して読み上げを確認する

```bash
uv run yomiage
```

`VOICEVOX CORE initialized` に続いて `Bot ready:` が表示されれば、Discordへの接続まで完了しています。
Discordで自分がVCに入り、読み上げたいテキストチャンネルでBotをメンションするか `/join` を実行します。
同じテキストチャンネルへ投稿して音声が出ることを確認してください。

フォアグラウンド実行は `Ctrl+C` で停止します。常時稼働にsystemdなどを使う場合も、
まず上の手順で起動を確認し、サービスの作業ディレクトリをプロジェクト直下に設定してください。

## 更新と再起動

稼働中のBotを停止してから、プロジェクト直下で実行します。
手動起動の場合は `Ctrl+C`、サービスの場合はそのサービスの停止操作を使ってください。

```bash
git pull --ff-only
uv sync --locked
uv run yomiage
```

サービス運用では、最後の `uv run yomiage` の代わりに既存のサービスを起動してください。
二重起動は避けてください。`git pull` がローカル変更や履歴の分岐で止まった場合は、
表示された内容を確認し、変更を保存・整理してから再実行します。

既存の `.env` は維持し、追加された設定は `.env.example` と見比べて反映します。
Runtime・辞書・モデルは `git pull` や `uv sync` では更新されません。
それらも更新した場合は、実際のファイル名・配置と `.env` のパスを再確認してください。

## 起動時のトラブルシューティング

### `VOICEVOX_ONNXRUNTIME_PATH must be a file` と表示される

設定されたパスにRuntimeがありません。プロジェクト直下で次を実行します。

```bash
pwd
find "$PWD/voicevox_core" -name 'libvoicevox_onnxruntime.so*' -type f
```

ファイルが見つかったら、表示された絶対パスを `.env` の `VOICEVOX_ONNXRUNTIME_PATH` に設定し、
Botを再起動してください。何も見つからない場合は、セットアップ手順4でダウンローダーを用意し、
`./download --only onnxruntime --devices cpu` で取得してから再確認します。

相対パスはBotを起動した作業ディレクトリを基準に解決されます。
手動起動時はプロジェクト直下へ `cd` し、サービス運用時は作業ディレクトリの設定も確認してください。

### 辞書またはモデルが見つからない

`OPEN_JTALK_DIC_DIR must be a directory` は辞書ディレクトリ、
`VOICEVOX_MODEL_PATH must be a .vvm file or a directory ...` はモデルの配置を確認します。
セットアップ手順4の `find` で実在する場所を確認し、`.env` の該当パスを設定してください。
未取得なら `./download --only dict` または `./download --only models --models-version 0.17.0` を実行します。

### `cannot import name 'SynthesisStream'` と表示される

古いBotコードが、インストール済みCOREにないエクスポートを必須インポートしている可能性があります。
[更新と再起動](#更新と再起動)の手順でコードとPython依存関係をそろえてください。
現在のコードではこのエクスポートを必須にせず、COREにストリーミングAPIがない場合は
`normal` / `auto` で通常合成を利用できます。`streaming` には対応COREと新形式VVMが必要です。

### Token・Intent・ffmpegのエラー

- `DISCORD_BOT_TOKEN is required`: プロジェクト直下の `.env` にTokenを設定してください。
- Discordの認証失敗: Tokenが有効か確認し、再発行した場合は `.env` を更新して再起動してください。
- Privileged Intentのエラー: Developer Portalで `MESSAGE CONTENT INTENT` を有効にしてください。
- `ffmpeg executable not found`: `ffmpeg -version` を確認し、未導入なら `sudo apt install ffmpeg` を実行してください。
  導入済みなのにPATHが通らない場合は、`which ffmpeg` で調べた絶対パスを `.env` の `FFMPEG_PATH` に設定します。

`audioop` の非推奨警告はPython 3.12で `discord.py` を読み込む際に出ることがあります。
この警告だけでは起動失敗ではありません。停止した場合は、その後の例外と起動ログを確認してください。

### 「ボイスチャンネルに接続できませんでした」と返信される

BotがVCへの接続に失敗しています。ログの `Failed to join voice channel` に続く例外を確認してください。
よくある原因は次のとおりです。

- BotにそのVCの `Connect`・`Speak` 権限がない
- VCの人数上限に達している
- `libopus0` が入っていない（`sudo apt install libopus0`）
- ネットワークの問題で接続がタイムアウトした

## VOICEVOX CORE の配置例

リポジトリ直下に `voicevox_core/` を置く場合の例です。Runtimeのファイル名は実物に合わせてください。

```text
voicevox_core/
├── onnxruntime/lib/libvoicevox_onnxruntime.so.1.23.2
├── dict/open_jtalk_dic_utf_8-1.11/
└── models/vvms/0.vvm
```

配置場所を変える場合は、`.env` の `VOICEVOX_ONNXRUNTIME_PATH`、
`OPEN_JTALK_DIC_DIR`、`VOICEVOX_MODEL_PATH` を変更してください。

## VOICEVOX CORE 0.17.1 への更新

このプロジェクトは VOICEVOX CORE **0.17.1** のPython wheelを使います（`uv sync` で入ります）。
0.16系からの主な違いは次のとおりです。

- **ONNX Runtime**: 推奨バージョンが1.23.2になりました。1.17〜1.29に対応しており、従来の
  `libvoicevox_onnxruntime.so.1.17.3` も引き続き使えます。1.23.2に更新する場合は
  `VOICEVOX_ONNXRUNTIME_PATH=./voicevox_core/onnxruntime/lib/libvoicevox_onnxruntime.so.1.23.2`
  のように設定してください。
- **新形式VVM**: 新形式（`vvm_format_version=2`）のVVMを読み込めるようになりました。
  ストリーミング合成ができるのは、新形式VVMに含まれる `streaming_talk` タイプのスタイルだけです。
- **旧形式VVM**: 0.16系で使っていたVVMもそのまま読み込めます。ただしスタイルが `talk` タイプなので、
  通常合成でのみ使われます。
- **CPU/GPU設定**: `VOICEVOX_ACCELERATION_MODE` とモデルの遅延ロードの動作は変わりません。

公式ダウンローダーで新形式VVMを取得する例です（詳細は
[公式ドキュメント](https://github.com/VOICEVOX/voicevox_core/blob/0.17.1/docs/guide/user/downloader.md)）。

```bash
./download --only models --models-version 0.17.0
```

VVMの形式は、次のコマンドで確認できます（`2` なら新形式です）。

```bash
unzip -p ./voicevox_core/models/vvms/0.vvm manifest.json | jq .vvm_format_version
```

新しいVVMに入れ替えたら、起動ログの `Available VOICEVOX style IDs` と
`Streaming-capable VOICEVOX style IDs` を確認してください。また、`/voice list` で話者IDを確認し、
`VOICEVOX_SPEAKER_ID` やサーバー・ユーザーごとの話者ID設定がまだ存在するかを確かめてください。

## 音声合成モード

`.env` の `VOICEVOX_SYNTHESIS_MODE` で音声合成の方式を選びます。値の大文字・小文字は区別しません。
設定は全サーバー共通です。**変更はBotの再起動後に反映されます。**
Discordコマンドでは変更できず、SQLiteにも保存しません。

| モード | 動作 |
| :- | :- |
| `normal`（デフォルト） | 従来どおり、音声全体を合成してから再生します。ストリーミング機能は使いません。 |
| `streaming` | `streaming_synthesis()` で約0.3秒ずつ合成し、合成が終わるのを待たずに再生を始めます。 |
| `auto` | 対応しているスタイルではストリーミングを使い、それ以外は通常合成を使います。 |

```env
VOICEVOX_SYNTHESIS_MODE=auto
```

各モードの細かな動作は次のとおりです。

- **`streaming`**:
  - 起動時にCOREのストリーミングAPIと、`VOICEVOX_SPEAKER_ID` が `streaming_talk` スタイルかどうかを確認します。
    対応していない場合はエラーになり、起動しません。
  - ユーザーが非対応の話者IDを設定している場合は、警告ログを出したうえで通常合成で読み上げます。
  - 合成中にエラーが起きた場合は、そのメッセージを読み上げずにスキップします（再試行はしません）。
- **`auto`**:
  - ストリーミング合成が**再生開始前に**失敗した場合だけ、通常合成でもう一度読み上げます。
  - **再生開始後**に失敗した場合は、同じ文を二重に読み上げないよう、通常合成には切り替えません。
    それまでに合成できた部分だけを再生します。
  - 同じスタイルで3回続けて失敗すると、そのスタイルは再起動まで通常合成に固定されます。
    これにより、失敗による再試行が際限なく続くのを防ぎます。

どのモードでも、音声キャッシュ（`VOICEVOX_CACHE_SIZE`）にある文は合成を省略して即座に再生します。
ストリーミングで合成した音声も、最後まで合成できた場合に限りキャッシュします。
`/skip` や合成エラーで途中までしか合成しなかった音声はキャッシュしません。

### ストリーミングのバッファ設定

| 変数 | デフォルト | 説明 |
| :- | :- | :- |
| `VOICEVOX_STREAM_SEGMENT_SECONDS` | `0.3` | 1回に合成する長さ（秒）。VOICEVOX COREのデフォルトと同じ値です。0.0054より大きく10以下で指定します。 |
| `VOICEVOX_STREAM_BUFFER_SECONDS` | `0.5` | 再生を始める前に貯めておく音声の長さ（秒）。0以上10以下で指定します。 |

- バッファが貯まる前に合成が終わった短い文は、待たずにすぐ再生します。
- 再生中にバッファが空になった場合（アンダーラン）は無音を流します。その後、
  `VOICEVOX_STREAM_BUFFER_SECONDS` 分が貯まってから再生を再開します。
- バッファの上限は「2秒」と「バッファ秒数 + セグメント秒数×2」の大きいほうです。上限に達すると、
  再生が進むまで合成を一時停止します。
- 音切れが多いときは `VOICEVOX_STREAM_BUFFER_SECONDS` を増やしてください。CPUが遅く、
  合成が再生に追いつかない場合は `VOICEVOX_STREAM_SEGMENT_SECONDS` も少し大きくしてください。
- 読み上げ開始をもっと早くしたい場合は、`VOICEVOX_STREAM_BUFFER_SECONDS` を減らしてください。

### 性能ログ

`VOICEVOX_PERFORMANCE_LOG=true` にすると、読み上げ1件ごとに次のようなログを出力します。

```text
INFO yomiage.perf: speech_perf guild=123 mode=auto path=streaming cache_hit=false outcome=completed synthesis_start_ms=0.4 first_audio_ms=180.2 playback_start_ms=545.9 synthesis_total_ms=812.7 playback_end_ms=2650.3 underruns=0
```

時間はすべて、そのメッセージの読み上げ処理を開始した時点からのミリ秒です。

| 項目 | 内容 |
| :- | :- |
| `mode` | 設定されているモード |
| `path` | 実際に使った方式（`normal` / `streaming` / `streaming->normal`（フォールバック）/ `cache`） |
| `cache_hit` | キャッシュにあったかどうか |
| `outcome` | 結果（`completed` / `cancelled`（skip・退出）/ `failed`） |
| `synthesis_start_ms` | 合成スレッドで合成を始めた時刻 |
| `first_audio_ms` | 最初の音声データができた時刻（通常合成では音声全体ができた時刻） |
| `playback_start_ms` | Discordの再生スレッドが最初に音声を読み出した時刻 |
| `synthesis_total_ms` | 合成開始から合成完了までの時間。合成ロックの待ち時間を含みます。ストリーミングでは、バッファが上限に達して合成を一時停止していた時間も含みます |
| `playback_end_ms` | 再生が終わった時刻 |
| `underruns` | アンダーランが起きた回数（ストリーミング時のみ） |

実際に計測できなかった値（キャッシュヒット時の合成時間など）は `n/a` と表示します。推定値は出しません。
通常合成とストリーミング合成の速さを比べるには、同じ文を `normal` と `streaming` でそれぞれ読み上げて、
`playback_start_ms` を比べてください。このとき2回目以降はキャッシュにヒットするので、
`VOICEVOX_CACHE_SIZE=0` にするか、別の文で比べてください。

### トラブルシューティング

- **`VOICEVOX_SYNTHESIS_MODE=streaming requires ...` と表示されて起動しない**:
  COREにストリーミングAPIがないか、デフォルト話者が新形式VVMの `streaming_talk` スタイルではありません。
  次のいずれかで対処してください。
  - `uv sync --locked` で対応するCOREのPython wheelをインストールする
  - 新形式VVMを導入する
  - 起動ログの `Streaming-capable VOICEVOX style IDs` にある話者IDを `VOICEVOX_SPEAKER_ID` に指定する
  - `auto` を使う
- **`VOICEVOX_SYNTHESIS_MODE must be one of ...` と表示される**: 値は `normal`、`streaming`、
  `auto` のいずれかにしてください。
- **`auto` にしてもストリーミングにならない**: 性能ログの `path` を確認してください。
  - `path=normal` の場合: COREにストリーミングAPIがないか、そのスタイルが `streaming_talk` ではありません。
    起動時の警告ログと、`Streaming-capable VOICEVOX style IDs` を確認してください。
  - `path=streaming->normal` の場合: ストリーミングに失敗しています。直前の警告ログを確認してください。
  - 3回続けて失敗したスタイルは、再起動まで通常合成に固定されます。
- **音が途切れる、または `underruns` が増える**: 合成が再生に追いついていません。
  - `VOICEVOX_STREAM_BUFFER_SECONDS` を増やしてください。
  - `VOICEVOX_ACCELERATION_MODE=GPU` の利用を検討してください。
  - VOICEVOX COREのPython API（非asyncio版）は、合成中にPythonのGILを保持します
    （[voicevox_core#1476](https://github.com/VOICEVOX/voicevox_core/issues/1476)）。
    そのため、複数サーバーで同時に読み上げると再生スレッドの動作が遅れることがあります。
- **`/skip` の後に次の読み上げが少し遅れる**: 停止の時点で合成中だったセグメント（約0.3秒分）は、
  合成が終わるまで待ちます。通常合成の場合は、合成中の音声全体を待ちます。

## 低遅延再生のしくみ

1. 合成スレッドが `streaming_synthesis()` から順にPCMセグメントを受け取ります。
   各セグメントの合成はVOICEVOXのロックを取得して行うので、他のサーバーと交互に合成されます。
2. 受け取ったセグメントは、その場でDiscord用の48kHz・16-bit・ステレオに変換します。
   補間に必要なデータを次のセグメントへ引き継ぐので、セグメントの境界でノイズは出ません。
3. 変換した音声は20ms単位のフレームに分けて `discord.AudioSource`（`StreamingPCMSource`）に貯めます。
   Discordの再生スレッドは、ここから音声を読み出して再生します。
4. 合成と再生は並行して進みます。全セグメントがそろうまで待つことはありません。
   ストリーミング再生ではffmpegを使いません。

`/skip`、`/leave`、自動退出、再接続、Bot終了のときは、次の処理を行います。

- 再生を止め、バッファを破棄します。
- 合成スレッドは、合成中のセグメントが終わった時点で停止します。
- 古いセッションの音声が、新しいセッションで再生されることはありません。

## Discord コマンド

- `/join`: 実行したテキストチャンネルを読み上げ対象にして、実行者のVCへ接続
- `@Bot`: 投稿した人のVCへ接続し、そのテキストチャンネルを読み上げ対象に設定
- `/leave`: VCから退出
- `/skip`: 現在の読み上げを停止
- `/s`: `/skip` の短縮版
- `s`, `S`, `!s`, `!S`, `！s`, `！S`: テキスト投稿で読み上げを停止
- `/dict add`: サーバー辞書へ単語を追加
- `/dict remove`: サーバー辞書から単語を削除
- `/dict list`: サーバー辞書を表示
- `/voice list`: VOICEVOXのキャラクター名、スタイル、話者IDを埋め込みで表示
- `/voice license`: VOICEVOXキャラクターのクレジット表記と利用規約URLを埋め込みで表示

`/voice` の一覧はページ移動ボタン付きで1ページずつ表示します。ボタンは1分後に消えます。

### サーバー辞書

- 1サーバーあたり最大27件まで登録できます。単語は120文字以内、読みは80文字以内です。
- `regex:true` で正規表現として登録できます。`(1)`、`(2)` と書くと、読みの中にキャプチャグループの内容を埋め込めます。
- `(a+)+` のように処理が極端に重くなりうる正規表現（入れ子の量指定子）は登録できません。
  Linuxでは、1件の正規表現置換が0.5秒を超えるとその辞書項目をスキップします。
- `/dict list` は、Discordの1メッセージの文字数上限を超える場合は複数のメッセージに分けて表示します。

Botの返信には辞書の単語などユーザーの入力が含まれますが、`@everyone`・`@here`・ロール・ユーザーへの
メンション通知は発生しません。

## 読み上げの制限

荒らしや長文で読み上げが詰まらないよう、次の制限があります。

- **レート制限**: サーバーごとに `MAX_TOKENS`（デフォルト400）個のトークンを持ち、1投稿で文字数分
  （最大80）を消費します。10秒ごとに50トークン回復します。足りない場合は回復までの目安を返信し、その投稿は読みません。
- **読み上げ待ち**: サーバーごとに最大50件です。超えた投稿はスキップし、その旨を返信します。
- **文字数**: 投稿は先頭512文字だけを変換し、変換後に80文字を超えた部分は「いかりゃく」と読みます。
- 絵文字など読める文字を含まない投稿は読み上げません。

## 読み上げ設定

- `/settings show`: 現在の設定を表示
- `/settings mention mode:名前/チャンネル名`: メンションやDiscordチャンネルURLを名前で読む
- `/settings mention mode:リンク省略`: メンションやDiscordチャンネルURLを `りんくしょうりゃく` と読む
- `/settings read_name enabled:true`: 読み上げ前に投稿者名を読む
- `/settings read_name enabled:false`: 投稿者名を読まない
- `/settings serverchat enabled:true`: ServerChat形式の先頭 `[...]<...>` を読まない
- `/settings serverchat enabled:false`: ServerChat形式の先頭 `[...]<...>` をそのまま読む
- `/settings default_speaker speaker_id:<ID>`: サーバーのデフォルト話者IDを変更
- `/settings user_speaker speaker_id:<ID>`: 自分の話者IDを設定
- `/settings clear_user_speaker`: 自分の話者ID設定を解除

これらのスラッシュコマンドはDiscordの `サーバー管理` 権限なしで実行できます。

## 開発用コマンド

```bash
uv run ruff check .
uv run basedpyright
uv run pytest
uv build
```

`uv build` の成果物は `dist/` に出力されます。`dist/`、`.venv/`、`.env`、SQLite DB、
VOICEVOX CORE本体はGit管理対象外です。

### テスト

`tests/` 配下に、Discord接続やVOICEVOX COREの実モデルなしで実行できる単体テストを用意しています。

- `test_rate_limit.py`: トークンバケットのレート制限ロジック
- `test_translator.py`: 辞書適用・正規表現・英単語/ローマ字変換・文字数省略などのテキスト変換
- `test_config.py`: 環境変数の検証ロジック
- `test_database.py`: SQLiteへの読み書きとキャッシュの整合性
- `test_session.py`: ボイスセッションの生成・再接続時の後始末・終了処理
- `test_bot_voice.py`: VC接続時のSelf Deaf設定、接続失敗時の返信、メンション通知の抑止、投稿テキストの整形、`/skip` による合成中の読み上げのキャンセル
- `test_commands.py`: 返信に含めるユーザー入力のエスケープ、`/dict list` のメッセージ分割、`/voice` の埋め込みページ
- `test_voice_catalog.py`: 話者ID一覧とクレジット表記のデータ、埋め込みのフィールド数上限
- `test_audio_stream.py`: PCM変換（48kHz・ステレオ化）、チャンク境界、20msフレーム分割、プリバッファ、アンダーラン、バックプレッシャー
- `test_streaming_session.py`: `normal` / `streaming` / `auto` の各モード、フォールバック、二重読み上げの防止、`/skip`・`/leave`・再接続、複数サーバーでの同時再生
- `test_voicevox_streaming.py`: 途中までしか合成しなかった音声をキャッシュしないこと、キャッシュキー、非対応VVMの扱い、起動時のモード検証

```bash
uv run pytest
```

### CI

`.github/workflows/ci.yml` で、push・PR時に `uv sync` → `ruff check` → `basedpyright` →
`pytest` → `uv build` を `ubuntu-latest` 上で実行しています。

## 環境変数

- `DISCORD_BOT_TOKEN`: Discord Bot token
- `BOT_ID`: 同じDBを複数のBotで共有するとき、辞書と設定を分けるためのID。デフォルトは `0`
- `YOMIAGE_DB`: SQLite DBのパス。デフォルトは `yomiage.sqlite3`
- `MAX_TOKENS`: サーバーごとの読み上げトークン上限（1〜100000）。デフォルトは `400`。[読み上げの制限](#読み上げの制限)を参照
- `VOICEVOX_SPEAKER_ID`: デフォルトの話者ID。デフォルトは `3`。読み込んだモデルにないIDだと起動しません
- `VOICEVOX_SPEED`: 話速（0より大きく10以下）。デフォルトは `1.2`
- `VOICEVOX_ONNXRUNTIME_PATH`: `libvoicevox_onnxruntime.so...` のパス（ONNX Runtime 1.17〜1.29に対応。推奨は1.23.2）
- `OPEN_JTALK_DIC_DIR`: OpenJTalk辞書ディレクトリ
- `VOICEVOX_MODEL_PATH`: `.vvm` モデルファイル、または `.vvm` を含むディレクトリ
- `VOICEVOX_MODEL_EXCLUDE`: 読み込まない `.vvm`。例: `4.vvm`、複数なら `4.vvm,9.vvm`
- `VOICEVOX_ACCELERATION_MODE`: `CPU`, `AUTO`, `GPU` のいずれか。デフォルトは `CPU`
- `VOICEVOX_CACHE_SIZE`: 音声合成キャッシュ数（0〜100000、`0` で無効）。デフォルトは `100`
- `FFMPEG_PATH`: ffmpegコマンド、または実行ファイルの絶対パス。デフォルトは `ffmpeg`。
  systemdなどでPATHが通らない場合は絶対パスを指定してください
- `VOICEVOX_SYNTHESIS_MODE`: `normal`, `streaming`, `auto` のいずれか。デフォルトは `normal`。[音声合成モード](#音声合成モード)を参照
- `VOICEVOX_STREAM_SEGMENT_SECONDS`: ストリーミングで1回に合成する長さ（秒）。デフォルトは `0.3`
- `VOICEVOX_STREAM_BUFFER_SECONDS`: ストリーミングで再生を始める前に貯める長さ（秒）。デフォルトは `0.5`
- `VOICEVOX_PERFORMANCE_LOG`: `true` で読み上げごとの性能ログを出力。デフォルトは `false`

## ライセンス

このプロジェクトはMIT Licenseで公開しています。詳細は [LICENSE](LICENSE) を参照してください。

このプロジェクトは [`tanetakumi/voicebot`](https://github.com/tanetakumi/voicebot) を参考にした
Python実装です。VOICEVOX CORE、VOICEVOXの音声モデル、その他依存ライブラリにはそれぞれ別の
ライセンスや利用条件があります。利用・配布時はそれらの条件も確認してください。

## Rust版との違い

元リポジトリはRustのDiscord bot、gRPC TTS server、Envoy、PostgreSQLで構成されています。
このPython版はまず動かしやすさを優先し、gRPC/Envoy/PostgreSQLを省いて単一プロセスにまとめています。
