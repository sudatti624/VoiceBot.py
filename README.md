# yomiage

VOICEVOX COREでDiscordのテキストチャンネル投稿をボイスチャンネルへ読み上げるPython botです。
[`tanetakumi/voicebot`](https://github.com/tanetakumi/voicebot) のRust実装を参考に、
単体で動かしやすい構成へ移植しています。

## 機能

- `/join`: 実行者がいるボイスチャンネルへ参加
- Botへのメンション: メンションした人がいるボイスチャンネルへ参加
- `/leave`: ボイスチャンネルから退出
- `/skip`: 再生中の読み上げを停止
- `/s`: `/skip` の短縮版
- `/dict add|remove|list`: サーバー辞書の管理
- `/settings show|mention|read_name|default_speaker|user_speaker|clear_user_speaker`: 読み上げ設定
- 参加時のテキストチャンネルに投稿されたメッセージをVOICEVOX COREで読み上げ
- 接続中のVCから人が全員退出したら自動退出
- Rust版と同じ考え方のトークンバケット式レート制限
- SQLiteによるローカル辞書保存
- URL、時刻、コード片、括弧などの簡易読み替え
- Discordメンション、ロール、チャンネル、DiscordチャンネルURLの読み替え
- 投稿者名の読み上げ
- ユーザーごとのVOICEVOX話者ID設定

## 必要なもの

- Python 3.12
- uv
- ffmpeg
- Discord Bot Token
- VOICEVOX CORE の実行ファイル一式

Discord Developer Portalでは、Botに次の権限とIntentを付けてください。

- `MESSAGE CONTENT INTENT`
- `View Channels`
- `Send Messages`
- `Read Message History`
- `Connect`
- `Speak`
- `Use Voice Activity`

VOICEVOX CORE はPyPIだけでは完結しません。このプロジェクトではPython wheelを依存に含めていますが、
実行時には別途VOICEVOX COREのONNX Runtime、OpenJTalk辞書、`.vvm` モデルが必要です。

## セットアップ

1. 依存関係をインストールします。

```bash
uv sync
```

2. 環境変数ファイルを作ります。

```bash
cp .env.example .env
```

3. `.env` を編集します。最低限、次の値を設定してください。

```env
DISCORD_BOT_TOKEN=あなたのDiscord Botトークン
VOICEVOX_ONNXRUNTIME_PATH=./voicevox_core/onnxruntime/lib/libvoicevox_onnxruntime.so.1.17.3
OPEN_JTALK_DIC_DIR=./voicevox_core/dict/open_jtalk_dic_utf_8-1.11
VOICEVOX_MODEL_PATH=./voicevox_core/models/0.vvm
```

4. Botを起動します。

```bash
uv run yomiage
```

起動後、DiscordでBotをメンションするか `/join` を実行すると、実行者が参加しているVCへ接続します。

## VOICEVOX CORE の配置例

`.env.example` のデフォルト値は、リポジトリ直下に `voicevox_core/` を置く想定です。

```text
voicevox_core/
├── onnxruntime/lib/libvoicevox_onnxruntime.so.1.17.3
├── dict/open_jtalk_dic_utf_8-1.11/
└── models/0.vvm
```

配置場所を変える場合は、`.env` の `VOICEVOX_ONNXRUNTIME_PATH`、
`OPEN_JTALK_DIC_DIR`、`VOICEVOX_MODEL_PATH` を変更してください。

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

## 読み上げ設定

- `/settings show`: 現在の設定を表示
- `/settings mention mode:名前/チャンネル名`: メンションやDiscordチャンネルURLを名前で読む
- `/settings mention mode:リンク省略`: メンションやDiscordチャンネルURLを `りんくしょうりゃく` と読む
- `/settings read_name enabled:true`: 読み上げ前に投稿者名を読む
- `/settings read_name enabled:false`: 投稿者名を読まない
- `/settings default_speaker speaker_id:<ID>`: サーバーのデフォルト話者IDを変更
- `/settings user_speaker user:<ユーザー> speaker_id:<ID>`: ユーザーごとの話者IDを設定
- `/settings clear_user_speaker user:<ユーザー>`: ユーザーごとの話者IDを解除

## 開発用コマンド

```bash
uv run ruff check .
uv run basedpyright src
uv build
```

`uv build` の成果物は `dist/` に出力されます。`dist/`、`.venv/`、`.env`、SQLite DB、
VOICEVOX CORE本体はGit管理対象外です。

## 環境変数

- `DISCORD_BOT_TOKEN`: Discord Bot token
- `BOT_ID`: 辞書を分けたい場合のbot ID。デフォルトは `0`
- `YOMIAGE_DB`: SQLite DBのパス。デフォルトは `yomiage.sqlite3`
- `MAX_TOKENS`: サーバーごとの読み上げトークン上限。デフォルトは `400`
- `VOICEVOX_SPEAKER_ID`: VOICEVOX話者ID。デフォルトは `3`
- `VOICEVOX_SPEED`: 話速。デフォルトは `1.2`
- `VOICEVOX_ONNXRUNTIME_PATH`: `libvoicevox_onnxruntime.so...` のパス
- `OPEN_JTALK_DIC_DIR`: OpenJTalk辞書ディレクトリ
- `VOICEVOX_MODEL_PATH`: `.vvm` モデルファイル
- `VOICEVOX_CACHE_SIZE`: 音声合成キャッシュ数。デフォルトは `100`
- `FFMPEG_PATH`: ffmpegコマンド。デフォルトは `ffmpeg`

## ライセンス

このプロジェクトはMIT Licenseで公開しています。詳細は [LICENSE](LICENSE) を参照してください。

このプロジェクトは [`tanetakumi/voicebot`](https://github.com/tanetakumi/voicebot) を参考にした
Python実装です。VOICEVOX CORE、VOICEVOXの音声モデル、その他依存ライブラリにはそれぞれ別の
ライセンスや利用条件があります。利用・配布時はそれらの条件も確認してください。

## Rust版との違い

元リポジトリはRustのDiscord bot、gRPC TTS server、Envoy、PostgreSQLで構成されています。
このPython版はまず動かしやすさを優先し、gRPC/Envoy/PostgreSQLを省いて単一プロセスにまとめています。
