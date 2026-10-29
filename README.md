# yomiage

VOICEVOX COREでDiscordのテキストチャンネル投稿をボイスチャンネルへ読み上げるPython botです。
[`tanetakumi/voicebot`](https://github.com/tanetakumi/voicebot) のRust実装を参考に、
単体で動かしやすい構成へ移植しています。

- [初回セットアップ](#セットアップ)
- [更新と再起動](#更新と再起動)
- [起動時のトラブルシューティング](#起動時のトラブルシューティング)
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
- VOICEVOX CORE **0.17.1** のONNX Runtime・OpenJTalk辞書・`.vvm` モデル

Discord Developer Portalでは、Botに次の権限とIntentを付けてください。

- `MESSAGE CONTENT INTENT`
- `View Channels`
- `Send Messages`
- `Embed Links`（`/voice list`・`/voice license` の埋め込み表示に必要）
- `Read Message History`
- `Connect`
- `Speak`
- `Use Voice Activity`

VOICEVOX CORE のPython wheel（0.17.1）は `uv sync` で入りますが、
実行時には別途ONNX Runtime、OpenJTalk辞書、`.vvm` モデルが必要です（[手順4](#4-voicevoxのruntime辞書モデルを取得する)）。

## セットアップ

以下は **Ubuntu / Linux x86_64・CPU実行** の手順です。
初回導入は上から順番に実行してください。すでに導入済みの場合は[更新と再起動](#更新と再起動)を参照してください。

### 1. OSのパッケージとuvを準備する

```bash
sudo apt update
sudo apt install -y git curl ca-certificates ffmpeg libopus0 nano
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

VOICEVOX CORE **0.17.1** の[公式ダウンローダー](https://github.com/VOICEVOX/voicevox_core/blob/0.17.1/docs/guide/user/downloader.md)を使います。
モデルの利用条件は、ダウンロードしたファイル内のREADMEも確認してください。

```bash
curl -fL https://github.com/VOICEVOX/voicevox_core/releases/download/0.17.1/download-linux-x64 -o download
chmod +x download
./download --only onnxruntime --devices cpu
./download --only dict
./download --only models --models-version 0.17.0
```

0.16系で使っていた旧形式のモデルもそのまま読み込めます。

標準の展開先はプロジェクト直下の `voicevox_core/` です。取得後、実際の配置を確認します。

```bash
find "$PWD/voicevox_core" -name 'libvoicevox_onnxruntime.so*' -type f
find "$PWD/voicevox_core/dict" -maxdepth 1 -type d
find "$PWD/voicevox_core/models" -name '*.vvm' -type f
```

配置は次のようになります。**ONNX Runtimeのファイル名に含まれるバージョン番号は、取得したものによって異なります**
（1.17〜1.29に対応、推奨は1.23.2）。`.env` には上の `find` で表示された実在するファイルを設定してください。

```text
voicevox_core/
├── onnxruntime/lib/libvoicevox_onnxruntime.so.1.23.2
├── dict/open_jtalk_dic_utf_8-1.11/
└── models/vvms/0.vvm
```

### 5. Discordと環境変数を設定する

Discord Developer PortalでBotを作成し、BotページでTokenを取得して
`MESSAGE CONTENT INTENT` を有効にします。OAuth2の招待URLでは `bot` と
`applications.commands` のスコープを指定し、[必要なもの](#必要なもの)に記載した権限でサーバーへ招待してください。

初回だけ環境変数ファイルを作ります。既存の `.env` がある場合は、このコピーを省略してください。

```bash
cp .env.example .env
nano .env
```

nanoでは `Ctrl+O` → Enterで保存し、`Ctrl+X` で終了します。最低限、次の値を設定します。
パスは手順4で確認した実在するものに合わせてください。

```env
DISCORD_BOT_TOKEN=あなたのDiscord Botトークン
VOICEVOX_ONNXRUNTIME_PATH=./voicevox_core/onnxruntime/lib/libvoicevox_onnxruntime.so.1.17.3
OPEN_JTALK_DIC_DIR=./voicevox_core/dict/open_jtalk_dic_utf_8-1.11
VOICEVOX_MODEL_PATH=./voicevox_core/models/vvms
```

Tokenを含む `.env` はGitに登録しないでください。その他の設定は[環境変数](#環境変数)を参照してください。

### 6. 起動して読み上げを確認する

```bash
uv run yomiage
```

`VOICEVOX CORE initialized` に続いて `Bot ready:` が表示されれば、Discordへの接続まで完了しています。
Discordで自分がVCに入り、読み上げたいテキストチャンネルでBotをメンションするか `/join` を実行します。
同じテキストチャンネルへ投稿して音声が出ることを確認してください。

フォアグラウンド実行は `Ctrl+C` で停止します。常時稼働にsystemdなどを使う場合も、
まず上の手順で起動を確認し、サービスの作業ディレクトリをプロジェクト直下に設定してください。

### モデルの読み込みとメモリ

起動時は、各 `.vvm` から話者IDの一覧（メタデータ）だけを読み込みます。
モデル本体は、その話者が**初めて使われたときに**読み込みます。使わないモデルでメモリを消費しないためです。
そのため、再起動後に初めて使う話者は、読み上げ開始まで数秒かかることがあります。

使わないモデルは `VOICEVOX_MODEL_EXCLUDE` で除外できます。

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

### 以前のバージョンから更新する場合

上の3コマンドで更新できます。VOICEVOX COREのPython wheelは `uv sync --locked` で自動的に入れ替わります。
以前のバージョンに応じて、次も確認してください。

- **VOICEVOX CORE 0.16系の頃から使っている場合**:
  手元のONNX Runtime（`1.17.3` など）・辞書・モデルはそのまま使えます。取得し直す必要はありません。
  新しいキャラクターを使いたい場合だけ、[手順4](#4-voicevoxのruntime辞書モデルを取得する)の0.17.1のダウンローダーで
  モデルを取得してください。
- **ストリーミング合成（`VOICEVOX_SYNTHESIS_MODE`）を使っていた場合**:
  ストリーミング合成は、音声が途切れたり、Discordとの接続が切れたりする問題があったため削除しました。
  読み上げは常に「全文を合成してから再生」になります。`.env` に残っている次の設定は無視されるので、削除して構いません。

  ```env
  VOICEVOX_SYNTHESIS_MODE=...
  VOICEVOX_STREAM_SEGMENT_SECONDS=...
  VOICEVOX_STREAM_BUFFER_SECONDS=...
  VOICEVOX_PERFORMANCE_LOG=...
  ```
- **新しく追加された設定**: `VOICEVOX_CPU_NUM_THREADS`（合成に使うCPUスレッド数）を追加しました。
  設定しなければ従来どおり `4` です。詳しくは[環境変数](#環境変数)を参照してください。

## 起動時のトラブルシューティング

### `VOICEVOX_ONNXRUNTIME_PATH must be a file` と表示される

設定されたパスにRuntimeがありません。プロジェクト直下で次を実行します。

```bash
pwd
find "$PWD/voicevox_core" -name 'libvoicevox_onnxruntime.so*' -type f
```

ファイルが見つかったら、表示された絶対パスを `.env` の `VOICEVOX_ONNXRUNTIME_PATH` に設定し、
Botを再起動してください。何も見つからない場合は、[手順4](#4-voicevoxのruntime辞書モデルを取得する)で取得してから再確認します。

相対パスはBotを起動した作業ディレクトリを基準に解決されます。
手動起動時はプロジェクト直下へ `cd` し、サービス運用時は作業ディレクトリの設定も確認してください。

### 辞書またはモデルが見つからない

- `OPEN_JTALK_DIC_DIR must be a directory`: 辞書ディレクトリがありません。
- `VOICEVOX_MODEL_PATH must be a .vvm file or a directory ...`: モデルがありません。
- `No VOICEVOX model metadata could be read`: モデルはありますが読み込めません。
  ファイルが壊れていないか、ログの直前の例外を確認してください。

[手順4](#4-voicevoxのruntime辞書モデルを取得する)の `find` で実在する場所を確認し、`.env` の該当パスを設定してください。
未取得なら `./download --only dict` または `./download --only models --models-version 0.17.0` を実行します。

### Token・Intent・ffmpegのエラー

- `DISCORD_BOT_TOKEN is required`: プロジェクト直下の `.env` にTokenを設定してください。
- Discordの認証失敗: Tokenが有効か確認し、再発行した場合は `.env` を更新して再起動してください。
- Privileged Intentのエラー: Developer Portalで `MESSAGE CONTENT INTENT` を有効にしてください。
- `ffmpeg executable not found`: `ffmpeg -version` を確認し、未導入なら `sudo apt install ffmpeg` を実行してください。
  導入済みなのにPATHが通らない場合は、`which ffmpeg` で調べた絶対パスを `.env` の `FFMPEG_PATH` に設定します。
- `VOICEVOX_SPEAKER_ID=... is not available`: 起動ログの `Available VOICEVOX style IDs` にあるIDを指定してください。

`audioop` の非推奨警告はPython 3.12で `discord.py` を読み込む際に出ることがあります。
この警告だけでは起動失敗ではありません。停止した場合は、その後の例外と起動ログを確認してください。

### 「ボイスチャンネルに接続できませんでした」と返信される

BotがVCへの接続に失敗しています。ログの `Failed to join voice channel` に続く例外を確認してください。
よくある原因は次のとおりです。

- BotにそのVCの `Connect`・`Speak` 権限がない
- VCの人数上限に達している
- `libopus0` が入っていない（`sudo apt install libopus0`）
- ネットワークの問題で接続がタイムアウトした

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
一覧はVOICEVOXの全キャラクターを表示するため、読み込んでいないモデルの話者IDも含まれます。
使えるIDは起動ログの `Available VOICEVOX style IDs` で確認できます。

### サーバー辞書

- 1サーバーあたり最大27件まで登録できます。単語は120文字以内、読みは80文字以内です。
- `regex:true` で正規表現として登録できます。`(1)`、`(2)` と書くと、読みの中にキャプチャグループの内容を埋め込めます。
- `(a+)+` のように処理が極端に重くなりうる正規表現（入れ子の量指定子）は登録できません。
  Linuxでは、1件の正規表現置換が0.5秒を超えるとその辞書項目をスキップします。
- `/dict list` は、Discordの1メッセージの文字数上限を超える場合は複数のメッセージに分けて表示します。

Botの返信には辞書の単語などユーザーの入力が含まれますが、`@everyone`・`@here`・ロール・ユーザーへの
メンション通知は発生しません。

### 読み上げ設定

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

## 読み上げの制限

荒らしや長文で読み上げが詰まらないよう、次の制限があります。

- **レート制限**: サーバーごとに `MAX_TOKENS`（デフォルト400）個のトークンを持ち、1投稿で文字数分
  （最大80）を消費します。10秒ごとに50トークン回復します。足りない場合は回復までの目安を返信し、その投稿は読みません。
- **読み上げ待ち**: サーバーごとに最大50件です。超えた投稿はスキップし、その旨を返信します。
- **文字数**: 投稿は先頭512文字だけを変換し、変換後に80文字を超えた部分は「いかりゃく」と読みます。
- 絵文字など読める文字を含まない投稿は読み上げません。

## 環境変数

| 変数 | デフォルト | 説明 |
| :- | :- | :- |
| `DISCORD_BOT_TOKEN` | なし（必須） | Discord Bot token |
| `BOT_ID` | `0` | 同じDBを複数のBotで共有するとき、辞書と設定を分けるためのID |
| `YOMIAGE_DB` | `yomiage.sqlite3` | SQLite DBのパス |
| `MAX_TOKENS` | `400` | サーバーごとの読み上げトークン上限（1〜100000）。[読み上げの制限](#読み上げの制限)を参照 |
| `VOICEVOX_SPEAKER_ID` | `3` | デフォルトの話者ID。読み込んだモデルにないIDだと起動しません |
| `VOICEVOX_SPEED` | `1.2` | 話速（0より大きく10以下） |
| `VOICEVOX_ONNXRUNTIME_PATH` | `./voicevox_core/onnxruntime/lib/libvoicevox_onnxruntime.so.1.17.3` | ONNX Runtimeのライブラリファイル（1.17〜1.29に対応） |
| `OPEN_JTALK_DIC_DIR` | `./voicevox_core/dict/open_jtalk_dic_utf_8-1.11` | OpenJTalk辞書ディレクトリ |
| `VOICEVOX_MODEL_PATH` | `./voicevox_core/models/vvms` | `.vvm` を含むディレクトリ。`.vvm` ファイルを指定した場合は、同じディレクトリの `.vvm` もまとめて対象にします |
| `VOICEVOX_MODEL_EXCLUDE` | 空 | 読み込まない `.vvm`。例: `4.vvm`、複数なら `4.vvm,9.vvm` |
| `VOICEVOX_ACCELERATION_MODE` | `CPU` | `CPU`、`AUTO`、`GPU` のいずれか |
| `VOICEVOX_CPU_NUM_THREADS` | `4` | 合成に使うCPUスレッド数（0〜1024）。`0` にするとVOICEVOX COREが環境に合わせて決めます |
| `VOICEVOX_CACHE_SIZE` | `100` | 音声合成キャッシュ数（0〜100000、`0` で無効）。キャッシュはメモリ上にだけ保存します |
| `FFMPEG_PATH` | `ffmpeg` | ffmpegコマンド、または実行ファイルの絶対パス。systemdなどでPATHが通らない場合は絶対パスを指定します |

## 開発

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
- `test_bot_voice.py`: VC接続時のSelf Deaf設定、接続失敗時の返信、メンション通知の抑止、投稿テキストの整形、`/skip`
- `test_commands.py`: 返信に含めるユーザー入力のエスケープ、`/dict list` のメッセージ分割、`/voice` の埋め込みページ
- `test_voice_catalog.py`: 話者ID一覧とクレジット表記のデータ、埋め込みのフィールド数上限

### CI

`.github/workflows/ci.yml` で、push・PR時に `uv sync` → `ruff check` → `basedpyright` →
`pytest` → `uv build` を `ubuntu-latest` 上で実行しています。

## ライセンス

このプロジェクトはMIT Licenseで公開しています。詳細は [LICENSE](LICENSE) を参照してください。

このプロジェクトは [`tanetakumi/voicebot`](https://github.com/tanetakumi/voicebot) を参考にした
Python実装です。VOICEVOX CORE、VOICEVOXの音声モデル、その他依存ライブラリにはそれぞれ別の
ライセンスや利用条件があります。利用・配布時はそれらの条件も確認してください。

## Rust版との違い

元リポジトリはRustのDiscord bot、gRPC TTS server、Envoy、PostgreSQLで構成されています。
このPython版はまず動かしやすさを優先し、gRPC/Envoy/PostgreSQLを省いて単一プロセスにまとめています。
